#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
OUTPUT=${OUTPUT:?OUTPUT is required}
PAIRS=${PAIRS:-3}
PORT=${PORT:-18230}
SERVER=${SERVER:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
PLUGIN=${PLUGIN:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/rocmfpx-vulkan-plugin.so}
RUNNER=$ROOT/work/scripts/benchmark_llama_backend.sh

if [[ -e "$OUTPUT" ]]; then
    echo "output already exists: $OUTPUT" >&2
    exit 2
fi
mkdir -p "$OUTPUT"
printf 'pairs=%s\norder=AB/BA alternating\ncontrol=fixed chunk128\ncandidate=idle chunk512, active-decoder chunk128\n' \
    "$PAIRS" >"$OUTPUT/protocol.txt"

run_arm() {
    local pair=$1 arm=$2 enabled=$3
    local destination="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm"
    GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=256 \
        REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=off \
        PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
        RESOURCE_SAMPLER_MODE=required LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
        LLAMA_SERVER_PREFILL_CHUNK_DECODE_AWARE="$enabled" \
        LLAMA_SERVER_PREFILL_CHUNK_IDLE_TOKENS=512 \
        ROCMFPX_PLUGIN_PATH="$PLUGIN" \
        BENCH_SEED="$((260916 + pair * 10000))" PORT="$PORT" \
        "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
          --label "v5-decode-aware-pair${pair}-${arm}" --output "$destination" -- \
          -dev ROCmFPXVulkan0 -c 34816 --kv-unified-per-slot 8704 \
          -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
}

for ((pair=0; pair<PAIRS; pair++)); do
    if (( pair % 2 == 0 )); then
        arms=(control candidate)
    else
        arms=(candidate control)
    fi
    for arm in "${arms[@]}"; do
        if [[ "$arm" == control ]]; then enabled=0; else enabled=1; fi
        run_arm "$pair" "$arm" "$enabled"
    done
done

python3 "$ROOT/work/scripts/summarize_prefill_service_pairs.py" "$OUTPUT" >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
