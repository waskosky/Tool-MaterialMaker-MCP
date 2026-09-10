"""Publication contracts using scripted subprocesses, not a native renderer."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from mm_mcp import preview, render
from mm_mcp.core import ServiceError, file_digest
from mm_mcp.policy import graph_dependencies


CRASH = 3221225477


def _script_processes(monkeypatch, attempts):
    """Run filesystem effects when the worker waits for each scripted process."""
    launched = []

    class Process:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.returncode = None
            self.code, self.effect = attempts[len(launched)]
            launched.append(self)

        def wait(self, timeout=None):
            if self.returncode is None:
                self.effect(self.cmd)
                self.returncode = self.code
            return self.returncode

        def poll(self):
            return self.wait()

        def kill(self):
            self.returncode = -9

    subprocess = SimpleNamespace(**vars(render.subprocess))
    subprocess.Popen = Process
    monkeypatch.setattr(render, 'subprocess', subprocess)
    return launched


def _render_paths(cmd):
    return Path(cmd[cmd.index('--export-material') + 1]), Path(cmd[cmd.index('-o') + 1])


def _write_render(cmd):
    ptex, stage = _render_paths(cmd)
    for channel in ('albedo', 'orm'):
        Image.new('RGB', (32, 32), (30, 60, 90)).save(stage / f'{ptex.stem}_{channel}.png')


def _write_preview(cmd):
    candidate = Path(next(a[6:] for a in cmd if a.startswith('--out=')))
    Image.new('RGB', (64, 32), (30, 60, 90)).save(candidate)


def _preview_inputs(cfg):
    inputs = []
    for channel in ('albedo', 'normal', 'orm'):
        path = Path(cfg.output_dir) / f'input_{channel}.png'
        Image.new('RGB', (32, 32)).save(path)
        inputs.append(str(path))
    return inputs


def test_render_retry_cannot_publish_images_from_a_crashed_attempt(cfg, graph, monkeypatch):
    output = Path(cfg.output_dir)
    previous = {'material_albedo.png': b'previous image', 'material.ptex': b'previous source',
                'unrelated.txt': b'keep this'}
    for name, data in previous.items():
        (output / name).write_bytes(data)
    launched = _script_processes(monkeypatch, [(CRASH, _write_render), (0, lambda cmd: None)])

    result = render.render(graph, size=32, cfg=cfg)

    assert not result.ok, 'A successful retry must produce its own images'
    assert not result.images
    assert len(launched) == 2
    assert {p.name: p.read_bytes() for p in output.iterdir()} == previous


def test_preview_retry_cannot_publish_image_from_a_crashed_attempt(cfg, monkeypatch):
    inputs = _preview_inputs(cfg)
    destination = Path(cfg.output_dir) / 'test_preview.png'
    destination.write_bytes(b'previous preview')
    launched = _script_processes(monkeypatch, [(CRASH, _write_preview), (0, lambda cmd: None)])

    result = preview.render_preview(*inputs, cfg=cfg, basename='test')

    assert not result.ok, 'A successful retry must produce its own preview'
    assert result.image is None
    assert len(launched) == 2
    assert destination.read_bytes() == b'previous preview'
    assert not list(Path(cfg.output_dir).glob('.preview-*'))


def test_retry_clears_only_private_attempt_files_and_restores_render_input(cfg, graph, monkeypatch):
    output = Path(cfg.output_dir)
    asset = output / 'keep.png'
    Image.new('RGB', (32, 32)).save(asset)
    original_asset = asset.read_bytes()
    original_graph = copy.deepcopy(graph)

    def crash(cmd):
        ptex, stage = _render_paths(cmd)
        _write_render(cmd)
        ptex.write_text('{}')
        (stage / 'native-buffer').mkdir()
        (stage / 'native-buffer' / 'data.bin').write_bytes(b'failed attempt')
        (stage / 'outside-link').symlink_to(output, target_is_directory=True)
        (stage / 'material.tres').write_text('failed sidecar')

    def succeed(cmd):
        ptex, stage = _render_paths(cmd)
        assert {p.name for p in stage.iterdir()} == {'material.ptex'}
        assert json.loads(ptex.read_text()) == original_graph
        _write_render(cmd)
        (stage / 'material.tres').write_text('native sidecar')

    _script_processes(monkeypatch, [(CRASH, crash), (0, succeed)])
    result = render.render(graph, size=32, cfg=cfg, required_channels=('albedo', 'orm'))

    assert result.ok, result.error
    assert {Path(p).name for p in result.images} == {'material_albedo.png', 'material_orm.png'}
    assert asset.read_bytes() == original_asset
    assert json.loads((output / 'material.ptex').read_text()) == original_graph
    assert graph == original_graph
    assert not (output / 'material.tres').exists()
    assert not list(output.glob('.render-*'))


def test_runner_prepares_each_attempt_before_launch(monkeypatch):
    events = []
    launched = _script_processes(monkeypatch, [
        (CRASH, lambda cmd: events.append('first')),
        (0, lambda cmd: events.append('second')),
    ])

    result = render._run_godot(['godot'], 10, before_attempt=lambda: events.append('prepare'))

    assert result.returncode == 0
    assert len(launched) == 2
    assert events == ['prepare', 'first', 'prepare', 'second']


@pytest.fixture
def asset_source(cfg, graph, catalog):
    source = Path(cfg.output_dir) / 'source'
    source.mkdir()
    asset = source / 'texture.png'
    Image.new('RGB', (32, 32), (10, 20, 30)).save(asset)
    catalog['source']['parameters'].append({'name': 'image', 'type': 'image'})
    graph['nodes'][1]['nodes'][0]['parameters']['image'] = '%PROJECT_PATH%/texture.png'
    return graph, source, asset


def test_policy_resolves_project_path_only_with_explicit_source_origin(cfg, asset_source):
    graph, source, asset = asset_source

    deps = graph_dependencies(graph, cfg, source_dir=str(source))

    assert deps == [{'path': str(asset.resolve()), 'sha256': file_digest(asset),
                     'reference': '%PROJECT_PATH%/texture.png'}]
    with pytest.raises(ServiceError) as error:
        graph_dependencies(graph, cfg)
    assert error.value.code == 'ASSET_PATH_AMBIGUOUS'
    graph['nodes'][1]['nodes'][0]['parameters']['image'] = 'texture.png'
    with pytest.raises(ServiceError) as error:
        graph_dependencies(graph, cfg, source_dir=str(source))
    assert error.value.code == 'ASSET_PATH_AMBIGUOUS'


@pytest.mark.parametrize('origin', ['relative', '', 123, 'missing', 'file', 'outside', 'symlink'])
def test_source_origin_requires_an_existing_approved_absolute_directory(cfg, graph, tmp_path, origin):
    outside = tmp_path / 'outside'
    outside.mkdir()
    regular_file = Path(cfg.output_dir) / 'file.txt'
    regular_file.write_text('not a directory')
    link = Path(cfg.output_dir) / 'link'
    link.symlink_to(outside, target_is_directory=True)
    source = {'relative': 'relative/path', '': '', 123: 123,
              'missing': str(Path(cfg.output_dir) / 'missing'), 'file': str(regular_file),
              'outside': str(outside), 'symlink': str(link)}[origin]

    with pytest.raises(ServiceError) as error:
        graph_dependencies(graph, cfg, source_dir=source)

    assert error.value.code in ('ASSET_SOURCE_DIR', 'ASSET_PATH_DENIED')


@pytest.mark.parametrize('reference', ['%PROJECT_PATH%/../../outside.png', '%PROJECT_PATH%/escape.png'])
def test_project_path_references_cannot_escape_approved_roots(cfg, asset_source, tmp_path, reference):
    graph, source, _ = asset_source
    outside = tmp_path / 'outside.png'
    Image.new('RGB', (32, 32)).save(outside)
    (source / 'escape.png').symlink_to(outside)
    graph['nodes'][1]['nodes'][0]['parameters']['image'] = reference

    with pytest.raises(ServiceError) as error:
        graph_dependencies(graph, cfg, source_dir=str(source))

    assert error.value.code == 'ASSET_PATH_DENIED'


@pytest.mark.parametrize('explicit', [True, False])
def test_render_resolves_project_assets_in_private_copy_and_publishes_original(cfg, asset_source, monkeypatch, explicit):
    graph, source, asset = asset_source
    output = Path(cfg.output_dir) if explicit else source
    original = copy.deepcopy(graph)
    source_file = source / 'original.ptex'
    source_file.write_text(json.dumps(original))
    source_bytes = source_file.read_bytes()
    asset_bytes = asset.read_bytes()

    def native(cmd):
        ptex, stage = _render_paths(cmd)
        staged = json.loads(ptex.read_text())
        assert staged['nodes'][1]['nodes'][0]['parameters']['image'] == str(asset.resolve())
        assert stage != source
        _write_render(cmd)
        # Exporters may update their working graph; this is not the caller's source.
        ptex.write_text('{}')
        (stage / 'material.tres').write_text('native sidecar')

    _script_processes(monkeypatch, [(0, native)])
    kwargs = {'source_dir': str(source)} if explicit else {}
    result = render.render(graph, size=32, outdir=str(output), cfg=cfg, **kwargs)

    assert result.ok, result.error
    assert json.loads((output / 'material.ptex').read_text()) == original
    assert graph == original
    assert source_file.read_bytes() == source_bytes
    assert asset.read_bytes() == asset_bytes
    assert not (output / 'material.tres').exists()


@pytest.mark.parametrize('explicit', [True, False])
def test_render_rejects_source_dependency_changes_before_publication(cfg, asset_source, monkeypatch, explicit):
    graph, source, asset = asset_source
    output = Path(cfg.output_dir) if explicit else source
    destination = output / 'material_albedo.png'
    destination.write_bytes(b'previous image')

    def native(cmd):
        _write_render(cmd)
        Image.new('RGB', (32, 32), (90, 80, 70)).save(asset)

    _script_processes(monkeypatch, [(0, native)])
    kwargs = {'source_dir': str(source)} if explicit else {}
    result = render.render(graph, size=32, outdir=str(output), cfg=cfg, **kwargs)

    assert not result.ok
    assert 'changed' in result.error
    assert destination.read_bytes() == b'previous image'
    assert not (output / 'material.ptex').exists()


def test_raw_graph_build_records_explicit_origin_and_asset_hash(app, baker, asset_source):
    graph, source, asset = asset_source
    original = copy.deepcopy(graph)
    origins = []

    def bake(ptex, **kwargs):
        origins.append(kwargs.get('source_dir'))
        return baker(ptex, **kwargs)

    app.render_fn = bake
    request = {'graph': graph, 'source_dir': str(source), 'size': 32}
    result = app.build(request)
    inputs = json.loads(app.builds.artifact(result['build_id'], 'request.json').read_text())

    assert inputs['source_dir'] == str(source.resolve())
    assert inputs['dependencies'] == [{'path': str(asset.resolve()), 'sha256': file_digest(asset),
                                       'reference': '%PROJECT_PATH%/texture.png'}]
    assert origins == [str(source.resolve())]
    assert json.loads(app.builds.artifact(result['build_id'], 'material.ptex').read_text()) == original
    assert graph == original
    assert app.build(request)['cached']
    Image.new('RGB', (32, 32), (90, 80, 70)).save(asset)
    assert app.build(request)['build_id'] != result['build_id']


def test_build_store_native_render_uses_source_origin_instead_of_build_stage(app, asset_source, monkeypatch):
    graph, source, asset = asset_source

    def native(cmd):
        ptex, _ = _render_paths(cmd)
        assert json.loads(ptex.read_text())['nodes'][1]['nodes'][0]['parameters']['image'] == str(asset.resolve())
        _write_render(cmd)

    _script_processes(monkeypatch, [(0, native)])
    result = app.builds.build(graph, size=32, source_dir=str(source))

    assert result['ok']
    assert json.loads(app.builds.artifact(result['build_id'], 'material.ptex').read_text()) == graph


def test_build_store_native_procedural_render_allows_output_outside_asset_roots(app, cfg, graph, tmp_path, monkeypatch):
    assets = tmp_path / 'assets'
    assets.mkdir()
    cfg.allowed_roots = [str(assets)]
    graph['description'] = '%PROJECT_PATH%/display-only.png'
    _script_processes(monkeypatch, [(0, _write_render)])

    result = app.builds.build(graph, size=32)

    assert result['ok']
    assert app.builds.get(result['build_id'])['status'] == 'complete'
    inputs = json.loads(app.builds.artifact(result['build_id'], 'request.json').read_text())
    assert inputs['source_dir'] is None
    assert inputs['dependencies'] == []
    assert inputs['renderer_kind'] == 'native_material_maker'


def test_render_rejects_explicit_source_outside_asset_roots_without_references(cfg, graph, tmp_path, monkeypatch):
    assets = tmp_path / 'assets'
    assets.mkdir()
    cfg.allowed_roots = [str(assets)]
    launched = _script_processes(monkeypatch, [(0, _write_render)])

    result = render.render(graph, size=32, cfg=cfg, source_dir=cfg.output_dir)

    assert not result.ok
    assert 'outside the allowed roots' in result.error
    assert not launched
    assert not list(Path(cfg.output_dir).glob('material*'))


def test_build_store_does_not_infer_source_origin_from_private_stage(app, asset_source, baker):
    graph, _, _ = asset_source

    with pytest.raises(ServiceError) as error:
        app.builds.build(graph, size=32, render_fn=baker)

    assert error.value.code == 'ASSET_PATH_AMBIGUOUS'
    assert baker.calls == 0


def test_build_rechecks_project_asset_hash_before_publication(app, asset_source, baker):
    graph, source, asset = asset_source

    def bake(ptex, **kwargs):
        result = baker(ptex, **kwargs)
        Image.new('RGB', (32, 32), (90, 80, 70)).save(asset)
        return result

    app.render_fn = bake
    with pytest.raises(ServiceError) as error:
        app.build({'graph': graph, 'source_dir': str(source), 'size': 32})

    assert error.value.code == 'DEPENDENCY_CHANGED'
    assert not list(app.builds.root.glob('b_*'))
    assert not list(app.builds.root.glob('.staging-*'))


@pytest.mark.parametrize('kind', ['recipe', 'project'])
def test_service_rejects_source_origin_on_non_raw_graph_requests(app, cfg, kind):
    request = {'recipe_id': 'fixture'}
    if kind == 'project':
        project = app.instantiate('fixture')
        request = {'project_id': project['project_id'], 'revision': 0}

    with pytest.raises(ServiceError) as error:
        app.build({**request, 'source_dir': cfg.output_dir, 'size': 32})

    assert error.value.code == 'BUILD_SOURCE'


def test_preview_successful_retry_publishes_only_its_own_image(cfg, monkeypatch):
    inputs = _preview_inputs(cfg)
    before = {path: Path(path).read_bytes() for path in inputs}

    def succeed(cmd):
        candidate = Path(next(a[6:] for a in cmd if a.startswith('--out=')))
        assert not candidate.exists()
        Image.new('RGB', (64, 32), (90, 80, 70)).save(candidate)

    _script_processes(monkeypatch, [(CRASH, _write_preview), (0, succeed)])
    result = preview.render_preview(*inputs, cfg=cfg, basename='test')

    assert result.ok, result.error
    with Image.open(result.image) as image:
        assert image.size == (64, 32)
        assert image.getpixel((0, 0)) == (90, 80, 70)
    assert {path: Path(path).read_bytes() for path in inputs} == before


def test_cancellation_between_attempts_does_not_launch_another_process(monkeypatch):
    cancelled = False
    preparations = []

    def crash(cmd):
        nonlocal cancelled
        cancelled = True

    launched = _script_processes(monkeypatch, [(CRASH, crash), (0, lambda cmd: None)])
    with pytest.raises(ServiceError) as error:
        render._run_godot(['godot'], 10, cancel=lambda: cancelled,
                          before_attempt=lambda: preparations.append(True))

    assert error.value.code == 'CANCELLED'
    assert len(launched) == 1
    assert preparations == [True]


def test_running_render_cancellation_kills_and_reaps_worker_without_publication(cfg, graph, monkeypatch):
    events = []
    running = False
    destination = Path(cfg.output_dir) / 'material_albedo.png'
    destination.write_bytes(b'previous image')

    class Process:
        returncode = None

        def __init__(self, cmd, **kwargs):
            nonlocal running
            _write_render(cmd)
            running = True

        def poll(self):
            return self.returncode

        def kill(self):
            events.append('kill')
            self.returncode = -9

        def wait(self, timeout=None):
            events.append('reap')
            return self.returncode

    monkeypatch.setattr(render.subprocess, 'Popen', Process)
    monkeypatch.setattr(render, '_kill_tree', lambda process: events.append('kill_tree'))
    result = render.render(graph, size=32, cfg=cfg, cancel=lambda: running)

    assert not result.ok and 'cancelled' in result.error
    assert events == ['kill_tree', 'kill', 'reap']
    assert destination.read_bytes() == b'previous image'
    assert not list(Path(cfg.output_dir).glob('.render-*'))


def test_render_cancellation_after_native_success_preserves_prior_source_and_maps(cfg, graph, monkeypatch):
    cancelled = False
    output = Path(cfg.output_dir)
    previous = {'material_albedo.png': b'previous image', 'material.ptex': b'previous graph'}
    for name, data in previous.items():
        (output / name).write_bytes(data)

    def native(cmd):
        nonlocal cancelled
        _write_render(cmd)
        cancelled = True

    _script_processes(monkeypatch, [(0, native)])
    result = render.render(graph, size=32, cfg=cfg, cancel=lambda: cancelled)

    assert not result.ok and 'cancelled' in result.error
    assert {p.name: p.read_bytes() for p in output.iterdir()} == previous
