"""Create local configuration interactively; no file paths need editing in commands."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def ask(prompt,check):
    while True:
        raw=input(prompt).strip().strip('"')
        path=Path(raw).expanduser().resolve()
        if raw and check(path):return str(path)
        print('The path does not match the required file or directory. Try again.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    path=ROOT/'.env'
    if path.exists():
        print('.env already exists; it was not overwritten. Preserve and edit your existing configuration.');return 1
    project=binary=''
    if not args.offline:
        project=ask('Material Maker source checkout directory: ',lambda p:(p/'addons/material_maker/nodes').is_dir())
        binary=ask('Godot desktop executable: ',lambda p:p.is_file())
    output=str(ROOT/'output');workspace=str(ROOT/'output/workspace')
    values={'MM_PROJECT_PATH':project,'MM_GODOT_BINARY':binary,'MM_OUTPUT_DIR':output,
            'MM_WORKSPACE_DIR':workspace,'MM_MAX_RESOLUTION':'2048','MM_IDLE_EXIT_MINUTES':'0',
            'MM_ENABLE_EXPERIMENTAL_LIVE_WRITES':'0','MM_ALLOW_CUSTOM_SHADERS':'0'}
    with path.open('x',encoding='utf-8') as handle:
        for key,value in values.items():handle.write(f'{key}={json.dumps(value)}\n')
    print(f'Wrote {path}. Native writes remain disabled. Run scripts/native_smoke.py before certifying rendering.')
    return 0
if __name__=='__main__':raise SystemExit(main())
