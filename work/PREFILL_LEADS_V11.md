# V11: prefill working notes — where the remaining time is and one refuted lead

## Prefill is compute-bound and the per-family efficiency is not uniform

The mixed-batch prefill graph from the V9 trace, 63 batches, recomputed from
`work/results/v11-misc-breakdown/misc-summary.json`:

| Shape | Total µs | Calls | TFLOPS | Share of prefill |
| --- | ---: | ---: | ---: | ---: |
| gate/up `m=10752 n=127 k=2048` (two per group) | 1,465,622 | 1,827 | **13.9** | 35.34% |
| down `m=2048 n=127 k=10752` | 1,105,045 | 1,827 | **9.25** | 26.64% |
| projection `m=2048 n=127 k=2048` | 185,981 | 1,827 | 6.6 | 4.48% |
| short-conv `m=6144 n=127 k=2048` (fused with CPY) | 183,954 | 756 | 6.3 | 4.44% |
| short-conv `m=6144 n=127 k=2048` | 175,235 | 630 | 7.2 | 4.22% |

`gate/up` and `down` perform the same number of multiply-accumulates per matrix
and read the same number of weight bytes, but `down` runs **1.5x slower**:
9.25 TFLOPS against 13.9. Since together they are 62% of the prefill graph,
closing that gap would be worth roughly 9% of prefill.

This is the same shape of finding as the decode batch fold: an asymmetry
between two operations that ought to cost the same. It is the top prefill lead.

## The obvious explanation is wrong

`down` has only `2048/64 = 32` row tiles against `10752/64 = 168` for gate/up,
so it looked parallelism-starved. The backend's split-k heuristic confirmed the
symptom: every prefill shape in this model gets `split_k = 1`.

```
split-k: m=10752 n=128 k=2048 tiles=336 cores=32 split_k=1
split-k: m=2048  n=128 k=10752 tiles=64  cores=32 split_k=1
split-k: m=6144  n=128 k=2048 tiles=192  cores=32 split_k=1
split-k: m=2048  n=128 k=2048 tiles=64   cores=32 split_k=1
```

An opt-in override that raises `split_k` until the tile grid reaches a target
number of workgroups per core was built and swept. It added a
`GGML_VK_SPLIT_K_WG_PER_CU` environment variable and a `GGML_VK_SPLIT_K_TRACE`
trace to `ggml_vk_guess_split_k`, defaulting to the existing behaviour:

| Workgroups per core target | pp128 | pp512 |
| ---: | ---: | ---: |
| off (current) | 2333.65 | 2491.73 |
| 4 | 2306.77 | 2490.94 |
| 8 | **723.23** | 2483.07 |

Best of three runs each. Four workgroups per core is neutral to slightly worse;
eight collapses pp128 by 69% while leaving pp512 untouched, which is consistent
with the split-k reduction overhead dominating at small n.

**Decision: REJECT.** `down`'s deficit is not a split-k or workgroup-count
problem, and the override was reverted from the tree. The remaining candidates
for the 1.5x gap are the row-length difference (5712 bytes per weight row for
`down` against 1088 for gate/up, so different L2/L1 residency) and the tile
geometry suited to `m=2048`. Both need shader work, not a dispatch change.

## What this leaves

For prefill, the measured levers in order of size:

1. the `down` versus gate/up efficiency gap, ~9% of prefill, unexplored
   mechanism;
2. the format choice, +13% at pp128 for Q4_0 over FP4_FAST, already validated
   and recorded in `FORMAT_PREFILL_V11.md`;
3. the elementwise and norm bucket, which `MISC_BREAKDOWN_V11.md` closes as an
   individual-op route.

For decode, after the batch fold:

| Component | µs | Share | Effective rate |
| --- | ---: | ---: | ---: |
| matmuls | 7,480 | 81.7% | 193 GB/s of 256 peak |
| everything else (357 dispatches) | 1,675 | 18.3% | overhead-bound |

The non-matmul figure is dispatch overhead, not bandwidth: `RMS_NORM_MUL` on a
`(2048, 4)` tensor costs 4.63 µs per call at batch 1 and 5.08 µs at batch 4, so
four times the data costs 10% more time. Fusing the norm/elementwise chain is
the next structural decode target.
