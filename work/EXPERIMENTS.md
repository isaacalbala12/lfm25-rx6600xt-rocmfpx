# Registro de experimentos

## V4-CONTEXT-CAPACITY-01 — KEEP

- Hypothesis: four slots can expose at least 8192 effective tokens each without
  interpreting `-c` as a per-slot value.
- Configuration: FP4_FAST, q8/q8 KV, R0/K0, `-c 34816`,
  `--kv-unified-per-slot 8704`, `-np 4`, b4096/u128.
- Evidence: `/props` reports `n_ctx=8704`; `/slots` reports four independent
  8704-token slots; 4/4 simultaneous 8192-token prompts completed.
- Weight eligibility: FP4_FAST whole-artifact BPW is 4.2771; Q4_0 is 4.7276.
- Harness change: resident-context priming is separate from measured decode,
  and promotion requires observed cache reuse rather than assuming residency.
- Decision: **KEEP** protocol and context configuration.

## V4-BASELINE-8K-01 — KEEP split baseline

- Profile A resident decode: FPX S1/S2/S3/S4 =
  113.13/184.86/225.56/265.79 tok/s; upstream Q4_0 =
  109.48/179.50/220.63/250.79. FPX C4 delta +5.98%.
- FPX C4 user p5/p50 = 65.11/66.52 tok/s; ITL p95 15.33 ms.
- Profile B simultaneous uncached 8192/256 C4: FPX 48.82 output tok/s,
  1562.17 input tok/s and TTFT p95 17.37 s; upstream 52.12, 1667.75 and
  15.82 s respectively.
- Decision: **KEEP FPX** as resident-decode control; **KEEP upstream** as the
  long-prefill control. No universal winner is declared.

Protocolo vigente desde 2026-09-17: prompts de 128 tokens generados por
`safe_corpus_cycle_v1`, 64 tokens de salida fija, tokens especiales excluidos
por `logit_bias`, caché de prompt desactivada, KV q8, `b512/ub128`, FA activado,
`-np 4 -cb`. La métrica primaria incluye prefill, cola, decode, streaming y
transporte desde el primer envío hasta la última respuesta.

## EXP-HARNESS-V2 — KEEP

- Hipótesis: el leaderboard necesitaba contabilizar tokens realmente entregados,
  TTFT, intervalos de entrega, caché efectiva, errores y hashes.
- Cambio: `work/scripts/bench_client.py` y
  `work/scripts/benchmark_llama_backend.sh`.
- Verificación: el smoke produjo 64/64 tokens, prompt efectivo 128, cero tokens
  cacheados y 102,58 tok/s en C=1.
- Corrección posterior: se eliminó la síntesis aritmética de IDs de vocabulario;
  podía introducir EOG/control. El corpus actual solo contiene tokens derivados
  de texto ordinario y bloquea especiales en la salida fija.
- Decisión: **KEEP**.

## EXP-VK-UBATCH-DPM — KEEP workaround / STAGE cause

- Hipótesis: la caída del servidor con `ubatch=512` ocurría dentro de la GPU.
- Evidencia servidor: C=1 cayó a 68,03 y C=4 a 110,14 tok/s; con `ubatch=128`
  volvió a ~101 y ~228 tok/s.
- Evidencia micro: `llama-bench` no reprodujo el fallo (PP ~2600, TG 121–125
  tok/s en ambas configuraciones).
- Evidencia trace-only: el mismo grafo n=124 tardó 65,0 ms con u128 y 271,9 ms
  con u512. Las formas y conteos fueron iguales.
- Telemetría: durante u512 la memoria alternó 541/1000 MHz; u128 mantuvo
  1000 MHz. No se cambió el perfil de energía.
- Decisión: **KEEP** `ubatch=128` en producción; causa DPM exacta **STAGE**.

## EXP-COMPACT-SLOTS — KEEP

- Hipótesis: active sequence IDs no contiguos penalizan Vulkan en C=3.
- Reproducer: `work/results/validation-v2-safe-prompt-upstream-c3`.
  Slots 0/1/2 dieron ~208–211 tok/s; conjuntos con hueco que incluían slot 3
  cayeron a ~117–126 tok/s con mclk a 1000 MHz.
