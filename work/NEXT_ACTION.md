# Próxima acción

## Producción

Ver `work/STATE_OF_THE_ART_V11.md` para la configuración completa, los números y
todo lo descartado con su evidencia. Resumen:

| Perfil | Formato | Claves |
| --- | --- | --- |
| `production-throughput` (128/64, C=4) | FP4_FAST | `-b 512 -ub 128`, KV q8, `-np 4 -cb`, slots compactos, chunk128 |
| `production-interactive` (8K, 4 slots) | Q4_0 | `-b 4096`, `--kv-unified-per-slot 9216`, `--cache-prompt`, chunk128 |

Backend: ROCmFPX `8634463` + el plegado de batch de V11
(`patches/v11-decode-batch-fold.patch`), con interruptor
`GGML_VK_MMV_NO_FOLD_BATCH` y traza `GGML_VK_MMV_TRACE_FOLD`.

Métrica primaria 128/64: **108,10 / 173,84 / 220,65 / 250,36 tok/s** en C=1..4.
Perfil 8K: TTFT 4772 ms, ITL p95 81,3 ms con Q4_0.

## Lo que cerró V11

1. **Plegado de batch en decode: +13,8% a cuatro secuencias.** Las proyecciones
   de convolución/SSM recibían `(k, 1, 4)` y se despachaban con `grid_y = 4`,
   releyendo los pesos una vez por secuencia. Detalle en
   `DECODE_BATCH_FOLD_V11.md`.
2. **Ningún motor moderno soporta esta GPU.** vLLM, SGLang y Lucebox no incluyen
   código para ningún gfx103x. ROCmFPX funciona porque compila shaders en
   Vulkan para la GPU que encuentra. `ENGINE_SUPPORT_V11.md`.
3. **La GPU es bimodal** (1000/541 MHz), el perfil `3D_FULL_SCREEN` bajó el modo
   lento de 5/12 a 1/10, y el protocolo de medida lo tiene en cuenta.
   `GPU_BIMODAL_V11.md`.
4. **Primera medición de calidad de la campaña.** Los tres formatos cuantizados
   cuestan entre +9% y +16% de perplexity frente a Q8_0; Q4_K_M es el mejor.
   `QUALITY_V11.md`.
5. **Retractación**: el cliff de `ubatch` **no** era el estado del reloj. Se
   reproduce con el perfil fijado (2,24× de throughput, 3,6× de TTFT).
   `ROUND2_V11.md`.

## Siguientes experimentos, por valor esperado

1. **La brecha `down` en prefill** (~9% del grafo). `m=2048 k=10752` corre a
   9,25 TFLOPS contra 13,9 de `m=10752 k=2048`, con los mismos MACs y bytes. Se
   han eliminado split-k, selección de tile y cualquier efecto en decode (8% de
   brecha allí). Queda como sospechoso la geometría de fila: 5.712 bytes por
   fila de pesos contra 1.088. Requiere leer `mul_mmq.comp` en profundidad.
2. **Fusión add+rms por encima de batch 1.** Implementada pero con la puerta
   `ggml_nrows(...) == 1`, así que está desactivada en toda concurrencia > 1:
   38 dispatches y 85 µs de un grafo de 10,3 ms. Necesita dimensionar el buffer
   de parciales para `nrows × num_partials` y un shader que emita parciales por
   fila. Ojo: el `add_rms.comp` no aparece en fuente en el árbol, solo las
   pipelines, así que hay que localizar primero de dónde sale.
3. **Evaluación formal de calidad.** Las cifras de perplexity vienen de dos
   corpus propios. Falta un corpus reservado, el checkpoint BF16 en GGUF y
   divergencia KL contra los logits de referencia.
4. **Recompilar vLLM con `gfx1032`** si se quiere agotar esa vía: 1-3 h, 10-20 GB
   y riesgo real, y partiría en desventaja porque los kernels 4-bit tendrían que
   venir de Triton (y quitar el desempaquetado FP4 no ayuda aquí: Q8_0 fue 16%
   más lento en pp128).

## No reabrir

Layouts FP4 (padding/planar/group4), BK_STEP, BM32, B-first, Q8-group4, bpair,
barridos de chunk o target, EWMA 65/68, override de split-k por workgroups,
KV q4_0, `ubatch >= 256`, decodificación especulativa a C=4, y las variantes
`ROCMFP4_FAST_DOWN_*` / `GATEUP_*` de V8 (definidas como `#ifdef` muertos; el
mejor candidato daba −2,16% local ≈ 0,5% del grafo de prefill).

## Protocolo de medida

Ninguna cifra de throughput cuenta sin decir en qué modo de reloj se tomó. Usar
`work/scripts/run_with_clock_guard.sh`, intercalar los brazos, y reportar la
media del modo rápido con el reparto de modos. Queda ~1 ejecución lenta de cada
10 incluso con el perfil fijado.

## Límites

- No cambiar perfiles de energía, drivers, firmware ni servicios más allá de lo
  ya autorizado (`3D_FULL_SCREEN`).
- No usar contadores PMC.
