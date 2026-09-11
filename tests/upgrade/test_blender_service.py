"""Real storage/queue/receipt behavior with a synthetic fixed-worker boundary."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
import time
import zipfile

import pytest
from PIL import Image

from mm_mcp.core import ServiceError, canonical, file_digest, file_lock
from mm_mcp.service import MaterialService
from test_blender_mesh import triangle_glb


def synthetic_worker(request_path, output_dir, **kwargs):
    request = json.loads(Path(request_path).read_text())
    dest = Path(output_dir)
    operation = request['operation']
    result = {'blender_version': 'synthetic-test-worker', 'diagnostics': {'objects': [], 'uv_preparation': 'smart_project_derivative' if request['unwrap'] else 'preserved'}, 'maps': {}}
    if operation != 'inspect':
        Image.new('RGB', (request['resolution'],) * 2, (100, 80, 50)).save(dest / 'preview.png')
        (dest / 'material.blend').write_bytes(b'BLENDER-v304synthetic test asset')
    if operation == 'bake':
        for role in ['base_color', 'normal', 'ao', 'roughness', 'metallic', 'height', 'emission']:
            Image.new('RGB', (request['resolution'],) * 2).save(dest / (role + '.png'))
            result['maps'][role] = {'file': role + '.png', 'channels': 'rgb' if role in ('base_color', 'normal', 'emission') else 'r', 'color_space': 'srgb' if role in ('base_color', 'emission') else 'linear'}
        (dest / 'material.blend').write_bytes(b'BLENDER-v304synthetic test asset')
        (dest / 'material.glb').write_bytes(triangle_glb())
    (dest / 'worker_result.json').write_text(canonical(result))


@pytest.fixture
def blender_app(cfg, catalog, baker):
    cfg.blender_binary = sys.executable
    service = MaterialService(cfg, catalog, render_fn=baker, blender_fn=synthetic_worker)
    yield service
    service.close()


def test_blender_disabled_is_explicit_and_optional(app, monkeypatch, tmp_path):
    from mm_mcp.config import load_config
    monkeypatch.setenv('MM_DOTENV', str(tmp_path / 'missing'))
    assert load_config({'MM_BLENDER_BINARY': ''}).blender_binary == ''
    assert load_config({'MM_BLENDER_BINARY': sys.executable}).blender_binary == str(Path(sys.executable).resolve())
    assert app.blender.capabilities()['configured'] is False
    with pytest.raises(ServiceError, match='MM_BLENDER_BINARY'):
        app.blender.submit({'operation': 'inspect'})


def test_upload_round_trip_and_corrupt_source_refused(blender_app):
    store = blender_app.blender
    raw = triangle_glb()
    result = store.upload(name='triangle.glb', data_base64=base64.b64encode(raw).decode())
    mesh = result['mesh']
    assert mesh['mesh_id'] == 'mesh_' + hashlib.sha256(raw).hexdigest()
    again = store.upload(name='renamed.glb', data_base64=base64.b64encode(raw).decode())
    assert again['mesh']['mesh_id'] == mesh['mesh_id']
    store.mesh_path(mesh['mesh_id']).write_bytes(b'corrupt')
    with pytest.raises(ServiceError):
        store.prepare({'operation': 'inspect', 'mesh_id': mesh['mesh_id']})


@pytest.mark.parametrize('body', [
    {}, {'operation': 'python'}, {'operation': 'inspect', 'script': 'evil'},
    {'operation': 'inspect', 'specimen': 'sphere', 'mesh_id': 'mesh_' + 'a' * 64},
    {'operation': 'inspect', 'specimen': 'teapot'}, {'operation': 'inspect', 'resolution': 1024},
    {'operation': 'inspect', 'resolution': True}, {'operation': 'inspect', 'unwrap': 'yes'},
    {'operation': 'inspect', 'uv_scale': 0}, {'operation': 'inspect', 'uv_scale': float('nan')},
    {'operation': 'preview'}, {'operation': 'bake', 'build_id': '../outside'},
])
def test_fixed_request_bounds(blender_app, body):
    with pytest.raises(ServiceError):
        blender_app.blender.prepare(body)


def test_exact_build_receipt_and_portable_zip(blender_app):
    app = blender_app
    build = app.build({'recipe_id': 'fixture', 'size': 32, 'physical_size_m': 2})
    request = {'operation': 'bake', 'build_id': build['build_id'], 'specimen': 'beveled_cube', 'resolution': 128, 'uv_scale': 3, 'unwrap': True}
    result = app.blender.execute(app.blender.prepare(request))
    manifest = app.blender.get(result['result_id'])
    assert manifest['schema'] == 'mm.blender-result/v1'
    assert manifest['renderer_kind'] == 'injected_test_double'
    assert manifest['physical_size_m'] == 2
    assert manifest['normal_convention'] == 'OpenGL (+Y)'
    assert manifest['maps']['normal'] == {'file': 'normal.png', 'channels': 'rgb', 'color_space': 'linear'}
    with zipfile.ZipFile(io.BytesIO(app.blender.export(result['result_id']))) as bundle:
        assert set(bundle.namelist()) == {f['name'] for f in manifest['files']} | {'manifest.json'}
        assert bundle.read('material.ptex') == app.builds.artifact(build['build_id'], 'material.ptex').read_bytes()
        assert bundle.read('source_request.json') == app.builds.artifact(build['build_id'], 'request.json').read_bytes()
        assert hashlib.sha256(bundle.read('request.json')).hexdigest() == manifest['input_hash']
        inputs = json.loads(bundle.read('request.json'))
        assert result['result_id'] == 'bl_' + manifest['input_hash']
        assert inputs['source']['input_hash'] == build['manifest']['input_hash']
        assert inputs['build_id'] == build['build_id'] and inputs['resolution'] == 128
        assert inputs['tools']['blender_binary_sha256'] == file_digest(sys.executable)
        assert 'material.blend' in bundle.namelist() and 'material.glb' in bundle.namelist()
    assert app.blender.execute(app.blender.prepare(request))['cached'] is True


def test_source_build_is_pinned_before_queue_execution(blender_app):
    app = blender_app
    build = app.build({'recipe_id': 'fixture', 'size': 32})
    request = app.blender.prepare({'operation': 'preview', 'build_id': build['build_id']})
    path = app.builds.artifact(build['build_id'], 'manifest.json')
    content = json.loads(path.read_text())
    content['created_unix'] += 1
    path.write_text(canonical(content))
    with pytest.raises(ServiceError, match='changed'):
        app.blender.execute(request)


@pytest.mark.parametrize('name', ['preview.png', 'request.json', 'diagnostics.json', 'manifest.json'])
def test_changed_result_artifacts_are_never_served(blender_app, name):
    app = blender_app
    bid = app.build({'recipe_id': 'fixture', 'size': 32})['build_id']
    result = app.blender.execute(app.blender.prepare({'operation': 'preview', 'build_id': bid}))
    app.blender.artifact(result['result_id'], name).write_bytes(b'corrupt')
    with pytest.raises(ServiceError):
        app.blender.export(result['result_id'])


def test_cancelled_worker_publishes_nothing(blender_app):
    request = blender_app.blender.prepare({'operation': 'inspect'})
    with pytest.raises(ServiceError, match='cancelled'):
        blender_app.blender.execute(request, cancel=lambda: True)
    assert not list(blender_app.blender.results.glob('bl_*'))
    assert not list(blender_app.blender.results.glob('.stage-*'))


def test_blender_uses_existing_queue(blender_app):
    job = blender_app.blender.submit({'operation': 'inspect'})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = blender_app.jobs.get(job['job_id'])
        if state['state'] in ('failed', 'complete'):
            break
        time.sleep(.02)
    assert state['state'] == 'complete', state
    assert blender_app.blender.get(state['result']['result_id'])['operation'] == 'inspect'


def test_direct_build_waits_for_shared_native_lock(blender_app):
    app = blender_app
    entered = threading.Event()
    finished = threading.Event()
    def build():
        entered.set()
        app.build({'recipe_id': 'fixture', 'size': 32})
        finished.set()
    with file_lock(app.root / '.native.lock'):
        thread = threading.Thread(target=build)
        thread.start()
        assert entered.wait(1)
        assert not finished.wait(.2)
    thread.join(5)
    assert finished.is_set()


@pytest.mark.parametrize('field,value', [('physical_size_m', 12), ('normal_convention', 'DirectX'), ('blender_version', 'invented'), ('preview', 'source_request.json')])
def test_receipt_metadata_must_agree_with_hashed_worker_inputs(blender_app, field, value):
    app = blender_app
    bid = app.build({'recipe_id': 'fixture', 'size': 32})['build_id']
    result = app.blender.execute(app.blender.prepare({'operation': 'preview', 'build_id': bid}))
    path = app.blender.artifact(result['result_id'], 'manifest.json')
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(canonical(manifest))
    with pytest.raises(ServiceError):
        app.blender.get(result['result_id'])


def test_invalid_native_bake_output_cannot_be_published(blender_app):
    app = blender_app
    bid = app.build({'recipe_id': 'fixture', 'size': 32})['build_id']
    def invalid_size(request, output, **kwargs):
        synthetic_worker(request, output, **kwargs)
        Image.new('RGB', (64, 64)).save(Path(output) / 'normal.png')
    app.blender.runner = invalid_size
    with pytest.raises(ServiceError):
        app.blender.execute(app.blender.prepare({'operation': 'bake', 'build_id': bid, 'resolution': 128}))


def test_blender_waits_for_shared_native_lock_and_cancels(blender_app):
    app = blender_app
    request = app.blender.prepare({'operation': 'inspect'})
    entered = threading.Event()
    result = []
    cancelled = threading.Event()
    def work():
        entered.set()
        try:
            app.blender.execute(request, cancel=cancelled.is_set)
        except ServiceError as exc:
            result.append(exc.code)
    with file_lock(app.root / '.native.lock'):
        thread = threading.Thread(target=work)
        thread.start()
        assert entered.wait(1)
        time.sleep(.1)
        assert not result
        cancelled.set()
        thread.join(2)
    assert result == ['CANCELLED']


def test_blender_never_packages_external_material_maker_dependencies(blender_app):
    app = blender_app
    bid = app.build({'recipe_id': 'fixture', 'size': 32})['build_id']
    directory = app.builds.directory(bid)
    request = json.loads((directory / 'request.json').read_text())
    request['dependencies'] = [{'path': '/arbitrary/artist/image.png', 'sha256': 'a' * 64}]
    raw = canonical(request).encode()
    (directory / 'request.json').write_bytes(raw)
    manifest = json.loads((directory / 'manifest.json').read_text())
    manifest['input_hash'] = hashlib.sha256(raw).hexdigest()
    for item in manifest['files']:
        if item['name'] == 'request.json':
            item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (directory / 'manifest.json').write_text(canonical(manifest))
    with pytest.raises(ServiceError) as error:
        app.blender.prepare({'operation': 'preview', 'build_id': bid})
    assert error.value.code == 'BLENDER_SOURCE_DEPENDENCIES'


def test_preview_retains_an_editable_packed_scene(blender_app):
    app = blender_app
    bid = app.build({'recipe_id': 'fixture', 'size': 32})['build_id']
    result = app.blender.execute(app.blender.prepare({'operation': 'preview', 'build_id': bid}))
    assert 'material.blend' in {item['name'] for item in result['manifest']['files']}


@pytest.mark.parametrize('operation', ['render_graph', 'render_node_output', 'render_preview', 'live_render'])
def test_retained_native_tools_share_blender_lock(app, graph, monkeypatch, operation):
    from mm_mcp import server
    from types import SimpleNamespace
    monkeypatch.setattr(server, '_ensure_ready', lambda: (app.cfg, app.catalog))
    executed = threading.Event()
    def renderer(*args, **kwargs):
        executed.set()
        return SimpleNamespace(ok=False, error='Synthetic renderer boundary', images=[], image=None, log_tail='')
    monkeypatch.setattr(server, 'render', renderer)
    monkeypatch.setattr(server, '_render_preview', renderer)
    monkeypatch.setattr(server, '_ensure_live_session', lambda cfg: SimpleNamespace(ok=True))
    monkeypatch.setattr(server.live, 'render', renderer)
    args = [graph] if operation == 'render_graph' else [graph, 'surface']
    if operation == 'render_preview':
        path = str(Path(app.cfg.output_dir) / 'map.png')
        args = [path, path, path]
    if operation == 'live_render':
        args = []
    result = []
    with file_lock(app.root / '.native.lock'):
        thread = threading.Thread(target=lambda: result.append(getattr(server, operation)(*args)))
        thread.start()
        assert not executed.wait(.15)
    thread.join(3)
    assert executed.is_set() and result
