#!/usr/bin/env bash
set -euo pipefail

if [[ "${GPU_RESERVATION_CONFIRMED:-0}" != "1" ]]; then
  echo "Refusing to start a GPU server: set GPU_RESERVATION_CONFIRMED=1." >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
PYTHON=${PYTHON:-/home/isaac/vllm-challenge/bin/python}
SERVER=${SERVER:?SERVER is required}
MODEL=${MODEL:?MODEL is required}
TOKENIZER=${TOKENIZER:-/home/isaac/vllm-challenge/models/LFM2.5-2.6B}
OUTPUT=${OUTPUT:?OUTPUT is required}
DEVICE=${DEVICE:-ROCmFPXVulkan0}
PORT=${PORT:-18186}
HOST=${HOST:-127.0.0.1}
RESOURCE_SAMPLER=${RESOURCE_SAMPLER:-$SCRIPT_DIR/resource_sampler.py}
CONTEXT_TOKENS=${CONTEXT_TOKENS:-8192}
DECODE_TOKENS=${DECODE_TOKENS:-768}
MIN_CACHED_PROMPT_TOKENS=${MIN_CACHED_PROMPT_TOKENS:-8188}
DECODER_COUNTS=${DECODER_COUNTS:-"1 2 3"}
PREFILL_CHUNK_TOKENS=${LLAMA_SERVER_PREFILL_CHUNK_TOKENS:-0}

if [[ -d "$OUTPUT" ]] && find "$OUTPUT" -mindepth 1 -print -quit | grep -q .; then
  echo "output directory is not empty: $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"

sha256sum "$SERVER" "$MODEL" "$SCRIPT_DIR/interference_client.py" "$RESOURCE_SAMPLER" >"$OUTPUT/hashes.txt"
find "$TOKENIZER" -maxdepth 1 -type f -print0 | sort -z | xargs -0 -r sha256sum >>"$OUTPUT/hashes.txt"
printf 'server=%q\nmodel=%q\ndevice=%q\ncontext_tokens=%q\ndecode_tokens=%q\ndecoder_counts=%q\nprefill_chunk_tokens=%q\n' \
  "$SERVER" "$MODEL" "$DEVICE" "$CONTEXT_TOKENS" "$DECODE_TOKENS" \
  "$DECODER_COUNTS" "$PREFILL_CHUNK_TOKENS" >"$OUTPUT/command.txt"

server_pid=0
sampler_pid=0
cleanup() {
  set +e
  if [[ "$sampler_pid" -gt 0 ]] && kill -0 "$sampler_pid" 2>/dev/null; then
    kill -TERM "$sampler_pid" 2>/dev/null
    wait "$sampler_pid" 2>/dev/null
  fi
  if [[ "$server_pid" -gt 0 ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

"$SERVER" --model "$MODEL" --host "$HOST" --port "$PORT" -ngl 99 -fa on -np 4 -cb \
  --cache-prompt --cache-reuse 0 -dev "$DEVICE" -c 36864 --kv-unified-per-slot 9216 \
  -b 4096 -ub 128 -ctk q8_0 -ctv q8_0 >"$OUTPUT/server.log" 2>&1 &
server_pid=$!

for _ in $(seq 1 300); do
  curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1 && break
  kill -0 "$server_pid" 2>/dev/null || { tail -80 "$OUTPUT/server.log" >&2; exit 1; }
  sleep 1
done
curl -fsS --max-time 10 "http://$HOST:$PORT/props" >"$OUTPUT/props.json"
curl -fsS --max-time 10 "http://$HOST:$PORT/slots" >"$OUTPUT/slots-before.json"

{
  readlink -f "/proc/$server_pid/exe"
  awk '$NF ~ /^\// {print $NF}' "/proc/$server_pid/maps" | sed 's/ (deleted)$//'
} | sort -u >"$OUTPUT/loaded-files.txt"
while IFS= read -r file; do [[ -f "$file" ]] && sha256sum "$file"; done <"$OUTPUT/loaded-files.txt" >>"$OUTPUT/hashes.txt"

"$PYTHON" "$RESOURCE_SAMPLER" --output "$OUTPUT/resources.csv" --interval 0.2 --pid "$server_pid" \
  >"$OUTPUT/resource-sampler.log" 2>&1 &
sampler_pid=$!

for n in $DECODER_COUNTS; do
  [[ "$n" =~ ^[123]$ ]] || { echo "invalid decoder count: $n" >&2; exit 2; }
  "$PYTHON" "$SCRIPT_DIR/interference_client.py" --base-url "http://$HOST:$PORT" \
    --tokenizer "$TOKENIZER" --request-model "$MODEL" --n-decoders "$n" \
    --context-tokens "$CONTEXT_TOKENS" --decode-tokens "$DECODE_TOKENS" \
    --min-cached-prompt-tokens "$MIN_CACHED_PROMPT_TOKENS" \
    --output "$OUTPUT/n${n}.json" | tee "$OUTPUT/n${n}.stdout.json"
done

curl -fsS --max-time 10 "http://$HOST:$PORT/slots" >"$OUTPUT/slots-after.json"
echo "completed $OUTPUT"
