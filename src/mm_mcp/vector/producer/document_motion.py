"""Deterministic rigid-part clips and editable, bounded hinge suggestions."""

from __future__ import annotations

import math
from copy import deepcopy

from . import document as v1
from .geometry import apply, compose, inverse, transform

PRESETS = ("auto", "sway", "bob", "flap", "walk")
KEY_FIELDS = {"time", "x", "y", "rotation", "scale"}


def validate(rig, nodes):
    v1.fields(rig, {"bones", "clips"})
    if not isinstance(rig["bones"], list) or len(rig["bones"]) > 24:
        raise ValueError("Use at most 24 rigid-part bones")
    if not isinstance(rig["clips"], list) or len(rig["clips"]) > 8:
        raise ValueError("Use at most eight motion clips")
    index = {n["id"]: n for n in nodes}
    bones = {}
    for bone in rig["bones"]:
        v1.fields(bone, {"node", "pivot"})
        v1.identifier(bone["node"])
        if bone["node"] not in index or bone["node"] in bones:
            raise ValueError("Bones require unique existing source parts")
        pivot = bone["pivot"]
        if not isinstance(pivot, list) or len(pivot) != 2:
            raise ValueError("A bone pivot has two local coordinates")
        for value in pivot:
            v1.number(value)
        bones[bone["node"]] = bone
    identifiers, total = set(), 0
    for clip in rig["clips"]:
        v1.fields(clip, {"id", "name", "duration", "loop", "tracks"})
        v1.identifier(clip["id"])
        from .document_v2 import label

        label(clip["name"])
        if clip["id"] in identifiers or type(clip["loop"]) is not bool:
            raise ValueError("Clips require unique IDs and a loop flag")
        identifiers.add(clip["id"])
        v1.number(clip["duration"], 0.2, 30)
        if not isinstance(clip["tracks"], list) or not 1 <= len(clip["tracks"]) <= 24:
            raise ValueError("Clips require one to 24 tracks")
        targets = set()
        for track in clip["tracks"]:
            v1.fields(track, {"node", "keys"})
            v1.identifier(track["node"])
            if track["node"] not in bones or track["node"] in targets:
                raise ValueError("Tracks require unique installed bones")
            targets.add(track["node"])
            keys = track["keys"]
            if not isinstance(keys, list) or not 2 <= len(keys) <= 32:
                raise ValueError("Tracks require two to 32 keys")
            previous = -1
            for key in keys:
                v1.fields(key, KEY_FIELDS)
                v1.number(key["time"], 0, clip["duration"])
                v1.number(key["x"], -2048, 2048)
                v1.number(key["y"], -2048, 2048)
                v1.number(key["rotation"], -360, 360)
                v1.number(key["scale"], 0.25, 4)
                if key["time"] <= previous:
                    raise ValueError("Keyframe times must increase strictly")
                previous = key["time"]
            if keys[0]["time"] != 0 or keys[-1]["time"] != clip["duration"]:
                raise ValueError("Tracks must cover both clip endpoints")
            if clip["loop"] and any(keys[0][k] != keys[-1][k] for k in KEY_FIELDS - {"time"}):
                raise ValueError("Loop endpoints must have matching poses")
            base = index[track["node"]]["transform"]
            low, high = min(k["scale"] for k in keys), max(k["scale"] for k in keys)
            for axis in ("scale_x", "scale_y"):
                v1.number(base[axis] * low, 0.01, 100)
                v1.number(base[axis] * high, 0.01, 100)
            for key in keys:
                v1.number(base["rotation"] + key["rotation"], -3600, 3600)
            # A conservative all-times bound, not a few sampled acceptance poses.
            px, py = bones[track["node"]]["pivot"]
            radius = abs(px * base["scale_x"]) + abs(py * base["scale_y"])
            for axis in ("x", "y"):
                if abs(base[axis]) + (1 + high) * radius + max(abs(k[axis]) for k in keys) > 8192:
                    raise ValueError(
                        "Animation exceeds the finite transform envelope; "
                        "move its local origin closer"
                    )
            total += len(keys)
    if total > 128:
        raise ValueError("A rig supports at most 128 total keyframes")


def matrix(t):
    return transform(t["x"], t["y"], math.radians(t["rotation"]), t["scale_x"], t["scale_y"])


def interpolate(keys, time):
    for left, right in zip(keys, keys[1:]):
        if time <= right["time"]:
            fraction = max(0.0, min(1.0, (time - left["time"]) / (right["time"] - left["time"])))
            fraction = fraction * fraction * (3 - 2 * fraction)
            return {
                key: left[key] + (right[key] - left[key]) * fraction
                for key in KEY_FIELDS - {"time"}
            }
    return {key: keys[-1][key] for key in KEY_FIELDS - {"time"}}


