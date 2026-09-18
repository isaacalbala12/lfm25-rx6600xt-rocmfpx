#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
RUNNER=$ROOT/work/scripts/run_interference_profile.sh
OUTPUT=${OUTPUT:?OUTPUT is required}
PAIRS=${PAIRS:-3}
BASELINE_CHUNK=${BASELINE_CHUNK:-128}
CANDIDATE_CHUNK=${CANDIDATE_CHUNK:-96}
DECODER_COUNTS=${DECODER_COUNTS:-3}
BASELINE_ARM=chunk${BASELINE_CHUNK}
CANDIDATE_ARM=chunk${CANDIDATE_CHUNK}

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"
printf 'pairs=%s\nbaseline_chunk=%s\ncandidate_chunk=%s\ndecoder_counts=%s\norder=AB/BA alternating\n' \
  "$PAIRS" "$BASELINE_CHUNK" "$CANDIDATE_CHUNK" "$DECODER_COUNTS" >"$OUTPUT/protocol.txt"

run_arm() {
  local pair=$1 arm=$2 chunk=$3
  LLAMA_SERVER_PREFILL_CHUNK_TOKENS="$chunk" OUTPUT="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" \
    DECODER_COUNTS="$DECODER_COUNTS" "$RUNNER"
}

for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then
    run_arm "$pair" "$BASELINE_ARM" "$BASELINE_CHUNK"
    run_arm "$pair" "$CANDIDATE_ARM" "$CANDIDATE_CHUNK"
  else
    run_arm "$pair" "$CANDIDATE_ARM" "$CANDIDATE_CHUNK"
    run_arm "$pair" "$BASELINE_ARM" "$BASELINE_CHUNK"
  fi
done

python3 "$ROOT/work/scripts/summarize_interference_pairs.py" "$OUTPUT" \
  --baseline-arm "$BASELINE_ARM" --candidate-arm "$CANDIDATE_ARM" >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
