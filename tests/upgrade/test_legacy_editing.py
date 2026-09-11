"""Imported legacy fields may survive edits; authoring new invalid fields cannot."""
import copy
import json
from pathlib import Path

import pytest

from mm_mcp.core import ServiceError
from mm_mcp.play.sliders import resolve_node
from mm_mcp.validator import validate_graph


@pytest.fixture
def legacy_project(app, cfg, graph):
    resolve_node(graph, 'Material')['parameters'].update(
        ao_light_affect=1, normal_scale=1, subsurf_scatter_strength=0)
    resolve_node(graph, 'surface/src')['parameters']['old_source_hint'] = {'value': 3}
    Path(cfg.cookbook_dir, 'test', 'fixture.ptex').write_text(json.dumps(graph))
    return app.instantiate('fixture')


def test_seed_and_declared_control_edits_preserve_legacy_source_and_receipts(app, legacy_project):
    project = legacy_project
    pid = project['project_id']
    operations = [{'op': 'set_seed', 'seed': 73022},
                  {'op': 'set_controls', 'values': {'surface/param0': 13}}]
    result = app.patch(pid, 0, operations, 'legacy-edit')
    assert result['revision'] == 1
    assert app.patch(pid, 0, operations, 'legacy-edit') == result
    after = app.read_project(pid)['graph']
    assert after['seed_int'] == 73022
    assert resolve_node(after, 'surface/src')['parameters']['gain'] == 13
    for path in ['Material', 'surface/src']:
        old = resolve_node(project['graph'], path)['parameters']
        new = resolve_node(after, path)['parameters']
        for key in ['ao_light_affect', 'normal_scale', 'subsurf_scatter_strength', 'old_source_hint']:
            if key in old:
                assert new[key] == old[key]
    # The ordinary authoring validator retains its strict public contract.
    assert any(p['severity'] == 'error' for p in validate_graph(after, app.catalog, mode='strict'))


def test_legacy_project_can_be_saved_and_reopened_as_personal_recipe(app, legacy_project):
    saved = app.save_recipe(legacy_project['project_id'], 'legacy_personal')
    reopened = app.instantiate(saved['id'])
    assert reopened['graph'] == legacy_project['graph']
    app.patch(reopened['project_id'], 0, [{'op': 'set_seed', 'seed': 7}], 'personal-edit')


@pytest.mark.parametrize('operation', [
    {'op': 'set_parameters', 'path': 'Material', 'parameters': {'new_typo': 1}},
    {'op': 'set_parameters', 'path': 'Material', 'parameters': {'normal_scale': 2}},
    {'op': 'set_parameters', 'path': 'Material', 'parameters': {'normal_scale': True}},
    {'op': 'set_parameters', 'path': 'surface/src', 'parameters': {'old_source_hint': {'value': 4}}},
    {'op': 'add_node', 'name': 'extra', 'node_type': 'material', 'parameters': {'normal_scale': 1}},
    {'op': 'set_parameters', 'path': 'surface/src', 'parameters': {'gain': True}},
    {'op': 'set_parameters', 'path': 'surface/src', 'parameters': {'mode': 100}},
    {'op': 'connect_nodes', 'from_name': 'surface', 'from_port': 0, 'to_name': 'Material', 'to_port': 0},
    {'op': 'add_node', 'name': 'injected', 'node': {'type': 'source', 'custom_export_script': 'unapproved'}},
    {'op': 'add_node', 'name': 'injected_shader', 'node': {'type': 'shader', 'shader_model': {
        'inputs': [], 'outputs': [], 'parameters': [], 'code': 'unapproved'}}},
])
def test_legacy_compatibility_does_not_admit_new_invalid_authoring(app, legacy_project, operation):
    before = app.read_project(legacy_project['project_id'])
    with pytest.raises(ServiceError):
        app.patch(before['project_id'], 0,
                  [{'op': 'set_seed', 'seed': 73022}, copy.deepcopy(operation)], 'bad-legacy-edit')
    assert app.read_project(before['project_id']) == before


@pytest.mark.parametrize('count', [500, 501, 1000])
@pytest.mark.parametrize('parameters', [{'roughness': True}, {'zz_new_typo': 1}])
def test_legacy_warning_limit_cannot_hide_new_authoring_errors(app, cfg, graph, count, parameters):
    resolve_node(graph, 'Material')['parameters'].update({f'legacy_{i:04}': i for i in range(count)})
    Path(cfg.cookbook_dir, 'test', 'fixture.ptex').write_text(json.dumps(graph))
    before = app.instantiate('fixture')
    with pytest.raises(ServiceError) as error:
        app.patch(before['project_id'], 0,
                  [{'op': 'set_parameters', 'path': 'Material', 'parameters': parameters}], 'overflow-edit')
    assert any(p['severity'] == 'error' for p in error.value.details['problems'])
    assert app.read_project(before['project_id']) == before


def test_import_warning_limit_cannot_hide_a_later_invalid_declared_value(graph, catalog):
    values = {f'legacy_{i:04}': i for i in range(500)}
    values['roughness'] = True
    resolve_node(graph, 'Material')['parameters'] = values
    problems = validate_graph(graph, catalog, mode='import')
    assert len(problems) <= 500
    assert any(p['severity'] == 'error' for p in problems)
