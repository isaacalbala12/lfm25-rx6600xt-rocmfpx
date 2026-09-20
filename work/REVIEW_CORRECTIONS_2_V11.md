# V11: second round of corrections — FA arithmetic, and an invalidated experiment

The reviewer's second pass found two more problems, both real. One of them
invalidates an experiment we published in the first round of corrections.

## 1. The FA correction was itself wrong, and worse than the original error

We first published 3,9 TMAC/s for the prefill attention. The reviewer showed it
did not follow from the artifacts. We then "corrected" it to 15,4 TMAC/s by
summing the per-chunk MACs. **That was wrong too, and the reviewer's number is
exactly right.**

Recomputed from the stored capture, with the accounting done per graph instead of
across the whole trace:

```
FA prefill: 504 calls across 63 batches, 571,660 us total = 0.5717 s
total MACs = 1.0909e12 = 1090.9 GMAC
rate = 1.0909e12 / 0.5717 = 1.908 TMAC/s
per graph: 17.32 GMAC in 9.074 ms
```

The mistake: the 64 distinct KV entries in the profile are the *distribution
across the 63 batches*, not the contents of one graph. Each prefill graph has
eight attention calls, one per attention layer, each with the context of that
moment. Summing all 64 entries' KV as if they coexisted inflated the MAC count by
a factor of eight.

**Consequence:** Flash attention runs at **1,91 TMAC/s against the matmuls'
7,2 TMAC/s, i.e. 27% of the achievable rate**, while being 13,78% of the prefill
graph and 11,5% of the mixed pair. The original instinct that attention is
inefficient was right; question 5 of the brief is **not dissolved**, and the
reviewer's conditional-rescaling idea is back on the table.

This is the second time in this exchange that a number was carried forward
without re-deriving its scope. The first was the decode bandwidth percentage; the
pattern is the same and it is now the single most frequent error in this work.

## 2. The scaling experiment is invalid: `-ub 256` is a pathological regime

The reviewer noticed that at the same n=128, `ADD`, `GLU` and `RMS` were 27--46x
slower in our `-ub 256` runs than in the `-ub 128` control. Confirmed, and it is
worse than that:

| Graph at n=128 | `-ub 128` | `-ub 256` | Factor |
| --- | ---: | ---: | ---: |
| Whole graph | 60.014 µs | **282.541 µs** | 4,7x |
| `ADD` x59 | 484 µs | **22.886 µs** | **47x** |
| `GLU` x30 | 1.132 µs | **48.680 µs** | **43x** |
| `MUL` x44 | 459 µs | **16.881 µs** | 37x |
| `RMS_NORM_MUL` x61 | 667 µs | **17.338 µs** | 26x |
| `CONCAT` x22 | 659 µs | 6.001 µs | 9x |

The dispatch counts are identical, so it is the per-call cost that explodes, from
roughly 8 µs to roughly 390 µs for an `ADD`. The matmuls degrade too, but only by
2,8x.

We used `-ub 256` in the scaling test because `-ub 128` cannot produce an n=256
graph, which means the test was run inside exactly the regime the campaign had
already flagged as a cliff. **Experiment 2 of `REVIEW_CORRECTIONS_V11.md` is
withdrawn.** The ratios it reported are not evidence about wave occupancy.

## 3. A new clue about the ubatch cliff

This is the first kernel-level signature of the `ubatch >= 256` cliff that the
campaign recorded only as a service-level throughput loss (2,24x of throughput,
3,6x of TTFT). The loss is not in the matmuls: it is concentrated in the
elementwise and normalisation ops, which degrade by an order of magnitude more.

It also means the earlier service-level numbers understated the mechanism. A
4,7x degradation of the prefill graph producing only a 2,24x service loss implies
the cliff is partly hidden by overlap in the server.

What causes an eight-microsecond elementwise dispatch to become a
four-hundred-microsecond one at `ub 256` is not known. The candidates are the
perf logger attributing wait time to small ops that follow a large matmul in a
differently-submitted graph, and a genuine occupancy collapse. Distinguishing
them needs the clock guard and a run without the logger, which is the next thing
to measure.

## 4. Accepted from the review

- Requiring monotonic improvement with n was too strong a demand; the reviewer
  withdrew it and we withdraw the corresponding claim.
- "One hundred launches" was an example, not a count. The model has 60
  residual-then-norm chains, so the budget for removing their `ADD` dispatches at
  C=4 is about **0,14 ms**, roughly 1,5% of the 9,15 ms step, before paying for
  the work the fused kernel would add.
- The proposed Z-replication experiment — same GEMM replicated along the batch
  dimension with separate outputs, R = 1, 2, 3, 6, gate/up as control — is a
  better discriminator than anything we have run, because it adds independent
  work without changing M, N, K, tile or shader.

## Standing status of the anomaly

The `down` gap at n=127 survives every control applied so far: not split-k, not
tile selection, not the BK3 confound (1,44 with BK3, 1,35 with BK4), not present
in the decode path. Its cause is unknown and the occupancy explanation is
neither confirmed nor refuted, because the experiment meant to test it was run in
an invalid configuration.
