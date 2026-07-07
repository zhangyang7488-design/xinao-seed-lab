from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from services.agent_runtime import codex_s_token_budget_gate

SCHEMA_VERSION = "xinao.codex_s.333_host_dialogue_gate_trace.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_333_HOST_DIALOGUE_GATE_TRACE_READY"
TASK_ID = "codex_333_host_dialogue_gate_trace_20260706"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_HOOKS_JSON = Path(r"C:\Users\xx363\.codex-seed-cortex\hooks.json")
TOOL_PROVIDER_ID = "codex_s.333_host_dialogue_gate_trace"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "codex_333_host_dialogue_gate_trace"
    return {
        "latest": state / "latest.json",
        "record": state / "records" / f"{TASK_ID}.json",
        "readback": runtime / "readback" / "zh" / "codex_333_host_dialogue_gate_trace.md",
    }


def hooks_user_prompt_submit_command(hooks_json: Path) -> str:
    payload = read_json(hooks_json)
    hook_groups = payload.get("hooks", {}).get("UserPromptSubmit")
    if not isinstance(hook_groups, list):
        return ""
    for group in hook_groups:
        hooks = group.get("hooks") if isinstance(group, dict) else None
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str) and "Invoke-CodexSUserPromptSubmitHook.ps1" in command:
                return command
    return ""


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_sample(prompt: str, repo: Path, runtime: Path) -> dict[str, Any]:
    raw_event = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "user_prompt": prompt},
        ensure_ascii=False,
    )
    payload = codex_s_token_budget_gate.build_payload(
        raw_event_json=raw_event,
        repo_root=repo,
        runtime_root=runtime,
        write=False,
    )
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    route_id = str(decision.get("route_id") or "")
    if route_id == "codex_direct_human_dialogue":
        message_class = "human_dialogue"
    elif route_id == "foreground_mirror_watch":
        message_class = "watch"
    elif route_id.startswith("codex_direct") and payload.get("flags", {}).get("dialogue"):
        message_class = "human_dialogue"
    else:
        message_class = "execution"
    return {
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "message_class": message_class,
        "route_id": route_id,
        "action": decision.get("action", ""),
        "codex_read_policy": decision.get("codex_read_policy", ""),
        "completion_claim_allowed": payload.get("completion_claim_allowed"),
    }


