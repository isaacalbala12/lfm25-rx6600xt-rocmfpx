#pragma once

// RDNA2/gfx103x has no MFMA/WMMA path, so ROCmFPX uses the existing DP4A
// loaders.  Keep the tile geometry aligned with the native RDNA2 table and
// reuse the ROCmFPX scale-layout choices used by the RDNA3 fallback path.
//
// This is intentionally a small, conservative table.  It makes the custom
// types executable on RDNA2 without claiming that RDNA3/4 launch shapes are
// optimal for gfx1032; performance tuning belongs in a separate A/B pass.
static constexpr __host__ __device__ ggml_cuda_mmq_config ggml_rocmfpx_mmq_get_config_rdna2(
        ggml_type type, int J, bool fallback) {
    auto layout = GGML_CUDA_MMQ_SRAM_LAYOUT_Q8_0;
    bool supported = true;

    switch (type) {
        case GGML_TYPE_Q4_0_ROCMFP4_FAST:
        case GGML_TYPE_Q4_0_ROCMI4:
        case GGML_TYPE_Q8_0_ROCMFPX:
            break;
        case GGML_TYPE_Q4_0_ROCMFP4:
        case GGML_TYPE_Q2_0_ROCMFPX:
        case GGML_TYPE_Q3_0_ROCMFPX:
        case GGML_TYPE_Q6_0_ROCMFPX:
            layout = GGML_CUDA_MMQ_SRAM_LAYOUT_Q3_K;
            break;
        default:
            supported = false;
            break;
    }

    // RDNA2's DP4A table uses 256 threads and I=128 for J=8..64.
    if (supported && J >= 8 && J <= 64 && J % 8 == 0) {
        return ggml_cuda_mmq_config(type, 256, 2, 128, J, layout, MMQ_ITER_K, false, fallback);
    }

    return ggml_cuda_mmq_config(GGML_TYPE_COUNT, 256, 2, 128, 64,
        GGML_CUDA_MMQ_SRAM_LAYOUT_Q8_0, 256, false, true);
}
