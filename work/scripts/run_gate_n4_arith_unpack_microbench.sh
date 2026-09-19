#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-cm1}
TEST=${TEST:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/test-backend-ops}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
OUTPUT=${OUTPUT:-$ROOT/work/results/v5-kernel-gate-n4-arith-unpack/abba10}
REPETITIONS=${REPETITIONS:-10}
FILTER=${FILTER:-'type_a=q4_0_rocmfp4_fast.*m=10752,n=4,k=2048.*'}
CANDIDATE_MODE=arith-gateup-n4

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_gate_n4_arith_unpack_microbench' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
fi
mkdir -p "$OUTPUT"

export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
unset GGML_VK_SELECTION_LOGGER GGML_VK_PERF_LOGGER GGML_VK_DMMV_PHASE_LOGGER

sha256sum "$TEST" "$BACKEND" >"$OUTPUT/hashes.txt"
printf 'repetitions=%s\nfilter=%s\ncandidate_mode=%s\norder=ABBA alternating by pair\n' \
  "$REPETITIONS" "$FILTER" "$CANDIDATE_MODE" >"$OUTPUT/command.txt"

run_one() {
  local index=$1
  local mode=$2
  local unpack=lut
  if [[ "$mode" == "$CANDIDATE_MODE" ]]; then
    unpack=$CANDIDATE_MODE
  fi
  GGML_VK_ROCMFP4_FAST_DMMV_WG=subgroup \
  GGML_VK_ROCMFP4_FAST_UNPACK=$unpack \
    "$TEST" perf -b ROCmFPXVulkan0 -o MUL_MAT -p "$FILTER" \
      >"$OUTPUT/${index}-${mode}.txt" 2>"$OUTPUT/${index}-${mode}.stderr"
}

index=0
for ((pair=0; pair<REPETITIONS; pair++)); do
  if (( pair % 2 == 0 )); then
    order=(subgroup "$CANDIDATE_MODE" "$CANDIDATE_MODE" subgroup)
  else
    order=("$CANDIDATE_MODE" subgroup subgroup "$CANDIDATE_MODE")
  fi
  for mode in "${order[@]}"; do
    run_one "$index" "$mode"
    index=$((index + 1))
  done
done

python3 "$ROOT/work/scripts/summarize_kernel_microbench.py" "$OUTPUT" "$CANDIDATE_MODE" >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
