#!/usr/bin/env python3
"""Reproducible OpenAI-compatible streaming benchmark client.

The primary service metric is output tokens actually reported/delivered divided
by the interval from the first request start to the last response completion.
The script records cache reuse, effective token counts, EOS policy, per-request
latency, and arrival timing so the metric cannot be confused with decode-only
throughput.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Barrier, Lock
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class RequestResult:
    ok: bool
    prompt_tokens: int
    cached_prompt_tokens: int | None
    output_tokens: int
    output_token_source: str
    ttft_ms: float | None
    e2e_ms: float | None
    inter_chunk_ms: list[float]
    stream_chunks_with_content: int
    finish_reason: str | None
    error: str | None
    text_chars: int
    text_sha256: str
    text: str | None
    request_started_s: float
    response_ended_s: float
    timings: dict
    stream_done_received: bool
    protocol_error: str | None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def distribution(values: list[float]) -> dict:
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "mean": statistics.mean(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "samples": len(values),
    }


def load_tokenizer(model: str):
    try:
        from transformers import AutoTokenizer
    except Exception as exc:  # pragma: no cover - environment diagnostic
        raise RuntimeError("transformers is required for exact token accounting") from exc
    return AutoTokenizer.from_pretrained(model, local_files_only=True, use_fast=True)


PROMPT_CORPUS = (
    "A careful engineer measures latency throughput memory use and correctness before "
    "changing a production system. The benchmark uses ordinary language, stable inputs, "
    "repeatable seeds, and independent requests. Each observation records the prompt, "
    "response timing, token count, configuration, and device state. Reliable conclusions "
    "need comparable workloads and enough repetitions to separate a real improvement from "
    "noise. Small servers should optimize for one, two, three, and four active users while "
    "preserving predictable response time and output quality. This neutral paragraph avoids "
    "control markers and unusual vocabulary so it can serve as a safe synthetic workload."
)


def parse_slot_ids(value: str | None, concurrency: int) -> list[int] | None:
    if value is None:
        return None
    try:
        slot_ids = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("slot IDs must be comma-separated integers") from exc
    if len(slot_ids) != concurrency:
        raise ValueError(f"expected {concurrency} slot IDs, got {len(slot_ids)}")
    if any(slot_id < 0 for slot_id in slot_ids):
        raise ValueError("slot IDs must be non-negative")
    if len(set(slot_ids)) != len(slot_ids):
        raise ValueError("slot IDs must be unique")
    return slot_ids


def load_prompt_ids(tokenizer, n: int, seed: int) -> list[int]:
    """Return exactly n ordinary-text tokens without synthesizing vocabulary IDs.

    Earlier versions offset token IDs arithmetically. That can create EOS/control tokens and
    makes a fixed-output benchmark invalid even when the HTTP request asks to ignore EOS.
    This generator only rotates and repeats IDs produced by encoding a fixed safe corpus.
    """
    base = tokenizer.encode(PROMPT_CORPUS, add_special_tokens=False)
    if not base:
        raise RuntimeError("tokenizer returned no base prompt tokens")
    special = set(getattr(tokenizer, "all_special_ids", []) or [])
    if any(token in special for token in base):
        raise RuntimeError("safe prompt corpus unexpectedly encoded a special token")
    rng = random.Random(seed)
    offset = rng.randrange(len(base))
    rotated = base[offset:] + base[:offset]
    repeats = (n + len(rotated) - 1) // len(rotated)
    return (rotated * repeats)[:n]


def make_payload(
    *,
    request_model: str,
    prompt_ids: list[int],
    max_tokens: int,
    temperature: float,
    top_p: float,
    sampler_seed: int,
    cache_prompt: bool,
    workload_kind: str,
    special_token_ids: list[int],
    slot_id: int | None = None,
) -> dict:
    """Build one request without conflating fixed-output and service EOS modes."""
    if workload_kind not in {"controlled_fixed_output", "service_eos_enabled"}:
        raise ValueError(f"unknown workload kind: {workload_kind}")
    controlled = workload_kind == "controlled_fixed_output"
    payload = {
        "model": request_model,
        "prompt": prompt_ids,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": True,
        "stream_options": {"include_usage": True},
        "ignore_eos": controlled,
        "cache_prompt": cache_prompt,
        "seed": sampler_seed,
    }
    if controlled:
        payload["logit_bias"] = [[token_id, False] for token_id in special_token_ids]
    if slot_id is not None:
        payload["id_slot"] = slot_id
    return payload


def cached_tokens_from_usage(usage: dict) -> int | None:
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    if "cached_tokens" not in details or details["cached_tokens"] is None:
        return None
    return int(details["cached_tokens"])


def post_stream(
    url: str,
    payload: dict,
    timeout: float,
    count_text_tokens: Callable[[str], int],
    record_text: bool,
) -> RequestResult:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    req = Request(url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    first = None
    events: list[float] = []
    pieces: list[str] = []
    usage: dict = {}
    timings: dict = {}
    finish_reason = None
    done_received = False
    protocol_error = None
    try:
        with urlopen(req, timeout=timeout) as resp:
            for line in resp:
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == b"[DONE]":
                    done_received = True
                    continue
                now = time.perf_counter()
                obj = json.loads(data)
                if obj.get("error") is not None:
                    error_obj = obj["error"]
                    if isinstance(error_obj, dict):
                        protocol_error = str(error_obj.get("message") or error_obj)
                    else:
                        protocol_error = str(error_obj)
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                if obj.get("timings"):
                    timings = obj["timings"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                if choices[0].get("finish_reason") is not None:
                    finish_reason = choices[0]["finish_reason"]
                delta = (choices[0].get("delta") or {}).get("content")
                if delta is None:
                    delta = choices[0].get("text")
                if delta:
                    if first is None:
                        first = now
                    events.append(now)
                    pieces.append(delta)
        ended = time.perf_counter()
        text = "".join(pieces)
        output_tokens = int(usage.get("completion_tokens") or 0)
        output_source = "usage.completion_tokens"
        if output_tokens <= 0:
            output_tokens = int(timings.get("predicted_n") or 0)
            output_source = "timings.predicted_n"
        if output_tokens <= 0 and text:
            output_tokens = count_text_tokens(text)
            output_source = "tokenizer_fallback"
        if output_tokens <= 0:
            output_source = "missing"
        prompt_tokens = int(usage.get("prompt_tokens") or timings.get("prompt_n") or len(payload.get("prompt", [])))
        completion_ok = output_tokens > 0 and protocol_error is None and done_received and finish_reason is not None
        if protocol_error is not None:
            error = f"HTTP 200 stream contained error: {protocol_error}"
        elif not done_received:
            error = "stream ended before [DONE]"
        elif finish_reason is None:
            error = "stream ended without finish_reason"
        elif output_tokens <= 0:
            error = "response contained no countable output tokens"
        else:
            error = None
        return RequestResult(
            ok=completion_ok,
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_tokens_from_usage(usage),
            output_tokens=output_tokens,
            output_token_source=output_source,
            ttft_ms=1000.0 * (first - started) if first else None,
            e2e_ms=1000.0 * (ended - started),
            inter_chunk_ms=[1000.0 * (b - a) for a, b in zip(events, events[1:])],
            stream_chunks_with_content=len(events),
            finish_reason=finish_reason,
            error=error,
            text_chars=len(text),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            text=text if record_text else None,
            request_started_s=started,
            response_ended_s=ended,
            timings=timings,
            stream_done_received=done_received,
            protocol_error=protocol_error,
        )
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        ended = time.perf_counter()
        return RequestResult(
            False, 0, None, 0, "missing", None, None, [], 0, None, repr(exc), 0,
            hashlib.sha256(b"").hexdigest(), None, started, ended, {}, False, repr(exc),
        )


def batch_wall_seconds(results: list[RequestResult]) -> float:
    if not results:
        return 0.0
    return max(r.response_ended_s for r in results) - min(r.request_started_s for r in results)


def summarize(results: list[RequestResult]) -> dict:
    wall_s = batch_wall_seconds(results)
    ok = [r for r in results if r.ok]
    ttft = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    e2e = [r.e2e_ms for r in ok if r.e2e_ms is not None]
    inter_chunk = [v for r in ok for v in r.inter_chunk_ms]
    per_request = [r.output_tokens / (r.e2e_ms / 1000.0) for r in ok if r.e2e_ms and r.e2e_ms > 0]
    total_out = sum(r.output_tokens for r in ok)
    total_in = sum(r.prompt_tokens for r in ok)
    cache_observations = [r.cached_prompt_tokens for r in ok if r.cached_prompt_tokens is not None]
    cache_telemetry_complete = len(cache_observations) == len(ok)
    total_cached = sum(cache_observations) if cache_telemetry_complete else None
    return {
        "requests": len(results),
        "successful": len(ok),
        "failed": len(results) - len(ok),
        "prompt_tokens_total": total_in,
        "cached_prompt_tokens_total": total_cached,
        "cached_prompt_tokens_observations": len(cache_observations),
        "cache_telemetry_complete": cache_telemetry_complete,
        "computed_prompt_tokens_total": total_in - total_cached if total_cached is not None else None,
        "output_tokens_total": total_out,
        "wall_seconds_first_send_to_last_completion": wall_s,
        "aggregate_output_tok_s": total_out / wall_s if wall_s > 0 else None,
        "aggregate_input_tok_s": total_in / wall_s if wall_s > 0 else None,
        "ttft_ms": distribution(ttft),
        "e2e_ms": distribution(e2e),
        "inter_chunk_ms": distribution(inter_chunk),
        "inter_chunk_basis": "non-empty SSE content chunks; not assumed to be one tokenizer token",
        "per_request_output_tok_s": per_request,
        "per_request_output_tok_s_distribution": distribution(per_request),
        "output_token_sources": sorted({r.output_token_source for r in ok}),
        "finish_reasons": sorted({str(r.finish_reason) for r in ok}),
        "errors": [r.error for r in results if not r.ok],
    }


def serializable_request(result: RequestResult, batch_start: float) -> dict:
    data = asdict(result)
    data["request_start_ms_from_batch"] = 1000.0 * (result.request_started_s - batch_start)
    data["response_end_ms_from_batch"] = 1000.0 * (result.response_ended_s - batch_start)
    del data["request_started_s"]
    del data["response_ended_s"]
    return data


def evaluate_validity(
    results: list[RequestResult],
    *,
    expected_prompt_tokens: int,
    max_tokens: int,
    workload_kind: str,
    cache_prompt: str,
) -> dict:
    fixed = workload_kind == "controlled_fixed_output"
    checks = {
        "all_requests_succeeded": bool(results) and all(r.ok for r in results),
        "all_streams_complete": bool(results) and all(r.stream_done_received and r.finish_reason is not None for r in results),
        "all_effective_prompts_match_target": bool(results) and all(r.prompt_tokens == expected_prompt_tokens for r in results),
        "all_outputs_match_budget": (bool(results) and all(r.output_tokens == max_tokens for r in results)) if fixed else None,
        "usage_token_counts_present": bool(results) and all(r.output_token_source == "usage.completion_tokens" for r in results),
        "cache_telemetry_available": bool(results) and all(r.cached_prompt_tokens is not None for r in results),
    }
    if cache_prompt == "off":
        checks["cache_policy_satisfied"] = checks["cache_telemetry_available"] and all(
            r.cached_prompt_tokens == 0 for r in results
        )
    else:
        checks["cache_policy_satisfied"] = checks["cache_telemetry_available"]

    required = [value for value in checks.values() if value is not None]
    valid = all(required)
    return {
        "status": "VALID" if valid else "INVALID",
        **checks,
        "invalid_reasons": [name for name, value in checks.items() if value is False],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True, help="Tokenizer path and default request model name")
    ap.add_argument("--tokenizer", help="Local tokenizer path when --model is a GGUF file")
    ap.add_argument("--request-model", help="Model name sent to the API")
    ap.add_argument("--prompt-tokens", type=int, required=True)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--repetitions", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--sampler-seed", type=int, default=0)
    ap.add_argument("--prompt-mode", choices=("varied", "identical"), default="varied")
    ap.add_argument("--slot-policy", choices=("auto", "compact", "forced"), default="auto")
    ap.add_argument("--slot-ids", help="Comma-separated logical slot IDs; required with --slot-policy forced")
    ap.add_argument("--cache-prompt", choices=("on", "off"), default="off")
    ap.add_argument(
        "--workload-kind",
        choices=("controlled_fixed_output", "service_eos_enabled"),
        default="controlled_fixed_output",
    )
    ap.add_argument("--arrival-stagger-ms", type=float, default=0.0)
    ap.add_argument("--record-text", action="store_true")
    ap.add_argument("--label", default="run")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.concurrency < 1 or args.repetitions < 1 or args.warmup < 0:
        ap.error("concurrency/repetitions must be positive and warmup non-negative")
    if args.arrival_stagger_ms < 0:
        ap.error("arrival stagger must be non-negative")
    try:
        forced_slot_ids = parse_slot_ids(args.slot_ids, args.concurrency)
    except ValueError as exc:
        ap.error(str(exc))
    if args.slot_policy == "forced" and forced_slot_ids is None:
        ap.error("--slot-ids is required with --slot-policy forced")
    if args.slot_policy != "forced" and forced_slot_ids is not None:
        ap.error("--slot-ids requires --slot-policy forced")

    endpoint = args.base_url.rstrip("/") + "/v1/completions"
    tokenizer = load_tokenizer(args.tokenizer or args.model)
    request_model = args.request_model or args.model
    tokenizer_lock = Lock()
    special_token_ids = sorted(set(getattr(tokenizer, "all_special_ids", []) or []))

    def count_text_tokens(text: str) -> int:
        with tokenizer_lock:
            return len(tokenizer.encode(text, add_special_tokens=False))

    config = {
        "label": args.label,
        "prompt_tokens": args.prompt_tokens,
        "max_tokens": args.max_tokens,
        "concurrency": args.concurrency,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "prompt_mode": args.prompt_mode,
        "slot_policy": args.slot_policy,
        "slot_ids": forced_slot_ids,
        "cache_prompt": args.cache_prompt,
        "workload_kind": args.workload_kind,
        "arrival_stagger_ms": args.arrival_stagger_ms,
    }
    print(json.dumps(config, ensure_ascii=False), flush=True)

    def payload_for(i: int, slot_id: int | None = None) -> dict:
        prompt_seed = args.seed if args.prompt_mode == "identical" else args.seed + i * 7919
        ids = load_prompt_ids(tokenizer, args.prompt_tokens, prompt_seed)
        return make_payload(
            request_model=request_model,
            prompt_ids=ids,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            sampler_seed=args.sampler_seed,
            cache_prompt=args.cache_prompt == "on",
            workload_kind=args.workload_kind,
            special_token_ids=special_token_ids,
            slot_id=slot_id,
        )

    for i in range(args.warmup):
        warm_slot = (forced_slot_ids or [0])[0] if args.slot_policy in {"compact", "forced"} else None
        warm = post_stream(endpoint, payload_for(i, warm_slot), args.timeout, count_text_tokens, False)
        if not warm.ok:
            print(f"warmup failed: {warm.error}", file=sys.stderr, flush=True)

    all_results: list[RequestResult] = []
    rep_summaries: list[dict] = []
    raw_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for rep in range(args.repetitions):
            barrier = Barrier(args.concurrency + 1)
            payloads = [
                payload_for(
                    args.warmup + rep * args.concurrency + i,
                    (forced_slot_ids[i] if args.slot_policy == "forced" else i)
                    if args.slot_policy in {"compact", "forced"} else None,
                )
                for i in range(args.concurrency)
            ]

            def one(index_payload: tuple[int, dict]) -> RequestResult:
                index, payload = index_payload
                barrier.wait()
                if args.arrival_stagger_ms:
                    time.sleep(index * args.arrival_stagger_ms / 1000.0)
                return post_stream(endpoint, payload, args.timeout, count_text_tokens, args.record_text)

            futures = [pool.submit(one, item) for item in enumerate(payloads)]
            barrier.wait()
            results = [future.result() for future in futures]
            batch_start = min(r.request_started_s for r in results)
            all_results.extend(results)
            raw_results.extend(serializable_request(r, batch_start) for r in results)
            rep_summary = {"repetition": rep, **summarize(results)}
            rep_summaries.append(rep_summary)
            print(json.dumps(rep_summary, ensure_ascii=False), flush=True)

    aggregate = summarize(all_results)
    record = {
        "schema_version": 2,
        "metric_definition": "sum(successful completion_tokens) / (last response end - first request start)",
        "metric_scope": "HTTP service throughput including prefill, queueing, decode, streaming and transport",
        "workload_kind": args.workload_kind,
        "label": args.label,
        "base_url": args.base_url,
        "model": args.model,
        "request_model": request_model,
        "tokenizer": args.tokenizer or args.model,
        "prompt_tokens_target": args.prompt_tokens,
        "max_tokens": args.max_tokens,
        "concurrency": args.concurrency,
        "repetitions": args.repetitions,
        "warmup": args.warmup,
        "seed": args.seed,
        "prompt_generator": {
            "name": "safe_corpus_cycle_v1",
            "corpus_sha256": hashlib.sha256(PROMPT_CORPUS.encode()).hexdigest(),
            "special_token_ids_excluded": True,
            "output_special_token_ids_biased_out": (
                special_token_ids if args.workload_kind == "controlled_fixed_output" else []
            ),
        },
        "sampling": {"temperature": args.temperature, "top_p": args.top_p, "seed": args.sampler_seed},
        "prompt_mode": args.prompt_mode,
        "slot_policy": args.slot_policy,
        "slot_ids": forced_slot_ids,
        "cache_prompt": args.cache_prompt,
        "ignore_eos": args.workload_kind == "controlled_fixed_output",
        "arrival_stagger_ms": args.arrival_stagger_ms,
        "validity": evaluate_validity(
            all_results,
            expected_prompt_tokens=args.prompt_tokens,
            max_tokens=args.max_tokens,
            workload_kind=args.workload_kind,
            cache_prompt=args.cache_prompt,
        ),
        "repetitions_detail": rep_summaries,
        "aggregate": aggregate,
        "raw": raw_results,
    }
    record["status"] = record["validity"]["status"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.output}")
    return 0 if record["validity"]["status"] == "VALID" else 3


if __name__ == "__main__":
    raise SystemExit(main())
