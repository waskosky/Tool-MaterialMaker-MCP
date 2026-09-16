import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import time
import zipfile

import pytest
from mm_mcp.core import ServiceError, file_lock
from mm_mcp.vector.ai import CodexProvider
from mm_mcp.vector.service import VectorService
from mm_mcp.vector.producer import document_motion as motion
from mm_mcp.vector.producer import document_v2 as v2


def call(service, operation, **fields):
    return service.command({"profile": v2.PROFILE, "operation": operation, **fields})


def current(service, p, op, **fields):
    return call(
        service,
        op,
        project_id=p["project_id"],
        expected_revision=p["revision"],
        **fields,
    )


def read(service, p):
    return call(service, "get", project_id=p["project_id"])


def patch(service, p, edits, key="edit"):
    current(service, p, "patch", operations=edits, idempotency_key=key)
    return read(service, p)


def test_explicit_upgrade_and_legacy_history_cannot_silently_admit_v2(app):
    old = app.vectors.documents.command(
        {"profile": "vector-document-v1", "operation": "create", "template": "beacon"}
    )
    frozen = app.vectors.documents.command(
        {
            "profile": "vector-document-v1",
            "operation": "build",
            "project_id": old["project_id"],
            "expected_revision": 0,
        }
    )
    before = app.vectors.documents.export(frozen["manifest"]["build_id"])
    assert read(app.vectors, old)["profile"] == "vector-document-v1"
    with pytest.raises(ServiceError, match="Upgrade"):
        patch(
            app.vectors,
            old,
            [{"op": "update", "id": "glass", "changes": {"fill": "#FFFFFF"}}],
        )
    request = dict(
        project_id=old["project_id"], expected_revision=0, idempotency_key="upgrade"
    )
    receipt = call(app.vectors, "upgrade", **request)
    upgraded = read(app.vectors, old)
    assert (
        upgraded["profile"] == v2.PROFILE
        and upgraded["preview_svg"] == old["preview_svg"]
    )
    assert call(app.vectors, "upgrade", **request) == receipt
    assert not app.vectors.documents.store.list()
    with pytest.raises(ServiceError, match="matching"):
        app.vectors.documents.command(
            {
                "profile": "vector-document-v1",
                "operation": "get",
                "project_id": old["project_id"],
            }
        )
    undone = current(app.vectors, upgraded, "history", direction="undo")
    assert undone["document"] == old["document"]
    with pytest.raises(ValueError):
        app.vectors.documents.command(
            {
                "profile": "vector-document-v1",
                "operation": "history",
                "project_id": old["project_id"],
                "expected_revision": undone["revision"],
                "direction": "redo",
            }
        )
    assert read(app.vectors, old) == undone
    assert (
        current(app.vectors, undone, "history", direction="redo")["document"]
        == upgraded["document"]
    )
    assert app.vectors.documents.export(frozen["manifest"]["build_id"]) == before


def test_library_is_immutable_shared_and_imports_are_revision_fenced(app):
    service = app.vectors
    p = call(service, "create", template="courier")
    entry = current(service, p, "library_save", kind="component", definition_id="wing")[
        "entry"
    ]
    other = VectorService(app.root)
    assert call(other, "library_get", library_id=entry["library_id"])["entry"] == entry
    assert len(call(other, "library_list")["entries"]) == 1
    blank = call(other, "create", template="blank")
    args = dict(
        project_id=blank["project_id"],
        expected_revision=0,
        library_id=entry["library_id"],
        idempotency_key="import",
        x=50,
        y=50,
    )
    result = call(other, "library_import", **args)
    assert call(other, "library_import", **args) == result
    imported = read(other, blank)
    assert (
        len(imported["document"]["components"]) == 1
        and result["changes"][0]["selected_id"]
    )
    source = deepcopy(imported["document"])
    p = patch(
        service,
        p,
        [
            {
                "op": "component_edit",
                "id": "wing",
                "operations": [
                    {
                        "op": "update",
                        "id": "feather",
                        "changes": {"name": "Changed locally"},
                    }
                ],
            }
        ],
    )
    assert read(other, blank)["document"] == source
    assert call(other, "library_get", library_id=entry["library_id"])["entry"] == entry
    path = service.studio.library_root / (entry["library_id"] + ".json")
    changed = json.loads(path.read_text())
    changed["snapshot"]["name"] = "Changed on disk"
    path.write_text(json.dumps(changed))
    with pytest.raises(ServiceError, match="immutable"):
        call(other, "library_get", library_id=entry["library_id"])


