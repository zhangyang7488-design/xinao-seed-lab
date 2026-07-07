from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

SEED_CORTEX_ROUTE_PROFILE = "seed_cortex_phase0"
LEGACY_CLEAN_RUNTIME_ROOT = Path(r"D:\XINAO_CLEAN_RUNTIME")
RUNTIME_ENV_KEYS = ("XINAO_RUNTIME_ROOT", "XINAO_RUNTIME")
COMPAT_RUNTIME_ENV_KEYS = ("XINAO_COMPAT_RUNTIME", "XINAO_COMPAT_RUNTIME_ROOT")
REFERENCE_ONLY_ENV = "XINAO_MCP_LEGACY_REFERENCE_ONLY"
ROUTE_PROFILE = os.environ.get("XINAO_ROUTE_PROFILE", "")


def _truthy_env(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on", "reference_only"}


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _compat_runtime_root_from_env(env: Mapping[str, str]) -> tuple[Path, str]:
    for key in COMPAT_RUNTIME_ENV_KEYS:
        configured = env.get(key)
        if configured:
            return Path(configured), key
    return LEGACY_CLEAN_RUNTIME_ROOT, "legacy_default(D:\\XINAO_CLEAN_RUNTIME)"


def _runtime_root_config_from_env(env: Mapping[str, str] | None = None) -> tuple[Path, str, bool]:
    env = os.environ if env is None else env
    route_profile = env.get("XINAO_ROUTE_PROFILE", "")
    reference_only = _truthy_env(env, REFERENCE_ONLY_ENV)
    compat_runtime, compat_source = _compat_runtime_root_from_env(env)

    for key in RUNTIME_ENV_KEYS:
        configured = env.get(key)
        if not configured:
            continue
        runtime = Path(configured)
        if (
            route_profile == SEED_CORTEX_ROUTE_PROFILE
            and _same_path(runtime, compat_runtime)
            and not reference_only
        ):
            raise RuntimeError(
                "XINAO_SEED_CORTEX_MCP_CLEAN_RUNTIME_REQUIRES_REFERENCE_ONLY: "
                "D:\\XINAO_CLEAN_RUNTIME cannot be the seed_cortex_phase0 MCP runtime root unless "
                "XINAO_MCP_LEGACY_REFERENCE_ONLY=1 is set."
            )
        return runtime, key, reference_only and _same_path(runtime, compat_runtime)

    if route_profile == SEED_CORTEX_ROUTE_PROFILE:
        if reference_only:
            return compat_runtime, f"{compat_source}(reference_only)", True
        raise RuntimeError(
            "XINAO_SEED_CORTEX_MCP_RUNTIME_ROOT_REQUIRED: set XINAO_RUNTIME or "
            "XINAO_RUNTIME_ROOT to D:\\XINAO_RESEARCH_RUNTIME. Refusing silent fallback "
            "to D:\\XINAO_CLEAN_RUNTIME; set XINAO_MCP_LEGACY_REFERENCE_ONLY=1 only for "
            "explicit reference_only compatibility reads."
        )

    if reference_only:
        return compat_runtime, f"{compat_source}(reference_only)", True
    return LEGACY_CLEAN_RUNTIME_ROOT, "legacy_default(D:\\XINAO_CLEAN_RUNTIME)", False


def _runtime_root_from_env(env: Mapping[str, str] | None = None) -> Path:
    runtime, _, _ = _runtime_root_config_from_env(env)
    return runtime


REPO_ROOT = Path(os.environ.get("XINAO_REPO_ROOT", Path(__file__).resolve().parents[2]))
RUNTIME_ROOT, RUNTIME_ROOT_SOURCE, RUNTIME_ROOT_REFERENCE_ONLY = _runtime_root_config_from_env()
MCP_HOST = os.environ.get("XINAO_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("XINAO_MCP_PORT", "19460"))
UCP_STATE_ROOT = RUNTIME_ROOT / "state" / "universal_control_plane_v0"
UCP_LAUNCHER = (
    RUNTIME_ROOT / "tools" / "universal_control_plane_v0" / "run_universal_control_plane_v0.ps1"
)
UCP_PYTHON = RUNTIME_ROOT / "tools" / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe"
UCP_SCRIPT = RUNTIME_ROOT / "tools" / "universal_control_plane_v0" / "universal_control_plane_v0.py"

mcp = FastMCP(
    "xinao-runtime-discovery",
    instructions=(
        "XINAO discovery and bounded UCP dispatch adapter. It exposes current "
        "runtime facts, OpenAPI contracts, Backstage-compatible catalog descriptors, "
        "mature stack status, and a thin wrapper over the existing UCP v0 runtime "
        "CLI. It is not the system of record and must not be treated as a static "
        "registry or root orchestrator."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*"],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://host.docker.internal:*",
        ],
    ),
)


def _read_text(path: Path, *, max_chars: int = 200_000) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[TRUNCATED_BY_XINAO_MCP_READONLY_ADAPTER]"
    return text


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    text = path.read_text(encoding="utf-8-sig")
    if len(text) > 200_000:
        text = text[:200_000]
    return json.loads(text)


def _json_resource(path: Path) -> str:
    payload = _read_json(path, default={"status": "missing", "path": str(path)})
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _runtime_root_boundary() -> dict[str, Any]:
    compat_runtime, compat_source = _compat_runtime_root_from_env(os.environ)
    return {
        "route_profile": ROUTE_PROFILE,
        "runtime_root": str(RUNTIME_ROOT),
        "source": RUNTIME_ROOT_SOURCE,
        "reference_only": RUNTIME_ROOT_REFERENCE_ONLY,
        "seed_cortex_runtime_required": ROUTE_PROFILE == SEED_CORTEX_ROUTE_PROFILE,
        "clean_runtime_silent_fallback_allowed": False
        if ROUTE_PROFILE == SEED_CORTEX_ROUTE_PROFILE
        else RUNTIME_ROOT_SOURCE.startswith("legacy_default"),
        "compat_runtime_root": str(compat_runtime),
        "compat_runtime_source": compat_source,
        "not_source_of_truth": RUNTIME_ROOT_REFERENCE_ONLY,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def _ucp_target_summary() -> dict[str, Any]:
    targets_payload = _read_json(UCP_STATE_ROOT / "targets.json", default={})
    targets = targets_payload.get("targets", {})
    if not isinstance(targets, dict):
        targets = {}
    by_status: dict[str, int] = {}
    for target in targets.values():
        if not isinstance(target, dict):
            continue
        status = str(target.get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "target_count": len(targets),
        "by_status": by_status,
        "targets": {
            name: {
                "status": payload.get("status", "unknown"),
                "carrier": payload.get("carrier", []),
                "verbs": payload.get("verbs", []),
                "surface": payload.get("surface", ""),
            }
            for name, payload in targets.items()
            if isinstance(payload, dict)
        },
    }


def _dify_public_workflow_status(
    dify_lane_state: dict[str, Any],
    saved_workflow_binding: dict[str, Any] | None = None,
    saved_workflow_node_binding: dict[str, Any] | None = None,
) -> str:
    saved_workflow_binding = saved_workflow_binding or {}
    saved_workflow_node_binding = saved_workflow_node_binding or {}
    acceptance = dify_lane_state.get("acceptance") or {}
    if dify_lane_state.get("status") == "dify_dsl_lane_machine_accepted_not_s13":
        return "machine_accepted_not_s13"
    if (
        acceptance.get("saved_workflow_or_agent_node_bound") is True
        and acceptance.get("real_chinese_goal_run_detail_verified") is True
    ):
        return "bound_and_real_run_verified"
    if acceptance.get("saved_workflow_or_agent_node_bound") is True:
        return "saved_workflow_or_agent_node_bound"
    if (
        saved_workflow_binding.get("status") == "dify_saved_workflow_bound_to_completion_claim"
        and saved_workflow_binding.get("saved_workflow_bound_to_completion_claim_bridge") is True
        and saved_workflow_node_binding.get("status")
        == "dify_saved_workflow_nodes_bound_to_completion_claim"
    ):
        return "saved_workflow_or_agent_node_bound"
    return "not_bound"


def _ucp_dispatch_removed_from_mcp(target: str, verb: str) -> dict[str, Any]:
    return {
        "schema": "xinao.universal-control-plane-dispatch.v1",
        "status": "BLOCKED",
        "exit_code": None,
        "named_blocker": "UCP_MCP_DISPATCH_REMOVED_USE_TEMPORAL_ACTIVITY",
        "target": target,
        "verb": verb,
        "dispatch_spawn_default": False,
        "dispatch_subprocess_available": False,
        "read_only_status_tool": "xinao_universal_control_plane_status",
        "read_only_resources": [
            "xinao://control-plane/universal/latest",
            "xinao://control-plane/universal/targets",
            "xinao://control-plane/universal/verification",
        ],
        "replacement_carrier": "Temporal workflow/activity or MCP Gateway OSS outside this read-only MCP server",
        "next_machine_action": "Use xinao_universal_control_plane_status for read-only state. Dispatch work through /codex-a/intent -> Temporal activity, not MCP subprocess.",
        "launcher": str(UCP_LAUNCHER),
        "python": str(UCP_PYTHON),
        "script": str(UCP_SCRIPT),
        "not_root_orchestrator": True,
        "not_user_completion": True,
    }


def _run_ucp_dispatch(
    source: str, target: str, verb: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return _ucp_dispatch_removed_from_mcp(target, verb)


@mcp.resource("xinao://startup/l0")
def startup_l0() -> str:
    return _read_text(RUNTIME_ROOT / "resources" / "startup" / "codex_l0_bootstrap.md")


@mcp.resource("xinao://active-object")
def active_object() -> str:
    return _json_resource(RUNTIME_ROOT / "ACTIVE_OBJECT.json")


@mcp.resource("xinao://current-context")
def current_context() -> str:
    return _json_resource(RUNTIME_ROOT / "projections" / "current_context.json")


@mcp.resource("xinao://current-facts")
def current_facts() -> str:
    return _json_resource(RUNTIME_ROOT / "projections" / "current_facts.json")


@mcp.resource("xinao://runtime/mature-stack-status")
def mature_stack_status() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "mature_stack_runtime_status" / "latest.json")


@mcp.resource("xinao://capability/inventory")
def capability_inventory() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "capability_inventory" / "latest.json")


@mcp.resource("xinao://control-plane/external-carrier-scan")
def external_mature_control_carrier_scan() -> str:
    return _json_resource(
        RUNTIME_ROOT / "state" / "external_mature_control_carrier_scan" / "latest.json"
    )


@mcp.resource("xinao://control-plane/openlineage-facade")
def openlineage_facade() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "openlineage_facade" / "latest.json")


