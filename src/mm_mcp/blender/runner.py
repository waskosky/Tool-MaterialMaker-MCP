"""Private, cancellable, output/time-bounded fixed Blender process boundary."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from mm_mcp.core import ServiceError


def private_environment(profile):
    profile = Path(profile)
    # Do not inherit session tokens, Python injection paths, user addon settings,
    # or dynamic-library injection settings from the HTTP/MCP service process.
    env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'LANG') if key in os.environ}
    env['PYTHONNOUSERSITE'] = '1'
    for key, folder in [('BLENDER_USER_CONFIG', 'config'), ('BLENDER_USER_SCRIPTS', 'scripts'), ('BLENDER_USER_DATAFILES', 'datafiles'), ('BLENDER_USER_EXTENSIONS', 'extensions'), ('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp')]:
        path = profile / folder
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return env


def _kill(process):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=3)


def run_process(command, *, cwd, env, timeout=600, max_output=1024 * 1024, cancel=None):
    """Internal process helper; callers cannot provide a command through any API."""
    if cancel and cancel():
        raise ServiceError('CANCELLED', 'Blender operation cancelled before launch.')
    # This write end stays owned by the service. On a hard service crash, EOF
    # reaches the fixed worker's guard even though its process group is detached.
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               **({'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}))
    chunks = bytearray()
    exceeded = threading.Event()

    def drain():
        total = 0
        while True:
            block = os.read(process.stdout.fileno(), 16384)
            if not block:
                break
            total += len(block)
            chunks.extend(block)
            del chunks[:-65536]
            if total > max_output:
                exceeded.set()
    reader = threading.Thread(target=drain, name='mm-blender-output', daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if cancel and cancel():
                raise ServiceError('CANCELLED', 'Blender operation cancelled; worker process cleaned up.')
            if exceeded.is_set():
                raise ServiceError('BLENDER_OUTPUT_LIMIT', 'Blender exceeded its bounded log budget.')
            if time.monotonic() >= deadline:
                raise ServiceError('BLENDER_TIMEOUT', 'Blender timed out; worker process cleaned up.')
            time.sleep(.025)
        reader.join(timeout=1)
        if exceeded.is_set():
            raise ServiceError('BLENDER_OUTPUT_LIMIT', 'Blender exceeded its bounded log budget.')
        output = chunks.decode('utf-8', errors='replace')
        if process.returncode:
            raise ServiceError('BLENDER_EXIT', 'Blender worker exited without completing its operation.', exit_code=process.returncode, log_tail=output[-4096:])
        return output
    finally:
        _kill(process)
        reader.join(timeout=2)
        process.stdout.close()
        process.stdin.close()


def run_worker(request_path, output_dir, *, binary, cancel=None):
    output_dir = Path(output_dir).resolve()
    with tempfile.TemporaryDirectory(prefix='.profile-', dir=output_dir.parent) as profile:
        command = [str(Path(binary).resolve()), '--background', '--factory-startup', '--disable-autoexec', '--offline-mode',
                   '--threads', '2', '--python-exit-code', '23', '--python', str(Path(__file__).with_name('worker.py')),
                   '--', str(Path(request_path).resolve()), str(output_dir)]
        env = private_environment(profile)
        env['MM_BLENDER_PARENT_PID'] = str(os.getpid())
        output = run_process(command, cwd=profile, env=env, cancel=cancel)
        (output_dir / 'worker.log').write_text(output, encoding='utf-8')
