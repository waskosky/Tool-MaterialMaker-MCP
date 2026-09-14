"""Check the vendored compiler pin; optionally reproduce from an exact RAI checkout."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mm_mcp.vector.provenance import verify

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rai-root', type=Path)
args = parser.parse_args()
lock = verify()
if args.rai_root:
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.rai_root, text=True).strip()
    if revision != lock['source_revision']:
        parser.error('RAI checkout must name the independent reviewed source pin.')
    subprocess.run([sys.executable, str(args.rai_root / 'scripts/export_vector_compiler.py'),
                    '--output', str(ROOT / 'src/mm_mcp/vector/producer'), '--verify'], check=True)
print(json.dumps({'ok': True, 'source_revision': lock['source_revision'], 'reproduced': bool(args.rai_root)}))
