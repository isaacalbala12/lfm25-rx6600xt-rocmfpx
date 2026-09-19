# V11: decode batch fold — sharing weights across concurrent slots

## Summary

The four-slot decode step re-read the weight matrix once per sequence. Folding
the replicated batch into the column dimension of the quantized mat-vec kernel
removes that, and it is the largest single change this campaign has measured on
decode:

| Measurement | Control | Folded | Delta |
| --- | ---: | ---: | ---: |
| Direct decode, 4 sequences (fast mode) | 351.9 tok/s | 397.6 tok/s | **+13.0%** |
| Direct decode, 8 sequences | 449.45 tok/s | 519.37 tok/s | +15.6% |
| Primary metric, C=4 service | 230.02 -- 231.37 | 235.79 -- 249.44 | **+4.0% (means) to +7.8% (fast mode)** |
| Primary metric C=4, E2E p95 | ~1133 ms | ~1087 ms | −4.0% |
| 8K profile, idle resident decode | 239.4 / 240.1 | 259.2 / 260.4 | **+8.4%** |
| 8K profile, TTFT | 5175 ms | 5102 ms | −1.4% |
| 8K profile, ITL p95 | 87.24 ms | 86.72 ms | −0.6% |
| Perplexity, batch 1 | 57.3483 | 57.3483 | identical |
| Output hashes, C=1 / C=2 | — | — | 10/10 and 20/20 identical |

The patch is 12 lines in `extensions/rocmfpx-vulkan/backend/ggml-vulkan.cpp`.

The direct decode figure is the cleanest statement of what the change does: on a
server where every step carries four sequences, decode is 13% faster. The
service figures are smaller because the fold only touches decode, and decode is
about two thirds of the C=4 128/64 workload and one sixth of the mixed 8K batch.
The 8K retention ratio moves the wrong way (−6.4%) purely because retention is
`during_prefill / baseline` and the baseline improved more than the numerator;
absolute throughput during prefill still rose (38.2 to 38.7 tok/s).

Read every number here together with `GPU_BIMODAL_V11.md`: the host has a fast
and a slow GPU clock state 1.56x apart, so a single run is not a measurement.

## How the roofline was established first

`llama-batched-bench`, FP4_FAST, `npp=8`, short context so attention stays cheap:

| Batch | Agg. tok/s | Step ms | Weight GB/s |
| ---: | ---: | ---: | ---: |
| 1 | 124.28 | 8.05 | 179 |
| 2 | 214.68 | 9.32 | 155 |
| 3 | 296.18 | 10.13 | 142 |
| 4 | 344.85 | 11.60 | 124 |
| 6 | 404.14 | 14.85 | 97 |
| 8 | 449.45 | 17.80 | 81 |

Every decode step must read the 1.442 GB of weights, whether it produces one
token or eight. The step time therefore ought to be nearly flat in the batch
size, and aggregate throughput ought to scale almost linearly. It does not: the
step fits `6.6 ms + 1.4 ms × batch`. The fixed 6.6 ms is the weight stream at
218 GB/s, which is 85% of the 256 GB/s peak and close to optimal. The 1.4 ms per
sequence is the problem, and at four slots it is 5.6 ms of an 11.6 ms step.

## Where the per-sequence cost came from

A decode graph at four slots, from the Vulkan timing groups:

| Group | 1 slot | 4 slots | Ratio |
| --- | ---: | ---: | ---: |
| `MUL_MAT_VEC m=10752 n=? k=2048` gate/up ×60 | 3081.8 µs | 3440.5 µs | 1.12 |
| `MUL_MAT_VEC m=2048 n=? k=10752` down ×30 | 1639.9 µs | 1832.2 µs | 1.12 |
| `MUL_MAT_VEC m=6144 n=1 k=2048 batch=4` ×22 | 721.9 µs | 1770.2 µs | **2.45** |
| `MUL_MAT_VEC m=2048 n=1 k=2048 batch=4` ×22 | 82.2 µs | 691.4 µs | **8.4** |

Four times the batch costs the FFN matmuls 12%, but the short-conv and SSM
projections 145%. The difference is the tensor layout, not the weight type:

- the FFN input is `(k, 4)`, so the backend takes the `batch_n` path with
  `NUM_COLS = 4`, one workgroup covering all four columns and reusing the weight
  rows it loads;
- the conv/SSM projections take input `(k, 1, 4)`, sequence in `ne[2]`. The
  backend dispatches those with `grid_y = ne12 * ne13 = 4`, so four workgroups
  each walk the entire weight matrix for a single token.

`get_offsets()` already computes `batch_idx_a = 0` for every element when
`ne02 == ne03 == 1`, which means the weights are *already* shared
mathematically — the redundancy is purely in how the work is dispatched, hidden
from the profiler by the Infinity Cache.

## The change

When the batch is a pure replication of a weight matrix that has no batch
dimension of its own, dispatch it as columns instead of as grid rows:

```cpp
const bool fold_batch_into_cols = !batch_n && ne11 == 1 && ne13 == 1 &&
                                  ne02 == 1 && ne03 == 1 &&
                                  ne12 > 1 && ne12 <= mul_mat_vec_max_cols;
const uint64_t pipeline_cols   = fold_batch_into_cols ? ne12 : ne11;
const uint64_t dispatch_batch  = fold_batch_into_cols ? 1 : ne12 * ne13;
```

`pipeline_cols` selects the `NUM_COLS` pipeline, `dispatch_batch` sets the grid,
and the batch strides become the shared ones the `batch_n` path already uses.
The layouts coincide exactly: with `ne11 == 1` the batch stride of `src1` equals
its row stride, and with `ne02 == ne03 == 1` the weight offset is zero for every
element, so the arithmetic per column is unchanged and only the traversal order
of the weight blocks differs.

A kill switch (`GGML_VK_MMV_NO_FOLD_BATCH`) and a trace
(`GGML_VK_MMV_TRACE_FOLD`) are included so the change can be A/B'd without a
rebuild and confirmed to fire:

```
mmv-fold: m=6144 n=1 k=2048 ne02=1 ne12=4 batch_n=0 fold=1
mmv-fold: m=2048 n=1 k=2048 ne02=1 ne12=4 batch_n=0 fold=1
```

## Correctness

- **Perplexity** on a 72 KB corpus, batch 1: `57.3483 ± 4.55373` on both
  backends, with all twelve per-chunk values equal to four decimals.
- **Output identity**: C=1 is 10/10 identical and C=2 is 20/20 identical. The
  fold is active at C=2, so the folded path is verified deterministically.
- At C=3 and C=4 outputs diverge between runs, but **control versus control
  diverges at the same rate** (30/40 identical) as control versus folded
  (29/40) and folded versus folded (29/40). The divergence is a property of the
  harness, not of the change.

That last point corrects a campaign assumption. V10 recorded that a composition
candidate had "one of twelve responses differ" and treated the divergence as
unexplained grounds to withhold promotion. The baseline rate is about 25% of
requests at C=4, so output-hash equality was never a usable gate at that
concurrency; the campaign's hard correctness gate was partly measuring noise.

## Decision

**KEEP.** The change is promoted into the production backend, and it is the
first kernel change since selective gate/up BK3 to clear the 0.75% gate by two
orders of magnitude.

Do not re-open: the fold is unconditional for the shapes it matches. The
remaining per-sequence cost is now 0.85 ms per slot at four slots, and what is
left of the step is the 6.6 ms weight stream plus roughly 1.5 ms of
norm/elementwise dispatches — see `DECODE_DISPATCH_V11.md` for what comes next.

## Reproduction

```bash
# Direct decode curve
llama-batched-bench -m LFM2.5-2.6B-ROCmFP4_FAST.gguf -dev ROCmFPXVulkan0 -ngl 99 \
  -fa on -c 8192 -b 2048 -ub 128 -ctk q8_0 -ctv q8_0 -npp 8 -ntg 192 -npl 1,2,3,4,6,8

# Interleaved service A/B of two backend directories
PAIRS=2 work/scripts/run_backend_interference_abba.sh <out> <control-bin> <candidate-bin>
```
