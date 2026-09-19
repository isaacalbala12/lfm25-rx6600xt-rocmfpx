# Kernel microbenchmark V5

No shader was promoted. The proposed 6144x2048 N=4 route was rejected before
implementation because C4 is already represented by `ne[2]=4` in one per-layer
dispatch. The measured new scheduler candidate was chunk96: 82.677-ms ITL p95
and 16.627% retention, but 6646-ms TTFT; **REJECT**.

The fenced 8K profile selects gate/up first: 23.500 ms per full N=128 tile,
32.79% of grouped GPU time. Down is 16.684 ms (23.28%), and Flash Attention is
16.566 ms (23.11%). The next variant must alter the gate/up in-wave MMQ tile or
FP4 unpack/load path, not subgroup count. It must use the plugin backend and
preserve FP4_FAST values.

Flash Attention is now mapped separately in `work/FLASH_ATTN_PROFILE_V5.md`.
Removing its RDNA2 occupancy limiter improves long-tile FA locally by only
about 0.7–1.6%, yields no logger-free service gain, and is **REJECT**.

## EXP-V5-KERNEL-GATEUP-N128-PACKED32 — REJECT

- Exact path: the plugin's medium integer MMQ pipeline for FP4_FAST x Q8_1,
  gate/up `M=10752`, `K=2048`, `N=128`. RADV has no cooperative-matrix path
  here, so the selector resolves to the plugin's medium pipeline.
- Hypothesis: replace four byte loads for each 16-code FP4_FAST block with two
  aligned 32-bit reads plus an exact shift/or extraction. Codes and the scale
  byte are unchanged; the candidate therefore changes storage access only.
- Implementation checkpoint: ROCmFPX `dea21b2`. The isolated CPU-reference
  case passed 1/1 before timing. Candidate binary hash:
  `2e9cda0c63fbddcf0e2e9737d089c19926fe282c06bd288a75dc0b6dec0a9be7`.
- Logger-free ABBA, ten pairs and twenty samples per arm: 427.475 us control
  versus 434.800 us candidate. The paired median regression is +1.880%, with
  bootstrap 95% interval [+1.692%, +2.071%].
- Maximum whole-profile leverage is therefore negative: approximately
  `32.79% * 1.88% = 0.62%` predicted regression even before other operations.
- Decision: **REJECT** before server testing. The production shader was
  restored at ROCmFPX `d92f6a4`; its library hash exactly matches the saved
  control (`40f6b9c...b25b40`). Candidate and revert patches plus all timing
  samples are retained under `patches/` and
  `work/results/v5-kernel-gateup-n128-packed-load-abba10/`.

This result closes the naive unaligned-to-aligned load substitution. The next
gate/up experiment must change tile geometry or reduce actual unpack/address
work; it must not reintroduce this extraction sequence.

## EXP-V5-KERNEL-PREFILL-WIDE-N128 — REJECT

- Selector audit corrected the specialization interpretation: the RDNA2 medium
  MMQ tuple is `BLOCK_SIZE=256, BM=64, BN=64`; 256 is not BM.
- Hypothesis: use `BM=32, BN=128` with the same 256 threads and remaining
  geometry. At N=128 this preserves the total number of workgroups while each
  weight row is loaded for one column tile instead of two.
- Exact CPU-reference correctness passes for both gate/up
  `10752x2048x128` and down `2048x10752x128`.
- Ten logger-free ABBA pairs, twenty samples per arm:
  - gate/up: 428.010 us control, 427.820 us candidate; paired median -0.125%,
    bootstrap 95% interval [-0.257%, +0.194%];
  - down: 507.215 us control, 508.920 us candidate; paired median +0.367%,
    interval [-0.068%, +0.541%].
- Decision: **REJECT** before server testing. Gate/up is indistinguishable from
  control and down trends slower; both effects are below the 0.75% retention
  threshold. ROCmFPX `a6dd6ad` restores the 64x64 tile, and the rebuilt backend
  hash matches the saved control exactly (`40f6b9c...b25b40`).

