# LFM2.5-2.6B on RX 6600 XT / gfx1032

Reproducible performance-engineering campaign for LFM2.5-2.6B on an AMD
Radeon RX 6600 XT (RDNA2/gfx1032), optimized for one to four concurrent
requests.

The primary workload is 128 input tokens and 64 output tokens. The primary
metric is aggregate output tokens delivered per second at concurrency four,
measured from the first HTTP request send to the final response completion.

## Current result

ROCmFPX `ROCmFPXVulkan0` with ROCmFP4_FAST, q8 KV, `batch=512`,
`ubatch=128`, continuous batching and compact slot allocation reaches:

| Concurrency | Aggregate output tok/s |
| ---: | ---: |
| 1 | 108.0 |
| 2 | 169.1 |
| 3 | 207.7 |
| 4 | 234.0 |

At C=4, a 200-request run measured 234.0 tok/s versus 226.7 tok/s for
upstream llama.cpp Vulkan Q4_0. The paired improvement was 3.30%, with a
95% bootstrap confidence interval of 2.77% to 3.84%. Both completed all 200
requests.

The winner depends on workload shape. ROCmFPX wins 128/64 and 512/128;
upstream llama.cpp Vulkan wins 2048/256 and the exploratory 7680/512 screen.

## Important engineering findings

- `ubatch=512` triggers a server-only performance cliff correlated with the
  RX 6600 XT memory clock alternating between 541 and 1000 MHz. `ubatch=128`
  avoids it without changing system power settings.
- Sparse active slot IDs such as `{0, 1, 3}` reduce the contemporary coherent
  model from about 200–202 to 131–132 tok/s. V3 proves that the recurrent
  allocator splits the sparse set every step. The staged opt-in runtime now
  uses dense internal sequence IDs while preserving logical API slot IDs; it
  passes active completion/cancellation/reuse with host sampling, but awaits
  deterministic logit equivalence and paired dynamic-service statistics.
- Backend sampling cannot currently be rebound safely during sequence
  migration. Dense remapping now rejects that combination explicitly instead
  of aborting or silently changing the sampling policy.
- A shape-specific four-subgroup FP4_FAST decode selector improved selected
  exact-pipeline microbenchmarks, but reduced full-server C4 throughput by
  5.29% in the observed run. It is retained only as an experimental switch;
  the production default remains unchanged.
- ROCmFPX Q2 is fast and memory-efficient but failed basic output-quality
  checks, so it is not a production candidate.
- ROCmFPX HIP kernels beat equivalent upstream HIP kernels in trace-only
  profiling, but both HIP server paths remain far behind Vulkan on gfx1032.

## Repository layout

- `work/RESULTS.md`: full decision report and leaderboard.
- `work/BASELINES.json`: machine-readable current baselines.
- `work/EXPERIMENTS.md`: hypotheses, evidence and KEEP/STAGE/REJECT decisions.
- `work/HARDWARE_MANIFEST.json`: hardware, source revisions and artifact hashes.
- `work/SHAPE_CENSUS.csv`: earlier upstream-oriented shape census.
- `work/SHAPE_CENSUS_V3.csv`: measured plugin pipelines and current shapes.
- `work/PLUGIN_EXECUTION_MAP.md`: proven plugin/backend dispatch map.
- `work/PROFILE_V3.md`: current profile and sparse-slot runtime decision.
- `work/CAMPAIGN_V3_RESULT.md`: first-campaign result in the requested handoff format.
- `work/SEQUENCE_REMAP_VALIDATION.md`: runtime migration invariants, active
  cancellation evidence and backend-sampling limitation.
- `work/KERNEL_MICROBENCH_V3.md`: exact plugin pipeline benchmark and rejected
  server-level kernel candidate.
- `work/scripts/`: reproducible HTTP benchmark and analysis scripts.
- `work/results/`: lightweight raw benchmark evidence.
- `patches/ROCmFPX-gfx1032.patch`: local ROCmFPX changes against revision
  `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1`.
- `patches/campaign-v3-runtime-kernel.patch`: cumulative continuation patch for
  versioned source files, including runtime controls, tests and the
  experimental kernel selector. The RDNA2 header is restored separately from
  the original patch as described in `work/NEXT_ACTION.md`.

## Excluded artifacts

Models, compiled builds, nested source clones and large raw profiler captures
are deliberately not committed. They total about 16 GiB and include files
larger than GitHub's normal 100 MB limit. Exact model hashes and source
revisions are recorded in `work/HARDWARE_MANIFEST.json`; see
`MODEL_ARTIFACTS.md` for details.

## Reproducing the primary benchmark

Build ROCmFPX at the recorded revision, apply the included patch, and provide
the FP4_FAST model with the recorded SHA-256. Then run the command recorded in
`work/NEXT_ACTION.md`.

No system driver, firmware, GPU power profile or clock setting was modified by
this campaign. Hardware profiling after the earlier reset was trace-only.
