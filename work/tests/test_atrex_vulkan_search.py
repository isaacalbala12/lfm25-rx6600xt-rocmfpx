import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "atrex_vulkan_search.py"
SPEC = importlib.util.spec_from_file_location("atrex_vulkan_search", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def manifest(candidate_id: str, mutation: str = "unroll compute loop") -> dict:
    return {
        "schema_version": 1,
        "id": candidate_id,
        "parent": "incumbent",
        "mutation": mutation,
        "control_env": {"CANDIDATE": "0"},
        "candidate_env": {"CANDIDATE": "1"},
        "expected_control_pipeline": "control",
        "expected_candidate_pipeline": "candidate",
    }


def test_queue_uses_manifest_id_and_skips_attempted_fingerprint(tmp_path):
    first = manifest("real-id")
    (tmp_path / "file-name-does-not-match.json").write_text(json.dumps(first))
    state = {"attempts": [{"id": "old", "fingerprint": MODULE.candidate_fingerprint(first)}]}
    assert MODULE.candidate_queue(tmp_path, state) == []


def test_queue_can_retry_invalid_without_retrying_valid(tmp_path):
    first = manifest("candidate")
    (tmp_path / "candidate.json").write_text(json.dumps(first))
    fingerprint = MODULE.candidate_fingerprint(first)
    invalid = {"attempts": [{"id": "candidate", "fingerprint": fingerprint, "gate": "INVALID"}]}
    assert len(MODULE.candidate_queue(tmp_path, invalid, retry_invalid=True)) == 1
    valid = {"attempts": [{"id": "candidate", "fingerprint": fingerprint, "gate": "PASS"}]}
    assert MODULE.candidate_queue(tmp_path, valid, retry_invalid=True) == []


def test_queue_rejects_equivalent_mutations(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(manifest("a")))
    (tmp_path / "b.json").write_text(json.dumps(manifest("b")))
    try:
        MODULE.candidate_queue(tmp_path, {"attempts": []})
    except ValueError as error:
        assert "equivalent candidate mutation" in str(error)
    else:
        raise AssertionError("equivalent manifests were accepted")


def test_only_formal_pass_evidence_updates_incumbent():
    state = {
        "baseline_candidate": "control",
        "attempts": [
            {"id": "smoke-win", "gate": "PASS", "evidence_level": "smoke", "delta_percent": -9.0},
            {"id": "invalid-win", "gate": "INVALID", "evidence_level": "formal_micro", "delta_percent": -8.0},
            {"id": "formal-win", "gate": "PASS", "evidence_level": "formal_micro", "delta_percent": -2.0},
        ],
    }
    result = MODULE.recompute_state(state)
    assert result["best_candidate"] == "formal-win"
    assert result["best_delta_percent"] == -2.0
    assert result["valid_candidates"] == 1


def test_new_state_uses_campaign_baseline(tmp_path):
    state = MODULE.load_state(tmp_path / "state.json", "down-bm64-bn64-bk32-bk4")
    assert state["baseline_candidate"] == "down-bm64-bn64-bk32-bk4"
    assert state["best_candidate"] == "down-bm64-bn64-bk32-bk4"


def test_existing_state_rejects_different_campaign_baseline(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"baseline_candidate": "gate", "attempts": []}))
    try:
        MODULE.load_state(path, "down")
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("cross-campaign state reuse was accepted")
