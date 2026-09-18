#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
SOURCE=${SOURCE:-$ROOT/work/sources/ROCmFPX}
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
BACKEND=${BACKEND:-$BUILD/bin/libggml-rocmfpx-vulkan.so}
PLUGIN=${PLUGIN:-$BUILD/bin/rocmfpx-vulkan-plugin.so}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf}
CMAKE=${CMAKE:-/home/isaac/vllm-challenge/toolchain/bin/cmake}
PYTHON=${PYTHON:-/home/isaac/vllm-challenge/bin/python}
PATCH=$ROOT/patches/v6-auto/gateup-selective-bkstep3.patch
RUNNER=$ROOT/work/scripts/benchmark_llama_backend.sh
QUALITY_CLIENT=$ROOT/work/scripts/service_quality_client.py
QUALITY_COMPARE=$ROOT/work/scripts/compare_service_quality.py
CORPUS=$ROOT/work/quality/service_eos_v5.json
OUTPUT=${OUTPUT:-$ROOT/work/results/v7-bk3-final-guardrails}
PORT=${PORT:-18234}
PAIRS=${PAIRS:-3}
PATCH_APPLIED=0
server_pid=0
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_BACKEND_PATH=$BACKEND
export ROCMFPX_PLUGIN_PATH=$PLUGIN

if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if [[ -n "$(git -C "$SOURCE" status --porcelain)" ]]; then
  echo "ROCmFPX source is not clean" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_v7_bk3_final' >/dev/null; then
  echo "another inference process is active" >&2
  exit 2
fi
mkdir -p "$OUTPUT"
sha256sum "$BACKEND" >"$OUTPUT/control-backend.sha256"
CONTROL_HASH=$(cut -d' ' -f1 "$OUTPUT/control-backend.sha256")

stop_server() {
  if (( server_pid > 0 )) && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  server_pid=0
}

cleanup() {
  local status=$?
  stop_server
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
    echo "ROCmFPX source not clean after guardrails" >&2
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
sha256sum "$SERVER" "$PLUGIN" "$BACKEND" "$MODEL" "$CORPUS" >"$OUTPUT/candidate-hashes.txt"
if [[ "$CONTROL_HASH" == "$(sha256sum "$BACKEND" | cut -d' ' -f1)" ]]; then
  echo "candidate backend was not rebuilt" >&2
  exit 2
fi

run_resident_arm() {
  local pair=$1 arm=$2 enabled=$3
  GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=8 \
    REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=on \
    PRIME_RESIDENT_CONTEXT=1 MIN_CACHED_PROMPT_TOKENS=8188 \
    PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
    RESOURCE_SAMPLER_MODE=required LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP="$enabled" \
    BENCH_SEED="$((270918 + pair * 10000))" PORT="$PORT" \
    "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
      --label "v7-bk3-resident-pair${pair}-${arm}" \
      --output "$OUTPUT/pair-$(printf '%02d' "$pair")-$arm" -- \
      -dev ROCmFPXVulkan0 -c 34816 --kv-unified-per-slot 8704 \
      -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
}

for ((pair=0; pair<PAIRS; pair++)); do
  if (( pair % 2 == 0 )); then arms=(control candidate); else arms=(candidate control); fi
  for arm in "${arms[@]}"; do
    if [[ "$arm" == control ]]; then enabled=0; else enabled=1; fi
    run_resident_arm "$pair" "$arm" "$enabled"
  done
done
python3 "$ROOT/work/scripts/summarize_prefill_service_pairs.py" "$OUTPUT" \
  >"$OUTPUT/resident-summary.json"

# Diagnostic-only selector trace. It is not used for wall performance.
GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=8192 MAX_TOKENS=8 \
  REPETITIONS=1 WARMUP=0 CONCURRENCIES=4 CACHE_PROMPT=off \
  PROMPT_MODE=varied SLOT_POLICY=compact WORKLOAD_KIND=controlled_fixed_output \
  RESOURCE_SAMPLER_MODE=disabled LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
  GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP=1 GGML_VK_SELECTION_LOGGER=1 \
  BENCH_SEED=370918 PORT="$PORT" \
  "$RUNNER" --server "$SERVER" --model "$MODEL" --port "$PORT" \
    --label v7-bk3-selector-trace --output "$OUTPUT/selector-trace" -- \
    -dev ROCmFPXVulkan0 -c 34816 --kv-unified-per-slot 8704 \
    -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
"$PYTHON" "$ROOT/work/scripts/summarize_gateup_selection.py" \
  "$OUTPUT/selector-trace/server.log" --output "$OUTPUT/gateup-n-histogram.json"

run_quality_arm() {
  local arm=$1 enabled=$2 arm_dir="$OUTPUT/quality-$1"
  mkdir -p "$arm_dir"
  env LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
    GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP="$enabled" \
    "$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" \
      -ngl 99 -fa on -np 4 -cb --cache-prompt --cache-reuse 0 \
      -dev ROCmFPXVulkan0 -c 36864 --kv-unified-per-slot 9216 \
      -b 4096 -ub 128 -ctk q8_0 -ctv q8_0 >"$arm_dir/server.log" 2>&1 &
  server_pid=$!
  for _ in $(seq 1 300); do
    curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
    kill -0 "$server_pid" 2>/dev/null || { tail -80 "$arm_dir/server.log" >&2; exit 1; }
    sleep 1
  done
  curl -fsS --max-time 10 "http://127.0.0.1:$PORT/props" >"$arm_dir/props.json"
  {
    readlink -f "/proc/$server_pid/exe"
    awk '$NF ~ /^\// {print $NF}' "/proc/$server_pid/maps" | sed 's/ (deleted)$//'
  } | sort -u >"$arm_dir/loaded-files.txt"
  while IFS= read -r file; do [[ -f "$file" ]] && sha256sum "$file"; done \
    <"$arm_dir/loaded-files.txt" >"$arm_dir/hashes.txt"
  "$PYTHON" "$QUALITY_CLIENT" --base-url "http://127.0.0.1:$PORT" \
    --model "$MODEL" --corpus "$CORPUS" --output "$arm_dir/result.json"
  stop_server
}

run_quality_arm control 0
run_quality_arm candidate 1
"$PYTHON" "$QUALITY_COMPARE" "$OUTPUT/quality-control/result.json" \
  "$OUTPUT/quality-candidate/result.json" --output "$OUTPUT/quality-comparison.json"

cat "$OUTPUT/resident-summary.json"
cat "$OUTPUT/gateup-n-histogram.json"
cat "$OUTPUT/quality-comparison.json"
