"""Standard-library source launcher; prepare runtime dependencies only as needed."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_HELP = 'Install Python 3.10 or newer from https://www.python.org/downloads/ and reopen Play.'
_RUNTIME_CHECK = """
import sys
from pathlib import Path
from importlib.metadata import version
import mm_mcp.play.server, mcp, dotenv, PIL
def numeric(name):
    return tuple(int(part) for part in version(name).split('.')[:2])
assert (2, 0) <= numeric('mcp') < (3, 0)
assert (10, 4) <= numeric('Pillow') < (13, 0)
assert numeric('python-dotenv') >= (1, 0)
assert Path(mm_mcp.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve() / 'src')
"""


def venv_python(root):
    return Path(root) / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def runtime_ready(python, root):
    try:
        return subprocess.run([str(python), '-c', _RUNTIME_CHECK, str(root)], cwd=root,
                              capture_output=True, timeout=30, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def prepare_runtime(root):
    root = Path(root)
    python = venv_python(root)
    if not python.is_file():
        print('Preparing the local Python environment...')
        subprocess.run([sys.executable, '-m', 'venv', str(root / '.venv')], cwd=root, check=True)
    if runtime_ready(python, root):
        return python
    print('Installing Material Workshop runtime dependencies...')
    pip = subprocess.run([str(python), '-m', 'pip', '--version'], cwd=root, capture_output=True, check=False)
    if pip.returncode:
        # uv-created environments may have all runtime packages but no pip.
        # Bootstrap pip only after the runtime probe actually needs an install.
        subprocess.run([str(python), '-m', 'ensurepip', '--upgrade'], cwd=root, check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-e', str(root)], cwd=root, check=True)
    if not runtime_ready(python, root):
        raise RuntimeError('The local runtime is still incomplete. Check the installation output above, then retry Play.')
    return python


def find_supported_python():
    """Finder/desktop PATHs often omit Homebrew or python.org installations."""
    candidates = []
    for directory in ('/opt/homebrew/bin', '/usr/local/bin', ''):
        for name in ('python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3', 'python'):
            candidate = str(Path(directory) / name) if directory else shutil.which(name)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    framework = Path('/Library/Frameworks/Python.framework/Versions')
    if framework.is_dir():
        candidates.extend(str(path / 'bin/python3') for path in list(framework.iterdir())[:32])
    for candidate in candidates:
        try:
            result = subprocess.run([candidate, '-c', 'import sys;sys.exit(sys.version_info < (3,10))'],
                                    capture_output=True, timeout=5, check=False)
            if result.returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.version_info < (3, 10):
        python = find_supported_python()
        if python:
            return subprocess.run([python, str(Path(__file__).resolve()), *argv], cwd=ROOT).returncode
        print(PYTHON_HELP, file=sys.stderr)
        return 1
    try:
        python = prepare_runtime(ROOT)
        return subprocess.run([str(python), '-m', 'mm_mcp.play.server', *argv], cwd=ROOT).returncode
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f'Workshop could not start: {exc}', file=sys.stderr)
        print('Check your network connection if dependencies need installation. ' + PYTHON_HELP, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
