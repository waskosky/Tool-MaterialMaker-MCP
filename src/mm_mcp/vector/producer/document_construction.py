"""Retained-source Boolean, offset and repeat sequences for solid artwork."""

from copy import deepcopy

from . import document as v1
from . import document_geometry as geometry

PROFILE = "vector-construction-v1"


def settings(value):
    v1.fields(value, {"kind", "steps"})
    steps = value["steps"]
    if value["kind"] != "construction" or not isinstance(steps, list) or not 1 <= len(steps) <= 4:
        raise ValueError("Construction requires one to four ordered steps")
    for step in steps:
        if not isinstance(step, dict) or type(step.get("enabled")) is not bool:
            raise ValueError("Each construction step needs an enabled boolean")
        kind = step.get("kind")
        if kind == "boolean":
            v1.fields(step, {"kind", "enabled", "operation"})
            if step["operation"] not in ("union", "difference", "intersection", "xor"):
                raise ValueError("Choose union, difference, intersection or xor")
        elif kind == "offset":
            v1.fields(step, {"kind", "enabled", "distance", "join"})
            v1.number(step["distance"], -128, 128)
            if step["join"] not in ("round", "miter", "square"):
                raise ValueError("Choose round, miter or square offset corners")
        elif kind == "repeat":
            v1.fields(step, {"kind", "enabled", "count", "dx", "dy"})
            if type(step["count"]) is not int or not 2 <= step["count"] <= 8:
                raise ValueError("Construction repeat needs two to eight copies")
            for axis in ("dx", "dy"):
                v1.number(step[axis], -2048, 2048)
        else:
            raise ValueError("Unknown installed construction step")
    return value


def component(request, name):
    from .document_v2 import label

    label(name)
    v1.encode(request)
    v1.fields(request, {"source", "settings"})
    source, config = request["source"], settings(request["settings"])
    v1.validate(source)
    if not 1 <= len(source["nodes"]) <= 31 or any(n["locked"] for n in source["nodes"]):
        raise ValueError("Construction source requires 1–31 unprotected parts")
    operands = geometry.operands(source)
    for step in config["steps"]:
        if not step["enabled"]:
            continue
        if step["kind"] == "boolean" and operands:
            paths, paint = operands[0]
            for other, _ in operands[1:]:
                paths = geometry.boolean(paths, other, step["operation"])
            operands = [(paths, paint)]
        elif step["kind"] == "offset":
            operands = [
                (geometry.offset(paths, step["distance"], step["join"]), paint)
                for paths, paint in operands
            ]
        elif step["kind"] == "repeat":
            count = step["count"]
            if (
                len(operands) * count > 64
                or sum(len(p) for paths, _ in operands for p in paths) * count
                > geometry.MAX_VERTICES
            ):
                raise ValueError("Repeated construction exceeds its part/vertex budget")
            operands = [
                (
                    geometry.bounded(
                        [
                            [
                                [
                                    x + round(i * step["dx"] * geometry.GRID),
                                    y + round(i * step["dy"] * geometry.GRID),
                                ]
                                for x, y in path
                            ]
                            for path in paths
                        ]
                    ),
                    paint,
                )
                for i in range(count)
                for paths, paint in operands
            ]
        geometry.bounded([path for paths, _ in operands for path in paths])
    nodes = [
        part
        for i, (paths, paint) in enumerate(operands)
        for part in geometry.parts(paths, paint, f"shape_{i}")
    ]
    if len(nodes) > 64:
        raise ValueError("Construction exceeds 64 component parts")
    # A fully collapsed inset/intersection is a valid empty, editable result.
    if not nodes:
        nodes = [v1.node("empty", "group", {}, name="Empty construction", fill="none")]
    v1.validate({**source, "nodes": nodes})
    return {
        "name": name,
        "nodes": nodes,
        "recipe": {"profile": PROFILE, "request": deepcopy(request)},
    }


def signage():
    from . import document_v2 as v2

    doc = v2.create("blank")
    doc["palette"] = {"accent": "#69E2C2", "ink": "#18364B"}
    doc["nodes"] = [
        v1.node("sign", "group", {}, name="Wayfinder sign"),
        v1.node(
            "plate",
            "rect",
            {"x": 30, "y": 66, "width": 196, "height": 124, "radius": 20},
            parent="sign",
            name="Plate — resize to fit",
        ),
        v1.node(
            "arrow",
            "path",
            {
                "commands": [
                    ["M", 69, 111],
                    ["L", 134, 111],
                    ["L", 134, 91],
                    ["L", 181, 128],
                    ["L", 134, 165],
                    ["L", 134, 145],
                    ["L", 69, 145],
                    ["Z"],
                ]
            },
            parent="sign",
            name="Arrow cutout",
        ),
        v1.node(
            "mount_left",
            "ellipse",
            {"cx": 47, "cy": 128, "rx": 4, "ry": 4},
            parent="sign",
            name="Left mounting hole",
        ),
        v1.node(
            "mount_right",
            "ellipse",
            {"cx": 209, "cy": 128, "rx": 4, "ry": 4},
            parent="sign",
            name="Right mounting hole",
        ),
    ]
    return v2.revise(
        doc,
        [
            {
                "op": "modifier_create",
                "root": "sign",
                "id": "wayfinder",
                "name": "Wayfinder signage",
                "settings": {
                    "kind": "construction",
                    "steps": [
                        {"kind": "boolean", "operation": "difference", "enabled": True},
                        {"kind": "offset", "distance": 0, "join": "round", "enabled": True},
                    ],
                },
            }
        ],
    )
