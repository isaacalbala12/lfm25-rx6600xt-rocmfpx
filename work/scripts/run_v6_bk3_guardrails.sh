#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SOURCE=${SOURCE:-$ROOT/work/sources/ROCmFPX}
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
TEST=${TEST:-$BUILD/bin/test-backend-ops}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
CMAKE=${CMAKE:-/home/isaac/vllm-challenge/toolchain/bin/cmake}
PATCH=$ROOT/patches/v6-auto/gateup-bkstep3.patch
OUTPUT=${OUTPUT:-$ROOT/work/results/v6-atrex-gateup-bk3-guardrails}
PAIRS=${PAIRS:-5}
CONTROL_BACKEND=$BUILD/bin/.v6-bk3-control-libggml-rocmfpx-vulkan.so
CANDIDATE_BACKEND=$BUILD/bin/.v6-bk3-candidate-libggml-rocmfpx-vulkan.so
PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
FILTER='type_a=q4_0_rocmfp4_fast,type_b=f32,.*(m=10752,n=(120|128|129),k=2048|m=2048,n=128,k=10752)'
PATCH_APPLIED=0

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
  echo "ROCmFPX source is not clean" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v6_bk3_guardrails' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
fi
mkdir -p "$OUTPUT"

cleanup() {
  local status=$?
  if (( PATCH_APPLIED )); then
    if git -C "$SOURCE" apply --check --reverse "$PATCH"; then
      git -C "$SOURCE" apply --reverse "$PATCH"
      "$CMAKE" --build "$BUILD" --target ggml-rocmfpx-vulkan -j 2 \
        >"$OUTPUT/restore-build.stdout" 2>"$OUTPUT/restore-build.stderr" || status=2
    else
      echo "candidate patch could not be reversed" >>"$OUTPUT/restore-build.stderr"
      status=2
    fi
  fi
  sha256sum "$BACKEND" >"$OUTPUT/restored-backend.sha256" 2>/dev/null || status=2
  rm -f "$CONTROL_BACKEND" "$CANDIDATE_BACKEND"
  if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
    echo "ROCmFPX source not clean after guardrail run" >&2
    status=2
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

cp "$BACKEND" "$CONTROL_BACKEND"
git -C "$SOURCE" apply --check "$PATCH"
git -C "$SOURCE" apply "$PATCH"
PATCH_APPLIED=1
"$CMAKE" --build "$BUILD" --target ggml-rocmfpx-vulkan test-backend-ops -j 2 \
  >"$OUTPUT/build.stdout" 2>"$OUTPUT/build.stderr"
cp "$BACKEND" "$CANDIDATE_BACKEND"
sha256sum "$TEST" "$CONTROL_BACKEND" "$CANDIDATE_BACKEND" >"$OUTPUT/hashes.txt"
if [[ "$(sha256sum "$CONTROL_BACKEND" | cut -d' ' -f1)" == "$(sha256sum "$CANDIDATE_BACKEND" | cut -d' ' -f1)" ]]; then
  echo "candidate backend hash equals control" >&2
  exit 2
fi

run_test() {
  local label=$1 expression=$2
  env LD_PRELOAD="$PRELOAD" ROCMFPX_BACKEND_PATH="$CANDIDATE_BACKEND" \
    "$TEST" test -b ROCmFPXVulkan0 -o MUL_MAT -p "$expression" \
    >"$OUTPUT/correctness-${label}.stdout" 2>"$OUTPUT/correctness-${label}.stderr"
  grep -q '1/1 tests passed' "$OUTPUT/correctness-${label}.stdout"
}
run_test gate120 'type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=120,k=2048'
run_test gate128 'type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=128,k=2048'
run_test gate129 'type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=129,k=2048'
run_test down128 'type_a=q4_0_rocmfp4_fast,type_b=f32,m=2048,n=128,k=10752'

index=0
for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then
    order=(control bk3 bk3 control)
  else
    order=(bk3 control control bk3)
  fi
  for arm in "${order[@]}"; do
    if [[ "$arm" == control ]]; then library=$CONTROL_BACKEND; else library=$CANDIDATE_BACKEND; fi
    env LD_PRELOAD="$PRELOAD" ROCMFPX_BACKEND_PATH="$library" \
      "$TEST" perf -b ROCmFPXVulkan0 -o MUL_MAT -p "$FILTER" \
      >"$OUTPUT/$(printf '%03d' "$index")-${arm}.txt" \
      2>"$OUTPUT/$(printf '%03d' "$index")-${arm}.stderr"
    index=$((index + 1))
  done
done

python3 "$ROOT/work/scripts/summarize_backend_abba.py" "$OUTPUT" bk3 control \
  >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
