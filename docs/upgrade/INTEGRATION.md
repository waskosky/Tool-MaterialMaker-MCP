# Local integration — 2026-09-08

The supplied 0.8.0a1 update is integrated into the repository on
`integration/next` (renamed from `integrate/0.8.0a1-updates`). The checkout started clean at
`b41b65c612557a7da35a045091199058c0f76abb`, matching the archive's documented baseline.
The user requested publishing this integration branch to `origin` and continuing
development there. Local and origin `main` are reserved for focused upstream pull
requests. No release or deployment is part of this integration.

`origin` is `waskosky/Tool-MaterialMaker-MCP`; the `upstream` remote points to
`graysonchalmers/Tool-MaterialMaker-MCP`. Both main branches matched the baseline
above when this branch was prepared. See [UPSTREAM.md](UPSTREAM.md) for the
recommended contribution order.

## Source and scope

- Input: `Tool-MaterialMaker-MCP-0.8.0a1-updated.zip` from the user-provided URL.
- Archive SHA-256: `c13d17e2597fa4ca1a461f02030dffeb7e010bb1bbd0865e7dc19b4f8750ca54`.
- Extracted source:
  `/Users/macuser/games/temp/materialmaker-0.8.0a1-updated-ccitfv89/Tool-MaterialMaker-MCP-0.8.0a1`.
- Imported all 22 changed files and 162 additions. No existing repository file
  was removed. The original cookbook and quality builders are unchanged.
- The original [delivery manifest](DELIVERY_FILE_MANIFEST.json) describes the
  supplied archive before the fixes below. Its checksums are not a manifest of
  the resulting working tree. Original execution logs remain in `evidence/`.

The imported service provides shared project revisions, atomic patches, undo/redo,
snapshots, recipes, verified immutable builds, target packages, local jobs,
composition, mesh masks and authenticated browser/native adapters. Native mutation
and new custom code remain disabled by default.

## Fixes made during integration

- Apply and validate raw-graph control overrides before rendering, so exported
  source agrees with requested controls and recorded build settings.
- Preserve approved cookbook code when saving and reopening personal recipes.
  Approval lives in service-owned provenance, separate from caller metadata.
- Include custom script and custom export script fields in code approval checks;
  inheriting a cookbook's shader approval cannot authorize newly added scripts.
- Resume persisted jobs through common service initialization, including MCP-only
  startup with an already-full queue.
- Ignore obsolete browser job responses after switching projects or starting a
  newer build; keep selection and cancellation attached to the current request.
- Use `pyproject.toml` as the dependency source, document new configuration in
  `.env.example`, open the authenticated URL from `play.bat`, and build wheels
  through the declared isolated PEP 517 backend. Package the cookbook README too.
- Restore documentation count checks against actual SDK tool registration. Extend
  the portable CI matrix to macOS and add a wheel metadata check. Update the
  handoff, changelog and host-environment guidance for the current source.

Two bounded code reviews checked the service and interfaces. Their concrete
findings were reproduced before fixes and checked again afterward.

## Local verification

Environment: macOS, Python 3.12.13, MCP SDK 2.2.0. The repository `.venv` contains
the editable project and its development/release dependencies.

| Check | Result |
| --- | --- |
| `.venv/bin/python scripts/check_release.py -m "not browser and not native" -rs` | 232 passed, 1 skipped, 2 deselected; 15.85 seconds. |
| Skip | Windows-only path case-folding on macOS. |
| Deselected | Chromium browser suite and opt-in native acceptance. |
| Package resource synchronization | All 109 source/package resource pairs match. |
| Python source parsing and `node --check src/mm_mcp/play/static/app.js` | Passed. |
| `.venv/bin/python scripts/build_distribution.py` | Built `dist/mm_mcp-0.8.0a1-py3-none-any.whl`. |
| `.venv/bin/python -m twine check dist/mm_mcp-0.8.0a1-py3-none-any.whl` | Passed. |
| Wheel installed with dependencies in a separate temporary virtualenv | Outside the source tree, found 53 cookbook recipes, the packaged guide/add-on, and all 42 registered SDK tools. |

The portable gate includes nine new focused regression cases for the fixes above,
including three Node-based request-order checks without browser or GPU startup.
Logs and JUnit output are under the extraction's parent directory as
`integration-contracts.log`, `integration-contracts.xml`, and `integration-wheel.log`.

The archive's earlier 218-pass Linux report is historical evidence. It does not
describe this checkout's checks. Native rendering, GDScript execution, WebGL
shading, engine imports, the historical full suite, and external GitHub CI were
not run during this integration. Those acceptance steps remain in
[TESTING.md](TESTING.md). The published-release manifest remains at 0.7.0 because
this alpha has not been released.

