# LFM2.5-2.6B en RX 6600 XT / gfx1032

> **Checkpoint contemporáneo (2026-09-17):** las cifras que siguen en este
> informe son el historial de exploración y no sustituyen el baseline v2. El
> GGUF situado en la ruta Q4_0 fue reemplazado a las 02:29 y las tandas previas
> no guardaron su hash. El resultado válido actual está en `BASELINES.json`:
> ROCmFPX plugin FP4_FAST + slots compactos alcanza 233,99 tok/s en 200
> peticiones C4, frente a 226,65 upstream, con 0 fallos. `ubatch=512` queda
> descartado por un cliff de DPM; producción usa `ubatch=128` y
> `LLAMA_SERVER_COMPACT_SLOTS=1`.

## Leaderboard contemporáneo v2

| Engine | Backend | Quant | C=1 TG | C=2 total | C=4 total | C=4 TG/user | TTFT C=4 p50/p95 | E2E p95 C=4 | VRAM |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ROCmFPX | ROCmFPXVulkan0 + slots compactos | FP4_FAST | **108,0** | **169,1** | **234,0** | **58,9** | 327/351 ms | **1.113 ms** | **1,85 GiB** |
| llama.cpp | Vulkan0 + slots compactos | Q4_0 | 100,8 | 163,0 | 226,7 | 56,9 | **297/309 ms** | 1.140 ms | 2,00 GiB |

El p95 de esta tabla usa 200 peticiones C=4 por backend; no es una extrapolación
de tres muestras. La ventaja emparejada de FPX en throughput C4 es +3,30%
(IC bootstrap 95% +2,77 a +3,84%). Con llegadas separadas 100 ms, FPX da
223,7 frente a 209,9 tok/s y también mejora TTFT p95 (116 frente a 193 ms).

La recomendación cambia con la forma: FPX gana 128/64 y 512/128; upstream
Q4_0 gana 2048/256 (101,7 vs 100,0 tok/s con b4096/u128) y la pantalla
exploratoria 7680/512 (92,4 vs 88,6). Por tanto, el perfil de producción de
arriba es el ganador de la carga prioritaria corta, no un ganador universal.

Informe de decisión para un servidor con un máximo real de cuatro solicitudes
concurrentes. La métrica primaria es el throughput agregado en C=4; el
ranking C=1 se conserva por separado.

## Decisión ejecutiva

La ruta que maximiza la métrica primaria —throughput agregado con cuatro
peticiones— es ahora la extensión Vulkan opcional de ROCmFPX:

```text
ROCmFPXVulkan0 (plugin Charlie, compilado con el mismo árbol ROCmFPX)
modelo: LFM2.5-2.6B-ROCmFP4_FAST.gguf
KV: q8_0 / q8_0
batch: 512, ubatch: 128
-ngl 99 -fa on -np 4 -cb -c 4096
```

En la matriz completa da 103,8 / 160,6 / 204,3 / **233,2 tok/s** en
C=1/2/3/4, 58,3 tok/s por usuario en C=4, TTFT p50 de 341 ms, p95 E2E de
1.094 ms y 1,865 GiB de VRAM. Las 30 peticiones medidas de la matriz
terminaron correctamente, además del warmup de cada celda. Esta es la mejor
ruta de rendimiento para producción si se empaqueta también la runtime GCC 16
exacta: el plugin necesita precargar la `libstdc++` del toolchain aislado
porque el RPATH de este build antepone la runtime del sistema. El margen es
de +1,2% frente al perfil upstream estable Q4_0 `b4096/ub512` y +2,1% frente
al control upstream `b512/ub128`.

La configuración de producción equilibrada, sin esa dependencia del plugin y
con menor TTFT, sigue siendo:

```text
llama.cpp Vulkan upstream
modelo: LFM2.5-2.6B-Q4_0.gguf
KV: q8_0 / q8_0
batch: 4096, ubatch: 512
-ngl 99 -fa on -np 4 -cb -c 4096
```

En la medición principal alcanza 230,5 tok/s agregados en C=4, 57,6 tok/s por
usuario, TTFT p50 de 272 ms, p95 E2E de 1.111 ms y 2,05 GiB de VRAM. El
baseline Q4_K_M conserva más margen de calidad, pero baja a 222,1 tok/s en
C=4.