The reusable test coverage for both exact N128 shapes remains at ROCmFPX
`f65b3dc`. Raw samples and paired bootstrap output are in
`work/results/v5-kernel-prefill-wide-n128/`.

## EXP-V5-KERNEL-PREFILL-BKSTEP2-GLOBAL — REJECT; selective signal STAGE

- Hypothesis: reduce FP4_FAST MMQ `BK_STEP` from 4 to 2. This halves staged K
  data and LDS per workgroup at the cost of twice as many K-loop barriers. The
  `MUL_MAT_ID` path remains at its mandatory value 1.
- Exact CPU-reference correctness passes for gate/up and down N128.
- Ten logger-free ABBA pairs, twenty samples per arm:
  - gate/up: 427.455 us control, 416.305 us candidate; paired median -2.400%,
    bootstrap 95% interval [-2.952%, -2.226%];
  - down: 508.665 us control, 531.600 us candidate; paired median +4.712%,
    interval [+4.458%, +5.041%].
- Profile-weighted estimate for enabling it globally:
  `32.79% * -2.400% + 23.28% * +4.712% = +0.310%` wall regression. This is an
  estimate from fenced group fractions, not a server result.
- Decision: global candidate **REJECT**, no server run. A dedicated gate/up
  pipeline is **STAGE hypothesis**: the isolated measured ceiling is about
  `32.79% * 2.400% = 0.787%` overall before dispatch/selector overhead.
- ROCmFPX `f7a53ab` restores global BK_STEP=4 and reproduces the saved control
  backend hash exactly. Candidate source and all samples remain reproducible in
  `patches/v5-fp4fast-bkstep2-candidate.patch` and
  `work/results/v5-kernel-prefill-bkstep2/`.

Do not enable BK_STEP=2 for all FP4_FAST matrices. The only justified follow-up
is a second compiled pipeline selected for gate/up-like `M=10752,K=2048,N`
prefill shapes, with step 4 retained for down and decode.

## EXP-V5-KERNEL-GATE-SELECTIVE-BKSTEP2 — ARCHIVE COMPOSABLE

- Implementation: a second embedded SPIR-V,
  `matmul_rocmfp4_fast_q8_1_bk2`, selected only when FP4_FAST uses quantized
  RHS with `M=10752,K=2048,N>64`. It is opt-in through
  `GGML_VK_ROCMFP4_FAST_MMQ_BK2_GATEUP=1`; default remains the control.
- Pipeline proof: gate/up N128 logs
  `matmul_rocmfp4_fast_q8_1_bk2_m`; down logs the unchanged
  `matmul_rocmfp4_fast_q8_1_m`. Decode N<=6 cannot satisfy the selector.
- CPU-reference correctness: gate/up N=120/128/129 and down N=128 all pass.
- Same-binary ABBA, ten pairs and twenty samples per arm:
  - gate/up: 426.790 -> 416.495 us; paired -2.601%, 95% CI
    [-2.862%, -2.211%];
  - down control guardrail: paired -0.005%, CI [-0.410%, +0.373%].
- Boundary exploration also wins at N=120/128/129 by approximately
  2.47%/3.10%/3.17% respectively.
- Simultaneous 8K prefill C4 with chunk128, three repetitions per arm:
  aggregate output 48.084 -> 48.600 tok/s (+1.072%), input 1538.70 ->
  1555.19 tok/s; TTFT p95 17807.29 -> 17573.98 ms (-1.31%). All 24 requests
  are valid and uncached. All 12 corresponding generated texts, finish reasons
  and output-token counts match exactly between arms.
- One contemporary 3D+1P guardrail: retention 15.632% -> 15.947%, resident ITL
  p95 89.366 -> 88.212 ms, and new-user TTFT 5304.59 -> 5221.88 ms. This is a
  single pair and is not a confidence claim.
