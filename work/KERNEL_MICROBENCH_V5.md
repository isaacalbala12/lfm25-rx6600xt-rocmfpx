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