## Upstream contributions after integration

The user then authorized the first two proposed upstream fixes. These were ported
onto the original 0.7 baseline in separate worktrees and published as
[#7](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/7) from `main`
and [#8](https://github.com/graysonchalmers/Tool-MaterialMaker-MCP/pull/8) from
`fix/render-publication`. The root checkout stays on `integration/next`.

The export patch passed 34 focused local checks and the fork's Windows CI
(1,002 passed, 25 deselected). The render patch passed 47 focused local checks,
including regressions for compatibility findings from pinned native source.
Both received independent review. These results concern the small upstream
patches, not a new native certification of this alpha. PR links, branch heads,
remaining alpha renderer follow-ups and workflow state are in [UPSTREAM.md](UPSTREAM.md).

## Workshop usability milestone — 2026-09-10

Following the user's approval of the [usability plan](../superpowers/plans/2026-09-09-workshop-usability.md),
work continues on `integration/next`. Further upstream work is paused until maintainer
activity. `main` and the existing contribution worktrees remain separate; this
milestone does not publish a release or modify other game/engine repositories.

The renderer now isolates each native retry's output and resolves recognized
`%PROJECT_PATH%` image references from an explicit, approved source origin. A private
render copy receives resolved paths; published source remains the original editable
graph. Successful publication still requires valid complete images.

Workshop gains saved native defaults, environment/`.env` precedence, bounded tool
discovery, in-place idle setup repair, cancellable native verification, and authenticated
launcher session reuse. Source launchers install runtime dependencies only as needed;
configuration repair preserves unrelated `.env` content and Unicode paths. Unknown
listeners never receive the existing session token.

The visual library uses readable guide metadata and authenticated previews from
verified completed builds, with bounded indexing and image caching. Browsing queues
no renders. Missing-catalog first use opens setup and resumes the selected recipe.
Typed controls, ranges, locks and seeds lead to visible candidate jobs, inspection,
exact editable selection, pin comparison, personal recipes, and named version restore.
Candidate family admission is atomic. Selected candidate previews can be reused
without rebaking when source and origin match. Serialized edit/history handling and
request epochs keep downloads, controls and previews aligned during late responses.

The initial source integration's cookbook graphs/builders are unchanged: 53 recipes,
12 categories, 24 shared tools, 10 batch tools and 8 live tools. Independent spec and
quality reviews covered renderer, setup and visual implementation; concrete findings
were reproduced before fixes and rechecked. [SETUP](SETUP.md) and [WORKSHOP](WORKSHOP.md)
are now the user entry points, and the existing CI workflow also runs on this branch.

### Current local verification

| Check | Result |
| --- | --- |
| Portable release gate | 377 passed, 1 Windows-only skip, 4 deselected; 35.02 seconds. |
| Resource synchronization | All 109 source/package resource files match. |
| Frontend request ordering | 21 focused Node cases pass, including Undo/Restore during both mutation and refresh requests. |
| Actual HTTP/CSP Chromium workflow | 3 passed in 59.31 seconds; WebGL required, explicitly synthetic maps. |
| Responsive/library inspection | Desktop and 390-pixel mobile viewport captured; real 53-recipe library and pinned 392-node catalog browsed without native jobs. |
| JavaScript syntax | `app.js`, `setup.js`, `library.js`, `variations.js` pass `node --check`. |
| Wheel build and metadata | `mm_mcp-0.8.0a1-py3-none-any.whl` built; `twine check` passes. |
| Isolated wheel installation | Outside the source checkout, finds 53 recipes, 12 categories, all new browser modules, guide/add-on/preview resources and 42 actual SDK tools. |
| Source launch and reuse | Two real launcher invocations use one authenticated workspace session; clean exit and discovery cleanup. |
| Real native worker cancellation | Owned Godot export process observed and cancelled; no child process or completed build left. |

The [machine-readable verification record](evidence/workshop-verification-local.json)
links the browser, installed-wheel, launcher and native evidence. Portable logs are
in `.acceptance/workshop-2026-09-10/`. These current results supersede the earlier
232-pass local count; the supplied archive's 218-pass record remains historical.

### Native boundary

Official Godot 4.7.1 and 4.7.2 against pristine Material Maker
`ad19fcf0ee34a7caf74df709dc4de7112f0d467d` failed Vulkan compute compilation on the
local Intel Mac/AMD Radeon Pro 460. No native bake completed. Real worker cancellation
passed, but native material appearance, successful bake/cache/export, exported graph
reopening and target-engine imports remain unverified. Browser test maps are labelled
`injected_test_double` and cannot mark setup as native verified. Complete those
acceptance steps on a compatible graphics setup using [TESTING](TESTING.md).
