# Resultado de la primera campaña V3

**Commit y entorno:** repositorio `6e99b2148030a08458e672bcc5eccdedfb63225e`; ROCmFPX `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` + `patches/ROCmFPX-gfx1032.patch`; Ryzen 5 1500X 4C/8T; RX 6600 XT/Navi23 `gfx1032`; sin cambios de sistema o potencia.

**Baseline contemporánea:** FP4_FAST coherente, ROCmFPXVulkan0, KV q8, b4096/u128: C1 102,8–104,5 tok/s; C4 estable 229,27–229,29 tok/s. Control disperso C3 `{0,1,3}`: 131,18–131,91 tok/s frente a 199,77–201,76 para `{0,1,2}`.

**Candidato:** IDs lógicos estables + IDs físicos densos, ensamblado por ID físico y migración de estado diferida al final de `post_decode()`; opt-in con `LLAMA_SERVER_COMPACT_SLOTS=1`.

**Problema demostrado:** el allocator recurrente secuencial dividía `{0,1,3}` en `{0,1}` + `{3}` cada paso. La simple relajación del selector no era segura y produjo una aserción de máscara de atención.

**Cambio implementado:** arnés válido/reproducible, trazas de selección, reproductor disperso y capa de IDs internos densos que preserva tareas, cancelación y respuestas por slot lógico.

**Pipeline realmente ejecutado:** plugin `rocmfpx-vulkan-charlie` → `libggml-rocmfpx-vulkan.so`; decode FP4_FAST usa `quantize_q8_1_x4` + `mul_mat_vec_rocmfp4_fast_q8_1_f32`. El `ggml-vulkan.cpp` integrado no interviene en `ROCmFPXVulkan0`.

**Microbenchmark/perfil:** todavía no hay microbenchmark causal promocionable. El perfil 2048/u128 identifica gate/up y down FP4_FAST como dominantes; la selección de decode contiene N=1/2/4/6. El profiler altera fuertemente la tasa del servidor.

**C1 / C4:** baseline normal 102,8–104,5 / 229,27–229,29 tok/s. El candidato no tiene todavía una confirmación C1/C4 emparejada estable; no se fabrica una cifra. En el caso causal C3 disperso alcanzó 176,98–193,93 tok/s en las tandas rápidas, frente a 131–132 original.

**TTFT / E2E p95:** no promocionables aún para el candidato. En la prueba dinámica trazada, TTFT individual 164–308 ms y E2E 674–1519 ms para salidas distintas, por lo que no forma una distribución homogénea.

**Contexto efectivo:** 128 tokens efectivos por solicitud en el reproducer; `n_ctx_slot=131072` informado por el servidor con cuatro slots. La campaña no interpreta `-c` como capacidad por slot sin leer `/props`/log.

**VRAM:** el sampler de dispositivo observó aproximadamente 6,61–6,66 GB durante la ejecución trazada, incluyendo VRAM ajena al proceso. No se usa como atribución de VRAM del candidato; la referencia previa de proceso/candidato sigue alrededor de 1,85 GiB.

**Correctitud:** 8/8 tests del arnés; cargas fija y EOS válidas; 4/4 solicitudes dinámicas válidas, desconexión tras ocho chunks y follow-up 32/32 válido. Falta comparación formal de logits y calidad de FP4_FAST.

**Incertidumbre:** repeticiones densas posteriores cayeron mientras mclk alternaba 541/1000 MHz. Es correlación, no causalidad cerrada. Falta A/B/B/A C4 con muestreo temporal fino.

**Decisión:** **STAGE**. No es todavía la configuración final de producción.

**Siguiente experimento:** A/B/B/A dinámico C4, control contemporáneo en cada pareja, clocks a mayor frecuencia y bootstrap por pareja/tanda; después logits y GEMV FP4_FAST N=1/2/4.

**Comando de reproducción:** `work/NEXT_ACTION.md`.
# Continuation checkpoint

The follow-on campaign separates R0/R1 runtime policy and K0/K1 kernel policy.
R1 passed active cancellation/recycle for forced initial, middle and final
holes with host sampling, but only 9/12 outputs were token-identical to R0
under non-identical concurrent ordering. Backend sampling exposed a reproducible
double-initialization abort and is now rejected explicitly. R1 remains STAGE.

An exact plugin microbenchmark was added for the observed FP4_FAST/Q8_1 decode
pipeline. A shape-specific four-subgroup reduction passed operation correctness
and won selected micro shapes, but regressed the full C4 server from 173.37 to
164.20 aggregate tok/s in the observed low/variable-clock run. K1 is REJECT.

See `work/SEQUENCE_REMAP_VALIDATION.md` and `work/KERNEL_MICROBENCH_V3.md`.
