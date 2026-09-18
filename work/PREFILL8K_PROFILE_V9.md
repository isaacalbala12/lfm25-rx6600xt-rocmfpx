# Prefill 8K profile V9

V9 did not rerun simultaneous Profile B because no kernel passed the micro
promotion gate. The authoritative production result remains selective BK3:
ten paired Profile-B runs improved its contemporary BK4 control by 1.1641%,
with 95% CI [+0.8093%, +1.3767%]. Do not turn that relative result into a new
absolute throughput figure without rerunning Profile B.

The new contribution is a mixed-workload profile at the actual interactive
shape. A 128-token scheduler allocation becomes a prefill graph with `N=127`
plus a separate decode graph with `N=4`. Of the profiled prefill graph:

- gate/up: 35.34%;
- down: 26.64%;
- Flash Attention: 13.78%;
- short-conv: 8.66%;
- 2048 projections: 6.42%;
- other: 9.15%.

Gate/up plus down are 61.98% of the prefill graph and 51.75% of the complete
decode+prefill profiled pair. They remain the only established kernel target
with enough combined leverage to move mixed latency materially.

The diagnostic logger fences every graph. Its 91.501 ms median must not replace
the uninstrumented 78.257 ms mixed-batch median.
