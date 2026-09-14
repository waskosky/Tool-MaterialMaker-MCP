"""Bounded inert plant artifacts; only checked-in trusted recipes are executable."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .portable_digest import PROFILE_ID, structural_digest

from . import core

SCHEMA = "rai.vector-asset/v1"
PROFILE = "vector-plant-v1"
MAX_BYTES = 64 * 1024
MAX_BONES = 128
MAX_SHAPES = 128
MAX_VERTICES = 8192
CATALOG_PATH = Path(__file__).parent / "data/catalog.json"
CATALOG_SHA256 = "5ed1ad88a520f3b467abe6713b51c261ceddfe384bbac475da192cea0d3682af"
REQUEST_FIELDS = {"seed", "parameters", "choices", "palette", "motion", "quality"}


def render(value: Any) -> str:
    structural_digest(value)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Vector artifact exceeds 64 KiB")
    return raw


def _payload(spec: dict, quality: int) -> dict:
    if sha256(CATALOG_PATH.read_bytes()).hexdigest() != CATALOG_SHA256:
        raise ValueError("Bundled recipe catalog differs from its frozen identity")
    core.validate_spec(spec)
    if spec["generator"] != "plant":
        raise ValueError("Only the installed vector-plant-v1 consumer profile is supported")
    asset = core.compile_asset(spec, quality)
    metrics = {
        "bones": len(asset.bones),
        "shapes": len(asset.shapes),
        "vertices": sum(len(shape["points"]) for shape in asset.shapes),
    }
    if not (
        0 < metrics["bones"] <= MAX_BONES
        and 0 < metrics["shapes"] <= MAX_SHAPES
        and 0 < metrics["vertices"] <= MAX_VERTICES
    ):
        raise ValueError("Vector geometry exceeds the installed profile budget")
    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "recipe_catalog_sha256": CATALOG_SHA256,
        "quality": asset.quality,
        "spec": deepcopy(spec),
        "metrics": metrics,
    }


def generate(request: dict) -> dict:
    render(request)
    if not isinstance(request, dict) or set(request) - REQUEST_FIELDS:
        raise ValueError("Unknown vector request fields")
    options = deepcopy(request)
    quality = options.pop("quality", 0)
    payload = _payload(core.create_spec(generator="plant", **options), quality)
    payload["integrity"] = {
        "algorithm": "sha-256",
        "canonicalization": PROFILE_ID,
        "content_sha256": structural_digest(payload),
    }
    render(payload)
    return payload


def validate(artifact: dict) -> None:
    render(artifact)
    fields = {
        "schema",
        "profile",
        "recipe_catalog_sha256",
        "quality",
        "spec",
        "metrics",
        "integrity",
    }
    if not isinstance(artifact, dict) or set(artifact) != fields:
        raise ValueError("Unknown vector artifact fields")
    expected = _payload(artifact["spec"], artifact["quality"])
    expected["integrity"] = {
        "algorithm": "sha-256",
        "canonicalization": PROFILE_ID,
        "content_sha256": structural_digest(expected),
    }
    # Structural comparison accepts Godot's integral JSON floats while rejecting
    # booleans and differences in catalog, geometry budget or resolved controls.
    if structural_digest(artifact) != structural_digest(expected):
        raise ValueError("Vector artifact identity or semantics differ from the trusted recipes")
