# Concurrency profile V6 checkpoint

Production remains fixed chunk128, runtime R0, ROCmFPXVulkan0 FP4_FAST, q8/q8
KV and >=8192 tokens per slot at C=4. The restored backend after every V6
experiment is `40f6b9c...b25b40`. The V4 resident baseline remains 265.79
tok/s with ITL p95 15.33 ms; V6 makes no new resident claim yet.

No temporal scheduler candidate was benchmarked in V6. The measured timeline
already shows the ~89 ms pause is dominated by a 79.96--87.55 ms mixed
128-token GPU batch rather than a hidden scheduler gap. Chunk96 worsened TTFT
and chunk128 passed service-EOS quality. The evidence-backed decision is to
retain chunk128 and reduce mixed-batch compute first. EWMA scheduling is
deferred until selective BK3 has a 3D+1P result, avoiding a confounded test.

Selective BK3 is **STAGE** from Profile B (+1.367% service throughput, -1.240%
TTFT p95, identical output 3/3). It has no 3D+1P, resident C4 or fairness claim
and is not installed in production.

