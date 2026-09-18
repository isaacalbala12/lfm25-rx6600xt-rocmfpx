#!/usr/bin/env python3
"""Summarize paired control/chunked-prefill interference runs."""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path


def median_ci(values: list[float]) -> list[float]:
    rng = random.Random(20260918)
    samples = sorted(
        statistics.median(rng.choices(values, k=len(values))) for _ in range(20000)
    )
    return [samples[499], samples[19499]]


def main() -> int:
    root = Path(sys.argv[1])
    runs: dict[int, dict[str, dict]] = {}
    invalid: list[str] = []
    for path in sorted(root.glob("pair-*-*/n3.json")):
        parts = path.parent.name.split("-")
        pair = int(parts[1])
        arm = "-".join(parts[2:])
        data = json.loads(path.read_text())
        if data.get("validity", {}).get("status") != "VALID":
            invalid.append(str(path.parent))
            continue
        runs.setdefault(pair, {})[arm] = data

    pairs = []
    for pair, arms in sorted(runs.items()):
        if set(arms) != {"control", "chunk128"}:
            invalid.append(f"pair-{pair:02d}: incomplete")
            continue
        control = arms["control"]
        candidate = arms["chunk128"]
        row = {"pair": pair}
        for key, getter in {
            "retention": lambda d: d["decode_throughput_retention"],
            "itl_p95_ms": lambda d: d["during_prefill"]["itl_ms"]["p95"],
            "prefill_ttft_ms": lambda d: d["prefill_ttft_ms"],
        }.items():
            c0 = getter(control)
            c1 = getter(candidate)
            row[f"control_{key}"] = c0
            row[f"chunk128_{key}"] = c1
            row[f"delta_{key}_percent"] = (c1 / c0 - 1.0) * 100.0
        pairs.append(row)

    metrics = {}
    for key in ("retention", "itl_p95_ms", "prefill_ttft_ms"):
        deltas = [row[f"delta_{key}_percent"] for row in pairs]
        metrics[key] = {
            "control_median": statistics.median(row[f"control_{key}"] for row in pairs),
            "chunk128_median": statistics.median(row[f"chunk128_{key}"] for row in pairs),
            "paired_delta_percent_median": statistics.median(deltas),
            "paired_delta_percent_bootstrap_95ci": median_ci(deltas),
        }

    result = {
        "schema_version": 1,
        "valid_pairs": len(pairs),
        "invalid": invalid,
        "metrics": metrics,
        "pairs": pairs,
    }
    print(json.dumps(result, indent=2))
    return 0 if pairs and not invalid else 2


if __name__ == "__main__":
    raise SystemExit(main())
