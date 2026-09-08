"""Content-addressed, verified material builds and engine-neutral packaging."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time
from PIL import Image
from mm_mcp import __version__
from mm_mcp.core import ServiceError, atomic_json, canonical, digest, file_digest, file_lock, identifier, resolution
from mm_mcp.artifacts import verify_images, verify_manifest, zip_build, image_metrics, channel_name
from mm_mcp.policy import graph_dependencies
from mm_mcp.graph import find_material_node
from mm_mcp import render as renderer

TARGETS = ('generic','godot','roblox','unity','unreal')
CANONICAL_PROFILE = 'Godot/Godot 4 Standard'


def tool_fingerprint(cfg, catalog):
    """Hash code/resources, not only a possibly dirty checkout's commit name."""
    root=Path(cfg.project_path)
    files=[]
    if root.is_dir():
        for p in sorted(root.rglob('*')):
            if any(part.startswith('.') for part in p.relative_to(root).parts):
                continue
            if p.is_file() and p.suffix.lower() in ('.gd','.gdshader','.mmg','.tres','.tscn','.godot'):
                files.append((str(p.relative_to(root)),file_digest(p)))
    binary=Path(cfg.console_binary or cfg.godot_binary)
    implementation=Path(__file__).parent
    source_hash=digest([(str(f.relative_to(implementation)),file_digest(f)) for f in sorted(implementation.rglob('*.py')) if '__pycache__' not in f.parts])
    return {'package':__version__,'implementation_sha256':source_hash, 'catalog_hash':digest(catalog), 'material_maker_hash':digest(files),
            'godot_binary_sha256':file_digest(binary) if binary.is_file() else None,
            'platform':platform.platform(),
            'render_device':os.environ.get('MM_RENDER_DEVICE_ID','unspecified'),
            'reproducibility':'Inputs are recorded; bit-identical GPU output across devices is not guaranteed.'}


def expected_channels(graph, catalog):
    """Require the maps associated with connected Material inputs, not absent defaults."""
    material=find_material_node(graph)
    spec=catalog.get('material',{})
    names=[p.get('name') for p in spec.get('inputs',[])]
    # This mapping is Material Maker's standard material interface. A catalog,
    # when present, takes precedence over the compatibility fallback.
    if not names:
        names=['albedo_tex','metallic_tex','roughness_tex','emission_tex','normal_tex','ao_tex','depth_tex','sss_tex']
    connected={names[e.get('to_port',0)] for e in graph.get('connections',[])
               if e.get('to')==material['name'] and type(e.get('to_port',0)) is int and 0<=e.get('to_port',0)<len(names)}
    channels=set()
    for name,channel in [('albedo_tex','albedo'),('normal_tex','normal'),('emission_tex','emission'),('depth_tex','height')]:
        if name in connected:
            channels.add(channel)
    if connected & {'ao_tex','roughness_tex','metallic_tex'}:
        channels.add('orm')
    return sorted(channels)


def _complete_defaults(stage, graph, images, size):
    """Only supply maps for UNCONNECTED channels; never cover up a failed bake."""
    params=find_material_node(graph).get('parameters',{})
    found={channel_name(p):p for p in images}; defaults=[]
    color=params.get('albedo_color',{})
    def byte(x):
        return round(max(0,min(1,float(x)))*255)
    values={'albedo':tuple(byte(color.get(c,1)) for c in 'rgba'),
            'normal':(128,128,255),
            'orm':(255,byte(params.get('roughness',1)),byte(params.get('metallic',0)))}
    for channel,value in values.items():
        if channel not in found:
            p=Path(stage)/f'material_{channel}.png'
            Image.new('RGBA' if channel=='albedo' else 'RGB',(size,size),value).save(p)
            images.append(str(p)); defaults.append(channel)
    return defaults


