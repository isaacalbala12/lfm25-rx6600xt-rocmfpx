#!/usr/bin/env python3
"""Parse paired test-backend-ops output and summarize by exact shape."""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

LINE = re.compile(
    r"MUL_MAT\(type_a=q4_0_rocmfp4_fast,type_b=f32,m=(\d+),n=(\d+),k=(\d+).*?"
    r"-\s+([0-9.]+) us/run"
)


def main() -> int:
    root = Path(sys.argv[1])
    samples: dict[str, dict[str, list[float]]] = {}
    for path in sorted(root.glob("[0-9]*-*.txt")):
        mode = path.stem.split("-", 1)[1]
        for match in LINE.finditer(path.read_text(errors="replace")):
            shape = f"m{match[1]}-n{match[2]}-k{match[3]}"
            samples.setdefault(shape, {}).setdefault(mode, []).append(float(match[4]))

    summary = {}
    for shape, modes in sorted(samples.items()):
        control = modes.get("subgroup", [])
        candidate = modes.get("large", [])
        c0 = statistics.median(control) if control else None
        c1 = statistics.median(candidate) if candidate else None
        summary[shape] = {
            "subgroup_us_median": c0,
            "large_us_median": c1,
            "delta_percent": ((c1 / c0) - 1.0) * 100.0 if c0 and c1 else None,
            "subgroup_samples": control,
            "large_samples": candidate,
        }
    print(json.dumps({"schema_version": 1, "shapes": summary}, indent=2))
    return 0 if summary else 2


if __name__ == "__main__":
    raise SystemExit(main())
