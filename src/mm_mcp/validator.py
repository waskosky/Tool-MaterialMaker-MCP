"""Bounded import and strict-authoring validation; errors are always data.

Numeric min/max values are editor hints, not shader clamps. This module does
not guess arbitrary port coercions. It checks catalog and inline interfaces.
"""
from collections import deque
from mm_mcp.catalog_builder import SPECIAL_TYPES, _parse_generic_node
from mm_mcp.core import MAX_DEPTH, MAX_NODES, canonical, finite


def _definition(node, catalog):
    if node.get("type") == "graph":
        return _parse_generic_node(node, "graph")
    if isinstance(node.get('shader_model'), dict):
        return node['shader_model']
    entry = catalog.get(node.get('type'))
    if entry and entry.get('input_template'):
        size = node.get('generic_size', entry.get('generic_size', 1))
        if type(size) is int and 1 <= size <= 128:
            entry = dict(entry)
            entry['inputs'] = [dict(p) for p in entry['input_template']
                               for _ in range(size if '#' in str(p.get('name', '')) else 1)]
    return entry


def validate_graph(ptex, catalog: dict, _path: str = '', *, mode: str = 'import',
                   max_nodes: int = MAX_NODES, max_depth: int = MAX_DEPTH) -> list[dict]:
    problems = []
    strict = mode == 'strict'
    def report(where, message, severity='error', code='INVALID_GRAPH'):
        if len(problems) < 500:
            problems.append(dict(severity=severity, where=where, message=message, code=code))
    if mode not in ('strict', 'import'):
        report('', 'mode must be strict or import'); return problems
    try:
        if len(canonical(ptex).encode()) > 8 * 1024 * 1024:
            report('', 'graph exceeds 8 MiB'); return problems
    except ValueError as exc:
        report('', str(exc)); return problems
    count = 0
    def walk(g, path, depth):
        nonlocal count
        if depth > max_depth:
            report(path, 'graph nesting limit exceeded'); return
        if not isinstance(g, dict):
            report(path, 'graph must be an object'); return
        nodes, edges = g.get('nodes', []), g.get('connections', [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            report(path, 'nodes and connections must be arrays'); return
        count += len(nodes)
        if count > max_nodes or len(edges) > max_nodes * 16:
            report(path, 'graph complexity limit exceeded'); return
        by_name = {}
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                report(path, f'node {i} must be an object'); continue
            name, t = n.get('name'), n.get('type')
            where = f'{path}/{name or i}'.strip('/')
            if not isinstance(name, str) or not name or any(c in name for c in '/\\') or name in ('.', '..'):
                report(where, 'node requires a non-empty, path-safe name'); continue
            if name in by_name:
                report(where, 'duplicate node name', code='DUPLICATE_NODE')
            by_name[name] = n
            if not isinstance(t, str) or (t not in catalog and t not in SPECIAL_TYPES and t != 'portal'):
                report(where, f"unknown node type '{t}'"); continue
            try:
                definition = _definition(n, catalog)
            except (TypeError, KeyError, AttributeError):
                report(where, 'malformed node interface'); definition = None
            params = n.get('parameters', {})
            if not isinstance(params, dict):
                report(where, 'parameters must be an object'); continue
            if 'generic_size' in n and (type(n['generic_size']) is not int or not 1 <= n['generic_size'] <= 128):
                report(where, 'generic_size must be an integer from 1 through 128')
            if definition:
                declared = {p.get('name'): p for p in definition.get('parameters', []) if isinstance(p, dict)}
                for key, value in params.items():
                    spec = declared.get(key)
                    if spec is None:
                        report(where, f"unknown parameter '{key}'", 'error' if strict else 'warning'); continue
                    typ = spec.get('type')
                    invalid = ((typ in ('float', 'int', 'size', 'enum') and not finite(value)) or
                               (typ in ('int', 'size', 'enum') and finite(value) and int(value) != value) or
                               (typ in ('boolean', 'bool') and type(value) is not bool))
                    if invalid:
                        report(where, f"parameter '{key}' requires a finite {typ}"); continue
                    if typ == 'color':
                        if not isinstance(value, dict) or not all(finite(value.get(c)) for c in ('r', 'g', 'b', 'a')):
                            report(where, f"parameter '{key}' requires numeric r/g/b/a")
                    if typ == 'gradient':
                        from mm_mcp.play.sliders import validate_values
                        try:
                            validate_values([{'id': key, 'kind': 'gradient'}], {key: value})
                        except ValueError as exc:
                            report(where, f"parameter '{key}': {exc}")
                    if finite(value):
                        low, high = spec.get('min'), spec.get('max')
                        outside = (finite(low) and value < low) or (finite(high) and value > high)
                        if typ == 'enum' and isinstance(spec.get('values'), list):
                            outside |= value < 0 or value >= len(spec['values'])
                        if outside:
                            msg = 'invalid enum index' if typ == 'enum' else 'outside editor range; not shader-clamped'
                            report(where, f"parameter '{key}': {msg}", 'error' if strict and typ == 'enum' else 'warning')
            if t == 'graph':
                walk(n, where, depth + 1)
        incoming, adjacency = set(), {name: set() for name in by_name}
        indegree = {name: 0 for name in by_name}
        for i, c in enumerate(edges):
            where = f'{path}/connection[{i}]'.strip('/')
            if not isinstance(c, dict):
                report(where, 'connection must be an object'); continue
            src, dst = c.get('from'), c.get('to')
            if not isinstance(src, str) or not isinstance(dst, str):
                report(where, 'connection endpoints must be names'); continue
            for name in (src, dst):
                if name not in by_name:
                    report(where, f"connection references missing node '{name}'")
            a, b = c.get('from_port', 0), c.get('to_port', 0)
            if type(a) is not int or type(b) is not int or a < 0 or b < 0:
                report(where, 'from_port and to_port indices must be nonnegative integers'); continue
            if (dst, b) in incoming:
                report(where, 'multiple connections to one input', 'error' if strict else 'warning')
            incoming.add((dst, b))
            for name, port, side in ((src, a, 'outputs'), (dst, b, 'inputs')):
                if name not in by_name:
                    continue
                try:
                    spec = _definition(by_name[name], catalog)
                except (TypeError, KeyError, AttributeError):
                    spec = None
                if spec and port >= len(spec.get(side, [])):
                    report(where, f"{name}: port {port} out of range for {side}")
            if src in adjacency and dst in adjacency and dst not in adjacency[src]:
                # Stateful buffer feedback requires native evaluation; do not invent its semantics.
                if by_name[src].get('type') == 'buffer' or by_name[dst].get('type') == 'buffer':
                    if strict:
                        report(where, 'stateful buffer feedback is not certified', 'warning', 'NATIVE_CHECK')
                else:
                    adjacency[src].add(dst); indegree[dst] += 1
        q = deque(k for k, v in indegree.items() if v == 0); visited = 0
        while q:
            k = q.popleft(); visited += 1
            for target in adjacency[k]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    q.append(target)
        if visited != len(indegree):
            report(path, 'cycle in stateless node connections', 'error' if strict else 'warning', 'CYCLE')
    try:
        walk(ptex, _path, 0)
    except (TypeError, AttributeError, KeyError, RecursionError, OverflowError) as exc:
        report(_path, f'malformed graph structure: {type(exc).__name__}')
    return problems
