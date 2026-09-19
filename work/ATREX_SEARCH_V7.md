# Atrex-style Vulkan search V7

## Selective BK3 promotion

Selective gate/up BK3 is **KEEP production** for FP4_FAST prefill at
`M=10752, K=2048, N>64`. Down and decode remain on BK4/current pipelines.

- Profile B, ten paired C4 8K runs: **+1.1641%** aggregate throughput,
  paired bootstrap 95% CI **[+0.8093%, +1.3767%]**; exact outputs 10/10.
- 3D+1P, ten pairs: retention **+1.5442%**, resident ITL p95 **-1.4472%**
  (89.211 -> 87.865 ms), new-user TTFT **-1.6769%**.
- Resident C4 8K: candidate 261.99--262.65 tok/s, all above the 260 tok/s
  guardrail; paired median -0.1467%, CI [-0.155%, +2.847%]. Exact outputs 3/3.
- Service-EOS reserved corpus: 7/7 VALID in both arms and exact text,
  finish reason and token count.
- Exact operation tests pass for N=65/96/112/120/126/127/128. Every shape
  improves locally, from -3.36% to -4.77% latency.
- Service traces observed BK3 at N=112/120/126/128. N=12/16 remained on the
  small control pipeline; resident decode does not enter BK3.

The functional production change is `283a889`; the final ROCmFPX checkpoint is
`15a5120`, which adds explicit reverts of the two rejected search-bank
candidates. BK3 is enabled by default and
`GGML_VK_ROCMFP4_FAST_MMQ_BK3_GATEUP=0` provides a same-binary BK4 control.
The rebuilt backend SHA-256 is
`5b3b36d54c45e7b8f6c51e654dcca96726e8fe02f4418b4e43cea0a593edc763`.
Correctness and selector proof are under
`work/results/v7-bk3-production-promotion/`. The first attempt omitted plugin
loading and is retained as INVALID under the explicitly named sibling folder.

## Static evidence

The BK3 SPIR-V is 20,460 bytes versus 23,152 for BK4 (-11.63%) and contains
11.25% fewer SPIR-V instructions. The largest structural reductions are in
address chains, integer additions, loads, stores and composite extraction.
This supports lower loop/address overhead as the mechanism, but is not RDNA2
ISA evidence: VGPR, SGPR, LDS, spills and occupancy remain unmeasured.

## Next search mechanism

BK_STEP is closed. The next candidate bank must keep BK3 as incumbent and test
orthogonal mechanisms in one binary: K-loop scheduling, safe prefetch/load
reordering, LDS organization and Q8/FP4 consumption order. The evaluator
remains the authority and candidates may not alter its correctness, route or
measurement gates.

## Candidate 01: explicit BK3 compute-loop unroll

The first same-binary orthogonal candidate added an opt-in shader with an
explicit unroll directive on the three-step compute loop. Correctness and route
proof passed. Five ABBA pairs measured 412.735 -> 411.595 us, **-0.159%**,
bootstrap 95% CI **[-0.652%, +0.107%]**. This is below the local promotion
threshold and crosses zero: **REJECT_MICRO**. No server run was justified.

The experiment also exercised the new build-once path. A supervisor smoke test
found two orchestration defects (self-detection as an inference process and a
relative result-path failure). Both failed attempts are retained as INVALID;
the fixes preserve exact foreign-process rejection, add explicit INVALID-only
retry, use manifest IDs rather than filenames, and deduplicate semantically
equivalent mutations by SHA-256 fingerprint. Three unit tests cover the queue.

Static comparison explains the null result: control and explicit-unroll SPIR-V
have exactly the same byte length, instruction count and opcode histogram.
The compiler had already produced the same structural loop form, so this is a
closed mechanism rather than evidence that loop scheduling is unimportant.

The evaluator now accepts a separately pinned, immutable problem definition.
Gate/up and down specify their own M/K/N and parsers outside candidate
manifests; a candidate cannot alter the benchmark shape while being evaluated.

## Down campaign start

The immutable down problem is `M=2048,K=10752,N=128`. A five-pair identity
run places the operation around 510 us, but its nominal arm delta (-0.375%) is
measurement drift, not an optimization: both arms execute the same pipeline.

Candidate `down-bm32-bn64` halved BM and WMITER while retaining BN64, BK32 and
BK_STEP4. It passed exact correctness and route proof but regressed 510.905 ->
621.560 us: **+21.802%**, bootstrap 95% CI **[+20.420%, +23.029%]**.
**REJECT_MICRO**. The loss of row-tile reuse dominates any lower LDS/register
footprint. Future down candidates must retain BM64 and target K-load scheduling
or address/scale consumption instead of reducing the row tile.

The final backend was rebuilt after removing both rejected opt-in shaders. Its
hash returned exactly to the promoted BK3 artifact
`5b3b36d54c45e7b8f6c51e654dcca96726e8fe02f4418b4e43cea0a593edc763`,
and route proof again selected `matmul_rocmfp4_fast_q8_1_bk3_m` by default.
