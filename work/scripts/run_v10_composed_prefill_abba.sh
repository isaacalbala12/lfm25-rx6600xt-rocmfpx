#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
PLUGIN=${PLUGIN:-$BUILD/bin/rocmfpx-vulkan-plugin.so}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
RUNNER=$ROOT/work/scripts/benchmark_llama_backend.sh
OUTPUT=${OUTPUT:-$ROOT/work/results/v10-prefill8k-composed-exact-paired3}
PAIRS=${PAIRS:-3}
PORT=${PORT:-18243}

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v10_composed_prefill' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
fi

mkdir -p "$OUTPUT"
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
export ROCMFPX_PLUGIN_PATH=$PLUGIN
unset GGML_VK_SELECTION_LOGGER GGML_VK_PERF_LOGGER GGML_VK_PERF_LOGGER_CONCURRENT
unset GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP_PADDED
unset GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP_PLANAR
unset GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP_GROUP4

sha256sum "$SERVER" "$PLUGIN" "$BACKEND" "$MODEL" >"$OUTPUT/hashes.txt"

run_arm() {
  local pair=$1 arm=$2 enabled=$3
  local destination="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm"
  GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=256 \
    REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=off \
    PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
    RESOURCE_SAMPLER_MODE=required LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP_SHAPE="$enabled" \
    GGML_VK_ROCMFP4_FAST_MMQ_DOWN_EXACT="$enabled" \
    BENCH_SEED="$((260919 + pair * 10000))" PORT="$PORT" \
    "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
      --label "v10-composed-pair${pair}-${arm}" --output "$destination" -- \
      -dev ROCmFPXVulkan0 -c 34816 --kv-unified-per-slot 8704 \
      -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
}

for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
  for arm in "${arms[@]}"; do
    if [[ "$arm" == control ]]; then enabled=0; else enabled=1; fi
    run_arm "$pair" "$arm" "$enabled"
  done
done

python3 "$ROOT/work/scripts/summarize_prefill_service_pairs.py" "$OUTPUT" >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
