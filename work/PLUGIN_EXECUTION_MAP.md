# ROCmFPXVulkan0 execution map (V3)

Date: 2026-09-17  
ROCmFPX source: `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` plus the working patch  
Campaign repository HEAD: `6e99b2148030a08458e672bcc5eccdedfb63225e`

## Proven backend boundary

`ROCmFPXVulkan0` is not the integrated `ggml-vulkan` backend. `extensions/rocmfpx-vulkan/plugin.cpp` registers `rocmfpx-vulkan-charlie` and loads its sibling `libggml-rocmfpx-vulkan.so`; the implementation is built from `extensions/rocmfpx-vulkan/backend/ggml-vulkan.cpp` and its own shader tree.

The opt-in selection trace begins with:

```
VKSEL event=backend source=rocmfpx-vulkan-plugin
```

and then records the plugin pipelines actually dispatched. Consequently, changes to `ggml/src/ggml-vulkan/ggml-vulkan.cpp`, including `ggml_vk_rocmfpx_use_intdot(type, n)`, are **not executed** when the selected device is `ROCmFPXVulkan0`. They apply to the integrated Vulkan backend only. This invalidates any attribution of the plugin result to that selector.

## LFM2.5 path observed

The model graph uses LFM2 short-convolution/recurrent state plus attention; it does not use the Gated Delta Net path. The measured FP4_FAST projection path is:

1. contiguous F32 activation;
2. `quantize_q8_1_x4` when the RHS satisfies the integer-dot conditions;
3. `mul_mat_vec_rocmfp4_fast_q8_1_f32` for small N, or `matmul_rocmfp4_fast_q8_1_{s,m}` for prefill tiles;
4. recurrent `ssm_conv_f32`, F32 elementwise operations and, in attention layers, Flash Attention pipelines;
5. output projection in Q6_K/F32.

Representative dominant weight shapes are `M=10752,K=2048` (gate/up), `M=2048,K=10752` (down), `M=6144,K=2048` (short-conv input) and `M=2048,K=2048` (short-conv output). Decode traces contain effective N=1,2,4 and occasionally 6; therefore “C=4” must not be treated as synonymous with N=4.

In the mixed 128/64 trace, the most frequent plugin dispatches were:

| Pipeline | Calls |
| --- | ---: |
| `mul_mat_vec_rocmfp4_fast_q8_1_f32` | 21,705 |
| `quantize_q8_1_x4` | 16,430 |
| `rms_norm_mul_f32` | 6,958 |
| `mul_f32_f32_f32_norepeat` | 6,028 |
| `add_f32_f32_f32_norepeat` | 4,424 |
| `swiglu_f32` | 4,105 |
| `ssm_conv_f32` | 3,014 |

Source: `work/results/v3-shape-128x64-plugin/server.log`.

## Instrumentation

- `GGML_VK_SELECTION_LOGGER=1`: backend identity, selected pipeline, tensor name/type, M/N/K, strides, contiguity, RHS quantization/conversion, workgroups and dispatch geometry.
- `GGML_VK_PERF_LOGGER=1`: Vulkan timestamp totals per operation/shape. These runs serialize or synchronize work and are diagnostic only.
- `LLAMA_SERVER_BATCH_TRACE=1`: logical and physical sequence IDs per submitted server batch.
- `LLAMA_RECURRENT_TRACE=1`: recurrent microbatch IDs, tails, head and occupied-cell range.

The full selection trace reduced the 128/64 workload from roughly 103/228 tok/s (normal C1/C4) to 13.6/43.6 tok/s. Profiled times are therefore useful for ranking work inside a traced graph, not as service latency.

## Sparse-slot execution finding

Before the runtime change, logical `{0,1,3}` was split by `llama_batch_allocr::split_equal(..., sequential=true, ...)` into recurrent microbatches `{0,1}` and `{3}` on every decode step. `{0,1,2}` remained one microbatch. This duplicated graph composition and submission and explains the immediate measured cliff; it does not prove that every residual variation is caused by ID sparsity.

The V3 candidate separates stable logical slot IDs from dense model-facing IDs, sorts prompt/decode assembly by physical ID, and moves recurrent/KV state only after all results in `post_decode()` have been consumed. External task, cancellation and response associations continue to use the logical ID.

