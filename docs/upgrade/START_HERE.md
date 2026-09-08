# Developer handoff

For the integration into the current repository, start with
[INTEGRATION.md](INTEGRATION.md). The delivery description below documents the
supplied archive; local fixes and verification are recorded separately.

## Scope of this delivery

This is application code, tests and integration guidance, not only a roadmap. It
adds a shared recipe/project/build service, replaces the browser's fragile state
and export paths, strengthens rendering verification, and supplies an experimental
revisioned native bridge. The original cookbook, quality builders, authoring
helpers and historical tests remain available.

The candidate version is **0.8.0a1**. It is intentionally not presented as a
production-certified successor to MaterialPilot. Its intended advantages are the
browser workflow, reusable recipes, reproducible asset builds, shared state,
variation families, context controls, bounded mesh masks and several engine package
layouts. Native editor correctness and global editor undo are not established by
this delivery; MaterialPilot's earlier native implementation remains a useful
reference rather than a benchmark this package has demonstrably beaten.

## Suggested integration order

1. Review CHANGE_MAP, SECURITY and STATUS before merging. Preserve a backup of your
   0.7 installation, configuration, working graphs and exports. Use a separate branch
   and a new workspace for this candidate.
2. Run `python scripts/check_release.py -rs`. It checks synchronized package data,
   the new contracts, and retained portable test modules. Inspect the skips.
   Keep native writes and new custom shaders disabled.
3. Configure native paths, then run `python scripts/native_smoke.py`. This creates a
   fresh acceptance workspace under your output directory. Review its report and
   exported images rather than only its exit status.
4. Exercise the browser on your supported desktop and mobile browsers. Confirm real
   three-dimensional shading, controls, revision conflicts, target output and exact
   downloads. Then perform your engine-import acceptance.
5. Enable the experimental live-write gate only in a disposable native project.
   Perform the native transaction, rollback, retry, manual-edit and history checks
   in TESTING before considering artist-project deployment.

## Where to read the implementation

Start at `service.py`; it is the shared application boundary. Read `transactions.py`
for graph edits, `builds.py` and `artifacts.py` for builds and exports, then `recipes.py`
and `play/sliders.py` for creative controls. `tools.py` and `play/server.py` are the
assistant/browser adapters. `live.py` and `addons/mm_live/live_server.gd` are a
separate native compatibility boundary; they do not own the workspace database.

The package is not a distributed render farm, a multi-user hosted service, a browser
port of Material Maker, or an end-to-end RAI/Godot Light integration. The exported
contracts are intended to make those integrations smaller and explicit.

## Evidence to retain

The `evidence/` directory contains the actual portable test log and machine-readable
results from this implementation run, plus an execution summary. The manifest marks
test-injected renders as `injected_test_double`; such images must never become
native quality evidence. A historical browser launch failure is recorded as an
environment policy limitation, not repaired by weakening that policy.

`python -m pytest tests` still explicitly requests the historical suite as well.
Some 0.7 tests assert behavior that this update intentionally removes, such as an
unauthenticated bridge or reconstruction-based export. Those files are retained for
migration auditing, not silently deleted or claimed passing. The current gate is
`python scripts/check_release.py`; see TESTING for the scope and CI change.

## Deployment choices

For a personal local tool, run one browser service and one assistant host against
the same workspace. For a renderer machine, use the bounded local jobs interface
and treat native rendering as a privileged dependency. Do not expose these listeners
on a public interface or add a reverse proxy and infer multi-user isolation.

Do not share a writable workspace among mutually untrusted users. SQLite and file
hashes provide consistency and corruption detection, not protection against a user
who can rewrite both data and the manifest. Operational isolation is a separate task.
