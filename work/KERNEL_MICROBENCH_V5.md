# Kernel microbenchmark V5

No shader was promoted. The proposed 6144x2048 N=4 route was rejected before
implementation because C4 is already represented by `ne[2]=4` in one per-layer
dispatch. The measured new scheduler candidate was chunk96: 82.677-ms ITL p95
and 16.627% retention, but 6646-ms TTFT; **REJECT**.

The fenced 8K profile selects gate/up first: 23.500 ms per full N=128 tile,
32.79% of grouped GPU time. Down is 16.684 ms (23.28%), and Flash Attention is
16.566 ms (23.11%). The next variant must alter the gate/up in-wave MMQ tile or
FP4 unpack/load path, not subgroup count. It must use the plugin backend and
preserve FP4_FAST values.
