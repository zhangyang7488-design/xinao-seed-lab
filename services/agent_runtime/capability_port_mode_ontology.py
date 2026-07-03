from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
SCHEMA_VERSION = "xinao.codex_s.capability_port_mode_ontology.v1"
ONTOLOGY_ID = "codex-s-capability-port-mode-ontology-20260702"
SENTINEL = "SENTINEL:XINAO_CAPABILITY_PORT_MODE_ONTOLOGY_READY"
DEFAULT_REPO_ROOT = Path("E:/XINAO_RESEARCH_WORKSPACES/S")
DEFAULT_RUNTIME_ROOT = Path("D:/XINAO_RESEARCH_RUNTIME")

DP_MODE_IDS = (
    "draft",
    "eval",
    "contradiction",
    "extraction",
    "audit",
    "search",
    "citation_verify",
    "provider_probe",
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def boundary_fields() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _source_surfaces(repo_root: Path, runtime_root: Path) -> list[str]:
    return [
        str(repo_root / "CODEX_S_L0.md"),
        str(repo_root / "SEED_CORTEX_MUST_READ_FIRST.md"),
        str(repo_root / "contracts" / "codex-s-workspace-boundary.v1.json"),
        str(repo_root / "contracts" / "schemas" / "seed_cortex_sidecar_capability_reuse.v1.json"),
        str(repo_root / "src" / "xinao_seedlab" / "adapters" / "capability_gateway.py"),
        str(repo_root / "contracts" / "openapi" / "seedlab.v1.yaml"),
        str(repo_root / "policies" / "seed_cortex_phase0.rego"),
        str(runtime_root / "state" / "seed_cortex_sidecar_capability_reuse" / "latest.json"),
    ]


def _dp_modes() -> list[dict[str, Any]]:
    common = {
        "direct_fact_promotion_allowed": False,
        "direct_repo_mutation_allowed": False,
    }
    return [
        {
            "mode_id": "draft",
            "mode_role": "bounded draft sidecar mode",
            "mode_state": "verified_mode",
            "requested_capability": "cheap_parallel_draft",
            "provider_id": "legacy.deepseek_dp_sidecar",
            "launcher_subcommand": "draft-deepseek",
            "acceptance_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\artifact_acceptance_queue\latest.json",
            **common,
        },
        {
            "mode_id": "eval",
            "mode_role": "evaluation sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
        {
            "mode_id": "contradiction",
            "mode_role": "contradiction and adversarial review sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
        {
            "mode_id": "extraction",
            "mode_role": "structured extraction sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
        {
            "mode_id": "audit",
            "mode_role": "audit sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
        {
            "mode_id": "search",
            "mode_role": "external research search mode, not the DP port definition",
            "mode_state": "verified_mode",
            "requested_capability": "dp_search",
            "provider_id": "deepseek.search_sidecar",
            "fan_in_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\deepseek_search_fan_in_acceptance\latest.json",
            "acceptance_ref": r"D:\XINAO_RESEARCH_RUNTIME\state\artifact_acceptance_queue\latest.json",
            **common,
        },
        {
            "mode_id": "citation_verify",
            "mode_role": "citation and source verification sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
        {
            "mode_id": "provider_probe",
            "mode_role": "provider probe sidecar mode",
            "mode_state": "declared_mode_candidate",
            "provider_id": "legacy.deepseek_dp_sidecar",
            **common,
        },
    ]


def build_capability_port_mode_ontology(
    *,
    repo_root: str | Path = DEFAULT_REPO_ROOT,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    write: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_root)
    runtime = Path(runtime_root)
    l0 = _read_text(repo / "CODEX_S_L0.md")
    must_read = _read_text(repo / "SEED_CORTEX_MUST_READ_FIRST.md")
    gateway = _read_text(repo / "src" / "xinao_seedlab" / "adapters" / "capability_gateway.py")
    openapi = _read_text(repo / "contracts" / "openapi" / "seedlab.v1.yaml")
    policy = _read_text(repo / "policies" / "seed_cortex_phase0.rego")
    boundary = _read_json(repo / "contracts" / "codex-s-workspace-boundary.v1.json")
    reuse_schema = _read_json(repo / "contracts" / "schemas" / "seed_cortex_sidecar_capability_reuse.v1.json")
    reuse_state = _read_json(runtime / "state" / "seed_cortex_sidecar_capability_reuse" / "latest.json")

    boundary_index = boundary.get("deepseek_and_search_index", {}) if isinstance(boundary, dict) else {}
    schema_policy = (
        reuse_schema.get("properties", {})
        .get("parallel_policy", {})
        .get("properties", {})
        if isinstance(reuse_schema, dict)
        else {}
    )
    state_policy = reuse_state.get("parallel_policy", {}) if isinstance(reuse_state, dict) else {}

    checks = {
        "l0_names_dp_port": "dp_sidecar_execution_port" in l0 and "dp_search" in l0,
        "must_read_names_dp_port": "dp_sidecar_execution_port" in must_read and "not \"search only\"" in must_read,
        "boundary_declares_dp_search_as_mode": boundary_index.get("dp_search_is_mode_not_port_definition") is True,
        "boundary_lists_all_dp_modes": set(boundary_index.get("dp_sidecar_execution_modes", [])) == set(DP_MODE_IDS),
        "sidecar_schema_role_is_port": (
            schema_policy.get("deepseek_role", {}).get("const")
            == "dp_sidecar_execution_port_no_repo_mutation"
        ),
        "sidecar_schema_lists_modes": set(
            schema_policy.get("deepseek_execution_modes", {}).get("items", {}).get("enum", [])
        )
        == set(DP_MODE_IDS),
        "runtime_state_role_is_port": state_policy.get("deepseek_role") == "dp_sidecar_execution_port_no_repo_mutation",
        "runtime_state_lists_modes": set(state_policy.get("deepseek_execution_modes", [])) == set(DP_MODE_IDS),
        "gateway_search_provider_not_port": (
            'capability_kinds=["external_research", "dp_search", "source_ledger_claimcards"]'
            in gateway
            and "sidecar_execution_port" not in gateway.split('provider_id="deepseek.search_sidecar"', 1)[-1].split("local_model", 1)[0]
        ),
        "openapi_has_dp_mode_scopes": "dp_sidecar_execution_mode" in openapi and "dp_search_mode" in openapi,
        "opa_has_mode_aware_sidecar_subcommands": "allowed_dp_sidecar_subcommand" in policy,
    }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "contract_status": "active_contract_not_completion",
        "ontology_id": ONTOLOGY_ID,
        "generated_at": now_iso(),
        "ports": [
            {
                "port_id": "dp_sidecar_execution_port",
                "role": "supplemental_durable_subexecution_port",
                "resource_lane": "dp_sidecar",
                "provider_ids": ["legacy.deepseek_dp_sidecar"],
                "mode_ids": list(DP_MODE_IDS),
                "modes": _dp_modes(),
                "outputs_require_codex_fan_in_acceptance": True,
                "not_execution_controller": True,
            }
        ],
        "invariants": {
            "dp_search_is_mode_not_port_definition": True,
            "search_sidecar_must_not_advertise_sidecar_execution_port": True,
            "dp_outputs_require_codex_fan_in_acceptance": True,
            "ontology_is_source_for_l0_gateway_openapi_opa_readback": True,
        },
        "source_surfaces": _source_surfaces(repo, runtime),
        "runtime_refs": {
            "latest": str(runtime / "state" / "capability_port_mode_ontology" / "latest.json"),
            "readback": str(runtime / "readback" / "zh" / "capability_port_mode_ontology_20260702.md"),
        },
        "validation": {
            "passed": all(checks.values()),
            "checks": checks,
        },
        "default_boundary": boundary_fields(),
        **boundary_fields(),
    }
    if write:
        latest = runtime / "state" / "capability_port_mode_ontology" / "latest.json"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        readback = runtime / "readback" / "zh" / "capability_port_mode_ontology_20260702.md"
        readback.parent.mkdir(parents=True, exist_ok=True)
        readback.write_text(_render_readback(payload), encoding="utf-8")
    return payload


def _render_readback(payload: dict[str, Any]) -> str:
    modes = ", ".join(payload["ports"][0]["mode_ids"])
    status = "通过" if payload["validation"]["passed"] else "失败"
    return (
        "# Capability Port Mode Ontology\n\n"
        f"- 验证状态：{status}\n"
        "- DP 定义：`dp_sidecar_execution_port` 是子执行端口，不是搜索。\n"
        f"- DP modes：{modes}\n"
        "- `dp_search` 只是 search mode/provider route，不能冒充 DP port definition。\n"
        "- 所有 DP sidecar 输出都要进 Codex fan-in / ArtifactAcceptanceQueue；不能直升事实、完成或仓库写入。\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    payload = build_capability_port_mode_ontology(
        repo_root=args.repo_root,
        runtime_root=args.runtime_root,
        write=not args.no_write,
    )
    print(json.dumps({"validation": payload["validation"], "latest": payload["runtime_refs"]["latest"]}, ensure_ascii=False))
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
