# Engineering decisions

## D01 — Immutable builds instead of shared image folders

The export bug was a state-identity failure, not only a missing slider argument.
Binding source and artifacts to a build ID removes stale-folder ambiguity and makes
approval, caching, download and regression evidence refer to one result. The cost
is extra storage and explicit retention management.

## D02 — SQLite-backed project revisions

A file per mutable graph would not by itself synchronize browser and assistant
processes, history and retry receipts. SQLite gives a local transactional boundary
without introducing a database server. It is not a substitute for remote multi-tenant
access control or a distributed render scheduler.

## D03 — Tolerant import, stricter authored output

Existing native files use legitimate flexibility that must not be mistaken for
malformed generated graphs. Separate modes preserve usable imports while checking
authored topology, types and bounds more strictly. Native semantic evaluation remains
separate from structural validity; strict validation does not guarantee a good material.

## D04 — Semantic recipes above raw node commands

The existing cookbook is a useful reusable knowledge base. Typed controls, descriptions,
explicit aliases, ranges and composition are a more dependable starting point than
asking an assistant to invent every connection. Low-level authoring remains available;
semantic aliases do not pretend that every recipe exposes identical physical concepts.

## D05 — One browser/assistant service, separate native compatibility layer

Shared project/build state prevents UI-specific export and concurrency bugs. The
native editor has its own object lifetime, global undo and tab semantics, so it remains
an explicit backend rather than a hidden implementation detail of every browser action.
Batch work must not hijack the artist's active tab merely to obtain a faster preview.

## D06 — Fail closed on unverified native mutation

Substantial native code was implemented, but this environment lacks the required
engine. A false production-readiness claim would be worse than an explicit experimental
gate. Source-based review and Python protocol mocks cannot certify GDScript parsing,
render-device behavior or native rollback. The gate is therefore off by default.

## D07 — Conservative composition and mask scope

Linear blending of encoded normal colors is not a sound general normal-composition
contract. This version chooses a normal source and constrains other layer interfaces.
Similarly, a small testable OBJ mask backend is preferable to claiming automatic
curvature/occlusion/physics from a partial implementation.

## D08 — Canonical PNG build path with explicit target transforms

A single verified raster contract makes incomplete output detection and source
identity testable. Destination profiles then add concrete packing/normal transforms
and honest import metadata. It sacrifices automatic coverage of every upstream
custom exporter; those need their own validators and acceptance cases.

## D09 — Evidence levels are part of the interface

Synthetic renderer output is labelled in manifests. Configured paths are distinguished
from native verification. Engine import and artistic approval default to false.
Tests and documentation use the same distinctions, so an agent cannot infer that a
successful schema or mock render proves visual or native success.

## D10 — Preserve historical tests without claiming obsolete contracts pass

The 0.7 suite contains valuable fixtures and historical requirements, including
assumptions deliberately removed by this upgrade. The current gate is explicit and
retains compatible unit modules. Historical tests are available for audit rather than
deleted or silently relabelled as passing. The migration cost is visible and documented.
