# Próxima acción

## Estado de producción V5

- Scheduler: `LLAMA_SERVER_PREFILL_CHUNK_TOKENS=128` es **KEEP production**.
  Pasó equivalencia controlada y el corpus reservado con EOS normal. Reduce la
  ITL p95 de residentes desde ~2189 ms hasta ~89 ms en 3D+1P.
- Kernel: el backend de producción vuelve al control FP4_FAST. SHA-256 de
  `libggml-rocmfpx-vulkan.so`:
  `40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
- Checkpoint ROCmFPX local: `7c4b5c0`; scheduler experimental y selectores
  negativos están revertidos. El `libllama-server-impl.so` reconstruido es
  `a056472b0980a05ea81ee78063d561126660aa119b9ff263245549cd4acab33d`.
- Remapeo denso R1 sigue **STAGE** y no debe componerse todavía con producción.

## Siguiente experimento: scheduler temporal decode-aware

Flash Attention y los cambios de geometría cooperativa quedan cerrados. La
variante hybrid exacta de down `M=2048,K=10752,N=4` regresa +17.744%, así que
una wave32 subgroup sigue siendo el control. Dos cambios internos adicionales
también han fallado: arithmetic unpack (+44.672%) y dual accumulator (+9.872%).
Sin una señal ISA nueva, el leverage inmediato vuelve al scheduler interactivo.

Usar runtime estable y chunk128 como control:

1. conservar LUT y acumulación simple: arithmetic unpack y dual-accumulator
   regresan +44.672% y +9.872%;
2. detener la microtuning especulativa de decode gate/up sin ISA nueva;
3. volver al leverage de servicio: medir una política temporal adaptativa
   chunk128/96 basada en duración EWMA, con máximo tres candidatos focalizados;
4. exigir una mejora del frente ITL/TTFT en 3D+1P y mantener C4 residente;
5. solo entonces componer el BK2 gate-only archivado si la mejora es
   contemporánea; no hacer otro sweep de rows/waves.

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
- hybrid/large para down `2048x10752,N=4` (+17.744% latencia).
- desempaquetado FP4_FAST aritmético para gate/up N=4 (+44.672% latencia).
- doble banco de acumuladores gate/up N=4 (+9.872% latencia).
- prefill idle ilimitado (rompe equidad del batch).

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

El scheduler decode-aware acotado (idle512/active128) queda archivado: gana
+0.259% en prompt-only, pero no mejora el único guardrail 3D+1P. Fixed chunk128
sigue siendo la configuración de producción.

## Control experimental

Usar el arnés V5 con un solo servidor y una sola carga GPU. Antes de cualquier
benchmark confirmar cuatro slots efectivos >=8192, KV q8/q8, modelo FP4_FAST
de 4.277124 BPW, chunk128 y ausencia de variables experimentales de shaders.
No cambiar clocks, perfiles de energía, drivers ni firmware.
