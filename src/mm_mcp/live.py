# src/mm_mcp/live.py
import json
import os
import socket
import subprocess
import time
import secrets
import stat
import copy
from pathlib import Path
from mm_mcp.core import ServiceError, MAX_JSON_BYTES, canonical, identifier, parse_json, resolution, digest
from mm_mcp.transactions import apply_patch
from mm_mcp.artifacts import verify_images
from mm_mcp.policy import graph_dependencies
from dataclasses import dataclass

from mm_mcp.catalog_builder import build_catalog
from mm_mcp.config import Config, load_config
from mm_mcp.overlay import ensure_overlay
from mm_mcp.render import RenderResult, _collect_fresh_images, _kill_tree, _snapshot_pngs
from mm_mcp.validator import validate_graph
from mm_mcp import paths

# Must match addons/mm_live/live_server.gd's LIVE_PORT -- no shared-constant
# mechanism exists across GDScript and Python, so keep both literals in sync
# by hand if this ever changes.
LIVE_HOST = "127.0.0.1"
LIVE_PORT = 8765

# How long connect_or_launch will wait for an already-listening port to
# either become ready or stop listening, before deciding it's occupied by an
# unresponsive process rather than one that's still booting. Much shorter
# than launch_timeout on purpose -- see connect_or_launch's docstring.
_SQUATTED_PORT_GRACE = 5.0

# Prefer the source addon while developing; a synchronized copy ships in wheels.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ADDON_PATH = os.path.join(_REPO_ROOT, "addons", "mm_live")
if not os.path.isdir(_ADDON_PATH):
    _ADDON_PATH = str(Path(__file__).parent / "data" / "addons" / "mm_live")


@dataclass
class LiveResult:
    ok: bool
    data: dict | None = None
    error: str | None = None



def _runtime_record():
    path = Path(os.environ.get('MM_RUNTIME_DIR') or Path.home()/'.mm-mcp')/'live.json'
    try:
        if path.is_symlink():
            raise ServiceError('AUTH_RECORD', 'Native discovery record must not be a symlink.')
        info = path.stat()
        if os.name != 'nt' and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
            raise ServiceError('AUTH_RECORD', 'Native discovery record must be private to the current user (0600).')
        record = parse_json(path.read_bytes())
        if record.get('host') != '127.0.0.1' or record.get('port') != LIVE_PORT or record.get('protocol') != 'mm-live/2':
            raise ServiceError('AUTH_RECORD', 'Unsupported native discovery endpoint.')
        return record
    except OSError as exc:
        raise ServiceError('AUTH_RECORD', 'No authenticated bridge record. Launch the updated addon first.') from exc


def _send_command(cmd: dict, host: str = LIVE_HOST, port: int = LIVE_PORT,
                   timeout: float = 5.0) -> LiveResult:
    if host not in ('127.0.0.1', 'localhost') or port != LIVE_PORT:
        return LiveResult(ok=False,error='Only the authenticated loopback bridge endpoint is supported.')
    try:
        record=_runtime_record()
        message={**cmd,'token':record['token'],'protocol':'mm-live/2'}
        payload=(canonical(message)+'\n').encode()
        if len(payload)>MAX_JSON_BYTES:
            raise ServiceError('LIMIT','Native request exceeds 8 MiB.')
        with socket.create_connection((host,port),timeout=timeout) as sock:
            sock.sendall(payload); sock.settimeout(timeout)
            buf=bytearray()
            while b'\n' not in buf:
                chunk=sock.recv(min(65536,MAX_JSON_BYTES+1-len(buf)))
                if not chunk:
                    raise ServiceError('CONNECTION_CLOSED','Bridge closed without a complete response.')
                buf.extend(chunk)
                if len(buf)>MAX_JSON_BYTES:
                    raise ServiceError('LIMIT','Native response exceeds 8 MiB.')
        data=parse_json(bytes(buf).split(b'\n',1)[0])
        if not isinstance(data,dict):
            raise ServiceError('BAD_RESPONSE','Bridge response must be an object.')
        return LiveResult(ok=bool(data.get('ok')),data=data,error=data.get('error'))
    except (ServiceError,OSError,KeyError,ValueError) as exc:
        return LiveResult(ok=False,error=str(exc),data=exc.result() if isinstance(exc,ServiceError) else None)


