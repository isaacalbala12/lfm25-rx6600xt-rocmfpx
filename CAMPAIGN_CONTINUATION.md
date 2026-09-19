# LFM2.5 RX 6600 XT performance campaign — continuation guide

This is the public entry point for continuing the engineering campaign on
`campaign-v3`. It summarizes the current production configuration, the evidence
that must be preserved, closed hypotheses, raw-result locations and the exact
next experiment. The current detailed audit is
[`work/HANDOFF_V10.md`](work/HANDOFF_V10.md); V9 remains the source for the
mixed-workload profile.

## Objective and constraints

Maximize real LFM2.5-2.6B service performance on an RX 6600 XT 8 GB
(Navi23/gfx1032, RDNA2, 32 CU, wave32) for four concurrent users, each with at
least 8192 effective context tokens.

Hard constraints:

- production weights must remain at least 4.0 effective BPW;
- current FP4_FAST artifact is about 4.277 BPW;
- one complete Vulkan backend per request, with no HIP/Vulkan hybrid;
- no context, sampler or quality reduction hidden as an optimization;
- no driver, firmware, clock or power changes;
- valid slow runs remain part of the evidence;
- profiling runs and service benchmarks are separate experiments.

## Current production state

- Runtime: R0.
- Backend: ROCmFPXVulkan0, using the plugin-owned Vulkan implementation under
  `extensions/rocmfpx-vulkan/backend`.
- Weights: FP4_FAST.
- KV: q8/q8.
- Scheduler: fixed 128-token prefill chunks.
- Kernel: selective gate/up BK3 for `M=10752,K=2048,N>64`.
- Context: four slots with at least 8192 effective tokens each.
- Dense remapping R1 remains STAGE and is not composed with production.
- All V8/V9 experimental selectors are disabled by default.

The production gate/up BK3 result is already closed and must not be revalidated:

- Profile B throughput: +1.1641%, 95% CI [+0.8093%, +1.3767%];
- 3D+1P retention: +1.5442%;
- resident ITL p95: -1.4472%;
- fresh-user TTFT: -1.6769%;
- service-EOS quality: 7/7 exact;
- no route leakage into resident decode.

## Contemporary mixed-workload baseline

The primary workload is three users decoding with resident 8K contexts while a
fourth submits an uncached 8K prefill.

Uninstrumented V9 baseline:

| Metric | Result |
|---|---:|
| Resident C3 throughput | 236.261 tok/s |
| Throughput during prefill | 38.542 tok/s |
| Decode retention | 16.313% |
| Baseline ITL p95 | 13.840 ms |
| ITL p95 during prefill | 88.471 ms |
| Fresh-user TTFT | 5137.25 ms |
| Mixed 128P+3D batch median | 78.257 ms |
| Mixed 128P+3D batch p95 | 86.479 ms |
| Decode-only C3 batch median | 11.572 ms |

Raw evidence is in
[`work/results/v9-mixed-timeline-production`](work/results/v9-mixed-timeline-production).

## Causal operation profile

The diagnostic Vulkan logger fences graphs and therefore cannot provide service
latency. It does prove the operation split. Every selected mixed batch contains
two graphs:

| Graph | Share of profiled GPU work |
|---|---:|
| Decode, N=4 | 16.51% |
| Prefill, N=127 | 83.49% |

Within the prefill graph:

| Family | Share within prefill |
|---|---:|
| Gate/up 10752x2048 | 35.34% |
| Down 2048x10752 | 26.64% |
| Flash Attention | 13.78% |
| Short-conv | 8.66% |
| 2048 projections | 6.42% |
| Other | 9.15% |

Gate/up plus down account for 61.98% of the prefill graph. Raw evidence and the
machine-readable summary are in
[`work/results/v9-mixed-operation-profile`](work/results/v9-mixed-operation-profile).

## Latest rejected experiments

### Gate/up Q8 pair prefetch

An exact opt-in pipeline prefetched both TN=2 Q8 columns into separate caches.
Correctness and route proof passed, but five ABBA pairs measured:

- production BK3: 412.085 us;
- candidate: 413.485 us;
- latency delta: +0.767%;
- bootstrap 95% CI: [-0.144%, +0.825%].

SPIR-V instructions increased 4.15%, including 18 additional access chains,
9 loads and 9 stores. Decision: **REJECT_MICRO**. Do not repeat this exact
array-cache implementation.

### Temporal EWMA scheduler

The default-off controller estimated mixed-batch milliseconds per prompt token
and selected a chunk between 64 and 128.

At a 65 ms target over three paired runs:

- retention improved 16.61%;
- ITL p95 improved 14.63%, from 87.085 to 74.678 ms;
- fresh-user TTFT regressed 47.97%, from 5150 to 7583 ms.

A 68 ms target reproduced the same poor frontier in its first pair. Chunks
64/65 take about 59.45 ms, while 66/67 jump to roughly 69–71 ms. Decision:
**REJECT production**. Fixed chunk128 remains production. Do not run another
generic chunk or EWMA-target sweep.

## V10 structural FP4 layout results

V10 implemented three reversible device representations for the exact gate/up
BK3 path. Every candidate preserved FP4 codes/scales, passed CPU-reference
correctness and proved its exact Vulkan route.

