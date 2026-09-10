#!/bin/sh
# Finder-compatible source launcher. Quoting preserves source paths with spaces.
cd -- "$(dirname -- "$0")" || exit 1
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
MM_LAUNCH_PYTHON=""
if [ -x .venv/bin/python ]; then
    MM_LAUNCH_PYTHON=".venv/bin/python"
else
    for MM_CANDIDATE in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$MM_CANDIDATE" >/dev/null 2>&1; then
            MM_LAUNCH_PYTHON="$(command -v "$MM_CANDIDATE")"
            break
        fi
    done
fi
if [ -z "$MM_LAUNCH_PYTHON" ]; then
    for MM_CANDIDATE in /Library/Frameworks/Python.framework/Versions/*/bin/python3; do
        if [ -x "$MM_CANDIDATE" ]; then
            MM_LAUNCH_PYTHON="$MM_CANDIDATE"
            break
        fi
    done
fi
if [ -z "$MM_LAUNCH_PYTHON" ]; then
    printf '%s\n' 'Install Python 3.10 or newer from https://www.python.org/downloads/ and reopen Play.'
    read -r MM_LAUNCH_WAIT
    exit 1
fi
"$MM_LAUNCH_PYTHON" scripts/launch.py "$@"
MM_LAUNCH_EXIT=$?
if [ "$MM_LAUNCH_EXIT" -ne 0 ]; then
    printf '%s\n' 'Press Return to close this window.'
    read -r MM_LAUNCH_WAIT
fi
exit "$MM_LAUNCH_EXIT"