def _write_target_files(stage: Path, images: list, target: str, physical_size_m: float):
    """Produce concrete map layouts; publish exact conventions in target.json."""
    maps={channel_name(p):Path(p) for p in images}
    with Image.open(maps['orm']) as src:
        r,g,b=src.convert('RGB').split()
    for name,im in [('ao',r),('roughness',g),('metallic',b)]:
        p=stage/f'material_{name}.png'; im.save(p); maps[name]=p
    info={'target':target,'physical_size_m':physical_size_m,'normal_convention':'OpenGL (+Y)',
          'normal_green_flip':False,'color_maps':['albedo','emission'],
          'linear_maps':['normal','orm','ao','roughness','metallic','height'],
          'orm_channels':{'red':'occlusion','green':'roughness','blue':'metallic'},
          'engine_import_verified':False}
    if target=='godot':
        # Relative resource paths keep the material relocatable as a folder.
        text="""[gd_resource type="ORMMaterial3D" load_steps=4 format=3]

[ext_resource type="Texture2D" path="material_albedo.png" id="1"]
[ext_resource type="Texture2D" path="material_normal.png" id="2"]
[ext_resource type="Texture2D" path="material_orm.png" id="3"]

[resource]
albedo_texture = ExtResource("1")
normal_enabled = true
normal_texture = ExtResource("2")
orm_texture = ExtResource("3")
"""
        (stage/'material.tres').write_text(text)
        info['notes']='Import the whole folder. Review transparency, emission, height and normal intensity for this material; the generated resource wires the baseline opaque channels only.'
    elif target=='roblox':
        info['SurfaceAppearance']={'ColorMap':'material_albedo.png','NormalMap':'material_normal.png',
                                   'MetalnessMap':'material_metallic.png','RoughnessMap':'material_roughness.png'}
        info['notes']='Upload maps in Roblox Studio and assign the resulting asset IDs. This package does not upload assets or make material graphs run in Roblox.'
    elif target=='unity':
        from PIL import ImageOps
        unity=Image.merge('RGBA',(b,b,b,ImageOps.invert(g))); unity.save(stage/'material_metallic_smoothness.png')
        info['metallic_smoothness']={'metallic':'red','smoothness':'alpha = 1 - roughness'}
        info['notes']='Choose the intended Unity render pipeline and configure normal/data import types; no pipeline-specific .mat is asserted.'
    elif target=='unreal':
        with Image.open(maps['normal']) as src:
            nr,ng,nb=src.convert('RGB').split()
        from PIL import ImageOps
        Image.merge('RGB',(nr,ImageOps.invert(ng),nb)).save(stage/'material_normal_directx.png')
        info['normal_convention']='DirectX (-Y) in material_normal_directx.png; original normal stays +Y'
        info['notes']='Use the DirectX normal variant and linear ORM data. Disable sRGB for ORM. No .uasset binary is generated.'
    atomic_json(stage/'target.json',info)
    return info


