#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
BUILD=${BUILD:-$ROOT/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented}
SERVER=${SERVER:-$BUILD/bin/llama-server}
MODEL=${MODEL:-$ROOT/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf}
TOKENIZER=${TOKENIZER:-/home/isaac/vllm-challenge/models/LFM2.5-2.6B}
PYTHON=${PYTHON:-/home/isaac/vllm-challenge/bin/python}
PORT=${PORT:-18161}
POLICY=${POLICY:-r1}
MODE=${MODE:-forced}
BACKEND_SAMPLING=${BACKEND_SAMPLING:-off}
LABEL=${LABEL:-v3-remap-${POLICY}-${MODE}-sampling-${BACKEND_SAMPLING}}
OUTPUT=${OUTPUT:-$ROOT/work/results/$LABEL}

case "$POLICY" in
  r0) lowest=1; dense=0 ;;
  r1) lowest=1; dense=1 ;;
  *) echo "POLICY must be r0 or r1" >&2; exit 2 ;;
esac
if [[ -e "$OUTPUT" ]]; then
  echo "output already exists: $OUTPUT" >&2
  exit 2
fi
if pgrep -af 'llama-server|vllm|python.*api_server' | grep -v -E 'pgrep|run_dynamic_remap_validation' >/dev/null; then
  echo "another inference process is active" >&2
  pgrep -af 'llama-server|vllm|python.*api_server' >&2 || true
  exit 2
fi

mkdir -p "$OUTPUT"
server_pid=0
cleanup() {
  set +e
  if [[ "$server_pid" -gt 0 ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH=$BUILD/bin/rocmfpx-vulkan-plugin.so
export LLAMA_SERVER_LOWEST_SLOT=$lowest
export LLAMA_SERVER_DENSE_SEQUENCES=$dense
export LLAMA_SERVER_REMAP_TRACE=1
export LLAMA_RECURRENT_TRACE=0
export GGML_VK_SELECTION_LOGGER=0
export GGML_VK_PERF_LOGGER=0

{
  printf 'policy=%s\nlowest_slot_first=%s\ndense_sequences=%s\nmode=%s\nbackend_sampling=%s\n' \
    "$POLICY" "$lowest" "$dense" "$MODE" "$BACKEND_SAMPLING"
  printf 'server=%s\nmodel=%s\ntokenizer=%s\nport=%s\n' "$SERVER" "$MODEL" "$TOKENIZER" "$PORT"
  printf 'server_args=-ngl 99 -fa on -np 4 -cb --no-cache-prompt --cache-reuse 0 -b 4096 -ub 128 -ctk q8_0 -ctv q8_0\n'
} >"$OUTPUT/command.txt"

sha256sum "$SERVER" "$MODEL" "$ROCMFPX_PLUGIN_PATH" \
  "$BUILD/bin/libllama-server-impl.so" "$BUILD/bin/libllama.so" \
  "$BUILD/bin/libggml-rocmfpx-vulkan.so" "$ROOT/work/scripts/dynamic_slot_reproducer.py" \
  >"$OUTPUT/hashes.txt"
find "$TOKENIZER" -maxdepth 1 -type f -print0 | sort -z | xargs -0 -r sha256sum >>"$OUTPUT/hashes.txt"

"$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" \
  -ngl 99 -fa on -np 4 -cb --no-cache-prompt --cache-reuse 0 \
  -b 4096 -ub 128 -ctk q8_0 -ctv q8_0 >"$OUTPUT/server.log" 2>&1 &
server_pid=$!

ready=0
for _ in $(seq 1 300); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    tail -n 100 "$OUTPUT/server.log" >&2
    exit 1
  fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo "server did not become ready" >&2; exit 1; }

{
  readlink -f "/proc/$server_pid/exe"
  awk '$NF ~ /^\// {print $NF}' "/proc/$server_pid/maps" | sed 's/ (deleted)$//'
} | sort -u >"$OUTPUT/loaded-files.txt"
while IFS= read -r file; do
  [[ -f "$file" ]] && sha256sum "$file"
done <"$OUTPUT/loaded-files.txt" >"$OUTPUT/loaded-hashes.txt"

"$PYTHON" "$ROOT/work/scripts/dynamic_slot_reproducer.py" \
  --base-url "http://127.0.0.1:$PORT" --model "$MODEL" --tokenizer "$TOKENIZER" \
  --mode "$MODE" --backend-sampling "$BACKEND_SAMPLING" --output "$OUTPUT/result.json" \
  | tee "$OUTPUT/client.stdout.json"

grep -E 'sequence policy|SEQCOMPACT|vector::_M_range_check|got exception' "$OUTPUT/server.log" >"$OUTPUT/remap-events.log" || true
