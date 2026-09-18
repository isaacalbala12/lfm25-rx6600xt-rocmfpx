# Próxima acción

## Estado de producción V5

- Scheduler: `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` es **KEEP production**.
  Pasó equivalencia controlada y el corpus reservado con EOS normal. Reduce la
  ITL p95 de residentes desde ~2189 ms hasta ~89 ms en 3D+1P.
- Kernel: el backend de producción vuelve al control FP4_FAST. SHA-256 de
  `libggml-rocmfpx-vulkan.so`:
  `40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
- Remapeo denso R1 sigue **STAGE** y no debe componerse todavía con producción.

## Siguiente experimento: Flash Attention a 8K

El perfil causal N=128/8K atribuye a Flash Attention 16.566 ms, el 23.11% del
tiempo GPU agrupado. Es el mayor hot path abierto después de cerrar los cambios
simples de gate/up. El siguiente experimento debe:

1. mapear el shader/pipeline exacto por capas y confirmar forma, strides,
   máscara, KV q8/q8, tamaño de subgroup y workgroup;
2. separar atención 1K/2K/4K/8K para confirmar el crecimiento y estimar el
   techo global antes de editar código;
3. inspeccionar ISA y recursos disponibles sin PMC inestable;
4. escoger una sola variante justificada de tile, vectorización o acceso KV;
5. validar correctitud, microbenchmark exacto hot/rotating y ABBA;
6. ejecutar Profile B y 3D+1P solamente si el microbenchmark gana al menos 3%
   local, equivalente a ~0.7% global máximo sobre la participación medida.

Conservar chunk128 durante la validación de servicio. Medir el kernel con el
runtime estable y no mezclarlo con R1.

## Hipótesis cerradas que no deben reabrirse sin evidencia nueva

- chunk96 y chunk256;
- caché adicional de Q8_1;
- rebatching de `6144x2048,N=1` (los cuatro usuarios ya están en `ne[2]`);
- gate/up con dos o cuatro subgroups;
- rows4 para short-conv;
- carga FP4 alineada de 32 bits;
- tile MMQ `BM=32,BN=128`;
- `BK_STEP=2` global o selectivo para gate/up.

El selectivo gate-only fue una mejora real pero insuficiente: diez pares AB/BA
dieron +0.486% de throughput (95% CI [+0.371%, +0.705%]) y outputs exactos
10/10. Es **REJECT** porque no alcanza el umbral V5 de 0.75% y añade una ruta
de shader completa. La implementación y su reversión permanecen en patches y
resultados para reproducibilidad.

## Control experimental

Usar el arnés V5 con un solo servidor y una sola carga GPU. Antes de cualquier
benchmark confirmar cuatro slots efectivos >=8192, KV q8/q8, modelo FP4_FAST
de 4.277124 BPW, chunk128 y ausencia de variables experimentales de shaders.
No cambiar clocks, perfiles de energía, drivers ni firmware.
