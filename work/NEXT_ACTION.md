# Próxima acción

## Estado de producción tras V11

Dos perfiles, separados por forma de carga. No hay ganador universal.

| Perfil | Formato | Batch | Scheduler | Gana en |
| --- | --- | --- | --- | --- |
| `production-throughput` | FP4_FAST | `b512/ub128` + slots compactos | chunk128 fijo | 128/64 y 512/128; decode residente en reposo |
| `production-interactive` | Q4_0 | `b4096/ub128` | chunk128 fijo | 8K mixto con cuatro slots |

- Scheduler fijo chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- Selective gate/up BK3 sigue **KEEP** en el perfil 8K.
- Todos los selectores de búsqueda V8--V10 siguen desactivados por defecto.
- El árbol ROCmFPX anidado queda en `8634463`.

## Resultado que cierra V11

**La elección de formato estaba mal muestreada.** La criba de formatos se hizo
una sola vez, en 128/64 y 512/128, formas donde el decode domina. Cuando V4--V9
cambiaron el objetivo a una carga 8K dominada por prefill (83,49% del par
mixto), nadie volvió a cribar.

En la forma de prefill real:

| Modelo | bpw | pp128 | pp512 | pp2048 | tg128 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ROCmFP4_FAST | 4,25 | 2271,27 | 2459,04 | 2389,32 | **132,74** |
| Q8_0 | 8,50 | 1907,07 | 2205,66 | 2174,76 | 76,03 |
| Q4_0 | 4,70 | **2621,13** | **2738,75** | **2668,87** | 123,87 |

Y en el A/B de servicio a 8K, tres pares emparejados, Q4_0 contra FP4_FAST:

| Métrica | FP4_FAST | Q4_0 | Delta emparejado | IC95% |
| --- | ---: | ---: | ---: | --- |
| TTFT de usuario nuevo | 5197,42 ms | 4847,29 ms | **−6,982%** | [−7,056, −6,410] |
| ITL p95 residente durante prefill | 88,53 ms | 82,97 ms | **−7,164%** | [−8,548, −3,799] |
| Retención de decode | 15,96% | 17,82% | **+11,612%** | [+11,320, +12,138] |
| Agregado residente sin prefill | 238,94 tok/s | 229,48 tok/s | −3,96% | — |

La hipótesis que motivó la criba (que Q8_0, sin desempaquetado FP4, sería más
rápido en prefill) queda **refutada**: Q8_0 es 16,0% más lento en pp128. El
formato de más bits no compra nada aquí. Lo que sí aparece es que el ranking de
formatos se invierte con la forma.

El objetivo de interactividad **sigue sin alcanzarse**: ITL p95 82,97 ms contra
≤70 ms, un 18,5% por encima. TTFT sí queda cómodo (4847 ms contra 5500 ms).

## Control de regresión que faltaba

La métrica primaria del README (128/64, C=4) no se había vuelto a medir desde
V2, pese a que V3 detectó 229,27 frente a los 233,99 publicados y lo dejó como
"estado de artefacto distinto" sin resolverlo. Medida ahora sobre el binario de
producción actual:

| Concurrency | V2 publicado | V11 medido | Delta |
| ---: | ---: | ---: | ---: |
| 1 | 108,01 | 107,96 | −0,04% |
| 2 | 169,12 | 167,72 | −0,83% |
| 3 | 207,71 | 206,28 | −0,69% |
| 4 | 233,99 | 230,82 | −1,36% |

Las cuatro celdas son `VALID`. El titular publicado aguanta dentro del 1,4%. El
residuo es el coste conjunto de todo lo que cambió después de V2, medido en la
propia métrica que el repositorio anuncia, y no se puede atribuir a un solo
cambio desde esta medida.

## Siguiente experimento exacto

1. **Extender la criba de formatos a todas las formas** ya registradas en
   `BASELINES.json`: 512/128, 2048/256, 7680/512, con y sin slots compactos. La
   tabla de V2 sugiere que Q4_0 ya ganaba en 2048/256 y 7680/512; hay que
   confirmarlo con el arnés actual y decidir el formato por forma, no una vez.
2. **Re-medir la métrica primaria 128/64 en cada promoción futura.** Añadirla
   como puerta obligatoria junto a las de 8K: ningún cambio de kernel se
   promueve ya con evidencia de un solo perfil.
3. **Evaluación formal de calidad** de FP4_FAST y Q4_0 contra el checkpoint
   BF16 con `llama-perplexity`, que ya está construido. Sigue pendiente desde el
   17 de septiembre y es lo único que bloquea una afirmación de despliegue.

No reabrir: familia de layouts FP4 (padding/planar/group4), BK_STEP, BM32,
B-first, Q8-group4, bpair, barridos de chunk o target, EWMA 65/68. V10 cerró el
layout y V11 explica por qué no podía pagar: el cuello no está ahí.

## Límites

- No cambiar perfiles de energía, drivers, firmware ni servicios.
- No usar contadores PMC.
- Las medidas de V11 son de servicio sin instrumentar salvo donde se indique.
