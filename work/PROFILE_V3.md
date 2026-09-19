# Profile V3: ROCmFPXVulkan0 on RX 6600 XT / gfx1032

## Scope and controls

Host verification: Ryzen 5 1500X, four physical cores/eight threads; Navi23 device `0x73ff`, `gfx1032`. Model: `LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf`; Vulkan plugin; KV Q8; `-b 4096 -ub 128`; no prompt cache. No clocks, power profile, driver or system library was changed.

Normal and profiled runs are kept separate. Selection/performance logging materially perturbs throughput and its timestamp totals are not added across overlapping submissions as if they were wall latency.

## Contemporary service baseline

The exact coherent-model control in `work/results/quant-screen-v2-rocmfpx-plugin-fp4-fast-coherent-compact` is approximately 103.7 tok/s at C1 and 228.0 tok/s at C4. A fresh instrumentation-disabled rebuild produced 102.8–104.5 tok/s at C1 and 229.27–229.29 tok/s in the two stable C4 repetitions (`work/results/v3-normal-128x64-plugin`). The published 108/169/207.7/234 series used a different artifact state and remains a candidate comparison, not an interchangeable causal baseline.

## GPU profile

For 2048-token prefill with ubatch 128, a representative warm profiled block totals 56.9–60.3 ms of serialized Vulkan timestamps. FP4_FAST matmuls dominate it:

- gate/up `10752x128x2048`: about 24.2–25.6 ms across 58 calls;
- down `2048x128x10752`: about 16.5–18.0 ms across 29 calls;
- short-conv input `6144x128x2048`: about 5.2–5.5 ms across 22 calls;
- short-conv output `2048x128x2048`: about 3.6–3.9 ms across 38 calls.

The first profiled block is colder and reaches 75.8 ms. The traced HTTP result (TTFT 1.143 s) is not a normal service measurement. Source: `work/results/v3-shape-2048-plugin/server.log`.

Decode selects `mul_mat_vec_rocmfp4_fast_q8_1_f32` after `quantize_q8_1_x4`; N=1 and N=4 dominate the separated shapes, with N=2 and N=6 also observed. This makes the small-N FP4_FAST GEMV family the next kernel candidate, but only after a microbenchmark can invoke the server's exact selector and rotate real matrices.

## Sparse slots: demonstrated cause and candidate

Original same-server measurements:

| Active logical IDs | Aggregate tok/s |
| --- | ---: |
| C3 `{0,1,2}` | 199.77–201.76 |
| C3 `{0,1,3}` | 131.18–131.91 |
| C3 `{0,2,3}` | 131.33–132.25 |
| C2 `{0,1}` | 163.79–163.95 |
| C2 `{0,3}` | 97.18–98.79 |

Raw data: `work/results/v3-sparse-slot-matrix`.

The original trace proves that a sparse logical set is split into two recurrent microbatches. A first attempt that merely relaxed the “consecutive ID” condition crashed an attention-mask assertion; a second length-gated relaxation did the same. Both were reverted and are REJECT.

The current candidate uses dense internal IDs and physical-ID-ordered batch assembly. The trace for logical `{0,1,3}` shows physical `[0,1,2]` and one recurrent microbatch (`work/results/v3-dense-seq-order-trace`). Its traced service throughput rose from about 128.3 tok/s before ordered assembly to 168.1 tok/s after it; these are profiler-perturbed diagnostics, not promotion numbers.

Uninstrumented/low-instrumentation candidate repetitions reached 176.98–193.93 tok/s for C3, but some later repetitions dropped to 91.7–98.5 tok/s while the batch remained physically dense. Resource samples during the slow interval show memory-clock alternation between 541 and 1000 MHz. This is correlation, not a closed causal claim, and prevents a clean production promotion from this short series.

The normal-API dynamic reproducer used lengths 96/24/64/40, 40 ms stagger, no forced `id_slot`, then disconnected a fifth stream after eight chunks and issued a follow-up request. All four varied requests and the 32-token follow-up completed correctly. Evidence: `work/results/v3-dynamic-dense.json` and `work/results/v3-dynamic-dense-server.log`.

## Decision

**STAGE**, not KEEP. The runtime change fixes the proven recurrent split in static and dynamic traces and survives completion, cancellation and reuse, but the candidate lacks a stable paired C4 performance confirmation and formal logits/quality evaluation. It is opt-in through `LLAMA_SERVER_COMPACT_SLOTS=1`; speculative decoding is explicitly excluded and prompt-cache ownership is cleared when physical IDs move.

Next experiment: paired A/B/B/A C4 dynamic runs with higher-frequency clock sampling, then operation-level logits comparison. If stable, profile N=1/2/4 FP4_FAST GEMV with hot and rotating matrices before changing a shader.