def transaction(operations,expected_revision,idempotency_key,*,cfg=None,dry_run=False,timeout=90.0):
    cfg=cfg or load_config()
    if not expected_revision or not idempotency_key:
        return LiveResult(False,error='expected_revision and idempotency_key are required.')
    try:
        client_hash=digest({'ops':operations,'expected_revision':expected_revision,'dry_run':dry_run})
    except ServiceError as exc:
        return LiveResult(False,data=exc.result(),error=str(exc))
    receipt=_send_command({'cmd':'transaction_status','idempotency_key':idempotency_key,
                           'client_request_hash':client_hash},timeout=timeout)
    if receipt.ok:
        return receipt
    if not receipt.data or receipt.data.get('code')!='RECEIPT_NOT_FOUND':
        return receipt
    current=get_graph(timeout=timeout)
    if not current.ok:
        return current
    if current.data.get('revision') != expected_revision:
        return LiveResult(False,data={'code':'REVISION_CONFLICT'},error='Native graph changed; inspect it again.')
    try:
        proposed,_=apply_patch(current.data['graph'],operations,_ensure_catalog(cfg))
        _check_new_shader_policy(current.data['graph'],proposed,cfg)
    except ServiceError as exc:
        return LiveResult(False,data=exc.result(),error=str(exc))
    return _send_command({'cmd':'replace_graph','data':canonical(proposed),
                          'expected_revision':expected_revision,'idempotency_key':idempotency_key,
                          'dry_run':dry_run,'client_request_hash':client_hash},timeout=timeout)


def _shader_models(value):
    out=set()
    if isinstance(value,dict):
        if 'shader_model' in value:
            out.add(digest(value['shader_model']))
        for child in value.values():
            out.update(_shader_models(child))
    elif isinstance(value,list):
        for child in value:
            out.update(_shader_models(child))
    return out


def _check_new_shader_policy(before,after,cfg):
    unchanged=_shader_models(after)<=_shader_models(before)
    graph_dependencies(after,cfg,trusted_recipe=unchanged)


def history(direction,expected_revision,idempotency_key):
    if direction not in ('undo','redo') or not expected_revision or not idempotency_key:
        return LiveResult(False,error='Supply undo/redo, expected_revision, and idempotency_key.')
    return _send_command({'cmd':direction,'expected_revision':expected_revision,'idempotency_key':idempotency_key,
                          'client_request_hash':digest({'direction':direction,'expected_revision':expected_revision})},timeout=90)


def ping(host: str = LIVE_HOST, port: int = LIVE_PORT, timeout: float = 5.0) -> LiveResult:
    return _send_command({"cmd": "ping"}, host, port, timeout)


def get_graph(host: str = LIVE_HOST, port: int = LIVE_PORT, timeout: float = 5.0) -> LiveResult:
    return _send_command({"cmd": "get_graph"}, host, port, timeout)


def clear_graph(*args, **kwargs):
    return LiveResult(False,error="Unconditional clear is disabled. Snapshot the project and apply an explicit revisioned replacement.")


