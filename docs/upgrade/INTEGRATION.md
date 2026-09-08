# Local integration — 2026-09-08

The supplied 0.8.0a1 update is integrated into the repository on
`integration/next` (renamed from `integrate/0.8.0a1-updates`). The checkout started clean at
`b41b65c612557a7da35a045091199058c0f76abb`, matching the archive's documented baseline.
The user requested publishing this integration branch to `origin` and continuing
development there. Local and origin `main` are reserved for focused upstream pull
requests. No release or deployment is part of this integration.

`origin` is `waskosky/Tool-MaterialMaker-MCP`; the `upstream` remote points to
`graysonchalmers/Tool-MaterialMaker-MCP`. Both main branches matched the baseline
above when this branch was prepared. See [UPSTREAM.md](UPSTREAM.md) for the
recommended contribution order.

## Source and scope

- Input: `Tool-MaterialMaker-MCP-0.8.0a1-updated.zip` from the user-provided URL.
- Archive SHA-256: `c13d17e2597fa4ca1a461f02030dffeb7e010bb1bbd0865e7dc19b4f8750ca54`.
- Extracted source:
  `/Users/macuser/games/temp/materialmaker-0.8.0a1-updated-ccitfv89/Tool-MaterialMaker-MCP-0.8.0a1`.
- Imported all 22 changed files and 162 additions. No existing repository file
  was removed. The original cookbook and quality builders are unchanged.
- The original [delivery manifest](DELIVERY_FILE_MANIFEST.json) describes the
  supplied archive before the fixes below. Its checksums are not a manifest of
  the resulting working tree. Original execution logs remain in `evidence/`.

The imported service provides shared project revisions, atomic patches, undo/redo,
snapshots, recipes, verified immutable builds, target packages, local jobs,
composition, mesh masks and authenticated browser/native adapters. Native mutation
and new custom code remain disabled by default.

## Fixes made during integration

- Apply and validate raw-graph control overrides before rendering, so exported
  source agrees with requested controls and recorded build settings.
- Preserve approved cookbook code when saving and reopening personal recipes.
  Approval lives in service-owned provenance, separate from caller metadata.
- Include custom script and custom export script fields in code approval checks;
  inheriting a cookbook's shader approval cannot authorize newly added scripts.
- Resume persisted jobs through common service initialization, including MCP-only
  startup with an already-full queue.
- Ignore obsolete browser job responses after switching projects or starting a
  newer build; keep selection and cancellation attached to the current request.
- Use `pyproject.toml` as the dependency source, document new configuration in
  `.env.example`, open the authenticated URL from `play.bat`, and build wheels
  through the declared isolated PEP 517 backend. Package the cookbook README too.
- Restore documentation count checks against actual SDK tool registration. Extend
  the portable CI matrix to macOS and add a wheel metadata check. Update the
  handoff, changelog and host-environment guidance for the current source.

Two bounded code reviews checked the service and interfaces. Their concrete
findings were reproduced before fixes and checked again afterward.

## Local verification

Environment: macOS, Python 3.12.13, MCP SDK 2.2.0. The repository `.venv` contains
the editable project and its development/release dependencies.

| Check | Result |
| --- | --- |
| `.venv/bin/python scripts/check_release.py -m "not browser and not native" -rs` | 232 passed, 1 skipped, 2 deselected; 15.85 seconds. |
| Skip | Windows-only path case-folding on macOS. |
| Deselected | Chromium browser suite and opt-in native acceptance. |
| Package resource synchronization | All 109 source/package resource pairs match. |
| Python source parsing and `node --check src/mm_mcp/play/static/app.js` | Passed. |
| `.venv/bin/python scripts/build_distribution.py` | Built `dist/mm_mcp-0.8.0a1-py3-none-any.whl`. |
| `.venv/bin/python -m twine check dist/mm_mcp-0.8.0a1-py3-none-any.whl` | Passed. |
| Wheel installed with dependencies in a separate temporary virtualenv | Outside the source tree, found 53 cookbook recipes, the packaged guide/add-on, and all 42 registered SDK tools. |

The portable gate includes nine new focused regression cases for the fixes above,
including three Node-based request-order checks without browser or GPU startup.
Logs and JUnit output are under the extraction's parent directory as
`integration-contracts.log`, `integration-contracts.xml`, and `integration-wheel.log`.

The archive's earlier 218-pass Linux report is historical evidence. It does not
describe this checkout's checks. Native rendering, GDScript execution, WebGL
shading, engine imports, the historical full suite, and external GitHub CI were
not run during this integration. Those acceptance steps remain in
[TESTING.md](TESTING.md). The published-release manifest remains at 0.7.0 because
this alpha has not been released.
