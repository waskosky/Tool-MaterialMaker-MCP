"""Immutable Blender inputs/results behind Workshop's existing private queue."""
from __future__ import annotations
import base64
import binascii
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from mm_mcp.artifacts import verify_images
from mm_mcp.core import ServiceError, atomic_json, canonical, digest, file_digest, file_lock, finite, identifier, parse_json
from mm_mcp.blender.mesh import MAX_MESH_BYTES, MAX_TRIANGLES, MAX_VERTICES, validate_glb

OPERATIONS = ('inspect', 'preview', 'bake')
SPECIMENS = ('sphere', 'beveled_cube', 'plane')
RESOLUTIONS = (128, 256, 512)
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 28 * 1024 * 1024
MAX_FILES = 64
MAP_ROLES = ('base_color', 'normal', 'ao', 'roughness', 'metallic', 'height', 'emission')
PUBLIC_FIELDS = {'operation', 'build_id', 'mesh_id', 'specimen', 'resolution', 'unwrap', 'uv_scale'}


def _id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r'[0-9a-f]{64}', value):
        raise ServiceError('BLENDER_ID', f'Invalid {prefix} content identifier.')
    return value


def _cancel(cancel):
    if cancel and cancel():
        raise ServiceError('CANCELLED', 'Blender operation cancelled before publication.')