- A/B explícito: `work/results/validation-v2-compact-slots-upstream-c3`
  mantuvo 197–211 tok/s usando 0/1/2.
- Cambio implementado: `LLAMA_SERVER_COMPACT_SLOTS=1` en
  `work/sources/ROCmFPX/tools/server/server-context.cpp`, que selecciona el
  menor slot libre antes de LRU. La política es opt-in y no cambia upstream.
- Verificación con cliente OpenAI sin `id_slot`:
  `work/results/validation-v2-rocmfpx-plugin-server-compact-c3`, cuatro tandas
  entre 205,6 y 209,2 tok/s, 12/12 respuestas correctas.
- Decisión: **KEEP**. Es obligatorio para el perfil de producción sin caché.

## EXP-ROCMFPX-PLUGIN-FINAL — KEEP

- Candidato: ROCmFPXVulkan0 + ROCmFP4_FAST + KV q8 + b512/u128 + compact slots.
- Resultado 10 pares: C1 108,01; C2 169,12; C3 207,71; C4 234,16 tok/s.
- Control upstream compacto: 100,84 / 162,97 / 205,42 / 227,83 tok/s.
- Delta emparejado medio: +7,19% / +3,77% / +1,26% / +2,89%.
- C4 formal (200 solicitudes por backend): 233,99 vs 226,65 tok/s; delta
  +3,30%, IC bootstrap 95% +2,77 a +3,84%; 0 fallos.
- Tradeoff simultáneo C4: TTFT p95 351 ms FPX vs 309 ms upstream; E2E p95
  1113 vs 1140 ms; VRAM 1,85 vs 2,00 GiB aproximadamente.
- Llegadas 100 ms: 223,69 vs 209,91 tok/s, TTFT p95 116 vs 193 ms.
- Decisión: **KEEP**, mejor configuración de producción actual.

## EXP-ROCMFPX-INTEGRATED-INTDOT — REJECT for production / KEEP kernels

- Cambio previo: registro de pipelines MMQ q8_1 FP4/FP4_FAST e int-dot por
  defecto, con `GGML_VK_ROCMFPX_INTDOT=off` para A/B.
- Criba contemporánea: mediana C4 229,37 tok/s, similar a upstream 229,91 y
  por debajo del plugin 236,98; TTFT también peor que upstream.
- Decisión: **REJECT** como motor de producción; **KEEP** como banco de kernels
  y fallback experimental.

## EXP-WORKLOAD-SHAPES-V2 — split recommendation

| Perfil | Upstream C1 | FPX C1 | Upstream C4 | FPX C4 | Ganador C4 |
| --- | ---: | ---: | ---: | ---: | --- |
| 128/64 | 100,8 | 108,0 | 226,7 | 234,0 | FPX |
| 512/128 | 93,9 | 98,1 | 182,6 | 186,3 | FPX |
| 2048/256, b4096/u128 | ~65,7 | ~65,9 | 101,7 | 100,0 | upstream |
| 7680/512, b4096/u128 | — | — | 92,4 | 88,6 | upstream (exploratorio) |

- El cruce procede sobre todo del prefill/TTFT: FPX conserva decode y menor
  VRAM, pero pierde con prefijos largos. La ruta integrada FP4_FAST tampoco lo
  corrige (94,9 tok/s C4 en 2048/256).
- `batch=4096/ubatch=128` mejora 2048/256 sin reactivar el cliff de u512.
- Decisión: FPX **KEEP** para carga corta/media; upstream **KEEP** para carga
  larga. No se combinan backends dentro de un experimento.

## EXP-FP4-ARITHMETIC-SHADER — REJECT

- La variante aritmética redujo el microbenchmark directo a PP 2206 y TG
  131,74 frente a PP 2248 y TG 132,85 restaurados, sin ganancia de servidor.
- Se revirtió el shader. Decisión: **REJECT**.

## EXP-HIP-SYNC — REJECT barrier removal / KEEP kernel work

- Las 409 sincronizaciones observadas esperan trabajo GPU real; los waits largos
  solapan los kernels pendientes. Eliminarlas rompería lectura de logits/KV.
- ROCmFPX reduce el tiempo de MMQ/MV, pero HIP sigue muy por detrás de Vulkan
  en gfx1032.
- Decisión: quitar barreras **REJECT**; optimizar/portar MMQ/MV **KEEP**.

