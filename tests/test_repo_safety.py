from __future__ import annotations

import ast
import hashlib
import json
import os
import queue
import subprocess
import threading
import tomllib
from pathlib import Path

import yaml

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
    "action_resume_receipt.py",
    "audit_adjudication.py",
    "carrier_identity.py",
    "closure_test_activities.py",
    "closure_test_proof.py",
    "codex_inner_profile_consumer.py",
    "codex_rollout_token_analyzer.py",
    "context_slice_manifest.py",
    "direct_worker_pool_common_adapter.py",
    "dispatch_economics.py",
    "codex_s_worker_lane_carrier.py",
    "default_plus_dynamic_escalate.py",
    "dp_sidecar_execution_port.py",
    "execution_contract.py",
    "grok_build_docker_worker.py",
    "grok_execution_contract_adapter.py",
    "integrated_bus_bus_nodes.py",
    "integrated_bus_facade_redirect.py",
    "integrated_bus_graph.py",
    "integrated_bus_litellm_langfuse.py",
    "integrated_bus_mem0_oss.py",
    "integrated_bus_parent_workflow.py",
    "integrated_bus_promotion_gate.py",
    "integrated_bus_runner.py",
    "integrated_bus_temporal_verify.py",
    "integrated_bus_worker_daemon.py",
    "integrated_bus_workflow_registry.py",
    "lexicon_cn_escape.py",
    "overnight_local_search.py",
    "outcome_boundary_preflight.py",
    "pro_review_after_draft.py",
    "provider_routing_preference.py",
    "quota_dispatch_epoch.py",
    "quota_capacity_adapter.py",
    "routing_policy_reader.py",
    "selector_release.py",
    "session_frontier_projection.py",
    "supervisor_worker_selector.py",
    "system_awareness_consumer.py",
    "task_entry_claim.py",
    "temporal_codex_task_workflow.py",
    "thin_bootstrap_sandbox.py",
    "thin_evidence_writer.py",
    "thin_glue_intake.py",
    "thin_glue_l3_execute.py",
    "thin_glue_l4_search.py",
    "thin_glue_l5_opa.py",
    "thin_glue_l5_openlineage.py",
    "worker_repo_mount_identity.py",
    "thin_glue_l5_verify.py",
    "thin_glue_l6_self_heal.py",
    "thin_glue_l7_dvc.py",
    "thin_glue_l7_mlflow.py",
    "thin_glue_l7_optuna.py",
    "thin_glue_l7_wandb.py",
    "thin_glue_l8_token_stack.py",
    "thin_glue_l9_ledger.py",
    "thin_glue_provider_scheduler.py",
    "thin_glue_rg_utils.py",
    "thin_glue_stack.py",
    "thin_glue_sunset_registry.py",
    "thin_glue_work_proof.py",
    "thin_langgraph_closure.py",
    "thin_provider_client.py",
    "tool_table_coverage.py",
    "work_unit_lifecycle.py",
}


