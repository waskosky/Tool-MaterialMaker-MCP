"""Visual workflow contracts; PNGs come only from the explicit injected baker."""
import io
import json
import os
from pathlib import Path
import threading

from PIL import Image
import pytest

from mm_mcp.core import ServiceError, digest
from mm_mcp.jobs import JobQueue
from mm_mcp.service import MaterialService
from tests.upgrade.test_http import call


def test_recipe_friendly_guide_fallback_preserves_identity(app):
    path = app.recipes.find('fixture')[2]
    guide = ('# fixture — Weathered stone\n\n'
             '_Category: test. Open the graph: `fixture.ptex`._\n\n'
             'Soft **weathering** across a cool stone surface.\n'
             'The gain control changes its grain.\n\n## Recipe\n\nLater details.')
    path.with_suffix('.md').write_text(guide)
    recipe = app.recipes.describe('fixture')
    assert recipe['id'] == recipe['name'] == 'fixture'
    assert recipe['display_name'] == 'Weathered stone'
    assert recipe['description'] == 'Soft weathering across a cool stone surface. The gain control changes its grain.'
    assert recipe['guide'] == guide and recipe['metadata'] == {}
    assert app.materials()['materials'][0]['display_name'] == recipe['display_name']


def test_cookbook_heading_removes_exact_id_with_underscores(app):
    path = app.recipes.find('fixture')[2]
    path.rename(path.with_name('stone_fixture.ptex'))
    path.with_name('stone_fixture.md').write_text('# stone_fixture - Cool stone\n\nA readable surface.')
    assert app.recipes.describe('stone_fixture')['display_name'] == 'Cool stone'


def test_metadata_names_and_description_are_searchable(app, graph):
    recipe = app.recipes.save('quiet', graph, {
        'display_name': 'Copper patina', 'description': 'Weathered verdigris highlights.',
        'tags': ['oxidized'],
    }, '# Different guide title\n\nA guide description.')
    assert recipe['display_name'] == 'Copper patina'
    assert recipe['description'] == 'Weathered verdigris highlights.'
    for query in ('Copper', 'verdigris', 'oxidized'):
        assert app.materials(query)['materials'][0]['id'] == 'user.quiet'
    assert app.recipes.describe('fixture')['display_name'] == 'Fixture'


def test_project_read_exposes_recipe_origin_without_approval(app, graph, http_service):
    project = app.instantiate('fixture')
    assert project['title'] == 'Fixture' and project['recipe_id'] == 'fixture'
    read = app.read_project(project['project_id'])
    assert read['recipe_id'] == 'fixture' and read['controls']
    assert not any('approved' in key or 'provenance' in key for key in read)
    assert call(http_service, '/api/projects/' + project['project_id'])[2] == read
    imported = app.graphs.create(graph)
    assert app.read_project(imported['project_id'])['recipe_id'] is None


def test_readable_snapshots_list_and_restore_as_new_revision(app, http_service):
    project = app.instantiate('fixture'); pid = project['project_id']
    app.graphs.snapshot(pid, 'Base / cool stone')
    app.patch(pid, 0, [{'op': 'set_controls', 'values': {'surface/param0': 13}}], 'edit-stone')
    app.graphs.snapshot(pid, 'Ébauche – warm')
    app.graphs.snapshot(pid, 'ASCII_legacy-01')
    expected = [
        {'name': 'ASCII_legacy-01', 'revision': 1},
        {'name': 'Base / cool stone', 'revision': 0},
        {'name': 'Ébauche – warm', 'revision': 1},
    ]
    assert app.graphs.snapshots(pid) == expected
    code, _, body = call(http_service, f'/api/projects/{pid}/snapshots')
    assert code == 200 and body == {'ok': True, 'project_id': pid, 'snapshots': expected}
    with pytest.raises(ServiceError, match='immutable'):
        app.graphs.snapshot(pid, 'Base / cool stone')
    with pytest.raises(ServiceError) as error:
        app.graphs.restore(pid, 'Base / cool stone', 0)
    assert error.value.code == 'REVISION_CONFLICT'
    restored = app.graphs.restore(pid, 'Base / cool stone', 1)
    assert restored['revision'] == 2 and restored['graph_hash'] == project['graph_hash']


