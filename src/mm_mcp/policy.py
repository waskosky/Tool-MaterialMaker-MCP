"""Local-workspace policy. This is not an operating-system shader sandbox."""
from pathlib import Path
import re
from mm_mcp.core import ServiceError, file_digest, identifier, digest, MAX_DEPTH
from mm_mcp.paths import ensure_within_roots, PathNotAllowed

FILE_KEYS = {'image', 'image_path', 'file_name', 'filename', 'file_path', 'path', 'texture_path', 'model_path'}

def graph_dependencies(graph: dict, cfg, *, trusted_recipe: bool = False) -> list[dict]:
    """Reject injected shader definitions by default and bound explicit file references.

    Built-in recipes may contain inline shaders. Trust is granted by the service
    loading its own recipe, never by a client-supplied boolean on an HTTP request.
    Unsupported URI schemes are rejected. Native custom exporters remain trusted code.
    """
    result = {}
    roots = list(cfg.allowed_roots or [cfg.output_dir])
    if cfg.project_path:
        roots.append(cfg.project_path)
    def walk(value, location='', depth=0):
        if depth > MAX_DEPTH * 4:
            raise ServiceError('GRAPH_DEPTH', 'Graph metadata nesting is excessive.')
        if isinstance(value, dict):
            if 'shader_model' in value and not (trusted_recipe or getattr(cfg, 'allow_custom_shaders', False)):
                raise ServiceError('CUSTOM_SHADER_DISABLED', 'Inline shader definitions require operator approval.', where=location)
            for key, child in value.items():
                if key == 'shader_model':
                    # The entire definition has already been approved. Export
                    # templates inside it are code, not input asset references.
                    continue
                if key in ('custom_script', 'custom_export_script') and child and not (trusted_recipe or getattr(cfg, 'allow_custom_shaders', False)):
                    raise ServiceError('CUSTOM_CODE_DISABLED', 'Custom export code requires operator approval.')
                loc = f'{location}/{key}'
                if key in FILE_KEYS and isinstance(child, str) and child and not child.startswith('#'):
                    looks_like_file = '/' in child or '\\' in child or re.search(r'\.(png|jpg|jpeg|exr|hdr|tga|webp|obj|glb|gltf|svg)$', child, re.I)
                    if looks_like_file:
                        if child.startswith('res://'):
                            resolved = Path(cfg.project_path) / child[6:]
                        elif '://' in child:
                            raise ServiceError('ASSET_URI_DENIED', f'Unsupported asset URI at {loc}')
                        elif Path(child).is_absolute():
                            resolved = Path(child)
                        else:
                            raise ServiceError('ASSET_PATH_AMBIGUOUS', f'Use a res:// or absolute approved asset path at {loc}')
                        try:
                            path = Path(ensure_within_roots(str(resolved), roots))
                        except PathNotAllowed as exc:
                            raise ServiceError('ASSET_PATH_DENIED', str(exc)) from exc
                        if not path.is_file():
                            raise ServiceError('ASSET_MISSING', f'Asset does not exist at {loc}', path=str(path))
                        if path.stat().st_size > 256 * 1024 * 1024:
                            raise ServiceError('ASSET_LIMIT', 'Referenced asset exceeds 256 MiB.')
                        result[str(path)] = {'path': str(path), 'sha256': file_digest(path), 'reference': child}
                walk(child, loc, depth+1)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, f'{location}/{i}', depth+1)
    walk(graph)
    return sorted(result.values(), key=lambda x: x['path'])


def code_hashes(graph):
    """Fingerprint every code field exempted by trusted_recipe, including exporters.

    Shader digests retain their existing form so older project approvals remain
    usable; separately supplied scripts require their own explicit approval.
    """
    found=set()
    def walk(value):
        if isinstance(value,dict):
            if 'shader_model' in value:
                found.add(digest(value['shader_model']))
            for key in ('custom_script', 'custom_export_script'):
                if value.get(key):
                    found.add(digest({key: value[key]}))
            for key,child in value.items():
                if key!='shader_model':
                    walk(child)
        elif isinstance(value,list):
            for child in value:
                walk(child)
    walk(graph)
    return found
