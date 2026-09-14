"""Small, dependency-free geometry vocabulary; no arbitrary SVG import."""

from __future__ import annotations

import math
from typing import Iterable

Point = tuple[float, float]
Transform = tuple[float, float, float, float, float, float]
IDENTITY: Transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def transform(x: float, y: float, angle: float = 0, sx: float = 1, sy: float = 1) -> Transform:
    c, s = math.cos(angle), math.sin(angle)
    return c * sx, s * sx, -s * sy, c * sy, x, y


def apply(m: Transform, p: Point) -> Point:
    a, b, c, d, x, y = m
    return a * p[0] + c * p[1] + x, b * p[0] + d * p[1] + y


def compose(a: Transform, b: Transform) -> Transform:
    return (
        a[0] * b[0] + a[2] * b[1],
        a[1] * b[0] + a[3] * b[1],
        a[0] * b[2] + a[2] * b[3],
        a[1] * b[2] + a[3] * b[3],
        a[0] * b[4] + a[2] * b[5] + a[4],
        a[1] * b[4] + a[3] * b[5] + a[5],
    )


def inverse(m: Transform) -> Transform:
    a, b, c, d, x, y = m
    det = a * d - b * c
    if abs(det) < 1e-10:
        raise ValueError("Singular transform")
    return d / det, -b / det, -c / det, a / det, (c * y - d * x) / det, (b * x - a * y) / det


def bezier(points: list[Point], t: float) -> Point:
    u = 1 - t
    w = (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)
    return tuple(sum(w[i] * points[i][j] for i in range(4)) for j in range(2))  # type: ignore[return-value]


def bezier_tangent(p: list[Point], t: float) -> Point:
    u = 1 - t
    return tuple(
        3 * u * u * (p[1][j] - p[0][j])
        + 6 * u * t * (p[2][j] - p[1][j])
        + 3 * t * t * (p[3][j] - p[2][j])
        for j in range(2)
    )  # type: ignore[return-value]


def superellipse(rx: float, ry: float, exponent: float, count: int) -> list[Point]:
    result = []
    for i in range(count):
        t = math.tau * i / count
        c, s = math.cos(t), math.sin(t)
        result.append(
            (
                rx * math.copysign(abs(c) ** (2 / exponent), c),
                ry * math.copysign(abs(s) ** (2 / exponent), s),
            )
        )
    return result


def tube(p: list[Point], widths: list[float], count: int) -> list[Point]:
    """Sample a cubic centerline and a linearly interpolated radius profile.

    Flat end caps intentionally overlap joint/attachment shapes. The trusted
    recipes limit curvature/radius; validate_polygons can detect failures.
    """
    left, right = [], []
    for i in range(count + 1):
        t = i / count
        c = bezier(p, t)
        tangent = bezier_tangent(p, t)
        length = math.hypot(*tangent)
        if length < 1e-8:
            raise ValueError("Degenerate tube tangent")
        n = (-tangent[1] / length, tangent[0] / length)
        at = t * (len(widths) - 1)
        k = min(int(at), len(widths) - 2)
        radius = widths[k] + (widths[k + 1] - widths[k]) * (at - k)
        left.append((c[0] + radius * n[0], c[1] + radius * n[1]))
        right.append((c[0] - radius * n[0], c[1] - radius * n[1]))
    return left + right[::-1]


def leaf(length: float, width: float, curl: float, count: int) -> list[Point]:
    a = [(0, 0), (length * 0.28, -width), (length * 0.8, -width + curl), (length, curl)]
    b = [(length, curl), (length * 0.75, width + curl), (length * 0.2, width), (0, 0)]
    return [bezier(a, i / count) for i in range(count)] + [
        bezier(b, i / count) for i in range(count)
    ]


def area(p: list[Point]) -> float:
    return 0.5 * sum(
        p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p))
    )


def self_intersects(p: list[Point]) -> bool:
    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    n = len(p)
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = p[j], p[(j + 1) % n]
            if cross(a, b, c) * cross(a, b, d) < -1e-9 and cross(c, d, a) * cross(c, d, b) < -1e-9:
                return True
    return False


def two_bone(target: Point, upper: float, lower: float, bend: float) -> tuple[float, float, bool]:
    """Return local angles for a +Y-oriented two-link chain, clamping reach."""
    distance = math.hypot(*target)
    near, far = abs(upper - lower) + 1e-6, upper + lower - 1e-6
    d = max(near, min(far, distance))
    c = max(-1.0, min(1.0, (d * d - upper * upper - lower * lower) / (2 * upper * lower)))
    elbow = math.acos(c) * (1 if bend >= 0 else -1)
    shoulder = (
        math.atan2(target[1], target[0])
        - math.atan2(lower * math.sin(elbow), upper + lower * math.cos(elbow))
        - math.pi / 2
    )
    return shoulder, elbow, abs(d - distance) > 1e-5


def bounds(points: Iterable[Point]) -> list[float]:
    values = list(points)
    if not values:
        return [0.0, 0.0, 1.0, 1.0]
    xs, ys = zip(*values)
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
