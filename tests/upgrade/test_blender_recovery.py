"""Orphan recovery exercises real locks, queues and Python child processes."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from mm_mcp.core import ServiceError, file_lock
from mm_mcp.service import MaterialService
from test_blender_service import blender_app


def _orphans(app):
    paths = [app.blender.results / name for name in ('.stage-orphan01', '.profile-orphan02')]
    for path in paths:
        path.mkdir()
        (path / 'private.tmp').write_text('Abandoned worker data')
    return paths


def test_idle_recovery_removes_only_private_temporary_directories(blender_app, tmp_path):
    app = blender_app
    result = app.blender.execute(app.blender.prepare({'operation': 'inspect'}))
    original = app.blender.export(result['result_id'])
    app.jobs.close()
    paths = _orphans(app)
    unrelated = app.blender.results / 'operator-notes'
    unrelated.mkdir()
    (unrelated / 'keep.txt').write_text('Keep this unrelated directory.')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('Do not traverse symlinks.')
    link = app.blender.results / '.stage-symlink1'
    try:
        link.symlink_to(outside, target_is_directory=True)
        (paths[1] / 'nested-link').symlink_to(outside, target_is_directory=True)
    except OSError:
        link = None
    assert app.jobs.run_one() is False
    assert not any(path.exists() for path in paths)
    assert (unrelated / 'keep.txt').read_text() == 'Keep this unrelated directory.'
    assert (outside / 'keep.txt').read_text() == 'Do not traverse symlinks.'
    assert link is None or link.is_symlink()
    assert app.blender.export(result['result_id']) == original


def test_idle_recovery_retries_temporarily_locked_directories(blender_app, monkeypatch):
    app = blender_app
    app.jobs.close()
    paths = _orphans(app)
    from mm_mcp.blender import service
    def locked(path):
        raise PermissionError('Worker exit has not released this directory yet.')
    with monkeypatch.context() as patch:
        patch.setattr(service.shutil, 'rmtree', locked)
        assert app.jobs.run_one() is False
        assert all(path.is_dir() for path in paths)
    assert app.jobs.run_one() is False
    assert not any(path.exists() for path in paths)


@pytest.mark.parametrize('lock_name', ['.worker.lock', '.native.lock'])
def test_recovery_preserves_active_work_until_shared_locks_release(blender_app, lock_name):
    app = blender_app
    app.jobs.close()
    with file_lock(app.root / lock_name):
        paths = _orphans(app)
        if lock_name == '.worker.lock':
            with pytest.raises(ServiceError) as error:
                app.jobs.run_one()
            assert error.value.code == 'BUSY'
        else:
            assert app.jobs.run_one() is False
        assert all((path / 'private.tmp').is_file() for path in paths)
    assert app.jobs.run_one() is False
    assert not any(path.exists() for path in paths)


def _alive(pid):
    if os.name == 'nt':
        output = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        return str(pid) in output
    state = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True).stdout.strip()
    return bool(state and not state.startswith('Z'))


def test_hard_owner_crash_recovers_child_profile_stage_and_job(blender_app, tmp_path):
    app = blender_app
    completed = app.blender.execute(app.blender.prepare({'operation': 'inspect'}))
    original = app.blender.export(completed['result_id'])
    app.jobs.close()
    ready_path, job_path = tmp_path / 'ready.json', tmp_path / 'job.json'
    parent_script = tmp_path / 'owner.py'
    # Replace only the actual native process boundary. run_worker still creates
    # its real private profile; execute and JobQueue own the real stage and locks.
    parent_script.write_text('''
import json, os, sys, threading
from pathlib import Path
from mm_mcp.config import Config
from mm_mcp.service import MaterialService
from mm_mcp.blender import runner
from mm_mcp.core import atomic_json

native_boundary = runner.run_process
guard_directory = str(Path(runner.__file__).parent)
child_source = "import json,os,sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from guard import start_parent_guard; start_parent_guard(int(os.environ['MM_BLENDER_PARENT_PID'])); ready=Path(sys.argv[2]); pending=ready.with_suffix('.tmp'); pending.write_text(json.dumps({'pid':os.getpid(),'stage':sys.argv[3],'profile':os.getcwd()})); pending.replace(ready); time.sleep(30)"
def python_child(command, **kwargs):
    return native_boundary([sys.executable, '-c', child_source, guard_directory, sys.argv[2], command[-1]], **kwargs)
runner.run_process = python_child
app = MaterialService(Config(**json.loads(sys.argv[1])), catalog={})
job = app.blender.submit({'operation':'inspect'})
atomic_json(sys.argv[3], job)
threading.Event().wait(30)
''')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'src')
    child_pid = None
    with (tmp_path / 'owner.log').open('wb') as log:
        parent = subprocess.Popen([sys.executable, str(parent_script), json.dumps(asdict(app.cfg)), str(ready_path), str(job_path)], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 5
            while not ready_path.exists() and time.monotonic() < deadline:
                time.sleep(.025)
            assert ready_path.exists(), (tmp_path / 'owner.log').read_text()
            ready = json.loads(ready_path.read_text())
            child_pid = ready['pid']
            stage, profile = Path(ready['stage']), Path(ready['profile'])
            assert stage.is_dir() and profile.is_dir()
            parent.kill()
            parent.wait(timeout=3)
            deadline = time.monotonic() + 3
            while _alive(child_pid) and time.monotonic() < deadline:
                time.sleep(.025)
            assert not _alive(child_pid), 'Detached worker survived its owner.'
            assert stage.is_dir() and profile.is_dir(), 'Hard crash fixture did not leave temporary directories.'
            with_service = MaterialService(app.cfg, catalog={})
            try:
                job_id = json.loads(job_path.read_text())['job_id']
                deadline = time.monotonic() + 3
                while (stage.exists() or profile.exists() or with_service.jobs.get(job_id)['state'] == 'running') and time.monotonic() < deadline:
                    time.sleep(.025)
                assert not stage.exists() and not profile.exists(), 'Restart did not recover abandoned worker directories.'
                recovered = with_service.jobs.get(job_id)
                assert recovered['state'] == 'failed' and recovered['result']['code'] == 'INTERRUPTED'
                assert with_service.blender.export(completed['result_id']) == original
            finally:
                with_service.close()
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=3)
            if child_pid is not None and _alive(child_pid):
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(child_pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                else:
                    import signal
                    os.killpg(child_pid, signal.SIGKILL)
