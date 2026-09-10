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

## Still requiring native or host acceptance

Godot 4.7.1 and 4.7.2 startup on the local Intel Mac/AMD GPU failed Vulkan compute
compilation. Successful native bake, cache/export, exported `.ptex` reopening and
native material appearance remain unverified for this milestone. The source checkout
was kept pristine. See [native evidence](evidence/workshop-native-local.json).

The authenticated native add-on, candidate replacement, recovery and bridge history
still need editor acceptance. Native writes remain disabled by default. Intended
assistant hosts need end-to-end tool and image-response checks, and target packages
need actual engine import. A working browser WebGL canvas does not establish these.

## Next practical work

1. Complete the small native bake/cache/export/reopen cycle on a graphics setup that
   can initialize the pinned Material Maker source. Validate representative opaque
   materials before expanding recipe and resolution coverage.
2. Import those real exports into the engine we intend to use, checking normal
   direction, channel packing, color handling, physical size and editable source.
3. Exercise a real assistant host against the same Workshop workspace, including
   preview images, edits, cancellation and recovery. Validate native editor writes
   separately in a disposable project before enabling them for normal use.
4. After regular material use produces evidence, prioritize library organization,
   build retention and targeted workflow improvements from that experience.

Development continues on `integration/next`; upstream contributions are paused until
maintainer activity. No separate game or engine repository is changed by this milestone.

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
