# Próxima acción

## Producción después de V9

- Scheduler fijo chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- Selective gate/up BK3 sigue **KEEP production**.
- El scheduler temporal EWMA y gate BK3 bpair están desactivados por defecto.
- ROCmFPX `f5acc76`; verificar el hash del backend después de cada rebuild.

## Resultado que cambia la siguiente acción

La baseline contemporánea 3D+1P mide 78.257 ms de mediana por mixed batch,
88.471 ms de ITL p95 y 16.313% de retention. El perfil diagnóstico separa dos
grafos: decode 16.51% y prefill 83.49%. Dentro de prefill, gate/up es 35.34% y
down 26.64%.

El prefetch de dos columnas Q8 añadió instrucciones/cargas y regredió 0.767%.
El scheduler EWMA65 mejoró ITL 14.63% pero empeoró TTFT 47.97%; EWMA68 repitió
la misma frontera. Ambos quedan cerrados. Chunk128 permanece producción.

## Siguiente experimento exacto

1. Prototipar prepacking reversible para **una** matriz gate/up real, conservando
   exactamente códigos FP4 y escalas.
2. Elegir el layout a partir del consumo wave32 (`K-block` y `M-tile`), no de
   una analogía con Metal u otra GPU.
3. Incluir coste de pack, VRAM y fallback; no duplicar el modelo completo.
4. Medir exact-plugin N=127, N=128 y un tail real, con buffers calientes y
   rotación entre matrices.
5. Exigir >=2.55% local aproximadamente antes de servidor: con el share actual
   es lo necesario para superar 0.75% de leverage mixed.
6. Si falla, cerrar MMQ y descomponer el 9.15% `other` del grafo prefill por
   operación antes de reabrir FA o scheduler.

No hacer más sweep de chunks/targets. No repetir bpair, exact-shape/bounds,
BK_STEP, BM32, B-first, Q8-group4 ni las familias cerradas de V4--V8.
