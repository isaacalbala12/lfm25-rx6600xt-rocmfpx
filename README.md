# LFM2.5-2.6B on RX 6600 XT / gfx1032

Reproducible performance-engineering campaign for LFM2.5-2.6B on an AMD
Radeon RX 6600 XT (RDNA2/gfx1032), optimized for one to four concurrent
requests.

Two workloads are tracked, because they have different winners:

- the **declared primary metric**: 128 input tokens, 64 output tokens,
  concurrency 4, aggregate output tok/s measured over HTTP from first request
  send to final response completion (`work/PRIMARY_METRIC_V11.md`);
- the **interactive 8K profile**: four slots of at least 8192 tokens each, three
  resident decoders plus one arriving prefill, where the metrics are new-user
  TTFT, resident inter-token latency and decode retention
  (`work/FORMAT_PREFILL_V11.md`).

Every number below is a service measurement over real HTTP with no
instrumentation, unless the referenced document says otherwise.

## Current result

### Primary metric, 128/64, re-measured 2026-09-19

Profile `production-throughput`: ROCmFP4_FAST, KV `q8_0/q8_0`, `b512/ub128`,
fixed `chunk128` scheduler, compact slot allocation, `-np 4 -cb`.

| Concurrency | Aggregate output tok/s | TTFT p50 | E2E p95 |
| ---: | ---: | ---: | ---: |
| 1 | 107.96 | 72.5 ms | 600 ms |
| 2 | 167.72 | 149.4 ms | 769 ms |
| 3 | 206.28 | 247.8 ms | 992 ms |
| 4 | **230.82** | 347.7 ms | 1128 ms |

All four cells `VALID`, 40/40 C=4 requests successful. The original V2 series
published 108.01 / 169.12 / 207.71 / **233.99** on an earlier build and weight
artifact; the current production binary measures 0.04% to 1.36% lower. See
`work/PRIMARY_METRIC_V11.md`.

### Interactive 8K profile, mixed 3 decoders + 1 prefill

| Format | New-user TTFT | Resident ITL p95 | Decode retention | Resident aggregate |
| --- | ---: | ---: | ---: | ---: |
| ROCmFP4_FAST (`b4096/ub128`) | 5197 ms | 88.5 ms | 15.96% | 238.9 tok/s |
| **Q4_0 (`b4096/ub128`)** | **4847 ms** | **83.0 ms** | **17.82%** | 229.5 tok/s |

Three paired runs, every 95% interval excluding zero: TTFT −6.98%
[−7.06, −6.41], ITL p95 −7.16% [−8.55, −3.80], retention +11.61%
[+11.32, +12.14], resident decode −3.96%. The control arm reproduces the
published V9 production numbers, which is what makes the deltas trustworthy.

The interactivity goal recorded in V8/V9 is **still not met**: 83.0 ms against
a ≤70 ms ITL target, with TTFT comfortably inside its ≤5.5 s guardrail.

### Direct kernel screen at the prefill shape

`ROCmFPXVulkan0`, three repetitions, same build:

| Model | bpw | pp128 | pp512 | pp2048 | tg128 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ROCmFP4_FAST | 4.25 | 2271 | 2459 | 2389 | **132.74** |
| Q8_0 | 8.50 | 1907 | 2206 | 2175 | 76.03 |
| Q4_0 | 4.70 | **2621** | **2739** | **2669** | 123.87 |

The format ranking inverts with shape: Q4_0 is 15.4% faster at the prefill
chunk and 11.7% faster at 2048, while FP4_FAST keeps a 7.2% decode advantage.

## Important engineering findings

- **The format choice depended on a shape the campaign had stopped
  measuring.** Format screening happened once, at 128/64 and 512/128, where
  decode dominates and FP4_FAST wins. When the objective moved to an 8K
  prefill-dominated workload (prefill is 83.5% of the mixed pair), the ranking
  inverted and nobody re-screened. Q4_0 is worth −7.0% TTFT and −7.2% ITL on
  the profile that was being optimized.
- **More bits do not buy prefill speed.** Q8_0 removes FP4 code/scale unpacking
  from the inner loop and doubles the weight bytes; it is 16.0% slower at
  pp128. V10's three FP4 block-layout candidates (padded +17.65% bytes for
  1.227% local, global planar +43.150%, grouped-four +3.851%) failed for the
  same reason: the bottleneck is not the block layout.
- **Marginal returns on the MMQ family are exhausted.** Roughly 40 shader
  variants across V3--V10 produced a best service-level kernel result of
  +1.1641% (selective gate/up BK3), and the largest service win in the whole
  campaign was a scheduler setting, not a kernel.
- `ubatch=512` triggers a server-only performance cliff correlated with the
  RX 6600 XT memory clock alternating between 541 and 1000 MHz. `ubatch=128`
  avoids it without changing system power settings.
- Sparse active slot IDs such as `{0, 1, 3}` reduce the contemporary coherent
  model from about 200--202 to 131--132 tok/s. V3 proves the recurrent allocator
  splits the sparse set every step. The opt-in compact scheduler in the included
  ROCmFPX patch selects the lowest available slots and removes this cliff; the
  staged dense-internal-ID runtime (R1) preserves logical API slot IDs, passes
  active completion/cancellation/reuse with host sampling, and still awaits
  deterministic logit equivalence before production.
- Backend sampling cannot be rebound safely during sequence migration. Dense
  remapping rejects that combination explicitly instead of aborting or silently
  changing the sampling policy.
