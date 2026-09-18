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

## EXP-V5-FA-RDNA2-BC64 — REJECT; close FA in V5

The one permitted follow-up doubled the scalar shader's column tile from
`Bc=32` to `Bc=64` only for RDNA2, Q8/Q8, HSK=HSV=64, N>=32 and KV>=1024.
It used the plugin backend and an exact LFM2 C4 long-context test geometry:
32 Q heads over 8 KV heads, four batch planes, N=32 and KV=8192. Both the
control and candidate pass the CPU-reference operation test.

A logger-free exploratory ABBA run measured synchronized operation wall time:

| Order | Control Bc32 | Candidate Bc64 |
|---|---:|---:|
| A/B | 7614.54 us | 8773.06 us |
| B/A | 7638.27 us | 8703.19 us |

The medians are 7626.41 us and 8738.13 us: **+14.58% latency** for Bc64.
This exceeds the predeclared 5% immediate-rejection boundary, so no server
benchmark was run. The candidate patch is archived as
`patches/0001-perf-prototype-RDNA2-FA-Bc64-tile.patch`; ROCmFPX `55dfdf0`
restores the production selector. The rebuilt production backend hash is again
`40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.

Decision: **REJECT** and close Flash Attention optimization for V5. The
occupancy bypass offers only ~0.35% global ceiling and Bc64 is decisively
slower. Reopen FA only with a new algorithmic or memory-access hypothesis whose
measured global leverage can exceed 0.75%.
