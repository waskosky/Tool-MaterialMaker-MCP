import base64
import hashlib
import io
import json
import zipfile
from unittest.mock import patch as mock_patch

import pytest

from mm_mcp.core import ServiceError
from mm_mcp.vector import provenance
from test_vector_studio import call, current, patch, read


def test_sdf_freezes_verified_source_and_preserves_plain_and_mask_exports(app):
    p = call(app.vectors, 'create', template='signage', title='Wayfinder')
    legacy = [current(app.vectors, p, 'build', **opts)['manifest']['build_id'] for opts in ({}, {'mask': True})]
    before = [app.vectors.studio.export(id) for id in legacy]
    direct = current(app.vectors, p, 'sdf', resolution=128, spread=8)
    opts = {'resolution': 128, 'spread': 8}
    built = current(app.vectors, p, 'build', sdf=opts)['manifest']
    result = call(app.vectors, 'build_get', build_id=built['build_id'])
    assert result['material_sdf_png'] == direct['png_base64']
    assert json.loads(result['material_sdf_json']) == result['material_sdf']
    assert result['material_sdf']['source_sha256'] == p['content_sha256']
    assert read(app.vectors, p)['revision'] == 0
    raw = app.vectors.studio.export(built['build_id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == {'manifest.json', 'project.json', 'document.json', 'preview.svg', 'sdf.json', 'sdf.png'}
        assert archive.read('sdf.png') == base64.b64decode(direct['png_base64'])
    params = p['document']['components']['wayfinder']['recipe']['request']['settings']
    params['steps'][1]['distance'] = 1
    changed = patch(app.vectors, p, [{'op': 'modifier_update', 'id': 'wayfinder', 'settings': params}])
    assert app.vectors.studio.export(built['build_id']) == raw
    assert [app.vectors.studio.export(id) for id in legacy] == before
    assert current(app.vectors, changed, 'build', sdf=opts)['manifest']['build_id'] != built['build_id']
    with pytest.raises(ServiceError, match='changed'):
        current(app.vectors, p, 'build', sdf=opts)


def test_sdf_rejects_rehashed_tampering_and_unknown_export_settings(app):
    p = call(app.vectors, 'create', template='signage')
    built = current(app.vectors, p, 'build', sdf={'resolution': 128, 'spread': 8})['manifest']
    root = app.vectors.studio.build_root / built['build_id']
    raw = bytearray((root / 'sdf.png').read_bytes())
    raw[-16] ^= 1
    (root / 'sdf.png').write_bytes(raw)
    record = next(r for r in built['files'] if r['name'] == 'sdf.png')
    record['sha256'] = hashlib.sha256(raw).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(built))
    with pytest.raises(ServiceError, match='differ'):
        call(app.vectors, 'build_get', build_id=built['build_id'])
    for opts in ({'resolution': 1024, 'spread': 8}, {'resolution': 128, 'spread': 8, 'file': '/tmp/a'}):
        with pytest.raises(ValueError):
            current(app.vectors, p, 'build', sdf=opts)


def test_dependency_pin_fails_closed():
    provenance.verify()
    with mock_patch.object(provenance, 'version', return_value='1.3.0'):
        with pytest.raises(ServiceError, match='pyclipper'):
            provenance.verify()
