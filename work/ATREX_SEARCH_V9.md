# Atrex-style exact Vulkan search V9

## Campaign

V9 reprofiled production before proposing another gate/up mutation. The exact
evaluator remained immutable: same-binary control, CPU reference, route proof,
artifact identity, logger-free ABBA, bootstrap and fail-closed rollback.

One orthogonal candidate was justified by the new gate/up share:

`gateup-bk3-bpair`

- parent: production selective BK3;
- mechanism: prefetch both TN=2 Q8 columns before accumulation;
- intended resource: Q8 load scheduling / ILP;
- risk: register/private-memory pressure;
- expected leverage: a 2.54% local gain would reach 0.75% globally.

## Result

All hard gates passed, but latency regressed 0.767% and the confidence interval
crossed zero. Static SPIR-V grew by 4.15% instructions and 4.56% bytes, with
more access chains, loads and stores. The candidate is **REJECT_MICRO** and the
queue stops after one candidate because the mechanism disproved itself.

This is intentional disciplined stopping, not an incomplete random sweep.
V8 already converged generic bounds/address simplification below 0.5% global
leverage. V9 shows naive register-array prefetch does not create useful ILP.

## Search memory update

Scope the rejection narrowly: prefetching both TN=2 Q8 columns into separate
array caches in the current GLSL structure. Do not mark all software pipelining
or all Q8 consumption changes taboo.

## Next search family

Do not spend another round on minor control-flow variants. Build a prototype
that changes data movement structurally:

1. choose gate/up or down, not both;
2. prepack one real hot tensor reversibly, preserving FP4 codes and scales;
3. arrange `[K-block][M-tile]` data in the lane-consumption order used by
   wave32;
4. account for extra VRAM and one-time packing;
5. benchmark N=127 and N=128 plus a representative tail;
6. abandon before server testing unless local gain clears the contemporary
   leverage gate.

This family directly targets the residual address/load cost that BK3's smaller
SPIR-V and V8's exact-shape results identify, while being orthogonal to the
closed BK_STEP, subgroup, arithmetic-unpack and bounds-removal families.