class BuildStore:
    def __init__(self, root, cfg, catalog):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.cfg,self.catalog=cfg,catalog
    def build(self, graph, *, material_id='custom', values=None, size=512, target='generic',
              seed=None, physical_size_m=1.0, provenance=None, trusted_recipe=False,
              render_fn=None, cancel=None, force=False):
        resolution(size,getattr(self.cfg,'max_resolution',2048)); identifier(material_id)
        if target not in TARGETS:
            raise ServiceError('TARGET','Unknown target profile.',targets=list(TARGETS))
        if type(physical_size_m) not in (int,float) or not 0<physical_size_m<=100000:
            raise ServiceError('PHYSICAL_SCALE','physical_size_m must be positive and finite.')
        graph=copy.deepcopy(graph)
        if seed is not None:
            if type(seed) is not int or not 0<=seed<=2147483647:
                raise ServiceError('SEED_RANGE','Seed must be a nonnegative 31-bit integer.')
            graph.pop('seed', None)
            graph['seed_int']=seed
        deps=graph_dependencies(graph,self.cfg,trusted_recipe=trusted_recipe)
        inputs={'schema_version':1,'material_id':material_id,'graph':graph,'values':values or {},
                'resolution':size,'target':target,'seed':seed,'physical_size_m':physical_size_m,
                'dependencies':deps,'renderer_kind':'injected_test_double' if render_fn is not None else 'native_material_maker','tools':tool_fingerprint(self.cfg,self.catalog), 'provenance':provenance or {}}
        key=digest(inputs); build_id='b_'+key
        target_dir=self.root/build_id
        with file_lock(self.root/'.build.lock',cancel=cancel):
            if target_dir.exists() and not force:
                manifest=verify_manifest(target_dir)
                return {'ok':True,'build_id':build_id,'cached':True,'manifest':manifest}
            if target_dir.exists():
                # A forced rebuild gets a unique ID; never replace an immutable approved result.
                build_id += '_'+str(time.time_ns()); target_dir=self.root/build_id
            stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=self.root))
            try:
                if cancel and cancel():
                    raise ServiceError('CANCELLED','Build cancelled.')
                expected=expected_channels(graph,self.catalog)
                # Recipe/native-graph validation happens before entering the build store.
                # Render into a private directory, even when a caller injects a renderer for tests.
                fn=render_fn or renderer.render
                result=fn(graph,size=size,outdir=str(stage),basename='material',target=CANONICAL_PROFILE,
                          cfg=self.cfg,**({'cancel':cancel} if cancel else {}))
                ok=result.get('ok') if isinstance(result,dict) else result.ok
                images=list(result.get('images',[]) if isinstance(result,dict) else result.images)
                if not ok:
                    if cancel and cancel():
                        raise ServiceError('CANCELLED','Build cancelled.')
                    error=result.get('error') if isinstance(result,dict) else result.error
                    raise ServiceError('RENDER_FAILED',error or 'Renderer reported failure.')
                verify_images(images,size,expected,stage)
                defaults=_complete_defaults(stage,graph,images,size)
                _write_target_files(stage,images,target,physical_size_m)
                # Save exactly the graph whose inputs identify this build, not the current browser state.
                atomic_json(stage/'material.ptex',graph)
                atomic_json(stage/'request.json',inputs)
                metrics={channel_name(p) or Path(p).name:image_metrics(p) for p in images}
                atomic_json(stage/'quality.json',{'metrics':metrics,'generated_default_channels':defaults,
                                                'visual_approval':'not_performed'})
                (stage/'IMPORT.md').write_text("""# Import this material\n\nKeep this directory together. `material.ptex` is the editable source; `request.json` records the exact inputs. Read `target.json` for channel conventions and limitations. `quality.json` is technical evidence, not an artistic approval. External source references are recorded by hash; obtain their licenses and preserve their original paths when reopening a recipe. Native engine import must be checked on your target engine.\n""")
                if cancel and cancel():
                    raise ServiceError('CANCELLED','Build cancelled before publication.')
                if graph_dependencies(graph,self.cfg,trusted_recipe=trusted_recipe)!=deps:
                    raise ServiceError('DEPENDENCY_CHANGED','A referenced source changed while rendering; build not published.')
                if tool_fingerprint(self.cfg,self.catalog)!=inputs['tools']:
                    raise ServiceError('TOOL_CHANGED','A rendering tool or definition changed during the build; output not published.')
                entries=[]
                for p in sorted(stage.iterdir()):
                    if not p.is_file() or p.is_symlink():
                        raise ServiceError('ARTIFACT_ESCAPE','Unexpected non-file in build output.')
                    item={'name':p.name,'sha256':file_digest(p),'bytes':p.stat().st_size}
                    if p.suffix.lower()=='.png':
                        item.update(verify_images([p],size,root=stage)[0])
                    entries.append(item)
                manifest={'schema_version':1,'status':'complete','build_id':build_id,'input_hash':key,
                          'material_id':material_id,'resolution':size,'target':target,'files':entries,
                          'renderer_kind':inputs['renderer_kind'],
                          'maps':[p.name for p in sorted(stage.glob('*.png'))],
                          'generated_default_channels':defaults,'created_unix':time.time()}
                atomic_json(stage/'manifest.json',manifest)
                os.replace(stage,target_dir)
                return {'ok':True,'build_id':build_id,'cached':False,'manifest':manifest}
            finally:
                if stage.exists():
                    shutil.rmtree(stage,ignore_errors=True)
    def directory(self, build_id):
        identifier(build_id,'build ID'); directory=self.root/build_id
        if not directory.is_dir() or directory.is_symlink():
            raise ServiceError('BUILD_NOT_FOUND','Build not found.')
        return directory
    def get(self,build_id):
        return verify_manifest(self.directory(build_id))
    def export(self,build_id):
        return zip_build(self.directory(build_id))
    def artifact(self,build_id,name):
        identifier(name,'artifact filename'); manifest=self.get(build_id)
        if name!='manifest.json' and name not in {f['name'] for f in manifest['files']}:
            raise ServiceError('ARTIFACT_NOT_FOUND','File is not part of this build.')
        return self.directory(build_id)/name
