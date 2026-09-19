# V11: the first quality measurement in the campaign

## Summary

`llama-perplexity` had been built in this tree since the start and the campaign
identified a formal quality evaluation as its highest-value next experiment on
2026-09-17. It was never run. It has now been run, and it changes the format
recommendation that the rest of this repository is built on.

| Format | bpw | PPL, 400 KB corpus | vs Q8_0 | PPL, 72 KB corpus | vs Q8_0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q8_0 (reference) | 8.50 | 81.47 ± 2.23 | — | 47.08 ± 2.61 | — |
| Q4_K_M | 4.94 | 89.09 ± 2.44 | **+9.4%** | 46.40 ± 2.54 | +0.0% |
| Q4_0 | 4.70 | 90.94 ± 2.50 | +11.6% | 51.71 ± 2.88 | +9.8% |
| ROCmFP4_FAST | 4.25 | 94.39 ± 2.63 | **+15.9%** | 50.52 ± 2.82 | +7.3% |

Method: `llama-perplexity -dev ROCmFPXVulkan0 -ngl 99 -fa on -c 512 -b 512
-ub 128 -ctk q8_0 -ctv q8_0`, 24 and 96 chunks of English markdown drawn from
this repository's own documents. Q8_0 stands in for the BF16 checkpoint: at
8.5 bpw its own deviation is small, and it is the highest precision artifact
available on this host. Both corpora are heterogeneous prose, which is why the
absolute values are high; only the comparisons matter.

## What is robust and what is not

With 96 chunks the standard error of a difference is about 0.33, so every gap in
the large-corpus column is many sigma wide.

- **All three quantized formats cost real quality against Q8_0**: +9% to +16%
  perplexity. That was unknown before this measurement. Every KEEP in this
  repository that traded quality for speed was made without it.
- **Q4_K_M is the best of the quantized formats on both corpora** and is within
  noise of Q8_0 on the smaller one. It is the quality-preserving choice at
  4.94 bpw.
- **The FP4_FAST versus Q4_0 ranking is not robust.** The small corpus puts
  Q4_0 2.3% worse; the large corpus puts FP4_FAST 3.8% worse. Do not claim
  either ordering from these two runs.

## Consequence for the format decision

`FORMAT_PREFILL_V11.md` recommends Q4_0 for the interactive 8K profile on a
−7.0% TTFT and −7.2% ITL margin. That recommendation stands on latency, but it
can no longer be presented as free: Q4_0 and FP4_FAST are both several
perplexity points above Q8_0, and neither is demonstrably better than the other
on quality from this evidence.

The honest statement is now: **the interactive profile trades about 10% of
perplexity against Q8_0 for its throughput, and so does the throughput profile.**
If quality matters more than the last 7% of TTFT, Q4_K_M at 4.94 bpw is the
right format, and its measured cost is a modest throughput reduction relative to
Q4_0 (213 versus 228 aggregate tok/s at C=4 in the V2 screens).

This is the first time the repository can state a quality cost at all.

## What a formal evaluation would still need

- A reserved corpus that is not drawn from the repository's own prose, and a
  standard one such as WikiText-2 for comparability with other work.
- The BF16 checkpoint converted to GGUF so the reference is the model rather
  than another quantization.
- KL divergence against the reference logits, not only perplexity.
- A task-level evaluation, since perplexity on markdown says nothing about
  instruction following or JSON validity, which is what the campaign's smoke
  battery actually tests.

Until then this note should be cited as "perplexity on two self-built corpora",
not as a quality evaluation.