## EXP-QUANT-SCREEN-V2 — KEEP FAST; reject alternatives

- Criba contemporánea C1/C4, tres tandas por celda salvo FAST (diez):
  FP4_FAST 108,0/234,2; FAST_COHERENT 103,7/228,0; Q2 122,9/220,6;
  FP4 92,7/184,5; Q3 86,3/163,2; Q4_0 100,8/227,8; Q4_K_M
  94,5/213,0 tok/s.
- Q2 usa solo 1,42 GiB y gana C1 bruto, pero falla las tres pruebas de calidad:
  repite frases, no devuelve `alpha beta gamma` y no produce el JSON pedido.
- FAST_COHERENT, FP4, Q3 y Q4_K_M no alcanzan al ganador C4. Q4_0 se mantiene
  como baseline estándar y Q4_K_M como baseline orientado a calidad.
- Decisión: FP4_FAST **KEEP**; Q2 **REJECT quality**; los demás candidatos
  ROCmFPX **REJECT performance** para este perfil de producción.

## EXP-VLLM-HIP — REJECT for this deployment

- vLLM ROCm FP16 histórico: ~45,7 tok/s C4 y ~6,94 GiB VRAM, muy por debajo de
  Vulkan. Mantener como control funcional, no como candidato de producción.
- Decisión: **REJECT** para RX 6600 XT / C<=4.

## EXP-V3-HARNESS-VALIDITY — KEEP

- Se separaron `controlled_fixed_output` y `service_eos_enabled`; el segundo ya no bloquea EOS ni otros tokens especiales.
- El orquestador devuelve 3 y conserva `status=INVALID` si falla finalización, presupuesto fijo, conteo, prompt efectivo o política de caché. Telemetría ausente ya no significa cero.
- Se registran ejecutable y objetos mapeados, hash del modelo antes/después y sampler local reproducible u opción explícita sin sampler.
- Ocho tests unitarios pasan. Smoke fijo y servicio: `work/results/v3-harness-*`.
- Decisión: **KEEP**.

## EXP-V3-SPARSE-PHYSICAL-SEQUENCES — STAGE

- Reproductor original: C3 compacto 199,77–201,76 tok/s; `{0,1,3}` 131,18–131,91; `{0,2,3}` 131,33–132,25. C2 compacto 163,79–163,95; `{0,3}` 97,18–98,79.
- La traza demuestra que `split_equal(sequential=true)` parte conjuntos dispersos en dos microbatches recurrentes por paso.
- Relajar directamente el selector produjo asserts de máscara de atención y se revirtió (**REJECT** para ambas variantes).
- Candidato: IDs físicos densos separados de IDs lógicos, lote ordenado por ID físico y migración diferida hasta el final de `post_decode()`.
- El reproductor normal con cuatro duraciones, llegada escalonada, desconexión y reciclaje termina correctamente (`work/results/v3-dynamic-dense.json`).
- Las mejores tandas C3 recuperan 176,98–193,93 tok/s, pero otras caen a 91,7–98,5 con batches densos y mclk alternando 541/1000 MHz.
- Decisión: **STAGE**. Falta confirmación C4 A/B/B/A estable y logits; el camino sigue opt-in y no admite speculative decoding.

## EXP-V3-PLUGIN-PROFILE — KEEP evidence

- `ROCmFPXVulkan0` ejecuta `extensions/rocmfpx-vulkan/backend`, no el Vulkan integrado.
- Decode FP4_FAST usa RHS Q8_1 y `mul_mat_vec_rocmfp4_fast_q8_1_f32` para N pequeño.
- Prefill 2048/u128 está dominado por matmuls FP4_FAST gate/up y down; véanse `work/PLUGIN_EXECUTION_MAP.md`, `work/SHAPE_CENSUS_V3.csv` y `work/PROFILE_V3.md`.
- Decisión: **KEEP** como evidencia; siguiente familia: GEMV FP4_FAST N=1/2/4, aún sin variante promocionable.

## EXP-V4-PREFILL-INTERFERENCE-R0K0 — KEEP evidence / REJECT scheduling

- Fixed control: ROCmFPXVulkan0 FP4_FAST (4.2771 artifact BPW), q8/q8 KV,
  R0/K0, 9216 tokens per slot, backend ubatch 128.
