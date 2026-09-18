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
