import copy
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from mm_mcp.core import ServiceError, parse_json, resolution, identifier
from mm_mcp.validator import validate_graph
from mm_mcp.transactions import GraphStore, apply_patch
from mm_mcp.play.sliders import derive_sliders,apply_values,resolve_node
from mm_mcp.recipes import variations,bind_world_context
from mm_mcp.composition import compose_layers

@pytest.mark.parametrize('raw',['{"a":1,"a":2}','{"v":NaN}','{"v":Infinity}','[','{"x":1e9999}'])
def test_noncanonical_json_rejected(raw):
    with pytest.raises(ServiceError):parse_json(raw)

@pytest.mark.parametrize('value',[0,31,33,513,4096,True,256.0,-1,'256'])
def test_resolution_rejects_invalid(value):
    with pytest.raises(ServiceError):resolution(value,512)

@pytest.mark.parametrize('value',['../x','a/b','a\\b','a:b','a..b','',None,'x'*129])
def test_identifiers_reject_escaping(value):
    with pytest.raises(ServiceError):identifier(value)

def errors(graph,catalog):return [p for p in validate_graph(graph,catalog,mode='strict') if p['severity']=='error']

def test_fixture_valid(graph,catalog):assert errors(graph,catalog)==[]

@pytest.mark.parametrize('value',['bad',None,True,[],float('nan'),float('inf')])
def test_numeric_parameter_types(graph,catalog,value):
    resolve_node(graph,'surface/src')['parameters']['gain']=value
    assert errors(graph,catalog)

@pytest.mark.parametrize('value',[.5,-1,2,True,'0'])
def test_enum_parameter_types(graph,catalog,value):
    resolve_node(graph,'surface/src')['parameters']['mode']=value
    assert errors(graph,catalog)

@pytest.mark.parametrize('port',[-1,.5,'0',True,None,999999])
def test_malformed_ports_are_diagnostics(graph,catalog,port):
    graph['connections'][0]['to_port']=port
    assert errors(graph,catalog)

def test_duplicate_names(graph,catalog):
    graph['nodes'].append(copy.deepcopy(graph['nodes'][0]));assert errors(graph,catalog)

def test_duplicate_input_and_cycles(graph,catalog):
    graph['connections'].append(copy.deepcopy(graph['connections'][0]));assert errors(graph,catalog)
    g={'nodes':[{'name':'a','type':'filter'},{'name':'b','type':'filter'}],
       'connections':[{'from':'a','to':'b','from_port':0,'to_port':0},{'from':'b','to':'a','from_port':0,'to_port':0}]}
    assert any(p['code']=='CYCLE' for p in errors(g,catalog))

def test_import_tolerance_is_separate(graph,catalog):
    resolve_node(graph,'surface/src')['parameters']['obsolete']=3
    assert errors(graph,catalog)
    assert not [p for p in validate_graph(graph,catalog,mode='import') if p['severity']=='error']

def test_controls_exposed_address_and_fanout(graph,catalog):
    spec=derive_sliders(graph,catalog)[0]
    assert spec['binding']=={'node':'surface','widget':'param0'}
    resolve_node(graph,'surface')['nodes'].append({'name':'extra','type':'source','parameters':{'gain':2}})
    resolve_node(graph,'surface/controls')['widgets'][0]['linked_widgets'].append({'node':'extra','widget':'gain'})
    changed=apply_values(graph,{'surface/param0':13},strict=True,catalog=catalog)
    for path in ['surface/src','surface/extra']:assert resolve_node(changed,path)['parameters']['gain']==13
    assert resolve_node(changed,'surface')['parameters']['param0']==13
    assert resolve_node(changed,'surface/controls')['parameters']['param0']==13
    assert resolve_node(graph,'surface/src')['parameters']['gain']==7

@pytest.mark.parametrize('key,value',[('unknown',1),('surface/param0','7'),('surface/param1',.5),('surface/param2',1),('surface/param3',{}),('surface/param4',{})])
def test_control_types(graph,catalog,key,value):
    with pytest.raises(ServiceError):apply_values(graph,{key:value},strict=True,catalog=catalog)