def _wait_for_ready_or_give_up(host: str, port: int,
                                deadline: float) -> tuple[bool, bool, bool, str]:
    """Poll ping() until it reports ready, or `deadline` (a time.monotonic()
    value) passes. Returns (ready, ever_answered, main_window_ever_ready,
    last_error).

    "Ready" here means both `ready` (main_window resolved) AND `has_graph`
    (a graph tab exists) from ping()'s response -- main_window can resolve
    one or more frames before the default graph tab is created, so gating
    on `ready` alone lets a caller proceed before add_node/get_graph/etc.
    are actually safe to call (see docs/superpowers/plans/
    2026-08-27-connect-or-launch-readiness-race.md).

    ever_answered is True the moment ping() ever returns ok=True, even with
    ready=False -- a real live-addon socket answers ping almost immediately
    after binding (project startup), well before main_window resolves (see
    the spec's "lazy main_window resolution" constraint). A single
    successful-but-not-ready response is proof this is a live addon that's
    still booting, not a dead/squatted process -- even if it never reaches
    ready before the deadline.

    main_window_ever_ready is True the moment ping() ever reports `ready`
    True on its own, independent of `has_graph` -- this lets a caller on
    the "already listening, attaching" path tell apart two situations that
    both look like "not ready by the deadline" from the combined check
    alone: main_window genuinely never resolving (still booting -- the
    existing ever_answered handling already covers this and must keep
    waiting), versus main_window resolving but no graph tab ever following
    it within the deadline (see connect_or_launch's docstring for why that
    second case gets failed fast instead of given the full launch_timeout).

    last_error is always a string, even on success (harmless: callers only
    read it on failure).
    """
    ever_answered = False
    main_window_ever_ready = False
    last_error = "timed out waiting for a response"
    while time.monotonic() < deadline:
        result = ping(host, port)
        if result.ok:
            ever_answered = True
            if result.data.get("ready"):
                main_window_ever_ready = True
                if result.data.get("has_graph"):
                    return True, ever_answered, main_window_ever_ready, last_error
        else:
            last_error = result.error
        time.sleep(0.5)
    return False, ever_answered, main_window_ever_ready, last_error


_catalog_cache: dict[str, dict] = {}


def _ensure_catalog(cfg: Config) -> dict:
    catalog = _catalog_cache.get(cfg.nodes_dir)
    if catalog is None:
        catalog = build_catalog(cfg.nodes_dir)
        _catalog_cache[cfg.nodes_dir] = catalog
    return catalog


def _validation_errors(ptex: dict, cfg: Config) -> list[dict]:
    problems = validate_graph(ptex, _ensure_catalog(cfg))
    return [p for p in problems if p["severity"] == "error"]


# Mutation ops (add_node/connect_nodes/disconnect_nodes/reposition_node/
# set_param/load_graph) default to a longer socket timeout than the read-only one-shots
# (ping/get_graph/clear_graph, 5s): a mutation right after a fresh launch can
# trigger shader warmup/compile of the affected node, which the 5s read-op
# budget could spuriously time out before finishing. 30s is a ceiling (max
# wait, not a fixed delay), half of render()'s proven-necessary 60s export
# budget -- a genuinely stuck op still fails, just not prematurely.
#
# Note: the ops that pre-flight with get_graph (all but add_node) pass this
# same timeout positionally into that internal get_graph call, so that read
# also gets the 30s budget -- deliberate, since a read right after a cold
# launch is subject to the same slowness. get_graph's *default* stays 5s for
# standalone callers; only ping (used by the connect_or_launch poll loop)
# must stay short there, and it is untouched.

def _one(op,cfg=None,timeout=90.0):
    current=get_graph(timeout=timeout)
    if not current.ok:
        return current
    return transaction([op],current.data['revision'],secrets.token_hex(16),cfg=cfg,timeout=timeout)

def add_node(node_type,parameters=None,x=0.0,y=0.0,cfg=None,**kwargs):
    name=node_type+'_'+secrets.token_hex(4)
    result=_one({'op':'add_node','node_type':node_type,'name':name,'parameters':parameters or {},'x':x,'y':y},cfg)
    if result.ok:
        result.data['name']=name
    return result

def connect_nodes(from_name,from_port,to_name,to_port,cfg=None,**kwargs):
    return _one({'op':'connect_nodes','from_name':from_name,'from_port':from_port,
                 'to_name':to_name,'to_port':to_port,'replace':True},cfg)

def disconnect_nodes(from_name,from_port,to_name,to_port,cfg=None,**kwargs):
    return _one({'op':'disconnect_nodes','from_name':from_name,'from_port':from_port,
                 'to_name':to_name,'to_port':to_port},cfg)

def reposition_node(name,x,y,cfg=None,**kwargs):
    return _one({'op':'reposition_node','name':name,'x':x,'y':y},cfg)

def set_param(name,parameters,cfg=None,**kwargs):
    return _one({'op':'set_param','path':name,'parameters':parameters},cfg)