@mcp.resource("xinao://workers/codex-exec-direct-canary")
def codex_exec_direct_canary() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "codex_exec_direct_canary" / "latest.json")


@mcp.resource("xinao://workers/codex-sdk-canary")
def codex_sdk_canary() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "codex_sdk_canary" / "latest.json")


@mcp.resource("xinao://control-plane/a2a-facade")
def a2a_facade() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "a2a_facade" / "latest_task.json")


@mcp.resource("xinao://control-plane/ag-ui-facade")
def ag_ui_facade() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "ag_ui_facade" / "latest.json")


@mcp.resource("xinao://catalog/service")
def service_catalog() -> str:
    return _json_resource(RUNTIME_ROOT / "catalog" / "service_catalog.json")


@mcp.resource("xinao://catalog/tool-registry")
def tool_registry() -> str:
    return _json_resource(
        RUNTIME_ROOT / "agent_runtime" / "tools" / "registry" / "tool_registry.json"
    )


@mcp.resource("xinao://catalog/backstage")
def backstage_catalog() -> str:
    return _read_text(REPO_ROOT / "catalog-info.yaml")


@mcp.resource("xinao://catalog/backstage-live")
def backstage_live_catalog() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "backstage_catalog" / "latest.json")


@mcp.resource("xinao://observability/otel-collector")
def otel_collector_state() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "otel_collector" / "latest.json")


