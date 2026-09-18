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
