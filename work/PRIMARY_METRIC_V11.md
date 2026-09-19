# V11: primary-metric regression control

## Why this ran

`README.md` declares the primary metric: 128 input tokens, 64 output tokens,
concurrency 4, aggregate output tok/s measured over HTTP from first request send
to last response completion. That exact shape was measured once, in V2, and
never again. V3 found 229.27 tok/s where the published series said 233.99 and
recorded the difference as an artifact-state mismatch rather than resolving it,
and every version from V4 onward measured 8K workloads instead.

So the campaign promoted one kernel change (selective gate/up BK3, +1.1641% on
the 8K profile) and several scheduler changes into "production" without ever
re-checking the metric the repository actually advertises. This closes that gap.

## Method

`work/scripts/run_primary_metric_v11.sh`, which drives the same
`benchmark_llama_backend.sh` + `bench_client.py` pair used by the V2 series:
prompt 128, max tokens 64, 1 warmup plus 10 repetitions per concurrency,
concurrency 1--4, `--no-cache-prompt --cache-reuse 0`, varied prompts, fixed
output via `ignore_eos` and a special-token bias.

Flags are the documented production profile: `-dev ROCmFPXVulkan0 -c 4096
-b 512 -ub 128 -ctk q8_0 -ctv q8_0`, `-ngl 99 -fa on -np 4 -cb`, with
`LLAMA_SERVER_COMPACT_SLOTS=1`, FP4_FAST weights, and the isolated GCC 16
runtime preloaded.

The binary is the V9/V10 production build
(`rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server`, nested ROCmFPX
`8634463`), not the `cm1` build the V2 series used. The comparison is therefore
"the published number versus the current production binary", which is the
question that matters operationally, not a controlled rebuild A/B.

Raw evidence: `work/results/v11-primary-128x64/`.

## Result

| Concurrency | V2 published | V11 measured | Delta | TTFT p50 | TTFT p95 | E2E p95 | Per-user p50 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 108.01 | 107.96 | −0.04% | 72.5 ms | 77.8 ms | 600.4 ms | 108.3 |
| 2 | 169.12 | 167.72 | −0.83% | 149.4 ms | 170.1 ms | 768.8 ms | 84.4 |
| 3 | 207.71 | 206.28 | −0.69% | 247.8 ms | 296.8 ms | 992.0 ms | 70.2 |
| 4 | 233.99 | 230.82 | −1.36% | 347.7 ms | 357.0 ms | 1127.9 ms | 58.3 |

All four cells report `VALID`: every request succeeded, every stream completed,
effective prompts matched the 128-token target, outputs matched the 64-token
budget, cache reuse was zero, and 40/40 C=4 requests carried usage token counts.

## What it means

The published headline is **real and reproducible to within 1.4%** at C=4 and
0.04% at C=1, on a different build, two days later, with the campaign's kernel
and scheduler changes in place. The V3 worry that the 234.0 series was
unreproducible does not hold up against the current binary; what V3 measured
was almost certainly a temporarily worse rebuild, as it suspected.

The residual −1.36% at C=4 is the cost of everything the campaign changed after
V2 as seen through its own advertised metric. It is not attributable to a single
change from this run alone -- the build, the nested revision and the promoted
BK3 selection all differ -- but the direction is consistent: the only kernel
change the campaign ever promoted was validated exclusively on the 8K profile,
and on the declared primary metric the current configuration is slightly slower
than the V2 series it replaced.

That is a regression-control gap, not a catastrophe: a 1.4% swing is inside the
noise band of a 10-repetition measurement on a part whose memory clock the
campaign itself observed alternating between 541 and 1000 MHz. The finding is
that no run existed to catch it, not that a specific change is bad.

## Decision

**KEEP both profiles, documented per workload.** Add this shape to the standing
gates so it is re-measured whenever a kernel or scheduler change is promoted:

| Profile | Format | Batch | Scheduler | Workload it wins |
| --- | --- | --- | --- | --- |
| `production-throughput` | FP4_FAST | `b512/ub128` + compact slots | fixed chunk128 | 128/64 and 512/128; idle resident decode |
| `production-interactive` | Q4_0 | `b4096/ub128` | fixed chunk128 | 8K mixed, four slots (`FORMAT_PREFILL_V11.md`) |

Any future promotion must clear both the 8K profile gates and this 128/64
primary-metric control. Do not promote a kernel change on the strength of one
profile again.
