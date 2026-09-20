# V11: state of the art on this machine

The capstone document. Everything below is a service measurement over real HTTP
with no instrumentation, taken with the GPU in its fast clock state, unless the
line says otherwise. Where a claim was withdrawn during the campaign it says so.

## The configuration

Two profiles, because the two workloads have different winners and no single
setting wins both.

### `production-throughput` — 128/64, four concurrent requests

```bash
BIN=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH="$BIN/rocmfpx-vulkan-plugin.so"
export LLAMA_SERVER_COMPACT_SLOTS=1
"$BIN/llama-server" \
  -m .../LFM2.5-2.6B-ROCmFP4_FAST.gguf \
  -dev ROCmFPXVulkan0 -ngl 99 -fa on -np 4 -cb -c 4096 \
  -b 512 -ub 128 -ctk q8_0 -ctv q8_0 --no-cache-prompt --cache-reuse 0
```

Every element is load-bearing and was tested:

| Setting | Why |
| --- | --- |
| `-ub 128` | `ubatch >= 256` costs 2.24x of throughput and 3.6x of TTFT |
| `LLAMA_SERVER_COMPACT_SLOTS=1` | sparse slot IDs cost 208 -> 117 tok/s at C=3 |
| `-ctk/-ctv q8_0` | `q4_0` costs 60% of resident decode throughput |
| `ROCmFP4_FAST` | best decode; the alternative format costs 13% of prefill |
| `-np 4 -cb` | the workload is exactly four concurrent requests |

### `production-interactive` — four slots of 8192 tokens, three resident plus one arriving

Same binary and flags except `-b 4096`, `-c 36864 --kv-unified-per-slot 9216`,
`--cache-prompt`, and `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128`.

The format choice differs here: **Q4_0 wins the interactive profile** by
−7.0% TTFT and −7.2% ITL against FP4_FAST, at the cost of 5.4% of idle resident
decode throughput. That trade is real but it is not free of quality cost; see
the quality section.

## The numbers

### Primary metric, 128/64, C=4, FP4_FAST with the batch fold

| Concurrency | tok/s | vs V2 published |
| ---: | ---: | ---: |
| 1 | 108.10 | +0.1% |
| 2 | 173.84 | +2.8% |
| 3 | 220.65 | +6.2% |
| 4 | **250.36** | **+7.0%** |

Direct decode on four sequences, the cleanest single statement of the fold:
**352.5 tok/s control against 401.3 folded, +13.8%**, three interleaved runs
each, all six in the fast clock state.

### Interactive 8K profile

| Format | TTFT | ITL p95 | Retention | Idle resident |
| --- | ---: | ---: | ---: | ---: |
| ROCmFP4_FAST + fold | 5102 ms | 86.7 ms | 14.9% | 260.4 tok/s |
| **Q4_0 + fold** | **4772 ms** | **81.3 ms** | **16.9%** | 246.2 tok/s |

The interactivity target recorded in V8/V9 — ITL p95 ≤ 70 ms with TTFT ≤ 5.5 s —
**is still not met**. TTFT clears its guardrail; ITL is 16% over. Closing it
needs a further ~15% off the prefill chunk, and the two identified routes
(format, already taken; the `down` gap, unexplained) do not sum to that.

### Quality, measured for the first time in this campaign

| Format | bpw | PPL, 96 chunks | vs Q8_0 |
| --- | ---: | ---: | ---: |
| Q8_0 | 8.50 | 81.47 | — |
| Q4_K_M | 4.94 | 89.09 | +9.4% |
| Q4_0 | 4.70 | 90.94 | +11.6% |
| ROCmFP4_FAST | 4.25 | 94.39 | +15.9% |

All three quantized formats cost real quality. Q4_K_M is the best of them on
both corpora tested. **If quality matters more than the last 7% of TTFT, Q4_K_M
is the right format** and its measured cost is a modest throughput reduction
relative to Q4_0.

## What the remaining gap is made of

Decode at four slots, 9.15 ms per step against a 5.63 ms floor at theoretical
bandwidth:

