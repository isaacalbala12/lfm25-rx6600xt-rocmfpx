# V11: DSpark speculative decoding is a dead end on this machine

## Why this was tested

An earlier V11 note dismissed speculative decoding at C=4 with an arithmetic
argument that assumed a general-purpose 1.2B drafter: +49% weight traffic for
~2.2 tokens per sequence, giving ~268 tok/s against 401. That assumption was
wrong and the dismissal with it. **DSpark is a purpose-built drafter** —
`Lfm2DSparkDraftModel`, 5 layers, hidden 2048, and the Q4_K_M GGUF is 199 MB, so
the traffic penalty is +14% rather than +49%. With those numbers the outcome
depends on the acceptance rate: break-even around 0.7, a win above 0.85.

llama.cpp supports it natively (`LLM_TENSOR_DSPARK_MARKOV_W1/W2`,
`LLM_TENSOR_DSPARK_CONF_PROJ`, `src/models/dflash.cpp`), and the server takes
`-md`. So it was measured.

## Three independent reasons it does not work here

### 1. It is slower even at a single sequence

`llama-cli`, `-dev Vulkan0`, identical prompts, `--temp 0`, two runs each:

| Condition | Generation |
| --- | ---: |
| No drafter | 121.7, 121.5 tok/s |
| DSpark Q8_0, `--spec-draft-n-max 4` | 104.7, 106.9 tok/s |

**−13%.** Whatever the acceptance rate is, the drafter's cost exceeds what it
buys on this part.

### 2. At four sequences it is broken, not just slow

The 128/64 C=4 metric, `-dev Vulkan0`:

| Condition | C=4 | Status |
| --- | ---: | --- |
| No drafter | 221.7, 219.7 tok/s | VALID |
| DSpark Q8_0, n-max 4 | 51.8, 72.4 tok/s | **INVALID** |

The throughput figures are meaningless because requests failed: 17 of 40 and 4
of 40 returned `HTTP 200 stream contained error: Invalid input batch`. The
speculative path does not survive four parallel sequences in this build.

### 3. The ROCmFPX backend cannot host the drafter at all

With `-dev ROCmFPXVulkan0` — the production backend, the one with the batch fold
— the server aborts while loading the draft model:

```
ggml-backend.cpp:941: pre-allocated tensor (token_embd.weight) in a buffer
(ROCmFPXVulkan0) that cannot run the operation (NONE)
  ...
  common_speculative_init_from_params -> llama_init_from_model ->
  sched_reserve -> ggml_backend_sched_split_graph
```

Reproduced with the Q8_0 and Q4_K_M drafters and with `-ngld 0` (drafter on
CPU), so it is neither the quantization type nor device placement. It is the
plugin's backend instance failing to accept the draft graph. The standard
`Vulkan0` device starts fine, which is what made tests 1 and 2 possible.

## Decision

**REJECT speculative decoding on this machine.** Not on assumption this time,
but on three measurements. The relevant conclusion for the project is that
`production-throughput` stays on `ROCmFPXVulkan0` with the batch fold, and that
no speculative configuration can be layered on top of it without first fixing
the plugin's draft-graph handling.

## What remains genuinely open from the earlier list

Speculative decoding was the largest entry. The others stand:

1. the `down` projection's 1.5x efficiency gap in prefill, worth ~9% of it;
2. Flash attention in the prefill chunk, measured at 56% of the matmul
   efficiency;
3. the `add+rms` fusion that is gated off at every concurrency above one;
4. the decode mat-vec kernel's 193 against 222 GB/s;
5. `SSM_CONV` and `GET_ROWS`, never examined.
