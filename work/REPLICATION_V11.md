# V11: the down gap measured in isolation is 1,19x, not 1,5x

## What the microbenchmark harness gives

`test-backend-ops` (ggml's own backend benchmark, driven by
`work/scripts/run_rocmfpx_kernel_microbench.sh`) can time our exact shapes
against the ROCmFPX backend with everything else stripped away:

```
test-backend-ops perf -b ROCmFPXVulkan0 -o MUL_MAT \
  -p 'type_a=q4_0_rocmfp4_fast.*n=128.*'
```

One clean run, same binary, same tile, same shader, same input type:

| Shape | µs/run | GFLOP/run | TFLOPS |
| --- | ---: | ---: | ---: |
| gate/up `m=10752 n=128 k=2048` | 404,57 | 5,64 | **13,93** |
| down `m=2048 n=128 k=10752` | 482,78 | 5,64 | **11,68** |

**The gap is 1,19x.** In the full prefill graph the same two shapes appear to
differ by 1,44x (with BK3) or 1,35x (with BK4). So most of the gap we have been
chasing is **context, not shape**: in the real graph, `down` runs after other
operations with a different cache and dependency state, and the Vulkan timing
logger attributes the intervals between dispatches.

This does not dissolve the anomaly — 1,19x is still a real asymmetry for
identical MACs and bytes — but it cuts its size by more than half and it moves
the question from "why is this shape 44% worse" to "why does it lose another 15%
in context".

It also validates the reviewer's methodological point: the graph-level
attribution we had been reasoning from was not measuring the kernel.

## The replication experiment: set up, not yet yielding

The reviewer's discriminator — the same GEMM replicated along the batch
dimension with M, N, K, tile and shader fixed — is expressible in this harness
without writing new code. `test_mul_mat` takes `bs` and `nr`, and:

- `bs={1,1}, nr={1,R}` gives A shared across replicas and B independent;
- `bs={1,R}, nr={1,1}` gives both operands independent;

which are two of the reviewer's three configurations. The third, both operands
shared, is not expressible as a ggml op because the output batch would have no
distinct input. In both expressible cases the content is identical across
replicas, so the only variable is addressing, which is what the review asked for.

Cases for R = 1, 2, 3, 6 were added to `tests/test-backend-ops.cpp` at line 8580
and the binary rebuilds, **but the added cases are not appearing in the run
output**: a filter that should match all of them returns only the two original
`bs=[1,1],nr=[1,1]` cases. The registration path is not yet understood and the
sweep has not produced a table.

A second problem showed up while trying: three consecutive runs of the same
command gave 404,57 µs and 4.522,17 µs for the same case, an eleven-fold
difference. The harness needs the clock guard and interleaving before any of its
numbers can be used, exactly like every other measurement in this repository.

## Status

- **Established:** the isolated gap is 1,19x. The graph-level 1,35--1,44x is
  partly an artifact of how the graph is measured.
- **Not established:** whether the residual gap is insufficient parallelism. The
  experiment designed to answer it is set up but not running.
- **Still open:** the ub=256 elementwise collapse, whose cause is unknown and
  which is now the more interesting anomaly of the two, because it is an order of
  magnitude larger.