La nueva ruta ROCmFPX Vulkan ya está optimizada para el servidor real:
`ROCmFP4_FAST`, MMQ int-dot habilitado, KV `q8_0/q8_0`, `b=512`,
`ubatch=128`, `-np 4 -cb`. En la matriz comparable alcanza 102,7 / 165,5 /
203,1 / 226,5 tok/s agregados en C=1/2/3/4, usa 1,87 GiB y gana C=1 y C=2;
en C=4 queda a ~0,9% del upstream equivalente. El valor de C=4 que había
quedado en 194,1 tok/s correspondía a `b=2048/ubatch=512`, no al punto
óptimo encontrado ahora.

El máximo C=4 bruto de esta tanda es Q4_0 f16 con `b1024/ub256`: 231,1
tok/s. Sólo supera al perfil de producción en ~0,3%, pero baja a 78,4 tok/s
en C=1 y empeora el p95; por eso no es la configuración de servicio.

La recomendación práctica es mantener estos perfiles:

1. `production-throughput`: ROCmFPX `ROCmFPXVulkan0`, FP4_FAST + KV q8 +
   `b512/ub128` (máximo C=4 medido y menor VRAM).
2. `production-safe`: llama.cpp Vulkan `Vulkan0`, Q4_0 + KV q8 +
   `b4096/ub512` (máximo sin plugin y menor TTFT).
3. `production-fpx-low-vram`: ROCmFPX Vulkan integrado, FP4_FAST + KV q8 +
   `b512/ub128` (mejor C=1/C=2, sin cargar el plugin).
4. `production-quality`: Q4_K_M + KV f16 + `b2048/ub512`.

El plugin actual pasa el smoke de disponibilidad 3/3 y las comprobaciones de
palabras exactas/JSON; eso no sustituye una evaluación de perplexity contra el
checkpoint BF16. Para un despliegue que no pueda aceptar esa validación
pendiente, usar `production-safe`.

Arranque reproducible del perfil ganador (las dos bibliotecas precargadas son
las del toolchain local, no las del sistema):

```bash
BIN=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/builds/rocmfpx-vulkan-gfx1032-cm1/bin
export ROCMFPX_PLUGIN_PATH="$BIN/rocmfpx-vulkan-plugin.so"
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
"$BIN/llama-server" -m /home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf -dev ROCmFPXVulkan0 \
  -ngl 99 -fa on -np 4 -cb -c 4096 -b 512 -ub 128 \
  -ctk q8_0 -ctv q8_0
```

## Leaderboard principal: estado reproducible post-Sunshine

Condiciones comunes: RX 6600 XT, gfx1032, p=128, salida máxima 64, warmup=1,
3 repeticiones por concurrencia, mismas semillas y tokenizer local. Los
throughputs son la mediana de las tres repeticiones agregadas. `TTFT` es el
p50 de las peticiones de C=4; `p95` es E2E de C=4. Las rutas HIP se miden en
una pantalla separada porque son órdenes de magnitud más lentas y no permiten
una matriz p=128/max=64 razonable en este equipo.

