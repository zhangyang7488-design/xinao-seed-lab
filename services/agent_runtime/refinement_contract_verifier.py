import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

DEFAULT_REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
ACTIVE_OBJECT_ID = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
VERIFIER_OBJECT_ID = "XINAO_REFINEMENT_CONTRACT_VERIFIER"
FULL_OBJECT_ID = "XINAO_SEMANTIC_LOCKED_AUTONOMOUS_EXECUTION_RUNTIME"
SENTINEL = "SENTINEL:XINAO_REFINEMENT_CONTRACT_VERIFIER_PASS"


def now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run_id():
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path, payload):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def authority_boundary(role):
    return {
        "schema_version": "xinao.authority-boundary.v1",
        "role": role,
        "source_of_truth": "external_mature_runtime",
        "authoritative_sources": [
            "OPA/Conftest policy decision",
            "Temporal workflow state and event history",
            "LangGraph checkpoint/frontier state",
            "verifier evidence",
            "human-visible acceptance when required",
        ],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_lifecycle_owner": True,
        "machine_readable_boundary": True,
    }


def demote_read_model(payload, role):
    payload["not_source_of_truth"] = True
    payload["not_user_completion"] = True
    payload["not_completion_decision"] = True
    payload["not_lifecycle_owner"] = True
    payload["authority_boundary"] = authority_boundary(role)
    return payload


def build_contract(
    contract_id,
    coverage_status,
    *,
    children=None,
    proof_or_validator="",
    frontier_update=None,
    operation_preserved=True,
    object_preserved=True,
    completion_requested=False,
    completion_claimed=None,
    claim="",
    if_unproven="",
):
    if completion_claimed is not None:
        completion_requested = completion_claimed
    return demote_read_model({
        "schema_version": "xinao.refinement_contract.v1",
        "contract_id": contract_id,
        "active_object_id": ACTIVE_OBJECT_ID,
        "original_object_ref": ACTIVE_OBJECT_ID,
        "parent": f"REFINE({FULL_OBJECT_ID})",
        "children": children or [
            "SEMLOCK-004 refinement_contract_verifier",
            "SEMLOCK-005 frontier_and_partial_state",
        ],
        "requested_operation_ref": "object-preserving autonomous planning/execution with explicit coverage and frontier",
        "claim": claim or "Children cover the parent scope under the scoped SEMLOCK-004/005 canary boundary.",
        "proof_or_validator": proof_or_validator,
        "coverage_status": coverage_status,
        "if_unproven": if_unproven,
        "frontier_update": frontier_update if frontier_update is not None else {"items": [], "remaining": []},
        "operation_preserved": operation_preserved,
        "object_preserved": object_preserved,
        "completion_requested": completion_requested,
        "completion_boundary": "completion_requested is scoped OPA canary input only; it is not user completion and not whole-runtime completion.",
    }, "refinement_contract_fixture")


def accepted_full_contract():
    return build_contract(
        "accepted_full_semantic_lock_refinement",
        "full",
        proof_or_validator="OPA policy data.xinao.refinement_contract_verifier.deny returned empty set for this scoped contract.",
        frontier_update={"items": [], "remaining": [], "status": "empty_after_full_coverage"},
        completion_requested=True,
    )


def accepted_partial_frontier_contract():
    return build_contract(
        "accepted_partial_frontier_semantic_lock_refinement",
        "partial",
        proof_or_validator="OPA policy accepts explicit frontier while refusing whole-object completion.",
        frontier_update={
            "status": "frontier_open",
            "items": [
                {
                    "frontier_id": "SEMLOCK-006-013",
                    "reason": "Durable executor, policy admission, trace/eval, S13, recursive maintenance, and stop audit remain open.",
                }
            ],
            "remaining": ["SEMLOCK-006", "SEMLOCK-007", "SEMLOCK-008", "SEMLOCK-009", "SEMLOCK-010", "SEMLOCK-011", "SEMLOCK-013"],
        },
        completion_requested=False,
        if_unproven="Keep this frontier in state; do not report complete.",
    )


def rejected_partial_complete_contract():
    contract = accepted_partial_frontier_contract()
    contract["contract_id"] = "rejected_partial_frontier_claimed_complete"
    contract["completion_requested"] = True
    return contract


def rejected_unproven_without_frontier_contract():
    return build_contract(
        "rejected_unproven_without_frontier",
        "unproven",
        proof_or_validator="candidate coverage only",
        frontier_update={"items": [], "remaining": []},
        completion_requested=False,
        if_unproven="No frontier was supplied; this must be denied.",
    )


def rejected_replacement_contract():
    return build_contract(
        "rejected_object_operation_replacement",
        "full",
        proof_or_validator="invalid because it replaces object and operation",
        operation_preserved=False,
        object_preserved=False,
        completion_requested=True,
    )


