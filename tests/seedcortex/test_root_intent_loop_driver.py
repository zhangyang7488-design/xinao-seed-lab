import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "root_intent_loop_driver.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_root_intent_loop_driver.v1.json"
)
ROOT_INTENT_WAVE_ID = "root-intent-loop-driver-focused-test-wave"
DP_MODE_COUNTS = {
    "draft": 12,
    "eval": 3,
    "contradiction": 2,
    "extraction": 1,
    "audit": 1,
    "search": 0,
    "citation_verify": 1,
    "provider_probe": 0,
}


def _load_module():
    assert MODULE_PATH.is_file(), (
        "RootIntentLoop driver module is expected at "
        "services/agent_runtime/root_intent_loop_driver.py"
    )
    spec = importlib.util.spec_from_file_location("root_intent_loop_driver", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeP1DefaultMainChain:
    calls: list[dict[str, Any]] = []

    @classmethod
    def build(cls, **kwargs: Any) -> dict[str, Any]:
        cls.calls.append(dict(kwargs))
        runtime = Path(kwargs["runtime_root"])
        repo = Path(kwargs["repo_root"])
        task_id = str(kwargs.get("task_id") or "xinao_seed_cortex_phase0_20260701")
        base_wave_id = str(kwargs.get("base_wave_id") or "p1-default-main-chain-test")
        wave03_id = f"{base_wave_id}-wave-03"
        wave04_id = f"{base_wave_id}-wave-04"
        p1_state = runtime / "state" / "codex_333_p1_loop_frontier"
        root_state = runtime / "state" / "root_intent_loop_driver"
        paths = {
            "runtime_latest": str(p1_state / "latest.json"),
            "runtime_task_latest": str(p1_state / f"{task_id}.json"),
            "p2_fan_in_hook_latest": str(p1_state / "p2_fan_in_hook_latest.json"),
            "p3_frontier_latest": str(p1_state / "p3_frontier_latest.json"),
            "root_driver_p1_default_main_chain_latest": str(root_state / "p1_default_main_chain_latest.json"),
            "root_driver_p1_continuation_latest": str(root_state / "p1_continuation_default_main_chain_latest.json"),
            "root_driver_p1_wave03_latest": str(root_state / "p1_wave03_default_main_chain_latest.json"),
            "root_driver_p1_default_main_chain_readback_zh": str(
                runtime / "readback" / "zh" / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
            ),
            "root_driver_p1_continuation_readback_zh": str(
                runtime / "readback" / "zh" / "root_intent_loop_driver_p1_default_main_chain_continuation_20260703.md"
            ),
            "runtime_readback_zh": str(
                runtime / "readback" / "zh" / f"codex_333_p1_loop_frontier_{task_id}_20260703.md"
            ),
            "repo_frontier_readback": str(repo / "docs" / "current" / "CODEX_S_333_P1_LOOP_FRONTIER_20260703.md"),
        }
        p3_frontier_id = f"p3-333-{base_wave_id}-frontier"
        p3_frontier = {
            "frontier_id": p3_frontier_id,
            "validation": {"passed": True},
        }
        bundle = {
            "schema_version": "xinao.codex_s.p1_loop_frontier_ref_bundle.v1",
            "status": "p1_loop_frontier_default_main_chain_enforced",
            "runtime_enforced": True,
            "trigger_installed": True,
            "invoked_by": "root_intent_loop_driver.default_runtime_scheduler",
            "wave_ids": [
                f"{base_wave_id}-wave-01",
                f"{base_wave_id}-wave-02",
                wave03_id,
                wave04_id,
            ],
            "wave03_id": wave03_id,
            "wave04_id": wave04_id,
            "wave04_plus_present": True,
            "latest_auto_wave_index": 4,
            "latest_auto_wave_id": wave04_id,
            "new_wave_ids_this_tick": [wave04_id],
            "p3_frontier_id": p3_frontier_id,
            "p2_fan_in_hook_ref": paths["p2_fan_in_hook_latest"],
            "p3_frontier_ref": paths["p3_frontier_latest"],
            "root_driver_default_trigger_enforcement_ref": str(
                root_state / "default_trigger_enforcement_latest.json"
            ),
            "durable_parallel_wave_packet_ref": str(
                runtime / "state" / "durable_parallel_wave_packet" / "latest.json"
            ),
            "completion_claim_allowed": False,
            "validation": {
                "passed": True,
                "checks": {
                    "default_main_chain_requested": True,
                    "root_trigger_enforcement_ref_bound": True,
                    "durable_runtime_enforced": True,
                    "wave04_plus_present": True,
                    "new_wave_this_tick_present": True,
                    "episode_default_hook_invoked": True,
                    "p2_fan_in_hook_runtime_enforced": True,
                    "p3_distinct_frontier_pushed": True,
                    "completion_claim_blocked": True,
                },
            },
        }
        payload = {
            "schema_version": "xinao.codex_s.333_p1_loop_frontier.v1",
            "status": "codex_333_p1_loop_frontier_runtime_invoked",
            "runtime_enforced": True,
            "trigger_installed": True,
            "default_main_chain": True,
            "while_wave_ids": [
                f"{base_wave_id}-wave-01",
                f"{base_wave_id}-wave-02",
                wave03_id,
                wave04_id,
            ],
            "p2_episode_fan_in_hook": {
                "episode_default_hook": True,
                "validation": {"passed": True},
            },
            "summary": {
                "while_wave_count": 4,
                "wave03_id": wave03_id,
                "wave03_floor_present_deprecated_compat": True,
                "wave04_id": wave04_id,
                "wave04_plus_present": True,
                "latest_auto_wave_index": 4,
                "latest_auto_wave_id": wave04_id,
                "new_wave_ids_this_tick": [wave04_id],
                "draft_eval_group_count_total": 4,
                "execute_search_invocation_count_total": 0,
                "provider_probe_invocation_count_total": 0,
            },
            "p1_loop_frontier_refs": bundle,
            "p3_frontier": p3_frontier,
            "output_paths": paths,
            "completion_claim_allowed": False,
            "validation": {"passed": True},
        }
        if kwargs.get("write", True):
            _write_json(Path(paths["runtime_latest"]), payload)
            _write_json(Path(paths["runtime_task_latest"]), payload)
            _write_json(Path(paths["root_driver_p1_default_main_chain_latest"]), bundle)
            _write_json(Path(paths["root_driver_p1_continuation_latest"]), bundle)
            _write_json(Path(paths["root_driver_p1_wave03_latest"]), {"wave_id": wave03_id})
            _write_json(Path(paths["p3_frontier_latest"]), p3_frontier)
            _write_json(Path(paths["p2_fan_in_hook_latest"]), payload["p2_episode_fan_in_hook"])
            Path(paths["root_driver_p1_default_main_chain_readback_zh"]).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            Path(paths["root_driver_p1_default_main_chain_readback_zh"]).write_text(
                "现在能 invoke：P1 auto_while wave04+ -> P3 distinct frontier\n",
                encoding="utf-8",
            )
            Path(paths["root_driver_p1_continuation_readback_zh"]).write_text(
                "现在能 invoke：P1 auto_while wave04+ -> P3 distinct frontier\n",
                encoding="utf-8",
            )
        return payload


def _state_payload(schema_version: str, status: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "status": status,
        "validation": {"passed": True},
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "not_source_of_truth": True,
    }
    payload.update(extra)
    return payload


def _seed_anchor_package(anchor_root: Path) -> None:
    anchor_root.mkdir(parents=True, exist_ok=True)
    for name in (
        "root_intent_loop_driver_anchor.txt",
        "新系统独立并行_自由发散外部研究总稿_20260701.txt",
        "当前工程最大能力并行动动态轮回循环外部搜索总稿_20260702.txt",
    ):
        (anchor_root / name).write_text(f"{name}\n", encoding="utf-8")


def _worker_dispatch_ledger_poll_entries(
    *,
    wave_id: str,
    poll_status: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def add_entry(lane_ref: str, mode: str, index: int, dp_mode: str = "") -> None:
        terminal_state = "succeeded" if poll_status == "succeeded" else poll_status
        lane_id = lane_ref
        if mode == "dp_sidecar_execution":
            safe_ref = "".join(
                ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in lane_ref
            )[:96]
            lane_id = f"root-intent-loop-dp-{index - 1:02d}-{safe_ref}"
        entries.append(
            {
                "entry_id": f"worker-ledger-entry-{index:02d}",
                "wave_id": wave_id,
                "task_id": "root-intent-loop-driver-focused-test",
                "lane_id": lane_id,
                "lane_ref": lane_ref,
                "agent_id": lane_ref.replace(":", "_"),
                "provider": "codex_s.worker_dispatch_ledger",
                "mode": mode,
                "dp_mode": dp_mode,
                "dispatch_time": "2026-07-03T00:00:00+00:00",
                "poll_status": poll_status,
                "terminal_state": terminal_state,
                "artifact_refs": [f"runtime://worker-dispatch-ledger/{lane_ref}"],
                "fan_in_decision": (
                    "accepted_for_ledger_evidence_only"
                    if poll_status == "succeeded"
                    else "not_applicable_not_spawned"
                ),
                "next_wave_decision": "requires_upstream_scheduler_explicit_call",
                "adoption_state": "verifier_ready_but_not_hooked",
                "source": "worker_dispatch_ledger_poll",
                "ledger_poll_source": "worker_dispatch_ledger_poll",
                "legacy_5d33_transport_pattern_reused": False,
                "legacy_5d33_owner_reused": False,
                "legacy_5d33_pass_reused": False,
                "legacy_5d33_latest_authority_reused": False,
                "completion_claim_allowed": False,
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_decision": True,
                "not_execution_controller": True,
            }
        )

    add_entry("codex-subagent:codex_s_current_worker", "worker", 1)
    index = 2
    for mode, count in DP_MODE_COUNTS.items():
        for lane_index in range(1, count + 1):
            add_entry(
                f"dp-sidecar-execution:{wave_id}:{mode}:{lane_index:02d}",
                "dp_sidecar_execution",
                index,
                mode,
            )
            index += 1
    return entries


def _seed_worker_dispatch_ledger_poll(
    runtime: Path,
    *,
    wave_id: str,
    poll_status: str = "succeeded",
) -> None:
    entries = _worker_dispatch_ledger_poll_entries(
        wave_id=wave_id,
        poll_status=poll_status,
    )
    succeeded_entries = [
        entry for entry in entries if entry["poll_status"] == "succeeded"
    ]
    state = runtime / "state"
    latest = state / "worker_dispatch_ledger" / "latest.json"
    poll_latest = state / "worker_dispatch_ledger" / "poll_latest.json"
    payload = _state_payload(
        "xinao.codex_s.worker_dispatch_ledger.v1",
        "worker_dispatch_ledger_poll_ready",
        adoption_state="verifier_ready_but_not_hooked",
        wave_id=wave_id,
        ledger_role="task_scoped_worker_subagent_dp_dispatch_read_model",
        dispatch_entries=entries,
        poll_entries=entries,
        succeeded_entries=succeeded_entries,
        succeeded_entry_ids=[entry["entry_id"] for entry in succeeded_entries],
        succeeded_count=len(succeeded_entries),
        poll_source="worker_dispatch_ledger_poll",
        source_kind="worker_dispatch_ledger_poll",
        driver_synthetic_succeeded_allowed=False,
        poll_result_summary={
            "entry_count": len(entries),
            "succeeded_count": len(succeeded_entries),
            "polling_or_non_success_count": len(entries) - len(succeeded_entries),
            "source_kind": "worker_dispatch_ledger_poll",
        },
        output_paths={
            "runtime_latest": str(latest),
            "poll_latest": str(poll_latest),
        },
    )
    _write_json(latest, payload)
    _write_json(poll_latest, payload)


def _seed_required_runtime_refs(runtime: Path, *, dp_provider_ready: bool = True) -> None:
    state = runtime / "state"
    artifact_queue = state / "artifact_acceptance_queue" / "latest.json"
    scheduler_latest = state / "scheduler_spawned_lane_evidence" / "latest.json"
    scheduler_wave = (
        state
        / "scheduler_spawned_lane_evidence"
        / "waves"
        / "root-intent-loop-driver-wave"
        / "scheduler-spawned-lanes-observed.json"
    )
    if dp_provider_ready:
        _write_json(
            state / "seed_cortex_sidecar_capability_reuse" / "latest.json",
            {
                "schema_version": "xinao.seed_cortex.sidecar_capability_reuse.v1",
                "status": "sidecar_capability_reuse_verified",
                "capabilities": {
                    "deepseek_dp_sidecar": {
                        "status": "verified_reusable_dp_sidecar",
                        "route": "python services/agent_runtime/agent_runtime.py --runtime D:/XINAO_RESEARCH_RUNTIME draft-deepseek",
                        "draft_path": str(runtime / "drafts" / "deepseek" / "draft.md"),
                        "delegation_path": str(
                            runtime / "state" / "delegations" / "deepseek" / "task.json"
                        ),
                        "review_index_path": str(
                            runtime
                            / "agent_runtime"
                            / "codex_review_queue"
                            / "review_index.json"
                        ),
                    }
                },
            },
        )
        _write_json(
            state / "deepseek_dynamic_routing_policy" / "latest.json",
            {
                "schema_version": "xinao.codex_s.deepseek_dynamic_routing_policy.v1",
                "status": "deepseek_dynamic_routing_policy_custom_stopgap_only",
                "routing_policy": {
                    "provider_backend": "custom_stopgap",
                    "mature_router_bound": False,
                    "adoption_state": "custom_stopgap_only",
                    "custom_router_allowed": False,
                    "custom_stopgap_mapping_allowed": True,
                    "default_intelligent_dispatch_allowed": False,
                    "completion_gate_passed": False,
                    "named_blocker": "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
                    "current_default_provider_width": 50,
                    "key_count_is_capacity_multiplier": False,
                    "same_account_keypool_capacity_multiplier_allowed": False,
                },
                "model_policy": {
                    "current_probe_model": "deepseek-chat",
                    "bulk_model_candidate": "deepseek-v4-flash",
                    "quality_model_candidate": "deepseek-v4-pro",
                    "deepseek_v4_pro_default_route_allowed": False,
                    "deepseek_v4_flash_default_route_allowed": False,
                    "pro_model_requires_separate_live_probe": True,
                    "model_alias_migration_required": True,
                },
                "named_blocker": "XINAO_MATURE_ROUTER_BACKEND_NOT_BOUND",
                "validation": {"passed": True},
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )

    _write_json(
        artifact_queue,
        _state_payload(
            "xinao.seedcortex.artifact_acceptance_queue.v1",
            "artifact_acceptance_queue_ready",
            adoption_state="api_cli_verifier_ready_not_hook_enforced",
            accepted_artifact_count=1,
            accepted_artifacts=["root-intent-loop-driver-default-runtime-proof"],
            accepted_for_next_frontier_only=True,
            direct_fact_promotion_allowed=False,
        ),
    )

    scheduler_payload = _state_payload(
        "xinao.codex_s.scheduler_spawned_lane_evidence.v1",
        "scheduler_spawned_lane_evidence_ready",
        lane_evidence_state="scheduler_spawned_lanes_observed",
        scheduler_invoked=True,
        parent_dispatch_invoked=False,
        activity_scope_scheduler_invoked=False,
        default_runtime_scheduler_invoked=True,
        runtime_enforced=True,
        trigger_installed=True,
        scheduler_spawned_lane_count=2,
        dp_sidecar_execution_lanes_spawned=True,
        dp_sidecar_execution_modes_seen=["draft", "audit", "search"],
        actual_dispatch_refs={
            "scheduler_spawned_lane_refs": [
                {
                    "lane_kind": "current_parent_codex_subagent",
                    "lane_ref": "codex-subagent:root-intent-loop-driver-1",
                    "poll_status": "completed",
                    "not_execution_controller": True,
                },
                {
                    "lane_kind": "dp_sidecar_execution",
                    "lane_ref": "dp-sidecar:root-intent-loop-driver-1",
                    "poll_status": "completed",
                    "not_execution_controller": True,
                },
            ],
            "refs_are_not_execution_controllers": True,
        },
        evidence_refs={
            "runtime_wave_record": str(scheduler_wave),
            "runtime_wave_record_digest_sha256": "b" * 64,
            "selected_runtime_latest": str(scheduler_latest),
        },
    )
    _write_json(scheduler_wave, scheduler_payload)
    _write_json(scheduler_latest, scheduler_payload)
    _write_json(
        state / "scheduler_spawned_lane_evidence" / "current_wave_latest.json",
        scheduler_payload,
    )

    default_trigger = _state_payload(
        "xinao.codex_s.default_main_loop_trigger_candidate.v1",
        "default_main_loop_trigger_runtime_installed",
        adoption_state="runtime_enforced",
        runtime_enforced=True,
        trigger_installed=True,
        stop_hook_controller=False,
        stop_handoff_consumed=True,
        default_runtime_scheduler_invoked=True,
        scheduler_default_runtime_lane_evidence_state="scheduler_spawned_lanes_observed",
        service_entrypoint={
            "caller": "SeedCortexService.default_main_loop_trigger_candidate",
            "api_cli_adoption_state": "api_cli_verifier_ready_not_hook_enforced",
            "runtime_enforced": True,
            "trigger_installed": True,
            "stop_hook_controller": False,
        },
    )
    for name in ("latest.json", "service_entrypoint_latest.json", "temporal_activity_latest.json"):
        _write_json(state / "default_main_loop_trigger_candidate" / name, default_trigger)

    main_tick = _state_payload(
        "xinao.codex_s.main_execution_loop_tick.v1",
        "main_execution_loop_tick_runtime_invoked",
        adoption_state="runtime_enforced",
        runtime_enforced=True,
        trigger_installed=True,
        runtime_entrypoint_invocation={
            "invoked": True,
            "invoked_by": "root_intent_loop_driver",
            "runtime_enforced": True,
            "runtime_enforced_scope": "root_intent_loop_driver_default_runtime",
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
    )
    for name in ("latest.json", "service_entrypoint_latest.json", "temporal_activity_latest.json"):
        _write_json(state / "codex_s_main_execution_loop_tick" / name, main_tick)

    durable_packet = _state_payload(
        "xinao.codex_s.durable_parallel_wave_packet.v1",
        "durable_parallel_wave_packet_default_runtime_invoked",
        adoption_state="runtime_enforced",
        runtime_enforced=True,
        trigger_installed=True,
        runtime_entrypoint_invocation={
            "invoked": True,
            "invoked_by": "root_intent_loop_driver",
            "runtime_enforced": True,
            "not_execution_controller": True,
            "not_completion_gate": True,
        },
        actual_dispatch_refs={
            "scheduler_spawned_lane_evidence_ref": {
                "path": str(scheduler_latest),
                "exists": True,
                "json_valid": True,
            },
            "spawned_by_this_runner": False,
            "refs_are_not_execution_controllers": True,
        },
        poll_refs={
            "live_backend_watch_ref": {
                "path": str(state / "codex_s_live_backend_watch" / "latest.json"),
                "exists": True,
            }
        },
        fan_in_refs={
            "artifact_acceptance_queue_ref": {
                "path": str(artifact_queue),
                "exists": True,
                "json_valid": True,
            },
            "direct_fact_promotion_allowed": False,
        },
    )
    for name in ("latest.json", "service_entrypoint_latest.json", "temporal_activity_latest.json"):
        _write_json(state / "durable_parallel_wave_packet" / name, durable_packet)

    _write_json(
        state / "codex_s_live_backend_watch" / "latest.json",
        _state_payload(
            "xinao.codex_s.live_backend_watch.v1",
            "live_backend_watch_no_foreground_blocker",
            foreground_poll_required=False,
        ),
    )
    _write_json(
        state / "codex_s_stop_continuation_audit" / "latest.json",
        _state_payload(
            "xinao.codex_s.stop_continuation_audit.v1",
            "stop_handoff_ready_for_root_intent_loop_driver",
            stop_handoff_available=True,
            stop_handoff_consumed=False,
            next_loop_packet={
                "restore": True,
                "dispatch": True,
                "poll": True,
                "fan_in": True,
                "verify_evidence_readback": True,
            },
        ),
    )
    _write_json(
        state / "root_intent_card" / "latest.json",
        _state_payload(
            "xinao.codex_s.root_intent_card.v1",
            "root_intent_card_ready",
            intent_id="root-intent-loop-driver-focused-test",
            root_intent_cn="Seed Cortex root intent loop driver focused test",
            anti_shrink_constraints=["do not treat report/PASS/latest as completion"],
        ),
    )


def _call_driver(module: Any, *, runtime: Path, repo: Path, anchor: Path) -> dict[str, Any]:
    builder = getattr(module, "build_root_intent_loop_driver", None) or getattr(module, "build", None)
    assert builder is not None, "RootIntentLoop driver must expose build(...)"
    signature = inspect.signature(builder)
    assert "runtime_root" in signature.parameters
    assert "repo_root" in signature.parameters
    _FakeP1DefaultMainChain.calls = []
    kwargs: dict[str, Any] = {
        "runtime_root": runtime,
        "repo_root": repo,
        "anchor_package_root": anchor,
        "wave_id": ROOT_INTENT_WAVE_ID,
        "write": True,
    }
    if "p1_module" in signature.parameters:
        kwargs["p1_module"] = _FakeP1DefaultMainChain
    accepted = {key: value for key, value in kwargs.items() if key in signature.parameters}
    payload = builder(**accepted)
    assert isinstance(payload, dict), "RootIntentLoop driver must return a payload dict"
    return payload


def _ref_path(ref: Any) -> Path:
    if isinstance(ref, str):
        return Path(ref)
    if isinstance(ref, dict):
        for key in ("path", "state_ref", "latest", "ref", "runtime_latest"):
            value = ref.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value)
    raise AssertionError(f"Cannot resolve ref path from {ref!r}")


def _has_ref_path(ref: Any) -> bool:
    try:
        _ref_path(ref)
    except AssertionError:
        return False
    return True


def _assert_existing_tmp_runtime_ref(ref: Any, runtime: Path, *path_parts: str) -> Path:
    path = _ref_path(ref)
    normalized = str(path).replace("\\", "/")
    runtime_normalized = str(runtime).replace("\\", "/")
    assert normalized.startswith(runtime_normalized)
    assert path.is_file()
    for part in path_parts:
        assert part in normalized
    if isinstance(ref, dict):
        assert ref.get("exists", True) is True
    return path


def _bundle_ref(payload: dict[str, Any], *names: str) -> Any:
    aliases: list[str] = []
    for name in names:
        aliases.extend(
            [
                name,
                f"{name}_ref",
                f"{name}_latest",
                f"{name}_state_ref",
                f"{name}_latest_ref",
            ]
        )
    bundles = (
        payload.get("default_runtime_refs"),
        payload.get("root_intent_loop_refs"),
        payload.get("runtime_refs"),
        payload.get("driver_refs"),
        payload.get("evidence_refs"),
    )
    for bundle in bundles:
        if isinstance(bundle, dict):
            for name in aliases:
                if name in bundle and _has_ref_path(bundle[name]):
                    return bundle[name]
    for bundle in bundles:
        if isinstance(bundle, dict):
            for name in aliases:
                if name in bundle:
                    return bundle[name]
    for name in aliases:
        if name in payload and _has_ref_path(payload[name]):
            return payload[name]
    for name in aliases:
        if name in payload:
            return payload[name]
    raise AssertionError(f"Missing any ref key from aliases: {names!r}")


def _nested_value(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict) or key not in current:
                break
            current = current[key]
        else:
            return current
    raise AssertionError(f"Missing value for paths: {paths!r}")


def test_root_intent_loop_driver_payload_uses_tmp_runtime_and_writes_continuity_envelope(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "new-system-anchor-package"
    (repo / "docs" / "current").mkdir(parents=True)
    _seed_anchor_package(anchor)
    _seed_required_runtime_refs(runtime)
    _seed_worker_dispatch_ledger_poll(
        runtime,
        wave_id=ROOT_INTENT_WAVE_ID,
        poll_status="succeeded",
    )

    payload = _call_driver(module, runtime=runtime, repo=repo, anchor=anchor)

    assert payload["schema_version"] == "xinao.codex_s.root_intent_loop_driver.v1"
    assert payload["runtime_enforced"] is True
    assert payload["trigger_installed"] is True
    assert payload["stop_hook_controller"] is False
    assert payload["stop_handoff_consumed"] is True
    assert payload["completion_claim_allowed"] is False
    readback = runtime / "readback" / "zh" / "root_intent_loop_driver_20260703.md"
    assert readback.is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "L 层差距" in readback_text
    assert "L1 不得冒充 L3 默认 runtime" in readback_text
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["checks"]["worker_dispatch_ledger_succeeded_present"] is True
    assert payload["validation"]["checks"]["fan_in_from_worker_dispatch_ledger_poll"] is True
    assert payload["validation"]["checks"]["no_driver_synthetic_succeeded_lane_results"] is True
    assert payload["validation"]["checks"]["default_trigger_enforcement_written"] is True
    assert payload["validation"]["checks"]["default_trigger_enforced_for_task"] is True
    assert payload["validation"]["checks"]["can_invoke_now_present"] is True
    assert payload["validation"]["checks"]["p1_default_main_chain_invoked"] is True
    assert payload["validation"]["checks"]["p1_wave04_plus_auto_present"] is True
    assert payload["validation"]["checks"]["p1_new_wave_this_tick_present"] is True
    assert payload["validation"]["checks"]["p1_episode_default_hook_invoked"] is True
    assert payload["validation"]["checks"]["p1_p3_distinct_frontier_pushed"] is True
    assert payload["validation"]["checks"]["p1_trigger_durable_same_binding_enforced"] is True
    assert payload["validation"]["checks"]["episode_default_hook_runtime_enforced"] is True
    assert _FakeP1DefaultMainChain.calls
    assert _FakeP1DefaultMainChain.calls[0]["wave_count"] >= 4
    assert _FakeP1DefaultMainChain.calls[0]["append_to_existing"] is True
    assert _FakeP1DefaultMainChain.calls[0]["default_main_chain"] is True
    assert payload["can_invoke_now"]["provider_probe_role"] == (
        "probe_only_not_bulk_progress"
    )
    assert "codex_333_p1_loop_frontier.default_main_chain_auto_while" in payload["can_invoke_now"]["runtime_chain"]
    assert "dp_sidecar_execution_port" in payload["can_invoke_now"]["runtime_chain"]
    assert "draft" in payload["can_invoke_now"]["dp_requested_modes_bound"]
    assert "litellm.model_gateway" in payload["can_invoke_now"]["carrier_providers_observed"]
    assert "deepseek.search_sidecar" not in payload["can_invoke_now"]["carrier_providers_observed"]
    assert "能 invoke" in payload["can_invoke_now_cn"]

    trigger_enforcement = payload["default_trigger_enforcement"]
    assert trigger_enforcement["runtime_enforced"] is True
    assert trigger_enforcement["trigger_enforced"] is True
    assert trigger_enforcement["trigger_installed"] is True
    assert trigger_enforcement["unique_authority_entry"] == str(anchor)
    assert "draft" in trigger_enforcement["can_invoke_now"]["model_gateway_modes_observed"]
    assert "eval" in trigger_enforcement["can_invoke_now"]["model_gateway_modes_observed"]
    assert "现在能 invoke" in trigger_enforcement["can_invoke_now_cn"]
    p1_chain = payload["p1_default_main_chain"]
    assert p1_chain["status"] == "p1_default_main_chain_auto_while_runtime_enforced"
    assert p1_chain["wave04_plus_present"] is True
    assert p1_chain["latest_auto_wave_index"] >= 4
    assert p1_chain["latest_auto_wave_id"].endswith("-wave-04")
    assert p1_chain["new_wave_ids_this_tick"]
    assert p1_chain["p3_frontier_id"].startswith("p3-333-")
    assert p1_chain["p3_frontier_id"] != "p3-333-total-draft-frontier-20260703"
    assert payload["p1_loop_frontier_refs"]["validation"]["passed"] is True
    p1_bundle_path = _assert_existing_tmp_runtime_ref(
        p1_chain["p1_ref_bundle_ref"],
        runtime,
        "state/root_intent_loop_driver",
    )
    p1_bundle = _read_json(p1_bundle_path)
    assert p1_bundle["wave04_plus_present"] is True
    assert p1_bundle["latest_auto_wave_index"] >= 4
    p1_continuation_path = _assert_existing_tmp_runtime_ref(
        p1_chain["p1_continuation_ref"],
        runtime,
        "state/root_intent_loop_driver",
    )
    assert _read_json(p1_continuation_path)["wave04_plus_present"] is True
    p1_wave03_path = _assert_existing_tmp_runtime_ref(
        p1_chain["p1_wave03_ref"],
        runtime,
        "state/root_intent_loop_driver",
    )
    assert _read_json(p1_wave03_path)["wave_id"].endswith("-wave-03")
    p1_readback = _assert_existing_tmp_runtime_ref(
        p1_chain["p1_readback_zh"],
        runtime,
        "readback/zh",
    )
    assert "现在能 invoke" in p1_readback.read_text(encoding="utf-8")
    episode_hook = payload["episode_default_hook"]
    assert episode_hook["status"] == "episode_default_hook_default_main_chain_enforced"
    assert episode_hook["hook_stage"] == "after_p2_fan_in_before_p3_frontier"
    assert episode_hook["validation"]["passed"] is True
    episode_hook_path = _assert_existing_tmp_runtime_ref(
        payload["evidence_refs"]["episode_default_hook_latest"],
        runtime,
        "state/root_intent_loop_driver",
    )
    assert _read_json(episode_hook_path)["direct_fact_promotion_allowed"] is False
    enforcement_path = _assert_existing_tmp_runtime_ref(
        trigger_enforcement["latest"],
        runtime,
        "state/root_intent_loop_driver",
    )
    enforcement_payload = _read_json(enforcement_path)
    assert enforcement_payload["schema_version"] == (
        "xinao.codex_s.333_loop_width_trigger_enforcement.v1"
    )
    assert enforcement_payload["runtime_enforced"] is True
    assert enforcement_payload["trigger_enforced"] is True
    assert enforcement_payload["default_trigger_candidate_is_candidate_view"] is True
    assert enforcement_payload["nonprobe_true_invocation_count"] >= 1
    assert enforcement_payload["provider_probe_bulk_progress_allowed"] is False
    assert enforcement_payload["fan_in_from_worker_dispatch_ledger_poll"] is True
    assert "can_invoke_now" in enforcement_payload
    assert "eval" in enforcement_payload["can_invoke_now"]["model_gateway_modes_observed"]
    assert enforcement_payload["validation"]["passed"] is True
    enforcement_readback = _assert_existing_tmp_runtime_ref(
        trigger_enforcement["readback_zh"],
        runtime,
        "readback/zh",
    )
    assert "333 本波的 trigger enforced" in enforcement_readback.read_text(
        encoding="utf-8"
    )

    worker_ledger = payload["worker_dispatch_ledger"]
    assert worker_ledger["source_kind"] == "worker_dispatch_ledger_poll"
    assert worker_ledger["succeeded_count"] >= 1
    assert worker_ledger["driver_synthetic_succeeded_allowed"] is False
    ledger_latest = _assert_existing_tmp_runtime_ref(
        worker_ledger["latest"],
        runtime,
        "state/worker_dispatch_ledger",
    )
    ledger_payload = _read_json(ledger_latest)
    assert ledger_payload["succeeded_count"] == worker_ledger["succeeded_count"]
    assert all(
        entry["poll_status"] == "succeeded"
        for entry in ledger_payload["succeeded_entries"]
    )

    _assert_existing_tmp_runtime_ref(
        _bundle_ref(
            payload,
            "default_main_loop_trigger_candidate",
            "default_trigger",
            "trigger",
        ),
        runtime,
        "state/default_main_loop_trigger_candidate",
    )
    _assert_existing_tmp_runtime_ref(
        _bundle_ref(payload, "main_execution_loop_tick", "main_loop_tick", "tick"),
        runtime,
        "state/codex_s_main_execution_loop_tick",
    )
    _assert_existing_tmp_runtime_ref(
        _bundle_ref(
            payload,
            "durable_parallel_wave_packet",
            "durable_packet",
            "durable",
        ),
        runtime,
        "state/durable_parallel_wave_packet",
    )

    scheduler_state = _nested_value(
        payload,
        ("scheduler_default_runtime_lane_evidence_state",),
        ("scheduler_lane_evidence", "lane_evidence_state"),
        ("scheduler_lane_evidence_refs", "lane_evidence_state"),
        ("scheduler_spawned_lane_evidence", "lane_evidence_state"),
    )
    assert scheduler_state == "scheduler_spawned_lanes_observed"
    _assert_existing_tmp_runtime_ref(
        _bundle_ref(
            payload,
            "scheduler_spawned_lane_evidence",
            "scheduler_default_runtime_lane_evidence",
        ),
        runtime,
        "state/scheduler_spawned_lane_evidence",
    )

    fan_in = payload["fan_in_acceptance"]
    assert fan_in["consumed_scheduler_lane_results"] is True
    assert fan_in["source_kind"] == "worker_dispatch_ledger_poll"
    assert fan_in["worker_dispatch_ledger_succeeded_count"] >= 1
    assert fan_in["driver_synthetic_succeeded_allowed"] is False
    assert fan_in["before_artifact_acceptance"] is True
    assert fan_in["lane_result_count"] == payload["scheduler_default_runtime"]["scheduler_spawned_lane_count"]
    assert fan_in["accepted_edge_count"] == fan_in["worker_dispatch_ledger_succeeded_count"]
    assert (
        payload["validation"]["checks"][
            "fan_in_accepted_edge_count_matches_ledger_succeeded"
        ]
        is True
    )
    assert payload["validation"]["checks"]["dp_nonprobe_true_invocation_present"] is True
    assert payload["validation"]["checks"]["provider_probe_not_bulk_progress"] is True
    assert payload["dp_port_poll"]["nonprobe_true_invocation_count"] >= 1
    assert payload["dp_port_poll"]["provider_probe_bulk_progress_allowed"] is False
    lane_results_path = _assert_existing_tmp_runtime_ref(
        fan_in["lane_results_latest"],
        runtime,
        "state/root_intent_loop_driver",
    )
    lane_results_payload = _read_json(lane_results_path)
    assert lane_results_payload["schema_version"] == (
        "xinao.codex_s.root_intent_loop_lane_results.v1"
    )
    assert lane_results_payload["source_kind"] == "worker_dispatch_ledger_poll"
    assert lane_results_payload["worker_dispatch_ledger_succeeded_count"] >= 1
    assert lane_results_payload["driver_synthetic_succeeded_allowed"] is False
    assert lane_results_payload["validation"]["checks"]["worker_dispatch_ledger_succeeded_present"] is True
    assert lane_results_payload["validation"]["checks"]["lane_results_source_worker_dispatch_ledger_poll"] is True
    assert lane_results_payload["validation"]["checks"]["no_driver_synthetic_succeeded_lane_results"] is True
    assert lane_results_payload["validation"]["checks"]["fan_in_accepts_lane_results"] is True
    assert lane_results_payload["validation"]["checks"]["lane_results_match_scheduler_lanes"] is True
    assert len(lane_results_payload["lane_result_refs"]) == fan_in["lane_result_count"]
    first_lane_result = _read_json(Path(lane_results_payload["lane_result_refs"][0]))
    assert first_lane_result["schema_version"] == "xinao.codex_s.parallel_lane_result.v1"
    assert first_lane_result["terminal_state"] == "succeeded"
    assert first_lane_result["source_kind"] == "worker_dispatch_ledger_poll"
    assert first_lane_result["worker_dispatch_ledger_poll_status"] == "succeeded"
    assert first_lane_result["worker_dispatch_ledger_entry_ref"]
    assert first_lane_result["synthetic_succeeded_by_driver"] is False
    assert first_lane_result["default_boundary"]["completion_claim_allowed"] is False
    fan_in_path = _assert_existing_tmp_runtime_ref(
        fan_in["fan_in_acceptance_latest"],
        runtime,
        "state/root_intent_loop_driver",
    )
    fan_in_payload = _read_json(fan_in_path)
    assert fan_in_payload["schema_version"] == "xinao.codex_s.fan_in_acceptance.v1"
    assert fan_in_payload["source_kind"] == "worker_dispatch_ledger_poll"
    assert fan_in_payload["worker_dispatch_ledger_succeeded_count"] >= 1
    assert fan_in_payload["driver_synthetic_succeeded_allowed"] is False
    assert len(fan_in_payload["accepted_edges"]) == fan_in["worker_dispatch_ledger_succeeded_count"]
    assert all(
        edge["source_kind"] == "worker_dispatch_ledger_poll"
        and edge["worker_dispatch_ledger_entry_id"]
        for edge in fan_in_payload["accepted_edges"]
    )

    accepted_count = _nested_value(
        payload,
        ("artifact_acceptance_queue", "accepted_artifact_count"),
        ("artifact_acceptance", "accepted_artifact_count"),
        ("ArtifactAcceptance", "accepted_artifact_count"),
    )
    assert int(accepted_count) >= 1
    artifact_queue_path = _assert_existing_tmp_runtime_ref(
        _bundle_ref(payload, "artifact_acceptance_queue", "ArtifactAcceptance"),
        runtime,
        "state/artifact_acceptance_queue",
    )
    artifact_queue_payload = _read_json(artifact_queue_path)
    assert artifact_queue_payload["candidate_count"] == 1
    assert artifact_queue_payload["accepted_artifact_count"] == 1
    assert artifact_queue_payload["decisions"][0]["candidate_id"] == (
        "root-intent-loop-default-runtime-continuation"
    )

    driver_latest = runtime / "state" / "root_intent_loop_driver" / "latest.json"
    assert driver_latest.is_file()
    written_payload = _read_json(driver_latest)
    assert written_payload["schema_version"] == "xinao.codex_s.root_intent_loop_driver.v1"
    assert written_payload["runtime_enforced"] is True
    assert written_payload["completion_claim_allowed"] is False

    continuity_ref = _nested_value(
        payload,
        ("continuity_envelope",),
        ("ContinuityEnvelope",),
        ("continuity_envelope_ref",),
        ("evidence_refs", "continuity_envelope_latest"),
    )
    continuity_path = _assert_existing_tmp_runtime_ref(
        continuity_ref,
        runtime,
        "state/root_intent_loop_driver",
    )
    continuity_payload = _read_json(continuity_path)
    assert continuity_payload["schema_version"] == "xinao.codex_s.continuity_envelope.v1"
    assert continuity_payload.get("object_type") == "ContinuityEnvelope"
    assert continuity_payload["completion_claim_allowed"] is False
    assert continuity_payload["runtime_enforced"] is True
    assert continuity_payload["trigger_installed"] is True
    assert "RootIntentLoop" in continuity_payload["chinese_anchor_text"]
    assert "Stop hook" in continuity_payload["chinese_anchor_text"]
    assert continuity_payload["chinese_anchor_language"] == "zh-CN"
    assert continuity_payload["return_stack_count"] == 1
    assert continuity_payload["return_stack"][0]["pop_restore_available"] is True
    assert continuity_payload["root_recompute_when_empty"] is True

    payload_envelope = payload["continuity_envelope"]
    assert payload_envelope["chinese_anchor_text"] == continuity_payload["chinese_anchor_text"]
    assert payload_envelope["return_stack_count"] == 1
    assert payload_envelope["root_recompute_when_empty"] is True

    fan_in = payload["fan_in_acceptance"]
    assert fan_in["lane_result_count"] >= 21
    assert fan_in["accepted_edge_count"] == fan_in["worker_dispatch_ledger_succeeded_count"]
    assert (
        payload["validation"]["checks"][
            "fan_in_accepted_edge_count_matches_ledger_succeeded"
        ]
        is True
    )
    assert fan_in["consumed_scheduler_lane_results"] is True
    assert fan_in["source_kind"] == "worker_dispatch_ledger_poll"
    assert fan_in["before_artifact_acceptance"] is True

    lane_results_path = runtime / "state" / "root_intent_loop_driver" / "parallel_lane_results_latest.json"
    fan_in_path = runtime / "state" / "root_intent_loop_driver" / "fan_in_acceptance_latest.json"
    assert lane_results_path.is_file()
    assert fan_in_path.is_file()
    lane_results_payload = _read_json(lane_results_path)
    fan_in_payload = _read_json(fan_in_path)
    assert lane_results_payload["lane_result_count"] == fan_in["lane_result_count"]
    assert lane_results_payload["source_kind"] == "worker_dispatch_ledger_poll"
    assert len(fan_in_payload["accepted_edges"]) == fan_in["accepted_edge_count"]
    assert fan_in_payload["source_kind"] == "worker_dispatch_ledger_poll"
    assert len(list((runtime / "state" / "root_intent_loop_driver" / "lane_results").glob("*.json"))) == (
        fan_in["lane_result_count"]
    )

    driver_artifact_path = (
        runtime / "state" / "root_intent_loop_driver" / "root_intent_loop_default_runtime_artifact.json"
    )
    assert driver_artifact_path.is_file()
    driver_artifact = _read_json(driver_artifact_path)
    assert driver_artifact["validation"]["passed"] is True
    assert driver_artifact["fan_in_consumed_real_lane_results"] is True
    assert driver_artifact["worker_dispatch_ledger_succeeded_present"] is True
    assert driver_artifact["fan_in_from_worker_dispatch_ledger_poll"] is True
    assert driver_artifact["no_driver_synthetic_succeeded_lane_results"] is True
    assert driver_artifact["fan_in_accepted_edge_count"] == fan_in["worker_dispatch_ledger_succeeded_count"]
    assert driver_artifact["scheduler_spawned_lane_count"] == 21


def test_root_intent_loop_driver_blocks_pass_without_worker_ledger_succeeded(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "Desktop" / "new-system-anchor-package"
    (repo / "docs" / "current").mkdir(parents=True)
    _seed_anchor_package(anchor)
    _seed_required_runtime_refs(runtime)
    _seed_worker_dispatch_ledger_poll(
        runtime,
        wave_id=ROOT_INTENT_WAVE_ID,
        poll_status="polling",
    )

    original_writer = module.write_worker_dispatch_ledger_for_dp_poll

    def fake_worker_ledger_poll(
        *,
        runtime: Path,
        repo: Path,
        wave_id: str,
        dp_poll: dict[str, Any],
        write: bool = True,
    ) -> dict[str, Any]:
        entries = _worker_dispatch_ledger_poll_entries(
            wave_id=wave_id,
            poll_status="polling",
        )
        latest = runtime / "state" / "worker_dispatch_ledger" / "latest.json"
        payload = _state_payload(
            "xinao.codex_s.worker_dispatch_ledger.v1",
            "worker_dispatch_ledger_poll_ready",
            adoption_state="verifier_ready_but_not_hooked",
            wave_id=wave_id,
            ledger_role="task_scoped_worker_subagent_dp_dispatch_read_model",
            dispatch_entries=entries,
            poll_entries=entries,
            succeeded_entries=[],
            succeeded_entry_ids=[],
            succeeded_count=0,
            poll_source="worker_dispatch_ledger_poll",
            source_kind="worker_dispatch_ledger_poll",
            driver_synthetic_succeeded_allowed=False,
            poll_result_summary={
                "entry_count": len(entries),
                "succeeded_count": 0,
                "polling_or_non_success_count": len(entries),
                "source_kind": "worker_dispatch_ledger_poll",
            },
            output_paths={"runtime_latest": str(latest)},
        )
        if write:
            _write_json(latest, payload)
        return payload

    module.write_worker_dispatch_ledger_for_dp_poll = fake_worker_ledger_poll
    try:
        payload = _call_driver(module, runtime=runtime, repo=repo, anchor=anchor)
    finally:
        module.write_worker_dispatch_ledger_for_dp_poll = original_writer

    assert payload["status"] == "root_intent_loop_driver_waiting_or_blocked"
    assert payload["runtime_enforced"] is False
    assert payload["trigger_installed"] is False
    assert payload["validation"]["passed"] is False
    assert payload["worker_dispatch_ledger"]["source_kind"] == "worker_dispatch_ledger_poll"
    assert payload["worker_dispatch_ledger"]["succeeded_count"] == 0
    assert payload["validation"]["checks"]["worker_dispatch_ledger_succeeded_present"] is False
    assert payload["validation"]["checks"]["fan_in_from_worker_dispatch_ledger_poll"] is False
    assert payload["validation"]["checks"]["no_driver_synthetic_succeeded_lane_results"] is True
    assert payload["named_blocker"] == "ROOT_INTENT_LOOP_WORKER_DISPATCH_LEDGER_NO_SUCCEEDED"
    assert payload["completion_claim_allowed"] is False
    assert _FakeP1DefaultMainChain.calls == []
    assert payload["p1_default_main_chain"]["status"] == "p1_default_main_chain_not_invoked_trigger_not_enforced"


def test_root_intent_loop_driver_schema_locks_runtime_enforced_driver() -> None:
    schema = _read_json(SCHEMA_PATH)

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.root_intent_loop_driver.v1"
    )
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_DRIVER_RUNTIME_ENFORCED"
    )
    assert set(schema["properties"]["adoption_state"]["enum"]) == {
        "runtime_enforced",
        "candidate_registered",
    }
    assert schema["properties"]["stop_hook_controller"]["const"] is False
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert schema["properties"]["not_user_completion"]["const"] is True
    assert schema["properties"]["not_completion_decision"]["const"] is True
    assert "worker_dispatch_ledger" in schema["required"]
    assert "default_trigger_enforcement" in schema["required"]
    assert "p1_default_main_chain" in schema["required"]
    assert "p1_loop_frontier_refs" in schema["required"]
    assert "episode_default_hook" in schema["required"]
    assert "can_invoke_now" in schema["required"]
    assert "can_invoke_now_cn" in schema["required"]
    can_invoke_def = schema["$defs"]["can_invoke_now"]
    assert "runtime_chain" in can_invoke_def["required"]
    assert "dp_requested_modes_bound" in can_invoke_def["required"]
    assert "carrier_providers_observed" in can_invoke_def["required"]
    assert can_invoke_def["properties"]["provider_probe_role"]["const"] == (
        "probe_only_not_bulk_progress"
    )
    p1_status_enum = set(
        schema["properties"]["p1_default_main_chain"]["properties"]["status"]["enum"]
    )
    assert "p1_default_main_chain_auto_while_runtime_enforced" in p1_status_enum
    assert "p1_default_main_chain_auto_while_waiting_or_blocked" in p1_status_enum
    episode_hook_schema = schema["properties"]["episode_default_hook"]["properties"]
    assert episode_hook_schema["status"]["const"] == "episode_default_hook_default_main_chain_enforced"
    assert episode_hook_schema["hook_stage"]["const"] == "after_p2_fan_in_before_p3_frontier"
    assert episode_hook_schema["completion_claim_allowed"]["const"] is False
    worker_ledger = schema["properties"]["worker_dispatch_ledger"]
    for required in (
        "latest",
        "source_kind",
        "succeeded_count",
        "poll_source",
        "driver_synthetic_succeeded_allowed",
    ):
        assert required in worker_ledger["required"]
    assert worker_ledger["properties"]["source_kind"]["const"] == "worker_dispatch_ledger_poll"
    assert worker_ledger["properties"]["poll_source"]["const"] == "worker_dispatch_ledger_poll"
    assert worker_ledger["properties"]["succeeded_count"]["minimum"] == 0
    assert worker_ledger["properties"]["driver_synthetic_succeeded_allowed"]["const"] is False
    runtime_branch = schema["allOf"][0]["then"]["properties"]
    assert runtime_branch["adoption_state"]["const"] == "runtime_enforced"
    assert runtime_branch["runtime_enforced"]["const"] is True
    assert runtime_branch["trigger_installed"]["const"] is True
    assert runtime_branch["stop_handoff_consumed"]["const"] is True
    runtime_worker_ledger = runtime_branch["worker_dispatch_ledger"]["properties"]
    assert runtime_worker_ledger["source_kind"]["const"] == "worker_dispatch_ledger_poll"
    assert runtime_worker_ledger["succeeded_count"]["minimum"] == 1
    assert runtime_worker_ledger["driver_synthetic_succeeded_allowed"]["const"] is False
    scheduler = runtime_branch["scheduler_default_runtime"]["properties"]
    assert scheduler["lane_evidence_state"]["const"] == "scheduler_spawned_lanes_observed"
    assert scheduler["default_runtime_scheduler_invoked"]["const"] is True
    assert scheduler["runtime_enforced"]["const"] is True
    dp_20 = runtime_branch["dp_20_lane_set"]["properties"]
    assert dp_20["bound"]["const"] is True
    assert dp_20["lane_count"]["const"] == 20
    fan_in = schema["properties"]["fan_in_acceptance"]
    assert "consumed_scheduler_lane_results" in fan_in["required"]
    assert "before_artifact_acceptance" in fan_in["required"]
    assert "source_kind" in fan_in["required"]
    assert "worker_dispatch_ledger_succeeded_count" in fan_in["required"]
    assert "driver_synthetic_succeeded_allowed" in fan_in["required"]
    runtime_fan_in = runtime_branch["fan_in_acceptance"]["properties"]
    assert runtime_fan_in["consumed_scheduler_lane_results"]["const"] is True
    assert runtime_fan_in["before_artifact_acceptance"]["const"] is True
    assert runtime_fan_in["source_kind"]["const"] == "worker_dispatch_ledger_poll"
    assert runtime_fan_in["worker_dispatch_ledger_succeeded_count"]["minimum"] == 1
    assert runtime_fan_in["driver_synthetic_succeeded_allowed"]["const"] is False
    continuity = schema["properties"]["continuity_envelope"]
    assert "chinese_anchor_text" in continuity["required"]
    assert "return_stack" in continuity["required"]
    runtime_continuity = runtime_branch["continuity_envelope"]["properties"]
    assert runtime_continuity["return_stack_count"]["const"] == 1
    assert runtime_continuity["root_recompute_when_empty"]["const"] is True
    runtime_trigger = runtime_branch["default_trigger_enforcement"]["properties"]
    assert runtime_trigger["status"]["const"] == "codex_s_333_loop_width_trigger_enforced"
    assert runtime_trigger["trigger_enforced"]["const"] is True
    assert runtime_trigger["unique_authority_entry"]["const"] == (
        "C:\\Users\\xx363\\Desktop\\新系统"
    )
    assert "can_invoke_now" in runtime_branch
    assert runtime_branch["can_invoke_now"]["$ref"] == "#/$defs/can_invoke_now"
    assert runtime_branch["can_invoke_now_cn"]["minLength"] == 1
    passed_gate = next(
        item
        for item in schema["allOf"]
        if item.get("if", {})
        .get("properties", {})
        .get("validation", {})
        .get("properties", {})
        .get("passed", {})
        .get("const")
        is True
    )
    passed_properties = passed_gate["then"]["properties"]
    assert passed_properties["worker_dispatch_ledger"]["properties"]["succeeded_count"][
        "minimum"
    ] == 1
    assert passed_properties["fan_in_acceptance"]["properties"]["source_kind"]["const"] == (
        "worker_dispatch_ledger_poll"
    )
    assert passed_properties["fan_in_acceptance"]["properties"][
        "driver_synthetic_succeeded_allowed"
    ]["const"] is False
