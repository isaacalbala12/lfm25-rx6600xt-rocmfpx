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

**The registration blocker is solved, and it was our error.** The cases were
added inside `make_test_cases_eval()`, but `MODE_PERF` builds its list from
`make_test_cases_perf()`, so the filter never saw them. The external review
identified this exactly. Moved, and the cases now appear.

The first table, two runs, minimum per cell:

| Shape | R | µs | µs/R |
| --- | ---: | ---: | ---: |
| down `m=2048 k=10752` | 1 | 480,24 | 480,24 |
| down | 2 | 6.109,30 | 3.054,65 |
| down | 3 | 8.323,79 | 2.774,60 |
| down | 6 | 18.370,44 | 3.061,74 |
| gate/up `m=10752 k=2048` | 1 | 404,41 | 404,41 |
| gate/up | 2 | 791,33 | 395,67 |
| gate/up | 3 | 1.192,18 | 397,39 |
| gate/up | 6 | 26.626,46 | 4.437,74 |

**These numbers are not usable and the table is published only to show why.**
gate/up scales exactly linearly for R=1,2,3 and then jumps 22x at R=6; down
jumps 12,7x at R=2. Those jumps are the slow clock state, not a scaling law.

Two further defects, both flagged by the review before we hit them: the
repetition count in `eval_perf()` varies with FLOPs (so R=1,2,3,6 get 18, 9, 6
and 3 repetitions), and `eval_perf()` times `ggml_backend_graph_compute()` with a
wall clock rather than the MMQ's GPU interval. And our own mode column is wrong
in the table above: A's batch is `bs[0]*bs[1]`, so the `bs={1,r}` rows are
A-independent, not A-shared.

The reviewer's other condition also stands: `init_tensor_uniform()` seeds from
`random_device`, so identical *content* across replicas is not guaranteed by
construction; the bytes have to be replicated explicitly and hashed per plane.

## Status

- **Established:** the isolated gap is 1,19x. The graph-level 1,35--1,44x is
  partly an artifact of how the graph is measured.
- **Not established:** whether the residual gap is insufficient parallelism. The
  experiment designed to answer it is set up but not running.
- **Still open:** the ub=256 elementwise collapse, whose cause is unknown and
  which is now the more interesting anomaly of the two, because it is an order of
  magnitude larger.
