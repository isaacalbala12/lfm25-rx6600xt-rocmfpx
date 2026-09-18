# Prefill 8K profile V5

With three resident decoders, each 128-token mixed prompt batch occupies 79.961
ms median and 87.554 ms p95, versus 11.561 ms for decode-only. Scheduler-only
changes cannot meet 50-ms ITL while retaining chunk128 unless prefill compute is
accelerated.

The contemporary baseline remains FPX 1562 input tok/s versus upstream Q4_0
1668 tok/s (-6.3%). A separate fenced operation run is stored at
`work/results/v5-prefill8k-operation-profile`; its 1734 input tok/s is profiler
perturbed and is not a service result.

For the last complete N=128 tile at effective 8192 context, the grouped Vulkan
time is 71.677 ms:

| Family | grouped GPU time | share |
|---|---:|---:|
| gate/up 10752x2048 | 23.500 ms | 32.79% |
| down 2048x10752 | 16.684 ms | 23.28% |
| Flash Attention (8 layers) | 16.566 ms | 23.11% |
| short-conv 6144x2048, with/without copy | 5.390 ms | 7.52% |
| 2048x2048 | 2.904 ms | 4.05% |

This is the first V5 causal ordering. Gate/up has the largest single leverage;
down is second. Flash Attention now exceeds the campaign's 5–10% trigger and
must remain open for 8K-specific tuning. V3's 2048-token shares are not reused.

## Gate-only BK_STEP=2 candidate

The selective pipeline at ROCmFPX `24376c3` retains BK_STEP=4 for down and
decode, and routes only gate/up-like `10752x2048,N>64` through BK_STEP=2.
Microbenchmark gate/up improves 2.601% paired while the down guardrail is flat.

With chunk128 enabled, a three-repetition simultaneous 8K C4 exploration moves
aggregate input throughput from 1538.70 to 1555.19 tok/s (+1.072%) and TTFT p95
from 17807.29 to 17573.98 ms (-1.31%). This contemporary control is slower than
the historical 1562 tok/s baseline, so the candidate is compared only against
its paired-build control and remains **STAGE**, not a new universal baseline.
