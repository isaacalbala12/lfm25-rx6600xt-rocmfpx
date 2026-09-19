#!/usr/bin/env bash
# Format screen V11: does a weight format with no FP4 unpack beat FP4_FAST at
# the prefill shape that dominates the mixed batch?
#
# V9 measured the prefill graph at 83.49% of the mixed pair, so prefill
# throughput is the product lever. V10 closed the FP4 block-layout family
# (padding, global planar, grouped-four) between -1.2% and +43%, which points at
# the weight fetch and unpack path rather than at the dot product. The cheapest
# way to test that is a format whose inner loop needs no FP4 reconstruction.
#
# Q8_0 has never been speed-qualified in this campaign: RESULTS.md lists the
# ROCmFPX Q5-Q8 family as "inventoried, without speed qualification".
#
# Usage: screen_format_prefill.sh <output-dir>
set -euo pipefail

OUT="${1:?usage: screen_format_prefill.sh <output-dir>}"
mkdir -p "$OUT"

WORK=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work
BIN="$WORK/builds/rocmfpx-vulkan-gfx1032-cm1/bin"
PLUGIN="$BIN/rocmfpx-vulkan-plugin.so"

source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH="$PLUGIN"

MODELS=(
  "$WORK/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf"
  "/home/isaac/Escritorio/BenchmarkLLM/models/LFM2.5-2.6B-Q8_0/LFM2.5-2.6B-Q8_0.gguf"
  "$WORK/results/models/LFM2.5-2.6B-Q4_0.gguf"
)

{
  echo "server=$BIN/llama-bench"
  echo "device=ROCmFPXVulkan0"
  echo "repetitions=3"
  echo "prompt_tokens=128,512,2048"
  echo "gen_tokens=128"
  printf 'models=%s\n' "${MODELS[@]}"
} > "$OUT/command.txt"

"$BIN/llama-bench" \
  -m "${MODELS[0]}" -m "${MODELS[1]}" -m "${MODELS[2]}" \
  -dev ROCmFPXVulkan0 -ngl 99 \
  -p 128,512,2048 -n 128 -r 3 \
  > "$OUT/bench.txt" 2> "$OUT/bench.stderr"

cat "$OUT/bench.txt"
