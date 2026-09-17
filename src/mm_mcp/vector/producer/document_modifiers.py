"""Bounded, editable repetition recipes; generated geometry is never source truth."""

import math
from copy import deepcopy
from hashlib import sha256

from . import document as v1

PROFILE = "vector-repeat-v1"


def settings(value):
    if not isinstance(value, dict) or value.get("kind") not in ("mirror", "linear", "radial"):
        raise ValueError("Choose mirror, linear or radial repetition")
    kind = value["kind"]
    if kind == "mirror":
        v1.fields(value, {"kind", "axis", "pivot"})
        if value["axis"] not in ("x", "y"):
            raise ValueError("Mirror axis must be x or y")
    else:
        extra = {"dx", "dy"} if kind == "linear" else {"pivot", "angle"}
        v1.fields(value, {"kind", "count", "seed", "jitter"} | extra)
        if type(value["count"]) is not int or not 2 <= value["count"] <= 16:
            raise ValueError("Use 2–16 copies")
        if type(value["seed"]) is not int or not 0 <= value["seed"] <= 2147483647:
            raise ValueError("Use an integer seed between 0 and 2147483647")
        v1.number(value["jitter"], 0, 64)
        for key in extra - {"pivot"}:
            v1.number(
                value[key], -360 if key == "angle" else -2048, 360 if key == "angle" else 2048
            )
    if "pivot" in value:
        if not isinstance(value["pivot"], list) or len(value["pivot"]) != 2:
            raise ValueError("Use a two-coordinate pivot")
        for number in value["pivot"]:
            v1.number(number)
    return value


def _reflect(part, axis):
    """Conjugate each local transform by reflection, retaining positive scales."""
    n = deepcopy(part)
    n["transform"][axis] *= -1
    n["transform"]["rotation"] *= -1
    g = n["geometry"]
    if n["kind"] == "rect":
        g[axis] = -g[axis] - g["width" if axis == "x" else "height"]
    elif n["kind"] == "ellipse":
        g["c" + axis] *= -1
    elif n["kind"] == "path":
        for command in g["commands"]:
            for i in range(1 if axis == "x" else 2, len(command), 2):
                command[i] *= -1
    return n


def _noise(seed, copy, axis):
    raw = sha256(f"vector-repeat-v1/{seed}/{copy}/{axis}".encode()).digest()
    return int.from_bytes(raw[:4], "big") / 4294967295 * 2 - 1


def component(request, name):
    from .document_v2 import label

    label(name)
    v1.encode(request)
    v1.fields(request, {"source", "settings"})
    source, params = request["source"], settings(request["settings"])
    v1.validate(source)
    if not 1 <= len(source["nodes"]) <= 31 or any(n["locked"] for n in source["nodes"]):
        raise ValueError("Modifier source requires 1–31 unprotected parts")
    # The source owns its palette; generated literal paints cannot accidentally
    # bind to another artwork's palette during library import.
    count = 2 if params["kind"] == "mirror" else params["count"]
    if count * (len(source["nodes"]) + 1) > 64:
        raise ValueError(
            "Modifier expansion exceeds 64 component parts; reduce copies or source detail"
        )
    nodes = []
    for i in range(count):
        root = "copy_" + str(i)
        transform = dict(v1.TRANSFORM)
        kind = params["kind"]
        if kind == "mirror" and i:
            transform[params["axis"]] = 2 * params["pivot"][0 if params["axis"] == "x" else 1]
        elif kind == "linear":
            transform.update(x=params["dx"] * i, y=params["dy"] * i)
        elif kind == "radial":
            angle = params["angle"] * i
            x, y = params["pivot"]
            c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            transform.update(x=x - c * x + s * y, y=y - s * x - c * y, rotation=angle)
        if kind != "mirror" and i:
            for axis in ("x", "y"):
                transform[axis] += _noise(params["seed"], i, axis) * params["jitter"]
        transform = {k: round(v, 8) for k, v in transform.items()}
        nodes.append(
            v1.node(root, "group", {}, name=f"Copy {i + 1}", fill="none", transform=transform)
        )
        mapping = {
            n["id"]: "m_" + sha256(f"{i}/{n['id']}".encode()).hexdigest()[:24]
            for n in source["nodes"]
        }
        for part in source["nodes"]:
            n = _reflect(part, params["axis"]) if kind == "mirror" and i else deepcopy(part)
            for paint in ("fill", "stroke"):
                if n[paint].startswith("@"):
                    n[paint] = source["palette"][n[paint][1:]]
            n.update(id=mapping[part["id"]], parent=mapping.get(part["parent"], root))
            nodes.append(n)
    v1.validate({**source, "nodes": nodes})
    return {
        "name": name,
        "nodes": nodes,
        "recipe": {"profile": PROFILE, "request": deepcopy(request)},
    }


