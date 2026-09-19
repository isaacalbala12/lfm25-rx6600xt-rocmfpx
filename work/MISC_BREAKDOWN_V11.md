# V11: prefill `misc` decomposition

## Why this ran

V10 closed the FP4 block-layout family (padded +17.65% bytes for 1.227% local,
global planar +43.150%, grouped-four +3.851%) and left one exact next action:
split the prefill graph's 9.15% `misc` bucket by operation and graph, using the
existing trace, and keep only what can clear the 0.75% mixed-batch gate.

This is that split. It runs no new profile: it re-reads
`work/results/v9-mixed-operation-profile/server.log`
(sha256 `ee5504a55ab05dab85d7eaf91aeb935b07d5f54473d7686be48019219336ccff`),
the same capture V9 published its family shares from. The new analyser is
`work/scripts/analyze_misc_breakdown.py`, covered by
`work/tests/test_analyze_misc_breakdown.py`.

## Method and its limits

The Vulkan perf logger emits one timestamp interval per ggml node plus its
fused ops, so a timing line is a fusion group whose description lists every op
it covers. Op attribution therefore comes in two flavours:

- **inclusive**: the whole group interval is charged to each op the group names;
- **exclusive**: only groups naming exactly one op are charged.

A fused group's interval cannot be split between its ops from this trace alone,
so exclusive time is a lower bound and inclusive time an upper bound. The
logger fences every graph; these shares are routing evidence, not a latency
prediction, and the instrumented wall time is not a service result.

Parse validation: every timing line matched the strict grammar, 1860 graph
headers balanced 1860 totals, and the summed per-graph interval differs from
each reported `Total time` by 3.93 µs across 63 batches. The family totals
reproduce the V9 numbers exactly (gate/up 29.50%, down 22.24%, FA 11.51%,
short-conv 7.23%, 2048 projections 5.36%, misc 7.64% of the decode+prefill
pair).

## Result

The prefill graph is 4,147,597 µs of the 4,967,892 µs pair. `misc` is
379,632 µs, i.e. **9.15% of the prefill graph and 7.64% of the mixed pair**.

Non-matmul, non-flash-attention groups in the prefill graph, largest first:

| Group | Total µs | Calls | µs/call | % prefill | % pair |
| --- | ---: | ---: | ---: | ---: | ---: |
| RMS_NORM_MUL_ROPE RMS_NORM(64,32,127,1) | 55,395 | 504 | 109.91 | 1.336 | 1.115 |
| GLU | 45,515 | 1,071 | 42.50 | 1.097 | 0.916 |
| RMS_NORM_MUL RMS_NORM(2048,127,1,1) | 44,666 | 3,591 | 12.44 | 1.077 | 0.899 |
| ADD | 44,487 | 3,654 | 12.17 | 1.073 | 0.895 |
| CONCAT | 41,780 | 1,323 | 31.58 | 1.007 | 0.841 |
| CPY, SSM_CONV | 37,274 | 1,386 | 26.89 | 0.899 | 0.750 |
| MUL | 32,898 | 2,709 | 12.14 | 0.793 | 0.662 |
| GLU, SCALE, GET_ROWS, GET_ROWS | 31,125 | 756 | 41.17 | 0.750 | 0.627 |
| MUL_MAT f32 m=64 n=4064 k=64 | 17,858 | 945 | 18.90 | 0.431 | 0.359 |
| MUL_MAT f32 m=64 n=1016 k=64, RMS_NORM_MUL_ROPE | 16,910 | 504 | 33.55 | 0.408 | 0.340 |
| SET_ROWS, SET_ROWS | 3,038 | 504 | 6.03 | 0.073 | 0.061 |
| CONCAT, CPY | 2,788 | 63 | 44.25 | 0.067 | 0.056 |
| MUL_MAT f32 m=64 n=1016 k=64 | 1,584 | 504 | 3.14 | 0.038 | 0.032 |

The 63 batches divide into 8 rope groups, 17 GLU groups, 57 norms, 58 adds, 21
concats, 22 conv copies and 43 muls per prefill graph, consistent with a
30-layer hybrid stack (22 conv/SSM layers, 8 attention layers).

## Leverage verdict

Applying the V10 rule, `share × plausible local gain` must exceed 0.75% of the
mixed batch. Exclusive shares of the pair:

| Op | Exclusive % pair | Local gain needed for 0.75% |
| --- | ---: | ---: |
| RMS_NORM_MUL_ROPE | 1.115 | 67% |
| GLU | 0.916 | 82% |
| RMS_NORM_MUL | 0.899 | 83% |
| ADD | 0.895 | 84% |
| CONCAT | 0.841 | 89% |
| CPY + SSM_CONV | 0.750 | 100% |
| MUL | 0.662 | 113% |

No single `misc` op clears the gate: each would have to become 67--113% faster,
and 100% means deleting it. That closes `misc` as a route to the 0.75% gate on
its own.

Two qualifications matter more than the table:

1. **RMS_NORM_MUL_ROPE is worth a second look despite the rule.** Its shape is
   64×32×127 = 260,096 elements in 109.91 µs, i.e. roughly 9.5 GB/s of traffic
   against a 256 GB/s part. 8 calls per prefill graph give it 4,064 parallel
   work items on a GPU with 4,096 lanes, so it is a near-single-wave,
   latency-bound dispatch rather than a bandwidth-bound one. A 3× local win,
   which is ordinary for that failure mode, is 0.74% of the pair — right at the
   gate. This is the only `misc` candidate with a defensible path to it.
2. **The whole elementwise/norm group is 5.33% of the pair**, so a fusion
   program that merged ADD, MUL, GLU, CONCAT and both norms into fewer
   dispatches could clear the gate collectively. That is a backend fusion
   change, not a shader-microbenchmark change, and the decode graph already
   shows fusion working there (`GLU, SCALE, GET_ROWS, GET_ROWS`,
   `CPY, SSM_CONV`, `SET_ROWS, SET_ROWS`) while the prefill graph still runs
   most of them as singletons.

## Product conclusion

Even deleting the entire `misc` bucket would recover 7.64% of the pair. The
interactivity target recorded in V8/V9 (resident ITL p95 ≤ 70 ms with TTFT
≤ 5.5 s) needs the pair to fall from 78.257 ms to about 70 ms, i.e. roughly
13% of the pair, with the prefill graph at 83.49% of it. `misc` cannot supply
that, and neither can any single remaining family at micro-optimisation scale.

That is why V11 also leaves the kernel/`misc` path and tests a
configuration-level lever instead: see `FORMAT_PREFILL_V11.md`.