@mcp.resource("xinao://observability/otel-unified-trace-canary")
def otel_unified_trace_canary() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "otel_unified_trace_canary" / "latest.json")


@mcp.resource("xinao://observability/langfuse-live-trace-canary")
def langfuse_live_trace_canary() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "langfuse_live_trace_canary" / "latest.json")


@mcp.resource("xinao://observability/litellm-live-gateway-canary")
def litellm_live_gateway_canary() -> str:
    return _json_resource(RUNTIME_ROOT / "state" / "litellm_live_gateway_canary" / "latest.json")


@mcp.resource("xinao://openapi/panel")
def panel_openapi() -> str:
    return _read_text(REPO_ROOT / "contracts" / "openapi" / "panel.openapi.yaml")


@mcp.resource("xinao://openapi/runtime-status-surface")
def runtime_status_surface_openapi() -> str:
    return _read_text(REPO_ROOT / "contracts" / "openapi" / "runtime-status-surface.openapi.yaml")


@mcp.resource("xinao://openapi/action-minimal-ingress")
def action_minimal_ingress_openapi() -> str:
    return _read_text(REPO_ROOT / "contracts" / "new_action_minimal_ingress_v1.openapi.yaml")


@mcp.resource("xinao://control-plane/universal/latest")
def universal_control_plane_latest() -> str:
    return _json_resource(UCP_STATE_ROOT / "latest.json")


