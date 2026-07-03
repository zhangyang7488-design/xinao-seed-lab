"""Grok local sync observe plane for codex exec --json (Popen + JSONL stream)."""

from __future__ import annotations

import json
import os
import pathlib
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_jsonl_event(line: str) -> dict[str, Any] | None:
    line = (line or "").strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return {"raw_line_excerpt": line[:240]}
    if not isinstance(event, dict):
        return None

    summary: dict[str, Any] = {
        "type": str(event.get("type") or event.get("method") or ""),
    }
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    params = event.get("params") if isinstance(event.get("params"), dict) else {}

    if summary["type"].startswith("item."):
        item = event.get("item") if isinstance(event.get("item"), dict) else item
    if item:
        summary["item_type"] = str(item.get("type") or "")
        if item.get("command"):
            summary["command"] = str(item.get("command"))[:500]
        if item.get("text"):
            summary["text_excerpt"] = str(item.get("text"))[:400]
        if item.get("status"):
            summary["item_status"] = str(item.get("status"))
    if params.get("delta"):
        summary["delta_excerpt"] = str(params.get("delta"))[:200]
    usage = event.get("usage")
    if isinstance(usage, dict):
        summary["usage"] = usage
    if event.get("thread_id"):
        summary["thread_id"] = str(event.get("thread_id"))
    return summary


def _drain_stream(
    stream,
    *,
    sink: list[str],
    label: str,
    observe: dict[str, Any],
    observe_path: pathlib.Path | None,
    on_line: Callable[[str], None] | None,
) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            sink.append(line)
            if on_line:
                on_line(line)
            if observe_path is not None:
                observe["stderr_tail"] = "\n".join(sink[-20:])[-2000:] if label == "stderr" else observe.get("stderr_tail", "")
                observe["updated_at"] = now_iso()
                write_json(observe_path, observe)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def run_codex_exec_json_observed(
    *,
    command: list[str],
    cwd: str,
    env: dict[str, str],
    stdin_text: str,
    stdout_jsonl_path: pathlib.Path,
    observe_path: pathlib.Path | None,
    timeout_seconds: int,
    ticket_id: str = "",
    auditor_code: str = "",
    role: str = "",
) -> dict[str, Any]:
    codex_binary = command[0] if command else ""
    observe: dict[str, Any] = {
        "schema_version": "xinao.grok_local_observe.v1",
        "generated_at": now_iso(),
        "updated_at": now_iso(),
        "ticket_id": ticket_id,
        "auditor_code": auditor_code,
        "role": role,
        "status": "starting",
        "pid": None,
        "jsonl_path": str(stdout_jsonl_path),
        "jsonl_line_count": 0,
        "last_event": {},
        "recent_events": [],
        "stderr_tail": "",
        "token_usage": {},
        "not_source_of_truth": True,
        "not_user_completion": True,
    }
    if observe_path is not None:
        write_json(observe_path, observe)

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    observe["pid"] = process.pid
    observe["status"] = "running"
    observe["updated_at"] = now_iso()
    if observe_path is not None:
        write_json(observe_path, observe)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    event_ring: list[dict[str, Any]] = []

    def on_stdout_line(line: str) -> None:
        stdout_lines.append(line)
        summary = summarize_jsonl_event(line)
        if summary:
            event_ring.append(summary)
            if len(event_ring) > 12:
                del event_ring[:-12]
            observe["last_event"] = summary
            observe["recent_events"] = list(event_ring)
            if summary.get("usage"):
                observe["token_usage"] = summary["usage"]
            if summary.get("item_type") == "agent_message" and summary.get("text_excerpt"):
                observe["last_agent_excerpt"] = summary["text_excerpt"]
            if summary.get("command"):
                observe["last_command"] = summary["command"]
        observe["jsonl_line_count"] = len(stdout_lines)
        observe["updated_at"] = now_iso()
        if observe_path is not None:
            write_json(observe_path, observe)
        try:
            with stdout_jsonl_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line if line.endswith("\n") else line + "\n")
        except OSError:
            pass

    stderr_thread = threading.Thread(
        target=_drain_stream,
        kwargs={
            "stream": process.stderr,
            "sink": stderr_lines,
            "label": "stderr",
            "observe": observe,
            "observe_path": observe_path,
            "on_line": None,
        },
        daemon=True,
    )
    stderr_thread.start()

    if process.stdin:
        process.stdin.write(stdin_text)
        process.stdin.close()

    deadline = time.monotonic() + max(30, int(timeout_seconds))
    try:
        while True:
            if process.poll() is not None:
                break
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=30)
                observe["status"] = "timeout"
                observe["named_blocker"] = "CODEX_EXEC_OBSERVE_TIMEOUT"
                break
            line = process.stdout.readline() if process.stdout else ""
            if line:
                on_stdout_line(line)
            elif process.poll() is not None:
                break
            else:
                time.sleep(0.05)
        if process.stdout:
            for line in process.stdout:
                on_stdout_line(line)
    finally:
        stderr_thread.join(timeout=5)
        exit_code = process.poll()
        if exit_code is None:
            process.wait(timeout=30)
            exit_code = process.returncode

    observe["exit_code"] = int(exit_code if exit_code is not None else 1)
    observe["status"] = "completed" if observe.get("status") != "timeout" else "timeout"
    observe["stderr_tail"] = "\n".join(stderr_lines)[-2000:]
    observe["finished_at"] = now_iso()
    observe["updated_at"] = observe["finished_at"]
    if observe_path is not None:
        write_json(observe_path, observe)

    return {
        "exit_code": observe["exit_code"],
        "stdout": "".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "observe": observe,
        "jsonl_path": str(stdout_jsonl_path),
    }