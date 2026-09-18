# Próxima acción

## Producción después de V8

- Scheduler chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- Selective gate/up BK3 sigue **KEEP production**.
- Ninguna variante down V8 está promovida; todos sus selectores opt-in quedan
  desactivados por defecto.
- ROCmFPX `063446d`; backend de control contemporáneo
  `ec4f79bc5545bbecded47b05a2b9bde6fd690c005ca3ef5b7181b0e0a5ff8540`.

## Resultado que cambia la siguiente acción

La búsqueda down alcanzó 11 candidatos formales. `down-exact` ganó 2.1607%
local, pero su techo global estimado es solo ~0.50%; no cruza el gate de servidor.
Q8-group4 ganó 1.793% solo y no compuso. La familia queda cerrada como
**ARCHIVE COMPOSABLE**, no KEEP.

## Siguiente experimento exacto

1. Volver a gate/up BK3 y gastar como máximo diez candidatos ortogonales.
2. Prioridad: progresión de punteros/address-hoisting que produzca una diferencia
   SPIR-V real; aplicar pre-gate estático antes de ocupar GPU.
3. Después probar una sola reorganización LDS justificada por bank mapping, sin
   aumentar indiscriminadamente los 18,960 bytes del control down.
4. Server-testear únicamente si el micro gana >=3% o si el leverage perfilado
   contemporáneo supera 0.75%.
5. Si gate también converge, reperfilar el mixed batch antes de decidir entre
   una hipótesis MMQ nueva o el primer scheduler EWMA de ~65 ms.

No abrir todavía Flash Attention, R1 ni un sweep de scheduler. No repetir BM32,
BK_STEP, B-first, stride-hoist equivalente, split-K-only, boundary-only ni
Q8-group4 combinado con down-exact.
