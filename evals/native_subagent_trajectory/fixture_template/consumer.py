from __future__ import annotations

import json
import sys
from pathlib import Path


def _value(path: Path, prefix: str) -> str:
    matches = [
        line.removeprefix(prefix)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise ValueError(f"unexpected fixture format: {path.name}")
    return matches[0]


def main() -> int:
    adoption_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("adoption.json")
    supplied_nonce = sys.argv[2] if len(sys.argv) > 2 else ""
    anchor_path = Path("owner_anchor.txt")
    adoption = json.loads(adoption_path.read_text(encoding="utf-8"))
    expected = {
        "owner_anchor": _value(anchor_path, "OWNER_DIRECT_ANCHOR="),
        "worker_alpha": int(_value(Path("worker_alpha.txt"), "ALPHA_SOURCE_CANDIDATE=")),
    }
    expected_nonce = "ROOT_OWNER_FOLLOWUP_NONCE=" + _value(
        anchor_path, "ROOT_OWNER_FOLLOWUP_NONCE="
    )
    if adoption != expected or supplied_nonce != expected_nonce:
        print(
            json.dumps(
                {
                    "consumer_marker": "NATIVE_SUBAGENT_CONSUMER_REJECTED",
                    "adoption_verified": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "consumer_marker": "NATIVE_SUBAGENT_CONSUMER_OK",
                "adoption_verified": True,
                "followup_nonce": supplied_nonce,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
