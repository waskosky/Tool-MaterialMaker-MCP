"""Deterministic, bounded, sampled distance texture from typed rest geometry.

Pixel centers use nonzero fill; the separable Euclidean distance transform is
linear in image area. This is a sampled SDF, not resolution-independent geometry.
"""

import base64
import math
import struct
import zlib

from . import document as v1
from . import document_geometry as geometry


def options(value):
    v1.fields(value, {"resolution", "spread"})
    if type(value["resolution"]) is not int or value["resolution"] not in (128, 256, 512):
        raise ValueError("SDF resolution must be 128, 256 or 512")
    if type(value["spread"]) is not int or not 2 <= value["spread"] <= 32:
        raise ValueError("SDF spread must be an integer from 2 to 32 texels")
    return value


def _edt_line(values):
    """Lower envelope of integer squared-distance parabolas."""
    sites, boundaries = [0], [-math.inf, math.inf]
    for q in range(1, len(values)):
        while True:
            p = sites[-1]
            cut = ((values[q] + q * q) - (values[p] + p * p)) / (2 * (q - p))
            if cut > boundaries[-2]:
                break
            sites.pop()
            boundaries.pop(-2)
        sites.append(q)
        boundaries.insert(-1, cut)
    result, k = [], 0
    for q in range(len(values)):
        while boundaries[k + 1] < q:
            k += 1
        result.append((q - sites[k]) ** 2 + values[sites[k]])
    return result


def _distances(mask, target):
    h, w = len(mask), len(mask[0])
    rows = [_edt_line([0 if value == target else 10**12 for value in row]) for row in mask]
    for x in range(w):
        column = _edt_line([rows[y][x] for y in range(h)])
        for y, value in enumerate(column):
            rows[y][x] = value
    return rows


def _coverage(paths, width, height, sx, sy):
    # Outside border defines the explicitly canvas-clipped silhouette.
    mask = [bytearray(width + 2) for _ in range(height + 2)]
    edges = []
    for path in paths:
        for a, b in zip(path, path[1:] + path[:1]):
            x1, y1 = a[0] / geometry.GRID * sx, a[1] / geometry.GRID * sy
            x2, y2 = b[0] / geometry.GRID * sx, b[1] / geometry.GRID * sy
            if y1 != y2:
                edges.append((x1, y1, x2, y2))
    for y in range(height):
        center = y + 0.5
        events = sorted(
            (x1 + (center - y1) * (x2 - x1) / (y2 - y1), 1 if y2 > y1 else -1)
            for x1, y1, x2, y2 in edges
            if min(y1, y2) <= center < max(y1, y2)
        )
        winding, previous = 0, 0
        for x, direction in events:
            if winding:
                start = max(0, min(width, math.ceil(previous - 0.5)))
                end = max(0, min(width, math.ceil(x - 0.5)))
                mask[y + 1][start + 1 : end + 1] = b"\x01" * (end - start)
            winding += direction
            previous = x
    return mask


def png(width, height, pixels):
    """Fixed stored-DEFLATE PNG; no encoder/compressor-version byte drift."""
    raw = b"".join(b"\0" + pixels[y * width : (y + 1) * width] for y in range(height))
    blocks = [raw[i : i + 65535] for i in range(0, len(raw), 65535)]
    packed = (
        b"\x78\x01"
        + b"".join(
            bytes([int(i == len(blocks) - 1)])
            + struct.pack("<HH", len(block), len(block) ^ 65535)
            + block
            for i, block in enumerate(blocks)
        )
        + struct.pack(">I", zlib.adler32(raw))
    )

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", packed)
        + chunk(b"IEND", b"")
    )


def export(document, resolution, spread):
    from .document_v2 import expand

    options({"resolution": resolution, "spread": spread})
    source = expand(document)
    paths = geometry.boolean([path for paths, _ in geometry.operands(source) for path in paths])
    canvas = source["canvas"]
    scale = resolution / max(canvas.values())
    width, height = [max(1, math.floor(canvas[k] * scale + 0.5)) for k in ("width", "height")]
    mask = _coverage(paths, width, height, width / canvas["width"], height / canvas["height"])
    inside, outside = _distances(mask, 1), _distances(mask, 0)
    pixels = bytearray()
    for y in range(1, height + 1):
        for x in range(1, width + 1):
            distance = math.sqrt(outside[y][x] if mask[y][x] else inside[y][x]) - 0.5
            signed = distance if mask[y][x] else -distance
            pixels.append(max(0, min(255, math.floor(128 + 127 * signed / spread + 0.5))))
    return {
        "schema": "rai.vector-sdf/v1",
        "source_sha256": v1.structural_digest(document),
        "canvas": dict(canvas),
        "width": width,
        "height": height,
        "resolution": resolution,
        "spread": spread,
        "channel": "r",
        "color_space": "linear",
        "pose": "rest",
        "encoding": "clamp(128+127*signed_distance/spread,0,255); positive inside",
        "sampling": (
            "nonzero pixel-center coverage; Euclidean grid distance minus 0.5 texel; canvas clipped"
        ),
        "geometry_tolerance": geometry.TOLERANCE,
        "geometry_grid": 1 / geometry.GRID,
        "png_base64": base64.b64encode(png(width, height, bytes(pixels))).decode("ascii"),
    }
