"""Build the local wheel only after checking synchronized resources."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
def main():
    result=subprocess.run([sys.executable,'scripts/sync_package_data.py','--check'],cwd=ROOT)
    if result.returncode:return result.returncode
    # Let the declared PEP 517 backend install its own build requirements in
    # isolation; setuptools is not a runtime dependency of a fresh virtualenv.
    return subprocess.run(
        [sys.executable, '-m', 'build', '--wheel', '--outdir', str(ROOT/'dist')],
        cwd=ROOT,
    ).returncode
if __name__=='__main__':raise SystemExit(main())
