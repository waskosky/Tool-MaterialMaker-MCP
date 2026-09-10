"""Local session reuse never trusts a URL or exposes bearer tokens to probes."""
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture(autouse=True)
def isolated_discovery(tmp_path, monkeypatch):
    monkeypatch.setenv('MM_SETTINGS_FILE', str(tmp_path / 'private' / 'settings.json'))


def test_session_endpoint_requires_auth_and_returns_no_token(http_service):
    from tests.upgrade.test_http import call
    code, _, data = call(http_service, '/api/session')
    assert code == 200 and data['application'] == 'material-workshop'
    assert data['workspace'] == str(http_service[2].root)
    assert data['session'] and http_service[1] not in json.dumps(data)
    assert call(http_service, '/api/session', headers={'X-MM-Token': ''})[0] == 401


def test_matching_private_session_reused_with_authenticated_identity(http_service, cfg):
    from mm_mcp.play.session import write_session, find_session, session_path
    from tests.upgrade.test_http import call
    active_cfg = replace(cfg, play_port=http_service[0].server_address[1])
    identity = call(http_service, '/api/session')[2]
    record = write_session(active_cfg, http_service[1], identity['session'])
    assert find_session(active_cfg) == record
    path = session_path(active_cfg)
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('field,value', [('workspace', '/other/workspace'), ('port', 1), ('application', 'other'), ('token', 'bad\r\nheader'), ('url', 'https://evil.example/')])
def test_bad_record_rejected_before_network(cfg, field, value, monkeypatch):
    import http.client
    from mm_mcp.play.session import write_session, session_path, find_session
    record = write_session(cfg, secrets.token_urlsafe(32), secrets.token_hex(16))
    record[field] = value
    session_path(cfg).write_text(json.dumps(record))
    def forbidden(*args, **kwargs):
        pytest.fail('malformed record must not make a network request')
    monkeypatch.setattr(http.client, 'HTTPConnection', forbidden)
    assert find_session(cfg) is None


def test_stale_wrong_token_is_rejected(http_service, cfg):
    from mm_mcp.play.session import write_session, find_session
    from tests.upgrade.test_http import call
    cfg = replace(cfg, play_port=http_service[0].server_address[1])
    identity = call(http_service, '/api/session')[2]
    write_session(cfg, secrets.token_urlsafe(32), identity['session'])
    assert find_session(cfg) is None


