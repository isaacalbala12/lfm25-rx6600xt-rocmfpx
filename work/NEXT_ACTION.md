# Próxima acción

## Estado de producción tras V11

Dos perfiles, separados por forma de carga. No hay ganador universal.

| Perfil | Formato | Batch | Scheduler | Gana en |
| --- | --- | --- | --- | --- |
| `production-throughput` | FP4_FAST | `b512/ub128` + slots compactos | chunk128 fijo | 128/64 y 512/128; decode residente en reposo |
| `production-interactive` | Q4_0 | `b4096/ub128` | chunk128 fijo | 8K mixto con cuatro slots |

El backend de producción es el árbol ROCmFPX con **el plegado de batch de V11**
(commit del parche en `patches/v11-decode-batch-fold.patch`, backend
`cf4c325ec2e400c0` antes del revert de split-k; el hash vigente se registra en
`work/HARDWARE_MANIFEST.json` al publicar).

- Scheduler fijo chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- Selective gate/up BK3 sigue **KEEP** en el perfil 8K.
- Los selectores de búsqueda V8--V10 siguen desactivados por defecto.
- El árbol ROCmFPX anidado queda en `8634463` más el parche V11.

## Lo que cerró V11

1. **El decode a cuatro slots releía la matriz de pesos una vez por secuencia.**
   Las proyecciones de convolución/SSM reciben un tensor `(k, 1, 4)`, así que el
   backend las despachaba con `grid_y = 4` y cada workgroup recorría todos los
   pesos para un solo token, mientras la FFN recibe `(k, 4)` y un solo workgroup
   sirve las cuatro columnas. Plegar el batch replicado en la dimensión de
   columna da **+13,8% en decode a cuatro secuencias**, +8,4% de decode
   residente en reposo a 8K, +4,0% en la métrica de servicio C=4 128/64 y un
   12% mejor en la cola E2E. Perplexity idéntica y salidas 20/20 idénticas a C=2
   (donde el plegado sí actúa). Detalle en `work/DECODE_BATCH_FOLD_V11.md`.

2. **La GPU es bimodal.** El mismo comando repetido da 397 y 240 tok/s porque la
   tarjeta entra al azar en un estado donde MEMCLK oscila entre 1000 y 541 MHz,
   con un coste del ~40%. Ocurrió en 5 de 12 ejecuciones intercaladas. El
   "cliff" de `ubatch=512` que documentó la campaña era este estado, y la
   discrepancia de V3 entre 229,27 y 233,99 es consistente con él. No se ha
   cambiado ningún ajuste de energía. Detalle y protocolo en
   `work/GPU_BIMODAL_V11.md`.

3. **Prefill: asimetría estructural sin explicar.** `down` (`m=2048 k=10752`)
   corre a 9,25 TFLOPS mientras `gate/up` (`m=10752 k=2048`) corre a 13,9, con
   los mismos MACs y los mismos bytes por matriz. Son el 62% del grafo de
   prefill, así que cerrar esa brecha valdría ~9% de prefill. La explicación
   obvia (falta de paralelismo, arreglable con split-k) quedó **refutada**
   experimentalmente. Detalle en `work/PREFILL_LEADS_V11.md`.

## Siguiente experimento exacto

1. **Fusión elementwise en el grafo de decode.** Son 357 dispatches no-matmul
   que suman 1.675 µs de 9.154 (18,3%), y son puro overhead de lanzamiento:
   `RMS_NORM_MUL` sobre `(2048,4)` tarda 4,63 µs con batch 1 y 5,08 con batch 4,
   o sea 4× los datos por +10% de tiempo. Fusionar la cadena norm/elementwise
   por capa es el siguiente objetivo estructural.
2. **La brecha `down` contra `gate/up` en prefill**, ~9% del grafo, con la
   hipótesis de split-k descartada. Los candidatos que quedan son la longitud de
   fila (5.712 bytes por fila de pesos en `down` contra 1.088 en `gate/up`) y la
   geometría de tile para `m=2048`. Requiere trabajo de shader.
3. **Evaluación formal de calidad** de FP4_FAST y Q4_0 con `llama-perplexity`
   contra el checkpoint BF16, que sigue pendiente desde el 17 de septiembre.

No reabrir: familia de layouts FP4 (padding/planar/group4), BK_STEP, BM32,
B-first, Q8-group4, bpair, barridos de chunk o target, EWMA 65/68. Añadir a la
lista: **override de split-k por número de workgroups** (refutado en V11).
Tampoco decodificación especulativa a C=4: el análisis de
`work/DECODE_BATCH_FOLD_V11.md` muestra que a cuatro slots los pesos ya están
amortizados entre secuencias, y un borrador de 1.2B añade ~49% de tráfico para
~2,2 tokens por secuencia, lo que da ~268 tok/s frente a los 401 actuales. Sí
tendría sentido a C=1, que no es el objetivo.

## Protocolo de medida obligatorio

Ninguna medida de throughput cuenta sin decir en qué modo de reloj se tomó. Usar
`work/scripts/run_with_clock_guard.sh`, intercalar los brazos y reportar la
media del modo rápido con el reparto de modos.

## Límites

- No cambiar perfiles de energía, drivers, firmware ni servicios. El hallazgo
  bimodal se reporta, no se actúa: fijar el perfil es una decisión de sistema.
- No usar contadores PMC.