- Final service validation: ten independent paired Profile B batches with
  alternating AB/BA order, one fresh server per arm and the same binary/model/
  sampler. All ten pairs are valid and all ten favor the candidate. Median
  aggregate throughput is +0.486%, with batch-level bootstrap 95% CI
  [+0.371%, +0.705%]. TTFT p95 improves 0.693% (CI 0.426–0.842%) and E2E p95
  improves 0.485% (CI 0.371–0.675%). Generated text, finish reason and output
  token count match exactly in 10/10 pairs.
- Decision: **ARCHIVE COMPOSABLE**, not a standalone promotion. The effect is
  reproducible and correct; +0.486% lies in the current 0.2–0.75% composable
  band. Do not spend more tuning time now, but retain its selector, patch and
  evidence for later composition. ROCmFPX `7838dd2` removes the candidate from
  production; the rebuilt production library exactly matches the
  saved control SHA-256 `40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
  The implementation and revert remain reproducible as patches; raw service
  evidence is in `work/results/v5-prefill8k-c4-selective-bk2-paired10/`.

## EXP-V5-FA-RDNA2-BC64 — REJECT

- Exact plugin path and shape: scalar integer-dot FA, Q8/Q8, HSK=HSV=64,
  nh=8, `nr23=[4,4]`, KV=8192, N=32.
- Correctness: control Bc32 and opt-in Bc64 both pass CPU reference.
- Logger-free ABBA operation times: control 7614.54/7638.27 us; candidate
  8773.06/8703.19 us. Median delta: **+14.58% latency**.
- Decision: **REJECT immediately**; no server run. The experiment exceeds the
  5% micro-regression cutoff, so no further FA tile sweep is justified in V5.

## EXP-V5-KERNEL-DOWN-N4-HYBRID — REJECT

- Exact path: `quantize_q8_1_x4 -> mul_mat_vec_rocmfp4_fast_q8_1_f32`,
  `M=2048,K=10752,N=4` in the plugin backend.
- Candidate: exact-shape selector for the existing four-subgroup
  `large_hybrid` reduction; all other forms remain subgroup.
- Selector proof reports `m=2048 n=4 k=10752 reduction=large_hybrid`.
- CPU-reference correctness passes for both arms.
- Ten ABBA pairs / twenty measurements per arm: 58.020 us subgroup versus
  68.315 us hybrid, **+17.744% latency**.
- Decision: **REJECT**, no server run. The current one-subgroup kernel is
  decisively better for down N=4; do not revive the old broad selector.

## EXP-V5-KERNEL-GATE-N4-ARITH-UNPACK — REJECT

- Exact path: FP4_FAST x Q8_1 DMMV, `M=10752,K=2048,N=4`, one wave32.
- Hypothesis: replace eight shared codebook lookups per FP4 block with an exact
  arithmetic decode of magnitude `{0,1,2,3,4,6,8,10}` and sign bit 3.
- Same-library selector proof reports `reduction=subgroup` and `unpack=arith`;
  all other shapes retain the LUT pipeline.
- CPU-reference correctness passes for control and candidate.
- Ten logger-free ABBA pairs / twenty samples per arm: 65.075 us LUT versus
  94.145 us arithmetic, **+44.672% latency**.
- Decision: **REJECT immediately**, no server run. Avoiding LDS here costs far
  more ALU/register work than it saves. Candidate commit `66a426a`; production
  is restored by ROCmFPX `055241b`.

## EXP-V5-KERNEL-GATE-N4-DUALACC — REJECT

- Hypothesis: alternate K iterations between two independent accumulator banks
  to break the FP4_FAST dot-product dependency chain inside the existing
  one-wave gate/up N=4 kernel.
- Selector proof reports `reduction=subgroup` and `accum=dual`; unpack,
  geometry, FP4 codes and scales remain unchanged.
- Both arms pass exact CPU-reference correctness.
- Ten logger-free ABBA pairs / twenty samples per arm: 64.680 us single-bank
  versus 71.065 us dual-bank, **+9.872% latency**.
- Decision: **REJECT**, no server run. Added VGPR pressure/final reduction
  outweighs any dependency-level parallelism. Candidate commit `150396a`;
  production is restored by ROCmFPX `7c4b5c0`.
