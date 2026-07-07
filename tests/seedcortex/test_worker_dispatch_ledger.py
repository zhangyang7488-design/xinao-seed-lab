import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "worker_dispatch_ledger.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_worker_dispatch_ledger.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("worker_dispatch_ledger", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_locks_worker_dispatch_ledger_boundary() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    entry = schema["$defs"]["DispatchEntry"]
    required = set(entry["required"])

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.worker_dispatch_ledger.v1"
    )
    assert schema["properties"]["work_id"]["const"] == "xinao_seed_cortex_phase0_20260701"
    assert schema["properties"]["adoption_state"]["$ref"] == "#/$defs/AdoptionState"
    assert "runtime_entrypoint_invocation" in schema["required"]
    assert "hot_path_binding" in schema["required"]
    assert "poll_entries" in schema["required"]
    assert "succeeded_count" in schema["required"]
    assert schema["properties"]["runtime_entrypoint_invocation"]["$ref"] == (
        "#/$defs/RuntimeEntrypointInvocation"
    )
    assert set(schema["$defs"]["AdoptionState"]["enum"]) == {
        "verifier_ready_but_not_hooked",
        "runtime_enforced_hot_path_hooked",
    }
    assert schema["$defs"]["AuthorityBoundary"]["properties"]["is_controller"]["const"] is False
    assert schema["$defs"]["AuthorityBoundary"]["properties"]["is_completion_gate"]["const"] is False
    assert schema["$defs"]["AuthorityBoundary"]["properties"]["is_source_of_truth"]["const"] is False
    assert schema["$defs"]["Legacy5d33Boundary"]["properties"]["transport_pattern_reuse_allowed"]["const"] is True
    assert schema["$defs"]["Legacy5d33Boundary"]["properties"]["owner_reuse_allowed"]["const"] is False
    assert schema["$defs"]["Legacy5d33Boundary"]["properties"]["pass_reuse_allowed"]["const"] is False
    assert schema["$defs"]["Legacy5d33Boundary"]["properties"]["latest_authority_reuse_allowed"]["const"] is False
    assert {
        "wave_id",
        "task_id",
        "lane_id",
        "agent_id",
        "provider",
        "mode",
        "dispatch_time",
        "poll_status",
        "artifact_refs",
        "fan_in_decision",
        "next_wave_decision",
        "adoption_state",
    }.issubset(required)
    assert set(schema["$defs"]["Mode"]["enum"]) == {
        "worker",
        "worker_poll",
        "subagent",
        "dp_sidecar_execution",
        "dp_search",
    }
    assert "worker_dispatch_ledger_poll_ready" in schema["properties"]["status"]["enum"]
    assert (
        "ledger_succeeded_drives_default_auto_dispatch"
        in schema["$defs"]["NextWaveDecision"]["enum"]
    )
    assert (
        "accepted_for_next_wave_dispatch"
        in schema["$defs"]["FanInDecision"]["enum"]
    )
    assert schema["$defs"]["Summary"]["properties"]["hooked_runtime_entrypoint_count"][
        "minimum"
    ] == 0
    assert schema["$defs"]["RuntimeEntrypointInvocation"]["properties"][
        "not_execution_controller"
    ]["const"] is True
    assert schema["$defs"]["RuntimeEntrypointInvocation"]["properties"][
        "not_completion_gate"
    ]["const"] is True


