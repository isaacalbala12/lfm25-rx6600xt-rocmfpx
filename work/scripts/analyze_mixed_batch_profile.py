#!/usr/bin/env python3
"""Summarize BATCHTRACE and Vulkan timing groups for mixed prefill/decode batches."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


SUBMIT_RE = re.compile(
    r"BATCHTRACE id=(\d+) phase=submit .*?prompt_tokens=(\d+) decode_tokens=(\d+)"
)
COMPLETE_RE = re.compile(r"BATCHTRACE id=(\d+) phase=complete wall_us=(\d+) ret=(-?\d+)")
TIMING_RE = re.compile(r"^(.*?)\s*=\s*([0-9.]+) us(?:\s|$)")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def category(description: str) -> str:
    if "FLASH_ATTN_EXT" in description:
        return "flash_attention"
    if "MUL_MAT q4_0_rocmfp4_fast m=10752" in description:
        return "gate_up"
    if "MUL_MAT q4_0_rocmfp4_fast m=2048" in description and "k=10752" in description:
        return "down"
    if "MUL_MAT q4_0_rocmfp4_fast m=6144" in description and "k=2048" in description:
        return "short_conv"
    if "MUL_MAT q4_0_rocmfp4_fast m=2048" in description and "k=2048" in description:
        return "projection_2048"
    return "misc"


def analyze(lines: list[str], prompt_tokens: int, decode_tokens: int) -> dict:
    active: dict | None = None
    records: list[dict] = []
    in_timings = False

    for line in lines:
        submit = SUBMIT_RE.search(line)
        if submit:
            batch_id, prompt, decode = map(int, submit.groups())
            active = {
                "id": batch_id,
                "prompt_tokens": prompt,
                "decode_tokens": decode,
                "graph_count": 0,
                "profile_us": defaultdict(float),
                "descriptions_us": defaultdict(float),
                "graphs_profile_us": [],
            }
            in_timings = False
            continue

        if active is None:
            continue

        if line == "Vulkan Timings:":
            active["graph_count"] += 1
            active["graphs_profile_us"].append(defaultdict(float))
            in_timings = True
            continue

        complete = COMPLETE_RE.search(line)
        if complete:
            batch_id, wall_us, ret = map(int, complete.groups())
            if batch_id == active["id"]:
                active["wall_us"] = wall_us
                active["ret"] = ret
                active["profile_us"] = dict(active["profile_us"])
                active["descriptions_us"] = dict(active["descriptions_us"])
                if (
                    active["prompt_tokens"] == prompt_tokens
                    and active["decode_tokens"] == decode_tokens
                ):
                    records.append(active)
            active = None
            in_timings = False
            continue

        if in_timings:
            timing = TIMING_RE.match(line)
            if timing:
                description, elapsed_us = timing.groups()
                description = re.sub(r":\s*\d+\s+x\s+[0-9.]+\s+us$", "", description)
                elapsed = float(elapsed_us)
                active["profile_us"][category(description)] += elapsed
                active["descriptions_us"][description] += elapsed
                active["graphs_profile_us"][-1][category(description)] += elapsed

    valid = [record for record in records if record["ret"] == 0]
    wall_ms = [record["wall_us"] / 1000.0 for record in valid]
    totals: dict[str, float] = defaultdict(float)
    description_totals: dict[str, float] = defaultdict(float)
    for record in valid:
        for name, elapsed_us in record["profile_us"].items():
            totals[name] += elapsed_us
        for description, elapsed_us in record["descriptions_us"].items():
            description_totals[description] += elapsed_us
    profile_total = sum(totals.values())
    graph_totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for record in valid:
        for graph_index, graph_profile in enumerate(record["graphs_profile_us"]):
            for name, elapsed_us in graph_profile.items():
                graph_totals[graph_index][name] += elapsed_us

    return {
        "schema_version": 2,
        "filter": {"prompt_tokens": prompt_tokens, "decode_tokens": decode_tokens},
        "valid_batches": len(valid),
        "graph_count_histogram": {
            str(count): sum(record["graph_count"] == count for record in valid)
            for count in sorted({record["graph_count"] for record in valid})
        },
        "instrumented_wall_ms": {
            "median": statistics.median(wall_ms) if wall_ms else None,
            "p95": percentile(wall_ms, 0.95),
        },
        "profiled_gpu_groups": {
            name: {
                "total_us": elapsed_us,
                "share": elapsed_us / profile_total if profile_total else None,
            }
            for name, elapsed_us in sorted(totals.items())
        },
        "profiled_gpu_total_us": profile_total,
        "profiled_gpu_by_graph_index": {
            str(graph_index): {
                "total_us": sum(groups.values()),
                "groups": {
                    name: {
                        "total_us": elapsed_us,
                        "share_within_graph": (
                            elapsed_us / sum(groups.values()) if sum(groups.values()) else None
                        ),
                        "share_of_all_graphs": (
                            elapsed_us / profile_total if profile_total else None
                        ),
                    }
                    for name, elapsed_us in sorted(groups.items())
                },
            }
            for graph_index, groups in sorted(graph_totals.items())
        },
        "top_timing_groups": [
            {
                "description": description,
                "total_us": elapsed_us,
                "share": elapsed_us / profile_total if profile_total else None,
            }
            for description, elapsed_us in sorted(
                description_totals.items(), key=lambda item: item[1], reverse=True
            )[:20]
        ],
        "warning": (
            "GGML_VK_PERF_LOGGER fences every graph. Shares are diagnostic; "
            "instrumented wall time is not a service throughput result."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--prompt-tokens", type=int, default=128)
    parser.add_argument("--decode-tokens", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.log.read_text(errors="replace").splitlines(), args.prompt_tokens, args.decode_tokens)
    payload = json.dumps(result, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload)
    print(payload, end="")
    return 0 if result["valid_batches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
