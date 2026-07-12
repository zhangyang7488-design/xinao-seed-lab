"""Re-run the pinned L0 M1 and mature M2-M4 walk-forward in one command."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
M1_SCRIPT = PROJECT_ROOT / "scripts" / "_l0_m1_frequency_null_canary.py"
M1_RESULT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\codex_L0_backtest_numbers.json")
SNAPSHOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_snapshot"
    r"\macaujc2_corrected_2023_2026_v2.txt"
)
MANIFEST = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\l0_snapshot\manifest.json")
M2M4_PYTHON = Path(r"E:\XINAO_EXTERNAL_MATURE\lab_seed_stack\venv\Scripts\python.exe")
M2M4_RUNNER = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\xinao_market\runner\run_s7_m2_m4_walkforward.py"
)
EVIDENCE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\evidence\dual_brain_mainline\l0_one_command_rerun")
LATEST = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\L0_one_command_rerun_latest.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run(command: list[str], *, cwd: Path, timeout: int, log_prefix: Path) -> int:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    log_prefix.with_suffix(".stdout.log").write_text(completed.stdout, encoding="utf-8")
    log_prefix.with_suffix(".stderr.log").write_text(completed.stderr, encoding="utf-8")
    return completed.returncode


def _m2_command(python: Path, runner: Path, evidence_dir: Path) -> list[str]:
    return [
        str(python),
        str(runner),
        "--n",
        "300",
        "--train0",
        "180",
        "--test-bars",
        "20",
        "--step",
        "20",
        "--prefer",
        "tsv",
        "--evidence-dir",
        str(evidence_dir),
    ]


def _acceptance_checks(
    manifest: dict[str, Any], snapshot_sha: str, m1: dict[str, Any], m2m4: dict[str, Any]
) -> dict[str, bool]:
    expected_sha = str(manifest.get("sha256") or "").upper()
    m1_pin = str((m1.get("data_pin") or {}).get("sha256") or "").upper()
    m2_pin = str((m2m4.get("data_pin") or {}).get("sha256") or "").upper()
    return {
        "snapshot_hash_matches_manifest": bool(expected_sha) and snapshot_sha.upper() == expected_sha,
        "m1_uses_pinned_snapshot": m1_pin == expected_sha,
        "m1_sample_n_300": (m1.get("sample") or {}).get("N") == 300,
        "m2m4_uses_same_pinned_snapshot": m2_pin == expected_sha,
        "m2m4_sample_n_300": (m2m4.get("sample") or {}).get("N") == 300,
        "m2m4_oos_cycles_ge_5": int(m2m4.get("n_oos_cycles") or 0) >= 5,
        "m2m4_is_not_m1_stub": m2m4.get("not_m1_stub") is True,
        "honest_completion_gate": m1.get("completion_claim_allowed") is False
        and m2m4.get("completion_claim_allowed") is False,
        "honest_edge_gate": m2m4.get("edge_claim") is False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m2m4-python", type=Path, default=M2M4_PYTHON)
    parser.add_argument("--m2m4-runner", type=Path, default=M2M4_RUNNER)
    parser.add_argument("--evidence-root", type=Path, default=EVIDENCE_ROOT)
    parser.add_argument("--latest", type=Path, default=LATEST)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    required = [M1_SCRIPT, SNAPSHOT, MANIFEST, args.m2m4_python, args.m2m4_runner]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required L0 capability: {missing}")

    run_id = datetime.now(UTC).strftime("l0_%Y%m%dT%H%M%SZ")
    evidence_dir = args.evidence_root / run_id
    m2_evidence = evidence_dir / "m2m4"
    evidence_dir.mkdir(parents=True, exist_ok=False)
    m2_evidence.mkdir()

    m1_command = [sys.executable, str(M1_SCRIPT)]
    m2_command = _m2_command(args.m2m4_python, args.m2m4_runner, m2_evidence)
    m1_exit = _run(m1_command, cwd=PROJECT_ROOT, timeout=args.timeout, log_prefix=evidence_dir / "m1")
    m2_exit = -1
    if m1_exit == 0:
        m2_exit = _run(
            m2_command,
            cwd=args.m2m4_runner.parent,
            timeout=args.timeout,
            log_prefix=evidence_dir / "m2m4",
        )

    manifest = _load_json(MANIFEST)
    m1 = _load_json(M1_RESULT) if m1_exit == 0 and M1_RESULT.is_file() else {}
    m2_result_path = m2_evidence / "RESULT.json"
    m2m4 = _load_json(m2_result_path) if m2_exit == 0 and m2_result_path.is_file() else {}
    checks = _acceptance_checks(manifest, _sha256(SNAPSHOT), m1, m2m4)
    all_ok = m1_exit == 0 and m2_exit == 0 and all(checks.values())

    payload = {
        "schema_version": "xinao.kaigong_wave.L0_one_command_rerun.v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "status": "verified" if all_ok else "failed",
        "all_ok": all_ok,
        "completion_claim_allowed": False,
        "edge_claim": False,
        "promote_L1_allowed": bool(m2m4.get("promote_L1_allowed") is True) if m2m4 else False,
        "checks": checks,
        "commands": {"m1": m1_command, "m2m4": m2_command},
        "exit_codes": {"m1": m1_exit, "m2m4": m2_exit},
        "data_pin": {"path": str(SNAPSHOT), "sha256": _sha256(SNAPSHOT)},
        "results": {"m1": str(M1_RESULT), "m2m4": str(m2_result_path)},
        "evidence_dir": str(evidence_dir),
        "numeric_gate_reasons": ((m2m4.get("gates") or {}).get("block_reasons") or []),
    }
    _write_json(evidence_dir / "result.json", payload)
    _write_json(args.latest, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
