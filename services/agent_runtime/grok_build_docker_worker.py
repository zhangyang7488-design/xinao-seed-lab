"""Docker-native Grok Build adapter for the canonical LangGraph worker.

Temporal/LangGraph owns scheduling.  This module is only a thin Activity-side
binding to xAI's official headless CLI.  It deliberately refuses host use so a
successful receipt proves that the model call happened inside ``houtai-gongren``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import portalocker
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    artifact_json_bytes,
    canonical_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DOCKER_CONSUMER_ID,
    build_grok_attempt_receipt,
    build_grok_logical_contract,
    expected_docker_grok_backend_models,
    grok_docker_model_identity_binding,
)

SCHEMA_VERSION = "xinao.grok.docker_native_cli.v1"
FANIN_SCHEMA_VERSION = "xinao.grok.temporal_acpx_fanin.v2"
FANIN_SENTINEL = "XINAO_GROK_TEMPORAL_FANIN_V1"
PROVIDER_ID = "grok_acpx_headless"
SUPERVISOR_PROFILE_REF = "grok.com.cached_profile"
SUPERVISOR_DURABLE_TRANSPORT_ID = "temporal-docker-langgraph"
MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v2"
DEFAULT_MODEL = "grok-composer-2.5-fast"
ESCALATION_MODEL = "grok-4.5"
ALLOWED_MODELS = frozenset({DEFAULT_MODEL, ESCALATION_MODEL})
# Composer has historically been callable through an authenticated xAI OAuth
# session while absent from /v1/models.  This exception only admits the
# selector for a fail-closed probe; it never attests the backend model.
HIDDEN_OAUTH_MODEL_SELECTORS = frozenset({DEFAULT_MODEL})
DEFAULT_ROUTE_ROLE = "default_background_worker"
ESCALATION_ROUTE_ROLE = "grok_4_5_escalation_worker"
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_MAX_TURNS = 16
DEFAULT_LANE_DEADLINE_SECONDS = 1_800
DEFAULT_MIN_RESULT_CHARS = 256
MIN_LANE_DEADLINE_SECONDS = 60
MAX_LANE_DEADLINE_SECONDS = 7_200
MAX_LANE_TURNS = 40
DEFAULT_RECOVERY_CONTINUATIONS = 2
MAX_RECOVERY_CONTINUATIONS = 8
COMPLETED_STOP_REASONS = frozenset({"endturn"})
RESULT_FORMATS = frozenset({"text", "json_object"})
CLI_POLICY_VERSION = "grok-cli-effective-output-v6"
EXECUTION_CONTRACT_VERSION = "xinao.grok.shared_execution_contract.v1"
MODEL_CAPABILITY_SNAPSHOT_VERSION = "xinao.grok.model_capabilities.v2"
AUTHENTICATED_MODEL_CATALOG_VERSION = "xinao.grok.authenticated_model_catalog.v1"
AUTHENTICATED_MODEL_CATALOG_ORIGIN = "https://cli-chat-proxy.grok.com/v1/models"
AUTHENTICATED_MODEL_CATALOG_TTL_SECONDS = 300
MODEL_CAPABILITY_BINDING_VERSION = "xinao.grok.model_capability_binding.v2"
MIN_GROK_CLI_VERSION = (0, 2, 85)
RULES_SNAPSHOT_VERSION = "xinao.grok.rules_snapshot.v1"
REQUIRED_RULE_PATHS = (
    Path("/app/AGENTS.md"),
    Path("/mainline/00_先读我_主线入口与读取顺序.txt"),
    Path("/mainline/工具胶水宪法/软件工具胶水宪法_当前有效.txt"),
    Path("/mainline/工具胶水宪法/跨接缝执行封套与一致性协议_当前有效.txt"),
    Path("/evidence/state/Codex_Situation_Island/contracts/working_agreement.md"),
)


class DockerGrokTransientError(RuntimeError):
    """A bounded Activity retry may recover this provider failure."""


class DockerGrokPermanentError(RuntimeError):
    """Retrying cannot repair this configuration, policy, or authentication failure."""


def docker_native_grok_enabled() -> bool:
    """Admit this provider only in the named Docker worker runtime."""

    enabled = os.environ.get("XINAO_GROK_DOCKER_NATIVE", "0").strip().lower()
    return enabled in {"1", "true", "yes", "on"} and Path("/.dockerenv").is_file()


def _grok_cli_environment(
    grok_home: Path,
    *,
    base: dict[str, str] | None = None,
) -> tuple[dict[str, str], Path]:
    """Bind the official CLI to the mounted, refreshable worker profile."""

    profile_dir = grok_home / ".grok"
    env = dict(os.environ if base is None else base)
    env["HOME"] = str(grok_home)
    # Grok Build 0.2.x treats GROK_HOME as the authoritative user-state root.
    # HOME remains bound for tools spawned by Grok, but cannot substitute for it.
    env["GROK_HOME"] = str(profile_dir)
    # This route intentionally burns the user's Grok Build subscription quota.
    # Never let a compose/API environment variable silently switch the billable surface.
    env.pop("XAI_API_KEY", None)
    env.pop("GROK_DEPLOYMENT_KEY", None)
    return env, profile_dir


def _safe(value: object, *, limit: int = 96) -> str:
    cleaned = _SAFE_RE.sub("_", str(value or "").strip())
    return (cleaned or "unknown")[:limit]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: object) -> bytes:
    return artifact_json_bytes(value)


def _write_bytes_atomic(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return _sha256(raw)


def _write_json_atomic(path: Path, value: object) -> str:
    raw = _json_bytes(value)
    return _write_bytes_atomic(path, raw)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _rules_snapshot(paths: tuple[Path, ...] = REQUIRED_RULE_PATHS) -> dict[str, Any]:
    """Freeze the current shared rules observed by this worker process."""

    files: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            raise DockerGrokPermanentError(f"required Grok rule source is unavailable: {path}")
        raw = path.read_bytes()
        files.append(
            {
                "path": str(path),
                "sha256": _sha256(raw),
                "size_bytes": len(raw),
            }
        )
    digest = _sha256(_json_bytes(files))
    return {
        "schema_version": RULES_SNAPSHOT_VERSION,
        "sha256": digest,
        "files": files,
    }


def _rules_cli_text(snapshot: dict[str, Any]) -> str:
    paths = ", ".join(str(item.get("path") or "") for item in snapshot["files"])
    return (
        f"Shared local rules snapshot {snapshot['sha256']} is bound to this run. "
        f"Read and follow the current files before acting: {paths}. "
        "The current task is task-level authority; these files provide stable context only. "
        "Do not inspect or emit secret values, and do not claim the parent task is complete."
    )


def _authenticated_model_catalog(
    catalog_path: Path,
    *,
    requested_model: str,
    cli_version: str,
    observed_at: datetime,
) -> dict[str, Any]:
    """Read only server-advertised models, excluding local CLI aliases."""

    if not catalog_path.is_file():
        raise DockerGrokPermanentError(
            f"authenticated Grok model catalog is unavailable: {catalog_path}"
        )
    try:
        raw = catalog_path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DockerGrokPermanentError("authenticated Grok model catalog is invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), dict):
        raise DockerGrokPermanentError("authenticated Grok model catalog has no server model map")
    origin = str(payload.get("origin") or "")
    if origin != AUTHENTICATED_MODEL_CATALOG_ORIGIN:
        raise DockerGrokPermanentError(
            f"authenticated Grok model catalog origin is invalid: {origin or 'missing'}"
        )
    fetched_at_text = str(payload.get("fetched_at") or "")
    try:
        fetched_at = datetime.fromisoformat(fetched_at_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DockerGrokPermanentError(
            "authenticated Grok model catalog fetched_at is invalid"
        ) from exc
    if fetched_at.tzinfo is None:
        raise DockerGrokPermanentError(
            "authenticated Grok model catalog fetched_at has no timezone"
        )
    age_seconds = (observed_at - fetched_at).total_seconds()
    if age_seconds < -30 or age_seconds > AUTHENTICATED_MODEL_CATALOG_TTL_SECONDS:
        raise DockerGrokPermanentError("authenticated Grok model catalog is stale")
    catalog_version = str(payload.get("grok_version") or "")
    if catalog_version != cli_version:
        raise DockerGrokPermanentError(
            "authenticated Grok model catalog CLI version mismatch: "
            f"catalog={catalog_version or 'missing'}, cli={cli_version}"
        )
    auth_method = str(payload.get("auth_method") or "")
    if auth_method != "session":
        raise DockerGrokPermanentError(
            "authenticated Grok model catalog auth mismatch: "
            f"observed={auth_method or 'missing'}, required=session"
        )
    modified_at = datetime.fromtimestamp(catalog_path.stat().st_mtime, tz=UTC)
    server_model_ids = sorted(map(str, payload["models"]))
    requested_entry = payload["models"].get(requested_model)
    if requested_model in payload["models"] and not isinstance(requested_entry, dict):
        raise DockerGrokPermanentError(
            "authenticated Grok model catalog requested entry is invalid"
        )
    requested_entry_sha256 = (
        _sha256(_json_bytes(requested_entry)) if requested_model in payload["models"] else ""
    )
    snapshot = {
        "schema_version": AUTHENTICATED_MODEL_CATALOG_VERSION,
        "origin": origin,
        "fetched_at": fetched_at.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "ttl_seconds": AUTHENTICATED_MODEL_CATALOG_TTL_SECONDS,
        "modified_at": modified_at.isoformat(),
        "grok_version": catalog_version,
        "auth_method": auth_method,
        "server_model_ids": server_model_ids,
        "requested_model_available": requested_model in server_model_ids,
        "requested_server_entry_sha256": requested_entry_sha256,
        "cache_sha256": _sha256(raw),
    }
    snapshot["sha256"] = _sha256(_json_bytes(snapshot))
    return snapshot


def _model_capability_binding(
    *,
    requested_model: str,
    cli_version: str,
    merged_cli_model_ids: list[str],
    authenticated_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable identity input; exclude catalog freshness evidence."""

    server_model_ids = set(map(str, authenticated_catalog.get("server_model_ids") or []))
    merged_model_ids = set(map(str, merged_cli_model_ids))
    requested_in_server_catalog = requested_model in server_model_ids
    requested_in_merged_cli = requested_model in merged_model_ids
    hidden_oauth_selector = requested_model in HIDDEN_OAUTH_MODEL_SELECTORS
    admission_source = (
        "authenticated_server_catalog"
        if requested_in_server_catalog
        else (
            "hidden_oauth_selector"
            if hidden_oauth_selector and requested_in_merged_cli
            else "unavailable"
        )
    )
    binding = {
        "schema_version": MODEL_CAPABILITY_BINDING_VERSION,
        "requested_model": requested_model,
        "cli_version": cli_version,
        "origin": str(authenticated_catalog.get("origin") or ""),
        "auth_method": str(authenticated_catalog.get("auth_method") or ""),
        "requested_server_entry_sha256": str(
            authenticated_catalog.get("requested_server_entry_sha256") or ""
        ),
        "requested_in_server_catalog": requested_in_server_catalog,
        "requested_in_merged_cli": requested_in_merged_cli,
        "hidden_oauth_selector": hidden_oauth_selector,
        "admission_source": admission_source,
        "identity_policy": "exact_declared_selector_backend_binding_v1",
        "expected_backend_model_ids": expected_docker_grok_backend_models(requested_model),
        "requested_model_available": bool(
            requested_in_merged_cli and (requested_in_server_catalog or hidden_oauth_selector)
        ),
    }
    binding["sha256"] = _sha256(_json_bytes(binding))
    return binding


