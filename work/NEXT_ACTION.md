# Próxima acción

## Producción después de V8

- Scheduler chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- Selective gate/up BK3 sigue **KEEP production**.
- Ninguna variante down V8 está promovida; todos sus selectores opt-in quedan
  desactivados por defecto.
- ROCmFPX `91655b2`; backend de control contemporáneo
  `3fd66d51fba2d2f1e4ae0e2957d119a05df96ec7022db5364bb6907652bd68dd`.

## Resultado que cambia la siguiente acción

La búsqueda down alcanzó 11 candidatos formales. `down-exact` ganó 2.1607%
local, pero su techo global estimado es solo ~0.50%; no cruza el gate de servidor.
Q8-group4 ganó 1.793% solo y no compuso. La familia queda cerrada como
**ARCHIVE COMPOSABLE**, no KEEP.

Gate/up exact-shape también convergió por debajo del gate. El mejor candidato
ganó 1.3163% local, IC 95% [-1.4474%, -0.4203%], pero su techo global es solo
~0.43%. Se conserva como **ARCHIVE COMPOSABLE** y no cambia producción.

## Siguiente experimento exacto

1. Reperfilar de forma ligera el mixed batch de producción actual para comprobar
   si gate/down/FA conservan sus shares después de BK3.
2. Si los shares se mantienen, no ampliar las especializaciones exact-shape:
   ninguna supera ~0.50% de techo global.
3. Abrir una sola hipótesis estructural de mayor leverage: software pipeline de
   loads/compute con evidencia estática de cambio real, o cerrar MMQ si añade
   registros/LDS sin ocultar latencia.
4. Si MMQ no ofrece un mecanismo con >0.75% de leverage, probar el primer
   scheduler EWMA con objetivo ~65 ms contra chunk128, manteniendo chunk128 como
   fallback y midiendo ITL/retention/TTFT.
5. Server-testear únicamente cambios que crucen el gate predeclarado.

No abrir todavía Flash Attention, R1 ni un sweep de scheduler. No repetir BM32,
BK_STEP, B-first, stride-hoist equivalente, split-K-only, boundary-only,
compile-time-K-only ni Q8-group4 combinado con down-exact.
