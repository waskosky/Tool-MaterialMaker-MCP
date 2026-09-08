# Historical review input — before this upgrade

The following review concerns the uploaded 0.7.0 package. See CHANGE_MAP.md and STATUS.md for the implemented changes and remaining acceptance limits.

# Material Maker MCP: implementation review and improvement plan

Review date: September 8, 2026. Uploaded implementation: Tool-MaterialMaker-MCP, version 0.7.0. Comparison: MaterialPilot 0.1.0 at commit `e3721eadd042e077f3aa7d472ad83c5594c7ea5b`.

## Executive judgment

The uploaded project is a more compelling starting point for an artist-facing material exploration product: it combines a browser interface, 53 editable cookbook materials in 12 categories, readable grouped graphs, recipe cards, procedural builders, batch export, diagnostic renders, and optional live editing. MaterialPilot has substantially stronger implemented transaction and authentication mechanisms. This is an architectural comparison, not a benchmark demonstrating that either assistant creates better-looking materials.

For a browser-oriented RAI/Godot asset platform, preserve this project's recipe and interaction design while adding reliable state, render, export, and permission contracts. MaterialPilot's native transaction adapter is useful reference material. Do not run independent competing mutation clients against the same graph, or merge both applications wholesale before defining their boundaries.

## Scope and evidence limits

The review inspected the uploaded Python, GDScript, JavaScript, tests, cookbook structure, and documentation. It also inspected current primary-source MaterialPilot bridge and transaction code. No source changes were made to the uploaded implementation.

Seven independent non-rendering probes reproduced the behaviors below. They call actual Python functions, with filesystem operations confined to temporary directories and renderer/socket calls replaced with explicit test doubles. The `live_apply` probe executes the original function body in isolation because the MCP dependency was unavailable. These probes do not certify a running MCP session or native rendering.

A selected upstream test run produced **89 passed, 12 failed, 1 skipped, and 3 deselected**. This is NOT a full-suite result. The 12 failures break down as follows:

- Five catalog parser cases require Material Maker node files absent from this environment.
- Three configuration cases require a real configured Material Maker/Godot installation; one expected binary error was masked by the earlier missing-project validation.
- Two path-list tests use Windows drive strings and fail under Linux's colon-separated path convention.
- One path-fragment test expects backslash rejection, whereas the implementation uses host operating-system separators.
- One subprocess test unconditionally uses Windows-only `creationflags`, so its launcher exits before the expected timeout on Linux.

Godot and the Material Maker checkout were not present, and installing the missing MCP package failed because outbound package-network access was unavailable. No real shader execution, rendered visual comparison, browser session, native undo, engine import, or cross-platform integration test was completed. Those limitations must not be confused with evidence that Windows rendering fails.

## Reproduced findings

### F1. Browser export does not preserve edited state

**Priority: high.** `src/mm_mcp/play/static/app.js:145-147` sends only the material identifier to `/api/export`. `src/mm_mcp/play/server.py:76-82` supplies `values={}`. `src/mm_mcp/play/api.py:66-81` reloads the original graph and packages every PNG in the shared output folder.

The probe changed `t01_sand_dunes`'s ripple scale from 7 to 13, then followed the export handler's input shape. The exported graph still contained 7. An unrelated PNG placed in the output directory was also included. The probe did not render those values.

**Fix:** Export by immutable completed build identifier. Each build must bind the exact graph snapshot, parameter values, resolution, target, seed, artifact inventory, and checksums. The download should be unavailable until the selected build finishes. Do not construct a graph from current controls while retrieving maps from a different build.

### F2. Browser live edits lose nested-node scope

**Priority: high.** `src/mm_mcp/play/sliders.py:83` emits an internal node name without its containing subgraph. `src/mm_mcp/play/api.py:45-46` forwards that name. `src/mm_mcp/live.py:283-286` searches only top-level nodes.

For the actual sand-dunes cookbook graph, the binding names `DuneRipples`, but the top-level node is `dune_ripples`. The actual `set_param` function returned `no node named 'DuneRipples' in the current live graph` before contacting the socket. The browser renderer's fallback can conceal this mismatch by reverting to batch rendering after loading the graph.

**Fix:** Use hierarchical, stable identifiers consistently, or modify the exposed parameter on the containing subgraph. Preserve all linked-widget relationships, not only the first link. Test browser-to-native updates on the shipped nested recipes.

