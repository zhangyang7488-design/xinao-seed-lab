"""Retired compatibility entry for the invalid campaign-wide capacity gate."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

RETIREMENT_REASON = "RETIRED_FULL_CAMPAIGN_PROVIDER_CAPACITY_PREFLIGHT"
REPLACEMENT = "scripts/run_g4_batch_execution_admission.py"


def main(argv: Sequence[str] | None = None) -> int:
    """Refuse the old topology without dispatching, querying quota, or reading outcomes."""

    ignored_arguments = list(argv) if argv is not None else sys.argv[1:]
    print(
        json.dumps(
            {
                "schema_version": "xinao.retired_entrypoint.v1",
                "status": "retired",
                "reason_code": RETIREMENT_REASON,
                "replacement": REPLACEMENT,
                "ignored_argument_count": len(ignored_arguments),
                "provider_invocation_performed": False,
                "quota_query_performed": False,
                "hidden_outcome_access": False,
                "g4_full": False,
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
