from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime import codex_s_worker_lane_carrier as lane_carrier

SCHEMA_VERSION = "xinao.codex_s.direct_worker_lane.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_DIRECT_WORKER_LANE"
TASK_ID = "codex_s_direct_worker_lane_20260705"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = lane_carrier.DEFAULT_REPO
STATE_NAME = "codex_s_direct_worker_lane"
PROVIDER_CHOICES = ("auto", "qwen", "dp")
S_VENV_REINVOKE_ENV = "XINAO_DIRECT_WORKER_LANE_REINVOKED_S_VENV"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / STATE_NAME
    return {
        "state": state,
        "latest": state / "latest.json",
        "records": state / "records",
        "readback": runtime / "readback" / "zh" / f"{STATE_NAME}.md",
    }


def _read_text_arg(*, input_text: str, input_file: str) -> str:
    if input_file:
        return Path(input_file).read_text(encoding="utf-8", errors="replace")
    return input_text


def should_reinvoke_s_venv_for_qwen(
    *,
    provider: str,
    mode: str,
    repo: Path,
    qwen_invoker_provided: bool,
    python_carrier: dict[str, Any] | None = None,
) -> bool:
    if qwen_invoker_provided:
        return False
    if os.environ.get(S_VENV_REINVOKE_ENV) == "1":
        return False
    if provider not in {"auto", "qwen"}:
        return False
    if mode not in lane_carrier.CHEAP_QWEN_FIRST_MODES:
        return False
    status = python_carrier if python_carrier is not None else lane_carrier.python_carrier_status(repo)
    expected_exists = status.get("expected_python_exists", status.get("expected_exists"))
    using_expected = status.get("using_expected_python", status.get("using_expected"))
    return bool(expected_exists and not using_expected)


def _json_payload_from_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return payload if isinstance(payload, dict) else {}
    return {}


def _reinvoke_s_venv_direct_worker_lane(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_id: str,
    mode: str,
    provider: str,
    objective: str,
    input_text: str,
    write: bool,
    python_carrier: dict[str, Any],
) -> dict[str, Any]:
    expected_python = str(python_carrier.get("expected_python") or "")
    if not expected_python:
        return {}
    command = [
        expected_python,
        "-m",
        "xinao_seedlab.cli.__main__",
        "direct-worker-lane",
        "--runtime-root",
        str(runtime),
        "--repo-root",
        str(repo),
        "--wave-id",
        wave_id,
        "--lane-id",
        lane_id,
        "--mode",
        mode,
        "--provider",
        provider,
        "--objective",
        objective,
        "--input-text",
        input_text,
    ]
    if not write:
        command.append("--no-write")
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo / 'src'};{repo}" + (
        f";{existing_pythonpath}" if existing_pythonpath else ""
    )
    env[S_VENV_REINVOKE_ENV] = "1"
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=240,
            check=False,
        )
    except Exception as exc:
        return {
            "python_carrier_reinvoke_attempted": True,
            "python_carrier_reinvoke_error": str(exc),
        }
    payload = _json_payload_from_stdout(result.stdout)
    if payload:
        payload["python_carrier_reinvoked_s_venv"] = True
        payload["reinvoked_from_python"] = sys.executable
        payload["reinvoked_to_python"] = expected_python
        payload["reinvoke_returncode"] = result.returncode
        payload["reinvoke_stderr_tail"] = result.stderr[-2000:]
        if write:
            paths = output_paths(runtime)
            record_path = paths["records"] / f"{lane_carrier.safe_stem(lane_id)}.json"
            lane_carrier.write_json(record_path, payload)
            lane_carrier.write_json(paths["latest"], payload)
            lane_carrier.write_text(paths["readback"], render_readback(payload))
    return payload


