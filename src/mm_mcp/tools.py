"""Transport adapter for the shared material service; no renderer logic lives here."""
from __future__ import annotations
import functools
import base64
import hashlib
import io
import json
from typing import Literal
from pathlib import Path
from PIL import Image as PILImage
from mm_mcp.core import ServiceError, atomic_json, file_digest, identifier
from mm_mcp.service import get_service
from mm_mcp.composition import compose_layers
from mm_mcp.policy import code_hashes


def safe(fn):
    """Keep the public signature intact for MCP schema generation."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            import sys
            server=sys.modules.get("mm_mcp.server")
            if server is not None and hasattr(server,"_touch_idle"):
                server._touch_idle()
            from mm_mcp.activity import operation
            with operation():
                return fn(*args, **kwargs)
        except ServiceError as exc:
            return exc.result()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {"ok": False, "code": "INVALID_REQUEST", "error": str(exc)}
    return wrapped

@safe
def material_capabilities() -> dict:
    """Discover supported features and native configuration before doing work."""
    return get_service().capabilities()

@safe
def material_recipe_search(query: str = "", category: str = "", limit: int = 30) -> dict:
    """Search friendly recipe names, metadata and guide text using lexical matching."""
    return {"ok": True, "recipes": get_service().materials(query, category=category, limit=limit)['materials']}

@safe
def material_recipe_describe(recipe_id: str, include_graph: bool = False) -> dict:
    """Inspect an editable recipe, version, typed controls and authoring notes."""
    return get_service().recipes.describe(recipe_id, include_graph=include_graph)

@safe
def material_project_create(recipe_id: str, values: dict | None = None, title: str = "") -> dict:
    """Instantiate a recipe as a persistent shared project without modifying native editor tabs."""
    return get_service().instantiate(recipe_id, values, title)

@safe
def material_project_import(graph: dict, title: str = "Imported material") -> dict:
    """Import a validated graph. New inline shaders require explicit operator approval."""
    app=get_service(); app._validated(graph)
    return app.graphs.create(graph,title)

@safe
def material_project_list() -> dict:
    """List the browser/MCP workspace projects, including their current revisions."""
    return {"ok":True,"projects":get_service().graphs.list()}

@safe
def material_project_get(project_id: str) -> dict:
    """Read the complete graph, current revision, hash and exposed controls."""
    return get_service().read_project(project_id)

@safe
def material_project_patch(project_id: str, expected_revision: int, operations: list,
                           idempotency_key: str, dry_run: bool = False) -> dict:
    """Atomically validate and apply a patch. Use a new key for new intent, the same key for an exact retry."""
    return get_service().patch(project_id,expected_revision,operations,idempotency_key,dry_run)

@safe
def material_project_history(project_id: str, expected_revision: int, direction: str) -> dict:
    """Undo or redo a workspace transaction; the project revision still increases."""
    return get_service().graphs.history_step(project_id,expected_revision,direction)

@safe
def material_project_snapshot(project_id: str, name: str) -> dict:
    """Create an immutable named recovery snapshot in the persistent workspace."""
    return get_service().graphs.snapshot(project_id,name)

@safe
def material_project_restore(project_id: str, name: str, expected_revision: int) -> dict:
    """Restore a named snapshot as a new, undoable revision."""
    return get_service().graphs.restore(project_id,name,expected_revision)

@safe
def material_build(request: dict) -> dict:
    """Build a recipe_id or project_id+revision, with size/target/values/seed/physical_size_m. Prefer jobs for long bakes."""
    return get_service().build(request)

@safe
def material_job_submit(request: dict) -> dict:
    """Queue a bounded build. A project revision conflict fails instead of baking newer unintended edits."""
    return get_service().jobs.submit(request)

@safe
def material_job_get(job_id: str) -> dict:
    """Read queued, running, complete, failed or cancelled status and any verified build result."""
    return get_service().jobs.get(job_id)

@safe
def material_job_cancel(job_id: str) -> dict:
    """Request cooperative cancellation of the worker-owned bake, not an artist's editor process."""
    return get_service().jobs.cancel(job_id)

