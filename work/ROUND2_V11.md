# V11 round 2: environment fix, chunk re-tune, KV dtype, and the shape of the down gap

## The power profile change worked, partially

The host was switched to the `3D_FULL_SCREEN` power profile, which sets MEMCLK
`MinActiveFreq = 850`. The slow clock state is not gone but it is much rarer:

| Condition | Slow runs | Runs measured |
| --- | ---: | ---: |
| `BOOTUP_DEFAULT` | 5 | 12 |
| `3D_FULL_SCREEN` | 1 | 10 |

A slow run is unambiguous from the outside: wall time 5.33 s against 3.92 s for
the same command, and throughput 218 against 353 tok/s. Individual 541 MHz
samples also appear inside fast runs while the clock ramps, so a single sample
is not diagnostic; the run time is.

Measurements below are best-of-N over interleaved runs, reporting the fast
cluster. The residual ~10% slow rate means a single run still has a one in ten
chance of being 40% off.

## Re-validated headline with a stable clock

| Backend | Runs (B=4 decode) | Fast-cluster mean |
| --- | --- | ---: |
| control | 354.68 / 352.86 / 354.22 | 353.9 |
| folded | 399.47 / 398.92 / 401.46 / 396.26 | 399.0 |

**+12.7%**, consistent with the +13.8% measured before the profile change, and
now reproducible enough to quote from a handful of runs.

## Prefill chunk size: 128 still wins, and the trade is now quantified

Single-arm service runs on the 8K mixed profile, folded backend:

| Chunk | TTFT | ITL p95 | ITL p50 | Retention |
| ---: | ---: | ---: | ---: | ---: |
| 128 | 5230 ms | 88.84 ms | — | 14.58% |
| 192 | 5504 ms | 133.95 ms | — | 9.44% |
| 256 | **4649 ms** | 156.66 ms | — | 8.70% |

Chunk 256 buys 11% of TTFT and pays 76% of ITL. The per-batch arithmetic says
why: a mixed batch is one decode step plus the chunk, so 8192 tokens at chunk
128 is 64 batches of 81.7 ms and at chunk 256 is 32 batches of 145 ms. The
decode step, about 9.2 ms, is a fixed cost per batch, and the prefill work
itself is only 6% cheaper per token at the larger size. **KEEP 128**, which
remains the only setting oriented at the interactivity objective.

## A withdrawn claim about harness reliability

An earlier version of this note reported that "four arms in eighteen produce no
`n3.json`" and that the harness was silently dropping one pair in five. **That
was wrong and is withdrawn.** The arms were still running when the result
directory was read; every arm produces its file. Both format A/B runs summarise
to two valid pairs with no invalid entries.

The mistake is worth recording because it is the same failure mode the campaign
kept hitting: reading a partial state as a final one. The rule it suggests is
that a paired run is only complete when the runner's own final summary exists,
not when the last arm's directory appears.

## The 8K format finding, measured four times

With both runs summarised correctly, Q4_0 against ROCmFP4_FAST on the mixed 8K
profile:

| Run | Pairs | TTFT | ITL p95 | Retention |
| --- | ---: | ---: | ---: | ---: |
| pre-fold | 3 | −6.98% | −7.16% | +11.6% |
| post-fold | 2 | −9.02% [−11.15, −6.89] | −7.61% [−8.93, −6.29] | +15.1% |
| stable clock | 2 | −6.38% [−6.82, −5.94] | −6.30% [−6.91, −5.68] | +12.2% |

Four independent measurements, every confidence interval excluding zero, and the
direction never changing. This is the most reproduced result in the repository
and the basis for the `production-interactive` profile.

## The ubatch cliff is real, and it is not the clock

The campaign rejected `ubatch=512` after seeing C=1 at 68.03 and C=4 at 110.14
tok/s together with an oscillating memory clock, and this note's first version
hypothesised that the cliff *was* the clock state. Re-testing under the fixed
power profile refutes that.

Three runs per configuration, C=4, 128/64, 10 repetitions, interleaved:

| Batch / ubatch | C=4 tok/s | TTFT p50 | E2E p95 |
| --- | --- | ---: | ---: |
| 512 / 128 | 249.16, 251.43, 253.72 | 320-344 ms | 1022-1066 ms |
| 512 / 256 | 111.82, 111.79, **205.05** | 441-1151 ms | 1286-2324 ms |
| 1024 / 512 | 114.96, 114.48, 114.35 | ~1090 ms | ~2260 ms |

Five of six runs at `ubatch >= 256` collapse, and the signature differs from the
clock state in a way that rules the clock out: the clock scales every metric by
about 1.56x uniformly, while this costs 2.24x of throughput and **3.6x of
TTFT**, so it damages prefill far more than decode. One `ubatch=256` run landed
at an intermediate 205 tok/s, so the effect has a threshold rather than being
cleanly binary.

**Decision: KEEP `ubatch=128`**, and record that the campaign's original
observation was correct while its stated cause was not. This is also the one
place where an earlier V11 claim has been withdrawn rather than extended.

## KV cache dtype: q4_0 rejected

| KV | TTFT | ITL p95 | Resident decode |
| --- | ---: | ---: | ---: |
| q8_0 | 5185 ms | 87.72 ms | 261.2 tok/s |
| q4_0 | 8359 ms | 165.69 ms | **105.0 tok/s** |

q4_0 KV costs 60% of resident decode throughput and 61% of TTFT. Flash attention
has to unpack the cache, and the unpacking costs more than the bytes it saves.
**REJECT**, no further work.

## The down gap is prefill-specific and is not a tile or split-k problem

`down` (`m=2048 n=127 k=10752`) runs at 9.25 TFLOPS against 13.9 for `gate/up`
(`m=10752 n=127 k=2048`), for identical multiply-accumulates and weight bytes
per matrix. Three candidate causes have now been eliminated:

1. **Not split-k.** Every prefill shape selects `split_k = 1`, and an override
   raising it to 2, 4 or 8 was neutral to catastrophic. See
   `PREFILL_LEADS_V11.md`.
2. **Not tile selection.** A trace of `ggml_vk_matmul` shows every prefill shape
   in this model using the same `(64, 64)` workgroup tile, with `split_k = 1`:
   ```
   mm: m=10752 n=128 k=2048  wg=(64,64) split_k=1
   mm: m=2048  n=128 k=10752 wg=(64,64) split_k=1
   mm: m=6144  n=128 k=2048  wg=(64,64) split_k=1
   ```
3. **It is specific to the prefill path.** In the decode graph, where the same
   shapes go through the mat-vec kernel, `down` costs 62.0 µs per call against
   57.2 for gate/up, an 8% gap rather than 50%. So the deficit lives in the MMQ
   (batch matmul) shader's behaviour at `m=2048, k=10752`, not in the weights or
   the shapes.

What remains unexamined is the row geometry: a `down` weight row is 5,712 bytes
against 1,088 for `gate/up`, so a k-loop is 336 FP4 blocks long against 64 with
5.25x fewer rows to overlap it. That is a shader-level question.

## add+rms fusion is silently disabled above batch 1

The backend has an add+rms fused path (`pipeline_add_rms`,
`pipeline_multi_add_rms`, `do_add_rms_partials`) but the graph builder gates it
on `ggml_nrows(next_node) == 1`. At four slots the tensors are `(2048, 4)`, so
`nrows == 4` and the fusion never triggers:

| Decode graph | Plain ADD dispatches | ADD time | Groups with a fused ADD |
| --- | ---: | ---: | --- |
| batch 1 | 22 | 59 µs | `MUL_MAT_ADD` x2 |
| batch 4 | **60** | **144 µs** | none |

That is 38 extra dispatches and 85 µs of a 10,339 µs graph, about 0.8%, plus the
per-row pass that the fusion would have saved. Enabling it needs the partials
buffer sized for `nrows x num_partials` (`ggml_vk_rms_num_partials` uses only
`ne[0]`) and the shader to emit per-row partials. Bounded, but not obviously
worth 1-2% against the risk. Recorded, not attempted.
