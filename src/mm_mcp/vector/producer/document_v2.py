"""Portable local components, shared styles and rigid-part motion.

Version one stays a separate renderer. Expansion is bounded before an SVG or
animation frame is admitted; definitions never load external code or resources.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from . import document as v1

SCHEMA = "rai.vector-document/v2"
PROFILE = "vector-document-v2"
STYLE_FIELDS = {"name", "fill", "stroke", "stroke_width", "opacity"}
MAX_COMPONENTS = 8
MAX_STYLES = 16


def label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or any(ord(c) < 32 for c in value):
        raise ValueError("Use a short readable name")


def upgrade(source):
    v1.validate(source)
    return {
        **deepcopy(source),
        "schema": SCHEMA,
        "styles": {},
        "components": {},
        "rig": {"bones": [], "clips": []},
    }


def resolved(item, styles):
    result = deepcopy(item)
    style = result.pop("style", None)
    if style is not None:
        v1.identifier(style)
        if style not in styles:
            raise ValueError("Unknown shared style")
        if item["kind"] in ("group", "instance"):
            raise ValueError("Apply a shared style to drawable parts")
        result.update({k: v for k, v in styles[style].items() if k != "name"})
    return result


def _plain(nodes, palette, styles, canvas, *, instances=False):
    result = []
    for item in nodes:
        v1.fields(item, v1.NODE_FIELDS, {"style"})
        v1.identifier(item["id"])
        if item["parent"] is not None:
            v1.identifier(item["parent"])
    instance_ids = {n["id"] for n in nodes if n["kind"] == "instance"}
    for item in nodes:
        v1.fields(item, v1.NODE_FIELDS, {"style"})
        copy = resolved(item, styles)
        if copy["parent"] in instance_ids:
            raise ValueError("Component instances cannot own outside children")
        if copy["kind"] == "instance" and instances:
            v1.fields(copy["geometry"], {"component"})
            v1.identifier(copy["geometry"]["component"])
            copy["kind"], copy["geometry"] = "group", {}
        result.append(copy)
    return v1.validate({"schema": v1.SCHEMA, "canvas": canvas, "palette": palette, "nodes": result})


def _expanded(document):
    result = []
    for item in document["nodes"]:
        copy = resolved(item, document["styles"])
        if item["kind"] != "instance":
            result.append(copy)
            continue
        key = item["geometry"]["component"]
        if key not in document["components"]:
            raise ValueError("Unknown component definition")
        parts = document["components"][key]["nodes"]
        copy["kind"], copy["geometry"] = "group", {}
        result.append(copy)
        mapping = {
            part["id"]: "v_" + sha256((item["id"] + "/" + part["id"]).encode()).hexdigest()[:32]
            for part in parts
        }
        for part in parts:
            child = resolved(part, document["styles"])
            child["id"] = mapping[part["id"]]
            child["parent"] = mapping.get(part["parent"], item["id"])
            result.append(child)
            if len(result) > v1.MAX_NODES:
                raise ValueError("Expanded components exceed 128 nodes")
    return {
        "schema": v1.SCHEMA,
        "canvas": deepcopy(document["canvas"]),
        "palette": deepcopy(document["palette"]),
        "nodes": result,
    }


def validate(document):
    v1.encode(document)
    v1.fields(document, {"schema", "canvas", "palette", "nodes", "styles", "components", "rig"})
    if document["schema"] != SCHEMA:
        raise ValueError("Use an explicitly upgraded v2 document")
    v1.validate(
        {
            "schema": v1.SCHEMA,
            "canvas": document["canvas"],
            "palette": document["palette"],
            "nodes": [],
        }
    )
    styles, components = document["styles"], document["components"]
    if not isinstance(styles, dict) or len(styles) > MAX_STYLES:
        raise ValueError("Use at most 16 shared styles")
    if not isinstance(components, dict) or len(components) > MAX_COMPONENTS:
        raise ValueError("Use at most eight local components")
    for key, style in styles.items():
        v1.identifier(key)
        v1.fields(style, STYLE_FIELDS)
        label(style["name"])
        for field in ("fill", "stroke"):
            v1.color(style[field], document["palette"])
        v1.number(style["stroke_width"], 0, 128)
        v1.number(style["opacity"], 0, 1)
    if not isinstance(document["nodes"], list) or len(document["nodes"]) > v1.MAX_NODES:
        raise ValueError("Use at most 128 source nodes")
    _plain(document["nodes"], document["palette"], styles, document["canvas"], instances=True)
    for key, component in components.items():
        v1.identifier(key)
        v1.fields(component, {"name", "nodes", "recipe"})
        label(component["name"])
        if not isinstance(component["nodes"], list) or not 1 <= len(component["nodes"]) <= 64:
            raise ValueError("Components require 1–64 parts")
        _plain(component["nodes"], document["palette"], styles, document["canvas"])
        if any(n["locked"] for n in component["nodes"]):
            raise ValueError("Protect component instances; definition parts cannot be locked")
        if component["recipe"] is not None:
            from .document_library import recipe_component

            recipe = component["recipe"]
            v1.fields(recipe, {"profile", "request"})
            if recipe["profile"] == "plant-rest-v1":
                expected = recipe_component(recipe["request"], component["name"])
            elif recipe["profile"] == "vector-repeat-v1":
                from .document_modifiers import component as repeat_component

                expected = repeat_component(recipe["request"], component["name"])
                if expected["recipe"]["profile"] != recipe["profile"]:
                    raise ValueError("Component recipe profile differs from its settings")
            elif recipe["profile"] == "vector-construction-v1":
                from .document_construction import component as construct

                expected = construct(recipe["request"], component["name"])
            else:
                raise ValueError("Unknown installed component recipe")
            if expected != component:
                raise ValueError("Recipe parts differ from their parameters; detach before editing")
    v1.validate(_expanded(document))
    from .document_motion import validate as validate_motion

    validate_motion(document["rig"], document["nodes"])
    return document


def expand(document):
    validate(document)
    return _expanded(document)


def render(document):
    return v1.render(expand(document))


def _motion_for(document, protected):
    rig = document["rig"]
    return {
        "bones": [b for b in rig["bones"] if b["node"] in protected],
        "clips": [
            {**c, "tracks": [t for t in c["tracks"] if t["node"] in protected]}
            for c in rig["clips"]
            if any(t["node"] in protected for t in c["tracks"])
        ],
    }


def dependencies(document, source_ids):
    """Include authored dependencies even when a style masks their appearance."""
    nodes = [n for n in document["nodes"] if n["id"] in source_ids]
    components = {n["geometry"]["component"] for n in nodes if n["kind"] == "instance"}
    definitions = {k: document["components"][k] for k in components}
    parts = nodes + [n for c in definitions.values() for n in c["nodes"]]
    styles = {n["style"] for n in parts if n.get("style")}
    return {
        "nodes": nodes,
        "components": definitions,
        "styles": {k: document["styles"][k] for k in styles},
    }


def assert_preserved(before, after):
    first, second = expand(before), expand(after)
    v1.assert_preserved(first, second)
    protected = v1._protected(first)
    if dependencies(before, protected) != dependencies(after, protected):
        raise ValueError("Protected source part or shared dependency changed")
    if _motion_for(before, protected) != _motion_for(after, protected):
        raise ValueError("Protected parts or ancestors cannot change motion")


def descendants(nodes, roots):
    result = set(roots)
    for _ in range(8):
        result.update(n["id"] for n in nodes if n["parent"] in result)
    return result


def _prune_motion(document, deleted):
    rig = document["rig"]
    rig["bones"] = [b for b in rig["bones"] if b["node"] not in deleted]
    for clip in rig["clips"]:
        clip["tracks"] = [t for t in clip["tracks"] if t["node"] not in deleted]
    rig["clips"] = [c for c in rig["clips"] if c["tracks"]]


def revise(source, operations):
    validate(source)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        raise ValueError("Use 1–32 atomic vector edits")
    v1.encode(operations)
    out = deepcopy(source)
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Vector edit must be an object")
        op = operation.get("op")
        index = {n["id"]: n for n in out["nodes"]}
        if op == "add":
            v1.fields(operation, {"op", "node"})
            out["nodes"].append(deepcopy(operation["node"]))
        elif op in ("update", "delete", "set_lock", "component_detach"):
            extra = {"changes"} if op == "update" else {"locked"} if op == "set_lock" else set()
            v1.fields(operation, {"op", "id"} | extra)
            v1.identifier(operation["id"])
            if operation["id"] not in index:
                raise ValueError("Unknown source part")
            item = index[operation["id"]]
            if op == "update":
                v1.fields(operation["changes"], (), (v1.NODE_FIELDS | {"style"}) - {"id", "locked"})
                item.update(deepcopy(operation["changes"]))
            elif op == "set_lock":
                if len(operations) != 1 or type(operation["locked"]) is not bool:
                    raise ValueError("set_lock must be a separate transaction")
                item["locked"] = operation["locked"]
                return validate(out)
            elif op == "delete":
                deleted = descendants(out["nodes"], [item["id"]])
                out["nodes"] = [n for n in out["nodes"] if n["id"] not in deleted]
                _prune_motion(out, deleted)
            else:
                if item["kind"] != "instance":
                    raise ValueError("Choose a component instance to detach")
                expanded = _expanded(out)
                included = descendants(expanded["nodes"], [item["id"]])
                at = out["nodes"].index(item)
                out["nodes"][at : at + 1] = [n for n in expanded["nodes"] if n["id"] in included]
        elif op == "palette":
            v1.fields(operation, {"op", "colors"})
            if not isinstance(operation["colors"], dict):
                raise ValueError("Use named palette colors")
            out["palette"].update(operation["colors"])
        elif op == "canvas":
            v1.fields(operation, {"op", "canvas"})
            out["canvas"] = deepcopy(operation["canvas"])
        elif op == "order":
            v1.fields(operation, {"op", "ids"})
            ids = operation["ids"]
            if (
                not isinstance(ids, list)
                or any(not isinstance(k, str) for k in ids)
                or len(ids) != len(index)
                or set(ids) != set(index)
            ):
                raise ValueError("Order must contain every source node exactly once")
            out["nodes"] = [index[k] for k in ids]
        elif op == "replace":
            v1.fields(operation, {"op", "document"})
            out = deepcopy(operation["document"])
        elif op in ("style_set", "component_set", "style_delete", "component_delete"):
            singular = "style" if op.startswith("style") else "component"
            setter = op.endswith("_set")
            v1.fields(operation, {"op", "id"} | ({singular} if setter else set()))
            v1.identifier(operation["id"])
            if setter:
                out[singular + "s"][operation["id"]] = deepcopy(operation[singular])
            elif operation["id"] not in out[singular + "s"]:
                raise ValueError("Unknown definition")
            else:
                del out[singular + "s"][operation["id"]]
        elif op == "component_create":
            v1.fields(operation, {"op", "id", "name", "root"})
            v1.identifier(operation["id"])
            if operation["id"] in out["components"] or operation["root"] not in index:
                raise ValueError("Use a new component ID and existing root part")
            root = index[operation["root"]]
            included = descendants(out["nodes"], [root["id"]])
            if any(b["node"] in included for b in out["rig"]["bones"]):
                raise ValueError("Remove this part's rig before converting it into a component")
            parts = [deepcopy(n) for n in out["nodes"] if n["id"] in included]
            if any(n["kind"] == "instance" for n in parts):
                raise ValueError("Detach nested instances before creating a component")
            definition_root = next(n for n in parts if n["id"] == root["id"])
            definition_root.update(parent=None, transform=dict(v1.TRANSFORM), visible=True)
            out["components"][operation["id"]] = {
                "name": operation["name"],
                "nodes": parts,
                "recipe": None,
            }
            instance = {
                **deepcopy(root),
                "kind": "instance",
                "geometry": {"component": operation["id"]},
                "style": None,
                "opacity": 1,
            }
            out["nodes"] = [
                instance if n["id"] == root["id"] else n
                for n in out["nodes"]
                if n["id"] == root["id"] or n["id"] not in included
            ]
        elif op == "component_edit":
            v1.fields(operation, {"op", "id", "operations"})
            v1.identifier(operation["id"])
            if operation["id"] not in out["components"]:
                raise ValueError("Unknown component")
            component = out["components"][operation["id"]]
            if component["recipe"] is not None:
                raise ValueError("Detach the recipe before editing generated parts")
            edits = operation["operations"]
            allowed = {"add", "update", "delete", "order"}
            if not isinstance(edits, list) or any(
                not isinstance(e, dict) or e.get("op") not in allowed for e in edits
            ):
                raise ValueError("Component editing supports part add/update/delete/order only")
            temporary = {
                **deepcopy(out),
                "nodes": deepcopy(component["nodes"]),
                "components": {},
                "rig": {"bones": [], "clips": []},
            }
            component["nodes"] = revise(temporary, edits)["nodes"]
        elif op in ("recipe_set", "recipe_detach"):
            v1.fields(
                operation, {"op", "id"} | ({"name", "request"} if op == "recipe_set" else set())
            )
            v1.identifier(operation["id"])
            if op == "recipe_set":
                from .document_library import recipe_component

                out["components"][operation["id"]] = recipe_component(
                    operation["request"], operation["name"]
                )
            else:
                if operation["id"] not in out["components"]:
                    raise ValueError("Unknown component")
                out["components"][operation["id"]]["recipe"] = None
        elif op in ("modifier_create", "modifier_update", "modifier_source"):
            from .document_modifiers import revise as revise_modifier

            out = revise_modifier(out, operation)
        elif op == "rig_set":
            v1.fields(operation, {"op", "rig"})
            out["rig"] = deepcopy(operation["rig"])
        elif op == "clip_set":
            v1.fields(operation, {"op", "clip"})
            clip = deepcopy(operation["clip"])
            v1.fields(clip, {"id", "name", "duration", "loop", "tracks"})
            out["rig"]["clips"] = [c for c in out["rig"]["clips"] if c["id"] != clip["id"]] + [clip]
        elif op == "clip_delete":
            v1.fields(operation, {"op", "id"})
            v1.identifier(operation["id"])
            if not any(c["id"] == operation["id"] for c in out["rig"]["clips"]):
                raise ValueError("Unknown clip")
            out["rig"]["clips"] = [c for c in out["rig"]["clips"] if c["id"] != operation["id"]]
        else:
            raise ValueError("Unknown v2 vector edit")
        validate(out)
        assert_preserved(source, out)
    return out


def create(template="blank"):
    from .document_templates import create as create_v1

    if template == "courier":
        from .document_library import courier

        return validate(courier())
    if template == "emblem":
        from .document_modifiers import emblem

        return validate(emblem())
    if template == "signage":
        from .document_construction import signage

        return validate(signage())
    return validate(upgrade(create_v1(template)))


def describe():
    return {
        "schema": "rai.vector-authoring/v2",
        "profile": PROFILE,
        "operation": "describe",
        "document_schema": SCHEMA,
        "templates": [
            "blank",
            "power_cell",
            "medical_kit",
            "beacon",
            "courier",
            "emblem",
            "signage",
        ],
        "limits": {
            "nodes_expanded": 128,
            "hierarchy": 8,
            "path_commands": 1024,
            "colors": 16,
            "components": 8,
            "styles": 16,
            "bones": 24,
            "clips": 8,
            "keyframes": 128,
            "frames": 16,
            "operations": 32,
            "request_bytes": v1.MAX_BYTES,
        },
        "operations": [
            "describe",
            "create",
            "upgrade",
            "revise",
            "preview",
            "variants",
            "rig_suggest",
            "sample",
            "frames",
            "mask",
            "sdf",
        ],
        "modifiers": ["mirror", "linear", "radial", "construction"],
        "construction_policy": (
            "1–4 ordered Boolean/offset/linear-repeat steps. Closed opaque fills only. "
            "Retained source; 2048 intermediate vertices, existing document limits apply."
        ),
        "sdf_policy": (
            "Static canvas-clipped sampled distance field, 128/256/512 pixels, "
            "2–32 texel spread. Same closed opaque geometry contract as construction."
        ),
        "modifier_policy": (
            "Editable source snapshot, at most 16 copies and 64 generated component parts. "
            "Seeded translation variation. Detach explicitly to bake."
        ),
        "rig_presets": ["auto", "sway", "bob", "flap", "walk"],
        "component_policy": (
            "Embedded definitions; explicit snapshot import. "
            "No recursive components or external resources."
        ),
        "motion_policy": (
            "Rigid named parts only. Suggestions require preview/accept; edit pivots "
            "and clips. No mesh skinning or raster segmentation."
        ),
    }


def execute(request):
    v1.encode(request)
    if not isinstance(request, dict):
        raise ValueError("Use a vector request object")
    operation = request.get("operation")
    contracts = {
        "describe": set(),
        "create": set(),
        "upgrade": {"source"},
        "revise": {"source", "operations"},
        "preview": {"source"},
        "variants": {"source", "palettes"},
        "rig_suggest": {"source", "preset"},
        "sample": {"source", "clip", "time"},
        "frames": {"source", "clip", "count"},
        "mask": {"source"},
        "sdf": {"source", "resolution", "spread"},
    }
    if request.get("profile") != PROFILE or operation not in contracts:
        raise ValueError("Use an installed vector-document-v2 operation")
    v1.fields(
        request,
        {"profile", "operation"} | contracts[operation],
        {"document", "template"} if operation == "create" else (),
    )
    if operation == "describe":
        return describe()
    if operation == "create":
        if "document" in request and "template" in request:
            raise ValueError("Choose a document or template")
        documents = [
            deepcopy(validate(request["document"]))
            if "document" in request
            else create(request.get("template", "blank"))
        ]
    elif operation == "upgrade":
        documents = [validate(upgrade(request["source"]))]
    elif operation == "revise":
        documents = [revise(request["source"], request["operations"])]
    elif operation == "preview":
        documents = [deepcopy(validate(request["source"]))]
    elif operation == "variants":
        palettes = request["palettes"]
        if not isinstance(palettes, list) or not 1 <= len(palettes) <= 6:
            raise ValueError("Compare one to six palettes")
        documents = [
            revise(request["source"], [{"op": "palette", "colors": colors}]) for colors in palettes
        ]
    elif operation == "sdf":
        from .document_sdf import export

        return {
            "profile": PROFILE,
            "operation": operation,
            **export(request["source"], request["resolution"], request["spread"]),
        }
    elif operation == "mask":
        from .document_modifiers import mask

        return {
            "schema": "rai.vector-material-mask/v1",
            "profile": PROFILE,
            "operation": operation,
            "svg": mask(request["source"]),
            "source_sha256": v1.structural_digest(request["source"]),
            "canvas": deepcopy(request["source"]["canvas"]),
            "channel": "r",
            "color_space": "linear",
            "pose": "rest",
        }
    elif operation == "rig_suggest":
        from .document_motion import suggest

        suggestion = suggest(request["source"], request["preset"])
        return {
            "schema": "rai.vector-authoring/v2",
            "profile": PROFILE,
            "operation": operation,
            **suggestion,
        }
    else:
        from .document_motion import frames, sample

        if operation == "sample":
            pose = sample(request["source"], request["clip"], request["time"])
            return {
                "schema": "rai.vector-authoring/v2",
                "profile": PROFILE,
                "operation": operation,
                "pose": pose,
                "preview_svg": v1.render(pose),
            }
        return frames(request["source"], request["clip"], request["count"])
    return {
        "schema": "rai.vector-authoring/v2",
        "profile": PROFILE,
        "operation": operation,
        "documents": documents,
        "unique_count": len({v1.structural_digest(d) for d in documents}),
        "previews": [
            {"svg": render(d), "content_sha256": v1.structural_digest(d)} for d in documents
        ],
    }
