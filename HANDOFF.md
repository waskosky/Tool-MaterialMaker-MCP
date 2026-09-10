# Session handoff: Tool-MaterialMaker-MCP

_Last updated: 2026-09-10 — Workshop usability milestone on integration/next; upstream paused._

## Current state

Continue on `integration/next`, published to `origin/integration/next`. Local and
origin `main` remain reserved for focused upstream contributions. The user asked
us to ignore upstream until maintainer activity; do not poll it or prepare more
upstream changes as part of this work. Existing PR/worktree references remain in
[UPSTREAM.md](docs/upgrade/UPSTREAM.md).

The supplied 0.8.0a1 archive is integrated. The usability milestone now adds isolated
native retry attempts and explicit source-image origins, saved native setup and
repair, runtime source launchers, authenticated session reuse, a responsive recipe
library, real cached thumbnails, automatic previews, typed variation ranges and
locks, exact editable candidate selection, pin comparison, personal recipes and
named version restore. Shared edits/history finish before previews; late requests
cannot replace a newer selection. Spec and quality reviews covered each implementation
task and their concrete findings were reproduced and fixed.

Start with [SETUP](docs/upgrade/SETUP.md) and [WORKSHOP](docs/upgrade/WORKSHOP.md).
The archive source/checksum and this milestone's verification are recorded in
[INTEGRATION](docs/upgrade/INTEGRATION.md). Cookbook graphs, builders and native source
remain unchanged. The alpha version stays 0.8.0a1; no release or deployment was made.

Local portable gate: **377 passed, 1 Windows-only skip, 4 deselected**. Real HTTP/CSP
browser acceptance: **3 passed**, with WebGL required and explicitly synthetic maps;
21 focused Node state cases also passed. Wheel build and metadata checks passed.
The actual SDK registers 42 tools. See the integration record for installation and
CI evidence. The repository `.venv` uses Python 3.12.13 and MCP SDK 2.2.0.

## Next work

1. Complete real native bake/cache/export/reopen acceptance on a graphics setup that
   can initialize the pinned Material Maker source. Local Intel Mac/AMD Radeon Pro
   460 runs with official Godot 4.7.1 and 4.7.2 failed Vulkan compute compilation.
   Actual worker cancellation passed; no successful native bake is claimed.
2. Import real exported materials into the intended engine and inspect normal
   direction, channel packing, color handling, physical scale and editable source.
3. Exercise an intended assistant host against the shared browser workspace,
   including image responses. Native editor writes require separate disposable
   project acceptance before enabling them for artist work.
4. Collect normal-use feedback before expanding library management or build retention.
   No work in Unity, Godot Light or other game repositories was included here.

## Heads-up

- [TESTING](docs/upgrade/TESTING.md) separates current browser/portable evidence from
  native graphics and historical 0.7 gates. Synthetic map screenshots certify no
  native material appearance. Native failure/cancellation details are in
  [runtime evidence](docs/upgrade/evidence/workshop-native-local.json).
- Native defaults resolve environment → `.env` → saved paths; setup changes apply
  only while the service is idle. Source launchers preserve the workspace and reuse
  authenticated matching sessions. Restart a separate assistant service after repair.
- `scripts/check_release.py` is the current portable gate. The historical full
  suite includes superseded contracts and machine-dependent fixtures.
- Build downloads require completed IDs. Workspace patches use expected revisions
  and retry keys. Code approval is service-owned; new custom code and experimental
  native writes are disabled by default. Never expose launch tokens or `.env`.
- Edit canonical cookbook/builders, `docs/AUTHORING.md` and `addons/mm_live/`, then
  run `scripts/sync_package_data.py`; package drift is checked. Run quality modules
  from the root with `python -m quality.<module>`.
- Render one Godot process at a time. Keep the compatible native source pristine;
  real texture baking needs desktop graphics, not Godot's `--headless` renderer.

## Session log

Newest first; older details remain in git history.

- 2026-09-10: Completed the approved setup/library/variation usability milestone,
  fixed reviewed native retry and browser ordering issues, exercised actual HTTP
  and WebGL with labelled test maps, and recorded the local native compiler blocker
  plus successful real worker cancellation. Continued on `integration/next` with
  upstream work paused.
- 2026-09-08: Submitted independent upstream export/render PRs #7/#8, fixed native
  compatibility findings during review, verified focused regressions and #7's
  Windows CI; kept the main checkout on `integration/next`.
- 2026-09-08: Integrated supplied 0.8.0a1 alpha, corrected five reviewed behavior
  issues, improved setup/package/docs, verified portable behavior, and published
  `integration/next`; reserved `main` for selected upstream PRs.
- 2026-09-06 (backup-ops wake-lock, cross-project): `pickup` here, Grayson picked next-step #2. Root-caused the 09-05 nightly truncation as idle-sleep mid-run (the git `NativeCommandError` is a handled CRLF warning; true signature is a missing `transcript end` footer, not a code bug), and added a `SetThreadExecutionState` wake-lock to `backup-ops\Backup-All.ps1` (acquire in try, release in finally). Verified compile + parse; commit `f7e809d` local, PUSH PENDING (ssh-agent not loaded this session). Commons log written. No MM-MCP code changed.
- 2026-09-06 (idle-exit watchdog): `MM_IDLE_EXIT_MINUTES` opt-in idle exit, 17/17 tools touch it, live session closed on exit; review found and fixed the two untouched tools and the atexit skip; merged `--no-ff` as `f669f8c`, suite 989; registration set to 120.
- 2026-09-06 (validate subgraph descent + crate round-trip prep)
- 2026-09-06 (teardown #5 executed): MCP user-wide, crate into the Unity sandbox, kit-map layer 4b, role-named cookbook
- 2026-09-05 (teardown #4 executed): hygiene sweep (CI pinned to the MM sha), `quality/` packaged, Phase-3 harness archived (`6e4568f`, `c5d473c`).
