# Próxima acción

## Checkpoint V3

El punto de revisión padre de esta continuación es `bad60333b6c694915e3ce9777f0cde62fe883ed2`; ROCmFPX parte de `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1`. El trabajo se conserva en un commit local de `campaign-v3`; no se hizo push. El equipo actual sigue siendo Ryzen 5 1500X 4C/8T y Navi23/gfx1032.

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
export LLAMA_SERVER_LOWEST_SLOT=1
export LLAMA_SERVER_DENSE_SEQUENCES=0
GPU_RESERVATION_CONFIRMED=1 PROMPT_TOKENS=128 MAX_TOKENS=64 \
  CONCURRENCIES="1 2 3 4" REPETITIONS=3 WARMUP=1 \
  work/scripts/benchmark_llama_backend.sh \
  --server work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented/bin/llama-server \
  --model work/results/models/LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf \
  --output work/results/reproduction-v3 -- \
  -b 4096 -ub 128 -ctk q8_0 -ctv q8_0
```

No cambiar perfiles de energía, clocks, drivers ni firmware. Mantener una sola carga GPU y no hacer push hasta revisar el patch regenerado.
# Checkpoint after V3 runtime/kernel continuation

1. Keep production on R0/K0. R1 remains STAGE for host sampling; K1 is REJECT.
2. Close remap equivalence with a deterministic stepwise harness that fixes the
   batch schedule and compares logits immediately before and after a move.
3. Repeat normal-API arrival/cancel/recycle cycles (not forced IDs), then use at
   least ten paired batches for the dynamic-service delta.
4. Add backend support for transferring an initialized sampler chain before
   allowing `backend_sampling` with dense remapping; the current combination
   must continue to return HTTP 400.
5. For kernels, timestamp Q8_1 preparation and MMV dispatch separately inside
   the exact plugin microbenchmark. Revisit only the M=2048 N=2 and N=4 shapes;
   do not promote the current selector without a server win.

Rebuild from ROCmFPX `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` and apply
the cumulative continuation patch plus the untracked RDNA2 header retained in
the original patch:

```bash
git apply /path/to/patches/campaign-v3-runtime-kernel.patch
git apply --include='ggml/rocmfpx/rocmfpx_mmq_rdna2.cuh' \
  /path/to/patches/ROCmFPX-gfx1032.patch
```