| Engine | Backend | Quant | C=1 TG | C=2 total TG | C=4 total TG | C=4 TG/user | TTFT C=4 | p95 C=4 | VRAM máx. | Estado |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| llama.cpp | Vulkan | Q4_0, KV q8, b4096/u512 | **100,5** | 152,7 | 230,5 | **57,6** | 272 ms | **1.111 ms** | 2,05 GiB | producción equilibrada |
| llama.cpp | Vulkan | Q4_0, KV q8, b512/u128 | 100,7 | 154,1 | 228,5 | 57,1 | 291 ms | 1.123 ms | 2,01 GiB | control actual del tuning |
| llama.cpp | Vulkan | Q4_0, KV f16, b4096/u512 | 97,4 | **156,9** | 229,2 | 57,3 | 272 ms | 1.117 ms | 2,06 GiB | mejor C=2 si se prioriza f16 |
| llama.cpp | Vulkan | Q4_0, KV f16, b2048/u512 | 97,6 | **159,0** | 227,6 | 56,9 | 261 ms | 1.123 ms | 2,07 GiB | menor TTFT |
| llama.cpp | Vulkan | Q4_0, KV f16, b1024/u256 | 78,4 | 154,3 | **231,1** | 57,8 | 280 ms | 1.167 ms | **2,04 GiB** | máximo C=4 bruto; peor C=1 |
| llama.cpp | Vulkan | Q4_K_M, KV f16, b2048/u512 | 93,9 | 149,4 | 222,1 | 55,5 | 306 ms | 1.164 ms | 2,14 GiB | baseline calidad |
| ROCmFPX CM1 | Vulkan | ROCmFP4_FAST, KV q8, b2048/u512 | 96,4 | 141,6 | 194,1 | 48,5 | 541 ms | 1.324 ms | **1,91 GiB** | ruta FPX actual |
| ROCmFPX Vulkan int-dot | Vulkan | ROCmFP4_FAST, KV q8, b512/u128 | **102,7** | **165,5** | 226,5 | 56,6 | 339 ms | 1.129 ms | **1,87 GiB** | mejor C=1/C=2 y rendimiento/VRAM |
| ROCmFPX Charlie plugin | Vulkan plugin | ROCmFP4_FAST, KV q8, b512/u128 | **103,8** | 160,6 | **233,2** | **58,3** | 341 ms | **1.094 ms** | **1,87 GiB** | mejor C=4; requiere runtime GCC16 |
| ROCmFPX CM1 | Vulkan | ROCmFP4_FAST, KV f16, b2048/u512 | 91,8 | 140,7 | 190,2 | 47,5 | 547 ms | 1.373 ms | 1,93 GiB | control FPX |
| vLLM ROCm | ROCm | FP16 | 12,0 | 23,0 | 45,7 | 11,4 | 389 ms | 5.646 ms | 6,94 GiB | no competitivo; modelo no GGUF |

Ganadores explícitos dentro del estado reproducible actual:

- mejor single-user: ROCmFP4_FAST del plugin, KV q8, `b512/ub128`
  (103,8 tok/s);
- mejor C=2: ROCmFP4_FAST int-dot, KV q8, `b512/ub128` (165,5 tok/s);
- mejor C=4 bruto y mejor rendimiento/VRAM: ROCmFP4_FAST del plugin,
  `b512/ub128` (233,2 tok/s; ~125 tok/s/GiB);
- mejor TTFT C=4 sin plugin: Q4_0, KV q8, `b4096/ub512` (272 ms);
- mejor configuración final para producción orientada a throughput: ROCmFPX
  `ROCmFPXVulkan0`, FP4_FAST, KV q8, `b512/ub128`, con la runtime GCC16
  aislada. La configuración de fallback es Q4_0 `b4096/ub512`.

La fila Q4_0 de `b2048/u512` contiene una repetición C=4 con una petición que
terminó en 4 tokens; la mediana de throughput sigue usando una repetición
completa, pero la variante final `b4096/u512 + KV q8` no presenta ese recorte.

## Tuning específico para cuatro usuarios

La ruta ROCmFPX int-dot requiere ajustar el tamaño de microbatch al servidor,
no al máximo teórico del backend. Con cuatro prompts de 128 tokens, `b=512` y
`ubatch=128` evita la fragmentación y mantiene el trabajo de prefill en un
solo bloque útil. La pantalla C=4 fue:

| ROCmFPX FP4_FAST, KV q8 | C=4 total | TTFT p50 | E2E p95 | Nota |
| --- | ---: | ---: | ---: | --- |
| int-dot, `b4096/ub512` | 111,5 | 1.087 ms | 2.283 ms | demasiado grande para esta carga |
| int-dot, `b4096/ub256` | 202,6 | 437 ms | 1.268 ms | mejora parcial |
| int-dot, `b4096/ub64` | 202,9 | 477 ms | 1.259 ms | fragmenta el prefill |
| int-dot, `b4096/ub128` | 227,9 | 339 ms | 1.129 ms | casi óptimo |
| int-dot, `b512/ub128` | **226,5** | 339 ms | 1.129 ms | configuración final; menor VRAM |
| plugin `ROCmFPXVulkan0`, `b512/ub128` | **233,2** | 341 ms | **1.094 ms** | ganador C=4; requiere `LD_PRELOAD` |

