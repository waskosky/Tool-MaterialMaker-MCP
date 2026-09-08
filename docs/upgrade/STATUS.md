# Capability status and remaining work

## Implemented and exercised in portable tests

Shared project transactions, persistent undo/redo and snapshots; revision conflicts
and exact retry semantics; verified immutable build/export contracts; type-aware
nested controls; recipe search and aliases; seeded range families with locks;
explicit environmental bindings; constrained layer composition; bounded CPU triangle
mask baking; local queue/cancellation; actual PNG validation and target-map transforms;
HTTP authentication/path checks; browser editing/export logic; synchronized package resources.

## Implemented but not fully certified here

The native renderer changes, authenticated Godot add-on, native candidate replacement,
recovery and bridge-specific history require the actual engine. Native writes are
disabled by default. Image-returning MCP tools and real server registration require
the real SDK/client. The corrected three-dimensional browser viewer requires a working
WebGL environment and visual validation. Target packages require actual engine import.
These are substantive implementations, not claimed finished acceptance results.

## Deliberately limited contracts

Layer composition preserves connected channels and requires equal material scalar
settings; it selects normals instead of blending them. OBJ masks provide three
specific geometric signals, not a full mesh-baking suite. World context uses explicit
bindings, not inferred physical material properties. The browser is a native-worker
client, not a Material Maker graph evaluator compiled to WebGL.

External asset references are recorded, not fully bundled. Completed-build retention
is operator-managed. A single trusted local operator is the deployment model. Browser
screenshots and generic channel statistics do not automatically establish artistic
quality. The high-level build path certifies canonical PNG artifacts, not every
custom upstream export profile or image format.

## Recommended next work, not represented as implemented

- Native compatibility certification and carefully integrated global editor undo.
- Image/reference-guided optimization, semantic/perceptual ranking and repeatable
  multi-lighting three-dimensional capture through a tested native renderer.
- Reoriented normal blending, height-aware layers, richer mesh baking and painting.
- Dependency vendoring with explicit licenses, content retention/quotas and platform
  compression/streaming policies.
- Concrete RAI/Godot Light adapters, engine import tests, runtime performance budgets
  and asset-library ingestion. No changes to those separate repositories are included.
- Browser-native graph execution, multi-user/cloud scheduling and calibrated simulation
  materials. These require separate backends and security/physics contracts.

## Comparison goal versus MaterialPilot

The proposed differentiators are an integrated browser recipe workflow, families and
world controls, persistent cross-interface projects, source-bound builds, several
concrete target layouts and bounded geometric-mask inputs. These are meaningful
extensions beyond an editor-command bridge.

There has been no controlled side-by-side native benchmark. Do not advertise this
candidate as universally more reliable, faster, safer, or more visually capable.
MaterialPilot's native-editor integration remains a capability reference, especially
for global undo and demonstrated native behavior. Evaluate both against the same
unfamiliar recipes, nested edits, failure recovery, concurrency, export identity,
actual render quality and human correction effort before choosing a production default.
