"""Native Grok session/MCP transport seam for genuine-scientist episodes.

Probes the actually-available Grok CLI (version, flags, MCP config layout) and
builds exact headless argv for multi-turn tool use via attempt-local MCP only.

Does NOT invoke live provider from worker seats without explicit Owner auth.
Fail closed when credentials, Docker, or nested live model are unavailable.
Leaves INSTRUMENT_CANARY entrypoint untouched (separate argv with --tools '').

Candidate only. completion_claim_allowed is always false.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "xinao.native_grok_session_contract.v1"
PROBE_SCHEMA = "xinao.native_grok_cli_probe.v1"
DRIVER_SCHEMA = "xinao.native_episode_session_driver.v1"
ATTEMPT_EVIDENCE_SCHEMA = "xinao.research_episode_live_attempt.v1"
CANDIDATE_EXPORT_SCHEMA = "xinao.research_episode_candidate_evidence_bundle.v1"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

# Observed on worker seat Grok Build TUI 0.2.112 (probe may re-verify).
REQUIRED_CLI_FLAGS = (
    "--tools",
    "--session-id",
    "--resume",
    "--continue",
    "--max-turns",
    "--output-format",
    "--disallowed-tools",
    "--no-subagents",
    "--no-memory",
    "--disable-web-search",
    "--permission-mode",
    "--agent",
)
MCP_SUBCOMMANDS = ("list", "add", "remove", "doctor")
GENUINE_TOOLS_ALLOWLIST = "search_tool,use_tool"
CANARY_TOOLS_ALLOWLIST = ""
# Live research path: multi-turn budget must exceed canary one-shot.
MIN_LIVE_MAX_TURNS = 8
DEFAULT_LIVE_MAX_TURNS = 16
DEFAULT_LIVE_MODEL = "grok-4.5"
DEFAULT_OUTER_TIMEOUT_SECONDS = 3600
MAX_OUTER_TIMEOUT_SECONDS = 4 * 3600
STRIPPED_BUILTINS = (
    "run_terminal_cmd",
    "read_file",
    "search_replace",
    "grep",
    "list_dir",
    "web_search",
    "web_fetch",
    "todo_write",
    "task",
    "kill_task",
    "get_task_output",
    "memory_search",
    "memory_get",
    "lsp",
    "Agent",
)
# Status vocabulary for Owner one-shot attach/run/export.
STATUS_PLANNED = "PLANNED"
STATUS_ATTEMPT_FAILED = "ATTEMPT_FAILED"
STATUS_LIVE_ATTEMPT_RECORDED = "LIVE_ATTEMPT_RECORDED"
STATUS_CANDIDATE_EVIDENCE_EXPORTED = "CANDIDATE_EVIDENCE_EXPORTED"
SECRET_ARGV_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "xai_api_key",
    "grok_api_key",
)


class NativeSessionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


def authority_clamp() -> dict[str, bool]:
    return {
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _emit_json_stdout(value: object) -> None:
    """Emit machine-readable JSON on stdout as UTF-8 bytes.

    Text-mode print() uses the console code page (often cp1252 on Windows
    GitHub runners) and raises UnicodeEncodeError on characters such as U+2192.
    Writing encoded bytes to the binary buffer preserves Unicode value semantics
    for any consumer that decodes UTF-8 and does not depend on the console page.
    """
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
        return
    sys.stdout.write(payload.decode("utf-8"))
    sys.stdout.flush()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run(argv: Sequence[str], *, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def resolve_grok_bin(explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    env = os.environ.get("XINAO_GROK_BIN") or os.environ.get("GROK_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    which = shutil.which("grok")
    if which:
        return which
    candidate = Path("/usr/local/bin/grok")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def is_uuid(value: str) -> bool:
    return bool(UUID_RE.fullmatch(str(value).strip()))


def new_session_uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class CliProbe:
    grok_bin: str | None
    version: str = ""
    help_text: str = ""
    flags_present: dict[str, bool] = field(default_factory=dict)
    mcp_available: bool = False
    mcp_subcommands: list[str] = field(default_factory=list)
    sessions_available: bool = False
    signed_in: bool | None = None
    docker_available: bool = False
    bwrap_available: bool = False
    auth_error: str = ""
    live_model_callable: bool = False

    def as_dict(self) -> dict[str, Any]:
        missing = [k for k, ok in self.flags_present.items() if not ok]
        return {
            "schema_version": PROBE_SCHEMA,
            "grok_bin": self.grok_bin,
            "version": self.version,
            "flags_present": dict(self.flags_present),
            "required_flags_missing": missing,
            "mcp_available": self.mcp_available,
            "mcp_subcommands": list(self.mcp_subcommands),
            "sessions_available": self.sessions_available,
            "signed_in": self.signed_in,
            "docker_available": self.docker_available,
            "bwrap_available": self.bwrap_available,
            "auth_error": self.auth_error[:500],
            "live_model_callable": self.live_model_callable,
            "native_session_contract_ready": bool(
                self.grok_bin and not missing and self.mcp_available
            ),
            **authority_clamp(),
        }


def probe_grok_cli(*, grok_bin: str | None = None, probe_auth: bool = True) -> CliProbe:
    """Inspect the worker-available Grok binary; never claim live episode success."""
    bin_path = resolve_grok_bin(grok_bin)
    probe = CliProbe(grok_bin=bin_path)
    probe.docker_available = shutil.which("docker") is not None
    probe.bwrap_available = shutil.which("bwrap") is not None or Path("/usr/bin/bwrap").is_file()
    if not bin_path:
        return probe
    try:
        ver = _run([bin_path, "version"])
        probe.version = (ver.stdout or ver.stderr or "").strip().splitlines()[0][:200]
    except (OSError, subprocess.TimeoutExpired) as exc:
        probe.auth_error = f"version_failed:{exc}"
        return probe
    try:
        help_out = _run([bin_path, "--help"])
        probe.help_text = (help_out.stdout or "") + "\n" + (help_out.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        probe.auth_error = f"help_failed:{exc}"
        return probe
    for flag in REQUIRED_CLI_FLAGS:
        probe.flags_present[flag] = flag in probe.help_text
    try:
        mcp_help = _run([bin_path, "mcp", "--help"])
        mcp_text = (mcp_help.stdout or "") + (mcp_help.stderr or "")
        probe.mcp_available = mcp_help.returncode == 0 and "mcp" in mcp_text.lower()
        probe.mcp_subcommands = [c for c in MCP_SUBCOMMANDS if c in mcp_text]
    except (OSError, subprocess.TimeoutExpired):
        probe.mcp_available = False
    try:
        sess = _run([bin_path, "sessions", "--help"])
        probe.sessions_available = sess.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        probe.sessions_available = False
    if probe_auth:
        # Cheap auth probe: single-turn empty-tools prompt must fail closed without creds.
        try:
            auth = _run(
                [
                    bin_path,
                    "-p",
                    "native-episode-auth-probe",
                    "--max-turns",
                    "1",
                    "--tools",
                    "",
                    "--no-subagents",
                    "--no-memory",
                    "--disable-web-search",
                    "--output-format",
                    "json",
                ],
                timeout=12.0,
            )
            out = (auth.stdout or "") + (auth.stderr or "")
            if auth.returncode == 0 and "error" not in out.lower():
                probe.signed_in = True
                probe.live_model_callable = True
            else:
                probe.signed_in = False
                probe.live_model_callable = False
                if "not signed in" in out.lower() or "xai_api_key" in out.lower():
                    probe.auth_error = "NOT_SIGNED_IN"
                else:
                    probe.auth_error = out.strip()[:300] or f"rc={auth.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            probe.signed_in = False
            probe.live_model_callable = False
            probe.auth_error = f"auth_probe_failed:{exc}"
    return probe


def build_canary_argv(
    *,
    grok_bin: str = "/usr/local/bin/grok",
    prompt_file: str = "/input/prompt.md",
    model: str = "grok-4.5",
) -> list[str]:
    """INSTRUMENT_CANARY exact one-shot contract (must stay tool-free)."""
    return [
        grok_bin,
        "--prompt-file",
        prompt_file,
        "--model",
        model,
        "--output-format",
        "json",
        "--no-subagents",
        "--no-memory",
        "--disable-web-search",
        "--max-turns",
        "1",
        "--permission-mode",
        "dontAsk",
        "--tools",
        CANARY_TOOLS_ALLOWLIST,
    ]


def build_genuine_session_argv(
    *,
    grok_bin: str = "/usr/local/bin/grok",
    session_id: str,
    resume: bool = False,
    continue_latest: bool = False,
    model: str = "grok-4.5",
    max_turns: int = 32,
    prompt: str | None = None,
    prompt_file: str | None = None,
    agent_profile: str | None = None,
    permission_mode: str = "dontAsk",
    cwd: str | None = None,
    include_disallowed_builtins: bool = True,
    extra: Sequence[str] | None = None,
) -> list[str]:
    """Exact native Grok argv for genuine dual-container multi-turn MCP episode.

    Session rules (CLI 0.2.112):
    - New conversation: --session-id <UUID> (must not already exist).
    - Resume exact session: --resume <SESSION_ID_OR_TITLE>.
    - Continue most recent in cwd: --continue (mutually exclusive with new id).
    - MCP tools arrive via GROK_HOME config.toml [mcp_servers.episode_lab];
      --tools search_tool,use_tool allowlists MCP discovery surface only.
    - Built-in host tools are stripped via --disallowed-tools and agent profile.
    """
    if continue_latest and resume:
        raise NativeSessionError(
            "ARGV_CONFLICT",
            "--continue and --resume are mutually exclusive with explicit dual use",
        )
    if continue_latest and session_id:
        # continue ignores explicit session-id for identity; reject to avoid silent drift
        raise NativeSessionError(
            "ARGV_CONFLICT",
            "--continue cannot bind an exact session_id; use --resume for exact identity",
        )
    if not continue_latest and not session_id:
        raise NativeSessionError("SESSION_ID_REQUIRED", "session_id empty")
    if not resume and not continue_latest and not is_uuid(session_id):
        # CLI requires UUID for --session-id on new conversations.
        raise NativeSessionError(
            "SESSION_ID_NOT_UUID",
            f"--session-id requires UUID, got {session_id[:64]!r}",
        )
    if max_turns < 2:
        raise NativeSessionError(
            "MAX_TURNS_TOO_LOW",
            "genuine multi-turn episode requires max_turns >= 2 (canary uses 1)",
        )
    argv: list[str] = [
        grok_bin,
        "--model",
        model,
        "--output-format",
        "json",
        "--no-subagents",
        "--no-memory",
        "--disable-web-search",
        "--max-turns",
        str(int(max_turns)),
        "--permission-mode",
        permission_mode,
        "--tools",
        GENUINE_TOOLS_ALLOWLIST,
    ]
    if include_disallowed_builtins:
        argv.extend(["--disallowed-tools", ",".join(STRIPPED_BUILTINS)])
    if agent_profile:
        argv.extend(["--agent", str(agent_profile)])
    if cwd:
        argv.extend(["--cwd", str(cwd)])
    if prompt_file:
        argv.extend(["--prompt-file", str(prompt_file)])
    if resume:
        argv.extend(["--resume", session_id])
    elif continue_latest:
        argv.append("--continue")
    else:
        argv.extend(["--session-id", session_id])
    if prompt and not prompt_file:
        # positional prompt after options is valid; prefer trailing for headless
        argv.append(prompt)
    if extra:
        argv.extend(list(extra))
    return argv


def assert_argv_is_genuine_not_canary(argv: Sequence[str]) -> None:
    joined = list(argv)
    if "--tools" not in joined:
        raise NativeSessionError("GENUINE_ARGV_MISSING_TOOLS", "no --tools")
    tools_val = joined[joined.index("--tools") + 1]
    if tools_val != GENUINE_TOOLS_ALLOWLIST:
        raise NativeSessionError(
            "GENUINE_TOOLS_MISMATCH",
            f"expected {GENUINE_TOOLS_ALLOWLIST!r} got {tools_val!r}",
        )
    if "--max-turns" in joined:
        mt = int(joined[joined.index("--max-turns") + 1])
        if mt < 2:
            raise NativeSessionError("GENUINE_MAX_TURNS_CANARY_SHAPED", str(mt))
    # Must not look like canary empty tools.
    if tools_val == "":
        raise NativeSessionError("CANARY_ARGV_ON_GENUINE_PATH", "empty tools")
    if "--no-subagents" not in joined:
        raise NativeSessionError("GENUINE_ARGV_SUBAGENTS_NOT_DISABLED", "missing --no-subagents")


def assert_live_research_argv(argv: Sequence[str], *, min_turns: int = MIN_LIVE_MAX_TURNS) -> None:
    """Fail closed for empty tools, canary one-turn, host-bypass builtins, low budget."""
    assert_argv_is_genuine_not_canary(argv)
    joined = list(argv)
    if "--max-turns" not in joined:
        raise NativeSessionError("LIVE_MAX_TURNS_MISSING", "no --max-turns")
    mt = int(joined[joined.index("--max-turns") + 1])
    if mt < int(min_turns):
        raise NativeSessionError(
            "LIVE_MAX_TURNS_TOO_LOW",
            f"max_turns={mt} < required={min_turns}",
        )
    if "--model" in joined:
        model = joined[joined.index("--model") + 1]
        if model != DEFAULT_LIVE_MODEL:
            raise NativeSessionError("LIVE_MODEL_MISMATCH", model)
    if "--disable-web-search" not in joined:
        raise NativeSessionError("LIVE_WEB_BYPASS_NOT_DISABLED", "missing --disable-web-search")
    if "--disallowed-tools" not in joined:
        raise NativeSessionError("LIVE_BUILTINS_NOT_STRIPPED", "missing --disallowed-tools")
    denied = joined[joined.index("--disallowed-tools") + 1]
    for required in ("run_terminal_cmd", "web_search", "read_file"):
        if required not in denied:
            raise NativeSessionError("LIVE_BUILTIN_STRIP_INCOMPLETE", required)


def assert_argv_is_canary(argv: Sequence[str]) -> None:
    joined = list(argv)
    if "--tools" not in joined:
        raise NativeSessionError("CANARY_ARGV_MISSING_TOOLS", "no --tools")
    tools_val = joined[joined.index("--tools") + 1]
    if tools_val != "":
        raise NativeSessionError("CANARY_TOOLS_NOT_EMPTY", tools_val)
    if "--max-turns" in joined and joined[joined.index("--max-turns") + 1] != "1":
        raise NativeSessionError("CANARY_MAX_TURNS_DRIFT", "expected 1")


def validate_resume_identity(
    *,
    expected_session_id: str,
    inventory_session_id: str,
    lease_session_id: str,
    receipt_session_id: str | None = None,
) -> None:
    """Reject session substitution / foreign resume."""
    if not expected_session_id:
        raise NativeSessionError("SESSION_ID_REQUIRED", "expected empty")
    if inventory_session_id != expected_session_id:
        raise NativeSessionError(
            "FOREIGN_SESSION",
            f"inventory={inventory_session_id} expected={expected_session_id}",
        )
    if lease_session_id != expected_session_id:
        raise NativeSessionError(
            "RESUME_IDENTITY_DRIFT",
            f"lease={lease_session_id} expected={expected_session_id}",
        )
    if receipt_session_id is not None and receipt_session_id != expected_session_id:
        raise NativeSessionError(
            "RECEIPT_SESSION_MISMATCH",
            f"receipt={receipt_session_id} expected={expected_session_id}",
        )


def reject_same_process_fake_resume(
    *,
    checkpoint_bind_sha256: str,
    prior_host_pid: int | None,
    current_host_pid: int,
    prior_transport_container_id: str | None,
    current_transport_container_id: str | None,
    containers_were_removed: bool,
) -> dict[str, Any]:
    """Fresh host-process resume proof gates (synthetic or live).

    Same-process in-memory 'resume' without container removal / new host PID is rejected.
    """
    if not checkpoint_bind_sha256 or HEX_SHA256.fullmatch(checkpoint_bind_sha256) is None:
        raise NativeSessionError("CHECKPOINT_BIND_REQUIRED", checkpoint_bind_sha256)
    if prior_host_pid is not None and prior_host_pid == current_host_pid:
        if not containers_were_removed:
            raise NativeSessionError(
                "SAME_PROCESS_FAKE_RESUME",
                f"pid={current_host_pid} still owns unremoved pair",
            )
    if (
        prior_transport_container_id
        and current_transport_container_id
        and prior_transport_container_id == current_transport_container_id
        and containers_were_removed
    ):
        raise NativeSessionError(
            "CONTAINER_ID_REUSE_AFTER_REMOVAL",
            "transport container id must change after remove",
        )
    return {
        "status": "FRESH_RESUME_GATES_OK",
        "checkpoint_bind_sha256": checkpoint_bind_sha256,
        "prior_host_pid": prior_host_pid,
        "current_host_pid": current_host_pid,
        "containers_were_removed": containers_were_removed,
        **authority_clamp(),
    }


def reject_fabricated_tool_event(
    *,
    event: Mapping[str, Any],
    trusted_event_hashes: Sequence[str],
) -> None:
    """Tool-event fabrication: event_hash must match canonical body AND trusted chain.

    A self-consistent hash that was never emitted by the sidecar is still fabricated
    for promotion purposes.
    """
    if not isinstance(event, Mapping):
        raise NativeSessionError("TOOL_EVENT_INVALID", "not object")
    claimed = event.get("event_hash")
    if not isinstance(claimed, str) or HEX_SHA256.fullmatch(claimed) is None:
        raise NativeSessionError("TOOL_EVENT_HASH_MISSING", str(claimed))
    body = {k: v for k, v in event.items() if k != "event_hash"}
    observed = _sha256_bytes(_canonical_bytes(body))
    trusted = set(trusted_event_hashes)
    if claimed != observed:
        raise NativeSessionError(
            "TOOL_EVENT_FABRICATED",
            f"claimed={claimed} observed={observed}",
        )
    if claimed not in trusted:
        raise NativeSessionError(
            "TOOL_EVENT_UNTRUSTED",
            "hash not in trusted MCP event chain",
        )


def reject_synthetic_receipt_promotion(
    *,
    receipt: Mapping[str, Any],
    live_required: bool = True,
) -> None:
    """Synthetic dual-host / harness receipts must not promote to live role fitness."""
    if receipt.get("completion_claim_allowed") is True:
        raise NativeSessionError("SYNTHETIC_RECEIPT_AUTHORITY", "completion_claim_allowed")
    if receipt.get("owner_adopted") is True:
        raise NativeSessionError("SYNTHETIC_RECEIPT_AUTHORITY", "owner_adopted")
    if receipt.get("role_fitness_claimed") is True:
        raise NativeSessionError("SYNTHETIC_RECEIPT_AUTHORITY", "role_fitness_claimed")
    if receipt.get("science_restored") is True:
        raise NativeSessionError("SYNTHETIC_RECEIPT_AUTHORITY", "science_restored")
    synthetic_markers = (
        receipt.get("synthetic") is True
        or str(receipt.get("tool_container_id") or "").startswith("synthetic-")
        or str(receipt.get("transport_container_id") or "").startswith("synthetic-")
        or receipt.get("mode") == "synthetic"
    )
    if live_required and synthetic_markers:
        raise NativeSessionError(
            "SYNTHETIC_RECEIPT_PROMOTION",
            "synthetic dual-container receipt cannot satisfy live acceptance",
        )


def credential_reachability_scan(
    *,
    env: Mapping[str, str] | None = None,
    tool_mounts: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Negative probe: tool-side must not see provider credentials or docker socket."""
    env = dict(env if env is not None else os.environ)
    mounts = list(tool_mounts or [])
    hits: list[str] = []
    for key, value in env.items():
        upper = key.upper()
        if not value:
            continue
        if upper in {"GROK_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"}:
            hits.append(f"env:{key}")
        if upper == "GROK_HOME" and "auth" in value.lower():
            hits.append(f"env:{key}")
        if upper == "DOCKER_HOST":
            hits.append(f"env:{key}")
    for m in mounts:
        lowered = m.lower()
        for bad in (
            "auth.json",
            "/grok-home",
            "docker.sock",
            "shadow_ledger",
            "/ledger",
            "/outcomes",
        ):
            if bad in lowered:
                hits.append(f"mount:{m}")
    return {
        "status": "CREDENTIAL_REACHABLE" if hits else "CREDENTIAL_UNREACHABLE",
        "hits": hits,
        "ok": not hits,
        **authority_clamp(),
    }


