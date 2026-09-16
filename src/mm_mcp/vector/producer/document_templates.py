"""Small editable starting points, not prompt-to-image model output."""

from .document import SCHEMA, node, validate


def create(template="blank"):
    document = {
        "schema": SCHEMA,
        "canvas": {"width": 256, "height": 256},
        "palette": {"ink": "#172B3A", "body": "#376B76", "accent": "#8DE5C4", "light": "#EAF3DF"},
        "nodes": [],
    }

    def rect(key, x, y, w, h, paint, radius=8, **extra):
        return node(
            key,
            "rect",
            {"x": x, "y": y, "width": w, "height": h, "radius": radius},
            fill="@" + paint,
            **extra,
        )

    def path(key, commands, paint, **extra):
        return node(key, "path", {"commands": commands}, fill="@" + paint, **extra)

    if template == "power_cell":
        document["nodes"] = [
            rect("contact", 102, 28, 52, 24, "light", 5),
            rect("body", 70, 45, 116, 177, "body", 22, stroke="@ink", stroke_width=8),
            rect("rim", 81, 59, 94, 16, "light", 6),
            rect("charge", 84, 157, 88, 50, "accent", 10),
            path(
                "energy",
                [
                    ["M", 134, 85],
                    ["L", 104, 134],
                    ["L", 128, 134],
                    ["L", 119, 169],
                    ["L", 153, 117],
                    ["L", 129, 117],
                    ["Z"],
                ],
                "light",
            ),
        ]
    elif template == "medical_kit":
        document["nodes"] = [
            rect("handle", 91, 51, 74, 52, "ink", 14),
            rect("handle_cutout", 104, 64, 48, 29, "light", 4),
            rect("body", 42, 82, 172, 130, "body", 24, stroke="@ink", stroke_width=8),
            rect("band", 48, 109, 160, 20, "accent", 0),
            node("badge", "ellipse", {"cx": 128, "cy": 151, "rx": 37, "ry": 37}, fill="@light"),
            path(
                "cross",
                [
                    ["M", 119, 126],
                    ["L", 137, 126],
                    ["L", 137, 142],
                    ["L", 153, 142],
                    ["L", 153, 160],
                    ["L", 137, 160],
                    ["L", 137, 176],
                    ["L", 119, 176],
                    ["L", 119, 160],
                    ["L", 103, 160],
                    ["L", 103, 142],
                    ["L", 119, 142],
                    ["Z"],
                ],
                "body",
            ),
        ]
    elif template == "beacon":
        document["canvas"] = {"width": 256, "height": 384}
        document["nodes"] = [
            node("signal", "group", {}, fill="none", name="Signal assembly"),
            rect("foot", 51, 341, 154, 23, "ink", 8),
            path(
                "stand",
                [["M", 101, 206], ["L", 155, 206], ["L", 172, 344], ["L", 84, 344], ["Z"]],
                "body",
                stroke="@ink",
                stroke_width=6,
            ),
            rect("stripe", 103, 251, 50, 12, "accent", 4),
            path(
                "housing",
                [
                    ["M", 82, 88],
                    ["Q", 128, 59, 174, 88],
                    ["L", 164, 207],
                    ["Q", 128, 226, 92, 207],
                    ["Z"],
                ],
                "body",
                parent="signal",
                stroke="@ink",
                stroke_width=7,
            ),
            path(
                "glass",
                [
                    ["M", 95, 102],
                    ["Q", 128, 81, 161, 102],
                    ["L", 154, 172],
                    ["Q", 128, 186, 102, 172],
                    ["Z"],
                ],
                "accent",
                parent="signal",
            ),
            rect("highlight", 111, 106, 10, 48, "light", 5, parent="signal"),
            rect("cap", 111, 50, 34, 30, "ink", 5, parent="signal"),
            path(
                "fin",
                [["M", 70, 157], ["L", 91, 145], ["L", 95, 200], ["L", 73, 217], ["Z"]],
                "ink",
                parent="signal",
            ),
        ]
    elif template != "blank":
        raise ValueError("Unknown vector template")
    return validate(document)
