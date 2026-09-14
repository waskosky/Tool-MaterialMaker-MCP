"""Cross-runtime structural JSON identity for portable game content.

RFC 8785 depends on ECMAScript's exact shortest-number rendering. Godot 4.7
does not expose that formatter, so hashing re-serialized JSON text would make
otherwise valid RAI bundles disagree with the runtime for ordinary finite
floats. This profile hashes JSON structure directly and represents every number
by its normalized IEEE-754 binary64 bits.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

PROFILE_ID = "rai.structural-json.binary64-utf8/v1"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_DEPTH = 64
MAX_NODES = 1_000_000


class PortableDigestError(ValueError):
    """Raised when a value is outside the portable JSON identity domain."""


def structural_bytes(value: Any) -> bytes:
    """Encode JSON data into the collision-free v1 structural byte stream.

    Tags are followed by either fixed-width data or a decimal count/length and
    a colon. Object keys are sorted by their UTF-8 bytes. Integers must be
    exactly representable as binary64; finite floats retain their binary64
    value, with negative zero normalized to positive zero.
    """

    output = bytearray()
    budget = [0]
    _encode(value, output, depth=0, budget=budget, path="$")
    return bytes(output)


def structural_digest(value: Any) -> str:
    return hashlib.sha256(structural_bytes(value)).hexdigest()


def _counted_prefix(output: bytearray, tag: bytes, count: int) -> None:
    output.extend(tag)
    output.extend(str(count).encode("ascii"))
    output.extend(b":")


def _encode(
    value: Any,
    output: bytearray,
    *,
    depth: int,
    budget: list[int],
    path: str,
) -> None:
    budget[0] += 1
    if budget[0] > MAX_NODES:
        raise PortableDigestError("Structural JSON exceeds the node budget")
    if depth > MAX_DEPTH:
        raise PortableDigestError(f"Structural JSON exceeds the nesting limit at {path}")
    if value is None:
        output.extend(b"n")
        return
    if isinstance(value, bool):
        output.extend(b"t" if value else b"f")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise PortableDigestError(f"Integer is outside the exact binary64 range at {path}")
        _encode_number(float(value), output, path)
        return
    if isinstance(value, float):
        _encode_number(value, output, path)
        return
    if isinstance(value, str):
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise PortableDigestError(f"String is not valid Unicode at {path}") from exc
        _counted_prefix(output, b"s", len(encoded))
        output.extend(encoded)
        return
    if isinstance(value, list):
        _counted_prefix(output, b"a", len(value))
        for index, child in enumerate(value):
            _encode(child, output, depth=depth + 1, budget=budget, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        encoded_keys: list[tuple[bytes, str]] = []
        for key in value:
            if not isinstance(key, str):
                raise PortableDigestError(f"Object key is not a string at {path}")
            try:
                encoded_key = key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PortableDigestError(f"Object key is not valid Unicode at {path}") from exc
            encoded_keys.append((encoded_key, key))
        encoded_keys.sort(key=lambda item: item[0])
        _counted_prefix(output, b"o", len(encoded_keys))
        for _encoded_key, key in encoded_keys:
            _encode(key, output, depth=depth + 1, budget=budget, path=f"{path}.<key>")
            _encode(value[key], output, depth=depth + 1, budget=budget, path=f"{path}.{key}")
        return
    raise PortableDigestError(f"Unsupported JSON value {type(value).__name__} at {path}")


def _encode_number(value: float, output: bytearray, path: str) -> None:
    if not math.isfinite(value):
        raise PortableDigestError(f"Number must be finite at {path}")
    if value == 0.0:
        value = 0.0
    output.extend(b"d")
    output.extend(struct.pack("<d", value).hex().encode("ascii"))