def test_worker_dispatch_ledger_writes_latest_and_readback(tmp_path: Path) -> None:
    module = _load_module()
    runtime_root = tmp_path / "runtime"

    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        write=True,
    )

    latest = runtime_root / "state" / "worker_dispatch_ledger" / "latest.json"
    readback = runtime_root / "readback" / "zh" / "worker_dispatch_ledger_20260702.md"

    assert payload["schema_version"] == "xinao.codex_s.worker_dispatch_ledger.v1"
    assert payload["validation"]["passed"] is True
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"
    assert payload["authority_boundary"]["is_controller"] is False
    assert payload["authority_boundary"]["is_completion_gate"] is False
    assert payload["authority_boundary"]["is_source_of_truth"] is False
    assert payload["legacy_5d33_boundary"]["transport_pattern_reuse_allowed"] is True
    assert payload["legacy_5d33_boundary"]["owner_reuse_allowed"] is False
    assert payload["legacy_5d33_boundary"]["pass_reuse_allowed"] is False
    assert payload["legacy_5d33_boundary"]["latest_authority_reuse_allowed"] is False
    assert payload["summary"]["spawned_external_agent_count"] == 0
    assert payload["summary"]["hooked_runtime_entrypoint_count"] == 0
    assert payload["runtime_entrypoint_invocation"]["invoked"] is False
    assert payload["runtime_entrypoint_invocation"]["runtime_enforced"] is False
    assert payload["runtime_entrypoint_invocation"]["not_execution_controller"] is True
    assert payload["runtime_entrypoint_invocation"]["not_completion_gate"] is True
    assert payload["hot_path_binding"]["runtime_enforced"] is False
    assert payload["source_kind"] == "dispatch_read_model"
    assert payload["poll_entries"] == []
    assert payload["succeeded_count"] == 0
    assert payload["machine_loop"]["auto_dispatch_performed"] is False
    assert latest.is_file()
    assert readback.is_file()

    latest_payload = json.loads(latest.read_text(encoding="utf-8"))
    assert latest_payload["work_id"] == "xinao_seed_cortex_phase0_20260701"
    assert latest_payload["output_paths"]["runtime_latest"] == str(latest)
    assert latest_payload["output_paths"]["runtime_readback_zh"] == str(readback)
    assert "能力采纳状态：verifier_ready_but_not_hooked" in readback.read_text(
        encoding="utf-8"
    )


def test_worker_dispatch_entries_cover_worker_subagent_and_dp_without_old_authority(
    tmp_path: Path,
) -> None:
    module = _load_module()
    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=tmp_path / "runtime",
        codex_subagents=[
            "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger",
            "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe",
        ],
        write=False,
    )

    entries = payload["dispatch_entries"]
    modes = {entry["mode"] for entry in entries}
    assert {"worker", "subagent", "dp_sidecar_execution", "dp_search"}.issubset(modes)
    subagent_ids = {entry["agent_id"] for entry in entries if entry["mode"] == "subagent"}
    assert "019f22a3-13b1-73d3-8f81-1b36cc635c23" in subagent_ids
    assert "019f22a3-141d-7311-bf78-69a37f9db88e" in subagent_ids

    for entry in entries:
        for field in module.REQUIRED_ENTRY_FIELDS:
            assert field in entry
        assert entry["adoption_state"] == "verifier_ready_but_not_hooked"
        assert entry["legacy_5d33_transport_pattern_reused"] is True
        assert entry["legacy_5d33_owner_reused"] is False
        assert entry["legacy_5d33_pass_reused"] is False
        assert entry["legacy_5d33_latest_authority_reused"] is False
        assert entry["completion_claim_allowed"] is False
        assert entry["not_source_of_truth"] is True
        assert entry["not_execution_controller"] is True
        assert "durable_parallel_wave_packet" not in "\n".join(entry["artifact_refs"])

    assert payload["validation"]["checks"]["durable_parallel_wave_packet_not_referenced"] is True
    assert payload["validation"]["checks"]["legacy_5d33_transport_only"] is True
    assert payload["validation"]["checks"]["runtime_entrypoint_count_matches_invocation"] is True


