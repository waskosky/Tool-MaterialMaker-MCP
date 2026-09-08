import pytest
from mm_mcp.config import load_config

def test_safe_defaults_and_native_gate(tmp_path,monkeypatch):
    monkeypatch.setenv('MM_DOTENV',str(tmp_path/'missing'))
    cfg=load_config({'MM_OUTPUT_DIR':str(tmp_path/'out'),'MM_ALLOWED_ROOTS':'','MM_TRUSTED_UNRESTRICTED_PATHS':'0','MM_ALLOW_CUSTOM_SHADERS':'0','MM_ENABLE_EXPERIMENTAL_LIVE_WRITES':'0'})
    assert cfg.allowed_roots and not cfg.allow_custom_shaders and not cfg.enable_experimental_live_writes
    assert load_config({'MM_ENABLE_EXPERIMENTAL_LIVE_WRITES':'1'}).enable_experimental_live_writes

@pytest.mark.parametrize('value',['0','31','33','8192','-2'])
def test_max_resolution_limits(value):
    with pytest.raises(ValueError):load_config({'MM_MAX_RESOLUTION':value})
