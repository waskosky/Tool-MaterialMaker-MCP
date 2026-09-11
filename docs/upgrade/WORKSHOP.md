# Make a material in Workshop

Open **Play.command** on macOS or **play.bat** on Windows. On Linux, run
`python3 scripts/launch.py`. If rendering is not connected, follow
[Setup & repair](SETUP.md). Launching again opens the same running workspace.

## Choose and edit

Search the recipe library, choose a category, or mark favorites with the star.
Cards show readable names and descriptions from the recipe guides. A **Last build**
image comes from a completed material associated with that recipe; it can reflect
your edited controls. Recipes without a completed image say **Preview after first
build**. Browsing does not queue the whole library for rendering.

Opening a recipe creates an editable project and starts a small preview when the
renderer is configured. If the native source catalog is missing, Workshop opens
setup first and remembers your selected recipe. Adjust numbers, sliders, colors
or gradient stops. Changes are saved to the shared workspace and trigger another preview. The initial preview
uses 256 pixels, or the configured resolution limit if it is smaller.

Drag to orbit, scroll to zoom, and try different shapes, lighting or tile repetition.
Expand **Texture channels** to inspect the source images. Use **Height as bump** to
inspect available height data in place of the normal map.

**Your projects** reopens saved projects. **Undo**, **Redo** and **Reset** let you
explore without losing the editable source. **Reload** reads changes made by an
assistant or another browser. A revision conflict reloads shared state and asks you
to review it before retrying your edit.

## Explore variations

1. Expand **Choose what varies**. Enable numeric controls and enter minimum and
   maximum values. A control locked in the editor stays fixed.
2. Choose 2–12 variants and a seed. The seed repeats the parameter sampling;
   unrelated graph seeds stay unchanged unless explicitly varied.
3. Choose resolution, package and physical tile size, then **Build variations**.
   Cards show actual job states as the local queue works through the family.
4. Click a completed image to inspect its albedo and values. **Use variant** opens
   those exact controls in a new editable project and selects the completed preview
   when its graph matches. The captured export settings come with it.
5. **Pin** any completed variants or the current preview, then **Compare pins** to
   see their albedo images together. Comparison is a visual aid, not an automatic
   quality score or a test of engine lighting.

**Cancel pending** stops unfinished family work. **Retry** on a failed or cancelled
card uses that candidate's captured values. Switching projects or replacing a family
cancels its unfinished jobs; late responses cannot select an older result.

## Keep versions and export

Under **Saved versions**, name and save a snapshot before exploring a different
direction. **Restore** creates a new project revision from the chosen snapshot and
updates its preview. Snapshot names are immutable; use a new name for a new version.

Under **Keep as a personal recipe**, give the current material a readable name.
It appears under **Personal recipes** and remains editable. Its library preview can
reuse a verified completed build with matching source and recipe origin.

Choose the package and tile size before building. **Download material** becomes
available when the current preview is complete. It downloads that exact build's
textures, editable `material.ptex`, input record and import notes. Further edits
disable the download until the new preview completes. Use **Retry build** if a build
fails, or **Setup & repair** to correct native paths and test the renderer.

## Continue in Foundry

When the operator configures the Shadermaker companion, **Foundry** appears beside
**Setup & repair**. Finish and select a preview, then use **Send to Foundry** to
open that exact completed build. The link carries its immutable build ID as
`?workshop_build=BUILD_ID` and the shared credential only in the URL fragment.
Changing controls or build settings hides this action until the new preview
completes. Choosing a completed variation sends that selected candidate's build.

Workshop keeps ownership of editable source, gradients, producer controls and the
native render queue. Foundry owns game recipes, scene/runtime controls and their
exports. Foundry's **Edit source** link returns to Workshop with `?project=ID`,
which opens the existing saved project after setup and library initialization.
Late initial reads cannot replace a material you have selected in the meantime.
The hosted configuration caps previews and variations at 1024 pixels; choose the
generic or Godot package for the Foundry handoff. [Hosted setup](SETUP.md#hosted-shadermaker-companion)
describes the explicit origin, paths and shared credential. Without that
configuration, the standalone editing and export workflow remains available.

The browser previews baseline opaque material channels. Review the downloaded maps
and import notes in your intended engine. Native editor writes remain disabled by
default. The current native and browser acceptance limits are in
[TESTING.md](TESTING.md).

[View the recipe library](evidence/workshop-cookbook.png). The separate
[desktop](evidence/workshop-desktop-test.png) and
[mobile viewport](evidence/workshop-mobile-test.png) workflow captures use labelled
synthetic test images; see their [verification record](evidence/workshop-browser-local.json).
