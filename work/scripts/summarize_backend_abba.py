#!/usr/bin/env python3
"""Summarize four-run ABBA/BAAB backend-library comparisons by pair."""

from __future__ import annotations

import json
import random
import re
import statistics
import sys
from pathlib import Path

LINE = re.compile(
    r"MUL_MAT\(type_a=q4_0_rocmfp4_fast,type_b=f32,m=(\d+),n=(\d+),k=(\d+).*?"
    r"-\s+([0-9.]+) us/run"
)


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def main() -> int:
    root = Path(sys.argv[1])
    candidate_mode = sys.argv[2]
    control_mode = sys.argv[3] if len(sys.argv) > 3 else "control"
    observations: dict[str, dict[int, tuple[str, float]]] = {}

    for path in sorted(root.glob("[0-9]*-*.txt")):
        index_text, mode = path.stem.split("-", 1)
        index = int(index_text)
        for match in LINE.finditer(path.read_text(errors="replace")):
            shape = f"m{match[1]}-n{match[2]}-k{match[3]}"
            observations.setdefault(shape, {})[index] = (mode, float(match[4]))

    rng = random.Random(0)
    summary: dict[str, object] = {}
    for shape, indexed in sorted(observations.items()):
        modes: dict[str, list[float]] = {control_mode: [], candidate_mode: []}
        pair_deltas: list[float] = []
        for pair_start in range(0, max(indexed) + 1, 4):
            pair: dict[str, list[float]] = {control_mode: [], candidate_mode: []}
            for index in range(pair_start, pair_start + 4):
                mode_value = indexed.get(index)
                if mode_value and mode_value[0] in pair:
                    pair[mode_value[0]].append(mode_value[1])
                    modes[mode_value[0]].append(mode_value[1])
            if all(len(pair[mode]) == 2 for mode in pair):
                control = statistics.median(pair[control_mode])
                candidate = statistics.median(pair[candidate_mode])
                pair_deltas.append((candidate / control - 1.0) * 100.0)

        if not pair_deltas:
            continue
        boot = []
        for _ in range(10_000):
            resample = [rng.choice(pair_deltas) for _ in pair_deltas]
            boot.append(statistics.median(resample))
        control_median = statistics.median(modes[control_mode])
        candidate_median = statistics.median(modes[candidate_mode])
        summary[shape] = {
            "control_mode": control_mode,
            "candidate_mode": candidate_mode,
            "control_us_median": control_median,
            "candidate_us_median": candidate_median,
            "raw_delta_percent": (candidate_median / control_median - 1.0) * 100.0,
            "paired_delta_percent_median": statistics.median(pair_deltas),
            "paired_bootstrap_95ci_percent": [percentile(boot, 0.025), percentile(boot, 0.975)],
            "paired_deltas_percent": pair_deltas,
            "pairs": len(pair_deltas),
            "samples_per_arm": len(modes[control_mode]),
        }

    print(json.dumps({"schema_version": 1, "shapes": summary}, indent=2))
    return 0 if summary else 2


if __name__ == "__main__":
    raise SystemExit(main())
