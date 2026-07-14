"""Fresh-process P11 NO_ACTION and future-leakage domain checks."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from xinao.validation import FeatureObservation, validate_candidate, validate_temporal_features
from xinao.world.builder import load_draws


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected_report.read_text(encoding="utf-8"))
    draws = load_draws()
    report = validate_candidate(draws).model_dump(mode="json")
    open_time = datetime(2026, 7, 15, tzinfo=UTC)
    validate_temporal_features(
        [
            FeatureObservation(
                feature_name="safe",
                feature_timestamp=open_time - timedelta(seconds=1),
                target_open_time=open_time,
            )
        ]
    )
    leakage_rejected = False
    leakage_error = ""
    try:
        validate_temporal_features(
            [
                FeatureObservation(
                    feature_name="future-leak",
                    feature_timestamp=open_time,
                    target_open_time=open_time,
                )
            ]
        )
    except ValueError as exc:
        leakage_rejected = "future leakage" in str(exc)
        leakage_error = str(exc)
    checks = {
        "draw_count_913": len(draws) == 913,
        "no_action": report["verdict"] == "NO_ACTION",
        "no_action_hash_matches_p5": report["output_hash"] == expected["output_hash"],
        "no_action_reasons_match_p5": report["no_action_reasons"]
        == expected["no_action_reasons"],
        "future_leakage_rejected": leakage_rejected,
    }
    result = {
        "schema_version": "xinao.p11_domain_checks.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "verified_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "candidate_report": report,
        "leakage_error": leakage_error,
    }
    write_json_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
