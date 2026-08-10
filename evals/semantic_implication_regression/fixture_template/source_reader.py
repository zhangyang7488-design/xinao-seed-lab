from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "selected_stimulus.json"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selector", choices=("canonical_variant", "canonical_recovery"), required=True
    )
    parser.add_argument("--case", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--order", choices=("AB", "BA", "none"), required=True)
    args = parser.parse_args()
    stimulus = json.loads(SOURCE.read_text(encoding="utf-8"))
    identity = (
        stimulus.get("source_selector"),
        stimulus.get("source_case_id"),
        stimulus.get("source_member_id"),
        stimulus.get("turn_order"),
    )
    requested = (args.selector, args.case, args.member, args.order)
    if identity != requested:
        raise SystemExit("selected stimulus identity mismatch")
    raw = SOURCE.read_bytes()
    print(
        json.dumps(
            {
                "status": "SEMANTIC_IMPLICATION_SOURCE_OK",
                "selected_file_sha256": hashlib.sha256(raw).hexdigest(),
                "selected_stimulus_sha256": hashlib.sha256(_canonical_bytes(stimulus)).hexdigest(),
                "stimulus": stimulus,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
