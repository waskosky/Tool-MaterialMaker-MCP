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
Standalone startup prints its private launch link; keep that link local.

## Hosted Shadermaker companion

An operator-managed reverse proxy can mount Workshop beside Foundry while both
services continue listening on loopback. Configure Workshop explicitly:

```dotenv
MM_PLAY_PORT=8788
MM_BASE_PATH=/shadermaker/workshop/
MM_PUBLIC_ORIGIN=https://w11.tailbcac65.ts.net
MM_FOUNDRY_PATH=/shadermaker/
MM_SESSION_TOKEN_FILE=/private/operator-state/companion.token
MM_MAX_RESOLUTION=1024
```

The supervisor supplies the shared token file before starting either service. It
must be a regular file containing exactly 64 hexadecimal characters, optionally
followed by one newline. On POSIX it must belong to the current user and have no
group or other permissions (normally mode 0600). Symlinks are rejected. Use the
same persistent `MM_WORKSPACE_DIR` for Workshop and its local assistant service.
Native rendering still requires the operator's prepared Material Maker source and
compatible Godot executable; mounting the browser does not prepare native tools.

`MM_BASE_PATH` defaults to `/`. Both mount settings require canonical `/segments/`
paths; `MM_FOUNDRY_PATH` is optional and cannot contain another origin. Public origin
configuration accepts one HTTPS host origin or explicit HTTP loopback origin, with
no path, credentials, query or fragment. Workshop's mount cannot begin with `/api/`
or `/static/`, which remain reserved for direct local connections. Without
`MM_FOUNDRY_PATH`, companion navigation remains hidden. The browser reads the
resolution capability, so this 1024-pixel configuration also removes larger preview
and variation choices.

Managed startup prints the public mounted URL without its token. Opening the
launcher with browser launch enabled still supplies the fragment credential. A
private discovery record remains under the Workshop settings directory's
`sessions/` folder, with `application`, `session`, `workspace`, `port` and `token`
fields. `mm_mcp.play.session.session_path(cfg)` locates it. A second launcher
verifies a nonce-bound session proof, hosting settings and managed token before
reusing the service. Changing those settings requires stopping the old service.
Never copy the discovery record or authenticated launch link into public logs.

Foundry's adapter uses fixed loopback `http://127.0.0.1:8788/api/...` and sends the
shared credential in `X-MM-Token`. Workshop also accepts the configured prefix,
including `/shadermaker/workshop/api/...`, so proxies that preserve or strip the
mount both work. Static resources resolve relative to the browser entry directory.
The mount without its final slash redirects to the directory URL and preserves
the project query. Proxy headers cannot authorize additional hosts or origins.
The authenticated `/api/companion` endpoint returns only `ok`, `base_path` and
`foundry_path`; it exposes neither credentials nor filesystem paths.

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
