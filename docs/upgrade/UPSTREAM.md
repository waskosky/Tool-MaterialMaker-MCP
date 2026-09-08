# Upstream contribution priorities — 2026-09-08

Continue development on `integration/next`, tracking `origin/integration/next`.
Reserve local and origin `main` for selected, reviewable upstream contributions.
Use separate contribution heads from `upstream/main` when concurrent PRs need
independent review. Do not merge the full integration branch into those heads.

- Fork: [waskosky/Tool-MaterialMaker-MCP](https://github.com/waskosky/Tool-MaterialMaker-MCP).
- Upstream: [graysonchalmers/Tool-MaterialMaker-MCP](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP).
- Contribution baseline: upstream main `b41b65c612557a7da35a045091199058c0f76abb`,
  identical to `origin/main` before these contributions. Each new PR contains one
  independent commit on that baseline.
- Previously open upstream work: no open issues; the sole PR before our submissions was the automated
  [0.8.0 release PR #6](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/6).
  It changes release metadata and the changelog, not the defects below. Its version
  number does not mean upstream already contains this fork's alpha implementation.

The first two contributions are now submitted and remain open. Priority reflects
the impact visible in upstream source; native/GPU behavior has not been newly
certified during this review.

| Request | Origin head | Commit | Verification |
| --- | --- | --- | --- |
| [#7: bind Play downloads to completed render snapshots](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/7) | `main` | `a2e100e` | 34 focused local checks; [Windows CI](https://github.com/waskosky/Tool-MaterialMaker-MCP/actions/runs/34260468951): 1,002 passed, 25 deselected. |
| [#8: validate staged output before publication](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/8) | `fix/render-publication` | `d3c0bb6` | 47 focused local checks; independent review and regression fixes. |

Both target upstream `main`. Upstream PR workflows require maintainer approval;
the fork's Windows result belongs to #7. The inherited `release-please` workflow
was disabled on the fork after it attempted to create a fork release PR and GitHub
rejected that operation. Release automation remains enabled upstream. No release
was published. The integration branch remains the development checkout.

Review worktrees are retained at `.worktrees/upstream-export` (`main`) and
`.worktrees/upstream-render` (`fix/render-publication`) for follow-up changes.

## 1. Export the graph and files that produced the selected preview

The upstream browser's export route explicitly passes empty control values, and
the export helper reloads the cookbook graph and includes every PNG in the shared
output directory. A user can therefore download an unedited graph with maps from
their edited preview, plus images left by another material.
Sources: [HTTP export route](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/play/server.py#L76-L81),
[ZIP helper](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/play/api.py#L66-L81).

Submitted in #7: each completed preview has private maps, a saved ZIP/applied
graph, and a receipt. Map and export routes require its `preview_id`. Browser
selection, editing and newer requests invalidate the prior download and ignore
obsolete replies. Tests cover edited controls, unrelated PNGs, later renders,
incomplete results, HTTP downloads and request-order races. Completed previews
persist on disk; the upstream README documents cleanup.

## 2. Reject failed or corrupt renders and preserve the previous preview

Upstream reports a successful batch render after a nonzero process exit whenever
any fresh PNG exists. Preview rendering accepts any nonempty output file and
deletes the preceding preview before the attempt. This can advertise partial or
invalid output and discard the user's last usable preview.
Sources: [batch result handling](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/render.py#L164-L194),
[preview publication](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/blob/b41b65c612557a7da35a045091199058c0f76abb/src/mm_mcp/preview.py#L50-L69).

Submitted in #8: private staging, successful-exit checks, actual PNG decoding and
baked-map dimensions, followed by publication after validation. Each crash retry
clears its old texture output. Process/decode failures preserve previous files.
Relative output paths are resolved before invoking Godot.

Native-source review caught compatibility details that the patch now preserves:
document-relative image references, rectangular dynamic texture buffers, protected
engine material/metadata files, and absolute texture paths in UE5 helper scripts.
Every native product is carried forward, with existing companion files visible
to the native overwrite rules. Public tool signatures are unchanged. This does
not certify PBR channel semantics, arbitrary custom profiles, or atomic publication
of an entire multi-file directory. Real native/engine acceptance remains pending.

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

Before alpha native acceptance, carry the retry-isolation and document-relative
image handling findings into its renderer with its cancellation and immutable
build contracts intact. The alpha renderer currently stages once per render,
not once per retry. Do not wholesale-copy #8's legacy engine-export publication
onto the service's separate package contract.
