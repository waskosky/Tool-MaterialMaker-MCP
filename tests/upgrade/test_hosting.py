"""Hosted and direct-loopback requests share one authenticated Workshop service."""
from dataclasses import replace
from html.parser import HTMLParser
import http.client
import json
import os
import threading
from urllib.parse import urljoin, urlsplit

import pytest

from mm_mcp.config import load_config
from mm_mcp.hosting import read_managed_token
from mm_mcp.play.server import make_handler, _StrictThreadingHTTPServer
from mm_mcp.service import MaterialService
from tests.upgrade.test_http import call


@pytest.fixture(autouse=True)
def isolated_hosting(tmp_path, monkeypatch):
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / 'missing.env'))
    monkeypatch.setenv('MM_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    for key in ('MM_BASE_PATH', 'MM_PUBLIC_ORIGIN', 'MM_FOUNDRY_PATH', 'MM_SESSION_TOKEN_FILE'):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / 'companion.token'
    path.write_text('ab12' * 16 + '\n', encoding='ascii')
    path.chmod(0o600)
    return path


def test_standalone_defaults_and_hosted_configuration(token_file):
    standalone = load_config()
    assert (standalone.base_path, standalone.public_origin, standalone.foundry_path, standalone.session_token_file) == ('/', None, None, None)
    hosted = load_config({'MM_BASE_PATH': '/shadermaker/workshop/',
        'MM_PUBLIC_ORIGIN': 'https://W11.tailbcac65.ts.net:443', 'MM_FOUNDRY_PATH': '/shadermaker/',
        'MM_SESSION_TOKEN_FILE': str(token_file), 'MM_MAX_RESOLUTION': '1024'})
    assert hosted.public_origin == 'https://w11.tailbcac65.ts.net'
    assert hosted.base_path == '/shadermaker/workshop/' and hosted.foundry_path == '/shadermaker/'
    assert hosted.max_resolution == 1024 and read_managed_token(hosted.session_token_file) == 'ab12' * 16
    assert 'ab12' * 16 not in repr(hosted)


@pytest.mark.parametrize('name', ['MM_BASE_PATH', 'MM_FOUNDRY_PATH'])
@pytest.mark.parametrize('value', ['https://evil.example/', '//evil.example/', '/mount', '/a//b/',
                                  '/a/../', '/./', '/%2e%2e/', '/a%2fb/', '/a%5cb/',
                                  '/a\\b/', '/a/?x=1', '/a/#token=secret', '/a/\n'])
def test_ambiguous_or_external_mounts_are_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        load_config({name: value})


@pytest.mark.parametrize('path', ['/api/', '/api/projects/', '/static/', '/static/assets/'])
def test_mount_cannot_shadow_fixed_loopback_routes(path):
    with pytest.raises(ValueError, match='MM_BASE_PATH.*reserved'):
        load_config({'MM_BASE_PATH': path})


@pytest.mark.parametrize('origin', ['http://localhost:8080', 'http://127.0.0.1:8788', 'http://[::1]:8788',
                                   'https://workshop.example', 'https://workshop.example:8443'])
def test_explicit_origins(origin):
    assert load_config({'MM_PUBLIC_ORIGIN': origin}).public_origin == origin


@pytest.mark.parametrize('origin', ['http://workshop.example', 'http://127.1', 'http://2130706433',
    'https://workshop.example/', 'https://workshop.example/path', 'https://workshop.example?',
    'https://workshop.example#', 'https://user:pass@workshop.example', 'https://workshop.example:0',
    'https://workshop.example:99999', 'https://workshop.example:', 'https://*.example',
    'https://workshop.example\\evil', 'https://workshop.example\n', 'https://workshop%2eexample',
    'https://127.1', 'https://2130706433', 'https://0x7f000001'])
def test_unsafe_origins_are_rejected(origin):
    with pytest.raises(ValueError, match='MM_PUBLIC_ORIGIN'):
        load_config({'MM_PUBLIC_ORIGIN': origin})


@pytest.mark.parametrize('data', ['secret-do-not-log', 'a' * 63, 'a' * 65, 'g' * 64, 'a' * 64 + '\n\n'])
def test_invalid_managed_token_fails_without_disclosure(token_file, data):
    token_file.write_text(data)
    with pytest.raises(ValueError, match='MM_SESSION_TOKEN_FILE') as exc:
        load_config({'MM_SESSION_TOKEN_FILE': str(token_file)})
    assert data not in str(exc.value)


def test_non_regular_or_missing_token_file_is_rejected(token_file, tmp_path):
    for path in (tmp_path, tmp_path / 'missing'):
        with pytest.raises(ValueError, match='MM_SESSION_TOKEN_FILE'):
            read_managed_token(path)
    link = tmp_path / 'linked.token'
    try:
        link.symlink_to(token_file)
    except OSError:
        pytest.skip('This Windows account cannot create symlinks')
    with pytest.raises(ValueError, match='MM_SESSION_TOKEN_FILE'):
        read_managed_token(link)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission and ownership contract')
def test_managed_token_checks_private_permissions_and_owner(token_file, monkeypatch):
    token_file.chmod(0o640)
    with pytest.raises(ValueError, match='MM_SESSION_TOKEN_FILE'):
        read_managed_token(token_file)
    token_file.chmod(0o400)
    assert read_managed_token(token_file) == 'ab12' * 16
    owner = os.getuid()
    monkeypatch.setattr(os, 'getuid', lambda: owner + 1)
    with pytest.raises(ValueError, match='MM_SESSION_TOKEN_FILE'):
        read_managed_token(token_file)


def test_managed_token_accepts_hex_case_and_a_single_platform_newline(token_file):
    token_file.write_bytes(b'AB12' * 16 + b'\r\n')
    assert read_managed_token(token_file) == 'AB12' * 16


@pytest.fixture
def hosted_service(cfg, catalog, baker, token_file):
    cfg = replace(cfg, base_path='/shadermaker/workshop/', public_origin='https://workshop.example',
                  foundry_path='/shadermaker/', session_token_file=str(token_file), max_resolution=1024)
    app = MaterialService(cfg, catalog, render_fn=baker)
    handler = make_handler(cfg, catalog, service=app)
    server = _StrictThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.workshop_config = replace(cfg, play_port=server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, read_managed_token(token_file), app
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        app.close()


class ResourceLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == 'script' or (tag == 'link' and fields.get('rel') == 'stylesheet'):
            self.paths.append(fields.get('src') or fields['href'])


def test_entry_resources_resolve_at_root_and_mount(hosted_service):
    for entry in ('/', '/shadermaker/workshop/'):
        code, headers, html = call(hosted_service, entry, headers={'Host': 'workshop.example', 'X-MM-Token': ''})
        assert code == 200 and b'Material Workshop' in html
        assert "connect-src 'self'" in headers['Content-Security-Policy']
        assert headers['Referrer-Policy'] == 'no-referrer' and 'Access-Control-Allow-Origin' not in headers
        links = ResourceLinks()
        links.feed(html.decode())
        assert len(links.paths) == 6
        for resource in links.paths:
            assert not resource.startswith('/')
            path = urlsplit(urljoin('https://workshop.example' + entry, resource)).path
            assert call(hosted_service, path, headers={'Host': 'workshop.example', 'X-MM-Token': ''})[0] == 200
    code, meta, _ = call(hosted_service, '/shadermaker/workshop?project=project_a')
    assert code == 308 and meta['Location'] == '/shadermaker/workshop/?project=project_a'


def test_mounted_and_stripped_apis_share_projects_and_safe_companion_info(hosted_service):
    for prefix in ('', '/shadermaker/workshop'):
        code, _, info = call(hosted_service, prefix + '/api/companion')
        assert code == 200 and info == {'ok': True, 'base_path': '/shadermaker/workshop/', 'foundry_path': '/shadermaker/'}
        assert hosted_service[1] not in json.dumps(info) and str(hosted_service[2].root) not in json.dumps(info)
        assert call(hosted_service, prefix + '/api/companion', headers={'X-MM-Token': ''})[0] == 401
        assert call(hosted_service, prefix + '/api/capabilities')[2]['limits']['max_resolution'] == 1024
    code, _, project = call(hosted_service, '/shadermaker/workshop/api/projects', {'recipe_id': 'fixture'},
                            headers={'Host': 'workshop.example', 'Origin': 'https://workshop.example'})
    assert code == 200
    assert call(hosted_service, '/api/projects/' + project['project_id'])[2]['project_id'] == project['project_id']
    assert call(hosted_service, '/api/projects', {'recipe_id': 'fixture'})[0] == 200


def test_host_origin_token_and_forwarded_spoof_denial(hosted_service):
    allowed = {'Host': 'workshop.example', 'Origin': 'https://workshop.example'}
    for prefix in ('', '/shadermaker/workshop'):
        path = prefix + '/api/companion'
        assert call(hosted_service, path, headers=allowed)[0] == 200
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
            {'Origin': 'http://workshop.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'},
            {'Host': 'evil.example', 'X-Forwarded-Host': 'workshop.example'},
            {'Origin': 'https://evil.example', 'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'workshop.example'},
            {'Host': 'evil.example', 'Forwarded': 'host=workshop.example;proto=https'}):
            assert call(hosted_service, path, headers={**allowed, **headers})[0] == 403
        for headers in ({'X-MM-Token': ''}, {'X-MM-Token': 'wrong'}):
            assert call(hosted_service, path + '?token=' + hosted_service[1], headers={**allowed, **headers})[0] == 401
        assert call(hosted_service, path, headers={**allowed, 'X-Forwarded-Host': 'evil.example'})[0] == 200
        assert call(hosted_service, prefix + '/api/projects', {'recipe_id': 'fixture'}, headers={'Origin': 'https://evil.example'})[0] == 403
        assert call(hosted_service, prefix + '/api/projects', {'recipe_id': 'fixture'}, headers={'X-MM-Token': ''})[0] == 401


def test_traversal_and_encoded_separators_cannot_escape_mount(hosted_service):
    for prefix in ('', '/shadermaker/workshop'):
        for path in ('/static/../config.py', '/static/%2e%2e/config.py', '/static/%252e%252e/config.py',
                     '/static%2fapp.js', '/static/app%5c.js', '/api/projects/../setup', '/api/%2563ompanion',
                     '/static/three.min.js%00', '/static/%zz', '/api//companion'):
            assert call(hosted_service, prefix + path)[0] == 400
    assert call(hosted_service, '/shadermaker/workshop-other/api/companion')[0] == 404


def test_duplicate_authority_or_token_headers_are_rejected(hosted_service):
    for duplicate, expected in [('Host', 403), ('Origin', 403), ('X-MM-Token', 401)]:
        connection = http.client.HTTPConnection('127.0.0.1', hosted_service[0].server_address[1], timeout=5)
        try:
            connection.putrequest('GET', '/shadermaker/workshop/api/companion', skip_host=True)
            headers = {'Host': 'workshop.example', 'Origin': 'https://workshop.example', 'X-MM-Token': hosted_service[1]}
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.putheader(duplicate, headers[duplicate])
            connection.endheaders()
            response = connection.getresponse()
            response.read()
            assert response.status == expected
        finally:
            connection.close()


def test_private_discovery_reuses_only_matching_hosted_settings(hosted_service, token_file):
    from mm_mcp.play.session import find_session, launch_url, write_session
    cfg = hosted_service[0].workshop_config
    session = call(hosted_service, '/api/session')[2]['session']
    record = write_session(cfg, hosted_service[1], session)
    assert find_session(cfg) == record
    assert launch_url(cfg, record['token']) == 'https://workshop.example/shadermaker/workshop/#token=' + record['token']
    assert find_session(replace(cfg, base_path='/elsewhere/')) is None
    assert find_session(replace(cfg, public_origin='https://other.example')) is None
    assert find_session(replace(cfg, session_token_file=None)) is None
    token_file.write_text('c' * 64)
    assert find_session(cfg) is None


def test_managed_launcher_keeps_token_private_on_start_and_reuse(hosted_service, monkeypatch, capsys):
    from mm_mcp.play import server, session
    cfg = hosted_service[0].workshop_config
    opened = []
    monkeypatch.setattr(server.webbrowser, 'open', opened.append)
    identity = call(hosted_service, '/api/session')[2]
    session.write_session(cfg, hosted_service[1], identity['session'])
    server.serve(cfg=cfg)
    assert opened == [session.launch_url(cfg, hosted_service[1])]
    output = capsys.readouterr().out
    assert 'https://workshop.example/shadermaker/workshop/' in output and hosted_service[1] not in output

    records = []
    class BoundServer:
        def __init__(self, *args):
            pass
        def serve_forever(self):
            records.append(session.read_session(cfg))
            raise KeyboardInterrupt
        def server_close(self):
            pass
    monkeypatch.setattr(server, 'port_in_use', lambda port: False)
    monkeypatch.setattr(server, '_StrictThreadingHTTPServer', BoundServer)
    monkeypatch.setattr(server, 'build_catalog', lambda path: hosted_service[2].catalog)
    monkeypatch.setattr(server, 'get_service', lambda *args: hosted_service[2])
    server.serve(cfg=cfg, open_browser=False)
    output = capsys.readouterr().out
    assert 'https://workshop.example/shadermaker/workshop/' in output and hosted_service[1] not in output
    assert records[0]['token'] == hosted_service[1]
    assert session.read_session(cfg) is None
