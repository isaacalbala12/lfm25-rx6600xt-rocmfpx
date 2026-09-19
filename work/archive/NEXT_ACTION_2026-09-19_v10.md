# Próxima acción

## Producción después de V10

- Scheduler fijo chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- Selective gate/up BK3 sigue **KEEP production**.
- Todos los layouts y selectores de búsqueda V8--V10 están desactivados por
  defecto.
- ROCmFPX search-bank `8634463`; backend
  `f89f3faaa85b22c5257b5194ea42aa3af9644afc93330bc2ab18f48fd26b4724`.

## Resultado que cierra la familia actual

El bloque padded alineado mejora gate/up 1.227%, pero sólo aporta ~0.36% de
techo mixed y aumenta 17.65% el almacenamiento de esos pesos. El plano global
compacto regresa 43.15% por pérdida de localidad de escalas. El agrupado local
sin memoria extra regresa 3.85%. El prepacking/layout gate/up probado queda
cerrado.

La composición de gate exact-shape + down exact mejora Profile B 0.549% en tres
pares, por debajo del umbral de promoción, y una de doce respuestas diverge.
Queda ARCHIVE COMPOSABLE, no producción.

## Siguiente experimento exacto

1. Descomponer el 9.15% `misc` del grafo prefill V9 por operación y por grafo,
   reutilizando la traza existente antes de generar otra invasiva.
2. Separar como mínimo RMS norm/rope, ADD, GLU, CPY/SSM-conv, CONCAT y MUL;
   registrar tiempo exclusivo, llamadas, shape y pipeline.
3. Calcular `share * plausible_local_gain` para cada familia. No implementar
   nada cuyo techo razonable no supere 0.75% del mixed batch.
4. Si ninguna operación misc alcanza el umbral, cerrar MMQ/misc y formular una
   hipótesis algorítmica de Flash Attention distinta de los tile sweeps cerrados.
5. Mantener chunk128 como fallback. No reabrir scheduler hasta que un cambio de
   kernel reduzca materialmente el batch mixed o exista una política que no
   viole TTFT <=5.5 s.

No repetir padding/planar/group-size layouts, bpair, exact-shape aislado,
BK_STEP, BM32, B-first, Q8-group4 ni sweeps de chunks/targets.
