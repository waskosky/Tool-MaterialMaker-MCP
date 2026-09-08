# Change map and regression traceability

The review's observations are input hypotheses; the tests below establish the
specific corrected behavior. Native source inspection is not counted as runtime evidence.

| Finding or objective | Implementation | Regression evidence |
| --- | --- | --- |
| Export dropped slider edits and included unrelated images. | `BuildStore` records exact source and settings; `zip_build` packages only a verified inventory. Browser exports a completed build ID. | `test_builds.py`, `test_http.py`, `test_browser.py`. The browser test changes a control to 13 and checks the exported graph. |
| Live controls lost nested paths. | Hierarchical resolution and linked-widget fan-out in `play/sliders.py`; live replacement uses the complete prepared graph instead of top-level name guesses. | Nested controls/fan-out tests in `test_contracts.py`; native path remains acceptance-gated. |
| Live rendering ignored requested resolution. | Explicit pixel resolution forwarded to native `export_material`; client checks image dimensions. | Build dimension tests; upstream signature inspection; real live export still unverified. |
| Nonzero process exit or junk PNG counted as success. | `render.py` and `preview.py` require successful exit, private output staging and image decoding. | `test_builds.py` and `test_additional.py` include failed exits, corrupt images and preservation of old preview files. |
| Weak types, cycles, duplicate nodes/connections and malformed ports. | Bounded strict/import validator, enum integrality, gradients, generic-size bounds and errors-as-data. | `test_contracts.py`, `test_additional.py`, retained `test_validator.py`. |
| Partial edits survived a failed batch. | SQLite atomic patches; a full copy is validated and authorized before publication. Native candidate loading, revision recheck and recovery are separate. | Transaction failure, authorization, dry run, retry and concurrency tests in `test_contracts.py`; native rollback checklist in TESTING. |
| Browser state could overwrite another client. | Expected revision on patches and builds; stale previews invalidate download controls. | Real HTTP conflicts plus Chromium UI conflict test. |
| Preview ignored metallic/occlusion and retained stale textures. | Correct ORM channels, color/data encoding, new material per build, disposal, second UV set, explicit height mode. | Code checks and primary-source review; WebGL rendering NOT certified in this run. |
| Local native bridge was unauthenticated. | Private discovery record, protocol token, loopback restriction, payload and peer limits. | Python client protocol/privacy tests; real native handshake still required. |
| Paths and destructive writes were too broad. | Safe defaults, graph input policy, managed-path restriction for legacy save, overwrite opt-in, native-write gate. | Path, inline-code policy, HTTP and safe-default tests. Native/OS sandbox is not claimed. |
| Recipe library was not a high-level service. | Search, descriptions, semantic aliases, typed controls, personal recipes, explicit ranges and locks. | Recipe, alias, metadata publication and family tests. |
| Material layers/world relationships were disconnected. | Two-layer native graphs, explicit context-to-control bindings, bounded OBJ masks. | Composition/context tests and actual CPU-generated PNG mask tests. Native composition render not certified. |
| Every preview repeated unrelated work. | Source-bound caching, local jobs, cancellation, queued results and content inventories. | Cache hit/corruption, lifecycle, cancellation and exact-source tests. |
| Bare file paths did not deliver assistant-visible images. | `material_preview_image` emits the official SDK's image helper with bounded PNG data. | Helper design checked against official SDK source; real SDK registration is an explicit skipped gate here. |
| Setup omitted assets from installed distributions. | Synchronized cookbook, guide and add-on package data; local wheel builder. | `test_distribution.py`, resource hash checks and wheel inspection. |
| Integer seed risked using the legacy floating seed field. | Build and patch use Material Maker's `seed_int`, not raw `seed`. | Explicit serialization regression; native visual seed effect remains an acceptance check. |

## Changes not equivalent to completed validation

The native bridge is substantially revised code but remains experimental. Target
packages contain concrete transformed maps and manifests, not certified engine
imports. The viewer implementation is corrected but was not shaded by a working
WebGL renderer here. These boundaries are deliberately visible in capabilities,
manifests, tests and documentation.
