import os
import json
from pathlib import Path
import sys
from dataclasses import dataclass, field
from dotenv import dotenv_values

# Config is env-var-first (an MCP client sets MM_* in its server "env" block).
# A .env file is a dev convenience only: looked up at MM_DOTENV if set, else in
# the current working directory. It is NOT anchored to the install location, so
# the same code works from a source checkout and from a `pip install` into
# site-packages. Path defaults are intentionally empty so a stranger with no
# config gets the actionable "set MM_PROJECT_PATH" message from require_valid()
# rather than a stale path baked in at build time.
_DEFAULTS = {
    "MM_GODOT_BINARY": "",
    "MM_PROJECT_PATH": "",
    "MM_OUTPUT_DIR": "",
    "MM_LIVE_OVERLAY_DIR": "",
    "MM_ALLOWED_ROOTS": "",
    "MM_COOKBOOK_DIR": "",
    "MM_PLAY_PORT": "8788",
    "MM_IDLE_EXIT_MINUTES": "0",
}

NATIVE_SETTINGS = {'godot_binary': 'MM_GODOT_BINARY', 'project_path': 'MM_PROJECT_PATH'}


def settings_path() -> Path:
    """Per-user native defaults; profiles/tests can select an isolated file."""
    override = os.environ.get('MM_SETTINGS_FILE')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        parent = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    elif sys.platform == 'darwin':
        parent = Path.home() / 'Library' / 'Application Support'
    else:
        parent = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return parent / 'MaterialWorkshop' / 'settings.json'


def _read_settings():
    path = settings_path()
    try:
        if not path.exists():
            return {}, None
        if path.stat().st_size > 32768:
            raise ValueError('file too large')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('expected object')
        # Settings never authorize other configuration, even if edited by hand.
        return {key: value[key] for key in NATIVE_SETTINGS if isinstance(value.get(key), str)}, None
    except (OSError, ValueError):
        # Keep repair available even when this optional defaults file is damaged.
        # Never rewrite it on read or disclose its contents in the warning.
        return {}, f'Cannot read native settings at {path}. Saving valid paths will replace these unreadable defaults.'


def read_settings() -> dict[str, str]:
    return _read_settings()[0]


def native_values(saved=None, dotenv=None):
    """Native-only resolution, without exposing any unrelated dotenv entries."""
    saved = read_settings() if saved is None else saved
    dotenv = dotenv_values(_dotenv_path()) if dotenv is None else dotenv
    values = {key: saved.get(key, '') for key in NATIVE_SETTINGS}
    sources = {}
    for key, env_key in NATIVE_SETTINGS.items():
        if dotenv.get(env_key):
            values[key] = dotenv[env_key]
            sources[key] = f'.env entry {env_key} in {_dotenv_path()}'
        if env_key in os.environ:
            values[key] = os.environ[env_key]
            sources[key] = f'environment variable {env_key}'
    return values, sources


def _dotenv_path() -> str:
    override = os.environ.get("MM_DOTENV")
    if override:
        return override
    return os.path.join(os.getcwd(), ".env")


@dataclass
class Config:
    godot_binary: str
    console_binary: str
    project_path: str
    output_dir: str
    nodes_dir: str
    examples_dir: str
    live_overlay_dir: str
    allowed_roots: list[str]
    cookbook_dir: str = ""
    play_port: int = 8788
    idle_exit_minutes: int = 0
    workspace_dir: str = ""
    max_resolution: int = 2048
    allow_custom_shaders: bool = False
    enable_experimental_live_writes: bool = False
    native_overrides: dict[str, str] = field(default_factory=dict)
    native_settings_warning: str | None = None


def _resolve_console(godot_binary: str) -> str:
    if godot_binary.lower().endswith(".exe"):
        candidate = godot_binary[:-4] + "_console.exe"
        if os.path.exists(candidate):
            return candidate
    return godot_binary


