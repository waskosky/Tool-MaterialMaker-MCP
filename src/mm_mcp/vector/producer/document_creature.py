"""One bounded articulated recipe, measurement fit and constrained planar IK.

The saved document contains ordinary editable shapes and rigid clips. Solvers
run during authoring only. Stable part IDs and local joint origins retain clips
when proportions change; detaching explicitly releases the anatomy contract.
"""

import math
from copy import deepcopy

from . import document as v1
from .geometry import apply, compose, inverse

SCHEMA = "rai.vector-creature/v1"
CONTROLS = {
    "body_width": (28, 64),
    "body_height": (32, 72),
    "head_radius": (14, 28),
    "ear_length": (12, 32),
    "upper_leg": (24, 56),
    "lower_leg": (24, 56),
    "hip_spacing": (16, 48),
}
DEFAULTS = dict(
    body_width=48,
    body_height=52,
    head_radius=22,
    ear_length=24,
    upper_leg=40,
    lower_leg=40,
    hip_spacing=32,
)
MEASUREMENTS = {
    "height": (
        {"body_height": 1, "head_radius": 2, "ear_length": 1, "upper_leg": 1, "lower_leg": 1},
        8,
    ),
    "body_width": ({"body_width": 1}, 0),
    "leg_length": ({"upper_leg": 1, "lower_leg": 1}, 0),
    "head_diameter": ({"head_radius": 2}, 0),
}
LIMITS = {"thigh": (-65, 65), "shin": (0, 140)}


def parameters(values):
    v1.fields(values, set(CONTROLS))
    for key, (low, high) in CONTROLS.items():
        v1.number(values[key], low, high)
    return deepcopy(values)


def measurements(values):
    return {
        key: round(offset + sum(values[k] * factor for k, factor in terms.items()), 6)
        for key, (terms, offset) in MEASUREMENTS.items()
    }


def _parts(p):
    nodes = []

    def node(key, kind, geometry, parent="creature_root", x=0, y=0, fill="@body"):
        item = dict(
            id=key,
            name=key.replace("_", " ").title(),
            kind=kind,
            parent=parent,
            visible=True,
            locked=False,
            transform={**v1.TRANSFORM, "x": x, "y": y},
            geometry=geometry,
            fill="none" if kind == "group" else fill,
            stroke="none",
            stroke_width=0,
            opacity=1,
        )
        nodes.append(item)

    def ellipse(key, parent, cx, cy, rx, ry, fill="@body"):
        node(key, "ellipse", dict(cx=cx, cy=cy, rx=rx, ry=ry), parent, fill=fill)

    node("creature_root", "group", {}, None, 192, 150)
    for side, sign in (("left", -1), ("right", 1)):
        upper, lower = side + "_thigh", side + "_shin"
        node(upper, "group", {}, x=sign * p["hip_spacing"] / 2, y=p["body_height"] / 2)
        ellipse(side + "_upper_shape", upper, 0, p["upper_leg"] / 2, 8, p["upper_leg"] / 2)
        node(lower, "group", {}, upper, 0, p["upper_leg"])
        ellipse(side + "_lower_shape", lower, 0, p["lower_leg"] / 2, 6, p["lower_leg"] / 2, "@ink")
        ellipse(side + "_foot_shape", lower, 0, p["lower_leg"] + 4, 14, 4, "@accent")
    ellipse("torso", "creature_root", 0, 0, p["body_width"] / 2, p["body_height"] / 2)
    ellipse("bib", "creature_root", 0, 2, p["body_width"] * 0.28, p["body_height"] * 0.3, "@light")
    radius, ears = p["head_radius"], p["ear_length"]
    node("head", "group", {}, y=-p["body_height"] / 2 - radius)
    for side, sign in (("left", -1), ("right", 1)):
        ellipse(side + "_ear", "head", sign * radius * 0.5, -radius - ears / 2, 5, ears / 2)
    ellipse("face", "head", 0, 0, radius, radius)
    for side, sign in (("left", -1), ("right", 1)):
        ellipse(side + "_eye", "head", sign * radius * 0.38, -2, 3, 4, "@ink")
    ellipse("nose", "head", 0, 7, 4, 3, "@accent")
    return nodes


