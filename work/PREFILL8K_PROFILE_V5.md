# Prefill 8K profile V5

With three resident decoders, each 128-token mixed prompt batch occupies 79.961
ms median and 87.554 ms p95, versus 11.561 ms for decode-only. Scheduler-only
changes cannot meet 50-ms ITL while retaining chunk128 unless prefill compute is
accelerated.

The contemporary baseline remains FPX 1562 input tok/s versus upstream Q4_0
1668 tok/s (-6.3%). A fresh operation-timestamp profile was deliberately not
mixed with this wall benchmark. Next, fence an 8192-token prefill and separate
10752x2048 gate/up and 2048x10752 down at actual tiles. V3's 2048-token shares
must not be reused as 8K attribution.