def _tracked_baseline_files() -> list[Path]:
    """Return the tracked baseline in a live checkout or its frozen raw snapshot."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [
            REPO_ROOT / relative.decode("utf-8", errors="surrogateescape")
            for relative in result.stdout.split(b"\0")
            if relative
        ]

    snapshot_manifest = REPO_ROOT.parent / "source-snapshot.v1.json"
    assert snapshot_manifest.is_file(), result.stderr.decode("utf-8", errors="replace")
    snapshot = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == "xinao.behavior_regression_source_snapshot.v1"
    assert Path(snapshot["raw_root"]).resolve() == REPO_ROOT
    return [REPO_ROOT / row["path"] for row in snapshot["raw_files"]]


def _assert_identity_absent_from_tracked_baseline(identity: str) -> None:
    needle = identity.encode("utf-8")
    matches: list[str] = []
    for path in _tracked_baseline_files():
        # `git ls-files` also lists an intentionally deleted tracked path until
        # the deletion is committed.  The live working tree is the object under
        # test; a removed file cannot carry a reachable identity.
        if not path.is_file():
            continue
        content = path.read_bytes()
        if b"\0" not in content and needle in content:
            matches.append(path.relative_to(REPO_ROOT).as_posix())
    assert not matches, f"{identity}: {matches}"


def _executable_text() -> str:
    chunks: list[str] = []
    for root in EXECUTABLE_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _project_agreement_contract_text() -> str:
    """Return the hot routing shell plus its versioned on-demand contract."""
    hot_path = REPO_ROOT / "AGENTS.md"
    cold_path = REPO_ROOT / "docs/current/CODEX_S_PROJECT_AGREEMENT_COLD_2026-07-13.md"
    hot = hot_path.read_text(encoding="utf-8")
    assert cold_path.relative_to(REPO_ROOT).as_posix() in hot
    cold = cold_path.read_text(encoding="utf-8")
    assert "SENTINEL:S_GENERIC_ENGINEERING_COLD_INCIDENT_V2" in cold
    return f"{hot}\n\n{cold}"


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


def test_retired_platform_carriers_are_absent() -> None:
    for relative in (
        "projects/dual-brain-coordination/scripts/run_grok_background_" + "window_canary.py",
        "scripts/manage_platform_" + "capacity_schedule.py",
        "services/agent_runtime/openhands_execution_" + "activity.py",
        "services/agent_runtime/openhands_execution_" + "contract.py",
        "services/agent_runtime/openhands_execution_" + "worker.py",
        "services/agent_runtime/platform_capacity_" + "maintenance.py",
        "services/agent_runtime/platform_control_" + "worker.py",
        "services/mcp/xinao_sandbox_" + "mcp_server.py",
    ):
        assert not (REPO_ROOT / relative).exists(), relative


def test_retired_platform_identities_are_absent_from_tracked_baseline() -> None:
    retired_identities = (
        "mowei-" + "zhixing",
        "xinao-platform-" + "capacity-daily-v1",
        "xinao_sandbox_" + "mcp_server",
        "openhands_execution_" + "activity",
        "platform_control_" + "worker",
    )
    for retired_identity in retired_identities:
        _assert_identity_absent_from_tracked_baseline(retired_identity)


def test_retired_backing_repo_identity_is_absent_from_tracked_baseline() -> None:
    retired_identity = "nianhua-new-" + "route-active"
    _assert_identity_absent_from_tracked_baseline(retired_identity)


def test_agent_runtime_only_contains_declared_hot_path_and_support_modules() -> None:
    actual = {path.name for path in (REPO_ROOT / "services/agent_runtime").glob("*.py")}
    assert actual == ALLOWED_AGENT_RUNTIME_MODULES


def test_agent_runtime_cannot_commit_the_worktree() -> None:
    route_files = sorted((REPO_ROOT / "services/agent_runtime").glob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in route_files).lower()
    assert "git_commit_all" not in text
    mutating_git_commands = {"init", "add", "commit"}
    violations: list[str] = []
    for path in route_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "add"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "git"
            ):
                violations.append(f"{path.name}:{node.lineno}:GitPython add")
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "commit"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "index"
            ):
                violations.append(f"{path.name}:{node.lineno}:GitPython commit")
            if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)):
                continue
            values = [
                item.value
                for item in node.args[0].elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if len(values) >= 2 and values[0] == "git" and values[1] in mutating_git_commands:
                violations.append(f"{path.name}:{node.lineno}:git {values[1]}")
    assert violations == []
    assert "gitpython_readonly" in text


def test_project_hot_entry_points_to_generic_engineering_substrate() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contract = REPO_ROOT / "docs" / "tool_glue" / "GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md"
    retired_projection = REPO_ROOT / "docs" / "tool_glue" / "SOFTWARE_TOOL_GLUE_CURRENT.md"
    assert "docs/tool_glue/GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md" in agreement
    assert "S 不是科学父目标" in agreement
    assert "S 不能决定科学是否开始、研究什么、是否值得继续或何时完成" in agreement
    contract_text = contract.read_text(encoding="utf-8")
    assert "SENTINEL:GENERIC_ENGINEERING_SUBSTRATE_CURRENT_V1" in contract_text
    assert "不定义任何科学父意图" in contract_text
    assert "工程入口只保证运行边界和事实血缘，不建立科学准入法院" in contract_text
    assert "scripts/preflight_outcome_boundary.py" in contract_text
    assert "不是语义安全证明、科学准入器或 Reveal 授权" in contract_text
    assert "WAIT_FOR_REAL_TARGET" not in contract_text
    assert "biased-urn" not in contract_text
    assert not retired_projection.exists()


def test_cross_seam_contract_is_generic_execution_truth_not_science_routing() -> None:
    text = (
        REPO_ROOT / "docs" / "tool_glue" / "CROSS_SEAM_EXECUTION_ENVELOPE_CURRENT.md"
    ).read_text(encoding="utf-8")
    assert "SENTINEL:CROSS_SEAM_EXECUTION_ENVELOPE_CURRENT_V2" in text
    assert "GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md" in text
    assert "本协议不创造任务授权、科学问题、科学路线" in text
    assert "caller/Owner 在本协议之前选择任务、工人和 transport" in text
    for stale_router in (
        "xinao-native-research",
        "无明确其他任务时默认进入",
        "默认工人身份",
        "《软件工具胶水宪法》",
        "父主线",
    ):
        assert stale_router not in text


def test_intent_continuity_baseline_reduces_burden_without_routing_science() -> None:
    model = json.loads(
        (
            REPO_ROOT
            / "evals"
            / "intent_continuity_baseline"
            / "decision_model.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert model["sentinel"] == "SENTINEL:INTENT_CONTINUITY_BASELINE_V1"
    assert model["authority"] is False
    assert model["not_a_runtime_gate"] is True
    assert model["not_a_science_router"] is True
    assert set(model["zero_beat"]) == {
        "parent_result_and_user_burden",
        "active_subject_and_object",
        "means_versus_endpoint",
        "user_codex_worker_tool_and_consumer_roles",
        "observable_completion_ruler",
        "authorization_and_pause_stop_boundary",
    }
    graph = model["current_intent_object_graph"]
    assert graph["shape"] == "typed_graph_with_a_minimal_current_tree_projection"
    assert graph["relational_levels"] == [
        "human_practice",
        "parent_result",
        "current_frame",
        "approach_or_capability",
        "responsibility",
        "runtime_carrier",
        "consumer_effect",
    ]
    assert "levels_are_assigned_by_the_current_relation_not_by_noun_or_file_type" in graph[
        "admission_rules"
    ]
    assert "an_action_requires_an_upward_service_path_to_the_current_parent_result" in graph[
        "admission_rules"
    ]
    assert "a_completion_claim_requires_a_downward_path_to_real_consumer_effect_and_readback" in graph[
        "admission_rules"
    ]
    economy = model["context_economy"]
    assert economy["forbidden_shape"] == "per_turn_full_PDM_dump_or_second_model_call"
    assert economy["hot_layer"].startswith("global_AGENTS")
    assert "worker_return" in economy["reanchor_events"]
    assert "completion_claim" in economy["reanchor_events"]
    compilation = model["utterance_to_intent_compilation"]
    assert compilation["user_speech_role"] == (
        "situated_increment_not_an_engineering_specification"
    )
    assert compilation["mature_domain_and_engineering_role"].startswith(
        "derive_facts_means_dependencies"
    )
    unified = model["unified_user_result_productivity_admission"]
    assert unified["not_a_new_controller_or_skill"] is True
    assert unified["admission_order"] == [
        "parent_intent_conservation",
        "real_activity_and_consumer_backward_first_principles",
        "productivity_among_semantically_and_materially_legal_candidates",
        "real_risk_and_consumer_bound_safety_or_formality",
        "bounded_decision_closure_and_defeater_search",
    ]
    assert unified["first_principles"]["return_rule"].startswith(
        "when_the_finite_foundation_is_sufficient"
    )
    assert unified["productivity"]["role"].startswith(
        "selection_among_already_legal_candidates"
    )
    assert unified["real_risk_and_anti_formalism"]["formality_admission"].startswith(
        "documents_schemas_checks_approvals"
    )
    closure = model["bounded_decision_closure_assurance"]
    assert {
        "execute",
        "no_action",
        "ask_user",
        "wait_or_defer",
        "retry",
        "abandon",
        "hand_back_to_user",
        "end_turn",
    } <= set(closure["control_decision_family"])
    assert {
        "unsafe_if_provided",
        "unsafe_if_not_provided",
        "unsafe_timing_or_order",
        "continued_too_long_or_stopped_too_early",
    } <= set(closure["symmetric_risk_guidewords"])
    assert closure["ordinary_path"].startswith("do_not_expand_the_full_graph")
    assert "new_failure_family" in closure["independent_defeater_search_when"]
    task_control = model["active_task_continuation_advisory"]
    assert task_control["task_source_rule"].startswith(
        "effect_bearing_work_requires_a_named_task"
    )
    assert task_control["observed_state_rule"].startswith(
        "cwd_STATUS_reports_tests_packages_worker_results"
    )
    assert task_control["permission_rule"].startswith(
        "ordinary_authorized_reads_writes_tests"
    )
    assert task_control["restore_failure_rule"].startswith(
        "fail_open_to_current_user_words_and_live_facts"
    )
    assert "select_a_scientific_question_or_next_action" in model["continuity_must_not"]
    assert (
        model["failure_semantics"]["missing_stale_or_conflicting_continuity"]
        == "fail_open_from_current_words_and_live_facts"
    )

    registry = json.loads(
        (REPO_ROOT / "evals" / "suite_registry.v1.json").read_text(encoding="utf-8")
    )
    assert (
        registry["loops"]["behavior"]["intent_decision_model"]
        == "evals/intent_continuity_baseline/decision_model.v1.json"
    )
    assert "context_intent_alignment" not in {
        item["id"] for item in registry["live_agent_suites"]
    }
    assert "parent_frame_admission" in {
        item["id"] for item in registry["live_agent_suites"]
    }
    assert "context_intent_alignment" in {
        item["id"] for item in registry["retired_compatibility_suites"]
    }

    runner = (REPO_ROOT / "scripts" / "run_behavior_regression.ps1").read_text(
        encoding="utf-8"
    )
    snapshot = (
        REPO_ROOT / "scripts" / "prepare_behavior_regression_snapshot.py"
    ).read_text(encoding="utf-8")
    assert "$runContext" not in runner
    assert "evals\\context_intent_alignment" not in runner
    assert "'deep', 'context', 'proactive'" not in runner
    assert '"context": False' in snapshot

    readme = (REPO_ROOT / "evals" / "behavior_regression" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "currently inventories 45" in readme
    assert "-Profile context" not in readme

    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docs/tool_glue/GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md" in attributes
    assert "docs/tool_glue/SOFTWARE_TOOL_GLUE_CURRENT.md" not in attributes

    this_test = Path(__file__).read_text(encoding="utf-8")
    retired_dead_function = "def _retired_" + "context_intent_alignment"
    assert retired_dead_function not in this_test


def test_docker_worker_rules_bind_only_generic_engineering_sources() -> None:
    source = (
        REPO_ROOT / "services" / "agent_runtime" / "grok_build_docker_worker.py"
    ).read_text(encoding="utf-8")
    assert 'Path("/app/AGENTS.md")' in source
    assert 'Path("/app/docs/tool_glue/GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md")' in source
    assert 'Path("/mainline/' not in source
    assert "Codex_Situation_Island/contracts/working_agreement.md" not in source


def test_thin_context_does_not_delete_visible_desktop_mainline() -> None:
    agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contract = (
        REPO_ROOT / "docs" / "tool_glue" / "GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md"
    ).read_text(encoding="utf-8")
    assert "C 主线只保留用户可理解和修改的薄掌控面" in agreement
    assert "不得触碰 `C:\\Users\\xx363\\Desktop\\历史备用 不动`" in agreement
    assert "C 只承载用户可见入口和必要句柄" in contract
    for duplicated_lifecycle_detail in (
        "publish-worktree-record",
        "services/agent_runtime/execution_consumers.v1.json",
    ):
        assert duplicated_lifecycle_detail not in agreement


def test_grok_worker_pool_runtime_is_independent_of_retired_admin_workspace() -> None:
    registry = json.loads(
        (REPO_ROOT / "services" / "agent_runtime" / "execution_consumers.v1.json").read_text(
            encoding="utf-8"
        )
    )
    direct_consumers = {
        item["consumer_id"]: item["source_path"]
        for item in registry["consumers"]
        if item["consumer_id"]
        in {"direct_grok_composer25_worker", "direct_grok_worker_pool"}
    }
    assert set(direct_consumers) == {
        "direct_grok_composer25_worker",
        "direct_grok_worker_pool",
    }
    assert all(
        path.startswith("D:/XINAO_RESEARCH_RUNTIME/tools/grok-worker-pool/bridge/")
        for path in direct_consumers.values()
    )
    assert all("Grok_Admin_Isolated/workspace" not in path for path in direct_consumers.values())

    cleanup_paths = json.loads(
        (REPO_ROOT / "plugins" / "safe-cleanup" / "config" / "protected_paths.json").read_text(
            encoding="utf-8"
        )
    )
    assert r"D:\XINAO_RESEARCH_RUNTIME\tools\grok-worker-pool" in cleanup_paths[
        "protected_subtrees"
    ]
    assert r"C:\Users\xx363\.grok-bg-workers" in cleanup_paths["protected_subtrees"]
    assert r"C:\Users\xx363\.codex-s-hardmode-account-b" in cleanup_paths[
        "protected_subtrees"
    ]
    assert r"C:\Users\xx363\CodexLaunchers" in cleanup_paths["protected_subtrees"]
    assert r"D:\Grok_Admin_Isolated\workspace" not in cleanup_paths["git_roots"]
    assert r"C:\Users\xx363\Grok_Admin_Isolated\workspace" not in cleanup_paths[
        "git_roots"
    ]


def test_live_grok_worker_runtime_uses_active_generic_contract_when_installed() -> None:
    runtime_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\grok-worker-pool")
    manifest_path = runtime_root / "runtime-manifest.v1.json"
    launcher_path = Path(r"C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1")
    if not manifest_path.is_file() or not launcher_path.is_file():
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "xinao.grok_worker_pool_runtime_manifest.v1"
    declared = {item["path"]: item["sha256"] for item in manifest["files"]}
    assert len(declared) == 15
    bridge_root = Path(manifest["bridge_root"])
    for name, expected_sha256 in declared.items():
        source = bridge_root / name
        assert source.is_file(), name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_sha256

    worker_text = (bridge_root / "Invoke-GrokComposer25Worker.ps1").read_text(
        encoding="utf-8"
    )
    launcher_text = launcher_path.read_text(encoding="utf-8")
    assert "GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md" in worker_text
    assert "软件工具胶水宪法_当前有效.txt" not in worker_text
    assert "Grok_Admin_Isolated\\workspace" not in launcher_text
    assert "Assert-CodexGrokWorkerRuntime" in launcher_text

    auth_helper = bridge_root / "GrokAuthenticatedCatalogRefresh.ps1"
    quoted_helper = str(auth_helper).replace("'", "''")
    classifier_check = subprocess.run(
        [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f". '{quoted_helper}'; "
                "$bare401 = Test-GrokAuthenticatedCatalogRefreshResultAuthRequired "
                "-RefreshResult ([pscustomobject]@{ exit_code=1; stderr='HTTP 401 unauthorized' }); "
                "$revoked = Test-GrokAuthenticatedCatalogRefreshResultAuthRequired "
                "-RefreshResult ([pscustomobject]@{ exit_code=1; stderr='invalid_grant: RefreshTokenRejected' }); "
                "if ($bare401 -or -not $revoked) { exit 1 }"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert classifier_check.returncode == 0, classifier_check.stderr

    skill_path = Path(
        r"C:\Users\xx363\.codex\skills\dispatch-grok-worker-pool\SKILL.md"
    )
    if skill_path.is_file():
        skill_text = skill_path.read_text(encoding="utf-8")
        assert "SelectionOnly success" in skill_text
        assert "oauth_allowed=true" in skill_text
        assert "Access-token age" in skill_text
        assert "directed\ncritic" in skill_text
        assert "minimal delta" in skill_text
        assert "not a scientific worker role" in skill_text
        assert "generic WorkerPool transport profile" in skill_text

    oauth_wrapper = Path(
        r"C:\Users\xx363\CodexLaunchers\Invoke-GrokWorkerOAuthRecovery.ps1"
    )
    assert oauth_wrapper.is_file()
    oauth_text = oauth_wrapper.read_text(encoding="utf-8")
    assert "SelectionOnly success is a hard OAuth veto" in oauth_text
    assert "GROK_WORKER_OAUTH_FORBIDDEN_AFTER_RECHECK" in oauth_text
    assert "grok-bg-workers" in oauth_text
    assert 'profile_identity = "generic_workerpool_transport"' in oauth_text
    assert "profile_role_authority = $false" in oauth_text
    assert "worker_transport_auth_present" in oauth_text


def test_shared_worker_skills_preserve_preclosure_independence_when_installed() -> None:
    skill_root = Path(r"C:\Users\xx363\.codex\skills")
    paths = {
        "amplify": skill_root / "amplify-supervisor-worker" / "SKILL.md",
        "dispatch": skill_root / "dispatch-grok-worker-pool" / "SKILL.md",
        "repair": skill_root / "repair-agent-behavior" / "SKILL.md",
    }
    if not all(path.is_file() for path in paths.values()):
        return

    amplify = paths["amplify"].read_text(encoding="utf-8")
    dispatch = paths["dispatch"].read_text(encoding="utf-8")
    repair = paths["repair"].read_text(encoding="utf-8")
    amplify_words = " ".join(amplify.split())
    assert "Owner locks the first candidate" in amplify
    assert (
        "directed red-team review rather than independent problem formation"
        in amplify_words
    )
    assert "Independence is also a timing and prompt-provenance claim" in dispatch
    assert "recommend rollback/removal/no-action" in dispatch
    assert "高杠杆候选是否由 Owner 先行封闭" in repair
    assert "确定性小任务不会被强制增加第二模型" in repair


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
def test_grok_mcp_bundle_excludes_unconfigured_vulnerable_endpoints() -> None:
    runtime = REPO_ROOT / "projects/dual-brain-coordination/provisioning/grok-mcp-runtime"
    package = json.loads((runtime / "package.json").read_text(encoding="utf-8"))
    dependencies = set(package["dependencies"])
    assert dependencies.isdisjoint(
        {
            "@modelcontextprotocol/server-github",
            "@wonderwhy-er/desktop-commander",
        }
    )

    surface = (
        REPO_ROOT
        / "projects/dual-brain-coordination/provisioning/grok-background-tool-surface.v1.toml"
    ).read_text(encoding="utf-8")
    assert "[mcp_servers.commander]\nenabled = false" in surface
    assert "[mcp_servers.github]" not in surface


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
    text = _project_agreement_contract_text()
    assert "不要求固定 provider、工人数、工具顺序、lane、平台或全量验证" in text
    assert "选择由当前任务适配性、风险、证据增量、可逆性和汇流成本决定" in text
    assert "通用工程能力可以服务科学，但不能取得科学路由或完成身份" in text


def test_project_agreement_orients_on_live_context_without_approval_theater() -> None:
    text = _project_agreement_contract_text()
    for required in (
        "当前用户请求定义对象、结果、授权与 Stop",
        "live 仓库、进程、接口和消费者定义技术事实",
        "不能产生授权",
        "不是热入口、科学父稿、恢复队列或第二控制面",
        "只修相交依赖锥",
    ):
        assert required in text, required


def test_fresh_promptfoo_codex_sessions_do_not_run_interactive_hooks() -> None:
    config_paths = (
        "evals/codex_capability/promptfooconfig.yaml",
        "evals/parent_frame_admission/promptfooconfig.yaml",
        "evals/mature_capability_recall/promptfooconfig.live.yaml",
        "evals/mature_capability_recall/promptfooconfig.yaml",
        "evals/proactive_mature_first/promptfooconfig.yaml",
        "evals/thin_localization/promptfooconfig.yaml",
        "evals/native_subagent_trajectory/promptfooconfig.yaml",
    )
    for relative_path in config_paths:
        config = yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        provider = config["providers"][0]
        assert provider["id"] == "openai:codex-app-server", relative_path
        provider_config = provider["config"]
        assert provider_config["reuse_server"] is False, relative_path
        expected_features = {"hooks": False}
        if relative_path == "evals/native_subagent_trajectory/promptfooconfig.yaml":
            expected_features["multi_agent"] = True
            expected_features["multi_agent_v2"] = True
            assert provider_config["include_raw_events"] is True
            assert provider_config["ephemeral"] is True
        assert provider_config["cli_config"] == {"features": expected_features}, relative_path


def test_eval_runners_inherit_the_active_codex_account_profile() -> None:
    runners = (
        "run_behavior_regression.ps1",
        "run_parent_frame_admission_eval.ps1",
        "run_codex_capability_eval.ps1",
        "run_proactive_mature_first_eval.ps1",
        "run_open_world_reuse_eval.ps1",
        "run_self_evolution_eval_battery.ps1",
    )
    for name in runners:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8-sig")
        assert "if ($env:CODEX_HOME) { $env:CODEX_HOME }" in text, name
        assert "else { Join-Path $HOME '.codex' }" in text, name

    regression = (REPO_ROOT / "scripts/run_behavior_regression.ps1").read_text(
        encoding="utf-8-sig"
    )
    battery = (REPO_ROOT / "scripts/run_self_evolution_eval_battery.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "[Guid]::NewGuid()" in regression
    assert "New-Item -ItemType Directory -Path $outputRoot -ErrorAction Stop" in regression
    assert "[Guid]::NewGuid()" in battery
    assert "New-Item -ItemType Directory -Path $batteryRoot -ErrorAction Stop" in battery


def test_ci_verifies_each_consolidated_project_in_its_locked_environment() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "project-verify:",
        "dual-brain-coordination",
        "runs-on: ${{ matrix.os }}",
        "os: windows-latest",
        "os: ubuntu-latest",
        "path: projects/dual-brain-coordination",
        "working-directory: ${{ matrix.path }}",
        "pytest_args: -q",
        "Install pinned AMQ prerequisite",
        "amq_0.42.0_windows_amd64.zip",
        "E155F108C1ACFB23EE0245E6CA1A89BFFBB886B45B1F8A309D98CF162F457EC3",
        "CCC3F59F00C8DD461E80229A38828703A229B77530B6810E620B0BB49E5DD9CE",
        "uv sync --frozen",
        "uv run ruff check ${{ matrix.ruff_paths }}",
        "uv run ruff format --check ${{ matrix.ruff_paths }}",
        "uv run pytest ${{ matrix.pytest_args }}",
    ):
        assert required in workflow, required


ROOT_CI_HYGIENE_PATHS = (
    "services",
    "scripts",
    "tests",
)
ROOT_HYGIENE_COMMANDS = (
    "uv run ruff check services scripts tests",
    "uv run ruff format --check services scripts tests",
    "uv run python -m compileall -q services scripts tests",
)


def test_ci_root_hygiene_job_is_single_platform_and_not_duplicated_in_pytest_matrix() -> None:
    """Root Ruff/format/compileall run once; OS matrix keeps pytest only."""
    workflow_text = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    assert "root-hygiene" in jobs
    assert "verify" in jobs
    assert "project-verify" in jobs

    root = jobs["root-hygiene"]
    assert root["runs-on"] == "ubuntu-latest"
    root_steps = "\n".join(step.get("run", "") for step in root["steps"] if isinstance(step, dict))
    for command in ROOT_HYGIENE_COMMANDS:
        assert command in root_steps, command
    assert "pytest" not in root_steps
    assert "continue-on-error:" not in workflow_text
    assert "paths-filter" not in workflow_text
    assert "dorny/paths-filter" not in workflow_text
    assert "lint_rc" in root_steps and "format_rc" in root_steps
    assert "set +e" in root_steps

    verify = jobs["verify"]
    assert verify["needs"] == "root-hygiene" or verify["needs"] == ["root-hygiene"]
    matrix_include = verify["strategy"]["matrix"]["include"]
    matrix_os = {entry["os"] for entry in matrix_include}
    assert matrix_os == {"ubuntu-latest", "windows-latest"}
    # Root pytest is sharded 3 ways per OS (six required jobs); full coverage is the union.
    assert len(matrix_include) == 6
    assert {(int(e["shard"]), int(e["shard_count"])) for e in matrix_include} == {
        (0, 3),
        (1, 3),
        (2, 3),
    }
    verify_steps = "\n".join(
        step.get("run", "") for step in verify["steps"] if isinstance(step, dict)
    )
    assert "uv run pytest -q" in verify_steps
    assert "-p scripts.pytest_shard" in verify_steps
    assert "--shard-count ${{ matrix.shard_count }}" in verify_steps
    assert "--shard-index ${{ matrix.shard }}" in verify_steps
    assert "pytest-shard-${{ matrix.shard }}" in verify_steps
    for command in ROOT_HYGIENE_COMMANDS:
        assert command not in verify_steps, f"duplicated in verify: {command}"
    assert "ruff check" not in verify_steps
    assert "ruff format" not in verify_steps
    assert "compileall" not in verify_steps

    project = jobs["project-verify"]
    assert "needs" not in project or project.get("needs") in (None, [])
    project_steps = "\n".join(
        step.get("run", "") for step in project["steps"] if isinstance(step, dict)
    )
    assert "uv run ruff check ${{ matrix.ruff_paths }}" in project_steps
    assert "uv run ruff format --check ${{ matrix.ruff_paths }}" in project_steps


def test_local_ci_hygiene_script_matches_root_and_project_cones() -> None:
    """Local entry path inventory must stay locked to workflow cones."""
    from scripts import run_ci_hygiene as hygiene

    assert hygiene.ROOT_PATHS == ROOT_CI_HYGIENE_PATHS

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["project-verify"]["strategy"]["matrix"]["include"]
    expected = []
    for entry in matrix:
        raw = entry["ruff_paths"]
        if isinstance(raw, str):
            paths = tuple(part for part in raw.replace("\n", " ").split() if part)
        else:
            paths = tuple(raw)
        expected.append((entry["project"], entry["path"], paths))
    assert list(hygiene.PROJECT_CONES) == expected

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv run python scripts/run_ci_hygiene.py" in readme
    assert "uv run python scripts/run_ci_hygiene.py --all" in readme
    assert "full remote hygiene parity" in readme.lower() or "Full remote hygiene parity" in readme
    assert "uv run ruff check services scripts tests\n" not in readme
    assert "uv run ruff format --check services scripts tests\n" not in readme
    for path in ROOT_CI_HYGIENE_PATHS:
        assert path in readme, path


def test_local_ci_hygiene_runs_lint_and_format_even_if_one_fails() -> None:
    """Control-flow: a lint failure must not skip format (no real network/install)."""
    from scripts import run_ci_hygiene as hygiene

    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_runner(argv, *, cwd=None):  # type: ignore[no-untyped-def]
        seq = tuple(argv)
        calls.append((seq, str(cwd) if cwd is not None else None))
        if seq[:4] == ("uv", "run", "ruff", "check") and "--fix" not in seq:
            return subprocess_completed(1)
        return subprocess_completed(0)

    def subprocess_completed(code: int):
        class _Proc:
            returncode = code

        return _Proc()

    results = hygiene.run_root_hygiene(
        repo_root=REPO_ROOT,
        fix=False,
        runner=fake_runner,
    )
    labels = [item.label for item in results]
    assert labels == ["root ruff check", "root ruff format", "root compileall"]
    assert results[0].returncode == 1
    assert results[1].returncode == 0
    assert results[2].returncode == 0
    assert hygiene.aggregate_returncode(results) == 1

    argv_bodies = [call[0] for call in calls]
    assert any(a[:4] == ("uv", "run", "ruff", "check") for a in argv_bodies)
    assert any(a[:5] == ("uv", "run", "ruff", "format", "--check") for a in argv_bodies)
    assert any("compileall" in a for a in argv_bodies)
    assert len(calls) == 3

    project_calls: list[tuple[str, ...]] = []

    def project_runner(argv, *, cwd=None):  # type: ignore[no-untyped-def]
        seq = tuple(argv)
        project_calls.append(seq)
        if seq[:4] == ("uv", "run", "ruff", "check") and "--fix" not in seq:
            return subprocess_completed(2)
        return subprocess_completed(0)

    project_results = hygiene.run_project_hygiene(
        repo_root=REPO_ROOT,
        fix=False,
        runner=project_runner,
    )
    assert project_results
    assert len(project_results) == len(hygiene.PROJECT_CONES) * 2
    lint_steps = [r for r in project_results if r.label.endswith("ruff check")]
    format_steps = [r for r in project_results if r.label.endswith("ruff format")]
    assert len(lint_steps) == len(format_steps) == len(hygiene.PROJECT_CONES)
    assert all(step.returncode == 2 for step in lint_steps)
    assert all(step.returncode == 0 for step in format_steps)
    assert hygiene.aggregate_returncode(project_results) == 2


def test_gitleaks_import_allowlist_is_exact_fingerprint_only() -> None:
    entries = [
        line
        for line in (REPO_ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(entries) == 29
    assert all(entry.rsplit(":", 2)[-2] == "generic-api-key" for entry in entries)
    assert all(int(entry.rsplit(":", 1)[-1]) > 0 for entry in entries)
    assert {entry.split(":", 1)[0] for entry in entries} == {
        "62b1f35759ffc4cd5b00c7aa2d5f3b44ea510374",
        "8eeb87ca223349a6b4abe882a518c7c9eeb88f4a",
        "c1b43643b38a086285611457979cd44d8e783c2a",
    }


def test_project_agreement_defers_engineering_adjudication_to_intent_live_facts_and_current_contract() -> (
    None
):
    text = _project_agreement_contract_text()
    for required in (
        "docs/tool_glue/GENERIC_ENGINEERING_SUBSTRATE_CURRENT.md",
        "当前用户请求定义对象、结果、授权与 Stop",
        "live 仓库、进程、接口和消费者定义技术事实",
        "不定义默认科学父任务、研究路线、continuous 或 Goal",
        "单一 Owner",
        "精确身份",
        "真实消费者回读",
        "事故处理从只读证据开始",
    ):
        assert required in text, required
    for retired_duplicate in (
        "Select Grok, Codex agents, or a mixed set",
        "single supervisor and writer for tightly coupled edits",
        "never encode a fixed provider, mandatory per-wave call, lane count, or transport",
    ):
        assert retired_duplicate not in text


def test_proactive_mature_first_eval_has_no_duplicate_worker_routing_protocol() -> None:
    fixture = json.loads(
        (REPO_ROOT / "evals/proactive_mature_first/cases.json").read_text(encoding="utf-8")
    )
    assert fixture["incident_required"] is False
    assert fixture["locked_core_spine"] == [
        "Temporal",
        "Docker houtai-gongren",
        "worker-internal LangGraph",
    ]
    assert "default_worker_policy" not in fixture
    cases = {case["id"]: case for case in fixture["negative_cases"]}
    assert set(cases) == {
        "NEG_NoIncident_DoesNotExemptHandRolledSurface",
        "NEG_CurrentlyGreen_IsNotRetentionEvidence",
        "NEG_PatchLoop_ReclassifiesAtArchitectureLevel",
        "NEG_LocalGlue_MustStayThin",
        "NEG_MatureInstall_RequiresPinRollbackAndRealInvocation",
        "NEG_CoreSpine_RequiresSeparateEvidenceToReplace",
    }
    assert all(case["expected"] and case["prohibited"] for case in cases.values())


def test_behavior_evolution_runner_is_thin_and_domain_research_stays_native() -> None:
    runner = (REPO_ROOT / "scripts/run_behavior_regression.ps1").read_text(encoding="utf-8")
    for required in (
        "0.121.18",
        "behavior-regression",
        "PROMPTFOO_CONFIG_DIR",
        "PROMPTFOO_LOG_DIR",
        "PROMPTFOO_CACHE_PATH",
        "PROMPTFOO_DISABLE_TELEMETRY",
        "PROMPTFOO_DISABLE_UPDATE",
        "PROMPTFOO_DISABLE_DEBUG_LOG",
        "PROMPTFOO_DISABLE_ERROR_LOG",
        "TSX_DISABLE_CACHE",
        "--no-progress-bar",
        "--no-cache",
    ):
        assert required in runner, required

    proactive_wrapper = (REPO_ROOT / "scripts/run_proactive_mature_first_eval.ps1").read_text(
        encoding="utf-8"
    )
    assert "run_behavior_regression.ps1" in proactive_wrapper
    assert "-Profile proactive" in proactive_wrapper

    config = (REPO_ROOT / "evals/proactive_mature_first/promptfooconfig.yaml").read_text(
        encoding="utf-8"
    )
    assert "reuse_server: false" in config
    assert "openai:codex-app-server" in config
    for case_id in (
        "NEG_NoIncident_DoesNotExemptHandRolledSurface",
        "NEG_CoreSpine_RequiresSeparateEvidenceToReplace",
    ):
        assert case_id in config
    assert config.count("domain: mature_first") == 6
    assert "domain: worker_routing" not in config

    battery = (REPO_ROOT / "scripts/run_self_evolution_eval_battery.ps1").read_text(
        encoding="utf-8"
    )
    assert "run_behavior_regression.ps1" in battery
    assert "admission_fixture_only" in battery
    assert "domain research belongs to xinao-native-research" in battery

    registry = json.loads((REPO_ROOT / "evals/suite_registry.v1.json").read_text(encoding="utf-8"))
    assert set(registry["loops"]) == {"behavior"}
    assert registry["loops"]["behavior"]["cannot_claim"] == "domain_edge_or_economic_truth"
    assert registry["native_domain_research"] == (
        "E:\\XINAO_RESEARCH_WORKSPACES\\xinao-native-research"
    )
    live_ids = {item["id"] for item in registry["live_agent_suites"]}
    assert "proactive_mature_first" in live_ids
    assert "parent_frame_admission" in live_ids
    assert "context_intent_alignment" not in live_ids
    assert "mature_capability_recall_replay" in live_ids
    assert "mature_capability_recall_live" in live_ids
    assert "thin_localization_live" in live_ids
    assert "native_subagent_trajectory" in live_ids
    retired_ids = {item["id"] for item in registry["retired_compatibility_suites"]}
    assert retired_ids == {"context_intent_alignment"}
    admission_ids = {item["id"] for item in registry["admission_fixture_only"]}
    assert admission_ids == {"thin_localization_contract"}

    assert "git_dirty" in runner
    assert "uncommitted_files_count" in runner
    assert "[int]$MaxConcurrency = 2" in runner
    assert "'--max-concurrency', $Concurrency" in runner
    assert "[int]$MaxErrorRetries = 1" in runner
    assert "'--filter-errors-only', $previousResult" in runner
    assert "-Concurrency 1" in runner
    assert "FailedFrom belongs to a different behavior suite" in runner
    assert "terminal_counts_authority = 'resolved_result_rows'" in runner
    assert "empty_selection = $true" in runner
    assert "repository_git_dirty" in battery

    catalog = json.loads(
        (REPO_ROOT / "evals/behavior_regression/catalog.json").read_text(encoding="utf-8")
    )
    suite_count = sum(item["case_count"] for item in catalog["suites"])
    assert suite_count == catalog["declared_case_count"] == 45
    assert catalog["live_profile_case_counts"] == {
        "capability": 1,
        "smoke": 1 + 1,
        "core": 18 + 1 + 6 + 2 + 1,
        "deep": 18 + 1 + 6 + 2 + 1 + 1,
        "intent": 27,
        "proactive": 6,
        "reuse": 4,
        "subagent": 1,
    }
    intent = next(item for item in catalog["suites"] if item["id"] == "parent_frame_admission")
    assert intent["kind"] == "promptfoo_live"
    assert intent["case_count"] == 27
    assert intent["runtime_claim_allowed"] is True
    assert intent["domain_routing_claim_allowed"] is False
    proactive = next(item for item in catalog["suites"] if item["id"] == "proactive_mature_first")
    assert proactive["kind"] == "promptfoo_live"
    assert proactive["policy_classification_claim_allowed"] is True
    assert proactive["replacement_runtime_claim_allowed"] is False
    recall_replay = next(
        item for item in catalog["suites"] if item["id"] == "mature_capability_recall_replay"
    )
    assert recall_replay["grounded_route_selection_claim_allowed"] is True
    assert recall_replay["replacement_runtime_claim_allowed"] is False
    thin_live = next(item for item in catalog["suites"] if item["id"] == "thin_localization_live")
    assert thin_live["parameter_locality_claim_allowed"] is True
    assert thin_live["real_external_invocation_claim_allowed"] is True
    assert thin_live["production_replacement_claim_allowed"] is False
    native_subagent = next(
        item for item in catalog["suites"] if item["id"] == "native_subagent_trajectory"
    )
    assert native_subagent["kind"] == "promptfoo_live_disposable_workspace_capability_probe"
    assert native_subagent["diagnostic_probe_only"] is True
    assert native_subagent["native_multi_agent_runtime_claim_allowed"] is False
    assert native_subagent["parent_owner_and_consumer_claim_allowed"] is False
    assert native_subagent["child_terminal_trace_claim_allowed"] is False
    assert native_subagent["child_internal_tool_trace_claim_allowed"] is False
    assert native_subagent["production_feature_enablement_claim_allowed"] is False
    assert native_subagent["runtime_claim_requires"] == [
        "spawn identity in the parent raw trace",
        "completed child terminal for that same identity",
        "later nonce-bearing Owner consumer invocation",
    ]


def test_behavior_failure_intake_is_trace_linked_and_never_auto_promotes() -> None:
    schema = json.loads(
        (REPO_ROOT / "evals/behavior_regression/candidate.schema.json").read_text(encoding="utf-8")
    )
    required = set(schema["required"])
    assert {"acceptance_criteria", "prohibited_side_effects", "trace_refs"} <= required
    assert schema["properties"]["promotion_status"]["const"] == "candidate"
    assert schema["properties"]["not_authority"]["const"] is True

    importer = (REPO_ROOT / "scripts/Import-PromptfooFailuresToBehaviorCandidates.ps1").read_text(
        encoding="utf-8"
    )
    for required_text in (
        "Where-Object { $_.success -ne $true }",
        "codexAppServer.threadId",
        "codexAppServer.turnId",
        "New-BehaviorRegressionCandidate.ps1",
        "-SourceType observed_failure",
    ):
        assert required_text in importer, required_text


def test_temporal_server_uses_supported_official_samples_server_shape() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "temporalio/auto-setup" not in compose
    assert "image: temporalio/server:1.31.0" in compose
    assert "image: temporalio/ui:2.49.1" in compose
    assert "DYNAMIC_CONFIG_FILE_PATH: config/dynamicconfig/xinao-production.yaml" in compose
    assert "./infra/temporal/dynamicconfig:/etc/temporal/config/dynamicconfig:ro" in compose
    source = json.loads(
        (REPO_ROOT / "infra/temporal/official_source.v1.json").read_text(encoding="utf-8")
    )
    assert source["source_repository"] == "https://github.com/temporalio/samples-server.git"
    assert source["source_commit"] == "ca1106b647c34323876bd6f221f4310271096dd8"
    assert source["images"]["temporal_server"]["tag"] == "temporalio/server:1.31.0"


def test_project_agreement_has_bounded_control_plane_tripwires() -> None:
    text = _project_agreement_contract_text()
    for required in (
        "单一 Owner",
        "PID、标题、路径相似或状态词不构成接管权",
        "Pause/Stop 立即冻结范围内的新检查、派工和 mutation",
        "不得探测、接管、interrupt 或终止其他活动 TUI/会话",
        "只修相交依赖锥",
        "不用恢复机制重新注册常驻控制器",
    ):
        assert required in text, required

    hot = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "不恢复旧新澳平台、科学路线、`continuous`、Goal" in hot
    for stale_positive_route in (
        "默认进入 `continuous`",
        "`continuous` 永续模式",
        "Goal 启用",
    ):
        assert stale_positive_route not in hot


def test_project_agreement_requires_user_named_incident_lifecycle_without_new_authority() -> None:
    text = _project_agreement_contract_text()
    for required in (
        "事故处理从只读证据开始",
        "确认影响、对象身份、活动消费者和因果候选",
        "先冻结已证有害路径，保留无关健康能力",
        "只有在当前授权内、回滚边界清楚且能终止现实影响时才施工",
        "fresh process 与真实消费者回读",
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


def test_live_codex_productivity_profile_keeps_core_and_colds_stale_surfaces() -> None:
    main_path = Path(r"C:\Users\xx363\.codex\config.toml")
    account_b_path = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b\config.toml")
    main_cold_profile_path = Path(r"C:\Users\xx363\.codex\cold-capabilities.config.toml")
    account_b_cold_profile_path = Path(
        r"C:\Users\xx363\.codex-s-hardmode-account-b\cold-capabilities.config.toml"
    )
    launcher_path = Path(r"C:\Users\xx363\CodexLaunchers\Open-Codex-S-Hardmode-Account-B.ps1")
    contract_path = Path(r"C:\Users\xx363\CodexLaunchers\CODEX_PRODUCTIVITY_PROFILE.md")
    required_paths = (
        main_path,
        account_b_path,
        main_cold_profile_path,
        account_b_cold_profile_path,
        launcher_path,
        contract_path,
    )
    if not all(path.is_file() for path in required_paths):
        return

    main = tomllib.loads(main_path.read_text(encoding="utf-8-sig"))
    account_b = tomllib.loads(account_b_path.read_text(encoding="utf-8-sig"))
    main_cold_profile = tomllib.loads(main_cold_profile_path.read_text(encoding="utf-8-sig"))
    account_b_cold_profile = tomllib.loads(
        account_b_cold_profile_path.read_text(encoding="utf-8-sig")
    )

    for feature in (
        "hooks",
        "memories",
        "shell_tool",
        "unified_exec",
        "browser_use",
        "computer_use",
        "plugins",
    ):
        assert main["features"][feature] is True, feature
        assert account_b["features"][feature] is True, feature
    assert main["memories"] == {
        "use_memories": True,
        "generate_memories": True,
        "disable_on_external_context": False,
    }
    assert main["features"]["apps"] is False
    assert main["features"]["goals"] is False
    assert main["features"]["multi_agent"] is False
    assert account_b["features"]["multi_agent"] is False
    for retained_profile in ("inner_luna_probe", "inner_terra_explorer", "inner_sol_verifier"):
        assert retained_profile in main["agents"]
        assert "config_file" in main["agents"][retained_profile]
    assert main["apps"]["_default"]["enabled"] is False

    cold_mcp = {
        "windows",
        "openaiDeveloperDocs",
        "codebase-memory",
        "chrome-devtools",
        "xinao-memory",
        "xinao-coordination",
        "serena",
        "opencode_workers",
    }
    for name in cold_mcp:
        main_server = main["mcp_servers"][name]
        b_server = account_b["mcp_servers"][name]
        assert main_server["enabled"] is False, name
        assert b_server["enabled"] is False, name
        assert "command" in main_server or "url" in main_server, name
    assert main["mcp_servers"]["node_repl"]["enabled"] is True

    cold_plugins = {
        "documents@openai-primary-runtime",
        "pdf@openai-primary-runtime",
        "spreadsheets@openai-primary-runtime",
        "presentations@openai-primary-runtime",
        "template-creator@openai-primary-runtime",
        "sites@openai-bundled",
        "visualize@openai-bundled",
        "latex@openai-bundled",
    }
    for plugin in cold_plugins:
        assert main["plugins"][plugin]["enabled"] is False, plugin
        assert account_b["plugins"][plugin]["enabled"] is False, plugin
        assert main_cold_profile["plugins"][plugin]["enabled"] is True, plugin
        assert account_b_cold_profile["plugins"][plugin]["enabled"] is True, plugin

    for plugin in (
        "browser@openai-bundled",
        "chrome@openai-bundled",
        "computer-use@openai-bundled",
        "safe-cleanup@personal",
    ):
        assert main["plugins"][plugin]["enabled"] is True, plugin
        assert account_b["plugins"][plugin]["enabled"] is True, plugin

    for plugin, server in (
        ("github@openai-curated", "github"),
        ("openai-developers@openai-curated", "openai-api-key-local-confirmation"),
    ):
        assert main["plugins"][plugin]["enabled"] is True
        assert account_b["plugins"][plugin]["enabled"] is True
        assert main["plugins"][plugin]["mcp_servers"][server]["enabled"] is False

    assert main["plugins"]["temporal@openai-curated"]["enabled"] is True
    assert account_b["plugins"]["temporal@openai-curated"]["enabled"] is True
    assert main["plugins"]["sites@openai-bundled"]["mcp_servers"][
        "sites-design-picker"
    ]["enabled"] is False

    b_node_env = account_b["mcp_servers"]["node_repl"]["env"]
    expected_b_home = r"C:\Users\xx363\.codex-s-hardmode-account-b"
    assert b_node_env["CODEX_HOME"] == expected_b_home
    assert b_node_env["NODE_REPL_TRUSTED_CODE_PATHS"] == expected_b_home
    assert account_b["shell_environment_policy"]["set"]["NODE_REPL_TRUSTED_CODE_PATHS"] == (
        expected_b_home
    )

    launcher = launcher_path.read_text(encoding="utf-8-sig")
    assert '"cold-capabilities.config.toml"' in launcher
    assert '"CODEX_HOME = \'$mainCodexHome\'"' in launcher
    assert '"CODEX_HOME = \'$codexHome\'"' in launcher
    assert "The copied config is rewritten only for B-local CODEX_HOME" in launcher
    main_agents = main_path.with_name("AGENTS.md").read_text(encoding="utf-8-sig")
    account_b_agents = account_b_path.with_name("AGENTS.md").read_text(encoding="utf-8-sig")
    assert main_agents == account_b_agents
    assert "cold-capabilities.config.toml" in main_agents
    assert "-p cold-capabilities" in main_agents
    assert "这个冷默认不是权限禁止" in main_agents
    assert "standing delegation" in main_agents
    assert "无需逐次向用户索取许可" in main_agents
    assert "只有当前用户明确要求时" not in main_agents

    contract = contract_path.read_text(encoding="utf-8-sig")
    assert "这是已授予的任务适配权，不是逐次用户审批点" in contract
    assert "普通探索、一般第二意见、并行方便、烧额度" in contract
    assert "只允许进程/任务作用域覆盖" in contract


def test_live_codex_zero_beat_and_finalization_hooks_are_trusted_and_bounded(
    tmp_path: Path,
) -> None:
    main_home = Path(r"C:\Users\xx363\.codex")
    account_b_home = Path(r"C:\Users\xx363\.codex-s-hardmode-account-b")
    script_root = Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\scripts"
    )
    pwsh = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")
    session_script = script_root / "session_start_continuity_pointer_v1.ps1"
    user_prompt_script = script_root / "user_prompt_zero_beat_v1.ps1"
    binder_script = script_root / "bind_active_task_continuation_v1.ps1"
    restore_script = script_root / "restore_parent_task_continuation_v1.ps1"
    stop_script = script_root / "turn_finalization_gate_v1.ps1"
    required = (
        main_home / "hooks.json",
        main_home / "config.toml",
        account_b_home / "hooks.json",
        account_b_home / "config.toml",
        session_script,
        user_prompt_script,
        binder_script,
        restore_script,
        stop_script,
        pwsh,
    )
    if not all(path.is_file() for path in required):
        return

    main_hooks = json.loads((main_home / "hooks.json").read_text(encoding="utf-8-sig"))
    account_b_hooks = json.loads(
        (account_b_home / "hooks.json").read_text(encoding="utf-8-sig")
    )
    assert main_hooks == account_b_hooks
    assert set(main_hooks["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "Stop",
    }

    session_handler = main_hooks["hooks"]["SessionStart"][0]["hooks"][0]
    prompt_handler = main_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    stop_handler = main_hooks["hooks"]["Stop"][0]["hooks"][0]
    # Codex already trusts each discovered hook command by currentHash. Do not
    # add a second hand-maintained script SHA inside the command: that duplicate
    # pin previously disabled continuity whenever script and hook edits landed
    # in different moments.
    handlers_and_scripts = (
        (session_handler, session_script),
        (prompt_handler, user_prompt_script),
        (stop_handler, stop_script),
    )
    for handler, script in handlers_and_scripts:
        assert "Get-FileHash" not in handler["command"]
        assert " -File " in handler["command"]
        assert str(script) in handler["command"]

    trust_by_home: dict[Path, dict[str, str]] = {}
    for config_path in (main_home / "config.toml", account_b_home / "config.toml"):
        config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
        trust = config["hooks"]["state"]
        for home in (main_home, account_b_home):
            home_trust = trust_by_home.setdefault(home, {})
            for event in (
                "session_start",
                "user_prompt_submit",
                "stop",
            ):
                key = f"{home}\\hooks.json:{event}:0:0"
                trusted_hash = trust[key]["trusted_hash"]
                assert trusted_hash.startswith("sha256:")
                assert len(trusted_hash) == len("sha256:") + 64
                assert all(char in "0123456789abcdef" for char in trusted_hash[7:])
                previous = home_trust.setdefault(event, trusted_hash)
                assert previous == trusted_hash
        assert not any(":pre_tool_use:" in key for key in trust)

    # Trust is a runtime consumer property, not a claim we can prove by copying
    # a hash into both the hook state and this test. Query a fresh Codex
    # app-server for each account and require its own discovery engine to accept
    # every installed hook.
    codex_exe = Path(
        r"D:\XINAO_RESEARCH_RUNTIME\tools\npm-global\node_modules\@openai\codex"
        r"\node_modules\@openai\codex-win32-x64\vendor"
        r"\x86_64-pc-windows-msvc\bin\codex.exe"
    )
    assert codex_exe.is_file()
    event_key_by_name = {
        "sessionStart": "session_start",
        "userPromptSubmit": "user_prompt_submit",
        "stop": "stop",
    }
    for home in (main_home, account_b_home):
        requests = (
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "hook-trust-regression",
                        "title": "hook-trust-regression",
                        "version": "1",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "optOutNotificationMethods": [],
                    },
                },
            },
            {"method": "initialized", "params": {}},
            {
                "method": "hooks/list",
                "id": 2,
                "params": {"cwds": [str(REPO_ROOT)]},
            },
        )
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        process = subprocess.Popen(
            [str(codex_exe), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()

        responses: queue.Queue[dict[str, object]] = queue.Queue()

        def read_hooks_response() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") == 2:
                    responses.put(response)
                    return

        reader = threading.Thread(target=read_hooks_response, daemon=True)
        reader.start()
        try:
            response = responses.get(timeout=10)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        discovered = response["result"]["data"][0]
        assert discovered["warnings"] == []
        assert discovered["errors"] == []
        assert len(discovered["hooks"]) == 3
        for hook in discovered["hooks"]:
            event_key = event_key_by_name[hook["eventName"]]
            assert hook["trustStatus"] == "trusted"
            assert hook["currentHash"] == trust_by_home[home][event_key]

    active_state_root = tmp_path / "active-task-state"

    def run_hook(script: Path, event: dict[str, object], *, test_root: Path | None = None):
        env = os.environ.copy()
        env["CODEX_ACTIVE_TASK_STATE_ROOT"] = str(active_state_root)
        if test_root is not None:
            env["CODEX_HOOK_TEST_SESSION_ROOT"] = str(test_root)
        completed = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(script)],
            input=json.dumps(event, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout.strip().splitlines()[-1])

    prompt_output = run_hook(
        user_prompt_script,
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "继续",
            "cwd": str(REPO_ROOT),
            "model": "gpt-5.6-sol",
            "permission_mode": "dontAsk",
            "session_id": "pytest",
            "transcript_path": None,
            "turn_id": "pytest-prompt",
        },
    )
    context = prompt_output["hookSpecificOutput"]["additionalContext"]
    assert "SENTINEL:ZERO_BEAT_CURRENT_INCREMENT_V1" in context
    assert "不要求用户重说“继续”" in context
    assert "TASK_CONTINUATION_ADVISORY_ONLY" in context
    assert "TASK_PROVENANCE_PENDING_INITIAL_BIND" not in context

    unbound_session = run_hook(
        session_script,
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": str(REPO_ROOT),
            "model": "gpt-5.6-sol",
            "permission_mode": "dontAsk",
            "session_id": "pytest-unbound",
            "transcript_path": None,
        },
    )
    unbound_context = unbound_session["hookSpecificOutput"]["additionalContext"]
    assert "TASK_CONTINUATION_ADVISORY_ONLY" in unbound_context
    assert "no separate manifest is required" in unbound_context
    assert "do not produce effect-bearing writes" not in unbound_context

    binder_env = os.environ.copy()
    binder_env["CODEX_ACTIVE_TASK_STATE_ROOT"] = str(active_state_root)
    binder_env["CODEX_THREAD_ID"] = "pytest"
    bound = subprocess.run(
        [
            str(pwsh),
            "-NoProfile",
            "-File",
            str(binder_script),
            "-SessionId",
            "pytest",
            "-TaskId",
            "task-provenance-regression",
            "-ParentTaskId",
            "behavior-parent",
            "-ActiveMode",
            "EXECUTE",
            "-TaskSource",
            "current_user_turn",
            "-UserTurnRelation",
            "same_parent_increment",
            "-BoundRoots",
            str(REPO_ROOT),
            "-AllowedEffects",
            "file_write",
            "-Scope",
            "verify task provenance consumer",
            "-CompletionCondition",
            "guard and compact readback pass",
            "-ContinuationStatus",
            "exact",
            "-ReturnTaskId",
            "behavior-parent",
            "-ReturnRepository",
            str(REPO_ROOT),
            "-ReturnPoint",
            "next known parent frontier",
            "-ReturnMode",
            "EXECUTE",
            "-StateRoot",
            str(active_state_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=binder_env,
        check=False,
    )
    assert bound.returncode == 0, bound.stderr
    assert json.loads(bound.stdout)["status"] == "bound"

    foreign_root = tmp_path / "foreign-repo"
    foreign_root.mkdir()

    compact_event: dict[str, object] = {
        "hook_event_name": "SessionStart",
        "source": "compact",
        "cwd": str(REPO_ROOT),
        "model": "gpt-5.6-sol",
        "permission_mode": "dontAsk",
        "session_id": "pytest",
        "transcript_path": None,
    }
    restored = run_hook(session_script, compact_event)
    assert "ACTIVE_TASK_CONTINUATION_ADVISORY" in restored["hookSpecificOutput"][
        "additionalContext"
    ]
    assert "next known parent frontier" in restored["hookSpecificOutput"][
        "additionalContext"
    ]

    # An ordinary new increment does not reset an established parent scope.
    # The Owner rebinds only when the meaning actually changes the parent,
    # object, mode, or effect scope.
    prompt_output_2 = run_hook(
        user_prompt_script,
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "继续，把相交测试跑完",
            "cwd": str(REPO_ROOT),
            "model": "gpt-5.6-sol",
            "permission_mode": "dontAsk",
            "session_id": "pytest",
            "transcript_path": None,
            "turn_id": "pytest-prompt-2",
        },
    )
    prompt_context_2 = prompt_output_2[
        "hookSpecificOutput"
    ]["additionalContext"]
    assert "TASK_CONTINUATION_ADVISORY_ONLY" in prompt_context_2
    assert "task-provenance-regression" in prompt_context_2
    compact_inherited = run_hook(session_script, compact_event)
    assert "ACTIVE_TASK_CONTINUATION_ADVISORY" in compact_inherited[
        "hookSpecificOutput"
    ]["additionalContext"]

    # A legitimate cross-repository child is bound internally with exact
    # lineage and return. The user is not asked to choose or approve a repo.
    child = subprocess.run(
        [
            str(pwsh),
            "-NoProfile",
            "-File",
            str(binder_script),
            "-SessionId",
            "pytest",
            "-TaskId",
            "task-provenance-child",
            "-ParentTaskId",
            "task-provenance-regression",
            "-ActiveMode",
            "EXECUTE",
            "-TaskSource",
            "surviving_parent",
            "-UserTurnRelation",
            "same_parent_increment",
            "-BoundRoots",
            str(foreign_root),
            "-AllowedEffects",
            "file_write",
            "-Scope",
            "verify automatic child binding",
            "-CompletionCondition",
            "child guard and exact return pass",
            "-ContinuationStatus",
            "exact",
            "-ReturnTaskId",
            "task-provenance-regression",
            "-ReturnRepository",
            str(REPO_ROOT),
            "-ReturnPoint",
            "resume parent provenance regression",
            "-ReturnMode",
            "EXECUTE",
            "-StateRoot",
            str(active_state_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=binder_env,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout)["binding_relation"] == (
        "child_of_surviving_parent"
    )

    restored_parent = subprocess.run(
        [
            str(pwsh),
            "-NoProfile",
            "-File",
            str(restore_script),
            "-SessionId",
            "pytest",
            "-StateRoot",
            str(active_state_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=binder_env,
        check=False,
    )
    assert restored_parent.returncode == 0, restored_parent.stderr
    assert json.loads(restored_parent.stdout)["task_id"] == (
        "task-provenance-regression"
    )

    paused = subprocess.run(
        [
            str(pwsh),
            "-NoProfile",
            "-File",
            str(binder_script),
            "-SessionId",
            "pytest",
            "-TaskId",
            "task-provenance-regression",
            "-ParentTaskId",
            "behavior-parent",
            "-ActiveMode",
            "PAUSED",
            "-TaskSource",
            "surviving_parent",
            "-UserTurnRelation",
            "pause",
            "-BoundRoots",
            str(REPO_ROOT),
            "-AllowedEffects",
            "file_write",
            "-Scope",
            "preserve the paused parent",
            "-CompletionCondition",
            "explicit resume or supersession",
            "-ContinuationStatus",
            "exact",
            "-ReturnTaskId",
            "behavior-parent",
            "-ReturnRepository",
            str(REPO_ROOT),
            "-ReturnPoint",
            "next known parent frontier",
            "-ReturnMode",
            "EXECUTE",
            "-StateRoot",
            str(active_state_root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=binder_env,
        check=False,
    )
    assert paused.returncode == 0, paused.stderr

    active_transcript = tmp_path / "active.jsonl"
    active_transcript.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "input": (
                        "await tools.update_plan({plan:["
                        "{step:'parent work',status:'in_progress'}]});"
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stop_event: dict[str, object] = {
        "hook_event_name": "Stop",
        "cwd": str(REPO_ROOT),
        "last_assistant_message": "local child is done",
        "model": "gpt-5.6-sol",
        "permission_mode": "dontAsk",
        "session_id": "pytest",
        "stop_hook_active": False,
        "transcript_path": str(active_transcript),
        "turn_id": "pytest-stop",
    }
    blocked = run_hook(stop_script, stop_event, test_root=tmp_path)
    assert blocked["decision"] == "block"
    assert "pending/in_progress" in blocked["reason"]

    stop_event["stop_hook_active"] = True
    assert run_hook(stop_script, stop_event, test_root=tmp_path) == {"continue": True}

    complete_transcript = tmp_path / "complete.jsonl"
    complete_transcript.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "input": (
                        "await tools.update_plan({plan:["
                        "{step:'parent work',status:'completed'}]});"
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stop_event["stop_hook_active"] = False
    stop_event["transcript_path"] = str(complete_transcript)
    assert run_hook(stop_script, stop_event, test_root=tmp_path) == {"continue": True}
