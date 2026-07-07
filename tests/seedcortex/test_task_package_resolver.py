import json
from pathlib import Path

from services.agent_runtime import task_package_resolver as resolver


def test_manifest_resources_are_current_package_and_exclude_reference_only(tmp_path: Path) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    (root / "current.txt").write_text("current\n", encoding="utf-8")
    (root / "plan.txt").write_text("plan\n", encoding="utf-8")
    (root / "old.txt").write_text("old\n", encoding="utf-8")
    (root / "TASK_PACKAGE.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.task_package_manifest.v1",
                "package_mode": "unit_current",
                "entrypoint": "current.txt",
                "execution_defaults": {
                    "north_star": "user_x_to_deliverable_y",
                    "task_shape": "one_deliverable_one_binding_one_verifier",
                    "default_acceptance_decisions": [
                        "accepted_for_binding",
                        "accepted_for_delivery",
                    ],
                    "exception_acceptance_decision": "accepted_for_next_frontier",
                    "next_frontier_default_outlet": False,
                    "forbid_background_self_proof_without_deliverable": True,
                    "bounded_retry": {
                        "policy_id": "bounded_delivery_retry",
                        "scope": "same_deliverable_only",
                        "max_attempts": 3,
                        "max_recursive_repairs": 2,
                        "next_frontier_on_failure": False,
                        "failure_terminal_state": "named_blocker",
                    },
                },
                "mature_bind_queue": [
                    {
                        "task_id": "p0_004a_provider_lane_index",
                        "status": "ready",
                        "deliverable": "provider lane index",
                        "replace_target": "opaque direct model calls",
                        "mature_carrier": "LiteLLM Router",
                        "thin_adapter": "ProviderScheduler policy wrapper",
                        "default_mainline_binding": "TaskContractRouter -> ProviderScheduler",
                        "runtime_evidence": ["runtime/latest.json"],
                        "verification": ["pytest tests/seedcortex/test_task_contract_router.py"],
                        "acceptance": {
                            "success_decision": "accepted_for_binding",
                            "success_field": "provider_lane_index_ready",
                        },
                        "fallback_or_blocker": "PROVIDER_LANE_INDEX_NOT_BOUND",
                    }
                ],
                "resources": [
                    {"path": "current.txt", "role": "entrypoint"},
                    {"path": "plan.txt", "role": "plan"},
                    {"path": "old.txt", "read": "reference_only"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = resolver.resolve_task_package(root, include_manifest_ref=False)

    assert package["package_mode"] == "unit_current"
    assert package["resolution"] == "task_package_manifest"
    assert package["manifest_driven"] is True
    assert package["legacy_fallback"] is False
    assert [Path(ref["path"]).name for ref in package["refs"]] == ["current.txt", "plan.txt"]
    assert "old.txt" not in package["required_files"]
    assert package["all_required_sources_read_full"] is True
    assert package["delivery_first_defaults_ready"] is True
    assert package["mature_bind_queue_ready"] is True
    assert package["next_mature_bind_task_id"] == "p0_004a_provider_lane_index"
    assert package["next_mature_bind_task"]["success_decision"] == "accepted_for_binding"


def test_runtime_acceptance_overlay_dequeues_accepted_mature_bind_task(tmp_path: Path) -> None:
    root = tmp_path / "新系统"
    runtime = tmp_path / "runtime"
    root.mkdir()
    (root / "current.txt").write_text("current\n", encoding="utf-8")
    (root / "TASK_PACKAGE.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.task_package_manifest.v1",
                "package_mode": "unit_current",
                "entrypoint": "current.txt",
                "mature_bind_queue": [
                    {
                        "task_id": "p0_004a_provider_lane_index",
                        "status": "ready",
                        "deliverable": "provider lane index",
                        "verification": ["pytest"],
                        "acceptance": {
                            "success_decision": "accepted_for_binding",
                            "success_field": "provider_lane_index_ready",
                        },
                    },
                    {
                        "task_id": "p0_005_mature_binding_gap_ledger",
                        "status": "ready",
                        "deliverable": "gap ledger",
                        "verification": ["pytest"],
                        "acceptance": {
                            "success_decision": "accepted_for_delivery",
                            "success_field": "mature_binding_gap_ledger_ready",
                        },
                    },
                ],
                "resources": [{"path": "current.txt", "role": "entrypoint"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    aaq = runtime / "runs" / "episodes" / "p0-004a" / "artifact_acceptance.json"
    aaq.parent.mkdir(parents=True)
    aaq.write_text(
        json.dumps(
            {
                "decisions": [
                    {
                        "candidate_id": "p0_004a_provider_lane_index",
                        "status": "accepted",
                        "artifact_acceptance_decision": "accepted_for_binding",
                        "artifact_ref": "provider_lane_index/latest.json",
                        "workflow_id": "workflow",
                        "workflow_run_id": "run",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    package = resolver.resolve_task_package(
        root,
        include_manifest_ref=False,
        runtime_root=runtime,
    )

    first, second = package["mature_bind_queue"]
    assert first["status"] == "accepted_for_binding"
    assert first["runtime_acceptance_overlay"]["source"] == "artifact_acceptance_queue"
    assert second["status"] == "ready"
    assert package["next_mature_bind_task_id"] == "p0_005_mature_binding_gap_ledger"
    assert package["runtime_accepted_task_ids"] == ["p0_004a_provider_lane_index"]


def test_explicit_entry_path_is_single_file_package_without_code_name_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    entry = tmp_path / "new_task.txt"
    entry.write_text("new task\n", encoding="utf-8")

    package = resolver.resolve_task_package(root, entry_path=entry)

    assert package["resolution"] == "explicit_task_entry_path"
    assert package["single_entry_driven"] is True
    assert package["legacy_fallback"] is False
    assert package["required_files"] == ["new_task.txt"]
    assert package["refs"][0]["path"] == str(entry)


def test_legacy_authority_is_only_fallback_when_no_current_anchor(tmp_path: Path) -> None:
    root = tmp_path / "新系统"
    root.mkdir()
    (root / "AUTHORITY_READ_ORDER.txt").write_text("legacy\n", encoding="utf-8")

    package = resolver.resolve_task_package(root)

    assert package["resolution"] == "legacy_authority_fallback"
    assert package["legacy_fallback"] is True
    assert package["manifest_driven"] is False
