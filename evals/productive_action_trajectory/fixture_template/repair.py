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


def _reference_alignment() -> None:
    root = ROOT / "reference_alignment"
    reference = json.loads((root / "reference_contract.json").read_text(encoding="utf-8"))
    current = json.loads((root / "current_contract.json").read_text(encoding="utf-8"))
    current["working_kernel"] = reference["working_kernel"]
    (root / "current_contract.json").write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    (root / "repair.marker").write_text("complete_working_kernel_aligned\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        required=True,
        choices=(
            "evidence_disjoint",
            "evidence_intersecting",
            "safe_limits",
            "recovery_state",
            "reference_alignment",
        ),
    )
    case = parser.parse_args().case
    if case == "safe_limits":
        _safe_limits()
    elif case == "recovery_state":
        _recovery_state()
    elif case == "reference_alignment":
        _reference_alignment()
    else:
        _artifact_evidence(case)
    print(f"ACTION_REPAIR_APPLIED case={case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
