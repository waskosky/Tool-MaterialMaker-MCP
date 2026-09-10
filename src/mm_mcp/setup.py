"""Native setup only: safe defaults, bounded checks, and idle service refresh."""
from dataclasses import replace
from itertools import islice
import os
from pathlib import Path
import re
import shutil
import subprocess

from mm_mcp.catalog_builder import build_catalog
from mm_mcp.config import NATIVE_SETTINGS, _resolve_console, native_values, require_valid, settings_path
from mm_mcp.core import ServiceError, atomic_json

INSTALL = {
    'godot_url': 'https://godotengine.org/download/archive/4.7.2-stable/',
    'material_maker_url': 'https://github.com/RodZill4/material-maker/archive/ad19fcf0ee34a7caf74df709dc4de7112f0d467d.zip',
}


def normalize_path(value, key):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\x00\r\n'):
        raise ServiceError('SETUP_PATH', f'{key} must be a nonempty local path.')
    raw = value.strip().strip('\"\'')
    if not raw:
        raise ServiceError('SETUP_PATH', f'{key} must be a nonempty local path.')
    try:
        path = Path(raw).expanduser()
        if key == 'godot_binary' and path.suffix.lower() == '.app':
            path = path / 'Contents' / 'MacOS' / 'Godot'
        path = path.resolve()
        if key == 'godot_binary':
            if not path.is_file() or (os.name != 'nt' and not os.access(path, os.X_OK)):
                raise ServiceError('SETUP_PATH', 'Godot must point to an executable file (or Godot.app).')
        elif not (path / 'project.godot').is_file() or not (path / 'addons/material_maker/nodes').is_dir():
            raise ServiceError('SETUP_PATH', 'Material Maker must contain project.godot and addons/material_maker/nodes.')
    except (OSError, RuntimeError) as exc:
        raise ServiceError('SETUP_PATH', f'{key} cannot be resolved; check permissions and symbolic links.') from exc
    return str(path)


def validated_settings(values):
    if not isinstance(values, dict) or set(values) != set(NATIVE_SETTINGS):
        raise ServiceError('SETUP_FIELDS', 'Only godot_binary and project_path may be saved; provide both paths.')
    return {key: normalize_path(values[key], key) for key in NATIVE_SETTINGS}


def save_settings(values):
    saved = validated_settings(values)
    atomic_json(settings_path(), saved)
    return saved


def discover_native():
    """Inspect common locations, never recurse through an entire home/drive.

    At most 160 entries per location, 4096 entries total and 24 results per kind. Only nearby
    Material Maker/Godot directories receive one additional level of inspection.
    Discovered executables are suggestions; discovery never runs them.
    """
    home, cwd = Path.home(), Path.cwd()
    roots = [cwd, home / 'games/temp', cwd.parent, home / 'games', home / 'Applications',
             Path('/Applications'), home / 'Downloads', Path('/usr/local/bin'), Path('/opt/homebrew/bin')]
    if os.name == 'nt':
        roots.extend(Path(os.environ[key]) / 'Godot' for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if os.environ.get(key))
    found = {'godot_binaries': set(), 'project_paths': set()}
    seen = set()
    scanned = set()
    remaining = 4096
    def inspect(path):
        for key, field in [('project_path', 'project_paths'), ('godot_binary', 'godot_binaries')]:
            if len(found[field]) >= 24:
                continue
            if key == 'godot_binary' and 'godot' not in path.name.lower():
                continue
            try:
                found[field].add(normalize_path(str(path), key))
            except (OSError, ValueError):
                pass
    def children(path):
        nonlocal remaining
        if path in scanned or remaining <= 0:
            return []
        scanned.add(path)
        try:
            entries = list(islice(path.iterdir(), min(160, remaining)))
            remaining -= len(entries)
            return entries
        except OSError:
            return []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        inspect(root)
        for child in children(root):
            inspect(child)
            name = child.name.lower()
            if child.suffix.lower() != '.app' and any(term in name for term in ('godot', 'material-maker', 'materialmaker', 'material_maker')):
                for nested in children(child):
                    inspect(nested)
    for name in ('godot', 'godot4', 'Godot', 'godot.exe'):
        path = shutil.which(name)
        if path:
            inspect(Path(path))
    return {key: sorted(values) for key, values in found.items()}


