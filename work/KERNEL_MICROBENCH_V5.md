# Kernel microbenchmark V5

No shader was promoted. The proposed 6144x2048 N=4 route was rejected before
implementation because C4 is already represented by `ne[2]=4` in one per-layer
dispatch. The measured new scheduler candidate was chunk96: 82.677-ms ITL p95
and 16.627% retention, but 6646-ms TTFT; **REJECT**.

The next kernel experiment is an 8K-prefill gate/up or down tile selected by a
fresh fenced profile. It must use the plugin backend and preserve FP4_FAST
values.

