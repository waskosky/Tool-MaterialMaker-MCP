"""Token-authenticated, loopback-only browser adapter for the shared service.

The operator receives a fragment-token launch URL. Fragments are not sent in
HTTP requests; JavaScript exchanges the token via a header. No CORS is enabled.
"""
import csv
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import threading
import subprocess
from urllib.parse import parse_qs,urlsplit
import webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from mm_mcp.config import load_config
from mm_mcp.hosting import browser_url, read_managed_token, request_path
from mm_mcp.catalog_builder import build_catalog
from mm_mcp.core import ServiceError,MAX_JSON_BYTES,parse_json,identifier
from mm_mcp.service import get_service
from mm_mcp.play.sliders import derive_sliders
from mm_mcp.paths import reject_path_fragment,PathNotAllowed
from mm_mcp.play.session import (identity, authenticated_probe, response_proof, find_session,
                                 write_session, remove_session, launch_url)

STATIC_DIR=str(Path(__file__).parent/'static')

def make_handler(cfg,catalog,outdir=None,static_dir=STATIC_DIR,*,service=None,token=None,session_id=None):
    app=service or get_service(cfg,catalog)
    session_token=token or (read_managed_token(cfg.session_token_file) if cfg.session_token_file else secrets.token_urlsafe(32))
    session_identity=identity(session_id or secrets.token_hex(16),app.root,cfg)
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def setup(self):
            super().setup(); self.connection.settimeout(30)
        def log_message(self,*args):
            pass
        def _send(self,data,ctype='application/json',status=200,filename=None,location=None):
            if not isinstance(data,bytes):
                data=json.dumps(data,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header('Content-Disposition',f'attachment; filename="{identifier(filename)}"')
            if location:
                self.send_header('Location',location)
            self.end_headers(); self.wfile.write(data)
        def _guard(self,api=False,session_probe=False):
            port=self.server.server_address[1]
            allowed={f'127.0.0.1:{port}',f'localhost:{port}'}
            origins={'http://'+host for host in allowed}
            if cfg.public_origin:
                allowed.add(urlsplit(cfg.public_origin).netloc)
                origins.add(cfg.public_origin)
            if len(self.headers.get_all('Host',[]))!=1 or self.headers.get('Host','') not in allowed:
                raise ServiceError('HOST_DENIED','Host is not an explicitly configured Workshop host.')
            origin=self.headers.get('Origin')
            if len(self.headers.get_all('Origin',[]))>1 or (origin is not None and origin not in origins):
                raise ServiceError('ORIGIN_DENIED','Cross-origin requests are disabled.')
            if 'cross-site' in self.headers.get_all('Sec-Fetch-Site',[]):
                raise ServiceError('ORIGIN_DENIED','Cross-site requests are disabled.')
            if (api and not (len(self.headers.get_all('X-MM-Token',[]))==1 and
                            hmac.compare_digest(self.headers.get('X-MM-Token','').encode(),session_token.encode()))
                    and not (session_probe and authenticated_probe(self.headers,session_token,session_identity['session']))):
                raise ServiceError('AUTH_REQUIRED','Open the authenticated Workshop launch link, including its fragment token.')
        def _body(self):
            if self.headers.get('Transfer-Encoding'):
                raise ServiceError('REQUEST_ENCODING','Chunked requests are not accepted.')
            if self.headers.get_content_type()!='application/json':
                raise ServiceError('CONTENT_TYPE','Use application/json.')
            try:
                length=int(self.headers.get('Content-Length','0'))
            except ValueError as exc:
                raise ServiceError('REQUEST_LENGTH','Invalid content length.') from exc
            if not 0<length<=MAX_JSON_BYTES:
                raise ServiceError('REQUEST_LENGTH','Body must contain 1 byte through 8 MiB.')
            body=parse_json(self.rfile.read(length))
            if not isinstance(body,dict):
                raise ServiceError('REQUEST_TYPE','Request must be an object.')
            return body
        def _static(self,name):
            reject_path_fragment(name)
            path=Path(static_dir)/name
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(Path(static_dir).resolve()):
                raise ServiceError('NOT_FOUND','Static file not found.')
            return self._send(path.read_bytes(),mimetypes.guess_type(name)[0] or 'application/octet-stream')
        def _get(self):
            url,path=self._route(); query=parse_qs(url.query)
            self._guard(api=path.startswith('/api/'),session_probe=path=='/api/session')
            if cfg.base_path!='/' and path==cfg.base_path.rstrip('/'):
                return self._send(b'','text/plain',status=308,
                                  location=cfg.base_path+('?' + url.query if url.query else ''))
            if path=='/':
                return self._static('index.html')
            if path.startswith('/static/'):
                return self._static(path[len('/static/'):])
            if path=='/api/capabilities':
                return self._send(app.capabilities())
            if path=='/api/companion':
                return self._send({'ok':True,'base_path':cfg.base_path,'foundry_path':cfg.foundry_path})
            if path=='/api/setup':
                return self._send(app.setup_status())
            if path=='/api/session':
                result=dict(session_identity)
                if authenticated_probe(self.headers,session_token,session_identity['session']):
                    result['proof']=response_proof(session_token,self.headers['X-MM-Session-Nonce'],session_identity)
                return self._send(result)
            if path=='/api/materials':
                return self._send(app.materials((query.get('q') or [''])[0],category=(query.get('category') or [''])[0]))
            if path.startswith('/api/material/'):
                info=app.recipes.describe(path[len('/api/material/'):])
                return self._send({**info,'sliders':info['controls']})
            if path=='/api/projects':
                return self._send({'ok':True,'projects':app.graphs.list()})
            if path.startswith('/api/projects/'):
                project_id=path[len('/api/projects/'):]
                if project_id.endswith('/snapshots'):
                    project_id=project_id[:-len('/snapshots')]
                    return self._send({'ok':True,'project_id':project_id,'snapshots':app.graphs.snapshots(project_id)})
                return self._send(app.read_project(project_id))
            if path.startswith('/api/jobs/'):
                return self._send(app.jobs.get(path[len('/api/jobs/'):]))
            if path.startswith('/api/builds/'):
                rest=path[len('/api/builds/'):].split('/')
                if len(rest)==1:
                    return self._send({'ok':True,'manifest':app.builds.get(rest[0])})
                if len(rest)==2 and rest[1]=='thumbnail.png':
                    return self._send(app.thumbnails.image(rest[0]),'image/png')
                if len(rest)==3 and rest[1]=='files':
                    file=app.builds.artifact(rest[0],rest[2])
                    return self._send(file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            if path=='/api/export':
                bid=(query.get('build_id') or [''])[0]
                return self._send(app.builds.export(bid),'application/zip',filename=bid+'.zip')
            if path.startswith('/api/comparisons/'):
                name=identifier(path[len('/api/comparisons/'):])
                file=app.root/'comparisons'/name
                if file.suffix!='.png' or not file.is_file() or file.is_symlink():
                    raise ServiceError('NOT_FOUND','Comparison not found.')
                return self._send(file.read_bytes(),'image/png')
            raise ServiceError('NOT_FOUND','Endpoint not found.')
        def _route(self):
            # Accept both the browser mount and ordinary routes used by local
            # adapters/path-stripping proxies. Forwarded headers authorize nothing.
            url=urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment:
                raise ServiceError('INVALID_REQUEST','Use an origin-relative request path.')
            return url,request_path(url.path,cfg.base_path)
        def _post(self):
            self._guard(api=True); _,path=self._route(); body=self._body()
            if path=='/api/render':
                result=app.build(body)
            elif path=='/api/setup':
                result=app.configure_native(body)
            elif path in ('/api/setup/check','/api/setup/verify'):
                if body:
                    raise ServiceError('SETUP_FIELDS','This setup operation requires an empty object.')
                result=app.setup_status(check=True) if path.endswith('/check') else app.verify_native()
            elif path=='/api/jobs':
                result=app.jobs.submit(body)
            elif path.startswith('/api/jobs/') and path.endswith('/cancel'):
                result=app.jobs.cancel(path[len('/api/jobs/'):-len('/cancel')])
            elif path=='/api/projects':
                result=app.instantiate(body['recipe_id'],body.get('values'),body.get('title',''))
            elif path=='/api/patch':
                result=app.patch(**body)
            elif path=='/api/history':
                result=app.graphs.history_step(body['project_id'],body['expected_revision'],body['direction'])
                result['controls']=derive_sliders(result['graph'],app.catalog)
            elif path=='/api/snapshot':
                result=app.graphs.snapshot(body['project_id'],body['name'])
            elif path=='/api/restore':
                result=app.graphs.restore(body['project_id'],body['name'],body['expected_revision'])
            elif path=='/api/family':
                result=app.family(**body)
            elif path=='/api/context':
                result=app.world_context(**body)
            elif path=='/api/compare':
                result=app.compare(**body)
            elif path=='/api/mesh-masks':
                from mm_mcp.mesh_masks import bake_mesh_masks
                result=bake_mesh_masks(cfg=cfg,**body)
            elif path=='/api/recipes/save':
                result=app.save_recipe(**body)
            else:
                raise ServiceError('NOT_FOUND','Endpoint not found.')
            return self._send(result)
        def _handle(self,callback):
            try:
                callback()
            except ServiceError as exc:
                status=401 if exc.code=='AUTH_REQUIRED' else 403 if exc.code in ('HOST_DENIED','ORIGIN_DENIED') else 404 if exc.code.endswith('NOT_FOUND') else 409 if 'CONFLICT' in exc.code or exc.code=='SETUP_BUSY' else 400
                self._send(exc.result(),status=status)
            except (ValueError,TypeError,KeyError,PathNotAllowed) as exc:
                self._send({'ok':False,'code':'INVALID_REQUEST','error':str(exc)},status=400)
            except (BrokenPipeError,ConnectionResetError,TimeoutError):
                pass
            except Exception:
                import traceback,sys
                traceback.print_exc(file=sys.stderr)
                self._send({'ok':False,'code':'INTERNAL_ERROR','error':'Local service error; consult the terminal log.'},status=500)
        def do_GET(self):
            self._handle(self._get)
        def do_POST(self):
            self._handle(self._post)
    Handler.session_token=session_token
    Handler.session_identity=session_identity
    return Handler

def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True when something accepts TCP connections on host:port. A connect
    probe, not a bind attempt: HTTPServer sets SO_REUSEADDR, and on Windows
    that lets a second bind to a LISTENING port succeed silently, which is
    how a stale mm-play kept answering the browser while a new one believed
    it had started fine."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def describe_port_owner(port: int) -> str | None:
    """Windows only: 'PID <n> (<image name>)' for the process LISTENING on
    127.0.0.1:<port>, from `netstat -ano` + `tasklist`. None off-Windows, or
    when either command fails or the port is not found."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = None
    for line in out.splitlines():
        parts = line.split()
        if (len(parts) >= 5 and parts[0].upper() == "TCP"
                and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING"):
            pid = parts[4]
            break
    if not pid:
        return None
    name = None
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
        first = next((ln for ln in out.splitlines() if ln.strip().startswith('"')), "")
        row = next(csv.reader([first])) if first else []
        if len(row) >= 2 and row[1] == pid:
            name = row[0]
    except (OSError, subprocess.SubprocessError, StopIteration):
        pass
    return f"PID {pid}" + (f" ({name})" if name else "")


class _StrictThreadingHTTPServer(ThreadingHTTPServer):
    # Backstop for the probe above: never bind beside an existing listener.
    # SO_REUSEADDR means different things on the two platforms. On Windows it
    # lets a second bind succeed beside a live listener, so it must stay off.
    # On POSIX it only bypasses TIME_WAIT, so clearing it there just makes a
    # quick restart fail; keep it on for anything that isn't Windows.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._request_slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()





def serve(cfg=None,open_browser=True):
    """Serve or reuse Workshop; return False when startup cannot claim the port."""
    cfg=cfg or load_config()
    if port_in_use(cfg.play_port):
        record=find_session(cfg)
        if record:
            print(f'Reusing the running Material Workshop on port {cfg.play_port}.')
            if cfg.session_token_file:
                print('Material Workshop URL:\n'+browser_url(cfg))
            if open_browser:
                webbrowser.open(launch_url(cfg,record['token']))
        else:
            print(f'Local port {cfg.play_port} is in use by an unverified session or another application. Set MM_PLAY_PORT to another port, or close the old process.')
            return False
        return None
    catalog=build_catalog(cfg.nodes_dir)
    token=read_managed_token(cfg.session_token_file) if cfg.session_token_file else secrets.token_urlsafe(32)
    session_id=secrets.token_hex(16)
    # Bind before service creation: a simultaneous launcher cannot start another
    # worker simply because it lost the race for the HTTP port.
    try:
        httpd=_StrictThreadingHTTPServer(('127.0.0.1',cfg.play_port),BaseHTTPRequestHandler)
    except OSError:
        print(f'Could not bind local port {cfg.play_port}. Close the conflicting process or set MM_PLAY_PORT.'); return False
    app=None
    try:
        app=get_service(cfg,catalog)
        httpd.RequestHandlerClass=make_handler(cfg,catalog,service=app,token=token,session_id=session_id)
        write_session(cfg,token,session_id)
    except Exception:
        httpd.server_close()
        if app:
            app.close()
        raise
    url=launch_url(cfg,token)
    try:
        if cfg.session_token_file:
            print('Material Workshop URL:\n'+browser_url(cfg))
            print('Authentication uses the private companion token file and local session discovery.')
        else:
            print('Material Maker Play launch URL (keep private):\n'+url)
        print('Catalog and native-render status are shown in the browser. Ctrl+C stops this process.')
        app.jobs.start()
        if open_browser:
            webbrowser.open(url)
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close(); app.close(); remove_session(cfg,session_id)
    return httpd

def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='Open the local Material Workshop.')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--open',action='store_true',help='Open the browser (the default).')
    group.add_argument('--no-open',action='store_true',help='Run without opening a browser.')
    args=parser.parse_args(argv)
    result=serve(open_browser=not args.no_open)
    return 1 if result is False else 0

if __name__=='__main__':
    raise SystemExit(main())
