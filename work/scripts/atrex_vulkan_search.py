#!/usr/bin/env python3
"""Bounded, resumable search supervisor for ROCmFPX Vulkan candidate manifests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVALUATOR = ROOT / "work/scripts/atrex_vulkan_evaluator.py"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {
        "schema_version": 1,
        "attempts": [],
        "valid_candidates": 0,
        "total_attempts": 0,
        "consecutive_without_improvement": 0,
        "best_candidate": "gateup-control",
        "best_delta_percent": 0.0,
    }


def run_search(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state(args.state)
    already = {item["id"] for item in state["attempts"]}
    manifests = sorted(args.candidates.glob("*.json"))
    manifests = [path for path in manifests if path.stem != "baseline" and path.stem not in already]

    for manifest in manifests:
        if state["total_attempts"] >= args.max_attempts:
            state["stop_reason"] = "max total attempts reached"
            break
        if state["valid_candidates"] >= args.max_valid:
            state["stop_reason"] = "max valid candidates reached"
            break
        if state["consecutive_without_improvement"] >= args.max_stall:
            state["stop_reason"] = "consecutive non-improvement limit reached"
            break

        candidate = json.loads(manifest.read_text())
        output = args.output / candidate["id"]
        command = [
            sys.executable,
            str(EVALUATOR),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--pairs",
            str(args.pairs),
        ]
        completed = subprocess.run(command, cwd=ROOT, check=False)
        result_path = output / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
        else:
            result = {"gate": "INVALID", "reason": f"evaluator exited {completed.returncode}"}

        record = {
            "id": candidate["id"],
            "parent": candidate.get("parent"),
            "mutation": candidate["mutation"],
            "gate": result.get("gate", "INVALID"),
            "decision": result.get("decision"),
            "delta_percent": result.get("paired_delta_median_percent"),
            "ci_percent": result.get("paired_bootstrap_95ci_percent"),
            "reason": result.get("reason"),
            "result": str(result_path.relative_to(ROOT)) if result_path.exists() else None,
        }
        state["attempts"].append(record)
        state["total_attempts"] += 1
        if result.get("gate") == "PASS":
            state["valid_candidates"] += 1
            delta = float(result["paired_delta_median_percent"])
            if delta < float(state["best_delta_percent"]):
                state["best_delta_percent"] = delta
                state["best_candidate"] = candidate["id"]
                state["consecutive_without_improvement"] = 0
            else:
                state["consecutive_without_improvement"] += 1
        else:
            state["consecutive_without_improvement"] += 1
        atomic_json(args.state, state)
    else:
        state["stop_reason"] = "candidate queue exhausted"
    atomic_json(args.state, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=ROOT / "work/atrex_v6/candidates"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "work/results/v6-atrex-gateup-search"
    )
    parser.add_argument(
        "--state", type=Path, default=ROOT / "work/atrex_v6/search_state.json"
    )
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--max-valid", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--max-stall", type=int, default=10)
    args = parser.parse_args()
    state = run_search(args)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
