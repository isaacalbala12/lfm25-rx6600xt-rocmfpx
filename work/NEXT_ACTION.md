# Próxima acción

## Campaign V5 checkpoint (current)

Chunk128 passed the reserved service-EOS gate and is **KEEP production**.
Chunk96 is **REJECT**. The light timeline proves each 128-token mixed batch
costs ~80 ms median; CPU scheduling gaps are not the main limiter. The apparent
6144x2048 N=1 path already batches four users in `ne[2]`, so close rebatching.

The fenced profile is complete: gate/up is 32.79%, down 23.28%, and Flash
Attention 23.11% of grouped time at the final N=128/8K tile. Next implement
exactly one in-wave/tile or packed-load change for gate/up. Require exact plugin
microbench correctness and ABBA before 3D+1P. Do not revisit chunk96, Q8 reuse,
subgroup-count gate/up variants, rows4 short-conv, or N-only selectors.

The first packed-load candidate is now closed: exact aligned uint extraction
regresses gate/up N128 by +1.880% (95% CI [+1.692%, +2.071%]) and is
**REJECT**. Production is restored byte-for-byte. The selector evidence shows
this shape uses the plugin's medium integer MMQ tile on RADV. The specialization
vector is `BLOCK_SIZE=256, BM=64, BN=64`—the leading 256 is not BM. Next test
one aspect-ratio change, `BM=32, BN=128`, retaining 256 threads and the other
parameters. At N=128 this keeps the total workgroup count while loading each
weight row for one N tile instead of two. Test gate/up and down independently.
Reject immediately on >5% regression in either dominant family; require ABBA
and exact CPU-reference correctness before any server run. Do not combine it
with the rejected packed-load code.

The 32x128 tile has now also been measured and is **REJECT**: gate/up is
-0.125% paired with confidence crossing zero, while down is +0.367% and also
inconclusive. The 64x64 production tile is restored exactly. The next isolated
high-leverage experiment is FP4_FAST `BK_STEP=2` versus the current 4 on the
same two N128 shapes. This halves staged K data/LDS per workgroup but doubles K
loop/barrier frequency, so reject it immediately if either dominant family
regresses by more than 5%. Keep the tile at 64x64 and the byte-load control;
require exact correctness and ABBA before considering a server run.

## Campaign V4 immediate checkpoint

Context capacity is proven with four 8704-token slots. Run the resident-decode
baseline with `PROMPT_TOKENS=8192`, cache priming enabled and
`MIN_CACHED_PROMPT_TOKENS=8188`, then run the cache-off 8192/256 prefill C4
control. Do not use the intentionally invalid 256-token smoke as a result.

After FPX C1–C4, repeat the exact protocol with upstream Vulkan Q4_0. Populate
`work/CONTEXT8K_BASELINES.json` before enabling profiling or changing code.

Completed: Profiles A, B and C are populated. FPX wins resident C4 by 5.98%;
upstream wins simultaneous long-prefill by 6.33%. Profile C demonstrates severe
scheduler starvation: one fresh 8K prefill leaves resident decoders at only
1.01–1.45% of their control delivery rate for about 4.3 seconds.

Next: add an opt-in logical prefill-chunk limit in the server scheduler, leaving
the backend ubatch fixed at 128. Compare the current unlimited logical batch
against 128/256-token scheduler chunks with Profile C, then verify the winning
candidate does not regress Profile A C4 or Profile B beyond the measured TTFT
tradeoff. Separately profile FPX C1 versus C4 with timestamps for
`quantize_q8_1_x4` and `mul_mat_vec_rocmfp4_fast_q8_1_f32`.

Implementation checkpoint: ROCmFPX `e9e88220302846f82e0fb86320c728f73f2a72e6`
adds opt-in `LLAMA_SERVER_PREFILL_CHUNK_TOKENS`; default zero preserves R0.
The Release server builds successfully. Chunk128 raises resident decode
retention from 1.01–1.45% to 11.28–15.63% and reduces ITL p95 from more than
2.1 seconds to 85–90 ms, at a 0.77–0.97 second TTFT cost. It remains STAGE.
Run chunk256 next, then the no-interference C4 guardrail for the winner.

