"""Synchronize reviewed source resources into the wheel; no downloads occur."""
import argparse
import hashlib
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'src/mm_mcp/data'
SOURCES = {'cookbook': ROOT/'cookbook', 'addons/mm_live': ROOT/'addons/mm_live',
           'AUTHORING.md': ROOT/'docs/AUTHORING.md'}
ALLOWED = {'.ptex', '.md', '.json', '.gd', '.cfg', '.uid'}

def mapping():
    files = {}
    for relative, source in SOURCES.items():
        candidates = source.rglob('*') if source.is_dir() else [source]
        for p in candidates:
            if p.is_file() and p.suffix.lower() in ALLOWED and not p.is_symlink():
                tail = p.relative_to(source) if source.is_dir() else Path()
                files[DEST / relative / tail] = p
    return files

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--check',action='store_true'); args=parser.parse_args()
    files=mapping(); stale=[]
    for target, source in files.items():
        if args.check:
            if not target.is_file() or target.read_bytes()!=source.read_bytes(): stale.append(str(target.relative_to(ROOT)))
        else:
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    extras=[p for p in DEST.rglob('*') if p.is_file() and p not in files] if DEST.exists() else []
    for p in extras:
        if args.check:stale.append(str(p.relative_to(ROOT)))
        else:p.unlink()
    if stale:
        print('Package resources differ. Run python scripts/sync_package_data.py.\n'+'\n'.join(stale));return 1
    print(f'{len(files)} package resource files '+('verified.' if args.check else 'synchronized.'));return 0
if __name__=='__main__':raise SystemExit(main())
