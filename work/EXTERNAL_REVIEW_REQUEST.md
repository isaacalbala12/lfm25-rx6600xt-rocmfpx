# Petición de revisión externa: LFM2.5-2.6B en RX 6600 XT (gfx1032)

Copia todo este documento como prompt. Es autocontenido, pero además **el código
y todas las mediciones están publicados**:

**https://github.com/isaacalbala12/lfm25-rx6600xt-rocmfpx**

---

## Qué te pido

Un análisis técnico de **por qué el prefill de un GEMM concreto rinde 1,5× menos
que otro con los mismos MACs y los mismos bytes**, y una opinión sobre si quedan
palancas grandes que no hayamos visto. Al final hay seis preguntas numeradas.

**Lo que NO me sirve:** matrices de características, listas de herramientas, o
sugerencias de "prueba X framework". El espacio de motores y de cuantizaciones ya
está cerrado con mediciones (§6). Lo que necesito son **hipótesis concretas y
falseables** sobre kernels, y razonamiento sobre los números que doy.

---

## 1. Hardware

- **AMD Radeon RX 6600 XT**, Navi 23, **gfx1032**, RDNA2.
- 32 CU, **wave32**, 64 KB de LDS por CU, **sin matrix cores** (RDNA2 no tiene
  WMMA; RADV reporta `matrix cores: none`).
- 8 GB GDDR6, bus de 128 bits a 16 Gbps → **256 GB/s teóricos**.
  Medido: **222 GB/s** es el pico práctico que alcanza nuestro mejor kernel (una
  proyección de salida `m=128000` en decode, streaming de pesos casi puro).
- FP32: 2048 SP × 2 × 2,589 GHz ≈ **10,6 TFLOPS**.
- Producto punto int8 (`V_DOT4_I32_I8`): **no sé la tasa real en gfx1032.** El
  rango posible es 21–42 TOPS según si emite a media o a tasa completa. Es una
  incógnita relevante (pregunta 2).
- CPU: Ryzen 5 1500X, **4 núcleos**. Un rebuild del backend tarda ~5 minutos.
- La GPU entra al azar en un estado donde el reloj de memoria oscila entre 1000
  y 541 MHz, con un coste del ~40% (§5.4).

## 2. Stack de software

- **ROCmFPX**, un fork de llama.cpp con un backend Vulkan propio.
- El driver Vulkan es **RADV (Mesa 26.0.8)**. Los shaders son **SPIR-V generados
  en tiempo de compilación** por shaderc. Esto es lo que permite que esta GPU
  funcione en absoluto (§6.3).
- Compilado con un GCC 16 aislado; el backend necesita precargar su `libstdc++`.
- **La ruta HIP/ROCm está descartada por medición**: los mismos kernels por HIP
  dan 1,7 tok/s frente a 132 tok/s por Vulkan en esta tarjeta. gfx1032 no está en
  el soporte oficial de ROCm.

## 3. Modelo

- **LFM2.5-2.6B** de LiquidAI. Arquitectura híbrida: **30 capas, 22 de
  convolución/SSM y 8 de atención**.
- hidden 2048, vocab 128000, **GQA 32 cabezas Q / 8 KV**, head_dim 64.
- Cuantizado a **ROCmFP4_FAST**: 4,25 bpw, **1,442 GB**, bloques de 17 bytes con
  4 palabras de código FP4 y una escala. La ruta usa **producto punto int8 con
  activaciones cuantizadas a q8_1**.
- Alternativa: **Q4_0** estándar, 4,70 bpw, 1,48 GB.
- Referencia casi sin pérdida: Q8_0, 8,50 bpw.

## 4. Carga de trabajo

Cuatro peticiones concurrentes, dos perfiles:

**Perfil A (métrica primaria):** 128 tokens de entrada, 64 de salida, C=1..4.
La métrica son tok/s agregados medidos por HTTP desde el primer envío hasta la
última respuesta.

**Perfil B (interactivo):** cuatro slots de 8192 tokens; tres decodificando y uno
que llega con un prompt nuevo. Métricas: TTFT del que llega, e ITL p95 (latencia
entre tokens) de los residentes durante el prefill.

## 5. Números actuales y de qué están hechos

### 5.1 Perfil A, con nuestro último cambio

| C | tok/s |
| ---: | ---: |
| 1 | 108,10 |
| 2 | 173,84 |
| 3 | 220,65 |
| 4 | **250,36** |

### 5.2 Perfil B

TTFT **4781 ms**, ITL p95 **81,6 ms**, con Q4_0. Objetivo declarado:
ITL ≤ 70 ms, TTFT ≤ 5,5 s. **El TTFT se cumple; el ITL no.**