def _default_cookbook_dir() -> str:
    """<repo>/cookbook when running from a source checkout (this file is
    src/mm_mcp/config.py, so three dirname hops up is the repo root). Empty
    when neither source nor wheel resources exist. Wheels include the reviewed
    cookbook under mm_mcp/data/cookbook."""
    here = os.path.abspath(__file__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    candidate = os.path.join(repo, "cookbook")
    packaged = os.path.join(os.path.dirname(__file__), "data", "cookbook")
    return candidate if os.path.isdir(candidate) else packaged if os.path.isdir(packaged) else ""


def require_valid(cfg: "Config") -> None:
    """Fail fast with an actionable message if required config paths are
    missing or wrong. Called at MCP server startup (not from load_config()),
    per the design spec's Error handling section: "Missing config
    (MM_GODOT_BINARY / MM_PROJECT_PATH absent or wrong) fails fast at server
    start with an actionable message."
    """
    if not os.path.isdir(cfg.project_path):
        raise FileNotFoundError(
            f"MM_PROJECT_PATH does not exist: '{cfg.project_path}'. "
            "Set the MM_PROJECT_PATH environment variable (or .env entry) "
            "to a valid Material Maker project checkout."
        )
    if not os.path.isdir(cfg.nodes_dir):
        raise FileNotFoundError(
            f"Node catalog directory does not exist: '{cfg.nodes_dir}'. "
            "This is derived from MM_PROJECT_PATH "
            f"('{cfg.project_path}') + addons/material_maker/nodes; "
            "check that MM_PROJECT_PATH points at a valid Material Maker checkout."
        )
    binary = cfg.console_binary if os.path.exists(cfg.console_binary) else cfg.godot_binary
    if not os.path.isfile(binary):
        raise FileNotFoundError(
            f"Godot binary does not exist: '{binary}'. "
            "Set the MM_GODOT_BINARY environment variable (or .env entry) "
            "to a valid Godot executable path."
        )


def _parse_idle_exit_minutes(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"MM_IDLE_EXIT_MINUTES must be a non-negative integer, got '{raw}'"
        )
    if value < 0:
        raise ValueError(
            f"MM_IDLE_EXIT_MINUTES must be a non-negative integer, got '{raw}'"
        )
    return value


def load_config(overrides: dict | None = None) -> Config:
    env = dict(_DEFAULTS)
    dotenv = dotenv_values(_dotenv_path())
    saved, settings_warning = _read_settings()
    native, sources = native_values(saved=saved, dotenv=dotenv)
    env.update({NATIVE_SETTINGS[key]: value for key, value in native.items()})
    env.update({k: v for k, v in dotenv.items() if v})
    env.update({k: v for k, v in os.environ.items() if k.startswith("MM_")})
    if overrides:
        env.update(overrides)
    project_path = env["MM_PROJECT_PATH"]
    output_dir = env["MM_OUTPUT_DIR"] or os.path.join(os.getcwd(), "output")
    live_overlay_dir = env["MM_LIVE_OVERLAY_DIR"] or os.path.join(os.getcwd(), "mm_live_overlay")
    workspace_dir = os.path.abspath(env.get("MM_WORKSPACE_DIR") or os.path.join(output_dir, "workspace"))
    roots_raw = env["MM_ALLOWED_ROOTS"]
    if roots_raw.startswith("["):
        import json
        allowed_roots = json.loads(roots_raw)
        if not isinstance(allowed_roots, list) or not all(isinstance(p, str) and p for p in allowed_roots):
            raise ValueError("MM_ALLOWED_ROOTS must be a JSON array of paths")
    else:
        allowed_roots = [p for p in roots_raw.split(os.pathsep) if p]
    if not allowed_roots and env.get("MM_TRUSTED_UNRESTRICTED_PATHS") != "1":
        allowed_roots = [workspace_dir, os.path.abspath(output_dir)]
    cookbook_dir = env["MM_COOKBOOK_DIR"] or _default_cookbook_dir()
    play_port = int(env["MM_PLAY_PORT"] or 8788)
    if not 1024 <= play_port <= 65535:
        raise ValueError("MM_PLAY_PORT must be between 1024 and 65535")
    maximum = int(env.get("MM_MAX_RESOLUTION", "2048"))
    if maximum < 32 or maximum > 4096 or maximum & (maximum - 1):
        raise ValueError("MM_MAX_RESOLUTION must be a power of two from 32 through 4096")
    idle_exit_minutes = _parse_idle_exit_minutes(env["MM_IDLE_EXIT_MINUTES"] or "0")
    return Config(
        godot_binary=env["MM_GODOT_BINARY"],
        console_binary=_resolve_console(env["MM_GODOT_BINARY"]),
        project_path=project_path,
        output_dir=output_dir,
        nodes_dir=os.path.join(project_path, "addons", "material_maker", "nodes"),
        examples_dir=os.path.join(project_path, "material_maker", "examples"),
        live_overlay_dir=live_overlay_dir,
        allowed_roots=allowed_roots,
        cookbook_dir=cookbook_dir,
        play_port=play_port,
        idle_exit_minutes=idle_exit_minutes,
        workspace_dir=workspace_dir,
        max_resolution=maximum,
        allow_custom_shaders=env.get("MM_ALLOW_CUSTOM_SHADERS") == "1",
        enable_experimental_live_writes=env.get("MM_ENABLE_EXPERIMENTAL_LIVE_WRITES") == "1",
        native_overrides=sources,
        native_settings_warning=settings_warning,
    )
