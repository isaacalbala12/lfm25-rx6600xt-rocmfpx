# Complete handoff after campaign V9

## Mission and hard constraints

Optimize LFM2.5-2.6B on an AMD RX 6600 XT 8 GB (Navi23/gfx1032, RDNA2,
32 CU, wave32) for four simultaneous users with at least 8192 effective context
tokens per user. Production weights must remain at least 4.0 effective BPW;
the current FP4_FAST artifact is about 4.277 BPW. Use one Vulkan backend for the
complete request. Do not change sampler, task, context, drivers, clocks or power
settings, and do not hide slow valid runs.

## Repository and source topology

- Main repository: `isaacalbala12/lfm25-rx6600xt-rocmfpx`.
- Branch: `campaign-v3`.
- Nested source tree: `work/sources/ROCmFPX`.
- The plugin executed by `ROCmFPXVulkan0` is implemented under
  `extensions/rocmfpx-vulkan/backend`, not upstream `ggml/src/ggml-vulkan`.
- Nested source checkpoint after V9: `f5acc76`.
- Reproducible nested delta from the V8 checkpoint is archived as
  `patches/v9-mixed-profile-bpair-ewma.patch`.
- The main repository intentionally stores patches, scripts, documents and raw
  evidence, not model weights or build products.

Contemporary built-artifact SHA-256 values at the checkpoint:

- `llama-server`: `92efcdf0018f4897165c7f4d405e5129b8145ca5f732efb712611d7c722165a0`;
- `libllama-server-impl.so`: `284fe0826a1f0fca439a705e4a795cc7265f0f7d49ac4b4770fec38096e1b190`;
- `libllama.so.0.3.0`: `3067a87a156465c1447256b9feffadd769057a8bc6f943fca99162cccfc03afc`;
- `rocmfpx-vulkan-plugin.so`: `40f3f48cfec7310bcfb017371d1232a7df7935f9e9fcadc2efcdda139832a208`;
- `libggml-rocmfpx-vulkan.so`: `a35c48d9b0790e94e7089e99a22efe4b5290b36a4e041a46ad1de5f5d224c624`;
- FP4_FAST GGUF: `d56f602eb9bcad2cafbe2a52cef2fa14ba09e6290679a2aee164db22815f0933`.

The backend hash includes the opt-in rejected bpair shader bank, while its
default selector still routes production BK3. The server implementation hash
includes the opt-in EWMA controller, while a zero/absent target keeps fixed
chunk128 behavior.

## Production configuration

- runtime R0;
- fixed `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128`;
- selective gate/up BK3 enabled (default);
- ROCmFPXVulkan0 / FP4_FAST;
- q8/q8 KV;
- four slots, global context configured so every slot exposes >=8192 tokens;
- R1 dense remapping remains STAGE and must not be composed yet;
- all V8/V9 experimental shader selectors default off;
- temporal EWMA scheduler defaults off unless
  `LLAMA_SERVER_PREFILL_TARGET_MS` is positive.

## Stable achievements to preserve

1. The benchmark harness distinguishes fixed-output compute workloads from
   service EOS, fails invalid workloads, preserves unknown cache telemetry and
   hashes the real loaded artifacts.
2. Chunk128 is KEEP production. It changed the original 3D+1P service from
   roughly 2189 ms ITL p95 / 1.46% retention to roughly 89 ms / 15.7%, with a
   modest TTFT cost and quality validation.
3. Selective gate/up BK3 is KEEP production. Formal Profile B: +1.1641%
   throughput, CI [+0.8093%, +1.3767%]. Formal 3D+1P: retention +1.5442%, ITL
   p95 -1.4472%, TTFT -1.6769%. Service-EOS quality 7/7 exact. It never routes
   resident decode.
4. The exact Vulkan evaluator is the authority. It has correctness, route and
   stale-artifact hard gates, same-binary controls, ABBA, bootstrap, bounded
   search state and rollback.

## Contemporary V9 control and causal profile

The uninstrumented result under `work/results/v9-mixed-timeline-production`
is the service baseline:

- resident C3 aggregate: 236.261 tok/s;
- during fresh 8K prefill: 38.542 tok/s;
- retention: 16.313%;
- resident ITL p95: 88.471 ms;
- fresh-user TTFT: 5137.25 ms;
- 128-prompt + 3-decode batch: 78.257 ms median, 86.479 ms p95;
- decode-only C3 batch: 11.572 ms median.

The separately instrumented run contains 63 valid mixed batches and two graphs
per batch. Its absolute wall time is perturbed and cannot be quoted as service
performance. Its time shares are useful:

- decode graph: 16.51%;
- prefill graph: 83.49%;
- within prefill: gate/up 35.34%, down 26.64%, FA 13.78%, short-conv 8.66%,
  2048 projections 6.42%, other 9.15%.

The actual mixed prefill graph is N=127, while the separate decode graph is
N=4. Gate/up and down together occupy 61.98% of the prefill graph.

## V9 kernel experiment

`gateup-bk3-bpair` prefetched both TN=2 Q8 columns into two register caches.
Correctness and exact route passed, but five ABBA pairs measured 412.085 us
control versus 413.485 us candidate: +0.767% latency, CI
[-0.144%, +0.825%]. SPIR-V grew 4.15% in instructions and added 18 access
chains, 9 loads and 9 stores. Decision: REJECT_MICRO. There was no server run.

Do not retry this exact array-cache implementation. It appears to materialize
extra private-memory traffic. This does not prove every software pipeline is
bad, but a future version needs static evidence that it actually reduces or
reorders instructions without adding address/load traffic.