def fail_closed_live_invoke(
    *,
    probe: CliProbe | None = None,
    force_live: bool = False,
) -> dict[str, Any]:
    """Refuse live model/docker when unavailable; emit exact command contract instead."""
    p = probe or probe_grok_cli()
    reasons: list[str] = []
    if not p.grok_bin:
        reasons.append("GROK_BIN_ABSENT")
    if p.signed_in is False or not p.live_model_callable:
        reasons.append("LIVE_MODEL_AUTH_UNAVAILABLE")
    if not p.docker_available:
        reasons.append("DOCKER_ABSENT")
    if force_live and reasons:
        raise NativeSessionError("LIVE_INVOKE_FORBIDDEN", ",".join(reasons))
    session = new_session_uuid()
    genuine_argv = build_genuine_session_argv(
        grok_bin=p.grok_bin or "/usr/local/bin/grok",
        session_id=session,
        resume=False,
        max_turns=32,
        prompt="genuine multi-turn MCP lab task",
    )
    resume_argv = build_genuine_session_argv(
        grok_bin=p.grok_bin or "/usr/local/bin/grok",
        session_id=session,
        resume=True,
        max_turns=32,
    )
    canary_argv = build_canary_argv(grok_bin=p.grok_bin or "/usr/local/bin/grok")
    assert_argv_is_genuine_not_canary(genuine_argv)
    assert_argv_is_canary(canary_argv)
    contract = {
        "schema_version": SCHEMA,
        "status": "FAIL_CLOSED_LIVE_UNAVAILABLE" if reasons else "LIVE_READY_CONTRACT",
        "reasons": reasons,
        "cli_probe": p.as_dict(),
        "canary_argv": canary_argv,
        "genuine_new_session_argv": genuine_argv,
        "genuine_resume_argv": resume_argv,
        "mcp_server": "episode_lab",
        "mcp_tools_allowlist": GENUINE_TOOLS_ALLOWLIST,
        "stripped_builtins": list(STRIPPED_BUILTINS),
        "session_id_example": session,
        "exact_host_commands": [
            {
                "step": "materialize_mcp_binding",
                "note": "episode_mcp_binding.materialize_attempt_local_binding → GROK_HOME",
            },
            {
                "step": "start_tool_then_transport",
                "note": "dual_container_host.start_pair order: tool_executor → transport",
            },
            {
                "step": "new_session",
                "argv": genuine_argv,
            },
            {
                "step": "interrupt_remove",
                "commands": [
                    "docker stop -t 2 <transport_id>",
                    "docker rm -f <transport_id> <tool_id>",
                ],
            },
            {
                "step": "fresh_host_resume",
                "argv": resume_argv,
            },
        ],
        "live_model_invoked": False,
        "role_fitness_claimed": False,
        **authority_clamp(),
    }
    contract["contract_sha256"] = _sha256_bytes(_canonical_bytes(contract))
    return contract


