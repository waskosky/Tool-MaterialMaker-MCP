"""Bounded vector frame and contact-sheet export from trusted recipes."""

from __future__ import annotations

import html
import json
import math

from .core import Compiled, compile_asset, evaluate_pose

VIEW = (-170, -380, 340, 410)


def svg_fragment(
    asset: Compiled, time_seconds: float = 0, clip: str = "rest", prefix: str = ""
) -> str:
    _, world, _ = evaluate_pose(asset, time_seconds, clip)
    parts = []
    for s in asset.shapes:
        path = "M " + " L ".join(f"{p[0]:.5f},{p[1]:.5f}" for p in s["points"]) + " Z"
        matrix = " ".join(f"{v:.8f}" for v in world[s["bone"]])
        parts.append(
            f'<path id="{html.escape(prefix + s["id"], quote=True)}" '
            f'data-bone="{html.escape(s["bone"], quote=True)}" '
            f'd="{path}" transform="matrix({matrix})" fill="{s["fill"]}" stroke="{s["stroke"]}" '
            f'stroke-width="{s["width"]:.3f}" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    return "\n".join(parts)


def frame_svg(
    asset: Compiled, time_seconds: float = 0, clip: str = "rest", width: int = 680
) -> str:
    if not isinstance(width, int) or isinstance(width, bool) or not 64 <= width <= 2048:
        raise ValueError("Preview width must be an integer in [64, 2048]")
    view = " ".join(str(v) for v in VIEW)
    metadata = html.escape(json.dumps(asset.spec, sort_keys=True))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{round(width * VIEW[3] / VIEW[2])}" viewBox="{view}">'
        f"<title>Vector Variation Lab — {asset.spec['generator']} #{asset.spec['seed']}</title>"
        f'<metadata id="vectorlab-spec">{metadata}</metadata>\n'
        + svg_fragment(asset, time_seconds, clip)
        + "\n</svg>\n"
    )


def contact_sheet(
    specs: list[dict],
    labels: list[str] | None = None,
    times: list[float] | None = None,
    clip: str = "rest",
    columns: int = 4,
    title: str = "VECTOR VARIATION LAB",
    quality: int = 1,
) -> str:
    if not 1 <= len(specs) <= 32:
        raise ValueError("A sheet needs 1–32 assets")
    if not isinstance(columns, int) or isinstance(columns, bool) or not 1 <= columns <= 8:
        raise ValueError("columns must be in [1, 8]")
    if labels is not None and len(labels) != len(specs):
        raise ValueError("Label count differs from asset count")
    if times is not None and len(times) != len(specs):
        raise ValueError("Time count differs from asset count")
    columns = min(columns, len(specs))
    rows = math.ceil(len(specs) / columns)
    cell_w, cell_h, margin, top = 238, 307, 20, 90
    width = columns * cell_w + margin * 2
    height = rows * cell_h + top + margin
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#17242e"/>',
        '<text x="24" y="37" font-family="sans-serif" font-size="21" '
        f'font-weight="bold" fill="#e8f0ec">{html.escape(title)}</text>',
        '<text x="24" y="62" font-family="sans-serif" font-size="13" fill="#a5b9bf">'
        "Seeded design families · semantic parameters · reusable motion</text>",
    ]
    for i, spec in enumerate(specs):
        x = margin + (i % columns) * cell_w
        y = top + (i // columns) * cell_h
        a = compile_asset(spec, quality)
        label = labels[i] if labels is not None else f"{spec['generator']} · seed {spec['seed']}"
        parts.extend(
            [
                f'<rect x="{x}" y="{y}" width="{cell_w - 12}" height="{cell_h - 12}" '
                'rx="13" fill="#f2f1e9"/>',
                f'<ellipse cx="{x + 113}" cy="{y + 248}" rx="55" ry="5" fill="#d8ded4"/>',
                f'<svg x="{x + 5}" y="{y + 9}" width="{cell_w - 22}" height="256" '
                'viewBox="-170 -380 340 410">',
                svg_fragment(a, 0 if times is None else times[i], clip, f"cell_{i}_"),
                "</svg>",
                f'<text x="{x + 13}" y="{y + 283}" font-family="sans-serif" font-size="12" '
                f'fill="#304150">{html.escape(label[:34])}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
