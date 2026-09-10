"""Setup contracts use disposable paths; no installed native program is launched."""
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time

import pytest

from mm_mcp.config import load_config
from mm_mcp.core import ServiceError


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    monkeypatch.setenv('MM_SETTINGS_FILE', str(tmp_path / 'settings' / 'native.json'))
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / '.env'))
    monkeypatch.delenv('MM_GODOT_BINARY', raising=False)
    monkeypatch.delenv('MM_PROJECT_PATH', raising=False)
    return tmp_path / 'settings' / 'native.json'


@pytest.fixture
def native_paths(tmp_path):
    app = tmp_path / 'Godot.app'
    binary = app / 'Contents' / 'MacOS' / 'Godot'
    binary.parent.mkdir(parents=True)
    binary.write_text('placeholder executable; tests never run this')
    binary.chmod(0o755)
    project = tmp_path / 'material-maker'
    (project / 'addons/material_maker/nodes').mkdir(parents=True)
    (project / 'project.godot').write_text('config_version=5')
    return {'godot_binary': str(app), 'project_path': str(project)}


def test_saved_native_paths_are_normalized_and_loaded_with_explicit_precedence(settings_env, native_paths, monkeypatch):
    from mm_mcp.setup import save_settings
    saved = save_settings(native_paths)
    assert saved['godot_binary'].endswith('Godot.app/Contents/MacOS/Godot')
    assert json.loads(settings_env.read_text()) == saved
    assert load_config().godot_binary == saved['godot_binary']
    Path(os.environ['MM_DOTENV']).write_text('MM_GODOT_BINARY="/dotenv/Godot"\nUNRELATED_SECRET=keep-private\n')
    assert load_config().godot_binary == '/dotenv/Godot'
    monkeypatch.setenv('MM_GODOT_BINARY', '/environment/Godot')
    assert load_config().godot_binary == '/environment/Godot'
    assert load_config().project_path == saved['project_path']


@pytest.mark.parametrize('extra', [{'token': 'secret'}, {'workspace_dir': '/tmp'}, {'allow_custom_shaders': True}])
def test_settings_reject_unsupported_keys_without_writing(settings_env, native_paths, extra):
    from mm_mcp.setup import save_settings
    save_settings(native_paths)
    before = settings_env.read_bytes()
    with pytest.raises(ServiceError, match='Only'):
        save_settings({**native_paths, **extra})
    assert settings_env.read_bytes() == before


@pytest.mark.parametrize('changed', [{'godot_binary': '/missing/Godot'}, {'project_path': '/missing/MM'}, {'godot_binary': 42}])
def test_invalid_paths_leave_existing_settings_unchanged(settings_env, native_paths, changed):
    from mm_mcp.setup import save_settings
    save_settings(native_paths)
    before = settings_env.read_bytes()
    with pytest.raises(ServiceError):
        save_settings({**native_paths, **changed})
    assert settings_env.read_bytes() == before


def test_atomic_save_failure_preserves_previous_settings(settings_env, native_paths, monkeypatch):
    from mm_mcp.setup import save_settings
    save_settings(native_paths)
    before = settings_env.read_bytes()
    def fail(*args):
        raise OSError('disk unavailable')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        save_settings(native_paths)
    assert settings_env.read_bytes() == before


def test_native_refresh_preserves_service_projects_and_policy(app, settings_env, native_paths):
    project = app.instantiate('fixture')
    app.cfg = replace(app.cfg, allow_custom_shaders=True, enable_experimental_live_writes=True)
    before = app.cfg
    objects = app.graphs, app.recipes, app.builds, app.jobs
    result = app.configure_native(native_paths)
    assert result['ok'] and result['settings']['project_path'] == native_paths['project_path']
    assert objects == (app.graphs, app.recipes, app.builds, app.jobs)
    assert app.graphs.read(project['project_id']) == project
    assert app.cfg.output_dir == before.output_dir and app.cfg.workspace_dir == before.workspace_dir
    assert app.cfg.allow_custom_shaders and app.cfg.enable_experimental_live_writes
    assert app.graphs.catalog is app.catalog and app.recipes.catalog is app.catalog
    assert app.builds.catalog is app.catalog and app.builds.cfg is app.cfg
    assert (app.root / 'provenance' / (project['project_id'] + '.json')).is_file()


