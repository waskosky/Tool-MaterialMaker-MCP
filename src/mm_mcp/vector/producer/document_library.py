"""Inert component/style snapshots and one explicit editable recipe adapter."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache

from . import document as v1
from .geometry import apply

LIBRARY_SCHEMA = "rai.vector-library-snapshot/v1"


@lru_cache(maxsize=16)
def _recipe_nodes(encoded):
    from . import artifact, core

    request = json.loads(encoded)
    if request.get("quality", 0) != 0:
        raise ValueError("The editable canvas plant adapter uses bounded detail zero")
    generated = artifact.generate(request)
    asset = core.compile_asset(generated["spec"], 0)
    _, matrices, _ = core.evaluate_pose(asset, 0, "rest")
    nodes = []
    for shape in asset.shapes:
        points = [apply(matrices[shape["bone"]], point) for point in shape["points"]]
        # Existing plant coordinates are rooted at (0,0) and grow upward. The
        # component has the same fixed 340x410 artboard as the recipe preview.
        commands = [
            ["M" if i == 0 else "L", round(x + 170, 8), round(y + 380, 8)]
            for i, (x, y) in enumerate(points)
        ] + [["Z"]]
        nodes.append(
            v1.node(
                shape["id"],
                "path",
                {"commands": commands},
                fill=shape["fill"],
                stroke=shape["stroke"],
                stroke_width=shape["width"],
            )
        )
    v1.validate(
        {
            "schema": v1.SCHEMA,
            "canvas": {"width": 340, "height": 410},
            "palette": {"accent": "#FFFFFF"},
            "nodes": nodes,
        }
    )
    return nodes


def recipe_component(request, name):
    from .document_v2 import label

    label(name)
    v1.encode(request)
    if not isinstance(request, dict):
        raise ValueError("Recipe parameters must be an object")
    encoded = json.dumps(request, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return {
        "name": name,
        "nodes": deepcopy(_recipe_nodes(encoded)),
        "recipe": {"profile": "plant-rest-v1", "request": deepcopy(request)},
    }


def snapshot(document, kind, key, name):
    from . import document_v2 as v2

    v2.validate(document)
    v2.label(name)
    if kind not in ("component", "style") or key not in document[kind + "s"]:
        raise ValueError("Choose an existing component or style")
    definition = deepcopy(document[kind + "s"][key])
    paints = []
    styles = {}
    if kind == "style":
        paints.extend((definition["fill"], definition["stroke"]))
    else:
        for node in definition["nodes"]:
            paints.extend((node["fill"], node["stroke"]))
            if node.get("style"):
                styles[node["style"]] = deepcopy(document["styles"][node["style"]])
        for style in styles.values():
            paints.extend((style["fill"], style["stroke"]))
    used = {p[1:] for p in paints if p.startswith("@")}
    palette = {k: document["palette"][k] for k in sorted(used)}
    result = {
        "schema": LIBRARY_SCHEMA,
        "kind": kind,
        "name": name,
        "definition": definition,
        "styles": styles,
        "palette": palette,
    }
    validate_snapshot(result)
    return result


def validate_snapshot(value):
    from . import document_v2 as v2

    v1.encode(value)
    v1.fields(value, {"schema", "kind", "name", "definition", "styles", "palette"})
    if value["schema"] != LIBRARY_SCHEMA or value["kind"] not in ("component", "style"):
        raise ValueError("Unknown library snapshot")
    v2.label(value["name"])
    document = v2.create("blank")
    if not isinstance(value["palette"], dict) or not isinstance(value["styles"], dict):
        raise ValueError("Snapshot colors and styles must be named maps")
    document["palette"] = deepcopy(value["palette"]) or {"accent": "#FFFFFF"}
    document["styles"] = deepcopy(value["styles"])
    if value["kind"] == "component":
        document["components"]["snapshot"] = deepcopy(value["definition"])
        document["nodes"] = [
            v1.node("snapshot_instance", "instance", {"component": "snapshot"}, fill="none")
        ]
    else:
        if value["styles"]:
            raise ValueError("A style snapshot cannot contain other styles")
        document["styles"]["snapshot"] = deepcopy(value["definition"])
    v2.validate(document)
    return value


def _free(base, used):
    base = base[:40]
    if base not in used:
        return base
    for number in range(1, 130):
        key = f"{base}_{number}"
        if key not in used:
            return key
    raise ValueError("No bounded unused identifier")


def import_edits(document, value, *, x=0, y=0, target=None):
    from . import document_v2 as v2

    v2.validate(document)
    validate_snapshot(value)
    v1.number(x)
    v1.number(y)
    colors = deepcopy(document["palette"])
    palette_map = {}
    for key, paint in value["palette"].items():
        existing = next((k for k, v in colors.items() if v.lower() == paint.lower()), None)
        mapped = existing or _free(key, colors)
        colors.setdefault(mapped, paint)
        palette_map[key] = mapped
    if len(colors) > 16:
        raise ValueError("This import would exceed 16 shared colors; consolidate colors first")

    def recolor(definition):
        result = deepcopy(definition)
        for paint in ("fill", "stroke"):
            if result[paint].startswith("@"):
                result[paint] = "@" + palette_map[result[paint][1:]]
        return result

    operations = [{"op": "palette", "colors": colors}]
    styles = deepcopy(document["styles"])
    style_map = {}
    for key, style in value["styles"].items():
        mapped = _free(key, styles)
        styles[mapped] = recolor(style)
        style_map[key] = mapped
        operations.append({"op": "style_set", "id": mapped, "style": styles[mapped]})
    if value["kind"] == "style":
        key = _free("saved_style", styles)
        operations.append({"op": "style_set", "id": key, "style": recolor(value["definition"])})
        if target is not None:
            v1.identifier(target)
            operations.append({"op": "update", "id": target, "changes": {"style": key}})
        selected = target
    else:
        key = _free("saved_component", document["components"])
        component = deepcopy(value["definition"])
        component["name"] = value["name"]
        component["nodes"] = [recolor(n) for n in component["nodes"]]
        for node in component["nodes"]:
            if node.get("style"):
                node["style"] = style_map[node["style"]]
        operations.append({"op": "component_set", "id": key, "component": component})
        selected = _free("saved_instance", {n["id"] for n in document["nodes"]})
        instance = v1.node(
            selected,
            "instance",
            {"component": key},
            name=value["name"],
            fill="none",
            transform={**v1.TRANSFORM, "x": x, "y": y},
        )
        operations.append({"op": "add", "node": instance})
    # Admission includes expanded complexity and protected palette/style users.
    v2.revise(document, operations)
    return {"operations": operations, "definition_id": key, "selected_id": selected}


def courier():
    """A small real component/style/hinge consumer, not model-generated artwork."""
    from .document_templates import create
    from .document_v2 import upgrade

    doc = upgrade(create("blank"))
    doc["palette"] = {"ink": "#183446", "body": "#5D8C91", "accent": "#E4B878", "light": "#F4EDD9"}
    doc["styles"] = {
        "shell": {
            "name": "Courier shell",
            "fill": "@accent",
            "stroke": "@ink",
            "stroke_width": 5,
            "opacity": 1,
        },
        "feather": {
            "name": "Courier wings",
            "fill": "@body",
            "stroke": "@ink",
            "stroke_width": 4,
            "opacity": 1,
        },
    }
    wing = v1.node(
        "feather",
        "path",
        {"commands": [["M", 0, 0], ["Q", 35, -42, 80, 0], ["Q", 35, 42, 0, 0], ["Z"]]},
        name="Wing surface",
        style="feather",
    )
    eye = [
        v1.node("eye_white", "ellipse", {"cx": 0, "cy": 0, "rx": 10, "ry": 13}, fill="@light"),
        v1.node("pupil", "ellipse", {"cx": 2, "cy": 1, "rx": 4, "ry": 6}, fill="@ink"),
    ]
    doc["components"] = {
        "wing": {"name": "Courier wing", "nodes": [wing], "recipe": None},
        "eye": {"name": "Courier eye", "nodes": eye, "recipe": None},
    }
    doc["nodes"] = [
        v1.node("courier", "group", {}, name="Courier body assembly"),
        v1.node(
            "left_wing",
            "instance",
            {"component": "wing"},
            name="Left wing",
            parent="courier",
            transform={**v1.TRANSFORM, "x": 113, "y": 144, "rotation": 180},
        ),
        v1.node(
            "right_wing",
            "instance",
            {"component": "wing"},
            name="Right wing",
            parent="courier",
            transform={**v1.TRANSFORM, "x": 143, "y": 144},
        ),
        v1.node(
            "body",
            "ellipse",
            {"cx": 128, "cy": 154, "rx": 32, "ry": 43},
            name="Body shell",
            parent="courier",
            style="shell",
        ),
        v1.node(
            "head",
            "ellipse",
            {"cx": 128, "cy": 108, "rx": 38, "ry": 34},
            name="Head shell",
            parent="courier",
            style="shell",
        ),
        v1.node(
            "left_eye",
            "instance",
            {"component": "eye"},
            name="Left eye",
            parent="courier",
            transform={**v1.TRANSFORM, "x": 113, "y": 105},
        ),
        v1.node(
            "right_eye",
            "instance",
            {"component": "eye"},
            name="Right eye",
            parent="courier",
            transform={**v1.TRANSFORM, "x": 143, "y": 105},
        ),
        v1.node(
            "beak",
            "path",
            {"commands": [["M", 120, 125], ["L", 136, 125], ["L", 128, 135], ["Z"]]},
            fill="@ink",
            parent="courier",
        ),
    ]
    return doc
