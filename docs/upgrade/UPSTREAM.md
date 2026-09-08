# Upstream contribution priorities — 2026-09-08

Continue development on `integration/next`, tracking `origin/integration/next`.
Reserve local and origin `main` for selected, reviewable upstream contributions.
Do not merge the full integration branch into that contribution branch.

- Fork: [waskosky/Tool-MaterialMaker-MCP](https://github.com/waskosky/Tool-MaterialMaker-MCP).
- Upstream: [graysonchalmers/Tool-MaterialMaker-MCP](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP).
- Inspected upstream main: `b41b65c612557a7da35a045091199058c0f76abb`, identical to
  `origin/main` when inspected. No code changes are needed on main to publish the
  integration branch.
- Open upstream work: no open issues; the sole open PR is the automated
  [0.8.0 release PR #6](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/6).
  It changes release metadata and the changelog, not the defects below. Its version
  number does not mean upstream already contains this fork's alpha implementation.

These are proposed contributions, not submitted requests. Priority reflects the
impact visible in current upstream source; native/GPU behavior has not been newly
certified during this review.

## 1. Export the graph and files that produced the selected preview

The upstream browser's export route explicitly passes empty control values, and
the export helper reloads the cookbook graph and includes every PNG in the shared
output directory. A user can therefore download an unedited graph with maps from
their edited preview, plus images left by another material.
Sources: [HTTP export route](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/play/server.py#L76-L81),
[ZIP helper](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/play/api.py#L66-L81).

Proposed PR: bind each completed preview to its exact saved graph, settings and
output inventory, and export that result. This can be a small file-backed receipt
without introducing the entire SQLite service. Cover edited controls, another
material's leftover PNG, and an obsolete preview response. The integration's
build/export tests provide examples of the required behavior.

## 2. Reject failed or corrupt renders and preserve the previous preview

Upstream reports a successful batch render after a nonzero process exit whenever
any fresh PNG exists. Preview rendering accepts any nonempty output file and
deletes the preceding preview before the attempt. This can advertise partial or
invalid output and discard the user's last usable preview.
Sources: [batch result handling](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/render.py#L164-L194),
[preview publication](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/preview.py#L50-L69).

Proposed PR: private staging, successful-exit checks, actual PNG decoding and
dimension/channel checks, followed by publication only after validation. Preserve
the last good preview on failure. Resolve relative output paths before passing
them to Godot as a small companion fix. Keep the existing public tool signatures
and upstream engine-export behavior when porting; do not copy a changed exporter
contract indiscriminately. Failure handling can be checked with small local
fixtures before native acceptance.

## 3. Protect native edits against unintended callers and stale/partial mutations

The native socket dispatches commands without authentication. `live_clear` is
explicitly irreversible, and `live_apply` performs operations sequentially until
one fails, without rolling earlier mutations back. Reads and writes do not share
an expected revision, so an intervening human edit is not detected.
Sources: [socket dispatch](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/addons/mm_live/live_server.gd#L17-L87),
[clear and batch tools](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/server.py#L344-L406).

Split this into reviewable requests: first authenticated local transport and
bounded requests; then explicit revision checks, saved recovery state and atomic
candidate application. The integration contains a proposed implementation, but
its native transaction/rollback behavior still needs Godot acceptance. Treat the
first small protection as urgent while keeping the larger native rewrite gated.

## 4. Ship the resources needed by installed distributions

Upstream wheels include browser/preview assets but omit the cookbook, authoring
guide and live add-on; cookbook discovery explicitly returns empty outside a
source checkout. The README recommends clone/editable installation, so this is
less urgent than incorrect outputs and unsafe edits.
Sources: [package data](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/pyproject.toml#L50-L51),
[cookbook discovery](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/config.py#L54-L63).

Proposed PR: synchronized package data, installed-resource fallbacks and an
isolated wheel-install check. Add portable CI separately from native renderer
claims. This integration's wheel was built and imported outside the checkout,
including its resources and real SDK registration.

The new shared project database, recipe families, world bindings, composition and
mesh workflows stay on `integration/next` while they mature. The fixes found only
inside those new modules are not existing upstream bugs. Coordinate release
numbering with upstream's release automation when submitting selected changes.
