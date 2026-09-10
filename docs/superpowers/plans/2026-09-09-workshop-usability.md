# Material Workshop Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make the local Material Workshop easy to configure, browse, preview and
use for selecting editable material variations; publish on `integration/next`.

**Architecture:** Preserve the shared service and immutable build model. Isolate
native retry output, add a small setup/session layer, and extend the existing plain
JavaScript client with visual recipe, variation and snapshot workflows.

**Tech Stack:** Python 3.10+, SQLite, Pillow, vanilla JavaScript, Three.js, pytest,
optional Playwright/Chromium, Godot and the compatible Material Maker source.

## Task 1 — Native rendering reliability

Files: `src/mm_mcp/render.py`, `preview.py`, `policy.py`, `builds.py`, and narrowly
related service interfaces if explicit asset origins require them; focused tests
under `tests/upgrade/`.

- [x] Reproduce retry contamination with a subprocess double: a crashing first
  attempt writes a valid image and a successful second attempt omits it; publication
  must fail and preserve any previous completed output.
- [x] Add a per-attempt cleanup callback to the native runner, preserving its
  cancellation and process cleanup behavior. Clear only private attempt files.
- [x] Reproduce and fix `%PROJECT_PATH%` resolution with an explicit source origin.
  Validate asset roots and dependency hashes, render a rewritten copy, and publish
  original source. Reject ambiguous origins through the shared build boundary.
- [x] Exercise render and preview retries, cancellation, source preservation and
  ordinary successful publication. Review spec compliance, then code quality.

## Task 2 — Setup and launch

Files: `src/mm_mcp/setup.py` and `play/session.py` (new bounded helpers),
`config.py`, `service.py`, `play/server.py`, `scripts/configure.py`, `play.bat`,
`Play.command`, `scripts/launch.py`, `play/static/setup.js`, and focused setup/session tests.

- [ ] Add persisted native-path settings beneath the user's configuration directory
  with environment and `.env` precedence, atomic writes, validation, and safe updates.
  Keep workspace/output configuration stable and never include tokens in setup data.
- [ ] Detect common local Godot executables and adjacent Material Maker checkouts.
  Expose authenticated setup status and save/recheck routes. Return actionable
  installation guidance and distinct missing/configured/verified states.
- [ ] Apply saved paths to the existing service only when its queue is idle; rebuild
  its catalog/recipe references without losing the workspace or approval records.
  Mark verification only after a successful genuine native build, reset on changes.
- [ ] Add private server discovery and authenticated identity checks. Launch opens a
  browser by default; a second launch opens the existing matching session. An
  unrelated server remains a clear conflict. Retain `--no-open` for automation.
- [ ] Add source launchers that prepare runtime dependencies and launch the browser;
  make `scripts/configure.py` support repair rather than refusing an existing file.
- [ ] Run focused setup/HTTP/session tests and review both contract and quality.

## Task 3 — Visual materials and variation workflow

Files: `recipes.py`, `transactions.py`, `play/server.py`,
`play/static/index.html`, `style.css`, `app.js`, and small focused client helpers
where needed. Focused service tests and the actual browser acceptance test.

- [ ] Derive friendly recipe titles/descriptions from existing guides/metadata; expose
  authenticated thumbnails from completed builds without background mass rendering.
- [ ] Add snapshot listing to GraphStore and the HTTP adapter.
- [ ] Build a responsive gallery with search, categories, favorites and recipe cards;
  add setup status/editor, first-use guidance and automatic small previews.
- [ ] Replace raw family JSON with typed range/lock controls and seed/count fields.
  Poll bounded candidate jobs into visible cards. Support inspect, select editable
  values, pin/compare and save. Cancel old family work and ignore stale responses.
- [ ] List and restore snapshots; show friendly job states and retry. Separate search
  debounce from preview debounce and keep project revision conflict handling intact.
- [ ] Run focused browser regressions and exercise a real browser with screenshots;
  review spec compliance and code quality and resolve concrete findings.

## Task 4 — Integration evidence and publication

Files: `.github/workflows/test.yml`, `README.md`, relevant setup documentation,
`HANDOFF.md`, `STATUS.md`, `docs/upgrade/STATUS.md`, `INTEGRATION.md`, and this plan.

- [ ] Enable the existing portable/package/browser CI workflow for `integration/next`.
- [ ] Attempt real native smoke, cancellation/restart and reopening exported `.ptex`
  with a compatible local runtime, preserving a pristine native source checkout.
- [ ] Update user quickstart, setup/preview acceptance notes and current handoff.
- [ ] Run the portable release gate, resource synchronization check, JavaScript syntax
  checks, wheel build/metadata check, and focused browser suite. Avoid a broad legacy
  test campaign or engine certifications in this milestone.
- [ ] Review the final diff, commit changes, push `origin integration/next`, verify
  remote branch and CI status, and report outcomes with remaining practical limits.
