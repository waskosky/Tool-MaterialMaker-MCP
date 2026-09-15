# Session handoff: Tool-MaterialMaker-MCP

_Last updated: 2026-09-15 — upstream synchronization and focused PR refresh._

## Current state

The user resumed upstream contributions after renewed maintainer activity.
Continue development on `integration/next`, tracking `origin/integration/next`;
keep `main` and focused fix branches for upstream PRs. This pass incorporates
upstream `362598cca9efa3cbf9e2a31a9deccd6a53a2b8f6`, retaining the existing hosted
Workshop, Foundry/Blender companion, vector-authoring and native protection code.

The cookbook contains 71 materials across 12 categories. Upstream's compound
catalog range/default resolution, enum-index errors and hints, material fixes,
authoring references and new preview rig are retained. The animated-preview MCP
tool joins the existing native lock. Package resources are synchronized (145
files); actual SDK registration is 33 shared, 11 batch and 8 live tools.

The final portable gate passes 641 checks with one Windows-only skip and nine
browser/native deselections. Catalog/default-resolution and material graph checks
use the pinned Material Maker source without launching Godot. PR #7's refreshed
diff removes release churn; PR #8 retains its publication checks alongside the
new upstream preview rig and sweeps. The new
[PR #13](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/13) safely
publishes complete animated sweeps and is also merged into the fork with canonical
input paths, bounded options and artifact checks. All three PRs are open and
mergeable. Contribution details and current acceptance scope belong in
[UPSTREAM.md](docs/upgrade/UPSTREAM.md).

Earlier native acceptance remains limited to sand at 128/256 pixels using the
prepared Godot 4.7 profile. Editable source reopening and native Godot LOW/HIGH
imports were checked at 128 pixels; the live record adds the 256-pixel bake,
browser/MCP handoff, serialized queue, cancellation and service recovery.
No new graphics acceptance or live deployment is part of this synchronization.
Native editor writes remain disabled. See [TESTING](docs/upgrade/TESTING.md), the
[native record](docs/upgrade/evidence/workshop-companion-native.json) and the
[live record](docs/upgrade/evidence/workshop-companion-live.json).

## Next work

1. Follow maintainer feedback on upstream PRs #7, #8 and #13. Packaging and small
   native transport protections are the next focused contribution candidates.
2. Expand ordinary material use beyond sand and inspect more opaque categories
   in the intended engine.
3. Keep native editor mutation/history acceptance separate before enabling it
   for artist work.

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

- 2026-09-15: Resumed focused upstream work; integrated upstream `362598c`,
  retaining Workshop/Blender/vector contracts and adding the expanded cookbook,
  catalog/default/enum fixes and preview rig. Refreshed PRs #7/#8, submitted #13,
  and verified the final fork with 641 portable checks plus read-only graph gates.
- 2026-09-14: Added pinned RAI plant authoring through shared Workshop/MCP projects,
  protected revisions, seeded variants and frozen exports; 570 portable checks.
- 2026-09-11: Added bounded Blender companion jobs, portable bakes and recovery;
  preserved the shared native lock and published through the integration branch.
- 2026-09-11: Repaired slashless proxy CSS/JS entry; 485 portable checks and a real
  proxy/browser regression passed with an inspected styled project page.
- 2026-09-11: Published the linked companion and verified TLS/browser/MCP handoff,
  128/256-pixel sand, cancellation, startup and crash recovery without rebooting.
- 2026-09-10: Completed setup/library/variation usability, renderer retries and
  browser ordering; recorded the then-current native compiler limitation.
- 2026-09-08: Submitted independent upstream export/render PRs #7/#8 and verified
  focused regressions; kept integration development separate from `main`.
- 2026-09-08: Integrated the supplied alpha, improved setup/package/docs, and
  published `integration/next`; reserved `main` for focused upstream contributions.
