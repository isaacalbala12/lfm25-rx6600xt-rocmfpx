# Atrex-style Vulkan search V6

## Outcome

V6 produced a functional bounded evaluator for the real `ROCmFPXVulkan0`
plugin and one server-relevant **STAGE** candidate. Official Atrex was audited
at `d83b01a`: its episode loop, ABBA, rollback and memory are reusable, but its
evaluator is coupled to `kernel.py` and `test_kernel.py`. The adapted loop keeps
`test-backend-ops` as source of truth; details are in
`work/ATREX_INTEGRATION_PLAN.md`.

Pinned control: root `d1263dc`, ROCmFPX `7c4b5c0`, backend
`40f6b9c...b25b40`, test executable `6cc800a...f6331`, GCC 16.2.0.

The evaluator enforces clean source, allowlisted reversible patches, taboo
memory, explicit plugin build, distinct artifact hashes, CPU-reference
correctness, selector proof, logger-free ABBA, paired bootstrap, rollback and
production restoration. Its first dry run caught that building
`test-backend-ops` alone left the plugin stale. Those same-hash records are
retained and marked INVALID; `f8e58a3` fixed the target and added a hard hash
gate.

## Campaign 01: K staging depth

This was a focal search, not a generic sweep. BK2 global was already taboo and
BK4 was control.

| Candidate | Gate N128 paired median | Decision |
| --- | ---: | --- |
| BK1 | +4.900% | REJECT |
| BK3 | **-3.891%** | guardrails |
| BK5 | +18.052% | REJECT |
| BK8 | +84.237% | REJECT |

Five-pair guardrails found BK3 at -4.020%/-4.291%/-3.854% for gate/up
N=120/128/129, but +2.122% for down N=128. Global BK3 is **REJECT**.

A separate gate/up-only shader selected
`matmul_rocmfp4_fast_q8_1_bk3_m`. It passed exact correctness and improved
428.975 -> 412.940 us over five ABBA pairs: **-3.859%**, bootstrap 95%
[-3.993%, -3.521%]. The measured curve is consistent with BK3 balancing
barrier amortization against the resource cliff at BK5/8; this is an inference,
not an occupancy measurement.

Three 8K-prefill C4 server pairs were valid and output-identical 3/3. Selective
BK3 improved aggregate input/output service throughput by **+1.367%** median;
all pairs were positive (+0.802%, +1.367%, +3.263%). TTFT p95 improved 1.240%
and E2E p95 1.347%. Candidate input rates were 1571.97--1575.87 tok/s, below
the 1668 tok/s target.

Decision: **STAGE**. It needs ten Profile-B pairs, 3D+1P, resident C4, selective
boundary/down route proof and final service-EOS quality. Production remains
unmodified.

Next tooling change: compile several opt-in candidates in one library, select
them by environment and restore once. This retains causal ABBA while avoiding
two full embedded-shader builds per mutation.

## Superseded by V7

The pending guardrails passed and selective BK3 is KEEP. The same-binary search
path, parametric gate/down problem definitions and subsequent negative
candidates are documented in `work/ATREX_SEARCH_V7.md`.
