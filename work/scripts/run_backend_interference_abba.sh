#!/usr/bin/env bash
# Backend A/B on the mixed 8K product workload.
#
# Alternates two llama-server build directories with identical flags and the same
# weight file, so the only difference is the compiled backend. Used to score
# candidate kernel changes on the workload the interactive profile cares about.
#
# Usage: PAIRS=2 [START_PAIR=0] run_backend_interference_abba.sh <output-dir> <control-bin> <candidate-bin>
set -euo pipefail

WORK=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work
RUNNER=$WORK/scripts/run_interference_profile.sh
MODEL=$WORK/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf

OUTPUT=${1:?usage: run_backend_interference_abba.sh <output-dir> <control-bin> <candidate-bin>}
CONTROL_BIN=${2:?control bin directory required}
CANDIDATE_BIN=${3:?candidate bin directory required}
PAIRS=${PAIRS:-2}
START_PAIR=${START_PAIR:-0}
PORT=${PORT:-18321}

source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1

if [[ ! -e "$OUTPUT" ]]; then
  mkdir -p "$OUTPUT"
fi

if [[ ! -e "$OUTPUT/protocol.txt" ]]; then
  {
    echo "control_bin=$CONTROL_BIN"
    echo "candidate_bin=$CANDIDATE_BIN"
    echo "model=$MODEL"
    echo "order=control/candidate alternating"
    echo "device=ROCmFPXVulkan0"
    echo "flags=-ngl 99 -fa on -np 4 -cb --cache-prompt -c 36864 --kv-unified-per-slot 9216 -b 4096 -ub 128 -ctk q8_0 -ctv q8_0"
    echo "prefill_chunk_tokens=128"
  } > "$OUTPUT/protocol.txt"
  sha256sum "$MODEL" "$CONTROL_BIN/libggml-rocmfpx-vulkan.so" "$CANDIDATE_BIN/libggml-rocmfpx-vulkan.so" >> "$OUTPUT/protocol.txt"
fi

run_arm() {
    local pair=$1 arm=$2 bin=$3
    GPU_RESERVATION_CONFIRMED=1 LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
      LLAMA_SERVER_PREFILL_CHUNK_DECODE_AWARE=0 \
      LLAMA_SERVER_PREFILL_CHUNK_IDLE_TOKENS=0 \
      SERVER="$bin/llama-server" MODEL="$MODEL" ROCMFPX_PLUGIN_PATH="$bin/rocmfpx-vulkan-plugin.so" \
      OUTPUT="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" \
      DECODER_COUNTS=3 PORT="$PORT" "$RUNNER"
}

for ((offset=0; offset<PAIRS; offset++)); do
    pair=$((START_PAIR + offset))
    if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
    for arm in "${arms[@]}"; do
        if [[ "$arm" == control ]]; then bin=$CONTROL_BIN; else bin=$CANDIDATE_BIN; fi
        run_arm "$pair" "$arm" "$bin"
    done
done

python3 "$WORK/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  --baseline-arm control --candidate-arm candidate >"$OUTPUT/summary.json" || true
cat "$OUTPUT/summary.json"