@pytest.mark.parametrize('name', ['', '   ', 'x' * 129, 'bad\nname', 'bad\x00name', 17])
def test_snapshot_names_are_bounded_readable_labels(app, name):
    project = app.instantiate('fixture')
    with pytest.raises(ServiceError) as error:
        app.graphs.snapshot(project['project_id'], name)
    assert error.value.code == 'SNAPSHOT_NAME'


def test_gallery_uses_authenticated_real_cached_albedo_without_baking(app, baker, http_service):
    first = call(http_service, '/api/materials')[2]['materials'][0]
    assert first['thumbnail'] is None and baker.calls == 0
    built = app.build({'recipe_id': 'fixture', 'size': 32})
    row = call(http_service, '/api/materials?q=fixture&category=test')[2]['materials'][0]
    assert row['thumbnail'] == {
        'build_id': built['build_id'], 'url': f"/api/builds/{built['build_id']}/thumbnail.png",
        'renderer_kind': 'injected_test_double',
    }
    url = row['thumbnail']['url']
    assert call(http_service, url, headers={'X-MM-Token': ''})[0] == 401
    code, headers, data = call(http_service, url)
    assert code == 200 and headers['Content-Type'] == 'image/png'
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (128, 128) and image.getpixel((0, 0)) == (7, 80, 120)
    assert call(http_service, url)[2] == data
    assert app.materials(category='absent')['materials'] == []
    assert baker.calls == 1


@pytest.mark.parametrize('kind', ['missing', 'corrupt'])
def test_missing_or_corrupt_build_removes_cached_gallery_thumbnail(app, baker, http_service, kind):
    built = app.build({'recipe_id': 'fixture', 'size': 32})
    url = app.materials()['materials'][0]['thumbnail']['url']
    assert call(http_service, url)[0] == 200
    image = app.builds.directory(built['build_id']) / 'material_albedo.png'
    if kind == 'missing':
        image.unlink()
    else:
        image.write_bytes(b'corrupt preview')
    assert call(http_service, '/api/materials')[2]['materials'][0]['thumbnail'] is None
    assert call(http_service, url)[0] == 404
    assert baker.calls == 1


def test_edited_project_preview_is_associated_only_with_original_recipe_version(app, cfg, catalog, baker):
    project = app.instantiate('fixture'); pid = project['project_id']
    app.patch(pid, 0, [{'op': 'set_controls', 'values': {'surface/param0': 13}}], 'edit-preview')
    built = app.build({'project_id': pid, 'revision': 1, 'size': 32})
    assert app.materials()['materials'][0]['thumbnail']['build_id'] == built['build_id']
    request = json.loads(app.builds.artifact(built['build_id'], 'request.json').read_text())
    assert request['provenance']['recipe_id'] == 'fixture'
    assert request['provenance']['recipe_version'] == app.recipes.describe('fixture')['recipe_version']
    app.close()
    reopened = MaterialService(cfg, catalog, render_fn=baker)
    try:
        assert reopened.materials()['materials'][0]['thumbnail']['build_id'] == built['build_id']
        path = reopened.recipes.find('fixture')[2]
        graph = json.loads(path.read_text()); graph['label'] = 'Changed recipe version'
        path.write_text(json.dumps(graph))
        assert reopened.materials()['materials'][0]['thumbnail'] is None
        assert baker.calls == 1
    finally:
        reopened.close()


