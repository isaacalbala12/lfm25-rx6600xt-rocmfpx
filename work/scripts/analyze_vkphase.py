#!/usr/bin/env python3
"""Aggregate opt-in ROCmFPX Vulkan internal-dispatch timestamps by graph."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


PHASE_RE = re.compile(
    r"^VKPHASE pipeline=(\S+)(?: m=(\d+) k=(\d+) n=(\d+))? "
    r"elements=(\d+),(\d+),(\d+) gpu_ns=(\d+)$"
)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = position - lo
    return ordered[lo] * (1 - fraction) + ordered[hi] * fraction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--tail-graphs", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    graphs: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] | None = None
    for line in args.log.read_text(errors="replace").splitlines():
        if line == "Vulkan Timings:":
            current = []
            graphs.append(current)
            continue
        match = PHASE_RE.match(line)
        if match and current is not None:
            current.append(
                {
                    "pipeline": match.group(1),
                    "shape": (
                        [int(match.group(2)), int(match.group(3)), int(match.group(4))]
                        if match.group(2)
                        else None
                    ),
                    "elements": [int(match.group(5)), int(match.group(6)), int(match.group(7))],
                    "gpu_ns": int(match.group(8)),
                }
            )

    selected = graphs[-args.tail_graphs :]
    pipeline_values: dict[str, list[int]] = defaultdict(list)
    element_counts: dict[str, Counter[str]] = defaultdict(Counter)
    shape_values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    per_graph: list[dict[str, object]] = []
    for relative_index, graph in enumerate(selected):
        graph_sums: dict[str, int] = defaultdict(int)
        graph_calls: Counter[str] = Counter()
        for event in graph:
            pipeline = str(event["pipeline"])
            gpu_ns = int(event["gpu_ns"])
            elements = "x".join(str(v) for v in event["elements"])
            shape = event["shape"]
            shape_key = (
                f"m={shape[0]},k={shape[1]},n={shape[2]}" if shape is not None else "unlabelled"
            )
            pipeline_values[pipeline].append(gpu_ns)
            shape_values[pipeline][shape_key].append(gpu_ns)
            element_counts[pipeline][elements] += 1
            graph_sums[pipeline] += gpu_ns
            graph_calls[pipeline] += 1
        per_graph.append(
            {
                "absolute_graph_index": len(graphs) - len(selected) + relative_index + 1,
                "calls": dict(graph_calls),
                "gpu_ns": dict(graph_sums),
            }
        )

    pipelines: dict[str, object] = {}
    for pipeline, values in sorted(pipeline_values.items()):
        graph_totals = [int(graph["gpu_ns"].get(pipeline, 0)) for graph in per_graph]
        pipelines[pipeline] = {
            "calls": len(values),
            "total_gpu_ns": sum(values),
            "dispatch_gpu_ns_p50": percentile([float(v) for v in values], 0.5),
            "dispatch_gpu_ns_p95": percentile([float(v) for v in values], 0.95),
            "per_graph_gpu_ns_p50": statistics.median(graph_totals),
            "elements": dict(sorted(element_counts[pipeline].items())),
            "shapes": {
                shape: {"calls": len(samples), "total_gpu_ns": sum(samples)}
                for shape, samples in sorted(shape_values[pipeline].items())
            },
        }

    quant_ns = sum(pipeline_values.get("quantize_q8_1_x4", []))
    mmv_ns = sum(pipeline_values.get("mul_mat_vec_rocmfp4_fast_q8_1_f32", []))
    measured_ns = quant_ns + mmv_ns
    result = {
        "schema_version": 1,
        "source": str(args.log),
        "total_graphs_in_log": len(graphs),
        "selected_tail_graphs": len(selected),
        "pipelines": pipelines,
        "quantize_plus_mmv_gpu_ns": measured_ns,
        "quantize_share_of_quantize_plus_mmv": quant_ns / measured_ns if measured_ns else None,
        "per_graph": per_graph,
        "warning": "profiling-only fenced execution; do not use wall throughput as service throughput",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
