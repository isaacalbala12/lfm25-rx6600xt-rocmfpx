# Flash Attention profile V5

## Executed path at C4 x 8K

The selection-only run in `work/results/v5-fa8k-selection-map/` proves that
ROCmFPXVulkan0 executes the plugin backend's scalar integer-dot Flash Attention
shader, not upstream Vulkan:

- source: `extensions/rocmfpx-vulkan/backend/vulkan-shaders/flash_attn.comp`;
- pipeline: `flash_attn_f32_f16_aligned` from the integer-dot SPIR-V module;
- Q head size / V head size: 64 / 64;
- KV: Q8_0 / Q8_0, four independent 9216-token slots;
- RDNA2 scalar tuning at the large prefill tile: wave32, 128-thread workgroup,
  `Br=8`, `Bc=32`, `D_split=8`, `row_split=1`, no K/V shared staging;
- the production selector reserves 26 KiB of otherwise unused shared memory to
  limit occupancy for `N>=64, HSK<=64` on RDNA2;
- the aligned path is used. No split-K reduction is needed at this high
  workgroup count.

Selection logging is invasive and its wall throughput is not a service result.
The run exists only to establish the executed pipeline and dispatch geometry.

## EXP-V5-FA-RDNA2-NO-OCCUPANCY-LIMIT — REJECT

Hypothesis: the synthetic 26-KiB shared-memory allocation may over-throttle the
large-N LFM2 prefill path. An opt-in, shape-scoped candidate removed it only for
RDNA2 `N>=64, HSK=HSV=64`; decode and all other shapes retained production
tuning.

Three logger-free simultaneous 8K C4 repetitions showed no service gain:

- control median input throughput: 1855.28 tok/s;
- candidate median input throughput: 1852.67 tok/s;
- exploratory delta: -0.141%.

A separate timestamp run, excluded from service throughput, compared the same
`N=32, batch=4` FA shapes. At KV=7168/7424/7680/7936/8192, median per-layer
candidate deltas were respectively -0.90%, -1.49%, -1.62%, -0.69% and -1.51%.
The local signal is therefore real but too small: at FA's 23.11% profile share,
1.51% local implies only about 0.35% maximum global leverage before overhead.

Decision: **REJECT**. The candidate is correct and narrowly faster inside FA,
but it misses the 0.75% global retention threshold and does not improve the
server. ROCmFPX `e7ec6c2` restores the production selector.

The next FA experiment must change useful work or memory access, not merely
occupancy. A single `Bc=64` large-N variant is the next bounded hypothesis,
subject to shared-memory feasibility and exact microbenchmarking first.
