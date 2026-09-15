"""The upstream sweep renderer must retain Workshop's native/path boundaries."""
from pathlib import Path

import pytest

from tests.test_preview_sweep import sweep, _render, _mock_render, _write_frames


@pytest.mark.parametrize('options', [
    {'frames': 121}, {'tile': 0}, {'tile': float('nan')},
    {'cone': float('inf')}, {'sweep_kind': 'unknown'},
])
def test_sweep_rejects_unbounded_native_options(monkeypatch, sweep, options):
    calls = _mock_render(monkeypatch)
    result = _render(sweep, **options)
    assert not result.ok and result.error
    assert not calls
    assert sweep.gif_path.read_bytes() == sweep.old_gif


def test_sweep_rejects_output_outside_allowed_roots(monkeypatch, sweep, tmp_path):
    sweep.cfg.allowed_roots = [str(sweep.outdir), str(Path(sweep.maps[0]).parent)]
    calls = _mock_render(monkeypatch)
    outside = tmp_path / 'outside'
    result = _render(sweep, outdir=str(outside))
    assert not result.ok
    assert not calls and not outside.exists()


def test_sweep_rejects_preview_destination_symlink(monkeypatch, sweep):
    target = sweep.outdir / 'human.gif'
    target.write_bytes(sweep.old_gif)
    sweep.gif_path.unlink()
    sweep.gif_path.symlink_to(target)
    calls = _mock_render(monkeypatch)
    result = _render(sweep)
    assert not result.ok
    assert not calls and sweep.gif_path.is_symlink()
    assert target.read_bytes() == sweep.old_gif


def test_sweep_returns_a_failure_for_input_png_checksum_error(monkeypatch, sweep):
    source = Path(sweep.maps[0])
    data = bytearray(source.read_bytes())
    offset = data.index(b'IDAT')
    length = int.from_bytes(data[offset - 4:offset], 'big')
    data[offset + 4 + length] ^= 1
    source.write_bytes(data)
    calls = _mock_render(monkeypatch)
    result = _render(sweep)
    assert not result.ok and result.error
    assert not calls
    assert sweep.gif_path.read_bytes() == sweep.old_gif


def test_sweep_uses_verified_paths_after_input_alias_changes(monkeypatch, sweep, tmp_path):
    original = Path(sweep.maps[0])
    alias = original.parent / 'alias.png'
    alias.symlink_to(original)
    outside = tmp_path / 'outside.png'
    outside.write_bytes(original.read_bytes())
    sweep.maps = (str(alias), *sweep.maps[1:])
    sweep.cfg.allowed_roots = [str(original.parent), str(sweep.outdir)]

    def render_after_retarget(directory):
        alias.unlink()
        alias.symlink_to(outside)
        _write_frames(directory)

    calls = _mock_render(monkeypatch, render_after_retarget)
    assert _render(sweep).ok
    rendered_input = Path(next(arg.split('=', 1)[1] for arg in calls[0].cmd
                               if arg.startswith('--albedo=')))
    assert rendered_input.resolve() == original.resolve()
