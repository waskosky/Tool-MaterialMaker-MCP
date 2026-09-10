"""Small regressions found while integrating the supplied 0.8 alpha archive."""
import copy
import json
from pathlib import Path
import threading

import pytest

from mm_mcp.core import ServiceError
from mm_mcp.jobs import JobQueue
from mm_mcp.play.sliders import resolve_node
from mm_mcp.service import MaterialService


def test_raw_graph_build_applies_controls_to_exported_source(app, graph):
    original = copy.deepcopy(graph)
    built = app.build({'graph': graph, 'values': {'surface/param0': 13}, 'size': 32})
    exported = json.loads(app.builds.artifact(built['build_id'], 'material.ptex').read_text())
    assert resolve_node(exported, 'surface/src')['parameters']['gain'] == 13
    assert graph == original


def test_raw_graph_build_rejects_unknown_controls_before_render(app, graph, baker):
    with pytest.raises(ServiceError, match='Unknown control'):
        app.build({'graph': graph, 'values': {'missing/param0': 13}, 'size': 32})
    assert baker.calls == 0


def test_personal_recipe_retains_approved_code_across_service_restart(app, cfg, catalog, baker, graph):
    graph['nodes'].append({'name': 'approved', 'type': 'shader', 'parameters': {},
                           'shader_model': {'inputs': [], 'outputs': [], 'parameters': []}})
    Path(cfg.cookbook_dir, 'test', 'fixture.ptex').write_text(json.dumps(graph))
    project = app.instantiate('fixture')
    saved = app.save_recipe(project['project_id'], 'personal_shader')
    reopened = MaterialService(cfg, catalog, render_fn=baker)
    try:
        personal = reopened.instantiate(saved['id'], {'gain': 13})
        assert resolve_node(personal['graph'], 'surface/src')['parameters']['gain'] == 13
        assert reopened.build({'recipe_id': saved['id'], 'size': 32})['ok']
        reopened.patch(personal['project_id'], 0,
                       [{'op': 'set_controls', 'values': {'surface/param0': 14}}], 'edit-personal')
        assert reopened.build({'project_id': personal['project_id'], 'revision': 1, 'size': 32})['ok']
        # Client-supplied recipe metadata cannot approve a different definition.
        graph['nodes'][-1]['shader_model']['code'] = 'unapproved'
        reopened.recipes.save('forged', graph, {'approved_shader_hashes': ['anything']})
        with pytest.raises(ServiceError, match='Inline shader definitions'):
            reopened.instantiate('user.forged')
    finally:
        reopened.close()


@pytest.mark.parametrize('field', ['custom_script', 'custom_export_script'])
def test_cookbook_project_cannot_add_unapproved_code(app, field):
    project = app.instantiate('fixture')
    with pytest.raises(ServiceError, match='Custom export code'):
        app.patch(project['project_id'], 0, [{'op': 'add_node', 'name': 'injected',
                   'node': {'type': 'source', field: 'unapproved code'}}], 'inject-code')
    assert app.read_project(project['project_id']) == project


def test_shared_service_resumes_persisted_jobs(cfg, catalog, baker, monkeypatch):
    pending = JobQueue(cfg.workspace_dir, lambda **kwargs: None, max_pending=1)
    monkeypatch.setattr(pending, 'start', lambda: None)
    job = pending.submit({'recipe_id': 'fixture', 'size': 32})
    resumed = threading.Event()

    def render(graph, **kwargs):
        result = baker(graph, **kwargs)
        resumed.set()
        return result

    service = MaterialService(cfg, catalog, render_fn=render)
    try:
        assert resumed.wait(2), 'Persisted queued work did not resume on service startup'
    finally:
        service.close()
        pending.close()
    assert service.jobs.get(job['job_id'])['state'] in ('complete', 'cancelled')
