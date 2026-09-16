"""General documents share transactions across browser/AI and retain exact exports."""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import zipfile

import pytest
from mm_mcp.core import ServiceError
from mm_mcp.vector.service import VectorService


def call(service, operation, **fields):
    return service.command({'profile': 'vector-document-v1', 'operation': operation, **fields})


def current(service, project, operation, **fields):
    return call(service, operation, project_id=project['project_id'], expected_revision=project['revision'], **fields)


def test_document_history_snapshot_freeze_and_existing_plants(app):
    service = app.vectors
    plant = service.command({'operation': 'create', 'request': {'seed': 2}})
    project = call(service, 'create', template='beacon', title='Field beacon')
    current(service, project, 'snapshot', name='Before edits')
    frozen = current(service, project, 'build')['manifest']
    archive = call(service, 'export', build_id=frozen['build_id'])
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(archive['data_base64']))) as bundle:
        assert set(bundle.namelist()) == {'document.json', 'preview.svg', 'manifest.json', 'project.json'}
        assert json.loads(bundle.read('document.json')) == project['document']
        assert bundle.read('preview.svg').decode() == project['preview_svg']
    request = dict(project_id=project['project_id'], expected_revision=0, idempotency_key='shared-edit',
                   operations=[{'op': 'update', 'id': 'glass', 'changes': {'fill': '#FFA455'}}])
    receipt = call(service, 'patch', **request)
    second = VectorService(app.root)
    assert call(second, 'patch', **request) == receipt
    edited = call(second, 'get', project_id=project['project_id'])
    assert edited['revision'] == 1 and edited['preview_svg'] != project['preview_svg']
    undone = current(second, edited, 'history', direction='undo')
    assert undone['document'] == project['document'] and undone['revision'] == 2
    redone = current(service, undone, 'history', direction='redo')
    assert redone['document'] == edited['document']
    restored = current(service, redone, 'restore', name='Before edits')
    assert restored['document'] == project['document'] and restored['revision'] == 4
    assert call(second, 'export', build_id=frozen['build_id']) == archive
    assert call(second, 'build_get', build_id=frozen['build_id'])['document'] == project['document']
    assert [p['id'] for p in call(service, 'list')['projects']] == [project['project_id']]
    assert [p['id'] for p in service.command({'operation': 'list'})['projects']] == [plant['project_id']]
    with pytest.raises(ServiceError, match='not found'):
        service.read(project['project_id'])
    with pytest.raises(ServiceError, match='not found'):
        call(service, 'get', project_id=plant['project_id'])
    path = service.documents.build_root / frozen['build_id'] / 'preview.svg'
    path.write_text('<svg/>')
    with pytest.raises(ServiceError, match='frozen'):
        call(service, 'export', build_id=frozen['build_id'])


def test_browser_and_ai_compete_for_exact_revision_and_protection(app):
    p = call(app.vectors, 'create', template='power_cell')
    services = [app.vectors, VectorService(app.root)]
    def edit(i):
        try:
            return current(services[i], p, 'patch', idempotency_key='edit-'+str(i),
                           operations=[{'op': 'set_lock', 'id': 'body', 'locked': True}])
        except ServiceError as exc:
            return exc.result()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(edit, range(2)))
    assert sum(r['ok'] for r in results) == 1
    assert [r['code'] for r in results if not r['ok']] == ['REVISION_CONFLICT']
    locked = call(app.vectors, 'get', project_id=p['project_id'])
    for operations in [
        [{'op': 'palette', 'colors': {'body': '#112233'}}],
        [{'op': 'delete', 'id': 'body'}],
        [{'op': 'replace', 'document': p['document']}],
    ]:
        with pytest.raises(ValueError, match='Protected'):
            current(app.vectors, locked, 'patch', idempotency_key='refused', operations=operations)
    assert call(app.vectors, 'get', project_id=p['project_id']) == locked
    candidates = current(app.vectors, locked, 'variants', palettes=[{'accent': '#FF8822'}, {'accent': '#AABBFF'}])
    assert candidates['unique_count'] == 2
    assert all(d['nodes'] == locked['document']['nodes'] for d in candidates['documents'])
    with pytest.raises(ValueError):
        call(app.vectors, 'create', template='beacon', svg='<svg/>')


def test_symlink_and_manifest_path_tampering_fail_closed(app, tmp_path):
    p = call(app.vectors, 'create', template='medical_kit')
    manifest = current(app.vectors, p, 'build')['manifest']
    root = app.vectors.documents.build_root / manifest['build_id']
    path = root / 'manifest.json'
    changed = json.loads(path.read_text())
    changed['files'][0]['name'] = '../outside.json'
    path.write_text(json.dumps(changed))
    with pytest.raises(ServiceError, match='frozen'):
        call(app.vectors, 'build_get', build_id=manifest['build_id'])
