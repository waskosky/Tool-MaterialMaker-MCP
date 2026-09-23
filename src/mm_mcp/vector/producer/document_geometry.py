"""Host-only, bounded filled geometry. Clipper owns topology; RAI owns the contract.

Coordinates snap to 1/1024 canvas unit after curves flatten to 0.25 unit.
The input is typed vector data, never SVG, executable code or a file path.
"""

import math

import pyclipper as clip

from . import document as v1

DEPENDENCIES = {"pyclipper": "1.4.0"}
GRID = 1024
TOLERANCE = 0.25
MAX_VERTICES = 2048


def bounded(paths):
    if sum(map(len, paths)) > MAX_VERTICES:
        raise ValueError("Construction exceeds 2048 flattened vertices; simplify the source")
    if any(abs(c) > 8192 * GRID for path in paths for point in path for c in point):
        raise ValueError("Constructed geometry exceeds the ±8192 canvas coordinate bound")
    return paths


def boolean(subject, other=(), operation="union", *, tree=False):
    if clip.__version__ != DEPENDENCIES["pyclipper"]:
        raise ValueError("Construction requires the pinned pyclipper 1.4.0 host dependency")
    bounded(list(subject) + list(other))
    if not subject and not other:
        return []
    if not subject and operation in ("difference", "intersection"):
        return []
    if not other and operation == "intersection":
        return []
    engine = clip.Pyclipper()
    if subject:
        engine.AddPaths(subject, clip.PT_SUBJECT, True)
    if other:
        engine.AddPaths(other, clip.PT_CLIP, True)
    code = {
        "union": clip.CT_UNION,
        "difference": clip.CT_DIFFERENCE,
        "intersection": clip.CT_INTERSECTION,
        "xor": clip.CT_XOR,
    }[operation]
    result = (engine.Execute2 if tree else engine.Execute)(code, clip.PFT_NONZERO, clip.PFT_NONZERO)
    bounded(clip.PolyTreeToPaths(result) if tree else result)
    return result


def offset(paths, distance, join):
    if not paths or not distance:
        return paths
    engine = clip.PyclipperOffset(miter_limit=2, arc_tolerance=TOLERANCE * GRID)
    engine.AddPaths(
        bounded(paths),
        {"round": clip.JT_ROUND, "miter": clip.JT_MITER, "square": clip.JT_SQUARE}[join],
        clip.ET_CLOSEDPOLYGON,
    )
    return bounded(engine.Execute(distance * GRID))


def _point(point, transforms):
    x, y = point
    for t in transforms:
        x, y = x * t["scale_x"], y * t["scale_y"]
        c, s = math.cos(math.radians(t["rotation"])), math.sin(math.radians(t["rotation"]))
        x, y = c * x - s * y + t["x"], s * x + c * y + t["y"]
    return x, y


def _curve(points, output, depth=0):
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    deviation = max(
        (abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / length if length else math.dist(p, a))
        for p in points[1:-1]
    )
    # Also bound backtracking along an otherwise collinear control polygon.
    excess = sum(math.dist(p, q) for p, q in zip(points, points[1:])) - length
    if deviation <= TOLERANCE and excess <= TOLERANCE:
        output.append(b)
        if len(output) > MAX_VERTICES:
            raise ValueError("Curve exceeds the construction vertex budget")
        return
    if depth >= 16:
        raise ValueError("Curve exceeds the construction subdivision budget")
    levels = [points]
    while len(levels[-1]) > 1:
        levels.append(
            [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(levels[-1], levels[-1][1:])]
        )
    _curve([level[0] for level in levels], output, depth + 1)
    _curve([level[-1] for level in reversed(levels)], output, depth + 1)


