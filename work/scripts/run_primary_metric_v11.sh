#!/usr/bin/env bash
# V11 regression control: re-measure the repository's declared primary metric on
# the current production binary.
#
# README.md declares the primary metric as 128 input tokens, 64 output tokens,
# concurrency 4, aggregate output tok/s measured over HTTP from first send to
# last completion. That exact shape was last measured in V2 (233.99 tok/s) and
# never again: V3 found the then-current artifact at 229.27 tok/s and warned
# that the published series used a different artifact state, and every
# subsequent version measured 8K workloads instead. This restores the anchor.
#
# Usage: GPU_RESERVATION_CONFIRMED=1 run_primary_metric_v11.sh <output-dir>
set -euo pipefail

WORK=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work
# Override BUILD to point the harness at a candidate backend directory.
BUILD=${BUILD:-$WORK/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin}
OUTPUT=${1:?usage: run_primary_metric_v11.sh <output-dir>}
PORT=${PORT:-18261}

source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH="$BUILD/rocmfpx-vulkan-plugin.so"
# Compact slot allocation is part of the documented production profile.
export LLAMA_SERVER_COMPACT_SLOTS=1

export PROMPT_TOKENS=128
export MAX_TOKENS=64
export REPETITIONS=10
export WARMUP=1
export CONCURRENCIES=${CONCURRENCIES:-"1 2 3 4"}
export CACHE_PROMPT=off
export PROMPT_MODE=varied
export SLOT_POLICY=auto
export ARRIVAL_STAGGER_MS=0

GPU_RESERVATION_CONFIRMED=1 \
  "$WORK/scripts/benchmark_llama_backend.sh" \
  --server "$BUILD/llama-server" \
  --model "$WORK/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf" \
  --tokenizer /home/isaac/vllm-challenge/models/LFM2.5-2.6B \
  --label v11-primary-128x64-plugin-compact-r10 \
  --port 18261 \
  --output "$OUTPUT" \
  -- -dev ROCmFPXVulkan0 -c 4096 -b 512 -ub 128 -ctk q8_0 -ctv q8_0

python3 - "$OUTPUT" <<'PY'
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
print()
print(f"{'C':>2} {'aggregate tok/s':>16} {'ttft p50 ms':>12} {'ttft p95 ms':>12} {'e2e p95 ms':>11} {'vram MiB':>9}")
for concurrency in (1, 2, 3, 4):
    data = json.loads(root.joinpath(f"c{concurrency}.json").read_text())
    aggregate = data["aggregate"]
    row = (
        f"{concurrency:>2} {aggregate['aggregate_output_tok_s']:>16.2f} "
        f"{aggregate.get('ttft_p50_ms', float('nan')):>12.2f} "
        f"{aggregate.get('ttft_p95_ms', float('nan')):>12.2f} "
        f"{aggregate.get('e2e_p95_ms', float('nan')):>11.1f} "
        f"{aggregate.get('vram_peak_bytes', 0) / 1048576:>9.1f}"
    )
    print(row)
PY
