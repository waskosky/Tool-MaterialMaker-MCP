"""Ephemeral artwork proposals; only explicit acceptance writes a project."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from mm_mcp.core import ServiceError, canonical, file_lock
from mm_mcp.activity import operation as active_operation
from mm_mcp.blender.runner import _kill
from .producer import document as v1
from .producer import document_v2 as v2
from .producer import document_assistant as planner

TTL = 15 * 60
MAX_PROPOSALS = 8
TIMEOUT = 180
DISABLED = (
    "shell_tool",
    "unified_exec",
    "apps",
    "multi_agent",
    "computer_use",
    "browser_use",
    "in_app_browser",
    "image_generation",
    "goals",
    "hooks",
    "remote_plugin",
    "plugin_sharing",
    "skill_mcp_dependency_install",
    "tool_suggest",
)


class CodexProvider:
    def __init__(self, binary="", model="", effort="low"):
        from mm_mcp.config import validate_vector_ai

        validate_vector_ai(binary, model, effort)
        self.binary, self.model, self.effort = binary, model, effort

    def capabilities(self):
        return {
            "configured": bool(self.binary),
            "provider": "codex-cli" if self.binary else None,
            "model": self.model or None,
            "effort": self.effort if self.binary else None,
            "timeout_seconds": TIMEOUT,
            "requires_review": True,
            "retention": "Unaccepted proposals expire after 15 minutes or a service restart.",
        }

    def command(self, directory):
        cmd = [
            self.binary,
            "exec",
            "--strict-config",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--cd",
            str(directory),
            "--model",
            self.model,
            "--color",
            "never",
            "--json",
            "--output-schema",
            str(directory / "response.schema.json"),
        ]
        settings = [
            'approval_policy="never"',
            'web_search="disabled"',
            "allow_login_shell=false",
            "model_reasoning_effort=" + json.dumps(self.effort),
        ]
        settings += ["features." + feature + "=false" for feature in DISABLED]
        for setting in settings:
            cmd.extend(["--config", setting])
        return cmd + ["-"]

    def run(self, prompt, cancel):
        if not self.binary:
            raise ServiceError(
                "AI_UNCONFIGURED",
                "Configure the host artwork AI provider, or use the external assistant handoff.",
            )
        if cancel():
            raise ServiceError("CANCELLED", "Artwork proposal cancelled before launch.")
        # Saved CLI authentication belongs to the host account. Do not forward
        # Workshop tokens, arbitrary API keys, Python/Node injection or plugins.
        env = {
            k: os.environ[k]
            for k in (
                "HOME",
                "USERPROFILE",
                "APPDATA",
                "LOCALAPPDATA",
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "COMSPEC",
                "LANG",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            )
            if k in os.environ
        }
        with tempfile.TemporaryDirectory(prefix="workshop-artwork-ai-") as temporary:
            root = Path(temporary)
            (root / "response.schema.json").write_text(
                canonical(planner.RESPONSE_SCHEMA)
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).with_name("ai_worker.py")),
                    str(os.getpid()),
                ],
                cwd=root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **(
                    {"start_new_session": True}
                    if os.name != "nt"
                    else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                ),
            )
            overflow = threading.Event()
            output = bytearray()

            def drain(stream, maximum, target=None):
                total = 0
                while True:
                    block = os.read(stream.fileno(), 16384)
                    if not block:
                        return
                    total += len(block)
                    if total > maximum:
                        overflow.set()
                    elif target is not None:
                        target.extend(block)

            readers = [
                threading.Thread(
                    target=drain,
                    args=(process.stdout, 2 * 1024 * 1024, output),
                    daemon=True,
                ),
                threading.Thread(
                    target=drain, args=(process.stderr, 128 * 1024), daemon=True
                ),
            ]
            for thread in readers:
                thread.start()
            deadline = time.monotonic() + TIMEOUT
            try:
                process.stdin.write(
                    (
                        canonical({"command": self.command(root), "prompt": prompt})
                        + "\n"
                    ).encode()
                )
                process.stdin.flush()  # Keep the owner pipe open until cleanup.
                while process.poll() is None:
                    if cancel():
                        raise ServiceError("CANCELLED", "Artwork proposal cancelled.")
                    if overflow.is_set():
                        raise ServiceError(
                            "AI_OUTPUT_LIMIT",
                            "The provider exceeded its bounded output allowance.",
                        )
                    if time.monotonic() >= deadline:
                        raise ServiceError(
                            "AI_TIMEOUT",
                            "Artwork proposal timed out. Try a smaller change.",
                        )
                    time.sleep(0.025)
                for thread in readers:
                    thread.join(timeout=1)
                if overflow.is_set() or process.returncode:
                    raise ServiceError(
                        "AI_PROVIDER",
                        "The provider did not complete. Check the host Codex login and configured model.",
                    )
                messages = []
                for line in output.decode("utf-8").splitlines():
                    event = json.loads(line)
                    if event.get("type") in ("turn.failed", "error"):
                        raise ValueError("Provider failure")
                    item = event.get("item", {})
                    if item and item.get("type") not in ("agent_message", "reasoning"):
                        raise ValueError("Unexpected provider tool event")
                    if (
                        event.get("type") == "item.completed"
                        and item.get("type") == "agent_message"
                    ):
                        messages.append(item["text"])
                if len(messages) != 1:
                    raise ValueError("Expected one structured response")
                return messages[0]
            except (OSError, ValueError, KeyError, UnicodeError) as exc:
                if isinstance(exc, ServiceError):
                    raise
                raise ServiceError(
                    "AI_PROVIDER",
                    "The provider returned an incomplete or unexpected response.",
                ) from exc
            finally:
                _kill(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
                for thread in readers:
                    thread.join(timeout=1)


class ProposalService:
    def __init__(self, root, documents, provider):
        self.root, self.documents, self.provider = Path(root), documents, provider
        self.lock = threading.RLock()
        self.jobs = {}
        self.thread = None
        self.closed = False

    def capabilities(self):
        with self.lock:
            return {
                **self.provider.capabilities(),
                "running": bool(self.thread and self.thread.is_alive()),
                "pending_review": sum(
                    j["state"] == "ready" for j in self.jobs.values()
                ),
            }

    def _prune(self):
        now = time.monotonic()
        self.jobs = {
            k: j
            for k, j in self.jobs.items()
            if j["state"] == "running" or now - j["created"] < TTL
        }

    def submit(self, project, intent, selected):
        source = deepcopy(project["document"])
        prompt = planner.prompt(source, intent, selected)
        if not self.provider.capabilities()["configured"]:
            raise ServiceError(
                "AI_UNCONFIGURED",
                "Configure the host AI provider or copy a handoff to your assistant.",
            )
        with self.lock:
            self._prune()
            if self.closed or (self.thread and self.thread.is_alive()):
                raise ServiceError(
                    "AI_BUSY",
                    "One artwork proposal is already running. Wait or cancel it.",
                )
            if len(self.jobs) >= MAX_PROPOSALS:
                disposable = next(
                    (
                        k
                        for k, j in self.jobs.items()
                        if j["state"] in ("failed", "cancelled", "accepted")
                    ),
                    None,
                )
                if disposable:
                    del self.jobs[disposable]
                else:
                    raise ServiceError(
                        "AI_CAPACITY",
                        "Review or discard pending proposals before requesting more.",
                    )
            key = "a_" + uuid.uuid4().hex
            job = {
                "id": key,
                "created": time.monotonic(),
                "state": "running",
                "cancel": threading.Event(),
                "project_id": project["project_id"],
                "revision": project["revision"],
                "source": source,
                "source_sha256": project["content_sha256"],
                "selected": deepcopy(selected),
            }
            self.jobs[key] = job
            self.thread = threading.Thread(
                target=self._run,
                args=(job, prompt),
                name="vector-ai-proposal",
                daemon=True,
            )
            self.thread.start()
            return self._public(job)

    def _run(self, job, prompt):
        try:
            # No persistent request queue. Separate HTTP/MCP processes share this
            # kernel lock and immediately refuse competing provider work.
            with (
                active_operation(),
                file_lock(
                    self.root / ".vector-ai.lock",
                    timeout=0,
                    cancel=job["cancel"].is_set,
                ),
            ):
                raw = self.provider.run(prompt, job["cancel"].is_set)
                result = planner.admit(job["source"], raw, job["selected"])
            with self.lock:
                if job["cancel"].is_set():
                    job["state"] = "cancelled"
                else:
                    job.update(state="ready", proposal=result)
        except (
            ValueError,
            OSError,
            KeyError,
            TypeError,
            RecursionError,
            OverflowError,
        ) as exc:
            with self.lock:
                job["state"] = "cancelled" if job["cancel"].is_set() else "failed"
                # Compiler errors are bounded generic diagnostics. Never retain
                # model output, prompt text or arbitrary provider stderr.
                job["error"] = (
                    str(exc)[:240]
                    if isinstance(exc, ServiceError)
                    else "The proposed edits failed artwork validation. Try a smaller, more specific change."
                )

    @staticmethod
    def _public(job):
        out = {
            "ok": True,
            "proposal_id": job["id"],
            "state": job["state"],
            "project_id": job["project_id"],
            "source_revision": job["revision"],
            "source_sha256": job["source_sha256"],
        }
        if job["state"] == "ready":
            out.update(deepcopy(job["proposal"]))
            out["preview_svg"] = v2.render(out["document"])
        if job.get("error"):
            out["error"] = job["error"]
        if job.get("receipt"):
            out["receipt"] = deepcopy(job["receipt"])
        return out

    def _job(self, key):
        self._prune()
        if not isinstance(key, str) or key not in self.jobs:
            raise ServiceError(
                "AI_EXPIRED",
                "This proposal expired or belongs to a previous service session. Request a new preview.",
            )
        return self.jobs[key]

    def get(self, key):
        with self.lock:
            return self._public(self._job(key))

    def cancel(self, key):
        with self.lock:
            job = self._job(key)
            if job["state"] != "accepted":
                job["cancel"].set()
                job["state"] = "cancelled"
                job.pop("proposal", None)
                job.pop("source", None)
            return self._public(job)

    def accept(self, key, project_id, expected_revision, candidate_sha256):
        with self.lock:
            job = self._job(key)
            if (
                project_id != job["project_id"]
                or type(expected_revision) is not int
                or expected_revision != job["revision"]
                or candidate_sha256 != job.get("proposal", {}).get("candidate_sha256")
            ):
                raise ServiceError(
                    "AI_SOURCE",
                    "Accept the exact artwork version and candidate shown in this proposal.",
                )
            if job["state"] == "accepted":
                return deepcopy(job["receipt"])
            if job["state"] != "ready":
                raise ServiceError(
                    "AI_NOT_READY",
                    "Only a validated, reviewed proposal can be accepted.",
                )
            current = self.documents.current(
                {"project_id": project_id, "expected_revision": expected_revision}
            )
            if current["content_sha256"] != job["source_sha256"]:
                raise ServiceError(
                    "AI_SOURCE", "Artwork source changed; request a new proposal."
                )
            proposal = job["proposal"]
            receipt = self.documents.store.patch(
                project_id,
                expected_revision,
                proposal["operations"],
                "accept-" + key,
                authorize=lambda document: self._exact(
                    document, proposal["candidate_sha256"]
                ),
            )
            job.update(state="accepted", receipt=receipt)
            return deepcopy(receipt)

    @staticmethod
    def _exact(document, expected):
        if v1.structural_digest(document) != expected:
            raise ServiceError(
                "AI_CANDIDATE",
                "The accepted operations differ from the reviewed candidate.",
            )

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                job["cancel"].set()
        if self.thread:
            self.thread.join(timeout=8)
