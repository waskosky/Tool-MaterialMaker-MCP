# High-level tool reference

These 32 shared functions are registered by `tools.register`, alongside 10 batch
and 8 live tools. Setup, session discovery, thumbnails and snapshot listing are
browser HTTP routes; they do not add MCP tools. The actual source is authoritative.

Core results return an `ok` flag and structured error codes. Native/live tools remain separate. The image tool returns the official SDK image helper, not only a local path. Real SDK/client acceptance remains required.

## material_capabilities

```python
material_capabilities() -> 'dict'
```

Discover supported features and native configuration before doing work.

## material_recipe_search

```python
material_recipe_search(query: 'str' = '', category: 'str' = '', limit: 'int' = 30) -> 'dict'
```

Search recipe names, categories and guide text. This is lexical search, not embeddings.

## material_recipe_describe

```python
material_recipe_describe(recipe_id: 'str', include_graph: 'bool' = False) -> 'dict'
```

Inspect an editable recipe, version, typed controls and authoring notes.

## material_project_create

```python
material_project_create(recipe_id: 'str', values: 'dict | None' = None, title: 'str' = '') -> 'dict'
```

Instantiate a recipe as a persistent shared project without modifying native editor tabs.

## material_project_import

```python
material_project_import(graph: 'dict', title: 'str' = 'Imported material') -> 'dict'
```

Import a validated graph. New inline shaders require explicit operator approval.

## material_project_list

```python
material_project_list() -> 'dict'
```

List the browser/MCP workspace projects, including their current revisions.

## material_project_get

```python
material_project_get(project_id: 'str') -> 'dict'
```

Read the complete graph, current revision, hash, exposed controls and originating
`recipe_id` (`null` for an imported project without recipe provenance).

## material_project_patch

```python
material_project_patch(project_id: 'str', expected_revision: 'int', operations: 'list', idempotency_key: 'str', dry_run: 'bool' = False) -> 'dict'
```

Atomically validate and apply a patch. Use a new key for new intent, the same key for an exact retry.

## material_project_history

```python
material_project_history(project_id: 'str', expected_revision: 'int', direction: 'str') -> 'dict'
```

Undo or redo a workspace transaction; the project revision still increases.

## material_project_snapshot

```python
material_project_snapshot(project_id: 'str', name: 'str') -> 'dict'
```

Create an immutable named recovery snapshot in the persistent workspace.

## material_project_restore

```python
material_project_restore(project_id: 'str', name: 'str', expected_revision: 'int') -> 'dict'
```

Restore a named snapshot as a new, undoable revision.

## material_build

```python
material_build(request: 'dict') -> 'dict'
```

Build exactly one source: `recipe_id` (or its legacy `material_id` alias),
`project_id` plus its current `revision`, or a raw `graph`. Options include `size`,
`target`, `values`, `seed`, `physical_size_m` and the boolean `force`. Prefer jobs
for long bakes; `material_job_submit` accepts the same build request.

Only raw graph requests accept `source_dir`. It must name an existing absolute
directory within an approved asset root. Recognized `%PROJECT_PATH%/…` asset
references need that explicit origin; ordinary relative asset paths remain
ambiguous even when `source_dir` is supplied. `res://` resolves against the native
Material Maker source, and approved absolute asset paths are also accepted. Asset
paths remain bounded by the configured roots plus the native source directory,
and their content hashes participate in build identity. The renderer receives a
rewritten copy while the exported source preserves the original references.

## material_job_submit

```python
material_job_submit(request: 'dict') -> 'dict'
```

Queue a bounded build. A project revision conflict fails instead of baking newer unintended edits.

## material_job_get

```python
material_job_get(job_id: 'str') -> 'dict'
```

Read queued, running, complete, failed or cancelled status and any verified build result.

## material_job_cancel

```python
material_job_cancel(job_id: 'str') -> 'dict'
```

Request cooperative cancellation of the worker-owned bake, not an artist's editor process.

## material_build_get

```python
material_build_get(build_id: 'str') -> 'dict'
```

Verify artifact hashes and return the immutable completed build manifest.

## material_build_export

```python
material_build_export(build_id: 'str') -> 'dict'
```

Write a verified ZIP into workspace/exports. It contains only that build's exact files.

## material_variation_family

