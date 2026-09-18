#!/usr/bin/env bash
set -euo pipefail

# Reproducible C<=4 benchmark for a llama.cpp-compatible server. Generated
# artifacts include hashes, effective server properties and raw request data.
if [[ "${GPU_RESERVATION_CONFIRMED:-0}" != "1" ]]; then
  echo "Refusing to start a GPU server: set GPU_RESERVATION_CONFIRMED=1." >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
WORK_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
VLLM_ROOT=${VLLM_ROOT:-/home/isaac/vllm-challenge}
PYTHON=${PYTHON:-$VLLM_ROOT/bin/python}
RESOURCE_SAMPLER=${RESOURCE_SAMPLER:-$SCRIPT_DIR/resource_sampler.py}
RESOURCE_SAMPLER_MODE=${RESOURCE_SAMPLER_MODE:-required}
SAMPLE_INTERVAL=${SAMPLE_INTERVAL:-0.25}
PORT=${PORT:-8002}
HOST=${HOST:-127.0.0.1}
LABEL=${LABEL:-llama-backend}
MODEL=${MODEL:-}
TOKENIZER=${TOKENIZER:-$VLLM_ROOT/models/LFM2.5-2.6B}
SERVER=${SERVER:-}
PROMPT_TOKENS=${PROMPT_TOKENS:-128}
MAX_TOKENS=${MAX_TOKENS:-64}
REPETITIONS=${REPETITIONS:-3}
WARMUP=${WARMUP:-1}
TIMEOUT=${TIMEOUT:-600}
BENCH_SEED=${BENCH_SEED:-260916}
CONCURRENCIES=${CONCURRENCIES:-"1 2 3 4"}
CACHE_PROMPT=${CACHE_PROMPT:-off}
PROMPT_MODE=${PROMPT_MODE:-varied}
SLOT_POLICY=${SLOT_POLICY:-auto}
SLOT_IDS=${SLOT_IDS:-}
WORKLOAD_KIND=${WORKLOAD_KIND:-controlled_fixed_output}
ARRIVAL_STAGGER_MS=${ARRIVAL_STAGGER_MS:-0}
PRIME_RESIDENT_CONTEXT=${PRIME_RESIDENT_CONTEXT:-0}
MIN_CACHED_PROMPT_TOKENS=${MIN_CACHED_PROMPT_TOKENS:-0}

usage() {
  echo "Usage: GPU_RESERVATION_CONFIRMED=1 $0 --server BIN --model GGUF [options] [-- server-extra-args...]" >&2
  echo "  --label NAME       result label" >&2
  echo "  --port PORT        isolated HTTP port" >&2
  echo "  --output DIR       result directory" >&2
  echo "  --tokenizer PATH   local tokenizer" >&2
  echo "  --seed N           base workload seed" >&2
}

OUTPUT_DIR=""
SERVER_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER=$2; shift 2 ;;
    --model) MODEL=$2; shift 2 ;;
    --label) LABEL=$2; shift 2 ;;
    --port) PORT=$2; shift 2 ;;
    --output) OUTPUT_DIR=$2; shift 2 ;;
    --tokenizer) TOKENIZER=$2; shift 2 ;;
    --seed) BENCH_SEED=$2; shift 2 ;;
    --) shift; SERVER_ARGS=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ -z "$SERVER" || -z "$MODEL" ]]; then
  echo "--server and --model are required" >&2
  exit 2
fi
if [[ ! -x "$SERVER" || ! -f "$MODEL" || ! -d "$TOKENIZER" ]]; then
  echo "server/model/tokenizer validation failed" >&2
  exit 2
fi
if [[ "$CACHE_PROMPT" != "on" && "$CACHE_PROMPT" != "off" ]]; then
  echo "CACHE_PROMPT must be on or off" >&2
  exit 2
fi
if [[ "$WORKLOAD_KIND" != "controlled_fixed_output" && "$WORKLOAD_KIND" != "service_eos_enabled" ]]; then
  echo "WORKLOAD_KIND must be controlled_fixed_output or service_eos_enabled" >&2
  exit 2
fi
if [[ "$RESOURCE_SAMPLER_MODE" != "required" && "$RESOURCE_SAMPLER_MODE" != "disabled" ]]; then
  echo "RESOURCE_SAMPLER_MODE must be required or disabled" >&2
  exit 2
fi
if [[ "$PRIME_RESIDENT_CONTEXT" != "0" && "$PRIME_RESIDENT_CONTEXT" != "1" ]]; then
  echo "PRIME_RESIDENT_CONTEXT must be 0 or 1" >&2
  exit 2
fi
if [[ "$RESOURCE_SAMPLER_MODE" == "required" && ! -f "$RESOURCE_SAMPLER" ]]; then
  echo "resource sampler is required but missing: $RESOURCE_SAMPLER" >&2
  exit 2
