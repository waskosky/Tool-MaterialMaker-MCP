"""Legacy render adapter. Browser production uses MaterialService/BuildStore.

The browser never silently takes ownership of the artist's active native tab.
Use explicit authenticated live tools to edit a native session.
"""
from mm_mcp import render
from mm_mcp.core import file_lock
from pathlib import Path

def render_material(applied_graph,changes,size,cfg,outdir,*,material_id=None,headless_render=None,**unused):
    fn=headless_render or render.render
    root=Path(getattr(cfg,'workspace_dir','') or Path(cfg.output_dir)/'workspace')
    with file_lock(root/'.legacy-render.lock'):
        result=fn(applied_graph,size=size,outdir=outdir,basename='material',cfg=cfg)
    return {'ok':result.ok,'path':'batch','images':list(result.images),'error':result.error}
