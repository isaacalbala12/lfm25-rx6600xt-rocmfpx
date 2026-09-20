# V11: no modern inference engine supports this GPU

## Summary

The question "would vLLM, SGLang or Lucebox remove the Vulkan dispatch overhead"
now has a definitive answer, and it is not the one the question assumed. None of
the three can run on an RX 6600 XT, and the reason is not quantization, not
memory, and not configuration. It is that **RDNA2 is outside every one of their
support matrices.**

| Engine | AMD gfx targets it ships code for | RDNA2 (gfx103x) |
| --- | --- | --- |
| vLLM 0.29.0+rocm723 | gfx90a, gfx942, gfx950, gfx1100, gfx1101, gfx1150, gfx1151, gfx1200, gfx1201 | **no** |
| SGLang | gfx942, gfx950, gfx1151 | **no** |
| Lucebox | gfx1100, gfx1151, gfx1201 | **no** |

That is CDNA2/3/4 (MI200, MI300, MI350) plus RDNA3, RDNA3.5 and RDNA4. There is
no code object for any gfx103x part in any of them.

## vLLM, measured rather than assumed

The campaign's earlier vLLM figure (45.7 tok/s at C=4, FP16) was an unfair test:
running FP16 on a bandwidth-bound card means 5.39 GB of weights per decode step
against our 1.44 GB, so it was doomed before it started. The fair test needs a
4-bit checkpoint, so one was obtained.

**The format question is solved.** `plavno/LFM2.5-2.6B-AutoRound-W4A16` (1.81 GB,
`quant_method: auto-round`, 4 bits, group size 128, packed as `auto_gptq`) loads
into vLLM on this machine: *"Model loading took 1.72 GiB memory and 6.83
seconds"*. vLLM 0.29 has no `auto-round` quantizer registered, but the GPTQ
packing means `quantization="gptq"` reads it.

**The kernel question is not.** Loading succeeds and then the engine core dies
with SIGSEGV inside vLLM's own kernels:

```
!!!!!!! Segfault encountered !!!!!!!
  in hip::ihipLaunchKernel_validate(...)
  in csrc/libtorch_stable/layernorm_kernels.hip, line 264, in rms_norm(...)
```

Isolated one kernel at a time, with plain `torch` matmul as a control:

| Operation | Result |
| --- | --- |
| `torch` matmul (rocBLAS) | works |
| `torch.ops._C.rms_norm` | **segfault** |
| `torch.ops._C.fused_add_rms_norm` | **segfault** |
| `torch.ops._C.silu_and_mul` | **segfault** |

So it is systemic, not one bad kernel. The environment's
`HSA_OVERRIDE_GFX_VERSION=10.3.0` makes the runtime *report* gfx1030, but no
gfx1030 code object exists in the library, so the launches fail. Inspecting the
shipped extensions gives the reason directly:

```
_C.abi3.so            -> gfx90a gfx942 gfx950 gfx1100 gfx1101 gfx1150 gfx1151 gfx1200 gfx1201
_C_stable_libtorch.so -> gfx90a gfx942 gfx950 gfx1100 gfx1101 gfx1150 gfx1151 gfx1200 gfx1201
```

## SGLang and Lucebox

SGLang's ROCm docker directory contains exactly two files, `rocm.Dockerfile`
(documenting `GPU_ARCH=gfx942` and `gfx950`) and `rocm-gfx1151.Dockerfile`, whose
own comment notes that the general image "includes components which do not
support gfx1151". One consumer target, RDNA3.5, and nothing for RDNA2.

Lucebox's README lists its AMD targets as RDNA3 `gfx1100`, RDNA3.5 `gfx1151` and
RDNA4 `gfx1201`, and states that HIP builds must target the device's exact gfx
architecture. It is also the closest relative of this project: its quantization
list includes a "ROCmFPX MIX".

## Why ROCmFPX works and the others do not

This is not an accident of project choice. ROCmFPX runs on **Vulkan through
RADV, which compiles the shaders for whatever GPU is present at runtime.** It
needs no vendor code objects, no per-architecture wheel, and no support matrix
entry. That is precisely why it is the only viable path on this card.

The consequence reframes the earlier analysis: **the dispatch overhead measured
at 18% of the decode step is the price of the only execution path this GPU can
use.** The engines that would avoid it — CUDA graphs, fused vendor kernels,
tuned GEMM libraries — are exactly the engines that do not ship code for RDNA2.
There is no configuration, quantization or flag that changes this.

## What would change the answer

Rebuilding one of these engines with `gfx1032` added to its architecture list.
For vLLM that means building from source with `PYTORCH_ROCM_ARCH=gfx1032`:
one to three hours on this four-core host, 10-20 GB of disk, and a real chance
of failing on dependencies. Even if it built, it would start from behind, because
the 4-bit kernels would have to come from Triton dequantization, and the
measurements in `FORMAT_PREFILL_V11.md` show that removing FP4 unpacking does not
help on this part (Q8_0 was 16% slower at pp128 than the packed FP4 path).

**Decision: stay on ROCmFPX.** The engine question is closed. Remaining effort
goes into the prefill `down` gap and the dispatch fusions, which do not depend on
any engine's support matrix.
