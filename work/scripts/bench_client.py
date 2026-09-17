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
    cached_prompt_tokens: int
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


def cached_tokens_from_usage(usage: dict) -> int:
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    return int(details.get("cached_tokens") or 0)


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
    try:
        with urlopen(req, timeout=timeout) as resp:
            for line in resp:
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if not data or data == b"[DONE]":
                    continue
                now = time.perf_counter()
                obj = json.loads(data)
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
        return RequestResult(
            ok=output_tokens > 0,
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_tokens_from_usage(usage),
            output_tokens=output_tokens,
            output_token_source=output_source,
            ttft_ms=1000.0 * (first - started) if first else None,
            e2e_ms=1000.0 * (ended - started),
            inter_chunk_ms=[1000.0 * (b - a) for a, b in zip(events, events[1:])],
            stream_chunks_with_content=len(events),
            finish_reason=finish_reason,
            error=None if output_tokens > 0 else "response contained no countable output tokens",
            text_chars=len(text),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            text=text if record_text else None,
            request_started_s=started,
            response_ended_s=ended,
            timings=timings,
        )
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        ended = time.perf_counter()
        return RequestResult(
            False, 0, 0, 0, "missing", None, None, [], 0, None, repr(exc), 0,
            hashlib.sha256(b"").hexdigest(), None, started, ended, {},
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
    total_cached = sum(r.cached_prompt_tokens for r in ok)
    return {
        "requests": len(results),
        "successful": len(ok),
        "failed": len(results) - len(ok),
        "prompt_tokens_total": total_in,
        "cached_prompt_tokens_total": total_cached,
        "computed_prompt_tokens_total": total_in - total_cached,
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
    ap.add_argument("--slot-policy", choices=("auto", "compact"), default="auto")
    ap.add_argument("--cache-prompt", choices=("on", "off"), default="off")
    ap.add_argument("--ignore-eos", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--arrival-stagger-ms", type=float, default=0.0)
    ap.add_argument("--record-text", action="store_true")
    ap.add_argument("--label", default="run")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.concurrency < 1 or args.repetitions < 1 or args.warmup < 0:
        ap.error("concurrency/repetitions must be positive and warmup non-negative")
    if args.arrival_stagger_ms < 0:
        ap.error("arrival stagger must be non-negative")

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
        "cache_prompt": args.cache_prompt,
        "ignore_eos": args.ignore_eos,
        "arrival_stagger_ms": args.arrival_stagger_ms,
    }
    print(json.dumps(config, ensure_ascii=False), flush=True)

    def make_payload(i: int, slot_id: int | None = None) -> dict:
        prompt_seed = args.seed if args.prompt_mode == "identical" else args.seed + i * 7919
        ids = load_prompt_ids(tokenizer, args.prompt_tokens, prompt_seed)
        payload = {
            "model": request_model,
            "prompt": ids,
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
            "ignore_eos": args.ignore_eos,
            "logit_bias": [[token_id, False] for token_id in special_token_ids],
            "cache_prompt": args.cache_prompt == "on",
            "seed": args.sampler_seed,
        }
        if slot_id is not None:
            payload["id_slot"] = slot_id
        return payload

    for i in range(args.warmup):
        warm_slot = 0 if args.slot_policy == "compact" else None
        warm = post_stream(endpoint, make_payload(i, warm_slot), args.timeout, count_text_tokens, False)
        if not warm.ok:
            print(f"warmup failed: {warm.error}", file=sys.stderr, flush=True)

    all_results: list[RequestResult] = []
    rep_summaries: list[dict] = []
    raw_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for rep in range(args.repetitions):
            barrier = Barrier(args.concurrency + 1)
            payloads = [
                make_payload(
                    args.warmup + rep * args.concurrency + i,
                    i if args.slot_policy == "compact" else None,
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
        "workload_kind": "controlled_fixed_output" if args.ignore_eos else "service_eos_enabled",
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
            "output_special_token_ids_biased_out": special_token_ids,
        },
        "sampling": {"temperature": args.temperature, "top_p": args.top_p, "seed": args.sampler_seed},
        "prompt_mode": args.prompt_mode,
        "slot_policy": args.slot_policy,
        "cache_prompt": args.cache_prompt,
        "ignore_eos": args.ignore_eos,
        "arrival_stagger_ms": args.arrival_stagger_ms,
        "validity": {
            "all_requests_succeeded": aggregate["failed"] == 0,
            "no_cache_reuse_observed": aggregate["cached_prompt_tokens_total"] == 0,
            "all_effective_prompts_match_target": all(r.prompt_tokens == args.prompt_tokens for r in all_results if r.ok),
            "all_outputs_match_budget": all(r.output_tokens == args.max_tokens for r in all_results if r.ok) if args.ignore_eos else None,
            "usage_token_counts_present": all(r.output_token_source == "usage.completion_tokens" for r in all_results if r.ok),
        },
        "repetitions_detail": rep_summaries,
        "aggregate": aggregate,
        "raw": raw_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.output}")
    return 0 if record["validity"]["all_requests_succeeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
