#!/usr/bin/env bash
# Format A/B on the mixed 8K product workload (3 resident 8K decoders + one
# fresh 8K prefill).
#
# Motivation: the campaign's format screens were run at 128/64 and 512/128,
# shapes where decode dominates (64 output tokens against 128 input tokens).
# A llama-bench screen at the prefill shape shows plain Q4_0 at 2621 pp tok/s
# against 2271 for ROCmFP4_FAST, a 15.4% prefill advantage, while FP4_FAST
# keeps a 7.2% decode advantage. V9 measured the prefill graph at 83.49% of the
# mixed pair, so the sign of that trade is a product question, not a
# microbenchmark question.
#
# Alternate FP4_FAST (control) and Q4_0 (candidate) with identical server
# flags; only the weight file changes.
#
# Usage: PAIRS=3 [START_PAIR=0] run_format_interference_abba.sh <output-dir>
set -euo pipefail

WORK=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work
RUNNER=$WORK/scripts/run_interference_profile.sh
# Same binary the V9 mixed timeline used, so the control arm is directly
# comparable with the published 5137 ms TTFT / 88.5 ms ITL baseline.
BUILD=$WORK/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin
SERVER=${SERVER:-$BUILD/llama-server}
PLUGIN=${PLUGIN:-$BUILD/rocmfpx-vulkan-plugin.so}
CONTROL_MODEL=$WORK/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf
CANDIDATE_MODEL=$WORK/results/models/LFM2.5-2.6B-Q4_0.gguf

# The plugin build puts the isolated GCC 16 runtime ahead of the system one in
# its RPATH, so the toolchain libstdc++/libgcc must be preloaded or the backend
# fails with an undefined GLIBCXX_3.4.35 symbol.
source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1

OUTPUT=${1:?usage: run_format_interference_abba.sh <output-dir>}
PAIRS=${PAIRS:-3}
START_PAIR=${START_PAIR:-0}
PORT=${PORT:-18311}

if [[ ! -e "$OUTPUT" ]]; then
  mkdir -p "$OUTPUT"
fi
if [[ ! -e "$OUTPUT/protocol.txt" ]]; then
  {
    echo "control_model=$CONTROL_MODEL"
    echo "candidate_model=$CANDIDATE_MODEL"
    echo "server=$SERVER"
    echo "plugin=$PLUGIN"
    echo "order=control/candidate alternating"
    echo "device=ROCmFPXVulkan0"
    echo "flags=-ngl 99 -fa on -np 4 -cb --cache-prompt -c 36864 --kv-unified-per-slot 9216 -b 4096 -ub 128 -ctk q8_0 -ctv q8_0"
    echo "prefill_chunk_tokens=128"
  } > "$OUTPUT/protocol.txt"
  sha256sum "$CONTROL_MODEL" "$CANDIDATE_MODEL" >> "$OUTPUT/protocol.txt"
fi

run_arm() {
    local pair=$1 arm=$2 model=$3
    GPU_RESERVATION_CONFIRMED=1 LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
      LLAMA_SERVER_PREFILL_CHUNK_DECODE_AWARE=0 \
      LLAMA_SERVER_PREFILL_CHUNK_IDLE_TOKENS=0 \
      SERVER="$SERVER" MODEL="$model" ROCMFPX_PLUGIN_PATH="$PLUGIN" \
      OUTPUT="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" \
      DECODER_COUNTS=3 PORT="$PORT" "$RUNNER"
}

for ((offset=0; offset<PAIRS; offset++)); do
    pair=$((START_PAIR + offset))
    if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
    for arm in "${arms[@]}"; do
        if [[ "$arm" == control ]]; then model=$CONTROL_MODEL; else model=$CANDIDATE_MODEL; fi
        run_arm "$pair" "$arm" "$model"
    done
done

python3 "$WORK/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  --baseline-arm control --candidate-arm candidate >"$OUTPUT/summary.json" || true
cat "$OUTPUT/summary.json"
