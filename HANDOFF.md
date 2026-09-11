# Session handoff: Tool-MaterialMaker-MCP

_Last updated: 2026-09-11 — slashless hosted-entry repair verified locally; upstream paused._

## Current state

Continue on `integration/next`, published to `origin/integration/next`. Local and
origin `main` remain reserved for focused upstream contributions. The user asked
us to ignore upstream until maintainer activity; do not poll it or prepare more
upstream changes as part of this work. Existing PR/worktree references remain in
[UPSTREAM.md](docs/upgrade/UPSTREAM.md).

The current follow-up repairs missing CSS/JavaScript when a prefix-stripping proxy
serves `/shadermaker/workshop` without its final slash. Hosted HTML anchors initial
assets to its configured mount; startup normalizes the browser URL before API
setup while retaining project/query/fragment handling. Token consumption, CSP and
Host/Origin checks are unchanged. The real proxy/browser regression passes with
an inspected styled page and saved project, without any native renderer configured.
This is local candidate evidence; publication and live URL checks remain separate.

The 0.8.0a1 Workshop now supports hosted subpaths, an explicit public origin and a
private shared token. Send to Foundry selects one verified immutable build; Edit
source returns to the same saved project. Adopted variations produce a build with
that saved project's provenance. Legacy imported parameters remain editable only
when the unrecognized fields are unchanged; new invalid fields still fail.

Start with [SETUP](docs/upgrade/SETUP.md) and [WORKSHOP](docs/upgrade/WORKSHOP.md).
The [128-pixel native evidence](docs/upgrade/evidence/workshop-companion-native.json)
records bake/cache/seed/export, retained scene and runtime edits, stale-source
rejection, editable-source reopening, and native Godot LOW/HIGH import/capture.
The [published live evidence](docs/upgrade/evidence/workshop-companion-live.json)
adds 256-pixel sand baking, exact browser handoff and Edit source navigation,
authenticated TLS, actual MCP PNG responses and one shared native queue,
cancellation, targeted restart, and service/manager crash recovery. This Mac works
with Godot 4.7 and the prepared native profile; earlier compiler failures are historical.

Clean published Workshop `107534a` (`integration/next`), Foundry `92abc89` (`main`)
and Godot Light `a13407bc` (`main`) passed live acceptance. The macOS LaunchAgent
is installed and loaded; login registration and automatic crash recovery were
verified, with no actual reboot. Existing Serve routes and peer listeners were
preserved. The game root returned 502 before and after; the companion tools run
independently of the stopped game stack and RAI. Native scope remains one sand
recipe at 128 and 256 pixels, with experimental native editor writes disabled.

Portable gate: **485 passed, 1 Windows-only skip, 5 deselected**. The hosted-entry
browser regression passes **1 case**; the earlier real HTTP/CSP suite passed
**3 cases** with required WebGL and explicitly synthetic test maps. The actual
Python 3.12.13 / MCP SDK 2.2.0 client exercised the shared workspace
and registered 42 tools. Package resources remain synchronized. Accepted-code
[CI run 34579067693](https://github.com/waskosky/Tool-MaterialMaker-MCP/actions/runs/34579067693)
passed all five jobs. Version 0.8.0a1 remains a development candidate; no alpha
release is being published.

## Next work

1. Expand ordinary material use beyond the accepted 128/256-pixel sand example and
   inspect additional opaque material categories in the intended engine.
2. Native editor writes, candidate replacement and bridge history need separate
   disposable editor acceptance before enabling them for artist work.
3. Use normal-use feedback to prioritize library management and build retention.

## Heads-up

- [TESTING](docs/upgrade/TESTING.md) separates current browser/portable evidence from
  native graphics and historical 0.7 gates. Synthetic map screenshots certify no
  native material appearance. Current native success is in the companion evidence;
  earlier failures remain in [runtime evidence](docs/upgrade/evidence/workshop-native-local.json).
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

- 2026-09-11: Reproduced slashless proxy CSS/JS misrouting, anchored hosted assets
  and normalized browser entry URLs; 485 portable checks and the real proxy/browser
  regression pass, with the styled project page inspected. Native rendering was
  unconfigured and live routes were unchanged.
- 2026-09-11: Published and deployed the reviewed companion revisions; verified
  live TLS/browser/MCP handoff, a serialized native queue, cancellation, targeted
  restart and crash recovery. Installed the login LaunchAgent and checked its
  automatic recovery without rebooting. Recorded the 128/256-pixel sand limit,
  disabled editor writes and unchanged pre-existing game-root 502.
- 2026-09-11: Added reviewed companion hosting and exact saved-project build handoff;
  repaired legacy-source editing and variation provenance; verified real native
  bake/export/reopen, Godot capture and shared browser/MCP workflows before deployment.
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
