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
    effect = case_input.get("effect") or {}
    if effect.get("authorized") is not True:
        raise SystemExit("effect not authorized for this case")
    effect_root = ROOT / "effects" / args.case
    target = effect_root / "target.txt"
    if not target.is_file():
        raise SystemExit("effect target is missing")
    if target.read_text(encoding="utf-8").strip() != effect.get("initial_target"):
        raise SystemExit("effect target is not at the declared initial value")
    target.write_text(str(effect["adopted_target"]) + "\n", encoding="utf-8", newline="")
    (effect_root / "effect.marker").write_text(
        "bounded-local-effect\n", encoding="utf-8", newline=""
    )
    print("SEMANTIC_IMPLICATION_EFFECT_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
