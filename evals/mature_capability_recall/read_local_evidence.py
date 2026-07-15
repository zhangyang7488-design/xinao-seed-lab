"""Read one curated local-evidence fixture and emit its exact split content hash."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "local"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    args = parser.parse_args()
    fixture = (FIXTURES / f"{args.case}.json").resolve()
    if fixture.parent != FIXTURES.resolve() or not fixture.is_file():
        raise SystemExit(f"unknown local-evidence case: {args.case}")
    raw = fixture.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    print(
        json.dumps(
            {
                "fixture_sha256_parts": f"{digest[:32]}:{digest[32:]}",
                "evidence": json.loads(raw.decode("utf-8")),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
