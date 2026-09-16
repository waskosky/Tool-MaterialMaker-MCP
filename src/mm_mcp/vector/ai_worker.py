"""Private Codex launcher with owner-death cleanup; never an HTTP/MCP entrypoint.

The service sends one bounded JSON line, then retains stdin as an ownership pipe.
Codex receives its own prompt pipe. No prompt or response file is written here.
"""

import json
import os
import signal
import subprocess
import sys
import threading


def terminate_group():
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(os.getpid()), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        elif os.getpgrp() == os.getpid():
            os.killpg(os.getpid(), signal.SIGKILL)
    finally:
        os._exit(72)


def main():
    parent = int(sys.argv[1])
    if parent <= 1 or os.getppid() != parent:
        return 72
    raw = sys.stdin.buffer.readline(512 * 1024 + 1)
    if not raw.endswith(b"\n") or len(raw) > 512 * 1024:
        return 73
    request = json.loads(raw)

    def watch():
        try:
            while os.read(0, 1):
                pass
        finally:
            terminate_group()

    threading.Thread(target=watch, name="vector-ai-owner", daemon=True).start()
    try:
        return subprocess.run(
            request["command"],
            input=request["prompt"].encode(),
            timeout=170,
            check=False,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return 74


if __name__ == "__main__":
    sys.exit(main())
