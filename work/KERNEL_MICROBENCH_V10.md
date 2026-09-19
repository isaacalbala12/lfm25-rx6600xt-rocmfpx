# V10 FP4_FAST gate/up layout microbenchmarks

## Immutable problem

- Backend: exact ROCmFPXVulkan0 plugin Vulkan path.
- Shape: `M=10752,K=2048,N=128`, FP4_FAST x Q8_1.
- Control: production selective BK3,
  `matmul_rocmfp4_fast_q8_1_bk3_m`.
- Method: CPU-reference hard gate, exact route proof, logger-free five-pair
  ABBA and paired bootstrap.
- V9 mixed-batch gate/up share: 29.50%; approximately 2.55% local improvement
  is required for 0.75% predicted mixed-batch leverage.

## Candidate results

| Candidate | Device representation | Control us | Candidate us | Paired delta | 95% CI | Decision |
|---|---|---:|---:|---:|---:|---|
| padded | 20 B/block: 4 aligned code words + aligned scale word | 412.250 | 407.230 | -1.227% | [-1.906%, -0.386%] | COMPOSABLE only |
| global planar | all 16-byte code regions, then all scales; 17 B/block | 412.685 | 588.300 | +43.150% | [+40.833%, +43.873%] | REJECT |
| grouped-four | 64 code bytes + four adjacent scales; 17 B/block | 412.715 | 428.005 | +3.851% | [+3.308%, +4.473%] | REJECT |

All candidates passed exact CPU-reference correctness and selected their named
pipelines. No server benchmark was run for the three layouts.

## Static evidence

The padded candidate reduced SPIR-V size 3.68% and instructions 2.80%, including
nine fewer access chains, nine fewer integer additions and nine fewer loads.
This produced a real but low-leverage local gain. It also expands each selected
weight tensor from 17 to 20 bytes per block: +17.65% for those tensors.

The compact global-planar candidate also removed nine access chains and nine
loads, but moving scales to a distant plane regressed latency 43.15%. This is
strong evidence that code/scale locality matters more than the static load-count
reduction.

The grouped-four candidate restored scale locality and retained exactly 17
bytes per block, but added group/lane address and extraction work and still
regressed 3.85%. The tested layout family is closed.

Raw results:

- `work/results/v10-gate-padded-micro/`
- `work/results/v10-gate-planar-micro/`
- `work/results/v10-gate-group4-micro/`
- `work/results/v10-gate-*-static.json`

Reconstruct the nested source from ROCmFPX `f5acc76` with the three mail patches
under `patches/v10-fp4-layouts/`. All selectors default off.