### 5.3 Descomposición del paso de decode a C=4

Un paso de decode son **9,15 ms para 4 tokens**. Cada paso lee los 1,442 GB de
pesos, produzca 1 token u 8.

| Componente | ms | % | Naturaleza |
| --- | ---: | ---: | --- |
| Streaming de pesos al pico práctico (222 GB/s) | 6,50 | 71% | muro físico |
| Ineficiencia de los matmuls | 0,98 | 11% | kernel |
| **357 dispatches no-matmul** | 1,67 | 18% | arquitectura del backend |

El coste de dispatch no es ancho de banda. `RMS_NORM_MUL` sobre un tensor de
32 KB tarda **4,63 µs a batch 1 y 5,08 µs a batch 4**: cuatro veces los datos por
un 10% más de tiempo. Es latencia de lanzamiento y drenaje de workgroups. El
grafo tiene **524 dispatches**, de los cuales 167 son matmuls (44,8 µs de media)
y 357 son operaciones elementales, normas, copias y concatenaciones (4,7 µs de
media). Los matmuls van a **193 GB/s**, el 87% del pico práctico.

**Curva de decode medida directamente** (llama-batched-bench, 4 secuencias,
contexto corto), antes y después de nuestro cambio de §6.1:

| Secuencias | Antes | Después |
| ---: | ---: | ---: |
| 1 | 124,28 | 120,49 |
| 2 | 214,68 | 227,32 |
| 3 | 296,18 | 323,69 |
| 4 | 344,85 | **399,54** |
| 6 | 404,14 | 471,34 |
| 8 | 449,45 | **519,37** |

Antes del cambio, el tiempo por paso se ajustaba a **6,6 ms + 1,4 ms × batch**:
el término fijo es el streaming de pesos a 218 GB/s (85% del pico) y el término
por secuencia era el recorrido redundante que eliminamos.

### 5.4 Descomposición del grafo de prefill (n=127, contexto 8448)

| Familia | % del grafo de prefill |
| --- | ---: |
| gate/up `m=10752 k=2048` | 35,34% |
| down `m=2048 k=10752` | 26,64% |
| Flash attention | 13,78% |
| short-conv `m=6144 k=2048` | 8,66% |
| proyecciones `m=2048 k=2048` | 6,42% |
| resto (normas, elementales, copias) | 9,15% |

Prefill medido en aislado: **pp512 a 2468 tok/s = 13,3 TFLOPS-equivalentes**.

## 6. Lo que YA está descartado, con mediciones

No hace falta que propongas nada de esto. Cada línea costó tiempo real.

### 6.1 El cambio que sí funcionó

Las proyecciones de convolución/SSM reciben un tensor `(k, 1, 4)` — la secuencia
en `ne[2]` — así que el backend las despachaba con **`grid_y = ne12 = 4`**, y cada
workgroup recorría **toda la matriz de pesos** para un solo token. La FFN recibe
`(k, 4)` y toma la ruta `batch_n`, donde un workgroup sirve las cuatro columnas.
Plegar el batch replicado en la dimensión de columna son 12 líneas en
`ggml_vk_mul_mat_vec_q_f16` y dio **+13,8% en decode a cuatro secuencias**
(352,5 → 401,3 tok/s medidos directamente), +8,4% de decode residente en reposo,
y +7,0% sobre la métrica primaria publicada. Perplexity bit-idéntica.

### 6.2 La anomalía que NO hemos resuelto (el objeto de esta consulta)

En el **mismo shader MMQ**, con **el mismo tile `(64,64)`**, **el mismo
`split_k=1`** y **los mismos MACs y los mismos bytes de pesos por matriz**:

| n | Ruta | gate/up `m=10752 k=2048` | down `m=2048 k=10752` | Brecha |
| ---: | --- | ---: | ---: | ---: |
| 4 | mat-vec | 57,2 µs/llamada | 62,0 µs/llamada | **8%** |
| 16 | MMQ | 2,53 TFLOPS | 0,97 TFLOPS | **2,6×** |
| 127 | MMQ | 13,9 TFLOPS | 9,25 TFLOPS | **1,5×** |

Es decir: **la brecha es específica de la ruta de matmul por lotes y se estrecha
al crecer n.** A n=4, con otro shader, las dos formas cuestan casi lo mismo.

Lo que hemos eliminado **por experimento**:
- **No es split-k.** Todas las formas de prefill reciben `split_k=1` con la
  heurística de `ggml_vk_guess_split_k`. Un override por variable de entorno que
  lo sube hasta un objetivo de workgroups por CU fue neutro con 4 y catastrófico
  con 8 (pp128 cayó de 2333 a 723 tok/s).
