"""Fixed bpy worker, invoked only by runner.py with service-owned private paths.

This module runs in Blender's bundled Python, not Workshop's interpreter. It has
no addon, network, arbitrary-code or user-path request parameters.
"""
import json
import math
import os
from pathlib import Path
import sys
from array import array

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from geometry import mesh_diagnostics
from guard import start_parent_guard


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def select_only(objects):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def inspect_object(obj):
    mesh = obj.data
    mesh.calc_loop_triangles()
    uv = mesh.uv_layers.active
    triangles = [tuple(tri.vertices) for tri in mesh.loop_triangles]
    uv_triangles = [[tuple(uv.data[index].uv) for index in tri.loops] for tri in mesh.loop_triangles] if uv else None
    report = mesh_diagnostics([tuple(vertex.co) for vertex in mesh.vertices], triangles, uv_triangles,
                              normals=[tuple(vertex.normal) for vertex in mesh.vertices], scale=tuple(obj.scale), material_slots=len(mesh.materials))
    report.update(name=obj.name, dimensions_m=list(obj.dimensions), location_m=list(obj.location), rotation_euler=list(obj.rotation_euler))
    return report


def unwrap(obj, name):
    select_only([obj])
    mesh = obj.data
    layer = mesh.uv_layers.get(name) or mesh.uv_layers.new(name=name)
    mesh.uv_layers.active = layer
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.035, correct_aspect=True, scale_to_bounds=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    return layer


def geometry(request, stage):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    tile = request['source']['physical_size_m'] if request['source'] else 1
    if request['mesh_id']:
        bpy.ops.import_scene.gltf(filepath=str(stage / 'source_mesh.glb'))
        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    else:
        if request['specimen'] == 'sphere':
            bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=tile / 2)
            for polygon in bpy.context.object.data.polygons:
                polygon.use_smooth = True
        elif request['specimen'] == 'beveled_cube':
            bpy.ops.mesh.primitive_cube_add(size=tile)
            bevel = bpy.context.object.modifiers.new('Specimen bevel', 'BEVEL')
            bevel.width, bevel.segments = tile * .075, 3
            bpy.ops.object.modifier_apply(modifier=bevel.name)
            unwrap(bpy.context.object, 'UVMap')
        else:
            bpy.ops.mesh.primitive_plane_add(size=tile)
        objects = [bpy.context.object]
        objects[0].name = request['specimen']
    if not objects:
        raise RuntimeError('No static mesh objects were imported.')
    diagnostics = {'objects': [inspect_object(obj) for obj in objects], 'units': 'meters',
                   'uv_preparation': 'smart_project_derivative' if request['unwrap'] else 'preserved',
                   'source_uv_scale': request['uv_scale'], 'material_assignment': 'Exact Workshop PBR build replaces every source material slot on the derivative.'}
    if request['operation'] == 'inspect' and not request['unwrap']:
        return objects[0], diagnostics
    had_uvs = all(obj.data.uv_layers.active for obj in objects)
    for obj in objects:
        if obj.data.uv_layers.active:
            obj.data.uv_layers.active.name = 'SourceUV'
    select_only(objects)
    if len(objects) > 1:
        bpy.ops.object.join()
    obj = bpy.context.object
    world_matrix = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world_matrix
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if request['unwrap']:
        destination = unwrap(obj, 'BakeUV')
        if not had_uvs:
            source = obj.data.uv_layers.get('SourceUV') or obj.data.uv_layers.new(name='SourceUV')
            for index, item in enumerate(destination.data):
                source.data[index].uv = item.uv
            obj.data.uv_layers.active = destination
    elif had_uvs:
        source = obj.data.uv_layers.get('SourceUV')
        destination = obj.data.uv_layers.new(name='BakeUV')
        for index, item in enumerate(source.data):
            destination.data[index].uv = item.uv
        obj.data.uv_layers.active = destination
    else:
        raise RuntimeError('Mesh has no complete UV map. Enable explicit unwrap to prepare a derivative.')
    obj.data.uv_layers.active.active_render = True
    diagnostics['prepared_objects'] = [inspect_object(obj)]
    if request['operation'] == 'bake' and not diagnostics['prepared_objects'][0]['uv']['bake_ready']:
        raise RuntimeError('UVs are overlapping, outside 0–1 or degenerate. Enable explicit unwrap to prepare a separate bake layout.')
    return obj, diagnostics


