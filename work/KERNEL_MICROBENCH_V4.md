# V4 exact-plugin kernel microbenchmarks

## Measurement correction

`ggml_vk_env_enabled()` enables a logger when its variable is present. The V3
microbenchmark exported `GGML_VK_PERF_LOGGER=0` and
`GGML_VK_SELECTION_LOGGER=0`; both loggers were therefore enabled. The old
1.69--1.72 ms gate/up measurements include the fenced profiler path and are
not valid hot-pipeline latency measurements. This does not overturn the K1
server rejection, which was measured separately, but it removes the apparent
microbenchmark win that motivated a gate/up-only selector.

The V4 runner now unsets all Vulkan logger variables. Profiling and service
benchmarking remain separate experiments.

## K2: four-subgroup gate/up N=4 selector — REJECT

- Source checkpoint: `3da7c18050e3eef0033c9faef8d154b452434849`.
- Plugin SHA-256:
  `ade1b213dbe9145e12c1dae2ff613309376e8244c4521233630f980c5a763aad`.
- Exact shape: FP4_FAST x Q8_1, M=10752, K=2048, N=4.
- Control: one-subgroup reduction.
- Candidate: existing four-subgroup hybrid reduction, selected only for the
  exact gate/up shape by `GGML_VK_ROCMFP4_FAST_DMMV_WG=gateup-n4`.
- Protocol: ten ABBA pairs, 20 samples per arm, hot buffers, exact plugin
  selector and pipeline, loggers absent.

| Arm | Median us | Range us |
| --- | ---: | ---: |
| subgroup | 60.840 | 60.17--61.63 |
| gateup-n4 | 110.655 | 108.89--112.10 |

Delta: **+81.88% latency** (regression). The exact operation passes the
CPU-reference correctness test. Selection logging proves that only
10752x2048,N=4 selects `large_hybrid`; adjacent N=2 and M=2048/6144 shapes
stay on `subgroup`.

Decision: **REJECT**. The signal is sufficiently large that a server run would
waste GPU time and cannot reverse the causal result. The next small-N variant
must change the geometry to two subgroups rather than reuse the rejected
four-subgroup reduction.

Evidence:

- `work/results/v4-kernel-gateup-n4-micro-abba10/`
- `work/results/v4-kernel-gateup-n4-correctness/`
- `work/results/v4-kernel-gateup-selector-proof/`

