#!/usr/bin/env python3
"""Compare instruction structure of two SPIR-V modules without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path


def opcode_names(grammar: Path) -> dict[int, str]:
    data = json.loads(grammar.read_text())
    return {int(item["opcode"]): item["opname"] for item in data["instructions"]}


def inspect(path: Path, names: dict[int, str]) -> dict:
    raw = path.read_bytes()
    if len(raw) < 20 or len(raw) % 4:
        raise ValueError(f"invalid SPIR-V size: {path}")
    words = struct.unpack(f"<{len(raw) // 4}I", raw)
    if words[0] != 0x07230203:
        raise ValueError(f"invalid SPIR-V magic: {path}")
    counts: Counter[str] = Counter()
    offset = 5
    while offset < len(words):
        word_count = words[offset] >> 16
        opcode = words[offset] & 0xFFFF
        if word_count == 0 or offset + word_count > len(words):
            raise ValueError(f"malformed instruction at word {offset}: {path}")
        counts[names.get(opcode, f"Op{opcode}")] += 1
        offset += word_count
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "words": len(words),
        "instructions": sum(counts.values()),
        "opcodes": dict(sorted(counts.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("control", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--grammar", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    names = opcode_names(args.grammar)
    control = inspect(args.control, names)
    candidate = inspect(args.candidate, names)
    all_names = set(control["opcodes"]) | set(candidate["opcodes"])
    differences = [
        {
            "opcode": name,
            "control": control["opcodes"].get(name, 0),
            "candidate": candidate["opcodes"].get(name, 0),
            "delta": candidate["opcodes"].get(name, 0) - control["opcodes"].get(name, 0),
        }
        for name in all_names
        if control["opcodes"].get(name, 0) != candidate["opcodes"].get(name, 0)
    ]
    differences.sort(key=lambda row: (-abs(row["delta"]), row["opcode"]))
    result = {
        "schema_version": 1,
        "control": control,
        "candidate": candidate,
        "delta_percent": {
            "bytes": (candidate["bytes"] / control["bytes"] - 1.0) * 100.0,
            "words": (candidate["words"] / control["words"] - 1.0) * 100.0,
            "instructions": (candidate["instructions"] / control["instructions"] - 1.0) * 100.0,
        },
        "opcode_differences": differences,
        "limitations": [
            "SPIR-V structure is not RDNA2 ISA.",
            "VGPR, SGPR, LDS allocation, spills and occupancy are not measured.",
        ],
    }
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
