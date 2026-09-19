llama-perplexity, ROCmFPXVulkan0, FP4_FAST backend with the V11 batch fold,
-ngl 99 -fa on -c 512 -b 512 -ub 128 -ctk q8_0 -ctv q8_0.

corpus.txt       72,516 bytes, 24 chunks
corpus-big.txt  400,000 bytes, 96 chunks (markdown from this repository)

format      bpw   PPL(24 chunks)   PPL(96 chunks)
Q8_0        8.50   47.0837 ± 2.61    81.4662 ± 2.23
Q4_K_M      4.94   46.3965 ± 2.54    89.0863 ± 2.44
Q4_0        4.70   51.7072 ± 2.88    90.9396 ± 2.50
FP4_FAST    4.25   50.5228 ± 2.82    94.3863 ± 2.63
