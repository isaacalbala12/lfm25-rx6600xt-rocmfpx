# V11: corrections from external review, and two experiments it prompted

An outside reviewer audited the brief in `EXTERNAL_REVIEW_REQUEST.md` against the
published artifacts. It found three arithmetic errors, one methodological flaw
and one confound. All five are real. This note records them, plus the two
experiments the review made obvious, both of which were run.

## Corrections to our own published numbers

### 1. MACs were compared against operations

`V_DOT4_I32_I8` performs four multiply-accumulates per lane per instruction, so
one instruction is four MACs but eight operations. Our published claim —
"7,2 TMAC/s, which is 74% of 21 TOPS or 18% of 42 TOPS" — mixed the two units
and was wrong by a factor of two.

The correct statement: **7,2 TMAC/s is 14,4 TOPS**, which is **34% of a 42,4 TOPS
full-rate ceiling** (64 SIMD × 32 lanes × 8 operations × 2,589 GHz) or **68% of a
21,2 TOPS half-rate ceiling**. Which of the two ceilings applies is still unknown
and is exactly what the reviewer's microbenchmark proposal would settle. The
consequence matters: if the ceiling is 42,4 TOPS, prefill has 3x of headroom and
we have been measuring at a third of the machine; if it is 21,2, we are at 68%
and the headroom is small.

### 2. Two different scopes were given the same denominator

"Decode is at 65% of the practical bandwidth wall" and "the step is 71%" are
both defensible but they are not the same measurement:

- **Service scope:** 401,3 tok/s at C=4 is 4 tokens per 9,97 ms, so
  1,442 GB / 9,97 ms = **144,6 GB/s = 65%** of 222 GB/s. This includes HTTP,
  scheduling and queueing.
- **Graph scope:** the decode graph alone is 9,15 ms, so
  1,442 GB / 9,15 ms = **157,6 GB/s = 71%** of 222 GB/s. GPU work only.

They should never share a denominator, and the document now says which is which.

### 3. The Flash Attention figure was derived from the wrong graph

We published 3,9 TMAC/s for the prefill attention. The reviewer could not
reproduce it and was right not to. Re-reading the V9 capture:

| Graph | FA shape | Queries | Context |
| --- | --- | ---: | --- |
| decode (index 0) | `dst(64,32,1,4), k(64,8448,8,4)` | 1 | 8448 |
| prefill (index 1) | `dst(64,32,127,1), k(64,7936,8,1)` | 127 | 256--8192 |

**The 8448-context shape is the resident decode graph.** The prefill chunk's
attention has 127 queries against a context that varies from 256 to 8192 across
the 64 entries, because each chunk sees a longer prefix than the last. We
attributed the decode context to the prefill.

**The first correction of this figure was also wrong.** See
`REVIEW_CORRECTIONS_2_V11.md`: summing the per-chunk MACs across the whole trace
double-counts by a factor of eight. The correct rate is **1,91 TMAC/s**, so
attention runs at 27% of the matmul rate and question 5 stands. Comparing it
against the int8 ceiling is still invalid, as the reviewer notes, because it
mixes quantized QK with fp32 PV and softmax.

### 4. The "gap narrows as n grows" curve mixes tile geometries

Our three data points are not the same kernel. At n=4 it is the mat-vec path, at
n=16 the pipeline selector picks the **small** tile (`n <= 32`), and at n=127 the
**large** tile. So the curve conflates n with tile size. The n=127 comparison
itself is same-geometry for both shapes, which is what the anomaly rests on, but
the trend across n does not support the interpretation we gave it.

### 5. The `down` versus `gate/up` comparison had a live confound

`vk_rocmfp4_fast_mmq_bk3_gateup` defaults to **true**, so in our headline
comparison gate/up ran `BK_STEP=3` while down ran `BK_STEP=4`. The reviewer
spotted it from the V7 record. It is a runtime switch
(`GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP=0`), not a build flag, so the control
costs one environment variable rather than a rebuild.

## Experiment 1: the BK3 confound does not explain the gap

Prefill graph at n=128, same binary, only that variable changed:

| Setting | gate/up | down | Ratio |
| --- | ---: | ---: | ---: |
| BK3 for gate/up (production) | 23.074 µs → 14,66 TFLOPS | 16.667 µs → 10,15 TFLOPS | **1,44** |
| BK4 for both | 24.557 µs → 13,77 TFLOPS | 16.613 µs → 10,18 TFLOPS | **1,35** |

`down` is **unchanged** (16.667 against 16.613 µs, 0,3%), because it was always
running BK4. `gate/up` gains 6% from BK3, which reproduces the V7 result. So the
confound shifts the ratio from 1,44 to 1,35 but **does not explain the gap**, and
the production comparison is now stated with its control.

## Experiment 2: the occupancy prediction is not confirmed

The reviewer's mechanism was waves-per-SIMD: `down` at n=127 offers 64
workgroups against 336 for gate/up, and with roughly 160 VGPRs only about four
of the six resident waves per SIMD can be filled. The discriminating test is
scaling at fixed geometry, and the prediction was that `down` should absorb 50%
more MACs in clearly less than 50% more time while `gate/up`, already saturated,
should track the added work.

BK4 fixed, `-ub 256 -npl 1`, one run per point:

| n | gate/up | down | Ratio |
| ---: | ---: | ---: | ---: |
| 128 | 67.051 µs → 4,88 TFLOPS | 45.840 µs → 3,57 TFLOPS | 1,37 |
| 192 | 93.999 µs → 5,22 TFLOPS | 59.712 µs → 4,11 TFLOPS | 1,27 |
| 256 | 125.160 µs → 5,22 TFLOPS | 87.386 µs → 3,74 TFLOPS | 1,40 |

| Interval | gate/up | down | Prediction |
| --- | ---: | ---: | --- |
| 128 → 192 (+50% MACs) | +40,2% | **+30,3%** | down well under 50%: **consistent** |
| 128 → 256 (+100% MACs) | +86,7% | **+90,6%** | down should stay ahead: **contradicted** |

The first interval behaves as predicted and the second does not, and the ratio
is not monotonic. **The occupancy explanation is not confirmed.** It is not
refuted either: these are single runs on a host whose clock state costs 40% when
it drifts, and the 128→192 and 128→256 intervals disagree with each other rather
than with the hypothesis. A properly powered version needs interleaved repeats
and the clock guard, which is the next thing to run.

## What this leaves

The anomaly is still real at n=127 (1,35--1,44 depending on BK3), still not
split-k, still not tile selection, still absent from the decode path, and now
also not explained by the BK3 confound. Its cause remains unknown, and the
occupancy mechanism is the best candidate without being demonstrated.

Three of our published figures were wrong and are corrected above. Two of them
(the MAC/operation factor and the attention scope) came from the same habit of
carrying a number forward without re-deriving its units, which is worth watching
for.
