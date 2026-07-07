import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_write_meta_rsi_wave_preserves_json_array_inputs(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    lanes_json = json.dumps(
        [
            {"lane_id": "control_plane_liveness", "status": "ready"},
            {"lane_id": "light_research_local_root", "status": "verified"},
        ]
    )
    results_json = json.dumps(
        [
            {"result_id": "pytest_reconciler", "status": "passed"},
            {"result_id": "runtime_reconciler", "status": "validated"},
        ]
    )

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "hardmode" / "Write-MetaRsiWave.ps1"),
            "-TaskId",
            "unit-meta-rsi-wave",
            "-WaveId",
            "unit-meta-rsi-wave-array-inputs",
            "-Mode",
            "repair",
            "-RuntimeRoot",
            str(runtime),
            "-LanesJson",
            lanes_json,
            "-ResultsJson",
            results_json,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    latest = json.loads(
        (runtime / "state" / "meta_rsi_wave" / "latest.json").read_text(
            encoding="utf-8-sig"
        )
    )

    assert [lane["lane_id"] for lane in payload["lanes"]] == [
        "control_plane_liveness",
        "light_research_local_root",
    ]
    assert [result["result_id"] for result in latest["results"]] == [
        "pytest_reconciler",
        "runtime_reconciler",
    ]
    assert "value" not in payload["lanes"][0]
    assert "Count" not in payload["results"][0]
