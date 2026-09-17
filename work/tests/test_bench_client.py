#!/usr/bin/env python3
from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bench_client  # noqa: E402


class _SSEHandler(BaseHTTPRequestHandler):
    body = b""

    def do_POST(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        pass


def run_stream(body: bytes) -> bench_client.RequestResult:
    handler = type("SSEHandler", (_SSEHandler,), {"body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = bench_client.make_payload(
            request_model="test",
            prompt_ids=[1, 2, 3],
            max_tokens=2,
            temperature=0.0,
            top_p=1.0,
            sampler_seed=0,
            cache_prompt=False,
            workload_kind="service_eos_enabled",
            special_token_ids=[0, 99],
        )
        return bench_client.post_stream(
            f"http://127.0.0.1:{server.server_port}/v1/completions",
            payload,
            5.0,
            lambda text: len(text),
            False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class PayloadTests(unittest.TestCase):
    def test_fixed_and_service_eos_are_distinct(self):
        common = dict(
            request_model="test",
            prompt_ids=[10, 11],
            max_tokens=4,
            temperature=0.0,
            top_p=1.0,
            sampler_seed=0,
            cache_prompt=False,
            special_token_ids=[0, 2],
        )
        fixed = bench_client.make_payload(**common, workload_kind="controlled_fixed_output")
        service = bench_client.make_payload(**common, workload_kind="service_eos_enabled")
        self.assertTrue(fixed["ignore_eos"])
        self.assertEqual(fixed["logit_bias"], [[0, False], [2, False]])
        self.assertFalse(service["ignore_eos"])
        self.assertNotIn("logit_bias", service)

    def test_missing_cache_telemetry_is_not_zero(self):
        self.assertIsNone(bench_client.cached_tokens_from_usage({}))
        usage = {"prompt_tokens_details": {"cached_tokens": 0}}
        self.assertEqual(bench_client.cached_tokens_from_usage(usage), 0)

    def test_forced_slot_ids_are_exact_and_unique(self):
        self.assertEqual(bench_client.parse_slot_ids("0,2,3", 3), [0, 2, 3])
        with self.assertRaisesRegex(ValueError, "expected 3"):
            bench_client.parse_slot_ids("0,2", 3)
        with self.assertRaisesRegex(ValueError, "unique"):
            bench_client.parse_slot_ids("0,0", 2)


class StreamTests(unittest.TestCase):
    def test_complete_eos_stream_finishes_normally(self):
        result = run_stream(
            b'data: {"choices":[{"text":"ok","finish_reason":null}]}\n\n'
            b'data: {"choices":[{"text":"","finish_reason":"stop"}],'
            b'"usage":{"prompt_tokens":3,"completion_tokens":1,'
            b'"prompt_tokens_details":{"cached_tokens":0}}}\n\n'
            b'data: [DONE]\n\n'
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.finish_reason, "stop")
        self.assertTrue(result.stream_done_received)

    def test_incomplete_stream_is_failure_even_with_tokens(self):
        result = run_stream(
            b'data: {"choices":[{"text":"ok","finish_reason":"length"}],'
            b'"usage":{"prompt_tokens":3,"completion_tokens":1,'
            b'"prompt_tokens_details":{"cached_tokens":0}}}\n\n'
        )
        self.assertFalse(result.ok)
        self.assertIn("before [DONE]", result.error)

    def test_error_inside_http_200_is_failure(self):
        result = run_stream(
            b'data: {"error":{"message":"backend failed"}}\n\n'
            b'data: [DONE]\n\n'
        )
        self.assertFalse(result.ok)
        self.assertIn("HTTP 200", result.error)


class ValidityTests(unittest.TestCase):
    def result(self, **overrides):
        values = dict(
            ok=True,
            prompt_tokens=3,
            cached_prompt_tokens=0,
            output_tokens=2,
            output_token_source="usage.completion_tokens",
            ttft_ms=1.0,
            e2e_ms=2.0,
            inter_chunk_ms=[],
            stream_chunks_with_content=1,
            finish_reason="length",
            error=None,
            text_chars=2,
            text_sha256="0" * 64,
            text=None,
            request_started_s=1.0,
            response_ended_s=2.0,
            timings={},
            stream_done_received=True,
            protocol_error=None,
        )
        values.update(overrides)
        return bench_client.RequestResult(**values)

    def test_fixed_output_invalidates_short_output(self):
        validity = bench_client.evaluate_validity(
            [self.result(output_tokens=1)],
            expected_prompt_tokens=3,
            max_tokens=2,
            workload_kind="controlled_fixed_output",
            cache_prompt="off",
        )
        self.assertEqual(validity["status"], "INVALID")
        self.assertIn("all_outputs_match_budget", validity["invalid_reasons"])

    def test_missing_cache_data_invalidates_cache_policy(self):
        validity = bench_client.evaluate_validity(
            [self.result(cached_prompt_tokens=None)],
            expected_prompt_tokens=3,
            max_tokens=2,
            workload_kind="controlled_fixed_output",
            cache_prompt="off",
        )
        self.assertEqual(validity["status"], "INVALID")
        self.assertFalse(validity["cache_telemetry_available"])
        self.assertFalse(validity["cache_policy_satisfied"])

    def test_resident_context_requires_observed_reuse(self):
        validity = bench_client.evaluate_validity(
            [self.result(prompt_tokens=8192, cached_prompt_tokens=8191)],
            expected_prompt_tokens=8192,
            max_tokens=2,
            workload_kind="controlled_fixed_output",
            cache_prompt="on",
            min_cached_prompt_tokens=8191,
        )
        self.assertEqual(validity["status"], "VALID")
        self.assertTrue(validity["minimum_cached_prompt_tokens_satisfied"])

        invalid = bench_client.evaluate_validity(
            [self.result(prompt_tokens=8192, cached_prompt_tokens=4096)],
            expected_prompt_tokens=8192,
            max_tokens=2,
            workload_kind="controlled_fixed_output",
            cache_prompt="on",
            min_cached_prompt_tokens=8191,
        )
        self.assertEqual(invalid["status"], "INVALID")
        self.assertIn("minimum_cached_prompt_tokens_satisfied", invalid["invalid_reasons"])


if __name__ == "__main__":
    unittest.main()
