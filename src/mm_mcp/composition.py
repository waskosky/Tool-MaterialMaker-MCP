"""Editable two-layer graph composition through an explicit shared grayscale mask.

Each material remains a nested native graph. This uses native blend nodes for
selected scalar/color material channels. Normal vectors are NOT naively blended:
normal source is selected explicitly; normal reorientation is a future backend.
"""
import copy
from mm_mcp.core import ServiceError
from mm_mcp.graph import find_material_node
from mm_mcp.validator import validate_graph


def compose_layers(base, coating, mask, catalog, channels=None, normal_source='base'):
    if normal_source not in ('base','coating'):
        raise ServiceError('NORMAL_SOURCE','normal_source must be base or coating.')
    if 'material' not in catalog or 'blend' not in catalog:
        raise ServiceError('CATALOG_REQUIRED','The material and blend catalog definitions are required.')
    inputs=catalog['material'].get('inputs',[])
    names=[p.get('name') for p in inputs]
    channels=channels or ['albedo_tex','metallic_tex','roughness_tex']
    allowed={'albedo_tex','metallic_tex','roughness_tex','ao_tex','depth_tex','emission_tex'}
    if not set(channels)<=allowed or not set(channels)<=set(names):
        raise ServiceError('LAYER_CHANNEL','Unsupported blend channel; normals require explicit source selection.')
    blend_inputs=[p.get('name') for p in catalog['blend'].get('inputs',[])]
    if blend_inputs!=['s1','s2','a']:
        raise ServiceError('CATALOG_INCOMPATIBLE','Native blend interface is not the supported s1/s2/a interface.')
    def extract(graph,name):
        graph=copy.deepcopy(graph); material=find_material_node(graph); outputs=[]; edges=[]
        incoming={c['to_port']:c for c in graph.get('connections',[]) if c['to']==material['name']}
        channel_ports={}
        for index,c in sorted(incoming.items()):
            if index>=len(names):
                raise ServiceError('MATERIAL_PORT','Material input does not exist in the catalog.')
            out_index=len(outputs); channel_ports[names[index]]=out_index
            typ=inputs[index].get('type','rgba')
            outputs.append({'name':names[index],'type':typ})
            edges.append({'from':c['from'],'from_port':c['from_port'],'to':'gen_outputs','to_port':out_index})
        graph['nodes']=[n for n in graph['nodes'] if n['name']!=material['name']]
        graph['connections']=[c for c in graph.get('connections',[]) if c['to']!=material['name'] and c['from']!=material['name']]+edges
        graph['nodes'] += [{'name':'gen_inputs','type':'ios','ports':[]},
                           {'name':'gen_outputs','type':'ios','ports':outputs}]
        graph.update({'name':name,'type':'graph','label':name.title(),'node_position':{'x':0,'y':0}})
        return graph,channel_ports,material
    left,lp,mat=extract(base,'base'); right,rp,coat_mat=extract(coating,'coating')
    if mat.get('parameters',{}) != coat_mat.get('parameters',{}):
        raise ServiceError('MATERIAL_SCALARS','Layer output parameters differ. Normalize material scalar multipliers and flags explicitly before composition.')
    mask_node=copy.deepcopy(mask)
    if not isinstance(mask_node,dict) or not isinstance(mask_node.get('type'),str):
        raise ServiceError('MASK_NODE','Supply a native single-output grayscale mask node or subgraph.')
    mask_node['name']='layer_mask'
    selected={name for name in channels}
    for name in selected:
        if name not in lp or name not in rp:
            raise ServiceError('LAYER_INPUT_MISSING',f'Both layers must expose connected {name}; scalar defaults are not silently invented.')
    out={'type':'graph','name':'composed_material','nodes':[copy.deepcopy(mat),left,right,mask_node],'connections':[]}
    for i,name in enumerate(names):
        if name in selected:
            blend_name='mix_'+name
            out['nodes'].append({'name':blend_name,'type':'blend','parameters':{'blend_type':0,'amount':1},
                                 'node_position':{'x':400,'y':i*150}})
            out['connections'] += [{'from':'base','from_port':lp[name],'to':blend_name,'to_port':0},
                                   {'from':'coating','from_port':rp[name],'to':blend_name,'to_port':1},
                                   {'from':'layer_mask','from_port':0,'to':blend_name,'to_port':2},
                                   {'from':blend_name,'from_port':0,'to':mat['name'],'to_port':i}]
        else:
            source=normal_source if name=='normal_tex' else 'base'; ports=lp if source=='base' else rp
            if name in ports:
                out['connections'].append({'from':source,'from_port':ports[name],'to':mat['name'],'to_port':i})
    problems=validate_graph(out,catalog,mode='strict')
    if any(p['severity']=='error' for p in problems):
        raise ServiceError('COMPOSITION_INVALID','Composed graph failed validation.',problems=problems)
    return {'graph':out,'warnings':['Normal maps are selected, not blended. Review height interactions and material scalar multipliers.'],
            'normal_source':normal_source,'blended_channels':channels}
