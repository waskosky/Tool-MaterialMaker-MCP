# Tool-MaterialMaker-MCP — 0.8.0a1

Make editable procedural materials in **Material Workshop**, then refine the real
`.ptex` node graph in Material Maker or use the exported textures in your engine.
The browser and your AI assistant share saved projects, controls, versions and builds.
The cookbook is 53 materials across 12 categories.

This is an alpha. Browser workflows and portable contracts have been exercised;
successful native baking still needs validation on a compatible graphics setup.
See [current verification](docs/upgrade/TESTING.md).

## Start Workshop

Install Python 3.10 or newer, then open the launcher in this source checkout:

- **macOS:** double-click `Play.command`.
- **Windows:** double-click `play.bat`.
- **Linux:** run `python3 scripts/launch.py`.

The launcher prepares runtime dependencies and opens your browser. Launching again
reopens the same running workspace. Keep its terminal open while using Workshop.

In **Setup & repair**, find or enter your Godot executable and compatible Material
Maker source folder, save them, and choose **Test a small render**. Setup can open
before the native tools are installed. The [setup guide](docs/upgrade/SETUP.md)
includes download links, manual installation, saved settings and repair steps.

## Make something

1. Search the recipe library or choose a category. Open a material to create an
   editable project and start a small preview when rendering is configured.
2. Adjust its numbers, sliders, colors or gradient stops. Changes save automatically.
3. Choose numeric ranges and locks, then build a seeded family of variations.
   Inspect candidates, compare pinned images, and open a favorite with its exact controls.
4. Save a named version or personal recipe. Download the completed build's textures,
   editable `.ptex` source and target import notes together.

Library images come from verified completed builds. Browsing never starts a mass
render, and unbuilt recipes show an explicit placeholder. Follow the
[Workshop walkthrough](docs/upgrade/WORKSHOP.md) for projects, variations, snapshots,
comparison and export. [View the library](docs/upgrade/evidence/workshop-cookbook.png).

## Use with an assistant

The server exposes 32 shared material tools, 10 batch tools, and 8 live tools.
Configure your MCP host to launch `mm-mcp` from the installed Python environment.
Use the same working folder or `MM_WORKSPACE_DIR` as Workshop to share projects.
The [tool reference](docs/upgrade/TOOLS.md) and [workflows](docs/upgrade/WORKFLOWS.md)
describe authoring, jobs, variations and exact-build downloads.

The optional [Blender companion](docs/upgrade/BLENDER.md) inspects admitted static
GLB meshes, previews exact Workshop builds, and bakes portable PBR maps and packed
assets. An operator enables it with `MM_BLENDER_BINARY`; the default is disabled.

Builds record their exact graph, inputs, source dependencies and target. Downloads
use immutable build IDs. Workspace edits use revisions and retry keys. Native editor
writes and new custom shaders remain disabled by default. Native baking requires a
working desktop graphics context; Godot's `--headless` dummy renderer cannot bake maps.

## Development and current limits

Continue development on `integration/next`. The fork's `main` remains the branch for
focused upstream contributions; further upstream work is paused pending maintainer activity.
No alpha release is published by this workflow.

Install the development extras in your environment, then run the portable gate:

```bash
python -m pip install -e '.[dev,release]'
python scripts/check_release.py -m 'not browser and not native' -rs
python scripts/build_distribution.py
```

See [TESTING](docs/upgrade/TESTING.md) for browser and native acceptance. The local
Godot 4.7 native attempt hit a Vulkan compute compiler failure; real worker
cancellation passed, but successful native bake, exported-source reopening and
engine imports remain unverified. Browser screenshots with test images establish
UI behavior, not native material appearance.

| Guide | Purpose |
| --- | --- |
| [Setup & repair](docs/upgrade/SETUP.md) | Launch, connect native tools and repair paths. |
| [Workshop](docs/upgrade/WORKSHOP.md) | Browse, edit, vary, save and export. |
| [Migration](docs/upgrade/MIGRATION.md) | Upgrade from 0.7 and preserve existing work. |
| [Architecture](docs/upgrade/ARCHITECTURE.md) | Shared state, builds and native boundaries. |
| [Security](docs/upgrade/SECURITY.md) | Local authentication, code approval and path policy. |
| [Status](docs/upgrade/STATUS.md) | Exercised capabilities and remaining work. |
| [Integration record](docs/upgrade/INTEGRATION.md) | Archive provenance, changes and verification. |
| [Developer handoff](HANDOFF.md) | Current branch and next practical work. |

For changed behavior, `docs/upgrade/` supersedes older documentation. The
[original README](docs/upgrade/README-0.7.0.md) and historical evidence remain available.

## License and provenance

The original MIT license and attribution are preserved. Cookbook and vendor files
retain their notices. MaterialPilot source code is not copied into this implementation.
The uploaded baseline was `b41b65c612557a7da35a045091199058c0f76abb`; the retained
Material Maker compatibility pin is `ad19fcf0ee34a7caf74df709dc4de7112f0d467d`.
Godot and Material Maker are installed separately. See [PROVENANCE](docs/upgrade/PROVENANCE.md).