### F3. Requested resolution is dropped on the live render path

**Priority: medium/high.** `src/mm_mcp/play/renderer.py:16-31,56` forwards `size` only to the batch renderer. `src/mm_mcp/live.py:345-365` has no size argument. The native addon calls `export_material` with an unchanged resolution argument at `addons/mm_live/live_server.gd:246`.

A mocked live render requested at 1024 received only `basename` and `cfg`. This demonstrates omitted forwarding, not the final native image dimensions.

**Fix:** Make resolution part of one shared render request contract and verify produced dimensions in both paths.

### F4. A partial or invalid render can be marked successful

**Priority: high.** `src/mm_mcp/render.py:130-152` checks filename, nonzero size, and modification time. At lines 186-194, a nonzero process return code does not cause failure if any fresh image exists.

The probe simulated an exit code of 17 and wrote a nonempty file named `probe_albedo.png` containing invalid image data. The function returned `ok=True`.

**Fix:** Require the target profile's full expected artifact set, decode images, verify dimensions and channel conventions, and publish from a private build directory only after validation. Classify known benign process anomalies explicitly instead of treating arbitrary partial output as success. Save detailed diagnostics and distinguish failed, partial, cancelled, and complete builds.

### F5. Validation does not provide an adequate strict authoring contract

**Priority: high before autonomous authoring.** `src/mm_mcp/validator.py:4-90` correctly checks some missing nodes, catalog membership, numeric ranges, port bounds, and nested graph contents, but important schema and structure checks are absent.

The probes returned no diagnostics for duplicate node names, a cycle, multiple connections to the same input, a string-valued numeric parameter, NaN, and a fractional enumeration value. A malformed string port raised `TypeError` instead of producing structured diagnostics.

**Fix:** Separate tolerant import compatibility from strict generated-graph validation. Define nested graph schemas, unique identifiers, typed finite parameters, integer enum/port checks, graph and nesting limits, legal connections, dynamic port interfaces, and target-specific output requirements. Match legitimate Material Maker conversions and node behavior; do not prohibit legal conversions or confuse user-interface slider hints with shader-enforced limits. An incomplete editing graph need not meet a final-export contract.

### F6. Live batches can leave partial edits behind

**Priority: high.** `src/mm_mcp/server.py:372-422` executes operations sequentially and stops on the first failure without rolling back earlier successful operations.

An isolated probe executed the original function with a successful mocked node addition followed by an unknown operation. The overall result failed while the first effect remained. This behavior is consistent with the function's documented design; it is a limitation for autonomous editing, not a claim that the code violates its own documentation.

**Fix:** Add transaction-level validation, graph revisions, snapshots, atomic commit/rollback, one native undo step, idempotent retries, and stable references for newly created nodes. Protect graph replacement and clear operations with explicit policy and recovery snapshots.

## Additional source-inspection findings

### Preview correctness affects creative decisions

`src/mm_mcp/play/static/app.js:14-27,54-72` initializes a gray-tinted material with roughness 0.8, binds packed ORM data only to roughness, and never binds metallic or occlusion channels. It lacks explicit texture color-space setup. It leaves existing maps in place when replacement outputs omit them and allocates replacement textures without disposing the old ones. These are source-inspection findings, not observations of an executed browser render.

With the documented three.js material semantics, the preview therefore cannot faithfully represent the full exported material. In particular, the metallic response remains at its default zero. Fix channel binding, neutral scalar multipliers, texture replacement/cleanup, normal convention, and color management together. The bundled library is r128, so modern property names must not be pasted into it without a deliberate version migration.

### Security is local but not authenticated

`addons/mm_live/live_server.gd:17-87` binds to loopback but has no authenticated handshake, request-size ceiling, or per-command authorization. The web surface explicitly states single-user/no-auth at `src/mm_mcp/play/server.py:1-3`. Path bounding is opt-in at `src/mm_mcp/paths.py:17-24`.

This is not evidence of an internet-exposed service or a demonstrated remote exploit. It is insufficient protection for untrusted agents, shared machines, or a hosted deployment. Add authenticated sessions, restrictive workspace roots, embedded-asset path policy, server-side request/graph limits, destructive-operation approval, and browser Origin/Host checks. Treat native rendering as a separately permissioned worker.

### Browser state and rendering need one owner