def _key(time, rotation=0):
    return dict(time=time, x=0, y=0, rotation=rotation, scale=1)


def create():
    bones = [
        dict(node=side + "_" + part, pivot=[0, 0])
        for side in ("left", "right")
        for part in ("thigh", "shin")
    ]
    bones.append(dict(node="head", pivot=[0, 0]))
    clips = []
    for name, duration, loop in (
        ("idle", 1.8, True),
        ("walk", 0.8, True),
        ("interact", 0.9, False),
    ):
        tracks = []
        for side in ("left", "right"):
            for part in ("thigh", "shin"):
                if name == "walk":
                    angles = (
                        ([-18, 18, -18] if side == "left" else [18, -18, 18])
                        if part == "thigh"
                        else ([12, 48, 12] if side == "left" else [48, 12, 48])
                    )
                else:
                    angles = (
                        [0, -8 if name == "interact" else 2, 0]
                        if part == "thigh"
                        else [6, 24 if name == "interact" else 10, 6]
                    )
                tracks.append(
                    dict(
                        node=side + "_" + part,
                        keys=[_key(t, a) for t, a in zip((0, duration / 2, duration), angles)],
                    )
                )
        tracks.append(
            dict(
                node="head",
                keys=[_key(0), _key(duration / 2, 8 if name == "interact" else 3), _key(duration)],
            )
        )
        clips.append(
            dict(
                id=name,
                name={"idle": "Idle", "walk": "Walk", "interact": "Greeting"}[name],
                duration=duration,
                loop=loop,
                tracks=tracks,
            )
        )
    return dict(
        schema="rai.vector-document/v2",
        canvas=dict(width=384, height=384),
        palette=dict(ink="#263B3A", body="#6E9472", accent="#E6B96A", light="#F2ECD5"),
        nodes=_parts(DEFAULTS),
        components={},
        styles={},
        rig=dict(bones=bones, clips=clips),
        creature=dict(schema=SCHEMA, recipe="trail-hopper-v1", parameters=deepcopy(DEFAULTS)),
    )


def validate(source):
    data = source["creature"]
    v1.fields(data, {"schema", "recipe", "parameters"})
    if data["schema"] != SCHEMA or data["recipe"] != "trail-hopper-v1":
        raise ValueError("Use the installed trail-hopper anatomy recipe")
    p = parameters(data["parameters"])
    index = {n["id"]: n for n in source["nodes"]}
    root = index.get("creature_root", {}).get("transform", {})
    if root.get("scale_x") != root.get("scale_y"):
        raise ValueError("Use a uniform creature root scale or explicitly detach the recipe")
    for expected in _parts(p):
        actual = index.get(expected["id"])
        fields = ("kind", "parent", "geometry") + (
            () if expected["id"] == "creature_root" else ("transform",)
        )
        if actual is None or any(actual[k] != expected[k] for k in fields):
            raise ValueError(
                "Anatomy differs from recipe parameters; use creature controls or detach"
            )
    bones = {b["node"]: b for b in source["rig"]["bones"]}
    joints = {
        side + "_" + part: limit for side in ("left", "right") for part, limit in LIMITS.items()
    }
    if any(key not in bones or bones[key]["pivot"] != [0, 0] for key in joints):
        raise ValueError("Anatomy requires its four named joint origins")
    for clip in source["rig"]["clips"]:
        for track in clip["tracks"]:
            if track["node"] in joints:
                low, high = joints[track["node"]]
                if any(
                    not low <= k["rotation"] <= high
                    or k["x"] != 0
                    or k["y"] != 0
                    or k["scale"] != 1
                    for k in track["keys"]
                ):
                    raise ValueError("Joint limits require bounded rotations without stretching")


def resize(source, values):
    p = parameters(values)
    generated = {n["id"]: n for n in _parts(p)}
    out = deepcopy(source)
    for node in out["nodes"]:
        if node["id"] in generated and node["id"] != "creature_root":
            node.update({k: generated[node["id"]][k] for k in ("geometry", "transform")})
    out["creature"]["parameters"] = p
    return out


