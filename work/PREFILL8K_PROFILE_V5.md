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