@mcp.resource("xinao://control-plane/universal/targets")
def universal_control_plane_targets() -> str:
    return _json_resource(UCP_STATE_ROOT / "targets.json")


@mcp.resource("xinao://control-plane/universal/agent-card")
def universal_control_plane_agent_card() -> str:
    return _json_resource(UCP_STATE_ROOT / "agent-card.json")


@mcp.resource("xinao://control-plane/universal/verification")
def universal_control_plane_verification() -> str:
    return _json_resource(UCP_STATE_ROOT / "verification" / "latest.json")


@mcp.resource("xinao://control-plane/codex-tui-disaster-recovery-binding")
def codex_tui_disaster_recovery_binding() -> str:
    return _json_resource(
        RUNTIME_ROOT / "state" / "codex_tui_disaster_recovery_binding" / "latest.json"
    )


@mcp.resource("xinao://control-plane/codex-tui-resume-preflight-canary")
def codex_tui_resume_preflight_canary() -> str:
    return _json_resource(
        RUNTIME_ROOT / "state" / "codex_tui_resume_preflight_canary" / "latest.json"
    )


@mcp.resource("xinao://control-plane/codex-tui-remote-app-server-launch-profile")
def codex_tui_remote_app_server_launch_profile() -> str:
    return _json_resource(
        RUNTIME_ROOT / "state" / "codex_tui_remote_app_server_launch_profile" / "latest.json"
    )


