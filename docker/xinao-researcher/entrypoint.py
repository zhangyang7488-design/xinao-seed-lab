from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

INPUT_ROOT = Path("/input")
OUTPUT_ROOT = Path("/output")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _failure(reason_code: str, detail: str, *, exit_code: int = 20) -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(
        OUTPUT_ROOT / "result.json",
        {
            "schema_version": "xinao.researcher_container_result.v1",
            "status": "RUNTIME_FAILED",
            "reason_codes": [reason_code],
            "detail": detail[:2000],
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
        },
    )
    return exit_code


def _valid_candidate(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "schema_version",
        "status",
        "research_question",
        "summary",
        "hypotheses",
        "methods",
        "evidence_needed",
        "current_action_projection",
    }
    if set(value) != required:
        return False
    if value.get("schema_version") != "xinao.research_candidate.v1":
        return False
    if value.get("status") not in {"CANDIDATE_READY", "EXPLICIT_NO_ACTION"}:
        return False
    projection = value.get("current_action_projection")
    return isinstance(projection, dict) and projection.get("status") in {
        "SUPPORTED",
        "UNSUPPORTED",
        "NOT_ASSESSED",
    }


def main() -> int:
    prompt_path = INPUT_ROOT / "prompt.md"
    schema_path = INPUT_ROOT / "output.schema.json"
    request_path = INPUT_ROOT / "request.json"
    for path in (prompt_path, schema_path, request_path):
        if not path.is_file():
            return _failure("INPUT_FILE_MISSING", str(path), exit_code=10)

    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failure("REQUEST_INVALID", str(exc), exit_code=10)
    if set(request) != {"schema_version", "research_question", "as_of"}:
        return _failure("REQUEST_FIELDS_INVALID", "request keys are not exact", exit_code=10)
    if request.get("schema_version") != "xinao.research_request.v1":
        return _failure("REQUEST_SCHEMA_INVALID", "unsupported request schema", exit_code=10)
    question = request.get("research_question")
    if not isinstance(question, str) or not question.strip():
        return _failure("RESEARCH_QUESTION_INVALID", "question must be non-empty", exit_code=10)

    schema_text = schema_path.read_text(encoding="utf-8")
    command = [
        "/usr/local/bin/grok",
        "--no-auto-update",
        "--prompt-file",
        str(prompt_path),
        "--model",
        "grok-4.5",
        "--output-format",
        "json",
        "--json-schema",
        schema_text,
        "--no-subagents",
        "--no-memory",
        "--disable-web-search",
        "--max-turns",
        "1",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--cwd",
        "/work",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return _failure("MODEL_TIMEOUT", "model invocation exceeded 900 seconds", exit_code=30)
    if completed.returncode != 0:
        return _failure("MODEL_INVOCATION_FAILED", completed.stderr, exit_code=30)
    try:
        provider_envelope = json.loads(completed.stdout)
        raw_text = provider_envelope["text"]
        candidate = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        return _failure("MODEL_OUTPUT_INVALID", str(exc), exit_code=40)
    if not _valid_candidate(candidate):
        return _failure(
            "CANDIDATE_SCHEMA_INVALID", "candidate envelope failed validation", exit_code=40
        )

    _write_json(
        OUTPUT_ROOT / "result.json",
        {
            "schema_version": "xinao.researcher_container_result.v1",
            "status": candidate["status"],
            "reason_codes": [],
            "candidate": candidate,
            "request_sha256": _sha256(request_path),
            "prompt_sha256": _sha256(prompt_path),
            "output_schema_sha256": _sha256(schema_path),
            "provider": "grok",
            "requested_model": "grok-4.5",
            "provider_stop_reason": provider_envelope.get("stopReason"),
            "provider_num_turns": provider_envelope.get("num_turns"),
            "provider_session_id_present": bool(provider_envelope.get("sessionId")),
            "provider_request_id_present": bool(provider_envelope.get("requestId")),
            "provider_model_usage": provider_envelope.get("modelUsage", {}),
            "usage": provider_envelope.get("usage", {}),
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
