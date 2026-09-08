# Verification and acceptance

## Executed release gate

The numbers below describe the supplied archive's run. See
[INTEGRATION.md](INTEGRATION.md) for subsequent local fixes and verification.

Run from the repository root with the project's Python environment:

```bash
python scripts/check_release.py -rs
```

The implementation run used Python 3.13 on Linux and produced **218 passed, 3 skipped**.
The skipped checks were real MCP SDK registration (dependency unavailable), opt-in
native rendering (Godot/Material Maker unavailable), and a retained Windows-only
path case-folding test. Exact logs and the XML report are in `evidence/`.

The gate checks synchronized package resources, all `tests/upgrade` modules, and
these retained modules: validator, paths, graph, inspect, naming, author helpers,
rename helpers, render comparisons, idle handling, cookbook discovery, and README
counts. The README count checks now use SDK registration and the current tool
reference; obsolete 0.7 transport contracts remain outside this gate.

The new tests exercise strict JSON/graph checks, transaction rollback, persistent
history, revisions and retries, cross-client conflicts, recipe controls and aliases,
world bindings, constrained composition, real CPU mask images, valid/corrupt PNGs,
exact exported graphs, missing channels, wrong dimensions, target packing, cache
corruption, jobs, cancellation, preview publication, native-client authentication,
HTTP authentication and browser logic. The native responses in client tests are mocks.

## Browser evidence and its boundary

Chromium executed the actual frontend JavaScript and DOM with the actual Python
service reached through an in-process test adapter. The test modifies a control,
waits for a synthetic PNG build, downloads a ZIP and checks its graph. It also
simulates a second client edit and verifies stale browser rejection.

This environment's browser networking policy blocked loopback navigation with
`ERR_BLOCKED_BY_ADMINISTRATOR`; that policy was not disabled. The real HTTP adapter
was tested separately using local socket requests. Chromium did not provide a working
WebGL context here, so the graceful image fallback was exercised. Do not describe
this result as a successful three-dimensional render or browser-network certification.

`MM_REQUIRE_WEBGL_TEST=1` makes the browser test require a WebGL canvas. It still does
not assess normal direction or visual correctness. For full local acceptance, use
the real launch URL and confirm a reflective metal material, a rough dielectric,
normal orientation, occlusion, color handling, tile repetition, geometry switching,
height preview and disposal while repeatedly changing materials. Check a supported
mobile device as well as desktop browsers.

## Real SDK gate

After installing the declared MCP dependency, run:

```bash
python -m pytest tests/upgrade/test_optional_integration.py -m sdk -q
```

That test imports the real server and checks registered tool discovery. Also connect
an actual host, call capabilities, read a recipe, edit a workspace graph, queue a build,
and inspect `material_preview_image` as image content. Test tool failures and image
responses with your host. SDK registration alone is not full wire-protocol acceptance.
The real SDK was not installed or run in this implementation environment.

## Native batch smoke

With real native paths configured, run:

```bash
python scripts/native_smoke.py
```

The script has no synthetic renderer fallback. It creates a fresh workspace under
output, instantiates a cookbook recipe, bakes real maps, verifies a cache hit and
exact export, then creates an explicit-seed build. It writes `acceptance.json` and
a verified archive. It does not touch an artist tab. A successful result is batch
acceptance for that configuration, not global engine or visual-quality certification.

Test additional recipe categories, resolutions and target packages. Reopen exported
`.ptex` source in Material Maker and compare against the approved maps. Test missing
graphics devices, process crashes, cancelled large graphs, corrupt source assets,
insufficient disk space and file permissions. Confirm driver/process cleanup.

## Native editor acceptance before enabling writes

Use a disposable Material Maker project and a backup. Establish a read-only authenticated
session first. Inspect capability/version/revision data. Enable the experimental-write
configuration only for this session, restart its overlay, and perform the following:

1. Save a recovery snapshot and apply a small parameter change. Confirm exact native
   state and visible output, then bridge undo and redo. Global native undo is not claimed.
2. Send a patch with a valid first operation and an invalid later operation. Verify
   that both serialized state and visible output remain unchanged and recovery is available.
3. Repeat an exact committed request key and verify no second mutation occurs. Reuse
   that key with different data and verify rejection.
4. Modify the native graph manually between inspection and mutation. Confirm a stale
   revision is rejected. Change active tabs during a delayed operation and verify it
   cannot mutate the wrong graph.
5. Exercise nested controls and fan-out, replacement, renderer failure, native export
   metadata, cancellation/timeout and disconnect/reconnect. Confirm retained recovery
   files reopen correctly. In particular, inspect whether native export metadata changes
   the serialized revision and requires a compatibility adjustment.

Run these against the actual pinned checkout and supported Godot binary. GDScript
parser compatibility, engine object lifetime and native rendering were not executed
here. Capability gating prevents an untested bridge from advertising global undo or
safe production artist-session mutation.

## Engine acceptance

Import a known metal, dielectric, normal-test surface and transparent/emissive case
into each intended engine. Validate channel packing, color/data flags, normal direction,
relative paths, scale and texture budgets. The generated Godot resource wires baseline
opaque channels only; other material features need explicit downstream configuration.
Roblox uploads, Unity pipeline material files and Unreal binary assets are not generated.

## Historical suite and CI

`python -m pytest tests` explicitly requests all historical tests too. Its full
collection during development included 963 collected cases and six import errors
from the absent MCP dependency before later additions. That is a historical diagnostic,
not the final test count or a passing full-suite claim. Some old tests specify the
removed protocol/export/path behavior. Keep them as migration evidence and port useful
requirements into the current gate; do not confuse assertion changes with native proof.

The CI workflow now invokes `scripts/check_release.py` on Linux, Windows and macOS, installs
the actual SDK dependency, and runs separate browser logic and wheel-build jobs. It no longer creates
a fake Godot executable and counts its existence as native validation. The CI workflow
itself has not been executed on the external GitHub runners during this delivery.
