from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_ROOTS = (
    REPO_ROOT / "services",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".github",
)
TEXT_SUFFIXES = {
    ".bat",
    ".cjs",
    ".cmd",
    ".js",
    ".json",
    ".mjs",
    ".ps1",
    ".psm1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}

ALLOWED_AGENT_RUNTIME_MODULES = {
    "__init__.py",
    "closure_test_activities.py",
    "closure_test_proof.py",
    "codex_s_worker_lane_carrier.py",
    "default_main_loop_trigger_candidate.py",
    "default_plus_dynamic_escalate.py",
    "dp_sidecar_execution_port.py",
    "integrated_bus_bus_nodes.py",
    "integrated_bus_facade_redirect.py",
    "integrated_bus_graph.py",
    "integrated_bus_litellm_langfuse.py",
    "integrated_bus_mem0_oss.py",
    "integrated_bus_parent_workflow.py",
    "integrated_bus_promotion_gate.py",
    "integrated_bus_runner.py",
    "integrated_bus_temporal_client_queue.py",
    "integrated_bus_temporal_verify.py",
    "integrated_bus_worker_daemon.py",
    "integrated_bus_workflow_registry.py",
    "lexicon_cn_escape.py",
    "overnight_local_search.py",
    "pro_review_after_draft.py",
    "routing_policy_reader.py",
    "task_entry_claim.py",
    "temporal_codex_task_workflow.py",
    "thin_bootstrap_runner.py",
    "thin_bootstrap_sandbox.py",
    "thin_evidence_writer.py",
    "thin_glue_intake.py",
    "thin_glue_l2_root_intent.py",
    "thin_glue_l3_execute.py",
    "thin_glue_l4_search.py",
    "thin_glue_l5_opa.py",
    "thin_glue_l5_openlineage.py",
    "thin_glue_l5_verify.py",
    "thin_glue_l6_self_heal.py",
    "thin_glue_l7_dvc.py",
    "thin_glue_l7_mlflow.py",
    "thin_glue_l7_optuna.py",
    "thin_glue_l7_wandb.py",
    "thin_glue_l8_token_stack.py",
    "thin_glue_l9_ledger.py",
    "thin_glue_lane_worker.py",
    "thin_glue_loop.py",
    "thin_glue_mainline_bridge.py",
    "thin_glue_mainline_spawn.py",
    "thin_glue_provider_scheduler.py",
    "thin_glue_rg_utils.py",
    "thin_glue_root_intent_temporal.py",
    "thin_glue_stack.py",
    "thin_glue_status.py",
    "thin_glue_sunset_registry.py",
    "thin_glue_temporal.py",
    "thin_glue_work_proof.py",
    "thin_glue_worker_pool_temporal.py",
    "thin_langgraph_closure.py",
    "thin_provider_client.py",
    "tool_table_coverage.py",
}


def _executable_text() -> str:
    chunks: list[str] = []
    for root in EXECUTABLE_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _nested_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_nested_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_nested_keys(nested))
    return keys


def test_retired_control_stack_directories_are_absent() -> None:
    for relative in (
        "apps",
        "contracts",
        "src",
        "services/agent_runtime/_retired",
        "services/codex_activator",
        "scripts/hardmode",
    ):
        assert not (REPO_ROOT / relative).exists(), relative


def test_agent_runtime_only_contains_declared_hot_path_and_support_modules() -> None:
    actual = {path.name for path in (REPO_ROOT / "services/agent_runtime").glob("*.py")}
    assert actual == ALLOWED_AGENT_RUNTIME_MODULES


def test_default_route_cannot_commit_the_worktree() -> None:
    route_files = (
        "integrated_bus_graph.py",
        "integrated_bus_runner.py",
        "integrated_bus_worker_daemon.py",
        "integrated_bus_workflow_registry.py",
        "task_entry_claim.py",
        "temporal_codex_task_workflow.py",
    )
    text = "\n".join(
        (REPO_ROOT / "services/agent_runtime" / name).read_text(encoding="utf-8")
        for name in route_files
    ).lower()
    for forbidden in ("git_commit_all", "git add -a", "git commit"):
        assert forbidden not in text, forbidden
    assert "gitpython_readonly" in text


