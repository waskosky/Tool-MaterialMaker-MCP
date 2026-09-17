"""V2 project commands: reusable artwork, proposals, rigs and frozen motion."""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from mm_mcp.core import ServiceError, atomic_json, canonical, digest, file_lock
from .documents import DocumentService, SCHEMA
from .producer import document as v1
from .producer import document_v2 as v2
from .producer import document_library as library
from .producer import document_motion as motion
from .ai import CodexProvider, ProposalService

BUILD_SCHEMA = "workshop.vector-document-build/v2"


def sheet(document, clip, count=16, cell=256):
    frames = motion.frames(document, clip, count)
    columns, rows = min(4, count), math.ceil(count / min(4, count))
    width, height = document["canvas"]["width"], document["canvas"]["height"]
    scale = min(cell / width, cell / height)
    left, top = (cell - width * scale) / 2, (cell - height * scale) / 2
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{columns * cell}" height="{rows * cell}" viewBox="0 0 {columns * cell} {rows * cell}">',
        f'<defs><clipPath id="cell"><rect width="{cell}" height="{cell}"/></clipPath></defs>',
    ]
    for frame in frames["frames"]:
        i = frame["index"]
        body = frame["svg"].split(">", 1)[1].rsplit("</svg>", 1)[0]
        svg.append(
            f'<g transform="translate({i % columns * cell} {i // columns * cell})"><g clip-path="url(#cell)"><g transform="translate({left} {top}) scale({scale})">{body}</g></g></g>'
        )
    svg.append("</svg>")
    timing = {k: frames[k] for k in ("clip", "duration", "loop", "source_sha256")}
    timing.update(
        schema="workshop.vector-sprite-sheet/v1",
        file="motion.sheet.svg",
        columns=columns,
        rows=rows,
        cell_width=cell,
        cell_height=cell,
        count=count,
        frames=[{"index": f["index"], "time": f["time"]} for f in frames["frames"]],
    )
    return "".join(svg).encode(), canonical(timing).encode()


