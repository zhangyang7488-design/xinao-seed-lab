from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    case_input = json.loads((ROOT / "case_input.json").read_text(encoding="utf-8"))
    if case_input.get("case_id") != args.case:
        raise SystemExit("case identity mismatch")
    local_result = case_input.get("local_result")
    if not isinstance(local_result, dict) or not local_result.get("claim_id"):
        raise SystemExit("case has no local result to return")
    state_path = ROOT / "parent_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    claim_id = str(local_result["claim_id"])
    returned = list(state.get("returned_result_ids") or [])
    if claim_id not in returned:
        returned.append(claim_id)
    state["returned_result_ids"] = returned
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    print("SEMANTIC_IMPLICATION_LOCAL_RESULT_RETURNED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