def test_retained_executable_sources_have_no_dead_desktop_or_runtime_entry() -> None:
    route_root = REPO_ROOT / "services/agent_runtime"
    text = "\n".join(
        (route_root / name).read_text(encoding="utf-8")
        for name in (
            "integrated_bus_graph.py",
            "integrated_bus_runner.py",
            "integrated_bus_worker_daemon.py",
            "task_entry_claim.py",
        )
    ).lower()
    for forbidden in (
        r"desktop\新系统".lower(),
        "open codex s hardmode.lnk",
        "rootintentloop",
        "xinao_clean_runtime",
    ):
        assert forbidden not in text, forbidden


def test_runtime_proof_stays_out_of_repository_root() -> None:
    assert not (REPO_ROOT / "integrated_bus_proof.txt").exists()
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "integrated_bus_proof.txt" in gitignore


def test_memory_server_is_isolated_from_retired_or_hosted_backends() -> None:
    text = (REPO_ROOT / "services/mcp/xinao_memory_mcp_server.py").read_text(encoding="utf-8")
    assert "local_mem0_store" in text
    for forbidden in (
        "services.agent_runtime",
        "materials/",
        "MemoryClient",
        "MEM0_API_KEY",
        "chromadb",
    ):
        assert forbidden not in text


def test_project_agreement_keeps_capabilities_available_but_activation_adaptive() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "availability as the hard default and activation as adaptive" in text
    assert "Do not impose a fixed score, lane count, or mandatory sequence" in text
    assert "decode “收口” as bounded review" in text


def test_project_agreement_has_control_plane_incident_tripwires() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "continuous execution is episodic and checkpoint-based",
        "no helper may veto a normal turn boundary",
        "adopt a session without a newer fenced ownership generation",
        "predeclared finite time, turn, and action/tool-call budgets",
        "incident circuit breaker",
        "freezes related automation before passive forensics",
        "Static fixtures are admission specifications, not runtime evidence",
    ):
        assert required in text, required


def test_project_agreement_requires_user_named_incident_lifecycle_without_new_authority() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "A user-named incident",
        "without granting new authority or proving cause/severity",
        "iteratively refresh current official-primary-source comparisons",
        "adaptive re-entrant evidence lenses",
        "a user stop cancels every phase including pending memory writes",
    ):
        assert required in text, required


def test_current_retained_executable_roots_have_no_known_retired_continuity_tokens() -> None:
    text = _executable_text().lower()
    for forbidden in (
        "xinao-continuity",
        "codex_continuity_already_running",
        "register-scheduledtask",
        "new-scheduledtasktrigger",
    ):
        assert forbidden not in text, forbidden


def test_control_plane_incident_eval_covers_required_negative_cases() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/control_plane_incident/cases.json").read_text(encoding="utf-8")
    )
    assert fixture["gate"] == "all_cases_must_pass_before_any_continuity_control_plane_canary"
    assert fixture["evidence_contract"]["static_fixture_is_runtime_evidence"] is False
    assert fixture["evidence_contract"]["fresh_process_required_for_restart_cases"] is True
    assert set(fixture["evidence_contract"]["required_per_case"]) == {
        "candidate_id",
        "candidate_hash",
        "operation_id",
        "pre_state",
        "observations",
        "post_state",
        "verdict",
    }
    assert fixture["canary_admission"]["requires_exact_candidate_identity"] is True
    assert fixture["canary_admission"]["requires_all_case_runtime_evidence"] is True
    assert set(fixture["canary_admission"]["episode_budget_fields"]) == {
        "max_duration",
        "max_turns",
        "max_actions_or_tool_calls",
    }
    assert set(fixture["canary_admission"]["canary_fields"]) == {
        "baseline_or_control",
        "attributable_metrics",
        "success_thresholds",
        "abort_thresholds",
        "observation_window",
    }
    case_list = fixture["cases"]
    cases = {case["id"]: case for case in case_list}
    assert len(cases) == len(case_list)
    required = {
        "NEG_StopHook_MustYieldAcrossTurns",
        "NEG_PauseFence_DominatesAllActions",
        "NEG_RollbackTombstone_PreventsGuardianResurrection",
        "NEG_MissingOrCorruptControl_FailsClosed",
        "NEG_NonCodexPreferredPid_CannotBecomeOwner",
        "NEG_FullFenceMismatch_NeverKills",
        "NEG_UnleasedDescendant_NeverKilled",
        "NEG_Recovery_IsSingleFlightAndDeduplicated",
        "NEG_ProtectedCanonicalShortcut_NotRecoveryTransport",
        "NEG_BackgroundObserver_HasNoVisibleOrResourceStorm",
        "NEG_UserHarm_TripsIncidentCircuitBreaker",
        "NEG_NonLivenessStates_NeverTriggerRecovery",
        "NEG_ContinuousIntent_DoesNotMutateControlPlane",
        "NEG_Takeover_AtomicallyFencesOlderGeneration",
        "NEG_Canary_RequiresDeclaredControlThresholdsAndDualOutcome",
    }
    assert required == set(cases)
    assert all(set(case) == {"id", "setup", "expected", "prohibited_effects"} for case in case_list)
    assert all(case["setup"] for case in cases.values())
    assert all(case["expected"] for case in cases.values())
    assert all(case["prohibited_effects"] for case in cases.values())


