# Upstream synchronization implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Bring current upstream into `integration/next`, refresh upstream PRs #7/#8, and submit a focused animated-preview publication fix.

**Architecture:** Keep the fork's shared service, hosted Workshop, Blender/vector tools, and native protections on `integration/next`. Merge upstream ancestry and retain its cookbook, catalog, validation, and preview improvements. Each upstream contribution contains only its individual fix; integration-only contracts stay in the fork.

**Tech Stack:** Python, pytest, Pillow, Godot/GDScript, git worktrees, GitHub CLI.

## Task 1: Integrate current upstream

Files: merge `README.md`, `HANDOFF.md`, `STATUS.md`, `pyproject.toml`, `requirements.txt`, `src/mm_mcp/{catalog_builder,preview,server,validator}.py`, `tests/test_readme_counts.py`; synchronize `src/mm_mcp/data/`; update `docs/upgrade/TOOLS.md` and `scripts/check_release.py` if new retained contracts require it.

- [x] Start an isolated branch from `origin/integration/next`; record the clean portable baseline with `python scripts/check_release.py -m 'not browser and not native'`.
- [x] Run `git merge --no-commit upstream/main` and resolve each conflict. Keep fork dependency/version/resource contracts. Preserve strict validation and legacy import behavior while adopting enum-index errors/hints. Preserve preview staging and add upstream sweep support. Register the added batch tool with fork idle/path protections and document it.
- [x] Preserve upstream compound range/default resolution and fork catalog input templates/generic sizes; exercise existing catalog and validator tests with synthetic fixtures where available.
- [x] Run `python scripts/sync_package_data.py`, then the portable gate. Derive README counts from actual cookbook discovery and MCP registration. Retain compatible upstream preview/catalog tests in the gate.
- [x] Review integration diff and make a merge commit after targeted tests pass.

## Task 2: Refresh PR #8

Worktree: `.worktrees/upstream-render`, branch `fix/render-publication`.
Files: merge `pyproject.toml`, `requirements.txt`, `src/mm_mcp/preview.py`; retain existing render/preview tests.

- [x] Read and run focused existing render/preview contracts using the repository virtualenv and this worktree's source.
- [x] Merge `upstream/main`; resolve Pillow dependency consistency and combine upstream animated preview functions with the PR's staged single-preview renderer.
- [x] Preserve render retry cleanup, input-origin handling and engine export compatibility. Leave animated-sweep publication to Task 4.
- [x] Run focused render/preview tests and `git diff --check`; commit the merge and complete independent spec/quality review.
- [x] Push the existing contribution branch and update PR #8's description with fresh validation and limitations.

## Task 3: Clean PR #7

Worktree: `.worktrees/upstream-export`, branch `main`.
Files: release-only files in the PR diff, including `CHANGELOG.md`, `.release-please-manifest.json`, `pyproject.toml`; original Play source/tests remain focused on completed preview snapshots.

- [x] Fast-forward local `main` to `origin/main`, then merge `upstream/main` without rewriting published history.
- [x] Restore release-only files from `upstream/main` so the PR diff contains no fork release/version churn. Preserve the completed-preview download fix and its documentation.
- [x] Run focused Play/API/frontend checks and `git diff --check`; inspect the complete diff against upstream and complete independent spec/quality review.
- [x] Commit/push `main` and update PR #7's description with current verification. Do not merge the integration branch into `main`.

## Task 4: Publish animated sweeps safely

Worktree: separate contribution branch from `upstream/main`.
Files: `src/mm_mcp/preview.py`, `src/mm_mcp/render.py` only if retry cleanup requires a backwards-compatible callback, `tests/test_preview_sweep.py`.

- [x] Add failure regressions using real tiny PNGs and simulated native results: nonzero exit with partial frames, successful exit with missing frames, timeout preserving an existing GIF, corrupt frame, encoding failure, successful atomic replacement, and transient retry isolation.
- [x] Run the focused regressions and confirm they fail on unchanged upstream behavior.
- [x] Render frames inside a private temporary directory under the destination directory. Require exit zero and the complete expected frame sequence; decode PNGs and require consistent dimensions. Assemble GIF in staging and use `os.replace` only after assembly succeeds. Return structured errors and clean temporary data on failures. Clear private frame data before each native retry.
- [x] Run new regressions plus compatible existing preview/render checks. Review the final diff independently for spec compliance and code quality.
- [x] Commit/push a focused branch and create an upstream PR describing the concrete partial-frame/timeout failure and fresh test evidence. Port the fix into the fork while retaining its validation/path/queue contracts.

## Task 5: Finish and publish the fork

Files: `HANDOFF.md`, `STATUS.md`, `docs/upgrade/{UPSTREAM,INTEGRATION}.md` and this checklist.

- [x] Record exact upstream revision, PR URLs, local test scope and remaining native acceptance limits. Supersede the earlier pause on upstream work.
- [x] Complete final integration review and the appropriate final portable checks after all changes.
- [x] Fast-forward the primary checkout's `integration/next` to the verified integration candidate, push to `origin/integration/next`, and verify remote heads and PR scope/state.
- [x] Leave the main workspace on clean `integration/next`; keep focused contribution worktrees for maintainer follow-up.

No new release, live deployment, native editor-write enablement, packaging redesign, or broad native transaction PR is part of this pass.

## Completion evidence

Upstream snapshot: `362598c`. Existing PRs #7 (`f4c3d25`) and #8 (`22f8e73`)
are refreshed; new PR #13 (`e2a1a78`) contains the independent animated-preview
fix. Their contribution branches are published to origin. The fork's code at
`a86b09a` includes both upstream ancestry and the adapted sweep contribution.
Final portable gate: 641 passed, 1 Windows-only skip, 9 browser/native deselections.
Read-only source/catalog/audit checks and all 71 cookbook graphs pass separately.
The cookbook check also led to a bounded HDR-gradient compatibility fix; review
found and repaired canonical sweep input handling. Native graphics were not rerun.
