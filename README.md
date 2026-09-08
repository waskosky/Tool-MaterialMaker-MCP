# Tool-MaterialMaker-MCP — 0.8.0a1

Author editable Material Maker node graphs through a browser or AI assistant,
then refine the real `.ptex` graph in Material Maker. This alpha upgrade adds a
shared, persistent material service; native compatibility still needs acceptance
testing. The cookbook is 53 materials across 12 categories, with the existing
authoring helpers preserved.

The server exposes 24 shared material tools, 10 batch tools, and 8 live tools.
See [the tool reference](docs/upgrade/TOOLS.md) for the interfaces and migration notes.

**Start with [the developer handoff](docs/upgrade/START_HERE.md).** It identifies the
actual changes, test evidence, migration steps, and the remaining native acceptance gates.
The [local integration record](docs/upgrade/INTEGRATION.md) documents the imported
archive, follow-up fixes, and checks in this checkout. Historical documentation is
retained. For behavior changed by this upgrade,
`docs/upgrade/` supersedes the older documentation; the original README is preserved
as [README-0.7.0.md](docs/upgrade/README-0.7.0.md).

## What changed

- Builds bind the exact graph, controls, source dependencies, seed, resolution,
  tool fingerprints and target to an immutable identifier. Downloads use that
  identifier and a verified file inventory, not shared output-directory contents.
- Browser and assistant operations use the same SQLite-backed projects, revisions,
  atomic patches, retry receipts, undo/redo history and named snapshots.
- Recipes support typed controls, semantic aliases, explicit variation ranges and
  locks, shared world-context bindings, personal recipes and constrained editable
  two-layer composition. A bounded triangle-OBJ backend bakes coverage, height and
  upward-facing masks; it does not infer physics, curvature or occlusion.
- The browser has color and gradient controls, search, favorites, comparisons,
  target selection, asynchronous jobs, cancellation and a corrected material viewer.
- Local transports are authenticated and bounded. New shader code is denied by
  default. Native editor writes remain explicitly experimental and disabled.
- Distribution includes the cookbook, authoring guide, browser files, preview
  project and native add-on. The release gate uses real PNG decoding and a clearly
  identified synthetic test renderer; it does not pass a fake Godot executable off
  as native validation.

## Installation from this source archive

Run these blocks from the extracted repository root. They do not require editing
paths inside the commands. The configuration program asks for your existing Material
Maker checkout and Godot executable; it does not install those native applications.

### Linux or macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,browser]'
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/check_release.py
.venv/bin/python -m mm_mcp.play.server --open
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,browser]"
.\.venv\Scripts\python.exe scripts\configure.py
.\.venv\Scripts\python.exe scripts\check_release.py
.\.venv\Scripts\python.exe -m mm_mcp.play.server --open
```

An existing `.env` is never overwritten by the configuration program. Preserve your
configuration and follow [MIGRATION.md](docs/upgrade/MIGRATION.md). For a renderer-free
installation, use `scripts/configure.py --offline`; recipe browsing and local data
operations can be explored, but native-catalog-dependent authoring and baking still
require the native installation. Browser tests are skipped when Playwright or a
Chromium executable is unavailable. That skip does not certify the viewer.

The `mm-mcp` entry point starts the Model Context Protocol server over standard input
and output. Configure your AI host to launch that executable from this environment,
with this repository as its working directory or explicit `MM_*` environment values.
The native renderer needs a desktop graphics context. Do not add Godot's
`--headless` dummy-renderer flag and expect texture baking to work.

## Verify before adoption

```bash
python scripts/check_release.py -rs
python scripts/native_smoke.py
```

The first command is the current portable gate, including the retained compatible
0.7 unit tests. The second requires your native tools and performs real batch baking
in a new output workspace without editing any artist tab. See
[TESTING.md](docs/upgrade/TESTING.md) for graphics, editor and engine checks.

Archive implementation-run result: **218 passed, 3 skipped** in the release gate. The skipped
checks were the unavailable real MCP software development kit, opt-in native
rendering, and a Windows-only case-folding check on Linux. Chromium exercised the
browser logic with an in-process test adapter and synthetic images; actual WebGL
shading and browser-to-loopback networking were not certified in this environment.
Current local results are recorded separately in [INTEGRATION.md](docs/upgrade/INTEGRATION.md).

## Documentation

| Document | Purpose |
| --- | --- |
| [START_HERE](docs/upgrade/START_HERE.md) | Integration order and release boundaries. |
| [CHANGE_MAP](docs/upgrade/CHANGE_MAP.md) | Review finding → implementation → regression evidence. |
| [ARCHITECTURE](docs/upgrade/ARCHITECTURE.md) | State, builds, jobs, trust and native boundaries. |
| [MIGRATION](docs/upgrade/MIGRATION.md) | Breaking changes, installation and configuration. |
| [TOOLS](docs/upgrade/TOOLS.md) | All 24 new high-level tools and their signatures. |
| [WORKFLOWS](docs/upgrade/WORKFLOWS.md) | Practical authoring, variation, context and engine workflows. |
| [SECURITY](docs/upgrade/SECURITY.md) | Actual protections, permissions and limitations. |
| [TESTING](docs/upgrade/TESTING.md) | Reproducible tests and native acceptance checklist. |
| [STATUS](docs/upgrade/STATUS.md) | Implemented versus unverified versus deferred capabilities. |
| [DECISIONS](docs/upgrade/DECISIONS.md) | Concise engineering rationale and tradeoffs. |

## License and provenance

The original package's MIT license and attribution are preserved. Existing cookbook
and vendor files retain their notices. MaterialPilot source code is not copied into
this implementation. The design adopts general transaction, revision and recovery
principles, implemented in this package's own Python and Godot architecture.

The uploaded baseline Git commit was `b41b65c612557a7da35a045091199058c0f76abb`.
The retained Material Maker compatibility pin is
`ad19fcf0ee34a7caf74df709dc4de7112f0d467d`. This archive does not include Material Maker,
Godot, or the MCP dependency itself. See [PROVENANCE.md](docs/upgrade/PROVENANCE.md).
