"""Track in-flight adapter work independently of optional MCP dependencies."""
from contextlib import contextmanager
import threading
import time

_LOCK = threading.Lock()
_ACTIVE = 0
_LAST = time.monotonic()

@contextmanager
def operation():
    global _ACTIVE, _LAST
    with _LOCK:
        _ACTIVE += 1
        _LAST = time.monotonic()
    try:
        yield
    finally:
        with _LOCK:
            _ACTIVE -= 1
            _LAST = time.monotonic()

def recent_or_active(grace_seconds=1.0):
    with _LOCK:
        return _ACTIVE > 0 or time.monotonic() - _LAST < grace_seconds
