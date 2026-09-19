#!/usr/bin/env python3
"""Extract conservative static metrics from a RADV_DEBUG=shaders dump."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def shader_blocks(text: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"(?m)^shader: MESA_SHADER_", text)]
    return [text[start:end] for start, end in zip(starts, starts[1:] + [len(text)])]


def header_int(block: str, name: str) -> int | None:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(\d+)", block)
    return int(match.group(1)) if match else None


def inspect_block(block: str) -> dict:
    disasm_marker = "\ndisasm:\n"
    if disasm_marker not in block:
        raise ValueError("shader block has no disassembly")
    disasm = block.split(disasm_marker, 1)[1]
    # Runtime route logs can follow the final instruction in the same capture.
    disasm = disasm.split("\nVKSEL event=", 1)[0]
    instruction_lines = [
        line.strip()
        for line in disasm.splitlines()
        if ";" in line and not line.lstrip().startswith(";")
    ]
    opcodes: Counter[str] = Counter()
    for line in instruction_lines:
        opcode = line.split(None, 1)[0]
        opcodes[opcode] += 1
    vgprs = [int(value) for value in re.findall(r"\bv(\d+)\b", disasm)]
    sgprs = [int(value) for value in re.findall(r"\bs(\d+)\b", disasm)]
    for lo, hi in re.findall(r"\b[vs]\[(\d+):(\d+)\]", disasm):
        # Register ranges are included in the numbered maxima below by class.
        del lo, hi
    v_ranges = [int(hi) for _, hi in re.findall(r"\bv\[(\d+):(\d+)\]", disasm)]
    s_ranges = [int(hi) for _, hi in re.findall(r"\bs\[(\d+):(\d+)\]", disasm)]
    vgprs.extend(v_ranges)
    sgprs.extend(s_ranges)
    return {
        "source_blake3": (re.search(r"(?m)^source_blake3:\s*(.+)$", block) or [None, None])[1],
        "workgroup_size_x": header_int(block, "workgroup_size"),
        "api_subgroup_size": header_int(block, "api_subgroup_size"),
        "shared_size_bytes": header_int(block, "shared_size"),
        "machine_instruction_count": len(instruction_lines),
        "max_numbered_vgpr_index_observed": max(vgprs) if vgprs else None,
        "max_numbered_sgpr_index_observed": max(sgprs) if sgprs else None,
        "opcode_histogram": dict(sorted(opcodes.items())),
        "selected_counts": {
            "barriers": sum(count for op, count in opcodes.items() if "barrier" in op),
            "buffer_loads": sum(count for op, count in opcodes.items() if op.startswith("buffer_load")),
            "buffer_stores": sum(count for op, count in opcodes.items() if op.startswith("buffer_store")),
            "lds_reads": sum(count for op, count in opcodes.items() if op.startswith("ds_read")),
            "lds_writes": sum(count for op, count in opcodes.items() if op.startswith("ds_write")),
            "integer_adds": sum(count for op, count in opcodes.items() if "add" in op and (op.startswith("s_") or op.startswith("v_"))),
            "integer_multiplies": sum(count for op, count in opcodes.items() if "mul" in op and "f" not in op),
            "dot4": sum(count for op, count in opcodes.items() if "dot4" in op),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("--workgroup-size-x", type=int, required=True)
    parser.add_argument("--subgroup-size", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    matches = []
    for block in shader_blocks(args.dump.read_text(errors="replace")):
        if header_int(block, "workgroup_size") != args.workgroup_size_x:
            continue
        if header_int(block, "api_subgroup_size") != args.subgroup_size:
            continue
        matches.append(inspect_block(block))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one matching shader, found {len(matches)}")
    result = {
        "schema_version": 1,
        "source": str(args.dump),
        "shader": matches[0],
        "limitations": [
            "Numbered register maxima are conservative observations from disassembly, not allocator-reported VGPR/SGPR counts.",
            "Spills and occupancy are not inferred because this dump does not report them.",
            "Instruction counts are static machine instructions, not dynamic execution counts.",
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
