"""Validated, versioned asset specs, shared-recipe compilation and rig evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from . import geometry as g
from .expression import evaluate as ev
from .expression import named_random

MAX_DOCUMENT_BYTES = 1_000_000
MOTION = {
    "cycle_seconds": (0.35, 4.0, 0.95),
    "energy": (0.0, 1.0, 0.5),
    "stride": (0.0, 1.0, 0.45),
    "lift": (0.0, 1.0, 0.45),
}
SPEC_KEYS = {
    "schema_version",
    "generator",
    "generator_version",
    "seed",
    "parameters",
    "choices",
    "palette",
    "motion",
}


def strict_json(text: str, max_bytes: int = MAX_DOCUMENT_BYTES) -> Any:
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"Document exceeds {max_bytes:,} bytes")

    def constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError(f"Duplicate key: {k}")
            obj[k] = v
        return obj

    try:
        return json.loads(text, parse_constant=constant, object_pairs_hook=pairs)
    except (RecursionError, TypeError) as exc:
        raise ValueError("Invalid or excessively nested JSON") from exc


@lru_cache(maxsize=1)
def catalog() -> dict:
    # One checked-in recipe file is consumed by Python and Godot.
    return strict_json(
        (Path(__file__).parent / "data/catalog.json").read_text(encoding="utf-8"), 16_000_000
    )


def family(name: str, version: int | None = None) -> dict:
    if not isinstance(name, str):
        raise ValueError("Generator name must be a string")
    active = catalog()["families"].get(name)
    if version is None:
        if active is None:
            raise ValueError(f"Unknown generator: {name}")
        return active
    if (
        isinstance(version, bool)
        or not isinstance(version, (int, float))
        or not math.isfinite(version)
        or int(version) != version
        or not 1 <= version <= 2147483647
    ):
        raise ValueError("Generator version must be an integer")
    if active is not None and active["version"] == version:
        return active
    archived = catalog().get("archives", {}).get(f"{name}@{int(version)}")
    if archived is None:
        raise ValueError(f"Unsupported generator version: {name}@{version}")
    return archived


def number(value: Any, lo: float, hi: float, name: str, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} must be finite and in [{lo}, {hi}]")
    if integer:
        if int(value) != value:
            raise ValueError(f"{name} must be an integer")
        return int(value)
    return float(value)


def create_spec(
    generator: str = "creature",
    seed: int = 42,
    parameters: dict | None = None,
    choices: dict | None = None,
    palette: str | None = None,
    motion: dict | None = None,
) -> dict:
    f = family(generator)
    seed = number(seed, 0, 2147483647, "seed", True)
    for name, value in (("parameters", parameters), ("choices", choices), ("motion", motion)):
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
    params = {}
    env = {"_seed": seed, "_namespace": f"{generator}@{f['version']}"}
    for name in f["parameter_order"]:
        d = f["parameters"][name]
        v = ev(d["sample"], env) if "sample" in d else d["default"]
        v = max(d["min"], min(d["max"], v))
        if d["type"] == "int":
            v = math.floor(v + 0.5)
        params[name] = v
        env[name] = v
    params.update(parameters or {})
    picks = {
        name: d["values"][int(named_random(seed, env["_namespace"], name) * len(d["values"]))]
        for name, d in f["choices"].items()
    }
    picks.update(choices or {})
    palettes = list(catalog()["palettes"])
    result = {
        "schema_version": 1,
        "generator": generator,
        "generator_version": f["version"],
        "seed": seed,
        "parameters": params,
        "choices": picks,
        "palette": palette
        if palette is not None
        else palettes[int(named_random(seed, env["_namespace"], "palette") * len(palettes))],
        "motion": {k: v[2] for k, v in MOTION.items()},
    }
    result["motion"].update(motion or {})
    return validate_spec(result)


def migrate_spec(spec: dict) -> dict:
    """Explicitly support the supplied v0 fixture; unknown future formats fail closed."""
    if not isinstance(spec, dict):
        raise ValueError("Asset must be an object")
    if spec.get("schema_version") == 0:
        allowed = {"schema_version", "family", "seed", "params"}
        if set(spec) - allowed:
            raise ValueError("Unknown legacy fields")
        return create_spec(spec["family"], spec["seed"], parameters=spec.get("params", {}))
    return deepcopy(spec)


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("Asset must be an object")
    if set(spec) != SPEC_KEYS:
        raise ValueError(f"Asset fields mismatch: {sorted(set(spec) ^ SPEC_KEYS)}")
    if (
        isinstance(spec["schema_version"], bool)
        or not isinstance(spec["schema_version"], (int, float))
        or spec["schema_version"] != 1
    ):
        raise ValueError("Unsupported schema_version; migrate explicitly")
    f = family(spec["generator"], spec["generator_version"])
    if (
        isinstance(spec["generator_version"], bool)
        or not isinstance(spec["generator_version"], (int, float))
        or spec["generator_version"] != f["version"]
    ):
        raise ValueError(
            "Unsupported generator version; retain the old generator to load this save"
        )
    result = deepcopy(spec)
    result["seed"] = number(spec["seed"], 0, 2147483647, "seed", True)
    result["schema_version"] = 1
    result["generator_version"] = f["version"]
    for section, definition in (
        ("parameters", f["parameters"]),
        ("choices", f["choices"]),
        ("motion", MOTION),
    ):
        if not isinstance(spec[section], dict) or set(spec[section]) != set(definition):
            raise ValueError(f"{section} fields mismatch")
    for name, d in f["parameters"].items():
        result["parameters"][name] = number(
            spec["parameters"][name], d["min"], d["max"], name, d["type"] == "int"
        )
    for name, d in f["choices"].items():
        if not isinstance(spec["choices"][name], str) or spec["choices"][name] not in d["values"]:
            raise ValueError(f"Invalid choice {name}; expected {d['values']}")
    if not isinstance(spec["palette"], str) or spec["palette"] not in catalog()["palettes"]:
        raise ValueError("Unknown palette")
    for name, (lo, hi, _) in MOTION.items():
        result["motion"][name] = number(spec["motion"][name], lo, hi, name)
    return result


def canonical(spec: dict) -> str:
    return json.dumps(validate_spec(spec), sort_keys=True, separators=(",", ":"), allow_nan=False)


def asset_id(spec: dict) -> str:
    return hashlib.sha256(canonical(spec).encode()).hexdigest()[:24]


def revise_spec(
    spec: dict,
    parameters: dict | None = None,
    choices: dict | None = None,
    palette: str | None = None,
    motion: dict | None = None,
    preserve: list[str] | None = None,
) -> dict:
    old = validate_spec(spec)
    new = deepcopy(old)
    f = family(old["generator"], old["generator_version"])
    if preserve is not None and (
        not isinstance(preserve, list) or any(not isinstance(x, str) for x in preserve)
    ):
        raise ValueError("preserve must be a list of parameter/group names")
    for key, patch in (("parameters", parameters), ("choices", choices), ("motion", motion)):
        if patch is not None:
            if not isinstance(patch, dict):
                raise ValueError(f"{key} must be an object")
            new[key].update(patch)
    if palette is not None:
        new["palette"] = palette
    new = validate_spec(new)
    for lock in preserve or []:
        if lock == "palette":
            if new["palette"] != old["palette"]:
                raise ValueError("Palette is protected")
        elif lock == "structure":
            if new["choices"] != old["choices"]:
                raise ValueError("Structure is protected")
            for p in f.get("structural_parameters", []):
                if new["parameters"][p] != old["parameters"][p]:
                    raise ValueError(f"Structural parameter {p} is protected")
        else:
            names = f.get("groups", {}).get(lock, [lock])
            for name in names:
                if name not in old["parameters"]:
                    raise ValueError(f"Unknown protected control: {lock}")
                if new["parameters"][name] != old["parameters"][name]:
                    raise ValueError(f"Protected parameter changed: {name}")
    return new


def environment(spec: dict) -> dict:
    f = family(spec["generator"], spec["generator_version"])
    env = {
        **spec["parameters"],
        **spec["choices"],
        "_seed": spec["seed"],
        "_namespace": f"{spec['generator']}@{f['version']}",
        "phase": 0.0,
    }
    env.update({"motion_" + k: v for k, v in spec["motion"].items()})
    for key, expr in f["derived"]:
        env[key] = ev(expr, env)
    return env


def expand(nodes: list[dict], env: dict) -> Iterator[tuple[dict, dict]]:
    for node in nodes:
        if "repeat" in node:
            r = node["repeat"]
            count = int(ev(r["count"], env))
            if not 0 <= count <= 32:
                raise ValueError("Recipe repetition exceeds budget")
            for i in range(count):
                yield from expand(node["items"], {**env, r["var"]: i})
        elif ev(node.get("when", True), env):
            yield node, env


def label(value: str, env: dict) -> str:
    # Only trusted recipe strings reach this formatter.
    return value.format_map(env)


@dataclass
class Compiled:
    spec: dict
    env: dict
    bones: list[dict]
    shapes: list[dict]
    ik: list[dict]
    measurements: dict
    quality: int


def compile_asset(spec: dict, quality: int = 1) -> Compiled:
    spec = validate_spec(spec)
    quality = number(quality, 0, 2, "quality", True)
    f = family(spec["generator"], spec["generator_version"])
    env = environment(spec)
    bones = []
    ids = set()
    shapes = []
    shape_ids = set()
    for d, e in expand(f["bones"], env):
        name = label(d["id"], e)
        parent = label(d.get("parent", ""), e)
        if name in ids or (parent and parent not in ids):
            raise ValueError("Duplicate or unordered bone")
        ids.add(name)
        bones.append(
            {
                "id": name,
                "parent": parent,
                "x": float(ev(d.get("x", 0), e)),
                "y": float(ev(d.get("y", 0), e)),
                "angle": float(ev(d.get("angle", 0), e)),
                "sx": float(ev(d.get("sx", 1), e)),
                "sy": float(ev(d.get("sy", 1), e)),
                "clips": d.get("clips", {}),
                "env": e,
            }
        )
    palette = catalog()["palettes"][spec["palette"]]
    for d, e in expand(f["shapes"], env):
        name = label(d["id"], e)
        bone = label(d.get("bone", "root"), e)
        if name in shape_ids or bone not in ids:
            raise ValueError("Duplicate shape or missing attachment")
        shape_ids.add(name)
        kind = d["kind"]
        n = (16, 32, 64)[quality]

        def num(k, default=0):
            return float(ev(d.get(k, default), e))

        if kind in ("ellipse", "superellipse"):
            points = g.superellipse(num("rx"), num("ry"), num("exponent", 2), n)
        elif kind == "tube":
            p = [tuple(float(ev(v, e)) for v in point) for point in d["curve"]]
            points = g.tube(p, [float(ev(v, e)) for v in d["widths"]], (5, 9, 17)[quality])
        elif kind == "leaf":
            points = g.leaf(num("length"), num("width"), num("curl"), (6, 10, 18)[quality])
        elif kind == "polygon":
            points = [tuple(float(ev(v, e)) for v in point) for point in d["points"]]
        else:
            raise ValueError(f"Unknown shape: {kind}")
        local = g.transform(num("x"), num("y"), num("angle"), num("sx", 1), num("sy", 1))
        points = [g.apply(local, p) for p in points]
        if abs(g.area(points)) < 1e-5:
            raise ValueError(f"Degenerate shape: {name}")
        if g.area(points) < 0:
            points.reverse()
        shapes.append(
            {
                "id": name,
                "bone": bone,
                "points": points,
                "fill": palette[d["fill"]],
                "stroke": palette[d.get("stroke", "ink")],
                "width": num("stroke_width", 2.8),
                "z": int(num("z")),
            }
        )
    if len(bones) > 128 or len(shapes) > 256 or sum(len(s["points"]) for s in shapes) > 15000:
        raise ValueError("Compiled asset exceeds geometry budget")
    shapes.sort(key=lambda s: s["z"])
    measurements = {k: float(ev(v, env)) for k, v in f.get("measurements", {}).items()}
    return Compiled(spec, env, bones, shapes, f.get("ik", []), measurements, quality)


def evaluate_pose(
    asset: Compiled, time_seconds: float = 0, clip: str = "rest"
) -> tuple[dict, dict, list[str]]:
    number(time_seconds, -1e8, 1e8, "time_seconds")
    if clip not in ("rest", "idle", "walk", "celebrate"):
        raise ValueError("Unknown clip")
    local = {}
    world = {}
    warnings = []
    phase = (time_seconds / asset.spec["motion"]["cycle_seconds"]) % 1.0
    for b in asset.bones:
        p = {k: b[k] for k in ("x", "y", "angle", "sx", "sy")}
        env = {**b["env"], "phase": phase}
        for key, expr in b["clips"].get(clip, {}).items():
            value = float(ev(expr, env))
            p[key] = p[key] * value if key in ("sx", "sy") else p[key] + value
        local[b["id"]] = p

    def refresh():
        for b in asset.bones:
            p = local[b["id"]]
            m = g.transform(**p)
            world[b["id"]] = g.compose(world.get(b["parent"], g.IDENTITY), m)

    refresh()
    for chain in asset.ik:
        e = {**asset.env, "phase": phase}
        target_expr = chain.get("targets", {}).get(clip, chain["target"])
        target = tuple(float(ev(v, e)) for v in target_expr)
        upper = chain["upper"]
        lower = chain["lower"]
        foot = chain["foot"]
        b = next(x for x in asset.bones if x["id"] == upper)
        parent = world.get(b["parent"], g.IDENTITY)
        target_local = g.apply(g.inverse(parent), target)
        target_local = (target_local[0] - local[upper]["x"], target_local[1] - local[upper]["y"])
        a, k, clamped = g.two_bone(
            target_local,
            float(ev(chain["length_a"], e)),
            float(ev(chain["length_b"], e)),
            float(chain["bend"]),
        )
        local[upper]["angle"] = a
        local[lower]["angle"] = k
        refresh()
        local[foot]["angle"] = -math.atan2(world[lower][1], world[lower][0])
        refresh()
        if clamped:
            warnings.append(f"{upper}: target exceeded reach and was clamped")
    return local, world, warnings


def validate_geometry(asset: Compiled, thorough: bool = True) -> dict:
    errors = []
    for s in asset.shapes:
        if any(not math.isfinite(v) for p in s["points"] for v in p):
            errors.append(s["id"] + ": nonfinite coordinates")
        if thorough and g.self_intersects(s["points"]):
            errors.append(s["id"] + ": crossing polygon edges")
    _, world, warning = evaluate_pose(asset)
    bbox = g.bounds(g.apply(world[s["bone"]], p) for s in asset.shapes for p in s["points"])
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warning,
        "bones": len(asset.bones),
        "shapes": len(asset.shapes),
        "vertices": sum(len(s["points"]) for s in asset.shapes),
        "bounds": bbox,
        "measurements": asset.measurements,
    }
