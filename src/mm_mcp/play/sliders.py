"""Typed exposed controls with hierarchical addressing and complete fan-out."""
import copy
from mm_mcp.core import ServiceError, canonical, finite

_KIND = {'float':'float', 'int':'int', 'size':'int', 'enum':'enum',
         'boolean':'bool', 'bool':'bool', 'color':'color', 'gradient':'gradient'}

def resolve_node(graph: dict, path: str) -> dict:
    if not isinstance(path, str) or not path or any(p in ('', '.', '..') for p in path.split('/')):
        raise ServiceError('NODE_PATH', 'Expected a hierarchical node path.')
    current = graph
    for part in path.split('/'):
        matches = [n for n in current.get('nodes', []) if n.get('name') == part]
        if len(matches) != 1:
            raise ServiceError('NODE_NOT_FOUND', f'Expected exactly one node at {path}.')
        current = matches[0]
    return current

def _remote_widgets(node):
    return [w for n in node.get('nodes', []) if n.get('type') == 'remote'
            for w in n.get('widgets', []) if isinstance(w, dict)]

def _spec(node, widget, catalog):
    for link in widget.get('linked_widgets', []):
        try:
            inner = resolve_node(node, link.get('node', ''))
        except ServiceError:
            continue
        definition = inner.get('shader_model') or catalog.get(inner.get('type'), {})
        for p in definition.get('parameters', []):
            if p.get('name') == link.get('widget'):
                return p
    return {}

def derive_sliders(graph: dict, catalog: dict) -> list[dict]:
    out = []
    def walk(g, prefix=''):
        for node in g.get('nodes', []):
            if node.get('type') != 'graph':
                continue
            path = '/'.join(filter(None, (prefix, node.get('name', ''))))
            for w in _remote_widgets(node):
                slot = w.get('name')
                if not slot:
                    continue
                spec = _spec(node, w, catalog)
                value = node.get('parameters', {}).get(slot, spec.get('default'))
                typ = spec.get('type')
                # An installed catalog is preferred, but recipes remain browsable offline.
                if typ is None:
                    typ = ('gradient' if isinstance(value, dict) and 'points' in value else
                           'color' if isinstance(value, dict) and all(k in value for k in 'rgba') else
                           'boolean' if type(value) is bool else 'float' if finite(value) else 'json')
                bindings = [{'node': f"{path}/{l['node']}", 'widget': l['widget']}
                            for l in w.get('linked_widgets', []) if l.get('node') and l.get('widget')]
                out.append({'id': f'{path}/{slot}', 'subgraph': path,
                            'group': node.get('label') or path, 'slot_id': slot,
                            'label': w.get('shortdesc') or w.get('label') or slot,
                            'kind': _KIND.get(typ, 'json'),
                            'min': spec.get('min'), 'max': spec.get('max'),
                            'step': spec.get('step'), 'options': spec.get('values', []),
                            'value': copy.deepcopy(value), 'binding': {'node': path, 'widget': slot},
                            'bindings': bindings})
            walk(node, path)
    walk(graph)
    return out

def validate_values(specs: list[dict], values: dict, *, enforce_ranges: bool = False) -> dict:
    if not isinstance(values, dict):
        raise ServiceError('INVALID_PARAMETERS', 'Control values must be an object keyed by control ID.')
    canonical(values)
    known = {s['id']: s for s in specs}
    def rgba(v):
        return isinstance(v, dict) and all(finite(v.get(k)) and 0 <= v[k] <= 1 for k in 'rgba')
    for key, value in values.items():
        if key not in known:
            raise ServiceError('UNKNOWN_CONTROL', f'Unknown control: {key}')
        s = known[key]; kind = s['kind']
        if kind in ('float', 'int', 'enum'):
            if not finite(value) or kind in ('int','enum') and int(value) != value:
                raise ServiceError('PARAMETER_TYPE', f'{key} requires a finite {kind}.')
            if kind == 'enum' and s.get('options') and not 0 <= value < len(s['options']):
                raise ServiceError('ENUM_RANGE', f'{key} has an invalid enum index.')
            if enforce_ranges or kind == 'enum':
                if finite(s.get('min')) and value < s['min'] or finite(s.get('max')) and value > s['max']:
                    raise ServiceError('PARAMETER_RANGE', f'{key} is outside the configured control range.')
        elif kind == 'bool' and type(value) is not bool:
            raise ServiceError('PARAMETER_TYPE', f'{key} requires a boolean.')
        elif kind == 'color' and not rgba(value):
            raise ServiceError('PARAMETER_TYPE', f'{key} requires r/g/b/a values between zero and one.')
        elif kind == 'gradient':
            points = value.get('points') if isinstance(value, dict) else None
            if (not isinstance(points, list) or not 2 <= len(points) <= 64 or
                any(not rgba(p) or not finite(p.get('pos')) or not 0 <= p['pos'] <= 1 for p in points) or
                any(a['pos'] > b['pos'] for a,b in zip(points, points[1:])) or
                type(value.get('interpolation', 1)) is not int or not 0 <= value.get('interpolation', 1) <= 4):
                raise ServiceError('GRADIENT_TYPE', f'{key} needs 2–64 ordered color stops and an interpolation index.')
    return copy.deepcopy(values)

def apply_values(graph: dict, values: dict, *, strict: bool = False, catalog: dict | None = None) -> dict:
    out = copy.deepcopy(graph)
    specs = derive_sliders(out, catalog or {})
    if strict:
        validate_values(specs, values)
    def set_control(sub, slot, value, visited):
        marker = (id(sub), slot)
        if marker in visited:
            raise ServiceError('CONTROL_CYCLE', 'Exposed controls form a cycle.')
        visited = visited | {marker}
        sub.setdefault('parameters', {})[slot] = copy.deepcopy(value)
        widgets = [w for w in _remote_widgets(sub) if w.get('name') == slot]
        for n in sub.get('nodes', []):
            if n.get('type') == 'remote' and any(w.get('name') == slot for w in n.get('widgets', [])):
                n.setdefault('parameters', {})[slot] = copy.deepcopy(value)
        for w in widgets:
            for link in w.get('linked_widgets', []):
                target = resolve_node(sub, link['node'])
                target.setdefault('parameters', {})[link['widget']] = copy.deepcopy(value)
                if target.get('type') == 'graph':
                    set_control(target, link['widget'], value, visited)
    known = {s['id']: s for s in specs}
    for key, value in values.items():
        if key in known:
            s = known[key]
            set_control(resolve_node(out, s['subgraph']), s['slot_id'], value, set())
    return out
