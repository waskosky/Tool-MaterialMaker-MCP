"""Actual bounded subprocess tests use Python, never Blender/GPU processes."""
import json
import os
from pathlib import Path
import sys
import time

import pytest
from mm_mcp.core import ServiceError


def test_process_output_is_captured_without_inheriting_secrets(tmp_path, monkeypatch):
    from mm_mcp.blender.runner import private_environment, run_process
    monkeypatch.setenv('MM_SESSION_TOKEN', 'private-token-must-not-be-inherited')
    monkeypatch.setenv('PYTHONPATH', 'untrusted-addon-directory')
    env = private_environment(tmp_path)
    result = run_process([sys.executable, '-c', 'import os,json; print(json.dumps(dict(os.environ)))'], cwd=tmp_path, env=env, timeout=5)
    inherited = json.loads(result)
    assert 'MM_SESSION_TOKEN' not in inherited and 'PYTHONPATH' not in inherited
    assert inherited['BLENDER_USER_CONFIG'] == str(tmp_path / 'config')
    assert inherited['BLENDER_USER_SCRIPTS'] == str(tmp_path / 'scripts')
    assert inherited['BLENDER_USER_EXTENSIONS'] == str(tmp_path / 'extensions')


@pytest.mark.parametrize('kind,code', [('timeout', 'BLENDER_TIMEOUT'), ('output', 'BLENDER_OUTPUT_LIMIT'), ('nonzero', 'BLENDER_EXIT'), ('cancel', 'CANCELLED')])
def test_process_limits_and_cleanup(tmp_path, kind, code):
    from mm_mcp.blender.runner import run_process
    started = time.monotonic()
    source = 'import time; time.sleep(30)'
    if kind == 'output':
        source = 'import sys; sys.stdout.write("x"*200000); sys.stdout.flush()'
    if kind == 'nonzero':
        source = 'raise SystemExit(7)'
    with pytest.raises(ServiceError) as error:
        run_process([sys.executable, '-c', source], cwd=tmp_path, env=os.environ.copy(), timeout=.15 if kind == 'timeout' else 5,
                    max_output=8192, cancel=(lambda: time.monotonic() - started > .15) if kind == 'cancel' else None)
    assert error.value.code == code
    assert time.monotonic() - started < 4


def test_fixed_worker_uses_private_factory_profile(tmp_path, monkeypatch):
    from mm_mcp.blender import runner
    captured = {}
    def process(command, **kwargs):
        captured.update(command=command, **kwargs)
        assert Path(kwargs['env']['BLENDER_USER_CONFIG']).is_dir()
        return 'Blender test process boundary'
    monkeypatch.setattr(runner, 'run_process', process)
    request = tmp_path / 'request.json'
    request.write_text('{}')
    runner.run_worker(request, tmp_path, binary=sys.executable)
    command = captured['command']
    for flag in ['--background', '--factory-startup', '--disable-autoexec', '--offline-mode', '--python-exit-code']:
        assert flag in command
    assert command[command.index('--python') + 1] == str(Path(runner.__file__).with_name('worker.py'))
    assert command[-2:] == [str(request), str(tmp_path)]
    assert not Path(captured['env']['BLENDER_USER_CONFIG']).exists()
    assert (tmp_path / 'worker.log').read_text() == 'Blender test process boundary'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process-group descendant check')
def test_timeout_kills_worker_descendants(tmp_path):
    from mm_mcp.blender.runner import run_process
    pid_file = tmp_path / 'child.pid'
    code = 'import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)'
    with pytest.raises(ServiceError, match='timed out'):
        run_process([sys.executable, '-c', code, str(pid_file)], cwd=tmp_path, env=os.environ.copy(), timeout=.5)
    pid = int(pid_file.read_text())
    import subprocess
    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
    assert not state or state.startswith('Z')


def test_worker_guard_exits_when_parent_is_killed(tmp_path):
    from mm_mcp.blender.guard import start_parent_guard
    import subprocess
    child_source = 'import os,sys,time,pathlib; from mm_mcp.blender.guard import start_parent_guard; start_parent_guard(int(os.environ["MM_BLENDER_PARENT_PID"])); pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)'
    parent_source = 'import os,sys; from mm_mcp.blender.runner import run_process; env=os.environ.copy(); env["MM_BLENDER_PARENT_PID"]=str(os.getpid()); run_process([sys.executable,"-c",sys.argv[1],sys.argv[2]],cwd=sys.argv[3],env=env,timeout=30)'
    pid_file = tmp_path / 'guarded.pid'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'src')
    parent = subprocess.Popen([sys.executable, '-c', parent_source, child_source, str(pid_file), str(tmp_path)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 4
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.025)
        assert pid_file.exists(), 'Guarded child never reached readiness.'
        pid = int(pid_file.read_text())
        parent.kill()
        parent.wait(timeout=3)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if os.name == 'nt':
                output = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
                alive = str(pid) in output
            else:
                state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
                alive = bool(state and not state.startswith('Z'))
            if not alive:
                break
            time.sleep(.05)
        assert not alive, 'Detached worker survived its owner process.'
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=3)


def test_guard_rejects_wrong_recorded_parent(tmp_path):
    from mm_mcp.blender.runner import run_process
    source = 'from mm_mcp.blender.guard import start_parent_guard; start_parent_guard(1)'
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'src')
    with pytest.raises(ServiceError) as error:
        run_process([sys.executable, '-c', source], cwd=tmp_path, env=env, timeout=3)
    assert error.value.code == 'BLENDER_EXIT'
    assert 'Recorded owner process' in error.value.details['log_tail']
