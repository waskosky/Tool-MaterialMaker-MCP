"""Create or repair native .env paths without changing artist/workspace settings."""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def ask(prompt, key):
    from mm_mcp.setup import normalize_path
    while True:
        try:
            return normalize_path(input(prompt), key)
        except ValueError as exc:
            print(exc)

def write_env(path, values):
    """Preserve every unrelated binding, comment, blank line and newline."""
    from dotenv.parser import parse_stream
    with path.open(encoding='utf-8', newline='') if path.exists() else io.StringIO('') as stream:
        original = stream.read()
    pending = dict(values)
    parts = []
    for binding in parse_stream(io.StringIO(original)):
        if binding.key not in values:
            parts.append(binding.original.string)
        elif binding.key in pending:
            newline = '\r\n' if binding.original.string.endswith('\r\n') else '\n'
            parts.append(f'{binding.key}={json.dumps(pending.pop(binding.key))}{newline}')
    content = ''.join(parts)
    if pending and content and not content.endswith('\n'):
        content += '\n'
    content += ''.join(f'{key}={json.dumps(value)}\n' for key, value in pending.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--godot-binary')
    parser.add_argument('--project-path')
    args = parser.parse_args(argv)
    if args.offline:
        # No third-party import or native path is needed to choose offline use.
        args.env_file.parent.mkdir(parents=True, exist_ok=True)
        if not args.env_file.exists():
            with args.env_file.open('x', encoding='utf-8') as stream:
                stream.write('# Offline Workshop: configure native paths in the browser when ready.\n')
        print(f'Offline browsing is ready. Existing configuration at {args.env_file} is preserved.')
        return 0
    from mm_mcp.setup import validated_settings
    try:
        values = validated_settings({
            'godot_binary': args.godot_binary or ask('Godot executable (or Godot.app): ', 'godot_binary'),
            'project_path': args.project_path or ask('Material Maker source checkout directory: ', 'project_path'),
        })
        write_env(args.env_file, {'MM_GODOT_BINARY': values['godot_binary'], 'MM_PROJECT_PATH': values['project_path']})
    except (OSError, ValueError) as exc:
        print(f'Configuration was not saved: {exc}', file=sys.stderr)
        return 1
    print(f'Updated native paths in {args.env_file}. Restart Workshop to load these .env values.')
    if any(key in os.environ for key in ('MM_GODOT_BINARY', 'MM_PROJECT_PATH')):
        print('MM_GODOT_BINARY/MM_PROJECT_PATH environment variables take precedence over .env entries.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