def test_rig_preview_and_animation_bundle_are_reproducible_and_tamper_checked(app):
    service = app.vectors
    p = call(service, "create", template="courier")
    result = current(service, p, "rig_suggest", preset="auto")
    assert read(service, p)["document"] == p["document"]
    p = patch(service, p, [{"op": "replace", "document": result["document"]}])
    clip = p["document"]["rig"]["clips"][0]["id"]
    sample = current(service, p, "sample", clip=clip, time=0.35)
    assert sample["pose"] == motion.sample(p["document"], clip, 0.35)
    manifest = current(service, p, "build", clip=clip)["manifest"]
    data = call(service, "build_get", build_id=manifest["build_id"])
    assert data["motion"]["count"] == 16 and data["motion"]["columns"] == 4
    exported = call(service, "export", build_id=manifest["build_id"])
    assert call(service, "export", build_id=manifest["build_id"]) == exported
    with zipfile.ZipFile(
        io.BytesIO(base64.b64decode(exported["data_base64"]))
    ) as bundle:
        assert set(bundle.namelist()) == {
            "document.json",
            "project.json",
            "preview.svg",
            "manifest.json",
            "motion.json",
            "motion.sheet.svg",
        }
        assert bundle.read("motion.sheet.svg").decode() == data["motion_sheet_svg"]
    p = patch(
        service,
        p,
        [{"op": "update", "id": "beak", "changes": {"fill": "#CC7733"}}],
        key="later",
    )
    assert call(service, "export", build_id=manifest["build_id"]) == exported
    path = service.studio.build_root / manifest["build_id"] / "motion.sheet.svg"
    path.write_text("<svg/>")
    with pytest.raises(ServiceError, match="frozen"):
        call(service, "export", build_id=manifest["build_id"])


class DeterministicProposalFixture:
    """Exercises admission/lifecycle; this fixture is not model acceptance."""

    def __init__(self, wait=False, invalid=False):
        self.release = threading.Event()
        self.started = threading.Event()
        self.invalid = invalid
        if not wait:
            self.release.set()

    def capabilities(self):
        return {"configured": True, "injected_test_provider": True}

    def run(self, prompt, cancel):
        self.started.set()
        while not self.release.wait(0.01):
            if cancel():
                raise ServiceError("CANCELLED", "Cancelled")
        if self.invalid:
            return "{}"
        return json.dumps(
            {
                "summary": "Warm the beak.",
                "warnings": [],
                "operations_json": json.dumps(
                    [{"op": "update", "id": "beak", "changes": {"fill": "#CC7722"}}]
                ),
            }
        )


def wait(service, key):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = call(service, "ai_get", proposal_id=key)
        if result["state"] != "running":
            return result
        time.sleep(0.01)
    raise AssertionError("Proposal did not complete")


def test_ai_preview_accept_retry_and_stale_source_never_overwrite(app):
    service = VectorService(app.root, DeterministicProposalFixture())
    try:
        p = call(service, "create", template="courier")
        queued = current(
            service, p, "ai_submit", intent="Warm the beak.", selected_ids=["beak"]
        )
        ready = wait(service, queued["proposal_id"])
        assert ready["state"] == "ready" and read(service, p)["revision"] == 0
        args = dict(
            project_id=p["project_id"],
            expected_revision=0,
            proposal_id=ready["proposal_id"],
            candidate_sha256=ready["candidate_sha256"],
        )
        receipt = call(service, "ai_accept", **args)
        assert call(service, "ai_accept", **args) == receipt
        p = read(service, p)
        assert p["document"] == ready["document"]
        # Restore different color so the next proposal remains meaningful.
        p = patch(
            service, p, [{"op": "update", "id": "beak", "changes": {"fill": "@ink"}}]
        )
        queued = current(
            service, p, "ai_submit", intent="Warm the beak.", selected_ids=["beak"]
        )
        ready = wait(service, queued["proposal_id"])
        p2 = patch(
            app.vectors,
            p,
            [
                {
                    "op": "update",
                    "id": "head",
                    "changes": {"name": "Head edited elsewhere"},
                }
            ],
            key="external",
        )
        with pytest.raises(ServiceError, match="changed"):
            call(
                service,
                "ai_accept",
                project_id=p["project_id"],
                expected_revision=p["revision"],
                proposal_id=ready["proposal_id"],
                candidate_sha256=ready["candidate_sha256"],
            )
        assert read(service, p) == p2
    finally:
        service.studio.proposals.close()


