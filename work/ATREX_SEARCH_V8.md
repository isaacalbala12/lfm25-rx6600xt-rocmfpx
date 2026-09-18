# V8 automatic search: down N128

## Objective

Optimize the exact ROCmFPXVulkan0 down pipeline at
`M=2048, K=10752, N=128`, while retaining BM64/BN64/BK32/BK_STEP4 and exact
FP4_FAST x Q8_1 arithmetic. Down accounts for about 23.28% of grouped N128
prefill time, so a 3.2% local win has an approximate 0.75% global ceiling.

## Evidence model

Search state schema 2 separates `smoke`, `exploratory`, `formal_micro`,
`formal_server`, and `production`. Only PASS evidence at `formal_micro` or above
can update the incumbent, valid-candidate count, or convergence counter. INVALID
and smoke history remains visible but cannot replace formal evidence.

The search driver now requires an explicit campaign baseline for a new state and
rejects reuse of a state created for another baseline. The V8 baseline is
`down-bm64-bn64-bk32-bk4`.

## Initial proposer memory

- `down BM32/BN64`: REJECT, +21.802% latency. Scope: reducing the down row tile
  from BM64 to BM32 under the measured geometry; not every possible BM change.
- Global BK2 and BK3 regressed down; keep BK_STEP4 during this campaign.
- Arithmetic FP4 unpack and naive packed32 extraction remain taboo.
- Exact compute-loop unroll was rejected for gate/up and generated structurally
  equivalent SPIR-V; equivalent directive-only mutations are not candidates.

## First candidate bank

| ID | Hypothesis | Expected mechanism | Affected resource | Expected local gain | Global ceiling |
|---|---|---|---|---:|---:|
| `down-notail` | Exact K does not need generic tail predicates | Remove repeated compare/branch/validity paths | control/address overhead | 2–5% | 0.47–1.16% |
| `down-hoist-strides` | Block strides are reconstructed in the loop | Hoist invariant divisions/terms | integer/address instructions | 0–3% | 0–0.70% |
| `down-b-first` | Current A-first staging exposes a worse issue order | Start Q8 staging before FP4 staging | load scheduling/latency hiding | 1–4% | 0.23–0.93% |

Each pipeline has an independent opt-in selector and route name in one search
library. Multiple candidate selectors are rejected instead of composing
silently. The production default remains the existing down pipeline.

## Budget and gates

- 20 formal valid candidates, 40 total attempts, or 8 formal candidates without
  improving the incumbent.
- Correctness, exact route, complete samples, and same-binary control are hard
  gates.
- A candidate may become micro incumbent at >=1% with favorable CI.
- Server test requires >=3% local, or 1–3% with >=0.75% predicted global leverage.

## Current status

Search complete: 11 formal PASS candidates, zero INVALID candidates. The best
microcandidate is `down-exact` at -2.1607%, 95% CI [-2.3803%, -1.1936%]. It
removes generic K-tail, split-K and output-bound control for the exact shape,
reducing SPIR-V instructions by 16.40%.

`down-q8group4` validates a second mechanism (-1.793%), but combining it with
`down-exact` reaches only -1.710%; the wins are not additive. Seven consecutive
formal candidates after the incumbent failed to improve it. The first V8 down
family is therefore converged under the predeclared stop rule.

No result reaches the server gate: `down-exact` has only ~0.50% predicted global
leverage. It is **ARCHIVE COMPOSABLE**, not production. Full results are in
`work/KERNEL_MICROBENCH_V8.md` and `work/results/v8-down-search/`.
