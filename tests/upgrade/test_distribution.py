"""Installation resources must match the reviewed source, including the cookbook."""
from pathlib import Path
import subprocess
import sys

def test_packaged_resources_are_synchronized():
    root=Path(__file__).resolve().parents[2]
    assert subprocess.run([sys.executable,'scripts/sync_package_data.py','--check'],cwd=root).returncode==0
    packaged=root/'src/mm_mcp/data'
    source_recipes = {p.relative_to(root/'cookbook') for p in (root/'cookbook').rglob('*.ptex')}
    packaged_recipes = {p.relative_to(packaged/'cookbook') for p in (packaged/'cookbook').rglob('*.ptex')}
    assert source_recipes
    assert packaged_recipes == source_recipes
    assert (packaged/'AUTHORING.md').is_file()
    assert (packaged/'addons/mm_live/live_server.gd').is_file()