@mcp.tool()
def xinao_discovery_map() -> dict[str, Any]:
    """Return the mature discovery lanes Codex should use before inventing XINAO registries."""
    backstage_state = _read_json(
        RUNTIME_ROOT / "state" / "backstage_catalog" / "latest.json", default={}
    )
    dify_provider_state = _read_json(
        RUNTIME_ROOT / "state" / "dify_mcp_provider_binding" / "latest.json", default={}
    )
    dify_toolengine_state = _read_json(
        RUNTIME_ROOT / "state" / "dify_mcp_toolengine_canary" / "latest.json", default={}
    )
    dify_lane_state = _read_json(
        RUNTIME_ROOT / "state" / "dify_dsl_authoring_publishing_lane" / "latest.json", default={}
    )
    dify_saved_workflow_binding = _read_json(
        RUNTIME_ROOT / "state" / "dify_saved_workflow_binding" / "latest.json", default={}
    )
    dify_saved_workflow_node_binding = _read_json(
        RUNTIME_ROOT / "state" / "dify_saved_workflow_node_binding" / "latest.json", default={}
    )
    dify_public_status = _dify_public_workflow_status(
        dify_lane_state,
        dify_saved_workflow_binding,
        dify_saved_workflow_node_binding,
    )
    still_not_done = [
        "Codex can discover this MCP server only after the relevant CODEX_HOME config is loaded by a new session.",
    ]
    if backstage_state.get("status") != "live_catalog_verified":
        still_not_done.append(
            "Backstage service is not verified live; catalog-info.yaml remains descriptor-only until scripts\\verify_backstage_catalog.ps1 passes."
        )
    if dify_provider_state.get("status") not in (
        "dify_workspace_mcp_provider_registered",
        "dify_mcp_provider_registered",
        "dify_mcp_provider_binding_verified",
    ):
        still_not_done.append("Dify workspace MCP provider is not verified registered.")
    elif dify_public_status == "machine_accepted_not_s13":
        still_not_done.append(
            "Dify public workflow/API route is machine-accepted with a real Chinese-goal run; S13 human-visible acceptance still blocks completion claims only."
        )
    elif dify_public_status == "saved_workflow_or_agent_node_bound":
        still_not_done.append(
            "Dify saved workflow/agent node is bound to /completion/claim; a fresh real Chinese-goal Dify run and S13 human-visible acceptance still block completion claims only."
        )
    elif dify_toolengine_state.get("status") == "dify_mcp_toolengine_workflow_invoke_verified":
        still_not_done.append(
            "Dify internal ToolEngine canary has invoked this MCP provider, but no saved public Dify workflow or agent node has accepted it in a real Chinese-goal flow."
        )
    else:
        still_not_done.append(
            "Dify workspace MCP provider is registered, but Dify internal ToolEngine or saved workflow/agent node invocation is not verified."
        )
    return {
        "schema": "xinao.mature-discovery-map.v1",
        "source_policy": "MCP/OpenAPI/Backstage/Dify/Docker state are discovery sources; XINAO JSON files are projections or migration inputs, not a new master registry.",
        "runtime_root_boundary": _runtime_root_boundary(),
        "ai_tool_discovery": {
            "carrier": "MCP",
            "server": "xinao-runtime-discovery",
            "resources": [
                "xinao://startup/l0",
                "xinao://active-object",
                "xinao://current-context",
                "xinao://current-facts",
                "xinao://runtime/mature-stack-status",
                "xinao://capability/inventory",
                "xinao://control-plane/external-carrier-scan",
                "xinao://control-plane/openlineage-facade",
                "xinao://workers/codex-exec-direct-canary",
                "xinao://workers/codex-sdk-canary",
                "xinao://control-plane/a2a-facade",
                "xinao://control-plane/ag-ui-facade",
                "xinao://catalog/tool-registry",
                "xinao://observability/otel-collector",
                "xinao://observability/otel-unified-trace-canary",
                "xinao://observability/langfuse-live-trace-canary",
                "xinao://observability/litellm-live-gateway-canary",
                "xinao://openapi/panel",
                "xinao://openapi/runtime-status-surface",
                "xinao://openapi/action-minimal-ingress",
                "xinao://control-plane/universal/latest",
                "xinao://control-plane/universal/targets",
                "xinao://control-plane/universal/agent-card",
                "xinao://control-plane/universal/verification",
                "xinao://control-plane/codex-tui-disaster-recovery-binding",
                "xinao://control-plane/codex-tui-resume-preflight-canary",
                "xinao://control-plane/codex-tui-remote-app-server-launch-profile",
            ],
        },
        "universal_control_plane": {
            "carrier": "MCP read-only discovery/status over UCP v0 state. Dispatch subprocess has been removed from this MCP surface.",
            "resources": [
                "xinao://control-plane/universal/latest",
                "xinao://control-plane/universal/targets",
                "xinao://control-plane/universal/agent-card",
                "xinao://control-plane/universal/verification",
                "xinao://control-plane/codex-tui-disaster-recovery-binding",
                "xinao://control-plane/codex-tui-resume-preflight-canary",
                "xinao://control-plane/codex-tui-remote-app-server-launch-profile",
            ],
            "tools": [
                "xinao_universal_control_plane_status",
            ],
            "dispatch_exposed": False,
            "dispatch_tool_exposed": False,
            "dispatch_spawn_default": False,
            "dispatch_subprocess_available": False,
            "dispatch_removed_named_blocker": "UCP_MCP_DISPATCH_REMOVED_USE_TEMPORAL_ACTIVITY",
            "dispatch_replacement": "Use /codex-a/intent -> Temporal workflow/activity or a managed MCP Gateway OSS route outside this read-only server.",
            "retired_dispatch_function": "xinao_universal_control_plane_dispatch",
            "latest_operation_status": _read_json(UCP_STATE_ROOT / "latest.json", default={}).get(
                "status", "missing"
            ),
            "verification_status": _read_json(
                UCP_STATE_ROOT / "verification" / "latest.json", default={}
            ).get("status", "missing"),
            "target_summary": _ucp_target_summary(),
            "not_root_orchestrator": True,
            "not_user_completion": True,
            "pass_means": "probe/verification only; never user-meaning completion",
            "completion_boundary": "UCP readback proves a current probe only. Dispatch work must be owned by Temporal/current_task_owner, not MCP subprocess.",
            "status_semantics": {
                "active": "scoped callable route, not completion",
                "active_read_probe": "read-only probe, not executor",
                "active_bounded_write_probe": "bounded canary with fresh evidence requirement",
                "fallback_bounded_canary": "fallback-only bounded canary",
            },
        },
        "http_capability_discovery": {
            "carrier": "OpenAPI",
            "contracts": xinao_list_openapi_contracts(),
        },
        "engineering_asset_catalog": {
            "carrier": "Backstage live catalog when verified; catalog-info.yaml descriptor fallback otherwise",
            "descriptor": str(REPO_ROOT / "catalog-info.yaml"),
            "live_status": backstage_state.get("status", "missing"),
            "backend_url": backstage_state.get("backend_url", "http://127.0.0.1:7007"),
            "state_ref": str(RUNTIME_ROOT / "state" / "backstage_catalog" / "latest.json"),
        },
        "workflow_tooling": {
            "carrier": "Dify workflow and MCP tool integration",
            "local_ui": "http://127.0.0.1:19420/",
            "status_ref": str(RUNTIME_ROOT / "state" / "dify_live_workflow_canary" / "latest.json"),
            "mcp_provider_status": dify_provider_state.get("status", "missing"),
            "mcp_toolengine_status": dify_toolengine_state.get("status", "missing"),
            "public_workflow_or_agent_node_status": dify_public_status,
            "dify_dsl_lane_status": dify_lane_state.get("status", "missing"),
            "dify_dsl_lane_ref": str(
                RUNTIME_ROOT / "state" / "dify_dsl_authoring_publishing_lane" / "latest.json"
            ),
            "saved_workflow_binding_status": dify_saved_workflow_binding.get("status", "missing"),
            "saved_workflow_node_binding_status": dify_saved_workflow_node_binding.get(
                "status", "missing"
            ),
        },
        "runtime_evidence": {
            "carriers": [
                "Docker",
                f"{RUNTIME_ROOT} state/projections",
                "Langfuse",
                "Postgres JSONB",
            ],
            "status_ref": str(
                RUNTIME_ROOT / "state" / "mature_stack_runtime_status" / "latest.json"
            ),
            "runtime_root_boundary": _runtime_root_boundary(),
        },
        "still_not_done": still_not_done,
    }


