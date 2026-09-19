# Kernel microbenchmark V8

## Exact problem

ROCmFPXVulkan0, FP4_FAST x Q8_1, `M=2048,K=10752,N=128`, pipeline
`matmul_rocmfp4_fast_q8_1_m`, BM64/BN64/BK32/BK_STEP4. Every candidate passed
CPU-reference correctness and exact route proof. Measurements are logger-free,
five-pair ABBA, and use one same-binary control.

| Candidate | Paired median delta | 95% bootstrap interval | Decision |
|---|---:|---:|---|
| B-first | -0.614% | [-1.313%, +0.025%] | REJECT; SPIR-V identical |
| stride hoist | -0.332% | [-1.366%, +0.025%] | REJECT; SPIR-V identical |
| no-tail | -0.945% | [-1.407%, -0.369%] | COMPOSABLE signal |
| no-split | +0.041% | [-0.227%, +0.759%] | REJECT |
| no-output-bounds | -0.249% | [-0.562%, +0.398%] | REJECT |
| exact shape | **-2.161%** | **[-2.380%, -1.194%]** | best; ARCHIVE COMPOSABLE |
| no-split + no-bounds | -0.400% | [-1.701%, +0.205%] | REJECT |
| no-tail + no-bounds | -1.615% | [-1.670%, -0.258%] | COMPOSABLE, below best |
| no-tail + no-split | -0.821% | [-1.422%, -0.057%] | below threshold |
| Q8 group4 | -1.793% | [-2.337%, -0.194%] | COMPOSABLE, below server gate |
| exact + Q8 group4 | -1.710% | [-2.554%, -1.295%] | non-additive; below best |

`down-exact` reduces SPIR-V instructions by 16.40%, chiefly access chains,
integer additions, labels/stores and conditional control. The much smaller
2.16% latency response shows that static instruction removal is useful but not
the dominant local limit. Its approximate global ceiling is 23.28% * 2.16% =
0.50%, so it was not sent to the server.

Raw results and static comparisons are in `work/results/v8-down-search/`.

## Gate/up BK3 exact-shape campaign

Exact problem: FP4_FAST x Q8_1, `M=10752,K=2048,N=128`, with production BK3
as the same-binary control. Five formal candidates used five ABBA pairs each.

| Candidate | Paired median delta | 95% bootstrap interval | Static instruction delta | Decision |
|---|---:|---:|---:|---|
| no split-K | -0.324% | [-0.636%, +0.593%] | -1.69% | REJECT |
| no output bounds | -0.734% | [-1.700%, -0.433%] | -1.61% | COMPOSABLE signal |
| no split + no bounds | -1.153% | [-1.523%, -0.716%] | -3.47% | below server leverage |
| compile-time K=2048 | -0.143% | [-0.593%, +1.182%] | -1.86% | REJECT |
| exact M/N/K shape | **-1.316%** | **[-1.447%, -0.420%]** | **-3.64%** | ARCHIVE COMPOSABLE |

The exact-shape candidate removes seven integer additions, five access chains,
five loads, four integer multiplies, three branches and two conditional
branches from the static SPIR-V module. The latency response remains only
1.32%; at the 32.79% profile share its approximate whole-profile ceiling is
0.43%. It therefore did not enter a server run.
