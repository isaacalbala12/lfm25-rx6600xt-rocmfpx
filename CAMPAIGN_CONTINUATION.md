# LFM2.5 RX 6600 XT performance campaign — continuation guide

This is the public entry point for continuing the engineering campaign on
`campaign-v3`. It summarizes the current production configuration, the evidence
that must be preserved, closed hypotheses, raw-result locations and the exact
next experiment. The detailed V9 audit remains in
[`work/HANDOFF_V9.md`](work/HANDOFF_V9.md).

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

## Closed directions

Do not reopen without a materially new mechanism:

- two/four subgroup gate reductions;
- broad N-only selectors;
- global BK2/BK3 or another BK_STEP sweep;
- explicit compute-loop unroll directives;
- dual accumulators or arithmetic FP4 unpack;
- naive packed32 reconstruction;
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

The next justified high-leverage family is a reversible, exact prepacking of one
real gate/up tensor. The hypothesis is that arranging unchanged FP4 codes and
scales in wave32 consumption order can remove address chains and improve
coalescing beyond what control-flow specialization achieved.

Required sequence:

1. Trace the current FP4_FAST block layout and exact lane-to-weight mapping.
2. Design one reversible `[K-block][M-tile]` or equivalent layout for a single
   hot matrix; do not convert or duplicate the complete model.
3. Account for one-time packing cost, extra VRAM and production headroom.
4. Add an exact opt-in pipeline and fallback while preserving identical codes,
   scales and mathematical values.
5. Extend the exact-plugin microbenchmark to consume the packed real matrix.
6. Measure N=127, N=128 and one real tail with hot and rotating buffers.
7. Require approximately 2.55% local improvement on gate/up before a server
   test; at the current profile share this corresponds to about 0.75% maximum
   mixed-workload leverage.
8. If it passes, run simultaneous 8K C4, then 3D+1P, resident C4 and quality.

If prepacking fails, close MMQ temporarily and split the 9.15% prefill `other`
bucket by exact operation. Do not fall back to random shader or scheduler tuning.

## Reproducibility and current hashes

Nested ROCmFPX source checkpoint: `f5acc76`.

The nested changes are archived in
[`patches/v9-mixed-profile-bpair-ewma.patch`](patches/v9-mixed-profile-bpair-ewma.patch).

Checkpoint artifact SHA-256 values:

- `llama-server`: `92efcdf0018f4897165c7f4d405e5129b8145ca5f732efb712611d7c722165a0`;
- `libllama-server-impl.so`: `284fe0826a1f0fca439a705e4a795cc7265f0f7d49ac4b4770fec38096e1b190`;
- `libllama.so.0.3.0`: `3067a87a156465c1447256b9feffadd769057a8bc6f943fca99162cccfc03afc`;
- `rocmfpx-vulkan-plugin.so`: `40f3f48cfec7310bcfb017371d1232a7df7935f9e9fcadc2efcdda139832a208`;
- `libggml-rocmfpx-vulkan.so`: `a35c48d9b0790e94e7089e99a22efe4b5290b36a4e041a46ad1de5f5d224c624`;
- FP4_FAST GGUF: `d56f602eb9bcad2cafbe2a52cef2fa14ba09e6290679a2aee164db22815f0933`.

At this checkpoint the repository harness passes 28/28 tests. With V9
experiment variables unset, exact CPU-reference validation selects
`matmul_rocmfp4_fast_q8_1_bk3_m` and passes.

## Key documents

- [`work/HANDOFF_V9.md`](work/HANDOFF_V9.md): complete technical handoff.
- [`work/CONCURRENCY_PROFILE_V9.md`](work/CONCURRENCY_PROFILE_V9.md): service and scheduler results.
- [`work/KERNEL_MICROBENCH_V9.md`](work/KERNEL_MICROBENCH_V9.md): exact kernel result.
- [`work/PREFILL8K_PROFILE_V9.md`](work/PREFILL8K_PROFILE_V9.md): mixed prefill operation shares.
- [`work/ATREX_SEARCH_V9.md`](work/ATREX_SEARCH_V9.md): search decision and next family.
- [`work/NEXT_ACTION.md`](work/NEXT_ACTION.md): shortest operational continuation.
