# Auditoría HIP de sincronizaciones — RX 6600 XT / gfx1032

Fecha de esta ronda: 2026-09-17. La captura se hizo sin contadores PMC y con
Sunshine desinstalado. El objetivo de esta auditoría es decidir si existe una
sincronización host innecesaria que explique el rendimiento HIP, no cambiar la
semántica de `ggml` a ciegas.

## Resultado ejecutivo

No se ha encontrado una sincronización redundante que pueda eliminarse de
forma segura. Las esperas largas son esperas por trabajo GPU realmente
pendiente, no esperas de copias host ni de asignaciones. En la ruta de servidor
las llamadas largas llegan a:

```text
server_context_impl::update_slots
  -> llama_context::synchronize()
  -> ggml_backend_sched_synchronize()
  -> ggml_backend_cuda_synchronize()
  -> hipStreamSynchronize()
```

El cuello de botella es el trabajo que queda dentro de la cola antes de ese
barrier (sobre todo MMQ/MV y cuantización auxiliar), no el coste de invocar
`hipStreamSynchronize` cuando la cola ya está vacía. Por ello la acción
`eliminar sincronizaciones globalmente` queda **REJECT** por riesgo de leer
logits/KV antes de completar o de sobrescribir buffers que aún usa la GPU.

## Trazas post-Sunshine

Las dos trazas se ejecutaron con el mismo prompt corto, `-n 2`, Flash
Attention y `-ngl 99`. Son el control gfx1030 compilado para el runtime HIP y
la variante ROCmFPX; el agente físico identificado por rocprofiler es la RX
6600 XT/gfx1032. La captura nativa gfx1032 se hizo aparte con el override de
HSA desactivado.

| variante | pared (s) | kernels | unión kernels (s) | `hipStreamSynchronize` | tiempo sync (s) | p50/p95/max sync (ms) | sync >1s | solape kernel de esos waits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| llama.cpp HIP Q4_K_M | 15.892 | 3,347 | 13.340 | 409 | 13.129 | 0.008/0.120/5502 | 4 | 1,648.9–5,498.3 ms |
| ROCmFPX HIP FAST | 12.169 | 3,347 | 9.445 | 409 | 9.319 | 0.007/0.089/4050 | 4 | 1,144.8–4,046.2 ms |

La unión de kernels es el tiempo de actividad GPU sin sumar dos veces kernels
superpuestos. Para cada uno de los cuatro waits de más de un segundo, el
solape de kernels explica prácticamente toda la espera; el solape con copias
de memoria es sólo ~0.075 ms. La conclusión se mantiene en el binario nativo
gfx1032: el wrapper observó waits de servidor de aproximadamente 1.158 s,
1.246 s, 4.056 s, 2.230 s y 0.581 s, todos en la misma cadena de
`ggml_backend_sched_synchronize`.

## Mapa de llamadas y semántica

| punto fuente | evidencia | decisión |
|---|---|---|
| `ggml-cuda.cu:2641–2647`, `ggml_backend_cuda_synchronize` | Los waits largos de servidor tienen como caller `ggml_backend_sched_synchronize`; la función sincroniza la stream del backend | **NECESSARY** mientras `llama_context::synchronize()` preceda a sampling, lectura de logits o reutilización de buffers |
| `ggml-backend.cpp:2015–2018`, `ggml_backend_sched_graph_compute` | La API síncrona ejecuta el grafo async y luego sincroniza todos los backends | **NECESSARY** para esa API; no sustituir por una devolución inmediata |
| `llama-context.cpp:713–730` | `llama_context::synchronize()` además actualiza estadísticas después de que finaliza el trabajo | **NECESSARY** en el camino público actual |
| `server-context.cpp:3731–3739` | Después de `llama_decode`, si el lote produce salida, el servidor llama explícitamente a `llama_synchronize` antes de muestrear | **NECESSARY** para ese contrato; candidato futuro sólo a una API async + evento/readback bien delimitado |
| `ggml-cuda.cu:881–955` | `set/get/memset/copy` async seguido de sync en las APIs de buffer síncronas; el wrapper identifica `ggml_backend_cuda_buffer_clear` durante inicialización | **NECESSARY** por contrato de buffer; no activo como causa del wait de segundos |
| `ggml-cuda.cu:2075–2098` | El fallback de `mul_mat_id` copia IDs a host, sincroniza, reordena y vuelve a copiar | **NO OBSERVADO** en este camino LFM2.5; revisar sólo si el grafo usa MoE/`MUL_MAT_ID` |
| `ggml-cuda.cu:503` (`cudaDeviceSynchronize`) | Ruta de recuperación ante OOM del pool | **NO OBSERVADO** |
| `ggml-cuda.cu:5763` (`cudaEventSynchronize`) | Sincronización explícita de evento | **NO OBSERVADO** |

El CSV de rocprofiler no incluye stack de llamada. Para resolver esa
limitación se usó un wrapper temporal de `hipStreamSynchronize` que registra
backtrace sólo para waits >=1 ms. Los frames muestran:

- los waits de inicialización/limpieza en `llama_kv_cache` y
  `llama_memory_*`, vía `ggml_backend_cuda_buffer_clear`;
- los waits de ejecución en `llama_context::synchronize()` vía
  `ggml_backend_sched_synchronize()`;
- los cinco waits largos de servidor del binario nativo gfx1032 en
  `server_context_impl::update_slots()`.

## HIP wall vs GPU active

| variante | API HIP acumulada (s) | fracción de pared en API | GPU kernel activa (s) | fracción de pared |
|---|---:|---:|---:|---:|
| llama.cpp HIP Q4_K_M | 14.519 | 91.4% | 13.340 | 84.0% |
| ROCmFPX HIP FAST | 10.737 | 88.2% | 9.445 | 77.6% |

La diferencia FPX frente a llama.cpp en esta captura es consistente con
kernels más rápidos, no con menos llamadas de sincronización: el conteo es
idéntico (409). En el resumen de kernels, FPX redujo el coste medio aproximado
de los kernels equivalentes de MMQ de 33.5 a 23.9 ms, MV-J2 de 9.3 a 6.9 ms y
MV-J4 de 17.7 a 12.6 ms. Eso no basta para hacer viable HIP en gfx1032, pero
señala que la siguiente investigación debe centrarse en ejecución/ocupación y
selección de kernels, no en borrar barriers.

## Instrumentación reproducible

- Analizador: `work/scripts/analyze_hip_timeline.py`.
- Resultado: `work/results/profiling/hip_timeline_postsunshine.json`.
- Wrapper diagnóstico: `work/tests/hip_sync_trace_preload.cpp`.
- Librería temporal: `work/builds/hip-sync-audit/libhip_sync_trace_preload.so`.
- Logs nativos: `work/results/profiling/hip-sync-wrapper-native-gfx1032-20260917.log`.

La instrumentación no forma parte de ningún backend de producción y no se
aplicará durante benchmarks de leaderboard.

## Siguiente hipótesis KEEP/STAGE/REJECT

- **REJECT:** eliminar `ggml_backend_cuda_synchronize()` globalmente; rompe
  dependencias y no elimina el trabajo GPU pendiente.
- **STAGE:** investigar una ruta async específica para el servidor que mantenga
  un evento por lote y haga el readback de logits sólo cuando sampling lo
  necesite; requiere validación de tokens/estabilidad y no se ha activado.
- **KEEP como dirección de trabajo:** optimizar los kernels MMQ/MV,
  cuantización auxiliar, ocupación y selección gfx1032; el perfil muestra una
  oportunidad real y no un artefacto del contador de sincronizaciones.
