"""Explicit browser hosting policy; proxy headers never grant authority."""
import ipaddress
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


def mount_path(value, name='MM_BASE_PATH'):
    """Require an unambiguous, same-origin directory path."""
    if (not isinstance(value, str) or len(value) > 512 or
            re.fullmatch(r'/(?:[A-Za-z0-9._~-]+/)*', value) is None or
            any(part in ('.', '..') for part in value.split('/'))):
        raise ValueError(f'{name} must be / or a canonical /segments/ path without traversal or encoding.')
    if name == 'MM_BASE_PATH' and value.startswith(('/api/', '/static/')):
        raise ValueError('MM_BASE_PATH must not overlap the reserved /api/ or /static/ routes.')
    return value


def public_origin(value):
    """Accept one HTTPS origin or an explicit HTTP loopback origin, never a URL path."""
    error = 'MM_PUBLIC_ORIGIN must be an HTTPS host origin or HTTP loopback origin, without a path, query, fragment or credentials.'
    if not isinstance(value, str) or not value or re.search(r'[\s\\%]', value):
        raise ValueError(error)
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (parsed.scheme not in ('http', 'https') or not host or parsed.path or
                parsed.query or parsed.fragment or parsed.username is not None or
                parsed.password is not None or any(mark in value for mark in ('?', '#')) or
                (port is not None and not 1 <= port <= 65535)):
            raise ValueError(error)
        if parsed.scheme == 'http' and host not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError(error)
        if ':' in host:
            host = '[' + str(ipaddress.IPv6Address(host)) + ']'
        elif re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', host.split('.')[-1]):
            # Browsers reinterpret abbreviated/integer IPv4 hosts. Accept only
            # their literal canonical form so the allowlist matches the URL.
            host = str(ipaddress.IPv4Address(host))
        elif (len(host) > 253 or any(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) is None
                                    for label in host.split('.'))):
            raise ValueError(error)
        authority = host + (f':{port}' if port is not None else '')
        # Reject parsing ambiguities such as an empty port or abbreviated IP.
        if value.lower() != f'{parsed.scheme}://{authority}':
            raise ValueError(error)
        if port == (443 if parsed.scheme == 'https' else 80):
            authority = host
        return f'{parsed.scheme}://{authority}'
    except (ValueError, TypeError) as exc:
        raise ValueError(error) from exc


def read_managed_token(filename):
    """Read one bounded secret from a private regular file without following a link."""
    error = 'MM_SESSION_TOKEN_FILE must be a private regular file owned by the current user containing one 64-character hexadecimal token.'
    try:
        path = Path(filename).expanduser()
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(error)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino) or
                    (os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
                raise ValueError(error)
            raw = handle.read(67)
        if re.fullmatch(rb'[a-fA-F0-9]{64}(?:\r?\n)?', raw) is None:
            raise ValueError(error)
        return raw.rstrip(b'\r\n').decode('ascii')
    except (OSError, ValueError, TypeError) as exc:
        # Never include file contents (or lower-level errors) in logs.
        raise ValueError(error) from None


def browser_url(cfg):
    return (cfg.public_origin or f'http://127.0.0.1:{cfg.play_port}') + cfg.base_path


def request_path(raw, base_path):
    """Normalize only the configured mount; also accept stripped/local API routes.

    Reject ambiguous input before decoding. No forwarded path/origin headers are
    consulted: the same handler supports direct loopback and a path-stripping proxy.
    """
    if (not raw.startswith('/') or re.search(r'\\|\s|[\x00-\x1f\x7f]', raw) or
            re.search(r'%(?:2f|5c|25)', raw, re.I) or re.search(r'%(?![0-9a-fA-F]{2})', raw)):
        raise ValueError('Invalid request path.')
    decoded = unquote(raw, errors='strict')
    if ('//' in decoded or any(part in ('.', '..') for part in decoded.split('/')) or
            re.search(r'[\x00-\x1f\x7f]', decoded)):
        raise ValueError('Invalid request path.')
    if base_path != '/' and decoded.startswith(base_path):
        return '/' + decoded[len(base_path):]
    return decoded
