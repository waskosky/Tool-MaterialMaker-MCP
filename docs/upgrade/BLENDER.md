# Optional Blender companion

Set `MM_BLENDER_BINARY` to an executable Blender 4.5 LTS binary to enable mesh
inspection, exact-build previews and mesh-specific PBR bakes. Leaving it empty
keeps the companion disabled without preventing ordinary Workshop use. This is
an operator setting; browser requests cannot select binaries, scripts, addons,
arbitrary paths or network assets.

Foundry supplies the browser controls through the existing private companion
mount. The same operations are available through the typed `blender_*` MCP tools
and [HTTP routes](TOOLS.md). They use existing session authentication and accept
both configured mounted routes and ordinary routes behind a stripping proxy.

## Inputs and operations

1. Save a completed Workshop build at 1024 pixels or below. Preview/bake require
   this exact immutable `build_id`; later project edits cannot change the input.
2. Choose `sphere` (default), `beveled_cube` or `plane`, or upload `{name,
   data_base64}` containing a static embedded GLB at most 4 MiB. Mesh bytes receive
   a `mesh_<sha256>` identity. Only plain glTF 2 triangles, embedded PNG/JPEG images
   and bounded vertex attributes are supported. External/data URIs, animation,
   skins, morph targets, cameras, sparse/compressed accessors and extensions are
   rejected before Blender launches.
3. Submit `inspect`, `preview` or `bake`, with a resolution of 128, 256 or 512.
   `uv_scale` explicitly repeats the procedural source from 0.125 through 16.
   Imported units are meters. Specimen sphere diameter and cube/plane side length
   equal the source `physical_size_m`, and diagnostics record their actual bounds.
4. Original UVs remain the default. `unwrap: true` creates a smart-project
   derivative with a separate destination layout, preserving uploaded bytes.
   Existing source UVs remain the material sampling coordinates where present;
   a mesh without complete source UVs uses the prepared coordinates. Bake rejects
   missing, degenerate, overlapping or out-of-tile layouts unless explicitly
   prepared. UV overlap screening samples a 64×64 grid, so subpixel overlaps still
   need artist review. Inspection reports topology, normals, transforms, UVs and
   material slots; preview/bake replace all slots on the derivative with the exact
   Workshop material.

Example public request:

```json
{"operation":"bake","build_id":"b_<exact-build-hash>","specimen":"beveled_cube","resolution":256,"unwrap":true,"uv_scale":2}
```

The response uses the existing `{ok, job_id, state, ...}` job envelope. Poll
`/api/jobs/{job_id}` or `blender_job_get`, and cancel with the existing cancellation
route or `blender_job_cancel`. Completed jobs contain `{ok, result_id, cached,
manifest}`. Reopening a browser can recover the selected job from that stable ID.

## Results and meaning

The manifest schema is `mm.blender-result/v1`, status `complete`, with identity
`bl_<input_hash>`. Its `request.json` is canonical JSON whose SHA-256 equals
`input_hash`. Inputs include the exact Workshop manifest and input hashes, source
file hashes, mesh identity, options, worker implementation hash, canonical binary
path and binary SHA-256. Receipts also record the actual Blender version. Only the
real fixed worker reports `renderer_kind: native_blender`; portable test doubles
remain explicitly identified, including the original source build's renderer.

Every result includes diagnostics and provenance. Preview/bake include
`preview.png` and a packed editable `material.blend`; the preview is supplementary
material evidence and does not replace Godot runtime validation. Native bakes also
contain:

- `base_color.png` and `emission.png` in sRGB; `normal.png`, `ao.png`,
  `roughness.png`, `metallic.png`, and `height.png` in linear space. Normal maps are
  OpenGL (+Y) tangent space. Height/emission are zero where absent from the source.
- `orm.png`, with R=AO, G=roughness and B=metallic. AO multiplies baked mesh
  occlusion by the source AO. Source color/material channels are sampled through
  an emission pass, avoiding scene-light contamination.
- `geometry_ao.png`, `world_normal.png` and two controlled masks. Crevice is
  inverted mesh AO; edge is a clamped image gradient of world normals. These are
  derived masks, with UV seam effects, and are not geometric curvature.
- An embedded `material.glb` with the baked material. It exposes the destination
  BakeUV as `TEXCOORD_0`, matching Foundry's shader; the packed `.blend` retains
  both the original sampling UVs and the destination layout.
- The exact `material.ptex`, original `source_manifest.json`, original
  `source_request.json`, original source maps/contracts, and `source_mesh.glb`
  when uploaded. Original procedural source remains authoritative.

Map descriptors follow Foundry roles, for example
`{"normal":{"file":"normal.png","channels":"rgb","color_space":"linear"}}`.
`physical_size_m` records the original procedural tile size; baked maps use the
mesh-specific destination UV layout. Foundry imports a native bake as a new
imported-map material with provenance, preserving its editable Workshop source.
No Material Maker shader translation is asserted. Arbitrary external Material
Maker dependencies remain rejected for this self-contained bundle.

Inventories are flat, at most 64 files, 16 MiB per file and 28 MiB total. Reads and
exports verify SHA-256 and byte counts, request identity, required files and map
contracts. ZIPs contain only inventoried artifacts plus the manifest, use stable
timestamps, and cannot expose unrelated workspace files.

## Execution and validation

Blender shares Workshop's persistent JobQueue, worker lock and native execution
lock with direct Material Maker builds. Workers use factory startup, disabled
Python auto-execution, offline mode, a private disposable user profile, a filtered
environment, two CPU render threads, a 600-second timeout and a 1 MiB output cap.
Cancellation, timeout and output-limit failures kill the owned process group and
remove staging/profile directories. A recorded-parent check plus an anonymous
owner pipe also terminates a detached worker after its HTTP/MCP parent crashes.
Legacy render/preview adapters share the same native lock. This fixed operation
boundary is not an OS sandbox for arbitrary Blender addons or scripts.

Portable tests use synthetic source/worker boundaries and real Python child
processes to check storage, authentication, scheduling and cleanup. Run them with
the normal `scripts/check_release.py -m 'not browser and not native'` gate.
The explicit native acceptance file uses a synthetic source fixture and records
that provenance; separate acceptance must preview/bake a real native Workshop
build and reopen its packed assets.

```bash
MM_TEST_BLENDER_BINARY=/Applications/Blender.app/Contents/MacOS/Blender \
python -m pytest tests/upgrade/test_blender_native.py -m native -q
```

Serialize this command with other native/GPU acceptance. No native worker runs
in the portable gate or without the explicit test binary setting.

Implementation verification on September 11, 2026: the portable release gate
passed 560 tests (one skipped, nine browser/native cases deselected). The Blender
subset includes 75 portable checks, including actual child-process timeout,
cancellation, output-limit and parent-crash cleanup. The first native run exposed
a Blender 4.5 normal-space enum mismatch; after correction, all four explicit
native cases passed. Preview scene packing and destination UV0 export gained
additional native assertions for the coordinated final acceptance run. These
native fixtures use a synthetic Workshop source and do not claim native Material
Maker provenance. The main integration acceptance records that separate canary.
