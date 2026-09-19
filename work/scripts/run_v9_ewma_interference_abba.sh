#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
PLUGIN=${PLUGIN:-$BUILD/bin/rocmfpx-vulkan-plugin.so}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
RUNNER=$ROOT/work/scripts/run_interference_profile.sh
OUTPUT=${OUTPUT:-$ROOT/work/results/v9-ewma65-interference-paired3}
PAIRS=${PAIRS:-3}
PORT=${PORT:-18283}
TARGET_MS=${TARGET_MS:-65}

export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
export ROCMFPX_PLUGIN_PATH=$PLUGIN

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v9_ewma_interference' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
fi

mkdir -p "$OUTPUT"
sha256sum "$SERVER" "$BACKEND" "$PLUGIN" "$MODEL" >"$OUTPUT/hashes.txt"
printf 'pairs=%s\norder=AB/BA alternating\ncontrol=chunk128\ncandidate=chunk128+EWMA%s,min64\n' "$PAIRS" "$TARGET_MS" \
  >"$OUTPUT/protocol.txt"

run_arm() {
  local pair=$1 arm=$2 target_ms=$3
  local destination="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm"
  GPU_RESERVATION_CONFIRMED=1 DECODER_COUNTS=3 \
    LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    LLAMA_SERVER_PREFILL_TARGET_MS="$target_ms" \
    LLAMA_SERVER_PREFILL_MIN_TOKENS=64 \
    PORT="$PORT" OUTPUT="$destination" SERVER="$SERVER" MODEL="$MODEL" \
    "$RUNNER"
}

for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
  for arm in "${arms[@]}"; do
    if [[ "$arm" == control ]]; then target_ms=0; else target_ms=$TARGET_MS; fi
    run_arm "$pair" "$arm" "$target_ms"
  done
done

python3 "$ROOT/work/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  --baseline-arm control --candidate-arm candidate >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
