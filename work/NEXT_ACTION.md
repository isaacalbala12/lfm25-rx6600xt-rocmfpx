# Próxima acción

## Producción V7

- Scheduler fixed chunk128 **KEEP**; runtime R0; R1 sigue STAGE.
- ROCmFPXVulkan0 FP4_FAST, KV q8/q8, C=4, >=8192 tokens/slot.
- Selective gate/up BK3 **KEEP**; down y decode permanecen en sus rutas control.
- ROCmFPX `283a889`, fuente limpia.
- Backend real: `5b3b36d54c45e7b8f6c51e654dcca96726e8fe02f4418b4e43cea0a593edc763`.

## Siguiente experimento exacto

1. Añadir un banco opt-in de variantes ortogonales en una sola biblioteca.
2. Hacer reanudable el driver y deduplicar por contenido/mutación, no por nombre.
3. Usar BK3 como incumbent y probar primero una modificación estructural del
   K-loop respaldada por la reducción de instrucciones SPIR-V observada.
4. Si diez candidatos válidos no mejoran el incumbent, cerrar gate/up y
   parametrizar el evaluator para down `M=2048,K=10752,N=128`.
5. Probar en servidor únicamente candidatos con leverage global >=0.75%.

No abrir todavía scheduler EWMA: primero debe existir otro kernel KEEP y debe
repetirse la timeline del mixed batch.

## No reabrir

Chunk96/256, caché Q8 adicional, rebatching 6144x2048, gate 2/4 subgroups,
rows4, packed32, BM32/BN128, BK2 global, FA V5, hybrid down N4, arithmetic
unpack, dual accumulators, Q2, backend híbrido, hipStreamSynchronize, MTP y
power/clocks.