def _rings(node, transforms):
    g, kind = node["geometry"], node["kind"]

    def point(p):
        return _point(p, transforms)

    if kind in ("rect", "ellipse"):
        if kind == "ellipse":
            cx, cy, rx, ry = (g[k] for k in ("cx", "cy", "rx", "ry"))
            if not rx or not ry:
                return []
            centers = [(cx, cy)] * 4
        else:
            x, y, w, h = (g[k] for k in ("x", "y", "width", "height"))
            if not w or not h:
                return []
            rx, ry = min(g["radius"], w / 2), min(g["radius"], h / 2)
            if not rx:
                return [[point(p) for p in [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]]
            centers = [
                (x + w - rx, y + h - ry),
                (x + rx, y + h - ry),
                (x + rx, y + ry),
                (x + w - rx, y + ry),
            ]
        scale = math.prod(max(t["scale_x"], t["scale_y"]) for t in transforms)
        radius = max(rx, ry) * scale
        angle = math.acos(max(-1, 1 - TOLERANCE / max(radius, TOLERANCE)))
        count = max(2, math.ceil(math.pi / (4 * angle)))
        if 4 * (count + 1) > MAX_VERTICES:
            raise ValueError("Ellipse exceeds the construction vertex budget")
        return [
            [
                point(
                    (
                        cx + rx * math.cos((quarter + i / count) * math.pi / 2),
                        cy + ry * math.sin((quarter + i / count) * math.pi / 2),
                    )
                )
                for quarter, (cx, cy) in enumerate(centers)
                for i in range(count + 1)
            ]
        ]
    rings, current = [], []
    for command in g["commands"]:
        op = command[0]
        points = [point(command[i : i + 2]) for i in range(1, len(command), 2)]
        if op == "M":
            if current:
                raise ValueError("Construction needs explicitly closed paths; close each outline")
            current = points
        elif op == "L":
            current.extend(points)
        elif op in ("Q", "C"):
            _curve([current[-1], *points], current)
        elif op == "Z":
            rings.append(current)
            current = []
    if current:
        raise ValueError("Construction needs explicitly closed paths; close each outline")
    return rings


def operands(document):
    """One nonzero-filled operand per visible shape, in authored node order."""
    v1.validate(document)
    index = {n["id"]: n for n in document["nodes"]}
    result, total = [], 0
    for node in document["nodes"]:
        if node["kind"] == "group":
            continue
        ancestors, current = [], node
        while current:
            ancestors.append(current)
            current = index.get(current["parent"])
        if any(not n["visible"] or n["opacity"] == 0 for n in ancestors):
            continue
        if any(n["opacity"] != 1 for n in ancestors) or (
            node["stroke"] != "none" and node["stroke_width"] > 0
        ):
            raise ValueError("Construction/SDF needs opaque filled shapes without strokes")
        if node["fill"] == "none":
            continue
        paths = []
        for ring in _rings(node, [n["transform"] for n in ancestors]):
            snapped = []
            for p in ring:
                xy = [round(c * GRID) for c in p]
                if not snapped or xy != snapped[-1]:
                    snapped.append(xy)
            if len(snapped) > 1 and snapped[0] == snapped[-1]:
                snapped.pop()
            if len(snapped) >= 3:
                paths.append(snapped)
        total += sum(map(len, paths))
        if total > MAX_VERTICES:
            raise ValueError("Source exceeds 2048 flattened vertices")
        paths = boolean(bounded(paths))
        paint = node["fill"]
        result.append((paths, document["palette"][paint[1:]] if paint.startswith("@") else paint))
    return result


def _canonical(ring):
    ring = [tuple(p) for p in ring]
    start = min(range(len(ring)), key=lambda i: ring[i:] + ring[:i])
    return ring[start:] + ring[:start]


def parts(paths, fill, prefix):
    """Keep holes in the same SVG path; nested islands become separate parts."""
    tree = boolean(paths, tree=True)
    if not tree:
        return []
    groups = []

    def visit(item):
        for child in item.Childs:
            if not child.IsHole:
                outer = _canonical(child.Contour)
                holes = sorted(_canonical(c.Contour) for c in child.Childs if c.IsHole)
                groups.append([outer, *holes])
            visit(child)

    visit(tree)
    nodes = []
    for i, rings in enumerate(sorted(groups)):
        commands = []
        for ring in rings:
            commands.extend(
                [["M" if j == 0 else "L", x / GRID, y / GRID] for j, (x, y) in enumerate(ring)]
            )
            commands.append(["Z"])
        if len(commands) > 256:
            raise ValueError("Constructed path exceeds 256 commands; simplify the shape or holes")
        nodes.append(v1.node(f"{prefix}_{i}", "path", {"commands": commands}, fill=fill))
    return nodes
