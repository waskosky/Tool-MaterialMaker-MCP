"""Atomic local graph editing, persistent revisions, snapshots and retry safety.

SQLite's write transaction is the synchronization boundary across browser/MCP
processes. No native Godot objects or sockets are exposed in this layer.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import time
import unicodedata
import uuid
from mm_mcp.core import ServiceError, MAX_OPERATIONS, canonical, digest, identifier, finite
from mm_mcp.play.sliders import resolve_node, apply_values
from mm_mcp.validator import validate_graph


def _snapshot_name(name):
    # Labels live only in SQLite. Slashes and punctuation have no path meaning.
    if (not isinstance(name,str) or not name.strip() or len(name)>128
            or any(unicodedata.category(char).startswith('C') for char in name)):
        raise ServiceError('SNAPSHOT_NAME','Snapshot name must be 1–128 readable characters without control characters.')
    return name


def _scope(graph, path=''):
    node = resolve_node(graph, path) if path else graph
    if node.get('type', 'graph') != 'graph':
        raise ServiceError('NOT_GRAPH', f'{path} is not a subgraph.')
    return node

def apply_patch(graph: dict, operations: list, catalog: dict, *, mode='strict') -> tuple[dict, list]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise ServiceError('PATCH_LIMIT', f'Provide between 1 and {MAX_OPERATIONS} operations.')
    out, changes = copy.deepcopy(graph), []
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            raise ServiceError('INVALID_OPERATION', f'Operation {index} must be an object.')
        kind = op.get('op'); path = op.get('path', op.get('name', ''))
        try:
            if kind == 'set_controls':
                out = apply_values(out, op['values'], strict=True, catalog=catalog)
            elif kind in ('set_param', 'set_parameters'):
                node = resolve_node(out, path)
                params = op['parameters']
                if not isinstance(params, dict):
                    raise ServiceError('PARAMETER_TYPE', 'parameters must be an object.')
                if node.get('type') == 'graph':
                    out = apply_values(out, {f'{path}/{k}': v for k,v in params.items()}, strict=True, catalog=catalog)
                else:
                    node.setdefault('parameters', {}).update(copy.deepcopy(params))
            elif kind == 'add_node':
                scope = _scope(out, op.get('scope', ''))
                name = op.get('name') or f"{op.get('node_type', 'node')}_{index}"
                identifier(name, 'node name')
                if any(n.get('name') == name for n in scope.get('nodes', [])):
                    raise ServiceError('DUPLICATE_NODE', f'Node already exists: {name}')
                node = copy.deepcopy(op.get('node') or {'type': op['node_type'], 'parameters': op.get('parameters', {})})
                node['name'] = name
                node.setdefault('node_position', {'x': op.get('x', 0), 'y': op.get('y', 0)})
                scope.setdefault('nodes', []).append(node)
            elif kind == 'delete_node':
                parent, _, name = path.rpartition('/')
                scope = _scope(out, parent); resolve_node(out, path)
                scope['nodes'] = [n for n in scope['nodes'] if n.get('name') != name]
                scope['connections'] = [c for c in scope.get('connections', []) if c.get('from') != name and c.get('to') != name]
                # Remove exposed links to deleted nodes rather than retain dangling bindings.
                for n in scope['nodes']:
                    if n.get('type') == 'remote':
                        for w in n.get('widgets', []):
                            w['linked_widgets'] = [l for l in w.get('linked_widgets', []) if l.get('node','').split('/')[0] != name]
            elif kind in ('reposition_node', 'move_node'):
                if not finite(op['x']) or not finite(op['y']):
                    raise ServiceError('POSITION_TYPE', 'Node positions must be finite.')
                resolve_node(out, path)['node_position'] = {'x': op['x'], 'y': op['y']}
            elif kind == 'set_label':
                if not isinstance(op['label'], str) or len(op['label']) > 512:
                    raise ServiceError('LABEL_LIMIT', 'Label must be a string of at most 512 characters.')
                resolve_node(out, path)['label'] = op['label']
            elif kind in ('connect_nodes', 'disconnect_nodes'):
                scope = _scope(out, op.get('scope', ''))
                edge = {'from': op['from_name'], 'from_port': op['from_port'],
                        'to': op['to_name'], 'to_port': op['to_port']}
                edges = scope.setdefault('connections', [])
                if kind == 'connect_nodes':
                    if op.get('replace', False):
                        edges[:] = [e for e in edges if not(e.get('to') == edge['to'] and e.get('to_port', 0) == edge['to_port'])]
                    edges.append(edge)
                elif edge not in edges:
                    raise ServiceError('CONNECTION_NOT_FOUND', 'The requested connection does not exist.')
                else:
                    edges.remove(edge)
            elif kind == 'set_seed':
                if type(op['seed']) is not int or not 0 <= op['seed'] <= 2147483647:
                    raise ServiceError('SEED_RANGE', 'Seed must be a nonnegative 31-bit integer.')
                seed_node = resolve_node(out, path) if path else out
                seed_node.pop('seed', None)
                seed_node['seed_int'] = op['seed']
            else:
                raise ServiceError('UNKNOWN_OPERATION', f'Unknown operation {kind!r}.')
        except (KeyError, TypeError) as exc:
            raise ServiceError('INVALID_OPERATION', f'Operation {index} has missing or malformed fields.', index=index) from exc
        changes.append({'index': index, 'op': kind, 'path': path})
    # GraphStore supplies this baseline from the same write transaction that
    # checks the revision. Legacy import fields cannot be newly introduced.
    problems = validate_graph(out, catalog, mode=mode, preserve_unknown_from=graph)
    if any(p['severity'] == 'error' for p in problems):
        raise ServiceError('VALIDATION_FAILED', 'Patch leaves an invalid graph; no changes were committed.', problems=problems)
    return out, changes

class GraphStore:
    def __init__(self, root: str | Path, catalog: dict):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.path, self.catalog = self.root/'state.sqlite3', catalog
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, title TEXT NOT NULL, revision INTEGER NOT NULL,
                    graph TEXT NOT NULL, cursor INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS history(project TEXT, seq INTEGER, graph TEXT NOT NULL, label TEXT,
                    PRIMARY KEY(project, seq));
                CREATE TABLE IF NOT EXISTS receipts(project TEXT, key TEXT, request_hash TEXT, result TEXT,
                    PRIMARY KEY(project, key));
                CREATE TABLE IF NOT EXISTS snapshots(project TEXT, name TEXT, graph TEXT, revision INTEGER,
                    PRIMARY KEY(project, name));
            """)
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=30000')
        try:
            with db:
                yield db
        finally:
            db.close()
    def create(self, graph, title='Untitled'):
        problems = validate_graph(graph, self.catalog, mode='import')
        if any(p['severity']=='error' for p in problems):
            raise ServiceError('VALIDATION_FAILED', 'Cannot create project from invalid graph.', problems=problems)
        pid, raw = 'p_' + uuid.uuid4().hex, canonical(graph)
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)', (pid, str(title)[:512], 0, raw, 0, time.time()))
            db.execute('INSERT INTO history VALUES(?,?,?,?)', (pid, 0, raw, 'Created'))
        return self.read(pid)
    def _row(self, db, pid):
        identifier(pid)
        row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if row is None:
            raise ServiceError('PROJECT_NOT_FOUND', 'Project not found.')
        return row
    @staticmethod
    def _result(row):
        return {'ok':True, 'project_id':row['id'], 'title':row['title'], 'revision':row['revision'],
                'graph':json.loads(row['graph']), 'graph_hash':digest(json.loads(row['graph']))}
    def read(self, pid):
        with self.connect() as db:
            return self._result(self._row(db, pid))
    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,title,revision,created FROM projects ORDER BY created DESC')]
    def patch(self, pid, expected_revision, operations, idempotency_key, *, dry_run=False, authorize=None):
        identifier(idempotency_key, 'idempotency key')
        if type(expected_revision) is not int:
            raise ServiceError('REVISION_REQUIRED', 'expected_revision must be an integer.')
        request_hash = digest({'revision':expected_revision,'operations':operations,'dry_run':dry_run})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt = db.execute('SELECT * FROM receipts WHERE project=? AND key=?', (pid,idempotency_key)).fetchone()
            if receipt:
                if receipt['request_hash'] != request_hash:
                    raise ServiceError('IDEMPOTENCY_CONFLICT', 'The key was already used for a different request.')
                return json.loads(receipt['result'])
            row = self._row(db, pid)
            if row['revision'] != expected_revision:
                raise ServiceError('REVISION_CONFLICT', 'Project changed; read it before retrying.', actual_revision=row['revision'])
            graph, changes = apply_patch(json.loads(row['graph']), operations, self.catalog)
            if authorize is not None:
                authorize(graph)
            result = {'ok':True, 'project_id':pid, 'revision':expected_revision if dry_run else expected_revision+1,
                      'status':'planned' if dry_run else 'committed', 'graph_hash':digest(graph), 'changes':changes}
            if dry_run:
                result['graph'] = graph
                return result
            raw, cursor = canonical(graph), row['cursor']+1
            db.execute('DELETE FROM history WHERE project=? AND seq>?', (pid,row['cursor']))
            db.execute('INSERT INTO history VALUES(?,?,?,?)', (pid,cursor,raw,'Patch'))
            db.execute('UPDATE projects SET graph=?,revision=revision+1,cursor=? WHERE id=?', (raw,cursor,pid))
            db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (pid,idempotency_key,request_hash,canonical(result)))
        return result
    def history_step(self, pid, expected_revision, direction):
        if direction not in ('undo','redo'):
            raise ServiceError('DIRECTION', 'Use undo or redo.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); row=self._row(db,pid)
            if row['revision'] != expected_revision:
                raise ServiceError('REVISION_CONFLICT','Read the current revision first.')
            cursor=row['cursor']+(-1 if direction=='undo' else 1)
            target=db.execute('SELECT graph FROM history WHERE project=? AND seq=?',(pid,cursor)).fetchone()
            if target is None:
                raise ServiceError('HISTORY_EMPTY',f'Nothing to {direction}.')
            db.execute('UPDATE projects SET graph=?,revision=revision+1,cursor=? WHERE id=?',(target['graph'],cursor,pid))
            return self._result(self._row(db,pid))
    def snapshot(self, pid, name):
        _snapshot_name(name)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); row=self._row(db,pid)
            try:
                db.execute('INSERT INTO snapshots VALUES(?,?,?,?)',(pid,name,row['graph'],row['revision']))
            except sqlite3.IntegrityError as exc:
                raise ServiceError('SNAPSHOT_EXISTS','Snapshot names are immutable; choose a new name.') from exc
        return {'ok':True,'project_id':pid,'name':name,'revision':row['revision']}
    def snapshots(self,pid):
        with self.connect() as db:
            self._row(db,pid)
            return [dict(row) for row in db.execute(
                'SELECT name,revision FROM snapshots WHERE project=? ORDER BY name COLLATE BINARY',(pid,))]
    def restore(self,pid,name,expected_revision):
        _snapshot_name(name)
        if type(expected_revision) is not int:
            raise ServiceError('REVISION_REQUIRED','expected_revision must be an integer.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE'); row=self._row(db,pid)
            if row['revision'] != expected_revision:
                raise ServiceError('REVISION_CONFLICT','Read the current revision first.')
            snap=db.execute('SELECT graph FROM snapshots WHERE project=? AND name=?',(pid,name)).fetchone()
            if snap is None:
                raise ServiceError('SNAPSHOT_NOT_FOUND','Snapshot not found.')
            cursor=row['cursor']+1
            db.execute('DELETE FROM history WHERE project=? AND seq>?',(pid,row['cursor']))
            db.execute('INSERT INTO history VALUES(?,?,?,?)',(pid,cursor,snap['graph'],'Restore '+name))
            db.execute('UPDATE projects SET graph=?,revision=revision+1,cursor=? WHERE id=?',(snap['graph'],cursor,pid))
            return self._result(self._row(db,pid))
