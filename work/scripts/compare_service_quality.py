#!/usr/bin/env python3
"""Compare service-EOS runs without hiding non-identical outputs."""

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("control", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    control = json.loads(args.control.read_text())
    candidate = json.loads(args.candidate.read_text())
    by_id = {record["id"]: record for record in candidate["records"]}
    comparisons = []
    for left in control["records"]:
        right = by_id[left["id"]]
        comparisons.append({
            "id": left["id"],
            "exact_visible_text": left["visible_text"] == right["visible_text"],
            "same_finish_reason": left["finish_reason"] == right["finish_reason"],
            "same_completion_tokens": left["usage"].get("completion_tokens") == right["usage"].get("completion_tokens"),
            "control_sha256": left["visible_sha256"],
            "candidate_sha256": right["visible_sha256"],
        })
    result = {
        "control_status": control["status"],
        "candidate_status": candidate["status"],
        "all_exact": all(item["exact_visible_text"] for item in comparisons),
        "all_finish_reasons_equal": all(item["same_finish_reason"] for item in comparisons),
        "comparisons": comparisons,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["control_status"] == result["candidate_status"] == "VALID" and result["all_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
