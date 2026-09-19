#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
RUNNER=$ROOT/work/scripts/run_interference_profile.sh
OUTPUT=${OUTPUT:?OUTPUT is required}
PAIRS=${PAIRS:-3}
DECODER_COUNTS=${DECODER_COUNTS:-3}
SERVER=${SERVER:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
PLUGIN=${PLUGIN:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/rocmfpx-vulkan-plugin.so}

if [[ -e "$OUTPUT" ]]; then
    echo "output already exists: $OUTPUT" >&2
    exit 2
fi
mkdir -p "$OUTPUT"
printf 'pairs=%s\ndecoder_counts=%s\norder=AB/BA alternating\n' "$PAIRS" "$DECODER_COUNTS" >"$OUTPUT/protocol.txt"

run_arm() {
    local pair=$1 arm=$2 enabled=$3
    GPU_RESERVATION_CONFIRMED=1 LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
      LLAMA_SERVER_PREFILL_CHUNK_DECODE_AWARE="$enabled" \
      LLAMA_SERVER_PREFILL_CHUNK_IDLE_TOKENS=512 \
      SERVER="$SERVER" MODEL="$MODEL" ROCMFPX_PLUGIN_PATH="$PLUGIN" \
      OUTPUT="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" \
      DECODER_COUNTS="$DECODER_COUNTS" PORT=18231 "$RUNNER"
}

for ((pair=0; pair<PAIRS; pair++)); do
    if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
    for arm in "${arms[@]}"; do
        if [[ "$arm" == control ]]; then enabled=0; else enabled=1; fi
        run_arm "$pair" "$arm" "$enabled"
    done
done

python3 "$ROOT/work/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  --baseline-arm control --candidate-arm candidate >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
