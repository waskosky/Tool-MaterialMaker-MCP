"""Private local discovery and authenticated identity checks for launcher reuse.

The record contains a bearer token, so it is never a public status document.
Probes exchange nonce-bound HMACs instead of sending that token to a listener
which may have replaced a previous Workshop process on the same local port.
"""
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import stat

from mm_mcp.config import settings_path
from mm_mcp.core import atomic_json, canonical, file_lock, parse_json

APPLICATION = 'material-workshop'
_FIELDS = {'application', 'session', 'workspace', 'port', 'token'}


def identity(session_id, root):
    return {'application': APPLICATION, 'session': session_id,
            'workspace': os.path.normcase(str(Path(root).resolve()))}


def workspace(cfg):
    return os.path.normcase(str(Path(cfg.workspace_dir or Path(cfg.output_dir) / 'workspace').resolve()))


def session_path(cfg):
    key = hashlib.sha256(f'{workspace(cfg)}\n{cfg.play_port}'.encode()).hexdigest()[:32]
    return settings_path().parent / 'sessions' / (key + '.json')


def _private(path, directory=False):
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        return False
    return os.name == 'nt' or (info.st_uid == os.getuid() and info.st_mode & 0o077 == 0)


def _valid(record, cfg):
    return (isinstance(record, dict) and set(record) == _FIELDS
            and record['application'] == APPLICATION and record['workspace'] == workspace(cfg)
            and type(record['port']) is int and record['port'] == cfg.play_port
            and isinstance(record['session'], str) and re.fullmatch(r'[a-f0-9]{32}', record['session']) is not None
            and isinstance(record['token'], str) and re.fullmatch(r'[A-Za-z0-9_-]{32,256}', record['token']) is not None)


def write_session(cfg, token, session_id):
    record = {**identity(session_id, workspace(cfg)), 'port': cfg.play_port, 'token': token}
    if not _valid(record, cfg):
        raise ValueError('Invalid local session record.')
    path = session_path(cfg)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not _private(path.parent, directory=True):
        raise OSError('Session discovery directory must be private and owned by the current user.')
    with file_lock(path.with_suffix('.lock'), timeout=2):
        atomic_json(path, record)
    return record


def read_session(cfg):
    path = session_path(cfg)
    try:
        if not _private(path.parent, directory=True) or not _private(path) or path.stat().st_size > 4096:
            return None
        record = parse_json(path.read_bytes())
        return record if _valid(record, cfg) else None
    except (OSError, ValueError):
        return None


def remove_session(cfg, session_id):
    path = session_path(cfg)
    if not path.parent.exists():
        return
    with file_lock(path.with_suffix('.lock'), timeout=2):
        record = read_session(cfg)
        if record and hmac.compare_digest(record['session'], session_id):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _proof(token, text):
    return hmac.new(token.encode(), text.encode(), hashlib.sha256).hexdigest()


def probe_proof(token, session_id, nonce):
    return _proof(token, f'workshop-session-request:{session_id}:{nonce}')


def response_proof(token, nonce, session_identity):
    return _proof(token, 'workshop-session-response:' + nonce + ':' + canonical(session_identity))


def authenticated_probe(headers, token, session_id):
    nonce = headers.get('X-MM-Session-Nonce', '')
    proof = headers.get('X-MM-Session-Proof', '')
    return (re.fullmatch(r'[a-f0-9]{64}', nonce) is not None
            and re.fullmatch(r'[a-f0-9]{64}', proof) is not None
            and hmac.compare_digest(proof, probe_proof(token, session_id, nonce)))


def find_session(cfg):
    record = read_session(cfg)
    if record is None:
        return None
    nonce = secrets.token_hex(32)
    expected = identity(record['session'], workspace(cfg))
    # A fixed loopback address, HTTPConnection, and explicit 200 acceptance
    # exclude record-provided URLs, environment proxies, and HTTP redirects.
    connection = http.client.HTTPConnection('127.0.0.1', cfg.play_port, timeout=2)
    try:
        connection.request('GET', '/api/session', headers={
            'X-MM-Session-Nonce': nonce,
            'X-MM-Session-Proof': probe_proof(record['token'], record['session'], nonce),
        })
        response = connection.getresponse()
        if response.status != 200:
            return None
        raw = response.read(4097)
        if len(raw) > 4096:
            return None
        result = parse_json(raw)
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
            return None
        proof = result.get('proof', '')
        if not isinstance(proof, str) or re.fullmatch(r'[a-f0-9]{64}', proof) is None:
            return None
        return record if hmac.compare_digest(proof, response_proof(record['token'], nonce, expected)) else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def launch_url(cfg, token):
    return f'http://127.0.0.1:{cfg.play_port}/#token={token}'