- One uncached 8192-token prefill reduced resident decode delivery to 1.01%,
  1.23% and 1.45% of control with respectively 1, 2 and 3 active decoders.
- Decoder ITL p95 rose from single-digit/low-double-digit milliseconds to
  2145–2189 ms while the new request reached first token in about 4.3 seconds.
- Per-user variation remained negligible; all resident users stalled together.
- Evidence: `work/results/v4-profile-c-fpx-q8/`.
- Decision: evidence **KEEP**; current unlimited logical prompt scheduling is
  **REJECT** for interactive concurrent service. Prototype a bounded prompt
  chunk per scheduler iteration without changing the ubatch control.

## EXP-V4-SCHED-CHUNK128 — STAGE

- Change: opt-in `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` caps prompt tokens
  admitted from one slot per logical scheduler iteration. Backend ubatch stays
  at 128; default zero preserves the old behavior.
- With 1/2/3 resident decoders plus one uncached 8K prefill, decode retention
  rises from 1.01/1.23/1.45% to 11.28/13.35/15.63%.
- Resident ITL p95 falls from 2145–2189 ms to 85–90 ms. New-user TTFT rises
  from about 4.30 seconds to 5.06–5.27 seconds.
- All output/cache/uncached-prefill invariants pass and per-user fairness is
  preserved. Evidence: `work/results/v4-profile-c-fpx-q8-chunk128/`.
- Decision: **STAGE**. Compare chunk256, then check resident C4 without a fresh
  prefill before considering promotion.

Follow-up:

- Chunk256 retains only 6.76/7.76/9.20% and yields 156–161 ms ITL p95, versus
  chunk128 at 11.28/13.35/15.63% and 85–90 ms. Its TTFT advantage is only
  0.44–0.50 seconds. Chunk128 remains the preferred interactive candidate.
- Chunk128 resident C4 median is 264.01 tok/s (263.32/264.01/274.02) versus
  control 265.79, a -0.67% guardrail delta inside run variability. All runs
  are VALID with 8188 cached prompt tokens per request.
- Two pre-measurement harness rejections are retained under
  `v4-profile-a-fpx-q8-chunk128-invalid-*`; neither enters statistics.
- Decision remains **STAGE** pending paired repetition and Profile B guardrail.

Profile B guardrail completed:

- Three valid C4 8192+256 repetitions give a chunk128 median 48.125 tok/s,
  17.687 s TTFT p95 and 21.278 s wall, versus control 48.818 tok/s, 17.372 s
  and 20.976 s: -1.42%, +1.81% and +1.44% respectively.
- This is a bounded regression compared with the 10–15x interference-retention
  gain, but it is not a ten-pair contemporary ABBA series.
- Decision remains **STAGE**; proceed to paired confirmation.

## EXP-V4-DMMV-PHASE-PROFILE — KEEP evidence

- Dedicated paired Vulkan timestamps isolate Q8_1 preparation from FP4_FAST
  MMV without mixing them into node-level query indices. Profiling forces a
  fence and its wall throughput is excluded.
- Seven resident-8K decode graphs: C1 spends 5.056/72.457 ms in Q8/MMV
  (Q8 6.52%); C4 spends 1.203/57.661 ms (Q8 2.04%).
- C4 MMV is led by gate/up N=4 (22.833 ms), down N=4 (12.153 ms), and an
  unbatched 6144x2048 N=1 path (11.946 ms).
- Gate/up has 420 MMV calls but 210 Q8 preparations: graph-local RHS reuse is
  already active and resets safely at graph boundaries.
- Decision: evidence **KEEP**; Q8 reuse experiment **REJECT as duplicate**.
  Next optimization must target a measured MMV shape, not all N=4 shapes.

## EXP-V4-KERNEL-GATEUP-N4-LARGE — REJECT

- Added an exact selector for the existing four-subgroup hybrid reduction only
  at gate/up M=10752, K=2048, N=4. Selection proof confirms no neighboring
  shape changed, and CPU-reference correctness passes.
- Found and corrected a microbenchmark defect: Vulkan loggers are enabled by
  variable presence, so the V3 runner's `LOGGER=0` still enabled fenced
  profiling. The old 1.69--1.72 ms micro timings are invalid as hot-pipeline
  measurements; the independent K1 server regression remains valid.
