"""Small, transport-independent contracts. No renderer or MCP imports."""
from __future__ import annotations
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_NODES = 4096
MAX_DEPTH = 24
MAX_OPERATIONS = 500

class ServiceError(ValueError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code, self.details = code, details
    def result(self) -> dict:
        return {"ok": False, "error": str(self), "code": self.code, **self.details}

def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ServiceError("INVALID_JSON", "Values must be finite JSON data.") from exc

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def file_digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def parse_json(raw: str | bytes) -> Any:
    if len(raw) > MAX_JSON_BYTES:
        raise ServiceError("LIMIT", "JSON request exceeds 8 MiB.")
    def reject(value):
        raise ServiceError("INVALID_JSON", f"Non-finite number {value} is not permitted.")
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ServiceError("INVALID_JSON", f"Duplicate JSON key: {k}")
            out[k] = v
        return out
    try:
        value = json.loads(raw, parse_constant=reject, object_pairs_hook=pairs)
        canonical(value)  # Also catches finite-looking literals that overflow, e.g. 1e9999.
        return value
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        if isinstance(exc, ServiceError):
            raise
        raise ServiceError("INVALID_JSON", "Invalid or excessively nested JSON.") from exc

def identifier(value: str, what: str = "identifier") -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value) or '..' in value:
        raise ServiceError("INVALID_ID", f"Invalid {what}; use letters, numbers, underscores, dots and hyphens.")
    return value

def resolution(value: int, maximum: int = 2048) -> int:
    if type(value) is not int or value < 32 or value > maximum or value & (value - 1):
        raise ServiceError("INVALID_RESOLUTION", f"Resolution must be a power of two between 32 and {maximum}.")
    return value

def finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)

def atomic_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(canonical(value)); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

@contextlib.contextmanager
def file_lock(path: str | Path, timeout: float = 190.0, cancel=None):
    """Advisory OS lock, released on process death. All local workers must cooperate."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+b') as f:
        if f.tell() == 0:
            f.write(b'0'); f.flush()
        deadline = time.monotonic() + timeout
        while True:
            if cancel and cancel():
                raise ServiceError("CANCELLED", "Operation cancelled while waiting for the resource lock.")
            try:
                f.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ServiceError("BUSY", "Another local worker holds the resource lock.")
                time.sleep(.05)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
