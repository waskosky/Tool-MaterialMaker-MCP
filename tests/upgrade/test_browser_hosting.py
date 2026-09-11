"""Real browser entry behind a prefix-stripping proxy; no renderer is configured."""
from dataclasses import replace
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import shutil
import threading
from urllib.parse import urlsplit

import pytest

from mm_mcp.play.server import make_handler, _StrictThreadingHTTPServer
from mm_mcp.service import MaterialService


@pytest.fixture
def stripped_proxy(cfg, catalog, tmp_path, monkeypatch):
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / 'absent.env'))
    monkeypatch.setenv('MM_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    mount = '/shadermaker/workshop/'
    token = 'browser-entry-fixture-token'
    observed = []

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def forward(self):
            url = urlsplit(self.path)
            if url.path == mount.rstrip('/'):
                path = '/'
            elif url.path.startswith(mount):
                path = '/' + url.path[len(mount):]
            else:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            target = path + ('?' + url.query if url.query else '')
            observed.append({'method': self.command, 'path': self.path, 'upstream': target,
                             'authenticated': self.headers.get('X-MM-Token') == token})
            body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) or None
            connection = http.client.HTTPConnection('127.0.0.1', upstream.server_address[1], timeout=5)
            try:
                connection.request(self.command, target, body=body, headers=dict(self.headers))
                response = connection.getresponse()
                data = response.read()
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in {'server', 'date', 'connection'}:
                        self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)
            finally:
                connection.close()

        do_GET = forward
        do_POST = forward

    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    origin = f'http://127.0.0.1:{proxy.server_address[1]}'
    configured = replace(cfg, base_path=mount, public_origin=origin,
                         godot_binary='', console_binary='', project_path='')
    app = MaterialService(configured, catalog)
    upstream = _StrictThreadingHTTPServer(('127.0.0.1', 0),
                                         make_handler(configured, catalog, service=app, token=token))
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, proxy)]
    for thread in threads:
        thread.start()
    try:
        yield origin, mount, token, app, observed
    finally:
        for server in (proxy, upstream):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
        app.close()


@pytest.mark.browser
def test_slashless_proxy_entry_loads_styles_and_authenticated_project(stripped_proxy):
    sync = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('MM_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:
        pytest.skip('Chromium executable unavailable; set MM_TEST_CHROMIUM')
    origin, mount, token, app, observed = stripped_proxy
    project = app.instantiate('fixture', title='Slashless entry project')
    query = '?project=' + project['project_id'] + '&view=source'
    entry = origin + mount.rstrip('/') + query
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True,
            args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        try:
            # URL normalization itself preserves history and non-token fragments.
            anonymous = browser.new_context(viewport={'width':1440, 'height':1050})
            anonymous.add_init_script("history.replaceState({entry:'retained'}, '', location.href)")
            page = anonymous.new_page()
            response = page.goto(entry + '#tab=source')
            assert response.status == 200
            assert "base-uri 'none'" in response.headers['content-security-policy']
            sync.expect(page.locator('#status')).to_contain_text('fragment token')
            assert page.evaluate('location.pathname') == mount
            assert page.evaluate('location.search') == query
            assert page.evaluate('location.hash') == '#tab=source'
            assert page.evaluate('history.state') == {'entry': 'retained'}
            sync.expect(page.locator('#layout')).to_have_css('display', 'grid')
            sync.expect(page.locator('body')).to_have_css('background-color', 'rgb(18, 25, 23)')
            assert page.request.get(origin + mount + 'api/projects').status == 401
            anonymous.close()

            context = browser.new_context(viewport={'width':1440, 'height':1050})
            page = context.new_page()
            errors, resources = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: resources.append((response.url, response.status))
                    if response.request.resource_type in {'stylesheet', 'script'} else None)
            start = len(observed)
            page.goto(entry + '#token=' + token)
            sync.expect(page.locator('#material-name')).to_have_text('Slashless entry project')
            sync.expect(page.locator('#projects')).to_have_value(project['project_id'])
            sync.expect(page.locator('.recipe-card')).to_have_count(1)
            sync.expect(page.locator('#layout')).to_have_css('display', 'grid')
            sync.expect(page.locator('body')).to_have_css('background-color', 'rgb(18, 25, 23)')
            assert page.url == origin + mount + query
            assert page.evaluate("sessionStorage.getItem('mm.token')") == token
            assert len(resources) == 6
            assert all(url.startswith(origin + mount + 'static/') and status == 200 for url, status in resources)
            assert observed[start]['upstream'] == '/' + query
            api = [request for request in observed[start:] if '/api/' in request['path']]
            assert api and all(request['path'].startswith(mount + 'api/') and request['authenticated'] for request in api)
            assert not any(token in request['path'] for request in observed)
            assert not any(request['method'] == 'POST' and request['upstream'] == '/api/jobs' for request in observed)
            assert not app.capabilities()['native_render_configured']
            assert not app.capabilities()['native_render_verified_this_session']
            # Reload now uses the canonical slash URL and the consumed session token.
            page.reload()
            sync.expect(page.locator('#material-name')).to_have_text('Slashless entry project')
            sync.expect(page.locator('#projects')).to_have_value(project['project_id'])
            assert page.url == origin + mount + query
            assert not errors, errors
            screenshot = os.environ.get('MM_HOSTED_ENTRY_BROWSER_EVIDENCE')
            if screenshot:
                page.screenshot(path=screenshot, full_page=True)
            context.close()
        finally:
            browser.close()
