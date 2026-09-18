#!/usr/bin/env python3
"""Compare output identities from two interference-profile artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def first_difference(left: list[int], right: list[int]) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right)) if len(left) != len(right) else None


def main() -> int:
    control = json.loads(Path(sys.argv[1]).read_text())
    candidate = json.loads(Path(sys.argv[2]).read_text())
    comparisons = []
    all_equal = True
    for phase in ("prime", "baseline", "interference"):
        left_items = control["raw"][phase]
        right_items = candidate["raw"][phase]
        for slot, (left, right) in enumerate(zip(left_items, right_items)):
            equal = left["retokenized_ids_sha256"] == right["retokenized_ids_sha256"]
            all_equal &= equal
            comparisons.append(
                {
                    "phase": phase,
                    "slot": slot,
                    "equal": equal,
                    "control_sha256": left["retokenized_ids_sha256"],
                    "candidate_sha256": right["retokenized_ids_sha256"],
                    "first_difference": first_difference(
                        left["retokenized_ids"], right["retokenized_ids"]
                    ),
                    "control_retokenized_count": len(left["retokenized_ids"]),
                    "candidate_retokenized_count": len(right["retokenized_ids"]),
                }
            )
    left = control["raw"]["prefill"]
    right = candidate["raw"]["prefill"]
    equal = left["retokenized_ids_sha256"] == right["retokenized_ids_sha256"]
    all_equal &= equal
    comparisons.append(
        {
            "phase": "prefill",
            "slot": control["n_decoders"],
            "equal": equal,
            "control_sha256": left["retokenized_ids_sha256"],
            "candidate_sha256": right["retokenized_ids_sha256"],
            "first_difference": first_difference(left["retokenized_ids"], right["retokenized_ids"]),
            "control_retokenized_count": len(left["retokenized_ids"]),
            "candidate_retokenized_count": len(right["retokenized_ids"]),
        }
    )
    print(json.dumps({"schema_version": 1, "all_equal": all_equal, "comparisons": comparisons}, indent=2))
    return 0 if all_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
