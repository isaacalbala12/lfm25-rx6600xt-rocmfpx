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

## Pending measurements

Profile C interference, non-invasive C1/C4 operation profiling and the first
new optimization are populated by the next checkpoint.