def test_incident_postmortem_has_reviewable_governance_and_runtime_gate_boundary() -> None:
    text = (
        REPO_ROOT / "docs/current/CODEX_CONTINUITY_INCIDENT_POSTMORTEM_2026-07-11.md"
    ).read_text(encoding="utf-8")
    for required in (
        "作者：",
        "独立复核：",
        "## 证据时间线",
        "REC-C05-TRANSPORT",
        "REC-C05-EXACT-RESUME",
        "REC-C06-REMOTE",
        "15 个负面案例",
        "static fixture 不是 runtime evidence",
        "https://kubernetes.io/docs/concepts/workloads/pods/probes/",
        "C-07",
        "CODEX_INCIDENT_RESPONSE_LIFECYCLE_2026-07-11.md",
    ):
        assert required in text, required


def test_incident_response_lifecycle_eval_schema_and_case_coverage() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/incident_response_lifecycle/cases.json").read_text(encoding="utf-8")
    )
    assert fixture["schema_version"] == "xinao.incident_response_lifecycle_eval.v1"
    assert fixture["gate"] == "all_lifecycle_cases_require_runtime_evidence_before_incident_closure"
    assert fixture["evidence_contract"]["static_fixture_is_runtime_evidence"] is False
    assert fixture["evidence_contract"]["runtime_evidence_required_for_closure"] is True
    assert fixture["lifecycle_contract"]["adaptive_and_reentrant"] is True
    assert fixture["lifecycle_contract"]["user_named_incident_is_proven_cause_or_severity"] is False
    assert fixture["lifecycle_contract"]["user_named_incident_creates_mutation_authority"] is False
    assert fixture["lifecycle_contract"]["single_incident_auto_promotes_global_rules"] is False
    case_list = fixture["cases"]
    cases = {case["id"]: case for case in case_list}
    assert len(cases) == len(case_list)
    required = {
        "LIFE_UserNamedIncident_OpensLifecycleWithoutVerdict",
        "LIFE_ObservedRegression_TripsCircuitBreaker",
        "LIFE_Stabilization_PrecedesRemediation",
        "LIFE_Authority_RecheckedForEveryMutation",
        "LIFE_MaturityResearch_IsIterativeCurrentAndDecisionRelevant",
        "LIFE_Recovery_IsScopedAndRuntimeVerified",
        "LIFE_RemediationImpact_ReentersAsChildIncident",
        "LIFE_Postmortem_IsEvidenceLedBlamelessAndReviewed",
        "LIFE_MemoryDistillation_IsNarrowNonAuthoritative",
        "LIFE_OneIncident_CannotAutoPromoteGlobalPolicy",
        "LIFE_CorrectiveRepair_RequiresPositiveAndNegativeRegression",
        "LIFE_GlobalCoherence_IsScopedAndReal",
        "LIFE_StaticSpecification_CannotCloseRuntimeIncident",
        "LIFE_TerminalStatus_IsPerObjectAndHonest",
        "LIFE_UserStopOrNewHarm_PreemptsLifecycle",
    }
    assert set(cases) == required
    expected_fields = set(fixture["case_required_fields"])
    assert expected_fields == {
        "id",
        "trigger",
        "expected",
        "required_evidence",
        "prohibited_effects",
    }
    assert all(set(case) == expected_fields for case in case_list)
    assert all(case["required_evidence"] for case in case_list)
    assert all(case["prohibited_effects"] for case in case_list)