async def _discover_model_capabilities(
    grok_bin: Path,
    *,
    env: dict[str, str],
    profile_dir: Path,
    requested_model: str,
) -> dict[str, Any]:
    """Discover the authenticated profile's current model catalog before dispatch."""

    version_process = await asyncio.create_subprocess_exec(
        str(grok_bin),
        "version",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        version_stdout, version_stderr = await asyncio.wait_for(
            version_process.communicate(), timeout=15
        )
    except TimeoutError as exc:
        await _terminate_and_reap(version_process)
        raise DockerGrokTransientError("Grok CLI version discovery timed out") from exc
    version_text = version_stdout.decode("utf-8", errors="replace").strip()
    version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text)
    version = tuple(int(part) for part in version_match.groups()) if version_match else ()
    if version_process.returncode != 0 or version < MIN_GROK_CLI_VERSION:
        raise DockerGrokPermanentError(
            "Grok CLI does not meet the structured-output/background-task minimum: "
            f"observed={version_text or 'unknown'}, required={'.'.join(map(str, MIN_GROK_CLI_VERSION))}, "
            f"rc={version_process.returncode}, stderr_sha256={_sha256(version_stderr)}"
        )

    process = await asyncio.create_subprocess_exec(
        str(grok_bin),
        "models",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError as exc:
        await _terminate_and_reap(process)
        raise DockerGrokTransientError("Grok model capability discovery timed out") from exc
    models_text = stdout.decode("utf-8", errors="replace")
    merged_cli_model_ids = sorted(
        {
            match.group(1).strip()
            for line in models_text.splitlines()
            if (match := re.match(r"^\s*[-*]\s+(\S+)\s*(?:\(default\))?\s*$", line))
        }
    )
    if process.returncode != 0:
        raise DockerGrokPermanentError(
            "authenticated Grok model discovery failed: "
            f"rc={process.returncode}, stderr_sha256={_sha256(stderr)}"
        )
    cli_authentication_ok = "you are logged in with grok.com." in models_text.casefold()
    if not cli_authentication_ok:
        raise DockerGrokPermanentError(
            "authenticated Grok CLI profile was not selected by model discovery"
        )
    authenticated_catalog = _authenticated_model_catalog(
        profile_dir / "models_cache.json",
        requested_model=requested_model,
        cli_version=".".join(map(str, version)),
        observed_at=datetime.now(UTC),
    )
    available = list(authenticated_catalog["server_model_ids"])
    binding = _model_capability_binding(
        requested_model=requested_model,
        cli_version=".".join(map(str, version)),
        merged_cli_model_ids=merged_cli_model_ids,
        authenticated_catalog=authenticated_catalog,
    )
    snapshot = {
        "schema_version": MODEL_CAPABILITY_SNAPSHOT_VERSION,
        "requested_model": requested_model,
        "available_model_ids": available,
        "merged_cli_model_ids": merged_cli_model_ids,
        "requested_model_available": binding["requested_model_available"],
        "cli_authentication_ok": cli_authentication_ok,
        "binding": binding,
        "binding_sha256": binding["sha256"],
        "authenticated_catalog": authenticated_catalog,
        "return_code": int(process.returncode or 0),
        "cli_version": ".".join(map(str, version)),
        "cli_version_stdout_sha256": _sha256(version_stdout),
        "cli_version_stderr_sha256": _sha256(version_stderr),
        "stdout_sha256": _sha256(stdout),
        "stderr_sha256": _sha256(stderr),
    }
    snapshot["sha256"] = _sha256(_json_bytes(snapshot))
    if snapshot["requested_model_available"] is not True:
        raise DockerGrokPermanentError(
            "requested Grok model is unavailable after authenticated CLI/catalog policy: "
            f"requested={requested_model}, server_available={available}, "
            f"merged_cli_models={merged_cli_model_ids}"
        )
    return snapshot


async def _inspect_grok_context(
    grok_bin: Path,
    *,
    env: dict[str, str],
    cwd: Path,
) -> dict[str, Any]:
    """Record the rules/configuration Grok actually discovers from the lane cwd."""

    process = await asyncio.create_subprocess_exec(
        str(grok_bin),
        "inspect",
        "--json",
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError as exc:
        await _terminate_and_reap(process)
        raise DockerGrokTransientError("Grok context inspection timed out") from exc
    payload = _decode_cli_payload(stdout)
    if process.returncode != 0 or not isinstance(payload, dict):
        raise DockerGrokPermanentError(
            "Grok context inspection failed: "
            f"rc={process.returncode}, stdout_sha256={_sha256(stdout)}, "
            f"stderr_sha256={_sha256(stderr)}"
        )
    instructions = [
        {
            "path": str(item.get("path") or ""),
            "scope": str(item.get("scope") or ""),
            "file_type": str(item.get("fileType") or ""),
            "size_bytes": int(item.get("sizeBytes") or 0),
            "approx_tokens": int(item.get("approxTokens") or 0),
        }
        for item in payload.get("projectInstructions", [])
        if isinstance(item, dict)
    ]
    root_agents_discovered = any(
        Path(item["path"]).name.casefold() == "agents.md" for item in instructions
    )
    if str(cwd).rstrip("/") == "/app" and not root_agents_discovered:
        raise DockerGrokPermanentError(
            "Grok inspect did not discover the mounted root AGENTS.md from /app"
        )
    snapshot = {
        "schema_version": "xinao.grok.context_inspect.v1",
        "grok_version": str(payload.get("grokVersion") or ""),
        "cwd": str(payload.get("cwd") or ""),
        "project_root": str(payload.get("projectRoot") or ""),
        "project_trusted": payload.get("projectTrusted") is True,
        "project_instructions": instructions,
        "root_agents_discovered": root_agents_discovered,
        "return_code": int(process.returncode or 0),
        "stdout_sha256": _sha256(stdout),
        "stderr_sha256": _sha256(stderr),
    }
    snapshot["sha256"] = _sha256(_json_bytes(snapshot))
    return snapshot


def _heartbeat(details: dict[str, Any]) -> None:
    try:
        from temporalio import activity

        activity.heartbeat(details)
    except RuntimeError:
        # Pure unit calls have no Activity context.
        pass


def _activity_owner() -> dict[str, Any]:
    try:
        from temporalio import activity

        info = activity.info()
    except RuntimeError:
        return {}
    return {
        "activity_id": str(info.activity_id),
        "activity_attempt": int(info.attempt),
        "workflow_id": str(info.workflow_id),
        "workflow_run_id": str(info.workflow_run_id),
    }


async def _acquire_operation_lease(
    lease_path: Path,
    *,
    lane_id: str,
    timeout_seconds: int,
) -> portalocker.Lock:
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lock = portalocker.Lock(
        str(lease_path),
        mode="a+",
        timeout=0,
        flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
    )
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        try:
            lock.acquire()
            return lock
        except portalocker.exceptions.LockException as exc:
            _heartbeat(
                {
                    "lane_id": lane_id,
                    "state": "waiting_for_operation_lease",
                    "lease_path_sha256": _sha256(str(lease_path).encode("utf-8")),
                }
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise DockerGrokTransientError(
                    "Docker Grok operation lease wait exceeded bounded timeout"
                ) from exc
            await asyncio.sleep(1)


def _map_host_path_to_container(raw: object) -> str:
    value = str(raw or "/app").strip().replace("\\", "/")
    folded = value.casefold().rstrip("/")
    mappings = (
        ("d:/xinao_research_runtime", "/evidence"),
        ("e:/xinao_research_workspaces/s", "/app"),
        ("e:/xinao_research_workspaces/nianhua-new-route-active", "/app"),
    )
    for host_root, container_root in mappings:
        if folded == host_root:
            return container_root
        prefix = f"{host_root}/"
        if folded.startswith(prefix):
            return f"{container_root}/{value[len(prefix) :]}"
    if len(folded) >= 3 and folded[0].isalpha() and folded[1:3] == ":/":
        raise ValueError(f"Windows path is not mounted into the Docker worker: {value}")
    return value


def _container_cwd(raw: object, *, write: bool) -> Path:
    value = _map_host_path_to_container(raw)
    path = Path(value).resolve()
    if write:
        isolated = Path("/evidence/worktrees").resolve()
        try:
            path.relative_to(isolated)
        except ValueError as exc:
            raise ValueError(f"write-enabled Docker Grok lane must stay under {isolated}") from exc
    elif not (str(path).startswith("/app") or str(path).startswith("/evidence")):
        path = Path("/app")
    if not path.is_dir():
        raise ValueError(f"Docker Grok cwd is not available: {path}")
    return path


def _operation_id(
    workflow_id: str,
    lane_id: str,
    prompt_sha256: str,
    model: str,
    *,
    execution_prompt_sha256: str = "",
    mode: str = "",
    cwd: str = "",
    write: bool = False,
    max_turns: int | None = None,
    deadline_seconds: int = 0,
    correlation_id: str = "",
    parent_operation_id: str = "",
    contract_id: str = "",
    allowed_tools: tuple[str, ...] = (),
    planning: str = "auto",
    subagents: str = "auto",
    external_research: str = "auto",
    memory: str = "auto",
    model_capability_sha256: str = "",
    rules_snapshot_sha256: str = "",
    context_inspect_sha256: str = "",
    max_recovery_continuations: int = 0,
    result_format: str = "text",
    result_json_schema_sha256: str = "",
    min_result_chars: int = 1,
    required_result_markers: tuple[str, ...] = (),
) -> str:
    raw = _json_bytes(
        {
            "workflow_id": workflow_id,
            "lane_id": lane_id,
            "prompt_sha256": prompt_sha256,
            "execution_prompt_sha256": execution_prompt_sha256,
            "model": model,
            "mode": mode,
            "cwd": cwd,
            "write": write,
            "max_turns": max_turns,
            "deadline_seconds": deadline_seconds,
            "correlation_id": correlation_id,
            "parent_operation_id": parent_operation_id,
            "contract_id": contract_id,
            "allowed_tools": list(allowed_tools),
            "planning": planning,
            "subagents": subagents,
            "external_research": external_research,
            "memory": memory,
            "model_capability_sha256": model_capability_sha256,
            "rules_snapshot_sha256": rules_snapshot_sha256,
            "context_inspect_sha256": context_inspect_sha256,
            "max_recovery_continuations": max_recovery_continuations,
            "result_format": result_format,
            "result_json_schema_sha256": result_json_schema_sha256,
            "min_result_chars": min_result_chars,
            "required_result_markers": list(required_result_markers),
            "cli_policy_version": CLI_POLICY_VERSION,
        }
    )
    return f"op_grok_docker_{_sha256(raw)[:32]}"


def _session_cli_args(
    session_id: str,
    *,
    attempt: int,
    session_materialized: bool = True,
    resume: bool | None = None,
) -> list[str]:
    should_resume = attempt > 1 and session_materialized if resume is None else bool(resume)
    return ["--resume", session_id] if should_resume else ["--session-id", session_id]


def _retryable_session_lock(stderr: bytes, *, attempt: int, retries: int) -> bool:
    return attempt > 1 and retries < 3 and b"is already in use" in stderr.lower()


def _session_materialized(grok_home: Path, session_id: str) -> bool:
    sessions_root = grok_home / ".grok" / "sessions"
    return sessions_root.is_dir() and any(
        candidate.is_dir() for candidate in sessions_root.glob(f"*/{session_id}")
    )


def _recovery_prompt(*, final_only: bool = False) -> str:
    if final_only:
        return (
            "Recovery continuation for the existing bounded read-only task. Do not repeat "
            "completed analysis or tool calls. Return the concise final answer now; use no "
            "additional tools unless strictly required to finish an incomplete observation."
        )
    return (
        "Recovery after a bounded worker interruption. Continue the existing read-only task "
        "from session context without repeating completed analysis, tool calls, or side "
        "effects. If the task is already complete, return the concise final answer now."
    )


def _output_contract_recovery_prompt(
    *,
    result_format: str,
    result_json_schema: dict[str, Any] | None,
    required_result_markers: tuple[str, ...],
) -> str:
    """Ask the same session to repair only its rejected final representation."""

    prompt = (
        "Your previous EndTurn response was rejected by the local effective-output "
        "contract. Do not repeat research, analysis, or tool calls. Return only a corrected "
        "final answer now. "
    )
    if result_format == "json_object":
        schema_text = json.dumps(
            result_json_schema or {"type": "object"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prompt += (
            "Return exactly one raw JSON object with no Markdown fence, preamble, or "
            f"trailing text, matching this JSON Schema exactly: {schema_text}. "
        )
    if required_result_markers:
        prompt += (
            "The final representation must contain these literal markers: "
            + json.dumps(list(required_result_markers), ensure_ascii=False)
            + "."
        )
    return prompt


def _decode_cli_payload(stdout: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _cli_failure_kind(stderr: bytes, payload: dict[str, Any] | None) -> str:
    folded = stderr.lower()
    if b"is already in use" in folded:
        return "session_in_use"
    if b"session" in folded and (b"not found" in folded or b"does not exist" in folded):
        return "session_not_found"
    if b"not signed in" in folded or b"authentication" in folded:
        return "authentication"
    if isinstance(payload, dict):
        stop_reason = str(payload.get("stopReason") or "").casefold()
        if stop_reason == "cancelled" and str(payload.get("sessionId") or "").strip():
            return "session_incomplete"
        if str(payload.get("type") or "").casefold() == "error":
            message = str(payload.get("message") or "").casefold()
            if "not signed in" in message or "authentication" in message:
                return "authentication"
            if "session" in message and ("not found" in message or "does not exist" in message):
                return "session_not_found"
    return "other"


def _observed_backend_models(model_usage: dict[str, Any]) -> list[str]:
    """Return only backend models that the CLI says executed at least once."""

    return sorted(
        str(model)
        for model, stats in model_usage.items()
        if isinstance(stats, dict) and int(stats.get("modelCalls") or 0) > 0
    )


def _safe_cli_summary(
    payload: dict[str, Any] | None,
    *,
    requested_model: str,
    return_code: int,
    stdout: bytes,
    stderr: bytes,
) -> dict[str, Any]:
    value = payload or {}
    raw_usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
    usage = {
        key: int(raw_usage.get(key) or 0)
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    }
    raw_model_usage = value.get("modelUsage") if isinstance(value.get("modelUsage"), dict) else {}
    model_usage = {
        str(model): {
            key: int(stats.get(key) or 0)
            for key in ("inputTokens", "outputTokens", "cacheReadInputTokens", "modelCalls")
        }
        for model, stats in raw_model_usage.items()
        if isinstance(stats, dict)
    }
    observed_models = _observed_backend_models(model_usage)
    expected_backend_models = expected_docker_grok_backend_models(requested_model)
    failure_kind = _cli_failure_kind(stderr, payload)
    if return_code == 0 and failure_kind == "other":
        failure_kind = "none"
    text = str(value.get("text") or "")
    return {
        "return_code": int(return_code),
        "failure_kind": failure_kind,
        "stdout_sha256": _sha256(stdout),
        "stderr_sha256": _sha256(stderr),
        "text_chars": len(text),
        "text_sha256": _sha256(text.encode("utf-8")) if text else "",
        "session_id": str(value.get("sessionId") or ""),
        "request_id": str(value.get("requestId") or ""),
        "stop_reason": str(value.get("stopReason") or ""),
        "usage": usage,
        "model_usage": model_usage,
        "requested_model": requested_model,
        "selected_model": requested_model,
        "observed_models": observed_models,
        "expected_backend_models": expected_backend_models,
        "model_identity_ok": bool(observed_models == expected_backend_models),
    }


def _aggregate_invocation_usage(invocations: list[dict[str, Any]]) -> dict[str, Any]:
    usage_keys = (
        "input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    totals = {key: 0 for key in usage_keys}
    accepted_tokens = 0
    cancelled_tokens = 0
    failed_tokens = 0
    for invocation in invocations:
        usage = invocation.get("usage") if isinstance(invocation.get("usage"), dict) else {}
        for key in usage_keys:
            totals[key] += int(usage.get(key) or 0)
        tokens = int(usage.get("total_tokens") or 0)
        stop_reason = str(invocation.get("stop_reason") or "").casefold()
        return_code = int(invocation.get("return_code") or 0)
        if (
            return_code == 0
            and stop_reason in COMPLETED_STOP_REASONS
            and invocation.get("effective_output_accepted", True) is True
        ):
            accepted_tokens += tokens
        elif stop_reason == "cancelled":
            cancelled_tokens += tokens
        else:
            failed_tokens += tokens
    return {
        "invocation_count": len(invocations),
        "usage": totals,
        "total_tokens": totals["total_tokens"],
        "accepted_tokens": accepted_tokens,
        "cancelled_tokens": cancelled_tokens,
        "failed_tokens": failed_tokens,
    }


def _invocation_accounting_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    total = int(value.get("total_tokens") or 0)
    accepted = int(value.get("accepted_tokens") or 0)
    cancelled = int(value.get("cancelled_tokens") or 0)
    failed = int(value.get("failed_tokens") or 0)
    return bool(
        int(value.get("invocation_count") or 0) >= 1
        and total > 0
        and accepted > 0
        and total == accepted + cancelled + failed
    )


def _recoverable_incomplete_result(
    payload: dict[str, Any] | None,
    *,
    requested_model: str,
    session_id: str,
) -> bool:
    if not isinstance(payload, dict):
        return False
    summary = _safe_cli_summary(
        payload,
        requested_model=requested_model,
        return_code=1,
        stdout=b"",
        stderr=b"",
    )
    return bool(
        str(payload.get("sessionId") or "") == session_id
        and str(payload.get("stopReason") or "").casefold() == "cancelled"
        and summary["model_identity_ok"] is True
        and int((summary.get("usage") or {}).get("total_tokens") or 0) > 0
    )


def _recoverable_effective_output_result(
    payload: dict[str, Any] | None,
    *,
    requested_model: str,
    session_id: str,
) -> bool:
    """Permit a final-only continuation after an attributable EndTurn contract miss."""

    if not isinstance(payload, dict):
        return False
    summary = _safe_cli_summary(
        payload,
        requested_model=requested_model,
        return_code=0,
        stdout=b"",
        stderr=b"",
    )
    return bool(
        str(payload.get("sessionId") or "") == session_id
        and str(payload.get("stopReason") or "").casefold() in COMPLETED_STOP_REASONS
        and summary["model_identity_ok"] is True
        and int((summary.get("usage") or {}).get("total_tokens") or 0) > 0
    )


def _record_operation_failure(
    *,
    root: Path,
    workflow_id: str,
    lane: dict[str, Any],
    exc: Exception,
) -> None:
    raw_manifest_path = str(lane.get("_operation_manifest_path") or "").strip()
    if raw_manifest_path:
        manifest_path = Path(raw_manifest_path)
    else:
        lane_id = str(lane.get("lane_id") or "").strip()
        prompt_sha256 = _sha256(str(lane.get("prompt") or "").strip().encode("utf-8"))
        model = str(lane.get("model") or DEFAULT_MODEL).strip()
        operation_id = _operation_id(workflow_id, lane_id, prompt_sha256, model)
        manifest_path = root / "operations" / operation_id / "manifest.json"
    manifest = _read_json(manifest_path)
    if not manifest or manifest.get("state") == "completed":
        return
    lease_token = str(lane.get("_lease_token") or "")
    if not lease_token or manifest.get("lease_token") != lease_token:
        return
    invocations = [
        dict(item) for item in manifest.get("cli_invocations", []) if isinstance(item, dict)
    ]
    manifest.update(
        {
            "state": "failed",
            "revision": int(manifest.get("revision") or 0) + 1,
            "failed_at": datetime.now(UTC).isoformat(),
            "error_type": type(exc).__name__,
            "error_sha256": _sha256(str(exc).encode("utf-8")),
            "invocation_accounting": _aggregate_invocation_usage(invocations),
        }
    )
    _write_json_atomic(manifest_path, manifest)


def _execution_prompt(task_prompt: str, intake: str, *, write: bool) -> str:
    boundary = (
        "You are a bounded Grok background worker running inside the canonical Docker "
        "LangGraph Activity. Work only on the task below. "
    )
    if write:
        boundary += "Writes are allowed only in the already-selected isolated worktree. "
    else:
        boundary += "This lane is read-only: do not modify files or external state. "
    boundary += "Return a concise, concrete result and do not claim the parent task is complete."
    material = intake[:16_000]
    return f"{boundary}\n\nTask:\n{task_prompt}\n\nCurrent intake:\n{material}"


def _cached_lane(
    manifest_path: Path,
    *,
    operation_id: str,
    requested_model: str,
    prompt_sha256: str,
    execution_prompt_sha256: str,
    operation_spec_sha256: str,
) -> dict[str, Any] | None:
    manifest = _read_json(manifest_path)
    lane = manifest.get("lane_result")
    if not isinstance(lane, dict):
        return None
    identity_ref = Path(str(lane.get("model_identity_ref") or ""))
    receipt_ref = Path(str(lane.get("cross_seam_attempt_receipt_ref") or ""))
    operation_spec_ref = Path(str(lane.get("operation_spec_ref") or ""))
    final_ref = Path(str(lane.get("final_ref") or ""))
    if not all(
        path.is_file() for path in (identity_ref, receipt_ref, operation_spec_ref, final_ref)
    ):
        return None
    try:
        identity_ref.resolve().relative_to(manifest_path.parent.resolve())
        receipt_ref.resolve().relative_to(manifest_path.parent.resolve())
        operation_spec_ref.resolve().relative_to(manifest_path.parent.resolve())
        final_ref.resolve().relative_to(manifest_path.parent.resolve())
    except ValueError:
        return None
    logical_contract = lane.get("cross_seam_logical_contract")
    attempt_receipt = lane.get("cross_seam_attempt_receipt")
    if not isinstance(logical_contract, dict) or not isinstance(attempt_receipt, dict):
        return None
    try:
        common_verdict = validate_attempt_receipt(
            logical_contract,
            attempt_receipt,
            expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
        )
    except (TypeError, ValueError):
        return None
    identity_payload = _read_json(identity_ref)
    identity_model_usage = (
        identity_payload.get("modelUsage")
        if isinstance(identity_payload.get("modelUsage"), dict)
        else {}
    )
    identity_observed_models = _observed_backend_models(identity_model_usage)
    expected_backend_models = expected_docker_grok_backend_models(requested_model)
    expected_identity_binding = grok_docker_model_identity_binding(requested_model)
    receipt_observed = attempt_receipt.get("observed")
    receipt_invocations = attempt_receipt.get("invocations")
    session_evidence = lane.get("session_model_evidence")
    if not (
        manifest.get("state") == "completed"
        and manifest.get("operation_spec_sha256") == operation_spec_sha256
        and lane.get("ok") is True
        and lane.get("execution_contract_version") == EXECUTION_CONTRACT_VERSION
        and lane.get("model_policy_id") == MODEL_POLICY_ID
        and lane.get("operation_id") == operation_id
        and lane.get("requested_model") == requested_model
        and lane.get("observed_model") == expected_backend_models[0]
        and lane.get("observed_models") == expected_backend_models
        and lane.get("observed_backend_models") == expected_backend_models
        and lane.get("model_identity_binding") == expected_identity_binding
        and lane.get("model_identity_ok") is True
        and identity_observed_models == expected_backend_models
        and isinstance(session_evidence, dict)
        and session_evidence.get("requestedModel") == requested_model
        and session_evidence.get("selectedSessionModel") == requested_model
        and session_evidence.get("observedModelId") == expected_backend_models[0]
        and session_evidence.get("modelUsageIds") == expected_backend_models
        and session_evidence.get("backendModelIds") == expected_backend_models
        and session_evidence.get("expectedBackendModelIds") == expected_backend_models
        and isinstance(receipt_observed, dict)
        and receipt_observed.get("model_id") == requested_model
        and isinstance(receipt_invocations, list)
        and bool(receipt_invocations)
        and all(
            isinstance(invocation, dict) and invocation.get("observed_model") == requested_model
            for invocation in receipt_invocations
        )
        and str(lane.get("stop_reason") or "").casefold() in COMPLETED_STOP_REASONS
        and bool(str(lane.get("result_text") or "").strip())
        and lane.get("model_capability_ok") is True
        and lane.get("rules_snapshot_ok") is True
        and lane.get("rules_projection_ok") is True
        and str(lane.get("requested_rules_snapshot_sha256") or "")
        == str(lane.get("observed_rules_snapshot_sha256") or "")
        and _invocation_accounting_valid(lane.get("invocation_accounting"))
        and lane.get("prompt_sha256") == prompt_sha256
        and lane.get("execution_prompt_sha256") == execution_prompt_sha256
        and _sha256(identity_ref.read_bytes()) == lane.get("model_identity_sha256")
        and _sha256(operation_spec_ref.read_bytes()) == lane.get("operation_spec_sha256")
        and _sha256(final_ref.read_bytes()) == lane.get("result_text_sha256")
        and final_ref.read_text(encoding="utf-8") == str(lane.get("result_text") or "")
        and lane.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and lane.get("cross_seam_attempt_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and lane.get("cross_seam_contract_sha256") == logical_contract_sha256(logical_contract)
        and common_verdict.accepted
        and _sha256(receipt_ref.read_bytes()) == lane.get("cross_seam_attempt_receipt_sha256")
    ):
        return None
    return {**lane, "replayed": True}


def _bind_replay_capability_observation(
    cached: dict[str, Any], model_capabilities: dict[str, Any]
) -> dict[str, Any]:
    """Attach the fresh preflight that authorized reuse of an old model result."""

    return {
        **cached,
        "replayed": True,
        "replay_model_capability_observation": model_capabilities,
        "replay_model_capability_binding_sha256": str(
            model_capabilities.get("binding_sha256") or ""
        ),
    }


async def _communicate_with_heartbeats(
    process: asyncio.subprocess.Process,
    *,
    operation_id: str,
    lane_id: str,
    deadline_seconds: int,
) -> tuple[bytes, bytes]:
    task = asyncio.create_task(process.communicate())
    elapsed = 0
    try:
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2)
            except TimeoutError:
                elapsed += 2
                _heartbeat(
                    {
                        "operation_id": operation_id,
                        "lane_id": lane_id,
                        "state": "grok_cli_running",
                        "elapsed_seconds": elapsed,
                    }
                )
                if elapsed >= deadline_seconds:
                    await _terminate_and_reap(process)
                    raise TimeoutError(f"Docker Grok lane exceeded {deadline_seconds}s")
        return await task
    except BaseException:
        await _terminate_and_reap(process)
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        raise


async def _terminate_and_reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


def _lane_capability_policy(lane: dict[str, Any]) -> dict[str, Any]:
    planning = str(lane.get("planning") or "auto").strip().casefold()
    subagents = str(lane.get("subagents") or "auto").strip().casefold()
    if planning not in {"auto", "off"}:
        raise ValueError("Docker Grok planning must be auto or off")
    if subagents not in {"auto", "off"}:
        raise ValueError("Docker Grok subagents must be auto or off")

    raw_external_research = lane.get("external_research", "auto")
    if isinstance(raw_external_research, bool):
        external_research = "auto" if raw_external_research else "off"
    else:
        external_research = str(raw_external_research or "auto").strip().casefold()
    if external_research not in {"auto", "off"}:
        raise ValueError("Docker Grok external_research must be auto/off or a JSON boolean")

    raw_memory = lane.get("memory", "auto")
    if isinstance(raw_memory, bool):
        memory = "auto" if raw_memory else "off"
    else:
        memory = str(raw_memory or "auto").strip().casefold()
    if memory not in {"auto", "off"}:
        raise ValueError("Docker Grok memory must be auto/off or a JSON boolean")
    return {
        "planning": planning,
        "subagents": subagents,
        "external_research": external_research,
        "memory": memory,
    }


def _lane_execution_limits(lane: dict[str, Any]) -> dict[str, int | None]:
    deadline_seconds = max(
        MIN_LANE_DEADLINE_SECONDS,
        min(
            MAX_LANE_DEADLINE_SECONDS,
            int(lane.get("deadline_seconds") or DEFAULT_LANE_DEADLINE_SECONDS),
        ),
    )
    raw_max_turns = lane.get("max_turns", "auto")
    if raw_max_turns is None or str(raw_max_turns).strip().casefold() == "auto":
        max_turns: int | None = None
    else:
        max_turns = max(1, min(MAX_LANE_TURNS, int(raw_max_turns)))
    max_recovery_continuations = max(
        0,
        min(
            MAX_RECOVERY_CONTINUATIONS,
            int(
                lane.get("max_recovery_continuations")
                if lane.get("max_recovery_continuations") is not None
                else DEFAULT_RECOVERY_CONTINUATIONS
            ),
        ),
    )
    return {
        "deadline_seconds": deadline_seconds,
        "max_turns": max_turns,
        "max_recovery_continuations": max_recovery_continuations,
    }


def _cli_capability_args(policy: dict[str, Any]) -> list[str]:
    args: list[str] = []
    if policy["planning"] == "off":
        args.append("--no-plan")
    if policy["subagents"] == "off":
        args.append("--no-subagents")
    if policy["external_research"] == "off":
        args.append("--disable-web-search")
    if policy["memory"] == "off":
        args.append("--no-memory")
    return args


def _lane_output_contract(lane: dict[str, Any]) -> dict[str, Any]:
    result_format = str(lane.get("result_format") or "text").strip().casefold()
    if result_format not in RESULT_FORMATS:
        raise ValueError(f"unsupported Docker Grok result_format: {result_format}")
    min_result_chars = max(
        1,
        min(200_000, int(lane.get("min_result_chars") or DEFAULT_MIN_RESULT_CHARS)),
    )
    raw_markers = lane.get("required_result_markers") or []
    if not isinstance(raw_markers, list):
        raise ValueError("Docker Grok required_result_markers must be a list")
    markers = tuple(
        dict.fromkeys(str(marker).strip() for marker in raw_markers if str(marker).strip())
    )
    if len(markers) > 32 or any(len(marker) > 256 for marker in markers):
        raise ValueError("Docker Grok required_result_markers exceed bounded contract")
    raw_schema = lane.get("result_json_schema")
    if result_format == "json_object":
        result_json_schema = raw_schema if isinstance(raw_schema, dict) else {"type": "object"}
        try:
            Draft202012Validator.check_schema(result_json_schema)
        except SchemaError as exc:
            raise ValueError("Docker Grok result_json_schema is invalid") from exc
    elif raw_schema is not None:
        raise ValueError("Docker Grok result_json_schema requires result_format=json_object")
    else:
        result_json_schema = None
    return {
        "result_format": result_format,
        "min_result_chars": min_result_chars,
        "required_result_markers": markers,
        "result_json_schema": result_json_schema,
        "result_json_schema_sha256": (
            _sha256(_json_bytes(result_json_schema)) if result_json_schema is not None else ""
        ),
    }


def _parse_cli_result(
    payload: dict[str, Any],
    *,
    requested_model: str,
    result_format: str = "text",
    min_result_chars: int = 1,
    required_result_markers: tuple[str, ...] = (),
    result_json_schema: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    text = str(payload.get("text") or "").strip()
    session_id = str(payload.get("sessionId") or "").strip()
    stop_reason = str(payload.get("stopReason") or "").strip()
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    model_usage = payload.get("modelUsage") if isinstance(payload.get("modelUsage"), dict) else {}
    observed = _observed_backend_models(model_usage)
    if stop_reason.casefold() not in COMPLETED_STOP_REASONS:
        raise ValueError(f"Grok CLI did not complete: stop_reason={stop_reason or 'missing'}")
    if not text or not session_id:
        raise ValueError("Grok CLI returned no attributable text/session")
    required_backend = expected_docker_grok_backend_models(requested_model)
    if observed != required_backend:
        raise ValueError(
            "Grok model identity mismatch: "
            f"requested={requested_model}, required_backend={required_backend}, "
            f"observed={observed}"
        )
    if int(usage.get("total_tokens") or 0) <= 0:
        raise ValueError("Grok CLI returned no positive token usage")
    if len(text) < min_result_chars:
        raise ValueError(
            f"Grok CLI result is not substantive: chars={len(text)}, required={min_result_chars}"
        )
    if result_format not in RESULT_FORMATS:
        raise ValueError(f"unsupported Grok result format: {result_format}")
    if result_format == "json_object":
        try:
            parsed_text = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Grok CLI result must be one JSON object") from exc
        if not isinstance(parsed_text, dict):
            raise ValueError("Grok CLI result must be one JSON object")
        try:
            Draft202012Validator(result_json_schema or {"type": "object"}).validate(parsed_text)
        except JsonSchemaValidationError as exc:
            raise ValueError("Grok CLI result failed the bound JSON schema") from exc
    missing_markers = [marker for marker in required_result_markers if marker not in text]
    if missing_markers:
        raise ValueError(f"Grok CLI result is missing required markers: {missing_markers}")
    return text, session_id, usage, model_usage


async def _execute_lane_locked(
    *,
    root: Path,
    workflow_id: str,
    lane: dict[str, Any],
    intake: str,
) -> dict[str, Any]:
    lane_id = str(lane.get("lane_id") or "").strip()
    task_prompt = str(lane.get("prompt") or "").strip()
    model = str(lane.get("model") or "").strip()
    mode = str(lane.get("mode") or "audit").strip()
    write = lane.get("write") is True
    if not lane_id or not task_prompt:
        raise ValueError("Docker Grok lane requires lane_id and prompt")
    if not model:
        raise ValueError("Docker Grok lane requires an explicit supervisor-selected model")
    if model not in ALLOWED_MODELS:
        raise ValueError(f"unsupported Docker Grok model: {model}")
    prompt_sha256 = _sha256(task_prompt.encode("utf-8"))
    grok_bin = Path(os.environ.get("XINAO_GROK_BIN", "/usr/local/bin/grok"))
    grok_home = Path(os.environ.get("XINAO_GROK_HOME", "/grok-home"))
    auth_handle = grok_home / ".grok" / "auth.json"
    if not grok_bin.is_file() or not auth_handle.is_file():
        raise DockerGrokPermanentError(
            "Docker Grok CLI or cached grok.com login handle is unavailable"
        )
    env, profile_dir = _grok_cli_environment(grok_home)
    model_capabilities = await _discover_model_capabilities(
        grok_bin,
        env=env,
        profile_dir=profile_dir,
        requested_model=model,
    )
    requested_rules_snapshot = _rules_snapshot()
    cwd = _container_cwd(lane.get("cwd"), write=write)
    context_inspect = await _inspect_grok_context(grok_bin, env=env, cwd=cwd)
    execution_limits = _lane_execution_limits(lane)
    deadline_seconds = execution_limits["deadline_seconds"]
    max_turns = execution_limits["max_turns"]
    max_recovery_continuations = execution_limits["max_recovery_continuations"]
    capability_policy = _lane_capability_policy(lane)
    output_contract = _lane_output_contract(lane)
    execution_prompt = _execution_prompt(task_prompt, intake, write=write)
    execution_prompt_sha256 = _sha256(execution_prompt.encode("utf-8"))
    correlation_id = str(lane.get("correlation_id") or "")
    parent_operation_id = str(lane.get("parent_operation_id") or "")
    contract_id = str(lane.get("contract_id") or "")
    allowed_tools = tuple(sorted(map(str, lane.get("allowed_tools") or [])))
    operation_id = _operation_id(
        workflow_id,
        lane_id,
        prompt_sha256,
        model,
        execution_prompt_sha256=execution_prompt_sha256,
        mode=mode,
        cwd=str(cwd),
        write=write,
        max_turns=max_turns,
        deadline_seconds=deadline_seconds,
        correlation_id=correlation_id,
        parent_operation_id=parent_operation_id,
        contract_id=contract_id,
        allowed_tools=allowed_tools,
        planning=str(capability_policy["planning"]),
        subagents=str(capability_policy["subagents"]),
        external_research=str(capability_policy["external_research"]),
        memory=str(capability_policy["memory"]),
        model_capability_sha256=str(model_capabilities["binding_sha256"]),
        rules_snapshot_sha256=str(requested_rules_snapshot["sha256"]),
        context_inspect_sha256=str(context_inspect["sha256"]),
        max_recovery_continuations=max_recovery_continuations,
        result_format=str(output_contract["result_format"]),
        result_json_schema_sha256=str(output_contract["result_json_schema_sha256"]),
        min_result_chars=int(output_contract["min_result_chars"]),
        required_result_markers=tuple(output_contract["required_result_markers"]),
    )
    common_output_contract_sha256 = _sha256(
        _json_bytes(
            {
                "result_format": output_contract["result_format"],
                "result_json_schema_sha256": output_contract["result_json_schema_sha256"],
                "min_result_chars": output_contract["min_result_chars"],
                "required_result_markers": list(output_contract["required_result_markers"]),
            }
        )
    )
    logical_contract = build_grok_logical_contract(
        workflow_id=workflow_id,
        lane_id=lane_id,
        operation_id=operation_id,
        correlation_id=correlation_id,
        parent_operation_id=parent_operation_id,
        task_contract_ref=contract_id,
        provider_id=PROVIDER_ID,
        model_id=model,
        execution_prompt_sha256=execution_prompt_sha256,
        context_sha256=str(context_inspect["sha256"]),
        rules_sha256=str(requested_rules_snapshot["sha256"]),
        output_contract_sha256=common_output_contract_sha256,
        capability_policy=capability_policy,
        allowed_tools=allowed_tools,
        cli_policy_version=CLI_POLICY_VERSION,
        write=write,
        deadline_seconds=deadline_seconds,
    )
    cross_seam_contract_sha256 = logical_contract_sha256(logical_contract)
    operation_root = root / "operations" / operation_id
    operation_manifest = operation_root / "manifest.json"
    operation_spec_path = operation_root / "operation-spec.json"
    logical_contract_path = operation_root / "logical_contract.json"
    logical_contract_artifact_sha256 = _sha256(_json_bytes(logical_contract))
    lane["_operation_manifest_path"] = str(operation_manifest)
    requested_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, operation_id))
    operation_spec = {
        "schema_version": SCHEMA_VERSION,
        "execution_contract_version": EXECUTION_CONTRACT_VERSION,
        "cli_policy_version": CLI_POLICY_VERSION,
        "operation_id": operation_id,
        "workflow_id": workflow_id,
        "lane_id": lane_id,
        "mode": mode,
        "model": model,
        "prompt_sha256": prompt_sha256,
        "execution_prompt_sha256": execution_prompt_sha256,
        "cwd": str(cwd),
        "write": write,
        "max_turns": max_turns,
        "deadline_seconds": deadline_seconds,
        "requested_session_id": requested_session_id,
        "correlation_id": correlation_id,
        "parent_operation_id": parent_operation_id,
        "contract_id": contract_id,
        "allowed_tools": list(allowed_tools),
        "planning": capability_policy["planning"],
        "subagents": capability_policy["subagents"],
        "external_research": capability_policy["external_research"],
        "memory": capability_policy["memory"],
        "model_capability_binding": model_capabilities["binding"],
        "requested_rules_snapshot": requested_rules_snapshot,
        "context_inspect": context_inspect,
        "max_recovery_continuations": max_recovery_continuations,
        "result_format": output_contract["result_format"],
        "result_json_schema": output_contract["result_json_schema"],
        "result_json_schema_sha256": output_contract["result_json_schema_sha256"],
        "min_result_chars": output_contract["min_result_chars"],
        "required_result_markers": list(output_contract["required_result_markers"]),
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_contract_sha256": cross_seam_contract_sha256,
        "cross_seam_logical_contract": logical_contract,
        "cross_seam_logical_contract_ref": str(logical_contract_path),
        "cross_seam_logical_contract_artifact_sha256": logical_contract_artifact_sha256,
    }
    operation_spec_sha256 = _sha256(_json_bytes(operation_spec))
    if (
        _write_json_atomic(logical_contract_path, logical_contract)
        != logical_contract_artifact_sha256
    ):
        raise RuntimeError("cross-seam logical contract artifact hash drifted")
    if _write_json_atomic(operation_spec_path, operation_spec) != operation_spec_sha256:
        raise RuntimeError("Docker Grok operation-spec artifact hash drifted")
    cached = _cached_lane(
        operation_manifest,
        operation_id=operation_id,
        requested_model=model,
        prompt_sha256=prompt_sha256,
        execution_prompt_sha256=execution_prompt_sha256,
        operation_spec_sha256=operation_spec_sha256,
    )
    if cached is not None:
        return _bind_replay_capability_observation(cached, model_capabilities)
    previous_manifest = _read_json(operation_manifest)
    prior_invocation_evidence = [
        dict(item)
        for item in previous_manifest.get("cli_invocations", [])
        if isinstance(item, dict)
    ]
    owner = _activity_owner()
    attempt = (
        int(owner.get("activity_attempt") or 0) or int(previous_manifest.get("attempt") or 0) + 1
    )
    lease_token = str(lane.get("_lease_token") or "")
    _write_json_atomic(
        operation_manifest,
        {
            **operation_spec,
            "operation_spec_sha256": operation_spec_sha256,
            "model_capability_observation": model_capabilities,
            "state": "running",
            "revision": int(previous_manifest.get("revision") or 0) + 1,
            "lease_token": lease_token,
            "attempt": attempt,
            "started_at": datetime.now(UTC).isoformat(),
            "container_id": socket.gethostname(),
            "pid": os.getpid(),
            "cli_invocations": prior_invocation_evidence,
            **owner,
        },
    )

    loop = asyncio.get_running_loop()
    expires_at = loop.time() + deadline_seconds
    resume_lock_retries = 0
    recovery_continuations = 0
    session_recreations = 0
    active_session_id = requested_session_id
    resume_session = attempt > 1 and _session_materialized(grok_home, requested_session_id)
    if write and attempt > 1:
        raise DockerGrokPermanentError(
            "automatic retry/resume is disabled for write-enabled Docker Grok lanes"
        )
    active_prompt = _recovery_prompt() if resume_session else execution_prompt
    invocation_evidence: list[dict[str, Any]] = prior_invocation_evidence
    cli_payload: dict[str, Any] | None = None
    stderr = b""
    while True:
        if loop.time() >= expires_at:
            raise TimeoutError(f"Docker Grok lane exceeded {deadline_seconds}s")
        args = [
            str(grok_bin),
            "--no-auto-update",
            "-p",
            active_prompt,
            "-m",
            model,
            "--output-format",
            "json",
            "--cwd",
            str(cwd),
            *_session_cli_args(
                active_session_id,
                attempt=attempt,
                session_materialized=resume_session,
                resume=resume_session,
            ),
            *_cli_capability_args(capability_policy),
            "--rules",
            _rules_cli_text(requested_rules_snapshot),
        ]
        if max_turns is not None:
            args.extend(["--max-turns", str(max_turns)])
        if output_contract["result_json_schema"] is not None:
            args.extend(
                [
                    "--json-schema",
                    json.dumps(
                        output_contract["result_json_schema"],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ]
            )
        if write:
            args.append("--always-approve")
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        remaining_seconds = max(1, int(expires_at - loop.time()))
        stdout, stderr = await _communicate_with_heartbeats(
            process,
            operation_id=operation_id,
            lane_id=lane_id,
            deadline_seconds=remaining_seconds,
        )
        cli_payload = _decode_cli_payload(stdout)
        summary = _safe_cli_summary(
            cli_payload,
            requested_model=model,
            return_code=int(process.returncode or 0),
            stdout=stdout,
            stderr=stderr,
        )
        summary.update(
            {
                "invocation": len(invocation_evidence) + 1,
                "session_mode": "resume" if resume_session else "new",
                "effective_output_accepted": False,
            }
        )
        invocation_evidence.append(summary)
        observed_manifest = _read_json(operation_manifest)
        if observed_manifest.get("lease_token") != lease_token:
            raise DockerGrokTransientError("Docker Grok operation lease token drifted")
        observed_manifest["revision"] = int(observed_manifest.get("revision") or 0) + 1
        observed_manifest["cli_invocations"] = invocation_evidence
        observed_manifest["active_session_id"] = active_session_id
        _write_json_atomic(operation_manifest, observed_manifest)
        if (
            process.returncode == 0
            and isinstance(cli_payload, dict)
            and str(cli_payload.get("stopReason") or "").casefold() in COMPLETED_STOP_REASONS
        ):
            try:
                _parse_cli_result(
                    cli_payload,
                    requested_model=model,
                    result_format=str(output_contract["result_format"]),
                    min_result_chars=int(output_contract["min_result_chars"]),
                    required_result_markers=tuple(output_contract["required_result_markers"]),
                    result_json_schema=output_contract["result_json_schema"],
                )
            except ValueError as exc:
                summary["effective_output_error_type"] = type(exc).__name__
                summary["effective_output_error_sha256"] = _sha256(str(exc).encode("utf-8"))
                rejected_manifest = _read_json(operation_manifest)
                if rejected_manifest.get("lease_token") != lease_token:
                    raise DockerGrokTransientError(
                        "Docker Grok operation lease token drifted"
                    ) from exc
                rejected_manifest["revision"] = int(rejected_manifest.get("revision") or 0) + 1
                rejected_manifest["cli_invocations"] = invocation_evidence
                rejected_manifest["active_session_id"] = active_session_id
                _write_json_atomic(operation_manifest, rejected_manifest)
                if (
                    not write
                    and recovery_continuations < max_recovery_continuations
                    and _recoverable_effective_output_result(
                        cli_payload,
                        requested_model=model,
                        session_id=active_session_id,
                    )
                ):
                    recovery_continuations += 1
                    resume_session = True
                    active_session_id = str(cli_payload.get("sessionId") or active_session_id)
                    active_prompt = _output_contract_recovery_prompt(
                        result_format=str(output_contract["result_format"]),
                        result_json_schema=output_contract["result_json_schema"],
                        required_result_markers=tuple(output_contract["required_result_markers"]),
                    )
                    continue
                raise
            summary["effective_output_accepted"] = True
            accepted_manifest = _read_json(operation_manifest)
            if accepted_manifest.get("lease_token") != lease_token:
                raise DockerGrokTransientError("Docker Grok operation lease token drifted")
            accepted_manifest["revision"] = int(accepted_manifest.get("revision") or 0) + 1
            accepted_manifest["cli_invocations"] = invocation_evidence
            accepted_manifest["active_session_id"] = active_session_id
            _write_json_atomic(operation_manifest, accepted_manifest)
            break
        failure_kind = str(summary["failure_kind"])
        if not _retryable_session_lock(
            stderr,
            attempt=attempt,
            retries=resume_lock_retries,
        ):
            if (
                recovery_continuations < max_recovery_continuations
                and _recoverable_incomplete_result(
                    cli_payload,
                    requested_model=model,
                    session_id=active_session_id,
                )
            ):
                recovery_continuations += 1
                resume_session = True
                active_session_id = str(cli_payload.get("sessionId") or active_session_id)
                active_prompt = _recovery_prompt(final_only=True)
                continue
            if failure_kind == "session_not_found" and session_recreations < 1 and not write:
                session_recreations += 1
                active_session_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{operation_id}:replacement")
                )
                resume_session = False
                active_prompt = execution_prompt
                continue
            error = (
                "Docker Grok CLI failed "
                f"kind={failure_kind}, rc={process.returncode}, "
                f"stdout_sha256={_sha256(stdout)}, stderr_sha256={_sha256(stderr)}"
            )
            if failure_kind == "authentication":
                raise DockerGrokPermanentError(error)
            if failure_kind == "session_not_found" and write:
                raise DockerGrokPermanentError(error)
            raise DockerGrokTransientError(error)
        resume_lock_retries += 1
        backoff_seconds = 10 * resume_lock_retries
        waiting_manifest = _read_json(operation_manifest)
        if waiting_manifest.get("lease_token") != lease_token:
            raise DockerGrokTransientError("Docker Grok operation lease token drifted")
        waiting_manifest.update(
            {
                "state": "waiting_for_session_release",
                "revision": int(waiting_manifest.get("revision") or 0) + 1,
                "resume_lock_retries": resume_lock_retries,
                "last_stderr_sha256": _sha256(stderr),
            }
        )
        _write_json_atomic(operation_manifest, waiting_manifest)
        backoff_until = min(expires_at, loop.time() + backoff_seconds)
        while loop.time() < backoff_until:
            _heartbeat(
                {
                    "operation_id": operation_id,
                    "lane_id": lane_id,
                    "state": "waiting_for_session_release",
                    "resume_lock_retries": resume_lock_retries,
                }
            )
            await asyncio.sleep(min(2, max(0, backoff_until - loop.time())))
        if loop.time() >= expires_at:
            raise TimeoutError(f"Docker Grok session release exceeded {deadline_seconds}s")
    if not isinstance(cli_payload, dict):
        raise ValueError("Docker Grok CLI JSON must be an object")
    result_text, session_id, usage, model_usage = _parse_cli_result(
        cli_payload,
        requested_model=model,
        result_format=str(output_contract["result_format"]),
        min_result_chars=int(output_contract["min_result_chars"]),
        required_result_markers=tuple(output_contract["required_result_markers"]),
        result_json_schema=output_contract["result_json_schema"],
    )
    observed_backend_models = _observed_backend_models(model_usage)
    observed_model = observed_backend_models[0]
    model_identity_binding = grok_docker_model_identity_binding(model)
    observed_rules_snapshot = _rules_snapshot()
    if observed_rules_snapshot["sha256"] != requested_rules_snapshot["sha256"]:
        raise DockerGrokTransientError("Grok shared rules changed during the lane execution")
    invocation_accounting = _aggregate_invocation_usage(invocation_evidence)
    identity_path = operation_root / "cli_result.json"
    identity_sha256 = _write_json_atomic(identity_path, cli_payload)
    session_evidence = {
        "source": "grok_cli_json_modelUsage",
        "requestedModel": model,
        "selectedSessionModel": model,
        "observedModelId": observed_model,
        "modelUsageIds": observed_backend_models,
        "availableModelIds": list(model_capabilities["merged_cli_model_ids"]),
        "backendModelIds": observed_backend_models,
        "expectedBackendModelIds": list(
            model_capabilities["binding"]["expected_backend_model_ids"]
        ),
        "capabilityBindingSha256": model_capabilities["binding_sha256"],
        "backendSessionId": session_id,
        "requestId": str(cli_payload.get("requestId") or ""),
    }
    result_text_sha256 = _sha256(result_text.encode("utf-8"))
    final_path = operation_root / "final.txt"
    if _write_bytes_atomic(final_path, result_text.encode("utf-8")) != result_text_sha256:
        raise RuntimeError("Docker Grok final artifact hash drifted")
    attempt_receipt = build_grok_attempt_receipt(
        logical_contract=logical_contract,
        attempt=attempt,
        invocation_evidence=invocation_evidence,
        invocation_accounting=invocation_accounting,
        observed_model=model,
        observed_rules_sha256=str(observed_rules_snapshot["sha256"]),
        runtime_version=str(model_capabilities["cli_version"]),
        execution_location="docker:houtai-gongren",
        executor_id=socket.gethostname(),
        result_format=str(output_contract["result_format"]),
        result_text_sha256=result_text_sha256,
        result_text_chars=len(result_text),
        output_schema_sha256=common_output_contract_sha256,
        schema_valid=True,
        markers_ok=True,
        substantive=len(result_text) >= int(output_contract["min_result_chars"]),
        stop_reason=str(cli_payload.get("stopReason") or ""),
        workflow_id=workflow_id,
        lane_id=lane_id,
        parent_operation_id=parent_operation_id,
        correlation_id=correlation_id,
        session_id=session_id,
        provider_contract_version=EXECUTION_CONTRACT_VERSION,
        provider_evidence_ref=str(identity_path),
        provider_evidence_sha256=identity_sha256,
        provider_evidence_valid=True,
        replayed=False,
    )
    attempt_receipt_path = operation_root / "attempt_receipt.json"
    attempt_receipt_sha256 = _write_json_atomic(attempt_receipt_path, attempt_receipt)
    lane_result = {
        "ok": True,
        "execution_contract_version": EXECUTION_CONTRACT_VERSION,
        "policy_id": SCHEMA_VERSION,
        "model_policy_id": MODEL_POLICY_ID,
        "provider_id": PROVIDER_ID,
        "workflow_id": workflow_id,
        "lane_id": lane_id,
        "mode": mode,
        "model": model,
        "requested_model": model,
        "observed_model": observed_model,
        "observed_models": observed_backend_models,
        "model_usage": model_usage,
        "observed_backend_models": observed_backend_models,
        "model_identity_binding": model_identity_binding,
        "session_model_evidence": session_evidence,
        "session_model_evidence_valid": True,
        "model_identity_ok": True,
        "agent_session_id": session_id,
        "model_identity_ref": str(identity_path),
        "model_identity_sha256": identity_sha256,
        "supervisor_worker_decision_sha256": str(
            lane.get("supervisor_worker_decision_sha256") or ""
        ),
        "model_route_role": (
            ESCALATION_ROUTE_ROLE if model == ESCALATION_MODEL else DEFAULT_ROUTE_ROLE
        ),
        "is_escalated": model == ESCALATION_MODEL,
        "escalation_reason": str(lane.get("escalation_reason") or ""),
        "prompt_sha256": prompt_sha256,
        "execution_prompt_sha256": execution_prompt_sha256,
        "operation_spec_sha256": operation_spec_sha256,
        "operation_spec_ref": str(operation_spec_path),
        "contract_id": contract_id,
        "write": write,
        "allowed_tools": list(allowed_tools),
        "planning": capability_policy["planning"],
        "subagents": capability_policy["subagents"],
        "external_research": capability_policy["external_research"],
        "memory": capability_policy["memory"],
        "model_capabilities": model_capabilities,
        "model_capability_ok": model_capabilities["requested_model_available"] is True,
        "requested_rules_snapshot_sha256": requested_rules_snapshot["sha256"],
        "observed_rules_snapshot_sha256": observed_rules_snapshot["sha256"],
        "rules_snapshot_ok": True,
        "context_inspect": context_inspect,
        "rules_projection_ok": (
            context_inspect["root_agents_discovered"] is True
            or bool(requested_rules_snapshot["sha256"])
        ),
        "max_recovery_continuations": max_recovery_continuations,
        "result_format": output_contract["result_format"],
        "result_json_schema": output_contract["result_json_schema"],
        "result_json_schema_sha256": output_contract["result_json_schema_sha256"],
        "min_result_chars": output_contract["min_result_chars"],
        "required_result_markers": list(output_contract["required_result_markers"]),
        "permission_mode": "approve-all" if write else "read_only_single_turn",
        "operation_id": operation_id,
        "operation_state": "completed",
        "activity_attempt": attempt,
        "resume_lock_retries": resume_lock_retries,
        "recovery_continuations": recovery_continuations,
        "session_recreations": session_recreations,
        "result_text": result_text,
        "result_text_sha256": result_text_sha256,
        "result_text_chars": len(result_text),
        "final_ref": str(final_path),
        "stop_reason": str(cli_payload.get("stopReason") or ""),
        "usage": usage,
        "invocation_accounting": invocation_accounting,
        "artifacts": [
            {
                "name": "operation-spec.json",
                "uri": str(operation_spec_path),
                "sha256": operation_spec_sha256,
                "size_bytes": operation_spec_path.stat().st_size,
                "operation_id": operation_id,
            },
            {
                "name": "final.txt",
                "uri": str(final_path),
                "sha256": result_text_sha256,
                "size_bytes": final_path.stat().st_size,
                "operation_id": operation_id,
            },
            {
                "name": "logical_contract.json",
                "uri": str(logical_contract_path),
                "sha256": logical_contract_artifact_sha256,
                "size_bytes": logical_contract_path.stat().st_size,
                "operation_id": operation_id,
            },
            {
                "name": "attempt_receipt.json",
                "uri": str(attempt_receipt_path),
                "sha256": attempt_receipt_sha256,
                "size_bytes": attempt_receipt_path.stat().st_size,
                "operation_id": operation_id,
            },
            {
                "name": "cli_result.json",
                "uri": str(identity_path),
                "sha256": identity_sha256,
                "size_bytes": identity_path.stat().st_size,
                "operation_id": operation_id,
            },
        ],
        "replayed": False,
        "execution_location": "docker:houtai-gongren",
        "container_id": socket.gethostname(),
        "auth_mode": "cached_grok_com_profile",
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_contract_sha256": cross_seam_contract_sha256,
        "cross_seam_logical_contract": logical_contract,
        "cross_seam_logical_contract_ref": str(logical_contract_path),
        "cross_seam_logical_contract_artifact_sha256": logical_contract_artifact_sha256,
        "cross_seam_attempt_receipt": attempt_receipt,
        "cross_seam_attempt_receipt_ref": str(attempt_receipt_path),
        "cross_seam_attempt_receipt_sha256": attempt_receipt_sha256,
    }
    if lane.get("correlation_id"):
        lane_result["correlation_id"] = str(lane["correlation_id"])
    if lane.get("parent_operation_id"):
        lane_result["parent_operation_id"] = str(lane["parent_operation_id"])
    _write_json_atomic(
        operation_manifest,
        {
            **operation_spec,
            "operation_spec_sha256": operation_spec_sha256,
            "model_capability_observation": model_capabilities,
            "state": "completed",
            "revision": int(_read_json(operation_manifest).get("revision") or 0) + 1,
            "lease_token": lease_token,
            "attempt": attempt,
            "completed_at": datetime.now(UTC).isoformat(),
            "container_id": socket.gethostname(),
            "stderr_sha256": _sha256(stderr),
            "cli_invocations": invocation_evidence,
            "invocation_accounting": invocation_accounting,
            "lane_result": lane_result,
        },
    )
    return lane_result


async def _execute_lane(
    *,
    root: Path,
    workflow_id: str,
    lane: dict[str, Any],
    intake: str,
) -> dict[str, Any]:
    """Fence one workflow/lane across Activity attempts and container generations."""

    lane_id = str(lane.get("lane_id") or "").strip()
    if not lane_id:
        raise ValueError("Docker Grok lane requires lane_id")
    lease_path = root / "leases" / f"{_safe(lane_id)}.lock"
    lease_token = uuid.uuid4().hex
    lane["_lease_token"] = lease_token
    lease = await _acquire_operation_lease(
        lease_path,
        lane_id=lane_id,
        timeout_seconds=max(30, min(240, int(lane.get("deadline_seconds") or 240))),
    )
    try:
        try:
            return await _execute_lane_locked(
                root=root,
                workflow_id=workflow_id,
                lane=lane,
                intake=intake,
            )
        except Exception as exc:
            _record_operation_failure(
                root=root,
                workflow_id=workflow_id,
                lane=lane,
                exc=exc,
            )
            raise
    finally:
        lease.release()


async def run_docker_native_grok_fanin(
    *,
    runtime_root: Path,
    workflow_id: str,
    input_path: Path,
    content_md: str,
    ready_frontier: object = None,
    serial_reason: str = "",
    correlation_id: str = "",
    parent_operation_id: str = "",
    supervisor_worker_decision: object = None,
    supervisor_selection_required: bool = False,
) -> dict[str, Any]:
    """Execute the caller-derived frontier in Docker and persist a v2 fan-in."""

    if not docker_native_grok_enabled():
        return {}
    if not workflow_id:
        raise ValueError("Docker-native Grok fan-in requires workflow_id")
    input_path = input_path.resolve()
    input_raw = input_path.read_bytes()
    raw_lanes = ready_frontier if isinstance(ready_frontier, list) else []
    lanes = [dict(item) for item in raw_lanes if isinstance(item, dict)]
    if not lanes:
        raise ValueError(
            "Docker-native Grok fan-in requires an explicit positive-benefit ready_frontier"
        )
    if len(lanes) > 8:
        raise ValueError("Docker-native Grok frontier exceeds bounded width 8")
    seen: set[str] = set()
    for index, lane in enumerate(lanes):
        lane_id = str(lane.get("lane_id") or f"lane-{index}").strip()
        if lane_id in seen:
            raise ValueError(f"duplicate Docker Grok lane_id: {lane_id}")
        seen.add(lane_id)
        lane["lane_id"] = lane_id
        if not str(lane.get("model") or "").strip():
            raise ValueError(
                f"Docker Grok lane {lane_id!r} requires an explicit supervisor-selected model"
            )
        lane.setdefault("mode", "audit")
        lane.setdefault("write", False)
        if not str(lane.get("cwd") or "").strip():
            raise ValueError(
                f"Docker Grok lane {lane_id!r} requires an explicit supervisor-selected cwd"
            )
        if correlation_id:
            lane.setdefault("correlation_id", correlation_id)
        if parent_operation_id:
            lane.setdefault("parent_operation_id", parent_operation_id)
    models = sorted({str(item.get("model") or "") for item in lanes})
    if len(models) != 1 or models[0] not in ALLOWED_MODELS:
        raise ValueError("one Docker Grok frontier must use one admitted model")
    decision_sha256 = ""
    if supervisor_selection_required or isinstance(supervisor_worker_decision, dict):
        if not isinstance(supervisor_worker_decision, dict):
            raise ValueError("Docker Grok execution requires a supervisor selection receipt")
        selected = supervisor_worker_decision.get("selected_candidate")
        declared_sha256 = str(supervisor_worker_decision.get("decision_sha256") or "")
        hash_input = dict(supervisor_worker_decision)
        hash_input.pop("decision_sha256", None)
        observed_sha256 = hashlib.sha256(
            json.dumps(
                hash_input,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if not (
            supervisor_worker_decision.get("decision") == "selected"
            and isinstance(selected, dict)
            and selected.get("provider_id") == PROVIDER_ID
            and selected.get("profile_ref") == SUPERVISOR_PROFILE_REF
            and selected.get("transport_id") == SUPERVISOR_DURABLE_TRANSPORT_ID
            and selected.get("model_id") == models[0]
            and declared_sha256 == observed_sha256
        ):
            raise ValueError("Docker Grok supervisor selection receipt is invalid")
        decision_sha256 = declared_sha256
        for lane in lanes:
            lane["supervisor_worker_decision_sha256"] = decision_sha256

    root = runtime_root.resolve() / "state" / "grok_docker_native" / _safe(workflow_id)
    root.mkdir(parents=True, exist_ok=True)

    async def run_one(lane: dict[str, Any]) -> dict[str, Any]:
        try:
            return await _execute_lane(
                root=root,
                workflow_id=workflow_id,
                lane=lane,
                intake=content_md,
            )
        except DockerGrokTransientError:
            raise
        except Exception as exc:
            manifest_path = Path(str(lane.get("_operation_manifest_path") or ""))
            failed_manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
            raw_invocations = [
                dict(item)
                for item in failed_manifest.get("cli_invocations", [])
                if isinstance(item, dict)
            ]
            invocation_accounting = failed_manifest.get("invocation_accounting")
            if not isinstance(invocation_accounting, dict):
                invocation_accounting = _aggregate_invocation_usage(raw_invocations)
            observed_backend_models = sorted(
                {
                    str(observed)
                    for invocation in raw_invocations
                    for observed in (
                        invocation.get("observed_models")
                        if isinstance(invocation.get("observed_models"), list)
                        else []
                    )
                    if str(observed or "")
                }
            )
            return {
                "ok": False,
                "provider_id": PROVIDER_ID,
                "workflow_id": workflow_id,
                "lane_id": str(lane.get("lane_id") or ""),
                "mode": str(lane.get("mode") or ""),
                "model": str(lane.get("model") or ""),
                "requested_model": str(lane.get("model") or ""),
                "observed_model": (
                    observed_backend_models[0] if len(observed_backend_models) == 1 else ""
                ),
                "observed_models": observed_backend_models,
                "observed_backend_models": observed_backend_models,
                "model_identity_ok": False,
                "supervisor_worker_decision_sha256": str(
                    lane.get("supervisor_worker_decision_sha256") or ""
                ),
                "operation_state": "failed",
                "named_blocker": f"{type(exc).__name__}:{str(exc)[:240]}",
                "invocation_accounting": invocation_accounting,
                "execution_location": "docker:houtai-gongren",
            }

    gathered = list(
        await asyncio.gather(*(run_one(lane) for lane in lanes), return_exceptions=True)
    )
    transient = next(
        (item for item in gathered if isinstance(item, DockerGrokTransientError)),
        None,
    )
    if transient is not None:
        raise transient
    unexpected = next((item for item in gathered if isinstance(item, BaseException)), None)
    if unexpected is not None:
        raise DockerGrokTransientError(
            f"unexpected Docker Grok lane error type={type(unexpected).__name__}"
        ) from unexpected
    results = [item for item in gathered if isinstance(item, dict)]
    model = models[0]
    expected_backend_models = expected_docker_grok_backend_models(model)
    model_identity_binding = grok_docker_model_identity_binding(model)
    successful = [
        item
        for item in results
        if item.get("ok") is True
        and item.get("model_identity_ok") is True
        and item.get("observed_model") == expected_backend_models[0]
        and item.get("observed_backend_models") == expected_backend_models
        and item.get("model_identity_binding") == model_identity_binding
    ]
    fanin_root = root / "fanin"
    fanin_root.mkdir(parents=True, exist_ok=True)
    manifest_path = fanin_root / "manifest.json"
    intake_path = fanin_root / "grok_fanin_input.md"
    sections = [
        f"<!-- {FANIN_SENTINEL} -->",
        f"<!-- grok_manifest_path={manifest_path} -->",
        content_md.rstrip(),
        "",
        "# Docker-native Grok fan-in",
    ]
    for item in successful:
        sections.extend(
            [
                "",
                f"## {item.get('lane_id')} ({item.get('mode')})",
                "",
                str(item.get("result_text") or "").rstrip(),
            ]
        )
    intake_bytes = ("\n".join(sections).rstrip() + "\n").encode("utf-8")
    intake_path.write_bytes(intake_bytes)
    common_receipt_bindings: list[dict[str, str]] = []
    for item in successful:
        logical_contract = item.get("cross_seam_logical_contract")
        attempt_receipt = item.get("cross_seam_attempt_receipt")
        if not isinstance(logical_contract, dict) or not isinstance(attempt_receipt, dict):
            raise ValueError("successful Grok lane is missing the common execution receipt")
        verdict = validate_attempt_receipt(
            logical_contract,
            attempt_receipt,
            expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
        )
        if not verdict.accepted:
            raise ValueError(
                "successful Grok lane failed common receipt validation: "
                + ",".join(verdict.reason_codes)
            )
        common_receipt_bindings.append(
            {
                "lane_id": str(item.get("lane_id") or ""),
                "contract_sha256": logical_contract_sha256(logical_contract),
                "attempt_receipt_sha256": str(item.get("cross_seam_attempt_receipt_sha256") or ""),
            }
        )
    common_receipt_set_sha256 = _sha256(canonical_json_bytes(common_receipt_bindings))
    observed_backend_models = sorted(
        {
            str(observed)
            for item in results
            for observed in (
                item.get("observed_backend_models")
                if isinstance(item.get("observed_backend_models"), list)
                else [item.get("observed_model")]
            )
            if str(observed or "")
        }
    )
    full_success = (
        len(successful) == len(results)
        and bool(results)
        and observed_backend_models == expected_backend_models
    )
    observed_model = observed_backend_models[0] if len(observed_backend_models) == 1 else ""
    observed_models = observed_backend_models
    lane_accounting = [
        item.get("invocation_accounting")
        for item in results
        if isinstance(item.get("invocation_accounting"), dict)
    ]
    token_accounting = {
        "invocation_count": sum(int(item.get("invocation_count") or 0) for item in lane_accounting),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in lane_accounting),
        "accepted_tokens": sum(int(item.get("accepted_tokens") or 0) for item in lane_accounting),
        "cancelled_tokens": sum(int(item.get("cancelled_tokens") or 0) for item in lane_accounting),
        "failed_tokens": sum(int(item.get("failed_tokens") or 0) for item in lane_accounting),
        "activity_attempt_count": sum(
            max(1, int(item.get("activity_attempt") or 1)) for item in results
        ),
    }
    token_accounting["all_invocations_total"] = token_accounting["total_tokens"]
    token_accounting["accepted_total"] = token_accounting["accepted_tokens"]
    token_accounting["cancelled_total"] = token_accounting["cancelled_tokens"]
    token_accounting["failed_total"] = token_accounting["failed_tokens"]
    manifest = {
        "schema_version": FANIN_SCHEMA_VERSION,
        "execution_contract_version": EXECUTION_CONTRACT_VERSION,
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_receipt_bindings": common_receipt_bindings,
        "cross_seam_receipt_set_sha256": common_receipt_set_sha256,
        "sentinel": FANIN_SENTINEL,
        "policy_id": SCHEMA_VERSION,
        "model_policy_id": MODEL_POLICY_ID,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": [model],
        "observed_model": observed_model,
        "observed_models": observed_models,
        "observed_backend_models": observed_backend_models,
        "model_identity_binding": model_identity_binding,
        "model_identity_ok": full_success
        and all(item.get("model_identity_ok") is True for item in successful),
        "workflow_id": workflow_id,
        "ok": full_success,
        "ready_width": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "serial_reason": serial_reason or "docker_native_single_intake",
        "lanes": results,
        "base_intake_path": str(input_path),
        "intake_path": str(input_path),
        "intake_sha256": _sha256(input_raw),
        "fanin_artifact_path": str(intake_path),
        "fanin_artifact_sha256": _sha256(intake_bytes),
        "generated_at": datetime.now(UTC).isoformat(),
        "execution_location": "docker:houtai-gongren",
        "container_id": socket.gethostname(),
        "token_accounting": token_accounting,
        "completion_claim_allowed": False,
        "supervisor_worker_decision_sha256": decision_sha256,
    }
    if correlation_id:
        manifest["correlation_id"] = correlation_id
    if parent_operation_id:
        manifest["parent_operation_id"] = parent_operation_id
    manifest_sha256 = _write_json_atomic(manifest_path, manifest)
    fanin = {
        "ok": full_success,
        "provider_id": PROVIDER_ID,
        "model": model,
        "models": [model],
        "observed_model": observed_model,
        "observed_models": observed_models,
        "observed_backend_models": observed_backend_models,
        "model_identity_binding": model_identity_binding,
        "model_policy_id": MODEL_POLICY_ID,
        "model_identity_ok": manifest["model_identity_ok"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "lane_count": len(results),
        "ready_width": len(results),
        "succeeded": len(successful),
        "failed": len(results) - len(successful),
        "token_accounting": token_accounting,
        "cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "cross_seam_attempt_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "cross_seam_receipt_set_sha256": common_receipt_set_sha256,
        "execution_location": "docker:houtai-gongren",
        "container_id": socket.gethostname(),
        "supervisor_worker_decision_sha256": decision_sha256,
        "intake": {
            "ok": True,
            "artifact_path": str(input_path),
            "container_path": str(input_path),
            "sha256": _sha256(input_raw),
            "size_bytes": len(input_raw),
        },
    }
    if correlation_id:
        fanin["correlation_id"] = correlation_id
    if parent_operation_id:
        fanin["parent_operation_id"] = parent_operation_id
    total_tokens = int(token_accounting["total_tokens"])
    return {
        "grok_fanin_ok": full_success,
        "grok_fanin_manifest_ref": str(manifest_path),
        "grok_fanin_evidence_ref": str(manifest_path),
        "grok_fanin_lane_count": len(results),
        "grok_fanin_lane_modes": [str(item.get("mode") or "") for item in results],
        "grok_fanin_model_identity_ok": manifest["model_identity_ok"],
        "grok_fanin_requested_model": model,
        "grok_fanin_observed_model": observed_model,
        "grok_lanes": results,
        "grok_fanin": fanin,
        "grok_fanin_result_text": "\n\n".join(
            str(item.get("result_text") or "") for item in successful
        ),
        "grok_total_tokens": total_tokens,
        "grok_accepted_tokens": int(token_accounting["accepted_tokens"]),
        "grok_cancelled_tokens": int(token_accounting["cancelled_tokens"]),
        "grok_failed_tokens": int(token_accounting["failed_tokens"]),
        "grok_invocation_count": int(token_accounting["invocation_count"]),
        "grok_token_accounting": token_accounting,
        "grok_execution_location": "docker:houtai-gongren",
        "grok_container_id": socket.gethostname(),
        "supervisor_worker_decision_sha256": decision_sha256,
        "provider_invocation_performed": any(
            item.get("replayed") is not True
            and int((item.get("invocation_accounting") or {}).get("invocation_count") or 0) > 0
            for item in results
        ),
        "model_invocation_performed": any(
            item.get("replayed") is not True
            and int((item.get("invocation_accounting") or {}).get("invocation_count") or 0) > 0
            for item in results
        ),
        "fallback_model_invocation_performed": False,
        "non_grok_model_invocations": 0,
    }


__all__ = [
    "ALLOWED_MODELS",
    "DEFAULT_MODEL",
    "ESCALATION_MODEL",
    "MODEL_POLICY_ID",
    "PROVIDER_ID",
    "_parse_cli_result",
    "docker_native_grok_enabled",
    "run_docker_native_grok_fanin",
]
