from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPOSITIONS = ROOT / "cold_evidence" / "dispositions"


def test_every_disposition_index_row_resolves_to_cold_non_authority_record() -> None:
    index = json.loads((DISPOSITIONS / "index.v1.json").read_text(encoding="utf-8"))
    assert index["runtime_loaded"] is False

    for row in index["records"]:
        record = json.loads((DISPOSITIONS / row["path"]).read_text(encoding="utf-8"))
        assert record["record_id"] == row["record_id"]
        assert record["disposition"] == row["disposition"]
        assert record["runtime_loaded"] is False
        assert record["authority"] is False
        assert record["completion_claim_allowed"] is False
        assert record["backup_presence_is_restore_proof"] is False
        assert record["recovery"]["source"]
        assert record["do_not_load_into"]


def test_removed_task_run_binding_record_preserves_exact_identity_and_recovery() -> None:
    record = json.loads(
        (
            DISPOSITIONS
            / "records"
            / "remove-transaction-added-task-run-binding-20260811.json"
        ).read_text(encoding="utf-8")
    )

    assert record["before_expected_state"] == "ABSENT"
    assert {item["sha256"] for item in record["removed_objects"]} == {
        "3103cf895ab94701c55af4bbc94a7b029e3ac65ffc4decf63f91c10b20564ae9",
        "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9",
    }
    assert record["removal_receipt"]["both_objects_absent_after"] is True
    assert record["recovery"]["preimage_bytes_required"] is False