def version_check(cfg):
    try:
        binary = normalize_path(cfg.console_binary or cfg.godot_binary, 'godot_binary')
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=4, check=False)
        version = result.stdout.strip().splitlines()[0][:240] if result.stdout.strip() else ''
        ok = result.returncode == 0 and re.match(r'^4\.7(?:\.\d+)?\.stable(?:\.|\s|$)', version) is not None
        detail = version if ok else 'The configured executable did not report Godot 4.7.x; install the recommended Godot version.'
    except (OSError, ValueError, subprocess.SubprocessError):
        ok, detail = False, 'Could not run the configured Godot executable with --version (4 second limit).'
    return {'name': 'Godot version', 'ok': ok, 'detail': detail}


def verify_native(app):
    if app.render_fn is not None:
        raise ServiceError('TEST_RENDERER', 'The injected test renderer cannot verify native Material Maker rendering.')
    try:
        require_valid(app.cfg)
    except (OSError, ValueError) as exc:
        raise ServiceError('SETUP_REQUIRED', str(exc)) from exc
    return app.jobs.submit({'recipe_id': 't01_sand_dunes', 'size': 128, 'target': 'generic', 'force': True})


def configure_native(app, values):
    saved = validated_settings(values)
    if not app._config_lock.acquire(blocking=False):
        raise ServiceError('SETUP_BUSY', 'Finish or cancel pending work before changing native settings.')
    try:
        with app.jobs.idle_transaction():
            effective, overrides = native_values(saved)
            project = effective['project_path']
            cfg = replace(app.cfg, **effective, console_binary=_resolve_console(effective['godot_binary']),
                          nodes_dir=str(Path(project) / 'addons/material_maker/nodes'),
                          examples_dir=str(Path(project) / 'material_maker/examples'), native_overrides=overrides,
                          native_settings_warning=None)
            catalog = build_catalog(cfg.nodes_dir)
            # All fallible preparation comes before persistence and in-memory swap.
            atomic_json(settings_path(), saved)
            changed = any(getattr(app.cfg, key) != getattr(cfg, key) for key in NATIVE_SETTINGS)
            app.cfg = cfg
            app.catalog = catalog
            app.graphs.catalog = app.recipes.catalog = app.builds.catalog = catalog
            app.builds.cfg = cfg
            if changed:
                app._native_verified = False
                app._last_render_error = None
    finally:
        app._config_lock.release()
    return setup_status(app)


def setup_status(app, check=False):
    cfg = app.cfg
    checks = []
    if cfg.native_settings_warning:
        checks.append({'name': 'saved settings', 'ok': False, 'required': False, 'detail': cfg.native_settings_warning})
    for key in NATIVE_SETTINGS:
        try:
            detail = normalize_path(getattr(cfg, key), key)
            ok = True
        except (ServiceError, OSError) as exc:
            detail, ok = str(exc), False
        checks.append({'name': key, 'ok': ok, 'detail': detail})
    caps = app.capabilities()
    detected = discover_native() if check else {'godot_binaries': [], 'project_paths': []}
    if check:
        checks.append(version_check(cfg))
    checks.append({'name': 'native render', 'ok': caps['native_render_verified_this_session'], 'required': False,
                   'detail': 'A new native build succeeded this session.' if caps['native_render_verified_this_session']
                   else 'Native rendering has not been verified this session. Save valid paths, then run the test render.'})
    return {'ok': True, 'settings': {key: getattr(cfg, key) for key in NATIVE_SETTINGS},
            'settings_file': str(settings_path()), 'overrides': dict(cfg.native_overrides),
            'detected': detected, 'checks': checks,
            'native_render_configured': caps['native_render_configured'],
            'catalog_available': caps['catalog_available'],
            'native_render_verified_this_session': caps['native_render_verified_this_session'],
            'last_render_error': caps['last_render_error'], 'install': dict(INSTALL),
            'busy': app._build_running or app.jobs.active(), 'injected_test_renderer': app.render_fn is not None}
