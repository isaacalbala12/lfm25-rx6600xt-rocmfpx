Interleaved runs of the same binary and command, with GPU memory clock sampled at
0.05 s intervals during each run. Fast mode is steady 1000 MHz; slow mode shows
repeated 541 MHz samples. The two modes differ by 1.56x in decode throughput.

backend  run  S_TG(B=4)  mode
control  1    357.64     fast
control  2    346.21     fast
control  3    225.57     slow
control  4    223.70     slow
control  5    225.20     slow
control  6    224.74     slow
folded   1    401.80     fast
folded   2    398.55     fast
folded   3    393.29     fast
folded   4    393.00     fast
folded   5    239.13     slow
folded   6    401.14     fast

Fast-mode means: control 351.9 (n=2), folded 397.6 (n=5) -> +13.0%
Within-mode spread: 2.2% (folded fast), 6.9% (slow runs).