El `b=512/ub=128` se repitió con el upstream: Q4_0 dio 228,5 tok/s en C=4,
por lo que ROCmFPX queda a 0,9% bajo el control. KV `f16/f16` en ROCmFPX
bajó a 199,2 tok/s; se conserva `q8_0/q8_0`. La misma ruta ROCmFPX sin
`GGML_VK_ROCMFPX_INTDOT=on` fue validada tras recompilar: el default ahora es
int-dot y reprodujo 228,3 tok/s en la repetición de verificación C=4.

El selector admite `GGML_VK_ROCMFPX_INTDOT=off` para A/B o depuración. El modo
escalar sigue siendo útil como control aislado, pero no es la configuración de
servicio en gfx1032: al procesar cuatro slots el prefill escalar cayó a unos
36 tok/s agregados.

Archivos de la matriz:

- [Q4_0 KV q8 C=1..4](results/llama-vulkan-q4_0-b4096-u512-kvq8-postsunshine)
- [Q4_0 KV f16 C=1..4](results/llama-vulkan-q4_0-b4096-u512-postsunshine)
- [Q4_K_M C=1..4](results/llama-vulkan-q4km-postsunshine)
- [ROCmFPX FAST KV q8 C=1..4](results/rocmfpx-vulkan-cm1-fast-kvq8-postsunshine)
- [ROCmFPX FAST int-dot optimizado KV q8 C=1..4](results/rocmfpx-vulkan-fp4-fast-intdot-on-b512-ub128)
- [ROCmFPX Charlie plugin FAST KV q8 C=1..4](results/rocmfpx-vulkan-plugin-b512-ub128)
- [Smoke de calidad del plugin FAST](results/quality-rocmfpx-plugin-fast-c4.json)
- [Upstream Q4_0 control actual b512/u128 C=1..4](results/llama-vulkan-q40-b512-ub128)
- [ROCmFPX FAST KV f16 C=1..4](results/rocmfpx-vulkan-cm1-fast-postsunshine)
- [vLLM ROCm C=1..4](results/vllm-rocm-fp16-postsunshine)

## C=3 y tendencia de escalado

| Configuración | C=1 TG | C=2 TG | C=3 TG | C=4 TG |
| --- | ---: | ---: | ---: | ---: |
| llama.cpp Vulkan Q4_0, KV q8, b4096/u512 | 100,5 | 152,7 | 206,7 | 230,5 |
| llama.cpp Vulkan Q4_0, KV q8, b512/u128 | 100,7 | 154,1 | 205,5 | 228,5 |
| llama.cpp Vulkan Q4_0, KV f16, b2048/u512 | 97,6 | **159,0** | **207,0** | 227,6 |
| llama.cpp Vulkan Q4_K_M | 93,9 | 149,4 | 193,0 | 222,1 |
| ROCmFPX FAST, KV q8 | 96,4 | 141,6 | 172,6 | 194,1 |
| ROCmFPX FAST int-dot, KV q8, b512/u128 | **102,7** | **165,5** | 203,1 | 226,5 |
| ROCmFPX Charlie plugin FAST, KV q8, b512/u128 | **103,8** | 160,6 | 204,3 | **233,2** |
| vLLM ROCm FP16 | 12,0 | 23,0 | 34,2 | 45,7 |

El scheduler de llama.cpp con continuous batching y `-np 4` escala de forma
útil para este caso. Prefix caching no se acredita en estas cifras porque el
harness cambia los ids del prompt entre repeticiones; sí se deja disponible
para producción cuando haya prefijos realmente repetidos. Chunked prefill y
paged KV quedan cubiertos por vLLM, pero no compensan el coste de esta GPU y
esta carga pequeña.

## ROCmFPX: formatos y mediciones