def sockets(source, clip=None, time=0):
    from . import document_motion as motion

    nodes = motion.sample(source, clip, time)["nodes"] if clip else source["nodes"]
    p = source["creature"]["parameters"]
    points = {
        side + "_foot": (side + "_shin", (0, p["lower_leg"] + 8)) for side in ("left", "right")
    }
    points["head"] = ("head", (0, -p["head_radius"]))
    return {
        key: [round(v, 6) for v in apply(motion._world_matrix(nodes, node), point)]
        for key, (node, point) in points.items()
    }


def describe(source):
    from . import document_v2 as v2

    v2.validate(source)
    if "creature" not in source:
        raise ValueError("Choose a trail-hopper creature")
    p = source["creature"]["parameters"]
    return dict(
        parameters=deepcopy(p),
        controls={k: dict(min=a, max=b, default=DEFAULTS[k]) for k, (a, b) in CONTROLS.items()},
        measurements=measurements(p),
        units="recipe canvas units at rest",
        limits={key: list(value) for key, value in LIMITS.items()},
        sockets=sockets(source),
    )


def _candidate(source, values):
    from . import document_v2 as v2

    operations = [dict(op="creature_set", parameters=values)]
    document = v2.revise(source, operations)
    return dict(
        document=document,
        operations=operations,
        source_sha256=v1.structural_digest(source),
        candidate_sha256=v1.structural_digest(document),
        preview_svg=v2.render(document),
    )


def fit(source, targets, free_parameters):
    describe(source)
    if (
        not isinstance(targets, dict)
        or not 1 <= len(targets) <= len(MEASUREMENTS)
        or set(targets) - MEASUREMENTS.keys()
    ):
        raise ValueError("Fit one to four named measurements")
    if (
        not isinstance(free_parameters, list)
        or not free_parameters
        or any(not isinstance(k, str) or k not in CONTROLS for k in free_parameters)
        or len(set(free_parameters)) != len(free_parameters)
    ):
        raise ValueError("Choose unique free recipe parameters")
    for target in targets.values():
        v1.fields(target, {"target", "weight"})
        v1.number(target["target"], 1, 1024)
        v1.number(target["weight"], 0.01, 100)
    p = deepcopy(source["creature"]["parameters"])
    for iteration in range(64):
        change = 0
        for key in sorted(free_parameters):
            numerator = denominator = 0
            observed = measurements(p)
            for name, goal in sorted(targets.items()):
                coefficient = MEASUREMENTS[name][0].get(key, 0)
                numerator += goal["weight"] * coefficient * (goal["target"] - observed[name])
                denominator += goal["weight"] * coefficient * coefficient
            if denominator:
                low, high = CONTROLS[key]
                value = max(low, min(high, p[key] + numerator / denominator))
                change = max(change, abs(value - p[key]))
                p[key] = value
        if change < 1e-7:
            break
    p = {k: round(v, 6) for k, v in p.items()}
    observed = measurements(p)
    residuals = {key: round(observed[key] - target["target"], 6) for key, target in targets.items()}
    return {
        **_candidate(source, p),
        "parameters": p,
        "measurements": observed,
        "residuals": residuals,
        "status": "fitted" if all(abs(v) <= 0.5 for v in residuals.values()) else "residual",
        "iterations": iteration + 1,
        "tolerance": 0.5,
        "units": "recipe canvas units at rest",
    }


