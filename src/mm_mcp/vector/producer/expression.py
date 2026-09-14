"""A bounded arithmetic language shared with the Godot implementation.

Recipes are trusted, versioned application data. Asset documents contain only
validated parameters, never expressions or executable code.
"""

from __future__ import annotations

import math
from typing import Any


def named_random(seed: int, namespace: str, name: str) -> float:
    """FNV-1a over UTF-8. Unrelated features never consume a shared RNG stream."""
    h = 2166136261
    for b in f"{seed}|{namespace}|{name}".encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    # Avalanche the high/low bits; all products fit signed 64-bit in GDScript.
    h ^= h >> 16
    h = (h * 73244475) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 73244475) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFFFFFF) / 4294967296.0


def evaluate(expr: Any, env: dict[str, Any], depth: int = 0) -> Any:
    if depth > 48:
        raise ValueError("Expression nesting limit exceeded")
    if not isinstance(expr, list):
        return expr
    if not expr or not isinstance(expr[0], str):
        raise ValueError("Malformed expression")
    op = expr[0]
    if op == "v":
        return env[expr[1]]
    if op == "rand":
        return named_random(int(env["_seed"]), env["_namespace"], str(expr[1]))
    if op == "if":
        return evaluate(expr[2] if evaluate(expr[1], env, depth + 1) else expr[3], env, depth + 1)
    a = [evaluate(x, env, depth + 1) for x in expr[1:]]
    if op == "+":
        return a[0] + a[1]
    if op == "-":
        return a[0] - a[1]
    if op == "*":
        return a[0] * a[1]
    if op == "/":
        return a[0] / a[1]
    if op == "pow":
        return a[0] ** a[1]
    if op == "sin":
        return math.sin(a[0])
    if op == "cos":
        return math.cos(a[0])
    if op == "abs":
        return abs(a[0])
    if op == "sqrt":
        return math.sqrt(max(0, a[0]))
    if op == "floor":
        return math.floor(a[0])
    if op == "min":
        return min(a)
    if op == "max":
        return max(a)
    if op == "clamp":
        return max(a[1], min(a[2], a[0]))
    if op == "mix":
        return a[0] + (a[1] - a[0]) * a[2]
    if op == "fract":
        return a[0] - math.floor(a[0])
    if op == "smooth":
        t = max(0.0, min(1.0, a[0]))
        return t * t * (3.0 - 2.0 * t)
    if op == "eq":
        return a[0] == a[1]
    if op == "lt":
        return a[0] < a[1]
    if op == "and":
        return all(a)
    if op == "or":
        return any(a)
    raise ValueError(f"Unknown recipe operation: {op}")
