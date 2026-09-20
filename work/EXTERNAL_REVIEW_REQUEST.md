# Petición de revisión externa: LFM2.5-2.6B en RX 6600 XT (gfx1032)

Copia todo este documento como prompt. Es autocontenido: quien lo lea no tiene
acceso a nuestro repositorio ni a nuestra conversación.

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
  Medido: **222 GB/s** es el pico práctico que alcanza nuestro mejor kernel
  (una proyección de salida `m=128000` en decode, streaming de pesos casi puro).
- FP32: 2048 SP × 2 × 2,589 GHz ≈ **10,6 TFLOPS**.
- Producto punto int8 (`V_DOT4_I32_I8`): **no sé la tasa real en gfx1032.**
  El rango posible es 21–42 TOPS según si emite a media o a tasa completa.
  Esto es una incógnita relevante (§5).
- CPU: Ryzen 5 1500X, **4 núcleos**. Un rebuild del backend tarda ~5 minutos y
  uno completo de llama.cpp, ~25.

## 2. Stack de software

- **ROCmFPX**, un fork de llama.cpp con un backend Vulkan propio, en
  `extensions/rocmfpx-vulkan/backend/ggml-vulkan.cpp` y sus shaders en
  `extensions/rocmfpx-vulkan/backend/vulkan-shaders/`.
- El driver Vulkan es **RADV (Mesa 26.0.8)**. Los shaders son **SPIR-V generados
  en tiempo de compilación** por shaderc. Esto importa: es la razón por la que
  esta GPU funciona en absoluto (§6).
- Compilado con un GCC 16 aislado; el backend necesita precargar su
  `libstdc++`.
- **La ruta HIP/ROCm está descartada por medición**: los mismos kernels por HIP
  dan 1,7 tok/s frente a 132 tok/s por Vulkan en esta tarjeta. gfx1032 no está
  en el soporte oficial de ROCm.

## 3. Modelo

- **LFM2.5-2.6B** de LiquidAI. Arquitectura híbrida: **30 capas, 22 de
  convolución/SSM y 8 de atención**.
- hidden 2048, vocab 128000, **GQA 32 cabezas Q / 8 KV**, head_dim 64.
- Cuantizado a **ROCmFP4_FAST**: 4,25 bpw, **1,442 GB**, bloques de 17 bytes con
  4 palabras de código FP4 y una escala. La ruta usa **producto punto int8 con
  activaciones cuantizadas a q8_1** (`mul_mmq.comp` / `mul_mat_vecq.comp`).
- Alternativa: **Q4_0** estándar, 4,70 bpw, 1,48 GB.
- Referencia casi sin pérdida: Q8_0, 8,50 bpw.

## 4. Carga de trabajo

Cuatro peticiones concurrentes, dos perfiles:

**Perfil A (métrica primaria):** 128 tokens de entrada, 64 de salida, C=1..4.
La métrica son tok/s agregados medidos por HTTP desde el primer envío hasta la
última respuesta.

**Perfil B (interactivo):** cuatro slots de 8192 tokens; tres decodificando y uno
que llega con un prompt nuevo. Métricas: TTFT del que llega, e ITL p95
(latencia entre tokens) de los residentes durante el prefill.

## 5. Números actuales y de qué están hechos

### Perfil A, con nuestro último cambio (ver §6.1)

| C | tok/s |
| ---: | ---: |
| 1 | 108,10 |
| 2 | 173,84 |
| 3 | 220,65 |
| 4 | **250,36** |

### Perfil B

TTFT **4781 ms**, ITL p95 **81,6 ms**, con Q4_0. Objetivo declarado: ITL ≤ 70 ms,
TTFT ≤ 5,5 s. **El TTFT se cumple; el ITL no.**

### Descomposición del paso de decode a C=4

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

### Descomposición del grafo de prefill (n=127, contexto 8448)

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
Plegar el batch replicado en la dimensión de columna son 12 líneas y dio
**+13,8% en decode a cuatro secuencias** (352,5 → 401,3 tok/s medidos
directamente), +8,4% de decode residente en reposo, y +7,0% sobre la métrica
primaria publicada. Perplexity bit-idéntica.

### 6.2 La anomalía que NO hemos resuelto (el objeto de esta consulta)

En el **mismo shader MMQ**, con **el mismo tile `(64,64)`**, **el mismo
`split_k=1`** y **los mismos MACs y los mismos bytes de pesos por matriz**:

| Forma | TFLOPS-equivalentes | n |
| --- | ---: | ---: |
| `m=10752, k=2048` (gate/up) | **13,9** | 127 |
| `m=2048, k=10752` (down) | **9,25** | 127 |

A n=4 (ruta mat-vec, otro shader) la brecha es solo del **8%**; a n=16 es de
**2,6×**; a n=127 es de **1,5×**. Es decir, **la brecha es específica de la ruta
de matmul por lotes y se estrecha al crecer n**.

