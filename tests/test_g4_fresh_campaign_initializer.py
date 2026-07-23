from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from xinao.capability.g4_hidden_benchmark.constants import FAMILY_IDS

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "initialize_g4_fresh_campaign.py"


def _load_initializer():
    spec = importlib.util.spec_from_file_location("g4_fresh_campaign_initializer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _campaign() -> dict:
    designs = []
    for index, family in enumerate(FAMILY_IDS):
        n = 122 if family == "H10" else 32 if index < 7 or index >= 12 else 19
        p0 = 0.85 if family == "H10" else 0.5
        p1 = 0.95 if family == "H10" else 0.8
        designs.append(
            {
                "family_id": family,
                "n": n,
                "p0": p0,
                "p1": p1,
                "attained_power": 0.82,
            }
        )
    return {
        "schema_version": "xinao.g4.v7.preregistration_freeze_candidate.v1",
        "content_hash": "a" * 64,
        "frozen_for_owner_decision": True,
        "no_peek_contract": {
            "sealed_before_real_evaluation": True,
            "attestation": "NO_REAL_H01_H14_OUTCOME_BYTES_ACCESSED",
        },
        "fixed_n_stopping": {
            "n_locked_before_results": True,
            "optional_raise_n_after_peek": False,
        },
        "seed_reducer": {
            "unit_of_analysis": "independent_heldout_case",
            "seed_role": "within_unit_replication_not_independent_n",
        },
        "h01_h14_sample_design": designs,
    }


def _accepted_campaign(tmp_path: Path) -> tuple[dict, dict, Path]:
    initializer = _load_initializer()
    campaign = _campaign()
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    acceptance = {
        "schema_version": "xinao.g4.v7.owner_content_acceptance.v1",
        "decision": "ACCEPT_SELECTION_AND_PREREGISTRATION_CONTENT__HOLD_CAPACITY",
        "lifecycle": {"owner_adopted": True},
        "subject": {
            "preregistration_file_sha256": initializer._raw_sha256(campaign_path),
            "preregistration_content_hash": campaign["content_hash"],
        },
    }
    return campaign, acceptance, campaign_path


def test_accepted_design_materializes_full_campaign_ledger_before_first_batch(
    tmp_path: Path,
) -> None:
    initializer = _load_initializer()
    campaign, acceptance, campaign_path = _accepted_campaign(tmp_path)
    designs = initializer._validated_designs(
        campaign,
        acceptance,
        campaign_path=campaign_path,
    )
    records_by_family = {
        family: [
            {"public_case_id": f"pc_{family.lower()}_{index:03d}"}
            for index in range(designs[family]["n"])
        ]
        for family in FAMILY_IDS
    }

    cells = initializer._all_campaign_cells(
        records_by_family=records_by_family,
        seed_ids=[17, 42, 99],
    )
    _ledger, disclosure = initializer._register_campaign_cells(
        campaign_id="campaign-1",
        cells=cells,
    )
    first_batch = initializer._first_batch_cells(
        records_by_family=records_by_family,
        families=["H01"],
        configurations=["C0-ALGO"],
        seed_ids=[17, 42, 99],
        cases_per_family=1,
    )

    assert len(cells) == 10_206
    assert disclosure["total_trials"] == 10_206
    registered_ids = {work_key.rsplit(":", 1)[-1] for work_key in disclosure["work_keys"]}
    assert len(first_batch) == 3
    assert all(initializer._stable_cell_id(cell) in registered_ids for cell in first_batch)


def test_seed_repetition_cannot_be_reclassified_as_independent_n(tmp_path: Path) -> None:
    initializer = _load_initializer()
    campaign, acceptance, campaign_path = _accepted_campaign(tmp_path)
    campaign["seed_reducer"]["seed_role"] = "independent_n"

    with pytest.raises(initializer.FreshCampaignError, match="seed role"):
        initializer._validated_designs(
            campaign,
            acceptance,
            campaign_path=campaign_path,
        )


def test_accepted_source_is_copied_byte_exact_for_portable_binding(
    tmp_path: Path,
) -> None:
    initializer = _load_initializer()
    source = tmp_path / "source.json"
    target = tmp_path / "package" / "source.json"
    source.write_bytes(b'{\r\n  "accepted": true\r\n}\r\n')

    initializer._copy_exact_source(source, target)

    assert target.read_bytes() == source.read_bytes()
    assert initializer._raw_sha256(target) == initializer._raw_sha256(source)


def test_subject_public_cases_are_safe_sorted_and_family_blind(tmp_path: Path) -> None:
    initializer = _load_initializer()
    records = [
        {
            "family_id": "H01",
            "public_case_id": "case-z",
            "public_instructions": "Use only the supplied public values.",
            "task_input": {"table": [[1, 2], [2, 3]], "labels": ["a", "b"]},
            "commitment_sha256": "a" * 64,
        },
        {
            "family_id": "H02",
            "public_case_id": "case-a",
            "public_instructions": "Use only the supplied public values.",
            "task_input": {"sequence": [1, 2, 3]},
            "commitment_sha256": "b" * 64,
        },
    ]
    output_path = tmp_path / "subject" / "public_cases.v1.jsonl"

    receipt = initializer._materialize_public_cases(records, output_path)

    rows = [
        json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line
    ]
    prompts = [json.loads(row["public_prompt"]) for row in rows]
    assert [row["public_case_id"] for row in rows] == ["case-a", "case-z"]
    assert all(set(row) == {"public_case_id", "public_prompt", "commitment_sha256"} for row in rows)
    assert all(
        set(prompt)
        == {
            "public_case_id",
            "public_instructions",
            "task_input",
            "commitment_sha256",
        }
        for prompt in prompts
    )
    serialized = output_path.read_text(encoding="utf-8")
    assert "family_id" not in serialized
    assert "truth" not in serialized
    assert "hidden_parameters" not in serialized
    assert receipt["case_count"] == 2
    assert receipt["family_labels_exposed"] is False
    assert receipt["outcome_accessed"] is False
    assert receipt["sha256"] == initializer._raw_sha256(output_path)
