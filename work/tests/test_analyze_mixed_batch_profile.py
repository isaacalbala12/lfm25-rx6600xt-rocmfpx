import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_mixed_batch_profile.py"
SPEC = importlib.util.spec_from_file_location("analyze_mixed_batch_profile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_mixed_batch_profile_groups_two_graphs_and_ignores_other_shapes():
    lines = [
        "BATCHTRACE id=1 phase=submit off=0 tokens=3 prompt_tokens=0 decode_tokens=3",
        "Vulkan Timings:",
        "MUL_MAT q4_0_rocmfp4_fast m=10752 n=3 k=2048: 1 x 2 us = 2 us",
        "BATCHTRACE id=1 phase=complete wall_us=10000 ret=0",
        "BATCHTRACE id=2 phase=submit off=0 tokens=131 prompt_tokens=128 decode_tokens=3",
        "Vulkan Timings:",
        "FLASH_ATTN_EXT dst(...): 1 x 4 us = 4 us",
        "Vulkan Timings:",
        "MUL_MAT q4_0_rocmfp4_fast m=10752 n=127 k=2048: 2 x 10 us = 20 us",
        "MUL_MAT q4_0_rocmfp4_fast m=2048 n=127 k=10752: 1 x 15 us = 15 us",
        "MUL_MAT q4_0_rocmfp4_fast m=6144 n=127 k=2048: 1 x 5 us = 5 us",
        "MUL_MAT q4_0_rocmfp4_fast m=2048 n=127 k=2048: 1 x 3 us = 3 us",
        "ADD: 1 x 3 us = 3 us",
        "BATCHTRACE id=2 phase=complete wall_us=80000 ret=0",
    ]
    result = MODULE.analyze(lines, 128, 3)
    assert result["valid_batches"] == 1
    assert result["graph_count_histogram"] == {"2": 1}
    assert result["instrumented_wall_ms"]["median"] == 80.0
    groups = result["profiled_gpu_groups"]
    assert groups["gate_up"]["total_us"] == 20.0
    assert groups["down"]["total_us"] == 15.0
    assert groups["flash_attention"]["total_us"] == 4.0
    assert groups["short_conv"]["total_us"] == 5.0
    assert groups["projection_2048"]["total_us"] == 3.0
    assert groups["misc"]["total_us"] == 3.0
    assert result["top_timing_groups"][0]["total_us"] == 20.0
    by_graph = result["profiled_gpu_by_graph_index"]
    assert by_graph["0"]["total_us"] == 4.0
    assert by_graph["0"]["groups"]["flash_attention"]["share_within_graph"] == 1.0
    assert by_graph["1"]["total_us"] == 46.0
    assert by_graph["1"]["groups"]["gate_up"]["total_us"] == 20.0
    assert by_graph["1"]["groups"]["gate_up"]["share_of_all_graphs"] == 0.4


def test_failed_batch_is_not_counted():
    lines = [
        "BATCHTRACE id=9 phase=submit off=0 tokens=131 prompt_tokens=128 decode_tokens=3",
        "Vulkan Timings:",
        "ADD: 1 x 1 us = 1 us",
        "BATCHTRACE id=9 phase=complete wall_us=1000 ret=-1",
    ]
    assert MODULE.analyze(lines, 128, 3)["valid_batches"] == 0