Lo que hemos eliminado por experimento:
- **No es split-k.** Todas las formas de prefill reciben `split_k=1` con la
  heurística del backend. Un override por variable de entorno que lo sube hasta
  un objetivo de workgroups por CU fue neutro con 4 y catastrófico con 8
  (pp128 cayó de 2333 a 723 tok/s).
- **No es selección de tile.** Una traza de `ggml_vk_matmul` muestra que todas
  las formas usan `wg=(64,64)` y `split_k=1`.
- **No aparece en decode**, luego no es el layout de pesos ni el tipo.

Lo que queda sin examinar: la **geometría de fila**. Una fila de pesos de `down`
mide **5.712 bytes** (336 bloques FP4 de 17 B) contra **1.088 bytes** de
`gate/up` (64 bloques). El bucle sobre k es 5,25× más largo con 5,25× menos filas
para solaparlo.

### 6.3 Otras cosas descartadas

- **Motores alternativos.** vLLM, SGLang y Lucebox **no compilan para ninguna
  gfx103x**. Los objetos de código de vLLM son
  `gfx90a gfx942 gfx950 gfx1100 gfx1101 gfx1150 gfx1151 gfx1200 gfx1201`;
  sus kernels `rms_norm`, `fused_add_rms_norm` y `silu_and_mul` **segfaultean**
  en gfx1032 mientras las matmuls de torch funcionan. SGLang compila para
  gfx942/gfx950/gfx1151; Lucebox documenta gfx1100/gfx1151/gfx1201.
  Cargar el modelo 4-bit en vLLM sí funciona (1,72 GiB, 6,8 s); lo que no
  funciona son sus kernels.
- **Decodificación especulativa.** Medida con el borrador específico DSpark
  (5 capas, 199 MB en Q4_K_M): **−13% a una sola secuencia** (121,6 → 105,8
  tok/s), **rota a cuatro secuencias** (fallos `Invalid input batch` en 17/40 y
  4/40 peticiones), y **el backend de producción ni la carga** (aborta con
  `pre-allocated tensor (token_embd.weight) ... cannot run the operation (NONE)`).
- **`ubatch >= 256`.** 111,8 tok/s con 256 y 114,4 con 512, contra 251 con 128.
  Firma distinta del estado de reloj (§6.4): 2,24× de throughput y 3,6× de TTFT.
- **KV cache `q4_0`.** Pierde el 60% del decode residente (105 vs 261 tok/s):
  flash attention tiene que descomprimir.
- **Familia de layouts FP4.** Padding a 20 bytes (+17,65% de memoria, −1,227%
  local), plano global compacto (+43,150%), agrupado de cuatro (+3,851%).
  Conclusión: la localidad de escalas domina; el cuello no está en el layout.
- **Unos 40 variantes de shader** acumuladas antes de nosotros: mejor resultado
  de servicio +1,16%.
- **Formato distinto por forma.** El ranking se invierte: Q4_0 es 15,4% más
  rápido en prefill (pp128) y FP4_FAST 7,2% en decode. Pero los tres formatos
  cuantizados cuestan calidad medida: perplexity +9,4% (Q4_K_M), +11,6% (Q4_0)
  y +15,9% (FP4_FAST) frente a Q8_0.
- **Chunk de prefill 256**: +11% de TTFT y +76% de ITL. **128 se queda.**

### 6.4 Un detalle de entorno que afecta a la interpretación

La GPU entra al azar en un estado donde el reloj de memoria oscila entre 1000 y
541 MHz, con un coste del **~40%**. Fijar el perfil de energía bajó la
incidencia de 5/12 a 1/10. **Todas las cifras de arriba están tomadas en el
estado rápido y verificadas con muestreo de reloj.**

## 7. Las preguntas

1. **¿Por qué un GEMM con `m=2048, k=10752` puede rendir 1,5× menos que uno con
   `m=10752, k=2048`** en el mismo shader MMQ (tile 64×64, `split_k=1`, mismos
   MACs, mismos bytes por matriz), **y por qué la brecha se estrecha al crecer
   n** (2,6× a n=16, 1,5× a n=127, 8% a n=4 en la ruta mat-vec)? ¿Qué mecanismo
   concreto lo explica y cómo se comprobaría?

2. **¿Qué tasa real tiene `V_DOT4_I32_I8` en gfx1032** y cómo se mide de forma
   fiable? Nuestro mejor kernel hace 7,2 TMAC/s, que es el 74% de 21 TOPS o el
   18% de 42 TOPS. Saber cuál de los dos es cambia por completo si el prefill
   tiene recorrido o no.

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

## 8. Qué forma tiene una respuesta útil

- Un mecanismo concreto, no una lista de opciones.
- Si propones un experimento, que sea ejecutable en este equipo en menos de una
  hora y que diga qué resultado refutaría la hipótesis.
- Los números que doy son de servicio real (HTTP), no de microbenchmarks, salvo
  donde digo "medido directamente". No mezcles ambas cosas al razonar.
