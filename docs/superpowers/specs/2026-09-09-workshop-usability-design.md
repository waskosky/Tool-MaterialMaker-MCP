# Material Workshop usability milestone

The user approved the recommended first milestone on `integration/next`: reliable
native renders, easier setup and launch, a visual recipe/variation workflow, and
continuous integration for this branch. Keep `main` and upstream requests separate.

## Intended experience

Launch Material Workshop once, reuse that running session on subsequent launches,
and see whether native rendering is missing, configured, or actually verified.
Detect existing Godot/Material Maker installations and let the operator save or
correct their paths from the browser. Provide concrete installation guidance when
dependencies are missing. Preserve environment-variable configuration for MCP use.

Browse readable recipe cards with descriptions and real cached thumbnails when
available. Selecting a recipe creates an editable project and starts a small preview
when the renderer is configured. Controls remain typed; technical control IDs belong
in optional details. Generate a bounded family through labeled range controls, see
each candidate finish, inspect it, choose it as the current editable project, pin it
for comparison, or save it as a personal recipe. List saved snapshots for restoration.
Show actual job states, cancellation and retry rather than invented progress values.

## Boundaries and architecture

- Retain the shared Python service, SQLite workspace, immutable builds and local
  authenticated HTTP adapter. Use the existing vanilla JavaScript/Three.js client.
- Every native retry starts with empty private output. Resolve source-relative
  image references against an explicit original source directory; preserve the
  user's original graph and the alpha build/export contract. Respect cancellation.
- Saved setup settings contain only supported native paths. Environment and `.env`
  remain explicit overrides. Configuration updates must not discard projects or
  replace a service while jobs are active. Native verification requires a real build.
- Reopening a running server requires a private local discovery record and an
  authenticated identity check; an unrelated listener must produce a port conflict.
- Preview cards use completed, verified build artifacts. Missing images are labeled
  as such. Do not manufacture native-render evidence or render the entire cookbook
  automatically at launch.
- Recipe metadata and snapshot listing are small additions to existing service
  boundaries. Browser state must ignore stale job/project/family responses.
- Keep native artist-project writes disabled. Engine import certification, cloud
  services, broad asset-library management, and upstream work are later milestones.

## Acceptance

Focused regression checks cover retry contamination, source-relative references,
setup persistence/precedence, authenticated session reuse, and browser state changes.
The portable release gate and wheel checks pass. Exercise the actual browser and a
small native render/export/reopen cycle if a compatible local graphics runtime is
available; record specific limitations instead of treating simulated renders as proof.
CI runs on pushes to `integration/next`. Update user quickstart and current handoff,
commit and push the finished work to `origin/integration/next`.

## Setup interface contract

The browser setup panel uses the same authenticated adapter as materials. It can
operate before the native catalog is configured. Responses contain native paths,
checks and installation links, never session tokens or unrelated environment values.

| Request | Result |
| --- | --- |
| `GET /api/setup` | Current settings, effective overrides, checks, configured/verified state and installation links. |
| `POST /api/setup/check` with `{}` | Recheck the current configuration and discover installed native tools. |
| `POST /api/setup` with `godot_binary` and `project_path` | Validate and save supported settings; refresh the idle service's catalog without changing workspace. |
| `POST /api/setup/verify` with `{}` | Submit a small, forced native recipe build through the cancellable jobs interface. |
| `GET /api/session` | Authenticated application/session/workspace identity for launch reuse. |

Setup responses expose `settings: {godot_binary, project_path}`, `settings_file`,
`overrides` keyed by setting name, `detected: {godot_binaries, project_paths}`,
`checks: [{name, ok, detail}]`, `native_render_configured`,
`native_render_verified_this_session`, `last_render_error`, and
`install: {godot_url, material_maker_url}`. A check describes actual path/version
findings; successful path checks alone never mark a native render verified.

The frontend owns setup-panel presentation. The Python setup/session helpers own
discovery, persistence, identity checks and configuration refresh. Source launchers
use a small standard-library bootstrap helper so an existing virtualenv without
pip can still be repaired, and ordinary launches do not reinstall dependencies.

## Visual workflow interface contract

Recipe IDs and existing service fields remain stable. Gallery records add
`display_name`, `description`, and `thumbnail` (null or
`{build_id, url, renderer_kind}`). Titles and descriptions come from guide text or
explicit metadata. A thumbnail is the last completed build associated with that
recipe, including an edited project derived from it; the UI labels this as a last
build, not a certified default appearance. Its authenticated URL is
`/api/builds/{build_id}/thumbnail.png`. Artifact verification precedes image use;
corrupt or missing builds do not break the gallery or produce a replacement image.

`GET /api/projects/{project_id}` adds the originating `recipe_id`, when known, so a
reopened project can generate variations. It does not expose code approval records.
`GET /api/projects/{project_id}/snapshots` returns `{ok, project_id, snapshots}` with
each snapshot's `name` and `revision`. Snapshot names are bounded human-readable
labels, with no filesystem interpretation.

Family requests retain their existing structure and add `physical_size_m`, which
is carried into every candidate build. Family submission either returns all job
IDs or leaves no newly queued, untracked work when queue capacity is insufficient.
The client captures recipe, values, locks, ranges and build settings together.
Changing projects or replacing a family cancels its unfinished jobs and ignores
late responses. Choosing a candidate creates an editable project with its exact
values. A cached candidate preview is selected only after its graph hash matches
that project and its captured build settings are restored.

The gallery and controls use separate debounce timers. Parameter edits, history and
snapshot restoration invalidate the current download before requesting a fresh
preview. First previews use 256 pixels. Build failures expose a retry action; cards
show real queued/running/completed/cancelled states. Completed candidates can be
pinned for channel comparison or saved as personal recipes through an editable
project. Technical IDs remain available in optional details.