The browser serializes renders with a process-local lock, uses shared `play_*` filenames, and tracks `_last_pushed_id` rather than a graph revision or session identity. This does not coordinate a separate MCP process or a human changing the active native tab. The browser also does not tag responses with an active request revision before applying them.

Use per-project revisions, immutable artifacts, a central worker queue, cancellation/supersession of stale requests, and a single mutation owner. A matching material name does not establish that the native graph still has the expected contents.

### Important existing functionality should be preserved

The project already contains recipe cards, grouped native graphs, role-based naming, procedural builders, an authoring guide resource, intermediate-node previews, a native 3D preview renderer, regression comparison helpers, and diagnostic swatches. It already forwards native exporter target profiles; multi-target support is not wholly absent. `STATUS.md` distinguishes Godot/Unity verification from Unreal file-level-only verification.

The missing step is to expose these foundations as robust, discoverable, artist-level services rather than replacing them or describing them as nonexistent. The browser currently skips color controls and uses range inputs for other types. Source-checkout installation is the supported path; the cookbook and guide are not packaged as full installed-wheel assets.

## Recommended architecture

1. A versioned material-recipe service owns recipes, parameter schemas, references, families, physical scale, provenance, and build requests.
2. Browser and MCP adapters call the same service. Neither owns its own conflicting copy of the active graph.
3. Native Material Maker workers build and validate editable graphs and bake assets. Batch and live workers implement the same request/result contracts.
4. Optional mesh workers supply curvature, cavity, orientation, exposure, and other geometry-derived inputs. World-generation systems provide explicitly identified spatial fields.
5. Engine adapters package verified outputs and target-specific material settings without promising identical shader capabilities across engines.

Material Maker remains a material backend, not the entire world generator. The existing browser is a display/control interface over native rendering; it is not a browser port of the Material Maker graph evaluator. Keep heavy graph generation and baking off older mobile clients. Support arbitrary browser graph execution only as a separately scoped backend with declared node coverage.

## Improvements with the greatest creative leverage

**Recipe-level authoring.** Promote the cookbook into searchable, versioned generators with meaningful controls such as wetness, age, grain direction, moss coverage, and real-world feature size. Compose reusable material layers through compatible channel/mask interfaces. Preserve native graph edits and source assets.

**Closed-loop evaluation.** Return actual preview images through MCP or resolvable image resources, not only local paths. Add controlled multi-light/shape previews, tiled-plane inspection, parameter sweeps, saved alternatives, visual feedback, and target-specific checks. Existing recipe guidance and debug swatches are useful starting points. Do not equate a render-success flag with aesthetic quality.

**World-context inputs.** Make dampness, orientation, shelter, traffic, erosion, and other agreed scene fields available as inputs to several related materials. Use mesh-derived masks for local wear. Keep visual material properties separate from simulation values such as friction or thermal behavior; provide those as explicit sourced or user-chosen metadata.

**Reliable asset builds.** Pin recipe and tool versions; record seeds, target settings, color conventions, and dimensions. Cache by complete build inputs and validated outputs. Distinguish semantic reproducibility from bit-identical rendering across devices. Include the editable source, source references, previews, engine packaging, and build report.

**Artist-facing controls.** Implement proper color/gradient editors, enum selectors, integer controls, lockable parameters, reset/undo, reference boards, before/after comparison, favorites, variant contact sheets, physical-scale controls, and touch input. Ship a repeatable installer and clean-machine tests rather than treating a unit-only test run as rendered integration evidence.

## Suggested order

First fix state/export identity, preview correctness, nested live addressing, render validation, transactions, and permissions. Next expose recipe search, typed semantic controls, variation/preview workflows, and persistent user libraries. Then add mesh/world inputs and engine-specific production packages. Broad arbitrary graph invention or autonomous world creation should follow these foundations rather than precede them.

## Evidence bundle

- `review_probes.py` contains the seven isolated reproduction probes.
- `probe-results.json` records their observed behavior.
- `selected-upstream-tests.txt` preserves the selected test run, including failures.
- `source-manifest.json` identifies the uploaded archive and relevant source-file hashes.

The probes require an extracted copy of the uploaded repository and its `python-dotenv` dependency. Run the script with `--repo` pointing to that extracted root. That path is specific to the local installation and must be supplied explicitly. The bundle contains review evidence, not patched application code.
