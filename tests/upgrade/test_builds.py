import copy
import io
import json
from pathlib import Path
import time
import zipfile
import pytest
from PIL import Image
from mm_mcp.core import ServiceError
from mm_mcp.artifacts import verify_images
from mm_mcp.play.sliders import resolve_node
from mm_mcp import render

def test_exact_graph_export_and_no_shared_directory_leak(app,baker,cfg):
    p=app.instantiate('fixture',{'surface/param0':13})
    Path(cfg.output_dir,'unrelated.png').write_bytes(b'not an image')
    result=app.build({'project_id':p['project_id'],'revision':0,'size':32})
    with zipfile.ZipFile(io.BytesIO(app.builds.export(result['build_id']))) as z:
        graph=json.loads(z.read('material.ptex'))
        assert resolve_node(graph,'surface/src')['parameters']['gain']==13
        assert 'unrelated.png' not in z.namelist()
        manifest=json.loads(z.read('manifest.json'))
        assert set(z.namelist())=={f['name'] for f in manifest['files']}|{'manifest.json'}
    assert baker.calls==1

def test_cache_identity_and_corruption(app,baker):
    req={'recipe_id':'fixture','values':{'surface/param0':8},'size':32}
    a=app.build(req);b=app.build(req)
    assert a['build_id']==b['build_id'] and b['cached'] and baker.calls==1
    c=app.build({**req,'values':{'surface/param0':9}})
    assert c['build_id']!=a['build_id']
    (app.builds.directory(a['build_id'])/'material_albedo.png').write_bytes(b'corrupt')
    with pytest.raises(ServiceError):app.build(req)
    assert baker.calls==2

def test_stale_project_revision_never_bakes(app,baker):
    p=app.instantiate('fixture');app.patch(p['project_id'],0,[{'op':'set_controls','values':{'surface/param0':13}}],'change-01')
    with pytest.raises(ServiceError):app.build({'project_id':p['project_id'],'revision':0,'size':32})
    assert baker.calls==0

@pytest.mark.parametrize('kind',['nonzero','invalid_png','wrong_size','missing_orm'])
def test_failed_or_incomplete_build_not_published(app,baker,kind):
    def bad(graph,**kw):
        result=baker(graph,**kw)
        if kind=='nonzero':result['ok']=False;result['error']='Simulated renderer failure'
        if kind=='invalid_png':Path(result['images'][0]).write_bytes(b'bad')
        if kind=='wrong_size':Image.new('RGB',(64,64)).save(result['images'][0])
        if kind=='missing_orm':result['images']=[p for p in result['images'] if '_orm' not in p]
        return result
    app.render_fn=bad
    with pytest.raises(ServiceError):app.build({'recipe_id':'fixture','size':32})
    assert not list(app.builds.root.glob('b_*')) and not list(app.builds.root.glob('.staging-*'))

def test_real_render_runner_nonzero_junk_never_success(monkeypatch,cfg,graph):
    def run(cmd,timeout,**kwargs):
        # The process runner is stubbed; render() itself is the real implementation.
        import subprocess
        return subprocess.CompletedProcess(cmd,3,stdout='',stderr='fatal simulated process failure')
    monkeypatch.setattr(render,'_run_godot',run)
    result=render.render(graph,size=32,cfg=cfg)
    assert result.ok is False and not result.images

def test_image_symlink_escape(tmp_path):
    outside=tmp_path/'outside.png';Image.new('RGB',(32,32)).save(outside)
    root=tmp_path/'stage';root.mkdir()
    link=root/'material_albedo.png'
    try:link.symlink_to(outside)
    except OSError:pytest.skip('Host does not permit symlink creation')
    with pytest.raises(ServiceError):verify_images([link],32,root=root)

@pytest.mark.parametrize('target',['generic','godot','roblox','unity','unreal'])
def test_engine_packages_explicit_channels_and_limits(app,target):
    r=app.build({'recipe_id':'fixture','size':32,'target':target});directory=app.builds.directory(r['build_id'])
    info=json.loads((directory/'target.json').read_text());assert info['engine_import_verified'] is False
    with Image.open(directory/'material_roughness.png') as image:assert image.getpixel((0,0))==128
    with Image.open(directory/'material_metallic.png') as image:assert image.getpixel((0,0))==64
    if target=='unity':
        with Image.open(directory/'material_metallic_smoothness.png') as image:assert image.getpixel((0,0))==(64,64,64,127)
    if target=='unreal':
        with Image.open(directory/'material_normal_directx.png') as image:assert image.getpixel((0,0))==(128,127,255)
    if target=='godot':assert 'ORMMaterial3D' in (directory/'material.tres').read_text()
    if target=='roblox':assert info['SurfaceAppearance']['MetalnessMap']=='material_metallic.png'

def test_compare_and_personal_library(app):
    a=app.build({'recipe_id':'fixture','size':32});b=app.build({'recipe_id':'fixture','size':32,'values':{'surface/param0':13}})
    result=app.compare([a['build_id'],b['build_id']]);assert Path(result['image']).is_file()
    p=app.instantiate('fixture');saved=app.save_recipe(p['project_id'],'my_stone',{'author':'fixture'},'A test recipe.')
    assert saved['source']=='user' and app.recipes.search('my_stone')
    with pytest.raises(ServiceError):app.save_recipe(p['project_id'],'my_stone')

def test_job_completion_and_persistent_result(app):
    job=app.jobs.submit({'recipe_id':'fixture','size':32})
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        state=app.jobs.get(job['job_id'])
        if state['state'] in ('complete','failed'):break
        time.sleep(.03)
    assert state['state']=='complete',state
    assert app.builds.get(state['result']['build_id'])['status']=='complete'

def test_cancelled_build_not_published(app):
    with pytest.raises(ServiceError,match='cancelled'):app.build({'recipe_id':'fixture','size':32},cancel=lambda:True)
    assert not list(app.builds.root.glob('b_*'))