Completed: chunk256 is inferior for resident inter-token latency, and chunk128
changes resident-only C4 by -0.67% (264.01 versus 265.79 tok/s median), within
the observed spread. Next run the four-simultaneous-prefill guardrail, then the
separate invasive C1/C4 operation profile. Keep chunk128 at STAGE until paired
confirmation; do not treat the two harness-rejected setup attempts as samples.

Profiling checkpoint: ROCmFPX `8e65941b623397bad47c2ff53fe750c38dfa9b96`
adds a dedicated, opt-in Vulkan timestamp pool for the internal
`quantize_q8_1_x4` and FP4_FAST MMV dispatches. A correctness smoke completed
and emitted 982 paired dispatch samples. The logger forces the existing fenced
perf path and is therefore profiling-only; never use its wall throughput as a
service result. Run the resident 8K C1/C4 traces and aggregate by graph, N and
pipeline next.

Completed at ROCmFPX `c800bd8360f40aa6044173578e9fbed055e74951`:
resident-8K C1/C4 phase traces are shape-labelled and summarized. At C4,
Q8 preparation is only 2.04% of Q8+MMV; gate/up already shares one preparation
between two consumers. The next kernel experiment must be limited to a measured
family. Prefer gate/up 10752x2048 N=4 (39.60% of measured MMV) unless a selector
or scheduler experiment can convert the 6144x2048 path from N=1 without adding
interactive delay. Do not implement another Q8 cache.

Chunk128 Profile B guardrail is also complete: median aggregate output -1.42%,
TTFT p95 +1.81%, wall +1.44%, with all 12 requests valid. Its large Profile C
benefit still justifies STAGE. Next run a ten-pair control/chunk128 confirmation
with predeclared exclusions; in parallel, prototype only one measured MMV shape
family, beginning with 10752x2048 N=4.

## Checkpoint V3

El punto de revisión padre de esta continuación es `bad60333b6c694915e3ce9777f0cde62fe883ed2`; ROCmFPX parte de `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1`. El trabajo se conserva tanto en un commit local de `campaign-v3` como en el checkpoint local ROCmFPX `2678844a0af778c7c41b2d552667e9a05d98248c`; no se hizo push. El equipo actual sigue siendo Ryzen 5 1500X 4C/8T y Navi23/gfx1032.

El arnés V3 está corregido y sus ocho tests pasan. El mapa de ejecución prueba que `ROCmFPXVulkan0` usa el backend Vulkan propio del plugin, no `ggml/src/ggml-vulkan`. El perfil 2048/u128 y el censo actual están en `work/PROFILE_V3.md` y `work/SHAPE_CENSUS_V3.csv`.

La baseline exacta del modelo coherente es aproximadamente 103,7 tok/s C1 y 228,0 C4. No sustituirla por 303,3 ni por los 230,5 históricos.

## Candidato en STAGE

`LLAMA_SERVER_COMPACT_SLOTS=1` activa IDs físicos densos sin cambiar los IDs lógicos de la API. Corrige el split recurrente demostrado y pasa el reproductor dinámico con finalizaciones distintas, desconexión y reciclaje. No está promovido a producción: falta una serie C4 emparejada estable, comparación de logits y evaluación formal de calidad.

Siguiente ejecución: A/B/B/A del runtime anterior frente al candidato en carga dinámica C4, con muestreo de clocks de mayor frecuencia. Resamplear por tanda, no por solicitudes hermanas. Si la ganancia sobrevive, ejecutar comparación de logits y después un microbenchmark del selector real para FP4_FAST GEMV N=1/2/4 con buffers calientes y rotación de matrices.

## Reproducción

