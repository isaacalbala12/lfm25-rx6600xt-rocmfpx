#!/usr/bin/env python3
"""Measure long-prefill interference against already-resident decoders."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.request import Request, urlopen

import bench_client


def percentile(values: list[float], q: float) -> float | None:
    return bench_client.percentile(values, q)


def timed_request(url: str, payload: dict, timeout: float, first_event: Event | None = None) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    events: list[float] = []
    text_parts: list[str] = []
    usage: dict = {}
    timings: dict = {}
    finish_reason = None
    done = False
    protocol_error = None
    try:
        with urlopen(request, timeout=timeout) as response:
            for line in response:
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == b"[DONE]":
                    done = True
                    continue
                now = time.perf_counter()
                obj = json.loads(data)
                if obj.get("error") is not None:
                    protocol_error = str(obj["error"])
                    continue
                usage = obj.get("usage") or usage
                timings = obj.get("timings") or timings
                choices = obj.get("choices") or []
                if not choices:
                    continue
                finish_reason = choices[0].get("finish_reason") or finish_reason
                text = (choices[0].get("delta") or {}).get("content")
                if text is None:
                    text = choices[0].get("text")
                if text:
                    text_parts.append(text)
                    events.append(now)
                    if first_event is not None:
                        first_event.set()
        ended = time.perf_counter()
        output_tokens = int(usage.get("completion_tokens") or timings.get("predicted_n") or 0)
        prompt_tokens = int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0)
        cached_tokens = bench_client.cached_tokens_from_usage(usage)
        ok = done and finish_reason is not None and output_tokens > 0 and protocol_error is None
        return {
            "ok": ok,
            "prompt_tokens": prompt_tokens,
            "cached_prompt_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "protocol_error": protocol_error,
            "started_s": started,
            "first_content_s": events[0] if events else None,
            "ended_s": ended,
            "events_s": events,
            "timings": timings,
            "output_text": "".join(text_parts),
        }
    except Exception as exc:  # exact error retained in the raw artifact
        ended = time.perf_counter()
        if first_event is not None:
            first_event.set()
        return {
            "ok": False,
            "prompt_tokens": 0,
            "cached_prompt_tokens": None,
            "output_tokens": 0,
            "finish_reason": None,
            "protocol_error": repr(exc),
            "started_s": started,
            "first_content_s": None,
            "ended_s": ended,
            "events_s": [],
            "timings": {},
            "output_text": "".join(text_parts),
        }


def run_parallel(url: str, payloads: list[dict], timeout: float) -> list[dict]:
    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        return list(pool.map(lambda payload: timed_request(url, payload, timeout), payloads))


def common_decode_window(results: list[dict]) -> tuple[float, float]:
    return max(r["first_content_s"] for r in results), min(r["events_s"][-1] for r in results)


def window_metrics(results: list[dict], start: float, end: float) -> dict:
    duration = max(0.0, end - start)
    rates: list[float] = []
    intervals: list[float] = []
    counts: list[int] = []
    for result in results:
        events = [event for event in result["events_s"] if start <= event <= end]
        counts.append(len(events))
        rates.append(len(events) / duration if duration > 0 else 0.0)
        intervals.extend(1000.0 * (b - a) for a, b in zip(events, events[1:]))
    mean_rate = statistics.mean(rates) if rates else 0.0
    cv = statistics.pstdev(rates) / mean_rate if rates and mean_rate > 0 else None
    return {
        "window_s": duration,
        "delivery_events_per_user": counts,
        "event_tok_s_per_user": rates,
        "aggregate_event_tok_s": sum(rates),
        "per_user_p5_tok_s": percentile(rates, 0.05),
        "per_user_p50_tok_s": percentile(rates, 0.50),
        "per_user_min_tok_s": min(rates) if rates else None,
        "per_user_max_tok_s": max(rates) if rates else None,
        "coefficient_of_variation": cv,
        "itl_ms": {
            "p50": percentile(intervals, 0.50),
            "p95": percentile(intervals, 0.95),
            "p99": percentile(intervals, 0.99),
            "samples": len(intervals),
        },
    }


def serializable(result: dict, origin: float) -> dict:
    copy = dict(result)
    events = copy.pop("events_s")
    copy["started_ms"] = 1000.0 * (copy.pop("started_s") - origin)
    first = copy.pop("first_content_s")
    copy["first_content_ms"] = 1000.0 * (first - origin) if first is not None else None
    copy["ended_ms"] = 1000.0 * (copy.pop("ended_s") - origin)
    copy["event_ms"] = [1000.0 * (event - origin) for event in events]
    return copy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--request-model", required=True)
    parser.add_argument("--n-decoders", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--context-tokens", type=int, default=8192)
    parser.add_argument("--decode-tokens", type=int, default=768)
    parser.add_argument("--prefill-output-tokens", type=int, default=1)
    parser.add_argument("--min-cached-prompt-tokens", type=int, default=8188)
    parser.add_argument("--seed", type=int, default=264000)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tokenizer = bench_client.load_tokenizer(args.tokenizer)
    special_ids = sorted(set(getattr(tokenizer, "all_special_ids", []) or []))
    url = args.base_url.rstrip("/") + "/v1/completions"

    def payload(slot: int, *, max_tokens: int, cache: bool, seed_offset: int = 0) -> dict:
        prompt = bench_client.load_prompt_ids(tokenizer, args.context_tokens, args.seed + seed_offset + slot * 7919)
        return bench_client.make_payload(
            request_model=args.request_model,
            prompt_ids=prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            top_p=1.0,
            sampler_seed=0,
            cache_prompt=cache,
            workload_kind="controlled_fixed_output",
            special_token_ids=special_ids,
            slot_id=slot,
        )

    decoder_payloads = [payload(slot, max_tokens=args.decode_tokens, cache=True) for slot in range(args.n_decoders)]
    prime_payloads = [payload(slot, max_tokens=1, cache=True) for slot in range(args.n_decoders)]
    prime = run_parallel(url, prime_payloads, args.timeout)

    baseline = run_parallel(url, decoder_payloads, args.timeout)
    baseline_start, baseline_end = common_decode_window(baseline)
    baseline_metrics = window_metrics(baseline, baseline_start, baseline_end)

    first_events = [Event() for _ in decoder_payloads]
    with ThreadPoolExecutor(max_workers=args.n_decoders) as pool:
        futures = [
            pool.submit(timed_request, url, decoder_payloads[index], args.timeout, first_events[index])
            for index in range(args.n_decoders)
        ]
        for event in first_events:
            if not event.wait(timeout=120.0):
                raise RuntimeError("decoder did not produce its first token before interference")
        prefill_payload = payload(
            args.n_decoders,
            max_tokens=args.prefill_output_tokens,
            cache=False,
            seed_offset=99991,
        )
        prefill = timed_request(url, prefill_payload, args.timeout)
        interference = [future.result() for future in futures]

    interference_start = prefill["started_s"]
    interference_end = prefill["first_content_s"] or prefill["ended_s"]
    interference_metrics = window_metrics(interference, interference_start, interference_end)
    ratio = (
        interference_metrics["aggregate_event_tok_s"] / baseline_metrics["aggregate_event_tok_s"]
        if baseline_metrics["aggregate_event_tok_s"] > 0 else None
    )
    all_results = prime + baseline + interference + [prefill]
    for result in all_results:
        output_text = result["output_text"]
        token_ids = tokenizer.encode(output_text, add_special_tokens=False)
        result["output_text_sha256"] = hashlib.sha256(output_text.encode()).hexdigest()
        result["retokenized_ids"] = token_ids
        result["retokenized_ids_sha256"] = hashlib.sha256(
            json.dumps(token_ids, separators=(",", ":")).encode()
        ).hexdigest()
    origin = min(result["started_s"] for result in all_results)
    cached_ok = all(
        result["cached_prompt_tokens"] is not None
        and result["cached_prompt_tokens"] >= args.min_cached_prompt_tokens
        for result in baseline + interference
    )
    validity = {
        "prime_complete": all(r["ok"] and r["prompt_tokens"] == args.context_tokens for r in prime),
        "baseline_decode_complete": all(r["ok"] and r["output_tokens"] == args.decode_tokens for r in baseline),
        "interference_decode_complete": all(r["ok"] and r["output_tokens"] == args.decode_tokens for r in interference),
        "resident_context_observed": cached_ok,
        "prefill_complete": prefill["ok"] and prefill["prompt_tokens"] == args.context_tokens,
        "prefill_uncached": prefill["cached_prompt_tokens"] == 0,
    }
    record = {
        "schema_version": 1,
        "profile": "C-prefill-decode-interference",
        "n_decoders": args.n_decoders,
        "context_tokens": args.context_tokens,
        "decode_tokens": args.decode_tokens,
        "baseline": baseline_metrics,
        "during_prefill": interference_metrics,
        "decode_throughput_retention": ratio,
        "prefill_ttft_ms": 1000.0 * (interference_end - interference_start),
        "validity": {"status": "VALID" if all(validity.values()) else "INVALID", **validity},
        "raw": {
            "prime": [serializable(r, origin) for r in prime],
            "baseline": [serializable(r, origin) for r in baseline],
            "interference": [serializable(r, origin) for r in interference],
            "prefill": serializable(prefill, origin),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: value for key, value in record.items() if key != "raw"}, indent=2))
    return 0 if record["validity"]["status"] == "VALID" else 3


if __name__ == "__main__":
    raise SystemExit(main())