def load_graph(graph=None,path=None,*,cfg=None,expected_revision=None,idempotency_key=None,**kwargs):
    cfg=cfg or load_config()
    if (graph is None)==(path is None):
        return LiveResult(False,error='Supply exactly one of graph or path.')
    try:
        if path is not None:
            graph=parse_json(Path(paths.ensure_within_roots(path,cfg.allowed_roots)).read_bytes())
        if not isinstance(graph,dict):
            raise ServiceError('GRAPH_TYPE','Graph must be an object.')
        problems=validate_graph(graph,_ensure_catalog(cfg),mode='strict')
        if any(p['severity']=='error' for p in problems):
            raise ServiceError('VALIDATION_FAILED','Graph failed validation.',problems=problems)
        if not expected_revision or not idempotency_key:
            raise ServiceError('REVISION_REQUIRED','Replacing a graph requires expected_revision and idempotency_key.')
        current=get_graph()
        if not current.ok:
            return current
        _check_new_shader_policy(current.data['graph'],graph,cfg)
        return _send_command({'cmd':'replace_graph','data':canonical(graph),'expected_revision':expected_revision,
                              'idempotency_key':idempotency_key},timeout=90)
    except (ServiceError,OSError,ValueError,paths.PathNotAllowed) as exc:
        return LiveResult(False,error=str(exc),data=exc.result() if isinstance(exc,ServiceError) else None)


def render(basename='material',profile='Godot/Godot 4 Standard',cfg=None,host=LIVE_HOST,port=LIVE_PORT,
           timeout=180.0,size=512,outdir=None,expected_revision=None):
    cfg=cfg or load_config()
    try:
        identifier(basename); resolution(size,getattr(cfg,'max_resolution',2048))
        current=get_graph(host,port,timeout)
        if not current.ok:
            return RenderResult(False,error=current.error)
        expected_revision=expected_revision or current.data['revision']
        output=Path(outdir or cfg.output_dir).resolve(); output.mkdir(parents=True,exist_ok=True)
        output=Path(paths.ensure_within_roots(str(output),[cfg.output_dir]))
        import tempfile,shutil
        with tempfile.TemporaryDirectory(prefix='.live-',dir=output) as stage:
            result=_send_command({'cmd':'render','prefix':str(Path(stage)/basename),'profile':profile,
                                  'size':size,'expected_revision':expected_revision},host,port,timeout)
            if not result.ok:
                return RenderResult(False,error=result.error)
            images=list(Path(stage).glob(basename+'_*.png'))
            from mm_mcp.builds import expected_channels
            verify_images(images,size,expected_channels(current.data['graph'],_ensure_catalog(cfg)),stage)
            published=[]
            for image in images:
                dest=output/image.name; os.replace(image,dest); published.append(str(dest))
            return RenderResult(True,images=published)
    except (ServiceError,OSError,paths.PathNotAllowed) as exc:
        return RenderResult(False,error=str(exc))


@dataclass
class LiveSession:
    ok: bool
    process: subprocess.Popen | None = None
    error: str | None = None

    def close(self) -> None:
        """Terminate the Godot process this session launched. No-op if this
        session attached to an already-running instance instead."""
        if self.process is not None:
            _terminate(self.process)
            self.process = None


def _is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _terminate(process: subprocess.Popen) -> None:
    """Terminate the launched process and any child process it spawned.

    Godot's console binary is a launcher that spawns the real GUI process
    as a separate child outside this Popen's own process tree on Windows,
    so process.terminate() alone only kills the launcher and leaves the GUI
    process running (confirmed via tasklist/wmic after a real integration
    test run -- two orphaned Godot processes remained). _kill_tree (shared
    with render.py's timeout path) taskkill /T's the whole tree rooted at
    the launcher's PID first, reaching the GUI child too; the plain
    terminate()/kill() sequence still runs after as a fallback in case
    taskkill silently failed (e.g. permission denied) or isn't available. A
    test double with no real OS pid (no .pid attribute) skips the taskkill
    step and falls straight to the fallback.
    """
    _kill_tree(process)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _launch_command(cfg: Config, overlay_dir: str) -> list[str]:
    return [cfg.console_binary, "--path", overlay_dir]


