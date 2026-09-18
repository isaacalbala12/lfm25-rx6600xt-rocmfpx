# Prefill 8K profile V6

V5 remains the causal operation profile: gate/up 32.79%, down 23.28%, Flash
Attention 23.11%, short-conv 7.52% and 2048x2048 4.05%. V6 separated exact
operation ABBA from service timing and did not reuse an invasive trace as wall
performance.

Configuration: ROCmFPXVulkan0, FP4_FAST (~4.277 artifact BPW), q8/q8 KV,
chunk128, C=4, context 34816 global/8704 per slot, 8192 input + 256 fixed output
per request, cache reuse disabled.

| Pair | Control input tok/s | Selective BK3 | Delta |
| --- | ---: | ---: | ---: |
| 0 | 1526.07 | 1575.87 | +3.263% |
| 1 | 1553.19 | 1574.42 | +1.367% |
| 2 | 1559.46 | 1571.97 | +0.802% |

Paired medians: input/output +1.367%, TTFT p95 -1.240%, E2E p95 -1.347%.
Outputs matched 3/3 and observed global VRAM was 2.079--2.106 GiB for both
arms. This is below 1668 input tok/s and is **STAGE**, not production.

