"""Run the 0.8 review gate and the retained compatible 0.7 unit contracts.

The full historical suite remains under tests/. Its old transport/export/security
expectations are not the release contract for this intentionally breaking upgrade.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RETAINED = [
    'test_validator.py', 'test_paths.py', 'test_graph.py', 'test_inspect.py',
    'test_naming.py', 'test_author_helpers.py', 'test_author_helpers_rename.py',
    'test_render_compare.py', 'test_idle.py', 'test_cookbook.py',
    'test_readme_counts.py',
]

def main():
    result=subprocess.run([sys.executable,'scripts/sync_package_data.py','--check'],cwd=ROOT)
    if result.returncode:return result.returncode
    command=[sys.executable,'-m','pytest','tests/upgrade',*[f'tests/{n}' for n in RETAINED],'-q',*sys.argv[1:]]
    return subprocess.run(command,cwd=ROOT).returncode
if __name__=='__main__':raise SystemExit(main())
