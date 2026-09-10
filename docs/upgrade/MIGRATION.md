# Migration from uploaded 0.7.0

## Do not merge by overwriting an active installation

Stop the old browser/MCP process. Preserve its source, `.env`, cookbook changes,
working `.ptex` files and output directories. Extract this candidate separately,
create a new virtual environment and use a fresh `MM_WORKSPACE_DIR`. There is no
in-place migration of arbitrary old shared-output folders into verified builds;
rerender the desired graphs to establish valid build identity.

The source and wheel carry proposed version 0.8.0a1. The wheel includes code and
resources but not Material Maker, Godot or third-party Python dependencies. The
optional configuration program creates or repairs `MM_GODOT_BINARY` and
`MM_PROJECT_PATH` in an existing `.env`, preserving unrelated settings and comments.
Run `python scripts/configure.py` from the prepared environment, then restart
Workshop to load the repaired `.env`. `--env-file` selects another file;
`--offline` preserves an existing file and allows native setup later in the browser.
See [SETUP.md](SETUP.md) for source launchers and browser setup. Standard Godot
does not require a `steam_appid.txt` workaround.

## New and changed environment settings

| Setting | Meaning |
| --- | --- |
| `MM_GODOT_BINARY`, `MM_PROJECT_PATH` | Native executable and Material Maker source paths. Environment and nonempty `.env` entries override the browser's saved per-user native defaults. |
| `MM_SETTINGS_FILE` | Process environment override for the native defaults JSON path. Only native paths are saved there; workspace and policy settings remain separate. |
| `MM_DOTENV` | Process environment override for the configuration file path. Default is `.env` in the current working directory. |
| `MM_WORKSPACE_DIR` | Persistent projects, revisions, recipes, jobs, builds and exports. Defaults to `output/workspace`. |
| `MM_ALLOWED_ROOTS` | Approved filesystem roots. A JSON array is preferred for cross-platform paths; the local path separator is also accepted. Default is the workspace plus output. |
| `MM_TRUSTED_UNRESTRICTED_PATHS=1` | Explicit legacy path opt-out. Do not use for untrusted agents. The new service still constrains recognized asset references. |
| `MM_ALLOW_CUSTOM_SHADERS=1` | Operator permission for new inline shader/export definitions. Disabled by default; not a sandbox. |
| `MM_ENABLE_EXPERIMENTAL_LIVE_WRITES=1` | Enables experimental writes in a newly launched overlay. Disabled by default. Restart the overlay after changing it. |
| `MM_MAX_RESOLUTION` | Default 2048, power of two from 32 through 4096. The experimental live bridge has its own 2048 limit. |
| `MM_PLAY_PORT` | Loopback browser port, default 8788. Allowed configuration range is 1024–65535. |
| `MM_RUNTIME_DIR` | Process environment override for private native discovery data. Default is the current user's `.mm-mcp` directory. |
| `MM_RENDER_DEVICE_ID` | Optional process environment tag recorded in build identity. It does not detect or select a graphics device. |
| `MM_IDLE_EXIT_MINUTES` | Existing opt-in timeout, default zero. New tool activity and pending/running shared jobs prevent idle expiry. |

Native paths follow process environment → nonempty `.env` → saved per-user native
defaults → built-in defaults. Other standard configuration values follow process
environment → nonempty `.env` → built-in defaults. Blank `.env` values are ignored.
An explicitly empty `MM_GODOT_BINARY` or `MM_PROJECT_PATH` process variable clears
that effective path; unset the variable to use the lower-precedence path again.
Empty process values for output/workspace paths, port and idle timeout use their
documented defaults. An empty process `MM_MAX_RESOLUTION` value is invalid.

By default the native settings file is `MaterialWorkshop/settings.json` beneath
`~/Library/Application Support` on macOS, `%APPDATA%` on Windows (falling back to
`~/AppData/Roaming`), or `$XDG_CONFIG_HOME` on Linux (falling back to `~/.config`).
Set `MM_SETTINGS_FILE`, `MM_DOTENV`, `MM_RUNTIME_DIR` and `MM_RENDER_DEVICE_ID` in the
process environment; entries for those overrides in `.env` have no effect.

Browser setup saves native defaults and applies the effective paths only while the
render queue is idle. It preserves workspace state and reports higher-precedence
overrides. Native write/custom-shader configuration is forwarded to overlays
launched by this package. An editor or assistant server launched separately must
receive the intended process environment and be restarted after native path changes.

## Breaking interface changes

Browser exports now require a completed `build_id`. They no longer accept a material
name and reconstruct a graph against a shared output folder. Browser requests carry
`X-MM-Token`; launch links contain the token in the URL fragment. Do not bookmark or
share tokens publicly. The viewer receives image bytes through authenticated requests.

Workspace edits require `project_id`, `expected_revision`, an operation array and
an idempotency key. `set_param`/`set_parameters` use a `parameters` object; exposed
controls use `set_controls` with their full IDs. Successful edits return a new
revision. A conflict means reread and reconsider, not blindly retry with a guessed revision.

The native protocol is `mm-live/2`, authenticated and revisioned. Old unauthenticated
clients cannot operate the new bridge. `live_apply` requires an expected revision
and retry key; graph replacement requires the same protections. Unconditional clear
is disabled. Live output rendering must supply a valid pixel resolution.

`save_graph` writes `.ptex` source outside the managed workspace. It cannot overwrite
state databases, provenance or build files; use the personal-recipe and build-export
tools for managed content. Overwriting an ordinary source file requires the explicit
boolean flag. Low-level authoring helpers remain available but are not a bypass of
the new code/path policies.

Render failures are now errors even when a process left a file behind. Corrupt or
wrong-size PNGs are errors. Canonical high-level builds use the Godot standard PNG
profile and convert into declared target packages. Arbitrary custom exporter formats
are not certified by that path; do not assume an EXR-oriented legacy workflow is
silently equivalent.

## Packaging and editable resources

`python scripts/sync_package_data.py` copies reviewed cookbook, guide and add-on
resources into package data. Run it after editing the canonical source copies.
`--check` detects drift; CI and wheel building require synchronization. Edit canonical
`cookbook/`, `docs/AUTHORING.md` and `addons/mm_live/`, not just their generated copies.

The source launchers `Play.command`, `play.bat` and `python3 scripts/launch.py`
prepare or repair the local virtual environment with runtime dependencies as needed.
They open the authenticated browser URL by default. A second launch verifies and
reuses the matching running workspace session; an unrelated listener is a port
conflict. Keep the first terminal open while using Workshop.

`mm-play` and `python -m mm_mcp.play.server` also open the browser by default.
Use `--no-open` for automation or a terminal-managed session; `--open` remains an
explicit compatibility option. The declared Python floor remains 3.10. CI targets
Python 3.13 on Linux, Windows and macOS; current executed checks and their native
rendering limits are recorded in [TESTING.md](TESTING.md) and
[INTEGRATION.md](INTEGRATION.md).
