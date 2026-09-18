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

## K3: two-subgroup gate/up N=4 reduction — REJECT

- Source checkpoint: `a62c523746bac882f2f38c5a443df2e78b3f7f70`.
- Candidate: a newly compiled 64-thread/two-wave hybrid reduction selected
  only for M=10752, K=2048, N=4 by `gateup-n4-2sg`.
- Correctness: exact operation passes the CPU-reference test; selection proof
  keeps all adjacent shapes on the one-subgroup control.
- Protocol: ten ABBA pairs, 20 samples per arm, loggers absent.

| Arm | Median us | Range us |
| --- | ---: | ---: |
| subgroup | 61.095 | 60.50--61.80 |
| gateup-n4-2sg | 83.230 | 82.46--84.53 |

Delta: **+36.23% latency** (regression). Together K2 and K3 establish a
monotonic loss for this exact hot shape as workgroup size grows from one to
two to four wave32 subgroups. Decision: **REJECT** and close subgroup-count
tuning for gate/up N=4. A future gate/up candidate must change the per-wave
algorithm, packing, or reuse rather than merely add cooperating waves.

Evidence:

- `work/results/v4-kernel-gateup-2sg-micro-abba10/`
- `work/results/v4-kernel-gateup-2sg-correctness/`
- `work/results/v4-kernel-gateup-2sg-selector-proof/`

## K4: 6144x2048,N=1 rows4 — REJECT

- Source checkpoint: `fee88e32dd01b22e594206397e1356d953a918c4`.
- Hypothesis: reduce FP4_FAST accumulators from eight to four rows per wave,
  improving register pressure and exposing twice as many workgroups while
  retaining BLOCK_SIZE=32.
- Selector: `conv-n1-rows4` changes only M=6144, K=2048, N=1; all neighboring
  shapes stay on the existing subgroup pipeline.
- Protocol: ten ABBA pairs, 20 samples per arm, loggers absent.

| Arm | Median us | Range us |
| --- | ---: | ---: |
| rows8 control | 367.390 | 358.60--379.67 |
| rows4 candidate | 363.740 | 353.48--375.27 |

The raw median delta is -0.99%, but the median pair delta is only -0.40% and
the deterministic pair-bootstrap 95% interval is [-1.43%, +0.19%]. The
standard correctness corpus has no exact 6144x2048,N=1 case (0/0 tests), so no
correctness claim is made from that invocation.

Decision: **REJECT**. The signal is inconclusive and its optimistic global
ceiling is roughly 0.2% because the shape is 20.72% of profiled C4 MMV. That
does not justify another pipeline plus unresolved exact-shape validation.

Evidence:

- `work/results/v4-kernel-conv-n1-rows4-micro-abba10/`
- `work/results/v4-kernel-conv-n1-rows4-selector-proof/`
- `work/results/v4-kernel-conv-n1-rows4-correctness/` (documents 0/0)
