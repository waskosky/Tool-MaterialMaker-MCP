"""Real Chromium and the authenticated HTTP adapter, with a synthetic PNG baker.

This exercises browser networking and either WebGL availability or its fallback.
It does not certify native Material Maker rendering or engine appearance.
"""
import json
import os
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
import pytest

@pytest.mark.browser
def test_browser_http_edit_export_matches_shared_state(http_service,tmp_path):
    sync=pytest.importorskip('playwright.sync_api')
    executable=os.environ.get('MM_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:pytest.skip('Chromium executable unavailable; set MM_TEST_CHROMIUM')
    server,token,app=http_service;errors=[]
    with sync.sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        # Exercise the real loopback adapter, including authenticated fetches,
        # CSP, setup and artifact routes. The baker remains explicitly synthetic.
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/#token={token}')
        page.locator('#setup-open').click()
        sync.expect(page.locator('#setup-state')).to_have_text('Test renderer')
        assert page.locator('#setup-verify').is_disabled()
        assert page.locator('#setup-godot').input_value() == app.cfg.godot_binary
        setup_screenshot = os.environ.get('MM_SETUP_BROWSER_EVIDENCE')
        if setup_screenshot:
            page.screenshot(path=setup_screenshot, full_page=True)
        page.locator('#setup-close').click()
        page.locator('.recipe-row button').first.click()
        sync.expect(page.locator('#material-name')).to_have_text('fixture')
        page.locator('#size').select_option('128')
        row=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0'))
        number=row.locator('input[type=number]');number.fill('13');number.dispatch_event('change')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        assert page.locator('#evidence img').count()>=3
        if os.environ.get('MM_REQUIRE_WEBGL_TEST')=='1':
            assert page.locator('#viewport canvas').count()==1, page.locator('#viewport').inner_text()
        else:
            assert page.locator('#viewport canvas').count()==1 or 'WebGL context' in page.locator('#viewport').inner_text()
        for item in page.locator('#evidence img').all():
            item.evaluate('image => image.decode()')
        with page.expect_download() as event:page.locator('#download').click()
        downloaded=event.value;destination=tmp_path/'download.zip';downloaded.save_as(destination)
        with zipfile.ZipFile(destination) as z:
            graph=json.loads(z.read('material.ptex'))
            assert next(n for n in graph['nodes'] if n['name']=='surface')['parameters']['param0']==13
        assert not errors,errors
        screenshot=os.environ.get('MM_BROWSER_EVIDENCE')
        if screenshot:page.screenshot(path=screenshot,full_page=True)
        # A shared MCP-style edit makes a stale browser patch fail rather than overwrite.
        pid=app.graphs.list()[0]['id'];revision=app.graphs.read(pid)['revision']
        app.patch(pid,revision,[{'op':'set_controls','values':{'surface/param0':18}}],'external-client')
        number=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0')).locator('input[type=number]')
        number.fill('14');number.dispatch_event('change')
        sync.expect(page.locator('#status')).to_have_class(re.compile(r'\berror\b'))
        assert app.graphs.read(pid)['revision']==revision+1
        assert page.locator('#download').is_disabled()
        browser.close()


@pytest.mark.browser
def test_browser_setup_save_check_and_cancel(http_service, tmp_path, monkeypatch):
    """Real HTTP/UI setup with a version probe and cancellable worker double.

    The double never returns a native manifest. This verifies configuration and
    cancellation interactions, and deliberately cannot certify a native render.
    """
    sync = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('MM_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:
        pytest.skip('Chromium executable unavailable; set MM_TEST_CHROMIUM')
    from mm_mcp.core import ServiceError
    import mm_mcp.setup as setup
    server, token, app = http_service
    settings_file = tmp_path / 'settings.json'
    monkeypatch.setenv('MM_SETTINGS_FILE', str(settings_file))
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / 'absent.env'))
    monkeypatch.delenv('MM_GODOT_BINARY', raising=False)
    monkeypatch.delenv('MM_PROJECT_PATH', raising=False)
    (Path(app.cfg.project_path) / 'project.godot').write_text('config_version=5\n')
    monkeypatch.setattr(setup, 'discover_native', lambda: {
        'godot_binaries': [app.cfg.godot_binary], 'project_paths': [app.cfg.project_path]})
    monkeypatch.setattr(setup, 'version_check', lambda cfg: {
        'name': 'Godot version', 'ok': True, 'detail': 'Simulated version probe for this UI test.'})
    app.render_fn = None
    entered = threading.Event()
    def waiting_render(request, cancel):
        assert request == {'recipe_id': 't01_sand_dunes', 'size': 128, 'target': 'generic', 'force': True}
        entered.set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cancel():
                raise ServiceError('CANCELLED', 'Test worker stopped.')
            time.sleep(.02)
        raise AssertionError('Browser did not cancel its test worker.')
    monkeypatch.setattr(app, '_build', waiting_render)
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True,
            args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width':1100, 'height':1000})
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/#token={token}')
        page.locator('#setup-open').click()
        sync.expect(page.locator('#setup-state')).to_have_text('Ready to test')
        page.locator('#setup-check').click()
        sync.expect(page.locator('#setup-message')).to_contain_text('Detected installations')
        page.locator('#setup-save').click()
        sync.expect(page.locator('#setup-message')).to_contain_text('Setup saved')
        assert json.loads(settings_file.read_text()) == {
            'godot_binary': str(Path(app.cfg.godot_binary).resolve()),
            'project_path': str(Path(app.cfg.project_path).resolve())}
        # Being configured but not yet verified must still allow the first test.
        page.locator('#setup-verify').click()
        assert entered.wait(5)
        sync.expect(page.locator('#setup-cancel')).to_be_enabled()
        page.locator('#setup-cancel').click()
        sync.expect(page.locator('#setup-message')).to_contain_text('Test cancelled', timeout=10000)
        sync.expect(page.locator('#setup-verify')).to_be_enabled()
        assert not app.capabilities()['native_render_verified_this_session']
        browser.close()
