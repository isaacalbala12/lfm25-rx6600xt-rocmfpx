# V10 handoff: FP4 layout search and archived composition

## Production state

Production is unchanged: ROCmFPXVulkan0, FP4_FAST, q8/q8 KV, runtime R0,
fixed chunk128 and selective gate/up BK3 for four users with at least 8192
effective tokens per slot. R1 remains STAGE. Every V8--V10 search selector is
off by default.

Main repository checkpoint before the V10 commit was `b8779bd`. Nested ROCmFPX
advanced from `f5acc76` through three isolated experimental commits:

- `a48783c`: padded 20-byte FP4_FAST block;
- `c1a9745`: compact global planar codes/scales;
- `8634463`: compact four-block grouped layout.

The built search-bank backend SHA-256 is
`f89f3faaa85b22c5257b5194ea42aa3af9644afc93330bc2ab18f48fd26b4724`.
With all experiment variables unset, exact route proof selects production
`matmul_rocmfp4_fast_q8_1_bk3_m` and passes 1/1 CPU-reference validation.

## What V10 proved

The original 17-byte FP4_FAST block causes four byte loads plus reconstruction
for each 32-bit code word. A 20-byte aligned internal block removes that work:
SPIR-V instructions fall 2.80% and exact latency improves 1.227%. The benefit
is real but below server leverage and costs 17.65% extra memory for selected
weights plus 182 lines of conversion/runtime machinery.

Removing the padding by putting all scales after all codes is catastrophically
bad (+43.15%), despite fewer static loads. Keeping one scale word next to four
blocks is much better but still regresses 3.85%. Therefore scale locality and
simple block addressing dominate this family on gfx1032. Do not continue with
group-size sweeps.

## Composition result

The independent V8 exact-shape gate and down candidates were tested together
on simultaneous 8K C4 prefill. Three paired runs consistently improved
throughput by 0.402--0.688%, median 0.549%, and reduced TTFT p95 by 0.581%.
This does not meet the 0.75% server-promotion threshold. Pair 1 also had one of
four output hashes differ, while pairs 0 and 2 were exact. Do not promote or
expand this composition until a future change makes its leverage material and
the divergence is explained.

## Validation performed

- All three layout candidates: exact CPU-reference PASS and exact route proof.
- Five formal ABBA pairs per candidate.
- Default route after experiments: production BK3 PASS.
- Repository suite: 28/28 via `/home/isaac/vllm-challenge/bin/pytest -q work/tests`.
- No server test was run for rejected layout candidates.
- No drivers, clocks, power settings, model files or system libraries changed.

## Files and reproduction

- Detailed micro results: `work/KERNEL_MICROBENCH_V10.md`.
- Search decisions: `work/ATREX_SEARCH_V10.md`.
- Candidate manifests: `work/atrex_v10/candidates/`.
- Raw exact results: `work/results/v10-gate-*-micro/`.
- Static SPIR-V results: `work/results/v10-gate-*-static.json`.
- Composition runner: `work/scripts/run_v10_composed_prefill_abba.sh`.
- Composition evidence: `work/results/v10-prefill8k-composed-exact-paired3/`.
- Nested source reconstruction: `patches/v10-fp4-layouts/` on top of ROCmFPX
  `f5acc76`.

## Exact next action

The gate/down MMQ control-flow and layout families are now converged below
product leverage. Do not add another shader variant immediately. First split
the V9 prefill `misc` bucket by operation and graph. Existing top groups suggest
RMS norm/rope, ADD, GLU, copy/SSM-conv and CONCAT, each around 0.8--1.1% of all
profiled work; quantify exclusive time before choosing one.

Choose a new implementation only when `profile_share * plausible_local_gain`
can exceed 0.75% mixed-batch leverage. If no misc operation qualifies, the next
material frontier is an algorithmic Flash Attention change (not another tile
sweep) or a scheduler/kernel co-design that processes a prompt chunk in smaller
GPU-critical sections without reproducing the 5.5 s TTFT violation. Preserve
fixed chunk128 as production fallback.
