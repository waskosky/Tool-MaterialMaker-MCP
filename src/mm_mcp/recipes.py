"""Searchable versioned recipes, reproducible variation families and context bindings."""
from __future__ import annotations
import copy
import json
import random
import re
from pathlib import Path
from mm_mcp.core import ServiceError, atomic_json, canonical, digest, file_digest, finite, identifier, file_lock, parse_json
from mm_mcp.cookbook import list_cookbook
from mm_mcp.play.sliders import derive_sliders, apply_values, validate_values

class RecipeLibrary:
    def __init__(self, cookbook_dir, user_dir, catalog):
        self.cookbook_dir=cookbook_dir
        self.user_dir=Path(user_dir); self.user_dir.mkdir(parents=True,exist_ok=True)
        self.catalog=catalog
    def _entries(self):
        records=[]
        for e in list_cookbook(self.cookbook_dir):
            records.append((e.name,e.category,Path(e.path),'cookbook'))
        for p in sorted(self.user_dir.glob('*.ptex')):
            records.append(('user.'+p.stem,'user',p,'user'))
        return records
    def find(self, recipe_id):
        identifier(recipe_id,'recipe ID')
        for name,category,path,source in self._entries():
            if name==recipe_id:
                return name,category,path,source
        raise ServiceError('RECIPE_NOT_FOUND',f'Unknown material recipe: {recipe_id}')
    def describe(self, recipe_id, *, include_graph=False):
        name,category,path,source=self.find(recipe_id)
        graph=parse_json(path.read_bytes())
        card=path.with_suffix('.md')
        meta_path=path.with_suffix('.recipe.json')
        metadata=parse_json(meta_path.read_bytes()) if meta_path.exists() else {}
        if not isinstance(metadata, dict):
            raise ServiceError('RECIPE_SCHEMA', 'Recipe metadata must be an object.')
        result={'ok':True,'id':name,'name':name,'category':category,'source':source,
                'recipe_version':digest({'graph':graph,'metadata':metadata}),
                'graph_sha256':file_digest(path),'controls':derive_sliders(graph,self.catalog),
                'metadata':metadata,'guide':card.read_text(encoding='utf-8') if card.exists() else ''}
        specs=result['controls']; aliases={}; used=set()
        for control in specs:
            alias=re.sub(r'[^a-z0-9]+','_',control['label'].lower()).strip('_')
            if not alias or alias in used:
                alias=re.sub(r'[^a-z0-9]+','_',control['id'].lower()).strip('_')
            if alias in used:
                continue
            aliases[alias]=control['id']; used.add(alias)
        explicit=metadata.get('semantic_controls',{})
        known={c['id'] for c in specs}
        if not isinstance(explicit,dict) or any(not isinstance(k,str) or v not in known for k,v in explicit.items()):
            raise ServiceError('RECIPE_SCHEMA','semantic_controls must map aliases to existing control IDs.')
        aliases.update(explicit);result['semantic_controls']=aliases
        if include_graph:
            result['graph']=graph
        return result
    def search(self,query='',category='',limit=30):
        if type(limit) is not int or not 1<=limit<=100:
            raise ServiceError('SEARCH_LIMIT','limit must be 1–100.')
        terms=re.findall(r'[a-z0-9]+',str(query).lower())
        records=[]
        for name,cat,path,source in self._entries():
            if category and category!=cat:
                continue
            card=path.with_suffix('.md')
            text=card.read_text(encoding='utf-8').lower() if card.exists() else ''
            title=(name+' '+cat).lower()
            score=sum(5*title.count(t)+min(3,text.count(t)) for t in terms)
            if terms and score==0:
                continue
            records.append({'id':name,'name':name,'category':cat,'source':source,'score':score})
        return sorted(records,key=lambda e:(-e['score'],e['category'],e['id']))[:limit]
    def instantiate(self,recipe_id,values=None):
        recipe=self.describe(recipe_id,include_graph=True)
        values=self.resolve_controls(recipe_id,values or {},description=recipe)
        graph=apply_values(recipe['graph'],values,strict=True,catalog=self.catalog)
        return graph,{'recipe_id':recipe_id,'recipe_version':recipe['recipe_version'],
                      'source':recipe['source'],'values':copy.deepcopy(values)}
    def resolve_controls(self,recipe_id,values,description=None):
        if not isinstance(values,dict):raise ServiceError('INVALID_PARAMETERS','Control values must be an object.')
        recipe=description or self.describe(recipe_id)
        known={c['id'] for c in recipe['controls']};aliases=recipe['semantic_controls'];resolved={}
        for key,value in values.items():
            target=key if key in known else aliases.get(key)
            if target is None:raise ServiceError('UNKNOWN_CONTROL',f'Unknown control or semantic alias: {key}')
            if target in resolved:raise ServiceError('CONTROL_COLLISION','Two supplied keys address the same control.')
            resolved[target]=copy.deepcopy(value)
        return resolved
    def save(self,name,graph,metadata=None,guide=''):
        identifier(name,'user recipe name')
        if metadata is not None and not isinstance(metadata, dict):
            raise ServiceError('RECIPE_SCHEMA', 'Recipe metadata must be an object.')
        metadata = copy.deepcopy(metadata or {})
        known = {s['id'] for s in derive_sliders(graph, self.catalog)}
        aliases = metadata.get('semantic_controls', {})
        if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) or v not in known for k,v in aliases.items()):
            raise ServiceError('RECIPE_SCHEMA', 'semantic_controls must map names to existing controls.')
        canonical(graph); canonical(metadata)
        if not isinstance(guide,str) or len(guide.encode()) > 1024*1024:
            raise ServiceError('RECIPE_SCHEMA', 'Guide must be text no larger than 1 MiB.')
        path=self.user_dir/(name+'.ptex')
        with file_lock(self.user_dir/'.publish.lock'):
            if path.exists() or path.is_symlink():
                raise ServiceError('RECIPE_EXISTS','Choose a new name; recipe versions are immutable.')
            atomic_json(path.with_suffix('.recipe.json'),metadata)
            path.with_suffix('.md').write_text(guide,encoding='utf-8')
            # Readers discover .ptex files; publish that discoverable entry last.
            atomic_json(path,graph)
        return self.describe('user.'+name)


