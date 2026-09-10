# Start Material Workshop

From a source checkout, open **Play.command** on macOS or **play.bat** on Windows.
On Linux, run `python3 scripts/launch.py` from the repository. The launcher prepares
the local Python environment when needed and opens the browser. Launching again
reopens the same running workspace. Keep its terminal open while using Workshop;
Ctrl+C stops the server.

Python 3.10 or newer must be installed. Native rendering also needs Godot and the
Material Maker source. Browser setup can open before those native tools are ready.
Development and browser-test dependencies are optional for normal use.

## Connect the native tools

1. Open **Setup & repair**, then **Find tools & check setup**. Choose your detected
   installations, or paste their paths.
2. For Godot, select its executable or the macOS application. Use the standard
   [Godot 4.7 download](https://godotengine.org/download/archive/4.7.2-stable/).
3. For Material Maker, select the extracted source folder containing `project.godot`
   and `addons/material_maker/nodes`. The compatible
   [source archive](https://github.com/RodZill4/material-maker/archive/ad19fcf0ee34a7caf74df709dc4de7112f0d467d.zip)
   uses the revision against which the cookbook was authored. A packaged Material
   Maker application alone does not provide this source checkout.
4. Save setup, then run **Test a small render**. Its progress and cancellation stay
   in the setup panel. **Rendering verified** means a native build completed in this
   server session. Finding the executable and source folder does not establish that
   the graphics driver can render them.

The native renderer uses a desktop graphics context. Do not add Godot's `--headless`
flag when baking materials. Finish or cancel render jobs before saving setup
changes. Existing projects and snapshots remain in the same workspace.

## Saved settings and repair

The setup panel shows the settings file and any overrides. Resolution order is
environment variables, the current `.env` file, saved native defaults, then built-in
defaults. Paths controlled by an override are identified in the panel. Change them
in the launcher that supplied them, or repair a source checkout's `.env` paths with:

```bash
.venv/bin/python scripts/configure.py
```

On Windows, use `.venv\Scripts\python.exe scripts\configure.py`. The configuration
program preserves unrelated settings. `--offline` remains available for a checkout
whose native installation will be configured later.

If the saved defaults file is unreadable, Workshop shows a repair notice and keeps
explicit environment and `.env` overrides. Saving valid paths in the setup panel
replaces that defaults file; opening Workshop alone does not rewrite it.

Source launchers use this repository's workspace. If launching an installed
`mm-play` directly, use the same working folder each time or set `MM_WORKSPACE_DIR`
to a fixed directory. Give an assistant host the same workspace and native settings
to share projects with the browser. Restart a separately running assistant server
after changing its native configuration.

If the browser was opened without its authenticated launch link, run the launcher
again. It verifies the existing local session and opens the complete link. If an
unrelated program occupies the configured port, set `MM_PLAY_PORT` to another port
or stop that program. The launcher does not take over an unrelated listener.

For a terminal-managed service that should not open a browser, use `mm-play --no-open`.
The terminal prints its private launch link; keep that link local.

## Manual installation

If you prefer to manage the Python environment yourself, use the runtime dependency
set rather than the development extras:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m mm_mcp.play.server
```

On Windows, use `python -m venv .venv`, then the executable under
`.venv\Scripts\python.exe` for the install and launch commands. A virtualenv created
without pip can be repaired with its Python's `-m ensurepip` command.

The developer checks and native acceptance limits are documented in
[TESTING.md](TESTING.md). Current local graphics findings are recorded in
[the runtime evidence](evidence/workshop-native-local.json).
