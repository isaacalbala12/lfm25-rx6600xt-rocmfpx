# Concurrency profile V5

## Checkpoint

- Root parent: `c1dd1e181c5adc16862cf882d0f6ba03c5730547`.
- ROCmFPX source after lightweight timing: `11649d0474908567e434ed9928cb02fda8ef1386`.
- Model: `LFM2.5-2.6B-ROCmFP4_FAST.gguf`, SHA-256 `d56f602e...`, artifact BPW 4.277124.
- Backend: `ROCmFPXVulkan0`, q8/q8 KV, four 9216-token slots (>=8192 required).

## Production gate for chunk128

`work/results/v5-quality-service-eos-r3` compares unlimited scheduling with
chunk128 under normal EOS, temperature 0 and seed 0. All seven reserved cases
pass (mathematics, JSON, tool-like JSON, instructions, Spanish, 8.9K-token
retrieval and long generation). Full visible text, finish reason and completion
token count are identical in all 7/7 pairs. Combined with the earlier 10/10
fixed-output identity check, chunk128 is **KEEP for production**. This does not
claim that FP4_FAST has the same quality as a higher-precision weight format.

## Chunk96 exploratory decision

| Candidate | retention | resident ITL p95 | new-user TTFT |
|---|---:|---:|---:|
| chunk128 | 15.659% | 89.190 ms | 5270.945 ms |
| chunk96 | 16.627% | 82.677 ms | 6646.088 ms |

Chunk96 gains only 6.19% relative retention and 7.30% ITL while adding 26.09%
TTFT. It reaches neither V5 target. Per the immediate-rejection rule, remaining
pairs were cancelled and chunk96 is **REJECT**. The interrupted pair-01 is not
a sample.

## Lightweight timeline

The opt-in trace now records submit/completion with a shared ID and duration.
The VALID reproduction gives 15.571% retention, 89.337 ms ITL p95 and 5319 ms
TTFT. Sixty-three full mixed batches (`128 prompt + 3 decode`) take 79.961 ms
median and 87.554 ms p95; decode-only C3 batches take 11.561 ms median. The
~89-ms pause is principally the mixed GPU batch, not a hidden CPU gap. The
scheduler already inserts all three decode tokens into every prompt chunk.

## Why 6144x2048 reports N=1

This was a dimensional interpretation error, not four independent users.
LFM2 short-conv reshapes input to `[2048,n_seq_tokens,n_seqs]`; its in-proj
produces `[6144,n_seq_tokens,n_seqs]`. C4 decode is `[6144,1,4]`. The Vulkan
profiler calls `ne[1]` matrix N, hence N=1, while users remain in `ne[2]=4`.
There are 154 calls over seven graphs: exactly 22 recurrent layers per graph,
not 88. `elements=6144x4x1` independently preserves the four batch planes.
Rebatching to N=4 would cross recurrent layout semantics. **REJECT hypothesis.**

## Decisions

- chunk128: **KEEP production** with V4 throughput guardrails.
- chunk96: **REJECT** after one valid early-rejection pair.
- lightweight timeline: **KEEP diagnostic only**.
- 6144 N=1 rebatching: **REJECT hypothesis**; already batched in `ne[2]`.

## Selective gate/up BK_STEP=2 final decision

The opt-in gate-only pipeline improves simultaneous 8K C4 service throughput
by 1.072% over its contemporary control (three repetitions each). In one 3D+1P
pair it also moves retention 15.632% -> 15.947%, ITL p95 89.366 -> 88.212 ms,
and new-user TTFT 5304.59 -> 5221.88 ms. It does not execute for resident decode
N<=6, so the steady-state decode path remains unchanged by construction.

Ten paired Profile B batches supersede the exploratory estimate: aggregate
throughput improves +0.486% median with 95% CI [+0.371%, +0.705%], TTFT p95
improves 0.693%, E2E p95 improves 0.485%, and outputs are exactly equal in all
10/10 pairs. Every pair favors the candidate, so this is a real small effect,
not evidence of a regression.

Decision: **REJECT**. It does not reach the predeclared 0.75% threshold and has
no structural value that offsets the added pipeline. The candidate has been
removed and the rebuilt production backend matches the saved control hash.