def _launch_overlay(cfg: Config) -> subprocess.Popen:
    overlay_dir = ensure_overlay(cfg.project_path, _ADDON_PATH, cfg.live_overlay_dir)
    os.makedirs(cfg.output_dir, exist_ok=True)
    log_file = open(os.path.join(cfg.output_dir, "mm_live.log"), "w", encoding="utf-8")
    # Godot's stdout must not be PIPE'd without draining it -- an undrained
    # pipe fills and blocks the child (confirmed during the Phase 5
    # feasibility spike). Redirect to a file instead.
    #
    # Popen dups the file descriptor for the child at spawn time, so the
    # parent's own copy of the handle must be closed once Popen returns --
    # otherwise every launch/relaunch leaks one fd. The finally runs even if
    # Popen raises, so a failed spawn doesn't leak the handle either.
    try:
        env = dict(os.environ)
        runtime = Path(env.get("MM_RUNTIME_DIR") or Path.home()/".mm-mcp")
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            runtime.chmod(0o700)
        env["MM_ENABLE_EXPERIMENTAL_LIVE_WRITES"] = "1" if cfg.enable_experimental_live_writes else "0"
        env["MM_ALLOW_CUSTOM_SHADERS"] = "1" if cfg.allow_custom_shaders else "0"
        env.update({"MM_ALLOWED_ROOTS":json.dumps(cfg.allowed_roots+[cfg.project_path]),"MM_RUNTIME_DIR":str(runtime),"MM_LIVE_TOKEN":secrets.token_urlsafe(32),
                    "MM_LIVE_OUTPUT_ROOT":str(Path(cfg.output_dir).resolve())})
        return subprocess.Popen(_launch_command(cfg, overlay_dir),
                                 stdout=log_file, stderr=subprocess.STDOUT, env=env,
                                 **({"start_new_session":True} if os.name!="nt" else {}))
    finally:
        log_file.close()


