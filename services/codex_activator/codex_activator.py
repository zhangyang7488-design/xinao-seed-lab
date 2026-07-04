import argparse
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from . import human_egress_jsonl_filter
except ImportError:
    import human_egress_jsonl_filter


HOST = "127.0.0.1"
PORT = 19120
RUNTIME_ROOT = Path(
    os.environ.get("XINAO_CODEX_ACTIVATOR_RUNTIME_ROOT")
    or os.environ.get("XINAO_RUNTIME_ROOT")
    or r"D:\XINAO_CLEAN_RUNTIME"
)
RESULT_ROOT = RUNTIME_ROOT / "state" / "codex_results"
ACTION_TRACE_ROOT = RUNTIME_ROOT / "state" / "action_delivery_trace"
TARGETS = {
    "codex-a": {
        "codex_home": Path(r"C:\Users\xx363\.codex-a"),
        "workspace_hint": Path(r"C:\Users\xx363\CodexWorkspaces\A"),
    },
    "codex-s": {
        "codex_home": Path(r"C:\Users\xx363\.codex-seed-cortex"),
        "workspace_hint": Path(r"E:\XINAO_RESEARCH_WORKSPACES\S"),
    },
}
TARGET_ORDER = tuple(TARGETS)
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RESULT_MARKER_PATTERN = re.compile(r"\bRESULT_[A-Z0-9_]+\b")
CODEX_USAGE_LIMIT = re.compile(
    r"(?i)(you(?:'|’)ve hit your usage limit|usage limit|try again at\s+[^\".]+)"
)
CODEX_RETRY_AFTER = re.compile(r"(?i)try again at\s+([^\".]+)")

DESTRUCTIVE_ACTION = re.compile(
    r"(?i)(delete|remove|erase|wipe|clear|destroy|overwrite|disable|stop|format|"
    r"删除|清空|销毁|覆盖|禁用|停止|格式化)"
)
RECOVERY_CONTEXT = re.compile(
    r"(?i)(snapshot|backup|checkpoint|restore|rollback|recovery|replacement|"
    r"快照|备份|检查点|恢复|回滚|替代)"
)
NO_RECOVERY_CONTEXT = re.compile(
    r"(?i)(without|no|missing|absent|没有|无|缺少).{0,16}"
    r"(snapshot|backup|checkpoint|restore|rollback|recovery|replacement|"
    r"快照|备份|检查点|恢复|回滚|替代)"
)
RUNTIME_CORE = re.compile(
    r"(?i)(D:\\XINAO_CLEAN_RUNTIME|XinaoCleanSupervisor|public_mux|ingress|"
    r"runner|codex_activator|result 回读|result path|control plane|控制面|接单链路)"
)
BOUNDED_TASK_WORKER_CONTEXT = re.compile(
    r"(?i)(BOUNDED SEGMENT-PASS L2 WORKER|RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK)"
)
CODEX_AUTH = re.compile(
    r"(?i)(C:\\Users\\xx363\\\.(?:codex-(?:a|b|c)|codex-seed-cortex)|"
    r"\.(?:codex-(?:a|b|c)|codex-seed-cortex).*(?:auth\.json|token|login))"
)
MASS_DESTRUCTION = re.compile(
    r"(?i)(format\s+[CDE]:|清空\s*C:\\|清空\s*Users|清空.*runtime root|"
    r"wipe\s+(?:C:\\|Users|runtime root)|delete\s+(?:C:\\|Users|runtime root))"
)
SECRET_EXPOSURE = re.compile(
    r"(?i)((show|print|output|return|cat|type|read|dump|显示|输出|读取|打印).{0,40}"
    r"(auth\.json|token|secret|password|private key|密钥|令牌|密码).{0,20}"
    r"(raw|plaintext|原文|明文)?)"
)
HUMAN_DECISION = re.compile(
    r"(?i)(payment|pay money|identity verification|account ownership transfer|"
    r"付款|支付|身份验证|账号所有权转移|账户所有权转移)"
)
IMPLEMENTATION_WORKER_SCOPE_BLOCKER = "CODEX_ACTIVATOR_WORKER_ASSIGNMENT_SCOPE_REQUIRED"

TASK_LOCK = threading.Lock()
RUNNING_TASKS: dict[str, threading.Thread] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def make_trace_id(task_id: str) -> str:
    safe = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in "-_")
    return "xinao-action-" + (safe or uuid.uuid4().hex)


