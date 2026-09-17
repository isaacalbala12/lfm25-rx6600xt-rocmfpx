# Excluded model artifacts

The GGUF files are not stored in this Git repository because each is roughly
1–1.8 GB. Reproduction must verify these SHA-256 hashes before comparing
results:

| Model | Bytes | SHA-256 |
| --- | ---: | --- |
| LFM2.5-2.6B-Q4_0.gguf | 1,593,894,912 | `a71d1b80e0f5914e899d366a0ef82c8f1ccecd40f1f4dc1329e1c8eeb7357fd7` |
| LFM2.5-2.6B-ROCmFP4_FAST.gguf | 1,442,031,616 | `d56f602eb9bcad2cafbe2a52cef2fa14ba09e6290679a2aee164db22815f0933` |
| LFM2.5-2.6B-ROCmFP4.gguf | 1,778,739,200 | `e632c792165ca22147a976ac463aba0842a6df37776a6d26f4682c8f439339d5` |
| LFM2.5-2.6B-ROCmFP4_FAST_COHERENT-own.gguf | 1,517,807,616 | `6221ae208de5102fe33fc2b246f6a34db32d0a2f20e371d2184838073f182198` |
| LFM2.5-2.6B-ROCmFPX-Q3.gguf | 1,448,380,608 | `c25a2b739a647c542ad2da1a499f2119d413e976e170930213b49d932bc9f63d` |
| LFM2.5-2.6B-ROCmFPX-Q2.gguf | 985,196,544 | `e5965401284196b4cf5148c5d3b1ba938295f5836d0b6a54ec09be368b6d0bb8` |
| LFM2.5-2.6B-Q4_K_M.gguf | 1,674,455,040 | `02a8b7e17487d326e46d68ce0ba24211e1b80a14c4cd0597fa73c1cd697f52ed` |

The exact local toolchain and server binary hashes are recorded in
`work/HARDWARE_MANIFEST.json`.

