import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "service_quality_client", ROOT / "work/scripts/service_quality_client.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_reserved_corpus_has_required_categories():
    corpus = json.loads((ROOT / "work/quality/service_eos_v5.json").read_text())
    categories = {case["category"] for case in corpus["cases"]}
    assert {
        "mathematics", "json", "tool-like structured output", "instructions",
        "Spanish", "long context", "long generation"
    } <= categories


def test_validators_cover_exact_json_contains_and_length():
    assert MODULE.validate("  alpha   beta ", {"kind": "normalized_exact", "value": "alpha beta"})[0]
    assert MODULE.validate('{"answer":"ok","count":3}', {
        "kind": "json_fields", "fields": {"answer": "ok", "count": 3}
    })[0]
    assert MODULE.validate("Madrid está en España.", {
        "kind": "contains_all", "values": ["Madrid", "España"]
    })[0]
    assert MODULE.validate("uno dos tres", {"kind": "min_words", "value": 3})[0]


def test_service_policy_is_not_fixed_output_policy():
    source = (ROOT / "work/scripts/service_quality_client.py").read_text()
    assert '"ignore_eos": False' in source
    assert '"logit_bias"' not in source
