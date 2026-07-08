from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.cheap_worker_patch_executor.v1"
SENTINEL = "SENTINEL:XINAO_CHEAP_WORKER_PATCH_EXECUTOR_READY"
DEFAULT_ALLOWED_ROOTS = ("contracts", "docs", "scripts", "services", "tests")
BLOCKED_PATH_PARTS = {
    ".env",
    ".venv",
    "private_config",
    "secrets",
    "credentials",
    "__pycache__",
}
BLOCKED_SUFFIXES = {".key", ".pem", ".pfx", ".p12"}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    return text[:limit]


def provider_payload_text(provider_payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("content", "text", "message", "final", "output"):
        value = provider_payload.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value)
    for key in ("result_path", "artifact_ref", "provider_invocation_ref"):
        value = str(provider_payload.get(key) or "")
        if value:
            path = Path(value)
            if path.is_file():
                file_text = _read_text(path)
                if file_text:
                    chunks.append(file_text)
                    try:
                        parsed = json.loads(file_text)
                    except json.JSONDecodeError:
                        parsed = {}
                    if isinstance(parsed, dict):
                        for parsed_key in ("content", "text", "message", "final", "output"):
                            parsed_value = parsed.get(parsed_key)
                            if isinstance(parsed_value, str) and parsed_value.strip():
                                chunks.append(parsed_value)
    return "\n\n".join(chunks)


def extract_unified_diff(text: str) -> str:
    if not text:
        return ""
    fenced = re.search(r"```(?:diff|patch)?\s*(diff --git .*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip() + "\n"
    marker = text.find("diff --git ")
    if marker < 0:
        return ""
    return text[marker:].strip() + "\n"


def _diff_path_from_line(line: str) -> str:
    raw = line[4:].strip()
    if raw == "/dev/null":
        return ""
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    return raw.split("\t", 1)[0].strip()


def touched_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        candidate = ""
        if line.startswith("+++ ") or line.startswith("--- "):
            candidate = _diff_path_from_line(line)
        elif line.startswith("diff --git "):
            parts = line.split()
            for part in parts[2:4]:
                if part.startswith(("a/", "b/")):
                    candidate = part[2:]
                    break
        if candidate and candidate not in paths:
            paths.append(candidate)
    return paths


def _path_allowed(
    repo_root: Path, rel_path: str, allowed_roots: tuple[str, ...]
) -> tuple[bool, str]:
    if not rel_path or Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
        return False, "BLOCKER_PATH_VIOLATION"
    normalized = Path(rel_path)
    first = normalized.parts[0] if normalized.parts else ""
    if first not in allowed_roots:
        return False, "BLOCKER_PATH_VIOLATION"
    lowered_parts = {part.lower() for part in normalized.parts}
    if lowered_parts & BLOCKED_PATH_PARTS:
        return False, "BLOCKER_PATH_VIOLATION"
    if normalized.suffix.lower() in BLOCKED_SUFFIXES:
        return False, "BLOCKER_PATH_VIOLATION"
    resolved = (repo_root / normalized).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return False, "BLOCKER_PATH_VIOLATION"
    return True, ""


def validate_diff(
    diff_text: str,
    *,
    repo_root: Path,
    allowed_roots: tuple[str, ...] = DEFAULT_ALLOWED_ROOTS,
) -> dict[str, Any]:
    if not diff_text.strip():
        return {
            "passed": False,
            "named_blocker": "CHEAP_WORKER_PATCH_DIFF_MISSING",
            "touched_paths": [],
        }
    touched = touched_paths_from_diff(diff_text)
    if not touched:
        return {
            "passed": False,
            "named_blocker": "CHEAP_WORKER_PATCH_PATHS_MISSING",
            "touched_paths": [],
        }
    for pattern in SECRET_PATTERNS:
        if pattern.search(diff_text):
            return {
                "passed": False,
                "named_blocker": "BLOCKER_SECRET_DETECTED",
                "touched_paths": touched,
            }
    for rel_path in touched:
        ok, blocker = _path_allowed(repo_root, rel_path, allowed_roots)
        if not ok:
            return {"passed": False, "named_blocker": blocker, "touched_paths": touched}
    return {"passed": True, "named_blocker": "", "touched_paths": touched}


def _thin_glue_verify_argv(repo_root: Path) -> list[str] | None:
    flag = os.environ.get("XINAO_THIN_GLUE_VERIFY", "1")
    if flag.strip().lower() in {"0", "false", "no", "off"}:
        return None
    test_file = repo_root / "tests" / "test_thin_glue_stack.py"
    if not test_file.is_file():
        return None
    return [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=line"]


def verifier_argv(command: str, repo_root: Path) -> tuple[list[str], str]:
    command = command.strip()
    if not command:
        return [], "BLOCKER_VERIFIER_MISSING"
    if "verify_" in command.lower() and command.lower().endswith(".ps1"):
        thin_argv = _thin_glue_verify_argv(repo_root)
        if thin_argv:
            return thin_argv, ""
    if any(token in command for token in ("|", "&&", "||", ";", "`", "$(")):
        return [], "BLOCKER_VERIFIER_COMMAND_NOT_ALLOWED"
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        return [], "BLOCKER_VERIFIER_COMMAND_NOT_ALLOWED"
    if not parts:
        return [], "BLOCKER_VERIFIER_MISSING"
    first = parts[0].strip('"')
    if (
        first.lower() in {"python", "python.exe", "py"}
        and len(parts) >= 3
        and parts[1:3] == ["-m", "pytest"]
    ):
        return [sys.executable, "-m", "pytest", *parts[3:]], ""
    if (
        first.lower() in {"python", "python.exe", "py"}
        and len(parts) >= 3
        and parts[1:3] == ["-m", "py_compile"]
    ):
        return [sys.executable, "-m", "py_compile", *parts[3:]], ""
    script = (
        (repo_root / first).resolve() if not Path(first).is_absolute() else Path(first).resolve()
    )
    try:
        script.relative_to((repo_root / "scripts").resolve())
    except ValueError:
        return [], "BLOCKER_VERIFIER_COMMAND_NOT_ALLOWED"
    if script.suffix.lower() != ".ps1" or not script.is_file():
        return [], "BLOCKER_VERIFIER_COMMAND_NOT_ALLOWED"
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *parts[1:],
    ], ""


def run_command(argv: list[str], *, cwd: Path, timeout_sec: int = 120) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "stdout": (exc.stdout or "")[-10000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-10000:] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
        }
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-10000:],
        "stderr": completed.stderr[-10000:],
        "timed_out": False,
    }