| Layout | Bytes/block | Local latency delta | 95% CI | Decision |
|---|---:|---:|---:|---|
| aligned padded | 20 | -1.227% | [-1.906%, -0.386%] | COMPOSABLE only |
| global code/scale planes | 17 | +43.150% | [+40.833%, +43.873%] | REJECT |
| four-block local groups | 17 | +3.851% | [+3.308%, +4.473%] | REJECT |

The padded layout proves aligned code loads can help: SPIR-V instructions fall
2.80%. It still predicts only ~0.36% mixed-batch leverage, expands selected
weights 17.65% and requires substantial runtime conversion. The compact planar
result proves scale locality is critical; grouping scales locally restores most
of the loss but remains slower. This layout family is closed.

V10 also composed the independent V8 exact gate/up and exact down candidates.
Three simultaneous-8K C4 pairs improved input/output throughput 0.549%, TTFT
p95 0.581% and E2E p95 0.549%. This is below the 0.75% promotion threshold,
and one of twelve output hashes diverged. It remains **ARCHIVE COMPOSABLE**, not
production. Raw evidence is under `work/results/v10-*`.

## Closed directions

Do not reopen without a materially new mechanism:

- two/four subgroup gate reductions;
- broad N-only selectors;
- global BK2/BK3 or another BK_STEP sweep;
- explicit compute-loop unroll directives;
- dual accumulators or arithmetic FP4 unpack;
- naive packed32 reconstruction;
- padded, global-planar or grouped-four gate/up layout variations;
- BM32/BN128 gate or BM32/BN64 down;
- V8 bounds/exact-shape candidates as standalone server promotions;
- Q8-group4 composition with down-exact;
- extra graph-local Q8 caches;
- 6144x2048 rebatching;
- chunk96, chunk256, unlimited prefill or idle-unlimited;
- EWMA ratio targets 65/68 with a 64-token minimum;
- FA occupancy bypass and Bc64;
- HIP synchronization removal, Q2, MTP and hybrid backends.

The full negative-result memory is
[`work/atrex_v6/taboo_mutations.json`](work/atrex_v6/taboo_mutations.json).

## Next experiment

Gate/down MMQ control-flow and layout work is now converged below product
leverage. The next step is measurement, not another shader mutation:

1. Split the V9 prefill `misc` bucket by exact operation and graph, beginning
   with RMS norm/rope, ADD, GLU, CPY/SSM-conv, CONCAT and MUL.
2. Reuse the existing raw V9 trace first; add instrumentation only for fields
   that are genuinely absent.
3. Record exclusive GPU time, calls, shape and selected pipeline.
4. Compute `profile_share * plausible_local_gain`; require at least 0.75%
   plausible mixed-batch leverage before implementing a candidate.
5. If no misc family qualifies, formulate an algorithmic Flash Attention
   hypothesis distinct from the rejected occupancy/Bc tile experiments.

Do not re-open prepacking by changing only group size. Do not re-open the
scheduler until a kernel materially lowers mixed-batch cost or a policy can
meet the existing TTFT guardrail.

## Reproducibility and current hashes

Nested ROCmFPX search-bank checkpoint: `8634463`.

V10 nested changes are archived as reconstructable mail patches under
[`patches/v10-fp4-layouts`](patches/v10-fp4-layouts), applied on top of
ROCmFPX `f5acc76`.

Checkpoint artifact SHA-256 values:

- `llama-server`: `92efcdf0018f4897165c7f4d405e5129b8145ca5f732efb712611d7c722165a0`;
- `libllama-server-impl.so`: `284fe0826a1f0fca439a705e4a795cc7265f0f7d49ac4b4770fec38096e1b190`;
- `libllama.so.0.3.0`: `3067a87a156465c1447256b9feffadd769057a8bc6f943fca99162cccfc03afc`;
- `rocmfpx-vulkan-plugin.so`: `40f3f48cfec7310bcfb017371d1232a7df7935f9e9fcadc2efcdda139832a208`;
- V10 search-bank `libggml-rocmfpx-vulkan.so`: `f89f3faaa85b22c5257b5194ea42aa3af9644afc93330bc2ab18f48fd26b4724`;
- FP4_FAST GGUF: `d56f602eb9bcad2cafbe2a52cef2fa14ba09e6290679a2aee164db22815f0933`.

At this checkpoint the repository harness passes 28/28 tests. With V10
experiment variables unset, exact CPU-reference validation selects
`matmul_rocmfp4_fast_q8_1_bk3_m` and passes.

## Key documents

- [`work/HANDOFF_V10.md`](work/HANDOFF_V10.md): current complete technical handoff.
- [`work/KERNEL_MICROBENCH_V10.md`](work/KERNEL_MICROBENCH_V10.md): layout results.
- [`work/ATREX_SEARCH_V10.md`](work/ATREX_SEARCH_V10.md): search and composition decisions.
- [`work/HANDOFF_V9.md`](work/HANDOFF_V9.md): V9 mixed-profile source.
- [`work/CONCURRENCY_PROFILE_V9.md`](work/CONCURRENCY_PROFILE_V9.md): service and scheduler results.
- [`work/KERNEL_MICROBENCH_V9.md`](work/KERNEL_MICROBENCH_V9.md): exact kernel result.
- [`work/PREFILL8K_PROFILE_V9.md`](work/PREFILL8K_PROFILE_V9.md): mixed prefill operation shares.
- [`work/ATREX_SEARCH_V9.md`](work/ATREX_SEARCH_V9.md): search decision and next family.
- [`work/NEXT_ACTION.md`](work/NEXT_ACTION.md): shortest operational continuation.