def test_unrelated_listener_cannot_receive_token_or_forge_identity(cfg):
    from mm_mcp.play.session import write_session, find_session
    seen = []
    record = {}
    class Other(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({key: record[key] for key in ('application', 'session', 'workspace')}).encode())
    server = HTTPServer(('127.0.0.1', 0), Other)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = replace(cfg, play_port=server.server_address[1])
        token = secrets.token_urlsafe(32)
        record.update(write_session(cfg, token, secrets.token_hex(16)))
        assert find_session(cfg) is None
        assert seen and token not in json.dumps(seen)
        assert 'X-MM-Token' not in seen[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_cleanup_removes_only_own_session(cfg):
    from mm_mcp.play.session import write_session, remove_session, session_path
    first, second = secrets.token_hex(16), secrets.token_hex(16)
    write_session(cfg, secrets.token_urlsafe(32), first)
    write_session(cfg, secrets.token_urlsafe(32), second)
    remove_session(cfg, first)
    assert session_path(cfg).exists()
    remove_session(cfg, second)
    assert not session_path(cfg).exists()


def test_second_launch_opens_existing_session_without_creating_service(http_service, cfg, monkeypatch):
    from mm_mcp.play import server
    from mm_mcp.play.session import write_session
    from tests.upgrade.test_http import call
    cfg = replace(cfg, play_port=http_service[0].server_address[1])
    identity = call(http_service, '/api/session')[2]
    write_session(cfg, http_service[1], identity['session'])
    opened = []
    monkeypatch.setattr(server.webbrowser, 'open', opened.append)
    def forbidden(*args, **kwargs):
        pytest.fail('reuse must not create a service or worker')
    monkeypatch.setattr(server, 'get_service', forbidden)
    server.serve(cfg=cfg, open_browser=True)
    assert opened == [f'http://127.0.0.1:{cfg.play_port}/#token={http_service[1]}']


def test_main_opens_browser_by_default_and_keeps_no_open_and_open_flags(monkeypatch):
    from mm_mcp.play import server
    calls = []
    monkeypatch.setattr(server, 'serve', lambda **kwargs: calls.append(kwargs))
    server.main([])
    server.main(['--no-open'])
    server.main(['--open'])
    assert [call['open_browser'] for call in calls] == [True, False, True]


def test_main_returns_success_after_server_closes(monkeypatch):
    from mm_mcp.play import server
    monkeypatch.setattr(server, 'serve', lambda **kwargs: object())
    assert server.main([]) == 0


def test_main_returns_failure_for_an_unrelated_occupied_port(cfg, monkeypatch, capsys):
    import socket
    from mm_mcp.play import server
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        active_cfg = replace(cfg, play_port=listener.getsockname()[1])
        monkeypatch.setattr(server, 'load_config', lambda: active_cfg)
        def forbidden(*args, **kwargs):
            pytest.fail('an unrelated listener must not create a service or worker')
        monkeypatch.setattr(server, 'get_service', forbidden)
        assert server.main(['--no-open']) == 1
    assert 'MM_PLAY_PORT' in capsys.readouterr().out


def test_module_entrypoint_exits_nonzero_for_an_unrelated_listener(tmp_path):
    import socket
    import subprocess
    import sys
    source_root = Path(__file__).resolve().parents[2]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        environment = dict(os.environ, MM_PLAY_PORT=str(listener.getsockname()[1]),
            MM_SETTINGS_FILE=str(tmp_path / 'settings.json'), MM_DOTENV=str(tmp_path / 'missing.env'),
            MM_OUTPUT_DIR=str(tmp_path / 'output'), MM_WORKSPACE_DIR=str(tmp_path / 'workspace'),
            MM_GODOT_BINARY='', MM_PROJECT_PATH='', PYTHONPATH=str(source_root / 'src'))
        result = subprocess.run([sys.executable, '-m', 'mm_mcp.play.server', '--no-open'],
                                env=environment, cwd=source_root, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1
    assert 'MM_PLAY_PORT' in result.stdout
    assert '#token=' not in result.stdout + result.stderr


def test_main_returns_failure_when_binding_loses_a_port_race(cfg, monkeypatch, capsys):
    from mm_mcp.play import server
    monkeypatch.setattr(server, 'load_config', lambda: cfg)
    monkeypatch.setattr(server, 'port_in_use', lambda port: False)
    def cannot_bind(*args, **kwargs):
        raise OSError('address already in use')
    monkeypatch.setattr(server, '_StrictThreadingHTTPServer', cannot_bind)
    assert server.main(['--no-open']) == 1
    assert 'Could not bind local port' in capsys.readouterr().out


def test_main_returns_success_when_reusing_a_verified_session(http_service, cfg, monkeypatch):
    from mm_mcp.play import server
    from mm_mcp.play.session import write_session
    from tests.upgrade.test_http import call
    active_cfg = replace(cfg, play_port=http_service[0].server_address[1])
    session = call(http_service, '/api/session')[2]['session']
    write_session(active_cfg, http_service[1], session)
    monkeypatch.setattr(server, 'load_config', lambda: active_cfg)
    assert server.main(['--no-open']) == 0


def test_redirecting_listener_is_not_followed_and_proxies_are_ignored(cfg, monkeypatch):
    from mm_mcp.play.session import write_session, find_session
    monkeypatch.setenv('HTTP_PROXY', 'http://bad-proxy.invalid:9999')
    monkeypatch.setenv('ALL_PROXY', 'http://bad-proxy.invalid:9999')
    seen = []
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header('Location', 'http://bad-redirect.invalid/')
            self.end_headers()
    server = HTTPServer(('127.0.0.1', 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = replace(cfg, play_port=server.server_address[1])
        write_session(cfg, secrets.token_urlsafe(32), secrets.token_hex(16))
        assert find_session(cfg) is None and seen == ['/api/session']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission contract')
def test_public_or_symlinked_discovery_record_is_rejected(cfg, tmp_path):
    from mm_mcp.play.session import write_session, read_session, session_path
    write_session(cfg, secrets.token_urlsafe(32), secrets.token_hex(16))
    path = session_path(cfg)
    path.chmod(0o644)
    assert read_session(cfg) is None
    public = tmp_path / 'public.json'
    path.rename(public)
    path.symlink_to(public)
    assert read_session(cfg) is None


def test_launcher_skips_install_when_existing_runtime_is_ready(tmp_path, monkeypatch):
    from scripts import launch
    python = launch.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(launch, 'runtime_ready', lambda *args: True)
    def forbidden(*args, **kwargs):
        pytest.fail('a ready runtime must not run pip or recreate the environment')
    monkeypatch.setattr(launch.subprocess, 'run', forbidden)
    assert launch.prepare_runtime(tmp_path) == python


def test_launcher_repairs_missing_pip_only_when_installation_is_needed(tmp_path, monkeypatch):
    from scripts import launch
    import subprocess
    python = launch.venv_python(tmp_path)
    python.parent.mkdir(parents=True)
    python.touch()
    ready = iter([False, True])
    monkeypatch.setattr(launch, 'runtime_ready', lambda *args: next(ready))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if command[-3:] == ['-m', 'pip', '--version'] else 0)
    monkeypatch.setattr(launch.subprocess, 'run', run)
    assert launch.prepare_runtime(tmp_path) == python
    assert calls == [[str(python), '-m', 'pip', '--version'],
                     [str(python), '-m', 'ensurepip', '--upgrade'],
                     [str(python), '-m', 'pip', 'install', '-e', str(tmp_path)]]


def test_launcher_creates_missing_environment_and_passes_paths_with_spaces(tmp_path, monkeypatch):
    from scripts import launch
    import subprocess
    root = tmp_path / 'a source checkout'
    root.mkdir()
    ready = iter([False, True])
    monkeypatch.setattr(launch, 'runtime_ready', lambda *args: next(ready))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(launch.subprocess, 'run', run)
    python = launch.prepare_runtime(root)
    assert calls[0] == [launch.sys.executable, '-m', 'venv', str(root / '.venv')]
    assert calls[-1] == [str(python), '-m', 'pip', 'install', '-e', str(root)]


def test_launcher_passes_browser_flags_to_app(tmp_path, monkeypatch):
    from scripts import launch
    import subprocess
    expected = tmp_path / 'Python with spaces'
    monkeypatch.setattr(launch, 'prepare_runtime', lambda root: expected)
    calls = []
    monkeypatch.setattr(launch.subprocess, 'run', lambda command, **kwargs: calls.append(command) or subprocess.CompletedProcess(command, 0))
    assert launch.main(['--no-open']) == 0
    assert calls == [[str(expected), '-m', 'mm_mcp.play.server', '--no-open']]


def test_launcher_propagates_server_startup_failure(tmp_path, monkeypatch):
    from scripts import launch
    import subprocess
    monkeypatch.setattr(launch, 'prepare_runtime', lambda root: tmp_path / 'python')
    monkeypatch.setattr(launch.subprocess, 'run', lambda command, **kwargs: subprocess.CompletedProcess(command, 1))
    assert launch.main(['--no-open']) == 1


def test_cleanup_cannot_unlink_a_replacement_session(cfg, monkeypatch):
    from mm_mcp.play import session
    first, second = secrets.token_hex(16), secrets.token_hex(16)
    session.write_session(cfg, secrets.token_urlsafe(32), first)
    entered, release, replaced = threading.Event(), threading.Event(), threading.Event()
    read = session.read_session
    def delayed_read(config):
        record = read(config)
        entered.set()
        assert release.wait(5)
        return record
    monkeypatch.setattr(session, 'read_session', delayed_read)
    remover = threading.Thread(target=lambda: session.remove_session(cfg, first))
    def replace_record():
        session.write_session(cfg, secrets.token_urlsafe(32), second)
        replaced.set()
    remover.start()
    assert entered.wait(3)
    writer = threading.Thread(target=replace_record)
    writer.start()
    try:
        assert not replaced.wait(.1)
    finally:
        release.set()
        remover.join(5)
        writer.join(5)
    assert read(cfg)['session'] == second
