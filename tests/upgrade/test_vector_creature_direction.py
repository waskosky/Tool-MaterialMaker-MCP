import json
import time

import pytest

from mm_mcp.core import ServiceError
from mm_mcp.vector.service import VectorService
from mm_mcp.vector.producer import document_v2 as v2


def call(service, operation, **fields):
    return service.command(dict(profile=v2.PROFILE, operation=operation, **fields))


def current(service, project, operation, **fields):
    return call(
        service,
        operation,
        project_id=project["project_id"],
        expected_revision=project["revision"],
        **fields,
    )


def read(service, project):
    return call(service, "get", project_id=project["project_id"])


class FamilyFixture:
    """Deterministic contract fixture; it does not claim real-model art quality."""

    def __init__(self, duplicate=False):
        self.calls = 0
        self.duplicate = duplicate

    def capabilities(self):
        return dict(configured=True, model="typed-test-fixture")

    def run(self, prompt, cancel):
        assert not cancel()
        context = json.loads(prompt.split("ARTWORK_REQUEST_JSON\n", 1)[1])
        doc = context["document"]
        index = 1 if self.duplicate else context["family_index"] + 1
        keys, colors = list(doc["palette"]), list(doc["palette"].values())
        self.calls += 1
        return json.dumps(
            dict(
                summary="Palette family " + str(index),
                warnings=[],
                operations_json=json.dumps(
                    [
                        dict(
                            op="palette",
                            colors=dict(zip(keys, colors[index:] + colors[:index])),
                        )
                    ]
                ),
            )
        )


def wait(service, job):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = call(service, "ai_get", proposal_id=job["proposal_id"])
        if result["state"] != "running":
            return result
        time.sleep(0.01)
    raise AssertionError("Proposal did not finish")


def test_fit_preview_exact_acceptance_history_and_frozen_export(app):
    project = call(app.vectors, "create", template="trail_hopper")
    build = current(app.vectors, project, "build", clip="walk")
    old = call(app.vectors, "export", build_id=build["manifest"]["build_id"])
    preview = current(
        app.vectors,
        project,
        "creature_fit",
        targets={"leg_length": dict(target=96, weight=1)},
        free_parameters=["upper_leg", "lower_leg"],
    )
    assert read(app.vectors, project) == project
    assert preview["status"] == "fitted"
    with pytest.raises(ServiceError, match="candidate"):
        current(
            app.vectors,
            project,
            "accept_preview",
            operations=preview["operations"],
            candidate_sha256="0" * 64,
            idempotency_key="wrong",
        )
    assert read(app.vectors, project) == project
    receipt = current(
        app.vectors,
        project,
        "accept_preview",
        operations=preview["operations"],
        candidate_sha256=preview["candidate_sha256"],
        idempotency_key="fit",
    )
    assert (
        current(
            app.vectors,
            project,
            "accept_preview",
            operations=preview["operations"],
            candidate_sha256=preview["candidate_sha256"],
            idempotency_key="fit",
        )
        == receipt
    )
    changed = read(app.vectors, project)
    with pytest.raises(ServiceError, match="different request"):
        current(app.vectors, project, "accept_preview", operations=preview["operations"],
                candidate_sha256="0"*64, idempotency_key="fit")
    assert changed["document"] == preview["document"]
    assert changed["document"]["rig"] == project["document"]["rig"]
    restored = current(app.vectors, changed, "history", direction="undo")
    assert restored["document"] == project["document"]
    assert call(app.vectors, "export", build_id=build["manifest"]["build_id"]) == old


def test_ik_preview_rejects_a_stale_accept_and_returns_visible_unreachable_residual(
    app,
):
    project = call(app.vectors, "create", template="trail_hopper")
    result = current(
        app.vectors,
        project,
        "creature_pose",
        leg="left",
        target=[400, -400],
        clip="idle",
        time=0.9,
    )
    assert not result["reachable"] and result["error"] > 100
    current(
        app.vectors,
        project,
        "patch",
        operations=[dict(op="palette", colors=dict(accent="#F0C070"))],
        idempotency_key="artist",
    )
    with pytest.raises(ServiceError, match="Project changed"):
        current(
            app.vectors,
            project,
            "accept_preview",
            operations=result["operations"],
            candidate_sha256=result["candidate_sha256"],
            idempotency_key="stale",
        )


def test_frozen_reference_family_does_not_write_until_exact_candidate_acceptance(
    tmp_path,
):
    provider = FamilyFixture()
    service = VectorService(tmp_path, ai_provider=provider)
    try:
        project = call(service, "create", template="trail_hopper")
        reference = call(service, "create", template="trail_hopper", title="Reference")
        job = current(
            service,
            project,
            "ai_submit",
            intent="Three coherent trail companions",
            selected_ids=[],
            direction=dict(
                reference_project_id=reference["project_id"],
                expected_reference_revision=0,
                stroke_width=0,
            ),
        )
        ready = wait(service, job)
        assert ready["state"] == "ready" and provider.calls == 3
        assert len(ready["candidates"]) == 3
        assert ready["reference"]["source_sha256"] == reference["content_sha256"]
        assert read(service, project) == project
        candidate = ready["candidates"][2]
        accepted = current(
            service,
            project,
            "ai_accept",
            proposal_id=job["proposal_id"],
            candidate_sha256=candidate["candidate_sha256"],
        )
        assert read(service, project)["document"] == candidate["document"]
        assert (
            current(
                service,
                project,
                "ai_accept",
                proposal_id=job["proposal_id"],
                candidate_sha256=candidate["candidate_sha256"],
            )
            == accepted
        )
        with pytest.raises(ServiceError):
            current(
                service,
                project,
                "ai_accept",
                proposal_id=job["proposal_id"],
                candidate_sha256=ready["candidates"][0]["candidate_sha256"],
            )
    finally:
        service.studio.proposals.close()


def test_duplicate_family_or_stale_reference_cannot_be_accepted(tmp_path):
    service = VectorService(tmp_path, ai_provider=FamilyFixture(duplicate=True))
    try:
        project = call(service, "create", template="trail_hopper")
        with pytest.raises(ServiceError, match="revision|Artwork changed"):
            current(
                service,
                project,
                "ai_submit",
                intent="Compare",
                selected_ids=[],
                direction=dict(
                    reference_project_id=project["project_id"],
                    expected_reference_revision=9,
                    stroke_width=0,
                ),
            )
        ready = wait(
            service,
            current(
                service,
                project,
                "ai_submit",
                intent="Compare",
                selected_ids=[],
                direction=dict(
                    reference_project_id=project["project_id"],
                    expected_reference_revision=0,
                    stroke_width=0,
                ),
            ),
        )
        assert ready["state"] == "failed" and "repeated" in ready["error"]
        assert read(service, project) == project
    finally:
        service.studio.proposals.close()