- A shape-specific four-subgroup FP4_FAST decode selector improved selected
  exact-pipeline microbenchmarks but reduced full-server C4 throughput by 5.29%
  in the observed run. It is retained only as an experimental switch.
- Capping prompt admission at 128 tokens per iteration lifted decode retention
  from 1.46% to 15.70% and cut resident ITL p95 from 2189 ms to 89 ms on the 8K
  profile, at a cost of +22.4% new-user TTFT. This remains the single largest
  improvement the campaign produced.
- ROCmFPX Q2 is fast and memory-efficient but failed basic output-quality
  checks, so it is not a production candidate.
- ROCmFPX HIP kernels beat equivalent upstream HIP kernels in trace-only
  profiling, but both HIP server paths remain far behind Vulkan on gfx1032.

## Known gaps

- **No formal quality metric exists for any format.** Perplexity and KL
  divergence against the BF16 checkpoint, using the `llama-perplexity` binary
  already built in this tree, were identified as the highest-value next
  experiment on 2026-09-17 and had still not been run when V11 closed. Every
  quality statement in this repository is a smoke test, an exact-text check or
  an output-hash comparison. This is the one item that blocks any deployment
  claim.
- The 8K interactivity target (ITL p95 ≤ 70 ms) is missed by 18.5%. V9 showed
  that scheduling alone cannot close it, and V11 shows that format choice alone
  cannot either; the remaining gap is prefill graph cost.
- The primary metric was re-measured only once, in V11, after having been left
  unchecked from V2 through V10. It is now a standing gate.

## Repository layout

- `work/RESULTS.md`: V2 decision report and leaderboard.
- `CAMPAIGN_CONTINUATION.md`: the V3--V10 continuation guide.
- `work/EXPERIMENTS.md`: hypotheses, evidence and KEEP/STAGE/REJECT decisions,
  V1 through V10.
- `work/BASELINES.json`: machine-readable baselines.
- `work/HARDWARE_MANIFEST.json`: hardware, source revisions and artifact hashes.
- `work/SHAPE_CENSUS.csv` and `work/SHAPE_CENSUS_V3.csv` through `_V5.csv`:
  profiled Vulkan operation shapes.
- `work/PLUGIN_EXECUTION_MAP.md`, `work/PROFILE_V3.md`,
  `work/CAMPAIGN_V3_RESULT.md`, `work/SEQUENCE_REMAP_VALIDATION.md`: the first
  campaign's plugin dispatch map, profile, result and runtime remap validation.
- `work/MISC_BREAKDOWN_V11.md`: prefill `misc` decomposition by op and graph,
  with the leverage verdict that closes the micro-optimization route.
- `work/FORMAT_PREFILL_V11.md`: the format finding, screen and paired A/B.
- `work/PRIMARY_METRIC_V11.md`: primary-metric regression control.
- `work/NEXT_ACTION.md`: current production state and the next exact actions.
- `work/HANDOFF_V9.md`, `work/HANDOFF_V10.md`: per-version handoffs.
- `work/KERNEL_MICROBENCH_V*.md`, `work/PREFILL8K_PROFILE_V*.md`,
  `work/ATREX_SEARCH_V*.md`, `work/CONCURRENCY_PROFILE_V*.md`: per-version
  microbenchmark, profile and automated-search records.
- `work/scripts/`: reproducible HTTP benchmark, interference, analysis and
  microbenchmark tooling.
- `work/tests/`: the harness and analyzer test suite (`pytest -q work/tests`).
- `work/results/`: raw benchmark evidence for every run.
- `patches/ROCmFPX-gfx1032.patch`: local ROCmFPX changes against revision
  `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1`.
- `patches/`: every candidate shader change, grouped by campaign version
  (`v5-*`, `v6-auto/`, `v8-*`, `v9-*`, `v10-fp4-layouts/`), each with its
  matching revert patch where one was applied.
- `patches/campaign-v3-runtime-kernel.patch`,
  `patches/campaign-v4-prefill-chunk.patch`: the two promoted runtime changes.

## Excluded artifacts

Models, compiled builds, nested source clones and large raw profiler captures
are deliberately not committed. They total about 16 GiB and include files larger
than GitHub's normal 100 MB limit. Exact model hashes and source revisions are
recorded in `work/HARDWARE_MANIFEST.json`; see `MODEL_ARTIFACTS.md` for details.

Raw capture files of 1 MiB or more under `work/results/` are excluded as well,
under the same policy. The excluded files are enumerated with sizes and SHA-256
hashes in `work/EXCLUDED_CAPTURES.json`, so a reader can tell whether a local
tree matches the published one.

## Reproducing the benchmarks

Build ROCmFPX at the recorded revision, apply the included patch, and provide
the models with the recorded SHA-256 values. Then:

```bash
# Primary metric, 128/64, C=1..4
GPU_RESERVATION_CONFIRMED=1 work/scripts/run_primary_metric_v11.sh /tmp/v11-primary

# Direct prefill/decode format screen
work/scripts/screen_format_prefill.sh /tmp/v11-screen

# Mixed 8K interactive profile, paired format A/B
PAIRS=3 work/scripts/run_format_interference_abba.sh /tmp/v11-abba
```

The plugin build needs the isolated GCC 16 runtime preloaded; the wrapper
scripts set `LD_PRELOAD` themselves. No system driver, firmware, GPU power
profile or clock setting was modified by this campaign. Hardware profiling after
the earlier reset was trace-only.