class StudioService(DocumentService):
    def __init__(self, root, producer, provider=None):
        super().__init__(root, producer, v2.PROFILE)
        self.library_root = Path(root) / "vector-library"
        self.proposals = ProposalService(root, self, provider or CodexProvider())

    def project(self, row):
        result = super().project(row)
        source = result["document"]
        result["expanded_document"] = (
            v2.expand(source) if result["profile"] == v2.PROFILE else deepcopy(source)
        )
        result["instance_owners"] = {}
        if result["profile"] == v2.PROFILE:
            for node in source["nodes"]:
                if node["kind"] == "instance":
                    for part in source["components"][node["geometry"]["component"]][
                        "nodes"
                    ]:
                        key = (
                            "v_"
                            + hashlib.sha256(
                                (node["id"] + "/" + part["id"]).encode()
                            ).hexdigest()[:32]
                        )
                        result["instance_owners"][key] = node["id"]
        return result

    def command(self, request):
        v1.encode(request)
        shared = {"project_id", "expected_revision"}
        contracts = {
            "upgrade": (shared | {"idempotency_key"}, set()),
            "library_list": (set(), set()),
            "library_get": ({"library_id"}, set()),
            "library_save": (shared | {"kind", "definition_id"}, set()),
            "library_import": (
                shared | {"library_id", "idempotency_key"},
                {"target", "x", "y"},
            ),
            "ai_submit": (shared | {"intent", "selected_ids"}, set()),
            "ai_get": ({"proposal_id"}, set()),
            "ai_cancel": ({"proposal_id"}, set()),
            "ai_accept": (shared | {"proposal_id", "candidate_sha256"}, set()),
            "rig_suggest": (shared | {"preset"}, set()),
            "preview_edits": (shared | {"operations"}, set()),
            "sample": (shared | {"clip", "time"}, set()),
            "frames": (shared | {"clip", "count"}, set()),
            "mask": (shared, set()),
            "build": (shared, {"clip", "mask"}),
        }
        operation = request.get("operation") if isinstance(request, dict) else None
        if operation not in contracts:
            result = super().command(request)
            if operation == "describe":
                from .producer.authoring import controls

                result.update(
                    operations=list(
                        dict.fromkeys(result["operations"] + list(contracts))
                    ),
                    ai=self.proposals.capabilities(),
                    library_limit=128,
                    recipes=[
                        {
                            "id": "plant-rest-v1",
                            "name": "Plant rest pose",
                            "controls": controls(),
                        }
                    ],
                )
            if (
                operation == "build_get"
                and result["manifest"]["schema"] == BUILD_SCHEMA
            ):
                root = self.build_root / result["manifest"]["build_id"]
                if (root / "motion.json").exists():
                    result.update(
                        motion_sheet_svg=(root / "motion.sheet.svg").read_text(),
                        motion=json.loads((root / "motion.json").read_bytes()),
                    )
                if (root / "mask.json").exists():
                    result.update(
                        material_mask_svg=(root / "mask.svg").read_text(),
                        material_mask=json.loads((root / "mask.json").read_bytes()),
                    )
            return result
        required, optional = contracts[operation]
        v1.fields(request, {"profile", "operation"} | required, optional)
        if request["profile"] != v2.PROFILE:
            raise ServiceError("VECTOR_VERSION", "Use the v2 artwork profile.")
        if operation == "library_list":
            return self.library_list()
        if operation == "library_get":
            return {"ok": True, "entry": self.library_get(request["library_id"])}
        if operation in ("ai_get", "ai_cancel"):
            return getattr(self.proposals, operation[3:])(request["proposal_id"])
        if operation == "ai_accept":
            return self.proposals.accept(
                request["proposal_id"],
                request["project_id"],
                request["expected_revision"],
                request["candidate_sha256"],
            )
        if operation == "upgrade":
            return self.store.patch(
                request["project_id"],
                request["expected_revision"],
                [{"op": "upgrade"}],
                request["idempotency_key"],
            )
        # Imported bytes are independently hash-pinned; GraphStore fences and
        # persists the exact proposed patch. Retrying retains the original receipt.
        if operation == "library_import":
            entry = self.library_get(request["library_id"])
            operations = [
                {
                    "op": "library_import",
                    "snapshot": entry["snapshot"],
                    "target": request.get("target"),
                    "x": request.get("x", 0),
                    "y": request.get("y", 0),
                }
            ]
            return self.store.patch(
                request["project_id"],
                request["expected_revision"],
                operations,
                request["idempotency_key"],
            )
        project = self.current(request)
        v2.validate(project["document"])
        if operation == "library_save":
            return self.library_save(
                project["document"], request["kind"], request["definition_id"]
            )
        if operation == "ai_submit":
            return self.proposals.submit(
                project, request["intent"], request["selected_ids"]
            )
        if operation == "build":
            return self.build(project, request.get("clip"), request.get("mask", False))
        if operation == "preview_edits":
            candidate = v2.revise(project["document"], request["operations"])
            return {
                "ok": True,
                "document": candidate,
                "preview_svg": v2.render(candidate),
                "project_id": project["project_id"],
                "revision": project["revision"],
                "source_sha256": project["content_sha256"],
                "candidate_sha256": v1.structural_digest(candidate),
            }
        fields = {
            "rig_suggest": ("preset",),
            "sample": ("clip", "time"),
            "frames": ("clip", "count"),
            "mask": (),
        }[operation]
        result = v2.execute(
            {
                "profile": v2.PROFILE,
                "operation": operation,
                "source": project["document"],
                **{k: request[k] for k in fields},
            }
        )
        return {
            "ok": True,
            **result,
            "project_id": project["project_id"],
            "revision": project["revision"],
            "source_sha256": project["content_sha256"],
        }

    def patch(self, source, operations):
        if (
            isinstance(operations, list)
            and len(operations) == 1
            and isinstance(operations[0], dict)
            and operations[0].get("op") == "library_import"
        ):
            op = operations[0]
            v1.fields(op, {"op", "snapshot", "target", "x", "y"})
            edits = library.import_edits(
                source, op["snapshot"], target=op["target"], x=op["x"], y=op["y"]
            )
            return v2.revise(source, edits["operations"]), [
                {
                    "op": "library_import",
                    "snapshot_sha256": digest(op["snapshot"]),
                    "definition_id": edits["definition_id"],
                    "selected_id": edits["selected_id"],
                }
            ]
        return super().patch(source, operations)

    def library_get(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"l_[a-f0-9]{64}", key):
            raise ServiceError("VECTOR_LIBRARY", "Invalid library identity.")
        path = self.library_root / (key + ".json")
        if (
            not path.is_file()
            or path.is_symlink()
            or self.library_root.is_symlink()
            or path.stat().st_size > 256 * 1024
        ):
            raise ServiceError(
                "VECTOR_LIBRARY", "Library entry is missing or exceeds its bound."
            )
        try:
            entry = json.loads(path.read_bytes())
            v1.fields(entry, {"schema", "library_id", "snapshot", "producer"})
            library.validate_snapshot(entry["snapshot"])
            if (
                entry["schema"] != "workshop.vector-library-entry/v1"
                or entry["library_id"] != key
                or "l_"
                + digest({"snapshot": entry["snapshot"], "producer": entry["producer"]})
                != key
            ):
                raise ValueError("Library hash differs")
            return entry
        except (ValueError, TypeError, KeyError) as exc:
            raise ServiceError(
                "VECTOR_LIBRARY", "Library bytes differ from their immutable identity."
            ) from exc

    def library_list(self):
        if not self.library_root.exists():
            return {"ok": True, "entries": []}
        paths = list(self.library_root.glob("l_*.json"))
        if len(paths) > 128:
            raise ServiceError(
                "VECTOR_LIBRARY", "Library inventory exceeds 128 saved entries."
            )
        entries = [self.library_get(p.stem) for p in sorted(paths)]
        return {
            "ok": True,
            "entries": [
                {
                    "library_id": e["library_id"],
                    "kind": e["snapshot"]["kind"],
                    "name": e["snapshot"]["name"],
                }
                for e in entries
            ],
        }

    def library_save(self, document, kind, definition_id):
        v1.identifier(definition_id)
        if (
            kind not in ("component", "style")
            or definition_id not in document[kind + "s"]
        ):
            raise ServiceError(
                "VECTOR_LIBRARY", "Choose an existing style or component definition."
            )
        snapshot = library.snapshot(
            document, kind, definition_id, document[kind + "s"][definition_id]["name"]
        )
        key = "l_" + digest({"snapshot": snapshot, "producer": self.producer})
        self.library_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.library_root.is_symlink():
            raise ServiceError(
                "VECTOR_LIBRARY", "Library must be an owned regular directory."
            )
        with file_lock(self.library_root / ".library.lock"):
            path = self.library_root / (key + ".json")
            if not path.exists():
                if len(self.library_list()["entries"]) >= 128:
                    raise ServiceError(
                        "VECTOR_LIBRARY", "The library contains 128 saved entries."
                    )
                atomic_json(
                    path,
                    {
                        "schema": "workshop.vector-library-entry/v1",
                        "library_id": key,
                        "snapshot": snapshot,
                        "producer": self.producer,
                    },
                )
            return {"ok": True, "entry": self.library_get(key)}

    def build(self, project, clip=None, mask=False):
        if project["profile"] != v2.PROFILE:
            return super().build(project)
        if clip is not None:
            v1.identifier(clip)
        if type(mask) is not bool:
            raise ValueError("Mask export must be explicitly true or false")
        source = {
            k: project[k]
            for k in (
                "schema",
                "project_id",
                "title",
                "revision",
                "document",
                "producer",
            )
        }
        source["export"] = {"clip": clip, "count": 16, "cell": 256}
        if mask:
            source["export"]["mask"] = True
        build_id = "d_" + digest(source)
        self.build_root.mkdir(parents=True, exist_ok=True)
        target = self.build_root / build_id
        with file_lock(self.build_root / ".build.lock"):
            if not target.exists():
                files = self._files(source)
                manifest = {
                    "schema": BUILD_SCHEMA,
                    "status": "complete",
                    "build_id": build_id,
                    "project_id": project["project_id"],
                    "revision": project["revision"],
                    "content_sha256": project["content_sha256"],
                    "producer": self.producer,
                    "files": [
                        {
                            "name": n,
                            "bytes": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        }
                        for n, raw in sorted(files.items())
                    ],
                }
                with tempfile.TemporaryDirectory(
                    prefix=".document-", dir=self.build_root
                ) as temporary:
                    stage = Path(temporary) / "build"
                    stage.mkdir()
                    for name, raw in files.items():
                        (stage / name).write_bytes(raw)
                    (stage / "manifest.json").write_text(canonical(manifest))
                    os.replace(stage, target)
            return {"ok": True, "manifest": self.get_build(build_id)[0]}

    @staticmethod
    def _files(source):
        v1.fields(
            source,
            {
                "schema",
                "project_id",
                "title",
                "revision",
                "document",
                "producer",
                "export",
            },
        )
        v1.fields(source["export"], {"clip", "count", "cell"}, {"mask"})
        if "mask" in source["export"] and source["export"]["mask"] is not True:
            raise ValueError("Invalid frozen mask option")
        if source["export"]["count"] != 16 or source["export"]["cell"] != 256:
            raise ValueError("Unsupported motion export format")
        v2.validate(source["document"])
        files = {
            "project.json": canonical(source).encode(),
            "document.json": canonical(source["document"]).encode(),
            "preview.svg": v2.render(source["document"]).encode(),
        }
        if source["export"]["clip"] is not None:
            files["motion.sheet.svg"], files["motion.json"] = sheet(
                source["document"], source["export"]["clip"]
            )
        if source["export"].get("mask"):
            result = v2.execute(
                {
                    "profile": v2.PROFILE,
                    "operation": "mask",
                    "source": source["document"],
                }
            )
            files["mask.svg"] = result.pop("svg").encode()
            result.pop("operation")
            result.pop("profile")
            result["file"] = "mask.svg"
            files["mask.json"] = canonical(result).encode()
        if sum(map(len, files.values())) > 4 * 1024 * 1024:
            raise ValueError("Animation build exceeds four MiB")
        return files

    def get_build(self, build_id):
        if not isinstance(build_id, str) or not re.fullmatch(
            r"d_[a-f0-9]{64}", build_id
        ):
            raise ServiceError("VECTOR_BUILD", "Invalid artwork build ID.")
        root = self.build_root / build_id
        path = root / "manifest.json"
        if (
            not root.is_dir()
            or root.is_symlink()
            or not path.is_file()
            or path.is_symlink()
            or path.stat().st_size > 32768
        ):
            raise ServiceError("BUILD_NOT_FOUND", "Artwork build not found.")
        try:
            manifest = json.loads(path.read_bytes())
            if manifest["schema"] != BUILD_SCHEMA:
                return super().get_build(build_id)
            paths = list(root.iterdir())
            if len(paths) not in (4, 6, 8) or any(
                p.is_symlink() or not p.is_file() or p.stat().st_size > 4 * 1024 * 1024
                for p in paths
            ):
                raise ValueError("Inventory")
            source = json.loads((root / "project.json").read_bytes())
            expected = self._files(source)
            if {p.name for p in paths} != set(expected) | {"manifest.json"}:
                raise ValueError("Inventory")
            records = [
                {
                    "name": n,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
                for n, raw in sorted(expected.items())
            ]
            if (
                manifest["status"] != "complete"
                or manifest["build_id"] != build_id
                or "d_" + digest(source) != build_id
                or source["schema"] != SCHEMA
                or manifest["files"] != records
                or any(
                    source[k] != manifest[k]
                    for k in ("project_id", "revision", "producer")
                )
                or manifest["content_sha256"]
                != v1.structural_digest(source["document"])
                or any(
                    (root / name).read_bytes() != raw for name, raw in expected.items()
                )
            ):
                raise ValueError("Frozen bytes")
            return manifest, source, expected["preview.svg"].decode()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ServiceError(
                "ARTIFACT_CORRUPT",
                "Artwork or motion bytes differ from the frozen source.",
            ) from exc
