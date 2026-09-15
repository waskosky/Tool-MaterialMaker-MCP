"""Portable contracts joining upstream catalog resolution to fork validation."""
import json
from types import SimpleNamespace

from mm_mcp import catalog_builder
from mm_mcp.validator import validate_graph


def _write(directory, name, data):
    path = directory / (name + '.mmg')
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


def _leaf():
    return {'generic_size': 2, 'shader_model': {
        'inputs': [{'name': 'input#', 'type': 'rgba'}],
        'outputs': [{'type': 'rgba'}],
        'parameters': [{'name': 'choice', 'type': 'enum', 'default': 0,
                        'values': [{'name': 'Add', 'value': '1'},
                                   {'name': 'Multiply', 'value': '-3'}]}]}}


def _compound(inner_type, default):
    return {'nodes': [
        {'type': 'ios', 'name': 'gen_inputs', 'ports': []},
        {'type': 'ios', 'name': 'gen_outputs', 'ports': [{'type': 'rgba'}]},
        {'type': inner_type, 'name': 'inner'},
        {'type': 'remote', 'parameters': {'choice': default}, 'widgets': [
            {'name': 'choice', 'linked_widgets': [{'node': 'inner', 'widget': 'choice'}]}]}]}


def test_compound_chains_preserve_outer_defaults_and_enum_hints(tmp_path, monkeypatch):
    files = [_write(tmp_path, 'outer', _compound('middle', 1)),
             _write(tmp_path, 'middle', _compound('leaf', 0)),
             _write(tmp_path, 'leaf', _leaf())]
    catalogs = []
    for order in (files, list(reversed(files))):
        monkeypatch.setattr(catalog_builder, 'glob', SimpleNamespace(glob=lambda _: order))
        catalogs.append(catalog_builder.build_catalog(str(tmp_path)))
    assert catalogs[0] == catalogs[1]
    outer = catalogs[0]['outer']['parameters'][0]
    assert outer['default'] == 1
    assert (outer['min'], outer['max']) == (0, 1)
    graph = {'nodes': [{'name': 'n', 'type': 'outer', 'parameters': {'choice': -3}}]}
    problems = validate_graph(graph, catalogs[0])
    assert any(p['severity'] == 'error' and "index 1 'Multiply'" in p['message']
               for p in problems)


def test_generic_inputs_remain_expandable_per_graph_instance(tmp_path):
    _write(tmp_path, 'leaf', _leaf())
    catalog = catalog_builder.build_catalog(str(tmp_path))
    graph = {'nodes': [{'name': 'source', 'type': 'leaf'},
                       {'name': 'target', 'type': 'leaf', 'generic_size': 3}],
             'connections': [{'from': 'source', 'from_port': 0, 'to': 'target', 'to_port': 2}]}
    assert not validate_graph(graph, catalog, mode='strict')
    graph['connections'][0]['to_port'] = 3
    assert any('port 3 out of range' in p['message'] for p in validate_graph(graph, catalog))