| Component | ms | Share | Nature |
| --- | ---: | ---: | --- |
| Weight stream at the practical peak (222 GB/s) | 6.50 | 71% | **hardware wall** |
| Matmul inefficiency | 0.98 | 11% | kernel |
| 357 non-matmul dispatches | 1.67 | 18% | **backend architecture** |

The dispatch cost is not bandwidth: `RMS_NORM_MUL` on a 32 KB tensor costs
4.63 µs at batch 1 and 5.08 µs at batch 4, so four times the data costs 10% more
time. It is launch and drain latency, and it is the price of the only execution
path this GPU can use.

## What has been ruled out, with numbers

Do not re-open these; each cost real time and each has a measurement behind it.

- **Other inference engines.** vLLM, SGLang and Lucebox ship no code for any
  gfx103x part. vLLM's extensions contain `gfx90a gfx942 gfx950 gfx1100 gfx1101
  gfx1150 gfx1151 gfx1200 gfx1201` and its `rms_norm`, `fused_add_rms_norm` and
  `silu_and_mul` kernels all segfault here while plain torch matmul works.
  SGLang builds for `gfx942`, `gfx950` and `gfx1151` only. See
  `ENGINE_SUPPORT_V11.md`.
- **`ubatch >= 256`.** 2.24x slower. `ROUND2_V11.md`.
- **KV cache `q4_0`.** 60% of resident decode throughput lost. `ROUND2_V11.md`.
- **Speculative decoding at C=4.** The weights are already amortized across four
  slots, and a 1.2B drafter adds ~49% traffic for ~2.2 tokens per sequence,
  giving ~268 tok/s against 401. It would help at C=1, which is not the target.
- **Split-k overrides** for the prefill shapes. Neutral to catastrophic.
  `PREFILL_LEADS_V11.md`.
- **The FP4 block layout family** (padding, planar, grouped). V10.
- **Roughly 40 shader variants** across V3-V10, best service result +1.16%.
- **`chunk=256`** for prefill. Buys 11% of TTFT and pays 76% of ITL.
- **Format screening at a single shape.** That was the campaign's original
  mistake; the ranking inverts between decode-dominated and prefill-dominated
  workloads.

## Open leads, in order of expected value

1. **The `down` projection gap.** `m=2048 k=10752` runs at 9.25 TFLOPS against
   13.9 for `m=10752 k=2048` with identical MACs and bytes, and it is 26.6% of
   the prefill graph. It is not split-k, not tile selection, and it does not
   appear in the decode path at all. Worth ~9% of prefill if solved. The
   remaining suspect is row geometry: 5,712 bytes per weight row against 1,088.
2. **Dispatch fusion.** `add+rms` is implemented but gated on
   `ggml_nrows(...) == 1`, so it is silently off at every concurrency above one.
   Enabling it needs the partials buffer sized for `nrows x num_partials` and a
   shader that emits per-row partials. Worth 1-2%.
3. **A formal quality evaluation.** The perplexity numbers above come from two
   self-built corpora. A reserved corpus, the BF16 checkpoint converted to GGUF,
   and KL divergence against reference logits would turn them into a quality
   evaluation.

## Measurement protocol

No throughput figure in this repository counts without saying which clock state
it was taken in.

- Every measurement runs interleaved with its control.
- Runs are clustered into fast and slow modes; the reported figure is the fast
  mode, with the split stated.
- `work/scripts/run_with_clock_guard.sh` samples MEMCLK alongside any command.
- The residual slow rate is about 1 in 10 even with the power profile pinned, so
  a single run still has a one in ten chance of being 40% off.

## Reproducing

```bash
GPU_RESERVATION_CONFIRMED=1 work/scripts/run_primary_metric_v11.sh <out>
PAIRS=3 work/scripts/run_format_interference_abba.sh <out>
PAIRS=2 work/scripts/run_backend_interference_abba.sh <out> <control-bin> <candidate-bin>
work/scripts/screen_format_prefill.sh <out>
```

The batch fold lives in `patches/v11-decode-batch-fold.patch` against ROCmFPX
`8634463`, with a kill switch (`GGML_VK_MMV_NO_FOLD_BATCH`) and a trace
(`GGML_VK_MMV_TRACE_FOLD`).
