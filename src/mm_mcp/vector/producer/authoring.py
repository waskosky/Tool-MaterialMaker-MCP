"""Pure bounded plant authoring shared by RAI and pinned authoring companions.

No workspace, network, arbitrary SVG input, executable recipe input or model is
part of this contract. The caller owns project revisions and publication.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy

from . import core, svg
from .artifact import CATALOG_SHA256, PROFILE, generate, structural_digest, validate
from .expression import named_random

SCHEMA = "rai.vector-authoring/v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_VARIANTS = 24
MAX_FRAMES = 16
CLIPS = ("rest", "idle", "walk", "celebrate")
OPERATIONS = ("describe", "create", "revise", "variants", "sweep", "preview")


def encode(value: object, limit: int = MAX_RESULT_BYTES) -> str:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("Vector authoring byte budget exceeded")
    return raw


def controls() -> list[dict]:
    family = core.family("plant")
    result = []
    for name in family["parameter_order"]:
        source = family["parameters"][name]
        result.append(
            {
                "id": "parameters." + name,
                "label": source["label"],
                "type": "integer" if source["type"] == "int" else "number",
                "min": source["min"],
                "max": source["max"],
                "default": source["default"],
            }
        )
    for name, source in family["choices"].items():
        result.append(
            {
                "id": "choices." + name,
                "label": name.replace("_", " ").title(),
                "type": "choice",
                "values": list(source["values"]),
            }
        )
    result.append(
        {
            "id": "palette",
            "label": "Palette",
            "type": "choice",
            "values": list(core.catalog()["palettes"]),
        }
    )
    for name, (lo, hi, default) in core.MOTION.items():
        result.append(
            {
                "id": "motion." + name,
                "label": name.replace("_", " ").title(),
                "type": "number",
                "min": lo,
                "max": hi,
                "default": default,
            }
        )
    result.extend(
        [
            {
                "id": "seed",
                "label": "Geometry seed",
                "type": "integer",
                "min": 0,
                "max": 2147483647,
                "default": 42,
            },
            {
                "id": "quality",
                "label": "Geometry detail",
                "type": "integer",
                "min": 0,
                "max": 2,
                "default": 0,
            },
        ]
    )
    return result


def describe() -> dict:
    # Detect a modified recipe before advertising controls from it.
    generate({"seed": 42})
    return {
        "schema": SCHEMA,
        "operation": "describe",
        "profile": PROFILE,
        "recipe_catalog_sha256": CATALOG_SHA256,
        "controls": controls(),
        "clips": list(CLIPS),
        "limits": {
            "variants": MAX_VARIANTS,
            "frames": MAX_FRAMES,
            "request_bytes": MAX_REQUEST_BYTES,
            "result_bytes": MAX_RESULT_BYTES,
        },
        "publication": "caller-owned reviewed content; no world mutation",
    }


def request_from_artifact(artifact: dict) -> dict:
    validate(artifact)
    spec = artifact["spec"]
    return {
        **{
            key: deepcopy(spec[key])
            for key in ("seed", "parameters", "choices", "palette", "motion")
        },
        "quality": artifact["quality"],
    }


def control_values(artifact: dict) -> dict:
    request = request_from_artifact(artifact)
    result = {}
    for control in controls():
        section, _, name = control["id"].partition(".")
        result[control["id"]] = request[section][name] if name else request[section]
    return result


def validate_locks(locked: object) -> list[str]:
    valid = {control["id"] for control in controls()}
    if (
        not isinstance(locked, list)
        or len(locked) > len(valid)
        or any(not isinstance(key, str) or key not in valid for key in locked)
        or len(set(locked)) != len(locked)
    ):
        raise ValueError("Locks must be unique installed control IDs")
    return sorted(locked)


def _set(request: dict, key: str, value: object) -> None:
    section, _, name = key.partition(".")
    if name:
        request[section][name] = value
    else:
        request[section] = value


def assert_preserved(before: dict, after: dict, locked: list[str]) -> None:
    locked = validate_locks(locked)
    old, new = control_values(before), control_values(after)
    for key in locked:
        if structural_digest(old[key]) != structural_digest(new[key]):
            raise ValueError("Protected control changed: " + key)


def revise(source: dict, values: dict, locked: list[str] | None = None) -> dict:
    locked = validate_locks([] if locked is None else locked)
    request = request_from_artifact(source)
    valid = {control["id"] for control in controls()}
    if not isinstance(values, dict) or not values or set(values) - valid:
        raise ValueError("Provide a nonempty patch of installed control IDs")
    for key, value in values.items():
        _set(request, key, value)
    result = generate(request)
    assert_preserved(source, result, locked)
    return result


def _integer(value: object, lo: int, hi: int, name: str) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer in [{lo}, {hi}]")
    return value


def _range(control: dict, value: object) -> tuple[float, float]:
    if (
        control["type"] not in ("integer", "number")
        or not isinstance(value, dict)
        or set(value) != {"min", "max"}
    ):
        raise ValueError("A variation range needs min/max for a numeric control")
    lo, hi = value["min"], value["max"]
    for item in (lo, hi):
        core.number(
            item, control["min"], control["max"], control["id"], control["type"] == "integer"
        )
    if lo > hi:
        raise ValueError("Variation range is reversed")
    return lo, hi


def variants(
    source: dict,
    count: int = 12,
    seed: int = 100,
    locked: list[str] | None = None,
    ranges: dict | None = None,
) -> list[dict]:
    _integer(count, 1, MAX_VARIANTS, "count")
    _integer(seed, 0, 2147483647 - count + 1, "variation seed")
    locked = validate_locks([] if locked is None else locked)
    base = request_from_artifact(source)
    old = control_values(source)
    definitions = {control["id"]: control for control in controls()}
    ranges = {} if ranges is None else ranges
    if not isinstance(ranges, dict) or set(ranges) - definitions.keys():
        raise ValueError("Unknown variation control")
    for key, value in ranges.items():
        if key in locked or key in ("seed", "quality"):
            raise ValueError("Cannot vary a locked control, geometry seed or detail range")
        _range(definitions[key], value)
    result = []
    for index in range(count):
        sampling_seed = seed + index
        candidate = generate(
            {"seed": sampling_seed, "quality": base["quality"], "motion": base["motion"]}
        )
        request = request_from_artifact(candidate)
        for key in locked:
            _set(request, key, old[key])
        for key, bounds in ranges.items():
            lo, hi = _range(definitions[key], bounds)
            r = named_random(sampling_seed, SCHEMA, key)
            value = lo + (hi - lo) * r
            if definitions[key]["type"] == "integer":
                value = min(int(hi), int(lo) + math.floor((hi - lo + 1) * r))
            _set(request, key, value)
        candidate = generate(request)
        assert_preserved(source, candidate, locked)
        result.append(candidate)
    return result


def _result(operation: str, assets: list[dict], source: dict | None = None) -> dict:
    result = {"schema": SCHEMA, "operation": operation, "profile": PROFILE, "assets": assets}
    if source is not None:
        result["source_content_sha256"] = source["integrity"]["content_sha256"]
    return result


def _preview(result: dict, source: dict, clip: str, time: float, frame_count: int) -> None:
    validate(source)
    if clip not in CLIPS:
        raise ValueError("Unknown installed motion clip")
    core.number(time, 0, 3600, "preview time")
    _integer(frame_count, 1, MAX_FRAMES, "frame_count")
    asset = core.compile_asset(source["spec"], source["quality"])
    cycle = source["spec"]["motion"]["cycle_seconds"]
    times = (
        [time] if frame_count == 1 else [time + cycle * i / frame_count for i in range(frame_count)]
    )
    result["frames"] = [{"time": t, "svg": svg.frame_svg(asset, t, clip)} for t in times]
    result["clip"] = clip
    result["cycle_seconds"] = cycle
    result["preview_svg"] = (
        result["frames"][0]["svg"]
        if frame_count == 1
        else svg.contact_sheet(
            [source["spec"]] * frame_count,
            times=times,
            clip=clip,
            quality=source["quality"],
            labels=[f"Phase {i + 1}/{frame_count}" for i in range(frame_count)],
            title="Plant motion",
        )
    )


def execute(request: dict) -> dict:
    encode(request, MAX_REQUEST_BYTES)
    if not isinstance(request, dict) or request.get("operation") not in OPERATIONS:
        raise ValueError("Unknown vector authoring operation")
    operation = request["operation"]
    fields = {
        "describe": set(),
        "create": {"request"},
        "revise": {"source", "values", "locked"},
        "variants": {"source", "count", "seed", "locked", "ranges"},
        "sweep": {"source", "control", "values", "locked"},
        "preview": {"source", "clip", "time", "frame_count"},
    }[operation] | {"operation"}
    if set(request) - fields:
        raise ValueError("Unknown vector authoring fields")
    if operation == "describe":
        result = describe()
    elif operation == "create":
        result = _result(operation, [generate(request.get("request", {}))])
        _preview(result, result["assets"][0], "rest", 0, 1)
    else:
        source = request["source"]
        validate(source)
        if operation == "revise":
            result = _result(
                operation, [revise(source, request["values"], request.get("locked"))], source
            )
            _preview(result, result["assets"][0], "rest", 0, 1)
        elif operation == "variants":
            assets = variants(
                source,
                request.get("count", 12),
                request.get("seed", 100),
                request.get("locked"),
                request.get("ranges"),
            )
            result = _result(operation, assets, source)
            result["unique_count"] = len({a["integrity"]["content_sha256"] for a in assets})
            result["preview_svg"] = svg.contact_sheet(
                [a["spec"] for a in assets],
                quality=source["quality"],
                labels=[f"Candidate {i + 1}" for i in range(len(assets))],
                title="Plant variations",
            )
        elif operation == "sweep":
            values = request["values"]
            if not isinstance(values, list) or not 1 <= len(values) <= 12:
                raise ValueError("A sweep needs 1–12 values")
            assets = [
                revise(source, {request["control"]: v}, request.get("locked")) for v in values
            ]
            result = _result(operation, assets, source)
            result["preview_svg"] = svg.contact_sheet(
                [a["spec"] for a in assets],
                quality=source["quality"],
                labels=[f"{request['control']}: {v}" for v in values],
                title="Plant control comparison",
            )
        else:
            result = _result(operation, [deepcopy(source)], source)
            _preview(
                result,
                source,
                request.get("clip", "idle"),
                request.get("time", 0),
                request.get("frame_count", 8),
            )
    encode(result)
    return result
