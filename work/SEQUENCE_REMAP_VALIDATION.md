# Sequence remap validation — campaign V3 continuation

## Scope and controls

Source base: ROCmFPX `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` plus
`patches/campaign-v3-runtime-kernel.patch` and the RDNA2 header from the
original patch, using the commands in `work/NEXT_ACTION.md`. Model SHA-256:
`6221ae208de5102fe33fc2b246f6a34db32d0a2f20e371d2184838073f182198`.

The old `LLAMA_SERVER_COMPACT_SLOTS` behavior is now split into two effective
policies and printed at startup:

- R0: `LLAMA_SERVER_LOWEST_SLOT=1`, `LLAMA_SERVER_DENSE_SEQUENCES=0`.
- R1: `LLAMA_SERVER_LOWEST_SLOT=1`, `LLAMA_SERVER_DENSE_SEQUENCES=1`.

The legacy variable remains a compatibility default for both switches. The
benchmark always records the effective policy, not merely the legacy name.

## Changes and invariants

- A slot now records `backend_sampling_active`; sampler existence is not used as
  a proxy for sampling policy.
- Migration remains deferred until all pending results in the decode batch have
  been consumed.
- Every move checks physical-ID range and global uniqueness, and checks that
  recurrent/KV minimum and maximum positions are unchanged after copy/remove.
- Source sampler registration is cleared. Host-sampled requests keep a null
  backend sampler at the destination.
- Speculative decoding remains excluded.
- Remap logging is value-controlled by `LLAMA_SERVER_REMAP_TRACE`; value `0`
  is now genuinely off. Recurrent tracing and Vulkan loggers received the same
  value-aware treatment.
- Batch ID sets are no longer collected while batch tracing is disabled.

## Cancellation while peers remain active

`work/scripts/dynamic_slot_reproducer.py` now starts three 128-token survivors
and one 256-token victim, disconnects the victim after eight streamed chunks,
then admits a 48-token newcomer before the survivors complete. Prompts are
distinct. Full text, retokenized IDs and SHA-256 hashes are retained.

Forced victims 0, 1 and 3 exercise initial, intermediate and final holes over
three consecutive recycle cycles.

| Runtime | Cycle wall ms (victim 0 / 1 / 3) | Completed survivors | Completed newcomers | Exceptions |
|---|---:|---:|---:|---:|
| R0 | 2331 / 4526 / 2599 | 9/9 | 3/3 | 0 |
| R1 | 2469 / 2546 / 2965 | 9/9 | 3/3 | 0 |

R1 removes the demonstrated sparse-ID collapse in the victim-1 cycle, but this
small campaign is not a statistical throughput promotion. It also has cycles
that are slower than R0.

Nine of twelve completed outputs are token-identical between R0 and R1. Three
first diverge at retokenized output positions 39, 100 and 13. Concurrent batch
ordering was not fixed across the two server processes, so this does not yet
distinguish grouping-dependent numerical variation from a remap defect. R1
therefore remains **STAGE**, not production-equivalent.

Raw evidence:

- `work/results/v3-remap-r0-forced-sampling-off/`
- `work/results/v3-remap-r1-forced-sampling-off/`

## Backend sampling

The first migration test with backend sampling reproduced a different hard
failure:

`llama_sampler_chain_backend_init() called twice`

The public sampler path initializes a chain for one physical sequence and does
not expose a safe rebind operation. Calling `llama_set_sampler()` after a move
therefore aborts. R1 now explicitly rejects `backend_sampling=true` with HTTP
400 before launch instead of crashing or silently switching sampling policy.
The rejection is verified in
`work/results/v3-remap-r1-backend-sampling-rejected/result.json`.

## Historical range-check exception

The old `vector::_M_range_check` with index `18446744073709551615` belongs to
the earlier immediate-migration implementation. It did not reproduce in the
three deferred-migration cycles above. This is recorded as **not reproduced
under the tested conditions**, not as proven fixed. The backend-sampler abort
is a separate, now-contained defect.

## Reproduction

```bash
POLICY=r0 MODE=forced BACKEND_SAMPLING=off PORT=18162 \
  work/scripts/run_dynamic_remap_validation.sh
POLICY=r1 MODE=forced BACKEND_SAMPLING=off PORT=18161 \
  work/scripts/run_dynamic_remap_validation.sh
POLICY=r1 MODE=forced BACKEND_SAMPLING=on PORT=18164 \
  work/scripts/run_dynamic_remap_validation.sh
```

## Decision

**STAGE** for host sampling only. The sparse-service benefit is demonstrated,
but token equivalence and repeated normal-API arrival/cancellation statistics
must be closed before production. Backend sampling with R1 is explicitly
unsupported and rejected.