@dataclass
class NativeEpisodeSessionDriver:
    """Attempt-local native session planner (no daemon, no authority writes)."""

    episode_id: str
    session_id: str
    grok_home: Path
    work_root: Path
    grok_bin: str = "/usr/local/bin/grok"
    max_turns: int = 32
    model: str = "grok-4.5"

    def materialize_binding(self, *, socket_path: str = "/ipc/tool.sock") -> dict[str, Any]:
        import importlib.util
        import sys

        pkg = Path(__file__).resolve().parent
        if str(pkg) not in sys.path:
            sys.path.insert(0, str(pkg))
        path = pkg / "episode_mcp_binding.py"
        spec = importlib.util.spec_from_file_location("xinao_episode_mcp_binding_native", path)
        if spec is None or spec.loader is None:
            raise NativeSessionError("MCP_BINDING_MISSING", str(path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        receipt = mod.materialize_attempt_local_binding(
            root=self.work_root / "attempt",
            episode_id=self.episode_id,
            socket_path=socket_path,
            server_path=str(pkg / "mcp_episode_lab_server.py"),
            pythonpath=str(pkg),
            grok_home=self.grok_home,
        )
        return receipt

    def plan_new(self, *, prompt: str) -> dict[str, Any]:
        binding = self.materialize_binding()
        argv = build_genuine_session_argv(
            grok_bin=self.grok_bin,
            session_id=self.session_id,
            resume=False,
            model=self.model,
            max_turns=self.max_turns,
            prompt=prompt,
            agent_profile=str(binding.get("agent_profile") or ""),
        )
        assert_argv_is_genuine_not_canary(argv)
        return {
            "schema_version": DRIVER_SCHEMA,
            "verb": "new_session",
            "episode_id": self.episode_id,
            "session_id": self.session_id,
            "argv": argv,
            "binding_receipt_sha256": binding.get("receipt_sha256"),
            "grok_home": str(self.grok_home),
            "env": {
                "GROK_HOME": str(self.grok_home),
                "XINAO_MCP_BINDING": "1",
                "XINAO_MCP_SERVER": "episode_lab",
                "XINAO_MCP_TOOLS": GENUINE_TOOLS_ALLOWLIST,
            },
            **authority_clamp(),
        }

    def plan_resume(self) -> dict[str, Any]:
        argv = build_genuine_session_argv(
            grok_bin=self.grok_bin,
            session_id=self.session_id,
            resume=True,
            model=self.model,
            max_turns=self.max_turns,
        )
        assert_argv_is_genuine_not_canary(argv)
        return {
            "schema_version": DRIVER_SCHEMA,
            "verb": "resume_session",
            "episode_id": self.episode_id,
            "session_id": self.session_id,
            "argv": argv,
            **authority_clamp(),
        }


def redact_argv(argv: Sequence[str]) -> list[str]:
    """Return argv copy with secret-looking tokens redacted for digests/logs.

    Only flag-shaped tokens (leading ``-`` or ``KEY=value``) are treated as
    secret carriers so values that merely contain substrings like ``secret``
    are not misclassified as flags.
    """
    out: list[str] = []
    skip_value = False
    for item in argv:
        text = str(item)
        lower = text.lower()
        if skip_value:
            out.append("<redacted>")
            skip_value = False
            continue
        is_flag = text.startswith("-")
        is_assign = (not text.startswith("-")) and ("=" in text)
        if is_flag or is_assign:
            key_part = lower.split("=", 1)[0]
            # Normalize --api-key / --xai-api-key style flags to underscore form.
            key_norm = key_part.lstrip("-").replace("-", "_")
            if any(
                marker in key_part or marker in key_norm for marker in SECRET_ARGV_MARKERS
            ):
                if "=" in text:
                    key, _sep, _val = text.partition("=")
                    out.append(f"{key}=<redacted>")
                else:
                    out.append(text)
                    skip_value = True
                continue
        out.append(text)
    return out


def argv_digest(argv: Sequence[str]) -> str:
    return _sha256_bytes(_canonical_bytes(redact_argv(argv)))


def clamp_outer_timeout(timeout_seconds: float | int | None) -> float:
    if timeout_seconds is None:
        return float(DEFAULT_OUTER_TIMEOUT_SECONDS)
    value = float(timeout_seconds)
    if value <= 0:
        raise NativeSessionError("OUTER_TIMEOUT_INVALID", str(timeout_seconds))
    if value > float(MAX_OUTER_TIMEOUT_SECONDS):
        raise NativeSessionError(
            "OUTER_TIMEOUT_TOO_LARGE",
            f"{value} > {MAX_OUTER_TIMEOUT_SECONDS}",
        )
    return value


def clamp_live_max_turns(max_turns: int | None) -> int:
    value = int(DEFAULT_LIVE_MAX_TURNS if max_turns is None else max_turns)
    if value < MIN_LIVE_MAX_TURNS:
        raise NativeSessionError(
            "LIVE_MAX_TURNS_TOO_LOW",
            f"max_turns={value} < required={MIN_LIVE_MAX_TURNS}",
        )
    return value


def _b64encode(payload: bytes) -> str:
    import base64

    return base64.b64encode(payload).decode("ascii")


def _b64decode(payload: str) -> bytes:
    import base64

    return base64.b64decode(payload.encode("ascii"), validate=True)


def write_cas_blob(root: Path, kind: str, payload: bytes) -> str:
    """Atomic content-addressed write under root/<kind>/sha256/ab/<digest>."""
    digest = _sha256_bytes(payload)
    dest_dir = Path(root) / kind / "sha256" / digest[:2]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / digest
    if dest.is_file():
        existing = dest.read_bytes()
        if existing != payload:
            raise NativeSessionError("CAS_IMMUTABLE_COLLISION", f"{kind}:{digest}")
        return digest
    temporary = dest.with_name(f".{dest.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, dest)
    return digest


def load_cas_blob(root: Path, kind: str, digest: str) -> bytes:
    if HEX_SHA256.fullmatch(str(digest)) is None:
        raise NativeSessionError("CAS_DIGEST_INVALID", digest)
    path = Path(root) / kind / "sha256" / digest[:2] / digest
    if not path.is_file():
        raise NativeSessionError("CAS_BLOB_MISSING", f"{kind}:{digest}")
    payload = path.read_bytes()
    if _sha256_bytes(payload) != digest:
        raise NativeSessionError("CAS_BLOB_HASH_MISMATCH", digest)
    return payload


def append_attempt_index(root: Path, entry: Mapping[str, Any]) -> None:
    index_path = Path(root) / "attempts" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with index_path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def parse_provider_machine_output(
    stdout: bytes | str,
    stderr: bytes | str = b"",
) -> dict[str, Any]:
    """Parse JSON/JSONL provider CLI output for session UUID, stop reason, turns."""
    if isinstance(stdout, str):
        stdout_b = stdout.encode("utf-8", errors="replace")
        stdout_text = stdout
    else:
        stdout_b = stdout
        stdout_text = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, str):
        stderr_text = stderr
    else:
        stderr_text = stderr.decode("utf-8", errors="replace")
    combined = stdout_text + "\n" + stderr_text
    records: list[dict[str, Any]] = []
    # Prefer line-delimited JSON then whole-document JSON.
    for line in stdout_text.splitlines():
        text = line.strip()
        if not text or text[0] not in "{[":
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    if not records:
        stripped = stdout_text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise NativeSessionError("PROVIDER_OUTPUT_MALFORMED", str(exc)[:300]) from exc
            if isinstance(value, dict):
                records = [value]
            elif isinstance(value, list):
                records = [item for item in value if isinstance(item, dict)]
    if not records:
        raise NativeSessionError("PROVIDER_OUTPUT_EMPTY", "no JSON/JSONL records")

    def _pick(keys: Sequence[str]) -> Any:
        for record in reversed(records):
            for key in keys:
                if key in record and record[key] not in (None, ""):
                    return record[key]
                nested = record.get("result") if isinstance(record.get("result"), dict) else None
                if nested and key in nested and nested[key] not in (None, ""):
                    return nested[key]
                meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else None
                if meta and key in meta and meta[key] not in (None, ""):
                    return meta[key]
        return None

    session_raw = _pick(
        ("session_id", "sessionId", "session_uuid", "conversation_id", "id")
    )
    stop_reason = _pick(("stop_reason", "stopReason", "finish_reason", "end_reason", "status"))
    model = _pick(("model", "model_id", "modelId"))
    turns_raw = _pick(("turn_count", "turns", "actual_turns", "num_turns", "message_count"))
    error = _pick(("error", "error_message", "message"))
    if session_raw is not None and not is_uuid(str(session_raw)):
        # Some CLIs nest session objects.
        if isinstance(session_raw, dict):
            session_raw = session_raw.get("id") or session_raw.get("session_id")
    session_uuid = str(session_raw).strip() if session_raw is not None else ""
    actual_turns: int | None = None
    if turns_raw is not None:
        try:
            actual_turns = int(turns_raw)
        except (TypeError, ValueError):
            actual_turns = None
    provider_error = None
    if isinstance(error, str) and error.strip():
        provider_error = error.strip()[:500]
    elif any(str(r.get("type") or "").lower() == "error" for r in records):
        provider_error = "provider_error_record"
    lower_combined = combined.lower()
    if "not signed in" in lower_combined or "xai_api_key" in lower_combined:
        provider_error = provider_error or "NOT_SIGNED_IN"
    return {
        "records": records,
        "session_uuid": session_uuid,
        "stop_reason": str(stop_reason).strip() if stop_reason is not None else "",
        "model": str(model).strip() if model is not None else "",
        "actual_turns": actual_turns,
        "provider_error": provider_error,
        "stdout_sha256": _sha256_bytes(stdout_b),
        "record_count": len(records),
    }


def reject_non_live_driver(
    *,
    synthetic: bool,
    driver: str | None,
    planned_only: bool,
    host_fallback: bool = False,
) -> None:
    if synthetic:
        raise NativeSessionError("SYNTHETIC_DRIVER_REFUSED", "synthetic=true")
    if planned_only:
        raise NativeSessionError("PLANNED_ARGV_NOT_LIVE", "planned output is not live evidence")
    if host_fallback:
        raise NativeSessionError("HOST_GROK_FALLBACK_REFUSED", "must docker exec transport")
    driver_text = str(driver or "").strip().lower()
    forbidden = (
        "mock",
        "fixture",
        "synthetic",
        "planned",
        "host_side",
        "host_fallback",
        "canary",
    )
    if any(token in driver_text for token in forbidden):
        raise NativeSessionError("MOCK_DRIVER_REFUSED", driver_text)


def build_live_attempt_record(
    *,
    episode_id: str,
    host_session_id: str,
    provider_session_uuid: str,
    attempt_id: str,
    argv: Sequence[str],
    stdout: bytes,
    stderr: bytes,
    exit_code: int,
    model: str,
    max_turns: int,
    timeout_seconds: float,
    started_at: str,
    finished_at: str,
    transport_container_id: str,
    tool_container_id: str,
    transport_image_id: str,
    tool_image_id: str,
    pair_receipt_sha256: str,
    namespace_receipt_sha256: str | None,
    release_id: str | None,
    release_identity_sha256: str | None,
    cas_head_sha256: str | None,
    mcp_event_hashes: Sequence[str],
    lab_artifact_manifest: Mapping[str, Any] | None,
    prior_attempt_hash: str | None,
    resume: bool,
    live_executed: bool,
    driver: str,
    synthetic: bool,
    timed_out: bool = False,
    docker_exec_failed: bool = False,
) -> dict[str, Any]:
    """Assemble attempt evidence. Does not claim success if provider/plumbing failed."""
    reject_non_live_driver(
        synthetic=synthetic,
        driver=driver,
        planned_only=not live_executed,
        host_fallback="host" in driver.lower() and "docker" not in driver.lower(),
    )
    assert_live_research_argv(list(argv))
    redacted = redact_argv(argv)
    stdout_sha = _sha256_bytes(stdout)
    stderr_sha = _sha256_bytes(stderr)
    tool_trace_sha = _sha256_bytes(
        _canonical_bytes({"mcp_event_hashes": list(mcp_event_hashes)})
    )
    artifact_manifest = dict(lab_artifact_manifest or {"artifacts": []})
    artifact_manifest_sha = _sha256_bytes(_canonical_bytes(artifact_manifest))
    parsed: dict[str, Any] | None = None
    parse_error = ""
    try:
        parsed = parse_provider_machine_output(stdout, stderr)
    except NativeSessionError as exc:
        parse_error = exc.reason_code
    status = STATUS_ATTEMPT_FAILED
    success_gates_ok = True
    failure_reasons: list[str] = []
    if not live_executed:
        success_gates_ok = False
        failure_reasons.append("NOT_LIVE_EXECUTED")
    if docker_exec_failed:
        success_gates_ok = False
        failure_reasons.append("DOCKER_EXEC_FAILED")
    if timed_out:
        success_gates_ok = False
        failure_reasons.append("OUTER_TIMEOUT")
    if exit_code != 0:
        success_gates_ok = False
        failure_reasons.append(f"NONZERO_EXIT:{exit_code}")
    if parsed is None:
        success_gates_ok = False
        failure_reasons.append(parse_error or "PROVIDER_OUTPUT_MALFORMED")
    else:
        if parsed.get("provider_error"):
            success_gates_ok = False
            failure_reasons.append(f"PROVIDER_ERROR:{parsed['provider_error']}")
        if not parsed.get("session_uuid") or not is_uuid(str(parsed["session_uuid"])):
            success_gates_ok = False
            failure_reasons.append("SESSION_UUID_MISSING")
        if not parsed.get("stop_reason"):
            success_gates_ok = False
            failure_reasons.append("STOP_REASON_MISSING")
        if not stdout:
            success_gates_ok = False
            failure_reasons.append("RAW_STDOUT_EMPTY")
        if not list(mcp_event_hashes):
            # Tool namespace is required; empty MCP chain is not live multi-tool research.
            # Allow zero only when explicit single-turn empty tools — which we already reject.
            success_gates_ok = False
            failure_reasons.append("MCP_EVENTS_MISSING")
        if provider_session_uuid and parsed.get("session_uuid"):
            if str(parsed["session_uuid"]).lower() != str(provider_session_uuid).lower():
                # For new session, provider returns the session; allow binding either way
                # only when caller left empty expected. Mismatch on resume is fatal.
                if resume:
                    success_gates_ok = False
                    failure_reasons.append("SESSION_UUID_MISMATCH")
    bound_session = provider_session_uuid
    if parsed and parsed.get("session_uuid") and is_uuid(str(parsed["session_uuid"])):
        if not resume or not provider_session_uuid:
            bound_session = str(parsed["session_uuid"])
        elif str(parsed["session_uuid"]).lower() == str(provider_session_uuid).lower():
            bound_session = str(parsed["session_uuid"])
    if success_gates_ok:
        status = STATUS_LIVE_ATTEMPT_RECORDED
    record: dict[str, Any] = {
        "schema_version": ATTEMPT_EVIDENCE_SCHEMA,
        "attempt_id": attempt_id,
        "episode_id": episode_id,
        "host_session_id": host_session_id,
        "provider_session_uuid": bound_session,
        "status": status,
        "live_executed": bool(live_executed),
        "synthetic": bool(synthetic),
        "driver": driver,
        "resume": bool(resume),
        "model": model,
        "max_turns": int(max_turns),
        "actual_turns": (parsed or {}).get("actual_turns"),
        "exit_code": int(exit_code),
        "stop_reason": (parsed or {}).get("stop_reason") or "",
        "timed_out": bool(timed_out),
        "docker_exec_failed": bool(docker_exec_failed),
        "failure_reasons": failure_reasons,
        "argv_digest": argv_digest(argv),
        "argv_redacted": redacted,
        "raw_stdout_sha256": stdout_sha,
        "raw_stderr_sha256": stderr_sha,
        "raw_stdout_b64": _b64encode(stdout),
        "raw_stderr_b64": _b64encode(stderr),
        "tool_trace_sha256": tool_trace_sha,
        "mcp_event_hashes": list(mcp_event_hashes),
        "artifact_manifest": artifact_manifest,
        "artifact_manifest_sha256": artifact_manifest_sha,
        "pair_receipt_sha256": pair_receipt_sha256,
        "namespace_receipt_sha256": namespace_receipt_sha256,
        "transport_container_id": transport_container_id,
        "tool_container_id": tool_container_id,
        "transport_image_id": transport_image_id,
        "tool_image_id": tool_image_id,
        "release_id": release_id,
        "release_identity_sha256": release_identity_sha256,
        "cas_head_sha256": cas_head_sha256,
        "prior_attempt_hash": prior_attempt_hash,
        "timeout_seconds": float(timeout_seconds),
        "started_at": started_at,
        "finished_at": finished_at,
        "parse_error": parse_error or None,
        "provider_record_count": (parsed or {}).get("record_count") or 0,
        **authority_clamp(),
    }
    # Strip large b64 from hash body? Keep full record hash including raw payloads.
    body_for_hash = {k: v for k, v in record.items() if k != "attempt_hash"}
    record["attempt_hash"] = _sha256_bytes(_canonical_bytes(body_for_hash))
    return record


def persist_live_attempt(episode_output_root: Path, attempt: Mapping[str, Any]) -> dict[str, Any]:
    """Write attempt + raw blobs under episode output with append-only index."""
    if attempt.get("schema_version") != ATTEMPT_EVIDENCE_SCHEMA:
        raise NativeSessionError("ATTEMPT_SCHEMA_INVALID", str(attempt.get("schema_version")))
    root = Path(episode_output_root)
    raw_stdout = _b64decode(str(attempt["raw_stdout_b64"]))
    raw_stderr = _b64decode(str(attempt["raw_stderr_b64"]))
    if _sha256_bytes(raw_stdout) != attempt.get("raw_stdout_sha256"):
        raise NativeSessionError("RAW_STDOUT_HASH_MISMATCH", "truncated or forged")
    if _sha256_bytes(raw_stderr) != attempt.get("raw_stderr_sha256"):
        raise NativeSessionError("RAW_STDERR_HASH_MISMATCH", "truncated or forged")
    stdout_digest = write_cas_blob(root, "raw", raw_stdout)
    stderr_digest = write_cas_blob(root, "raw", raw_stderr)
    # Store attempt without embedded b64 (pointers only) for durable CAS object.
    durable = dict(attempt)
    durable["raw_stdout_cas"] = stdout_digest
    durable["raw_stderr_cas"] = stderr_digest
    durable.pop("raw_stdout_b64", None)
    durable.pop("raw_stderr_b64", None)
    body = {k: v for k, v in durable.items() if k != "attempt_hash"}
    durable["attempt_hash"] = _sha256_bytes(_canonical_bytes(body))
    attempt_digest = write_cas_blob(root, "attempts", _canonical_bytes(durable))
    if attempt_digest != durable["attempt_hash"]:
        # CAS path uses content hash of durable bytes; keep both identities explicit.
        durable["attempt_cas_digest"] = attempt_digest
    else:
        durable["attempt_cas_digest"] = attempt_digest
    # Re-write if hash field changed identity of bytes — ensure single canonical object.
    final_bytes = _canonical_bytes(durable)
    final_digest = write_cas_blob(root, "attempts", final_bytes)
    append_attempt_index(
        root,
        {
            "attempt_id": durable.get("attempt_id"),
            "attempt_cas_digest": final_digest,
            "attempt_hash": durable.get("attempt_hash"),
            "status": durable.get("status"),
            "episode_id": durable.get("episode_id"),
            "provider_session_uuid": durable.get("provider_session_uuid"),
            "recorded_at": durable.get("finished_at"),
            "prior_attempt_hash": durable.get("prior_attempt_hash"),
        },
    )
    # Preserve successful attempt pointer; failed must not overwrite success.
    success_ptr = root / "attempts" / "last_successful.json"
    latest_ptr = root / "attempts" / "last_recorded.json"
    pointer = {
        "attempt_cas_digest": final_digest,
        "attempt_hash": durable.get("attempt_hash"),
        "status": durable.get("status"),
        "episode_id": durable.get("episode_id"),
        "provider_session_uuid": durable.get("provider_session_uuid"),
    }
    _write_json_atomic(latest_ptr, pointer)
    if durable.get("status") == STATUS_LIVE_ATTEMPT_RECORDED:
        _write_json_atomic(success_ptr, pointer)
    elif success_ptr.is_file():
        # leave prior success intact
        pass
    return {
        "status": durable.get("status"),
        "attempt_cas_digest": final_digest,
        "attempt_hash": durable.get("attempt_hash"),
        "raw_stdout_cas": stdout_digest,
        "raw_stderr_cas": stderr_digest,
        "provider_session_uuid": durable.get("provider_session_uuid"),
        "attempt": durable,
        **authority_clamp(),
    }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(dict(value)))
    os.replace(temporary, path)


def load_attempt_cas(episode_output_root: Path, attempt_cas_digest: str) -> dict[str, Any]:
    payload = load_cas_blob(Path(episode_output_root), "attempts", attempt_cas_digest)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise NativeSessionError("ATTEMPT_CAS_INVALID", attempt_cas_digest)
    return value


def validate_attempt_exportable(attempt: Mapping[str, Any]) -> None:
    """Fail closed: only LIVE_ATTEMPT_RECORDED with complete evidence may export."""
    if attempt.get("schema_version") != ATTEMPT_EVIDENCE_SCHEMA:
        raise NativeSessionError("ATTEMPT_SCHEMA_INVALID", str(attempt.get("schema_version")))
    if attempt.get("status") != STATUS_LIVE_ATTEMPT_RECORDED:
        raise NativeSessionError("ATTEMPT_NOT_EXPORTABLE", str(attempt.get("status")))
    if attempt.get("live_executed") is not True:
        raise NativeSessionError("PLANNED_ARGV_NOT_LIVE", "live_executed!=true")
    if attempt.get("synthetic") is True:
        raise NativeSessionError("SYNTHETIC_DRIVER_REFUSED", "synthetic attempt")
    reject_non_live_driver(
        synthetic=bool(attempt.get("synthetic")),
        driver=str(attempt.get("driver") or ""),
        planned_only=attempt.get("live_executed") is not True,
    )
    exit_code = attempt.get("exit_code")
    if exit_code is None or int(exit_code) != 0:
        raise NativeSessionError("NONZERO_EXIT_NOT_EXPORTABLE", str(exit_code))
    if attempt.get("timed_out") is True:
        raise NativeSessionError("TIMEOUT_NOT_EXPORTABLE", "timed_out")
    if attempt.get("docker_exec_failed") is True:
        raise NativeSessionError("DOCKER_FAILURE_NOT_EXPORTABLE", "docker_exec_failed")
    if attempt.get("failure_reasons"):
        raise NativeSessionError(
            "ATTEMPT_FAILURE_REASONS_PRESENT",
            ",".join(str(x) for x in attempt.get("failure_reasons") or []),
        )
    session = str(attempt.get("provider_session_uuid") or "")
    if not is_uuid(session):
        raise NativeSessionError("SESSION_UUID_MISSING", session)
    if not attempt.get("stop_reason"):
        raise NativeSessionError("STOP_REASON_MISSING", "empty")
    if not attempt.get("raw_stdout_sha256") or HEX_SHA256.fullmatch(
        str(attempt.get("raw_stdout_sha256"))
    ) is None:
        raise NativeSessionError("RAW_STDOUT_MISSING", "hash")
    if not attempt.get("mcp_event_hashes"):
        raise NativeSessionError("MCP_EVENTS_MISSING", "empty tool trace")
    if not attempt.get("pair_receipt_sha256"):
        raise NativeSessionError("PAIR_RECEIPT_MISSING", "export")
    for key in (
        "transport_image_id",
        "tool_image_id",
        "transport_container_id",
        "tool_container_id",
        "argv_digest",
        "tool_trace_sha256",
        "artifact_manifest_sha256",
    ):
        if not attempt.get(key):
            raise NativeSessionError("ATTEMPT_FIELD_MISSING", key)
    # Authority theater hard reject.
    for bad in ("owner_adopted", "science_restored", "parent_complete", "completion_claim_allowed"):
        if attempt.get(bad) is True:
            raise NativeSessionError("AUTHORITY_CLAIM_FORBIDDEN", bad)


def export_candidate_evidence_bundle(
    *,
    episode_output_root: Path,
    attempt_cas_digest: str,
    episode_id: str,
    cas_head_sha256: str,
    expected_provider_session_uuid: str | None = None,
    expected_pair_receipt_sha256: str | None = None,
    expected_namespace_receipt_sha256: str | None = None,
    expected_transport_image_id: str | None = None,
    expected_tool_image_id: str | None = None,
    package_release_id: str | None = None,
    package_release_identity_sha256: str | None = None,
    prompt_material_cutoff: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Export closed-schema candidate-only bundle from canonical attempt CAS.

    Derives identities from stored attempt evidence; rejects forged caller hashes.
    Idempotent for identical inputs; never writes shadow/adoption/freeze state.
    """
    root = Path(episode_output_root)
    attempt = load_attempt_cas(root, attempt_cas_digest)
    validate_attempt_exportable(attempt)
    if attempt.get("episode_id") != episode_id:
        raise NativeSessionError(
            "EPISODE_MISMATCH",
            f"attempt={attempt.get('episode_id')} expected={episode_id}",
        )
    if cas_head_sha256 and attempt.get("cas_head_sha256") not in {None, cas_head_sha256}:
        if attempt.get("cas_head_sha256") != cas_head_sha256:
            raise NativeSessionError(
                "CHECKPOINT_HEAD_DRIFT",
                f"attempt={attempt.get('cas_head_sha256')} expected={cas_head_sha256}",
            )
    if expected_provider_session_uuid and (
        str(attempt.get("provider_session_uuid") or "").lower()
        != str(expected_provider_session_uuid).lower()
    ):
        raise NativeSessionError(
            "SESSION_UUID_MISMATCH",
            f"attempt={attempt.get('provider_session_uuid')} expected={expected_provider_session_uuid}",
        )
    if expected_pair_receipt_sha256 and attempt.get("pair_receipt_sha256") != expected_pair_receipt_sha256:
        raise NativeSessionError("PAIR_RECEIPT_MISMATCH", "export")
    if expected_namespace_receipt_sha256 and attempt.get(
        "namespace_receipt_sha256"
    ) != expected_namespace_receipt_sha256:
        raise NativeSessionError("NAMESPACE_RECEIPT_MISMATCH", "export")
    if expected_transport_image_id and attempt.get("transport_image_id") != expected_transport_image_id:
        raise NativeSessionError("TRANSPORT_IMAGE_MISMATCH", "export")
    if expected_tool_image_id and attempt.get("tool_image_id") != expected_tool_image_id:
        raise NativeSessionError("TOOL_IMAGE_MISMATCH", "export")
    # Caller package identity must not override attempt-sealed identity when present.
    release_id = attempt.get("release_id") or package_release_id
    release_identity = attempt.get("release_identity_sha256") or package_release_identity_sha256
    if package_release_id and attempt.get("release_id") and package_release_id != attempt.get(
        "release_id"
    ):
        raise NativeSessionError("RELEASE_ID_MISMATCH", "export")
    if (
        package_release_identity_sha256
        and attempt.get("release_identity_sha256")
        and package_release_identity_sha256 != attempt.get("release_identity_sha256")
    ):
        raise NativeSessionError("RELEASE_IDENTITY_MISMATCH", "export")
    # Reconstruct raw session hash from CAS when available.
    raw_session_hash = str(attempt.get("raw_stdout_sha256"))
    if attempt.get("raw_stdout_cas"):
        raw_bytes = load_cas_blob(root, "raw", str(attempt["raw_stdout_cas"]))
        if _sha256_bytes(raw_bytes) != raw_session_hash:
            raise NativeSessionError("RAW_STDOUT_HASH_MISMATCH", "cas drift")
    bundle_body = {
        "schema_version": CANDIDATE_EXPORT_SCHEMA,
        "status": STATUS_CANDIDATE_EVIDENCE_EXPORTED,
        "episode_id": episode_id,
        "cas_head_sha256": cas_head_sha256 or attempt.get("cas_head_sha256"),
        "attempt_id": attempt.get("attempt_id"),
        "attempt_hash": attempt.get("attempt_hash"),
        "attempt_cas_digest": attempt_cas_digest,
        "raw_session_hash": raw_session_hash,
        "tool_trace_hash": attempt.get("tool_trace_sha256"),
        "artifact_manifest_hash": attempt.get("artifact_manifest_sha256"),
        "pair_receipt_sha256": attempt.get("pair_receipt_sha256"),
        "namespace_receipt_sha256": attempt.get("namespace_receipt_sha256"),
        "release_id": release_id,
        "release_identity_sha256": release_identity,
        "transport_image_id": attempt.get("transport_image_id"),
        "tool_image_id": attempt.get("tool_image_id"),
        "transport_container_id": attempt.get("transport_container_id"),
        "tool_container_id": attempt.get("tool_container_id"),
        "model": attempt.get("model"),
        "provider_session_uuid": attempt.get("provider_session_uuid"),
        "max_turns": attempt.get("max_turns"),
        "actual_turns": attempt.get("actual_turns"),
        "stop_reason": attempt.get("stop_reason"),
        "argv_digest": attempt.get("argv_digest"),
        "mcp_event_hashes": list(attempt.get("mcp_event_hashes") or []),
        "prompt_material_cutoff": dict(prompt_material_cutoff or {}),
        "candidate_only": True,
        "shadow_write": False,
        "next_task_created": False,
        "disposition_written": False,
        "freeze_written": False,
        "settlement_written": False,
        "portfolio_updated": False,
        **authority_clamp(),
    }
    bundle_hash = _sha256_bytes(_canonical_bytes(bundle_body))
    bundle = dict(bundle_body)
    bundle["bundle_sha256"] = bundle_hash
    export_digest = write_cas_blob(root, "exports", _canonical_bytes(bundle))
    export_ptr = root / "exports" / "last_export.json"
    pointer = {
        "bundle_sha256": bundle_hash,
        "export_cas_digest": export_digest,
        "attempt_cas_digest": attempt_cas_digest,
        "episode_id": episode_id,
        "status": STATUS_CANDIDATE_EVIDENCE_EXPORTED,
    }
    # Idempotent: identical pointer content is fine; conflicting partial fails closed.
    if export_ptr.is_file():
        prior = json.loads(export_ptr.read_text(encoding="utf-8"))
        if (
            prior.get("attempt_cas_digest") == attempt_cas_digest
            and prior.get("bundle_sha256") not in {None, bundle_hash}
        ):
            raise NativeSessionError(
                "EXPORT_CONFLICT",
                f"prior={prior.get('bundle_sha256')} new={bundle_hash}",
            )
        if (
            prior.get("attempt_cas_digest") == attempt_cas_digest
            and prior.get("bundle_sha256") == bundle_hash
        ):
            return {
                **bundle,
                "export_cas_digest": export_digest,
                "idempotent": True,
                **authority_clamp(),
            }
    _write_json_atomic(export_ptr, pointer)
    return {
        **bundle,
        "export_cas_digest": export_digest,
        "idempotent": False,
        **authority_clamp(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Native Grok session contract probe/driver")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="Probe local Grok CLI + fail-closed live contract")
    p_plan = sub.add_parser("plan-new", help="Plan genuine new-session argv")
    p_plan.add_argument("--episode-id", required=True)
    p_plan.add_argument("--session-id", default=None)
    p_plan.add_argument("--work-root", type=Path, required=True)
    p_plan.add_argument("--prompt", default="native episode multi-turn lab task")
    p_res = sub.add_parser("plan-resume", help="Plan genuine resume argv")
    p_res.add_argument("--episode-id", required=True)
    p_res.add_argument("--session-id", required=True)
    p_res.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "probe":
        contract = fail_closed_live_invoke()
        _emit_json_stdout(contract)
        return 0
    session_id = getattr(args, "session_id", None) or new_session_uuid()
    driver = NativeEpisodeSessionDriver(
        episode_id=args.episode_id,
        session_id=session_id,
        grok_home=Path(args.work_root) / "grok-home",
        work_root=Path(args.work_root),
        grok_bin=resolve_grok_bin() or "/usr/local/bin/grok",
    )
    if args.cmd == "plan-new":
        _emit_json_stdout(driver.plan_new(prompt=args.prompt))
        return 0
    if args.cmd == "plan-resume":
        _emit_json_stdout(driver.plan_resume())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

