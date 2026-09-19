# Kernel microbenchmark V9

## Gate/up BK3 Q8 pair prefetch

Exact problem: ROCmFPXVulkan0 FP4_FAST x Q8_1,
`M=10752,K=2048,N=128`, production selective BK3 as same-binary control.

Hypothesis: load both TN=2 Q8 columns into independent register caches before
the FP4 dot products, exposing load/compute instruction-level parallelism.
The candidate pipeline was
`matmul_rocmfp4_fast_q8_1_bk3_bpair_m`; route proof, CPU-reference correctness,
artifact checks and five logger-free ABBA pairs all passed.

| Arm | Median |
|---|---:|
| Production BK3 | 412.085 us |
| Q8 pair prefetch | 413.485 us |

Paired median delta: **+0.767% latency**. Bootstrap 95% interval:
**[-0.144%, +0.825%]**. This is a regression/noise result, not a win.

Static SPIR-V moved in the wrong direction:

- bytes +4.56%;
- instructions +4.15%;
- 18 additional access chains;
- 9 additional loads and 9 additional stores.

The compiler materialized the caches through extra private-memory-style SPIR-V
traffic rather than producing useful scheduling. VGPR, spills and occupancy
were not measured and are not inferred.

Decision: **REJECT_MICRO**. No server test. Do not repeat this exact
"prefetch both TN columns into arrays" mechanism. This does not prohibit a
genuinely different pipeline with static evidence that removes rather than adds
load/address instructions.

## Updated leverage

The contemporary mixed profile places gate/up at 29.50% and down at 22.24% of
the two profiled graphs. Therefore the archived V8 exact-shape gains have only
about 0.39% and 0.48% whole-pair ceilings respectively. Neither warrants a
standalone server promotion.

The next MMQ hypothesis must be structural. The strongest remaining candidate
family is reversible prepacking/layout for one hot tensor family, because the
address-control and simple scheduling families have converged below the
product-level gate.