def test_persistent_atomic_patches_and_retry(app):
    project=app.instantiate('fixture');pid=project['project_id'];ops=[{'op':'set_controls','values':{'surface/param0':13}}]
    result=app.patch(pid,0,ops,'change-001')
    assert result['revision']==1
    assert app.patch(pid,0,ops,'change-001')==result
    with pytest.raises(ServiceError,match='different request'):app.patch(pid,0,[{'op':'set_label','path':'surface','label':'No'}],'change-001')
    with pytest.raises(ServiceError):app.patch(pid,0,ops,'stale-001')
    reopened=GraphStore(app.root,app.catalog)
    assert resolve_node(reopened.read(pid)['graph'],'surface')['parameters']['param0']==13

def test_failed_batch_commits_nothing(app):
    p=app.instantiate('fixture');before=app.graphs.read(p['project_id'])
    with pytest.raises(ServiceError):app.patch(p['project_id'],0,[{'op':'set_controls','values':{'surface/param0':13}},{'op':'not_supported'}],'bad-batch')
    assert app.graphs.read(p['project_id'])==before

def test_dry_run_and_policy_denial_leave_no_changes(app):
    p=app.instantiate('fixture');pid=p['project_id'];ops=[{'op':'set_controls','values':{'surface/param0':13}}]
    planned=app.patch(pid,0,ops,'dry-run-1',True)
    assert planned['status']=='planned' and app.graphs.read(pid)==p
    with pytest.raises(ServiceError):
        app.patch(pid,0,[{'op':'add_node','name':'code','node':{'type':'shader','shader_model':{'parameters':[],'inputs':[],'outputs':[],'code':'injected'}}}],'shader-1')
    assert app.graphs.read(pid)==p

def test_concurrent_edits_one_wins(app):
    p=app.instantiate('fixture');barrier=threading.Barrier(2)
    def edit(value):
        barrier.wait()
        try:return app.patch(p['project_id'],0,[{'op':'set_controls','values':{'surface/param0':value}}],f'concurrent-{value}')
        except ServiceError as exc:return exc.result()
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(edit,[8,9]))
    assert sum(bool(r['ok']) for r in results)==1
    assert app.graphs.read(p['project_id'])['revision']==1

def test_undo_redo_and_named_snapshot(app):
    p=app.instantiate('fixture');pid=p['project_id'];app.graphs.snapshot(pid,'base')
    app.patch(pid,0,[{'op':'set_controls','values':{'surface/param0':13}}],'edit-001')
    undo=app.graphs.history_step(pid,1,'undo');assert undo['revision']==2
    assert resolve_node(undo['graph'],'surface')['parameters']['param0']==7
    redo=app.graphs.history_step(pid,2,'redo');assert redo['revision']==3
    restored=app.graphs.restore(pid,'base',3);assert restored['revision']==4
    with pytest.raises(ServiceError):app.graphs.snapshot(pid,'base')

def test_seeded_families_and_locked_controls(graph,catalog):
    args={'count':6,'seed':17,'ranges':{'surface/param0':[5,15],'surface/param1':[0,1]},'locked':['surface/param1']}
    a=variations(graph,catalog,**args);b=variations(graph,catalog,**args)
    assert a==b and len({x['graph_hash'] for x in a})==6
    assert all(resolve_node(x['graph'],'surface/src')['parameters']['mode']==0 for x in a)

def test_explicit_world_context(graph,catalog):
    r=bind_world_context(graph,catalog,{'wetness':.25},[{'field':'wetness','control':'surface/param0','range':[4,20]}])
    assert r['values']['surface/param0']==8 and r['physics_inferred'] is False
    with pytest.raises(ServiceError):bind_world_context(graph,catalog,{'wetness':2},[{'field':'wetness','control':'surface/param0'}])

def test_editable_composition(graph,catalog):
    r=compose_layers(graph,graph,{'name':'mask','type':'source','parameters':{'gain':.5}},catalog,channels=['albedo_tex','roughness_tex'])
    assert not errors(r['graph'],catalog)
    assert {'base','coating','layer_mask'}<={n['name'] for n in r['graph']['nodes']}
    assert r['normal_source']=='base' and r['warnings']
