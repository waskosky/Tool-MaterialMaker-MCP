# Migration from uploaded 0.7.0

## Do not merge by overwriting an active installation

Stop the old browser/MCP process. Preserve its source, `.env`, cookbook changes,
working `.ptex` files and output directories. Extract this candidate separately,
create a new virtual environment and use a fresh `MM_WORKSPACE_DIR`. There is no
in-place migration of arbitrary old shared-output folders into verified builds;
rerender the desired graphs to establish valid build identity.

The source and wheel carry proposed version 0.8.0a1. The wheel includes code and
resources but not Material Maker, Godot or third-party Python dependencies. The
configuration program asks for native paths. With existing configuration, review
it rather than using a placeholder-filled shell command.

## New and changed environment settings

| Setting | Meaning |
| --- | --- |
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

Use process environment variables for runtime-directory and render-device overrides;
those are read directly where used. Standard configuration values follow environment
→ `.env` → defaults precedence. Native write/custom-shader configuration is forwarded
to overlays launched by this package. An editor launched manually must receive the
same intended process environment; changing the browser's settings does not alter
an already-running editor process.

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

The `play.bat` launcher now passes `--open` to open the authenticated launch URL.
The documented module command with `--open` works on every platform. Python 3.13 is the
implementation-run interpreter. The declared Python floor remains 3.10, but the
entire interpreter/platform matrix has not been executed here.