def load_texture(stage, name, role):
    image = bpy.data.images.load(str(stage / name), check_existing=True)
    image.colorspace_settings.name = 'sRGB' if role in ('base_color', 'emission') else 'Non-Color'
    return image


def material(stage, maps, *, uv_name, uv_scale=1, orm=None):
    mat = bpy.data.materials.new('Workshop PBR ' + uv_name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    uv = nodes.new('ShaderNodeUVMap')
    uv.uv_map = uv_name
    mapping = nodes.new('ShaderNodeVectorMath')
    mapping.operation = 'MULTIPLY'
    mapping.inputs[1].default_value = (uv_scale, uv_scale, 1)
    links.new(uv.outputs['UV'], mapping.inputs[0])
    sockets = {}
    for role, filename in maps.items():
        texture = nodes.new('ShaderNodeTexImage')
        texture.name = role
        texture.image = load_texture(stage, filename, role)
        texture.extension = 'REPEAT'
        links.new(mapping.outputs[0], texture.inputs['Vector'])
        sockets[role] = texture.outputs['Color']
    links.new(sockets['base_color'], bsdf.inputs['Base Color'])
    links.new(sockets['roughness'], bsdf.inputs['Roughness'])
    links.new(sockets['metallic'], bsdf.inputs['Metallic'])
    normal = nodes.new('ShaderNodeNormalMap')
    normal.uv_map = uv_name
    links.new(sockets['normal'], normal.inputs['Color'])
    links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
    if 'emission' in sockets:
        links.new(sockets['emission'], bsdf.inputs['Emission Color'])
        bsdf.inputs['Emission Strength'].default_value = 1
    if orm:
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = load_texture(stage, orm, 'orm')
        # Direct UV mapping is recognizable by glTF and needs no transform extension.
        links.new(uv.outputs['UV'], texture.inputs['Vector'])
        separate = nodes.new('ShaderNodeSeparateColor')
        links.new(texture.outputs['Color'], separate.inputs['Color'])
        links.new(separate.outputs['Green'], bsdf.inputs['Roughness'])
        links.new(separate.outputs['Blue'], bsdf.inputs['Metallic'])
        group = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
        group.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
        node = nodes.new('ShaderNodeGroup')
        node.node_tree = group
        links.new(separate.outputs['Red'], node.inputs['Occlusion'])
        # All exported baked textures sample their unique destination UV directly.
        for texture_node in [node for node in nodes if node.type == 'TEX_IMAGE']:
            links.new(uv.outputs['UV'], texture_node.inputs['Vector'])
    return mat, output, sockets


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.material_index = 0


def new_image(name, size, color_space='Non-Color', color=(0, 0, 0, 1)):
    image = bpy.data.images.new(name, width=size, height=size, alpha=False)
    image.colorspace_settings.name = color_space
    image.generated_color = color
    return image


def save_image(image, stage, name):
    image.file_format = 'PNG'
    image.filepath_raw = str(stage / name)
    image.save()


def bake_image(obj, mat, stage, name, size, kind, *, normal_space='TANGENT', color_space='Non-Color'):
    print('Workshop Blender bake: ' + name, flush=True)
    image = new_image(name, size, color_space)
    target = mat.node_tree.nodes.new('ShaderNodeTexImage')
    target.image = image
    mat.node_tree.nodes.active = target
    select_only([obj])
    bpy.ops.object.bake(type=kind, margin=4, use_clear=True, use_selected_to_active=False,
                        normal_space=normal_space, normal_r='POS_X', normal_g='POS_Y', normal_b='POS_Z')
    save_image(image, stage, name)
    mat.node_tree.nodes.remove(target)
    return image


def pixels(image):
    result = array('f', [0]) * (image.size[0] * image.size[1] * 4)
    image.pixels.foreach_get(result)
    return result


def image_from_pixels(stage, name, size, data):
    image = new_image(name, size)
    image.pixels.foreach_set(data)
    save_image(image, stage, name)
    return image


def bake(obj, mat, output, sockets, stage, request):
    size = request['resolution']
    baked = {}
    # Tangent normals include the source material's normal map. World normals
    # support a clearly described image-gradient mask, never claimed curvature.
    baked['normal'] = bake_image(obj, mat, stage, 'normal.png', size, 'NORMAL')
    # Rotation/scale and parent transforms were applied above. Blender 4.5's
    # OBJECT bake therefore records world-oriented vectors on this derivative.
    world_normal = bake_image(obj, mat, stage, 'world_normal.png', size, 'NORMAL', normal_space='OBJECT')
    geometry_ao = bake_image(obj, mat, stage, 'geometry_ao.png', size, 'AO')
    links = mat.node_tree.links
    original = output.inputs['Surface'].links[0].from_socket
    emitter = mat.node_tree.nodes.new('ShaderNodeEmission')
    links.new(emitter.outputs[0], output.inputs['Surface'])
    for role in ('base_color', 'roughness', 'metallic', 'height', 'emission', 'ao'):
        for link in list(emitter.inputs['Color'].links):
            links.remove(link)
        if role in sockets:
            links.new(sockets[role], emitter.inputs['Color'])
        else:
            emitter.inputs['Color'].default_value = (0, 0, 0, 1)
        filename = 'source_ao_bake.png' if role == 'ao' else role + '.png'
        baked[role] = bake_image(obj, mat, stage, filename, size, 'EMIT', color_space='sRGB' if role in ('base_color', 'emission') else 'Non-Color')
    links.new(original, output.inputs['Surface'])
    mat.node_tree.nodes.remove(emitter)
    geo, source_ao = pixels(geometry_ao), pixels(baked['ao'])
    ao = array('f', [0]) * len(geo)
    for i in range(0, len(geo), 4):
        value = max(0, min(1, geo[i] * source_ao[i]))
        ao[i:i + 4] = array('f', [value, value, value, 1])
    baked['ao'] = image_from_pixels(stage, 'ao.png', size, ao)
    roughness, metallic, world = pixels(baked['roughness']), pixels(baked['metallic']), pixels(world_normal)
    orm = array('f', [0]) * len(ao)
    crevice, edge = array('f', [0]) * len(ao), array('f', [0]) * len(ao)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            orm[i:i + 4] = array('f', [ao[i], roughness[i], metallic[i], 1])
            # Black unbaked texels are excluded from derived masks.
            covered = sum(world[i:i + 3]) > .001
            cavity = max(0, min(1, 1 - geo[i])) if covered else 0
            gradient = 0
            if covered:
                for nx, ny in ((min(size - 1, x + 1), y), (x, min(size - 1, y + 1))):
                    j = (ny * size + nx) * 4
                    if sum(world[j:j + 3]) > .001:
                        gradient += math.sqrt(sum((world[i + c] - world[j + c]) ** 2 for c in range(3)))
            value = min(1, gradient * 2)
            crevice[i:i + 4] = array('f', [cavity, cavity, cavity, 1])
            edge[i:i + 4] = array('f', [value, value, value, 1])
    image_from_pixels(stage, 'orm.png', size, orm)
    image_from_pixels(stage, 'crevice.png', size, crevice)
    image_from_pixels(stage, 'edge.png', size, edge)
    maps = {role: {'file': role + '.png', 'channels': 'rgb' if role in ('base_color', 'normal', 'emission') else 'r', 'color_space': 'srgb' if role in ('base_color', 'emission') else 'linear'} for role in baked}
    masks = {'crevice': {'file': 'crevice.png', 'channels': 'r', 'color_space': 'linear', 'derivation': 'Controlled 1 minus mesh AO, excluding uncovered texels; not geometric curvature.'},
             'edge': {'file': 'edge.png', 'channels': 'r', 'color_space': 'linear', 'derivation': 'Controlled image-space world-normal gradient ×2, clamped to 0–1; includes UV seam effects, not geometric curvature.'}}
    return maps, masks


def scene_for_preview(obj, size):
    scene = bpy.context.scene
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    center = sum(corners, Vector()) / 8
    radius = max((corner - center).length for corner in corners)
    if radius < 1e-6:
        raise RuntimeError('Mesh bounds have no visible extent.')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value = (.18, .2, .25, 1)
    scene.world.node_tree.nodes.get('Background').inputs[1].default_value = .35
    bpy.ops.object.camera_add(location=center + Vector((1.4, -2.2, 1.3)) * radius * 1.8)
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = radius * 2.5
    camera.data.clip_end = max(100, radius * 30)
    camera.data.clip_start = max(.00001, radius / 10000)
    scene.camera = camera
    for name, direction, power in [('Key', (-2, -3, 4), 700), ('Fill', (3, -1, 2), 350), ('Rim', (0, 3, 3), 900)]:
        bpy.ops.object.light_add(type='AREA', location=center + Vector(direction) * radius)
        light = bpy.context.object
        light.name = name
        light.data.energy = power * radius * radius
        light.data.shape = 'DISK'
        light.data.size = radius * 3
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.view_settings.view_transform = 'AgX'


def main():
    start_parent_guard(int(os.environ.get('MM_BLENDER_PARENT_PID', '0')))
    arguments = sys.argv[sys.argv.index('--') + 1:]
    if len(arguments) != 2:
        raise RuntimeError('Fixed worker requires its service-owned request and output directory.')
    request_path, stage = Path(arguments[0]), Path(arguments[1])
    request = json.loads(request_path.read_text())
    if request['operation'] not in ('inspect', 'preview', 'bake') or request['resolution'] not in (128, 256, 512):
        raise RuntimeError('Unsupported fixed worker operation.')
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 2
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    bpy.context.preferences.filepaths.save_version = 0
    obj, diagnostics = geometry(request, stage)
    report = {'blender_version': bpy.app.version_string, 'diagnostics': diagnostics, 'maps': {}, 'masks': {}}
    if request['operation'] != 'inspect':
        mat, output, sockets = material(stage, request['source']['maps'], uv_name='SourceUV', uv_scale=request['uv_scale'])
        assign(obj, mat)
        if request['operation'] == 'bake':
            report['maps'], report['masks'] = bake(obj, mat, output, sockets, stage, request)
            final_mat, _, _ = material(stage, {role: entry['file'] for role, entry in report['maps'].items()}, uv_name='BakeUV', orm='orm.png')
            assign(obj, final_mat)
        scene_for_preview(obj, request['resolution'])
        scene.render.filepath = str(stage / 'preview.png')
        bpy.ops.render.render(write_still=True)
        if request['operation'] == 'bake':
            # Foundry's portable shader samples UV0. Export only the destination
            # UV on a temporary mesh copy; the packed scene keeps both layouts.
            export_obj = obj.copy()
            export_mesh = obj.data.copy()
            export_obj.data = export_mesh
            bpy.context.scene.collection.objects.link(export_obj)
            try:
                for layer in list(export_mesh.uv_layers):
                    if layer.name != 'BakeUV':
                        export_mesh.uv_layers.remove(layer)
                export_mesh.uv_layers.active_index = 0
                export_mesh.uv_layers[0].active_render = True
                select_only([export_obj])
                bpy.ops.export_scene.gltf(filepath=str(stage / 'material.glb'), export_format='GLB', export_image_format='AUTO',
                                           export_texcoords=True, export_normals=True, export_materials='EXPORT', export_yup=True,
                                           use_selection=True, export_animations=False, export_cameras=False, export_lights=False)
            finally:
                bpy.data.objects.remove(export_obj, do_unlink=True)
                bpy.data.meshes.remove(export_mesh)
                select_only([obj])
        bpy.ops.file.pack_all()
        unpacked = [image.name for image in bpy.data.images if image.source == 'FILE' and not image.packed_file]
        if unpacked:
            raise RuntimeError('Packed Blender result still has external images: ' + ', '.join(unpacked))
        bpy.ops.wm.save_as_mainfile(filepath=str(stage / 'material.blend'), compress=False)
        report['diagnostics']['packed_images'] = sum(bool(image.packed_file) for image in bpy.data.images)
    write_json(stage / 'worker_result.json', report)
    print('Workshop Blender completed ' + request['operation'], flush=True)


if __name__ == '__main__':
    main()
