#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
TEST=${TEST:-$BUILD/bin/test-backend-ops}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
OUTPUT=${OUTPUT:-$ROOT/work/results/v5-fa-bc64-exploratory-abba}
FILTER='hsk=64.*hsv=64.*nh=8.*nr23=\[4,4\].*kv=8192.*nb=32.*type_K=q8_0.*type_V=q8_0'

if [[ -e "$OUTPUT" ]]; then
    echo "output already exists: $OUTPUT" >&2
    exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_fa_bc64_microbench' >/dev/null; then
    echo "another inference process is active" >&2
    exit 2
fi

mkdir -p "$OUTPUT"
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
unset GGML_VK_SELECTION_LOGGER GGML_VK_PERF_LOGGER

sha256sum "$TEST" "$BACKEND" >"$OUTPUT/hashes.txt"
printf '%s\n' \
    'shape=LFM2 C4 hsk64 hsv64 nh8 nr23[4,4] kv8192 nb32 Q8/Q8' \
    'order=control,candidate,candidate,control' \
    'candidate=GGML_VK_FA_RDNA2_BC64=1' >"$OUTPUT/command.txt"

run_one() {
    local index=$1
    local mode=$2
    if [[ "$mode" == candidate ]]; then
        export GGML_VK_FA_RDNA2_BC64=1
    else
        unset GGML_VK_FA_RDNA2_BC64
    fi
    "$TEST" perf -b ROCmFPXVulkan0 -o FLASH_ATTN_EXT -p "$FILTER" \
        >"$OUTPUT/${index}-${mode}.txt" 2>"$OUTPUT/${index}-${mode}.stderr"
}

run_one 0 control
run_one 1 candidate
run_one 2 candidate
run_one 3 control

