"""Portable contract fixtures. The synthetic renderer is NOT a native render test."""
import copy
import json
from pathlib import Path
import sys
import pytest
from PIL import Image
from mm_mcp.config import Config
from mm_mcp.service import MaterialService

@pytest.fixture
def catalog():
    params=[{'name':'gain','type':'float','min':0,'max':32,'default':7},
            {'name':'mode','type':'enum','values':['one','two'],'min':0,'max':1},
            {'name':'enabled','type':'boolean'},
            {'name':'tint','type':'color'}, {'name':'ramp','type':'gradient'}]
    return {'source':{'type':'source','inputs':[],'outputs':[{'type':'rgba'}],'parameters':params},
            'filter':{'type':'filter','inputs':[{'name':'in','type':'rgba'}],'outputs':[{'type':'rgba'}],'parameters':[]},
            'blend':{'type':'blend','inputs':[{'name':x,'type':'rgba'} for x in ['s1','s2','a']],
                     'outputs':[{'type':'rgba'}],'parameters':[{'name':'blend_type','type':'enum','values':['normal','multiply']},{'name':'amount','type':'float'}]},
            'material':{'type':'material','inputs':[{'name':n,'type':'rgba'} for n in ['albedo_tex','metallic_tex','roughness_tex','emission_tex','normal_tex','ao_tex','depth_tex']],
                        'outputs':[], 'parameters':[{'name':'metallic','type':'float'},{'name':'roughness','type':'float'},{'name':'albedo_color','type':'color'}]}}

@pytest.fixture
def graph():
    color={'type':'Color','r':.2,'g':.3,'b':.4,'a':1.0}
    ramp={'type':'Gradient','interpolation':1,'points':[dict(color,pos=0),dict(color,pos=1)]}
    values=[7,0,True,color,ramp]
    names=['gain','mode','enabled','tint','ramp']
    sub={'type':'graph','name':'surface','label':'Surface','parameters':{f'param{i}':v for i,v in enumerate(values)},
         'nodes':[{'type':'source','name':'src','parameters':dict(zip(names,values))},
                  {'type':'remote','name':'controls','parameters':{},'widgets':[{'name':f'param{i}','shortdesc':n,'linked_widgets':[{'node':'src','widget':n}]} for i,n in enumerate(names)]},
                  {'type':'ios','name':'gen_inputs','ports':[]},
                  {'type':'ios','name':'gen_outputs','ports':[{'name':'color','type':'rgba'}]}],
         'connections':[{'from':'src','from_port':0,'to':'gen_outputs','to_port':0}]}
    return {'type':'graph','name':'fixture','nodes':[{'type':'material','name':'Material','parameters':{'roughness':.5,'metallic':.25}},sub],
            'connections':[{'from':'surface','from_port':0,'to':'Material','to_port':0},
                           {'from':'surface','from_port':0,'to':'Material','to_port':2}]}

@pytest.fixture
def cfg(tmp_path,graph):
    native=tmp_path/'native';nodes=native/'addons/material_maker/nodes';nodes.mkdir(parents=True)
    output=tmp_path/'output';output.mkdir();workspace=output/'workspace'
    cookbook=tmp_path/'cookbook'/'test';cookbook.mkdir(parents=True)
    (cookbook/'fixture.ptex').write_text(json.dumps(graph));(cookbook/'fixture.md').write_text('Stone fixture with procedural gain controls.')
    return Config(godot_binary=sys.executable,console_binary=sys.executable,project_path=str(native),
                  output_dir=str(output),nodes_dir=str(nodes),examples_dir=str(native/'examples'),
                  live_overlay_dir=str(tmp_path/'overlay'),allowed_roots=[str(output)],
                  cookbook_dir=str(cookbook.parent),workspace_dir=str(workspace),max_resolution=512)

@pytest.fixture
def baker():
    class SyntheticRenderer:
        def __init__(self):self.calls=0
        def __call__(self,graph,*,size,outdir,**kwargs):
            self.calls+=1;directory=Path(outdir);directory.mkdir(parents=True,exist_ok=True)
            gain=next((n.get('parameters',{}).get('param0',7) for n in graph['nodes'] if n.get('name')=='surface'),7)
            paths=[]
            for channel,pixel in [('albedo',(int(gain)%256,80,120)),('orm',(200,128,64)),('normal',(128,128,255))]:
                f=directory/f'material_{channel}.png';Image.new('RGB',(size,size),pixel).save(f);paths.append(str(f))
            return {'ok':True,'images':paths}
    return SyntheticRenderer()

@pytest.fixture
def app(cfg,catalog,baker):
    service=MaterialService(cfg,catalog,render_fn=baker)
    yield service
    service.close()

@pytest.fixture
def http_service(app,cfg,catalog):
    import threading
    from mm_mcp.play.server import make_handler,_StrictThreadingHTTPServer
    token='fixture-token-'+'x'*48
    server=_StrictThreadingHTTPServer(('127.0.0.1',0),make_handler(cfg,catalog,service=app,token=token))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server,token,app
    server.shutdown();server.server_close();thread.join(timeout=3)
