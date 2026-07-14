"""Export deterministic P1 contract schemas to a requested evidence directory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from xinao.contracts import (
    AuthorityContract,
    BaselineOddsWaterVersion,
    CommonEnvelope,
    DatasetSnapshot,
    HandoffMessage,
    domain_schema_catalog,
)


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    output = args.out.resolve()
    write_atomic(output / "common_envelope.schema.json", CommonEnvelope.model_json_schema())
    write_atomic(output / "domain_schema_catalog.json", domain_schema_catalog())
    write_atomic(output / "agent_handoff.schema.json", HandoffMessage.model_json_schema())
    write_atomic(output / "authority_contract.schema.json", AuthorityContract.model_json_schema())
    write_atomic(output / "dataset_snapshot.schema.json", DatasetSnapshot.model_json_schema())
    write_atomic(
        output / "baseline_odds_water_version.schema.json",
        BaselineOddsWaterVersion.model_json_schema(),
    )
    summary = {
        "ok": True,
        "output": str(output),
        "domain_object_count": len(domain_schema_catalog()["objects"]),
        "handoff_variant_count": 16,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
