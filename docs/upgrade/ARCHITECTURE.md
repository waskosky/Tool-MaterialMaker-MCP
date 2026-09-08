# Architecture

## One state model, two user interfaces

`MaterialService` is the application boundary used by `tools.py` and the local
browser handler. It does not require the MCP dependency for its core data and
rendering contracts. The browser is not a separate source of material truth.

A project is an editable graph with a persistent identifier and monotonically
increasing revision. A build is an immutable evaluation of one exact graph and
its complete recorded request. Changing a project never changes a prior build.
Native artist tabs form a third, explicitly separate state domain: attaching to
Material Maker does not silently make the browser's workspace project an editor tab.

## Project transactions

`GraphStore` uses SQLite write transactions with a full candidate copy. Operations
are applied to that copy, validated and authorized, then committed with history
and an idempotency receipt. A revision conflict, bad operation or policy failure
leaves the stored graph unchanged. Dry runs do not commit. Exact retries return
the earlier result; the same key with different intent is rejected.

Undo and redo create new revisions. History branching retains a defined cursor,
and named snapshots are immutable. This is workspace history, not Godot's global
editor undo manager. Stable nested paths address nodes; structural renames or edits
require reinspection rather than an assumption that stale paths remain meaningful.

## Builds and publication

The build key includes the graph, values, seed, resolution, target, declared
physical size, dependency hashes, recipe/project provenance, implementation hash,
Material Maker resources, executable hash, platform and optional render-device tag.
Hashing native resources is deliberately conservative and may cost time on large
checkouts. It is not a guarantee of bit-identical graphics output across devices.

The renderer writes into a private staging directory. A successful process exit is
necessary but insufficient. PNG decoding, dimensions and required connected-channel
checks must also succeed. Unconnected baseline channels may receive explicit
constant defaults; a missing connected channel is never repaired this way. A
constant-only graph that produces no native images is not silently declared a
successful native bake by the canonical path.

The service writes `material.ptex`, `request.json`, `target.json`, `quality.json`,
import notes and the exact artifact inventory. Dependencies and tool fingerprints
are rechecked before publication. Only then is the staging directory atomically
renamed to its immutable build directory. Failed and cancelled work is not published
as a successful build. A forced rerender receives a distinct identifier.

A cached build is reverified, including file hashes and source-contract inventory.
Exports are deterministic ZIP files of that inventory, not a directory glob. Hash
verification detects modification; it is not a cryptographic signature from an
external authority. External input textures are recorded by hash and reference,
not automatically copied or relicensed into the ZIP.

## Jobs and concurrency

SQLite stores queued, running, complete, failed and cancelled jobs. An operating-system
worker lock prevents cooperating processes from running the same queue simultaneously.
A prior running row encountered after obtaining the worker lock is marked interrupted
rather than reported complete. Capacity is bounded; cancellation is cooperative and
terminates only worker-owned subprocesses. An artist-attached process is not a job
cancellation target.

A build lock protects each workspace's publication path; operating-system locks
release when their owning process exits. Rendering across different workspaces or
independently launched native editors is not a distributed scheduler. Run one native
worker configuration per operator-controlled rendering context until acceptance
establishes a broader deployment model. Retention/quotas beyond pending-job limits
remain operator-managed; database history and completed builds are not auto-pruned.

## Recipe and control contracts

Recipes retain native graphs. Remote controls resolve through nested subgraphs to
all linked widgets, with explicit kinds for numbers, integers, enums, booleans,
colors and gradients. Human-facing semantic aliases map to real control IDs; they
are labels and explicit metadata, not guessed universal material semantics.

Variation families change only requested ranges and unlocked controls. Their random
sampling seed is distinct from a material's native seed. Environmental bindings
map authored normalized fields to named control ranges; they do not infer physical
properties. Composition requires compatible catalog interfaces and equal output
scalar parameters, preserves both editable layers, and selects normals explicitly
rather than applying an invalid color blend to vectors.

The OBJ backend is intentionally independent: it emits coverage, normalized height
and upward-facing masks from triangles with supplied texture coordinates. Those
files can be supplied to approved image nodes through explicit paths. It does not
unfold UVs, repair topology, compute ambient occlusion, infer curvature or paint a model.

## Adapter and native boundaries

The browser handler performs session authentication and request/response translation.
The MCP adapter offers 24 high-level functions plus the retained authoring surface.
Capabilities distinguish configured native paths from demonstrated native execution.

The native bridge authenticates requests, captures the serialized editor revision,
loads a candidate before replacement, rechecks for intervening edits, and preserves
recovery data. Its own undo history is separate from global native undo. Since the
native implementation was not run against Material Maker in this environment,
write capability requires `MM_ENABLE_EXPERIMENTAL_LIVE_WRITES=1` and explicit local
acceptance. That flag is not evidence that acceptance has passed.