def test_setup_reports_only_effective_native_paths_and_override_sources(app, settings_env, native_paths, monkeypatch):
    monkeypatch.setenv('MM_GODOT_BINARY', app.cfg.godot_binary)
    Path(os.environ['MM_DOTENV']).write_text('UNRELATED_SECRET=keep-private\n')
    result = app.configure_native(native_paths)
    assert result['settings']['godot_binary'] == app.cfg.godot_binary
    assert 'environment' in result['overrides']['godot_binary']
    assert 'keep-private' not in json.dumps(result)
    assert set(json.loads(settings_env.read_text())) == {'godot_binary', 'project_path'}


def test_direct_build_blocks_reconfiguration_but_not_capabilities(app, settings_env, native_paths, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = app.render_fn
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    app.render_fn = blocked
    failures = []
    def build():
        try:
            app.build({'recipe_id': 'fixture', 'size': 32})
        except Exception as exc:
            failures.append(exc)
    worker = threading.Thread(target=build)
    worker.start()
    try:
        assert entered.wait(3)
        started = time.monotonic()
        assert app.capabilities()['native_render_verified_this_session'] is False
        with pytest.raises(ServiceError) as error:
            app.configure_native(native_paths)
        assert error.value.code == 'SETUP_BUSY'
        assert time.monotonic() - started < 1
        assert not settings_env.exists()
    finally:
        release.set()
        worker.join(5)
    assert not failures


def test_queued_jobs_block_reconfiguration(app, settings_env, native_paths, monkeypatch):
    app.jobs.close()
    monkeypatch.setattr(app.jobs, 'start', lambda: None)
    app.jobs.submit({'recipe_id': 'fixture', 'size': 32})
    with pytest.raises(ServiceError) as error:
        app.configure_native(native_paths)
    assert error.value.code == 'SETUP_BUSY'
    assert not settings_env.exists()


def test_only_new_successful_native_manifest_certifies_session(app, monkeypatch):
    results = [
        {'ok': True, 'cached': False, 'manifest': {'renderer_kind': 'injected_test_double'}},
        {'ok': True, 'cached': True, 'manifest': {'renderer_kind': 'native_material_maker'}},
        {'ok': True, 'cached': False, 'manifest': {'renderer_kind': 'native_material_maker'}},
    ]
    monkeypatch.setattr(app.builds, 'build', lambda *args, **kwargs: results.pop(0))
    app.render_fn = None
    for expected in (False, False, True):
        app.build({'recipe_id': 'fixture', 'size': 32})
        assert app.capabilities()['native_render_verified_this_session'] is expected


def test_injected_renderer_never_certifies_and_native_failure_is_remembered(app, monkeypatch):
    monkeypatch.setattr(app.builds, 'build', lambda *args, **kwargs: {'ok': True, 'cached': False, 'manifest': {'renderer_kind': 'native_material_maker'}})
    app.build({'recipe_id': 'fixture', 'size': 32})
    assert not app.capabilities()['native_render_verified_this_session']
    def failed(*args, **kwargs):
        raise ServiceError('RENDER_FAILED', 'native renderer failed')
    monkeypatch.setattr(app.builds, 'build', failed)
    app.render_fn = None
    with pytest.raises(ServiceError):
        app.build({'recipe_id': 'fixture', 'size': 32})
    assert app.setup_status()['last_render_error'] == 'native renderer failed'


def test_new_native_paths_reset_session_verification(app, settings_env, native_paths, monkeypatch):
    monkeypatch.setattr(app.builds, 'build', lambda *args, **kwargs: {'ok': True, 'cached': False, 'manifest': {'renderer_kind': 'native_material_maker'}})
    app.render_fn = None
    app.build({'recipe_id': 'fixture', 'size': 32})
    assert app.capabilities()['native_render_verified_this_session']
    assert not app.configure_native(native_paths)['native_render_verified_this_session']


def test_idle_configuration_transaction_serializes_racing_submissions(app, settings_env, native_paths, monkeypatch):
    import mm_mcp.setup as setup
    app.jobs.close()
    monkeypatch.setattr(app.jobs, 'start', lambda: None)
    entered, release, submitted = threading.Event(), threading.Event(), threading.Event()
    original = setup.atomic_json
    def blocked_save(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(setup, 'atomic_json', blocked_save)
    failures = []
    def configure():
        try:
            app.configure_native(native_paths)
        except Exception as exc:
            failures.append(exc)
    def submit():
        app.jobs.submit({'recipe_id': 'fixture', 'size': 32})
        submitted.set()
    configure_thread = threading.Thread(target=configure)
    configure_thread.start()
    assert entered.wait(3)
    submit_thread = threading.Thread(target=submit)
    submit_thread.start()
    try:
        assert not submitted.wait(.1)
    finally:
        release.set()
        configure_thread.join(5)
        submit_thread.join(5)
    assert submitted.is_set() and not failures
    assert app.jobs.active()
    assert app.cfg.project_path == native_paths['project_path']


def test_discovery_finds_bounded_nearby_checkouts_and_godot_apps(tmp_path, native_paths, monkeypatch):
    from mm_mcp.setup import discover_native
    import shutil
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    cwd = home / 'games' / 'workshop'
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    project = home / 'games/temp/material-maker-pinned/material-maker-ad19fcf'
    shutil.copytree(native_paths['project_path'], project)
    godot = home / 'games/temp/godot-4.7.2-workshop/Godot.app'
    shutil.copytree(native_paths['godot_binary'], godot)
    found = discover_native()
    assert str(project) in found['project_paths']
    assert str(godot / 'Contents/MacOS/Godot') in found['godot_binaries']
    assert len(found['project_paths']) <= 24 and len(found['godot_binaries']) <= 24


@pytest.mark.parametrize('version_text', ['4.7.2.stable.official.abc', '4.7.stable.official.abc'])
def test_check_only_executes_current_configured_binary_and_distinguishes_version_from_render(app, monkeypatch, version_text):
    import mm_mcp.setup as setup
    import subprocess
    calls = []
    def version(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, version_text + '\n', '')
    monkeypatch.setattr(subprocess, 'run', version)
    monkeypatch.setattr(setup, 'discover_native', lambda: {'godot_binaries': ['/untrusted/Godot'], 'project_paths': []})
    status = app.setup_status(check=True)
    assert calls == [[str(Path(app.cfg.console_binary).resolve()), '--version']]
    assert any(c['name'] == 'Godot version' and c['ok'] and version_text in c['detail'] for c in status['checks'])
    assert next(c for c in status['checks'] if c['name'] == 'native render')['required'] is False
    assert not status['native_render_verified_this_session']


def test_setup_http_routes_are_authenticated_and_keep_existing_guards(http_service, settings_env, native_paths):
    from tests.upgrade.test_http import call
    for path, body in [('/api/setup', None), ('/api/setup/check', {}), ('/api/setup', native_paths), ('/api/setup/verify', {})]:
        assert call(http_service, path, body, headers={'X-MM-Token': ''})[0] == 401
        assert call(http_service, path, body, headers={'Origin': 'https://evil.example'})[0] == 403
    code, _, status = call(http_service, '/api/setup')
    assert code == 200 and 'install' in status and 'checks' in status
    assert call(http_service, '/api/setup', {**native_paths, 'token': 'secret'})[0] == 400
    assert call(http_service, '/api/setup', native_paths)[0] == 200
    code, _, result = call(http_service, '/api/setup/verify', {})
    assert code == 400 and result['code'] == 'TEST_RENDERER'


def test_verify_submits_forced_small_native_cookbook_job(app, monkeypatch):
    app.render_fn = None
    requests = []
    def submit(request):
        requests.append(request)
        return {'ok': True, 'job_id': 'j_fixture', 'state': 'queued'}
    monkeypatch.setattr(app.jobs, 'submit', submit)
    assert app.verify_native()['job_id'] == 'j_fixture'
    assert requests == [{'recipe_id': 't01_sand_dunes', 'size': 128, 'target': 'generic', 'force': True}]


def test_configure_cli_repairs_native_entries_and_preserves_unrelated_text(settings_env, native_paths, tmp_path, monkeypatch):
    from scripts import configure
    dotenv = tmp_path / 'source.env'
    original = '# artist settings\nMM_OUTPUT_DIR="/kept/output"\nMM_ALLOW_CUSTOM_SHADERS=1\nSECRET="keep-private"\n'
    dotenv.write_text(original + 'MM_GODOT_BINARY="/old/Godot"\nMM_PROJECT_PATH="/old/MM"\n')
    assert configure.main(['--env-file', str(dotenv), '--godot-binary', native_paths['godot_binary'], '--project-path', native_paths['project_path']]) == 0
    updated = dotenv.read_text()
    assert updated.startswith(original)
    assert '/old/' not in updated
    assert 'Godot.app/Contents/MacOS/Godot' in updated


def test_configure_cli_offline_works_without_native_paths(tmp_path):
    from scripts import configure
    dotenv = tmp_path / '.env'
    assert configure.main(['--offline', '--env-file', str(dotenv)]) == 0
    assert dotenv.is_file()


@pytest.mark.parametrize('existing', [False, True], ids=['append', 'replace'])
@pytest.mark.parametrize('native_path', [
    '/Users/José/材质/Godot',
    r'C:\Users\José\Godot',
    '/Users/José/A "quoted" path/Godot',
    '/Users/José/backslash\\"quote/Godot',
    '/Users/José/control\x1f/Godot',
])
def test_configure_env_paths_round_trip_unicode_and_dotenv_escaping(tmp_path, existing, native_path):
    from dotenv import dotenv_values
    from scripts.configure import write_env
    path = tmp_path / '.env'
    unrelated = '# Artist configuration\nMM_OUTPUT_DIR="/preserved/output"\n'
    path.write_text(unrelated + ('MM_GODOT_BINARY="old"\n' if existing else ''), encoding='utf-8')
    write_env(path, {'MM_GODOT_BINARY': native_path})
    assert dotenv_values(path)['MM_GODOT_BINARY'] == native_path
    assert path.read_text(encoding='utf-8').startswith(unrelated)


def test_invalid_build_request_does_not_replace_real_render_error(app):
    app.render_fn = None
    app._last_render_error = 'Previous native graphics failure'
    with pytest.raises(ServiceError):
        app.build({'recipe_id': 'fixture', 'size': 17})
    assert app.setup_status()['last_render_error'] == 'Previous native graphics failure'


def test_discovery_has_a_global_filesystem_budget(tmp_path, monkeypatch):
    import mm_mcp.setup as setup
    calls = []
    def missing(path, key):
        calls.append((path, key))
        raise ServiceError('SETUP_PATH', 'not found')
    monkeypatch.setattr(setup, 'normalize_path', missing)
    monkeypatch.setattr(Path, 'iterdir', lambda path: (path / f'godot-candidate-{i}' for i in range(10000)))
    setup.discover_native()
    assert len(calls) <= 8500


def test_symlink_loop_is_rejected_as_a_path_error_and_discovery_skips_it(tmp_path, monkeypatch):
    from mm_mcp.setup import discover_native, normalize_path
    loop = tmp_path / 'Godot.app'
    try:
        loop.symlink_to(loop)
    except OSError:
        pytest.skip('symlink creation is unavailable')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ServiceError) as error:
        normalize_path(str(loop), 'godot_binary')
    assert error.value.code == 'SETUP_PATH'
    assert str(loop) not in discover_native()['godot_binaries']


def test_malformed_settings_do_not_block_environment_or_offline_repair(settings_env, native_paths, monkeypatch, cfg, catalog):
    from mm_mcp.service import MaterialService
    settings_env.parent.mkdir()
    settings_env.write_text('{broken secret-native-value')
    before = settings_env.read_bytes()
    monkeypatch.setenv('MM_GODOT_BINARY', cfg.godot_binary)
    loaded = load_config({'MM_WORKSPACE_DIR': cfg.workspace_dir, 'MM_OUTPUT_DIR': cfg.output_dir})
    assert loaded.godot_binary == cfg.godot_binary
    service = MaterialService(loaded, catalog)
    try:
        status = service.setup_status()
        assert any(check['name'] == 'saved settings' and not check['ok'] and check['required'] is False for check in status['checks'])
        assert 'secret-native-value' not in json.dumps(status)
        assert settings_env.read_bytes() == before
        saved = service.configure_native(native_paths)
        assert saved['ok'] and not any(check['name'] == 'saved settings' and not check['ok'] for check in saved['checks'])
        assert set(json.loads(settings_env.read_text())) == {'godot_binary', 'project_path'}
    finally:
        service.close()
