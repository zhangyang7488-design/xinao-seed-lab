"""Register the completed P3/P4/P5 vertical into the live formal event ledger."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import DEFAULT_CATALOG_PATH, write_atomic
from xinao.contracts.objects import AuthorityContract, BaselineOddsWaterVersion, DatasetSnapshot
from xinao.ledger import append_event, create_event
from xinao.settlement import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "domain"
WORLD_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\world"
    r"\special-number-settlement.v1"
)
VALIDATION_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-mainline-20260714T014700\p5_validation_court"
)
CORRELATION_ID = "0190f9c0-6f4c-7c00-8b22-334455667788"
TRACE_ID = "0190f9c0-6f4c-7e00-8b22-334455667788"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--world-root", type=Path, default=WORLD_ROOT)
    parser.add_argument("--validation-root", type=Path, default=VALIDATION_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def sealed_fixture(name: str, model_type: type) -> dict[str, Any]:
    model = model_type.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))
    return model.with_content_hash().model_dump(mode="json")


def objects(
    *, catalog_path: Path, world_root: Path, validation_root: Path
) -> list[tuple[str, str, str, str, dict[str, Any]]]:
    authority = sealed_fixture("authority_contract.json", AuthorityContract)
    dataset = sealed_fixture("dataset_snapshot.json", DatasetSnapshot)
    baseline = sealed_fixture("baseline_odds_water_version.json", BaselineOddsWaterVersion)
    catalog = read_json(catalog_path)
    matrix = read_json(world_root / "event_matrix_snapshot.json")
    world = read_json(world_root / "world_snapshot.json")
    split = read_json(validation_root / "dataset_split_version.json")
    protocol = read_json(validation_root / "validation_protocol_version.json")
    validation = read_json(validation_root / "candidate_validation_report.json")
    rule = {
        "rule": SPECIAL_NUMBER_RULE.model_dump(mode="json"),
        "settlement_function": SPECIAL_NUMBER_FUNCTION.model_dump(mode="json"),
    }
    rule["content_hash"] = canonical_sha256(rule)
    candidate = {
        "candidate_ref": validation["candidate_ref"],
        "semantic_config": {"panel": "B", "selected_number": 1, "stake": "1.0000"},
        "validation_output_hash": validation["output_hash"],
        "status": "REJECTED_NO_ACTION",
    }
    candidate["content_hash"] = canonical_sha256(candidate)
    return [
        (
            "AuthorityContract",
            authority["contract_ref"],
            "AuthorityContractActivated",
            authority["idempotency_key"],
            authority,
        ),
        (
            "DatasetSnapshot",
            dataset["dataset_ref"],
            "DatasetPromoted",
            dataset["idempotency_key"],
            dataset,
        ),
        (
            "BaselineOddsWaterVersion",
            baseline["baseline_ref"],
            "BaselineOddsWaterActivated",
            baseline["idempotency_key"],
            baseline,
        ),
        (
            "PlayCatalog",
            catalog["catalog_ref"],
            "PlayCatalogActivated",
            "play-catalog-v1",
            catalog,
        ),
        (
            "RuleVersion",
            SPECIAL_NUMBER_RULE.rule_ref,
            "RuleVersionActivated",
            "special-number-rule-v1",
            rule,
        ),
        (
            "EventMatrixSnapshot",
            matrix["snapshot_ref"],
            "EventMatrixCompiled",
            "event-matrix-special-number-v1",
            matrix,
        ),
        (
            "WorldSnapshot",
            world["world_ref"],
            "WorldSnapshotCompiled",
            "world-special-number-v1",
            world,
        ),
        (
            "DatasetSplitVersion",
            split["split_ref"],
            "DatasetPromoted",
            "dataset-split-verified-913-v1",
            split,
        ),
        (
            "ValidationProtocolVersion",
            protocol["protocol_ref"],
            "ExperimentStarted",
            "validation-protocol-special-number-v1",
            protocol,
        ),
        (
            "CandidateVersion",
            candidate["candidate_ref"],
            "CandidateCreated",
            "candidate-constant-01-panel-b-v0",
            candidate,
        ),
        (
            "ValidationReport",
            validation["report_ref"],
            "ValidationFailed",
            "validation-report-constant-01-panel-b-v0",
            validation,
        ),
    ]


def event_id(index: int, family: str) -> str:
    return f"0190f9c0-6f4c-7{family}{index:02x}-8b22-334455667788"


def main() -> int:
    args = parse_args()
    registrations = objects(
        catalog_path=args.catalog,
        world_root=args.world_root,
        validation_root=args.validation_root,
    )
    events = []
    for index, (aggregate_type, aggregate_id, event_type, idempotency_key, payload) in enumerate(
        registrations, start=1
    ):
        events.append(
            create_event(
                event_id=event_id(index, "f"),
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=1,
                occurred_at=datetime(2026, 7, 14, 4, 5, 0, index * 1000, tzinfo=UTC),
                correlation_id=CORRELATION_ID,
                causation_id=None,
                actor="Codex-single-writer",
                command_id=event_id(index, "d"),
                idempotency_key=idempotency_key,
                payload_schema_version=f"{aggregate_type}.v1",
                payload=payload,
                prior_event_hash=None,
                trace_id=TRACE_ID,
                workflow_id="xinao-mainline-registration-p3-p5",
                run_id="xinao-mainline-20260714T014700",
            )
        )
    with psycopg.connect(
        host=os.environ.get("XINAO_DB_HOST", "shiwu-ku"),
        port=os.environ.get("XINAO_DB_PORT", "5432"),
        dbname=args.database,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    ) as connection:
        before = connection.execute(
            "SELECT count(*) FROM domain_event WHERE correlation_id=%s", (CORRELATION_ID,)
        ).fetchone()[0]
        connection.execute("SET ROLE xinao_discovery_event_writer")
        first_ids = [
            append_event(connection, event, outbox_id=event_id(index, "e"))
            for index, event in enumerate(events, start=1)
        ]
        replay_ids = [
            append_event(connection, event, outbox_id=event_id(index, "e"))
            for index, event in enumerate(events, start=1)
        ]
        connection.execute("RESET ROLE")
        after = connection.execute(
            "SELECT count(*) FROM domain_event WHERE correlation_id=%s", (CORRELATION_ID,)
        ).fetchone()[0]
        outbox = connection.execute(
            "SELECT count(*) FROM transactional_outbox o JOIN domain_event e "
            "ON e.event_id=o.event_id WHERE e.correlation_id=%s",
            (CORRELATION_ID,),
        ).fetchone()[0]
    if first_ids != replay_ids or after - before != len(events) or outbox != len(events):
        raise AssertionError("formal registration transaction or idempotent replay failed")
    report = {
        "schema_version": "xinao.formal_vertical_registration.v1",
        "database": args.database,
        "correlation_id": CORRELATION_ID,
        "registered_count": len(events),
        "idempotent_replay_count_delta": 0,
        "outbox_count": outbox,
        "event_ids": first_ids,
        "event_hashes": [event.event_hash for event in events],
        "aggregate_types": [event.aggregate_type for event in events],
        "status": "verified",
    }
    write_atomic(args.out, report)
    print(json.dumps({"status": "verified", "output": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