def test_temporal_worker_activity_entry_records_actual_runtime_invocation(
    tmp_path: Path,
) -> None:
    module = _load_module()
    worker_result = {
        "status": "activity_gate_checked",
        "worker_task_id": "worker-xinao-seed-cortex-phase0-20260702",
        "jsonl_path": str(tmp_path / "worker.jsonl"),
        "final_path": str(tmp_path / "final.md"),
        "raw_final_path": str(tmp_path / "raw_final.md"),
        "actual_provider_id": "local_ollama_qwen25_coder",
        "actual_provider_family": "local_ollama",
        "actual_carrier_provider_id": "local_ollama_qwen",
        "provider_router_active": True,
        "provider_route_reason": "dynamic_router_local_qwen25_coder_code_draft",
        "execute_worker_turn": True,
    }
    entry = module.temporal_worker_activity_entry(
        wave_id="temporal-wave-20260702",
        task_id="xinao_seed_cortex_phase0_20260701",
        worker_result=worker_result,
        dispatch_time="2026-07-02T00:00:00+08:00",
    )
    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=tmp_path / "runtime",
        wave_id="temporal-wave-20260702",
        extra_entries=[entry],
        runtime_entrypoint_invocation={
            "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_write",
            "runtime_enforced": True,
        },
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        write=False,
    )

    temporal_entries = [
        item
        for item in payload["dispatch_entries"]
        if item["provider"] == "temporal.codex_worker_turn_activity"
    ]
    assert len(temporal_entries) == 1
    temporal_entry = temporal_entries[0]
    assert temporal_entry["agent_id"] == "worker-xinao-seed-cortex-phase0-20260702"
    assert temporal_entry["poll_status"] == "succeeded"
    assert temporal_entry["worker_status"] == "activity_gate_checked"
    assert temporal_entry["provider"] == "temporal.codex_worker_turn_activity"
    assert temporal_entry["actual_provider_id"] == "local_ollama_qwen25_coder"
    assert temporal_entry["actual_provider_family"] == "local_ollama"
    assert temporal_entry["actual_carrier_provider_id"] == "local_ollama_qwen"
    assert temporal_entry["provider_router_active"] is True
    assert temporal_entry["execute_worker_turn"] is True
    assert temporal_entry["jsonl_exists"] is None
    assert temporal_entry["fan_in_decision"] == "accepted_for_ledger_evidence_only"
    assert temporal_entry["transport_pattern_ref"] == (
        "temporal_codex_task_workflow_task_scoped_worker_result"
    )
    assert temporal_entry["legacy_5d33_owner_reused"] is False
    assert temporal_entry["legacy_5d33_pass_reused"] is False
    assert temporal_entry["legacy_5d33_latest_authority_reused"] is False
    assert payload["runtime_entrypoint_invocation"]["invoked"] is True
    assert payload["runtime_entrypoint_invocation"]["runtime_enforced"] is True
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"
    assert payload["hot_path_binding"]["runtime_enforced"] is False
    assert payload["source_kind"] == "worker_dispatch_ledger_poll"
    assert payload["poll_source"] == "worker_dispatch_ledger_poll"
    assert payload["succeeded_count"] == 1
    assert payload["poll_entries"][0]["fan_in_decision"] == "accepted_for_next_wave_dispatch"
    assert payload["machine_loop"]["next_wave"] == "ledger_succeeded_drives_default_auto_dispatch"
    assert payload["runtime_entrypoint_invocation"]["not_execution_controller"] is True
    assert payload["runtime_entrypoint_invocation"]["not_completion_gate"] is True
    assert payload["summary"]["hooked_runtime_entrypoint_count"] == 1
    assert payload["validation"]["passed"] is True


