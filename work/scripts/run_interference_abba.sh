#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
RUNNER=$ROOT/work/scripts/run_interference_profile.sh
OUTPUT=${OUTPUT:?OUTPUT is required}
PAIRS=${PAIRS:-10}
CHUNK_TOKENS=${CHUNK_TOKENS:-128}
DECODER_COUNTS=${DECODER_COUNTS:-3}

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"
printf 'pairs=%s\nchunk_tokens=%s\ndecoder_counts=%s\norder=AB/BA alternating\n' \
  "$PAIRS" "$CHUNK_TOKENS" "$DECODER_COUNTS" >"$OUTPUT/protocol.txt"

run_arm() {
  local pair=$1
  local arm=$2
  local run_output="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm"
  if [[ "$arm" == control ]]; then
    env -u LLAMA_SERVER_PREFILL_CHUNK_TOKENS \
      OUTPUT="$run_output" DECODER_COUNTS="$DECODER_COUNTS" "$RUNNER"
  else
    env LLAMA_SERVER_PREFILL_CHUNK_TOKENS="$CHUNK_TOKENS" \
      OUTPUT="$run_output" DECODER_COUNTS="$DECODER_COUNTS" "$RUNNER"
  fi
}

for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then
    order=(control chunk128)
  else
    order=(chunk128 control)
  fi
  for arm in "${order[@]}"; do
    run_arm "$pair" "$arm"
  done
done

python3 "$ROOT/work/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
