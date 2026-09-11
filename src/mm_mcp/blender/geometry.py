"""Pure geometry diagnostics, shared by portable tests and the fixed bpy worker."""
import math
from collections import Counter


def mesh_diagnostics(vertices, triangles, uv_triangles=None, *, normals=None, scale=(1, 1, 1), material_slots=0):
    edges = Counter()
    degenerate = 0
    for tri in triangles:
        a, b, c = (vertices[i] for i in tri)
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        cross = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]
        degenerate += sum(v * v for v in cross) < 1e-20
        edges.update(tuple(sorted((tri[i], tri[(i + 1) % 3]))) for i in range(3))
    pixels = Counter()
    outside = uv_degenerate = 0
    present = uv_triangles is not None and len(uv_triangles) == len(triangles)
    if present:
        for uv in uv_triangles:
            outside += any(not math.isfinite(v) or v < -1e-6 or v > 1 + 1e-6 for point in uv for v in point)
            a, b, c = uv
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denominator) < 1e-12:
                uv_degenerate += 1
                continue
            for y in range(max(0, int(min(v[1] for v in uv) * 64)), min(64, math.ceil(max(v[1] for v in uv) * 64))):
                for x in range(max(0, int(min(v[0] for v in uv) * 64)), min(64, math.ceil(max(v[0] for v in uv) * 64))):
                    px, py = (x + .5) / 64, (y + .5) / 64
                    u = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / denominator
                    v = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / denominator
                    if min(u, v, 1 - u - v) > 1e-8:
                        pixels[(x, y)] += 1
    overlaps = sum(count > 1 for count in pixels.values())
    invalid_normals = sum(not all(math.isfinite(v) for v in normal) or sum(v * v for v in normal) < .25 for normal in normals or [])
    return {
        'vertices': len(vertices), 'triangles': len(triangles), 'material_slots': material_slots,
        'topology': {'boundary_edges': sum(n == 1 for n in edges.values()), 'non_manifold_edges': sum(n > 2 for n in edges.values()), 'degenerate_triangles': degenerate},
        'uv': {'present': present, 'degenerate_triangles': uv_degenerate, 'out_of_tile_triangles': outside, 'sampled_overlap_pixels': overlaps, 'sample_grid': 64,
               'bake_ready': bool(present and not outside and not uv_degenerate and not overlaps),
               'notes': 'Overlap screening samples a 64×64 grid; small subpixel overlaps may require artist review.'},
        'normals': {'present': normals is not None, 'invalid_vertices': invalid_normals},
        'transforms': {'scale': list(scale), 'non_uniform_scale': max(scale) - min(scale) > 1e-6, 'negative_scale': any(v < 0 for v in scale)},
    }
