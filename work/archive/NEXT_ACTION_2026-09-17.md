# Próxima acción

## Checkpoint actual

El ganador contemporáneo para 128/64 y 512/128 es ROCmFPX
`ROCmFPXVulkan0` con FP4_FAST, KV q8, `b512/ub128`, `-np 4 -cb` y
`LLAMA_SERVER_COMPACT_SLOTS=1`. En 200 peticiones 128/64 C4 da 233,99 tok/s
frente a 226,65 upstream, sin fallos, y usa ~153 MiB menos de VRAM. El IC95%
emparejado del delta es +2,77 a +3,84%.

Para 2048/256 y 7680/512 gana llama.cpp upstream Q4_0. Con b4096/u128,
2048/256 C4 da 101,66 frente a 99,98 tok/s; la pantalla 7680/512 da 92,40
frente a 88,58. No declarar un único ganador sin especificar la forma de carga.

## Siguiente experimento de mayor valor

La criba contemporánea de formatos ya está cerrada: FP4_FAST conserva el mejor
C4; Q2 gana C1 bruto pero queda rechazado por calidad. El siguiente paso es una
evaluación formal de calidad/perplexity de FP4_FAST frente al checkpoint BF16 y
Q4_0/Q4_K_M, con un corpus reservado y hashes de cada artefacto.

Después, perfilar trace-only el prefill largo 2048/256 de ambos finalistas para
localizar el cruce (matmul/dequant/attention/SSM) y decidir si algún kernel del
plugin puede corregirse o portarse. Los perfiles 512/128, 2048/256 y la
pantalla 7680/512 ya están ejecutados. No usar contadores PMC.

## Bloqueos y límites

- No cambiar perfiles de energía, drivers, firmware ni servicios sin permiso.
- El perfil COMPUTE podría aclarar el cliff u512, pero no está autorizado y no
  es necesario para la configuración ganadora.
- La calidad FP4_FAST solo tiene smoke funcional; falta una evaluación formal
  contra BF16/perplexity antes de un despliegue que exija equivalencia de calidad.
- No publicar ni hacer push. El árbol ROCmFPX contiene cambios locales que deben
  revisarse y separarse antes de un commit.

## Comando de producción actual

```bash
source /home/isaac/vllm-challenge/env.sh
unset HSA_OVERRIDE_GFX_VERSION
export LD_PRELOAD=/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6:/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1
export ROCMFPX_PLUGIN_PATH=/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/builds/rocmfpx-vulkan-gfx1032-cm1/bin/rocmfpx-vulkan-plugin.so
export LLAMA_SERVER_COMPACT_SLOTS=1
/home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/builds/rocmfpx-vulkan-gfx1032-cm1/bin/llama-server \
  -m /home/isaac/Documents/Codex/2026-09-16/recalcar-vas-a-estar-en-paralelo-2/work/results/models/LFM2.5-2.6B-ROCmFP4_FAST.gguf \
  -dev ROCmFPXVulkan0 -ngl 99 -fa on -np 4 -cb -c 4096 -b 512 -ub 128 \
  -ctk q8_0 -ctv q8_0 --no-cache-prompt --cache-reuse 0
```

Commit: no creado. El cambio de scheduler se aisló correctamente, pero Git
rechazó el commit porque el repositorio no tiene `user.name`/`user.email`.
No se inventó ni cambió la identidad del usuario; tampoco quedó nada staged.
Cuando exista identidad, el commit aislado se obtiene con:

```bash
git -C work/sources/ROCmFPX add -- tools/server/server-context.cpp
git -C work/sources/ROCmFPX commit -m "server: add opt-in compact slot scheduling"
```