def capture(document, nodes):
    """Capture effective shapes; the enclosing instance retains root placement."""
    from .document_v2 import resolved

    copied = []
    for part in nodes:
        n = resolved(part, document["styles"])
        n["locked"] = False
        for paint in ("fill", "stroke"):
            if n[paint].startswith("@"):
                n[paint] = document["palette"][n[paint][1:]]
        copied.append(n)
    return {
        "schema": v1.SCHEMA,
        "canvas": deepcopy(document["canvas"]),
        "palette": deepcopy(document["palette"]),
        "nodes": copied,
    }


def revise(document, operation):
    from . import document_v2 as v2

    op = operation["op"]
    if op == "modifier_create":
        v1.fields(operation, {"op", "root", "id", "name", "settings"})
        # Existing component conversion enforces locks, hierarchy and rig guards.
        document = v2.revise(
            document,
            [{"op": "component_create", **{k: operation[k] for k in ("root", "id", "name")}}],
        )
        definition = document["components"][operation["id"]]
        request = {
            "source": capture(document, definition["nodes"]),
            "settings": operation["settings"],
        }
    else:
        v1.fields(operation, {"op", "id", "settings" if op == "modifier_update" else "operations"})
        v1.identifier(operation["id"])
        definition = document["components"].get(operation["id"])
        if not definition or not definition["recipe"] or definition["recipe"]["profile"] != PROFILE:
            raise ValueError("Choose a procedural repetition component")
        request = deepcopy(definition["recipe"]["request"])
        if op == "modifier_update":
            request["settings"] = operation["settings"]
        else:
            edits = operation["operations"]
            if not isinstance(edits, list) or any(
                not isinstance(e, dict)
                or e.get("op") not in {"add", "update", "delete", "order", "palette"}
                for e in edits
            ):
                raise ValueError(
                    "Modifier source edits support add/update/delete/order/palette only"
                )
            request["source"] = v1.revise(request["source"], edits)
    document["components"][operation["id"]] = component(request, definition["name"])
    return document


def mask(document):
    """Opaque linear grayscale silhouette: white coverage on black, at rest."""
    from .document_v2 import expand

    source = expand(document)
    source["palette"] = {"mask": "#FFFFFF"}
    for n in source["nodes"]:
        for paint in ("fill", "stroke"):
            if n[paint] != "none":
                n[paint] = "#FFFFFF"
    rendered = v1.render(source)
    start = rendered.index(">") + 1
    w, h = source["canvas"]["width"], source["canvas"]["height"]
    return rendered[:start] + f'<rect width="{w}" height="{h}" fill="#000000"/>' + rendered[start:]


def emblem():
    from . import document_v2 as v2

    doc = v2.create("blank")
    doc["palette"] = {"accent": "#F1B85A", "ink": "#19394D"}
    doc["nodes"] = [
        v1.node(
            "ray",
            "path",
            {"commands": [["M", 117, 75], ["L", 128, 29], ["L", 139, 75], ["Z"]]},
            name="Emblem ray",
        )
    ]
    doc = v2.revise(
        doc,
        [
            {
                "op": "modifier_create",
                "id": "rays",
                "root": "ray",
                "name": "Radial emblem",
                "settings": {
                    "kind": "radial",
                    "count": 8,
                    "pivot": [128, 128],
                    "angle": 45,
                    "seed": 42,
                    "jitter": 0,
                },
            }
        ],
    )
    doc["nodes"].extend(
        [
            v1.node(
                "ring",
                "ellipse",
                {"cx": 128, "cy": 128, "rx": 44, "ry": 44},
                fill="none",
                stroke="@accent",
                stroke_width=10,
            ),
            v1.node(
                "center",
                "path",
                {
                    "commands": [
                        ["M", 128, 108],
                        ["L", 147, 128],
                        ["L", 128, 148],
                        ["L", 109, 128],
                        ["Z"],
                    ]
                },
                fill="@accent",
            ),
        ]
    )
    return doc
