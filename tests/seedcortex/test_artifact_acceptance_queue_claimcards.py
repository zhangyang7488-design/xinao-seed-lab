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
    assert decisions["valid-claim"]["artifact_acceptance_decision"] == "accepted_for_next_frontier"
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


def test_artifact_acceptance_queue_counts_unique_artifacts(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    artifact = runtime / "merge_artifacts" / "same.merged.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("same artifact\n", encoding="utf-8")
    service = build_default_service(runtime, repo_root=repo)

    payload = service.artifact_acceptance_queue(
        "aaq-dedupe-test",
        [
            {
                "candidate_id": "candidate-a",
                "artifact_ref": str(artifact),
                "artifact_kind": "merge_review",
                "workflow_id": "workflow-1",
                "workflow_run_id": "run-1",
                "accepted_for": "next_frontier_evidence",
            },
            {
                "candidate_id": "candidate-b",
                "artifact_ref": str(artifact),
                "artifact_kind": "merge_review",
                "workflow_id": "workflow-1",
                "workflow_run_id": "run-1",
                "accepted_for": "next_frontier_evidence",
            },
        ],
        write_runtime=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["accepted_candidate_count"] == 2
    assert payload["accepted_artifact_count"] == 1
    assert payload["unique_accepted_artifact_count"] == 1
    assert payload["duplicate_accepted_candidate_count"] == 1
    assert len(payload["unique_accepted_artifacts"]) == 1
    decisions = {decision["candidate_id"]: decision for decision in payload["decisions"]}
    assert decisions["candidate-a"]["counts_as_unique_acceptance"] is True
    assert decisions["candidate-b"]["counts_as_unique_acceptance"] is False
    assert decisions["candidate-b"]["artifact_acceptance_decision"] == (
        "accepted_duplicate_artifact_ref_not_counted"
    )


def test_artifact_acceptance_queue_preserves_binding_and_delivery_decisions(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    binding_artifact = runtime / "provider_lane_index" / "latest.json"
    delivery_artifact = runtime / "deliverables" / "ready.json"
    binding_artifact.parent.mkdir(parents=True)
    delivery_artifact.parent.mkdir(parents=True)
    binding_artifact.write_text('{"status":"provider_lane_index_ready"}\n', encoding="utf-8")
    delivery_artifact.write_text('{"status":"delivery_ready"}\n', encoding="utf-8")
    service = build_default_service(runtime, repo_root=repo)

    payload = service.artifact_acceptance_queue(
        "aaq-binding-delivery-test",
        [
            {
                "candidate_id": "provider-lane-index",
                "artifact_ref": str(binding_artifact),
                "artifact_kind": "provider_lane_index",
                "workflow_id": "workflow-binding",
                "workflow_run_id": "run-binding",
                "accepted_for": "accepted_for_binding",
            },
            {
                "candidate_id": "usable-deliverable",
                "artifact_ref": str(delivery_artifact),
                "artifact_kind": "deliverable",
                "workflow_id": "workflow-delivery",
                "workflow_run_id": "run-delivery",
                "accepted_for": "accepted_for_delivery",
            },
        ],
        write_runtime=True,
    )

    decisions = {decision["candidate_id"]: decision for decision in payload["decisions"]}
    assert payload["validation"]["passed"] is True
    assert payload["accepted_for_next_frontier_only"] is False
    assert payload["accepted_for_binding_count"] == 1
    assert payload["accepted_for_delivery_count"] == 1
    assert payload["accepted_for_next_frontier_count"] == 0
    assert payload["validation"]["checks"]["binding_and_delivery_not_forced_to_frontier"] is True
    assert (
        decisions["provider-lane-index"]["artifact_acceptance_decision"] == "accepted_for_binding"
    )
    assert decisions["provider-lane-index"]["workflow_run_id"] == "run-binding"
    assert (
        decisions["usable-deliverable"]["artifact_acceptance_decision"] == "accepted_for_delivery"
    )
    assert decisions["usable-deliverable"]["workflow_run_id"] == "run-delivery"
