#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SOURCE=${SOURCE:-$ROOT/work/sources/ROCmFPX}
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
TEST=${TEST:-$BUILD/bin/test-backend-ops}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
PLUGIN=${PLUGIN:-$BUILD/bin/rocmfpx-vulkan-plugin.so}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
CMAKE=${CMAKE:-/home/isaac/vllm-challenge/toolchain/bin/cmake}
PATCH=$ROOT/patches/v6-auto/gateup-selective-bkstep3.patch
RUNNER=$ROOT/work/scripts/benchmark_llama_backend.sh
OUTPUT=${OUTPUT:-$ROOT/work/results/v7-bk3-resident-boundaries}
PAIRS=${PAIRS:-3}
MICRO_PAIRS=${MICRO_PAIRS:-5}
PORT=${PORT:-18235}
FILTER='type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=(65|96|112|120|126|127|128),k=2048'
PATCH_APPLIED=0
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
export ROCMFPX_PLUGIN_PATH=$PLUGIN

if [[ -e "$OUTPUT" ]]; then echo "output already exists: $OUTPUT" >&2; exit 2; fi
if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then echo "ROCmFPX source is not clean" >&2; exit 2; fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v7_bk3_resident' >/dev/null; then
  echo "another inference process is active" >&2; exit 2
fi
mkdir -p "$OUTPUT"
sha256sum "$BACKEND" >"$OUTPUT/control-backend.sha256"
CONTROL_HASH=$(cut -d' ' -f1 "$OUTPUT/control-backend.sha256")

cleanup() {
  local status=$?
  if (( PATCH_APPLIED )); then
    if git -C "$SOURCE" apply --check --reverse "$PATCH"; then
      git -C "$SOURCE" apply --reverse "$PATCH"
      "$CMAKE" --build "$BUILD" --target ggml-rocmfpx-vulkan -j 2 \
        >"$OUTPUT/restore-build.stdout" 2>"$OUTPUT/restore-build.stderr" || status=2
    else
      echo "candidate patch could not be reversed" >>"$OUTPUT/restore-build.stderr"; status=2
    fi
  fi
  sha256sum "$BACKEND" >"$OUTPUT/restored-backend.sha256" 2>/dev/null || status=2
  [[ -z "$(git -C "$SOURCE" status --porcelain)" ]] || status=2
  exit "$status"
}
trap cleanup EXIT INT TERM

git -C "$SOURCE" apply --check "$PATCH"
git -C "$SOURCE" apply "$PATCH"
PATCH_APPLIED=1
"$CMAKE" --build "$BUILD" --target ggml-rocmfpx-vulkan -j 2 \
  >"$OUTPUT/build.stdout" 2>"$OUTPUT/build.stderr"
sha256sum "$SERVER" "$TEST" "$PLUGIN" "$BACKEND" "$MODEL" >"$OUTPUT/candidate-hashes.txt"
[[ "$CONTROL_HASH" != "$(sha256sum "$BACKEND" | cut -d' ' -f1)" ]]

env GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP=1 \
  "$TEST" test -b ROCmFPXVulkan0 -o MUL_MAT -p "$FILTER" \
  >"$OUTPUT/boundary-correctness.stdout" 2>"$OUTPUT/boundary-correctness.stderr"
grep -q '7/7 tests passed' "$OUTPUT/boundary-correctness.stdout"
env GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP=1 GGML_VK_SELECTION_LOGGER=1 \
  "$TEST" perf -b ROCmFPXVulkan0 -o MUL_MAT -p "$FILTER" \
  >"$OUTPUT/boundary-route.stdout" 2>"$OUTPUT/boundary-route.stderr"
grep -q 'pipeline=matmul_rocmfp4_fast_q8_1_bk3_m' "$OUTPUT/boundary-route.stderr"

index=0
for ((pair=0; pair<MICRO_PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then order=(control candidate candidate control); else order=(candidate control control candidate); fi
  for arm in "${order[@]}"; do
    if [[ "$arm" == control ]]; then enabled=0; else enabled=1; fi
    env GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP="$enabled" \
      "$TEST" perf -b ROCmFPXVulkan0 -o MUL_MAT -p "$FILTER" \
      >"$OUTPUT/$(printf '%03d' "$index")-$arm.txt" \
      2>"$OUTPUT/$(printf '%03d' "$index")-$arm.stderr"
    index=$((index + 1))
  done
done
python3 "$ROOT/work/scripts/summarize_backend_abba.py" "$OUTPUT" candidate control \
  >"$OUTPUT/boundary-performance.json"

run_arm() {
  local pair=$1 arm=$2 enabled=$3
  GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=256 \
    REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=on \
    PRIME_RESIDENT_CONTEXT=1 MIN_CACHED_PROMPT_TOKENS=8188 \
    PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
    RESOURCE_SAMPLER_MODE=required LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP="$enabled" \
    BENCH_SEED="$((470918 + pair * 10000))" PORT="$PORT" \
    "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
      --label "v7-bk3-resident256-pair${pair}-${arm}" \
      --output "$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" -- \
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
python3 "$ROOT/work/scripts/summarize_prefill_service_pairs.py" "$OUTPUT" \
  >"$OUTPUT/resident-summary.json"
cat "$OUTPUT/boundary-performance.json"
cat "$OUTPUT/resident-summary.json"
