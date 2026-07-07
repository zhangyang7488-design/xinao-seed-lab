import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Literal

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from services.agent_runtime import codex_centric_object_preserving_runtime as runtime
from services.agent_runtime import memory_budget_rollback_gate

DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
SENTINEL = "SENTINEL:XINAO_COMPLETION_CLAIM_PAYLOAD_BUILDER_PASS"
COMPLETION_LIKE_PATTERN = re.compile(
    r"(complete|completed|completion|done|finished|final|handoff|writeback|stop|"
    r"完成|已完成|结束|收尾|收口|交接|移交|写回|停止|可以停|报告完成)",
    re.IGNORECASE,
)
REPORT_LIKE_PATTERN = re.compile(
    r"(report|summary|handoff|writeback|final|morning_report|status|projection|"
    r"报告|总结|交接|移交|写回|最终|状态|投影|验收)",
    re.IGNORECASE,
)
CONTINUATION_MARKER_PATTERN = re.compile(
    r"(next action|next step|todo|gap|blocker|unfinished|continue|fix|repair|"
    r"named_blocker|open frontier|"
    r"下一步|继续|缺口|卡点|阻断|未完成|待处理|修复|问题|优化|开放前沿)",
    re.IGNORECASE,
)
CLOSURE_INTENT_PATTERN = re.compile(
    r"(closeout|closure|landed|complete closeout|full closeout|"
    r"收口|完整收口|全部收口|收口基础|默认主路|运行态|提交推送|提交合并|证据/readback)",
    re.IGNORECASE,
)
CLOSURE_EVIDENCE_REQUIRED_FIELDS = (
    "default_mainline_weld_point",
    "runtime_worker_loaded",
    "verification_passed",
    "evidence_readback_written",
    "git_status_clean",
    "commit_hash",
    "push_target",
    "mainline_state",
    "remaining_state",
)
CLOSURE_EVIDENCE_PATTERN_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "default_mainline_weld_point": (
        (
            r"default mainline",
            r"RootIntentLoop",
            r"S Default Dynamic Loop",
            r"TemporalCodexTaskWorkflow\.run",
            r"默认主路",
            r"焊",
            r"绑定",
        ),
    ),
    "runtime_worker_loaded": (
        (r"\bworker\b", r"\bpid\b", r"\bpolling\b", r"\bpollers\b", r"运行态"),
        (r"\bpolling\b", r"\bpollers\b", r"\bpid\b", r"\bloaded\b", r"\brestarted\b", r"加载", r"重启"),
    ),
    "verification_passed": (
        (r"\btest\b", r"\bpytest\b", r"\bverifier\b", r"验证", r"测试"),
        (r"\bpass(?:ed)?\b", r"\bgreen\b", r"通过", r"成功"),
    ),
    "evidence_readback_written": (
        (r"\bevidence\b", r"\breadback\b", r"证据", r"回读"),
    ),
    "git_status_clean": (
        (r"git status", r"\bworktree\b", r"工作区"),
        (r"\bclean\b", r"nothing to commit", r"干净", r"无改动"),
    ),
    "commit_hash": (
        (r"\bcommit\b", r"提交", r"\bsha\b", r"\bhash\b"),
        (r"\b[0-9a-f]{7,40}\b",),
    ),
    "push_target": (
        (r"\bpush(?:ed)?\b", r"origin/", r"远端", r"推送", r"合并"),
        (r"origin/main", r"\bmain\b", r"\bremote\b", r"远端", r"已推送"),
    ),
    "mainline_state": (
        (r"\b333\b", r"\bTemporal\b", r"RootIntentLoop", r"\bmainline\b", r"主线"),
        (r"\bactive\b", r"NO_ACTIVE_333_MAINLINE", r"\bpolling\b", r"\bworkflow\b", r"\brun_id\b", r"blocker", r"没有", r"无", r"状态"),
    ),
    "remaining_state": (
        (r"remaining_state", r"remaining", r"named_blocker", r"\bblocker\b", r"next_machine_action", r"剩余", r"未完成"),
        (r"\bnone\b", r"\bno\b", r"无", r"没有", r"named_blocker", r"BLOCKER", r"NO_ACTIVE_333_MAINLINE", r"TEMPORAL_"),
    ),
}


def user_goal_ref(user_goal: str) -> str:
    if not user_goal:
        return "no_user_goal_source"
    return f"non_authoritative_user_goal_sha256:{hashlib.sha256(user_goal.encode('utf-8')).hexdigest()}"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized[:120] or "codex_completion_claim"


