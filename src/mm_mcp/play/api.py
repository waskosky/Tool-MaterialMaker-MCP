"""Compatibility endpoints delegating to the shared material service.

Exports deliberately require a completed build ID. Combining arbitrary current
slider values with whichever PNGs happen to exist is no longer supported.
"""
from mm_mcp.service import get_service
from mm_mcp.core import ServiceError
from mm_mcp.play.sliders import derive_sliders

def list_materials(cfg):
    service=get_service(cfg)
    return {'ok':True,'materials':service.recipes.search(limit=100)}

def get_material(cfg,catalog,name):
    try:
        info=get_service(cfg,catalog).recipes.describe(name)
        return {**info,'name':name,'sliders':info['controls']}
    except ServiceError as exc:
        return exc.result()

def _changes_for(graph,catalog,values):
    known={s['id']:s for s in derive_sliders(graph,catalog)}
    return [{'node':known[k]['binding']['node'],'widget':known[k]['binding']['widget'],'value':v}
            for k,v in values.items() if k in known]

def render_request(cfg,catalog,body,outdir=None,render_fn=None):
    try:
        service=get_service(cfg,catalog)
        if render_fn is not None:
            raise ServiceError('RENDER_ADAPTER','Inject a renderer into MaterialService for tests, not into a public request handler.')
        result=service.build(body)
        return {**result,'path':'batch','maps':result['manifest']['maps']}
    except (ServiceError,OSError,ValueError) as exc:
        return exc.result() if isinstance(exc,ServiceError) else {'ok':False,'error':str(exc)}

def export(cfg,catalog,body,outdir=None):
    try:
        build_id=body.get('build_id')
        if not build_id:
            raise ServiceError('BUILD_ID_REQUIRED','Export requires the completed build_id returned by rendering.')
        return get_service(cfg,catalog).builds.export(build_id),build_id+'.zip'
    except ServiceError as exc:
        return None,str(exc)