```python
material_variation_family(recipe_id: 'str', count: 'int' = 6, seed: 'int' = 1, ranges: 'dict | None' = None, locked: 'list | None' = None, values: 'dict | None' = None, build: 'bool' = False, size: 'int' = 256, target: 'str' = 'generic', physical_size_m: 'float' = 1) -> 'dict'
```

Create deterministic recipe variations from explicit ranges, preserving locked
controls. With `build=True`, queued candidates retain `size`, `target` and
`physical_size_m` (default 1 metre).

## material_world_context

```python
material_world_context(recipe_id: 'str', context: 'dict', bindings: 'list', locked: 'list | None' = None, values: 'dict | None' = None) -> 'dict'
```

Apply explicit normalized environment-to-control mappings. No physical properties are inferred.

## material_compose_layers

```python
material_compose_layers(base_recipe_id: 'str', coating_recipe_id: 'str', mask: 'dict', channels: 'list | None' = None, normal_source: 'str' = 'base') -> 'dict'
```

Compose two editable recipes through a native scalar mask; normals are selected, not linearly blended.

## material_recipe_save

```python
material_recipe_save(project_id: 'str', name: 'str', metadata: 'dict | None' = None, guide: 'str' = '') -> 'dict'
```

Save a new personal recipe without overwriting the cookbook or existing recipes.

## material_compare

```python
material_compare(build_ids: 'list', channel: 'str' = 'albedo') -> 'dict'
```

Create a channel contact sheet and technical metrics; this is not a visual-quality score.

## material_preview_image

```python
material_preview_image(build_id: 'str', channel: 'str' = 'albedo', max_size: 'int' = 768)
```

Return actual bounded image content to the assistant, not merely a filesystem path.

## material_mesh_masks

```python
material_mesh_masks(obj_path: 'str', size: 'int' = 256, up_axis: 'str' = 'y') -> 'dict'
```

Bake coverage, normalized height and upward-facing masks from an approved triangle OBJ with unique UVs.

## blender_capabilities

`blender_capabilities()` returns the optional worker's configured status, supported
operations, specimens, dimensions and upload/result limits.

## blender_mesh_upload

`blender_mesh_upload(name: str, data_base64: str)` admits a static, embedded GLB at
most 4 MiB and returns `{ok, mesh: {mesh_id, sha256, bytes, name, ...}}`.

## blender_job_submit

`blender_job_submit(operation, build_id=None, mesh_id=None, specimen=None,
resolution=256, unwrap=False, uv_scale=1)` queues `inspect`, `preview` or `bake`.
The typed schema restricts specimens to `sphere`, `beveled_cube`, `plane` and
resolution to 128, 256, 512. Preview/bake require an exact completed `build_id`.
The source build, worker and binary identities are pinned before queue admission.

## blender_job_get

`blender_job_get(job_id: str)` reads the existing persistent queue. Both material
and Blender tools observe the same jobs and terminal result receipts.

## blender_job_cancel

`blender_job_cancel(job_id: str)` requests cancellation and worker cleanup through
that same queue; source builds and admitted meshes remain available.

## blender_result_get

`blender_result_get(result_id: str)` verifies the entire immutable inventory and
returns `{ok, manifest}` with schema `mm.blender-result/v1`.

## blender_result_file

`blender_result_file(result_id: str, name: str)` returns one verified inventory
artifact as `{ok, result_id, name, bytes, sha256, data_base64}`. No filesystem path
or URL may be supplied. Files are bounded to 16 MiB.

## blender_result_export

`blender_result_export(result_id: str)` writes a verified deterministic ZIP to the
managed exports directory and returns its path, byte count and SHA-256. The bundle
includes exact procedural source provenance and only its inventoried artifacts.
See [Blender companion](BLENDER.md) for maps, diagnostics and native acceptance.

## Batch and native tools

The original authoring tools remain registered alongside the shared service.
Native mutations require the experimental gate, an expected revision and a retry
key. `live_clear` returns a diagnostic directing callers to revisioned replacement.

