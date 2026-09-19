#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/atrex_vulkan_evaluator.py"
SPEC = importlib.util.spec_from_file_location("atrex_vulkan_evaluator", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EvaluatorUnitTests(unittest.TestCase):
    def test_perf_parser_requires_exact_shape(self) -> None:
        output = (
            "MUL_MAT(type_a=q4_0_rocmfp4_fast,type_b=f32,m=10752,n=128,k=2048,"
            "bs=[1,1]): 2000 runs - 426.75 us/run - 13.2 TFLOPS"
        )
        self.assertEqual(float(MODULE.PERF_RE.search(output).group(1)), 426.75)
        self.assertIsNone(MODULE.PERF_RE.search(output.replace("n=128", "n=129")))

    def test_problem_definition_changes_filter_and_parser_together(self) -> None:
        problem = MODULE.validate_problem(
            {
                "schema_version": 1,
                "family": "down",
                "type_a": "q4_0_rocmfp4_fast",
                "type_b": "f32",
                "m": 2048,
                "n": 128,
                "k": 10752,
            }
        )
        self.assertEqual(
            MODULE.problem_filter(problem),
            "type_a=q4_0_rocmfp4_fast,type_b=f32,m=2048,n=128,k=10752",
        )
        output = "MUL_MAT(" + MODULE.problem_filter(problem) + "): 10 runs - 999.5 us/run"
        self.assertEqual(MODULE.perf_regex(problem).search(output).group(1), "999.5")

    def test_taboo_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "taboo.json"
            path.write_text(
                json.dumps(
                    {
                        "mutations": [
                            {"id": "dual", "patterns": ["dual accumulator"]}
                        ]
                    }
                )
            )
            manifest = {"id": "c7", "mutation": "try dual accumulator scheduling"}
            with self.assertRaises(MODULE.EvaluationError):
                MODULE.check_taboo(manifest, path)

    def test_patch_allowlist_rejects_evaluator_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.patch"
            path.write_text(
                "diff --git a/work/scripts/atrex_vulkan_evaluator.py "
                "b/work/scripts/atrex_vulkan_evaluator.py\n"
                "--- a/work/scripts/atrex_vulkan_evaluator.py\n"
                "+++ b/work/scripts/atrex_vulkan_evaluator.py\n"
            )
            with self.assertRaises(MODULE.EvaluationError):
                MODULE.patch_paths(path)

    def test_patch_allowlist_accepts_plugin_shader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "good.patch"
            path.write_text(
                "diff --git a/extensions/rocmfpx-vulkan/backend/vulkan-shaders/mul_mmq.comp "
                "b/extensions/rocmfpx-vulkan/backend/vulkan-shaders/mul_mmq.comp\n"
                "--- a/extensions/rocmfpx-vulkan/backend/vulkan-shaders/mul_mmq.comp\n"
                "+++ b/extensions/rocmfpx-vulkan/backend/vulkan-shaders/mul_mmq.comp\n"
            )
            self.assertEqual(
                MODULE.patch_paths(path),
                ["extensions/rocmfpx-vulkan/backend/vulkan-shaders/mul_mmq.comp"],
            )

    def test_bootstrap_is_reproducible(self) -> None:
        values = [-2.0, -1.0, 0.0, 1.0]
        self.assertEqual(MODULE.bootstrap_ci(values), MODULE.bootstrap_ci(values))


if __name__ == "__main__":
    unittest.main()