def pose_transform(base, pivot, key):
    fixed = apply(matrix(base), pivot)
    pose = {
        **base,
        "rotation": base["rotation"] + key["rotation"],
        "scale_x": base["scale_x"] * key["scale"],
        "scale_y": base["scale_y"] * key["scale"],
    }
    moved = apply(matrix({**pose, "x": 0, "y": 0}), pivot)
    pose.update(x=fixed[0] + key["x"] - moved[0], y=fixed[1] + key["y"] - moved[1])
    return pose


def sample(document, clip_id, time):
    from .document_v2 import expand

    v1.number(time, 0, 86400)
    v1.identifier(clip_id)
    output = expand(document)
    clip = next((c for c in document["rig"]["clips"] if c["id"] == clip_id), None)
    if clip is None:
        raise ValueError("Unknown animation clip")
    at = time % clip["duration"] if clip["loop"] else min(time, clip["duration"])
    bones = {b["node"]: b for b in document["rig"]["bones"]}
    nodes = {n["id"]: n for n in output["nodes"]}
    for track in clip["tracks"]:
        node = nodes[track["node"]]
        node["transform"] = pose_transform(
            node["transform"], bones[track["node"]]["pivot"], interpolate(track["keys"], at)
        )
    return v1.validate(output)


def _geometry_points(node):
    g = node["geometry"]
    if node["kind"] == "rect":
        x, y, width, height = g["x"], g["y"], g["width"], g["height"]
    elif node["kind"] == "ellipse":
        x, y, width, height = g["cx"] - g["rx"], g["cy"] - g["ry"], 2 * g["rx"], 2 * g["ry"]
    elif node["kind"] == "path":
        # Curve control hulls are conservative. Suggestions expose this heuristic
        # and let the artist correct the pivot before accepting it.
        return [
            (command[i], command[i + 1])
            for command in g["commands"]
            for i in range(1, len(command), 2)
        ]
    else:
        return []
    return [(x, y), (x + width, y), (x, y + height), (x + width, y + height)]


def bounds(expanded, root=None):
    def points(parent, parent_matrix):
        result = []
        for node in expanded["nodes"]:
            if node["parent"] != parent or not node["visible"]:
                continue
            world = compose(parent_matrix, matrix(node["transform"]))
            result.extend(apply(world, point) for point in _geometry_points(node))
            result.extend(points(node["id"], world))
        return result

    identity = (1, 0, 0, 1, 0, 0)
    if root is None:
        values = points(None, identity)
    else:
        node = next(n for n in expanded["nodes"] if n["id"] == root)
        values = _geometry_points(node) + points(root, identity)
    if not values:
        raise ValueError("Visible artwork is needed to suggest a pivot")
    xs, ys = zip(*values)
    return min(xs), min(ys), max(xs), max(ys)


def _world_matrix(nodes, key):
    index = {n["id"]: n for n in nodes}
    node = index[key]
    result = matrix(node["transform"])
    parent = node["parent"]
    while parent is not None:
        result = compose(matrix(index[parent]["transform"]), result)
        parent = index[parent]["parent"]
    return result


