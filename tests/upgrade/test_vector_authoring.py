"""Real pure-compiler, persistent-store, HTTP and MCP adapter proofs; no native renderer."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
import shutil
import urllib.error
import urllib.request
import zipfile
import pytest
from mm_mcp.core import ServiceError
from mm_mcp.vector.service import VectorService
from mm_mcp.vector.provenance import ROOT, verify
from mm_mcp import tools


def create(app):
    return app.vectors.command({'operation': 'create', 'request': {'seed': 42}})


def command(app, project, operation, **kwargs):
    return app.vectors.command({'operation': operation, 'project_id': project['project_id'],
                               'expected_revision': project['revision'], **kwargs})


def test_locks_revisions_shared_material_isolation_and_exact_retry(app):
    p = create(app)
    patch = {'operation': 'patch', 'project_id': p['project_id'], 'expected_revision': 0,
             'idempotency_key': 'lock-palette', 'operations': [{'op': 'set_locks', 'locked': ['palette']}]}
    receipt = app.vectors.command(patch)
    second = VectorService(app.root)
    assert second.read(p['project_id'])['locked'] == ['palette']
    assert second.command(patch) == receipt
    p = second.read(p['project_id'])
    with pytest.raises(ValueError, match='Protected'):
        command(app, p, 'patch', idempotency_key='bad', operations=[{'op': 'set_controls', 'values': {'palette': 'orchid' if p['values']['palette'] != 'orchid' else 'moss'}}])
    with pytest.raises(ServiceError, match='separate'):
        command(app, p, 'patch', idempotency_key='bypass', operations=[{'op': 'set_locks', 'locked': []}, {'op': 'set_controls', 'values': {'palette': 'moss'}}])
    assert app.graphs.list() == []
    with pytest.raises(ServiceError, match='not found'):
        app.graphs.read(p['project_id'])
    with pytest.raises(ServiceError, match='not found'):
        app.graphs.patch(p['project_id'], 0, patch['operations'], 'lock-palette')
    assert second.command(patch) == receipt
    material = app.instantiate('fixture')
    assert len(app.graphs.list()) == 1 and len(second.store.list()) == 1
    with pytest.raises(ServiceError, match='not found'):
        second.read(material['project_id'])
    assert second.read(p['project_id'])['revision'] == 1


def test_concurrent_browser_ai_edits_fence_same_revision(app):
    p = create(app)
    other = VectorService(app.root)
    def edit(index):
        try:
            return (app.vectors if index == 0 else other).command({
                'operation': 'patch', 'project_id': p['project_id'], 'expected_revision': 0,
                'idempotency_key': 'edit-' + str(index),
                'operations': [{'op': 'set_controls', 'values': {'parameters.height': 150 + index}}]})
        except ServiceError as exc:
            return exc.result()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, range(2)))
    assert sum(r['ok'] for r in results) == 1
    assert [r['code'] for r in results if not r['ok']] == ['REVISION_CONFLICT']
    assert other.read(p['project_id'])['revision'] == 1


def test_candidates_motion_adoption_history_and_immutable_export(app):
    p = create(app)
    command(app, p, 'snapshot', name='Original')
    command(app, p, 'patch', idempotency_key='locks', operations=[{'op': 'set_locks', 'locked': ['palette', 'choices.crown']}])
    p = app.vectors.read(p['project_id'])
    family = command(app, p, 'variants', count=12, seed=80)
    assert family == command(app, p, 'variants', count=12, seed=80)
    assert family['unique_count'] == 12
    assert all(a['spec']['palette'] == p['values']['palette'] for a in family['assets'])
    motion = command(app, p, 'preview', clip='idle', frame_count=8)
    assert len({f['svg'] for f in motion['frames']}) > 1
    command(app, p, 'patch', idempotency_key='adopt', operations=[{'op': 'adopt', 'artifact': family['assets'][3]}])
    adopted = app.vectors.read(p['project_id'])
    build = command(app, adopted, 'build')['manifest']
    export = app.vectors.command({'operation': 'export', 'build_id': build['build_id']})
    data = base64.b64decode(export['data_base64'])
    assert hashlib.sha256(data).hexdigest() == export['sha256']
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert set(z.namelist()) == {'manifest.json', 'project.json', 'plant.artifact.json', 'plant.request.json', 'preview.svg'}
        artifact = json.loads(z.read('plant.artifact.json'))
        assert artifact == adopted['artifact']
        assert z.read('plant.artifact.json') == app.vectors.render(app.vectors.compiler.generate(json.loads(z.read('plant.request.json')))).encode()
        assert app.vectors.compiler.execute({'operation': 'create', 'request': json.loads(z.read('plant.request.json'))})['assets'][0] == artifact
    restored = command(app, adopted, 'restore', name='Original')
    assert restored['artifact'] == p['artifact'] and restored['locked'] == []
    undone = command(app, restored, 'history', direction='undo')
    assert undone['artifact'] == adopted['artifact'] and undone['locked'] == p['locked']
    assert app.vectors.export(build['build_id']) == data
    with pytest.raises(ServiceError, match='changed'):
        command(app, adopted, 'build')
    artifact_path = app.vectors.build_root / build['build_id'] / 'preview.svg'
    artifact_path.write_text('<svg/>')
    with pytest.raises(ServiceError, match='checksum'):
        app.vectors.export(build['build_id'])


def test_projection_tampering_and_unknown_file_rejected(tmp_path):
    root = tmp_path / 'vector'
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('__pycache__'))
    assert verify(root) == verify()
    path = root / 'producer' / 'core.py'
    original = path.read_bytes()
    path.write_bytes(original + b'\n')
    with pytest.raises(ServiceError, match='bytes'):
        verify(root)
    path.write_bytes(original)
    (root / 'producer' / 'unexpected.py').write_text('')
    with pytest.raises(ServiceError, match='inventory'):
        verify(root)


def test_real_http_mcp_share_one_project_and_auth(http_service, monkeypatch):
    server, token, app = http_service
    monkeypatch.setattr(tools, 'get_service', lambda: app)
    url = f'http://127.0.0.1:{server.server_port}/api/vectors'
    def http(body, auth=True):
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['X-MM-Token'] = token
        request = urllib.request.Request(url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    with pytest.raises(urllib.error.HTTPError) as error:
        http({'operation': 'list'}, False)
    assert error.value.code == 401
    p = http({'operation': 'create', 'request': {'seed': 12}})
    assert tools.vector_author({'operation': 'get', 'project_id': p['project_id']}) == app.vectors.read(p['project_id'])
    result = tools.vector_author({'operation': 'patch', 'project_id': p['project_id'], 'expected_revision': 0,
                                 'idempotency_key': 'ai-edit', 'operations': [{'op': 'set_controls', 'values': {'parameters.height': 180}}]})
    assert result['ok']
    assert http({'operation': 'get', 'project_id': p['project_id']})['values']['parameters.height'] == 180
    with pytest.raises(urllib.error.HTTPError) as error:
        http({'operation': 'preview', 'project_id': p['project_id'], 'expected_revision': 0})
    assert error.value.code == 409
    assert tools.vector_author({'operation': 'create', 'request': {'svg': '<script/>'}})['ok'] is False