```bash
work/tests/run_harness_tests.sh

source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH="$PWD/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/rocmfpx-vulkan-plugin.so"
export LLAMA_SERVER_LOWEST_SLOT=1
export LLAMA_SERVER_DENSE_SEQUENCES=0
GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=128 MAX_TOKENS=64 \
  CONCURRENCIES="1 2 3 4" REPETITIONS=3 WARMUP=1 \
  work/scripts/benchmark_llama_backend.sh \
  --server work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server \
  --model work/results/models/LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf \
  --output work/results/reproduction-v3 -- \
  -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
```

No cambiar perfiles de energía, clocks, drivers ni firmware. Mantener una sola carga GPU y no hacer push hasta revisar el patch regenerado.
# Checkpoint after V3 runtime/kernel continuation

1. Keep production on R0/K0. R1 remains STAGE for host sampling; K1 is REJECT.
2. Close remap equivalence with a deterministic stepwise harness that fixes the
   batch schedule and compares logits immediately before and after a move.
3. Repeat normal-API arrival/cancel/recycle cycles (not forced IDs), then use at
   least ten paired batches for the dynamic-service delta.
4. Add backend support for transferring an initialized sampler chain before
   allowing `backend_sampling` with dense remapping; the current combination
   must continue to return HTTP 400.
5. For kernels, timestamp Q8_1 preparation and MMV dispatch separately inside
   the exact plugin microbenchmark. Revisit only the M=2048 N=2 and N=4 shapes;
   do not promote the current selector without a server win.

Rebuild from ROCmFPX `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` and apply
the cumulative continuation patch plus the untracked RDNA2 header retained in
the original patch:

```bash
git apply /path/to/patches/campaign-v3-runtime-kernel.patch
git apply --include='ggml/rocmfpx/rocmfpx_mmq_rdna2.cuh' \
  /path/to/patches/ROCmFPX-gfx1032.patch
```

## V4 kernel correction and next experiment

The exact logger-free ABBA microbenchmark rejects the existing four-subgroup
reduction at gate/up 10752x2048,N=4 (+81.88% latency). The V3 micro runner
accidentally enabled fenced profiling with `LOGGER=0`; it now unsets logger
variables. Preserve the independent K1 server rejection.

Next, compile and test a true two-subgroup hybrid reduction for only this exact
shape. Require CPU-reference correctness and logger-free ABBA evidence before
any resident C4x8K server run. Chunk128 remains a separate STAGE scheduler
candidate and must not be enabled during kernel comparisons.

Result: the true two-subgroup candidate also regresses (+36.23% exact-kernel
latency). Close gate/up N=4 subgroup-count tuning: one wave beats both two and
four waves. The next kernel investigation should target the unbatched
6144x2048,N=1 path (20.72% of measured C4 MMV) or alter gate/up's per-wave
algorithm; do not add more cooperative-wave variants without new ISA/resource
evidence.

Rows4 result: M=6144,K=2048,N=1 has a -0.40% paired median with a 95%
bootstrap interval crossing zero; its optimistic whole-MMV effect is about
0.2%. Mark REJECT and do not spend a server run on it. Return to the high-value
chunk128 scheduler candidate and run contemporary paired interference controls,
keeping all kernel experiment variables unset.

Paired chunk128 confirmation is complete: 10/10 valid pairs yield +977.76%
median retention and -95.923% resident ITL p95, with +22.44% new-user TTFT.
Mark KEEP as an engineering/service improvement. Before production default,
run deterministic fixed-order logits/output equivalence plus the reserved
service-EOS quality corpus. Then compare chunk96/chunk128 only if the TTFT/ITL
product requirement warrants another point; do not reopen a generic chunk
sweep.

Controlled output equivalence now passes: 10/10 corresponding output hashes
and retokenized-ID sequences match, including every 768-token resident decode.
Next production gate is the service-EOS reserved corpus and, if feasible, a
direct logits checkpoint around chunk boundaries. Do not treat fixed-output
identity as a complete quality evaluation.