@safe
def material_build_get(build_id: str) -> dict:
    """Verify artifact hashes and return the immutable completed build manifest."""
    return {"ok":True,"manifest":get_service().builds.get(build_id)}

@safe
def material_build_export(build_id: str) -> dict:
    """Write a verified ZIP into workspace/exports. It contains only that build's exact files."""
    app=get_service(); data=app.builds.export(build_id)
    directory=app.root/'exports';directory.mkdir(exist_ok=True)
    path=directory/(identifier(build_id)+'.zip')
    from mm_mcp.core import file_lock
    with file_lock(directory/'.export.lock'):
        if path.exists():
            if path.is_symlink() or path.read_bytes()!=data:
                raise ServiceError('EXPORT_CONFLICT','An existing export has different bytes; do not overwrite it silently.')
        else:
            import os, tempfile
            fd,temp=tempfile.mkstemp(prefix='.export-',dir=directory)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(data);f.flush();os.fsync(f.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    return {"ok":True,"build_id":build_id,"path":str(path),"bytes":len(data),"sha256":file_digest(path)}

@safe
def material_variation_family(recipe_id: str, count: int = 6, seed: int = 1,
                              ranges: dict | None = None, locked: list | None = None,
                              values: dict | None = None, build: bool = False,
                              size: int = 256, target: str = "generic", physical_size_m: float = 1) -> dict:
    """Create deterministic recipe variations from explicit ranges, preserving locked controls."""
    return get_service().family(recipe_id,count,seed,ranges,locked,values,build,size,target,physical_size_m)

@safe
def material_world_context(recipe_id: str, context: dict, bindings: list,
                           locked: list | None = None, values: dict | None = None) -> dict:
    """Apply explicit normalized environment-to-control mappings. No physical properties are inferred."""
    return get_service().world_context(recipe_id,context,bindings,locked,values)

@safe
def material_compose_layers(base_recipe_id: str, coating_recipe_id: str, mask: dict,
                            channels: list | None = None, normal_source: str = "base") -> dict:
    """Compose two editable recipes through a native scalar mask; normals are selected, not linearly blended."""
    app=get_service()
    base,bp=app.recipes.instantiate(base_recipe_id)
    coat,cp=app.recipes.instantiate(coating_recipe_id)
    app._validated(base,'import',app._recipe_trust(bp,base));app._validated(coat,'import',app._recipe_trust(cp,coat))
    app._validated({'type':'graph','nodes':[mask],'connections':[]})
    result=compose_layers(base,coat,mask,app.catalog,channels=channels,normal_source=normal_source)
    graph=result['graph']; permitted=code_hashes(base)|code_hashes(coat)
    trusted=code_hashes(graph).issubset(permitted)
    app._validated(graph,trusted=trusted)
    project=app.graphs.create(graph,'Layered '+base_recipe_id)
    atomic_json(app.root/'provenance'/f"{project['project_id']}.json",
                {'source':'composition','base':bp,'coating':cp,'approved_code_hashes':sorted(permitted)})
    return {**project,'warnings':result.get('warnings',[])}

@safe
def material_recipe_save(project_id: str, name: str, metadata: dict | None = None, guide: str = "") -> dict:
    """Save a new personal recipe without overwriting the cookbook or existing recipes."""
    return get_service().save_recipe(project_id,name,metadata,guide)

@safe
def material_compare(build_ids: list, channel: str = "albedo") -> dict:
    """Create a channel contact sheet and technical metrics; this is not a visual-quality score."""
    return get_service().compare(build_ids,channel)

@safe
def material_preview_image(build_id: str, channel: str = "albedo", max_size: int = 768):
    """Return actual bounded image content to the assistant, not merely a filesystem path."""
    if type(max_size) is not int or not 32<=max_size<=1024:
        raise ServiceError('PREVIEW_LIMIT','max_size must be between 32 and 1024.')
    app=get_service();manifest=app.builds.get(build_id)
    entry=next((f for f in manifest['files'] if f.get('channel')==channel),None)
    if entry is None:raise ServiceError('CHANNEL_MISSING','No such channel exists in this completed build.')
    with PILImage.open(app.builds.artifact(build_id,entry['name'])) as image:
        image.thumbnail((max_size,max_size));out=io.BytesIO();image.save(out,format='PNG')
    from mcp.server.mcpserver.utilities.types import Image
    return Image(data=out.getvalue(),format='png')

@safe
def material_mesh_masks(obj_path: str, size: int = 256, up_axis: str = "y") -> dict:
    """Bake coverage, normalized height and upward-facing masks from an approved triangle OBJ with unique UVs."""
    from mm_mcp.mesh_masks import bake_mesh_masks
    return bake_mesh_masks(obj_path,get_service().cfg,size=size,up_axis=up_axis)


@safe
def blender_capabilities() -> dict:
    """Inspect optional fixed Blender operations and upload/render limits."""
    return get_service().blender.capabilities()


@safe
def blender_mesh_upload(name: str, data_base64: str) -> dict:
    """Admit a static, embedded GLB at most 4 MiB; return its content identity."""
    return get_service().blender.upload(name=name,data_base64=data_base64)


@safe
def blender_job_submit(operation: Literal['inspect','preview','bake'], build_id: str | None = None,
                       mesh_id: str | None = None, specimen: Literal['sphere','beveled_cube','plane'] | None = None,
                       resolution: Literal[128,256,512] = 256, unwrap: bool = False, uv_scale: float = 1) -> dict:
    """Queue a fixed Blender operation on an exact build and specimen or admitted GLB. Unwrap explicitly creates a derivative."""
    body={key:value for key,value in locals().items() if value is not None}
    return get_service().blender.submit(body)


@safe
def blender_job_get(job_id: str) -> dict:
    """Read a Blender job from the shared persistent Workshop queue."""
    return get_service().jobs.get(job_id)


@safe
def blender_job_cancel(job_id: str) -> dict:
    """Cancel queued/running work and clean up its bounded worker process."""
    return get_service().jobs.cancel(job_id)


@safe
def blender_result_get(result_id: str) -> dict:
    """Verify every immutable Blender artifact and return the exact input receipt."""
    return {'ok':True,'manifest':get_service().blender.get(result_id)}


@safe
def blender_result_file(result_id: str, name: str) -> dict:
    """Download one verified, inventory-listed Blender artifact as bounded base64 bytes."""
    data=get_service().blender.artifact(result_id,name).read_bytes()
    return {'ok':True,'result_id':result_id,'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'data_base64':base64.b64encode(data).decode()}


@safe
def blender_result_export(result_id: str) -> dict:
    """Write a verified self-contained ZIP into the managed exports directory."""
    app=get_service();data=app.blender.export(result_id)
    directory=app.root/'exports';directory.mkdir(exist_ok=True)
    path=directory/(identifier(result_id)+'.zip')
    from mm_mcp.core import file_lock
    with file_lock(directory/'.export.lock'):
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.read_bytes()!=data:
                raise ServiceError('EXPORT_CONFLICT','Existing export differs from its immutable result.')
        else:
            import os,tempfile
            fd,temp=tempfile.mkstemp(prefix='.export-',dir=directory)
            try:
                with os.fdopen(fd,'wb') as output:
                    output.write(data);output.flush();os.fsync(output.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    return {'ok':True,'result_id':result_id,'path':str(path),'bytes':len(data),'sha256':file_digest(path)}

TOOLS=[material_capabilities,material_recipe_search,material_recipe_describe,material_project_create,
       material_project_import,material_project_list,material_project_get,material_project_patch,
       material_project_history,material_project_snapshot,material_project_restore,material_build,
       material_job_submit,material_job_get,material_job_cancel,material_build_get,material_build_export,
       material_variation_family,material_world_context,material_compose_layers,material_recipe_save,
       material_compare,material_preview_image,material_mesh_masks,
       blender_capabilities,blender_mesh_upload,blender_job_submit,blender_job_get,blender_job_cancel,
       blender_result_get,blender_result_file,blender_result_export]

def register(mcp):
    for fn in TOOLS:
        mcp.tool(structured_output=False if fn is material_preview_image else None)(fn)
    @mcp.resource('build://{build_id}/manifest')
    def build_manifest(build_id: str) -> str:
        return json.dumps(get_service().builds.get(build_id),indent=2)