def test_temporal_worker_activity_entry_keeps_blocker_diagnostics(tmp_path: Path) -> None:
    module = _load_module()
    worker_result = {
        "status": "activity_blocked",
        "worker_task_id": "seed-cortex-worker-blocked",
        "named_blocker": "CODEX_ACTIVATOR_UNKNOWN_TARGET",
        "expected_marker": "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK",
        "expected_marker_seen": False,
        "activator_ok": False,
        "jsonl_exists": False,
    }

    entry = module.temporal_worker_activity_entry(
        wave_id="temporal-wave-blocked",
        task_id="xinao_seed_cortex_phase0_20260701",
        worker_result=worker_result,
        dispatch_time="2026-07-04T00:00:00+08:00",
    )

    assert entry["poll_status"] == "blocked"
    assert entry["worker_named_blocker"] == "CODEX_ACTIVATOR_UNKNOWN_TARGET"
    assert entry["expected_marker"] == "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK"
    assert entry["expected_marker_seen"] is False
    assert entry["activator_ok"] is False
    assert entry["jsonl_exists"] is False


def _write_current_worker_brief_queue(runtime_root: Path) -> list[dict[str, str]]:
    briefs = [
        {
            "worker_brief_id": "current-p0-three-text:brief:01",
            "source_package_id": "current_p0_three_text_20260707",
            "source_ledger_entry_id": "source-entry-01",
            "source_ref": str(runtime_root / "sources" / "01.txt"),
            "source_sha256": "sha-01",
            "source_role": "project_boundary",
            "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
        },
        {
            "worker_brief_id": "current-p0-three-text:brief:02",
            "source_package_id": "current_p0_three_text_20260707",
            "source_ledger_entry_id": "source-entry-02",
            "source_ref": str(runtime_root / "sources" / "02.txt"),
            "source_sha256": "sha-02",
            "source_role": "p0_execution_entrypoint",
            "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_v4_pro"],
        },
        {
            "worker_brief_id": "current-p0-three-text:brief:03",
            "source_package_id": "current_p0_three_text_20260707",
            "source_ledger_entry_id": "source-entry-03",
            "source_ref": str(runtime_root / "sources" / "03.txt"),
            "source_sha256": "sha-03",
            "source_role": "p1_gate_context",
            "provider_candidates": ["qwen_prepaid_cheap_worker", "deepseek_dp"],
        },
    ]
    queue = runtime_root / "state" / "worker_brief_queue" / "latest.json"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.worker_brief_queue.v1",
                "status": "worker_brief_queue_ready",
                "queue_id": "current-p0-three-text-worker-brief-queue",
                "source_package_id": "current_p0_three_text_20260707",
                "brief_count": len(briefs),
                "dispatch_ready": True,
                "next_frontier_default_outlet": False,
                "briefs": briefs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return briefs


def _real_worker_entry(module, runtime_root: Path, brief: dict[str, str], provider_id: str) -> dict:
    worker_result = {
        "status": "activity_gate_checked",
        "worker_task_id": f"p0_008_worker_dispatch_real_receipt.{brief['source_role']}",
        "artifact_ref": str(runtime_root / "artifacts" / f"{brief['source_role']}.json"),
        "actual_provider_id": provider_id,
        "actual_provider_family": "deepseek" if "deepseek" in provider_id else "qwen",
        "actual_carrier_provider_id": provider_id,
        "provider_router_active": True,
        "provider_route_reason": "worker_brief_real_receipt_unit",
        "worker_brief_id": brief["worker_brief_id"],
        "worker_brief_queue_id": "current-p0-three-text-worker-brief-queue",
        "source_package_id": brief["source_package_id"],
        "source_ledger_entry_id": brief["source_ledger_entry_id"],
        "source_ref": brief["source_ref"],
        "source_sha256": brief["source_sha256"],
        "source_role": brief["source_role"],
        "provider_candidates": brief["provider_candidates"],
        "worker_dispatch_real_receipt_required": True,
        "worker_brief_real_receipt_required": True,
    }
    return module.temporal_worker_activity_entry(
        wave_id="p0-008-worker-dispatch-real-receipt-unit",
        task_id="xinao_seed_cortex_phase0_20260701",
        worker_result=worker_result,
        dispatch_time="2026-07-07T20:00:00+08:00",
    )


