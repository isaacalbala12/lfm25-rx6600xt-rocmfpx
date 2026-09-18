# Concurrency profile V8

No candidate was promoted to a full-server concurrency run. The product control
remains chunk128 + selective gate/up BK3 on runtime R0. The latest validated
3D+1P result remains resident ITL p95 about 87.9 ms, with BK3 improving ITL by
1.447% and retention by 1.544% versus its contemporary control.

V8 deliberately did not convert a 2.16% isolated down win into a claimed mixed
batch result. At the measured 23.28% down share, the ceiling is ~0.50%, which is
insufficient to move the ~80 ms mixed batch materially or meet the <70 ms
target. No timeline, fairness, TTFT, VRAM or quality numbers changed.

The next concurrency measurement is gated on a gate/up candidate with useful
global leverage or a new profile showing that shares have shifted.