def worker_assignment_scope_issues(payload: dict[str, Any]) -> list[str]:
    if not (
        payload.get("assignment_driven_dispatch") is True
        or payload.get("implementation_worker_required") is True
        or payload.get("continue_same_task_signal_worker_required") is True
    ):
        return []
    issues = []
    if str(payload.get("worker_kind") or "") != "implementation_worker":
        issues.append("worker_kind")
    if not str(payload.get("phase_scope") or ""):
        issues.append("phase_scope")
    if not str(payload.get("worker_assignment_ref") or ""):
        issues.append("worker_assignment_ref")
    if not isinstance(payload.get("work_package"), dict) or not payload.get("work_package"):
        issues.append("work_package")
    if not isinstance(payload.get("verification"), (list, dict)) or not payload.get("verification"):
        issues.append("verification")
    return issues


def append_action_trace(task_id: str, trace_id: str, event_name: str, status: str, payload: dict[str, Any] | None = None) -> None:
    safe_task_id = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in "-_")
    if not safe_task_id:
        return
    ACTION_TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "xinao.action-delivery-trace-event.v1",
        "trace_id": trace_id or make_trace_id(safe_task_id),
        "task_id": safe_task_id,
        "event_name": event_name,
        "status": status,
        "service": "codex_activator",
        "otel_name": "xinao.action_delivery." + event_name,
        "timestamp": now_iso(),
        "payload": payload or {},
    }
    with (ACTION_TRACE_ROOT / f"{safe_task_id}.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def capacity_file() -> Path:
    return RUNTIME_ROOT / "state" / "codex_capacity.json"


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def capacity_state(target: str, capacity: dict[str, Any]) -> str:
    try:
        return str(capacity.get("targets", {}).get(target, {}).get("capacity", "unknown"))
    except Exception:
        return "unknown"


def target_available(target: str, capacity: dict[str, Any]) -> bool:
    return capacity_state(target, capacity) == "available"


def choose_target(payload: dict[str, Any]) -> tuple[dict[str, str] | None, str]:
    preselected = payload.get("effective_target")
    if preselected in TARGETS and payload.get("target") == preselected:
        return {
            "original_target": str(payload.get("original_target", preselected)),
            "effective_target": preselected,
            "fallback_reason": str(payload.get("fallback_reason", "")),
        }, ""
    requested = payload.get("target")
    if requested in TARGETS:
        return {
            "original_target": str(requested),
            "effective_target": str(requested),
            "fallback_reason": "",
        }, ""
    if requested not in (None, ""):
        return None, "CODEX_ACTIVATOR_UNKNOWN_TARGET"
    return {
        "original_target": str(requested or ""),
        "effective_target": "codex-a",
        "fallback_reason": "legacy_hardmode_codex_a_default",
    }, ""


def effective_workspace_hint(payload: dict[str, Any], target: str) -> str:
    candidate = str(payload.get("workspace_hint") or payload.get("repo_root") or "").strip()
    if candidate:
        path = Path(candidate)
        if path.is_dir():
            return str(path)
    return str(TARGETS[target]["workspace_hint"])


def current_identity() -> str:
    try:
        completed = subprocess.run(
            ["whoami"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode == 0:
            return completed.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")


def find_codex() -> str | None:
    candidates = [
        shutil.which("codex.cmd"),
        shutil.which("codex.exe"),
        shutil.which("codex"),
        r"C:\Users\xx363\AppData\Roaming\npm\codex.cmd",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def kill_process_tree(pid: int) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except Exception:
            pass
    try:
        subprocess.run(
            ["kill", "-TERM", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass


def guard_prompt(prompt: str) -> str:
    if HUMAN_DECISION.search(prompt):
        return "CODEX_ACTIVATOR_GUARD_REJECTED_PAYMENT_IDENTITY_ACCOUNT_TRANSFER"
    if MASS_DESTRUCTION.search(prompt):
        return "CODEX_ACTIVATOR_GUARD_REJECTED_SELF_DESTRUCT"
    if SECRET_EXPOSURE.search(prompt):
        return "CODEX_ACTIVATOR_GUARD_REJECTED_SECRET_EXPOSURE"
    if DESTRUCTIVE_ACTION.search(prompt) and CODEX_AUTH.search(prompt):
        return "CODEX_ACTIVATOR_GUARD_REJECTED_AUTH_DESTRUCTION"
    if (
        DESTRUCTIVE_ACTION.search(prompt)
        and RUNTIME_CORE.search(prompt)
        and not BOUNDED_TASK_WORKER_CONTEXT.search(prompt)
        and (
            not RECOVERY_CONTEXT.search(prompt)
            or NO_RECOVERY_CONTEXT.search(prompt)
        )
    ):
        return "CODEX_ACTIVATOR_GUARD_REJECTED_SELF_DESTRUCT"
    return ""


def task_paths(task_id: str, target: str = "") -> dict[str, Path]:
    root = RESULT_ROOT / task_id
    return {
        "root": root,
        "request": root / "request.json",
        "prompt": root / "prompt.txt",
        "stdout": root / "stdout.log",
        "stderr": root / "stderr.log",
        "jsonl": root / "codex-events.jsonl",
        "raw_final": root / "raw-final.md",
        "final": root / "final.md",
        "egress_filter": root / "human-egress-filter.json",
        "result": root / "result.json",
    }


def human_egress_filter_required(request_payload: dict[str, Any]) -> bool:
    return human_egress_jsonl_filter.filter_required(request_payload)


def _jsonl_agent_message_texts(path: Path) -> list[str]:
    texts: list[str] = []
    if not path.is_file():
        return texts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates: list[Any] = [item]
        nested = item.get("item") if isinstance(item, dict) else None
        if isinstance(nested, dict):
            candidates.append(nested)
        payload = item.get("payload") if isinstance(item, dict) else None
        if isinstance(payload, dict):
            candidates.append(payload)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            kind = str(candidate.get("type") or candidate.get("event") or "")
            if "agent" not in kind.lower() and "assistant" not in kind.lower():
                continue
            for key in ("text", "message", "content", "delta"):
                value = candidate.get(key)
                if isinstance(value, str):
                    texts.append(value)
    return texts


PYTEST_WALL_PATTERN = re.compile(
    r"(?i)(\bpytest\b|\bunittest\b|\b\d+\s+OK\b|\bPASS\b|Ran\s+\d+\s+tests?|"
    r"验收结果|测试结果|py_compile|JSONL|final\.md|codex-events\.jsonl)"
)


def apply_human_egress_filter(
    *,
    task_id: str,
    paths: dict[str, Path],
    request_payload: dict[str, Any],
    expected_marker: str,
) -> dict[str, Any]:
    return human_egress_jsonl_filter.apply_filter(
        task_id=task_id,
        paths=paths,
        request_payload=request_payload,
        expected_marker=expected_marker,
    )


def classify_codex_failure(paths: dict[str, Path]) -> dict[str, Any]:
    snippets: list[str] = []
    for key in ("jsonl", "stdout", "stderr", "raw_final", "final"):
        path = paths.get(key)
        if not path or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text:
            snippets.append(text[-20000:])
    combined = "\n".join(snippets)
    if not CODEX_USAGE_LIMIT.search(combined):
        return {}
    retry_match = CODEX_RETRY_AFTER.search(combined)
    retry_after_text = retry_match.group(1).strip() if retry_match else ""
    return {
        "named_blocker": "CODEX_USAGE_LIMIT_RETRY_AFTER",
        "retry_after_text": retry_after_text,
        "external_condition": True,
        "retryable": True,
    }


def make_result(
    *,
    task_id: str,
    target: str,
    ok: bool,
    exit_code: int,
    started_at: str,
    started_clock: float,
    codex_home: str,
    workspace: str,
    paths: dict[str, Path],
    named_blocker: str,
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "task_id": task_id,
        "target": target,
        "ok": bool(ok),
        "status": "PASS" if ok else "FAIL",
        "exit_code": int(exit_code),
        "started_at": started_at,
        "finished_at": now_iso(),
        "duration_sec": round(time.monotonic() - started_clock, 3),
        "runtime_root": str(RUNTIME_ROOT),
        "codex_home": codex_home,
        "workspace": workspace,
        "cd": workspace,
        "stdout_path": str(paths["stdout"]),
        "stderr_path": str(paths["stderr"]),
        "jsonl_path": str(paths["jsonl"]),
        "final_path": str(paths["final"]),
        "raw_final_path": str(paths.get("raw_final", paths["final"])),
        "human_egress_filter_ref": str(paths.get("egress_filter", "")),
        "request_path": str(paths["request"]),
        "named_blocker": named_blocker,
    }
    if request_payload:
        result["trace_id"] = request_payload.get("trace_id", make_trace_id(task_id))
        result["original_target"] = request_payload.get("original_target", target)
        result["effective_target"] = request_payload.get("effective_target", target)
        result["fallback_reason"] = request_payload.get("fallback_reason", "")
        result["action_rules_version"] = request_payload.get("action_rules_version", "")
        result["action_rules_hash"] = request_payload.get("action_rules_hash", "")
        result["action_decision"] = request_payload.get("action_decision", "")
        result["dispatch_strategy"] = request_payload.get("dispatch_strategy", "")
        result["mature_execution_carrier"] = request_payload.get("mature_execution_carrier", "")
        result["mature_execution_carrier_refs"] = request_payload.get("mature_execution_carrier_refs", [])
        result["worker_evidence_contract"] = request_payload.get("worker_evidence_contract", "")
        result["segment_pass_checker_default"] = request_payload.get("segment_pass_checker_default") is True
        result["worker_kind"] = request_payload.get("worker_kind", "")
        result["phase_scope"] = request_payload.get("phase_scope", "")
        result["worker_assignment_ref"] = request_payload.get("worker_assignment_ref", "")
        result["phase_execution"] = request_payload.get("phase_execution", {})
        result["work_package"] = request_payload.get("work_package", {})
        result["verification"] = request_payload.get("verification", [])
        result["worker_assignment_scope_issues"] = request_payload.get("worker_assignment_scope_issues", [])
        result["assignment_driven_dispatch"] = request_payload.get("assignment_driven_dispatch") is True
        result["implementation_worker_required"] = request_payload.get("implementation_worker_required") is True
        result["continue_same_task_signal_worker_required"] = request_payload.get("continue_same_task_signal_worker_required") is True
        result["segment_boundary_policy"] = request_payload.get("segment_boundary_policy", "")
        result["grok_audit_policy"] = request_payload.get("grok_audit_policy", "")
    return result


def failed_request_result(
    task_id: str,
    target: str,
    blocker: str,
    request_payload: dict[str, Any],
    exit_code: int = 2,
) -> dict[str, Any]:
    paths = task_paths(task_id, target)
    paths["root"].mkdir(parents=True, exist_ok=True)
    write_json(paths["request"], request_payload)
    paths["stdout"].touch()
    paths["stderr"].write_text(blocker + "\n", encoding="utf-8")
    paths["jsonl"].touch()
    paths["raw_final"].touch()
    paths["final"].touch()
    started_at = now_iso()
    result = make_result(
        task_id=task_id,
        target=target,
        ok=False,
        exit_code=exit_code,
        started_at=started_at,
        started_clock=time.monotonic(),
        codex_home=str(TARGETS.get(target, {}).get("codex_home", "")),
        workspace=str(request_payload.get("workspace_hint") or TARGETS.get(target, {}).get("workspace_hint", "")),
        paths=paths,
        named_blocker=blocker,
        request_payload=request_payload,
    )
    write_json(paths["result"], result)
    append_action_trace(
        task_id,
        str(result.get("trace_id") or make_trace_id(task_id)),
        "activator.request_failed",
        "BLOCKED",
        {"target": target, "named_blocker": blocker, "exit_code": exit_code},
    )
    return result


def run_codex_task(request_payload: dict[str, Any]) -> dict[str, Any]:
    task_id = request_payload["task_id"]
    target = request_payload["target"]
    prompt = request_payload["prompt"]
    timeout_sec = request_payload["timeout_sec"]
    target_config = TARGETS[target]
    workspace = str(request_payload.get("workspace_hint") or target_config["workspace_hint"])
    paths = task_paths(task_id, target)
    paths["root"].mkdir(parents=True, exist_ok=True)
    write_json(paths["request"], request_payload)
    paths["prompt"].write_text(prompt, encoding="utf-8")
    append_action_trace(
        task_id,
        str(request_payload.get("trace_id") or make_trace_id(task_id)),
        "activator.exec_started",
        "STARTED",
        {"target": target, "workspace": workspace},
    )

    codex = find_codex()
    started_at = now_iso()
    started_clock = time.monotonic()
    if not codex:
        return failed_request_result(
            task_id,
            target,
            "CODEX_ACTIVATOR_CODEX_NOT_FOUND",
            request_payload,
            exit_code=127,
        )

    expected_markers = RESULT_MARKER_PATTERN.findall(prompt)
    expected_marker = expected_markers[-1] if expected_markers else ""
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(target_config["codex_home"])
    command = [
        codex,
        "exec",
        "--cd",
        workspace,
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--json",
        "--output-last-message",
        str(paths["raw_final"] if human_egress_filter_required(request_payload) else paths["final"]),
        "-",
    ]

    exit_code = 1
    blocker = ""
    try:
        with (
            paths["prompt"].open("rb") as stdin_handle,
            paths["jsonl"].open("wb") as stdout_handle,
            paths["stderr"].open("wb") as stderr_handle,
        ):
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=environment,
                stdin=stdin_handle,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                exit_code = process.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                kill_process_tree(process.pid)
                process.wait(timeout=30)
                exit_code = 124
                blocker = "CODEX_ACTIVATOR_EXEC_TIMEOUT"
    except OSError as error:
        paths["stderr"].write_text(str(error) + "\n", encoding="utf-8")
        blocker = "CODEX_ACTIVATOR_EXEC_FAILED"
        exit_code = 126
    except Exception as error:
        paths["stderr"].write_text(str(error) + "\n", encoding="utf-8")
        blocker = "CODEX_ACTIVATOR_EXEC_FAILED"
        exit_code = 1

    if paths["jsonl"].exists():
        shutil.copyfile(paths["jsonl"], paths["stdout"])
    else:
        paths["jsonl"].touch()
        paths["stdout"].touch()
    if not paths["stderr"].exists():
        paths["stderr"].touch()
    if not paths["final"].exists():
        paths["final"].touch()
    if not paths["raw_final"].exists():
        paths["raw_final"].touch()

    filter_payload = apply_human_egress_filter(
        task_id=task_id,
        paths=paths,
        request_payload=request_payload,
        expected_marker=expected_marker,
    )
    final_for_marker = paths["raw_final"] if filter_payload.get("raw_final_backend_evidence_only") else paths["final"]
    final_text = final_for_marker.read_text(encoding="utf-8", errors="replace")
    failure_classification = classify_codex_failure(paths)
    if exit_code != 0 and failure_classification.get("named_blocker"):
        blocker = str(failure_classification["named_blocker"])
    if not blocker and exit_code != 0:
        blocker = "CODEX_ACTIVATOR_EXEC_FAILED"
    if not blocker and expected_marker and expected_marker not in final_text:
        blocker = "CODEX_ACTIVATOR_RESULT_MARKER_MISSING"
    ok = exit_code == 0 and not blocker
    result = make_result(
        task_id=task_id,
        target=target,
        ok=ok,
        exit_code=exit_code,
        started_at=started_at,
        started_clock=started_clock,
        codex_home=str(target_config["codex_home"]),
        workspace=workspace,
        paths=paths,
        named_blocker=blocker,
        request_payload=request_payload,
    )
    result.update({
        "headless_worker": filter_payload.get("headless_worker") is True,
        "human_egress_policy": str(filter_payload.get("human_egress_policy") or ""),
        "human_egress_filter": filter_payload,
        "raw_final_backend_evidence_only": filter_payload.get("raw_final_backend_evidence_only") is True,
        "worker_final_user_visible_allowed": filter_payload.get("worker_final_user_visible_allowed") is True,
        "codex_final_to_user_allowed": filter_payload.get("codex_final_to_user_allowed") is True,
        "no_pytest_wall_to_user": filter_payload.get("no_pytest_wall_to_user") is True,
        "failure_classification": failure_classification,
    })
    write_json(paths["result"], result)
    append_action_trace(
        task_id,
        str(request_payload.get("trace_id") or make_trace_id(task_id)),
        "activator.exec_finished",
        result["status"],
        {"target": target, "exit_code": exit_code, "named_blocker": blocker, "ok": ok},
    )
    return result


def normalize_request(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    requested_task_id = payload.get("task_id") or f"codex-activator-{uuid.uuid4().hex}"
    task_id = str(requested_task_id)
    if not TASK_ID_PATTERN.fullmatch(task_id):
        fallback_id = f"codex-activator-invalid-{uuid.uuid4().hex}"
        result = failed_request_result(
            fallback_id,
            str(payload.get("target", "")),
            "CODEX_ACTIVATOR_BAD_TASK_ID",
            payload,
        )
        return None, result

    selection, selection_blocker = choose_target(payload)
    if selection_blocker:
        return None, failed_request_result(
            task_id,
            str(payload.get("target", "")),
            selection_blocker,
            {
                **payload,
                "original_target": str(payload.get("target", "")),
                "effective_target": "",
                "fallback_reason": selection_blocker,
            },
        )
    assert selection is not None
    target = selection["effective_target"]

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, failed_request_result(
            task_id,
            target,
            "CODEX_ACTIVATOR_PROMPT_REQUIRED",
            payload,
        )

    blocker = guard_prompt(prompt)
    if blocker:
        return None, failed_request_result(task_id, target, blocker, payload)

    scope_issues = worker_assignment_scope_issues(payload)
    if scope_issues:
        return None, failed_request_result(
            task_id,
            target,
            IMPLEMENTATION_WORKER_SCOPE_BLOCKER,
            {**payload, "worker_assignment_scope_issues": scope_issues},
        )

    try:
        timeout_sec = int(payload.get("timeout_sec", 900))
    except (TypeError, ValueError):
        timeout_sec = 900
    timeout_sec = max(1, min(timeout_sec, 7200))
    request_payload = {
        "task_id": task_id,
        "trace_id": str(payload.get("trace_id") or make_trace_id(task_id)),
        "target": target,
        "original_target": selection["original_target"],
        "effective_target": selection["effective_target"],
        "fallback_reason": selection["fallback_reason"],
        "prompt": prompt,
        "timeout_sec": timeout_sec,
        "wait": bool(payload.get("wait", True)),
        "workspace_hint": effective_workspace_hint(payload, target),
        "repo_root": str(payload.get("repo_root") or ""),
        "action_rules_version": str(payload.get("action_rules_version", "")),
        "action_rules_hash": str(payload.get("action_rules_hash", "")),
        "action_decision": str(payload.get("action_decision", "")),
        "dispatch_strategy": str(payload.get("dispatch_strategy", "")),
        "mature_execution_carrier": str(payload.get("mature_execution_carrier") or "codex_exec_json_app_server_sdk_worker"),
        "mature_execution_carrier_refs": list(payload.get("mature_execution_carrier_refs") or []),
        "worker_evidence_contract": str(payload.get("worker_evidence_contract") or "task_bound_codex_exec_jsonl"),
        "segment_pass_checker_default": payload.get("segment_pass_checker_default") is True,
        "worker_kind": str(payload.get("worker_kind") or ""),
        "phase_scope": str(payload.get("phase_scope") or ""),
        "worker_assignment_ref": str(payload.get("worker_assignment_ref") or ""),
        "phase_execution": payload.get("phase_execution") if isinstance(payload.get("phase_execution"), dict) else {},
        "work_package": payload.get("work_package") if isinstance(payload.get("work_package"), dict) else {},
        "verification": payload.get("verification") if isinstance(payload.get("verification"), (list, dict)) else [],
        "worker_assignment_scope_issues": [],
        "assignment_driven_dispatch": payload.get("assignment_driven_dispatch") is True,
        "implementation_worker_required": payload.get("implementation_worker_required") is True,
        "continue_same_task_signal_worker_required": payload.get("continue_same_task_signal_worker_required") is True,
        "segment_boundary_policy": str(payload.get("segment_boundary_policy") or ""),
        "grok_audit_policy": str(payload.get("grok_audit_policy") or ""),
        "headless_worker": payload.get("headless_worker") is True,
        "segment_boundary_headless": payload.get("segment_boundary_headless") is True,
        "human_egress_policy": str(payload.get("human_egress_policy") or ""),
        "worker_final_user_visible_allowed": payload.get("worker_final_user_visible_allowed") is True,
        "submitted_at": now_iso(),
    }
    return request_payload, None


def run_background(request_payload: dict[str, Any]) -> None:
    try:
        run_codex_task(request_payload)
    finally:
        with TASK_LOCK:
            RUNNING_TASKS.pop(request_payload["task_id"], None)


class Handler(BaseHTTPRequestHandler):
    server_version = "XinaoCodexActivator/1.0"

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/health":
            codex = find_codex()
            self.send_json(
                200 if codex else 503,
                {
                    "ok": bool(codex),
                    "service": "codex_activator",
                    "runtime_root": str(RUNTIME_ROOT),
                    "identity": current_identity(),
                    "codex": codex or "",
                    "targets": list(TARGETS),
                },
            )
            return
        prefix = "/codex/result/"
        if route.startswith(prefix):
            task_id = unquote(route[len(prefix) :])
            if not TASK_ID_PATTERN.fullmatch(task_id):
                self.send_json(400, {"ok": False, "named_blocker": "CODEX_ACTIVATOR_BAD_TASK_ID"})
                return
            result_path = task_paths(task_id)["result"]
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                append_action_trace(
                    task_id,
                    str(result.get("trace_id") or make_trace_id(task_id)),
                    "activator.result_read",
                    str(result.get("status", "FINAL")),
                    {"named_blocker": result.get("named_blocker", ""), "ok": result.get("ok")},
                )
                self.send_json(200, result)
                return
            with TASK_LOCK:
                running = task_id in RUNNING_TASKS
            self.send_json(
                202 if running else 404,
                {
                    "task_id": task_id,
                    "ok": False,
                    "status": "RUNNING" if running else "NOT_FOUND",
                    "named_blocker": "" if running else "CODEX_ACTIVATOR_RESULT_NOT_FOUND",
                },
            )
            return
        self.send_json(404, {"ok": False, "named_blocker": "CODEX_ACTIVATOR_ROUTE_NOT_FOUND"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/codex/exec":
            self.send_json(404, {"ok": False, "named_blocker": "CODEX_ACTIVATOR_ROUTE_NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except Exception as error:
            self.send_json(
                400,
                {"ok": False, "named_blocker": "CODEX_ACTIVATOR_INVALID_JSON", "error": str(error)},
            )
            return

        request_payload, rejected = normalize_request(payload)
        if rejected:
            status = 403 if rejected["named_blocker"] == "CODEX_ACTIVATOR_GUARD_REJECTED_SELF_DESTRUCT" else 400
            self.send_json(status, rejected)
            return
        assert request_payload is not None
        task_id = request_payload["task_id"]
        append_action_trace(
            task_id,
            request_payload["trace_id"],
            "activator.request_accepted",
            "ACCEPTED",
            {"target": request_payload["target"], "wait": request_payload["wait"]},
        )
        paths = task_paths(task_id, request_payload["target"])
        with TASK_LOCK:
            if task_id in RUNNING_TASKS or paths["result"].exists():
                append_action_trace(
                    task_id,
                    request_payload["trace_id"],
                    "activator.request_rejected",
                    "BLOCKED",
                    {"named_blocker": "CODEX_ACTIVATOR_TASK_ID_CONFLICT"},
                )
                self.send_json(
                    409,
                    {
                        "task_id": task_id,
                        "ok": False,
                        "named_blocker": "CODEX_ACTIVATOR_TASK_ID_CONFLICT",
                    },
                )
                return
            if request_payload["wait"]:
                RUNNING_TASKS[task_id] = threading.current_thread()
            else:
                thread = threading.Thread(
                    target=run_background,
                    args=(request_payload,),
                    name=f"codex-activator-{task_id}",
                    daemon=True,
                )
                RUNNING_TASKS[task_id] = thread
                thread.start()

        if request_payload["wait"]:
            try:
                result = run_codex_task(request_payload)
            finally:
                with TASK_LOCK:
                    RUNNING_TASKS.pop(task_id, None)
            self.send_json(200 if result["ok"] else 500, result)
            return

        self.send_json(
            202,
            {
                "task_id": task_id,
                "trace_id": request_payload["trace_id"],
                "target": request_payload["target"],
                "ok": True,
                "status": "RUNNING",
                "result_url": f"/codex/result/{task_id}",
                "named_blocker": "",
            },
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> int:
    global RUNTIME_ROOT, RESULT_ROOT, ACTION_TRACE_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", default=PORT, type=int)
    parser.add_argument("--runtime", default=str(RUNTIME_ROOT))
    args = parser.parse_args()

    RUNTIME_ROOT = Path(args.runtime)
    RESULT_ROOT = RUNTIME_ROOT / "state" / "codex_results"
    ACTION_TRACE_ROOT = RUNTIME_ROOT / "state" / "action_delivery_trace"
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as error:
        if getattr(error, "winerror", None) == 10048 or error.errno == 10048:
            print("CODEX_ACTIVATOR_PORT_IN_USE", flush=True)
            return 2
        raise
    print(f"CODEX_ACTIVATOR_READY http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