def test_ai_cancellation_validation_and_cross_process_lock(app):
    fixture = DeterministicProposalFixture(wait=True)
    service = VectorService(app.root, fixture)
    try:
        p = call(service, "create", template="courier")
        job = current(service, p, "ai_submit", intent="Change beak.", selected_ids=[])
        assert fixture.started.wait(2)
        from mm_mcp.activity import recent_or_active

        assert recent_or_active(grace_seconds=0)
        assert call(service, "describe")["ai"]["running"]
        with pytest.raises(ServiceError, match="already running"):
            current(service, p, "ai_submit", intent="Change beak.", selected_ids=[])
        assert (
            call(service, "ai_cancel", proposal_id=job["proposal_id"])["state"]
            == "cancelled"
        )
        service.studio.proposals.thread.join(2)
        assert read(service, p)["revision"] == 0
        with file_lock(app.root / ".vector-ai.lock"):
            job = current(
                service, p, "ai_submit", intent="Change beak.", selected_ids=[]
            )
            assert wait(service, job["proposal_id"])["state"] == "failed"
        fixture.invalid = True
        fixture.release.set()
        service.studio.proposals.thread.join(2)
        job = current(service, p, "ai_submit", intent="Change beak.", selected_ids=[])
        assert wait(service, job["proposal_id"])["state"] == "failed"
        assert read(service, p)["revision"] == 0
    finally:
        service.studio.proposals.close()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux process-state owner-death proof"
)
def test_ai_owner_death_kills_the_entire_private_worker_group(tmp_path):
    binary = tmp_path / "codex-fixture"
    pids = tmp_path / "pids.json"
    binary.write_text(
        "#!"
        + sys.executable
        + "\n"
        + f"""
import os,json,sys,subprocess,time
from pathlib import Path
sys.stdin.read()
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
Path({str(pids)!r}).write_text(json.dumps([os.getppid(),os.getpid(),child.pid]))
time.sleep(120)
"""
    )
    binary.chmod(0o700)
    code = "from mm_mcp.vector.ai import CodexProvider; import sys; CodexProvider(sys.argv[1],'fixture','low').run('fixture',lambda:False)"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    owner = subprocess.Popen(
        [sys.executable, "-c", code, str(binary)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    recorded = []

    def live(pid):
        path = Path("/proc") / str(pid) / "stat"
        try:
            return path.read_text().rpartition(") ")[2].split()[0] not in ("Z", "X")
        except (OSError, IndexError):
            return False

    try:
        deadline = time.monotonic() + 5
        while not pids.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert pids.exists(), "Worker did not start"
        recorded = json.loads(pids.read_text())
        assert all(live(pid) for pid in recorded)
        owner.kill()
        owner.wait(timeout=3)
        deadline = time.monotonic() + 5
        while any(live(pid) for pid in recorded) and time.monotonic() < deadline:
            time.sleep(0.025)
        assert not any(live(pid) for pid in recorded), (
            "Provider descendants survived owner death"
        )
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=3)
        if recorded and any(live(pid) for pid in recorded):
            import signal

            try:
                os.killpg(recorded[0], signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX fake executable boundary; real Codex requires host login",
)
def test_codex_worker_uses_closed_flags_ephemeral_cwd_and_bounded_output(
    tmp_path, monkeypatch
):
    binary = tmp_path / "codex-fixture"
    binary.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """
import json,os,sys
assert '--ignore-user-config' in sys.argv and '--ignore-rules' in sys.argv
assert '--ephemeral' in sys.argv and '--strict-config' in sys.argv
assert 'features.shell_tool=false' in sys.argv and 'features.multi_agent=false' in sys.argv
assert '--output-schema' in sys.argv and '--sandbox' in sys.argv
assert 'MM_TEST_SECRET' not in os.environ and 'NODE_OPTIONS' not in os.environ
assert os.path.basename(os.getcwd()).startswith('workshop-artwork-ai-')
assert sys.stdin.read() == 'bounded fixture prompt'
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{"fixture":true}'}}))
"""
    )
    binary.chmod(0o700)
    monkeypatch.setenv("MM_TEST_SECRET", "private")
    monkeypatch.setenv("NODE_OPTIONS", "untrusted")
    provider = CodexProvider(str(binary), "fixture-model", "low")
    assert json.loads(provider.run("bounded fixture prompt", lambda: False)) == {
        "fixture": True
    }
    with pytest.raises(ServiceError, match="cancelled"):
        provider.run("bounded fixture prompt", lambda: True)
    binary.write_text(
        "#!" + sys.executable + '\nimport sys\nsys.stdout.write("x"*3000000)\n'
    )
    with pytest.raises(ServiceError, match="bounded|complete"):
        provider.run("bounded fixture prompt", lambda: False)
