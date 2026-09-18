# Próxima acción

## Producción V6

- Scheduler fixed chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- ROCmFPX `7c4b5c0`, fuente limpia.
- Backend restaurado real: `40f6b9c4768ed3fd1cb214e94983fe5a6e24dc85bb2c50eded662e9e07b25b40`.
- Selective BK3 no está instalado; queda **STAGE**.

## Siguiente experimento exacto

Confirmar `patches/v6-auto/gateup-selective-bkstep3.patch` sin cambiar scheduler
ni workload:

1. diez pares Profile B AB/BA, con outputs idénticos e intervalo por pares;
2. 3D+1P exploratorio y diez pares si conserva ITL/retention/TTFT;
3. resident C4 8K para guardrail >=260 tok/s y VRAM;
4. selector selectivo en N=120/128/129 y prueba de que down sigue BK4;
5. service EOS y corpus reservado antes de KEEP;
6. solo después probar BK3 + BK2 archivado, sin asumir aditividad.

Si BK3 no conserva valor en 3D+1P, rechazarlo para producto aunque gane Profile
B. Si lo conserva, medir un único scheduler temporal EWMA contra chunk128; no
mezclar kernel y scheduler en la primera comparación.

## Search loop

Compilar varias variantes opt-in en una biblioteca, alternarlas por variable de
entorno y restaurar una vez. El evaluador actual es correcto, pero recompila
cientos de shaders por patch. No ampliar el espacio hasta amortizar ese coste.

## No reabrir

Chunk96/256, caché Q8 adicional, rebatching 6144x2048, gate 2/4 subgroups,
rows4, packed32, BM32/BN128, BK2 global, FA V5, hybrid down N4, arithmetic
unpack, dual accumulators, Q2, backend híbrido, hipStreamSynchronize, MTP y
power/clocks.