def suggest(source, preset="auto"):
    from . import document_v2 as v2

    v2.validate(source)
    if preset not in PRESETS:
        raise ValueError("Use auto, sway, bob, flap or walk")
    document = deepcopy(source)
    expanded = v2.expand(document)
    protected = v1._protected(expanded)

    def named(node, words):
        name = (node["name"] + " " + node["id"]).lower().replace("_", " ").replace("-", " ")
        return any(word in name.split() for word in words)

    movable = [n for n in document["nodes"] if n["visible"] and n["id"] not in protected]
    wings = [n for n in movable if named(n, ("wing", "wings", "fin", "flipper"))]
    legs = [n for n in movable if named(n, ("leg", "legs", "arm", "arms"))]
    flap_candidate = any(named(n, ("wing", "wings")) for n in wings) or len(wings) >= 2
    chosen = (
        ("flap" if flap_candidate else "walk" if legs else "sway") if preset == "auto" else preset
    )
    targets = wings if chosen == "flap" else legs if chosen == "walk" else []
    warnings = [
        "Hinges are suggestions from named parts and conservative bounds; "
        "adjust them before acceptance."
    ]
    if chosen in ("flap", "walk") and not targets:
        raise ValueError("This preset needs separately named wing/fin or leg/arm parts")
    if not targets:
        roots = [n for n in document["nodes"] if n["parent"] is None]
        if not roots:
            raise ValueError("Draw or import artwork before suggesting a rig")
        if protected:
            raise ValueError(
                "Whole-art motion would affect protected parts; "
                "unlock explicitly or rig an unprotected appendage"
            )
        if len(roots) > 1:
            used = {n["id"] for n in document["nodes"]}
            key = next(
                (f"motion_root_{i}" for i in range(129) if f"motion_root_{i}" not in used), None
            )
            root = v1.node(key, "group", {}, name="Artwork motion root", fill="none")
            for node in roots:
                node["parent"] = key
            document["nodes"].insert(0, root)
            targets = [root]
            expanded = v2.expand(document)
        else:
            targets = roots
        warnings.append(
            "This is whole-part rigid motion; no segmentation or mesh deformation is inferred."
        )
    if len(targets) > 24:
        raise ValueError("Too many candidate bones; simplify the named part hierarchy")
    # Do not animate both a matching group and one of its children twice.
    selected = {n["id"] for n in targets}
    targets = [
        n
        for n in targets
        if not any(
            n["id"] in v2.descendants(document["nodes"], [other]) - {other} for other in selected
        )
    ]
    world_bounds = bounds(expanded)
    center = ((world_bounds[0] + world_bounds[2]) / 2, (world_bounds[1] + world_bounds[3]) / 2)
    duration = {"flap": 1.4, "walk": 1.2, "sway": 2.4, "bob": 1.6}[chosen]
    bones, tracks, suggestions = [], [], []
    for index, node in enumerate(targets):
        box = bounds(expanded, node["id"])
        if chosen == "flap":
            body = apply(inverse(_world_matrix(expanded["nodes"], node["id"])), center)
            pivot = [
                box[0] if abs(body[0] - box[0]) <= abs(body[0] - box[2]) else box[2],
                (box[1] + box[3]) / 2,
            ]
        elif chosen == "walk":
            pivot = [(box[0] + box[2]) / 2, box[1]]
        else:
            pivot = [(box[0] + box[2]) / 2, box[3]]
        pivot = [round(v, 8) for v in pivot]
        bones.append({"node": node["id"], "pivot": pivot})
        if named(node, ("left",)):
            sign = -1
        elif named(node, ("right",)):
            sign = 1
        else:
            sign = 1 if index % 2 == 0 else -1
        amplitude = {"flap": 18, "walk": 22, "sway": 5, "bob": 0}[chosen]
        keys = [
            {
                "time": duration * at / 4,
                "x": 0,
                "y": wave * 4 if chosen == "bob" else 0,
                "rotation": wave * amplitude * sign,
                "scale": 1,
            }
            for at, wave in enumerate((0, 1, 0, -1, 0))
        ]
        tracks.append({"node": node["id"], "keys": keys})
        suggestions.append(
            {
                "node": node["id"],
                "pivot": pivot,
                "confidence": "medium" if chosen in ("flap", "walk") else "low",
                "reason": "Named appendage and local control-hull bounds"
                if chosen in ("flap", "walk")
                else "Whole-art lower-center pivot",
            }
        )
    # Suggestion replaces the rig explicitly; the caller previews before writing.
    document["rig"] = {
        "bones": bones,
        "clips": [
            {
                "id": chosen,
                "name": chosen.title(),
                "duration": duration,
                "loop": True,
                "tracks": tracks,
            }
        ],
    }
    v2.assert_preserved(source, document)
    return {
        "document": document,
        "preset": chosen,
        "suggestions": suggestions,
        "warnings": warnings,
        "preview_svg": v2.render(document),
        "source_sha256": v1.structural_digest(source),
    }


def frames(document, clip_id, count=16):
    from .document_v2 import validate as validate_document

    validate_document(document)
    v1.identifier(clip_id)
    if type(count) is not int or not 2 <= count <= 16:
        raise ValueError("Export two to sixteen bounded frames")
    clip = next((c for c in document["rig"]["clips"] if c["id"] == clip_id), None)
    if clip is None:
        raise ValueError("Unknown clip")
    result = {
        "schema": "rai.vector-motion-frames/v1",
        "profile": "vector-document-v2",
        "operation": "frames",
        "clip": clip_id,
        "duration": clip["duration"],
        "loop": clip["loop"],
        "source_sha256": v1.structural_digest(document),
        "frames": [],
    }
    for index in range(count):
        time = index * clip["duration"] / (count if clip["loop"] else count - 1)
        result["frames"].append(
            {"index": index, "time": time, "svg": v1.render(sample(document, clip_id, time))}
        )
    from .authoring import encode

    encode(result)
    return result