- **No es selección de tile.** Una traza de `ggml_vk_matmul` muestra que todas
  las formas usan `wg=(64,64)` y `split_k=1`.
- **No aparece en decode**, luego no es el layout de pesos ni el tipo.

Lo que queda sin examinar: la **geometría de fila**. Una fila de pesos de `down`
mide **5.712 bytes** (336 bloques FP4 de 17 B) contra **1.088 bytes** de
`gate/up` (64 bloques). El bucle sobre k es 5,25× más largo con 5,25× menos filas
para solaparlo.

**Datos del shader que hemos leído** (`mul_mmq.comp`):
- `#define BK 32`, y `BK_STEP` con default 1 (hay un `#ifndef BK_STEP → 4`).
- Tiles por `constant_id`: `BM = 64`, `BN = 64`.
- `shared block_a_cache buf_a[BM * BK_STEP]` y `buf_b[BN * BK_STEP]`.
- El despacho con `split_k == 1` usa una rejilla `{m, n, groups_z}`.
- El shader está lleno de `#ifdef ROCMFP4_FAST_DOWN_*` y `ROCMFP4_FAST_GATEUP_*`
  (`NO_SPLIT_K`, `HOIST_STRIDES`, `NO_K_TAIL`, `B_FIRST`, `Q8_GROUP4`,
  `GATEUP_K_2048`, `SHAPE_10752_128_2048`) que **no se definen en ningún sitio
  del árbol**: son restos de una campaña anterior, con sus parches en
  `patches/v8-*.patch`.

### 6.3 Otras cosas descartadas

- **Motores alternativos.** vLLM, SGLang y Lucebox **no compilan para ninguna
  gfx103x**. Los objetos de código de vLLM son
  `gfx90a gfx942 gfx950 gfx1100 gfx1101 gfx1150 gfx1151 gfx1200 gfx1201`; sus
  kernels `rms_norm`, `fused_add_rms_norm` y `silu_and_mul` **segfaultean** en
  gfx1032 mientras las matmuls de torch funcionan. SGLang compila para
  gfx942/gfx950/gfx1151; Lucebox documenta gfx1100/gfx1151/gfx1201. Cargar el
  modelo 4-bit en vLLM sí funciona (1,72 GiB, 6,8 s); lo que no funciona son sus
  kernels.
- **Decodificación especulativa.** Medida con el borrador específico DSpark
  (5 capas, 199 MB en Q4_K_M): **−13% a una sola secuencia** (121,6 → 105,8
  tok/s), **rota a cuatro secuencias** (fallos `Invalid input batch` en 17/40 y
  4/40 peticiones), y **el backend de producción ni la carga** (aborta con
  `pre-allocated tensor (token_embd.weight) ... cannot run the operation (NONE)`).
- **`ubatch >= 256`.** 111,8 tok/s con 256 y 114,4 con 512, contra 251 con 128.
  Firma distinta del estado de reloj: 2,24× de throughput y 3,6× de TTFT.
- **KV cache `q4_0`.** Pierde el 60% del decode residente (105 vs 261 tok/s):
  flash attention tiene que descomprimir.
- **Familia de layouts FP4.** Padding a 20 bytes (+17,65% de memoria, −1,227%
  local), plano global compacto (+43,150%), agrupado de cuatro (+3,851%).
  Conclusión: la localidad de escalas domina; el cuello no está en el layout.
- **Unos 40 variantes de shader** acumuladas antes de nosotros: mejor resultado
  de servicio +1,16%.
- **Formato distinto por forma.** El ranking se invierte: Q4_0 es 15,4% más
  rápido en prefill (pp128) y FP4_FAST 7,2% en decode. Pero los tres formatos
  cuantizados cuestan calidad medida: perplexity +9,4% (Q4_K_M), +11,6% (Q4_0) y
  +15,9% (FP4_FAST) frente a Q8_0.
- **Chunk de prefill 256**: +11% de TTFT y +76% de ITL. **128 se queda.**

### 6.4 Cómo medimos, para que puedas juzgar los números

- Todo throughput es **de servicio real por HTTP**, no de microbenchmark, salvo
  donde digo "medido directamente".
- Las ejecuciones se **intercalan** con su control y se agrupan por estado de
  reloj; se reporta el modo rápido y se declara el reparto. Queda ~1 ejecución
  lenta de cada 10 incluso con el perfil de energía fijado.
- Hay **perplexity** de cada formato sobre dos corpus propios, y **hashes de
  salida** para verificar que un cambio de kernel no altera el resultado.
- Los gates de validación son duros: una medida que no cumple el contrato de
  salida fija se marca `INVALID` y se descarta.

## 7. Dónde está el código y cómo se reproduce

