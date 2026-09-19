# V11: format choice at the prefill-dominated shape

## Summary

Plain `Q4_0` beats `ROCmFP4_FAST` on the mixed 8K product workload that V4--V10
optimised for. Three paired service runs give **new-user TTFT −6.98%**,
**resident ITL p95 −7.16%** and **decode retention +11.61%**, paid for with
**−3.96% resident decode throughput**. Every interval excludes zero.

The format had been screened once, at 128/64 and 512/128, where decode
dominates and FP4_FAST wins. Nobody re-screened it after the campaign changed
its objective to an 8K prefill-dominated workload.

## Why this was worth re-opening

The campaign's format screen was run at shapes where output tokens dominate:
128/64 has 128 input tokens against 64 output tokens, so decode is roughly 89%
of the work and the decode ranking decides the winner. V9 then established that
in the 8K mixed workload the **prefill graph is 83.49% of the mixed pair**, the
opposite weighting. On a shape where prefill dominates, the format ranking can
invert, because the prefill and decode kernels do not share a bottleneck.

V2 already recorded the crossover at service level without acting on it: its
workload table shows upstream Q4_0 winning 2048/256 (101.66 against 99.98 tok/s)
and the exploratory 7680/512 (92.40 against 88.58), while FP4_FAST won the short
shapes. `RESULTS.md` lists the ROCmFPX Q5--Q8 family as "inventoried, without
speed qualification".

## Step 1: direct screen

`work/scripts/screen_format_prefill.sh`, device `ROCmFPXVulkan0`, three
repetitions, same build for every format. Raw output in
`work/results/format-screen-v11-prefill/`.

| Model | Bytes | bpw | pp128 | pp512 | pp2048 | tg128 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ROCmFP4_FAST | 1.34 GiB | 4.25 | 2271.27 | 2459.04 | 2389.32 | **132.74** |
| Q8_0 | 2.67 GiB | 8.50 | 1907.07 | 2205.66 | 2174.76 | 76.03 |
| Q4_0 | 1.48 GiB | 4.70 | **2621.13** | **2738.75** | **2668.87** | 123.87 |

Two results, one of which refutes the hypothesis that motivated the screen:

- **The no-unpack hypothesis is wrong.** Q8_0 removes FP4 code/scale
  reconstruction from the inner loop, doubles the weight bytes, and comes out
  16.0% *slower* at pp128 and 42.7% slower at tg128. The FP4 path is not
  unpack-bound in a way more bits can buy back; extra bytes cost more than the
  unpack arithmetic they remove.
- **The format ranking inverts with shape.** Q4_0 is 15.4% faster than
  FP4_FAST at pp128 and 11.7% faster at pp2048, while FP4_FAST keeps a 7.2%
  decode advantage. That is exactly the trade V9's 83.49% prefill share says
  should matter.

## Step 2: paired service A/B at the product workload

`work/scripts/run_format_interference_abba.sh`, three alternating pairs, both
arms on the same binary, same flags, same KV type, differing only in the weight
file. Raw evidence in `work/results/v11-format-abba-8k-mixed/`.

| Metric | FP4_FAST (control) | Q4_0 (candidate) | Paired delta | 95% CI |
| --- | ---: | ---: | ---: | --- |
| New-user TTFT | 5197.42 ms | 4847.29 ms | **−6.982%** | [−7.056, −6.410] |
| Resident ITL p95 during prefill | 88.53 ms | 82.97 ms | **−7.164%** | [−8.548, −3.799] |
| Decode retention | 15.96% | 17.82% | **+11.612%** | [+11.320, +12.138] |
| Resident aggregate (no prefill) | 238.94 tok/s | 229.48 tok/s | −3.96% | — |

Per pair, the direction never changed:

| Pair | Order | Retention delta | ITL p95 delta | TTFT delta |
| ---: | --- | ---: | ---: | ---: |
| 0 | control → candidate | +11.32% | −3.80% | −6.41% |
| 1 | candidate → control | +11.61% | −7.16% | −6.98% |
| 2 | control → candidate | +12.14% | −8.55% | −7.06% |

All six arms report `VALID`; no arm was discarded.

### Control validation

The control arm reproduces the V9 published production numbers, which is what
makes the deltas trustworthy:

| Metric | V9 published | V11 control |
| --- | ---: | ---: |
| Resident aggregate, C3 | 236.26 tok/s | 238.94 tok/s |
| ITL p95 during prefill | 88.47 ms | 88.53 ms |
| Decode retention | 16.31% | 15.96% |
| New-user TTFT | 5137.25 ms | 5197.42 ms |

## What this does and does not achieve

It does **not** reach the interactivity target. TTFT now clears its guardrail
comfortably (4847 ms against 5500 ms), but resident ITL p95 is 82.97 ms against
the ≤70 ms goal, so the target is still missed by 18.5%. One 128-token chunk
plus one decode step still costs more than 70 ms on this GPU.

It does move the Pareto front. Against the FP4_FAST incumbent, Q4_0 is better on
TTFT, better on resident ITL, better on retention, and worse only on idle
resident throughput. It is also a *higher* bit-width format (4.70 bpw against
4.25), and Q4_0 is the campaign's standard baseline whose quality smoke tests
pass, whereas FP4_FAST has never had a formal quality evaluation. So the switch
trades idle decode throughput for interactive latency without introducing a new
quality exposure.

Both arms used the `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` fixed chunk. Nothing
in this experiment changes the scheduler, the runtime, the gate/up BK3
selection, drivers, clocks or power settings.

## Decision

**KEEP as a candidate profile, split by objective.** The two formats win
different workloads and there is still no universal winner:

- `production-interactive`: Q4_0, KV q8, `b4096/ub128`, fixed chunk128 — best
  TTFT, best ITL, best retention at 8K with four slots;
- `production-throughput`: FP4_FAST, KV q8, `b512/ub128`, compact slots — best
  idle resident throughput and the winner at the short 128/64 shape.

The 128/64 primary metric still favours FP4_FAST end to end (see
`PRIMARY_METRIC_V11.md`), so this is a workload-dependent split, not a
replacement of the incumbent everywhere.

## Next exact actions

1. Re-run the 2048/256 and 7680/512 service shapes with both formats; V2's
   table suggests Q4_0 already won there and the mixed-8K result should be
   consistent with it.
2. Turn the format screen into a small matrix across every shape already in
   `BASELINES.json`, so the format decision follows the shape decision instead
   of being made once at one shape.
3. Do not re-run the FP4 block-layout family: V10 closed it, and this result
   explains why it could never pay. The remaining FP4 headroom is not in the
   block layout.
