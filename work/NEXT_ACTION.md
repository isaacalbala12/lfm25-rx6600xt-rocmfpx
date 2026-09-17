# Próxima acción

## Checkpoint V3

El HEAD principal sigue en `6e99b2148030a08458e672bcc5eccdedfb63225e`; ROCmFPX parte de `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1`. No se creó commit ni se hizo push. El equipo actual sigue siendo Ryzen 5 1500X 4C/8T y Navi23/gfx1032.

El arnés V3 está corregido y sus ocho tests pasan. El mapa de ejecución prueba que `ROCmFPXVulkan0` usa el backend Vulkan propio del plugin, no `ggml/src/ggml-vulkan`. El perfil 2048/u128 y el censo actual están en `work/PROFILE_V3.md` y `work/SHAPE_CENSUS_V3.csv`.

La baseline exacta del modelo coherente es aproximadamente 103,7 tok/s C1 y 228,0 C4. No sustituirla por 303,3 ni por los 230,5 históricos.

## Candidato en STAGE

`LLAMA_SERVER_COMPACT_SLOTS=1` activa IDs físicos densos sin cambiar los IDs lógicos de la API. Corrige el split recurrente demostrado y pasa el reproductor dinámico con finalizaciones distintas, desconexión y reciclaje. No está promovido a producción: falta una serie C4 emparejada estable, comparación de logits y evaluación formal de calidad.

Siguiente ejecución: A/B/B/A del runtime anterior frente al candidato en carga dinámica C4, con muestreo de clocks de mayor frecuencia. Resamplear por tanda, no por solicitudes hermanas. Si la ganancia sobrevive, ejecutar comparación de logits y después un microbenchmark del selector real para FP4_FAST GEMV N=1/2/4 con buffers calientes y rotación de matrices.

## Reproducción

```bash
work/tests/run_harness_tests.sh

source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH="$PWD/work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/rocmfpx-vulkan-plugin.so"
export LLAMA_SERVER_COMPACT_SLOTS=1
GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=128 MAX_TOKENS=64 \
  CONCURRENCIES="1 2 3 4" REPETITIONS=3 WARMUP=1 \
  work/scripts/benchmark_llama_backend.sh \
  --server work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server \
  --model work/results/models/LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf \
  --output work/results/reproduction-v3 -- \
  -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
```

No cambiar perfiles de energía, clocks, drivers ni firmware. Mantener una sola carga GPU y no hacer push hasta revisar el patch regenerado.