def connect_or_launch(cfg: Config | None = None, host: str = LIVE_HOST,
                       port: int = LIVE_PORT, launch_timeout: float = 60.0) -> LiveSession:
    """Probe (host, port); if nothing answers, rebuild the overlay if stale
    and launch Material Maker against it. Either way, poll ping() until the
    addon reports both main_window is wired AND a graph tab exists -- never
    assume the first successful ping means the GUI is usable (see the
    spec's "lazy main_window resolution" constraint) -- or give up. Giving
    up can happen two ways: after the full launch_timeout (the normal case,
    and the only case for a process this call launched itself), or fast,
    within the much shorter grace period, when attaching to an
    already-listening instance that turns out to be responsive but stuck
    without a graph tab (see the grace-period paragraph below).

    A port that's already listening gets a short grace period
    (_SQUATTED_PORT_GRACE, much shorter than launch_timeout) to either
    become ready or stop listening, before this function commits to
    attaching. This is what lets a genuinely-booting instance attach
    normally while also recovering from a dying instance (e.g. a previous
    test's Material Maker process that's still closing its socket) instead
    of burning the entire launch_timeout on a corpse that will never
    answer. If the port is still listening and still unresponsive after the
    grace period, that's treated as a squatted port: connect_or_launch fails
    fast with a diagnostic error rather than continuing to wait, since it
    can't safely bind its own listener there anyway. The discriminator is
    whether the port ever answers a ping validly at all (proves a live,
    still-booting addon) versus never answering once (genuinely squatted)
    -- not whether it reaches `ready` in time, since a real instance can
    legitimately take far longer than the grace period to finish booting.

    A third outcome shares that same grace period: if the port answers and
    even reports `ready` (main_window resolved) at least once during the
    grace period, but `has_graph` never follows within that same window,
    this function fails fast with a diagnosis rather than falling through
    to the full launch_timeout. A real addon's own boot sequence creates
    the default graph tab near-synchronously after main_window resolves,
    so the grace period is already generous enough to see it happen if it's
    ever going to; waiting the full launch_timeout here would just misdiagnose
    a genuinely responsive (but stale-addon or tab-less) instance as "timed
    out". This only applies to the "already listening, attaching" path --
    a process this call launched itself always gets the full launch_timeout
    for both conditions, since there's no ambiguity to resolve (we know it's
    a fresh boot, not a possibly-stale pre-existing instance).

    Attaching to an already-running instance never launches a process, so
    the returned session's close() is a no-op for that case: we only own the
    lifecycle of a process we started ourselves.
    """
    cfg = cfg or load_config()
    process = None
    still_listening = _is_listening(host, port)

    if still_listening:
        grace_deadline = time.monotonic() + min(_SQUATTED_PORT_GRACE, launch_timeout)
        ready, ever_answered, main_window_ever_ready, grace_error = _wait_for_ready_or_give_up(
            host, port, grace_deadline)
        if ready:
            return LiveSession(ok=True, process=None)
        if not ever_answered:
            still_listening = _is_listening(host, port)
            if still_listening:
                return LiveSession(
                    ok=False,
                    error=(
                        f"port {port} is occupied by a process that never answered as the live "
                        f"server after waiting {min(_SQUATTED_PORT_GRACE, launch_timeout):.0f}s "
                        f"({grace_error}). If a previous Material Maker/Godot process is stuck "
                        "on this port, close it (or taskkill the Godot console binary) and retry."
                    ),
                )
            # else: the occupant stopped listening during the grace period --
            # the port is free now, so fall through and launch normally.
        elif main_window_ever_ready:
            # main_window resolved at least once during the grace period,
            # but has_graph never followed within that same window -- this
            # is not a still-booting instance (that case leaves
            # main_window_ever_ready False and is handled below), it's a
            # responsive, already-running Material Maker with no graph tab.
            # A real addon's boot sequence makes graph-tab creation follow
            # main_window resolution near-synchronously, so the grace
            # period (already far longer than that gap) is enough to prove
            # this isn't just slow. Fail fast here instead of falling
            # through to the full launch_timeout, which would otherwise
            # misdiagnose a healthy-but-stuck instance as "timed out" a
            # minute later.
            return LiveSession(
                ok=False,
                error=(
                    f"Material Maker at {host}:{port} is running and responsive, but reports no "
                    "active graph tab after waiting "
                    f"{min(_SQUATTED_PORT_GRACE, launch_timeout):.0f}s. If this instance was "
                    "launched before this version, close it and let this tool relaunch a fresh "
                    "one so the updated live-control addon loads; otherwise open a material/graph "
                    "tab in it and retry."
                ),
            )
        # else: it answered at least once during the grace period but
        # main_window itself never resolved -- a real live-addon socket
        # that's still booting, not squatted. still_listening stays True,
        # so we skip the launch branch below and fall straight into the
        # main poll loop with its full launch_timeout budget, same as this
        # project's pre-hardening behavior for this exact case.

    if not still_listening:
        process = _launch_overlay(cfg)

    # The launch-and-poll span below is wrapped so that if anything raises
    # while we're waiting (not just the plain timeout, which is handled
    # after the loop), the process we just launched still gets terminated
    # instead of leaking as an orphaned, visible Godot window. Today
    # nothing in the loop actually raises (ping()/_send_command() catch
    # every exception type they can produce), but that's an implementation
    # detail of _send_command, not a guarantee -- this is a structural
    # safety net, not a response to an observed failure.
    try:
        deadline = time.monotonic() + launch_timeout
        last_error = "timed out waiting for the live server to become ready"
        while time.monotonic() < deadline:
            result = ping(host, port)
            if result.ok and result.data.get("ready") and result.data.get("has_graph"):
                return LiveSession(ok=True, process=process)
            if not result.ok:
                last_error = result.error
            if process is not None and process.poll() is not None:
                # The process we launched has already exited -- no point
                # waiting out the rest of launch_timeout. Point at the log
                # file _launch_overlay redirected stdout/stderr into, since
                # that's where the real diagnosis (GPU/driver failure, a
                # GDScript parse error, etc.) will be.
                return LiveSession(
                    ok=False,
                    error=f"Material Maker exited with code {process.returncode} before the "
                          f"live server became ready; see "
                          f"{os.path.join(cfg.output_dir, 'mm_live.log')}",
                )
            time.sleep(0.5)
    except BaseException:
        if process is not None:
            _terminate(process)
        raise

    if process is not None:
        _terminate(process)
    return LiveSession(ok=False, error=last_error, process=None)
