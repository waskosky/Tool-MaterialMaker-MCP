"""Local-workspace policy. This is not an operating-system shader sandbox."""
from pathlib import Path
import copy
import re
from mm_mcp.core import ServiceError, file_digest, identifier, digest, MAX_DEPTH
from mm_mcp.paths import ensure_within_roots, PathNotAllowed

FILE_KEYS = {'image', 'image_path', 'file_name', 'filename', 'file_path', 'path', 'texture_path', 'model_path'}


def _asset_roots(cfg):
    roots = list(cfg.allowed_roots or [cfg.output_dir])
    if cfg.project_path:
        roots.append(cfg.project_path)
    return roots


def source_directory(source_dir, cfg) -> str | None:
    """Validate an explicit original graph directory without inferring one."""
    if source_dir is None:
        return None
    if not isinstance(source_dir, (str, Path)) or not Path(source_dir).is_absolute():
        raise ServiceError('ASSET_SOURCE_DIR', 'source_dir must be an absolute directory path.')
    try:
        path = ensure_within_roots(str(source_dir), _asset_roots(cfg))
    except PathNotAllowed as exc:
        raise ServiceError('ASSET_PATH_DENIED', str(exc)) from exc
    if not Path(path).is_dir():
        raise ServiceError('ASSET_SOURCE_DIR', 'source_dir must name an existing directory.')
    return path


def graph_dependencies(graph: dict, cfg, *, trusted_recipe: bool = False,
                       source_dir=None) -> list[dict]:
    """Reject injected shader definitions by default and bound explicit file references.

    Built-in recipes may contain inline shaders. Trust is granted by the service
    loading its own recipe, never by a client-supplied boolean on an HTTP request.
    Unsupported URI schemes are rejected. Native custom exporters remain trusted code.
    %PROJECT_PATH% references require an explicit approved source_dir; other
    relative paths remain ambiguous even when an origin is supplied.
    """
    return _graph_dependencies(graph, cfg, trusted_recipe=trusted_recipe, source_dir=source_dir)


def prepare_render_graph(graph: dict, cfg, *, source_dir=None,
                         inferred_source_dir=None) -> tuple[dict, list[dict]]:
    """Resolve assets in a copy of an already-authorized native render graph.

    Code approval belongs to the service/build policy; the legacy native runner
    validates asset boundaries without imposing a second code-approval policy.
    Its inferred origin is validated only when a %PROJECT_PATH% asset needs it.
    """
    prepared = copy.deepcopy(graph)
    deps = _graph_dependencies(prepared, cfg, trusted_recipe=True, source_dir=source_dir,
                               inferred_source_dir=inferred_source_dir, rewrite=True)
    return prepared, deps


def _graph_dependencies(graph, cfg, *, trusted_recipe=False, source_dir=None,
                        inferred_source_dir=None, rewrite=False):
    result = {}
    roots = _asset_roots(cfg)
    source_dir = source_directory(source_dir, cfg)
    def walk(value, location='', depth=0):
        nonlocal source_dir
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
                        if source_dir is None and child.startswith(('%PROJECT_PATH%/', '%PROJECT_PATH%\\')):
                            source_dir = source_directory(inferred_source_dir, cfg)
                        if child.startswith('res://'):
                            resolved = Path(cfg.project_path) / child[6:]
                        elif child.startswith(('%PROJECT_PATH%/', '%PROJECT_PATH%\\')) and source_dir is not None:
                            resolved = Path(source_dir) / child[len('%PROJECT_PATH%')+1:].replace('\\', '/')
                        elif '://' in child:
                            raise ServiceError('ASSET_URI_DENIED', f'Unsupported asset URI at {loc}')
                        elif Path(child).is_absolute():
                            resolved = Path(child)
                        else:
                            raise ServiceError('ASSET_PATH_AMBIGUOUS', f'Use res://, an approved absolute path, or %PROJECT_PATH% with source_dir at {loc}')
                        try:
                            path = Path(ensure_within_roots(str(resolved), roots))
                        except PathNotAllowed as exc:
                            raise ServiceError('ASSET_PATH_DENIED', str(exc)) from exc
                        if not path.is_file():
                            raise ServiceError('ASSET_MISSING', f'Asset does not exist at {loc}', path=str(path))
                        if path.stat().st_size > 256 * 1024 * 1024:
                            raise ServiceError('ASSET_LIMIT', 'Referenced asset exceeds 256 MiB.')
                        result[str(path)] = {'path': str(path), 'sha256': file_digest(path), 'reference': child}
                        if rewrite and child.startswith('%PROJECT_PATH%'):
                            value[key] = str(path)
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
