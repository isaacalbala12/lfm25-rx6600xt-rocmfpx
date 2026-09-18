#!/usr/bin/env python3
"""Run the reserved service-EOS corpus and retain auditable full outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


def norm(text: str) -> str:
    return " ".join(text.strip().split())


def validate(text: str, spec: dict) -> tuple[bool, str]:
    kind = spec["kind"]
    if kind == "normalized_exact":
        ok = norm(text) == spec["value"]
    elif kind == "contains_all":
        ok = all(value in text for value in spec["values"])
    elif kind == "min_words":
        ok = len(text.split()) >= int(spec["value"])
    elif kind == "json_fields":
        try:
            obj = json.loads(text.strip())
            ok = all(obj.get(key) == value for key, value in spec["fields"].items())
        except (ValueError, AttributeError):
            ok = False
    else:
        raise ValueError(f"unknown validator: {kind}")
    return ok, kind


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text())
    records = []
    for case in corpus["cases"]:
        prompt = case["prompt"] + case.get("repeat_text", "") * int(case.get("repeat_count", 0)) + case.get("suffix", "")
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": args.seed,
            "max_tokens": case["max_tokens"],
            "stream": False,
            "ignore_eos": False,
            "cache_prompt": False
        }
        started = time.perf_counter()
        error = None
        response_obj = None
        try:
            request = Request(
                args.base_url.rstrip("/") + "/v1/chat/completions",
                data=json.dumps(payload, separators=(",", ":")).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=args.timeout) as response:
                response_obj = json.load(response)
        except Exception as exc:
            error = repr(exc)
        elapsed_ms = 1000.0 * (time.perf_counter() - started)
        choice = ((response_obj or {}).get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        visible = content if content.strip() else reasoning
        valid, validator = validate(visible, case["validator"]) if error is None else (False, case["validator"]["kind"])
        records.append({
            "id": case["id"],
            "category": case["category"],
            "prompt_chars": len(prompt),
            "elapsed_ms": elapsed_ms,
            "finish_reason": choice.get("finish_reason"),
            "usage": (response_obj or {}).get("usage") or {},
            "content": content,
            "reasoning_content": reasoning,
            "visible_text": visible,
            "visible_sha256": hashlib.sha256(visible.encode()).hexdigest(),
            "validator": validator,
            "validation_passed": valid,
            "error": error,
        })

    policy = {"ignore_eos": False, "logit_bias_present": False, "stream": False}
    result = {
        "schema_version": 1,
        "corpus": corpus["name"],
        "request_policy": policy,
        "all_requests_succeeded": all(r["error"] is None and r["finish_reason"] is not None for r in records),
        "all_validators_passed": all(r["validation_passed"] for r in records),
        "records": records,
    }
    result["status"] = "VALID" if result["all_requests_succeeded"] and result["all_validators_passed"] else "INVALID"
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": result["status"], "cases": len(records), "passed": sum(r["validation_passed"] for r in records)}))
    return 0 if result["status"] == "VALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