def completion_like(text: str) -> bool:
    return bool(COMPLETION_LIKE_PATTERN.search(text or ""))


def _pattern_groups_match(text: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    return all(any(re.search(pattern, text, re.IGNORECASE) for pattern in group) for group in groups)


def closure_evidence_bundle_status(text: str, *, user_text: str = "") -> dict[str, Any]:
    evidence_text = text or ""
    intent_text = f"{user_text or ''}\n{evidence_text}"
    closure_intent = bool(CLOSURE_INTENT_PATTERN.search(intent_text))
    checks = {
        field: _pattern_groups_match(evidence_text, groups)
        for field, groups in CLOSURE_EVIDENCE_PATTERN_GROUPS.items()
    }
    missing = [
        field
        for field in CLOSURE_EVIDENCE_REQUIRED_FIELDS
        if not checks.get(field)
    ] if closure_intent else []
    return {
        "closure_intent": closure_intent,
        "complete": closure_intent and not missing,
        "required_fields": list(CLOSURE_EVIDENCE_REQUIRED_FIELDS),
        "checks": checks,
        "missing_fields": missing,
        "rule": (
            "Execution closure requires default mainline binding, runtime worker load, "
            "verification, evidence/readback, clean git status, commit hash, push target, "
            "333/mainline state, and remaining/named-blocker state."
        ),
    }


def report_requires_continuation(text: str) -> bool:
    value = text or ""
    closure = closure_evidence_bundle_status(value)
    if closure["closure_intent"]:
        return bool(completion_like(value) and not closure["complete"])
    if REPORT_LIKE_PATTERN.search(value) and CONTINUATION_MARKER_PATTERN.search(value):
        return True
    return False


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_if_exists(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def current_task_owner_for_claim(task_id: str, runtime_root: pathlib.Path) -> dict[str, Any]:
    state_root = runtime_root / "state" / "current_task_owner"
    candidates = [
        state_root / f"{safe_name(task_id)}.json",
        state_root / f"{task_id}.json",
        state_root / "latest.json",
    ]
    for path in candidates:
        owner = read_json_if_exists(path)
        if owner.get("task_id") == task_id:
            owner["claim_owner_ref"] = str(path)
            owner["claim_owner_ref_is_read_model_only"] = True
            return owner
    return {}


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "source_of_truth": "external_mature_runtime",
        "truth_carriers": [
            "Temporal workflow state",
            "LangGraph checkpoint/store",
            "OPA/Conftest policy decision",
            "completion claim gate decision",
            "machine verifier evidence",
        ],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "claim_payload_is_not_decision": True,
    }


def demote_payload(payload: dict[str, Any], role: str) -> dict[str, Any]:
    payload["not_source_of_truth"] = True
    payload["not_user_completion"] = True
    payload["authority_boundary"] = authority_boundary(role)
    return payload


def _contract(
    *,
    mode: Literal["partial", "complete"],
    task_id: str,
    user_goal: str,
    next_action: str,
) -> dict[str, Any]:
    is_complete = mode == "complete"
    return runtime.RefinementContract(
        contract_id=f"{safe_name(task_id)}_{mode}_completion_claim",
        parent=f"IMPLEMENT({runtime.TARGET_OBJECT})",
        children=runtime.DEFAULT_PATH if is_complete else ("semantic_entry_lock", "refinement_verifier"),
        requested_operation_ref=f"codex_default_task_runner:{task_id}",
        claim=(
            f"Full coverage for {runtime.TARGET_OBJECT} is verified for compiled goal ref: {user_goal_ref(user_goal)}"
            if is_complete
            else f"Partial checkpoint for {runtime.TARGET_OBJECT}; next action remains: {next_action}"
        ),
        proof_or_validator=(
            "Task-scoped completion claim: required frontier evidence is closed and the verifier gate must read the same task_id."
            if is_complete
            else "Partial checkpoint: open frontier is intentionally preserved before any completion claim."
        ),
        coverage_status="full" if is_complete else "partial",
        if_unproven="" if is_complete else "Continue frontier until coverage is full.",
        frontier_update={"items": [], "remaining": []} if is_complete else {"items": [{"frontier_id": "continue_execution", "next_action": next_action}], "remaining": ["continue_execution"]},
        completion_claimed=is_complete,
    ).model_dump(mode="json")


def _verification(
    *,
    mode: Literal["partial", "complete"],
    contract: dict[str, Any],
    next_action: str,
) -> dict[str, Any]:
    is_complete = mode == "complete"
    return runtime.VerificationResult(
        is_valid=True,
        coverage_claim=contract["claim"],
        proof_summary=contract["proof_or_validator"],
        issues=() if is_complete else ("FRONTIER_NOT_EMPTY",),
        recommendation="accept" if is_complete else "partial",
        frontier_open=not is_complete,
        completion_claimed=is_complete,
    ).model_dump(mode="json")


def _frontier(*, mode: Literal["partial", "complete"], next_action: str) -> dict[str, Any]:
    if mode == "complete":
        return runtime.FrontierState(status="empty").model_dump(mode="json")
    return runtime.FrontierState(
        status="open",
        items=({"frontier_id": "continue_execution", "next_action": next_action},),
    ).model_dump(mode="json")


def build_claim_payload(
    *,
    task_id: str,
    mode: Literal["rejected", "partial", "complete"] = "partial",
    user_goal: str = "",
    next_action: str = "Continue object-preserving execution until frontier is empty and coverage is proven.",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    include_evidence: bool = True,
    over_budget: bool = False,
    budget_user_confirmed: bool = False,
    token_budget_limit: int | None = None,
    cost_budget_usd_limit: float | None = None,
    human_visible_status: dict[str, Any] | None = None,
    current_task_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    owner = current_task_owner if current_task_owner is not None else current_task_owner_for_claim(task_id, runtime_root)
    evidence = (
        memory_budget_rollback_gate.build_evidence_fields(
            task_id=task_id,
            runtime_root=runtime_root,
            over_budget=over_budget,
            user_confirmed_over_budget=budget_user_confirmed,
            token_budget_limit=token_budget_limit,
            cost_budget_usd_limit=cost_budget_usd_limit,
            human_visible_status=human_visible_status,
        )
        if include_evidence
        else {}
    )
    if mode == "rejected":
        return demote_payload(runtime.CompletionClaim(
            task_object_id=task_id,
            frontier=runtime.FrontierState(
                status="open",
                items=({"frontier_id": "missing_contract_or_verification", "next_action": next_action},),
            ),
            current_task_owner=owner,
            **evidence,
        ).model_dump(mode="json"), "completion_claim_request_payload")

    contract = _contract(mode=mode, task_id=task_id, user_goal=user_goal, next_action=next_action)
    verification = _verification(mode=mode, contract=contract, next_action=next_action)
    return demote_payload(runtime.CompletionClaim(
        task_object_id=task_id,
        contract=runtime.RefinementContract(**contract),
        verification=runtime.VerificationResult(**verification),
        frontier=runtime.FrontierState(**_frontier(mode=mode, next_action=next_action)),
        current_task_owner=owner,
        **evidence,
    ).model_dump(mode="json"), "completion_claim_request_payload")


def write_claim_payload(
    *,
    payload: dict[str, Any],
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    output_path: pathlib.Path | None = None,
) -> pathlib.Path:
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    verification = payload.get("verification") if isinstance(payload.get("verification"), dict) else {}
    coverage_status = str(contract.get("coverage_status") or verification.get("recommendation") or "").lower()
    completion_claimed = contract.get("completion_claimed") is True or verification.get("completion_claimed") is True
    frontier_open = verification.get("frontier_open") is True or str((payload.get("frontier") or {}).get("status") or "").lower() == "open"
    stop_allowed = bool(payload.get("stop_allowed")) and not frontier_open and coverage_status in {"complete", "full"} and completion_claimed
    if "effective_status" not in payload:
        payload["effective_status"] = "complete_allowed" if stop_allowed else "partial_continue"
    payload["stop_allowed"] = stop_allowed
    payload["current_task_owner_bound"] = bool(payload.get("current_task_owner_bound", True))
    payload["requested_status_is_claim_request_not_fact"] = True
    payload["not_completion_decision"] = True
    payload["not_user_completion"] = True
    if output_path is None:
        task_id = payload.get("task_object_id") or "codex_completion_claim"
        output_path = runtime_root / "state" / "completion_claim_payloads" / f"{safe_name(str(task_id))}.json"
    write_json(output_path, payload)
    return output_path


def build_continuation_envelope(
    *,
    task_id: str,
    reason: str,
    next_action: str,
    claim_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    return demote_payload({
        "schema_version": "xinao.completion_claim_continuation_envelope.v1",
        "generated_at": now(),
        "status": "partial_continue_required",
        "task_object_id": task_id,
        "reason": reason,
        "frontier_preserved": True,
        "complete_allowed": False,
        "stop_allowed": False,
        "next_action": next_action,
        "claim_path": str(claim_path) if claim_path else None,
        "hard_laws": [
            "object_replacement_forbidden",
            "operation_degradation_forbidden",
            "completion_requires_empty_frontier_full_contract_coverage",
            "partial_or_rejected_must_preserve_frontier_and_next_action",
        ],
    }, "completion_claim_continuation_envelope")


def build_report_continuation_envelope(
    *,
    task_id: str,
    report_text: str,
    next_action: str = "Convert report gaps/next steps into machine actions and continue execution.",
    claim_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    if not report_requires_continuation(report_text):
        return {}
    closure = closure_evidence_bundle_status(report_text)
    closure_incomplete = bool(closure["closure_intent"] and not closure["complete"])
    envelope = build_continuation_envelope(
        task_id=task_id,
        reason="CLOSURE_EVIDENCE_BUNDLE_MISSING_OR_INCOMPLETE" if closure_incomplete else "REPORT_CONTAINS_CONTINUATION_MARKERS",
        next_action=(
            "Fill the execution closure bundle: default mainline binding, runtime worker load, "
            "verification, evidence/readback, clean git status, commit hash, push target, "
            "333/mainline state, and remaining/named-blocker state."
            if closure_incomplete
            else next_action
        ),
        claim_path=claim_path,
    )
    envelope["report_stop_inversion"] = True
    envelope["report_text_is_not_terminal"] = True
    envelope["closure_evidence_bundle"] = closure
    envelope["report_terminal_rule"] = (
        "Reports, summaries, handoffs, projections, and final files are evidence views; "
        "when they contain gaps or next actions they must become continuation work items."
    )
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strict /completion/claim payloads for Codex default paths.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--mode", choices=("rejected", "partial", "complete"), default="partial")
    parser.add_argument("--user-goal", default="")
    parser.add_argument("--next-action", default="Continue object-preserving execution until frontier is empty and coverage is proven.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--output-path", default="")
    parser.add_argument("--completion-text", default="")
    parser.add_argument("--without-evidence", action="store_true")
    parser.add_argument("--over-budget", action="store_true")
    parser.add_argument("--budget-user-confirmed", action="store_true")
    parser.add_argument("--token-budget-limit", type=int, default=None)
    parser.add_argument("--cost-budget-usd-limit", type=float, default=None)
    args = parser.parse_args()

    runtime_root = pathlib.Path(args.runtime_root)
    output_path = pathlib.Path(args.output_path) if args.output_path else None
    payload = build_claim_payload(
        task_id=args.task_id,
        mode=args.mode,
        user_goal=args.user_goal,
        next_action=args.next_action,
        runtime_root=runtime_root,
        include_evidence=not args.without_evidence,
        over_budget=args.over_budget,
        budget_user_confirmed=args.budget_user_confirmed,
        token_budget_limit=args.token_budget_limit,
        cost_budget_usd_limit=args.cost_budget_usd_limit,
    )
    claim_path = write_claim_payload(payload=payload, runtime_root=runtime_root, output_path=output_path)
    report_continuation_envelope = build_report_continuation_envelope(
        task_id=args.task_id,
        report_text=args.completion_text,
        next_action=args.next_action,
        claim_path=claim_path,
    )
    result = demote_payload({
        "schema_version": "xinao.completion_claim_payload_builder.cli.v1",
        "generated_at": now(),
        "status": "payload_built",
        "task_object_id": args.task_id,
        "mode": args.mode,
        "completion_like": completion_like(args.completion_text),
        "closure_evidence_bundle": closure_evidence_bundle_status(args.completion_text),
        "report_requires_continuation": bool(report_continuation_envelope),
        "report_stop_inverted": bool(report_continuation_envelope),
        "report_continuation_envelope": report_continuation_envelope,
        "required_evidence_fields_present": all(payload.get(field) for field in memory_budget_rollback_gate.REQUIRED_CLAIM_FIELDS),
        "claim_path": str(claim_path),
        "sentinel": SENTINEL,
    }, "completion_claim_payload_builder_cli_result")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