def _bytes(path, maximum=MAX_FILE_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ServiceError('BLENDER_ARTIFACT_CORRUPT', f'Missing, linked or oversized artifact: {path.name}')
    return path.read_bytes()


class BlenderService:
    def __init__(self, app, *, runner=None):
        self.app, self.runner = app, runner
        self.root = app.root / 'blender'
        self.meshes, self.results = self.root / 'meshes', self.root / 'results'
        self.meshes.mkdir(parents=True, exist_ok=True)
        self.results.mkdir(parents=True, exist_ok=True)

    def capabilities(self):
        binary = self.app.cfg.blender_binary
        configured = bool(binary and Path(binary).is_file() and os.access(binary, os.X_OK))
        return {'ok': True, 'configured': configured, 'operations': list(OPERATIONS), 'specimens': list(SPECIMENS),
                'renderer_kind': 'injected_test_double' if self.runner else 'native_blender',
                'configuration_error': None if configured else 'Set MM_BLENDER_BINARY to an executable Blender binary to enable the optional companion.',
                'limits': {'mesh_bytes': MAX_MESH_BYTES, 'vertices': MAX_VERTICES, 'triangles': MAX_TRIANGLES, 'resolutions': list(RESOLUTIONS),
                           'source_resolution': 1024, 'uv_scale_min': .125, 'uv_scale_max': 16, 'files': MAX_FILES, 'file_bytes': MAX_FILE_BYTES, 'result_bytes': MAX_RESULT_BYTES, 'timeout_seconds': 600},
                'normal_convention': 'OpenGL (+Y)', 'orm_channels': {'r': 'ao', 'g': 'roughness', 'b': 'metallic'},
                'notes': 'Static embedded GLB, meters, original UVs by default. Explicit unwrap creates a derivative. Blender previews are supplementary evidence; validate materials in Godot.'}

    def _enabled(self):
        status = self.capabilities()
        if not status['configured']:
            raise ServiceError('BLENDER_DISABLED', status['configuration_error'])

    def _tools(self):
        self._enabled()
        binary = Path(self.app.cfg.blender_binary).resolve()
        worker_files = sorted(Path(__file__).parent.glob('*.py'))
        return {'worker_schema': 1, 'worker_sha256': digest([(p.name, file_digest(p)) for p in worker_files]),
                'blender_binary': str(binary), 'blender_binary_sha256': file_digest(binary),
                'renderer_kind': 'injected_test_double' if self.runner else 'native_blender', 'engine': 'CYCLES', 'device': 'CPU'}

    def upload(self, *, name, data_base64):
        self._enabled()
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or any(ord(c) < 32 for c in name) or '/' in name or '\\' in name:
            raise ServiceError('BLENDER_MESH_NAME', 'Use a short display filename without path separators.')
        if not isinstance(data_base64, str) or len(data_base64) > 4 * ((MAX_MESH_BYTES + 2) // 3):
            raise ServiceError('BLENDER_MESH_LIMIT', 'GLB upload exceeds 4 MiB.')
        try:
            raw = base64.b64decode(data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ServiceError('BLENDER_MESH_INVALID', 'Mesh data must be standard base64.') from exc
        metadata = {**validate_glb(raw), 'name': name}
        path = self.meshes / (metadata['mesh_id'] + '.glb')
        with file_lock(self.meshes / '.upload.lock'):
            if path.exists() or path.is_symlink():
                if _bytes(path, MAX_MESH_BYTES) != raw:
                    raise ServiceError('BLENDER_MESH_CORRUPT', 'Stored mesh bytes differ from their content identifier.')
            else:
                fd, temp = tempfile.mkstemp(prefix='.upload-', dir=self.meshes)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(raw)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temp, path)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
        return {'ok': True, 'mesh': metadata}

    def mesh_path(self, mesh_id):
        path = self.meshes / (_id(mesh_id, 'mesh_') + '.glb')
        raw = _bytes(path, MAX_MESH_BYTES)
        if 'mesh_' + hashlib.sha256(raw).hexdigest() != mesh_id:
            raise ServiceError('BLENDER_MESH_CORRUPT', 'Uploaded mesh changed after admission.')
        validate_glb(raw)
        return path

    def _source(self, build_id):
        manifest = self.app.builds.get(build_id)
        directory = self.app.builds.directory(build_id)
        raw = _bytes(directory / 'request.json')
        request = parse_json(raw)
        if hashlib.sha256(raw).hexdigest() != manifest['input_hash']:
            raise ServiceError('BLENDER_SOURCE_CORRUPT', 'Source build request does not match its input hash.')
        if request.get('dependencies'):
            raise ServiceError('BLENDER_SOURCE_DEPENDENCIES', 'Blender portable bundles require a self-contained Workshop source; arbitrary Material Maker external dependencies remain unsupported.')
        if manifest['resolution'] > 1024:
            raise ServiceError('BLENDER_SOURCE_LIMIT', 'Use an exact Workshop build at 1024 pixels or below for the bounded portable bundle.')
        files = []
        maps = {}
        for entry in manifest['files']:
            name = 'material.ptex' if entry['name'] == 'material.ptex' else 'source_' + entry['name']
            identifier(name)
            files.append({'source_name': entry['name'], 'name': name, 'bytes': entry['bytes'], 'sha256': entry['sha256']})
            role = 'base_color' if entry.get('channel') == 'albedo' else entry.get('channel')
            if role in MAP_ROLES and entry['name'].endswith('.png'):
                maps[role] = name
        if not {'base_color', 'normal', 'roughness', 'metallic', 'ao'} <= set(maps):
            raise ServiceError('BLENDER_SOURCE_MAPS', 'Completed Workshop build lacks its portable PBR maps.')
        return {'input_hash': manifest['input_hash'], 'manifest_sha256': file_digest(directory / 'manifest.json'),
                'renderer_kind': manifest['renderer_kind'], 'physical_size_m': request['physical_size_m'], 'files': files, 'maps': maps}

    def prepare(self, body):
        self._enabled()
        if not isinstance(body, dict) or set(body) - PUBLIC_FIELDS:
            raise ServiceError('BLENDER_REQUEST', 'Use only the fixed Blender operation fields.')
        operation = body.get('operation')
        if operation not in OPERATIONS:
            raise ServiceError('BLENDER_OPERATION', 'Choose inspect, preview or bake.')
        size = body.get('resolution', 256)
        if type(size) is not int or size not in RESOLUTIONS:
            raise ServiceError('BLENDER_RESOLUTION', 'Blender resolution must be 128, 256 or 512.')
        unwrap, scale = body.get('unwrap', False), body.get('uv_scale', 1)
        if type(unwrap) is not bool or not finite(scale) or not .125 <= scale <= 16:
            raise ServiceError('BLENDER_UV', 'unwrap must be boolean; uv_scale must be finite from 0.125 through 16.')
        mesh_id = body.get('mesh_id')
        specimen = body.get('specimen')
        if mesh_id is not None and specimen is not None:
            raise ServiceError('BLENDER_GEOMETRY', 'Choose exactly one uploaded mesh or specimen.')
        if mesh_id is not None:
            self.mesh_path(mesh_id)
        else:
            specimen = specimen or 'sphere'
            if specimen not in SPECIMENS:
                raise ServiceError('BLENDER_SPECIMEN', 'Choose sphere, beveled_cube or plane.')
        build_id = body.get('build_id')
        if operation in ('preview', 'bake') and not build_id:
            raise ServiceError('BLENDER_BUILD_REQUIRED', 'Preview and bake require an exact completed Workshop build_id.')
        source = self._source(build_id) if build_id is not None else None
        return {'schema': 'mm.blender-request/v1', 'operation': operation, 'build_id': build_id, 'mesh_id': mesh_id, 'specimen': specimen,
                'resolution': size, 'unwrap': unwrap, 'uv_scale': scale, 'source': source, 'tools': self._tools()}

    def submit(self, body):
        return self.app.jobs.submit({'kind': 'blender', 'request': self.prepare(body)})

    def execute(self, request, cancel=None):
        # Even persisted/internal requests must regenerate an identical permitted
        # input contract; no arbitrary runner paths can cross this boundary.
        if not isinstance(request, dict):
            raise ServiceError('BLENDER_REQUEST', 'Invalid persisted Blender request.')
        prepared = self.prepare({key: value for key, value in request.items() if key in PUBLIC_FIELDS and value is not None})
        if canonical(prepared) != canonical(request):
            raise ServiceError('BLENDER_INPUT_CHANGED', 'Blender source, worker or binary changed after job admission; resubmit explicitly.')
        key = digest(request)
        result_id = 'bl_' + key
        with file_lock(self.app.root / '.native.lock', timeout=660, cancel=cancel):
            _cancel(cancel)
            target = self.results / result_id
            if target.exists():
                return {'ok': True, 'result_id': result_id, 'cached': True, 'manifest': self.get(result_id)}
            stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.results))
            try:
                atomic_json(stage / 'request.json', request)
                if request['mesh_id']:
                    (stage / 'source_mesh.glb').write_bytes(_bytes(self.mesh_path(request['mesh_id']), MAX_MESH_BYTES))
                source = request['source']
                if source:
                    directory = self.app.builds.directory(request['build_id'])
                    (stage / 'source_manifest.json').write_bytes(_bytes(directory / 'manifest.json'))
                    for item in source['files']:
                        raw = _bytes(directory / item['source_name'])
                        if hashlib.sha256(raw).hexdigest() != item['sha256'] or len(raw) != item['bytes']:
                            raise ServiceError('BLENDER_INPUT_CHANGED', 'Source build changed before Blender launch.')
                        (stage / item['name']).write_bytes(raw)
                if self.runner:
                    runner = self.runner
                else:
                    from mm_mcp.blender.runner import run_worker
                    runner = run_worker
                runner(stage / 'request.json', stage, binary=self.app.cfg.blender_binary, cancel=cancel)
                _cancel(cancel)
                if self._tools() != request['tools'] or (source and self._source(request['build_id']) != source):
                    raise ServiceError('BLENDER_INPUT_CHANGED', 'Source build or Blender worker changed while running.')
                report = parse_json(_bytes(stage / 'worker_result.json'))
                if not isinstance(report, dict) or not isinstance(report.get('diagnostics'), dict) or not isinstance(report.get('blender_version'), str):
                    raise ServiceError('BLENDER_RESULT_INVALID', 'Worker did not produce versioned diagnostics.')
                atomic_json(stage / 'diagnostics.json', report['diagnostics'])
                atomic_json(stage / 'provenance.json', {'build_id': request['build_id'], 'source': source, 'mesh_id': request['mesh_id'], 'specimen': request['specimen'],
                                                      'tools': request['tools'], 'unwrap_derivative': request['unwrap'], 'uv_scale': request['uv_scale'],
                                                      'notes': 'Original procedural source and source mesh bytes are preserved. Mesh-specific baked maps are a separate derivative, not shader-language translation.'})
                files = []
                total = 0
                for path in sorted(stage.iterdir()):
                    identifier(path.name)
                    raw = _bytes(path)
                    total += len(raw)
                    if total > MAX_RESULT_BYTES or len(files) >= MAX_FILES:
                        raise ServiceError('BLENDER_RESULT_LIMIT', 'Portable result exceeds its 28 MiB / 64 file budget.')
                    if path.suffix == '.png':
                        verify_images([path], root=stage)
                        from PIL import Image
                        with Image.open(path) as im:
                            maximum = 1024 if path.name.startswith('source_') else request['resolution']
                            if im.width > maximum or im.height > maximum:
                                raise ServiceError('BLENDER_RESULT_INVALID', 'Worker image exceeds its requested dimensions.')
                    files.append({'name': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                manifest = {'schema': 'mm.blender-result/v1', 'status': 'complete', 'result_id': result_id, 'input_hash': key,
                            **{k: request[k] for k in ('operation', 'build_id', 'mesh_id', 'specimen', 'resolution', 'unwrap', 'uv_scale')},
                            'renderer_kind': request['tools']['renderer_kind'], 'blender_version': report['blender_version'], 'tools': request['tools'],
                            'physical_size_m': source['physical_size_m'] if source else 1, 'normal_convention': 'OpenGL (+Y)',
                            'diagnostics': report['diagnostics'], 'maps': report.get('maps', {}), 'masks': report.get('masks', {}), 'files': files,
                            'preview': 'preview.png' if request['operation'] != 'inspect' else None,
                            'notes': 'Mesh-specific UV bake. Source physical_size_m records the procedural tile scale; uv_scale applies to source sampling. Preview is supplementary evidence, not a Godot runtime capture.'}
                atomic_json(stage / 'manifest.json', manifest)
                self._verify(stage, result_id)
                _cancel(cancel)
                os.replace(stage, target)
                return {'ok': True, 'result_id': result_id, 'cached': False, 'manifest': manifest}
            finally:
                shutil.rmtree(stage, ignore_errors=True)

    def directory(self, result_id):
        path = self.results / _id(result_id, 'bl_')
        if path.is_symlink() or not path.is_dir():
            raise ServiceError('BLENDER_RESULT_NOT_FOUND', 'Blender result not found.')
        return path

    def _verify(self, directory, result_id):
        manifest = parse_json(_bytes(directory / 'manifest.json'))
        if not isinstance(manifest, dict) or manifest.get('schema') != 'mm.blender-result/v1' or manifest.get('status') != 'complete' or manifest.get('result_id') != result_id:
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid Blender result manifest.')
        files = manifest.get('files')
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid Blender artifact inventory.')
        seen, total = set(), 0
        for item in files:
            if not isinstance(item, dict):
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid artifact entry.')
            name = identifier(item.get('name'))
            if name in seen or name == 'manifest.json':
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Duplicate or reserved artifact entry.')
            raw = _bytes(directory / name)
            if type(item.get('bytes')) is not int or len(raw) != item['bytes'] or hashlib.sha256(raw).hexdigest() != item.get('sha256'):
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender artifact failed SHA-256 verification: ' + name)
            total += len(raw)
            seen.add(name)
        if total > MAX_RESULT_BYTES or not {'request.json', 'diagnostics.json', 'provenance.json', 'worker_result.json'} <= seen:
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Incomplete or oversized Blender result.')
        if {p.name for p in directory.iterdir()} != seen | {'manifest.json'}:
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Result directory differs from its exact file inventory.')
        raw_request = _bytes(directory / 'request.json')
        key = hashlib.sha256(raw_request).hexdigest()
        request = parse_json(raw_request)
        if result_id != 'bl_' + key or manifest.get('input_hash') != key or raw_request != canonical(request).encode():
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender request identity mismatch.')
        for field in ('operation', 'build_id', 'mesh_id', 'specimen', 'resolution', 'unwrap', 'uv_scale', 'tools'):
            if manifest.get(field) != request.get(field):
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender receipt does not match its request.')
        if manifest.get('renderer_kind') != request.get('tools', {}).get('renderer_kind'):
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender renderer provenance mismatch.')
        if manifest.get('diagnostics') != parse_json(_bytes(directory / 'diagnostics.json')):
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender diagnostics mismatch.')
        report = parse_json(_bytes(directory / 'worker_result.json'))
        expected_scale = request['source']['physical_size_m'] if request.get('source') else 1
        expected_preview = 'preview.png' if request['operation'] != 'inspect' else None
        if (manifest.get('physical_size_m') != expected_scale or manifest.get('normal_convention') != 'OpenGL (+Y)'
                or manifest.get('preview') != expected_preview):
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender physical/map conventions differ from its request.')
        if any(manifest.get(key) != report.get(key, {}) for key in ('blender_version', 'diagnostics', 'maps', 'masks')):
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Blender manifest differs from the inventoried worker report.')
        if request.get('source'):
            source = request['source']
            if file_digest(directory / 'source_manifest.json') != source['manifest_sha256']:
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Original build manifest changed.')
            for item in source['files']:
                if item['name'] not in seen or file_digest(directory / item['name']) != item['sha256']:
                    raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Original build artifact changed.')
        maps = manifest.get('maps')
        if not isinstance(maps, dict) or set(maps) - set(MAP_ROLES):
            raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid portable map roles.')
        for role, entry in maps.items():
            expected = {'file': role + '.png', 'channels': 'rgb' if role in ('base_color', 'normal', 'emission') else 'r', 'color_space': 'srgb' if role in ('base_color', 'emission') else 'linear'}
            if entry != expected or entry['file'] not in seen:
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid portable map contract.')
            verify_images([directory / entry['file']], request['resolution'], root=directory)
        if manifest['operation'] == 'bake':
            if set(maps) != set(MAP_ROLES) or not {'material.blend', 'material.glb', 'material.ptex'} <= seen:
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Bake is missing its portable PBR maps or packed asset.')
            validate_glb(_bytes(directory / 'material.glb'), max_bytes=MAX_FILE_BYTES)
        if manifest['operation'] != 'inspect':
            if not {'preview.png', 'material.blend'} <= seen:
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Missing preview image or packed editable scene.')
            verify_images([directory / 'preview.png'], request['resolution'], root=directory)
            if not _bytes(directory / 'material.blend').startswith(b'BLENDER'):
                raise ServiceError('BLENDER_ARTIFACT_CORRUPT', 'Invalid packed Blender asset.')
        return manifest

    def get(self, result_id):
        return self._verify(self.directory(result_id), result_id)

    def artifact(self, result_id, name):
        identifier(name, 'Blender artifact filename')
        manifest = self.get(result_id)
        if name != 'manifest.json' and name not in {entry['name'] for entry in manifest['files']}:
            raise ServiceError('BLENDER_ARTIFACT_NOT_FOUND', 'File is not part of this immutable result.')
        return self.directory(result_id) / name

    def export(self, result_id):
        manifest = self.get(result_id)
        directory = self.directory(result_id)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in sorted([entry['name'] for entry in manifest['files']] + ['manifest.json']):
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                archive.writestr(entry, _bytes(directory / name))
        return output.getvalue()
