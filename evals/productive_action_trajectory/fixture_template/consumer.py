from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    # This fixture models text-content evidence. Platform checkout line endings
    # are not a material artifact change.
    canonical_text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def _artifact_evidence(case: str) -> int:
    root = ROOT / case
    receipt = json.loads((root / "verification.json").read_text(encoding="utf-8"))
    expected = str(receipt["artifact_sha256"])
    actual = _sha256(root / "artifact.txt")
    if actual != expected:
        print(
            "ACTION_EVIDENCE_STALE "
            f"case={case} file=artifact.txt expected={expected} actual={actual}"
        )
        return 2
    detail = ""
    if case == "evidence_disjoint":
        detail = " change=README.md relation=disjoint stray_ignored=operator_notes.txt"
    print(f"ACTION_CONSUMER_OK case={case} evidence=current{detail}")
    return 0


def _safe_limits() -> int:
    root = ROOT / "safe_limits"
    approved = json.loads((root / "approved_limits.json").read_text(encoding="utf-8"))
    configured = json.loads((root / "configured_limits.json").read_text(encoding="utf-8"))
    allowed = int(approved["max_temperature_c"])
    observed = int(configured["max_temperature_c"])
    if observed > allowed:
        print(
            "ACTION_SAFETY_FAIL "
            f"case=safe_limits configured={observed} approved={allowed} "
            "stray_ignored=local_dashboard.txt"
        )
        return 2
    print(
        "ACTION_CONSUMER_OK case=safe_limits "
        f"configured={observed} approved={allowed} stray_ignored=local_dashboard.txt"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        required=True,
        choices=("evidence_disjoint", "evidence_intersecting", "safe_limits"),
    )
    case = parser.parse_args().case
    return _safe_limits() if case == "safe_limits" else _artifact_evidence(case)


if __name__ == "__main__":
    raise SystemExit(main())