## V9 scheduler experiment

The opt-in temporal scheduler measures completed mixed decode wall time, keeps
an EWMA of milliseconds per prompt token and picks a prompt chunk in [64,128].
It is default-off and was evaluated against fixed chunk128 in the same binary.

EWMA target 65 ms, three paired runs:

- retention +16.61%;
- ITL p95 -14.63% (87.085 -> 74.678 ms);
- TTFT +47.97% (5150 -> 7583 ms).

EWMA target 68 ms, one exploratory pair:

- retention +8.62%;
- ITL p95 -13.12% (88.310 -> 76.720 ms);
- TTFT +44.64% (5146 -> 7442 ms).

Both are REJECT production. The diagnostic shows a nonlinear cliff: chunks
64/65 are around 59.45 ms, while 66/67 are around 69--71 ms. Tail batches and
startup at 128 contaminate a simple ms/token ratio. More importantly, even the
aggressive controller cannot meet <=70 ms p95 while respecting <=5.5 s TTFT.
Do not perform another generic target/chunk sweep. A future scheduler should be
shape-aware with hysteresis, but only after a new kernel win lowers the work.

## Important closed hypotheses

Do not repeat without genuinely new evidence:

- gate/up 2- or 4-subgroup reductions;
- decode rows4, dual accumulators or arithmetic FP4 unpack;
- naive packed32 extraction;
- BM32/BN128 gate or BM32/BN64 down;
- broad N-only selection;
- global BK2/BK3; selective BK3 is already production;
- explicit compute-loop unroll directives;
- V8 exact-shape/bounds-only variants as standalone promotions;
- V8 down Q8-group4, including its non-additive composition with down-exact;
- Q8 preparation caching (gate/up already shares graph-local preparation);
- rebatching 6144x2048: four users are already represented in `ne[2]=4`;
- chunk96, chunk256, unlimited or idle-unlimited scheduling;
- EWMA ratio controllers at 65/68 ms with min chunk 64;
- FA occupancy bypass and Bc64 tile;
- HIP synchronization removal, Q2, MTP, hybrid backends or power tuning.

## Archived composable signals

- selective gate BK2: +0.486% full Profile B, superseded by production BK3;
- V8 down exact shape: -2.1607% local, only ~0.48% contemporary mixed ceiling;
- V8 gate exact shape: -1.3163% local, only ~0.39% contemporary mixed ceiling.

Do not add these percentages. They modify overlapping paths or may not compose.
Only retest them alongside a new independent KEEP candidate.

## Recommended next experiment

The next high-leverage family is reversible prepacking/layout for one hot
FP4_FAST tensor family. Start with gate/up because it is 35.34% of the prefill
graph, but prototype only one layer/matrix before duplicating weights.

The hypothesis must be concrete: reorder the same FP4 codes and scales into the
`[K-block][M-tile]`/lane-consumption order used by wave32 to remove address
chains and make code/scale loads coalesced. Preserve exact values. Include the
one-time prepack, extra VRAM, selector and fallback. Benchmark N=127, N=128 and
a real tail. A local gain below roughly 2.55% on gate/up cannot clear a 0.75%
whole-mixed leverage gate under the contemporary share and should not proceed
to the server.

Before implementing a large layout conversion, extend the exact microbench so
one real gate tensor can be packed once and rotated among representative
matrices. Record model headroom to ensure C4x8K still fits safely. If the layout
prototype fails, close MMQ and reprofile the 9.15% prefill `other` bucket by
exact operation rather than reopening FA or scheduler sweeps.

## Reproduction commands

From the main repository root:

```bash
# Uninstrumented contemporary 3D+1P control
OUT_DIR="$PWD/work/results/repro-v9-mixed" \
LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128 \
bash work/scripts/run_interference_profile.sh

# Analyze an instrumented server log (profiling run only)
python3 work/scripts/analyze_mixed_batch_profile.py \
  work/results/v9-mixed-operation-profile/server.log \
  --output /tmp/mixed-summary.json

# Re-run temporal scheduler AB/BA, target 65 ms
TARGET_MS=65 PAIRS=3 \
OUT_ROOT="$PWD/work/results/repro-v9-ewma65" \
bash work/scripts/run_v9_ewma_interference_abba.sh

# Verify the nested patch matches the current nested checkpoint
git -C work/sources/ROCmFPX apply --check --reverse \
  "$PWD/patches/v9-mixed-profile-bpair-ewma.patch"
```

The exact gate candidate manifest is
`work/atrex_v9/gate_candidates/gateup-bk3-bpair.json`; its authoritative result
is `work/results/v9-gate-search/gateup-bk3-bpair/result.json`.

## Validity and operational warnings

- Only one GPU load at a time.
- Keep profiler and service runs separate.
- Unknown cache telemetry is not zero cache reuse.
- Preserve all valid slow batches unless an objective exclusion applies.
- Verify loaded library hashes, not just the launcher.
- Experimental environment variables are presence/value-sensitive; explicitly
  unset them for production validation.
- Model and build artifacts stay outside Git.
- The current binary contains opt-in rejected experiments, but defaults route
  to production BK3 and fixed chunk128. Rebuilding from the archived patch is
  reproducible; do not enable bpair or EWMA in production.
- Repository tests pass 28/28. A final exact CPU-reference route check with all
  V9 experiment variables unset selected
  `matmul_rocmfp4_fast_q8_1_bk3_m` and passed 1/1 operations.
