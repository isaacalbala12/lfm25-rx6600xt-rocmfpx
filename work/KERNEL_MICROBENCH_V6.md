# Kernel microbenchmark V6

Exact plugin path: FP4_FAST x Q8_1 medium MMQ in
`extensions/rocmfpx-vulkan/backend`, `M=10752,K=2048,N=128`.

The bounded BK-step search found BK3 as the only winner. BK1/BK5/BK8 regressed
4.90%/18.05%/84.24%. Global BK3 improved gate/up about 4% at N=120/128/129 but
regressed down 2.12%, so it was rejected.

The selective implementation adds an opt-in SPIR-V only for FP4_FAST x Q8_1
gate/up (`M=10752,K=2048,N>64`). It preserves codes, scales, RHS quantization,
down and decode.

- control: 428.975 us;
- selective BK3: 412.940 us;
- paired delta: **-3.859%**;
- 95% interval: **[-3.993%, -3.521%]**;
- candidate pipeline: `matmul_rocmfp4_fast_q8_1_bk3_m`;
- candidate backend: `b59203b2...f5982`;
- CPU-reference correctness: PASS.

At the 32.79% gate/up profile share, the isolated wall ceiling is about 1.27%.
The three-pair server median of +1.367% is consistent in scale but remains
exploratory. Selective BK3 is **STAGE**; global BK3 is **REJECT**.

