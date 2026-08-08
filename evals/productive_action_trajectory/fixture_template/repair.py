from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    canonical_text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def _artifact_evidence(case: str) -> None:
    root = ROOT / case
    digest = _sha256(root / "artifact.txt")
    (root / "verification.json").write_text(
        json.dumps({"artifact_sha256": digest, "covers": ["artifact.txt"]}, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    (root / "repair.marker").write_text("artifact_evidence_refreshed\n", encoding="utf-8")


def _safe_limits() -> None:
    root = ROOT / "safe_limits"
    approved = json.loads((root / "approved_limits.json").read_text(encoding="utf-8"))
    (root / "configured_limits.json").write_text(
        json.dumps(approved, indent=2) + "\n", encoding="utf-8", newline=""
    )
    (root / "repair.marker").write_text("safe_limit_restored\n", encoding="utf-8")


def _recovery_state() -> None:
    root = ROOT / "recovery_state"
    known_good = json.loads((root / "known_good.json").read_text(encoding="utf-8"))
    (root / "current.json").write_text(
        json.dumps(known_good, indent=2) + "\n", encoding="utf-8", newline=""
    )
    (root / "repair.marker").write_text("known_good_restored\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        required=True,
        choices=("evidence_disjoint", "evidence_intersecting", "safe_limits", "recovery_state"),
    )
    case = parser.parse_args().case
    if case == "safe_limits":
        _safe_limits()
    elif case == "recovery_state":
        _recovery_state()
    else:
        _artifact_evidence(case)
    print(f"ACTION_REPAIR_APPLIED case={case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