def _route_for_provider(
    *,
    provider: str,
    mode: str,
    route_context: dict[str, Any],
) -> dict[str, Any]:
    route = dict(lane_carrier.provider_route_for_mode(mode, route_context))
    if provider == "auto":
        return route
    if provider == "dp":
        route.update(
            {
                "route_class": route.get("route_class") or "direct_dp_worker_lane",
                "lane_kind": "dp_sidecar_execution",
                "preferred_provider_id": lane_carrier.DEEPSEEK_DP_PROVIDER_ID,
                "preferred_provider_label": "DeepSeek/DP sidecar",
                "fallback_provider_ids": ["codex_exec"],
                "qwen_prepaid_first_required": False,
                "qwen_prepaid_first_reason": "direct_worker_lane_dp_override",
            }
        )
        return route
    if provider == "qwen":
        route.update(
            {
                "route_class": "direct_qwen_cheap_worker_lane",
                "lane_kind": "provider_gateway_cheap_worker",
                "preferred_provider_id": lane_carrier.QWEN_CHEAP_WORKER_PROVIDER_ID,
                "preferred_provider_label": "Qwen prepaid cheap worker",
                "preferred_model": route_context.get("qwen_selected_model") or "qwen3.6-flash",
                "fallback_provider_ids": [lane_carrier.DEEPSEEK_DP_PROVIDER_ID, "codex_exec"],
                "qwen_prepaid_first_required": True,
                "qwen_prepaid_first_reason": "direct_worker_lane_qwen_override",
            }
        )
        return route
    raise ValueError(f"Unsupported direct worker lane provider: {provider}")


