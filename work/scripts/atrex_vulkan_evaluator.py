#!/usr/bin/env python3
"""Fail-closed exact-plugin evaluator for the V6 ROCmFPX Vulkan search.

The evaluator deliberately does not import Atrex.  It is the command adapter
that an Atrex episode (or another bounded search driver) invokes.  The plugin's
normal graph planner, selector and test-backend-ops benchmark remain the source
of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "work/sources/ROCmFPX"
DEFAULT_BUILD = ROOT / "work/builds/rocmfpx-vulkan-gfx1032-v3-instrumented"
DEFAULT_TEST = DEFAULT_BUILD / "bin/test-backend-ops"
DEFAULT_BACKEND = DEFAULT_BUILD / "bin/libggml-rocmfpx-vulkan.so"
DEFAULT_CMAKE = Path("/home/isaac/vllm-challenge/toolchain/bin/cmake")
DEFAULT_PRELOAD = ":".join(
    [
        "/home/isaac/vllm-challenge/toolchain/lib/libstdc++.so.6",
        "/home/isaac/vllm-challenge/toolchain/lib/libgcc_s.so.1",
    ]
)
FILTER = "type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=128,k=2048"
PERF_RE = re.compile(
    r"MUL_MAT\(type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=128,k=2048.*?"
    r"-\s+([0-9.]+) us/run"
)
ROUTE_RE = re.compile(
    r"VKSEL event=mul_mat .*?m=10752 n=128 k=2048 .*?pipeline=([^\s]+)"
)
ALLOWED_PREFIXES = (
    "extensions/rocmfpx-vulkan/backend/ggml-vulkan.cpp",
    "extensions/rocmfpx-vulkan/backend/vulkan-shaders/",
    "tests/test-backend-ops.cpp",
)
PROTECTED_ENV_PREFIXES = ("GGML_VK_SELECTION_LOGGER", "ROCMFPX_BACKEND_PATH", "LD_PRELOAD")


class EvaluationError(RuntimeError):
    pass


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 600,
    output_prefix: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if output_prefix is not None:
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_prefix.with_suffix(".stdout").write_text(result.stdout)
        output_prefix.with_suffix(".stderr").write_text(result.stderr)
    return result


def git(source: Path, *args: str) -> str:
    result = run(["git", *args], cwd=source)
    if result.returncode:
        raise EvaluationError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def require_idle_gpu() -> None:
    result = subprocess.run(
        ["pgrep", "-af", "llama-server|vllm|python.*api_server"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    offenders = [line for line in result.stdout.splitlines() if "atrex_vulkan_evaluator" not in line]
    if offenders:
        raise EvaluationError("another inference process is active: " + offenders[0])


def clean_source(source: Path) -> None:
    status = git(source, "status", "--porcelain")
    if status:
        raise EvaluationError("ROCmFPX source is not clean:\n" + status)


def patch_paths(patch: Path) -> list[str]:
    paths: list[str] = []
    for line in patch.read_text(errors="strict").splitlines():
        if not line.startswith("+++ b/"):
            continue
        path = line[6:]
        allowed = any(
            path.startswith(prefix) if prefix.endswith("/") else path == prefix
            for prefix in ALLOWED_PREFIXES
        )
        if not allowed:
            raise EvaluationError(f"candidate patch changes non-allowlisted path: {path}")
        paths.append(path)
    if not paths:
        raise EvaluationError("candidate patch contains no allowlisted changes")
    return sorted(set(paths))


def environment(backend: Path, extra: dict[str, str], *, selection: bool = False) -> dict[str, str]:
    for key in extra:
        if key in PROTECTED_ENV_PREFIXES:
            raise EvaluationError(f"candidate may not override protected environment variable {key}")
    env = dict(os.environ)
    env["LD_PRELOAD"] = DEFAULT_PRELOAD
    env["ROCMFPX_BACKEND_PATH"] = str(backend)
    for key in (
        "GGML_VK_SELECTION_LOGGER",
        "GGML_VK_PERF_LOGGER",
        "GGML_VK_PERF_LOGGER_CONCURRENT",
        "GGML_VK_DMMV_PHASE_LOGGER",
    ):
        env.pop(key, None)
    env.update(extra)
    if selection:
        env["GGML_VK_SELECTION_LOGGER"] = "1"
    return env


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise EvaluationError("candidate manifest must use schema_version 1")
    for key in ("id", "mutation", "control_env", "candidate_env"):
        if key not in value:
            raise EvaluationError(f"candidate manifest is missing {key}")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", str(value["id"])):
        raise EvaluationError("candidate id is invalid")
    if not isinstance(value["control_env"], dict) or not isinstance(value["candidate_env"], dict):
        raise EvaluationError("control_env and candidate_env must be objects")
    return value


def check_taboo(manifest: dict[str, Any], taboo_path: Path) -> None:
    taboo = json.loads(taboo_path.read_text())
    text = " ".join(
        [str(manifest.get("id", "")), str(manifest.get("mutation", "")), str(manifest.get("notes", ""))]
    ).lower()
    hits = []
    for item in taboo.get("mutations", []):
        if any(pattern.lower() in text for pattern in item.get("patterns", [])):
            hits.append(item["id"])
    if hits and not manifest.get("allow_taboo_retest", False):
        raise EvaluationError("candidate matches taboo mutation(s): " + ", ".join(hits))


def build(cmake: Path, build_dir: Path, log: Path) -> None:
    result = run(
        [
            str(cmake),
            "--build",
            str(build_dir),
            "--target",
            "ggml-rocmfpx-vulkan",
            "test-backend-ops",
            "-j",
            "2",
        ],
        cwd=ROOT,
        timeout=1800,
        output_prefix=log,
    )
    if result.returncode:
        raise EvaluationError("candidate build failed")


def correctness(test: Path, backend: Path, extra: dict[str, str], log: Path) -> None:
    result = run(
        [str(test), "test", "-b", "ROCmFPXVulkan0", "-o", "MUL_MAT", "-p", FILTER],
        cwd=ROOT,
        env=environment(backend, extra),
        timeout=300,
        output_prefix=log,
    )
    if result.returncode or "1/1 tests passed" not in result.stdout or "OK" not in result.stdout:
        raise EvaluationError("exact CPU-reference correctness gate failed")


def route_proof(
    test: Path,
    backend: Path,
    extra: dict[str, str],
    expected_pipeline: str,
    log: Path,
) -> str:
    result = run(
        [str(test), "perf", "-b", "ROCmFPXVulkan0", "-o", "MUL_MAT", "-p", FILTER],
        cwd=ROOT,
        env=environment(backend, extra, selection=True),
        timeout=300,
        output_prefix=log,
    )
    routes = ROUTE_RE.findall(result.stderr)
    if result.returncode or not routes:
        raise EvaluationError("selector proof did not observe the exact gate/up route")
    if expected_pipeline and any(route != expected_pipeline for route in routes):
        raise EvaluationError(
            f"unexpected pipeline(s) {sorted(set(routes))}; expected {expected_pipeline}"
        )
    return routes[0]


def perf_once(
    test: Path,
    backend: Path,
    extra: dict[str, str],
    log: Path,
) -> float:
    result = run(
        [str(test), "perf", "-b", "ROCmFPXVulkan0", "-o", "MUL_MAT", "-p", FILTER],
        cwd=ROOT,
        env=environment(backend, extra),
        timeout=300,
        output_prefix=log,
    )
    match = PERF_RE.search(result.stdout)
    if result.returncode or not match:
        raise EvaluationError("logger-free perf run did not produce the exact shape")
    return float(match.group(1))


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def stats(values: list[float]) -> dict[str, Any]:
    return {
        "samples_us": values,
        "median_us": statistics.median(values),
        "p5_us": percentile(values, 0.05),
        "p95_us": percentile(values, 0.95),
        "mean_us": statistics.mean(values),
        "stdev_us": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def bootstrap_ci(values: list[float], seed: int = 260918, draws: int = 10000) -> list[float]:
    if not values:
        raise EvaluationError("cannot bootstrap an empty sample")
    rng = random.Random(seed)
    medians = []
    for _ in range(draws):
        medians.append(statistics.median(rng.choice(values) for _ in values))
    return [percentile(medians, 0.025), percentile(medians, 0.975)]


def provenance(
    source: Path,
    test: Path,
    control_backend: Path,
    candidate_backend: Path,
    manifest: Path,
    cmake: Path,
) -> dict[str, Any]:
    compiler = run(
        ["/home/isaac/vllm-challenge/toolchain/bin/g++", "--version"], cwd=ROOT
    )
    return {
        "source_head": git(source, "rev-parse", "HEAD"),
        "source_status": git(source, "status", "--porcelain"),
        "test_sha256": sha256(test),
        "control_backend_sha256": sha256(control_backend),
        "candidate_backend_sha256": sha256(candidate_backend),
        "manifest_sha256": sha256(manifest),
        "filter": FILTER,
        "compiler": compiler.stdout.splitlines()[0] if compiler.returncode == 0 else "unavailable",
        "cmake_sha256": sha256(cmake),
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source.resolve()
    build_dir = args.build.resolve()
    test = args.test.resolve()
    backend = args.backend.resolve()
    manifest_path = args.manifest.resolve()
    manifest = validate_manifest(json.loads(manifest_path.read_text()))
    check_taboo(manifest, args.taboo.resolve())
    require_idle_gpu()
    clean_source(source)
    for path in (test, backend, args.cmake):
        if not path.exists():
            raise EvaluationError(f"required path does not exist: {path}")

    result_dir = args.output.resolve()
    if result_dir.exists():
        raise EvaluationError(f"output already exists: {result_dir}")
    result_dir.mkdir(parents=True)
    patch_value = manifest.get("patch")
    patch = (ROOT / patch_value).resolve() if patch_value else None
    patch_applied = False
    control_backend = backend
    candidate_backend = backend
    snapshots: list[Path] = []
    result: dict[str, Any] = {
        "schema_version": 1,
        "candidate_id": manifest["id"],
        "parent": manifest.get("parent"),
        "mutation": manifest["mutation"],
        "started_at_unix": time.time(),
        "gate": "INVALID",
        "reason": "evaluation did not complete",
    }
    try:
        if patch:
            if not patch.is_file():
                raise EvaluationError(f"candidate patch does not exist: {patch}")
            result["changed_files"] = patch_paths(patch)
            check = run(["git", "apply", "--check", str(patch)], cwd=source)
            if check.returncode:
                raise EvaluationError("candidate patch does not apply cleanly: " + check.stderr.strip())
            applied = run(["git", "apply", str(patch)], cwd=source)
            if applied.returncode:
                raise EvaluationError("candidate patch application failed: " + applied.stderr.strip())
            patch_applied = True
            control_backend = build_dir / "bin/.atrex-control-libggml-rocmfpx-vulkan.so"
            candidate_backend = build_dir / "bin/.atrex-candidate-libggml-rocmfpx-vulkan.so"
            shutil.copy2(backend, control_backend)
            snapshots.append(control_backend)
            build(args.cmake, build_dir, result_dir / "build")
            shutil.copy2(backend, candidate_backend)
            snapshots.append(candidate_backend)

        result["provenance"] = provenance(
            source,
            test,
            control_backend,
            candidate_backend,
            manifest_path,
            args.cmake,
        )
        if patch and (
            result["provenance"]["control_backend_sha256"]
            == result["provenance"]["candidate_backend_sha256"]
        ):
            raise EvaluationError(
                "patched candidate produced the same backend hash as the control; "
                "the candidate was not rebuilt into the loaded artifact"
            )
        correctness(
            test, control_backend, manifest["control_env"], result_dir / "correctness-control"
        )
        correctness(
            test,
            candidate_backend,
            manifest["candidate_env"],
            result_dir / "correctness-candidate",
        )
        result["control_pipeline"] = route_proof(
            test,
            control_backend,
            manifest["control_env"],
            manifest.get("expected_control_pipeline", ""),
            result_dir / "route-control",
        )
        result["candidate_pipeline"] = route_proof(
            test,
            candidate_backend,
            manifest["candidate_env"],
            manifest.get("expected_candidate_pipeline", ""),
            result_dir / "route-candidate",
        )

        control: list[float] = []
        candidate: list[float] = []
        pair_deltas: list[float] = []
        index = 0
        for pair in range(args.pairs):
            order = ["control", "candidate", "candidate", "control"]
            if pair % 2:
                order = ["candidate", "control", "control", "candidate"]
            pair_values = {"control": [], "candidate": []}
            for arm in order:
                extra = manifest[f"{arm}_env"]
                arm_backend = control_backend if arm == "control" else candidate_backend
                value = perf_once(
                    test, arm_backend, extra, result_dir / f"perf-{index:03d}-{arm}"
                )
                pair_values[arm].append(value)
                (control if arm == "control" else candidate).append(value)
                index += 1
            control_median = statistics.median(pair_values["control"])
            candidate_median = statistics.median(pair_values["candidate"])
            pair_deltas.append((candidate_median / control_median - 1.0) * 100.0)

        median_delta = statistics.median(pair_deltas)
        result.update(
            {
                "control": stats(control),
                "candidate": stats(candidate),
                "paired_delta_percent": pair_deltas,
                "paired_delta_median_percent": median_delta,
                "paired_bootstrap_95ci_percent": bootstrap_ci(pair_deltas),
                "pairs": args.pairs,
                "gate": "PASS",
                "decision": (
                    "ADVANCE_SERVER"
                    if median_delta <= -3.0
                    else "REVIEW_LEVERAGE"
                    if median_delta <= -1.0
                    else "REJECT_MICRO"
                ),
                "reason": "all build, correctness, route and timing gates passed",
            }
        )
    except (EvaluationError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        if patch_applied and patch:
            reversed_patch = run(["git", "apply", "--check", "--reverse", str(patch)], cwd=source)
            if reversed_patch.returncode == 0:
                reversal = run(["git", "apply", "--reverse", str(patch)], cwd=source)
                if reversal.returncode == 0:
                    try:
                        build(args.cmake, build_dir, result_dir / "restore-build")
                    except EvaluationError as exc:
                        result["gate"] = "INVALID"
                        result["reason"] += f"; production rebuild failed: {exc}"
                else:
                    result["gate"] = "INVALID"
                    result["reason"] += "; candidate patch reversal failed"
            else:
                result["gate"] = "INVALID"
                result["reason"] += "; candidate patch is not reversibly applicable"
        try:
            clean_source(source)
            result["restored_clean"] = True
        except EvaluationError as exc:
            result["gate"] = "INVALID"
            result["restored_clean"] = False
            result["reason"] += f"; {exc}"
        for snapshot in snapshots:
            try:
                snapshot.unlink()
            except FileNotFoundError:
                pass
        result["finished_at_unix"] = time.time()
        atomic_json(result_dir / "result.json", result)
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--manifest", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--pairs", type=int, default=5)
    value.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    value.add_argument("--build", type=Path, default=DEFAULT_BUILD)
    value.add_argument("--test", type=Path, default=DEFAULT_TEST)
    value.add_argument("--backend", type=Path, default=DEFAULT_BACKEND)
    value.add_argument("--cmake", type=Path, default=DEFAULT_CMAKE)
    value.add_argument(
        "--taboo", type=Path, default=ROOT / "work/atrex_v6/taboo_mutations.json"
    )
    return value


def main() -> int:
    args = parser().parse_args()
    if not 1 <= args.pairs <= 20:
        print("--pairs must be between 1 and 20", file=sys.stderr)
        return 2
    result = evaluate(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("gate") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
