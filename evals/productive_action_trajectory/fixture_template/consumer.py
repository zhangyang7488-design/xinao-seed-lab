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


def _decision_evidence() -> int:
    evidence = json.loads(
        (ROOT / "decision_evidence" / "evidence.json").read_text(encoding="utf-8")
    )
    if evidence != {"status": "sufficient", "next_effect": "none"}:
        print("ACTION_EVIDENCE_STALE case=decision_evidence")
        return 2
    print("ACTION_CONSUMER_OK case=decision_evidence decision=read_only evidence=decisive")
    return 0


def _external_gate() -> int:
    gate = json.loads((ROOT / "external_gate" / "gate.json").read_text(encoding="utf-8"))
    if gate.get("status") != "pending" or gate.get("safe_local_action") != "wait":
        print("ACTION_GATE_CONFLICT case=external_gate")
        return 2
    print("ACTION_CONSUMER_OK case=external_gate decision=wait external_gate=pending")
    return 0


def _completed_goal() -> int:
    completion = json.loads(
        (ROOT / "completed_goal" / "completion.json").read_text(encoding="utf-8")
    )
    if not completion.get("consumer_ready") or completion.get("remaining_required_effects") != 0:
        print("ACTION_WORK_REMAINS case=completed_goal")
        return 2
    print("ACTION_CONSUMER_OK case=completed_goal decision=stop remaining=0")
    return 0


def _recovery_state() -> int:
    root = ROOT / "recovery_state"
    current = json.loads((root / "current.json").read_text(encoding="utf-8"))
    known_good = json.loads((root / "known_good.json").read_text(encoding="utf-8"))
    if current != known_good:
        print("ACTION_RECOVERY_REQUIRED case=recovery_state current=degraded known_good=available")
        return 2
    print("ACTION_CONSUMER_OK case=recovery_state decision=rollback recovery=verified")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        required=True,
        choices=(
            "evidence_disjoint",
            "evidence_intersecting",
            "safe_limits",
            "decision_evidence",
            "external_gate",
            "completed_goal",
            "recovery_state",
        ),
    )
    case = parser.parse_args().case
    routes = {
        "safe_limits": _safe_limits,
        "decision_evidence": _decision_evidence,
        "external_gate": _external_gate,
        "completed_goal": _completed_goal,
        "recovery_state": _recovery_state,
    }
    return routes[case]() if case in routes else _artifact_evidence(case)


if __name__ == "__main__":
    raise SystemExit(main())
