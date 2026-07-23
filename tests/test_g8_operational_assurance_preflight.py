from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_g8_operational_assurance_preflight.py"


def _command(op_root: Path, proof: Path, *, require_ready: bool = False) -> list[str]:
    now = datetime.now(UTC)
    issued_at = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    expires_at = (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    command = [
        sys.executable,
        str(SCRIPT),
        "--op-root",
        str(op_root),
        "--runtime-root",
        str(op_root.parent),
        "--report-id",
        "fresh-process-current-gap",
        "--scope",
        "xinao-domain-mainline",
        "--realm",
        "DOMAIN_FIXED_AXIOM",
        "--source-commit",
        "9" * 40,
        "--input-hash",
        f"contract={'a' * 64}",
        "--artifact-hash",
        f"lockfile={'b' * 64}",
        "--producer-identity",
        "preflight-producer",
        "--verifier-identity",
        "preflight-verifier",
        "--independence-evidence",
        str(proof),
        "--issued-at",
        issued_at,
        "--expires-at",
        expires_at,
    ]
    if require_ready:
        command.append("--require-ready")
    return command


def test_fresh_process_materializes_explicit_current_deny(tmp_path: Path) -> None:
    proof = tmp_path / "independent-review.json"
    proof.write_text('{"verdict":"non-authoritative discovery"}\n', encoding="utf-8")
    completed = subprocess.run(
        _command(tmp_path / "op", proof),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    manifest = json.loads((tmp_path / "op" / "run_manifest.v1.json").read_text())
    assert result["decision"] == "DENY"
    assert result["g8_closed"] is False
    assert result["live_shadow_claim_allowed"] is False
    assert result["parent_complete"] is False
    assert len(result["missing_or_unready_dimensions"]) == 6
    assert manifest["verification_ok"] is True
    assert manifest["g8_closed"] is False


def test_require_ready_returns_nonzero_on_current_gap(tmp_path: Path) -> None:
    proof = tmp_path / "independent-review.json"
    proof.write_text('{"verdict":"non-authoritative discovery"}\n', encoding="utf-8")
    completed = subprocess.run(
        _command(tmp_path / "op-required", proof, require_ready=True),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["g8_closed"] is False
