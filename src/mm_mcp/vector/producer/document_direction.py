"""Typed, frozen reference style constraints and a small reviewable art family.

These metrics describe palette/stroke consistency and retained editability.
They do not stand in for an artist's judgment about a candidate's usefulness.
"""

import re
from copy import deepcopy
from hashlib import sha256

from . import document as v1
from . import document_v2 as v2

SCHEMA = "rai.vector-direction/v1"


def validate(style):
    v1.fields(style, {"schema", "reference_sha256", "palette", "stroke_width"})
    if (
        style["schema"] != SCHEMA
        or not isinstance(style["reference_sha256"], str)
        or not re.fullmatch("[a-f0-9]{64}", style["reference_sha256"])
    ):
        raise ValueError("Use a frozen typed reference style")
    if not isinstance(style["palette"], dict) or not 1 <= len(style["palette"]) <= 16:
        raise ValueError("Reference palette requires one to sixteen colors")
    for key, color in style["palette"].items():
        v1.identifier(key)
        if not isinstance(color, str) or not re.fullmatch("#[a-fA-F0-9]{6}", color):
            raise ValueError("Reference colors are literal RGB values")
    v1.number(style["stroke_width"], 0, 12)
    return style


def constraints(reference, stroke_width):
    v2.validate(reference)
    return validate(
        dict(
            schema=SCHEMA,
            reference_sha256=v1.structural_digest(reference),
            palette=deepcopy(reference["palette"]),
            stroke_width=stroke_width,
        )
    )


def evaluate(source, candidate, style, selected=()):
    validate(style)
    v2.validate(source)
    v2.validate(candidate)
    v2.assert_preserved(source, candidate)
    if candidate["rig"] != source["rig"] or candidate.get("creature") != source.get("creature"):
        raise ValueError("Style direction must preserve the rig and recipe")
    protected = v1._protected(v2.expand(source))
    included = v2.descendants(v2.expand(candidate)["nodes"], selected) if selected else None
    colors = {c.upper() for c in style["palette"].values()}
    checked = 0
    for node in v2.expand(candidate)["nodes"]:
        if node["id"] in protected or (included is not None and node["id"] not in included):
            continue
        if node["opacity"] != 1:
            raise ValueError("Style opacity differs from the reference constraints")
        if node["kind"] == "group":
            continue
        checked += 1
        for field in ("fill", "stroke"):
            paint = node[field]
            if paint.startswith("@"):
                paint = candidate["palette"][paint[1:]]
            if paint != "none" and paint.upper() not in colors:
                raise ValueError("Style color is outside the frozen reference palette")
        if node["opacity"] != 1 or (
            node["stroke"] != "none" and node["stroke_width"] != style["stroke_width"]
        ):
            raise ValueError("Style opacity or stroke differs from the reference constraints")
    old_scope = v2.descendants(source["nodes"], selected) if selected else None
    old = {n["id"] for n in source["nodes"] if old_scope is None or n["id"] in old_scope}
    new = {n["id"] for n in candidate["nodes"] if included is None or n["id"] in included}
    retained = len(old & new) / len(old) if old else 1
    if retained < 0.8:
        raise ValueError(
            "Style direction must retain at least eighty percent of editable named parts"
        )
    svg = v2.render(candidate)
    return dict(
        candidate_sha256=v1.structural_digest(candidate),
        preview_svg=svg,
        rendered_sha256=sha256(svg.encode()).hexdigest(),
        metrics=dict(
            palette_compliance=1,
            stroke_compliance=1,
            parts_checked=checked,
            protected_parts=len(protected),
            retained_part_fraction=retained,
            rig_preserved=True,
        ),
    )


def compare(source, reference, candidates, stroke_width):
    style = constraints(reference, stroke_width)
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise ValueError("Compare exactly three art-direction candidates")
    rows = [evaluate(source, candidate, style) for candidate in candidates]
    if len({r["rendered_sha256"] for r in rows}) != 3:
        raise ValueError("Distinct rendered candidates are required for a family")
    return dict(
        schema=SCHEMA,
        reference_sha256=style["reference_sha256"],
        constraints=style,
        candidates=rows,
        requires_acceptance=True,
        interpretation=(
            "Typed style consistency and retained editability; usefulness requires artist review"
        ),
    )