def test_gallery_discovers_preexisting_completed_build_without_repeated_scan(app, baker, monkeypatch):
    graph, origin = app.recipes.instantiate('fixture')
    built = app.builds.build(graph, material_id='fixture', size=32, provenance=origin,
                             trusted_recipe=True, render_fn=baker)
    assert app.materials()['materials'][0]['thumbnail']['build_id'] == built['build_id']
    original_scandir = os.scandir
    def unexpected_scan(path, *args, **kwargs):
        if Path(path) == app.builds.root:
            raise AssertionError('Gallery scanned build directories again')
        return original_scandir(path, *args, **kwargs)
    monkeypatch.setattr('mm_mcp.thumbnails.os.scandir', unexpected_scan)
    assert app.materials()['materials'][0]['thumbnail']['build_id'] == built['build_id']
    assert baker.calls == 1


def test_preview_index_failure_cannot_fail_successful_build(app, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('Preview index unavailable')
    monkeypatch.setattr(app.thumbnails, 'record', unavailable)
    built = app.build({'recipe_id': 'fixture', 'size': 32})
    assert built['ok'] and app.builds.get(built['build_id'])['status'] == 'complete'


def test_corrupt_optional_preview_index_does_not_prevent_startup_or_render(app, cfg, catalog, baker):
    app.close()
    app.thumbnails.path.write_bytes(b'corrupt optional preview index')
    reopened = MaterialService(cfg, catalog, render_fn=baker)
    try:
        built = reopened.build({'recipe_id': 'fixture', 'size': 32})
        assert built['ok']
        assert reopened.materials()['materials'][0]['thumbnail'] is None
        assert reopened.thumbnails.image(built['build_id']).startswith(b'\x89PNG')
    finally:
        reopened.close()


def test_legacy_project_build_discovers_origin_and_newest_completed_preview(app, baker):
    older = app.build({'recipe_id': 'fixture', 'size': 32})
    project = app.instantiate('fixture', {'surface/param0': 13})
    built = app.builds.build(project['graph'], material_id=project['project_id'], size=32,
                             provenance={'project_id': project['project_id'], 'revision': 0},
                             trusted_recipe=True, render_fn=baker)
    assert app.materials()['materials'][0]['thumbnail']['build_id'] == built['build_id']
    assert built['build_id'] != older['build_id']


def test_repeated_gallery_queries_reuse_unchanged_artifact_verification(app, monkeypatch):
    app.build({'recipe_id': 'fixture', 'size': 32})
    assert app.materials()['materials'][0]['thumbnail']
    original_get = app.builds.get
    calls = []
    def tracked_get(build_id):
        calls.append(build_id)
        return original_get(build_id)
    monkeypatch.setattr(app.builds, 'get', tracked_get)
    assert app.materials()['materials'][0]['thumbnail']
    assert not calls


def test_saved_recipe_reuses_only_matching_current_project_preview(app):
    project = app.instantiate('fixture'); pid = project['project_id']
    built = app.build({'project_id': pid, 'revision': 0, 'size': 32})
    saved = app.save_recipe(pid, 'saved_preview')
    assert app.materials('saved_preview')['materials'][0]['thumbnail']['build_id'] == built['build_id']
    app.patch(pid, 0, [{'op': 'set_controls', 'values': {'surface/param0': 13}}], 'edit-saved')
    app.save_recipe(pid, 'without_preview')
    assert app.materials('without_preview')['materials'][0]['thumbnail'] is None
    assert saved['source'] == 'user'


def test_selected_family_candidate_becomes_saved_recipe_preview_without_rebaking(app, baker, monkeypatch):
    app.jobs.close(); monkeypatch.setattr(app.jobs, 'start', lambda: None)
    app.jobs.stop_event.clear()
    candidate = app.family('fixture', count=1, seed=17, ranges={'gain': [8, 16]},
                            size=32, build=True)['candidates'][0]
    assert app.jobs.run_one()
    job = app.jobs.get(candidate['job']['job_id'])
    assert job['state'] == 'complete', job
    project = app.instantiate('fixture', candidate['values'])
    assert project['graph_hash'] == candidate['graph_hash']
    saved = app.save_recipe(project['project_id'], 'selected_stone')
    row = next(row for row in app.materials()['materials'] if row['id'] == saved['id'])
    assert row['thumbnail']['build_id'] == job['result']['build_id']
    assert row['thumbnail']['renderer_kind'] == 'injected_test_double'
    assert baker.calls == 1


def test_saved_recipe_does_not_reuse_another_recipe_version_with_identical_graph(app, baker):
    app.build({'recipe_id': 'fixture', 'size': 32})
    path = app.recipes.find('fixture')[2]
    path.with_suffix('.recipe.json').write_text(json.dumps({'description': 'New recipe revision'}))
    project = app.instantiate('fixture')
    saved = app.save_recipe(project['project_id'], 'new_recipe_version')
    row = next(row for row in app.materials()['materials'] if row['id'] == saved['id'])
    assert row['thumbnail'] is None
    assert baker.calls == 1


def test_family_atomic_capacity_and_scale(app, monkeypatch):
    app.jobs.close(); monkeypatch.setattr(app.jobs, 'start', lambda: None)
    app.jobs.stop_event.clear()
    app.jobs.max_pending = 2
    existing = app.jobs.submit({'recipe_id': 'fixture', 'size': 32})
    with pytest.raises(ServiceError) as error:
        app.family('fixture', count=2, build=True, size=32, physical_size_m=2.5)
    assert error.value.code == 'QUEUE_FULL'
    with app.jobs._db() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
    app.jobs.cancel(existing['job_id'])
    family = app.family('fixture', count=2, ranges={'gain': [2, 9]}, build=True,
                        size=32, target='unity', physical_size_m=2.5)
    with app.jobs._db() as db:
        rows = db.execute("SELECT request FROM jobs WHERE state='queued' ORDER BY created").fetchall()
    assert len(rows) == len(family['candidates']) == 2
    for row, candidate in zip(rows, family['candidates']):
        request = json.loads(row['request'])
        assert request['physical_size_m'] == 2.5 and request['target'] == 'unity'
        assert candidate['values'] == request['values']
        graph, _ = app.recipes.instantiate('fixture', candidate['values'])
        assert candidate['graph_hash'] == digest(graph)
        app.jobs.run_one()
        result = app.jobs.get(candidate['job']['job_id'])['result']
        assert result['ok'], result
        target = json.loads(app.builds.artifact(result['build_id'], 'target.json').read_text())
        assert target['physical_size_m'] == 2.5


@pytest.mark.parametrize('fields,code', [
    ({'size': 257}, 'INVALID_RESOLUTION'), ({'target': 'unknown'}, 'TARGET'),
    ({'physical_size_m': 0}, 'PHYSICAL_SCALE'), ({'physical_size_m': float('nan')}, 'PHYSICAL_SCALE'),
    ({'physical_size_m': True}, 'PHYSICAL_SCALE'), ({'count': 33}, 'VARIATION_LIMIT'),
])
def test_invalid_family_settings_never_queue(app, fields, code):
    with pytest.raises(ServiceError) as error:
        app.family('fixture', build=True, **fields)
    assert error.value.code == code
    with app.jobs._db() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


@pytest.mark.parametrize('requests', [[], [{}] * 33, [{'size': 32}, {'size': float('nan')}], [{}, []]])
def test_batch_validates_every_serialized_request_before_admission(tmp_path, requests, monkeypatch):
    queue = JobQueue(tmp_path, lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(queue, 'start', lambda: None)
    with pytest.raises(ServiceError):
        queue.submit_many(requests)
    with queue._db() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


def test_batch_waits_for_setup_idle_transaction(tmp_path, monkeypatch):
    queue = JobQueue(tmp_path, lambda *args, **kwargs: {'ok': True})
    monkeypatch.setattr(queue, 'start', lambda: None)
    started = threading.Event(); finished = threading.Event(); result = []
    def submit():
        started.set()
        result.extend(queue.submit_many([{'size': 32}, {'size': 64}]))
        finished.set()
    with queue.idle_transaction():
        thread = threading.Thread(target=submit); thread.start()
        assert started.wait(1) and not finished.wait(.1)
    thread.join(2)
    assert finished.is_set() and len(result) == 2
