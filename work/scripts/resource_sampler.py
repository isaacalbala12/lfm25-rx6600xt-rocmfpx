#!/usr/bin/env python3
"""Sample ROCm SMI and process CPU/memory without changing system state."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


def read_smi(cmd: str) -> dict[str, str]:
    try:
        out = subprocess.run(
            [cmd, "--showmeminfo", "vram", "--showuse", "--showtemp", "--showclocks"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
            check=False,
        ).stdout
    except Exception as exc:
        return {"smi_error": repr(exc)}
    patterns = {
        "vram_used_bytes": r"VRAM Total Used Memory \(B\):\s*(\d+)",
        "vram_total_bytes": r"VRAM Total Memory \(B\):\s*(\d+)",
        "gpu_busy_percent": r"GPU use \(%\):\s*(\d+)",
        "temp_edge_c": r"Temperature \(Sensor edge\) \(C\):\s*([0-9.]+)",
        "sclk": r"sclk clock level:\s*[^ ]*\s*\(([^)]+)\)",
        "mclk": r"mclk clock level:\s*[^ ]*\s*\(([^)]+)\)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, out)
        if match:
            result[key] = match.group(1)
    if not result and out.strip():
        result["smi_error"] = out.strip().replace("\n", " | ")[:500]
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--duration", type=float, default=0.0)
    ap.add_argument("--interval", type=float, default=0.5)
    vllm_root = Path(os.environ.get("VLLM_ROOT", "/home/isaac/vllm-challenge"))
    bundled_smi = vllm_root / "bin" / "rocm-smi"
    default_smi = os.environ.get("ROCM_SMI") or shutil.which("rocm-smi")
    if not default_smi and bundled_smi.is_file():
        default_smi = str(bundled_smi)
    ap.add_argument("--smi", default=default_smi)
    ap.add_argument("--pid", type=int, default=0, help="process to sample for CPU/RSS")
    args = ap.parse_args()
    if not args.smi:
        ap.error("rocm-smi was not found; pass --smi or set ROCM_SMI")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    fields = [
        "time_unix", "elapsed_s", "pid", "sampler_pid", "cpu_percent", "rss_bytes",
        "gpu_busy_percent", "vram_used_bytes", "vram_total_bytes", "temp_edge_c", "sclk",
        "mclk", "smi_error",
    ]
    try:
        import psutil

        process = psutil.Process(args.pid or os.getpid())
        process.cpu_percent(interval=None)
    except Exception:
        process = None
    with args.output.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        while True:
            row = {
                "time_unix": time.time(),
                "elapsed_s": time.monotonic() - started,
                "pid": args.pid or os.getpid(),
                "sampler_pid": os.getpid(),
            }
            row.update(read_smi(args.smi))
            try:
                if process is not None:
                    row["cpu_percent"] = process.cpu_percent(interval=None)
                    row["rss_bytes"] = process.memory_info().rss
            except Exception:
                pass
            writer.writerow(row)
            output.flush()
            if args.duration and time.monotonic() - started >= args.duration:
                break
            time.sleep(max(0.05, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