def _blocked_qwen_not_suitable_payload(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_id: str,
    mode: str,
    objective: str,
    input_text: str,
    route_context: dict[str, Any],
    provider_route: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    lane_result = {
        "lane_id": lane_id,
        "mode": mode,
        "objective": objective,
        "status": "blocked",
        "mode_invocation_status": "blocked",
        "selected_carrier_provider_id": lane_carrier.QWEN_CHEAP_WORKER_PROVIDER_ID,
        "provider": lane_carrier.QWEN_CHEAP_WORKER_PROVIDER_ID,
        "provider_invocation_performed": False,
        "model_invocation_performed": False,
        "tool_invocation_performed": False,
        "qwen_prepaid_invocation": False,
        "deepseek_dp_invocation": False,
        "qwen_prepaid_first_required": True,
        "qwen_prepaid_first_attempted": False,
        "qwen_prepaid_first_succeeded": False,
        "fallback_allowed": False,
        "provider_route": provider_route,
        "artifact_ref": "",
        "artifact_exists": False,
        "provider_invocation_ref": "",
        "provider_latest_ref": "",
        "raw_response_ref": "",
        "raw_response_missing": False,
        "usage": {},
        "rate_limit_error": "",
        "named_blocker": "TASK_NOT_SUITABLE_FOR_QWEN",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    return build_payload(
        runtime=runtime,
        repo=repo,
        wave_id=wave_id,
        lane_id=lane_id,
        mode=mode,
        provider="qwen",
        objective=objective,
        input_text=input_text,
        route_context=route_context,
        provider_route=provider_route,
        lane_result=lane_result,
        write=write,
    )


def build_brief(
    *,
    lane_id: str,
    mode: str,
    objective: str,
    input_text: str,
    provider: str,
    provider_route: dict[str, Any],
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "mode": mode,
        "objective": objective,
        "input_text": input_text,
        "provider_override": provider,
        "provider_route": provider_route,
        "direct_worker_lane": True,
        "not_333_mainline": True,
        "not_execution_controller": True,
        "completion_claim_allowed": False,
        "outputs_to_staging_only": True,
        "direct_repo_write_allowed": False,
        "requires_codex_s_fan_in": True,
        "requires_aaq_for_fact_or_next_frontier": True,
    }


def build_payload(
    *,
    runtime: Path,
    repo: Path,
    wave_id: str,
    lane_id: str,
    mode: str,
    provider: str,
    objective: str,
    input_text: str,
    route_context: dict[str, Any],
    provider_route: dict[str, Any],
    lane_result: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    paths = output_paths(runtime)
    record_path = paths["records"] / f"{lane_carrier.safe_stem(lane_id)}.json"
    lane_status = str(lane_result.get("status") or "")
    named_blocker = str(lane_result.get("named_blocker") or "")
    lane_succeeded = lane_status == "succeeded" and not named_blocker
    checks = {
        "direct_worker_lane_marked": True,
        "not_333_mainline_marked": True,
        "completion_claim_blocked": True,
        "not_execution_controller_marked": True,
        "provider_route_present": bool(provider_route.get("preferred_provider_id")),
        "lane_terminal_result": lane_status in {"succeeded", "blocked"},
        "lane_succeeded": lane_succeeded,
        "writes_runtime_evidence_only": True,
        "requires_fanin_and_aaq": True,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "direct_worker_lane_ready" if lane_succeeded else "direct_worker_lane_blocked",
        "generated_at": lane_carrier.now_iso(),
        "runtime_root": str(runtime),
        "repo_root": str(repo),
        "wave_id": wave_id,
        "lane_id": lane_id,
        "mode": mode,
        "provider_override": provider,
        "selected_carrier_provider_id": str(lane_result.get("selected_carrier_provider_id") or ""),
        "objective": objective,
        "input_text_sha256": hashlib.sha256(
            input_text.encode("utf-8", errors="replace")
        ).hexdigest(),
        "direct_worker_lane": True,
        "not_333_mainline": True,
        "not_mainline_reason": (
            "Direct foreground/provider worker lane. It did not enter "
            "Invoke-CodexSRootIntentLoopDriver and has no server-bound Temporal "
            "workflow_id/run_id/event history."
        ),
        "not_execution_controller": True,
        "not_completion_boundary": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "completion_claim_allowed": False,
        "direct_fact_promotion_allowed": False,
        "sidecar_repo_mutation_performed": False,
        "outputs_to_staging_only": True,
        "requires_codex_s_fan_in": True,
        "requires_aaq_for_fact_or_next_frontier": True,
        "provider_route_context": route_context,
        "provider_route": provider_route,
        "underlying_mature_entrypoints": [
            "ModelGateway: thin_provider_client (LiteLLM :20128)",
            "WorkerLane: codex_s_worker_lane_carrier.run_lane (thin, not phase1)",
            "Qwen: invoke_qwen_cheap_worker_lane via thin_provider_client",
            "DP: dp_sidecar_execution_port.invoke_dp_sidecar_execution_port",
        ],
        "mainline_promotion_requires": [
            "Invoke-CodexSRootIntentLoopDriver.ps1",
            "live Temporal server 127.0.0.1:7233",
            "worker polling task queue xinao-codex-task-default",
            "server-bound workflow_id/run_id/event history",
            "same-wave worker lane terminal results",
            "fan-in/merge",
            "ArtifactAcceptanceQueue acceptance",
            "D-runtime evidence/readback",
        ],
        "worker_lane_result": lane_result,
        "named_blocker": named_blocker,
        "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
        "validation": {
            "passed": lane_succeeded,
            "checks": checks,
        },
        "evidence_refs": {
            "record": str(record_path),
            "latest": str(paths["latest"]),
            "readback": str(paths["readback"]),
            "provider_latest_ref": str(lane_result.get("provider_latest_ref") or ""),
            "provider_invocation_ref": str(lane_result.get("provider_invocation_ref") or ""),
            "artifact_ref": str(lane_result.get("artifact_ref") or ""),
        },
    }
    if write:
        lane_carrier.write_json(record_path, payload)
        lane_carrier.write_json(paths["latest"], payload)
        lane_carrier.write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    provider = payload.get("selected_carrier_provider_id") or ""
    blocker = payload.get("named_blocker") or ""
    lines = [
        "# Codex S Direct Worker Lane",
        "",
        f"- status: `{status}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- lane_id: `{payload.get('lane_id')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- provider: `{provider}`",
        "- mainline: `not_333_mainline`",
        "- completion_claim_allowed: `false`",
        "- promotion_requires: RootIntentLoop driver + live Temporal event history + fan-in + AAQ",
    ]
    if blocker:
        lines.append(f"- named_blocker: `{blocker}`")
    lines.append("")
    return "\n".join(lines)


def invoke_direct_worker_lane(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "",
    lane_id: str = "",
    mode: str = "draft",
    provider: str = "auto",
    objective: str = "",
    input_text: str = "",
    input_file: str = "",
    write: bool = True,
    dp_invoker: lane_carrier.DpInvoker | None = None,
    qwen_invoker: lane_carrier.QwenInvoker | None = None,
) -> dict[str, Any]:
    if mode not in lane_carrier.MODE_ORDER:
        raise ValueError(f"Unsupported direct worker lane mode: {mode}")
    if provider not in PROVIDER_CHOICES:
        raise ValueError(f"Unsupported direct worker lane provider: {provider}")
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    resolved_wave_id = wave_id or f"direct-worker-lane-{lane_carrier.now_iso()}"
    resolved_lane_id = lane_id or f"{resolved_wave_id}-{mode}-01"
    resolved_input_text = _read_text_arg(input_text=input_text, input_file=input_file)
    python_carrier = lane_carrier.python_carrier_status(repo)
    if should_reinvoke_s_venv_for_qwen(
        provider=provider,
        mode=mode,
        repo=repo,
        qwen_invoker_provided=qwen_invoker is not None,
        python_carrier=python_carrier,
    ):
        reinvoked = _reinvoke_s_venv_direct_worker_lane(
            runtime=runtime,
            repo=repo,
            wave_id=resolved_wave_id,
            lane_id=resolved_lane_id,
            mode=mode,
            provider=provider,
            objective=objective,
            input_text=resolved_input_text,
            write=write,
            python_carrier=python_carrier,
        )
        if reinvoked.get("schema_version") == SCHEMA_VERSION:
            return reinvoked
    route_context = lane_carrier.load_provider_route_context(runtime)
    provider_route = _route_for_provider(
        provider=provider,
        mode=mode,
        route_context=route_context,
    )
    if provider == "qwen" and mode not in lane_carrier.CHEAP_QWEN_FIRST_MODES:
        return _blocked_qwen_not_suitable_payload(
            runtime=runtime,
            repo=repo,
            wave_id=resolved_wave_id,
            lane_id=resolved_lane_id,
            mode=mode,
            objective=objective,
            input_text=resolved_input_text,
            route_context=route_context,
            provider_route=provider_route,
            write=write,
        )
    brief = build_brief(
        lane_id=resolved_lane_id,
        mode=mode,
        objective=objective,
        input_text=resolved_input_text,
        provider=provider,
        provider_route=provider_route,
    )
    lane_result = lane_carrier.run_lane(
        runtime=runtime,
        wave_id=resolved_wave_id,
        brief=brief,
        dp_invoker=dp_invoker or lane_carrier.default_dp_invoker(),
        qwen_invoker=qwen_invoker or lane_carrier.default_qwen_invoker(),
        write=write,
    )
    return build_payload(
        runtime=runtime,
        repo=repo,
        wave_id=resolved_wave_id,
        lane_id=resolved_lane_id,
        mode=mode,
        provider=provider,
        objective=objective,
        input_text=resolved_input_text,
        route_context=route_context,
        provider_route=provider_route,
        lane_result=lane_result,
        write=write,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-s-direct-worker-lane")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="")
    parser.add_argument("--lane-id", default="")
    parser.add_argument("--mode", choices=list(lane_carrier.MODE_ORDER), default="draft")
    parser.add_argument("--provider", choices=list(PROVIDER_CHOICES), default="auto")
    parser.add_argument("--objective", default="")
    parser.add_argument("--input-text", default="")
    parser.add_argument("--input-file", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = invoke_direct_worker_lane(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        lane_id=args.lane_id,
        mode=args.mode,
        provider=args.provider,
        objective=args.objective,
        input_text=args.input_text,
        input_file=args.input_file,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
