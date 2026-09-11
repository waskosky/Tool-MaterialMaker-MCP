"""One application service used by the browser and MCP adapters."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import threading
from mm_mcp.config import load_config, require_valid
from mm_mcp.catalog_builder import build_catalog
from mm_mcp.core import ServiceError, atomic_json, digest, identifier, finite, resolution
from mm_mcp.validator import validate_graph
from mm_mcp.transactions import GraphStore
from mm_mcp.recipes import RecipeLibrary, variations, bind_world_context
from mm_mcp.composition import compose_layers
from mm_mcp.builds import BuildStore, TARGETS
from mm_mcp.jobs import JobQueue
from mm_mcp.thumbnails import ThumbnailStore
from mm_mcp.artifacts import contact_sheet, image_metrics
from mm_mcp.policy import graph_dependencies, code_hashes

class MaterialService:
    def __init__(self,cfg=None,catalog=None,*,render_fn=None,blender_fn=None):
        self._config_lock=threading.RLock()
        self._build_running=False
        self._native_verified=False
        self._last_render_error=None
        self.cfg=cfg or load_config()
        self.catalog=catalog if catalog is not None else build_catalog(self.cfg.nodes_dir)
        self.root=Path(getattr(self.cfg,'workspace_dir','') or Path(self.cfg.output_dir)/'workspace').resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.graphs=GraphStore(self.root,self.catalog)
        self.recipes=RecipeLibrary(self.cfg.cookbook_dir,self.root/'recipes',self.catalog)
        self.builds=BuildStore(self.root/'builds',self.cfg,self.catalog)
        self.thumbnails=ThumbnailStore(self.root,self.builds,self._project_origin)
        self.render_fn=render_fn
        from mm_mcp.blender.service import BlenderService
        self.blender=BlenderService(self,runner=blender_fn)
        self.jobs=JobQueue(self.root,self._job)
        # Recover persisted work for both MCP and browser clients, including a
        # queue already too full to accept another submission after a restart.
        self.jobs.start()
    def _job(self,request,cancel=None):
        if isinstance(request,dict) and request.get('kind')=='blender':
            if set(request)!={'kind','request'}:
                raise ServiceError('UNKNOWN_FIELDS','Unknown Blender job fields.')
            return self.blender.execute(request['request'],cancel=cancel)
        return self.build(request,cancel=cancel)
    def capabilities(self):
        try:
            require_valid(self.cfg); native=True; reason=None
        except (OSError,ValueError) as exc:
            native=False; reason=str(exc)
        if self.render_fn is not None:
            native=False; reason='Injected test renderer; native Material Maker rendering is not being tested.'
        return {'ok':True,'schema_version':1,'workspace':str(self.root),
                'injected_test_renderer':self.render_fn is not None,
                'catalog_available':bool(self.catalog),'native_render_configured':native,
                'native_render_verified_this_session':self._native_verified,'render_configuration_error':reason,
                'last_render_error':self._last_render_error,
                'features':{'recipe_search':True,'typed_controls':True,'variation_families':True,
                            'world_context_bindings':True,'graph_transactions':True,'persistent_undo':True,
                            'immutable_builds':True,'jobs':True,'cancel_worker_render':True,
                            'layer_composition':bool(self.catalog),'engine_packages':list(TARGETS),
                            'mesh_mask_baking':['coverage','normalized_height','upward_facing'],'automatic_aesthetic_judgment':False,
                            'browser_native_graph_execution':False,'multi_user_hosting':False,
                            'native_paint_strokes':False,'native_global_undo_certified':False},
                'limits':{'max_resolution':getattr(self.cfg,'max_resolution',2048),'max_variants':32,'max_pending_jobs':64}}
    def _validated(self,graph,mode='strict',trusted=False,source_dir=None,*,preserve_unknown_from=None):
        problems=validate_graph(graph,self.catalog,mode=mode,preserve_unknown_from=preserve_unknown_from)
        if any(p['severity']=='error' for p in problems):
            raise ServiceError('VALIDATION_FAILED','Graph validation failed.',problems=problems)
        graph_dependencies(graph,self.cfg,trusted_recipe=trusted,source_dir=source_dir)
        return problems
    def instantiate(self,recipe_id,values=None,title=''):
        graph,provenance=self.recipes.instantiate(recipe_id,values)
        trusted=self._recipe_trust(provenance,graph)
        self._validated(graph,'import',trusted=trusted)
        result=self.graphs.create(graph,title or self.recipes.describe(recipe_id)['display_name'])
        atomic_json(self.root/'provenance'/f"{result['project_id']}.json", {**provenance, 'approved_code_hashes': sorted(code_hashes(graph)) if trusted else []})
        return self.read_project(result['project_id'])
    def _project_origin(self,project_id):
        path=self.root/'provenance'/f"{identifier(project_id)}.json"
        if not path.is_file():
            return {}
        origin=json.loads(path.read_text())
        return {key:origin[key] for key in ('recipe_id','recipe_version') if key in origin}
    def read_project(self,project_id):
        from mm_mcp.play.sliders import derive_sliders
        result=self.graphs.read(project_id)
        result['controls']=derive_sliders(result['graph'],self.catalog)
        result['recipe_id']=self._project_origin(project_id).get('recipe_id')
        return result
    def materials(self,query='',category='',limit=100):
        materials=self.recipes.search(query,category=category,limit=limit)
        for material in materials:
            try:
                material['thumbnail']=self.thumbnails.for_recipe(material['id'],material['recipe_version'])
            except Exception:
                # Optional preview indexing must not make the recipe library unavailable.
                material['thumbnail']=None
        return {'ok':True,'materials':materials}
    def _recipe_trust(self,provenance,graph):
        if provenance['source']=='cookbook':
            return True
        path=self.root/'provenance'/'recipes'/f"{identifier(provenance['recipe_id'])}.json"
        if not path.is_file():
            return False
        approval=json.loads(path.read_text())
        return code_hashes(graph).issubset(set(approval.get('approved_code_hashes',[])))
    def _project_trust(self, project_id, graph):
        """A project may reuse approved code but cannot introduce or alter it."""
        path=self.root/'provenance'/f"{identifier(project_id)}.json"
        if not path.is_file():
            return False
        origin=json.loads(path.read_text())
        approved=origin.get('approved_code_hashes',origin.get('approved_shader_hashes',[]))
        return origin.get('source') in ('cookbook','composition','user') and code_hashes(graph).issubset(set(approved))
    def patch(self,project_id,expected_revision,operations,idempotency_key,dry_run=False):
        def authorize(graph):
            # The transaction already checked structure against its stored
            # baseline. Authorization still rejects new code/dependencies.
            graph_dependencies(graph,self.cfg,trusted_recipe=self._project_trust(project_id,graph))
        return self.graphs.patch(project_id,expected_revision,operations,idempotency_key,
                                 dry_run=dry_run,authorize=authorize)
    def setup_status(self,check=False):
        from mm_mcp.setup import setup_status
        return setup_status(self,check=check)
    def configure_native(self,values):
        from mm_mcp.setup import configure_native
        return configure_native(self,values)
    def verify_native(self):
        from mm_mcp.setup import verify_native
        return verify_native(self)
    def build(self,request,cancel=None):
        # Reconfiguration must neither swap a build's cfg/catalog nor replace
        # its worker. Status reads deliberately do not acquire this long lock.
        with self._config_lock:
            self._build_running=True
            try:
                return self._build(request,cancel)
            finally:
                self._build_running=False
    def _build(self,request,cancel=None):
        if not isinstance(request,dict):
            raise ServiceError('REQUEST_TYPE','Build request must be an object.')
        unknown=set(request)-{'material_id','recipe_id','project_id','revision','graph','values','size','target','seed','physical_size_m','force','source_dir'}
        if unknown:
            raise ServiceError('UNKNOWN_FIELDS','Unknown build request fields.',fields=sorted(unknown))
        sources=sum(bool(request.get(k)) for k in ('graph','project_id'))+bool(request.get('recipe_id') or request.get('material_id'))
        if sources!=1:
            raise ServiceError('BUILD_SOURCE','Provide exactly one of recipe_id/material_id, project_id, or graph.')
        if 'recipe_id' in request and 'material_id' in request:
            raise ServiceError('BUILD_SOURCE','Use recipe_id or its legacy material_id alias, not both.')
        if 'source_dir' in request and not request.get('graph'):
            raise ServiceError('BUILD_SOURCE','source_dir is only supported for raw graph builds.')
        if type(request.get('force',False)) is not bool:
            raise ServiceError('REQUEST_TYPE','force must be boolean.')
        if 'values' in request and not isinstance(request['values'],dict):
            raise ServiceError('REQUEST_TYPE','values must be an object.')
        trusted=False; values=request.get('values') or {}; provenance={}
        recipe_id=request.get('recipe_id',request.get('material_id'))
        if recipe_id:
            graph,provenance=self.recipes.instantiate(recipe_id,values)
            trusted=self._recipe_trust(provenance,graph); name=recipe_id
        elif request.get('project_id'):
            project=self.graphs.read(request['project_id'])
            if type(request.get('revision')) is not int or request.get('revision')!=project['revision']:
                raise ServiceError('REVISION_CONFLICT','Build requires the current project revision.',actual_revision=project['revision'])
            graph=project['graph']; name=project['project_id']
            provenance={**self._project_origin(name),'project_id':name,'revision':project['revision']}
            if values:
                from mm_mcp.play.sliders import apply_values
                graph=apply_values(graph,values,strict=True,catalog=self.catalog)
            trusted=self._project_trust(name,graph)
        else:
            graph=request['graph']; name='custom'
            if values:
                from mm_mcp.play.sliders import apply_values
                graph=apply_values(graph,values,strict=True,catalog=self.catalog)
        source_dir=request.get('source_dir')
        self._validated(graph,'import' if trusted else 'strict',trusted,source_dir=source_dir)
        if self.render_fn is None:
            require_valid(self.cfg)
        try:
            result=self.builds.build(graph,material_id=name,values=values,size=request.get('size',512),
                                     target=request.get('target','generic'),seed=request.get('seed'),
                                     physical_size_m=request.get('physical_size_m',1),provenance=provenance,
                                     trusted_recipe=trusted,render_fn=self.render_fn,cancel=cancel,
                                     force=request.get('force',False),source_dir=source_dir)
        except Exception as exc:
            native_failures={'RENDER_FAILED','IMAGE_FORMAT','IMAGE_LIMIT','IMAGE_DIMENSIONS','INVALID_IMAGE',
                             'DUPLICATE_CHANNEL','MISSING_CHANNELS','NO_IMAGES','TOOL_CHANGED'}
            if self.render_fn is None and getattr(exc,'code',None) in native_failures:
                self._last_render_error=str(exc)
            raise
        if (self.render_fn is None and result.get('ok') is True and result.get('cached') is False
                and result.get('manifest',{}).get('renderer_kind')=='native_material_maker'):
            self._native_verified=True
            self._last_render_error=None
        try:
            if result.get('build_id'):
                self.thumbnails.record(result['build_id'])
        except Exception:
            logging.getLogger(__name__).warning('Completed build could not be indexed for previews.')
        return result
    def family(self,recipe_id,count=6,seed=1,ranges=None,locked=None,values=None,build=False,size=256,target='generic',physical_size_m=1):
        resolution(size,getattr(self.cfg,'max_resolution',2048))
        if target not in TARGETS:
            raise ServiceError('TARGET','Unknown target profile.',targets=list(TARGETS))
        if not finite(physical_size_m) or not 0<physical_size_m<=100000:
            raise ServiceError('PHYSICAL_SCALE','physical_size_m must be positive and finite.')
        if type(build) is not bool:
            raise ServiceError('REQUEST_TYPE','build must be boolean.')
        graph,origin=self.recipes.instantiate(recipe_id,values)
        ranges=self.recipes.resolve_controls(recipe_id,ranges or {})
        locked=list(self.recipes.resolve_controls(recipe_id,{key:True for key in locked or []}))
        values=self.recipes.resolve_controls(recipe_id,values or {})
        candidates=variations(graph,self.catalog,count=count,seed=seed,ranges=ranges,locked=locked,base_values=values)
        jobs=self.jobs.submit_many([{'recipe_id':recipe_id,'values':c['values'],'size':size,
                                    'target':target,'physical_size_m':physical_size_m} for c in candidates]) if build else []
        result=[]
        for index,c in enumerate(candidates):
            item={k:v for k,v in c.items() if k!='graph'}
            if build:
                item['job']=jobs[index]
            result.append(item)
        return {'ok':True,'recipe_id':recipe_id,'origin':origin,'candidates':result}
    def world_context(self,recipe_id,context,bindings,locked=None,values=None):
        graph,origin=self.recipes.instantiate(recipe_id,values)
        import copy
        bindings=copy.deepcopy(bindings)
        for binding in bindings:
            binding['control']=next(iter(self.recipes.resolve_controls(recipe_id,{binding['control']:0})))
        locked=list(self.recipes.resolve_controls(recipe_id,{key:True for key in locked or []}))
        result=bind_world_context(graph,self.catalog,context,bindings,locked=locked)
        return {'ok':True,'origin':origin,**result}
    def compare(self,build_ids,channel='albedo'):
        if not isinstance(build_ids,list) or not 1<=len(build_ids)<=32:
            raise ServiceError('COMPARE_LIMIT','Compare 1–32 completed builds.')
        identifier(channel)
        paths=[]; labels=[]; stats=[]
        for bid in build_ids:
            manifest=self.builds.get(bid)
            entry=next((f for f in manifest['files'] if f.get('channel')==channel),None)
            if entry is None:
                raise ServiceError('CHANNEL_MISSING',f'{bid} has no {channel}.')
            p=self.builds.artifact(bid,entry['name']); paths.append(p)
            labels.append(manifest['material_id']); stats.append({'build_id':bid,**image_metrics(p)})
        comparison_id='c_'+digest({'build_ids':build_ids,'channel':channel})
        dest=self.root/'comparisons'; dest.mkdir(exist_ok=True)
        image=dest/(comparison_id+'.png'); contact_sheet(paths,image,labels)
        return {'ok':True,'comparison_id':comparison_id,'image':str(image),'metrics':stats,
                'warning':'Contact sheet shows channel images, not an aesthetic ranking or engine-lighting test.'}
    def save_recipe(self,project_id,name,metadata=None,guide=''):
        project=self.graphs.read(project_id)
        graph=project['graph']
        self._validated(graph,trusted=self._project_trust(project_id,graph),preserve_unknown_from=graph)
        result=self.recipes.save(name,graph,metadata,guide)
        # Approval is service-owned and separate from caller-supplied recipe metadata.
        atomic_json(self.root/'provenance'/'recipes'/f"{result['id']}.json",
                    {'project_id':project_id,'approved_code_hashes':sorted(code_hashes(graph))})
        try:
            self.thumbnails.reuse_project(project_id,project['graph_hash'],result)
        except Exception:
            logging.getLogger(__name__).warning('Saved recipe %s could not reuse its project preview.',result['id'])
        return result
    def close(self):
        self.jobs.close()

_SERVICES={}; _LOCK=threading.Lock()
def get_service(cfg=None,catalog=None):
    cfg=cfg or load_config()
    root=str(Path(getattr(cfg,'workspace_dir','') or Path(cfg.output_dir)/'workspace').resolve())
    with _LOCK:
        if root not in _SERVICES:
            _SERVICES[root]=MaterialService(cfg,catalog)
        return _SERVICES[root]


def services_active():
    from mm_mcp.activity import recent_or_active
    if recent_or_active():
        return True
    with _LOCK:
        services = list(_SERVICES.values())
    return any(service.jobs.active() for service in services)


def close_services():
    with _LOCK:
        services = list(_SERVICES.values())
        _SERVICES.clear()
    for service in services:
        service.close()


import atexit
atexit.register(close_services)
