"""Explicit dependency/runtime gates; skipping is never native certification."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
import pytest

@pytest.mark.sdk
def test_real_sdk_tool_registration():
    pytest.importorskip('mcp.server.mcpserver')
    from mm_mcp.server import mcp
    from mm_mcp.tools import TOOLS
    listed=asyncio.run(mcp.list_tools())
    assert {fn.__name__ for fn in TOOLS} <= {tool.name for tool in listed}

@pytest.mark.native
def test_native_acceptance_only_with_explicit_opt_in():
    if os.environ.get('MM_RUN_NATIVE_ACCEPTANCE')!='1':
        pytest.skip('Native rendering requires MM_RUN_NATIVE_ACCEPTANCE=1 and configured tools.')
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'scripts/native_smoke.py'],cwd=root,timeout=600)
    assert result.returncode==0
