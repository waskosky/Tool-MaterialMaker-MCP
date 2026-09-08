# Session handoff: Tool-MaterialMaker-MCP

_Last updated: 2026-09-08 — publish the integration branch and reserve main for upstream PRs._

## Current state

The user-supplied alpha archive is integrated on `integration/next`,
starting from clean baseline `b41b65c`. This is the continuing development branch,
published to `origin/integration/next`. Local and origin `main` remain reserved
for focused upstream PRs; do not merge the complete integration into `main`.
The original source was extracted under `~/games/temp/`; the exact path, checksum,
review findings and fixes are in [docs/upgrade/INTEGRATION.md](docs/upgrade/INTEGRATION.md).

The shared browser/MCP service, persistent projects, recipes, build/export
contracts, jobs and authenticated native bridge are present. Follow-up fixes
cover ignored controls, code approval for personal recipes, custom export-code
approval, job recovery and stale browser responses. Setup, packaging, CI and
current documentation were updated. Cookbook graphs and builders are unchanged.

Portable validation: **232 passed, 1 Windows-only skip, 2 deselected** (Chromium
and native acceptance). Wheel build, metadata check and installation into a
separate virtualenv passed; installed resources and actual SDK registration were
verified. The repo `.venv` uses Python 3.12.13 and MCP SDK 2.2.0.

## Next work

1. Continue on `integration/next`. The recommended focused upstream contributions
   are in [UPSTREAM.md](docs/upgrade/UPSTREAM.md); their source branch is `main`.
   Review [migration notes](docs/upgrade/MIGRATION.md) before native use.
2. When native testing is wanted, configure actual native paths in a fresh
   workspace and follow [TESTING.md](docs/upgrade/TESTING.md), starting with batch
   rendering and reopening the exported editable graph in Material Maker.
3. Exercise the browser visually and import target packages into the intended
   engines. Leave native mutation disabled until its separate acceptance passes.
4. The prior Unity crate hand-edit/round-trip session remains outstanding; this
   integration did not operate on Unity or the other repositories.

## Heads-up

- Native and GPU validation was intentionally deferred at the user's request.
  Archive logs in `evidence/` describe its earlier Linux run; current checks are
  in the integration record. Do not infer current native readiness from 0.7 gates.
- `scripts/check_release.py` is the current portable gate. The historical full
  suite contains machine-dependent fixtures and superseded 0.7 contracts.
- Build downloads require a completed build ID. Workspace patches use expected
  revisions and retry keys. Native protocol `mm-live/2` is incompatible with the
  old unauthenticated bridge.
- Personal-recipe code approval is service-owned provenance; client metadata
  cannot authorize new code. New custom code and native mutations are off by default.
- Edit canonical cookbook/builders, `docs/AUTHORING.md`, and `addons/mm_live/`, then
  run `scripts/sync_package_data.py`; packaged copies are checked for drift.
- Run quality modules from the root with `python -m quality.<module>`. Render one
  Godot process at a time. Keep `.env` and runtime credentials private.

## Session log

Newest first; older details remain in git history.

- 2026-09-08: Integrated supplied 0.8.0a1 alpha, corrected five reviewed behavior
  issues, improved setup/package/docs, verified portable behavior, and published
  `integration/next`; reserved `main` for selected upstream PRs.
- 2026-09-06 (backup-ops wake-lock, cross-project): `pickup` here, Grayson picked next-step #2. Root-caused the 09-05 nightly truncation as idle-sleep mid-run (the git `NativeCommandError` is a handled CRLF warning; true signature is a missing `transcript end` footer, not a code bug), and added a `SetThreadExecutionState` wake-lock to `backup-ops\Backup-All.ps1` (acquire in try, release in finally). Verified compile + parse; commit `f7e809d` local, PUSH PENDING (ssh-agent not loaded this session). Commons log written. No MM-MCP code changed.
- 2026-09-06 (idle-exit watchdog): `MM_IDLE_EXIT_MINUTES` opt-in idle exit, 17/17 tools touch it, live session closed on exit; review found and fixed the two untouched tools and the atexit skip; merged `--no-ff` as `f669f8c`, suite 989; registration set to 120.
- 2026-09-06 (validate subgraph descent + crate round-trip prep)
- 2026-09-06 (teardown #5 executed): MCP user-wide, crate into the Unity sandbox, kit-map layer 4b, role-named cookbook
- 2026-09-05 (teardown #4 executed): hygiene sweep (CI pinned to the MM sha), `quality/` packaged, Phase-3 harness archived (`6e4568f`, `c5d473c`).
- 2026-09-05 (teardown #3 executed): examples/ folded into the cookbook (46 -> 53), mm-play port diagnostic, backup exclusions, baton diet (`87be578`, `5b93785`); v0.7.0 released.
- 2026-09-05 (mm-play verified): Grayson ran `play.bat` hands-on; row promoted 🔌 -> ✅ (`056dcd4`).
