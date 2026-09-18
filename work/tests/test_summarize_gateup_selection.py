import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "work/scripts/summarize_gateup_selection.py"


def test_gateup_histogram_filters_other_shapes(tmp_path):
    log = tmp_path / "server.log"
    out = tmp_path / "summary.json"
    log.write_text(
        "VKSEL event=mul_mat tensor=gate m=10752 n=128 k=2048 pipeline=bk3_m\n"
        "VKSEL event=mul_mat tensor=up m=10752 n=128 k=2048 pipeline=bk3_m\n"
        "VKSEL event=mul_mat tensor=down m=2048 n=128 k=10752 pipeline=control_m\n"
        "VKSEL event=mul_mat tensor=gate m=10752 n=96 k=2048 pipeline=bk3_m\n"
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(log), "--output", str(out)],
        check=False,
    )
    assert completed.returncode == 0
    data = json.loads(out.read_text())
    assert data["all_mul_mat_events"] == 4
    assert data["gateup_events"] == 3
    assert data["histogram"] == [
        {"n": 96, "pipeline": "bk3_m", "calls": 1},
        {"n": 128, "pipeline": "bk3_m", "calls": 2},
    ]