def test_p0_008_accepts_only_real_workerbrief_provider_receipts(tmp_path: Path) -> None:
    module = _load_module()
    runtime_root = tmp_path / "runtime"
    briefs = _write_current_worker_brief_queue(runtime_root)
    provider_ids = ["qwen_prepaid_cheap_worker", "deepseek_v4_pro", "qwen_prepaid_cheap_worker"]
    entries = [
        _real_worker_entry(module, runtime_root, brief, provider_id)
        for brief, provider_id in zip(briefs, provider_ids)
    ]

    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        wave_id="p0-008-worker-dispatch-real-receipt-unit",
        extra_entries=entries,
        runtime_entrypoint_invocation={
            "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_activity",
            "runtime_enforced": True,
        },
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        auto_dispatch_performed=True,
        worker_dispatch_real_receipt_required=True,
        write=False,
    )

    p0_008 = payload["p0_008_worker_dispatch_real_receipt"]
    assert payload["validation"]["passed"] is True
    assert payload["adoption_state"] == "runtime_enforced_hot_path_hooked"
    assert payload["summary"]["spawned_external_agent_count"] == 3
    assert payload["succeeded_count"] == 3
    assert payload["worker_dispatch_real_receipt_ready"] is True
    assert payload["actual_worker_result_count"] == 3
    assert p0_008["worker_dispatch_real_receipt_ready"] is True
    assert p0_008["receipt_count"] == 3
    assert p0_008["succeeded_receipt_count"] == 3
    assert p0_008["dp_receipt_count"] == 1
    assert p0_008["qwen_receipt_count"] == 2
    assert p0_008["phase1_receipt_count"] == 0
    assert p0_008["synthetic_succeeded_by_driver_count"] == 0


def test_p0_008_rejects_phase1_or_synthetic_receipts(tmp_path: Path) -> None:
    module = _load_module()
    runtime_root = tmp_path / "runtime"
    briefs = _write_current_worker_brief_queue(runtime_root)
    entries = [
        _real_worker_entry(module, runtime_root, brief, provider_id)
        for brief, provider_id in zip(
            briefs,
            ["qwen_prepaid_cheap_worker", "deepseek_v4_pro", "qwen_prepaid_cheap_worker"],
        )
    ]
    entries[0]["transport_pattern_ref"] = "modular_dynamic_worker_pool_phase1"
    entries[1]["synthetic_succeeded_by_driver"] = True

    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        wave_id="p0-008-worker-dispatch-real-receipt-unit",
        extra_entries=entries,
        runtime_entrypoint_invocation={
            "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_activity",
            "runtime_enforced": True,
        },
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        auto_dispatch_performed=True,
        worker_dispatch_real_receipt_required=True,
        write=False,
    )

    p0_008 = payload["p0_008_worker_dispatch_real_receipt"]
    assert payload["validation"]["passed"] is False
    assert p0_008["worker_dispatch_real_receipt_ready"] is False
    assert p0_008["phase1_receipt_count"] == 1
    assert p0_008["synthetic_succeeded_by_driver_count"] == 1
    assert p0_008["validation"]["checks"]["phase1_receipts_forbidden"] is False
    assert p0_008["validation"]["checks"]["synthetic_succeeded_by_driver_forbidden"] is False


