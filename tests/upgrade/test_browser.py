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
        page.locator('.recipe-card .recipe-open').first.click(timeout=5000)
        sync.expect(page.locator('#material-name')).to_have_text('Fixture')
        # Opening a configured recipe automatically starts a small preview.
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        page.locator('#size').select_option('128')
        row=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0'))
        number=row.locator('input[type=number]');number.fill('13');number.press('Tab')
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
        original_project = page.locator('#projects').input_value()
        page.locator('#snapshots-panel > summary').click()
        page.locator('#snapshot-name').fill('Before variations')
        page.locator('#snapshot').click()
        sync.expect(page.locator('#snapshot-count')).to_have_text('1')
        page.locator('#target').select_option('godot')
        page.locator('#physical-size').fill('2.5')
        page.locator('#physical-size').press('Tab')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        page.locator('#family-settings > summary').click()
        gain_range = page.locator('.variation-range[data-control-id="surface/param0"]')
        page.get_by_label('Lock Gain', exact=True).check()
        assert gain_range.locator('input[type=number]').first.is_disabled()
        page.get_by_label('Lock Gain', exact=True).uncheck()
        gain_range.locator('input[type=number]').nth(0).fill('4')
        gain_range.locator('input[type=number]').nth(1).fill('8')
        page.get_by_label('Lock Mode', exact=True).check()
        page.locator('#family-count').fill('3')
        page.locator('#family-seed').fill('17')
        with page.expect_response(lambda r: r.url.endswith('/api/family') and r.request.method == 'POST') as response:
            page.locator('#family').click()
        candidates = response.value.json()['candidates']
        sync.expect(page.locator('#family-progress')).to_have_text('3 / 3 ready', timeout=20000)
        page.locator('.variant-image').first.click()
        sync.expect(page.locator('#variant-dialog')).to_be_visible()
        page.locator('#variant-dialog img').evaluate('image => image.decode()')
        page.locator('#variant-dialog').get_by_role('button', name='Close', exact=True).click()
        page.locator('.pin-variant').nth(0).click()
        page.locator('.pin-variant').nth(1).click()
        page.locator('#compare').click()
        sync.expect(page.locator('#comparison')).to_be_visible()
        page.locator('#comparison').evaluate('image => image.decode()')
        calls = app.render_fn.calls
        page.locator('.use-variant').nth(1).click()
        sync.expect(page.locator('#material-name')).to_have_text('Fixture · variant 2')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        assert app.render_fn.calls == calls, 'Selecting an exact completed candidate should not rebake it'
        assert float(page.locator('.control').filter(has=page.locator('code',has_text='surface/param0')).locator('input[type=number]').input_value()) == candidates[1]['values']['surface/param0']
        with page.expect_download() as event:
            page.locator('#download').click()
        event.value.save_as(destination)
        from mm_mcp.core import digest
        with zipfile.ZipFile(destination) as z:
            assert digest(json.loads(z.read('material.ptex'))) == candidates[1]['graph_hash']
            target = json.loads(z.read('target.json'))
            assert target['target'] == 'godot' and target['physical_size_m'] == 2.5
        page.locator('#personal-panel > summary').click()
        page.locator('#recipe-name').fill('Blue study')
        page.locator('#save-recipe').click()
        sync.expect(page.get_by_role('button', name='Open Blue study', exact=True)).to_be_visible()
        page.locator('#search').fill('Blue study')
        sync.expect(page.locator('.recipe-card')).to_have_count(1)
        page.locator('.fav').click()
        page.locator('#favorites-only').check()
        sync.expect(page.locator('.recipe-card')).to_have_count(1)
        page.locator('#favorites-only').uncheck()
        page.locator('#search').fill('')
        sync.expect(page.locator('.recipe-card')).to_have_count(2)
        assert not errors,errors
        screenshot=os.environ.get('MM_BROWSER_EVIDENCE')
        page.evaluate('() => window.scrollTo(0, 0)')
        if screenshot:page.screenshot(path=screenshot,full_page=True)
        # Responsive layout and selected build survive a small touch viewport.
        page.set_viewport_size({'width':390, 'height':844})
        assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth')
        mobile = os.environ.get('MM_MOBILE_BROWSER_EVIDENCE')
        if mobile:page.screenshot(path=mobile,full_page=True)
        page.set_viewport_size({'width':1440, 'height':1050})
        page.locator('#projects').select_option(original_project)
        sync.expect(page.locator('#material-name')).to_have_text('Fixture')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        number = page.locator('.control').filter(has=page.locator('code',has_text='surface/param0')).locator('input[type=number]')
        number.fill('15'); number.press('Tab')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        page.locator('#snapshot-list').get_by_role('button', name='Restore', exact=True).click()
        sync.expect(number).to_have_value('13')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        # A shared MCP-style edit makes a stale browser patch fail rather than overwrite.
        pid=original_project;revision=app.graphs.read(pid)['revision']
        app.patch(pid,revision,[{'op':'set_controls','values':{'surface/param0':18}}],'external-client')
        number=page.locator('.control').filter(has=page.locator('code',has_text='surface/param0')).locator('input[type=number]')
        number.fill('14');number.press('Tab')
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


@pytest.mark.browser
def test_first_recipe_resumes_after_setup_loads_catalog(http_service, tmp_path, monkeypatch):
    """A simulated catalog installation resumes first use; the baker stays labelled."""
    sync = pytest.importorskip('playwright.sync_api')
    executable = os.environ.get('MM_TEST_CHROMIUM') or shutil.which('chromium') or shutil.which('google-chrome')
    if not executable:
        pytest.skip('Chromium executable unavailable; set MM_TEST_CHROMIUM')
    import mm_mcp.setup as setup
    server, token, app = http_service
    original = app.catalog
    app.catalog = app.graphs.catalog = app.recipes.catalog = app.builds.catalog = {}
    monkeypatch.setattr(setup, 'build_catalog', lambda nodes: original)
    monkeypatch.setenv('MM_SETTINGS_FILE', str(tmp_path / 'settings.json'))
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / 'absent.env'))
    monkeypatch.delenv('MM_GODOT_BINARY', raising=False)
    monkeypatch.delenv('MM_PROJECT_PATH', raising=False)
    (Path(app.cfg.project_path) / 'project.godot').write_text('config_version=5\n')
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True,
            args=['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width':1280, 'height':1000})
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/#token={token}')
        page.get_by_role('button', name='Open Fixture', exact=True).click()
        sync.expect(page.locator('#setup-dialog')).to_be_visible()
        assert not app.graphs.list()
        page.locator('#setup-save').click()
        sync.expect(page.locator('#setup-dialog')).not_to_be_visible()
        sync.expect(page.locator('#material-name')).to_have_text('Fixture')
        sync.expect(page.locator('#download')).to_be_enabled(timeout=20000)
        assert len(app.graphs.list()) == 1
        assert not app.capabilities()['native_render_verified_this_session']
        browser.close()
