from pathlib import Path

from xinao_seedlab.application.seed_cortex import build_default_service


def test_artifact_acceptance_queue_claimcard_hard_gate_and_source_ledger(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    service = build_default_service(runtime, repo_root=repo)

    payload = service.artifact_acceptance_queue(
        "claimcard-hard-gate-test",
        [
            {
                "object_type": "ClaimCard",
                "candidate_id": "valid-claim",
                "source_url": "https://example.test/source",
                "source_family": "external_research",
                "claim": "External finding must enter SourceLedger before promotion.",
                "verification_need": "Cross-check citation and fan-in result.",
                "accepted_for": "next_frontier_evidence",
                "artifact_ref": "claimcards/valid-claim.json",
            },
            {
                "object_type": "ClaimCard",
                "candidate_id": "invalid-claim",
                "claim": "Missing source metadata must not be accepted.",
            },
        ],
        write_runtime=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["claim_card_hard_gate_enforced"] is True
    assert payload["claim_card_requires_source_ledger"] is True
    assert payload["accepted_artifact_count"] == 1
    assert payload["rejected_artifact_count"] == 1
    decisions = {decision["candidate_id"]: decision for decision in payload["decisions"]}
    assert decisions["valid-claim"]["status"] == "accepted"
    assert decisions["valid-claim"]["source_ledger_entry_id"]
    assert decisions["invalid-claim"]["status"] == "rejected"
    assert decisions["invalid-claim"]["artifact_acceptance_decision"] == (
        "rejected_missing_claim_card_fields"
    )
    assert set(decisions["invalid-claim"]["missing_fields"]) >= {
        "source_url",
        "source_family",
        "verification_need",
        "accepted_for",
    }

    ledger_path = Path(payload["source_ledger_ref"])
    assert ledger_path.is_file()
    ledger = service.global_source_ledger(
        task_id="manual-readback",
        episode_id="manual-readback",
        source_entries=[],
        write_runtime=False,
    )
    assert ledger["validation"]["passed"] is False

    import json

    source_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert source_ledger["schema_version"] == "xinao.seedcortex.source_ledger.v1"
    assert source_ledger["global_ledger"] is True
    assert source_ledger["private_ledger"] is False
    assert source_ledger["entry_count"] == 1
    assert source_ledger["entries"][0]["candidate_id"] == "valid-claim"
    assert source_ledger["entries"][0]["direct_fact_promotion_allowed"] is False
    assert source_ledger["entries"][0]["completion_claim_allowed"] is False