| Tool | Purpose |
| --- | --- |
| `list_node_types` | Discover native catalog node names. |
| `describe_node` | Read a node's ports and parameters. |
| `validate` | Validate a graph, including nested subgraphs. |
| `render_graph` | Batch-render an editable graph. |
| `render_node_output` | Batch-render an isolated node output from a copy. |
| `render_preview` | Preview existing maps on native 3D geometry. |
| `save_graph` | Save source outside managed workspace state; overwrite is opt-in. |
| `list_examples` | List cookbook and native example graphs. |
| `load_example` | Read a graph from either library. |
| `inspect_project` | Inspect a saved graph and its content hash. |
| `live_start` | Connect to or launch the native overlay. |
| `live_get_graph` | Read the active graph and revision. |
| `live_apply` | Apply a revisioned native transaction. |
| `live_render` | Render the active graph at the requested resolution. |
| `live_render_node_output` | Batch-render an isolated copy of a native node. |
| `live_clear` | Explain the replacement for unconditional clearing. |
| `live_load` | Replace a native graph with revision checks and recovery. |
| `live_history` | Use bridge-owned undo or redo. |

## Graph operation names

`set_controls`, `set_param`, `set_parameters`, `add_node`, `delete_node`, `reposition_node`, `move_node`, `set_label`, `connect_nodes`, `disconnect_nodes`, and `set_seed` are implemented. Inspect `transactions.apply_patch` for the exact fields. Exposed controls use full hierarchical IDs; material-family APIs also accept recipe aliases. The set-seed operation writes the native integer field `seed_int`.

## Important errors

Handle `REVISION_CONFLICT` by rereading, `VALIDATION_FAILED` by inspecting diagnostics, `CUSTOM_SHADER_DISABLED` by leaving policy intact, `MISSING_CHANNELS`/`INVALID_IMAGE` by investigating the renderer, and `ARTIFACT_CORRUPT` by quarantining rather than silently trusting cached files. A cancelled job is not a completed build.

## HTTP adapter

Browser API calls require `X-MM-Token`. Launcher session discovery can instead use
the authenticated challenge/proof protocol implemented in `play/session.py`.
The adapter enforces loopback Host/Origin checks and a content security policy.

| Method and route | Purpose |
| --- | --- |
| `GET /api/capabilities` | Shared features and native rendering state. |
| `GET /api/setup` | Effective native paths, overrides, settings location and configuration state. |
| `POST /api/setup` | Save native defaults and apply effective paths while the queue is idle. |
| `POST /api/setup/check` | Discover native paths and check current configuration; body is `{}`. |
| `POST /api/setup/verify` | Queue a small native verification build; body is `{}`. Inspect or cancel its job through the jobs routes. |
| `GET /api/session` | Authenticated workspace/session identity for launcher reuse. |
| `GET /api/materials`, `GET /api/material/{recipe_id}` | Search recipes or describe one recipe and its controls. |
| `GET /api/projects`, `GET /api/projects/{project_id}` | List projects or read current graph state and recipe origin. |
| `POST /api/projects` | Instantiate an editable project from a recipe. |
| `POST /api/patch`, `POST /api/history` | Revisioned edits, undo and redo. |
| `GET /api/projects/{project_id}/snapshots` | List saved snapshots. |
| `POST /api/snapshot`, `POST /api/restore` | Save a named snapshot or restore it as a new revision. |
| `POST /api/render`, `POST /api/jobs` | Build synchronously or queue a bounded build. |
| `GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/cancel` | Read job state or request cancellation. |
| `GET /api/builds/{build_id}` | Read a verified completed manifest. |
| `GET /api/builds/{build_id}/thumbnail.png` | Read an authenticated thumbnail from a completed build. |
| `GET /api/builds/{build_id}/files/{filename}` | Read an artifact from that exact build. |
| `GET /api/export?build_id={build_id}` | Download the verified build ZIP. |
| `POST /api/family`, `POST /api/context` | Create variations or apply explicit world-context bindings. |
| `POST /api/compare`, `GET /api/comparisons/{filename}` | Create or read a comparison image. |
| `POST /api/recipes/save`, `POST /api/mesh-masks` | Save a personal recipe or build bounded mesh masks. |
| `GET /api/blender/capabilities` | Optional fixed Blender operations and bounds. |
| `POST /api/blender/meshes` | Upload `{name, data_base64}` as a static embedded GLB. |
| `POST /api/blender/jobs` | Queue a fixed inspect/preview/bake request; use existing job status/cancel routes. |
| `GET /api/blender/results/{result_id}` | Verify and read the immutable result manifest. |
| `GET /api/blender/results/{result_id}/files/{name}` | Download a verified result artifact. |
| `GET /api/blender/results/{result_id}/export` | Download the bounded self-contained ZIP. |

Use the shared Python service or MCP interface for integrations. The actual route
dispatch in `play/server.py` defines the browser adapter contract.