def test_incident_memory_contract_is_narrow_non_authoritative() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/incident_response_lifecycle/cases.json").read_text(encoding="utf-8")
    )
    memory = fixture["memory_contract"]
    assert memory["durable_write_requires_explicit_user_request"] is True
    assert memory["user_named_incident_alone_authorizes_durable_write"] is False
    assert memory["memory_is_instruction_or_authorization"] is False
    assert set(memory["verified_lesson_fields"]) == {
        "trigger",
        "observed_impact",
        "evidenced_cause",
        "narrow_next_time_action",
        "provenance",
        "scope",
        "confidence",
        "verified_at",
        "supersedes_or_expiry",
    }
    forbidden_keys = {
        "authority_grant",
        "commands",
        "scripts",
        "raw_transcript",
        "raw_log",
        "raw_reasoning",
        "secrets",
    }
    assert not (_nested_keys(fixture) & forbidden_keys)
    assert set(memory["forbidden_content"]) == {
        "secrets or credential values",
        "raw transcript",
        "raw terminal log",
        "raw reasoning or chain of thought",
        "executable external instruction",
        "blame or unverified allegation",
        "authorization grant",
    }
    memory_case = next(
        case
        for case in fixture["cases"]
        if case["id"] == "LIFE_MemoryDistillation_IsNarrowNonAuthoritative"
    )
    assert "current user explicitly requests a memory update" in memory_case["trigger"]


def test_generic_lifecycle_and_continuity_canary_fixtures_are_independent() -> None:
    lifecycle = json.loads(
        (REPO_ROOT / "evals/incident_response_lifecycle/cases.json").read_text(encoding="utf-8")
    )
    continuity = json.loads(
        (REPO_ROOT / "evals/control_plane_incident/cases.json").read_text(encoding="utf-8")
    )
    lifecycle_ids = {case["id"] for case in lifecycle["cases"]}
    continuity_ids = {case["id"] for case in continuity["cases"]}
    assert lifecycle["schema_version"] != continuity["schema_version"]
    assert lifecycle["gate"] != continuity["gate"]
    assert len(lifecycle_ids) == len(continuity_ids) == 15
    assert lifecycle_ids.isdisjoint(continuity_ids)


def test_incident_lifecycle_requires_iterative_bounded_primary_source_comparison() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/incident_response_lifecycle/cases.json").read_text(encoding="utf-8")
    )
    research = fixture["research_contract"]
    assert research["current_official_primary_sources_required"] is True
    assert research["initial_lookup_required"] is True
    assert research["fixed_search_count_or_cadence"] is False
    assert len(research["refresh_on"]) >= 6
    assert set(research["evidence_fields"]) == {
        "question",
        "retrieved_at",
        "official_url_or_version",
        "supported_claim",
        "local_inference",
        "decision_effect",
    }
    text = (REPO_ROOT / "docs/current/CODEX_INCIDENT_RESPONSE_LIFECYCLE_2026-07-11.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "外部成熟对照的重复触发",
        "不按时间或日志数量实现",
        "来源只支持候选决策，不授予动作权限",
        "不是固定工具链、固定代理数、定时循环或第二运行时",
    ):
        assert required in text, required


def test_runtime_incident_cannot_close_from_static_fixture_or_merge_object_status() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/incident_response_lifecycle/cases.json").read_text(encoding="utf-8")
    )
    cases = {case["id"]: case for case in fixture["cases"]}
    static_case = cases["LIFE_StaticSpecification_CannotCloseRuntimeIncident"]
    status_case = cases["LIFE_TerminalStatus_IsPerObjectAndHonest"]
    child_case = cases["LIFE_RemediationImpact_ReentersAsChildIncident"]
    assert "closure from static fixture" in static_case["prohibited_effects"]
    assert "per-object verdict" in status_case["required_evidence"]
    assert "child incident ID" in child_case["required_evidence"]