- With all logger variables absent, ten ABBA pairs give 60.840 us for subgroup
  versus 110.655 us for gateup-n4: **+81.88% latency**, a clear regression.
- Decision: **REJECT** without a server run. Implement a genuinely different
  two-subgroup geometry next; do not reuse the four-subgroup K1 pipeline.
- Evidence: `work/KERNEL_MICROBENCH_V4.md` and
  `work/results/v4-kernel-gateup-n4-micro-abba10/`.

## EXP-V4-KERNEL-GATEUP-N4-2SG — REJECT

- Compiled a true 64-thread/two-subgroup hybrid pipeline and selected it only
  for gate/up M=10752, K=2048, N=4. Exact correctness and selector isolation
  pass.
- Ten logger-free ABBA pairs give 61.095 us for one subgroup versus 83.230 us
  for two subgroups: **+36.23% latency**.
- Decision: **REJECT** without a server run. One wave is decisively better than
  two and four waves for this shape. Close subgroup-count tuning here.

## EXP-V4-KERNEL-CONV-N1-ROWS4 — REJECT

- Halved rows accumulated per wave from eight to four only for FP4_FAST
  M=6144, K=2048, N=1. Selector isolation passes.
- Ten logger-free ABBA pairs: raw medians 367.390 us control versus 363.740 us
  candidate (-0.99%). Pair median is -0.40%, bootstrap 95% interval
  [-1.43%, +0.19%].
- The stock CPU-reference corpus has no exact case (0/0), so correctness is
  explicitly unproven rather than inferred.
- Decision: **REJECT**. Statistical signal and global ceiling are too small to
  justify the extra pipeline or a server campaign.

## EXP-V4-SCHED-CHUNK128-PAIRED10 — KEEP engineering

- Ten control/chunk128 pairs alternated A/B and B/A for three resident 8K
  decoders plus one uncached 8K prefill. All 20 runs are VALID; no exclusions.
- Median decode retention rises 1.455% -> 15.702%. Paired improvement is
  +977.76%, bootstrap 95% interval [+973.09%, +984.93%].
- Resident ITL p95 falls 2188.74 -> 89.23 ms: -95.923%, interval
  [-95.932%, -95.900%]. New-user TTFT rises 4308.79 -> 5268.14 ms:
  +22.44%, interval [+21.99%, +23.15%].
- Same loaded artifacts and equal per-user event counts were verified in every
  arm. Resident C4 and simultaneous-prefill guardrails remain -0.67% and
  -1.42% respectively in their prior three-run checks.
- Decision: **KEEP engineering/service value**. Do not make it the production
  default until deterministic output/logit equivalence and reserved quality
  validation are complete.

Follow-up output identity:

- A fixed-order control/chunk128 reproduction retained full text and
  retokenized IDs. All 10 corresponding outputs match exactly, including six
  768-token decoder outputs (baseline and interference).
- Decision remains **KEEP engineering**. This closes an initial output-state
  corruption check, but not logits equivalence or the service-EOS quality
  corpus required for a production default.
# V3 continuation: runtime remap and exact plugin microbenchmark

## V3-RUNTIME-02 — deferred remap under active cancellation

- Hypothesis: physical-ID densification can remove the sparse recurrent
  allocator split without mixing request state.
- Change: separate lowest-slot allocation from physical remapping; preserve
  host/backend sampling policy; assert physical identity and recurrent
  positions; move only after pending results are consumed.
- Evidence: forced holes 0/1/3 with three live survivors and immediate reuse.
  All 12 completed requests met their output budgets. R1 reduces the sparse
  middle-hole cycle from 4526 ms to 2546 ms. Nine of twelve outputs are exactly
  equal to R0; three differ under non-identical concurrent batch ordering.
- Backend sampling: reproduced a double-initialization abort; R1 now rejects
  that combination with HTTP 400.
- Historical range error: not reproduced, not declared solved.
- Decision: **STAGE** (host sampling only).

## V3-KERNEL-01 — hybrid DMMV reduction by shape

- Hypothesis: the four-subgroup hybrid reduction can improve FP4_FAST MMVQ at
  N=2/4.
