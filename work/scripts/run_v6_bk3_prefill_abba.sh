#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SOURCE=${SOURCE:-$ROOT/work/sources/ROCmFPX}
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
CMAKE=${CMAKE:-/home/isaac/vllm-challenge/toolchain/bin/cmake}
PATCH=$ROOT/patches/v6-auto/gateup-selective-bkstep3.patch
RUNNER=$ROOT/work/scripts/benchmark_llama_backend.sh
OUTPUT=${OUTPUT:-$ROOT/work/results/v6-prefill8k-c4-selective-bk3-paired3}
PAIRS=${PAIRS:-3}
PORT=${PORT:-18230}
PATCH_APPLIED=0

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
  echo "ROCmFPX source is not clean" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v6_bk3_prefill' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
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
      echo "candidate patch could not be reversed" >>"$OUTPUT/restore-build.stderr"
      status=2
    fi
  fi
  sha256sum "$BACKEND" >"$OUTPUT/restored-backend.sha256" 2>/dev/null || status=2
  if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
    echo "ROCmFPX source not clean after server run" >&2
    status=2
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

git -C "$SOURCE" apply --check "$PATCH"
git -C "$SOURCE" apply "$PATCH"
PATCH_APPLIED=1
"$CMAKE" --build "$BUILD" --target ggml-rocmfpx-vulkan -j 2 \
  >"$OUTPUT/build.stdout" 2>"$OUTPUT/build.stderr"
sha256sum "$SERVER" "$BACKEND" "$MODEL" >"$OUTPUT/candidate-hashes.txt"
if [[ "$CONTROL_HASH" == "$(sha256sum "$BACKEND" | cut -d' ' -f1)" ]]; then
  echo "candidate backend was not rebuilt" >&2
  exit 2
fi

run_arm() {
  local pair=$1 arm=$2 enabled=$3
  local destination="$OUTPUT/pair-$(printf '%02d' "$pair")-$arm"
  GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=256 \
    REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=off \
    PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
    RESOURCE_SAMPLER_MODE=required LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP="$enabled" \
    BENCH_SEED="$((260918 + pair * 10000))" PORT="$PORT" \
    "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
      --label "v6-bk3-pair${pair}-${arm}" --output "$destination" -- \
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
  >"$OUTPUT/summary.json"
cat "$OUTPUT/summary.json"
