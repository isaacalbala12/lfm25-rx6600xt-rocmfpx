#!/usr/bin/env python3
"""Summarize gate/up MMQ selector events from a diagnostic Vulkan log."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


FIELD = re.compile(r"(?:^|\s)([a-z0-9_]+)=([^\s]+)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    histogram: Counter[tuple[int, str]] = Counter()
    total_mul_mat = 0
    for line in args.log.open(errors="replace"):
        if "VKSEL event=mul_mat " not in line:
            continue
        total_mul_mat += 1
        fields = dict(FIELD.findall(line))
        if fields.get("m") != "10752" or fields.get("k") != "2048":
            continue
        histogram[(int(fields["n"]), fields.get("pipeline", "UNKNOWN"))] += 1

    rows = [
        {"n": n, "pipeline": pipeline, "calls": calls}
        for (n, pipeline), calls in sorted(histogram.items())
    ]
    result = {
        "schema_version": 1,
        "source": str(args.log),
        "all_mul_mat_events": total_mul_mat,
        "gateup_events": sum(histogram.values()),
        "histogram": rows,
    }
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload, end="")
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