- Pipeline: `quantize_q8_1_x4 -> mul_mat_vec_rocmfp4_fast_q8_1_f32` in the
  actual plugin backend.
- Microbenchmark: large wins 1.0–12.6% on selected M=2048/N=2 and N=4 shapes,
  but loses 39–49% on M=6144/10752 at N=2. CPU-reference checks pass.
- Server: K0 173.37 versus K1 164.20 aggregate tok/s at C4; C1 80.45 versus
  80.04. All slow batches retained; clocks were variable.
- Decision: **REJECT** for production. Preserve only as an experimental switch
  and evidence for a timestamped shader-level follow-up.
# V5 concurrency service checkpoint

## EXP-V5-QUALITY-CHUNK128 — KEEP production

- Service EOS: 7/7 valid in both arms; 7/7 exact outputs, finish reasons and
  token counts, including 8886-token retrieval and long generation.
- Evidence: `work/results/v5-quality-service-eos-r3`.

## EXP-V5-SCHED-CHUNK96 — REJECT

- ITL 89.190 -> 82.677 ms and retention 15.659% -> 16.627%, but TTFT
  5270.945 -> 6646.088 ms (+26.09%). Remaining pairs cancelled by the declared
  early-rejection rule.

## EXP-V5-TIMELINE-CHUNK128 — KEEP diagnostic

- 63 mixed 128-prompt/3-decode batches: 79.961 ms median, 87.554 ms p95.
  Decode-only C3: 11.561 ms median. Mixed GPU work, not scheduler idle time,
  dominates the 89-ms ITL.

## EXP-V5-SHORTCONV-REBATCH — REJECT hypothesis

- `6144x2048 N=1` is `[6144,n_seq_tokens=1,n_seqs=4]`. Twenty-two calls per
  graph prove all four batch planes already share each recurrent-layer call.

## EXP-V5-PREFILL8K-PROFILE — KEEP evidence

- Final full N=128 tile: gate/up 23.500 ms (32.79%), down 16.684 ms (23.28%),
  Flash Attention 16.566 ms (23.11%), short-conv 5.390 ms (7.52%).
- Fenced profiler throughput is not a service baseline. Gate/up is the next
  shader target; 8K Flash Attention is now material and remains open.

## EXP-V5-KERNEL-GATEUP-N128-PACKED32 — REJECT

- Changed only the real plugin shader for the medium FP4_FAST x Q8_1 MMQ path:
  four byte loads became two aligned uint loads plus exact reconstruction.
- Exact gate/up `10752x2048x128` correctness passed against the CPU reference.
- Ten logger-free ABBA pairs: 427.475 us control versus 434.800 us candidate;
  paired regression +1.880%, bootstrap 95% CI [+1.692%, +2.071%].
- Decision: **REJECT**, no server run. ROCmFPX `d92f6a4` reverts the candidate
  and reproduces the control library hash exactly. Preserve the evidence, but
  do not retry this packed-read implementation.

## EXP-V5-KERNEL-PREFILL-WIDE-N128 — REJECT

- Changed the real plugin medium MMQ tile from 64x64 to 32x128, retaining 256
  threads and all FP4_FAST values. Exact gate/up and down correctness pass.
- Ten ABBA pairs: gate/up paired -0.125% with 95% CI
  [-0.257%, +0.194%]; down +0.367% with CI [-0.068%, +0.541%].
- Decision: **REJECT**, no server run. Neither shape reaches the 0.75% stage
  threshold, and down trends in the wrong direction. ROCmFPX `a6dd6ad`
  restores the production tile and exact control library hash.

## EXP-V5-KERNEL-PREFILL-BKSTEP2-GLOBAL — REJECT / selective STAGE

- FP4_FAST `BK_STEP=2` passes exact gate/up and down N128 correctness.
- Ten ABBA pairs: gate/up improves -2.400% (95% CI
  [-2.952%, -2.226%]); down regresses +4.712% ([+4.458%, +5.041%]).
- The profile-weighted global estimate is a 0.310% regression, so the global
  candidate is **REJECT** without a server run.
- The gate-only result is a **STAGE hypothesis** with a measured ~0.787% global
  ceiling. Follow up only with a distinct gate/up pipeline; never route down or
  decode through BK_STEP=2. Control is restored at ROCmFPX `f7a53ab`.

