"""Keep the current README and tool reference consistent with shipped resources."""
import asyncio
from pathlib import Path
import re

import pytest

from mm_mcp import server
from mm_mcp.cookbook import list_cookbook
from mm_mcp.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / 'README.md').read_text(encoding='utf-8')
REFERENCE = (ROOT / 'docs/upgrade/TOOLS.md').read_text(encoding='utf-8')
REGISTERED = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
SHARED = {tool.__name__ for tool in TOOLS}
LIVE = {name for name in REGISTERED if name.startswith('live_')}


def test_readme_cookbook_material_count_matches_tree():
    entries = list_cookbook(str(ROOT / 'cookbook'))
    counts = re.search(r'cookbook is (\d+) materials across (\d+) categories', README)
    assert counts, 'README must describe the cookbook material and category counts'
    assert int(counts[1]) == len(entries)
    assert int(counts[2]) == len({entry.category for entry in entries})


@pytest.mark.parametrize('kind, names', [
    ('shared material', SHARED), ('batch', REGISTERED - SHARED - LIVE), ('live', LIVE),
])
def test_readme_tool_counts_match_sdk_registration(kind, names):
    count = re.search(r'(\d+) ' + kind + r' tools', README)
    assert count, f'README must state the number of {kind} tools'
    assert int(count[1]) == len(names)


def test_reference_documents_all_registered_tools():
    shared = set(re.findall(r'^## ((?:material|blender)_\w+)$', REFERENCE, re.M))
    legacy = set(re.findall(r'^\| `(\w+)` \|', REFERENCE, re.M))
    assert shared == SHARED
    assert shared | legacy == REGISTERED
