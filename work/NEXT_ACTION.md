# Próxima acción

## Estado de producción V5

- Scheduler: `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` es **KEEP production**.
  Pasó equivalencia controlada y el corpus reservado con EOS normal. Reduce la
  ITL p95 de residentes desde ~2189 ms hasta ~89 ms en 3D+1P.
- Kernel: el backend de producción vuelve al control FP4_FAST. SHA-256 de
  `libggml-rocmfpx-vulkan.so`:
  `40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
- Remapeo denso R1 sigue **STAGE** y no debe componerse todavía con producción.

## Siguiente experimento: down projection N=4

Flash Attention queda cerrada en V5: quitar el límite de ocupación tenía un
techo global de ~0.35%, y el único Bc64 permitido empeoró la latencia exacta
8Kx4 un 14.58%. El siguiente candidato de leverage alto es la proyección down
`M=2048,K=10752,N=4`, que representa 21.08% del MMV decode medido y 23.28% del
prefill 8K agrupado.

Usar el runtime estable y chunk128. Aislar exclusivamente la forma down y
comparar el pipeline subgroup actual con la variante hybrid/large ya compilada,
sin repetir el selector N-only rechazado. Primero:

1. confirmar pipeline, tipos y strides exactos en el plugin;
2. ejecutar correctitud de operación y ABBA logger-free para down N=4;
3. exigir una mejora local clara y estimar leverage global antes del servidor;
4. si pasa, validar C4 resident 8K y Profile B/3D+1P por separado;
5. si la señal antigua no se reproduce, cerrar la variante y atacar K tiling o
   unpack con una hipótesis nueva, no ampliar el selector.

## Hipótesis cerradas que no deben reabrirse sin evidencia nueva

- chunk96 y chunk256;
- caché adicional de Q8_1;
- rebatching de `6144x2048,N=1` (los cuatro usuarios ya están en `ne[2]`);
- gate/up con dos o cuatro subgroups;
- rows4 para short-conv;
- carga FP4 alineada de 32 bits;
- tile MMQ `BM=32,BN=128`;
- `BK_STEP=2` global para todas las formas.
- eliminación del limitador de ocupación FA de RDNA2.
- `Bc=64` FA sobre la forma exacta 8Kx4.

El selectivo gate-only fue una mejora real pero insuficiente: diez pares AB/BA
dieron +0.486% de throughput (95% CI [+0.371%, +0.705%]) y outputs exactos
10/10. Con la política de leverage vigente queda **ARCHIVE COMPOSABLE**: no se
promociona sola ni recibe más tiempo ahora, pero su selector, patch y resultados
se conservan para una futura composición de bajo coste.

La primera variante FA está cerrada: quitar el limitador sintético de
26 KiB gana solo ~1.5% local en el tile largo, no mejora el servidor (-0.141%
exploratorio) y tiene un techo global de ~0.35%. Es **REJECT**. No volver a
tocar ocupación sin una modificación algorítmica que cambie ese techo.

Bc64 también está cerrado: pasa correctitud, pero el microbenchmark exacto
regresa +14.58%. No ejecutar una campaña de servidor ni probar más tiles FA en
V5.

## Control experimental

Usar el arnés V5 con un solo servidor y una sola carga GPU. Antes de cualquier
benchmark confirmar cuatro slots efectivos >=8192, KV q8/q8, modelo FP4_FAST
de 4.277124 BPW, chunk128 y ausencia de variables experimentales de shaders.
No cambiar clocks, perfiles de energía, drivers ni firmware.
