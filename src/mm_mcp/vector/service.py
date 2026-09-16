"""Shared browser/MCP plant authoring. No native renderer or world publication."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from mm_mcp.core import ServiceError, canonical, digest, file_lock, identifier
from mm_mcp.transactions import GraphStore
from .provenance import verify

SCHEMA = 'workshop.vector-project/v1'
BUILD_SCHEMA = 'workshop.vector-build/v1'


class VectorService:
    def __init__(self, root):
        self.root = Path(root)
        self.producer = verify()
        from .documents import DocumentService
        self.documents = DocumentService(root, self.producer)
        from .producer import authoring
        from .producer.artifact import render
        self.compiler, self.render = authoring, render
        self.store = GraphStore(root, {}, kind='vector-plant',
                                validate=self._validate, patch=self._patch)
        self.build_root = self.root / 'vector-builds'

    def _validate(self, document):
        if not isinstance(document, dict) or set(document) != {'schema', 'artifact', 'locked'} or document['schema'] != SCHEMA:
            raise ServiceError('VECTOR_DOCUMENT', 'Use an installed plant document.')
        self.compiler.request_from_artifact(document['artifact'])
        self.compiler.validate_locks(document['locked'])
        return []

    def _patch(self, document, operations):
        self._validate(document)
        if not isinstance(operations, list) or not 1 <= len(operations) <= 16:
            raise ServiceError('VECTOR_PATCH', 'Provide 1–16 plant operations.')
        out, changes = deepcopy(document), []
        for op in operations:
            if not isinstance(op, dict):
                raise ServiceError('VECTOR_PATCH', 'A plant operation must be an object.')
            kind = op.get('op')
            if kind == 'set_locks' and set(op) == {'op', 'locked'} and len(operations) == 1:
                out['locked'] = self.compiler.validate_locks(op['locked'])
            elif kind == 'set_controls' and set(op) == {'op', 'values'}:
                out['artifact'] = self.compiler.revise(out['artifact'], op['values'], document['locked'])
            elif kind == 'adopt' and set(op) == {'op', 'artifact'}:
                self.compiler.assert_preserved(document['artifact'], op['artifact'], document['locked'])
                out['artifact'] = deepcopy(op['artifact'])
            else:
                raise ServiceError('VECTOR_PATCH', 'Use set_controls, adopt, or a separate set_locks transaction.')
            changes.append({'op': kind})
        self._validate(out)
        return out, changes

    def _project(self, row):
        document = row['graph']
        self._validate(document)
        return {'ok': True, 'schema': SCHEMA, 'project_id': row['project_id'],
                'title': row['title'], 'revision': row['revision'],
                'artifact': document['artifact'], 'locked': document['locked'],
                'values': self.compiler.control_values(document['artifact']),
                'controls': self.compiler.controls(), 'producer': self.producer}

    def read(self, project_id, expected_revision=None):
        row = self.store.read(project_id)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != row['revision']):
            raise ServiceError('REVISION_CONFLICT', 'Plant changed; reload it before retrying.', actual_revision=row['revision'])
        return self._project(row)

    def _current(self, request):
        if type(request.get('expected_revision')) is not int:
            raise ServiceError('REVISION_REQUIRED', 'An exact plant revision is required.')
        return self.read(request['project_id'], request['expected_revision'])

    def command(self, request):
        if isinstance(request, dict) and request.get('profile') == 'vector-document-v1':
            return self.documents.command(request)
        self.compiler.encode(request, self.compiler.MAX_REQUEST_BYTES)
        if not isinstance(request, dict):
            raise ServiceError('VECTOR_REQUEST', 'Use a plant command object.')
        operation = request.get('operation')
        shared = {'project_id', 'expected_revision'}
        fields = {
            'describe': set(), 'list': set(), 'create': {'title', 'request'}, 'get': {'project_id'},
            'patch': shared | {'operations', 'idempotency_key'},
            'history': shared | {'direction'}, 'snapshot': shared | {'name'},
            'snapshots': {'project_id'}, 'restore': shared | {'name'},
            'variants': shared | {'count', 'seed', 'ranges'}, 'sweep': shared | {'control', 'values'},
            'preview': shared | {'clip', 'time', 'frame_count'}, 'build': shared,
            'build_get': {'build_id'}, 'export': {'build_id'},
        }.get(operation)
        if fields is None or set(request) - (fields | {'operation'}):
            raise ServiceError('VECTOR_REQUEST', 'Unknown plant command or fields.')
        if operation == 'describe':
            return {'ok': True, **self.compiler.describe(), 'producer': self.producer,
                    'project_schema': SCHEMA, 'operations': list(self.operations())}
        if operation == 'list':
            return {'ok': True, 'projects': self.store.list()}
        if operation == 'create':
            result = self.compiler.execute({'operation': 'create', 'request': request.get('request', {})})
            row = self.store.create({'schema': SCHEMA, 'artifact': result['assets'][0], 'locked': []},
                                    request.get('title', 'Vector plant'))
            return {**self._project(row), 'preview_svg': result['preview_svg']}
        if operation == 'get':
            return self.read(request['project_id'])
        if operation == 'patch':
            receipt = self.store.patch(request['project_id'], request['expected_revision'],
                                       request['operations'], request['idempotency_key'])
            # Return the exact receipt on retry; a separate get returns current state.
            return {k: v for k, v in receipt.items() if k != 'graph_hash'}
        if operation == 'history':
            return self._project(self.store.history_step(request['project_id'], request['expected_revision'], request['direction']))
        if operation == 'snapshot':
            self._current(request)
            return self.store.snapshot(request['project_id'], request['name'], request['expected_revision'])
        if operation == 'snapshots':
            return {'ok': True, 'snapshots': self.store.snapshots(request['project_id'])}
        if operation == 'restore':
            return self._project(self.store.restore(request['project_id'], request['name'], request['expected_revision']))
        if operation in ('build_get', 'export'):
            manifest = self.get_build(request['build_id'])
            if operation == 'build_get':
                return {'ok': True, 'manifest': manifest}
            import base64
            data = self.export(request['build_id'])
            return {'ok': True, 'build_id': request['build_id'], 'mime': 'application/zip',
                    'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                    'data_base64': base64.b64encode(data).decode('ascii')}
        project = self._current(request)
        if operation == 'build':
            return self.build(project)
        pure = {k: v for k, v in request.items() if k not in shared}
        pure['source'] = project['artifact']
        if operation in ('variants', 'sweep'):
            pure['locked'] = project['locked']
        result = self.compiler.execute(pure)
        return {'ok': True, **result, 'project_id': project['project_id'],
                'revision': project['revision'], 'locked': project['locked']}

    @staticmethod
    def operations():
        return ('describe', 'list', 'create', 'get', 'patch', 'history', 'snapshot', 'snapshots',
                'restore', 'variants', 'sweep', 'preview', 'build', 'build_get', 'export')

    def build(self, project):
        source = {k: project[k] for k in ('schema', 'project_id', 'title', 'revision', 'artifact', 'locked', 'producer')}
        build_id = 'v_' + digest(source)
        self.build_root.mkdir(parents=True, exist_ok=True)
        destination = self.build_root / build_id
        with file_lock(self.build_root / '.build.lock'):
            if not destination.exists():
                preview = self.compiler.execute({'operation': 'preview', 'source': project['artifact'], 'clip': 'rest', 'frame_count': 1})
                files = {'project.json': canonical(source).encode(),
                         'plant.artifact.json': self.render(self.compiler.generate(self.compiler.request_from_artifact(project['artifact']))).encode(),
                         'plant.request.json': self.render(self.compiler.request_from_artifact(project['artifact'])).encode(),
                         'preview.svg': preview['preview_svg'].encode()}
                manifest = {'schema': BUILD_SCHEMA, 'status': 'complete', 'build_id': build_id,
                            'project_id': project['project_id'], 'revision': project['revision'],
                            'content_sha256': project['artifact']['integrity']['content_sha256'],
                            'producer': self.producer,
                            'files': [{'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                                      for name, raw in sorted(files.items())]}
                with tempfile.TemporaryDirectory(prefix='.vector-', dir=self.build_root) as temp:
                    stage = Path(temp) / 'build'; stage.mkdir()
                    for name, raw in files.items():
                        (stage / name).write_bytes(raw)
                    (stage / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
                    os.replace(stage, destination)
            return {'ok': True, 'manifest': self.get_build(build_id)}

    def get_build(self, build_id):
        import re
        if not isinstance(build_id, str) or not re.fullmatch(r'v_[a-f0-9]{64}', build_id):
            raise ServiceError('VECTOR_BUILD', 'Invalid plant build ID.')
        root = self.build_root / identifier(build_id)
        if not root.is_dir():
            raise ServiceError('BUILD_NOT_FOUND', 'Plant build not found.')
        names = {'project.json', 'plant.artifact.json', 'plant.request.json', 'preview.svg', 'manifest.json'}
        if root.is_symlink() or {p.name for p in root.iterdir()} != names or any((root / n).is_symlink() for n in names):
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant inventory differs from its fixed contract.')
        if any(not (root / n).is_file() or (root / n).stat().st_size > 512 * 1024 for n in names):
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant artifact exceeds its bound.')
        manifest = json.loads((root / 'manifest.json').read_bytes())
        records = manifest.get('files', [])
        if (manifest.get('schema') != BUILD_SCHEMA or manifest.get('status') != 'complete'
                or manifest.get('build_id') != build_id or len(records) != 4
                or {r['name'] for r in records} != names - {'manifest.json'}):
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant manifest identity differs from its build.')
        for record in records:
            data = (root / record['name']).read_bytes()
            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ServiceError('ARTIFACT_CORRUPT', 'Plant artifact checksum differs from its build.')
        source = json.loads((root / 'project.json').read_bytes())
        artifact = json.loads((root / 'plant.artifact.json').read_bytes())
        if ('v_' + digest(source) != build_id or source['artifact'] != artifact
                or source['producer'] != manifest.get('producer')
                or source['revision'] != manifest.get('revision')
                or source['project_id'] != manifest.get('project_id')
                or artifact['integrity']['content_sha256'] != manifest.get('content_sha256')
                or self.compiler.request_from_artifact(artifact) != json.loads((root / 'plant.request.json').read_bytes())):
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant source differs from its build identity.')
        request = self.compiler.request_from_artifact(artifact)
        if (root / 'plant.artifact.json').read_bytes() != self.render(self.compiler.generate(request)).encode():
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant bytes are not the reproducible native producer output.')
        preview = self.compiler.execute({'operation':'preview', 'source':artifact, 'clip':'rest', 'frame_count':1})
        if (root / 'preview.svg').read_bytes() != preview['preview_svg'].encode():
            raise ServiceError('ARTIFACT_CORRUPT', 'Plant preview differs from its source.')
        return manifest

    def export(self, build_id):
        manifest = self.get_build(build_id)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in sorted([r['name'] for r in manifest['files']] + ['manifest.json']):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, (self.build_root / build_id / name).read_bytes())
        return data.getvalue()
