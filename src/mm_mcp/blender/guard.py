"""Blender owner-death guard; uses a pipe owned by the spawning service process."""
import os
import signal
import subprocess
import threading


def start_parent_guard(expected_parent):
    """Reject an already-orphaned startup and exit on owner-pipe EOF.

    The owner PID is recorded before Popen, never inferred after startup. The
    anonymous pipe also detects owner death on Windows, whose parent PID may
    otherwise remain unchanged. No other child inherits the pipe's write end.
    """
    if type(expected_parent) is not int or expected_parent <= 1 or os.getppid() != expected_parent:
        raise RuntimeError('Recorded owner process exited or changed before Blender startup.')

    def watch():
        try:
            while os.read(0, 1):
                pass
        except OSError:
            pass
        # The fixed runner creates a new process group/session for this worker.
        # Kill its descendants as well when the owner can no longer clean them.
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(os.getpid()), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            elif os.getpgrp() == os.getpid():
                os.killpg(os.getpid(), signal.SIGKILL)
        finally:
            os._exit(72)
    threading.Thread(target=watch, name='mm-blender-owner-guard', daemon=True).start()