def test_p0_008_ready_latest_is_not_overwritten_by_empty_read_model(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime_root = tmp_path / "runtime"
    briefs = _write_current_worker_brief_queue(runtime_root)
    entries = [
        _real_worker_entry(module, runtime_root, brief, provider_id)
        for brief, provider_id in zip(
            briefs,
            ["qwen_prepaid_cheap_worker", "deepseek_v4_pro", "qwen_prepaid_cheap_worker"],
        )
    ]

    ready_payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        wave_id="p0-008-worker-dispatch-real-receipt-unit",
        extra_entries=entries,
        runtime_entrypoint_invocation={
            "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
            "runtime_enforced_scope": "seed_cortex_temporal_worker_dispatch_ledger_activity",
            "runtime_enforced": True,
        },
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        auto_dispatch_performed=True,
        worker_dispatch_real_receipt_required=True,
        write=True,
    )
    assert ready_payload["p0_008_worker_dispatch_real_receipt"]["worker_dispatch_real_receipt_ready"] is True

    overwrite_attempt = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        wave_id="empty-read-model-overwrite-attempt",
        write=True,
    )
    latest_path = Path(ready_payload["output_paths"]["runtime_latest"])
    latest = json.loads(latest_path.read_text(encoding="utf-8"))

    assert overwrite_attempt["canonical_latest_write_suppressed"] is True
    assert latest["wave_id"] == "p0-008-worker-dispatch-real-receipt-unit"
    assert latest["p0_008_worker_dispatch_real_receipt"]["required"] is True
    assert latest["p0_008_worker_dispatch_real_receipt"]["worker_dispatch_real_receipt_ready"] is True
    assert latest["worker_dispatch_real_receipt_ready"] is True
    assert latest["actual_worker_result_count"] == 3
    assert latest["p0_008_worker_dispatch_real_receipt"]["receipt_count"] == 3

    failed_p0_008_overwrite = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=runtime_root,
        wave_id="failed-p0-008-overwrite-attempt",
        worker_dispatch_real_receipt_required=True,
        write=True,
    )
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert failed_p0_008_overwrite["canonical_latest_write_suppressed"] is True
    assert latest["wave_id"] == "p0-008-worker-dispatch-real-receipt-unit"
    assert latest["p0_008_worker_dispatch_real_receipt"]["worker_dispatch_real_receipt_ready"] is True

    module.write_json(latest_path, failed_p0_008_overwrite)
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["wave_id"] == "p0-008-worker-dispatch-real-receipt-unit"
    assert latest["p0_008_worker_dispatch_real_receipt"]["worker_dispatch_real_receipt_ready"] is True


def test_worker_dispatch_ledger_hot_path_adoption_requires_auto_dispatch(
    tmp_path: Path,
) -> None:
    module = _load_module()
    worker_result = {
        "status": "activity_gate_checked",
        "worker_task_id": "root-driver-hot-path-worker",
        "jsonl_path": str(tmp_path / "worker.jsonl"),
    }
    entry = module.temporal_worker_activity_entry(
        wave_id="root-driver-hot-path-wave",
        task_id="xinao_seed_cortex_phase0_20260701",
        worker_result=worker_result,
        dispatch_time="2026-07-04T00:00:00+08:00",
    )

    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=tmp_path / "runtime",
        wave_id="root-driver-hot-path-wave",
        extra_entries=[entry],
        runtime_entrypoint_invocation={
            "invoked_by": "root_intent_loop_driver.dp_sidecar_execution_port_poll",
            "runtime_enforced_scope": "seed_cortex_root_intent_loop_driver_dp_port_poll",
            "runtime_enforced": True,
        },
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        auto_dispatch_performed=True,
        write=False,
    )

    assert payload["adoption_state"] == "runtime_enforced_hot_path_hooked"
    assert payload["machine_loop"]["auto_dispatch_performed"] is True
    assert payload["validation"]["checks"]["hot_path_adoption_requires_runtime_entrypoint"] is True
    assert payload["validation"]["passed"] is True


def test_worker_dispatch_ledger_validation_rejects_runtime_enforced_adoption(
    tmp_path: Path,
) -> None:
    module = _load_module()
    payload = module.build_worker_dispatch_ledger(
        repo_root=REPO_ROOT,
        runtime_root=tmp_path / "runtime",
        write=False,
    )
    payload["adoption_state"] = "runtime_enforced_hot_path_hooked"

    validation = module.build_validation(payload)

    assert validation["passed"] is False
    assert validation["checks"]["top_level_adoption_state_fixed"] is True
    assert validation["checks"]["hot_path_adoption_requires_runtime_entrypoint"] is False