## EXP-V5-KERNEL-GATE-SELECTIVE-BKSTEP2 — ARCHIVE COMPOSABLE

- Added a separate BK2 SPIR-V and exact shape selector, disabled by default.
  Logs prove gate/up uses BK2 while down remains on the control pipeline.
- Four CPU-reference cases pass: gate N120/128/129 and down N128.
- Ten same-binary ABBA pairs: gate/up -2.601% (95% CI
  [-2.862%, -2.211%]); down -0.005% ([-0.410%, +0.373%]).
- Three-run simultaneous 8K C4: 48.084 -> 48.600 output tok/s and 1538.70 ->
  1555.19 input tok/s (+1.072%); TTFT p95 improves 1.31%. Corresponding
  generated texts, finish reasons and token counts match 12/12.
- One 3D+1P guardrail is favorable on retention, ITL and TTFT, but is not a
  statistical confirmation.
- Final ten-pair AB/BA Profile B validation: all pairs valid and favorable;
  aggregate throughput +0.486% median, 95% CI [+0.371%, +0.705%]; TTFT p95
  -0.693%; E2E p95 -0.485%; exact corresponding outputs 10/10.
- Decision under the current leverage policy: **ARCHIVE COMPOSABLE**. The
  +0.486% effect is reproducible, correct and cheap enough to preserve, but it
  is not promoted alone and receives no further tuning now. ROCmFPX `7838dd2`
  removes it from the production build; candidate/revert patches, selector and
  raw paired results are retained for later composition.

## EXP-V5-FA-RDNA2-NO-OCCUPANCY-LIMIT — REJECT

- Selection trace proves the executed path is the plugin scalar integer-dot
  `flash_attn_f32_f16_aligned` shader with Q8_0/Q8_0 KV, HSK=HSV=64, wave32,
  128 threads, Br=8/Bc=32/D_split=8 and aligned accesses.
- Candidate removes the synthetic 26-KiB occupancy allocation only for RDNA2
  large-N 64-wide prefill; all decode and other shapes stay on control.
- Three logger-free 8K C4 runs: 1855.28 -> 1852.67 input tok/s median
  (-0.141%). Timestamp-only common long tiles improve roughly 0.7–1.6% local,
  giving at most ~0.35% predicted global leverage at the measured 23.11% share.
- Decision: **REJECT**. Correct but below the 0.75% global threshold and no
  server win. ROCmFPX `e7ec6c2` restores production.

## EXP-V5-FA-RDNA2-BC64 — REJECT / FA closed for V5

- Added an opt-in `Bc=64` scalar FA tile only for RDNA2, Q8/Q8,
  HSK=HSV=64, N>=32 and KV>=1024.
- Added exact CPU-reference and performance coverage for LFM2 C4 8K:
  nh=8, `nr23=[4,4]`, KV=8192 and N=32. Both control and candidate pass.
- Logger-free ABBA synchronized operation medians: Bc32 7626.41 us, Bc64
  8738.13 us, or **+14.58% latency**.
- Decision: **REJECT immediately**, without a server run. This exceeds the 5%
  micro-regression cutoff. Patch and raw evidence are archived; ROCmFPX
  `55dfdf0` restores the exact production backend hash. Flash Attention is
  closed for V5 absent a new >0.75%-global-leverage hypothesis.

## EXP-V5-KERNEL-DOWN-N4-HYBRID — REJECT

- Hypothesis: isolate the existing four-subgroup hybrid reduction to the exact
  decode down projection `M=2048,K=10752,N=4`, avoiding the rejected N-only
  selector. Its measured MMV share is 21.08%, so a substantial local win would
  have useful global leverage.
- Selection logging proves `large_hybrid` executed only on the target shape;
  control and candidate both pass the CPU-reference operation test.
- Contemporary logger-free ABBA, 20 samples per arm: subgroup median 58.020 us,
  hybrid median 68.315 us, **+17.744% latency**.
- Decision: **REJECT immediately**, no server run. The historical -1.02%
  signal does not reproduce on the current backend/build. Patch, selector proof
  and all samples are retained; ROCmFPX `6f6a8ce` restores production.

## EXP-V5-SCHED-DECODE-AWARE-IDLE — ARCHIVE COMPOSABLE / not production