def solve(upper, lower, target):
    v1.number(upper, 24, 56)
    v1.number(lower, 24, 56)
    if not isinstance(target, list) or len(target) != 2:
        raise ValueError("An IK target has two coordinates")
    for value in target:
        v1.number(value, -8192, 8192)
    x, y = target
    direction = math.atan2(-x, y)

    def clamp(angle, limit):
        return max(math.radians(limit[0]), min(math.radians(limit[1]), angle))

    knee = math.acos(
        max(-1, min(1, (x * x + y * y - upper * upper - lower * lower) / (2 * upper * lower)))
    )
    hip = direction - math.atan2(lower * math.sin(knee), upper + lower * math.cos(knee))
    candidates = [
        (clamp(hip + wrap, LIMITS["thigh"]), clamp(knee, LIMITS["shin"]))
        for wrap in (-2 * math.pi, 0, 2 * math.pi)
    ]
    # The constrained optimum is either the analytic interior solution or an
    # optimum on one of the four joint-limit boundaries. Enumerate all four.
    for degree in LIMITS["thigh"]:
        a = math.radians(degree)
        b = math.atan2(-(x + upper * math.sin(a)), y - upper * math.cos(a)) - a
        for wrap in (-2 * math.pi, 0, 2 * math.pi):
            candidates.append((a, clamp(b + wrap, LIMITS["shin"])))
    for degree in LIMITS["shin"]:
        b = math.radians(degree)
        a = direction - math.atan2(lower * math.sin(b), upper + lower * math.cos(b))
        for wrap in (-2 * math.pi, 0, 2 * math.pi):
            candidates.append((clamp(a + wrap, LIMITS["thigh"]), b))

    def point(a, b):
        return [
            -upper * math.sin(a) - lower * math.sin(a + b),
            upper * math.cos(a) + lower * math.cos(a + b),
        ]

    a, b = min(candidates, key=lambda pair: math.dist(point(*pair), target))
    achieved = point(a, b)
    error = math.dist(achieved, target)
    return dict(
        angles=[math.degrees(a), math.degrees(b)],
        achieved=achieved,
        error=error,
        reachable=error <= 0.01,
    )


def pose(source, leg, target, clip, time):
    from . import document_motion as motion
    from . import document_v2 as v2

    describe(source)
    if leg not in ("left", "right"):
        raise ValueError("Choose the left or right leg")
    chosen = next((c for c in source["rig"]["clips"] if c["id"] == clip), None)
    if chosen is None:
        raise ValueError("Choose an existing motion clip")
    v1.number(time, 0, chosen["duration"])
    if not isinstance(target, list) or len(target) != 2:
        raise ValueError("An IK target has two canvas coordinates")
    for value in target:
        v1.number(value, -4096, 4096)
    p = source["creature"]["parameters"]
    current = motion.sample(source, clip, time)
    root = motion._world_matrix(current["nodes"], "creature_root")
    hip = compose(
        root,
        motion.matrix(
            {
                **v1.TRANSFORM,
                "x": (-1 if leg == "left" else 1) * p["hip_spacing"] / 2,
                "y": p["body_height"] / 2,
            }
        ),
    )
    local_target = list(apply(inverse(hip), target))
    result = solve(p["upper_leg"], p["lower_leg"], local_target)
    updated = deepcopy(chosen)
    for part, angle in zip(("thigh", "shin"), result["angles"]):
        node = leg + "_" + part
        track = next((t for t in updated["tracks"] if t["node"] == node), None)
        if track is None:
            track = dict(node=node, keys=[_key(0), _key(chosen["duration"])])
            updated["tracks"].append(track)
        key = _key(time, angle)
        track["keys"] = sorted(
            [k for k in track["keys"] if k["time"] != time] + [key], key=lambda k: k["time"]
        )
        if chosen["loop"] and time in (0, chosen["duration"]):
            endpoint = chosen["duration"] if time == 0 else 0
            track["keys"] = [
                {**key, "time": endpoint} if k["time"] == endpoint else k for k in track["keys"]
            ]
    operations = [dict(op="clip_set", clip=updated)]
    document = v2.revise(source, operations)
    achieved = list(apply(hip, result["achieved"]))
    return dict(
        document=document,
        operations=operations,
        source_sha256=v1.structural_digest(source),
        candidate_sha256=v1.structural_digest(document),
        preview_svg=v1.render(motion.sample(document, clip, time)),
        target=deepcopy(target),
        achieved=achieved,
        error=math.dist(achieved, target),
        reachable=result["reachable"],
        angles=result["angles"],
        sockets=sockets(document, clip, time),
    )
