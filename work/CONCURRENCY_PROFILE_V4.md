# Concurrency profile V4 — 8K per user

## Fixed controls

- Hardware: RX 6600 XT 8 GB, Navi23/gfx1032, 32 CU, wave32.
- Stable runtime: R0 (`LLAMA_SERVER_LOWEST_SLOT=1`,
  `LLAMA_SERVER_DENSE_SEQUENCES=0`).
- Kernel control: K0; the rejected four-subgroup selector is not enabled.
- FPX weights: `LFM2.5-2.6B-ROCmFP4_FAST.gguf`, SHA-256
  `d56f602eb9bcad2cafbe2a52cef2fa14ba09e6290679a2aee164db22815f0933`.
- The GGUF contains 2,697,198,592 tensor elements and is 1,442,031,616
  bytes: **4.2771 artifact bits per tensor element**. This includes GGUF
  metadata/alignment and is the reproducible whole-artifact BPW measure.
- Q4_0 control: 1,593,894,912 bytes over the same tensor-element count:
  **4.7276 artifact BPW**.

## Context-capacity proof

The server was started with `-c 34816 --kv-unified-per-slot 8704 -np 4`.
Both `/props` and `/slots` report 8704 tokens for every slot. Four simultaneous
requests each processed exactly 8192 prompt tokens and completed successfully.
There was no OOM or system swap event. The observed global VRAM maximum was
about 2.21 GB; this is device-global telemetry and is not misreported as
process-attributed allocation.

Evidence: `work/results/v4-context8k-capacity-fpx/`.

## Resident-context protocol

`bench_client.py --prime-resident-context` now fills every measured slot with
its own stable prompt before timing. The measured request uses the same prompt
and physical slot, and a run is invalid unless cache telemetry proves the
required resident prefix. llama-server intentionally reevaluates the final
four prompt tokens, so the 8192-token profile requires at least 8188 cached
tokens. The initial fill is retained as separate evidence and excluded from
the measured decode interval.

The 256-token smoke observed 252 cached plus four reevaluated tokens per slot,
which validates the protocol. It is intentionally marked INVALID because its
first test threshold was 255; the production threshold is corrected to
`prompt_tokens - 4`.

## Profile A — resident 8K decode

All cells are VALID and observed 8188 cached prompt tokens per request.

| Backend | S1 | S2 | S3 | S4 | scaling4 | efficiency4 | C4 user p5/p50 | C4 ITL p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ROCmFPXVulkan0 FP4_FAST | 113.13 | 184.86 | 225.56 | 265.79 | 2.349 | 0.587 | 65.11 / 66.52 | 15.33 ms |
| upstream Vulkan Q4_0 | 109.48 | 179.50 | 220.63 | 250.79 | 2.291 | 0.573 | 62.18 / 62.74 | 16.03 ms |

FPX wins C4 resident decode by 5.98%. The three FPX C4 repetitions were
260.29, 265.79 and 278.66 tok/s; the median, not the fastest run, is the
baseline.

## Profile B — simultaneous 8K prefill C4

| Backend | input tok/s | output tok/s service | TTFT p95 | wall | global VRAM peak |
|---|---:|---:|---:|---:|---:|
| ROCmFPXVulkan0 FP4_FAST | 1562.17 | 48.82 | 17.37 s | 20.98 s | 2.21 GB |
| upstream Vulkan Q4_0 | 1667.75 | 52.12 | 15.82 s | 19.65 s | 2.40 GB |

Upstream wins this long-prefill control by 6.33%. This is consistent with the
V3 gate/up and down profile and does not contradict the FPX decode win.

## Profile C — resident decode versus a fresh 8K prefill

The interference client first primes 8192 tokens per resident decoder, measures
a 768-token cache-hit decode control, and then repeats that decode while a
previously unused slot receives an uncached 8192-token prompt. The interference
window starts only after every resident decoder has emitted content and ends at
the first content token of the new request. Delivery events are counted at the
HTTP stream boundary and are therefore reported as event-token rate rather than
silently assuming a second tokenizer.

| Resident decoders + fresh prefill | Control aggregate | During prefill | Retention | Decoder ITL p95 | New-user TTFT |
|---|---:|---:|---:|---:|---:|
| 1 + 1 | 115.29 | 1.16 | 1.01% | 2144.95 ms | 4292.61 ms |
| 2 + 1 | 189.78 | 2.33 | 1.23% | 2184.65 ms | 4298.10 ms |
| 3 + 1 | 239.98 | 3.48 | 1.45% | 2188.54 ms | 4304.59 ms |

All three cases are VALID: the resident prompts observed at least 8188 cached
tokens, both decode phases completed their full output, and the new 8K prefill
observed zero cached tokens. Per-user rates inside each window remain almost
identical (coefficient of variation 0 to 0.0006), so the immediate problem is
not one user winning over another. The long prefill monopolizes useful GPU
service for roughly 4.3 seconds and stalls every resident decoder together.

Evidence: `work/results/v4-profile-c-fpx-q8/`.

Decision: **KEEP evidence / REJECT current scheduling for interactive service**.
The next candidate must cap the number of prompt tokens admitted to one logical
scheduler iteration; changing shader geometry cannot repair this starvation.

### Scheduler candidate: 128 prompt tokens per logical iteration

`LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` bounds only prompt admission by the
server scheduler. Backend `-ub 128`, weights, KV, context and kernels remain
unchanged. The default value zero preserves the control.

| Resident decoders + fresh prefill | Retention control | Retention chunk128 | ITL p95 control | ITL p95 chunk128 | TTFT chunk128 |
|---|---:|---:|---:|---:|---:|
| 1 + 1 | 1.01% | 11.28% | 2144.95 ms | 85.24 ms | 5061.95 ms |
| 2 + 1 | 1.23% | 13.35% | 2184.65 ms | 87.72 ms | 5158.57 ms |
| 3 + 1 | 1.45% | 15.63% | 2188.54 ms | 89.60 ms | 5271.76 ms |

All candidate cases are VALID. Resident fairness is unchanged: every decoder
received exactly 66 delivery events during the prefill in each case. The
candidate increases new-user TTFT by 0.77–0.97 seconds, but changes multi-second
resident stalls into roughly 80–90 ms inter-token intervals. This is a large
service-quality improvement even though aggregate decode remains far below its
no-prefill control.

Evidence: `work/results/v4-profile-c-fpx-q8-chunk128/`.
Decision: **STAGE**, pending the 256-token tradeoff and no-interference C4 check.

## Pending measurements

Non-invasive C1/C4 operation profiling, separated Q8_1 preparation versus MMV,
the 256-token scheduler candidate, and the no-interference C4 guardrail are
populated by the next checkpoint.
