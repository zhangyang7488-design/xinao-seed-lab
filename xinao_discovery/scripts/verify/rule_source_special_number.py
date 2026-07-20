"""Compile current source-binding and special-number convention evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xinao.settlement import verify_special_number_rule_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--fresh-process-replay", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify_special_number_rule_evidence(
        source_report_path=args.evidence_root / "source_bundle_verification.json",
        fresh_process_replay_path=args.fresh_process_replay,
        output_path=args.evidence_root / "special_number_rule_evidence.json",
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "rule_ref": result["rule_ref"],
                "source_bundle_hash": result["source_bundle_hash"],
                "output": str(args.evidence_root / "special_number_rule_evidence.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
