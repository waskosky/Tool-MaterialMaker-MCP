"""Bounded, engine-neutral vector documents. No SVG input or executable content.

The browser and agents submit the same atomic edits. All rendering comes from
this validated data contract; consumers receive inert, reproducible SVG.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from html import escape

from .artifact import structural_digest

SCHEMA = "rai.vector-document/v1"
PROFILE = "vector-document-v1"
MAX_BYTES = 128 * 1024
MAX_NODES = 128
MAX_COMMANDS = 1024
ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,47}\Z")
COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
NODE_FIELDS = {
    "id",
    "name",
    "kind",
    "parent",
    "visible",
    "locked",
    "transform",
    "geometry",
    "fill",
    "stroke",
    "stroke_width",
    "opacity",
}
TRANSFORM = {"x": 0, "y": 0, "rotation": 0, "scale_x": 1, "scale_y": 1}


def encode(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(raw.encode()) > MAX_BYTES:
        raise ValueError("Vector document/request exceeds 128 KiB")
    return raw


def fields(value, required, optional=()):
    if (
        not isinstance(value, dict)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("Unknown or missing vector fields")


def number(value, low=-8192, high=8192):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Vector number outside its finite bound")


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("Invalid vector identifier")


def color(value, palette):
    if not isinstance(value, str) or not (
        value == "none"
        or COLOR.fullmatch(value)
        or (value.startswith("@") and value[1:] in palette)
    ):
        raise ValueError("Use a solid color, none, or an existing @palette token")


def node(node_id, kind, geometry, *, name=None, **values):
    return {
        "id": node_id,
        "name": name or node_id.replace("_", " ").title(),
        "kind": kind,
        "parent": None,
        "visible": True,
        "locked": False,
        "transform": dict(TRANSFORM),
        "geometry": geometry,
        "fill": "@accent",
        "stroke": "none",
        "stroke_width": 0,
        "opacity": 1,
        **values,
    }


def validate(document):
    encode(document)
    fields(document, {"schema", "canvas", "palette", "nodes"})
    if document["schema"] != SCHEMA:
        raise ValueError("Unknown vector document schema")
    fields(document["canvas"], {"width", "height"})
    for value in document["canvas"].values():
        number(value, 16, 2048)
    palette = document["palette"]
    if not isinstance(palette, dict) or not 1 <= len(palette) <= 16:
        raise ValueError("Use 1–16 named palette colors")
    for key, value in palette.items():
        identifier(key)
        if not isinstance(value, str) or not COLOR.fullmatch(value):
            raise ValueError("Palette colors must be six-digit hex colors")
    nodes = document["nodes"]
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise ValueError("Use at most 128 vector nodes")
    index, commands = {}, 0
    for item in nodes:
        fields(item, NODE_FIELDS)
        identifier(item["id"])
        if item["id"] in index:
            raise ValueError("Duplicate vector node ID")
        index[item["id"]] = item
        if (
            not isinstance(item["name"], str)
            or not 1 <= len(item["name"]) <= 80
            or any(ord(c) < 32 for c in item["name"])
        ):
            raise ValueError("Use a short visible part name")
        if type(item["visible"]) is not bool or type(item["locked"]) is not bool:
            raise ValueError("Visibility and protection must be booleans")
        fields(item["transform"], TRANSFORM)
        for key, value in item["transform"].items():
            number(
                value, -3600 if key == "rotation" else -8192, 3600 if key == "rotation" else 8192
            )
            if key.startswith("scale_"):
                number(value, 0.01, 100)
        number(item["opacity"], 0, 1)
        number(item["stroke_width"], 0, 128)
        color(item["fill"], palette)
        color(item["stroke"], palette)
        geometry, kind = item["geometry"], item["kind"]
        if kind == "group":
            fields(geometry, ())
        elif kind == "rect":
            fields(geometry, {"x", "y", "width", "height", "radius"})
            for key, value in geometry.items():
                number(value, 0 if key in ("width", "height", "radius") else -8192)
        elif kind == "ellipse":
            fields(geometry, {"cx", "cy", "rx", "ry"})
            for key, value in geometry.items():
                number(value, 0 if key in ("rx", "ry") else -8192)
        elif kind == "path":
            fields(geometry, {"commands"})
            path = geometry["commands"]
            if not isinstance(path, list) or not 2 <= len(path) <= 256:
                raise ValueError("Paths require 2–256 typed commands")
            open_path = False
            for i, command in enumerate(path):
                if not isinstance(command, list) or not command or not isinstance(command[0], str):
                    raise ValueError("Use numeric M, L, Q, C, Z commands")
                op = command[0]
                length = {"M": 3, "L": 3, "Q": 5, "C": 7, "Z": 1}.get(op)
                if (
                    length != len(command)
                    or (i == 0 and op != "M")
                    or (not open_path and op != "M")
                ):
                    raise ValueError("Invalid path command order/arity")
                open_path = op != "Z"
                for value in command[1:]:
                    number(value)
            commands += len(path)
        else:
            raise ValueError("Use rect, ellipse, path or group")
    if commands > MAX_COMMANDS:
        raise ValueError("Document exceeds 1024 path commands")
    for item in nodes:
        seen, parent = {item["id"]}, item["parent"]
        while parent is not None:
            identifier(parent)
            if parent not in index or index[parent]["kind"] != "group" or parent in seen:
                raise ValueError("Parents must be existing groups without cycles")
            seen.add(parent)
            if len(seen) > 8:
                raise ValueError("Vector hierarchy exceeds eight levels")
            parent = index[parent]["parent"]
    return document


def _protected(document):
    """Protect geometry, hierarchy, transforms, visibility and referenced colors.

    This is an edit lock, not a guarantee against overlap by new artwork.
    """
    index = {n["id"]: n for n in document["nodes"]}
    protected = {n["id"] for n in index.values() if n["locked"]}
    for item in index.values():
        parent = item["parent"]
        while parent:
            if parent in protected:
                protected.add(item["id"])
                break
            parent = index[parent]["parent"]
    ancestors = set()
    for key in protected:
        parent = index[key]["parent"]
        while parent:
            ancestors.add(parent)
            parent = index[parent]["parent"]
    return protected | ancestors


def assert_preserved(before, after):
    validate(before)
    validate(after)
    first = {n["id"]: n for n in before["nodes"]}
    second = {n["id"]: n for n in after["nodes"]}
    # Locks can only change through a separate, explicit set_lock transaction.
    if {n["id"] for n in first.values() if n["locked"]} != {
        n["id"] for n in second.values() if n["locked"]
    }:
        raise ValueError("Protected state requires a separate set_lock edit")
    protected = _protected(before)
    if protected != _protected(after):
        raise ValueError("Protected subtree membership changed")
    if protected and before["canvas"] != after["canvas"]:
        raise ValueError("Protected artwork prevents canvas changes")
    for key in protected:
        if first[key] != second.get(key):
            raise ValueError("Protected part or ancestor changed: " + key)
        for paint in (first[key]["fill"], first[key]["stroke"]):
            if paint.startswith("@") and before["palette"][paint[1:]] != after["palette"].get(
                paint[1:]
            ):
                raise ValueError("Protected part uses this palette color")
    # Moving a protected part in the painter order is also an edit.
    old_order = [n["id"] for n in before["nodes"]]
    new_order = [n["id"] for n in after["nodes"] if n["id"] in first]
    for key in protected:
        if [k for k in old_order[: old_order.index(key)] if k in second] != new_order[
            : new_order.index(key)
        ]:
            raise ValueError("Protected part cannot be reordered")


def revise(source, operations):
    validate(source)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        raise ValueError("Use 1–32 atomic vector edits")
    encode(operations)
    out = deepcopy(source)
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Vector edit must be an object")
        op = operation.get("op")
        index = {n["id"]: n for n in out["nodes"]}
        if op == "add":
            fields(operation, {"op", "node"})
            out["nodes"].append(deepcopy(operation["node"]))
        elif op in ("update", "delete", "set_lock"):
            required = {"op", "id"} | (
                {"changes"} if op == "update" else {"locked"} if op == "set_lock" else set()
            )
            fields(operation, required)
            identifier(operation["id"])
            if operation["id"] not in index:
                raise ValueError("Unknown part ID")
            item = index[operation["id"]]
            if op == "update":
                fields(operation["changes"], (), NODE_FIELDS - {"id", "locked"})
                item.update(deepcopy(operation["changes"]))
            elif op == "set_lock":
                if len(operations) != 1 or type(operation["locked"]) is not bool:
                    raise ValueError("set_lock must be a separate transaction")
                item["locked"] = operation["locked"]
                return validate(out)
            else:
                deleted = {item["id"]}
                for _ in range(8):
                    deleted.update(n["id"] for n in out["nodes"] if n["parent"] in deleted)
                out["nodes"] = [n for n in out["nodes"] if n["id"] not in deleted]
        elif op == "palette":
            fields(operation, {"op", "colors"})
            if not isinstance(operation["colors"], dict):
                raise ValueError("Palette edit must contain colors")
            out["palette"].update(operation["colors"])
        elif op == "canvas":
            fields(operation, {"op", "canvas"})
            out["canvas"] = deepcopy(operation["canvas"])
        elif op == "order":
            fields(operation, {"op", "ids"})
            if (
                not isinstance(operation["ids"], list)
                or any(not isinstance(k, str) for k in operation["ids"])
                or len(operation["ids"]) != len(index)
                or set(operation["ids"]) != set(index)
            ):
                raise ValueError("Order must contain every current node exactly once")
            out["nodes"] = [index[key] for key in operation["ids"]]
        elif op == "replace":
            fields(operation, {"op", "document"})
            out = deepcopy(operation["document"])
        else:
            raise ValueError("Unknown vector edit")
        validate(out)
        assert_preserved(source, out)
    return out


def render(document):
    validate(document)
    palette = document["palette"]

    def fmt(value):
        return "0" if value == 0 else format(value, ".12g")

    def paint(value):
        return palette[value[1:]] if value.startswith("@") else value

    def children(parent):
        output = []
        for item in document["nodes"]:
            if item["parent"] != parent:
                continue
            t, g = item["transform"], item["geometry"]
            attrs = (
                f'id="{item["id"]}" data-part="{item["id"]}" '
                f'transform="translate({fmt(t["x"])} {fmt(t["y"])}) '
                f"rotate({fmt(t['rotation'])}) "
                f'scale({fmt(t["scale_x"])} {fmt(t["scale_y"])})" '
                f'opacity="{fmt(item["opacity"])}" fill="{paint(item["fill"])}" '
                f'stroke="{paint(item["stroke"])}" stroke-width="{fmt(item["stroke_width"])}" '
                f'stroke-linejoin="round" stroke-linecap="round"'
            )
            if not item["visible"]:
                attrs += ' display="none"'
            title = "<title>" + escape(item["name"]) + "</title>"
            kind = item["kind"]
            if kind == "group":
                output.append(f"<g {attrs}>{title}{children(item['id'])}</g>")
            elif kind == "path":
                path = " ".join(c[0] + " ".join(fmt(v) for v in c[1:]) for c in g["commands"])
                output.append(f'<path {attrs} d="{path}">{title}</path>')
            else:
                geometry = " ".join(
                    f'{"rx" if k == "radius" else k}="{fmt(g[k])}"'
                    for k in (
                        ("x", "y", "width", "height", "radius")
                        if kind == "rect"
                        else ("cx", "cy", "rx", "ry")
                    )
                )
                output.append(f"<{kind} {attrs} {geometry}>{title}</{kind}>")
        return "".join(output)

    w, h = (fmt(document["canvas"][k]) for k in ("width", "height"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">{children(None)}</svg>'
    )


def describe():
    return {
        "schema": "rai.vector-document-authoring/v1",
        "profile": PROFILE,
        "document_schema": SCHEMA,
        "operations": ["describe", "create", "revise", "preview", "variants"],
        "edits": ["add", "update", "delete", "set_lock", "palette", "canvas", "order", "replace"],
        "templates": ["blank", "power_cell", "medical_kit", "beacon"],
        "limits": {
            "nodes": MAX_NODES,
            "path_commands": MAX_COMMANDS,
            "depth": 8,
            "bytes": MAX_BYTES,
            "variants": 8,
        },
        "lock_policy": (
            "Protect part/subtree, ancestors and referenced palette colors. "
            "Unlock separately. New artwork may overlap locked parts."
        ),
        "capabilities": {
            "typed_paths": ["M", "L", "Q", "C", "Z"],
            "svg_input": False,
            "raster_tracing": False,
            "animation": False,
        },
    }


def execute(request):
    encode(request)
    fields(
        request,
        {"profile", "operation"},
        {"document", "template", "source", "operations", "palettes"},
    )
    if request["profile"] != PROFILE:
        raise ValueError("Unknown vector profile")
    op = request["operation"]
    allowed = {
        "describe": set(),
        "create": {"document", "template"},
        "revise": {"source", "operations"},
        "preview": {"source"},
        "variants": {"source", "palettes"},
    }.get(op)
    if allowed is None or set(request) - {"profile", "operation"} - allowed:
        raise ValueError("Unknown document operation or fields")
    if op == "describe":
        return {**describe(), "operation": op}
    if op == "create":
        if "document" in request and "template" in request:
            raise ValueError("Choose a document or template")
        from .document_templates import create

        documents = [
            deepcopy(validate(request["document"]))
            if "document" in request
            else create(request.get("template", "blank"))
        ]
    elif op == "revise":
        documents = [revise(request["source"], request["operations"])]
    elif op == "preview":
        documents = [deepcopy(validate(request["source"]))]
    else:
        palettes = request["palettes"]
        if not isinstance(palettes, list) or not 1 <= len(palettes) <= 8:
            raise ValueError("Provide 1–8 explicit candidate palettes")
        documents = [revise(request["source"], [{"op": "palette", "colors": p}]) for p in palettes]
    return {
        "schema": "rai.vector-document-authoring/v1",
        "profile": PROFILE,
        "operation": op,
        "documents": documents,
        "previews": [{"svg": render(d), "sha256": structural_digest(d)} for d in documents],
        "unique_count": len({structural_digest(d) for d in documents}),
    }
