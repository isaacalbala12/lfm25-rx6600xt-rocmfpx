#!/usr/bin/env python3
"""Summarize paired 8K-prefill service runs by independent server batch."""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> int:
    root = Path(sys.argv[1])
    metrics = {
        "aggregate_output_tok_s": [],
        "aggregate_input_tok_s": [],
        "ttft_p95_ms": [],
        "e2e_p95_ms": [],
    }
    output_identity = []
    pairs = sorted({p.name.split("-")[1] for p in root.glob("pair-*-control")})
    for pair in pairs:
        arms = {}
        for arm in ("control", "candidate"):
            data = json.loads((root / f"pair-{pair}-{arm}" / "c4.json").read_text())
            if data["status"] != "VALID":
                raise RuntimeError(f"invalid pair {pair} {arm}: {data['status']}")
            arms[arm] = data
        for name in metrics:
            if name == "ttft_p95_ms":
                control = arms["control"]["aggregate"]["ttft_ms"]["p95"]
                candidate = arms["candidate"]["aggregate"]["ttft_ms"]["p95"]
            elif name == "e2e_p95_ms":
                control = arms["control"]["aggregate"]["e2e_ms"]["p95"]
                candidate = arms["candidate"]["aggregate"]["e2e_ms"]["p95"]
            else:
                control = arms["control"]["aggregate"][name]
                candidate = arms["candidate"]["aggregate"][name]
            metrics[name].append((candidate / control - 1) * 100)
        output_identity.append([
            item["text_sha256"] for item in arms["control"]["raw"]
        ] == [item["text_sha256"] for item in arms["candidate"]["raw"]])

    rng = random.Random(0)
    summary = {}
    for name, deltas in metrics.items():
        boot = [statistics.median(rng.choices(deltas, k=len(deltas))) for _ in range(10_000)]
        summary[name] = {
            "paired_delta_percent_median": statistics.median(deltas),
            "bootstrap_95ci_percent": [percentile(boot, 0.025), percentile(boot, 0.975)],
            "pair_deltas_percent": deltas,
        }
    print(json.dumps({
        "schema_version": 1,
        "valid_pairs": len(pairs),
        "exact_output_pairs": sum(output_identity),
        "metrics": summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
