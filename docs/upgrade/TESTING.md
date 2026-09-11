# Verification and acceptance

## Current portable checks

Run from the repository root with the project's Python environment:

```bash
python scripts/check_release.py -m 'not browser and not native' -rs
```

The gate checks synchronized package resources, portable `tests/upgrade` contracts,
and retained validator, paths, graph, inspect, naming, authoring, render-comparison,
idle, cookbook and README checks. It uses the actual installed MCP SDK for registered
tool discovery. [INTEGRATION.md](INTEGRATION.md) records the current run and its skips.

The slashless hosted-entry follow-up passes 485 portable tests, with one
Windows-only skip and five browser/native cases deselected; all 109 packaged
resource files match. These checks do not start a browser or native renderer.

Focused regressions cover isolated native retry attempts, source-relative image
references, setup persistence and precedence, idle configuration refresh, authenticated
session reuse, atomic family admission, verified gallery previews, exact candidate
selection, snapshot history and stale browser responses. Native subprocess doubles
and synthetic images remain explicitly identified in tests.

## Browser evidence

The current Chromium suite navigates the actual loopback HTTP server and exercises
authenticated fetches under the production content security policy. It checks setup
save/check/cancellation, missing-catalog first-use recovery, automatic preview,
controls, family ranges and locks, inspect/use/compare, personal recipes, snapshots,
exact downloads and cross-client revision conflicts.

```bash
python -m pip install -e '.[dev,browser]'
python -m playwright install chromium
```

Set `MM_TEST_CHROMIUM` to your installed Chromium executable, then run:

```bash
MM_REQUIRE_WEBGL_TEST=1 python -m pytest tests/upgrade/test_browser.py -q
```

On PowerShell, set `$env:MM_REQUIRE_WEBGL_TEST = '1'` before running Python. Without
Playwright or Chromium the browser tests skip; inspect the result. WebGL-required
runs must create a canvas. The local run used SwiftShader and decoded synthetic PNG
channels, with desktop and 390-pixel mobile viewport checks. It establishes browser
behavior and a working viewer path, not native material appearance or physical-device
acceptance. [Evidence and screenshots](evidence/workshop-browser-local.json) record
these boundaries. The full cookbook was also browsed using its real recipe files
and, separately, the pinned native catalog; neither check started native builds.

For visual acceptance after native baking works, inspect a reflective metal, a rough
dielectric, normal orientation, occlusion, color handling, tiling, shape switching,
height preview and repeated material changes. Check intended desktop browsers and
physical mobile devices. Compare preview appearance with the actual target engine.

### Slashless hosted entry

`tests/upgrade/test_hosting.py` reproduces a prefix-stripping proxy forwarding `/`
while the browser displays `/shadermaker/workshop` without its final slash. Before
the fix, the stylesheet resolved to `/shadermaker/static/style.css`. Hosted HTML
now anchors its initial assets to the configured mount, and startup normalizes
the browser URL before choosing its API base. CPU checks retain root/file paths,
project queries, token handling and history state during normalization.

The real browser regression uses an actual local prefix-stripping HTTP proxy,
the Workshop server and a saved fixture project. It checks applied CSS, protected
API denial, authenticated project selection, correct asset/API routes, query and
fragment handling, and reload after the token is consumed. Its native renderer
is unconfigured; no native or synthetic bake is used as appearance evidence.
Run it only when the shared browser/graphics test slot is available:

```bash
MM_TEST_CHROMIUM=/path/to/chromium python -m pytest tests/upgrade/test_browser_hosting.py -q
```

Set `MM_HOSTED_ENTRY_BROWSER_EVIDENCE` to a private screenshot filename with an
existing parent directory to retain the styled page. This regression does not
change Tailscale routes, public-origin allowlists, token checks or CSP.
The local Chromium run passes one case in 25.85 seconds. Its private screenshot
was inspected: styles are applied and the saved project is selected. This is
candidate browser/routing evidence; publication and live URL checks remain separate.
The existing CI browser job runs this regression alongside `test_browser.py`
and retains `workshop-slashless-entry.png` in its browser evidence artifact.

## Setup and native runtime evidence

The source launcher was exercised twice against an isolated workspace. The second
launch reused its authenticated session, both invocations exited cleanly, and private
discovery state was removed at shutdown. See [launch evidence](evidence/workshop-launch-local.json).
Setup tests distinguish path configuration from successful native rendering.

Native startup was attempted with official Godot 4.7.1 and 4.7.2 against pristine
Material Maker `ad19fcf0ee34a7caf74df709dc4de7112f0d467d`, on macOS 15.7.1 with an Intel
CPU and AMD Radeon Pro 460. Vulkan compute compilation failed before a bake could
complete. A separate real worker cancellation check observed and stopped its owned
Godot process, leaving no completed build or child process. See
[native evidence](evidence/workshop-native-local.json). Successful bake/cache/export,
exported `.ptex` reopening and target-engine imports were unverified in that run.

