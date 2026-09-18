# Atrex integration plan for ROCmFPX Vulkan

## Audit scope and pinned source

The audit uses the official `alibaba/atrex-kernel-agent` repository at
`d83b01a4a14f2dd451630f4e3551bbd1a3a69575`, cloned read-only under the ignored
`work/sources/` tree.  The production source of truth remains the ROCmFPX
plugin Vulkan backend at checkpoint `7c4b5c0`; Atrex is not a replacement
backend.

The current Atrex entry point (`orchestrator/optimize.py`) is designed around
native Atrex-Bench/SOL-ExecBench operator workspaces.  Its campaign fast path
constructs `python test_kernel.py --version ...`, its production policy expects
the generated implementation in `kernel.py`, and its verifier consumes the
Atrex result schema.  It therefore cannot directly evaluate this multi-file
GLSL/C++ plugin without an adapter.

## What can be reused

- A bounded episode loop with explicit attempt, valid-candidate and consecutive
  non-improvement limits.
- Git-isolated candidate history, parent relationships and binary patch
  archives.
- Fail-closed promotion: build, route proof and numerical correctness are hard
  gates, never terms in a speed score.
- Alternating ABBA verification of incumbent and candidate, with each complete
  run as the statistical unit.
- Canonical campaign memory containing accepted, rejected and taboo mutations,
  so later agents do not rediscover measured failures.
- Atomic JSON state, resumability, candidate handoff records and explicit
  rollback on evaluator or agent failure.
- Static compiler/disassembly evidence as a safe profiler hook.  Hardware PMC
  collection is deliberately excluded.

## What cannot be reused unchanged

- The single-file `kernel.py` candidate policy.  ROCmFPX candidates may need a
  shader, shader generator, backend selector and exact test case.
- `test_kernel.py`, its `RESULT_JSON` payload and Atrex's latency/geomean
  parser.  The source of truth here is `test-backend-ops` loaded through
  `ROCmFPXVulkan0`.
- Framework conversion and production-policy checks for Triton/FlyDSL.  A fast
  Triton or HIP result is algorithm-discovery evidence only.
- Private-shape and evaluator bundling assumptions.  Our boundary shapes and
  selector proof must remain inspectable and reproducible.
- A fresh worktree for every timed arm: the ROCmFPX build is large and only
  about 13 GiB was free at audit time.  Candidate source isolation is useful,
  but duplicating build trees would create an avoidable disk/OOM risk.

## Minimal adapter

`work/scripts/atrex_vulkan_evaluator.py` is the compatibility seam.  It uses a
small JSON candidate manifest rather than pretending that ROCmFPX is an Atrex
operator:

1. verify the pinned source revision, clean source tree and exact build/test/
   backend paths;
2. reject mutations matching the V4/V5 taboo catalogue;
3. optionally apply a reversible candidate patch to an allowlisted set of
   plugin backend/test files;
4. build only the required targets and record compiler, source, shader,
   executable and loaded-backend hashes;
5. run the exact CPU-reference operation test for FP4_FAST x Q8_1 at
   `M=10752,K=2048,N=128` (plus boundary guardrails for finalists);
6. require selector/logger evidence that the candidate pipeline actually ran;
7. run logger-free incumbent/candidate measurements in ABBA order and emit a
   stable JSON result with median, p5/p95, paired delta and variance;
8. store the candidate result and update bounded campaign state atomically;
9. reverse the patch and verify the source and production backend are restored,
   even after build, test or benchmark failure.

The preferred experiment shape compiles incumbent and opt-in candidate
pipelines into one library, selected by an environment variable.  This makes
same-binary ABBA possible and avoids attributing toolchain or unrelated build
changes to the shader.  A candidate that replaces the incumbent globally must
instead provide two verified backend artifacts and alternate the exact loaded
library; it receives a stronger provenance check.

The first evaluator targets gate/up `10752x2048x128`.  Down
`2048x10752x128` is a separate campaign and search space, not another shape in
the same fitness aggregate.

## Correctness and promotion contract

Correctness is a hard gate.  A build failure, missing expected pipeline,
non-finite output, tolerance failure or incomplete sample set records an
invalid candidate and no latency score.  The evaluator itself, tolerances,
reference and selectors are protected files and may not be changed by a
candidate.

The primary fitness is median exact-operation latency.  Secondary diagnostics
are p5/p95, paired dispersion, binary size and compilation success.  A local
gain of at least 3% advances immediately to server validation; 1--3% advances
only when profile share makes global leverage useful.  Below 1% is rejected
unless evaluation cost is negligible and the mutation is structurally useful.

Finalists must also pass N=120/128/129, another matrix in the same family,
logger-free server tests, service EOS and the reserved quality corpus.  No
microbenchmark result changes production by itself.

## Search budget and memory

The first campaign stops at 30 valid candidates, 60 total attempts, or ten
consecutive valid candidates without improving the incumbent.  Every record
contains candidate id, parent, mutation, changed files, build outcome,
correctness, route proof, samples, median delta, variance, decision and reason.

Initial taboo mutations are populated from measured V4/V5 results:

- two- and four-subgroup gate/up reductions;
- arithmetic FP4 unpack;
- dual accumulators;
- naive aligned packed-32 extraction;
- `BM=32, BN=128` for the N=128 prefill family;
- global `BK_STEP=2`;
- rows4 short-conv and broad N-only selectors.

Selective gate/up `BK_STEP=2` is not taboo: it is archived as composable and
must be evaluated only after an independent winner exists.

## Risks and controls

- **Benchmark specialization:** final candidates are checked at N=120/129 and
  on another real matrix before server promotion.
- **Wrong route:** selector evidence and loaded-library hashes are mandatory;
  timed runs have logging disabled.
- **Stale binary:** shader/source and backend hashes are recorded after every
  build, and a no-change build/hash check is part of baseline establishment.
- **Thermal/order bias:** use ABBA, retain slow valid samples and treat a full
  run/pair as the unit of inference.
- **Unsafe rollback:** only allowlisted patches are reversible; restoration and
  a clean-source check run in `finally`.  The evaluator never uses destructive
  Git reset/checkout operations.
- **Disk pressure:** reuse one build tree, keep text logs/patches, and avoid
  copying models or complete build trees.
- **Agent reward hacking:** candidate code cannot modify evaluator, reference,
  filters, tolerance, result parser or promotion threshold.

## Expected benefit

The integration does not itself promise a speedup.  Its immediate benefit is
to turn the remaining high-leverage shader search into a reproducible,
fail-closed campaign where negative results become memory.  Gate/up owns
32.79% and down 23.28% of the profiled N=128 prefill tile, so a genuine 10%
local improvement has ceilings of roughly 3.28% and 2.33% respectively before
server effects.  Those are large enough to justify automated search and small
enough that exact route proof and paired measurements are essential.

