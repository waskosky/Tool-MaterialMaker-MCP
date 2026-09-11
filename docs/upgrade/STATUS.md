# Capability status and remaining work

## Implemented and exercised

Workshop now provides runtime-only source launchers, private authenticated session
reuse, saved native paths, discovery and repair, and a cancellable setup test. Setup
can open before a catalog is available and resumes the first selected recipe after
configuration. Environment and `.env` overrides remain visible and take precedence.

The responsive library has friendly names, guide descriptions, search, categories,
favorites and authenticated thumbnails from completed builds. Projects expose typed
controls and automatic small previews. Variation ranges, locks and seeds produce
bounded candidate jobs; users can inspect, select exact editable values, pin and
compare, save personal recipes, and list/restore named versions. History and edits
are serialized before previews, and obsolete requests cannot select old results.

Shared project transactions, persistent undo/redo, revision conflicts, exact retry
semantics, immutable build/export contracts, type-aware controls, world bindings,
constrained composition, bounded CPU triangle masks, target-map transforms, jobs,
path policy and synchronized package resources have portable regression coverage.
The actual SDK registers all documented tools.

Real Chromium exercised the HTTP/authentication/CSP path and a WebGL canvas with
explicitly synthetic maps, including a mobile viewport. The actual 53-recipe library
was browsed without rendering. Native worker cancellation was exercised against a
real Godot process. [TESTING.md](TESTING.md) and [INTEGRATION.md](INTEGRATION.md) provide
the current evidence and commands.

## Native and companion acceptance

The reviewed Godot 4.7 profile with Metal argument buffers disabled now bakes the
128-pixel sand recipe on this Intel Mac/AMD GPU. Native PNGs, cache identity,
explicit seeds and verified archives pass. Its exported source reopens in an
isolated Material Maker editor; the linked Foundry package imports and captures
LOW/HIGH views in native Godot. Browser source updates retain independent scene,
runtime and image edits, while stale revisions fail. Actual MCP SDK clients share
the same queue/workspace and receive PNG image content. See
[companion evidence](evidence/workshop-companion-native.json).

The [published live record](evidence/workshop-companion-live.json) adds native
256-pixel sand baking and cache reuse, exact Send to Foundry and Edit source
browser navigation, inspected LOW/HIGH Godot Web references, and TLS authentication checks.
Actual MCP stdio clients share the deployed workspace and serialized queue: one
native process and one running job at a time, with PNG responses from both tools.
Foundry cancellation drains Workshop's worker while preserving the last good
package. Targeted Foundry restart preserves Workshop's active native job, and
service/manager crashes recover without losing packages, projects or the shared
token. Existing Serve routes and peer listeners remain unchanged.

Clean published Workshop `107534a` on `integration/next`, Foundry `92abc89` and
Godot Light `a13407bc` on their `main` branches passed that live acceptance.
Workshop's accepted-code [CI run 34579067693](https://github.com/waskosky/Tool-MaterialMaker-MCP/actions/runs/34579067693)
passed all five jobs. The macOS LaunchAgent is installed and loaded, with login
registration and automatic crash recovery exercised; no actual reboot occurred.
The existing game root returned 502 before and after deployment. These tools run
independently of the stopped game stack and RAI.

Hosted subpaths, explicit origins and shared private tokens are deployed. Adopted
recipe variations obtain a saved-project build before handoff. Imported legacy
fields may remain unchanged during valid edits; this does not admit new unknown
fields or custom code. Native acceptance remains limited to one sand recipe at
128 and 256 pixels. Experimental native editor writes remain disabled.

The earlier Godot 4.7.1/4.7.2 default-profile failures remain in the historical
[native record](evidence/workshop-native-local.json). The upstream source remains
pristine; the working renderer uses an isolated prepared toolchain.

## Next practical work

1. Expand real native and engine checks beyond sand at 128 and 256 pixels.
2. Validate native editor writes, replacement, recovery and bridge history in a
   disposable project before enabling them for artist work.
3. Prioritize library organization and retention after ordinary material use.

Development continues on `integration/next`; upstream contributions remain paused.
Foundry and Godot Light integration stays in their independent repositories.
Version 0.8.0a1 remains a development candidate; no alpha release is being published.

## Deliberately limited contracts

Layer composition requires equal material scalar settings and selects normals;
it does not blend their orientations. OBJ masks provide coverage, height and
upward-facing signals. World context uses explicit bindings, not inferred physical
properties. The browser delegates baking to Material Maker rather than evaluating
its graph in WebGL.

External dependencies are recorded but not fully bundled. Build retention is
operator-managed. The deployment model is one trusted local operator. Screenshots
and channel statistics are not artistic-quality scores. The high-level path verifies
canonical PNG artifacts, not arbitrary upstream export formats.

Reference-guided optimization, semantic ranking, richer layers and mesh painting,
platform compression, game-specific adapters, browser-native graph execution and
multi-user scheduling remain separate work. There has been no controlled native
benchmark against MaterialPilot; its editor integration remains a capability
reference rather than evidence of this package's comparative performance.
