"""Revisioned general vector art, sharing Workshop's transactional project store."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from mm_mcp.core import ServiceError, canonical, digest, file_lock
from mm_mcp.transactions import GraphStore
from .producer import document as compiler
from .producer import document_v2 as advanced

SCHEMA = 'workshop.vector-document-project/v1'
BUILD_SCHEMA = 'workshop.vector-document-build/v1'


class DocumentStore(GraphStore):
    def __init__(self, *args, schemas, **kwargs):
        self.schemas = schemas
        super().__init__(*args, **kwargs)

    def _row(self, db, pid):
        row = super()._row(db, pid)
        if json.loads(row['graph']).get('schema') not in self.schemas:
            raise ServiceError('VECTOR_VERSION', 'Use the matching artwork profile; v2 features require an explicit upgrade.')
        return row

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,title,revision,created,json_extract(graph,'$.schema') AS document_schema "
                "FROM projects WHERE kind=? AND json_extract(graph,'$.schema') IN (" + ','.join('?' for _ in self.schemas) + ') ORDER BY created DESC',
                (self.kind, *self.schemas))]


class DocumentService:
    def __init__(self, root, producer, profile=compiler.PROFILE):
        self.producer = producer
        self.profile = profile
        self.compiler = advanced if profile == advanced.PROFILE else compiler
        self.build_root = Path(root) / 'vector-document-builds'
        self.store = DocumentStore(root, {}, kind='vector-document', schemas=(compiler.SCHEMA, advanced.SCHEMA) if profile == advanced.PROFILE else (compiler.SCHEMA,), validate=self.validate, patch=self.patch)

    def renderer(self, document):
        if document.get('schema') == advanced.SCHEMA and self.profile == advanced.PROFILE:
            return advanced
        return compiler

    def validate(self, document):
        self.renderer(document).validate(document)
        return []

    def patch(self, document, operations):
        if self.profile == advanced.PROFILE and operations == [{'op': 'upgrade'}]:
            return advanced.upgrade(document), [{'op': 'upgrade'}]
        if self.profile == advanced.PROFILE and document.get('schema') != advanced.SCHEMA:
            raise ServiceError('VECTOR_UPGRADE', 'Upgrade this artwork before using v2 edits.')
        return self.renderer(document).revise(document, operations), [{'op': op['op']} for op in operations]

    def project(self, row):
        renderer = self.renderer(row['graph'])
        renderer.validate(row['graph'])
        return {'ok': True, 'schema': SCHEMA, 'profile': renderer.PROFILE,
                'project_id': row['project_id'], 'title': row['title'], 'revision': row['revision'],
                'document': row['graph'], 'preview_svg': renderer.render(row['graph']),
                'content_sha256': compiler.structural_digest(row['graph']), 'producer': self.producer}

    def current(self, request):
        row = self.store.read(request['project_id'])
        if type(request.get('expected_revision')) is not int or request['expected_revision'] != row['revision']:
            raise ServiceError('REVISION_CONFLICT', 'Artwork changed; reload before retrying.', actual_revision=row['revision'])
        return self.project(row)

    def command(self, request):
        compiler.encode(request)
        shared = {'project_id', 'expected_revision'}
        contracts = {
            'describe': (set(), set()), 'list': (set(), set()),
            'create': (set(), {'title', 'document', 'template'}), 'get': ({'project_id'}, set()),
            'patch': (shared | {'operations', 'idempotency_key'}, set()),
            'history': (shared | {'direction'}, set()), 'snapshot': (shared | {'name'}, set()),
            'snapshots': ({'project_id'}, set()), 'restore': (shared | {'name'}, set()),
            'variants': (shared | {'palettes'}, set()), 'preview': (shared, set()), 'build': (shared, set()),
            'build_get': ({'build_id'}, set()), 'export': ({'build_id'}, set()),
        }
        if not isinstance(request, dict) or request.get('profile') != self.profile or request.get('operation') not in contracts:
            raise ServiceError('VECTOR_REQUEST', 'Use a supported vector document operation.')
        op = request['operation']
        required, optional = contracts[op]
        compiler.fields(request, required | {'profile', 'operation'}, optional)
        if op == 'describe':
            return {'ok': True, **self.compiler.describe(), 'producer': self.producer, 'project_schema': SCHEMA,
                    'operations': list(contracts), 'revision_policy': 'Read, patch exact revision with unique idempotency_key, then get. History restores complete state including locks.'}
        if op == 'list':
            return {'ok': True, 'projects': self.store.list()}
        if op == 'create':
            title = request.get('title', 'Untitled artwork')
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80 or any(ord(c) < 32 for c in title):
                raise ServiceError('VECTOR_TITLE', 'Use a name of 1–80 readable characters.')
            pure = {k: v for k, v in request.items() if k != 'title'}
            document = self.compiler.execute(pure)['documents'][0]
            return self.project(self.store.create(document, title.strip()))
        if op == 'get':
            return self.project(self.store.read(request['project_id']))
        if op == 'patch':
            # GraphStore returns the original receipt on a retry, including after later edits.
            return self.store.patch(request['project_id'], request['expected_revision'], request['operations'], request['idempotency_key'])
        if op == 'history':
            return self.project(self.store.history_step(request['project_id'], request['expected_revision'], request['direction']))
        if op == 'snapshots':
            return {'ok': True, 'snapshots': self.store.snapshots(request['project_id'])}
        if op == 'restore':
            return self.project(self.store.restore(request['project_id'], request['name'], request['expected_revision']))
        if op in ('build_get', 'export'):
            manifest, source, svg = self.get_build(request['build_id'])
            if op == 'build_get':
                return {'ok': True, 'manifest': manifest, 'document': source['document'], 'preview_svg': svg}
            data = self.export(request['build_id'])
            return {'ok': True, 'build_id': manifest['build_id'], 'mime': 'application/zip',
                    'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'data_base64': base64.b64encode(data).decode('ascii')}
        project = self.current(request)
        if op == 'snapshot':
            return self.store.snapshot(request['project_id'], request['name'], request['expected_revision'])
        if op == 'build':
            return self.build(project)
        result = self.renderer(project['document']).execute({'profile': project['profile'], 'operation': op, 'source': project['document'],
                                   **({'palettes': request['palettes']} if op == 'variants' else {})})
        return {'ok': True, **result, 'project_id': project['project_id'], 'revision': project['revision']}

    def build(self, project):
        source = {key: project[key] for key in ('schema', 'project_id', 'title', 'revision', 'document', 'producer')}
        build_id = 'd_' + digest(source)
        self.build_root.mkdir(parents=True, exist_ok=True)
        target = self.build_root / build_id
        with file_lock(self.build_root / '.build.lock'):
            if not target.exists():
                files = {'project.json': canonical(source).encode(), 'document.json': canonical(source['document']).encode(),
                         'preview.svg': self.renderer(source['document']).render(source['document']).encode()}
                manifest = {'schema': BUILD_SCHEMA, 'status': 'complete', 'build_id': build_id,
                            'project_id': project['project_id'], 'revision': project['revision'],
                            'content_sha256': project['content_sha256'], 'producer': self.producer,
                            'files': [{'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in sorted(files.items())]}
                with tempfile.TemporaryDirectory(prefix='.document-', dir=self.build_root) as temp:
                    stage = Path(temp) / 'build'
                    stage.mkdir()
                    for name, raw in files.items():
                        (stage / name).write_bytes(raw)
                    (stage / 'manifest.json').write_text(canonical(manifest), encoding='utf-8')
                    os.replace(stage, target)
            return {'ok': True, 'manifest': self.get_build(build_id)[0]}

    def get_build(self, build_id):
        if not isinstance(build_id, str) or not re.fullmatch(r'd_[a-f0-9]{64}', build_id):
            raise ServiceError('VECTOR_BUILD', 'Invalid vector document build ID.')
        root = self.build_root / build_id
        names = {'project.json', 'document.json', 'preview.svg', 'manifest.json'}
        if not root.is_dir():
            raise ServiceError('BUILD_NOT_FOUND', 'Artwork build not found.')
        if root.is_symlink() or {p.name for p in root.iterdir()} != names or any((root / n).is_symlink() or not (root / n).is_file() or (root / n).stat().st_size > 512*1024 for n in names):
            raise ServiceError('ARTIFACT_CORRUPT', 'Artwork inventory differs from its fixed contract.')
        try:
            manifest = json.loads((root / 'manifest.json').read_bytes())
            records = manifest['files']
            if manifest['schema'] != BUILD_SCHEMA or manifest['status'] != 'complete' or manifest['build_id'] != build_id or len(records) != 3 or {r['name'] for r in records} != names - {'manifest.json'}:
                raise ValueError('manifest identity')
            for record in records:
                data = (root / record['name']).read_bytes()
                if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                    raise ValueError('checksum')
            source = json.loads((root / 'project.json').read_bytes())
            self.renderer(source['document']).validate(source['document'])
            svg = self.renderer(source['document']).render(source['document'])
            if ('d_' + digest(source) != build_id or source['schema'] != SCHEMA
                    or any(source[k] != manifest[k] for k in ('project_id', 'revision', 'producer'))
                    or compiler.structural_digest(source['document']) != manifest['content_sha256']
                    or (root / 'document.json').read_bytes() != canonical(source['document']).encode()
                    or (root / 'preview.svg').read_bytes() != svg.encode()):
                raise ValueError('source identity or render')
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError('ARTIFACT_CORRUPT', 'Artwork bytes differ from the frozen source.') from exc
        return manifest, source, svg

    def export(self, build_id):
        manifest, _, _ = self.get_build(build_id)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name in sorted([r['name'] for r in manifest['files']] + ['manifest.json']):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                bundle.writestr(info, (self.build_root / build_id / name).read_bytes())
        return data.getvalue()
