"""Explicit operator-run Blender acceptance; source fixture is a test double.

MM_TEST_BLENDER_BINARY=/absolute/blender python -m pytest this_file -m native
No native executable is launched unless the operator opts in with that variable.
"""
import base64
import os
import json
import struct
from pathlib import Path

import pytest
from PIL import Image

from mm_mcp.service import MaterialService
from test_blender_mesh import triangle_glb

pytestmark = [pytest.mark.native, pytest.mark.skipif(not os.environ.get('MM_TEST_BLENDER_BINARY'), reason='Explicit Blender acceptance binary not configured')]


def assert_baked_uv_is_first(glb_path):
    raw = glb_path.read_bytes()
    json_length = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + json_length])
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            assert 'TEXCOORD_0' in primitive['attributes']
            assert 'TEXCOORD_1' not in primitive['attributes'], 'Matching mesh must expose only BakeUV as TEXCOORD_0.'
    def textures(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith('Texture'):
                    assert child.get('texCoord', 0) == 0
                textures(child)
        elif isinstance(value, list):
            for child in value:
                textures(child)
    textures(doc.get('materials', []))


@pytest.fixture
def native_blender(cfg, catalog, baker):
    cfg.blender_binary = os.environ['MM_TEST_BLENDER_BINARY']
    app = MaterialService(cfg, catalog, render_fn=baker)
    yield app
    app.close()


@pytest.mark.parametrize('operation', ['inspect', 'preview', 'bake'])
def test_real_blender_fixed_operations(native_blender, operation):
    app = native_blender
    body = {'operation': operation, 'resolution': 128, 'specimen': 'sphere'}
    if operation != 'inspect':
        body['build_id'] = app.build({'recipe_id': 'fixture', 'size': 128})['build_id']
    result = app.blender.execute(app.blender.prepare(body))
    manifest = app.blender.get(result['result_id'])
    assert manifest['renderer_kind'] == 'native_blender'
    assert manifest['blender_version'].startswith('4.5.')
    assert manifest['diagnostics']['objects'][0]['vertices'] > 0
    if operation != 'inspect':
        with Image.open(app.blender.artifact(result['result_id'], 'preview.png')) as preview:
            assert preview.size == (128, 128) and sum(preview.convert('RGB').getextrema()[0]) > 0
        assert manifest['tools']['blender_binary'] == str(Path(os.environ['MM_TEST_BLENDER_BINARY']).resolve())
        assert app.blender.artifact(result['result_id'], 'material.blend').stat().st_size > 10000
    if operation == 'bake':
        assert set(manifest['maps']) == {'base_color', 'normal', 'ao', 'roughness', 'metallic', 'height', 'emission'}
        assert set(manifest['masks']) == {'crevice', 'edge'}
        assert app.blender.artifact(result['result_id'], 'material.blend').stat().st_size > 10000
        assert app.blender.artifact(result['result_id'], 'material.glb').stat().st_size > 1000
        with Image.open(app.blender.artifact(result['result_id'], 'normal.png')) as normals:
            assert normals.convert('RGB').getextrema()[2][1] > 200
        assert_baked_uv_is_first(app.blender.artifact(result['result_id'], 'material.glb'))


def test_real_uploaded_mesh_explicit_unwrap_derivative(native_blender):
    app = native_blender
    raw = triangle_glb(lambda doc: doc['meshes'][0]['primitives'][0]['attributes'].pop('TEXCOORD_0'))
    mesh_id = app.blender.upload(name='no-uv.glb', data_base64=base64.b64encode(raw).decode())['mesh']['mesh_id']
    inspected = app.blender.execute(app.blender.prepare({'operation': 'inspect', 'mesh_id': mesh_id, 'resolution': 128}))
    assert inspected['manifest']['diagnostics']['objects'][0]['uv']['present'] is False
    build_id = app.build({'recipe_id': 'fixture', 'size': 128})['build_id']
    prepared = app.blender.execute(app.blender.prepare({'operation': 'bake', 'build_id': build_id, 'mesh_id': mesh_id, 'resolution': 128, 'unwrap': True, 'uv_scale': 2}))
    diagnostics = prepared['manifest']['diagnostics']
    assert diagnostics['uv_preparation'] == 'smart_project_derivative'
    assert diagnostics['prepared_objects'][0]['uv']['bake_ready'] is True
    assert app.blender.artifact(prepared['result_id'], 'source_mesh.glb').read_bytes() == raw
    assert_baked_uv_is_first(app.blender.artifact(prepared['result_id'], 'material.glb'))
