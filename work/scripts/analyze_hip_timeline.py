#!/usr/bin/env python3
"""Summarise a rocprofv3 HIP trace without PMC counters.

The script deliberately uses only runtime/kernel/memory trace timestamps.  It
does not infer a host-side caller for a HIP API row: rocprofv3's CSV trace does
not contain a call stack.  It instead reports the source-neutral relationship
between synchronisation intervals and GPU work, which is the safe evidence
needed before changing a synchronisation in ggml.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def number(row: dict[str, str], key: str) -> int | float | None:
    value = row.get(key, "")
    if value in (None, "", "nan", "NaN"):
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None


def intervals(rows: Iterable[dict[str, str]]) -> list[tuple[int, int, dict[str, str]]]:
    result = []
    for row in rows:
        start = number(row, "Start_Timestamp")
        end = number(row, "End_Timestamp")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
            result.append((int(start), int(end), row))
    return sorted(result, key=lambda item: (item[0], item[1]))


def union_ns(items: Iterable[tuple[int, int]]) -> int:
    total = 0
    current_start: int | None = None
    current_end: int | None = None
    for start, end in sorted(items):
        if current_start is None:
            current_start, current_end = start, end
        elif start <= current_end:  # type: ignore[operator]
            current_end = max(current_end, end)  # type: ignore[arg-type]
        else:
            total += current_end - current_start  # type: ignore[operator]
            current_start, current_end = start, end
    if current_start is not None and current_end is not None:
        total += current_end - current_start
    return total


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def ms(ns: int | float | None) -> float | None:
    return None if ns is None else ns / 1_000_000.0


def duration_stats(rows: Iterable[dict[str, str]]) -> dict[str, Any]:
    durations = [int(number(row, "End_Timestamp") - number(row, "Start_Timestamp"))
                 for row in rows
                 if isinstance(number(row, "Start_Timestamp"), (int, float))
                 and isinstance(number(row, "End_Timestamp"), (int, float))]
    return {
        "count": len(durations),
        "total_ms": ms(sum(durations)),
        "mean_ms": ms(sum(durations) / len(durations)) if durations else None,
        "p50_ms": ms(quantile([float(value) for value in durations], 0.50)),
        "p95_ms": ms(quantile([float(value) for value in durations], 0.95)),
        "max_ms": ms(max(durations)) if durations else None,
    }


def overlap_ns(start: int, end: int, spans: list[tuple[int, int]]) -> int:
    clipped = []
    for other_start, other_end in spans:
        if other_end <= start:
            continue
        if other_start >= end:
            break
        clipped.append((max(start, other_start), min(end, other_end)))
    return union_ns(clipped)


def nearest_kernel(sync: tuple[int, int, dict[str, str]], kernels: list[tuple[int, int, dict[str, str]]]) -> tuple[str | None, str | None, float | None, float | None]:
    start, end, _ = sync
    previous = None
    following = None
    for kernel in kernels:
        if kernel[1] <= start:
            previous = kernel
        elif kernel[0] >= end:
            following = kernel
            break
    previous_name = previous[2].get("Kernel_Name") if previous else None
    following_name = following[2].get("Kernel_Name") if following else None
    previous_gap = ms(start - previous[1]) if previous else None
    following_gap = ms(following[0] - end) if following else None
    return previous_name, following_name, previous_gap, following_gap


def trace_prefix(trace_dir: Path) -> Path:
    candidates = sorted(trace_dir.glob("*_hip_api_trace.csv"))
    if not candidates:
        raise FileNotFoundError(f"no *_hip_api_trace.csv in {trace_dir}")
    return candidates[0].with_name(candidates[0].name.removesuffix("_hip_api_trace.csv"))


def analyse(trace_dir: Path, label: str) -> dict[str, Any]:
    prefix = trace_prefix(trace_dir)
    api_rows = read_csv(prefix.with_name(prefix.name + "_hip_api_trace.csv"))
    kernel_rows = read_csv(prefix.with_name(prefix.name + "_kernel_trace.csv"))
    copy_path = prefix.with_name(prefix.name + "_memory_copy_trace.csv")
    copy_rows = read_csv(copy_path) if copy_path.exists() else []

    api_intervals = intervals(api_rows)
    kernel_intervals = intervals(kernel_rows)
    copy_intervals = intervals(copy_rows)
    if not api_intervals:
        raise RuntimeError(f"no timestamped HIP API rows in {prefix}")

    wall_start = min(row[0] for row in api_intervals)
    wall_end = max(row[1] for row in api_intervals)
    wall_ns = wall_end - wall_start
    kernel_spans = [(row[0], row[1]) for row in kernel_intervals]
    copy_spans = [(row[0], row[1]) for row in copy_intervals]
    sync_rows = [row for row in api_intervals if row[2].get("Function") == "hipStreamSynchronize"]
    sync_durations = [row[1] - row[0] for row in sync_rows]

    function_rows: dict[str, list[dict[str, str]]] = {}
    for row in api_rows:
        function_rows.setdefault(row.get("Function", ""), []).append(row)
    function_summary = []
    for function, rows in sorted(function_rows.items(), key=lambda item: sum(
        (number(row, "End_Timestamp") or 0) - (number(row, "Start_Timestamp") or 0)
        for row in item[1]
    ), reverse=True):
        stats = duration_stats(rows)
        function_summary.append({"function": function, **stats})

    long_syncs = []
    for sync in sync_rows:
        start, end, row = sync
        duration = end - start
        if duration < 1_000_000:
            continue
        previous_name, following_name, previous_gap, following_gap = nearest_kernel(sync, kernel_intervals)
        long_syncs.append({
            "start_s": (start - wall_start) / 1_000_000_000.0,
            "duration_ms": ms(duration),
            "gpu_kernel_overlap_ms": ms(overlap_ns(start, end, kernel_spans)),
            "copy_overlap_ms": ms(overlap_ns(start, end, copy_spans)),
            "previous_kernel": previous_name,
            "previous_kernel_gap_ms": previous_gap,
            "following_kernel": following_name,
            "following_kernel_gap_ms": following_gap,
            "correlation_id": row.get("Correlation_Id"),
        })

    api_duration_ns = sum(row[1] - row[0] for row in api_intervals)
    kernel_active_ns = union_ns(kernel_spans)
    copy_active_ns = union_ns(copy_spans)
    result = {
        "label": label,
        "trace_dir": str(trace_dir),
        "prefix": str(prefix),
        "wall": {"start": wall_start, "end": wall_end, "seconds": wall_ns / 1_000_000_000.0},
        "rows": {"hip_api": len(api_rows), "kernels": len(kernel_rows), "memory_copies": len(copy_rows)},
        "api_duration": {"sum_ms": ms(api_duration_ns), "occupancy_vs_wall": api_duration_ns / wall_ns},
        "gpu_activity": {
            "kernel_union_ms": ms(kernel_active_ns),
            "kernel_union_vs_wall": kernel_active_ns / wall_ns,
            "copy_union_ms": ms(copy_active_ns),
            "copy_union_vs_wall": copy_active_ns / wall_ns,
        },
        "sync": {
            "count": len(sync_rows),
            "total_ms": ms(sum(sync_durations)),
            "share_of_api_duration": sum(sync_durations) / api_duration_ns if api_duration_ns else None,
            "p50_ms": ms(quantile([float(value) for value in sync_durations], 0.50)),
            "p95_ms": ms(quantile([float(value) for value in sync_durations], 0.95)),
            "max_ms": ms(max(sync_durations)) if sync_durations else None,
            "over_1ms": sum(value >= 1_000_000 for value in sync_durations),
            "over_10ms": sum(value >= 10_000_000 for value in sync_durations),
            "over_100ms": sum(value >= 100_000_000 for value in sync_durations),
            "over_1s": sum(value >= 1_000_000_000 for value in sync_durations),
            "long_waits": long_syncs,
        },
        "api_by_total_duration": function_summary,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", action="append", required=True, type=Path)
    parser.add_argument("--label", action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if len(args.trace_dir) != len(args.label):
        parser.error("provide one --label for every --trace-dir")
    report = [analyse(path, label) for path, label in zip(args.trace_dir, args.label)]
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
