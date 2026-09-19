import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_radv_shader_dump.py"
SPEC = importlib.util.spec_from_file_location("analyze_radv_shader_dump", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_inspect_block_extracts_static_machine_metrics():
    block = """shader: MESA_SHADER_COMPUTE
source_blake3: {0x1}
workgroup_size: 128, 1, 1
shared_size: 18960
api_subgroup_size: 32
disasm:
BB0:
\tv_add_u32 v40, v1, v2 ; deadbeef
\tds_read_b32 v3, v4 ; deadbeef
\ts_barrier ; deadbeef
\tbuffer_load_dword v0, v1, s[16:19], 0 offen ; deadbeef
"""
    result = MODULE.inspect_block(block)
    assert result["shared_size_bytes"] == 18960
    assert result["max_numbered_vgpr_index_observed"] == 40
    assert result["max_numbered_sgpr_index_observed"] == 19
    assert result["selected_counts"]["barriers"] == 1
    assert result["selected_counts"]["buffer_loads"] == 1
    assert result["selected_counts"]["lds_reads"] == 1
