"""Verified native previews of already-baked maps, with private staging."""
import os
import tempfile
import shutil
from PIL import Image
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


@dataclass
class PreviewSweepResult:
    ok: bool
    image: str | None = None
    frame_count: int = 0
    log_tail: str = ""
    error: str | None = None


def _build_command(cfg, albedo_path, normal_path, orm_path, out_path, tile):
    return [cfg.console_binary, "--path", _PREVIEW_PROJECT, "--",
            f"--albedo={albedo_path}", f"--normal={normal_path}",
            f"--orm={orm_path}", f"--out={out_path}", f"--tile={tile}"]


def render_preview(albedo_path: str, normal_path: str, orm_path: str,
                   outdir: str | None = None, basename: str = "preview",
                   tile: float = 0.45, cfg: Config | None = None) -> PreviewResult:
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


def _build_sweep_command(cfg: Config, albedo_path: str, normal_path: str, orm_path: str,
                          sweep_dir: str, frames: int, tile: float,
                          sweep_kind: str = "precess", cone: float = 18.0) -> list[str]:
    return [
        cfg.console_binary, "--path", _PREVIEW_PROJECT, "--",
        f"--albedo={albedo_path}", f"--normal={normal_path}",
        f"--orm={orm_path}", f"--sweep-outdir={sweep_dir}",
        f"--sweep-frames={frames}", f"--tile={tile}",
        f"--sweep-kind={sweep_kind}", f"--cone={cone}",
    ]

def _frames_to_gif(frame_paths: list[str], gif_path: str, frame_duration_ms: int) -> None:
    """Stitch already-rendered frame PNGs (in order) into a looping GIF.
    Pure assembly only -- callers own producing and cleaning up the frames."""
    images = [Image.open(p).convert("RGB") for p in frame_paths]
    images[0].save(gif_path, save_all=True, append_images=images[1:],
                    duration=frame_duration_ms, loop=0)

def render_preview_sweep(albedo_path: str, normal_path: str, orm_path: str,
                          outdir: str | None = None, basename: str = "preview",
                          tile: float = 0.45, frames: int = 18,
                          frame_duration_ms: int = 80,
                          sweep_kind: str = "precess", cone: float = 18.0,
                          cfg: Config | None = None) -> PreviewSweepResult:
    """Animate the key light around the same sphere/cube/cutaway rig
    render_preview uses, and composite the frames into a looping GIF -- relief
    that a single fixed-angle static frame hides becomes visible across the
    sweep.

    sweep_kind defaults to 'precess': the key stays aimed at the object and its
    aim traces a small cone (radius = cone degrees) so highlights circle the
    relief without the shot ever going backlit. sweep_kind='azimuth' is the
    older full 360-degree orbit of the key. The rim/fill are held fixed either
    way.

    Same inputs as render_preview (already-rendered albedo/normal/orm maps,
    not a .ptex graph). Renders every frame inside ONE Godot process rather
    than launching one process per frame, since a fresh process would pay
    the project-load cost N times over. This is optional and slower than
    render_preview -- reach for it only when a static preview leaves relief
    ambiguous.
    """
    for label, path in (("albedo", albedo_path), ("normal", normal_path),
                         ("orm", orm_path)):
        if not os.path.isfile(path):
            return PreviewSweepResult(ok=False, error=f"{label} path does not exist: '{path}'")

    albedo_path = os.path.abspath(albedo_path)
    normal_path = os.path.abspath(normal_path)
    orm_path = os.path.abspath(orm_path)

    cfg = cfg or load_config()
    outdir = outdir or cfg.output_dir
    os.makedirs(outdir, exist_ok=True)

    sweep_dir = os.path.abspath(os.path.join(outdir, basename + "_sweep_frames"))
    if os.path.exists(sweep_dir):
        shutil.rmtree(sweep_dir)

    gif_path = os.path.abspath(os.path.join(outdir, basename + "_sweep.gif"))
    if os.path.exists(gif_path):
        os.remove(gif_path)

    cmd = _build_sweep_command(cfg, albedo_path, normal_path, orm_path, sweep_dir,
                                frames, tile, sweep_kind=sweep_kind, cone=cone)

    timeout = max(90, frames * 8)
    try:
        proc = _run_godot(cmd, timeout)
    except _GodotTimeout:
        return PreviewSweepResult(ok=False, error=f"preview sweep render timed out after {timeout}s")
    log_tail = _log_tail(proc)

    frame_paths = sorted(
        os.path.join(sweep_dir, fn) for fn in os.listdir(sweep_dir)
        if fn.lower().endswith(".png")
    ) if os.path.isdir(sweep_dir) else []
    if not frame_paths:
        error = f"Godot exited {proc.returncode}" if proc.returncode != 0 else "no sweep frames produced"
        return PreviewSweepResult(ok=False, log_tail=log_tail, error=error)

    _frames_to_gif(frame_paths, gif_path, frame_duration_ms)
    shutil.rmtree(sweep_dir, ignore_errors=True)

    return PreviewSweepResult(ok=True, image=gif_path, frame_count=len(frame_paths), log_tail=log_tail)
