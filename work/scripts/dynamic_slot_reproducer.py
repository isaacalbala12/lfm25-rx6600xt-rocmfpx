#!/usr/bin/env python3
"""Exercise normal slot allocation with staggered lengths, disconnects, and reuse."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_client import load_prompt_ids, load_tokenizer, make_payload, post_stream  # noqa: E402


def cancel_stream(url: str, payload: dict, after_chunks: int, timeout: float) -> dict:
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    chunks = 0
    started = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if line.startswith(b"data:") and b"[DONE]" not in line:
                chunks += 1
                if chunks >= after_chunks:
                    resp.close()
                    break
    return {"cancelled_after_chunks": chunks, "elapsed_ms": (time.perf_counter() - started) * 1000.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    tok = load_tokenizer(args.tokenizer)
    special = sorted(set(tok.all_special_ids or []))
    endpoint = args.base_url.rstrip("/") + "/v1/completions"
    lengths = [96, 24, 64, 40]
    staggers = [0.0, 0.04, 0.08, 0.12]
    started = Event()

    def run_one(index: int):
        started.wait()
        time.sleep(staggers[index])
        payload = make_payload(
            request_model=args.model,
            prompt_ids=load_prompt_ids(tok, 128, 7300 + index),
            max_tokens=lengths[index],
            temperature=0.0,
            top_p=1.0,
            sampler_seed=index,
            cache_prompt=False,
            workload_kind="controlled_fixed_output",
            special_token_ids=special,
        )
        return post_stream(endpoint, payload, args.timeout, lambda text: len(tok.encode(text, add_special_tokens=False)), False)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run_one, i) for i in range(4)]
        batch_start = time.perf_counter()
        started.set()
        varied = [future.result() for future in futures]

    cancel_payload = make_payload(
        request_model=args.model,
        prompt_ids=load_prompt_ids(tok, 128, 8100),
        max_tokens=128,
        temperature=0.0,
        top_p=1.0,
        sampler_seed=9,
        cache_prompt=False,
        workload_kind="controlled_fixed_output",
        special_token_ids=special,
    )
    cancelled = cancel_stream(endpoint, cancel_payload, 8, args.timeout)
    time.sleep(0.1)

    follow_payload = make_payload(
        request_model=args.model,
        prompt_ids=load_prompt_ids(tok, 128, 8200),
        max_tokens=32,
        temperature=0.0,
        top_p=1.0,
        sampler_seed=10,
        cache_prompt=False,
        workload_kind="controlled_fixed_output",
        special_token_ids=special,
    )
    follow = post_stream(endpoint, follow_payload, args.timeout, lambda text: len(tok.encode(text, add_special_tokens=False)), False)

    result = {
        "schema_version": 1,
        "slot_policy": "normal API allocation; no id_slot",
        "lengths": lengths,
        "stagger_ms": [v * 1000 for v in staggers],
        "varied": [
            {
                "ok": r.ok,
                "output_tokens": r.output_tokens,
                "finish_reason": r.finish_reason,
                "ttft_ms": r.ttft_ms,
                "e2e_ms": r.e2e_ms,
                "error": r.error,
            }
            for r in varied
        ],
        "batch_wall_ms": (max(r.response_ended_s for r in varied) - batch_start) * 1000.0,
        "cancel": cancelled,
        "follow_up": {
            "ok": follow.ok,
            "output_tokens": follow.output_tokens,
            "finish_reason": follow.finish_reason,
            "error": follow.error,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if all(r.ok for r in varied) and follow.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
