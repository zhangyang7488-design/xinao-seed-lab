from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    case_input_path = ROOT / "case_input.json"
    case_input = json.loads(case_input_path.read_text(encoding="utf-8"))
    if case_input.get("case_id") != args.case:
        raise SystemExit("case identity mismatch")
    payload: dict[str, object] = {
        "status": "SEMANTIC_IMPLICATION_CONSUMER_OK",
        "case_id": args.case,
        "nonce": case_input["read_nonce"],
        "case_input_sha256": _sha256(case_input_path),
        "facts": case_input,
    }
    effect_root = ROOT / "effects" / args.case
    target_path = effect_root / "target.txt"
    marker_path = effect_root / "effect.marker"
    if target_path.is_file():
        payload["target"] = target_path.read_text(encoding="utf-8").strip()
        payload["effect_marker"] = marker_path.is_file()
    parent_state_path = ROOT / "parent_state.json"
    if parent_state_path.is_file():
        payload["parent_state"] = json.loads(parent_state_path.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