The September 11 companion run passes with Godot 4.7, an isolated prepared source
copy with the reviewed size-forwarding repair/import cache, and
`MVK_CONFIG_USE_METAL_ARGUMENT_BUFFERS=0`. The upstream checkout remains pristine.
A real 128-pixel sand material passes native bake/cache/seed/verified export, exact
Workshop-to-Foundry navigation, source refresh retaining scene/runtime/image edits,
stale-source denial, actual MCP stdio image responses, editable-source reopening
and native Godot LOW/HIGH import/capture. See the normalized
[companion record](evidence/workshop-companion-native.json); raw captures and logs
remain private. Its `pending_at_recording` entry is historical and links to the
completed live acceptance below.

## Published companion acceptance

The [live companion record](evidence/workshop-companion-live.json) covers clean,
published Workshop `107534a` (`integration/next`), Foundry `92abc89` (`main`) and
Godot Light `a13407bc` (`main`) under the independent companion manager. A real
256-pixel sand build and exact cache reuse supplement the earlier 128-pixel native
checks. Browser Send to Foundry imports the selected immutable build; Edit source
opens the authenticated saved project in its actual popup. Rendered captures and
compiled Godot Web LOW/HIGH references were inspected without script or shader
errors under strict CSP. TLS requests without a token return 401, and unapproved
origins return 403.

Actual MCP SDK 2.2.0 stdio clients use the generated deployed configurations,
register 42 Workshop and 19 Foundry tools, and receive PNG image content. Concurrent
requests produce at most one native process and one running job; Foundry waits
for Workshop's shared queue. Targeted Foundry restart preserves Workshop's process
and active native job. Foundry cancellation reaches Workshop, drains the native
worker and preserves the last good package. Foundry crash recovery removes its
stale lock, and manager crash recovery cleans up owned children. Packages,
projects and the shared token persist; pre-existing Serve routes and peer
listeners are preserved, with private credential files and no managed-log token leak.

The macOS LaunchAgent is installed and loaded. Login registration and automatic
crash recovery were exercised; no actual reboot or pre-login daemon was tested.
The existing game root returned 502 before and after this deployment. The tools
operate independently of the stopped game stack and RAI.

Native scope is one opaque sand recipe at 128 and 256 pixels, without a full recipe
or device matrix. Chromium SwiftShader establishes browser functionality, not
hardware performance; the earlier native Godot captures separately exercise the
Mac graphics driver. Experimental native editor writes and global undo remain
disabled and were not part of this acceptance. Raw logs and captures remain private.

## Real SDK gate

```bash
python -m pytest tests/upgrade/test_optional_integration.py -m sdk -q
```

The actual installed SDK registers all 42 tools; README counts are checked against
that registration. Also connect your intended host, call capabilities, read a recipe,
edit a workspace graph, queue a build and inspect `material_preview_image` as image
content. SDK registration alone is not complete host or wire-protocol acceptance.

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

Beyond the accepted sand at 128 and 256 pixels, test additional recipe categories,
resolutions and target packages. Reopen exported `.ptex` source in Material Maker
and compare against the approved maps. Test missing
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

Run these against the actual pinned checkout and supported Godot binary. The batch/render and source-reopen checks above do not certify editor object lifetime
or editor-write compatibility. Capability gating prevents an untested bridge from advertising global undo or
safe production artist-session mutation.

## Engine acceptance

Import a known metal, dielectric, normal-test surface and transparent/emissive case
into each intended engine. Validate channel packing, color/data flags, normal direction,
relative paths, scale and texture budgets. The generated Godot resource wires baseline
opaque channels only; other material features need explicit downstream configuration.
Roblox uploads, Unity pipeline material files and Unreal binary assets are not generated.

## Historical evidence and CI

The supplied archive's root `evidence/` directory records its earlier Linux run:
218 passed and 3 skips. It used an in-process browser adapter because that environment
blocked loopback navigation, and it lacked WebGL and the real SDK. Those historical
limits do not describe the current local browser/SDK checks above.

`python -m pytest tests` also requests historical 0.7 contracts. Some specify removed
transport/export behavior or machine-dependent native fixtures. The bounded release
gate is the current acceptance command; this milestone does not claim a passing
historical full suite.

The CI workflow runs on `integration/next`, `main`, pull requests and manual dispatch.
It checks portable contracts on Linux, Windows and macOS, builds and checks the wheel,
and runs the real HTTP browser suite with WebGL required and labelled synthetic maps.
Browser screenshots are retained as CI artifacts. Native GPU baking and engine imports
remain separate acceptance work; this workflow does not publish a release.
The accepted Workshop revision `107534a` passed all five jobs in
[CI run 34579303994](https://github.com/waskosky/Tool-MaterialMaker-MCP/actions/runs/34579303994).
Version 0.8.0a1 remains a development candidate; no new alpha release or upstream
work is included in this delivery.
