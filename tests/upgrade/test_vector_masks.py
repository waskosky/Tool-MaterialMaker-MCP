import hashlib
import io
import json
import zipfile

import pytest

from mm_mcp.core import ServiceError
from mm_mcp.vector.producer import document_v2 as v2
from test_vector_studio import call, current, patch, read


def test_mask_freezes_exact_revision_with_source_and_preserves_old_exports(app):
    p = call(app.vectors, "create", template="emblem", title="Emblem")
    plain = current(app.vectors, p, "build")["manifest"]["build_id"]
    old = app.vectors.studio.export(plain)
    mask = current(app.vectors, p, "mask")
    assert read(app.vectors, p)["revision"] == 0
    built = current(app.vectors, p, "build", mask=True)["manifest"]
    result = call(app.vectors, "build_get", build_id=built["build_id"])
    assert result["material_mask_svg"] == mask["svg"]
    assert result["material_mask"]["source_sha256"] == p["content_sha256"]
    raw = app.vectors.studio.export(built["build_id"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "project.json",
            "document.json",
            "preview.svg",
            "mask.svg",
            "mask.json",
        }
    params = p["document"]["components"]["rays"]["recipe"]["request"]["settings"]
    changed = patch(
        app.vectors,
        p,
        [
            {
                "op": "modifier_update",
                "id": "rays",
                "settings": {**params, "count": 6, "angle": 60},
            }
        ],
    )
    assert app.vectors.studio.export(built["build_id"]) == raw
    assert app.vectors.studio.export(plain) == old
    assert (
        current(app.vectors, changed, "build", mask=True)["manifest"]["build_id"]
        != built["build_id"]
    )
    with pytest.raises(ServiceError, match="changed"):
        current(app.vectors, p, "build", mask=True)


def test_mask_rejects_tampered_bytes_even_with_rehashed_manifest(app):
    p = call(app.vectors, "create", template="emblem")
    build = current(app.vectors, p, "build", mask=True)["manifest"]
    root = app.vectors.studio.build_root / build["build_id"]
    raw = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    (root / "mask.svg").write_bytes(raw)
    record = next(r for r in build["files"] if r["name"] == "mask.svg")
    record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (root / "manifest.json").write_text(json.dumps(build))
    with pytest.raises(ServiceError, match="differ"):
        call(app.vectors, "build_get", build_id=build["build_id"])


def test_mask_and_motion_share_one_bounded_frozen_bundle(app):
    from mm_mcp.vector.producer import document_motion

    doc = document_motion.suggest(v2.create("emblem"), "sway")["document"]
    p = call(app.vectors, "create", document=doc)
    clip = doc["rig"]["clips"][0]["id"]
    build = current(app.vectors, p, "build", mask=True, clip=clip)["manifest"]
    result = call(app.vectors, "build_get", build_id=build["build_id"])
    assert (
        result["motion"]["clip"] == clip and result["material_mask"]["pose"] == "rest"
    )
    assert len(build["files"]) == 7
    with pytest.raises(ValueError):
        current(app.vectors, p, "build", mask="true")