def run_opa(repo, contract_path):
    completed = subprocess.run(
        [
            "opa",
            "eval",
            "--format=json",
            "--data",
            str(pathlib.Path(repo) / "policies" / "refinement_contract_verifier.rego"),
            "--input",
            str(contract_path),
            "data.xinao.refinement_contract_verifier.deny",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return [f"OPA_EVAL_FAILED: {completed.stderr.strip() or completed.stdout.strip()}"]
    try:
        value = json.loads(completed.stdout)["result"][0]["expressions"][0]["value"]
        return sorted(value)
    except Exception as exc:
        return [f"OPA_PARSE_FAILED: {type(exc).__name__}"]


def verify_contract(contract, repo_root=DEFAULT_REPO, output_dir=None):
    repo = pathlib.Path(repo_root)
    if output_dir is None:
        output_dir = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME") / "artifacts" / "tmp" / "refinement_contract_verifier"
    output_dir = pathlib.Path(output_dir)
    contract_path = output_dir / f"{contract.get('contract_id', 'contract')}.json"
    write_json(contract_path, contract)
    denies = run_opa(repo, contract_path)
    return demote_read_model({
        "contract_id": contract.get("contract_id"),
        "contract_path": str(contract_path),
        "is_valid": len(denies) == 0,
        "denies": denies,
        "coverage_status": contract.get("coverage_status"),
        "frontier_open": bool(
            (contract.get("frontier_update") or {}).get("items")
            or (contract.get("frontier_update") or {}).get("remaining")
        ),
        "completion_requested": contract.get("completion_requested") is True,
        "completion_boundary": "is_valid means this scoped OPA contract result only; it is not user completion.",
    }, "refinement_contract_opa_result")


def build(repo_root=DEFAULT_REPO, runtime_root=DEFAULT_RUNTIME, output_dir=None):
    repo = pathlib.Path(repo_root)
    runtime = pathlib.Path(runtime_root)
    rid = run_id()
    output_dir = pathlib.Path(output_dir) if output_dir else runtime / "artifacts" / "generated" / "refinement_contract_verifier" / rid
    state_latest = runtime / "state" / "refinement_contract_verifier" / "latest.json"

    contracts = {
        "accepted_full_contract": accepted_full_contract(),
        "accepted_partial_frontier_contract": accepted_partial_frontier_contract(),
        "rejected_partial_complete_contract": rejected_partial_complete_contract(),
        "rejected_unproven_without_frontier_contract": rejected_unproven_without_frontier_contract(),
        "rejected_replacement_contract": rejected_replacement_contract(),
    }
    results = {
        name: verify_contract(contract, repo_root=repo, output_dir=output_dir / "contracts")
        for name, contract in contracts.items()
    }
    acceptance = {
        "accepted_full_contract_passed": results["accepted_full_contract"]["is_valid"] is True,
        "accepted_partial_frontier_contract_passed": results["accepted_partial_frontier_contract"]["is_valid"] is True,
        "partial_as_complete_denied": results["rejected_partial_complete_contract"]["is_valid"] is False,
        "unproven_without_frontier_denied": results["rejected_unproven_without_frontier_contract"]["is_valid"] is False,
        "object_operation_replacement_denied": results["rejected_replacement_contract"]["is_valid"] is False,
        "opa_policy_gate_used": True,
    }
    passed = all(acceptance.values())
    payload = {
        "schema_version": "xinao.refinement-contract-verifier.v1",
        "status": "refinement_contract_verifier_scoped_verified" if passed else "refinement_contract_verifier_blocked",
        "generated_at": now(),
        "run_id": rid,
        "active_object_id": ACTIVE_OBJECT_ID,
        "verifier_object_id": VERIFIER_OBJECT_ID,
        "scoped_items": ["SEMLOCK-004", "SEMLOCK-005"],
        "policy": {
            "carrier": "OPA/Conftest",
            "policy_path": str(repo / "policies" / "refinement_contract_verifier.rego"),
            "schema_path": str(repo / "schemas" / "refinement-contract.schema.json"),
        },
        "contracts": contracts,
        "verification_results": results,
        "acceptance": acceptance,
        "human_visible_status": "这是 SEMLOCK-004/005 scoped 验证：refinement contract 和 partial/frontier gate 已用 OPA canary 验证。它不是用户完成，不是 S13，也不代表整个 XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME 完成。",
        "claim_boundaries": {
            "user_completion_allowed": False,
            "s13_allowed": False,
            "whole_runtime_completion_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "authority_boundary": authority_boundary("refinement_claim_boundaries_readback"),
        },
        "completion_boundary_cn": "accepted full contract 只证明 scoped full contract 可通过；partial/unproven 必须保留 frontier，不能被说成 complete。",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_lifecycle_owner": True,
        "authority_boundary": authority_boundary("refinement_contract_verifier_read_model"),
        "artifact_paths": {
            "output_dir": str(output_dir),
            "runtime_state_latest": str(state_latest),
        },
        "rollback_path": "Repo rollback: delete refinement_contract_verifier service, Rego policy, schema, test, verifier script, and dispatcher integration lines. Runtime rollback: delete D:/XINAO_CLEAN_RUNTIME/state/refinement_contract_verifier and generated artifacts.",
        "sentinel": SENTINEL if passed else "SENTINEL:XINAO_REFINEMENT_CONTRACT_VERIFIER_BLOCKED",
    }
    write_json(output_dir / "refinement_contract_verifier.json", payload)
    write_json(output_dir / "accepted_full_contract.json", contracts["accepted_full_contract"])
    write_json(output_dir / "accepted_partial_frontier_contract.json", contracts["accepted_partial_frontier_contract"])
    write_json(state_latest, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description="Verify XINAO refinement contracts with OPA.")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    payload = build(args.repo_root, args.runtime_root, args.output_dir)
    print(json.dumps({
        "schema_version": "xinao.refinement_contract_verifier_generation.v1",
        "status": payload["status"],
        "acceptance": payload["acceptance"],
        "human_visible_status": payload["human_visible_status"],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "authority_boundary": authority_boundary("cli_generation_summary"),
        "sentinel": payload["sentinel"],
    }, ensure_ascii=False, indent=2))
    print(payload["sentinel"])
    return 0 if payload["sentinel"] == SENTINEL else 1


if __name__ == "__main__":
    sys.exit(main())