def variations(graph, catalog, *, count=6, seed=1, ranges=None, locked=None, base_values=None):
    if type(count) is not int or not 1<=count<=32:
        raise ServiceError('VARIATION_LIMIT','count must be 1–32.')
    if type(seed) is not int or not 0<=seed<=2147483647:
        raise ServiceError('SEED_RANGE','Seed must be a nonnegative 31-bit integer.')
    specs=derive_sliders(graph,catalog); by_id={s['id']:s for s in specs}
    base_values=validate_values(specs,base_values or {})
    locked=set(locked or [])
    if not locked<=by_id.keys():
        raise ServiceError('UNKNOWN_CONTROL','A locked control does not exist.')
    ranges=ranges or {}
    for key,bounds in ranges.items():
        if key not in by_id or by_id[key]['kind'] not in ('float','int','enum'):
            raise ServiceError('VARIATION_CONTROL',f'{key} is not a numeric control.')
        if not isinstance(bounds,list) or len(bounds)!=2 or not all(finite(v) for v in bounds) or bounds[0]>bounds[1]:
            raise ServiceError('VARIATION_RANGE',f'{key} needs finite [minimum, maximum].')
    rng=random.Random(seed); result=[]
    for i in range(count):
        values=copy.deepcopy(base_values)
        for key,bounds in ranges.items():
            if key in locked:
                continue
            s=by_id[key]
            if s['kind'] in ('int','enum'):
                import math
                lo,hi=math.ceil(bounds[0]),math.floor(bounds[1])
                if lo>hi:
                    raise ServiceError('VARIATION_RANGE','Integer range contains no integer.')
                values[key]=rng.randint(lo,hi)
            else:
                values[key]=round(rng.uniform(*bounds),6)
        candidate=apply_values(graph,values,strict=True,catalog=catalog)
        # Seed stays explicit and shared unless the user actually varies it. A family
        # of slider edits should not also change hidden structure unpredictably.
        result.append({'index':i,'family_seed':seed,'values':values,'graph_hash':digest(candidate),'graph':candidate})
    return result


def bind_world_context(graph,catalog,context,bindings,*,locked=None):
    """Map named normalized environmental fields into explicitly chosen controls.

    No material is assumed to understand a universal 'wetness' knob. The author
    supplies bindings; physical/simulation properties remain separate metadata.
    """
    if not isinstance(context,dict) or not isinstance(bindings,list) or len(bindings)>64:
        raise ServiceError('CONTEXT_SCHEMA','Provide a context object and at most 64 bindings.')
    locked=set(locked or []); values={}
    for b in bindings:
        try:
            field,control=b['field'],b['control']
            if control in locked:
                continue
            value=context[field]
            if not finite(value) or not 0<=value<=1:
                raise ServiceError('CONTEXT_RANGE',f'{field} must be normalized to zero–one.')
            bounds=b.get('range',[0,1]); exponent=b.get('exponent',1)
            if not isinstance(bounds,list) or len(bounds)!=2 or not all(finite(v) for v in bounds):
                raise ServiceError('CONTEXT_RANGE','Binding range must contain two finite values.')
            if not finite(exponent) or not 0<exponent<=8:
                raise ServiceError('CONTEXT_CURVE','exponent must be positive and no greater than eight.')
            if b.get('invert',False):
                value=1-value
            mapped=bounds[0]+(bounds[1]-bounds[0])*(value**exponent)
            if b.get('integer',False):
                mapped=round(mapped)
            if control in values:
                raise ServiceError('CONTEXT_COLLISION',f'Multiple fields map to {control}; author one combined field instead.')
            values[control]=mapped
        except (TypeError,KeyError) as exc:
            raise ServiceError('CONTEXT_SCHEMA','Binding requires existing field and control names.') from exc
    return {'values':values,'graph':apply_values(graph,values,strict=True,catalog=catalog),
            'context':copy.deepcopy(context),'bindings':copy.deepcopy(bindings),
            'physics_inferred':False}