@mcp.tool()
def xinao_list_openapi_contracts() -> list[dict[str, str]]:
    """List OpenAPI contracts that should be used before hand-writing HTTP tool bindings."""
    contracts_dir = REPO_ROOT / "contracts" / "openapi"
    contracts = [
        {
            "name": path.stem,
            "path": str(path),
            "resource_uri": f"xinao://openapi/{path.stem.replace('.openapi', '')}",
        }
        for path in sorted(contracts_dir.glob("*.yaml"))
    ]
    contracts.append(
        {
            "name": "new_action_minimal_ingress_v1",
            "path": str(REPO_ROOT / "contracts" / "new_action_minimal_ingress_v1.openapi.yaml"),
            "resource_uri": "xinao://openapi/action-minimal-ingress",
        }
    )
    return contracts


@mcp.tool()
def xinao_runtime_mature_services() -> dict[str, Any]:
    """Return current mature-stack service status from the existing runtime status artifact."""
    status = _read_json(
        RUNTIME_ROOT / "state" / "mature_stack_runtime_status" / "latest.json", default={}
    )
    return {
        "schema": "xinao.runtime-mature-services.v1",
        "status": status.get("status", "unknown"),
        "generated_at": status.get("generated_at", ""),
        "services": {
            name: {
                "status": payload.get("status", "unknown"),
                "container_count": payload.get("container_count", 0),
                "failed_probe_names": payload.get("failed_probe_names", []),
            }
            for name, payload in status.get("services", {}).items()
            if isinstance(payload, dict)
        },
        "network_download_policy": status.get("network_download_policy", {}),
        "not_source_of_truth": True,
    }