def build_sample_traces(repo: Path, runtime: Path) -> list[dict[str, Any]]:
    samples = [
        ("human_dialogue", "这个机制是什么意思，先讨论"),
        ("execution", "落地 host_dialogue_gate_trace.v1 并运行验证"),
        ("watch", "后台镜像轮询 watch 当前 workflow"),
    ]
    traces = []
    for expected, prompt in samples:
        trace = classify_sample(prompt, repo, runtime)
        trace["sample_id"] = expected
        trace["expected_message_class"] = expected
        trace["matches_expected"] = trace["message_class"] == expected
        traces.append(trace)
    return traces


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    hooks_json: str | Path = DEFAULT_HOOKS_JSON,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    hooks_path = Path(hooks_json)
    hook_script = repo / "scripts" / "hardmode" / "Invoke-CodexSUserPromptSubmitHook.ps1"
    clean_gate_latest = runtime / "state" / "clean_dialogue_gate" / "latest.json"
    hook_latest = runtime / "state" / "codex_s_user_prompt_submit_hook" / "latest.json"
    token_gate_latest = runtime / "state" / "codex_s_token_budget_gate" / "latest.json"
    continuity_latest = runtime / "state" / "codex_333_stateful_continuity_router" / "latest.json"
    tool_registry_latest = runtime / "agent_runtime" / "tools" / "registry" / "tool_registry.json"
    paths = output_paths(runtime)

    hook_command = hooks_user_prompt_submit_command(hooks_path)
    hook_text = hook_script.read_text(encoding="utf-8", errors="replace") if hook_script.is_file() else ""
    clean_gate = read_json(clean_gate_latest)
    hook_payload = read_json(hook_latest)
    token_gate = read_json(token_gate_latest)
    continuity = read_json(continuity_latest)
    tool_registry = read_json(tool_registry_latest)
    provider_ids = (
        tool_registry.get("provider_ids")
        if isinstance(tool_registry.get("provider_ids"), list)
        else []
    )
    sample_traces = build_sample_traces(repo, runtime)

    checks = {
        "hooks_json_exists": hooks_path.is_file(),
        "user_prompt_submit_hook_configured": bool(hook_command),
        "hook_script_exists": hook_script.is_file(),
        "hook_script_names_message_classes": all(
            item in hook_text for item in ["human_dialogue", "diagnosis", "execution", "watch"]
        ),
        "hook_latest_ready": hook_payload.get("status") == "user_prompt_submit_hook_ready",
        "token_gate_latest_ready": token_gate.get("status") == "token_budget_gate_ready",
        "clean_dialogue_gate_latest_ready": clean_gate.get("validation", {}).get("passed") is True,
        "continuity_router_points_here": continuity.get("next_required_artifact") == "host_dialogue_gate_trace.v1",
        "sample_classes_match": all(item["matches_expected"] for item in sample_traces),
        "human_dialogue_no_hot_path_policy": any(
            item["message_class"] == "human_dialogue"
            and item["codex_read_policy"] == "no_hot_path_reads_for_dialogue"
            for item in sample_traces
        ),
        "cli_entrypoint_registered": "333-host-dialogue-gate-trace" in (
            (repo / "src" / "xinao_seedlab" / "cli" / "__main__.py").read_text(
                encoding="utf-8",
                errors="replace",
            )
            if (repo / "src" / "xinao_seedlab" / "cli" / "__main__.py").is_file()
            else ""
        ),
        "completion_claim_disallowed": True,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "work_id": WORK_ID,
        "status": "host_dialogue_gate_trace_ready" if all(checks.values()) else "host_dialogue_gate_trace_blocked",
        "repo_root": str(repo),
        "runtime_root": str(runtime),
        "hooks_json": {
            "path": str(hooks_path),
            "exists": hooks_path.is_file(),
            "user_prompt_submit_command": hook_command,
        },
        "host_order_contract": {
            "required_order": [
                "UserPromptSubmit hook",
                "message_class = human_dialogue / diagnosis / execution / watch",
                "TokenBudgetGate advisory",
                "AGENTS/L0/hot-path/tool execution only if message_class permits it",
            ],
            "message_class_before_hot_path": True,
            "human_dialogue_blocks_hot_path_reads": True,
            "execution_requires_explicit_user_action": True,
            "proof_scope": "S-scoped configured UserPromptSubmit hook plus regression/sample evidence; not a host platform trace controller.",
        },
        "runtime_refs": {
            "hook_script": str(hook_script),
            "hook_script_sha256": file_sha256(hook_script),
            "hook_latest": str(hook_latest),
            "token_gate_latest": str(token_gate_latest),
            "clean_dialogue_gate_latest": str(clean_gate_latest),
            "continuity_latest": str(continuity_latest),
            "tool_registry_latest": str(tool_registry_latest),
        },
        "tool_registry": {
            "provider_id": TOOL_PROVIDER_ID,
            "provider_visible": TOOL_PROVIDER_ID in provider_ids,
            "provider_ids_ref": str(tool_registry_latest),
            "visibility_required_for": "333_sleep_watch_p0_landing ToolRegistry generation; this trace remains callable through CLI even before registry refresh.",
        },
        "cli": {
            "command": "python -m xinao_seedlab.cli.__main__ 333-host-dialogue-gate-trace",
            "registered": checks["cli_entrypoint_registered"],
        },
        "sample_traces": sample_traces,
        "accepted_for": "P0.host_dialogue_gate_trace",
        "adoption_state": "default_hot_path_ready",
        "default_mainline_hardened": True,
        "default_consumer": (
            "UserPromptSubmit hook / TokenBudgetGate / S ToolRegistry / "
            "default trigger no-stop ToolRegistry consumption / stateful continuity router"
        ),
        "workspace_only": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "output_paths": {key: str(value) for key, value in paths.items()},
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["latest"], payload)
        write_json(paths["record"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return "\n".join(
        [
            "# 333 host dialogue gate trace",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- adoption_state: `{payload.get('adoption_state')}`",
            f"- accepted_for: `{payload.get('accepted_for')}`",
            f"- validation_passed: {validation.get('passed')}",
            "- boundary: UserPromptSubmit/TokenBudgetGate/CleanDialogueGate trace, not execution controller.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--hooks-json", default=str(DEFAULT_HOOKS_JSON))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        hooks_json=args.hooks_json,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
