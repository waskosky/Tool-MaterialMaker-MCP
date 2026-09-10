"""Additional hardening contracts: synthetic native responses are explicitly mocks."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from PIL import Image
from mm_mcp.core import ServiceError, file_lock
from mm_mcp.mesh_masks import parse_obj, bake_arrays, bake_mesh_masks
from mm_mcp.validator import validate_graph
from mm_mcp.idle import IdleWatchdog
from mm_mcp import live, preview, tools

OBJ = '''v 0 0 0
v 1 1 0
v 0 0 1
vt 0 0
vt 1 0
vt 0 1
f 1/1 3/3 2/2
'''


def test_mesh_masks_are_real_png_and_cached(cfg):
    source=Path(cfg.output_dir)/'triangle.obj';source.write_text(OBJ)
    result=bake_mesh_masks(str(source),cfg,size=32)
    assert not result['cached'] and 0 < result['metrics']['coverage_fraction'] < 1
    assert result['inputs']['up_axis']=='y'
    for entry in result['files']:
        with Image.open(entry['path']) as im:
            assert im.size==(32,32) and im.mode=='L'
            if entry['channel']=='upward': assert im.getextrema()[1] > 0
    assert bake_mesh_masks(str(source),cfg,size=32)['cached']
    Path(result['files'][0]['path']).write_bytes(b'corrupt')
    with pytest.raises(ServiceError,match='changed'):bake_mesh_masks(str(source),cfg,size=32)

@pytest.mark.parametrize('text',[OBJ.replace('f 1/1 3/3 2/2','f 1 3 2'),OBJ.replace('vt 1 0','vt 2 0'),OBJ.replace('v 0 0 0','v nan 0 0'),OBJ.replace('f 1/1 3/3 2/2','f 1/1 3/3 2/2 1/1')])
def test_mesh_invalid_inputs(text):
    with pytest.raises(ServiceError):parse_obj(text)

def test_mesh_overlap_and_budget():
    vertices,uvs,triangles=parse_obj(OBJ)
    with pytest.raises(ServiceError,match='overlap'):bake_arrays(vertices,uvs,triangles*2,size=32)
    with pytest.raises(ServiceError,match='budget'):bake_arrays(vertices,uvs,triangles,size=32,max_raster_work=1)

def test_mesh_path_escape_and_encoding(cfg,tmp_path):
    path=tmp_path/'outside.obj';path.write_text(OBJ)
    with pytest.raises(ServiceError):bake_mesh_masks(str(path),cfg,size=32)
    path=Path(cfg.output_dir)/'encoding.obj';path.write_bytes(b'\xff')
    with pytest.raises(ServiceError,match='UTF-8'):bake_mesh_masks(str(path),cfg,size=32)

def test_semantic_aliases_and_locks(app):
    described=app.recipes.describe('fixture')
    assert described['semantic_controls']['gain']=='surface/param0'
    graph,_=app.recipes.instantiate('fixture',{'gain':13})
    surface=next(n for n in graph['nodes'] if n['name']=='surface')
    assert surface['parameters']['param0']==13
    family=app.family('fixture',count=3,seed=12,ranges={'gain':[2,9]},locked=['gain'],values={'gain':6})
    assert all(v['values']['surface/param0']==6 for v in family['candidates'])

def test_recipe_invalid_metadata_does_not_publish(app,graph):
    with pytest.raises(ServiceError):app.recipes.save('invalid',graph,{'semantic_controls':{'gain':'nope'}})
    assert not (app.recipes.user_dir/'invalid.ptex').exists()

def test_recipe_alias_roundtrip(app,graph):
    saved=app.recipes.save('new',graph,{'semantic_controls':{'weathering':'surface/param0'}},'An explicit control binding.')
    assert saved['semantic_controls']['weathering']=='surface/param0'
    loaded,_=app.recipes.instantiate('user.new',{'weathering':4})
    assert loaded['nodes'][1]['parameters']['param0']==4

@pytest.mark.parametrize('change',[{'parameters':[]},{'generic_size':2.5},{'generic_size':10000},{'parameters':{'gain':'x'}},{'parameters':{'ramp':{'type':'Gradient','points':[]}}}])
def test_strict_validation_hardening(graph,catalog,change):
    graph['nodes'][1]['nodes'][0].update(change)
    assert any(p['severity']=='error' for p in validate_graph(graph,catalog,mode='strict'))

def test_active_idle_guard():
    clock=SimpleNamespace(now=0);calls=[];busy=[True]
    watcher=IdleWatchdog(10,clock=lambda:clock.now,on_expire=calls.append,is_active=lambda:busy[0])
    clock.now=30;assert not watcher.check() and not calls
    busy[0]=False;clock.now=39;assert not watcher.check()
    clock.now=40;assert watcher.check() and calls==[10]

def test_cancellation_before_resource_wait(tmp_path):
    with pytest.raises(ServiceError,match='cancelled'):
        with file_lock(tmp_path/'x.lock',cancel=lambda:True):pass

def _preview_inputs(cfg):
    result=[]
    for name in ('albedo','normal','orm'):
        path=Path(cfg.output_dir)/('material_'+name+'.png');Image.new('RGB',(32,32)).save(path);result.append(str(path))
    return result

@pytest.mark.parametrize('exit_code,corrupt',[(1,False),(0,True),(0,False)])
def test_preview_verified_atomic_publish(cfg,monkeypatch,exit_code,corrupt):
    inputs=_preview_inputs(cfg);destination=Path(cfg.output_dir)/'test_preview.png';destination.write_bytes(b'previous good file')
    def run(cmd,timeout,**kwargs):
        out=Path(next(a[6:] for a in cmd if a.startswith('--out=')))
        if corrupt:out.write_bytes(b'junk')
        else:Image.new('RGB',(64,32)).save(out)
        return subprocess.CompletedProcess(cmd,exit_code,'','')
    monkeypatch.setattr(preview,'_run_godot',run)
    result=preview.render_preview(*inputs,cfg=cfg,basename='test')
    assert result.ok==(exit_code==0 and not corrupt)
    if not result.ok:assert destination.read_bytes()==b'previous good file'
    else:
        with Image.open(destination) as im:assert im.size==(64,32)

def test_native_record_and_authenticated_payload(tmp_path,monkeypatch):
    monkeypatch.setenv('MM_RUNTIME_DIR',str(tmp_path))
    record=tmp_path/'live.json';record.write_text(json.dumps({'host':'127.0.0.1','port':8765,'protocol':'mm-live/2','token':'private-token'}));record.chmod(0o600)
    captured=[]
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def sendall(self,payload):captured.append(json.loads(payload))
        def settimeout(self,value):pass
        def recv(self,count):return b'{"ok":true,"revision":"instance:tab:hash"}\n'
    monkeypatch.setattr(live.socket,'create_connection',lambda *a,**k:Socket())
    assert live.ping().ok and captured[0]['token']=='private-token'
    assert not live.ping(host='example.com').ok
    if os.name!='nt':
        record.chmod(0o644);assert not live.ping().ok

def test_native_retry_uses_receipt_before_stale_read(cfg,monkeypatch):
    calls=[]
    def send(command,**kwargs):
        calls.append(command);return live.LiveResult(True,data={'ok':True,'revision':'new'})
    monkeypatch.setattr(live,'_send_command',send)
    result=live.transaction([], 'old', 'same-request', cfg=cfg)
    assert result.ok and len(calls)==1 and calls[0]['cmd']=='transaction_status'

def test_adapter_roundtrip_and_errors(app,monkeypatch):
    monkeypatch.setattr(tools,'get_service',lambda:app)
    result=tools.material_project_create('fixture',{'gain':12})
    assert result['ok'] and tools.material_project_get(result['project_id'])['controls']
    assert tools.material_project_patch(result['project_id'],False,[], 'bad')['ok'] is False
    assert tools.material_recipe_search(limit=999)['ok'] is False
    assert len(tools.TOOLS)==24

def test_real_worker_subprocess_cancel():
    from mm_mcp.render import _run_godot
    with pytest.raises(ServiceError,match='cancelled'):
        _run_godot([sys.executable,'-c','import time;time.sleep(30)'],timeout=5,cancel=lambda:True)

def test_manifest_identity_is_verified(app):
    build=app.build({'recipe_id':'fixture','size':32})
    p=app.builds.directory(build['build_id'])/'manifest.json';m=json.loads(p.read_text());m['build_id']='wrong';p.write_text(json.dumps(m))
    with pytest.raises(ServiceError,match='identity'):app.builds.get(build['build_id'])


def test_seed_uses_native_integer_serialization(app):
    built=app.build({'recipe_id':'fixture','size':32,'seed':12345})
    graph=json.loads(app.builds.artifact(built['build_id'],'material.ptex').read_text())
    assert graph['seed_int']==12345 and 'seed' not in graph