```
extensions/rocmfpx-vulkan/backend/ggml-vulkan.cpp     el backend completo
extensions/rocmfpx-vulkan/backend/vulkan-shaders/     los shaders .comp
  mul_mmq.comp          matmul por lotes (prefill)  ← la anomalía
  mul_mat_vecq.comp     mat-vec (decode), con el plegado de §6.1
  mul_mat_vec_base.glsl offsets y reducción
  flash_attn.comp       atención
work/scripts/           arnés de medida por HTTP y análisis
work/*_V11.md           los informes, con todas las mediciones
patches/                cada cambio de shader, con su reversión
```

Compilar:

```bash
cmake -G Ninja -DGGML_VULKAN=ON -DROCMFPX_VULKAN_PLUGIN=ON \
      -DCMAKE_C_COMPILER=.../toolchain/bin/gcc \
      -DCMAKE_CXX_COMPILER=.../toolchain/bin/g++ ...
ninja -j4          # ~5 minutos incremental, ~25 desde cero
```

Herramientas disponibles: `llama-bench` (pp/tg directos),
`llama-batched-bench` (la curva de decode por número de secuencias),
`llama-perplexity`, `llama-server` con el arnés HTTP propio, y el logger de
tiempos de Vulkan (`GGML_VK_PERF_LOGGER=1`, con
`GGML_VK_PERF_LOGGER_FREQUENCY`) que da el desglose por operación y por grafo.

Variables de entorno que ya existen en el backend:
`GGML_VK_DISABLE_FUSION`, `GGML_VK_DISABLE_MMVQ`, `GGML_VK_FORCE_MMVQ`,
`GGML_VK_MMV_NO_FOLD_BATCH` (interruptor de nuestro cambio),
`GGML_VK_MMV_TRACE_FOLD` (traza de nuestro cambio).

Restricciones: no se pueden cambiar perfiles de energía, drivers ni firmware
más allá de lo ya autorizado, y no se usan contadores PMC.

## 8. Las preguntas

1. **¿Por qué un GEMM con `m=2048, k=10752` puede rendir 1,5× menos que uno con
   `m=10752, k=2048`** en el mismo shader MMQ (tile 64×64, `split_k=1`, mismos
   MACs, mismos bytes por matriz), **y por qué la brecha se estrecha al crecer
   n** (2,6× a n=16, 1,5× a n=127, 8% a n=4 en la ruta mat-vec)? ¿Qué mecanismo
   concreto lo explica y cómo se comprobaría?

2. **¿Qué tasa real tiene `V_DOT4_I32_I8` en gfx1032** y cómo se mide de forma
   fiable? Nuestro mejor kernel hace 7,2 TMAC/s = 14,4 TOPS, que es el **34% de
   un techo de 42,4 TOPS** a tasa completa o el **68% de 21,2 TOPS** a media
   tasa. Saber cuál de los dos es cambia por completo si el prefill tiene
   recorrido: 3x de margen o casi ninguno.

3. **Patologías conocidas de RDNA2 en bucles FP4/int8**: conflictos de banco en
   LDS, wave32 contra wave64, algo específico de gfx1032 que no aparezca en
   gfx1100. ¿Hay algo documentado que explique un déficit del 50% en un GEMM y
   no en otro?

4. **El 18% del paso de decode en 357 dispatches de ~5 µs** para tensores
   diminutos: ¿cuál es la forma menos invasiva de reducirlo en un backend
   Vulkan? El backend ya tiene fusión (`pipeline_add_rms`,
   `pipeline_multi_add_rms`) pero está limitada por `ggml_nrows(...) == 1`, o
   sea desactivada en toda concurrencia > 1. ¿Merece la pena habilitarla para
   varias filas, y qué trampas tiene?

5. **Flash attention en el chunk de prefill**: 127 queries contra 8448 de
   contexto, medida a 3,9 TMAC/s (56% de la eficiencia de los matmuls). El
   backend ya usa split-KV. ¿Hay una formulación mejor para ese régimen de pocas
   queries y contexto largo?

6. **¿Ves alguna palanca grande que no hayamos tocado?** Concretamente: dado que
   el decode está al 65% del muro práctico de ancho de banda y el prefill entre
   el 35% y el 70% del muro de cómputo int8, ¿dónde buscarías los próximos
   puntos porcentuales?

## 9. Qué forma tiene una respuesta útil

- Un mecanismo concreto, no una lista de opciones.
- Si propones un experimento, que sea ejecutable en este equipo en menos de una
  hora y que diga qué resultado refutaría la hipótesis.
- Los números que doy son de servicio real (HTTP), no de microbenchmarks, salvo
  donde digo "medido directamente". No mezcles ambas cosas al razonar.
