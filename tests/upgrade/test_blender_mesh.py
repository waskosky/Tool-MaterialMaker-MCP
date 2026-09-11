"""Portable GLB admission and diagnostics; these tests never launch Blender."""
import copy
import hashlib
import json
import struct

import pytest

from mm_mcp.core import ServiceError


def triangle_glb(change=None):
    binary = struct.pack('<9f6f3H', 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 1, 2)
    doc = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2}]}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 24}, {'buffer': 0, 'byteOffset': 60, 'byteLength': 6}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}, {'bufferView': 1, 'componentType': 5126, 'count': 3, 'type': 'VEC2'}, {'bufferView': 2, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}],
    }
    if change:
        change(doc)
    raw = json.dumps(doc, separators=(',', ':')).encode()
    raw += b' ' * (-len(raw) % 4)
    binary += b'\0' * (-len(binary) % 4)
    return struct.pack('<III', 0x46546c67, 2, 28 + len(raw) + len(binary)) + struct.pack('<II', len(raw), 0x4e4f534a) + raw + struct.pack('<II', len(binary), 0x004e4942) + binary


def test_static_embedded_glb_is_content_addressed():
    from mm_mcp.blender.mesh import validate_glb
    data = triangle_glb()
    result = validate_glb(data)
    assert result['mesh_id'] == 'mesh_' + hashlib.sha256(data).hexdigest()
    assert result['vertices'] == 3 and result['triangles'] == 1
    assert result['has_uvs'] is True and result['units'] == 'meters'


@pytest.mark.parametrize('change', [
    lambda d: d['buffers'][0].update(uri='file:///secret'),
    lambda d: d.update(images=[{'uri': 'https://example.invalid/asset.png'}]),
    lambda d: d.update(images=[{'uri': 'data:image/png;base64,abc'}]),
    lambda d: d.update(skins=[{}]),
    lambda d: d.update(animations=[{}]),
    lambda d: d['meshes'][0]['primitives'][0].update(targets=[{}]),
    lambda d: d.update(extensionsRequired=['KHR_draco_mesh_compression']),
    lambda d: d['nodes'][0].update(children=[0]),
    lambda d: d['meshes'][0]['primitives'][0].update(mode=1),
    lambda d: d['accessors'][0].update(count=99999999),
    lambda d: d['accessors'][0].update(sparse={}),
    lambda d: d['bufferViews'][0].update(byteLength=4),
    lambda d: d['nodes'][0].update(translation=[float('inf'), 0, 0]),
])
def test_dependent_animated_or_malformed_glb_rejected(change):
    from mm_mcp.blender.mesh import validate_glb
    with pytest.raises(ServiceError):
        validate_glb(triangle_glb(change))


@pytest.mark.parametrize('data', [b'', b'not glb', triangle_glb()[:-1], triangle_glb() + b'extra', b'x' * (4 * 1024 * 1024 + 1)], ids=['empty', 'text', 'truncated', 'trailing', 'oversized'])
def test_glb_header_and_byte_limit(data):
    from mm_mcp.blender.mesh import validate_glb
    with pytest.raises(ServiceError):
        validate_glb(data)


def test_diagnostics_report_uv_overlap_topology_and_transforms():
    from mm_mcp.blender.geometry import mesh_diagnostics
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    triangles = [(0, 1, 2), (0, 1, 3)]
    uv = [[(0, 0), (1, 0), (0, 1)]] * 2
    report = mesh_diagnostics(vertices, triangles, uv, normals=[(0, 0, 0)] * 4, scale=(2, 1, 1), material_slots=2)
    assert report['topology']['boundary_edges'] == 4
    assert report['uv']['sampled_overlap_pixels'] > 0
    assert report['uv']['bake_ready'] is False
    assert report['normals']['invalid_vertices'] == 4
    assert report['transforms']['non_uniform_scale'] is True
    assert report['material_slots'] == 2


def test_diagnostics_accept_unique_uvs_and_report_missing_uvs():
    from mm_mcp.blender.geometry import mesh_diagnostics
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    report = mesh_diagnostics(vertices, [(0, 1, 2)], [[(0, 0), (1, 0), (0, 1)]])
    assert report['uv']['bake_ready'] is True
    assert mesh_diagnostics(vertices, [(0, 1, 2)])['uv']['bake_ready'] is False


@pytest.mark.parametrize('change', [
    lambda d: d.update(asset=[]),
    lambda d: d['accessors'][0].update(componentType=[]),
    lambda d: d['accessors'][0].update(type=[]),
    lambda d: d['nodes'][0].update(children=[{}]),
    lambda d: d['scenes'][0].update(nodes=[0, 0]),
    lambda d: d.update(materials=[{'pbrMetallicRoughness': {'baseColorTexture': {'index': 9}}}]),
])
def test_invalid_glb_structures_fail_preflight_with_service_error(change):
    from mm_mcp.blender.mesh import validate_glb
    with pytest.raises(ServiceError):
        validate_glb(triangle_glb(change))
