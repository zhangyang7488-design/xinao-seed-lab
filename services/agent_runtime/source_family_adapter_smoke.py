from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from services.agent_runtime import next_frontier_continuation_supervisor as next_frontier_supervisor


SCHEMA_VERSION = "xinao.codex_s.source_family_adapter_smoke.v1"
SENTINEL = "SENTINEL:XINAO_SOURCE_FAMILY_ADAPTER_SMOKE_READY"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
PARENT_TASK_ID = WORK_ID
TASK_ID = "wave6_source_family_adapter_smoke_20260704"
ROUTING = "continue_same_task"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")
SMOKE_ACTION = "smoke_mature_carrier_adapter_candidates"
NEXT_ACTION = "implement_thin_bind_adapter_for_smoked_candidates"
THIN_BIND_NEXT_ACTION = "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway"
RETRY_ACTION = "retry_source_family_adapter_smoke_or_write_named_blocker"
IDEMPOTENT_REPLAY_ACTIONS = {NEXT_ACTION, THIN_BIND_NEXT_ACTION, RETRY_ACTION}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def replace_path_with_retry(tmp: Path, path: Path) -> None:
    last_error: PermissionError | None = None
    for attempt in range(25):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_path_with_retry(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_path_with_retry(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def path_digest(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def json_ref(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "path": str(path),
        "exists": path.is_file(),
        "json_valid": bool(payload) or not path.is_file(),
        "sha256": path_digest(path),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "wave_id": payload.get("wave_id"),
        "task_id": payload.get("task_id"),
        "validation_passed": validation.get("passed"),
        "not_execution_controller": payload.get("not_execution_controller"),
    }


def safe_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    chars = [ch if ch.isalnum() else "-" for ch in text]
    cleaned = "-".join("".join(chars).split("-"))
    return cleaned[:96] or "candidate"


def output_paths(repo: Path, runtime: Path, wave_id: str) -> dict[str, str]:
    root = runtime / "state" / "source_family_adapter_smoke"
    return {
        "runtime_latest": str(root / "latest.json"),
        "wave_latest": str(root / "waves" / f"{wave_id}.json"),
        "candidate_results_latest": str(root / "candidate_results" / "latest.json"),
        "candidate_results_wave": str(root / "candidate_results" / f"{wave_id}.json"),
        "candidate_result_dir": str(root / "candidate_results" / wave_id),
        "schema": str(repo / "contracts" / "schemas" / "codex_s_source_family_adapter_smoke.v1.json"),
        "candidate_queue_latest": str(
            runtime / "state" / "source_family_mature_thin_bind_sunset" / "candidate_adapter_smoke_queue" / "latest.json"
        ),
        "phase5_sunset_latest": str(runtime / "state" / "source_family_mature_thin_bind_sunset" / "latest.json"),
        "previous_next_frontier_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "next_frontier_machine_actions_latest": str(runtime / "state" / "next_frontier_machine_actions" / "latest.json"),
        "artifact_acceptance_queue_latest": str(runtime / "state" / "artifact_acceptance_queue" / "latest.json"),
        "source_ledger_latest": str(runtime / "state" / "source_ledger" / "latest.json"),
        "manifest": str(runtime / "capabilities" / "codex_s.source_family_adapter_smoke" / "manifest.json"),
        "readback_zh": str(runtime / "readback" / "zh" / "source_family_adapter_smoke_20260704.md"),
    }


def first_next_action(payload: dict[str, Any]) -> str:
    actions = payload.get("next_frontier")
    if isinstance(actions, list) and actions:
        first = actions[0]
        if isinstance(first, dict):
            return str(first.get("action") or "")
    return ""


def run_git_ls_remote(source_url: str, timeout_sec: int) -> dict[str, Any]:
    started = now_iso()
    try:
        completed = subprocess.run(
            ["git", "ls-remote", "--heads", source_url],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "probe": "git_ls_remote_heads",
            "started_at": started,
            "ok": False,
            "error": str(exc),
            "returncode": -1,
            "stdout_excerpt": "",
            "stderr_excerpt": "",
        }
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    first_ref = stdout_lines[0].split()[0] if stdout_lines and stdout_lines[0].split() else ""
    return {
        "probe": "git_ls_remote_heads",
        "started_at": started,
        "ok": completed.returncode == 0 and bool(stdout_lines),
        "returncode": completed.returncode,
        "first_ref_sha": first_ref,
        "stdout_excerpt": "\n".join(stdout_lines[:3])[:1000],
        "stderr_excerpt": completed.stderr[:1000],
    }


def run_http_probe(source_url: str, timeout_sec: int) -> dict[str, Any]:
    started = now_iso()
    request = urllib_request.Request(source_url, method="HEAD", headers={"User-Agent": "CodexS-AdapterSmoke/1.0"})
    try:
        with urllib_request.urlopen(request, timeout=timeout_sec) as response:
            return {
                "probe": "http_head",
                "started_at": started,
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "final_url": response.geturl(),
            }
    except (urllib_error.URLError, ValueError, TimeoutError) as exc:
        return {
            "probe": "http_head",
            "started_at": started,
            "ok": False,
            "error": str(exc),
            "status_code": 0,
        }


def source_probe(source_url: str, *, probe_mode: str, timeout_sec: int) -> dict[str, Any]:
    if probe_mode == "synthetic":
        digest = hashlib.sha256(source_url.encode("utf-8", errors="replace")).hexdigest()
        return {
            "probe_mode": probe_mode,
            "source_url": source_url,
            "source_reachable": True,
            "git_ls_remote": {
                "probe": "synthetic_git_ls_remote_heads",
                "ok": True,
                "first_ref_sha": digest[:40],
                "stdout_excerpt": f"{digest[:40]}\trefs/heads/main",
            },
            "http_probe": {"probe": "synthetic_http_head", "ok": True, "status_code": 200},
            "live_network_invoked": False,
        }
    git_probe = run_git_ls_remote(source_url, timeout_sec)
    http_probe = {"probe": "http_head", "ok": False, "skipped": git_probe.get("ok") is True}
    if git_probe.get("ok") is not True:
        http_probe = run_http_probe(source_url, timeout_sec)
    return {
        "probe_mode": probe_mode,
        "source_url": source_url,
        "source_reachable": git_probe.get("ok") is True or http_probe.get("ok") is True,
        "git_ls_remote": git_probe,
        "http_probe": http_probe,
        "live_network_invoked": True,
    }


def build_candidate_result(
    *,
    candidate: dict[str, Any],
    index: int,
    paths: dict[str, str],
    probe_mode: str,
    timeout_sec: int,
) -> dict[str, Any]:
    source_url = str(candidate.get("source_url") or "")
    probe = source_probe(source_url, probe_mode=probe_mode, timeout_sec=timeout_sec) if source_url else {
        "probe_mode": probe_mode,
        "source_url": source_url,
        "source_reachable": False,
        "git_ls_remote": {},
        "http_probe": {},
        "live_network_invoked": probe_mode == "live",
    }
    binding_id = str(candidate.get("binding_id") or f"candidate-{index:02d}")
    result_path = Path(paths["candidate_result_dir"]) / f"{index:02d}-{safe_id(binding_id)}.json"
    checks = {
        "binding_id_present": bool(binding_id),
        "source_claim_card_present": bool(candidate.get("source_claim_card_id")),
        "source_url_present": bool(source_url),
        "source_probe_reachable": probe.get("source_reachable") is True,
        "promotion_gate_enforced": candidate.get("promotion_gate") == "adapter_smoke_before_default_capability",
        "not_promoted_before_smoke": candidate.get("thin_bind_landed") is False,
    }
    passed = all(checks.values())
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.candidate_result.v1",
        "status": "adapter_smoke_reference_probe_passed" if passed else "adapter_smoke_reference_probe_blocked",
        "candidate_index": index,
        "queue_id": candidate.get("queue_id"),
        "binding_id": binding_id,
        "mature_carrier": candidate.get("mature_carrier"),
        "handrolled_surface": candidate.get("handrolled_surface"),
        "source_claim_card_id": candidate.get("source_claim_card_id"),
        "source_url": source_url,
        "promotion_gate": candidate.get("promotion_gate"),
        "thin_bind_landed": candidate.get("thin_bind_landed") is True,
        "probe": probe,
        "proposed_adapter_scope": {
            "adapter_kind": "source_reachable_reference_probe",
            "promotion_allowed": False,
            "next_required_action": "implement_thin_bind_adapter_for_smoked_candidate",
        },
        "output_path": str(result_path),
        "validation": {"passed": passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    return payload


def build_manifest(paths: dict[str, str], validation_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.source_family_adapter_smoke",
        "status": "ready" if validation_passed else "blocked",
        "invoke": {
            "cli": "python -m xinao_seedlab.cli.__main__ source-family-adapter-smoke --wave-id <wave>",
            "verifier": "scripts/verify_source_family_adapter_smoke.ps1",
            "input_action": SMOKE_ACTION,
        },
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "consumes": [
            paths["candidate_queue_latest"],
            paths["phase5_sunset_latest"],
            paths["previous_next_frontier_latest"],
        ],
        "writes": [
            paths["runtime_latest"],
            paths["candidate_results_latest"],
            paths["next_frontier_machine_actions_latest"],
        ],
        "not_completion_boundary": True,
        "secret_values_recorded": False,
    }


def build_next_frontier(
    *,
    wave_id: str,
    parent_wave_id: str,
    paths: dict[str, str],
    validation_passed: bool,
) -> dict[str, Any]:
    if validation_passed:
        next_items = [
            {
                "action_id": "next-wave-implement-smoked-thin-bind-adapters",
                "action": NEXT_ACTION,
                "why": "Candidate mature-carrier source probes passed; continue with thin adapter implementation, not promotion by report.",
                "requires": [
                    paths["candidate_results_latest"],
                    "thin adapter implementation diff",
                    "AAQ",
                    "SourceLedger",
                ],
            },
            {
                "action_id": "next-wave-default-temporal-chain-poll",
                "action": "keep_default_temporal_chain_polling",
                "why": "Adapter smoke is not completion; foreground/background polling continues.",
                "requires": ["Temporal task queue poller", "worker dispatch ledger"],
            },
        ]
    else:
        next_items = [
            {
                "action_id": "retry-source-family-adapter-smoke",
                "action": "retry_source_family_adapter_smoke_or_write_named_blocker",
                "why": "One or more candidate adapter smoke probes did not pass.",
                "requires": [paths["candidate_queue_latest"], paths["candidate_results_latest"]],
            }
        ]
    return {
        "schema_version": "xinao.codex_s.next_frontier_machine_actions.v1",
        "status": "adapter_smoke_next_frontier_ready" if validation_passed else "adapter_smoke_next_frontier_repair_required",
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "should_continue_loop": True,
        "stop_allowed": False,
        "stop_allowed_reason": "adapter_smoke_is_evidence_only_thin_adapter_implementation_still_open",
        "adapter_smoke": {
            "consumed_action": SMOKE_ACTION,
            "candidate_results_ref": paths["candidate_results_latest"],
        },
        "next_frontier": next_items,
        "output_paths": {"runtime_latest": paths["next_frontier_machine_actions_latest"]},
        "validation": {
            "passed": validation_passed,
            "checks": {
                "adapter_smoke_action_consumed": validation_passed,
                "candidate_results_ref_written": bool(paths["candidate_results_latest"]),
                "stop_denied": True,
            },
        },
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def render_readback(payload: dict[str, Any]) -> str:
    checks = payload.get("validation", {}).get("checks", {})
    lines = [
        "# Source-family adapter smoke readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- parent_wave_id: `{payload.get('parent_wave_id')}`",
        f"- consumed action: `{payload.get('consumed_next_frontier_action')}`",
        f"- candidates passed: {payload.get('passed_candidate_count')} / {payload.get('candidate_count')}",
        f"- candidate_results: `{payload.get('output_paths', {}).get('candidate_results_latest')}`",
        f"- next_frontier: `{payload.get('output_paths', {}).get('next_frontier_machine_actions_latest')}`",
        "",
        "验收三句：",
        "1. 本动作消费的是 phase5 写出的 `smoke_mature_carrier_adapter_candidates`，不是完成声明。",
        "2. smoke 只验证候选成熟载体 source/gate/引用可继续适配，不把候选直接提升成默认能力。",
        "3. 下一步是写 thin adapter diff 并继续 AAQ/SourceLedger/FanIn，不允许停在报告。",
        "",
        f"- validation checks: `{checks}`",
        "",
        SENTINEL,
        "",
    ]
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "wave-block6-source-family-adapter-smoke",
    probe_mode: str = "live",
    timeout_sec: int = 20,
    write: bool = True,
) -> dict[str, Any]:
    del anchor_package_root
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    paths = output_paths(repo, runtime, wave_id)
    candidate_queue = read_json(Path(paths["candidate_queue_latest"]))
    phase5_sunset = read_json(Path(paths["phase5_sunset_latest"]))
    previous_next_frontier = read_json(Path(paths["previous_next_frontier_latest"]))
    phase5_next_frontier = (
        phase5_sunset.get("next_frontier_machine_actions")
        if isinstance(phase5_sunset.get("next_frontier_machine_actions"), dict)
        else {}
    )
    effective_next_frontier = (
        phase5_next_frontier
        if first_next_action(phase5_next_frontier) == SMOKE_ACTION
        else previous_next_frontier
    )
    aaq = read_json(Path(paths["artifact_acceptance_queue_latest"]))
    source_ledger = read_json(Path(paths["source_ledger_latest"]))
    candidates = candidate_queue.get("candidates") if isinstance(candidate_queue.get("candidates"), list) else []

    candidate_results = [
        build_candidate_result(
            candidate=item if isinstance(item, dict) else {},
            index=index,
            paths=paths,
            probe_mode=probe_mode,
            timeout_sec=timeout_sec,
        )
        for index, item in enumerate(candidates, start=1)
    ]
    passed_candidate_count = sum(1 for item in candidate_results if item.get("validation", {}).get("passed") is True)
    previous_action = first_next_action(effective_next_frontier)
    already_consumed = (
        previous_action in IDEMPOTENT_REPLAY_ACTIONS
        and effective_next_frontier.get("stop_allowed") is False
    )
    consumed_action = SMOKE_ACTION if already_consumed else previous_action
    parent_wave_id = str(
        effective_next_frontier.get("parent_wave_id")
        if already_consumed
        else effective_next_frontier.get("wave_id")
        or phase5_sunset.get("wave_id")
        or candidate_queue.get("wave_id")
        or ""
    )
    checks = {
        "candidate_queue_ready": candidate_queue.get("validation", {}).get("passed") is True
        if isinstance(candidate_queue.get("validation"), dict)
        else False,
        "candidate_queue_nonempty": len(candidates) > 0,
        "previous_next_action_smoke_or_idempotent": previous_action == SMOKE_ACTION or already_consumed,
        "phase5_sunset_validation_passed": phase5_sunset.get("validation", {}).get("passed") is True
        if isinstance(phase5_sunset.get("validation"), dict)
        else False,
        "all_candidate_smokes_passed": bool(candidate_results) and passed_candidate_count == len(candidate_results),
        "no_candidate_promoted_by_smoke": all(item.get("thin_bind_landed") is not True for item in candidate_results),
        "aaq_and_source_ledger_present": bool(aaq) and bool(source_ledger),
        "completion_claim_denied": True,
    }
    validation_passed = all(checks.values())
    candidate_results_payload = {
        "schema_version": f"{SCHEMA_VERSION}.candidate_results.v1",
        "status": "adapter_smoke_candidate_results_ready" if validation_passed else "adapter_smoke_candidate_results_blocked",
        "work_id": WORK_ID,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "candidate_count": len(candidate_results),
        "passed_candidate_count": passed_candidate_count,
        "probe_mode": probe_mode,
        "results": candidate_results,
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    repair_plan = {
        "schema_version": "xinao.codex_s.source_family_adapter_smoke_repair_plan.v1",
        "status": "repair_not_required" if validation_passed else "repair_required",
        "named_blocker": "" if validation_passed else "SOURCE_FAMILY_ADAPTER_SMOKE_INPUT_OR_NETWORK_BLOCKED",
        "missing_checks": [name for name, passed in checks.items() if not passed],
        "return_to_main_route": True,
        "not_user_completion": True,
        "not_execution_controller": True,
    }
    manifest = build_manifest(paths, validation_passed)
    next_frontier = build_next_frontier(
        wave_id=wave_id,
        parent_wave_id=parent_wave_id,
        paths=paths,
        validation_passed=validation_passed,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "parent_task_id": PARENT_TASK_ID,
        "task_id": TASK_ID,
        "routing": ROUTING,
        "route_profile": ROUTE_PROFILE,
        "wave_id": wave_id,
        "parent_wave_id": parent_wave_id,
        "status": "source_family_adapter_smoke_ready" if validation_passed else "source_family_adapter_smoke_blocked",
        "generated_at": now_iso(),
        "consumed_next_frontier_action": consumed_action,
        "probe_mode": probe_mode,
        "candidate_count": len(candidate_results),
        "passed_candidate_count": passed_candidate_count,
        "input_refs": {
            "candidate_queue_latest": json_ref(Path(paths["candidate_queue_latest"])),
            "phase5_sunset_latest": json_ref(Path(paths["phase5_sunset_latest"])),
            "previous_next_frontier_latest": json_ref(Path(paths["previous_next_frontier_latest"])),
            "phase5_wave_specific_next_frontier_used": first_next_action(phase5_next_frontier) == SMOKE_ACTION,
            "artifact_acceptance_queue_latest": json_ref(Path(paths["artifact_acceptance_queue_latest"])),
            "source_ledger_latest": json_ref(Path(paths["source_ledger_latest"])),
        },
        "candidate_results": candidate_results_payload,
        "capability_manifest": manifest,
        "next_frontier_machine_actions": next_frontier,
        "repair_plan": repair_plan,
        "output_paths": paths,
        "validation": {"passed": validation_passed, "checks": checks},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        result_dir = Path(paths["candidate_result_dir"])
        for result in candidate_results:
            write_json(Path(str(result.get("output_path") or result_dir / "candidate.json")), result)
        write_json(Path(paths["candidate_results_latest"]), candidate_results_payload)
        write_json(Path(paths["candidate_results_wave"]), candidate_results_payload)
        write_json(Path(paths["manifest"]), manifest)
        next_frontier_supervisor.promote_candidate_next_frontier(
            runtime_root=runtime,
            candidate=next_frontier,
            source_kind="source_family_adapter_smoke",
            source_ref=paths["runtime_latest"],
        )
        write_json(Path(paths["runtime_latest"]), payload)
        write_json(Path(paths["wave_latest"]), payload)
        write_text(Path(paths["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke source-family mature-carrier adapter candidates.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="wave-block6-source-family-adapter-smoke")
    parser.add_argument("--probe-mode", choices=["live", "synthetic"], default="live")
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        probe_mode=args.probe_mode,
        timeout_sec=args.timeout_sec,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
