# Concurrency profile V9

## Production control

- Runtime R0, fixed `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128`.
- ROCmFPXVulkan0, FP4_FAST weights, q8/q8 KV, selective gate/up BK3.
- Four slots have at least 8192 effective context tokens each.
- The uninstrumented run is the service result. The Vulkan timing run fences
  graphs and is diagnostic only.

## Contemporary 3D+1P timeline

`work/results/v9-mixed-timeline-production` is valid and uncached. Three users
were resident at 8K and decoding while a fourth submitted an uncached 8K
prompt.

| Metric | Result |
|---|---:|
| C3 resident aggregate before prefill | 236.261 tok/s |
| C3 aggregate during prefill | 38.542 tok/s |
| Decode retention | 16.313% |
| Baseline ITL p95 | 13.840 ms |
| Resident ITL p95 during prefill | 88.471 ms |
| New-user TTFT | 5137.25 ms |
| Full mixed batch, median | 78.257 ms |
| Full mixed batch, p95 | 86.479 ms |
| Decode-only C3 batch, median | 11.572 ms |

There were 63 full batches with 128 prompt tokens and three decode tokens.
This reproduces the V5/V7 conclusion with the current production binary: the
interactive pause is the work in a mixed batch, not a hidden CPU scheduler gap.

## Diagnostic split by graph

`work/results/v9-mixed-operation-profile` enabled the Vulkan timing logger and
is intentionally excluded from service throughput claims. All 63 selected
mixed batches contain two graphs. Graph index 0 is the decode graph and graph
index 1 is the prefill graph, as demonstrated by their shapes.

| Graph | Profiled GPU time | Share of both graphs |
|---|---:|---:|
| Decode (`N=4`, KV around 8448) | 820.295 ms | 16.51% |
| Prefill (`N=127`) | 4147.597 ms | 83.49% |

Within the prefill graph:

| Family | Share within prefill | Share of full profiled pair |
|---|---:|---:|
| gate/up 10752x2048 | 35.34% | 29.50% |
| down 2048x10752 | 26.64% | 22.24% |
| Flash Attention | 13.78% | 11.51% |
| short-conv | 8.66% | 7.23% |
| 2048 projections | 6.42% | 5.36% |
| other | 9.15% | 7.64% |

The profiler inflates wall time to 91.501 ms median and 111.589 ms p95, so the
percentages are routing/prioritization evidence, not a latency prediction.

## Temporal EWMA scheduler experiment

An opt-in controller estimated mixed-batch milliseconds per prompt token and
selected a chunk between 64 and 128 tokens. It is disabled by default.

At a 65 ms target, three paired runs produced:

| Metric | chunk128 | EWMA65 | Paired delta |
|---|---:|---:|---:|
| Retention | 16.238% | 18.952% | +16.61% |
| Resident ITL p95 | 87.085 ms | 74.678 ms | -14.63% |
| New-user TTFT | 5150.07 ms | 7583.40 ms | +47.97% |

The diagnostic run exposed a shape cliff: chunks 64/65 were about 59.45 ms,
while 66/67 were about 69--71 ms. Startup at 128 and tail batches also pollute
the ratio EWMA. A 68 ms target was stopped after one pair: ITL improved 13.12%
but TTFT regressed 44.64%.

Decision: **REJECT production** for the ratio controller at 65 and 68 ms. It
proves the expected latency/TTFT trade-off but does not improve the Pareto front
enough: it misses the <=70 ms ITL goal and the <=5.5 s TTFT guardrail. Fixed
chunk128 remains production.

## Product conclusion

Scheduling alone cannot reach the product target. Even an aggressive ~64-token
budget leaves resident ITL around 75 ms while adding roughly 2.4 seconds of
TTFT. The next material win must reduce prefill graph cost, especially gate/up
and down, rather than split the same work into ever smaller chunks.
