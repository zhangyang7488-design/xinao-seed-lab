from __future__ import annotations

import json
from pathlib import Path

ALLOWED_ROLES = {"parameters", "paths", "contract_translation", "thin_adapter"}


def evaluate(evidence: dict[str, object]) -> str:
    roles = set(evidence.get("changed_roles") or [])
    verified = all(
        (
            bool(roles) and roles <= ALLOWED_ROLES,
            evidence.get("provider_pinned") is True,
            int(evidence.get("upstream_invocation_count") or 0) >= 2,
            evidence.get("fallback_used") is False,
            evidence.get("new_runtime") is False,
            evidence.get("external_source_modified") is False,
        )
    )
    return "verified" if verified else "rejected"


def load_cases() -> list[dict[str, object]]:
    path = Path(__file__).with_name("contract_cases.json")
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


if __name__ == "__main__":
    rows = [
        {
            "id": case["id"],
            "actual": evaluate(case["evidence"]),
            "expected": case["expected"],
        }
        for case in load_cases()
    ]
    print(json.dumps(rows, sort_keys=True))
    raise SystemExit(0 if all(row["actual"] == row["expected"] for row in rows) else 1)