fi
if [[ -z "$OUTPUT_DIR" ]]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  OUTPUT_DIR="$WORK_DIR/results/${LABEL}-${stamp}"
fi
if [[ -d "$OUTPUT_DIR" ]] && find "$OUTPUT_DIR" -mindepth 1 -print -quit | grep -q .; then
  echo "output directory is not empty: $OUTPUT_DIR" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR"

SERVER_LOG="$OUTPUT_DIR/server.log"
RESOURCE_CSV="$OUTPUT_DIR/resources.csv"
COMMAND_TXT="$OUTPUT_DIR/command.txt"
HASHES_TXT="$OUTPUT_DIR/hashes.txt"
ENV_TXT="$OUTPUT_DIR/environment.txt"

cache_server_arg=--no-cache-prompt
if [[ "$CACHE_PROMPT" == "on" ]]; then
  cache_server_arg=--cache-prompt
fi

{
  printf 'date_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'label=%q\nserver=%q\nmodel=%q\ntokenizer=%q\nhost=%q\nport=%q\n' \
    "$LABEL" "$SERVER" "$MODEL" "$TOKENIZER" "$HOST" "$PORT"
  printf 'prompt_tokens=%q\nmax_tokens=%q\nrepetitions=%q\nwarmup=%q\nseed=%q\n' \
    "$PROMPT_TOKENS" "$MAX_TOKENS" "$REPETITIONS" "$WARMUP" "$BENCH_SEED"
  printf 'concurrencies=%q\ncache_prompt=%q\nprompt_mode=%q\nslot_policy=%q\nslot_ids=%q\nworkload_kind=%q\narrival_stagger_ms=%q\n' \
    "$CONCURRENCIES" "$CACHE_PROMPT" "$PROMPT_MODE" "$SLOT_POLICY" "$SLOT_IDS" "$WORKLOAD_KIND" "$ARRIVAL_STAGGER_MS"
  printf 'prime_resident_context=%q\nmin_cached_prompt_tokens=%q\n' "$PRIME_RESIDENT_CONTEXT" "$MIN_CACHED_PROMPT_TOKENS"
  printf 'resource_sampler_mode=%q\nresource_sampler=%q\n' "$RESOURCE_SAMPLER_MODE" "$RESOURCE_SAMPLER"
  printf 'fixed_server_args=-ngl\ 99\ -fa\ on\ -np\ 4\ -cb\ %q\ --cache-reuse\ 0\n' "$cache_server_arg"
  printf 'server_args='; printf '%q ' "${SERVER_ARGS[@]}"; printf '\n'
} >"$COMMAND_TXT"

model_sha256_before=$(sha256sum "$MODEL" | awk '{print $1}')
sha256sum "$SERVER" "$MODEL" "$SCRIPT_DIR/bench_client.py" >"$HASHES_TXT"
if [[ "$RESOURCE_SAMPLER_MODE" == "required" ]]; then
  sha256sum "$RESOURCE_SAMPLER" >>"$HASHES_TXT"
fi
find "$TOKENIZER" -maxdepth 1 -type f -print0 | sort -z | xargs -0 -r sha256sum >>"$HASHES_TXT"
{
  printf 'uname='; uname -a
  printf 'ld_preload=%s\n' "${LD_PRELOAD:-}"
  printf 'ld_library_path=%s\n' "${LD_LIBRARY_PATH:-}"
  printf 'hsa_override_gfx_version=%s\n' "${HSA_OVERRIDE_GFX_VERSION:-}"
  printf 'ggml_vk_visible_devices=%s\n' "${GGML_VK_VISIBLE_DEVICES:-}"
  printf 'rocmfpx_plugin_path=%s\n' "${ROCMFPX_PLUGIN_PATH:-}"
  printf 'rocmfpx_mmq_bk2_gateup=%s\n' "${GGML_VK_ROCMFP4_FAST_MMQ_BK2_GATEUP:-}"
  printf 'rocmfpx_fa_rdna2_no_occupancy_limit=%s\n' "${GGML_VK_FA_RDNA2_NO_OCCUPANCY_LIMIT:-}"
  printf 'power_dpm_force_performance_level='; cat /sys/class/drm/card1/device/power_dpm_force_performance_level 2>/dev/null || true
  printf 'power_profile_active='; sed -n 's/^ \?\([0-9][0-9]* [^:]*\)\*:.*/\1/p' \
    /sys/class/drm/card1/device/pp_power_profile_mode 2>/dev/null || true
} >"$ENV_TXT"
ldd "$SERVER" >"$OUTPUT_DIR/ldd.txt"

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
    for _ in $(seq 1 20); do
      kill -0 "$server_pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$server_pid" 2>/dev/null
    wait "$server_pid" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

if curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
  echo "port $PORT already serves a live endpoint" >&2
  exit 2
fi

"$SERVER" --model "$MODEL" --host "$HOST" --port "$PORT" \
  -ngl 99 -fa on -np 4 -cb "$cache_server_arg" --cache-reuse 0 "${SERVER_ARGS[@]}" \
  >"$SERVER_LOG" 2>&1 &
server_pid=$!
printf 'server_pid=%s\n' "$server_pid" >>"$COMMAND_TXT"

ready=0
for _ in $(seq 1 300); do
  if curl -fsS --max-time 2 "http://$HOST:$PORT/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    tail -n 80 "$SERVER_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "server did not become ready" >&2
  exit 1
fi

# Hash what the live process actually executes and maps. The small launcher is
# retained above, but it is not accepted as the server implementation hash.
{
  readlink -f "/proc/$server_pid/exe"
  awk '$NF ~ /^\// {print $NF}' "/proc/$server_pid/maps" | sed 's/ (deleted)$//'
} | sort -u >"$OUTPUT_DIR/loaded-files.txt"
while IFS= read -r loaded_file; do
  if [[ -f "$loaded_file" ]]; then
    sha256sum "$loaded_file"
  fi
done <"$OUTPUT_DIR/loaded-files.txt" >>"$HASHES_TXT"

curl -fsS --max-time 10 "http://$HOST:$PORT/props" >"$OUTPUT_DIR/props.json" || true
curl -fsS --max-time 10 "http://$HOST:$PORT/slots" >"$OUTPUT_DIR/slots-before.json" || true

if [[ "$RESOURCE_SAMPLER_MODE" == "required" ]]; then
  "$PYTHON" "$RESOURCE_SAMPLER" --output "$RESOURCE_CSV" --interval "$SAMPLE_INTERVAL" \
    --pid "$server_pid" >"$OUTPUT_DIR/resource-sampler.log" 2>&1 &
  sampler_pid=$!
  for _ in $(seq 1 20); do
    if [[ -s "$RESOURCE_CSV" ]]; then
      break
    fi
    if ! kill -0 "$sampler_pid" 2>/dev/null; then
      cat "$OUTPUT_DIR/resource-sampler.log" >&2 || true
      echo "required resource sampler exited before producing data" >&2
      exit 5
    fi
    sleep 0.1
  done
  if [[ ! -s "$RESOURCE_CSV" ]]; then
    echo "required resource sampler produced no data" >&2
    exit 5
  fi
  printf 'enabled\n' >"$OUTPUT_DIR/resource-sampler-status.txt"
else
  printf 'disabled: RESOURCE_SAMPLER_MODE=disabled\n' >"$OUTPUT_DIR/resource-sampler-status.txt"
fi

for concurrency in $CONCURRENCIES; do
  slot_args=()
  if [[ -n "$SLOT_IDS" ]]; then
    slot_args=(--slot-ids "$SLOT_IDS")
  fi
  resident_args=()
  if [[ "$PRIME_RESIDENT_CONTEXT" == "1" ]]; then
    resident_args=(--prime-resident-context --min-cached-prompt-tokens "$MIN_CACHED_PROMPT_TOKENS")
  fi
  "$PYTHON" "$SCRIPT_DIR/bench_client.py" \
    --base-url "http://$HOST:$PORT" \
    --model "$MODEL" --tokenizer "$TOKENIZER" --request-model "$MODEL" \
    --prompt-tokens "$PROMPT_TOKENS" --max-tokens "$MAX_TOKENS" \
    --concurrency "$concurrency" --repetitions "$REPETITIONS" --warmup "$WARMUP" \
    --timeout "$TIMEOUT" --seed "$((BENCH_SEED + concurrency * 1009))" \
    --prompt-mode "$PROMPT_MODE" --cache-prompt "$CACHE_PROMPT" \
    --slot-policy "$SLOT_POLICY" "${slot_args[@]}" \
    --workload-kind "$WORKLOAD_KIND" --arrival-stagger-ms "$ARRIVAL_STAGGER_MS" \
    "${resident_args[@]}" \
    --label "${LABEL}-c${concurrency}" --output "$OUTPUT_DIR/c${concurrency}.json" \
    | tee "$OUTPUT_DIR/c${concurrency}.stdout.jsonl"
done

model_sha256_after=$(sha256sum "$MODEL" | awk '{print $1}')
if [[ "$model_sha256_before" != "$model_sha256_after" ]]; then
  echo "model changed during benchmark: $MODEL" >&2
  exit 4
fi

curl -fsS --max-time 10 "http://$HOST:$PORT/slots" >"$OUTPUT_DIR/slots-after.json" || true
echo "completed $OUTPUT_DIR"