def execute_patch_artifact(
    *,
    runtime_root: str | Path,
    repo_root: str | Path,
    task_id: str,
    worker_task_id: str,
    diff_text: str,
    verification: list[str] | tuple[str, ...],
    apply_patch: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    # Preserve the logical workspace path in evidence. On this machine the S
    # workspace is a Windows link; resolve() expands it to a legacy target.
    repo = Path(repo_root).absolute()
    record_dir = runtime / "state" / "cheap_worker_patch_executor" / "records"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{task_id}.{worker_task_id}")[:180]
    record_path = record_dir / f"{safe_id}.json"
    latest_path = runtime / "state" / "cheap_worker_patch_executor" / "latest.json"
    diff_path = runtime / "state" / "cheap_worker_patch_executor" / "diffs" / f"{safe_id}.diff"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text(diff_text, encoding="utf-8")

    validation = validate_diff(diff_text, repo_root=repo)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "blocked",
        "task_id": task_id,
        "worker_task_id": worker_task_id,
        "repo_root": str(repo),
        "diff_path": str(diff_path),
        "diff_sha256": _sha256_text(diff_text),
        "validation": validation,
        "touched_paths": validation.get("touched_paths", []),
        "repo_mutation_performed": False,
        "verifier_results": [],
        "named_blocker": validation.get("named_blocker", ""),
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "created_at": now_iso(),
    }
    if not validation.get("passed"):
        write_json(record_path, result)
        write_json(latest_path, result)
        result["record_path"] = str(record_path)
        result["latest_path"] = str(latest_path)
        return result

    check = run_command(
        ["git", "apply", "--check", "--whitespace=nowarn", str(diff_path)], cwd=repo
    )
    result["git_apply_check"] = check
    if check["exit_code"] != 0:
        result["named_blocker"] = "BLOCKER_PATCH_APPLY_CHECK_FAILED"
        write_json(record_path, result)
        write_json(latest_path, result)
        result["record_path"] = str(record_path)
        result["latest_path"] = str(latest_path)
        return result
    if apply_patch:
        applied = run_command(["git", "apply", "--whitespace=nowarn", str(diff_path)], cwd=repo)
        result["git_apply"] = applied
        if applied["exit_code"] != 0:
            result["named_blocker"] = "BLOCKER_PATCH_APPLY_FAILED"
            write_json(record_path, result)
            write_json(latest_path, result)
            result["record_path"] = str(record_path)
            result["latest_path"] = str(latest_path)
            return result
        result["repo_mutation_performed"] = True

    allowed_verifiers: list[str] = []
    for command in verification:
        if isinstance(command, str) and command.strip():
            allowed_verifiers.append(command.strip())
    if not allowed_verifiers:
        result["named_blocker"] = "BLOCKER_VERIFIER_MISSING"
        write_json(record_path, result)
        write_json(latest_path, result)
        result["record_path"] = str(record_path)
        result["latest_path"] = str(latest_path)
        return result

    for command in allowed_verifiers:
        argv, blocker = verifier_argv(command, repo)
        verifier_result = {"command": command, "argv": argv, "named_blocker": blocker}
        if blocker:
            result["verifier_results"].append(verifier_result)
            result["named_blocker"] = blocker
            write_json(record_path, result)
            write_json(latest_path, result)
            result["record_path"] = str(record_path)
            result["latest_path"] = str(latest_path)
            return result
        run = run_command(argv, cwd=repo, timeout_sec=300)
        verifier_result.update(run)
        result["verifier_results"].append(verifier_result)
        if run["exit_code"] != 0:
            result["named_blocker"] = "BLOCKER_VERIFIER_FAILED"
            write_json(record_path, result)
            write_json(latest_path, result)
            result["record_path"] = str(record_path)
            result["latest_path"] = str(latest_path)
            return result

    result["status"] = "applied_verified" if apply_patch else "verified_dry_run"
    result["named_blocker"] = ""
    write_json(record_path, result)
    write_json(latest_path, result)
    result["record_path"] = str(record_path)
    result["latest_path"] = str(latest_path)
    return result


def execute_from_provider_payload(
    *,
    runtime_root: str | Path,
    repo_root: str | Path,
    task_id: str,
    worker_task_id: str,
    provider_payload: dict[str, Any],
    verification: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    text = provider_payload_text(provider_payload)
    diff_text = extract_unified_diff(text)
    return execute_patch_artifact(
        runtime_root=runtime_root,
        repo_root=repo_root,
        task_id=task_id,
        worker_task_id=worker_task_id,
        diff_text=diff_text,
        verification=verification,
        apply_patch=True,
    )