El árbol oficial actual de [ROCmFPX](https://github.com/ROCmFPX/ROCmFPX)
expone `ROCmFP4`, `ROCmFP4_FAST`, familias ROCmFPX Q2/Q3/Q5/Q6/Q7/Q8,
variantes `_COHERENT`, `_EVEN`, `_LEAN`, `_AGENT` y `ROCMI4`. El propio
proyecto advierte que la disponibilidad de un formato no implica que sea la
ruta más rápida en una GPU concreta.

| Formato | bpw aprox. | PP tok/s | TG tok/s | C=4 agregado histórico | Calidad/salida | VRAM observada |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| ROCmFPX Q2 | 2,90 | 1.242 | 174,2 | 345,6 | **rechazado**: texto repetitivo/incoherente y JSON incorrecto | 1,58 GiB |
| ROCmFPX Q3 | 4,27 | 1.215 | 111,1 | 230,5 | no formalmente puntuado; salida válida en smoke | no aislada |
| ROCmFP4_FAST | 4,25 | 1.007 post-reset / 2.250 pre-reset; 2.248 integrado; 2.224 plugin | 132,8 post-reset / 133,6 pre-reset; 132,9 integrado; 131,4 plugin | 303,3 pre-reset; 226,5 integrado; **233,2 plugin** con `b512/ub128` | smoke chat: palabras exactas y JSON pasan; disponibilidad plugin 3/3 | 1,87 GiB con KV q8 |
| ROCmFP4_FAST_COHERENT | 4,48 | — | — | 286,3 pre-reset | smoke anterior válido, sin métrica de calidad formal | ~2,09 GiB |
| ROCmFP4 | 4,50 | — | — | 257,4 pre-reset | no aislado formalmente | ~2,32 GiB |
| ROCMI4 / otras Q5--Q8 | 4,48--8,25 | inventariadas, sin speed qualification completa | — | — | pendientes de perplexity/eval | — |
| Q4_0 estándar | 4,70 | 2.296 post-reset | 125,0 | 227,6 post-reset | smoke chat de la familia estándar; usar Q4_K_M si prima calidad | 2,05--2,07 GiB |
| Q4_K_M estándar | 4,94 | 1.650 post-reset | 121,9 | 222,1 post-reset | smoke chat: palabras exactas y JSON pasan | 2,14 GiB |

PP/TG de `llama-bench` son pruebas directas con p=128 y n=128 para aislar
prefill/decode; las cifras C=4 son peticiones HTTP reales y, por tanto,
incluyen scheduler, TTFT y sincronización. No se debe mezclar la cifra
histórica de ROCmFPX anterior al reset con el leaderboard actual.

El Q2 es un ejemplo importante de por qué no se debe seleccionar por tamaño:
ganó en throughput bruto, pero falló el smoke de calidad. El FAST normal es
el mejor compromiso FPX probado; FAST_COHERENT no superó a FAST en esta carga.

## HIP, Vulkan y vLLM

Se compilaron y se hicieron pruebas de los cinco caminos solicitados:

- ROCmFPX HIP nativo gfx1032: carga y ejecución con
  `HSA_OVERRIDE_GFX_VERSION` sin definir; `llama-bench` directo dio PP 4,70 y
  TG 1,738 tok/s con FAST. En pantalla C=1..4, p=16/max=8, quedó en
  aproximadamente 0,765 / 0,815 / 0,799 / 0,912 tok/s agregados.
- llama.cpp HIP nativo gfx1032: `llama-bench` directo dio PP 3,44 y TG
  1,211 tok/s con Q4_K_M; la pantalla C=1..4 p=16/max=8 quedó en
  aproximadamente 0,534 / 0,553 / 0,546 / 0,629 tok/s.
- ROCmFPX Vulkan integrado: el build CM1 se probó, pero RADV en gfx1032
  declara `matrix cores: none` y no activa cooperative matrices; el salto útil
  vino de registrar los kernels MMQ int-dot FP4 y de ajustar `b512/ub128`.
- ROCmFPX Vulkan Charlie plugin: se cargó como `ROCmFPXVulkan0` y se midió
  con FP4_FAST, KV q8 y `b512/ub128`; alcanzó 233,2 tok/s agregados en C=4,
  por encima del upstream. Sin `LD_PRELOAD` no arranca por el símbolo
  `GLIBCXX_3.4.35`; con la runtime GCC16 aislada sí registra el dispositivo y
  completa la matriz.
- llama.cpp Vulkan upstream: es el mejor fallback sin plugin para C=4 con
  Q4_0 y ofrece el menor TTFT de C=4.
- vLLM ROCm: versión local `0.29.0+rocm723`, FP16, `max_num_seqs=4`, prefix
  caching y chunked prefill activos; quedó limitado a ~45,7 tok/s agregados en
  C=4 y utilizó ~6,94 GiB.

El HIP runtime instalado expone gfx1030 cuando se usa
`HSA_OVERRIDE_GFX_VERSION=10.3.0`; por eso el binario nativo se ejecutó con
el override quitado. La construcción gfx1030 sigue disponible como fallback,
pero no se usa para el ranking nativo.

## Profiling y origen de la diferencia

Se hizo profiling trace-only seguro después de retirar Sunshine. Los dos
traces observan la misma GPU física (gfx1032, wave32, LDS 64 KiB, 32 CUs):

| Dominio | llama.cpp HIP estándar | ROCmFPX HIP |
| --- | ---: | ---: |
| HIP API | 51,25% | 52,04% |
| dispatch de kernels | 47,26% | 46,06% |
| copias de memoria | 236 ms | 204 ms |
| `hipStreamSynchronize` dentro de API | 13,13 s | 9,32 s |
| kernel MMQ principal | 36,56%, 33,5 ms/call | 40,96%, 23,9 ms/call |
| grupo M·V J=2 | 20,26%, 9,3 ms/call | 23,52%, 6,9 ms/call |
| grupo M·V J=4 | 19,25%, 17,7 ms/call | 21,69%, 12,6 ms/call |
| Flash Attention observado | 0,656% | 0,925% |

La tabla muestra de dónde sale la ventaja HIP de ROCmFPX: sus kernels MMQ/MVV
custom tienen menor tiempo medio y el trace tiene menos sincronización total.
En Vulkan, el port de MMQ int-dot para FP4_FAST redujo la pantalla directa de
~1.025k PP tok/s escalar con N=124 a ~2.231k PP tok/s con N=128 int-dot. En el
servidor, el beneficio decisivo no es sólo el kernel aislado: `ubatch=128`
evita la regresión del scheduler al agrupar cuatro slots. El resultado final
queda a la par del upstream, con menos VRAM y mejor C=1/C=2, pero aún no
desplaza al upstream en el objetivo primario C=4 para el backend integrado.
La extensión Charlie obtiene 233,2 tok/s en esa misma pantalla; su `llama-bench`
aislado es similar (PP 2.224 / TG 131,4), así que la mejora aparece en la ruta
de servidor multi-slot y no debe atribuirse a un único microkernel sin una
traza específica del plugin.

No se repitieron contadores PMC de ocupación/bandwidth/register pressure/LDS:
la ejecución anterior de contadores coincidió con el reset amdgpu. Repetirla
antes de aislar la causa aumentaría el riesgo y no mejoraría la evidencia
actual.

## Incidente de sesión y estabilidad

No hubo reinicio completo del sistema: el boot era el mismo. A las 03:09 el
kernel registró timeout de `amdgpu comp_1.0.1` en el proceso `sunshine`, reset
de GPU con pérdida de VRAM, errores AER PCIe en la función de audio y reinicio
de Xwayland/GNOME Shell. Sunshine se eliminó; desde entonces las pruebas
completadas no han generado nuevos timeouts de anillo ni procesos de
benchmark persistentes. El mensaje posterior de `svm_range_deferred_list_work`
es una advertencia de carga del workqueue, no otro reset.

El sistema tiene el root filesystem alrededor del 94% ocupado. No se han
eliminado modelos, builds ni resultados automáticamente.

## Reproducibilidad y fuentes locales

- [Auditoría de builds y soporte RDNA2](ROCmFPX_AUDIT.md)
- [Benchmark ROCmFPX FAST KV q8](results/rocmfpx-vulkan-cm1-fast-kvq8-postsunshine)
- [Benchmark Q4_0 final](results/llama-vulkan-q4_0-b4096-u512-kvq8-postsunshine)
- [Perfil ROCmFPX HIP](results/profiling/rocmfpx-hip-postsunshine)
- [Perfil llama.cpp HIP](results/profiling/llama-hip-postsunshine)
- [Smoke de calidad Q4_0 KV q8](results/quality-q4_0-kvq8-chat-postsunshine.json)
- [Smoke de calidad ROCmFPX plugin FAST](results/quality-rocmfpx-plugin-fast-c4.json)
- Selector MMQ: `test-rocmfpx-mmq-rdna2` pasa 112 configuraciones ROCmFPX y
  el control estándar; `check-rocmfpx-reference.sh` también pasa usando el
  compilador C/C++ incluido en `/home/isaac/vllm-challenge/toolchain`.

Referencias de proyecto: [ROCmFPX format status](https://github.com/ROCmFPX/ROCmFPX/blob/main/docs/rocmfpx/README.md), [llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md), [vLLM GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/).
