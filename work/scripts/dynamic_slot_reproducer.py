#!/usr/bin/env python3
"""Exercise cancellation, dense remapping, and slot reuse while peers stay active."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_client import load_prompt_ids, load_tokenizer, make_payload, post_stream  # noqa: E402


def cancel_stream(url: str, payload: dict, after_chunks: int, timeout: float, cancelled: Event) -> dict:
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    chunks = 0
    pieces: list[str] = []
    started = time.perf_counter()
    with urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if line.startswith(b"data:") and b"[DONE]" not in line:
                chunks += 1
                try:
                    obj = json.loads(line[5:].strip())
                    choices = obj.get("choices") or []
                    if choices:
                        piece = (choices[0].get("delta") or {}).get("content")
                        if piece is None:
                            piece = choices[0].get("text")
                        if piece:
                            pieces.append(piece)
                except json.JSONDecodeError:
                    pass
                if chunks >= after_chunks:
                    resp.close()
                    cancelled.set()
                    break
    text = "".join(pieces)
    return {
        "cancelled_after_chunks": chunks,
        "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        "partial_text": text,
        "partial_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def describe(result, tok) -> dict:
    text = result.text or ""
    token_ids = tok.encode(text, add_special_tokens=False)
    return {
        "ok": result.ok,
        "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason,
        "ttft_ms": result.ttft_ms,
        "e2e_ms": result.e2e_ms,
        "error": result.error,
        "text": text,
        "text_sha256": result.text_sha256,
        "retokenized_ids": token_ids,
        "retokenized_ids_sha256": hashlib.sha256(json.dumps(token_ids).encode()).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--backend-sampling", choices=("off", "on"), default="off")
    ap.add_argument("--mode", choices=("normal", "forced"), default="normal")
    ap.add_argument("--holes", default="0,1,3", help="Victim slots for forced mode")
    args = ap.parse_args()

    tok = load_tokenizer(args.tokenizer)
    special = sorted(set(tok.all_special_ids or []))
    endpoint = args.base_url.rstrip("/") + "/v1/completions"
    holes = [int(item) for item in args.holes.split(",") if item.strip()] if args.mode == "forced" else [1, 2]

    def prompt_ids(label: str, seed: int) -> list[int]:
        prefix = tok.encode(f"Independent request {label}. Preserve this request's state. ", add_special_tokens=False)
        filler = load_prompt_ids(tok, 128, seed)
        ids = (prefix + filler)[:128]
        if len(ids) < 128:
            ids.extend(filler[:128 - len(ids)])
        return ids

    def payload(label: str, seed: int, max_tokens: int, slot_id: int | None) -> dict:
        payload = make_payload(
            request_model=args.model,
            prompt_ids=prompt_ids(label, seed),
            max_tokens=max_tokens,
            temperature=0.0,
            top_p=1.0,
            sampler_seed=seed,
            cache_prompt=False,
            workload_kind="controlled_fixed_output",
            special_token_ids=special,
            slot_id=slot_id,
        )
        payload["backend_sampling"] = args.backend_sampling == "on"
        return payload

    if args.backend_sampling == "on":
        rejection_payload = payload("backend-sampling-rejection", 9900, 8, 0 if args.mode == "forced" else None)
        req = Request(endpoint, data=json.dumps(rejection_payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
        status = None
        body = ""
        try:
            with urlopen(req, timeout=args.timeout) as resp:
                status = resp.status
                body = resp.read().decode(errors="replace")
        except HTTPError as exc:
            status = exc.code
            body = exc.read().decode(errors="replace")
        expected = status == 400 and "sampler migration is not supported" in body
        result = {
            "schema_version": 2,
            "slot_policy": args.mode,
            "backend_sampling": args.backend_sampling,
            "expected_rejection": expected,
            "http_status": status,
            "response_body": body,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if expected else 3

    scenarios = []
    all_ok = True
    for cycle, victim in enumerate(holes):
        started = Event()
        cancelled_event = Event()

        def run_survivor(index: int):
            started.wait()
            return post_stream(
                endpoint,
                payload(f"cycle-{cycle}-survivor-{index}", 7300 + 100 * cycle + index, 128,
                        index if args.mode == "forced" else None),
                args.timeout,
                lambda text: len(tok.encode(text, add_special_tokens=False)),
                True,
            )

        def run_victim():
            started.wait()
            return cancel_stream(
                endpoint,
                payload(f"cycle-{cycle}-victim-{victim}", 8100 + cycle, 256,
                        victim if args.mode == "forced" else None),
                8,
                args.timeout,
                cancelled_event,
            )

        survivor_ids = [idx for idx in range(4) if idx != victim]
        with ThreadPoolExecutor(max_workers=5) as pool:
            survivor_futures = [pool.submit(run_survivor, idx) for idx in survivor_ids]
            victim_future = pool.submit(run_victim)
            batch_start = time.perf_counter()
            started.set()
            if not cancelled_event.wait(args.timeout):
                raise RuntimeError("victim stream did not reach its cancellation point")
            # Give the server a bounded interval to observe the disconnected client,
            # then recycle that logical slot while the three long requests continue.
            time.sleep(0.05)
            newcomer = post_stream(
                endpoint,
                payload(f"cycle-{cycle}-newcomer-{victim}", 9100 + cycle, 48,
                        victim if args.mode == "forced" else None),
                args.timeout,
                lambda text: len(tok.encode(text, add_special_tokens=False)),
                True,
            )
            survivors = [future.result() for future in survivor_futures]
            cancelled_result = victim_future.result()

        survivor_desc = [describe(result, tok) for result in survivors]
        newcomer_desc = describe(newcomer, tok)
        scenario_ok = all(item["ok"] and item["output_tokens"] == 128 for item in survivor_desc)
        scenario_ok &= newcomer_desc["ok"] and newcomer_desc["output_tokens"] == 48
        all_ok &= scenario_ok
        scenarios.append({
            "cycle": cycle,
            "victim_slot": victim if args.mode == "forced" else None,
            "survivor_slots": survivor_ids if args.mode == "forced" else None,
            "survivors": survivor_desc,
            "cancel": cancelled_result,
            "newcomer": newcomer_desc,
            "scenario_ok": scenario_ok,
            "wall_ms": (time.perf_counter() - batch_start) * 1000.0,
        })

    result = {
        "schema_version": 2,
        "slot_policy": args.mode,
        "backend_sampling": args.backend_sampling,
        "scenario_contract": "cancel while three peers remain active, then recycle before peers finish",
        "scenarios": scenarios,
        "all_scenarios_ok": all_ok,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if all_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