- Unlimited idle prefill was stopped after one pair: the first prompt filled
  the 4096-token batch, harmed fairness and moved 48.684 -> 47.890 tok/s.
- The bounded candidate uses 512 tokens per request when no decoder is active
  and the production 128 when one or more decoders are active.
- Three simultaneous-prefill ABBA pairs, all valid and output-identical:
  aggregate input/output +0.259% median, observed range +0.099% to +0.390%;
  E2E p95 -0.259%. TTFT p95 median -0.230%, with one pair at +0.033%.
- One 3D+1P guardrail is slightly unfavorable: retention -0.475%, ITL p95
  +0.713%, TTFT +0.321%. This is one pair and consistent with noise, but the
  candidate does not improve the primary workload.
- Decision: **ARCHIVE COMPOSABLE / INCONCLUSIVE guardrail**. Preserve the
  low-cost patch and evidence, but keep fixed chunk128 in production. ROCmFPX
  `cce47ba` restores the production scheduler.

## EXP-V5-KERNEL-GATE-N4-ARITH-UNPACK — REJECT

- Added a separate opt-in DMMV pipeline for exact gate/up decode
  `10752x2048x4`; selection logs prove the normal one-wave reduction plus the
  arithmetic unpack pipeline executed.
- The candidate preserves every FP4_FAST code and scale. Both arms pass the
  exact CPU-reference operation test.
- Ten ABBA pairs: LUT median 65.075 us; arithmetic median 94.145 us;
  **+44.672% latency**.
- Decision: **REJECT**, without server testing. The attempted LDS-to-ALU trade
  is decisively unfavorable on gfx1032. Patch, selector proof, correctness and
  all raw samples are retained under
  `work/results/v5-kernel-gate-n4-arith-unpack/`.

## EXP-V5-KERNEL-GATE-N4-DUALACC — REJECT

- Added an exact opt-in gate/up N=4 shader with two alternating accumulator
  banks. Selection logging proves it kept the one-wave subgroup reduction and
  executed only the target pipeline.
- Control and candidate pass CPU-reference correctness.
- Ten ABBA pairs: 64.680 us single-bank versus 71.065 us dual-bank,
  **+9.872% latency**.
- Decision: **REJECT**, without server testing. The extra live accumulators and
  final merge cost more than the removed dependency pressure. Patch and raw
  evidence are retained in `patches/` and
  `work/results/v5-kernel-gate-n4-dualacc/`.
- Production was rebuilt after the revert at ROCmFPX `7c4b5c0`; the backend
  SHA-256 is `567bead1147b1215f7f0c968fabef1a0ca91e92596d7a68684e6dfac6ef641d0`.
  An exact gate/up N=4 CPU-reference smoke test passes with all experimental
  selector variables unset.

## EXP-V6-ATREX-ADAPTER — KEEP tooling

- Audited official Atrex at `d83b01a`; its supervisor/ABBA/memory concepts are
  reusable, while its evaluator is coupled to `kernel.py`/Triton/FlyDSL.
- Added a bounded exact-plugin adapter with reversible allowlisted patches,
  taboo memory, hard correctness, route proof, artifact hashes, ABBA and
  restoration checks.
- A dry run exposed a stale-plugin flaw. The records are retained INVALID; the
  fixed evaluator builds `ggml-rocmfpx-vulkan` and rejects identical patched
  hashes. Decision: **KEEP tooling**.

## EXP-V6-GATEUP-BK-SEARCH — selective BK3 STAGE

- Automated focal search: BK1 +4.900%, BK3 -3.891%, BK5 +18.052%, BK8
  +84.237% on `10752x2048x128`.
- BK3 wins 3.85--4.29% at gate/up N=120/128/129 but regresses down N128 by
  2.122%. Global BK3 is **REJECT**.
- A gate/up-only BK3 pipeline improves 428.975 -> 412.940 us over five ABBA
  pairs: -3.859%, 95% [-3.993%, -3.521%], with correctness and route proof.
- Three valid Profile-B pairs all favor it: input/output +1.367% median, TTFT
  p95 -1.240%, E2E p95 -1.347%, identical outputs 3/3.
- Decision: **STAGE** pending ten pairs plus 3D+1P/resident/quality guardrails.
  Production was restored to backend `40f6b9c...b25b40`.
