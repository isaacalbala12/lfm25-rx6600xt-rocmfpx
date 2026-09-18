# V8 down N128 static analysis

## Control and route

- Main HEAD at capture: `cd73704` (functional baseline inherited from `049eeaa`).
- ROCmFPX source: `15a5120`.
- Loaded plugin SHA-256: `5b3b36d54c45e7b8f6c51e654dcca96726e8fe02f4418b4e43cea0a593edc763`.
- SPIR-V module SHA-256: `0f185d8bb4590aae4d1ea4b2c8a7cf5a684d4433a023a1dda670e3997b66addf`.
- Shape: `M=2048, K=10752, N=128`, FP4_FAST x Q8_1.
- Selected pipeline: `matmul_rocmfp4_fast_q8_1_m`.
- Dispatch: `32 x 2 x 1` workgroups; workgroup size 128; subgroup size 32.
- Geometry: BM64, BN64, BK32, BK_STEP4.

The route was captured separately with `RADV_DEBUG=shaders` and the existing
selection logger. It is not a throughput run. The raw evidence is in
`work/results/v8-down-static-radv/`.

## SPIR-V structure

The exact non-fp32 module selected by the fp16-capable device contains:

- 23,224 bytes / 5,806 words;
- 1,329 SPIR-V instructions;
- 179 `OpAccessChain`;
- 130 `OpIAdd`, 56 `OpIMul`, and 19 `OpUDiv`;
- 115 `OpLoad`, 67 `OpStore`;
- 3 control barriers.

These are static module counts. The module is shared by multiple runtime shapes,
so they do not represent dynamic counts for one down dispatch.

## RADV/ACO static output

For the exact MMQ shader selected by the down dispatch:

- shared memory reported by RADV: 18,960 bytes;
- static machine instructions: 2,754;
- barriers: 3;
- buffer loads/stores: 16 / 32;
- LDS reads/writes: 264 / 35;
- static integer add/multiply-family instructions: 149 / 85;
- dot4-family instructions: 1,024;
- highest numbered VGPR observed: `v159`;
- highest numbered SGPR observed: `s56`.

The register maxima are conservative observations from disassembly, not
allocator-reported register counts. RADV did not print occupancy, spill count,
or an explicit allocated VGPR/SGPR summary. Therefore this campaign does **not**
claim occupancy or spill behavior from these data. The `p_init_scratch` ACO
pseudo-op is not treated as proof of spills.

## Mechanisms selected for the first bank

1. **Exact-K no-tail specialization.** `10752` is divisible by
   `BK * BK_STEP = 128`. The generic shader nevertheless carries tail-validity
   decisions in both A and B staging. A down-only pipeline can remove those
   conditions without changing any value. Expected affected resource: branch,
   compare, and address/control overhead across 84 K-loop iterations. This is
   the highest-confidence structural candidate.
2. **Explicit stride-block hoisting.** Compute `stride_a / BK` and
   `stride_b / BK` once before the K loop and reuse them. Static SPIR-V comparison
   is a pre-gate: if the compiler already performs the transformation and the
   generated module is equivalent, the candidate is REJECT without GPU time.
3. **B-before-A staging.** Stage the smaller Q8-side work before FP4 weights to
   test whether load/compute issue ordering shortens the long-K path without
   adding LDS or changing geometry. Resource risk: no intended extra storage,
   but register lifetime may worsen; correctness and exact latency decide.
4. **Incremental row/block pointer progression.** Hoist lane-invariant row bases
   and advance block indices instead of reconstructing them. This follows only
   if the stride-hoist candidate changes generated code or disassembly confirms
   remaining repeated address chains.
5. **LDS layout change.** Deferred until the first three candidates report
   static deltas. The control already uses 18,960 bytes; padding or double
   buffering would increase a scarce resource without current bank-conflict
   evidence.

The first three are orthogonal hypotheses, not a parameter sweep. BM64, BN64,
BK32, BK_STEP4 and the arithmetic remain fixed.

## Limitations

- No PMC was used.
- The RADV diagnostic run perturbs execution and is not a service benchmark.
- Static instruction counts do not estimate dynamic latency.
- Candidate resource comparisons must be generated from the same binary/toolchain.

