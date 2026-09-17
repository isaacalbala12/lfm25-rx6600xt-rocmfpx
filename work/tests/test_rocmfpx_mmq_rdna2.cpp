#include "ggml.h"

#define GGML_COMMON_DECL_CPP
#define GGML_COMMON_DECL_HIP
#include "ggml-common.h"

#include <cstdio>

// Compile the selector tables without HIP or a GPU.  The generated header is
// produced by ROCmFPX's check-rocmfpx-reference.sh script.
#define __host__
#define __device__
#define GGML_ROCMI4_W4A4 0
#define MMQ_TILE_NE_K 32
#define MMQ_ITER_K 256
#define MMQ_ITER_K_FP4 512
static bool amd_mfma_available(int) { return false; }
static bool amd_wmma_available(int) { return false; }
static bool turing_mma_available(int) { return false; }

#include "rocmfpx-mmq-config-extract.h"

#include <initializer_list>

static bool is_custom(const ggml_type type) {
    return type == GGML_TYPE_Q4_0_ROCMFP4 || type == GGML_TYPE_Q4_0_ROCMFP4_FAST ||
           type == GGML_TYPE_Q4_0_ROCMI4 || type == GGML_TYPE_Q2_0_ROCMFPX ||
           type == GGML_TYPE_Q3_0_ROCMFPX || type == GGML_TYPE_Q6_0_ROCMFPX ||
           type == GGML_TYPE_Q8_0_ROCMFPX;
}

static ggml_cuda_mmq_sram_layout expected_layout(const ggml_type type) {
    switch (type) {
        case GGML_TYPE_Q4_0_ROCMFP4:
        case GGML_TYPE_Q2_0_ROCMFPX:
        case GGML_TYPE_Q3_0_ROCMFPX:
        case GGML_TYPE_Q6_0_ROCMFPX:
            return GGML_CUDA_MMQ_SRAM_LAYOUT_Q3_K;
        default:
            return GGML_CUDA_MMQ_SRAM_LAYOUT_Q8_0;
    }
}

int main() {
    int checked = 0;
    for (int t = 0; t < GGML_TYPE_COUNT; ++t) {
        const auto type = static_cast<ggml_type>(t);
        if (!is_custom(type)) {
            continue;
        }

        for (const bool fallback : {false, true}) {
            for (int J = 8; J <= 64; J += 8) {
                const auto got = ggml_cuda_mmq_get_config_rdna2(type, J, fallback);
                const auto expected = ggml_cuda_mmq_config(type, 256, 2, 128, J,
                    expected_layout(type), MMQ_ITER_K, false, fallback);
                if (got.type != expected.type || got.nthreads != expected.nthreads ||
                    got.occupancy != expected.occupancy || got.I != expected.I ||
                    got.J != expected.J || got.sram_layout != expected.sram_layout ||
                    got.K_vram != expected.K_vram || got.stream_k != expected.stream_k ||
                    got.fallback != expected.fallback) {
                    std::fprintf(stderr, "FAIL RDNA2 custom config: type=%d J=%d fallback=%d\n",
                        t, J, fallback);
                    return 1;
                }
                ++checked;
            }

            for (const int J : {0, 72, 80}) {
                const auto got = ggml_cuda_mmq_get_config_rdna2(type, J, fallback);
                if (got.type != GGML_TYPE_COUNT || !got.fallback) {
                    std::fprintf(stderr, "FAIL RDNA2 unsupported config: type=%d J=%d fallback=%d\n",
                        t, J, fallback);
                    return 1;
                }
            }
        }
    }

    // Confirm the extension did not replace a normal RDNA2 table entry.
    const auto standard = ggml_cuda_mmq_get_config_rdna2(GGML_TYPE_Q4_0, 32, false);
    if (standard.type != GGML_TYPE_Q4_0 || standard.nthreads != 256 || standard.I != 128 ||
        standard.J != 32 || standard.sram_layout != GGML_CUDA_MMQ_SRAM_LAYOUT_Q8_0) {
        std::fprintf(stderr, "FAIL RDNA2 standard Q4_0 control\n");
        return 1;
    }

    std::printf("PASS RDNA2 MMQ: %d ROCmFPX configurations and standard control\n", checked);
    return 0;
}
