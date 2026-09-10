"""Verified native previews of already-baked maps, with private staging."""
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from mm_mcp.config import Config, load_config
from mm_mcp.render import _run_godot, _log_tail, _GodotTimeout, _clear_attempt_files
from mm_mcp.core import ServiceError, finite, identifier
from mm_mcp.paths import ensure_within_roots, PathNotAllowed
from mm_mcp.artifacts import verify_images

_PREVIEW_PROJECT = os.path.join(os.path.dirname(__file__), "preview_project")

@dataclass
class PreviewResult:
    ok: bool
    image: str | None = None
    log_tail: str = ""
    error: str | None = None


def _build_command(cfg, albedo_path, normal_path, orm_path, out_path, tile):
    return [cfg.console_binary, "--path", _PREVIEW_PROJECT, "--",
            f"--albedo={albedo_path}", f"--normal={normal_path}",
            f"--orm={orm_path}", f"--out={out_path}", f"--tile={tile}"]


def render_preview(albedo_path: str, normal_path: str, orm_path: str,
                   outdir: str | None = None, basename: str = "preview",
                   tile: float = 1.0, cfg: Config | None = None) -> PreviewResult:
    """Render verified PNG maps on native preview geometry.

    This requires a real rendering device. It is not a dummy-headless operation.
    Failed, nonzero-exit, oversized and corrupt outputs never replace a good file.
    """
    cfg = cfg or load_config()
    log_tail = ""
    try:
        identifier(basename, "preview basename")
        if not finite(tile) or not 0 < tile <= 64:
            raise ServiceError("TILE_RANGE", "tile must be finite, positive and no greater than 64.")
        inputs = [ensure_within_roots(p, cfg.allowed_roots)
                  for p in (albedo_path, normal_path, orm_path)]
        verify_images(inputs)
        output = Path(ensure_within_roots(outdir or cfg.output_dir, cfg.allowed_roots))
        output.mkdir(parents=True, exist_ok=True)
        destination = output / (basename + "_preview.png")
        if destination.is_symlink():
            raise ServiceError("ARTIFACT_SYMLINK", "Refusing to replace a preview symlink.")
        with tempfile.TemporaryDirectory(prefix=".preview-", dir=output) as temporary:
            candidate = Path(temporary) / destination.name
            proc = _run_godot(_build_command(cfg, *inputs, str(candidate), tile), 60,
                              before_attempt=lambda: _clear_attempt_files(temporary))
            log_tail = _log_tail(proc)
            if proc.returncode != 0:
                raise ServiceError("PREVIEW_EXIT", f"Godot exited {proc.returncode}; preview was not published.")
            verify_images([candidate], root=temporary)
            os.replace(candidate, destination)
        return PreviewResult(True, str(destination), log_tail)
    except _GodotTimeout:
        return PreviewResult(False, log_tail=log_tail, error="preview render timed out after 60s")
    except (ServiceError, PathNotAllowed, OSError, ValueError) as exc:
        return PreviewResult(False, log_tail=log_tail, error=str(exc))
