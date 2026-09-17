# ROCmFPX / RDNA2 audit for LFM2.5-2.6B

This is the reproducibility record for the RX 6600 XT / gfx1032 work. GPU
measurements are kept separate from host-only checks. The runs recorded here
were performed solo; Sunshine was removed after it was implicated in the
graphics-session failure described in `work/RESULTS.md`.

## Source revisions

| Component | Revision | Local path |
| --- | --- | --- |
| ROCmFPX official repository | `aed0d5fd9620ee96a10cb4e6b16c18514ea370e1` (2026-09-06) | `work/sources/ROCmFPX` |
| upstream llama.cpp | `930e2fa5995789efbf249a8bf61325bb626e417b` (2026-09-16) | `work/sources/llama.cpp` |

The public ROCmFPX repository is the current canonical stack; the older
`charlie12345/ROCmFPX` lineage remains reachable but is not the build source.

## RDNA2 support finding

The official tree includes `scripts/build-rdna2.sh`, automatic `gfx103x`
selection, HIP code-object verification, and documentation that lists RDNA2
as a supported CPU/Vulkan/HIP tier. The unmodified `mmq-config-rdna2.cuh`,
however, had no ROCmFPX custom-type cases. Custom types therefore reached the
generic `GGML_TYPE_COUNT` return and the HIP MMQ dispatcher aborted with
`J_best=0` on gfx1032.

The local experimental fix is deliberately conservative:

- `ggml/rocmfpx/rocmfpx_mmq_rdna2.cuh` adds DP4A-compatible configurations for
  `Q4_0_ROCMFP4`, `Q4_0_ROCMFP4_FAST`, `Q4_0_ROCMI4`, `Q2/Q3/Q6_0_ROCMFPX`, and
  `Q8_0_ROCMFPX`.
- `ggml/src/ggml-cuda/mmq-config-rdna2.cuh` calls that table only after the
  standard RDNA2 entries, so standard quantizations retain their original
  path.
- The initial geometry is 256 threads, occupancy 2, `I=128`, `J=8..64`,
  `MMQ_ITER_K=256`; dual-scale formats use the Q3-K shared-memory layout and
  speed-layout formats use Q8-0 layout.

Host-only validation passes 112 custom configurations and the standard Q4_0
control:

```text
PASS RDNA2 MMQ: 112 ROCmFPX configurations and standard control
PASS RDNA3 MMQ: 112 ROCmFPX configurations, 3920 unchanged vanilla/unsupported controls
```

The test source is `work/tests/test_rocmfpx_mmq_rdna2.cpp`; the reference
script is `work/sources/ROCmFPX/scripts/check-rocmfpx-reference.sh`.

## Built backends

| Backend | Build artifact | Status |
| --- | --- | --- |
| ROCmFPX HIP, gfx1032 | `work/builds/rocmfpx-hip-gfx1032-fpx-mmfix-v1/bin` | built; native gfx1032 direct and C<=4 screen pass with the override unset |
| ROCmFPX HIP, gfx1030 fallback | `work/builds/rocmfpx-hip-gfx1030-fpx-mmfix-v1/bin` | built; model load and GPU generation smoke pass with the matching Tensile library path |
| ROCmFPX Vulkan scalar | `work/builds/rocmfpx-vulkan-gfx1032-scalar/bin` | built |
| ROCmFPX Vulkan integrado + CM1/plugin | `work/builds/rocmfpx-vulkan-gfx1032-cm1/bin` | ambos construidos; `Vulkan0` y `ROCmFPXVulkan0` probados |
| llama.cpp HIP, gfx1032 | `work/builds/llama-hip-gfx1032-v1/bin` | built |
| llama.cpp HIP, gfx1030 fallback | `work/builds/llama-hip-gfx1030-v1/bin` | built |
| llama.cpp Vulkan | `work/builds/llama-vulkan-gfx1032-v1/bin` | built |

All builds use the local ROCm 7.14 toolchain and the requested GPU target.
With `HSA_OVERRIDE_GFX_VERSION=10.3.0` the installed HIP runtime exposes the
card as gfx1030, so a gfx1032 code object is not accepted. The native gfx1032
tests therefore run with that variable explicitly unset; the gfx1030 build is
kept only as a compatibility fallback. vLLM remains a separate exception
because its installed ROCm wheel requires the gfx1030 override.

The optional Charlie Vulkan extension needs the GCC 16 `libstdc++` shipped in
the isolated toolchain. In this build the backend RPATH searches the system
directory first, whose library does not provide the required
`_ZNSt8__format15__do_vformat_to...@GLIBCXX_3.4.35` symbol. Loading the matching
toolchain libraries with `LD_PRELOAD` registers `ROCmFPXVulkan0` successfully;
no system or vLLM library was changed. Under that runtime, FP4_FAST with
`b512/ub128` completed the common C=1..4 matrix at 103.8 / 160.6 / 204.3 /
233.2 tok/s and 1.865 GiB peak VRAM.

## Quantization inventory

The ROCmFPX quantizer currently exposes these relevant families:

- `Q4_0_ROCMFP4` (dual-scale, 4.50 bpw)
- `Q4_0_ROCMFP4_FAST` (single-scale speed layout, 4.25 bpw)
- `Q4_0_ROCMFP4_COHERENT` and `Q4_0_ROCMFP4_FAST_COHERENT`
- `Q4_0_ROCMFP4_EVEN`, `Q4_0_ROCMFP4_FAST_EVEN`, `Q4_0_ROCMFP4_LEAN`
- `Q2_0_ROCMFPX`, `Q3_0_ROCMFPX`, `Q5_0_ROCMFPX`, `Q6_0_ROCMFPX`,
  `Q7_0_ROCMFPX`, `Q8_0_ROCMFPX`
- `_AGENT`, `_LEAN`, and `Q4_0_ROCMI4` variants where exposed by the build
- standard `Q4_0` and `Q4_K_M` baselines

Dry-run sizes from the same LFM2.5-2.6B Q8 source (before GPU qualification)
were approximately: Q2 ROCmFPX 2.90 bpw, Q3 ROCmFPX 4.27 bpw, ROCmFP4 FAST
4.25 bpw, ROCmFP4 FAST COHERENT 4.48 bpw, standard Q4_0 4.70 bpw, Q4_K_M
4.94 bpw, Q6 ROCmFPX 6.57 bpw, Q8 ROCmFPX 8.25 bpw. These are size
expectations, not performance or quality claims.

## Measurement status

The full comparable server matrix is post-reset and post-Sunshine removal:
same tokenizer, p=128, max output=64, warmup=1, three repetitions, randomized
non-prefix-reusing prompts, and C=1..4. Vulkan backends use `-fa on`,
continuous batching, `-np 4`, and the tested batch/ubatch/KV settings. The
current production candidates and the complete leaderboard are in
`work/RESULTS.md`. The integrated ROCmFPX Vulkan backend and the optional
`ROCmFPXVulkan0` plugin are recorded as separate rows; the plugin run is in
`work/results/rocmfpx-vulkan-plugin-b512-ub128`.

Hardware PMC counter profiling is intentionally not repeated in this session:
the earlier counter run coincided with an amdgpu reset. Safe trace-only
profiling was completed instead and is summarized in the results report.