@mcp.tool()
def xinao_universal_control_plane_status() -> dict[str, Any]:
    """Return read-only UCP v0 status, target inventory summary, and verification evidence."""
    latest = _read_json(UCP_STATE_ROOT / "latest.json", default={})
    verification = _read_json(UCP_STATE_ROOT / "verification" / "latest.json", default={})
    agent_card = _read_json(UCP_STATE_ROOT / "agent-card.json", default={})
    verification_status = verification.get("status", "missing")
    return {
        "schema": "xinao.universal-control-plane-status.v1",
        "status": verification_status,
        "latest_operation_status": latest.get("status", "missing"),
        "updated_at": latest.get("updated_at", ""),
        "latest_request_id": latest.get("latest_request_id", ""),
        "latest_dispatch_ref": latest.get("latest_dispatch_ref", ""),
        "verification_status": verification_status,
        "verification_target_count": verification.get("target_count"),
        "verification_passed_targets": verification.get("passed_targets", []),
        "verification_passed_targets_semantics": verification.get("passed_targets_semantics", ""),
        "passed_active_or_fallback_targets": verification.get(
            "passed_active_or_fallback_targets", []
        ),
        "passed_candidate_probe_targets": verification.get("passed_candidate_probe_targets", []),
        "candidate_blockers": verification.get("candidate_blockers", []),
        "missing_targets": verification.get("missing_targets", []),
        "missing_current_passes": verification.get("missing_current_passes", []),
        "failed_checks": verification.get("failed_checks", []),
        "named_blocker": verification.get("named_blocker"),
        "target_summary": _ucp_target_summary(),
        "agent_card_ref": str(UCP_STATE_ROOT / "agent-card.json"),
        "agent_card_name": agent_card.get("name", ""),
        "resource_uris": [
            "xinao://control-plane/universal/latest",
            "xinao://control-plane/universal/targets",
            "xinao://control-plane/universal/agent-card",
            "xinao://control-plane/universal/verification",
        ],
        "read_only_discovery_surface": True,
        "dispatch_exposed_here": False,
        "dispatch_spawn_default": False,
        "dispatch_subprocess_available": False,
        "dispatch_removed_named_blocker": "UCP_MCP_DISPATCH_REMOVED_USE_TEMPORAL_ACTIVITY",
        "dispatch_replacement": "Use /codex-a/intent -> Temporal workflow/activity or a managed MCP Gateway OSS route outside this read-only server.",
        "dispatch_tool_exposed": False,
        "retired_dispatch_function": "xinao_universal_control_plane_dispatch",
        "not_root_orchestrator": True,
        "not_user_completion": True,
    }


def xinao_universal_control_plane_dispatch(
    target: str,
    verb: str,
    source: str = "codex-a",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retired compatibility function; not exposed as an MCP tool."""
    return _run_ucp_dispatch(source=source, target=target, verb=verb, payload=payload)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="XINAO read-only MCP discovery server.")
    parser.add_argument("--transport", choices=("stdio", "streamable-http", "sse"), default="stdio")
    args = parser.parse_args()
    mcp.run(args.transport)


if __name__ == "__main__":
    main()
