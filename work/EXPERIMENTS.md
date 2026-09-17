# Registro de experimentos

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
