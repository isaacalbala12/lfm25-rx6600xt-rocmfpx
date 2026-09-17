# ROCmFPX Vulkan kernel experiment — gfx1032

## Exact path

The benchmark extends `test-backend-ops` and directly loads
`libggml-rocmfpx-vulkan.so`. It builds normal GGML graphs with
`q4_0_rocmfp4_fast` weights and F32 activations, so the plugin's real planner
selects:

`quantize_q8_1_x4 -> mul_mat_vec_rocmfp4_fast_q8_1_f32`

Selection logs prove the backend, tensor types, strides, Q8_1 preparation,
pipeline and workgroup denominators. Shapes come from the LFM2.5-2.6B census:
10752x2048, 2048x10752, 6144x2048 and 2048x2048 at N=1/2/4/6.

The timing reported by this first microbenchmark is synchronized graph wall
time per operation, including the graph's activation preparation where
selected. It is not claimed as DRAM bandwidth or pure shader GPU time. The
server profiler remains the source for timestamped per-node GPU timing.

Logger controls were also checked with all relevant variables absent versus
explicitly set to `0`. Both paths parse to false and emit no diagnostic logs.
The three-sample medians were 112.02 and 115.77 microseconds respectively;
because the executed path is identical and clocks/order were not paired, this
difference is treated as environmental noise, not instrumentation overhead.
Raw evidence is in `work/results/v3-instrumentation-off-ab/`.

## K1 hypothesis

K0 uses the one-subgroup reduction. K1 exposes the already compiled
four-subgroup hybrid reduction through the real selector. No weights,
quantized values or arithmetic were changed.

ABBA results (six samples per mode, medians):

| Shape | K0 subgroup us | K1 large us | Delta |
|---|---:|---:|---:|
| 10752x2048, N=2 | 59.42 | 88.34 | +48.67% |
| 2048x10752, N=2 | 1793.29 | 1735.85 | -3.20% |
| 2048x2048, N=2 | 420.68 | 367.82 | -12.57% |
| 6144x2048, N=2 | 74.12 | 103.06 | +39.04% |
| 10752x2048, N=4 | 1721.78 | 1690.60 | -1.81% |
| 2048x10752, N=4 | 1786.80 | 1768.51 | -1.02% |
| 2048x2048, N=4 | 371.43 | 352.54 | -5.08% |
| 6144x2048, N=4 | 992.68 | 970.52 | -2.23% |

This rejects an N-only selector. The final experimental selector uses the
hybrid variant only for all observed N=4 shapes and M=2048 at N=2. Selection
proof shows gate/up N=2 remains subgroup while down N=2 and N=4 use hybrid.

Both variants pass CPU-reference checks for gate/up and down at N=2/4 (4/4
each). These are operation checks, not model-quality evaluation.

## Server validation

Stable runtime R0 was held constant. Workload: fixed 128/64, b4096/u128,
KV q8, cache disabled, three measured batches after one warmup.

| Candidate | C1 tok/s | C4 tok/s | C4 TTFT p95 ms | C4 E2E p95 ms | Max global VRAM GiB |
|---|---:|---:|---:|---:|---:|
| K0 subgroup | 80.45 | 173.37 | 481.07 | 1510.77 | 6.207 |
| K1 shape selector | 80.04 | 164.20 | 428.56 | 1702.21 | 6.207 |

All batches are retained. K1 C4 is -5.29% on the aggregate. Memory clock
samples include 96/675/1000 MHz for K0 and 96/541/675/1000 MHz for K1; this
campaign therefore cannot attribute the whole delta to the selector. The
candidate nevertheless fails the required server-level confirmation.

## Decision

**REJECT** for production. The shape-specific micro signal is real enough to
guide a future timestamped shader benchmark, but it did not make this server
faster under the controlled workload. The environment variable remains an
experimental switch; production default is unchanged (`auto`).

Raw evidence:

- `work/results/v3-kernel-micro-paired-r3/`
- `work/results/v3-kernel-micro-conv/`
- `work/results/v3-kernel-correctness/`
- `work/results/v3-kernel-selector-proof/`
- `work/results/v3-kernel-server-k0-subgroup/`
- `work/results/v3-kernel-server-k1-shape/`

Reproduce:

```bash
REPETITIONS=3 work/scripts/run_rocmfpx_kernel_microbench.sh
```
