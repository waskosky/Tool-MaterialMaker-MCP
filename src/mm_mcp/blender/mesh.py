"""Bounded preflight for a deliberately small, self-contained static GLB subset."""
import hashlib
import io
import math
import struct

from PIL import Image
from mm_mcp.core import ServiceError, parse_json

MAX_MESH_BYTES = 4 * 1024 * 1024
MAX_VERTICES = 100000
MAX_TRIANGLES = 200000


def _require(condition, message):
    if not condition:
        raise ServiceError('BLENDER_MESH_INVALID', message)


def _integer(value, minimum=0, maximum=MAX_MESH_BYTES):
    return type(value) is int and minimum <= value <= maximum


def validate_glb(data, *, max_bytes=MAX_MESH_BYTES):
    """Reject dependent, executable, compressed, animated or unbounded input.

    Embedded PNG/JPEG images are accepted; URI resources and glTF extensions are
    outside this worker's admission contract, even when a particular URI is local.
    Native import receives only these already checked bytes in its private stage.
    """
    try:
        return _validate_glb(data, max_bytes)
    except (TypeError, KeyError, AttributeError, IndexError, struct.error) as exc:
        raise ServiceError('BLENDER_MESH_INVALID', 'Malformed static GLB structure.') from exc


def _validate_glb(data, max_bytes):
    _require(isinstance(data, bytes) and 20 <= len(data) <= max_bytes, 'GLB exceeds the supported byte limit.')
    magic, version, length = struct.unpack_from('<III', data)
    _require(magic == 0x46546c67 and version == 2 and length == len(data), 'Expected a complete glTF 2 binary container.')
    chunks = []
    offset = 12
    while offset < length:
        _require(offset + 8 <= length, 'Truncated GLB chunk header.')
        size, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        _require(size % 4 == 0 and offset + size <= length, 'Invalid GLB chunk length.')
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    _require(len(chunks) == 2 and [c[0] for c in chunks] == [0x4e4f534a, 0x004e4942], 'GLB requires one JSON and one embedded binary chunk.')
    doc, binary = parse_json(chunks[0][1]), chunks[1][1]
    _require(isinstance(doc, dict) and doc.get('asset', {}).get('version') == '2.0', 'Expected a glTF 2 asset.')

    def walk(value, depth=0):
        _require(depth <= 32, 'GLB metadata nesting exceeds the supported limit.')
        if isinstance(value, dict):
            _require('uri' not in value, 'GLB resources must use embedded buffer views; resource URIs are unsupported.')
            _require(not value.get('extensions') and not value.get('extensionsRequired'), 'glTF extensions are unsupported; export plain static glTF 2.')
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    walk(doc)
    _require(not any(doc.get(k) for k in ('skins', 'animations', 'cameras')), 'Only static meshes without skins, animations or cameras are supported.')
    arrays = {}
    for key, limit in [('buffers', 1), ('bufferViews', 2048), ('accessors', 2048), ('meshes', 256), ('nodes', 256), ('scenes', 32), ('materials', 64), ('images', 64), ('textures', 64), ('samplers', 64)]:
        value = doc.get(key, [])
        _require(isinstance(value, list) and len(value) <= limit and all(isinstance(v, dict) for v in value), f'Invalid or excessive {key}.')
        arrays[key] = value

    def ref(key, value):
        _require(_integer(value, maximum=len(arrays[key]) - 1), f'Invalid {key} reference.')
        return arrays[key][value]

    buffers = arrays['buffers']
    _require(len(buffers) == 1 and _integer(buffers[0].get('byteLength'), maximum=max_bytes) and len(binary) - 3 <= buffers[0]['byteLength'] <= len(binary), 'Invalid embedded buffer length.')
    for view in arrays['bufferViews']:
        _require(view.get('buffer') == 0 and _integer(view.get('byteOffset', 0), maximum=max_bytes) and _integer(view.get('byteLength'), minimum=1, maximum=max_bytes), 'Invalid buffer view.')
        _require(view.get('byteOffset', 0) + view['byteLength'] <= buffers[0]['byteLength'], 'Buffer view exceeds embedded bytes.')
        if 'byteStride' in view:
            _require(_integer(view['byteStride'], 4, 252) and view['byteStride'] % 4 == 0, 'Unsupported buffer stride.')

    decoded = []
    components = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
    dimensions = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
    total_values = 0
    for accessor in arrays['accessors']:
        _require('sparse' not in accessor and accessor.get('componentType') in components and accessor.get('type') in dimensions, 'Sparse or unsupported accessors are not admitted.')
        count = accessor.get('count')
        _require(_integer(count, 1, MAX_TRIANGLES * 3), 'Accessor count exceeds the geometry budget.')
        total_values += count * dimensions[accessor['type']]
        _require(total_values <= 2000000, 'GLB exceeds the decoded value budget.')
        view = ref('bufferViews', accessor.get('bufferView'))
        form, unit = components[accessor['componentType']]
        form = '<' + form * dimensions[accessor['type']]
        width = struct.calcsize(form)
        stride = view.get('byteStride', width)
        start = accessor.get('byteOffset', 0)
        _require(_integer(start) and start % unit == 0 and stride >= width and start + (count - 1) * stride + width <= view['byteLength'], 'Accessor exceeds its buffer view.')
        values = [struct.unpack_from(form, binary, view.get('byteOffset', 0) + start + i * stride) for i in range(count)]
        _require(all(math.isfinite(v) and abs(v) <= 1e8 for row in values for v in row), 'Non-finite or excessive mesh coordinates.')
        decoded.append(values)

    for image in arrays['images']:
        _require(image.get('mimeType') in ('image/png', 'image/jpeg'), 'Only embedded PNG/JPEG images are supported.')
        view = ref('bufferViews', image.get('bufferView'))
        raw = binary[view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']]
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                _require(opened.width <= 2048 and opened.height <= 2048 and opened.format in ('PNG', 'JPEG'), 'Embedded texture exceeds 2048 pixels or has an unsupported format.')
                opened.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ServiceError('BLENDER_MESH_INVALID', 'Invalid embedded image.') from exc
    for texture in arrays['textures']:
        ref('images', texture.get('source'))
        if 'sampler' in texture:
            ref('samplers', texture['sampler'])
    def material_textures(value):
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key.endswith('Texture'):
                _require(isinstance(child, dict), 'Invalid material texture descriptor.')
                ref('textures', child.get('index'))
                _require(_integer(child.get('texCoord', 0), 0, 1), 'Unsupported material texture coordinate set.')
            elif isinstance(child, dict):
                material_textures(child)
    for material in arrays['materials']:
        material_textures(material)

    vertices = triangles = primitives = 0
    has_uvs = True
    for mesh in arrays['meshes']:
        _require(not mesh.get('weights'), 'Morph weights are unsupported.')
        entries = mesh.get('primitives')
        _require(isinstance(entries, list) and 1 <= len(entries) <= 256, 'A mesh requires bounded primitives.')
        for primitive in entries:
            _require(isinstance(primitive, dict) and primitive.get('mode', 4) == 4 and not primitive.get('targets'), 'Only triangle primitives without morph targets are supported.')
            attrs = primitive.get('attributes')
            _require(isinstance(attrs, dict) and 'POSITION' in attrs and set(attrs) <= {'POSITION', 'NORMAL', 'TANGENT', 'TEXCOORD_0', 'TEXCOORD_1', 'COLOR_0'}, 'Unsupported vertex attributes.')
            position = ref('accessors', attrs['POSITION'])
            _require(position['type'] == 'VEC3' and position['componentType'] == 5126, 'Positions must be float VEC3 values.')
            count = position['count']
            for semantic, index in attrs.items():
                attr = ref('accessors', index)
                _require(attr['count'] == count, 'Vertex attribute counts differ.')
                required_type = 'VEC2' if semantic.startswith('TEXCOORD') else 'VEC3' if semantic in ('POSITION', 'NORMAL') else 'VEC4'
                _require(attr['type'] == required_type or semantic == 'COLOR_0' and attr['type'] == 'VEC3', 'Invalid vertex attribute shape.')
            if 'indices' in primitive:
                indices = ref('accessors', primitive['indices'])
                _require(indices['type'] == 'SCALAR' and indices['componentType'] in (5121, 5123, 5125), 'Indices must be unsigned scalar integers.')
                _require(all(v[0] < count for v in decoded[primitive['indices']]), 'Triangle index exceeds vertex count.')
                indices_count = indices['count']
            else:
                indices_count = count
            _require(indices_count % 3 == 0, 'Incomplete triangle primitive.')
            if 'material' in primitive:
                ref('materials', primitive['material'])
            vertices += count
            triangles += indices_count // 3
            primitives += 1
            has_uvs = has_uvs and 'TEXCOORD_0' in attrs
    _require(0 < vertices <= MAX_VERTICES and 0 < triangles <= MAX_TRIANGLES and primitives <= 256, 'Geometry exceeds the supported vertex/triangle budget.')

    parents = set()
    active = set()
    visited = set()
    instances = 0

    def visit(index):
        nonlocal instances
        node = ref('nodes', index)
        _require(index not in active, 'Cyclic node hierarchy.')
        if index in visited:
            return
        active.add(index)
        _require('skin' not in node and 'weights' not in node and 'camera' not in node, 'Only static mesh nodes are supported.')
        for key, size in [('matrix', 16), ('translation', 3), ('rotation', 4), ('scale', 3)]:
            if key in node:
                _require(isinstance(node[key], list) and len(node[key]) == size and all(type(v) in (float, int) and math.isfinite(v) and abs(v) <= 10000 for v in node[key]), 'Invalid node transform.')
        if 'mesh' in node:
            ref('meshes', node['mesh'])
            instances += 1
        children = node.get('children', [])
        _require(isinstance(children, list) and len(children) <= 256, 'Invalid node children.')
        for child in children:
            _require(child not in parents, 'Node has more than one parent.')
            parents.add(child)
            visit(child)
        active.remove(index)
        visited.add(index)
    for index in range(len(arrays['nodes'])):
        visit(index)
    _require(instances > 0 and vertices * instances <= MAX_VERTICES * 4 and triangles * instances <= MAX_TRIANGLES * 4, 'Missing or excessive mesh instances.')
    for scene in arrays['scenes']:
        roots = scene.get('nodes', [])
        _require(isinstance(roots, list) and len(roots) <= 256, 'Invalid scene roots.')
        for root in roots:
            ref('nodes', root)
        _require(len(set(roots)) == len(roots), 'Duplicate scene roots.')
    if 'scene' in doc:
        ref('scenes', doc['scene'])
    return {'mesh_id': 'mesh_' + hashlib.sha256(data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'vertices': vertices, 'triangles': triangles, 'has_uvs': has_uvs, 'material_slots': len(arrays['materials']), 'units': 'meters'}
