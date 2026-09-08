# Practical workflows

## Inspect, instantiate, edit, build, export

Ask the assistant to call `material_capabilities`, search with
`material_recipe_search`, and inspect the chosen recipe with
`material_recipe_describe`. Inspect the actual controls and aliases before supplying
values. A semantic alias is a recipe-specific mapping, not a promise that every
material has a wetness or age parameter.

Create a shared project with `material_project_create`. Read its current revision
and apply one patch. An illustrative patch body follows; use the real project ID,
revision and control ID returned by the inspection tools, rather than copying these
example identifiers as actual application state.

```json
{
  "project_id": "p_example",
  "expected_revision": 0,
  "idempotency_key": "courtyard-roughness-edit-001",
  "operations": [
    {"op": "set_controls", "values": {"surface/param0": 13}}
  ],
  "dry_run": true
}
```

A dry run does not commit. Submit the reviewed intended patch as a commit with a
new key; preserve the key only for exact retries of that request. After a commit,
submit `material_job_submit` with the actual project ID and new revision, resolution
and target. Poll `material_job_get`. Read `material_build_get`, request image evidence
with `material_preview_image`, and export that exact ID with `material_build_export`.

## Browser workflow

Open the full printed launch URL. Select a recipe or existing shared project. Change
typed controls, save snapshots, lock controls, and choose a preview resolution. New
edits invalidate the old downloadable selection until the matching build completes.
A conflicting external edit is reported; it is not silently overwritten.

The browser's comparison list pins completed builds. Compare several candidates
under the same geometry, lighting and tile scale, and inspect individual maps. The
channel contact sheet is useful evidence but not a proof of physical accuracy.
Use the explicit height-preview toggle to choose bump visualization; it is not a
replacement for actual displaced geometry.

## Variation families

`material_variation_family` accepts an existing recipe, numeric ranges, a deterministic
sampling seed, locks and initial values. For example, search for a stone material,
inspect its controls, lock its pattern-scale control, vary two selected weathering
controls, and request six candidates at the same resolution. With `build=false` the
service returns candidate values and graph hashes without baking. With `build=true`
it queues the candidates and returns job identifiers.

The family seed controls sampling of parameters. A native material seed is a separate
explicit build or graph operation and is serialized as `seed_int`. No visual seed
change is assumed for a graph whose nodes do not use that seed.

## Shared world context

World context is explicit authored data. A binding selects a normalized field, real
control ID, numeric output range, optional exponent and optional inversion. The
service returns the resulting graph and values with `physics_inferred=false`.

A caller can use the same moisture field to adjust selected controls on ground,
stone and wood recipes. The caller must choose the mapping for each recipe. This
creates a traceable relationship without pretending that the package knows a
universal physical wetness function or derives calibrated friction from appearance.

## Editable two-layer composition

Use `material_compose_layers` with two inspected recipes and a native grayscale mask
node or subgraph. The supplied mask needs its native type/name/interface and must
satisfy normal graph/code policy. Both layers must expose the selected connected
material channels, have compatible native interfaces, and use equal output scalar
parameters. Normalize differences explicitly before composition.

The result keeps the layers editable, routes the mask to selected color/scalar
blend nodes and chooses the normal source. It does not perform reoriented normal
blending or height-aware multilayer displacement. That narrower contract is preferable
to advertising physically meaningful composition while doing a naive vector blend.

## Mesh-aware masks

`material_mesh_masks` accepts an approved local `.obj` path, resolution and up axis.
The file must already contain triangles with unique zero-to-one texture coordinates.
It generates coverage, normalized coordinate height and triangle-facing masks.
Reference their returned local paths from an approved image node; this step is
explicit rather than an automatic guess about the desired material layer.

The bake has a raster-work budget and refuses overlapping UV interiors. Empty texels
are zero and have a separate coverage mask; there is no automatic padding. Triangle
winding affects upward-facing values. The mesh is interpreted in its own coordinates,
not transformed into a game world's coordinate system. Use a proper mesh/engine tool
for unwrapping, curvature, ambient occlusion, topology repair and simulation properties.

## Engine packages and runtime budgets

`generic` exports canonical PNG maps and metadata. `godot` adds a baseline opaque
ORMMaterial3D resource. `roblox` adds explicit SurfaceAppearance filename mappings,
not uploads or fabricated asset identifiers. `unity` adds metallic/smoothness packing,
not a pipeline-specific material. `unreal` adds a green-flipped normal variant,
not a binary engine asset. Actual engine import is explicitly unverified in each manifest.

For older mobile/web targets, start with 256–512 previews and a deliberately small
final texture budget. Material evaluation remains on native workers; the client
consumes baked assets. Packed maps and bounded preview pixel ratio are implemented;
platform texture compression, atlas policies, streaming, render-cost budgets and
RAI/Godot Light import adapters must be selected by your downstream platform. This
package does not automatically impose an engine performance budget or generate full worlds.
