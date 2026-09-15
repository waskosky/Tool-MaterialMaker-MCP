# Upstream contributions — 2026-09-15

Continue development on `integration/next`, tracking `origin/integration/next`.
Reserve `main` for focused upstream contributions; use separate fix branches when
PRs need independent review. The fork's application integration does not belong
in those contribution branches.

- Fork: [waskosky/Tool-MaterialMaker-MCP](https://github.com/waskosky/Tool-MaterialMaker-MCP).
- Upstream: [graysonchalmers/Tool-MaterialMaker-MCP](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP).
- Current integration baseline: upstream `362598cca9efa3cbf9e2a31a9deccd6a53a2b8f6`.
- The user resumed upstream work after maintainer activity. Earlier instructions
  pausing this work are historical.

## Incoming synchronization

The merge starts from fork `d850361`, including the recent Blender and RAI plant
work. It incorporates 112 upstream commits since the shared baseline: 18 new
recipes, existing-material repairs, compound catalog range/default resolution,
enum-index errors with corrective hints, authoring references and preview-rig
improvements. The cookbook now has 71 materials across 12 categories.

Fork-specific service, hosting, native protections and vector/Blender features
remain intact. The animated-preview MCP tool uses the same native lock as the
other render adapters. Actual SDK registration is 33 shared material tools,
11 batch tools and 8 live tools. All 145 package resources match their canonical
sources; package checks compare recipe paths rather than a fixed material count.

The cookbook check found an existing fork compatibility issue in
`s05_hex_stone_tile`: native gradient RGB values can exceed 1.0, and its roughness
ramp uses 1.05. Source validation now preserves finite HDR gradient colors, while
browser color-input validation retains its unit range. Material Maker's pinned
`types/gradient.gd` deserializes those RGB values directly into `Color`.

## Submitted upstream PRs

| Request | Origin branch / revision | Current evidence |
| --- | --- | --- |
| [#7: completed render downloads](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/7) | `main` / `f4c3d25` | 42 passed, 1 Windows-only skip, 1 native case excluded; [fork CI passed](https://github.com/waskosky/Tool-MaterialMaker-MCP/actions/runs/34935410321). |
| [#8: staged render publication](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/8) | `fix/render-publication` / `22f8e73` | 75 passed, 6 native/platform cases excluded; independent spec and code-quality review. |
| [#13: complete animated sweeps](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/13) | `fix/preview-sweep-publication` / `e2a1a78` | 76 passed, 6 native/platform cases excluded; 46 original failures reproduced and independent reviews passed. |

PRs #7 and #8 have been refreshed against current upstream without rewriting their
published histories. GitHub reports all three PRs mergeable. PR #7's version, release
manifest and changelog now match upstream; its seven-file diff contains only the
Play snapshot fix, tests and documentation. PR #8 resolves the dependency and
preview conflicts, retaining upstream's rig, sweep behavior and tile defaults.

PR #7 binds maps, ZIP and editable source to one completed `preview_id`; browser
edits, selections and newer requests invalidate old downloads. PR #8 requires a
successful native exit and decoded PNG output, clears each retry, preserves
previous files on failure and retains native exporter compatibility. Multi-file
engine publication still replaces files individually, without a directory-wide
transaction. Neither refresh constitutes new native/GPU acceptance.

Contribution worktrees remain at `.worktrees/upstream-export` and
`.worktrees/upstream-render` for maintainer follow-up. The new sweep contribution
uses `.worktrees/upstream-sweep`. Fork release automation
remains disabled; this pass publishes source branches and PRs, not a release.

## Animated-preview publication

Upstream's new `render_preview_sweep` could report success with one of 18 frames
after a failed process and deleted a previous GIF before attempting a render.
These cases were reproduced with simulated processes and real tiny PNG fixtures.
The submitted [PR #13](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/13)
on `fix/preview-sweep-publication` stages frames and GIF
assembly privately, verifies complete successful output, and publishes only after
assembly succeeds. The contribution is kept separate from the broader batch and
single-image changes in #8. Both upstream contribution branches merge cleanly in
either order; they share an identical optional retry callback.

The same fix is ported into the fork with existing PNG limits, canonical input
paths, allowed roots and destination-symlink checks. The new native call is bounded
to 120 frames, finite tile/cone controls and encodable frame timing. Review caught
an input-alias race in the initial port; the native command now receives the
canonical paths that were verified, with a regression that retargets the alias.
Corrupt PNG checksums also return a structured failure through artifact validation.

## Validation scope

Commands use the repository virtualenv. For worktree scripts, `PYTHONPATH=src:.`
ensures imports come from that worktree rather than the editable primary checkout.

- Portable integration gate: **641 passed, 1 Windows-only skip, 9 browser/native deselections**
  using `python scripts/check_release.py -m 'not browser and not native'` (56.19 seconds).
- Read-only native-source checks: set `MM_PROJECT_PATH` to the pinned Material
  Maker checkout, then run `pytest tests/test_catalog_parse.py tests/test_catalog_build.py tests/test_normal_albedo_audit.py -q` (22 passed) and
  `pytest tests/test_cookbook_gate.py -q` (216 passed across all 71 recipes).
- HDR and legacy-edit regressions: 25 passed, including reproduced HDR failures
  before the fix and unchanged browser color bounds.
- PR #7: `pytest tests/test_play_api.py tests/test_play_server.py tests/test_play_browser.py tests/test_play_renderer.py tests/test_readme_counts.py -m 'not integration' -q`.
  Startup tests use the pinned source and an inert executable path; no renderer
  is launched. JavaScript syntax and diff checks pass.
- PR #8: `pytest tests/test_render_publication.py tests/test_preview.py tests/test_render.py tests/test_play_renderer.py tests/test_render_tracked.py tests/test_render_compare.py tests/test_make_showcase.py tests/test_readme_counts.py -m 'not integration' -k 'not real_timeout_with_a_detached_grandchild' -q`.
- PR #13: `pytest tests/test_preview.py tests/test_preview_sweep.py tests/test_render.py -m 'not integration' -k 'not real_timeout_with_a_detached_grandchild' -q`.
- Fork sweep/catalog subset: 59 passed. The portable gate now retains the upstream
  sweep regressions and normal/albedo audit, plus portable compound-catalog cases.

Native graphics, broader engine acceptance and a live deployment are outside this
pass. The earlier sand acceptance remains in [TESTING.md](TESTING.md).

## Later candidates

After maintainer feedback on these focused fixes, consider portable installation
resources and small authenticated/bounded native transport changes. The larger
native revision/rollback rewrite needs separate disposable-editor acceptance.
Workshop, Foundry, Blender and vector-authoring architecture remain on the fork
until there is maintainer interest in broader adoption.
