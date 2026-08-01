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

# Supported live CLI for ResearchEpisode dual-host path. Fail closed on mismatch.
SUPPORTED_GROK_CLI_VERSION = "0.2.117"
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
    "--always-approve",
)
MCP_SUBCOMMANDS = ("list", "add", "remove", "doctor")
# ResearchEpisode profiles (Owner-sealed).
PROFILE_OPEN_RESEARCH = "OPEN_RESEARCH"
PROFILE_CLOSED_LAB = "CLOSED_LAB"
PROFILE_INSTRUMENT_CANARY = "INSTRUMENT_CANARY"
DEFAULT_RESEARCH_PROFILE = PROFILE_OPEN_RESEARCH
# Grok 0.2.117: built-in meta-tools + web on OPEN_RESEARCH.
OPEN_RESEARCH_TOOLS_ALLOWLIST = "search_tool,use_tool,web_search,web_fetch"
CLOSED_LAB_TOOLS_ALLOWLIST = "search_tool,use_tool"
# Backward-compatible alias: default genuine = OPEN_RESEARCH.
GENUINE_TOOLS_ALLOWLIST = OPEN_RESEARCH_TOOLS_ALLOWLIST
CANARY_TOOLS_ALLOWLIST = ""
# Live research path: multi-turn budget must exceed canary one-shot.
MIN_LIVE_MAX_TURNS = 8
DEFAULT_LIVE_MAX_TURNS = 16
DEFAULT_LIVE_MODEL = "grok-4.5"
DEFAULT_OUTER_TIMEOUT_SECONDS = 3600
MAX_OUTER_TIMEOUT_SECONDS = 4 * 3600
CANONICAL_GROK_HOME = "/grok-home"
CANONICAL_LAB_CWD = "/episode-lab"
CANONICAL_MCP_EVENTS = "/output/mcp_events.jsonl"
CANONICAL_TOOL_SIDECAR_EVENTS = "/sidecar-evidence/tool_events.jsonl"
TOOL_SIDECAR_EVENTS_FILENAME = "tool_events.jsonl"
CANONICAL_AGENT_PROFILE = "/grok-home/agents/genuine_scientist_mcp.md"
EPISODE_LAB_MCP_ALLOW_RULE = "MCPTool(episode_lab__*)"
PRODUCTIVE_LAB_OPS = frozenset({"write_file", "shell_exec"})
# Tool-executor / MCP success vocabulary (only status==ok is a successful productive op).
TOOL_STATUS_OK = "ok"
TOOL_STATUS_NON_SUCCESS = frozenset({"denied", "error", "timeout", "malformed", "unknown"})
# Fixed lab path for sealed candidate body (tool path only).
# Schema/constants/validator body: package-owned research_episode_candidate_manifest.
CANDIDATE_MANIFEST_RELATIVE = "candidate/candidate_manifest.v1.json"
CANDIDATE_MANIFEST_SCHEMA = "xinao.research_episode_candidate_manifest.v1"
CANDIDATE_MANIFEST_MARKER = "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"
ACCOUNT_RECOMMENDATION_VALUES = frozenset(
    {
        "ACTION_CANDIDATE",
        "NO_ACTION_CANDIDATE",
        "NO_RECOMMENDATION",
    }
)


def is_successful_productive_status(status: object) -> bool:
    """Only an actually successful tool/MCP status may count as productive evidence."""
    if not isinstance(status, str):
        return False
    if status in TOOL_STATUS_NON_SUCCESS:
        return False
    return status == TOOL_STATUS_OK


def is_successful_productive_event(event: Mapping[str, Any]) -> bool:
    """Productive op AND successful status; never trust productive flag alone."""
    if not isinstance(event, Mapping):
        return False
    op = str(event.get("op") or "")
    if op not in PRODUCTIVE_LAB_OPS:
        return False
    return is_successful_productive_status(event.get("status"))


# Host control builtins stripped on all research profiles (web stripped only on CLOSED_LAB).
# Include live 0.2.117 ids (run_terminal_command, spawn_subagent) plus legacy aliases.
STRIPPED_HOST_BUILTINS = (
    "run_terminal_cmd",
    "run_terminal_command",
    "read_file",
    "search_replace",
    "grep",
    "list_dir",
    "todo_write",
    "task",
    "kill_task",
    "get_task_output",
    "memory_search",
    "memory_get",
    "lsp",
    "Agent",
    "spawn_subagent",
)
# Honest policy: Grok 0.2.117 can disable subagents via --no-subagents, and the only
# named spawn tool (spawn_subagent) is denied in --disallowed-tools. Claiming
# "episode-confined subagent role fitness" while spawn is stripped is false.
# Keep --no-subagents on all research profiles until a real lab-only subagent path exists.
OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS = False
OPEN_RESEARCH_SUBAGENT_POLICY_REASON = (
    "OPEN_RESEARCH keeps --no-subagents: spawn_subagent is physically denied in "
    "--disallowed-tools, host builtins remain stripped, and no lab-only subagent "
    "mount/agent profile is wired. Do not claim subagent role fitness."
)
# Default (OPEN_RESEARCH) does not strip web_search/web_fetch.
STRIPPED_BUILTINS = STRIPPED_HOST_BUILTINS
STRIPPED_BUILTINS_CLOSED_LAB = STRIPPED_HOST_BUILTINS + (
    "web_search",
    "web_fetch",
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


def normalize_research_profile(profile: str | None) -> str:
    if not profile:
        return DEFAULT_RESEARCH_PROFILE
    name = str(profile).strip().upper()
    if name in {"GENUINE_SCIENTIST_EPISODE", "GENUINE", "GENUINE_SCIENTIST"}:
        return PROFILE_OPEN_RESEARCH
    if name in {PROFILE_OPEN_RESEARCH, PROFILE_CLOSED_LAB, PROFILE_INSTRUMENT_CANARY}:
        return name
    raise NativeSessionError("UNKNOWN_RESEARCH_PROFILE", str(profile)[:80])


def tools_allowlist_csv(profile: str | None = None) -> str:
    name = normalize_research_profile(profile)
    if name == PROFILE_CLOSED_LAB:
        return CLOSED_LAB_TOOLS_ALLOWLIST
    if name == PROFILE_INSTRUMENT_CANARY:
        return CANARY_TOOLS_ALLOWLIST
    return OPEN_RESEARCH_TOOLS_ALLOWLIST


def stripped_builtins_csv(profile: str | None = None) -> str:
    name = normalize_research_profile(profile)
    if name == PROFILE_CLOSED_LAB:
        return ",".join(STRIPPED_BUILTINS_CLOSED_LAB)
    return ",".join(STRIPPED_BUILTINS)


def web_enabled_for_profile(profile: str | None = None) -> bool:
    return normalize_research_profile(profile) == PROFILE_OPEN_RESEARCH


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


def parse_grok_cli_version(version_text: str | None) -> str | None:
    """Extract x.y.z from `grok version` output."""
    if not version_text:
        return None
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", str(version_text))
    return match.group(1) if match else None


def require_supported_grok_cli_version(version_text: str | None) -> str:
    """Fail closed when installed CLI is not the release-supported version."""
    parsed = parse_grok_cli_version(version_text)
    if parsed != SUPPORTED_GROK_CLI_VERSION:
        raise NativeSessionError(
            "GROK_CLI_VERSION_UNSUPPORTED",
            f"required={SUPPORTED_GROK_CLI_VERSION} observed={version_text!r}",
        )
    return parsed


def probe_grok_cli(
    *,
    grok_bin: str | None = None,
    probe_auth: bool = True,
    require_supported_version: bool = False,
) -> CliProbe:
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
    if require_supported_version:
        try:
            require_supported_grok_cli_version(probe.version)
        except NativeSessionError as exc:
            probe.auth_error = f"{exc.reason_code}:{exc.detail}"
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
    research_profile: str | None = None,
    extra: Sequence[str] | None = None,
) -> list[str]:
    """Exact native Grok argv for dual-container multi-turn MCP ResearchEpisode.

    Session rules (CLI 0.2.117):
    - New conversation: --session-id <UUID> (must not already exist).
    - Resume exact session: --resume <SESSION_ID_OR_TITLE>.
    - Continue most recent in cwd: --continue (mutually exclusive with new id).
    - MCP lab ops arrive via GROK_HOME config.toml [mcp_servers.episode_lab];
      --tools allowlists Grok built-in meta-tools (+ web on OPEN_RESEARCH).
    - Host file/shell builtins stripped via --disallowed-tools and agent profile.
    - OPEN_RESEARCH: no --disable-web-search; CLOSED_LAB: disable web.
    - --cwd defaults to mounted lab path /episode-lab.
    - Headless trigger (CLI 0.2.117): prompt must use -p/--single or
      --prompt-file/--prompt-json. A bare positional PROMPT starts the
      interactive TUI, which opens /dev/tty and fails under no-TTY docker exec
      with ``Error: No such device or address (os error 6)``.
    """
    profile = normalize_research_profile(research_profile)
    if profile == PROFILE_INSTRUMENT_CANARY:
        raise NativeSessionError(
            "CANARY_ON_GENUINE_PATH",
            "use build_canary_argv for INSTRUMENT_CANARY",
        )
    if continue_latest and resume:
        raise NativeSessionError(
            "ARGV_CONFLICT",
            "--continue and --resume are mutually exclusive with explicit dual use",
        )
    if continue_latest and session_id:
        raise NativeSessionError(
            "ARGV_CONFLICT",
            "--continue cannot bind an exact session_id; use --resume for exact identity",
        )
    if not continue_latest and not session_id:
        raise NativeSessionError("SESSION_ID_REQUIRED", "session_id empty")
    if not resume and not continue_latest and not is_uuid(session_id):
        raise NativeSessionError(
            "SESSION_ID_NOT_UUID",
            f"--session-id requires UUID, got {session_id[:64]!r}",
        )
    if max_turns < 2:
        raise NativeSessionError(
            "MAX_TURNS_TOO_LOW",
            "genuine multi-turn episode requires max_turns >= 2 (canary uses 1)",
        )
    tools_csv = tools_allowlist_csv(profile)
    # Headless MCP productivity: trust only the already-isolated episode cwd and
    # explicitly allow its single attempt-local MCP server.  Grok 0.2.117 otherwise
    # discovers the project-scoped server but refuses to start it for an untrusted
    # folder; dontAsk also requires an explicit allow rule for MCP writes.
    effective_permission = permission_mode
    argv: list[str] = [
        grok_bin,
        "--model",
        model,
        "--output-format",
        "json",
        "--no-memory",
        "--max-turns",
        str(int(max_turns)),
        "--permission-mode",
        effective_permission,
        "--always-approve",
        "--trust",
        "--allow",
        EPISODE_LAB_MCP_ALLOW_RULE,
        "--tools",
        tools_csv,
    ]
    # Honest policy: keep --no-subagents on all research profiles (including OPEN_RESEARCH).
    if profile != PROFILE_OPEN_RESEARCH or not OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS:
        argv.insert(argv.index("--no-memory"), "--no-subagents")
    # CLOSED_LAB / non-open profiles hard-disable web; OPEN_RESEARCH must not.
    if not web_enabled_for_profile(profile):
        argv.append("--disable-web-search")
    if include_disallowed_builtins:
        argv.extend(["--disallowed-tools", stripped_builtins_csv(profile)])
    resolved_agent = agent_profile if agent_profile is not None else CANONICAL_AGENT_PROFILE
    if resolved_agent:
        argv.extend(["--agent", str(resolved_agent)])
    resolved_cwd = cwd if cwd is not None else CANONICAL_LAB_CWD
    if resolved_cwd:
        argv.extend(["--cwd", str(resolved_cwd)])
    if prompt_file:
        argv.extend(["--prompt-file", str(prompt_file)])
    if resume:
        argv.extend(["--resume", session_id])
    elif continue_latest:
        argv.append("--continue")
    else:
        argv.extend(["--session-id", session_id])
    if prompt and not prompt_file:
        # Must be -p/--single (headless). Positional PROMPT is TUI-only.
        argv.extend(["-p", prompt])
    if extra:
        argv.extend(list(extra))
    return argv


def assert_argv_is_genuine_not_canary(
    argv: Sequence[str],
    *,
    research_profile: str | None = None,
) -> None:
    joined = list(argv)
    profile = normalize_research_profile(research_profile)
    if "--tools" not in joined:
        raise NativeSessionError("GENUINE_ARGV_MISSING_TOOLS", "no --tools")
    tools_val = joined[joined.index("--tools") + 1]
    expected = tools_allowlist_csv(profile)
    if tools_val != expected:
        raise NativeSessionError(
            "GENUINE_TOOLS_MISMATCH",
            f"profile={profile} expected {expected!r} got {tools_val!r}",
        )
    if "--max-turns" in joined:
        mt = int(joined[joined.index("--max-turns") + 1])
        if mt < 2:
            raise NativeSessionError("GENUINE_MAX_TURNS_CANARY_SHAPED", str(mt))
    if tools_val == "":
        raise NativeSessionError("CANARY_ARGV_ON_GENUINE_PATH", "empty tools")
    # OPEN_RESEARCH may omit --no-subagents (episode-confined; host tools stripped).
    # CLOSED_LAB / non-open profiles must keep --no-subagents.
    if profile != PROFILE_OPEN_RESEARCH or not OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS:
        if "--no-subagents" not in joined:
            raise NativeSessionError(
                "GENUINE_ARGV_SUBAGENTS_NOT_DISABLED",
                "missing --no-subagents",
            )


def assert_live_research_argv(
    argv: Sequence[str],
    *,
    min_turns: int = MIN_LIVE_MAX_TURNS,
    research_profile: str | None = None,
) -> None:
    """Fail closed for empty tools, canary one-turn, host-bypass builtins, low budget.

    OPEN_RESEARCH must NOT pass --disable-web-search and must allow web builtins.
    CLOSED_LAB must disable web and strip web builtins.
    OPEN_RESEARCH may omit --no-subagents when episode-confined subagents are allowed.
    """
    profile = normalize_research_profile(research_profile)
    assert_argv_is_genuine_not_canary(argv, research_profile=profile)
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
    if "--always-approve" not in joined:
        raise NativeSessionError(
            "LIVE_ALWAYS_APPROVE_MISSING",
            "headless MCP productivity requires --always-approve",
        )
    if "--trust" not in joined:
        raise NativeSessionError(
            "LIVE_EPISODE_TRUST_MISSING",
            "project-scoped episode_lab MCP requires exact episode cwd trust",
        )
    allow_rules = [
        str(joined[index + 1])
        for index, value in enumerate(joined[:-1])
        if value == "--allow"
    ]
    if EPISODE_LAB_MCP_ALLOW_RULE not in allow_rules:
        raise NativeSessionError(
            "LIVE_EPISODE_MCP_ALLOW_MISSING",
            EPISODE_LAB_MCP_ALLOW_RULE,
        )
    if web_enabled_for_profile(profile):
        if "--disable-web-search" in joined:
            raise NativeSessionError(
                "OPEN_RESEARCH_WEB_DISABLED",
                "OPEN_RESEARCH must not pass --disable-web-search",
            )
        if profile == PROFILE_OPEN_RESEARCH and OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS:
            if "--no-subagents" in joined:
                raise NativeSessionError(
                    "OPEN_RESEARCH_SUBAGENTS_HARD_DISABLED",
                    OPEN_RESEARCH_SUBAGENT_POLICY_REASON,
                )
    else:
        if "--disable-web-search" not in joined:
            raise NativeSessionError(
                "LIVE_WEB_BYPASS_NOT_DISABLED",
                "CLOSED_LAB missing --disable-web-search",
            )
        if "--no-subagents" not in joined:
            raise NativeSessionError(
                "GENUINE_ARGV_SUBAGENTS_NOT_DISABLED",
                "CLOSED_LAB missing --no-subagents",
            )
    if "--disallowed-tools" not in joined:
        raise NativeSessionError("LIVE_BUILTINS_NOT_STRIPPED", "missing --disallowed-tools")
    denied = joined[joined.index("--disallowed-tools") + 1]
    for required in (
        "run_terminal_cmd",
        "run_terminal_command",
        "read_file",
        "spawn_subagent",
    ):
        if required not in denied:
            raise NativeSessionError("LIVE_BUILTIN_STRIP_INCOMPLETE", required)
    if web_enabled_for_profile(profile):
        if "web_search" in denied or "web_fetch" in denied:
            raise NativeSessionError(
                "OPEN_RESEARCH_WEB_STRIPPED",
                "OPEN_RESEARCH must not deny web_search/web_fetch",
            )
        tools_val = joined[joined.index("--tools") + 1]
        for need in ("search_tool", "use_tool", "web_search", "web_fetch"):
            if need not in tools_val:
                raise NativeSessionError("OPEN_RESEARCH_TOOLS_INCOMPLETE", need)
    else:
        for required in ("web_search", "web_fetch"):
            if required not in denied:
                raise NativeSessionError("CLOSED_LAB_WEB_STRIP_INCOMPLETE", required)
    if "--cwd" in joined:
        cwd = joined[joined.index("--cwd") + 1]
        if str(cwd).replace("\\", "/").rstrip("/") != CANONICAL_LAB_CWD:
            raise NativeSessionError("LIVE_CWD_MISALIGNED", cwd)
    # Live attach under docker exec has no controlling TTY. Grok 0.2.117 headless
    # mode is entered only via -p/--single/--prompt-file/--prompt-json. A bare
    # positional PROMPT opens interactive TUI → ENXIO on /dev/tty (os error 6).
    value_taking_flags = {
        "--model",
        "--max-turns",
        "--tools",
        "--disallowed-tools",
        "--agent",
        "--cwd",
        "--session-id",
        "--resume",
        "--permission-mode",
        "--output-format",
        "--prompt-file",
        "--prompt-json",
        "-p",
        "--single",
        "--json-schema",
        "--rules",
        "--system-prompt-override",
        "--debug-file",
        "--allow",
        "--deny",
    }
    if joined:
        last = str(joined[-1])
        if last and not last.startswith("-"):
            prev = str(joined[-2]) if len(joined) >= 2 else ""
            if prev not in value_taking_flags:
                raise NativeSessionError(
                    "LIVE_TUI_POSITIONAL_PROMPT",
                    "bare positional PROMPT is interactive TUI; use -p/--single "
                    "or --prompt-file/--prompt-json for no-TTY docker exec",
                )


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
    hash_key: str = "event_hash",
    verify_self_hash: bool = True,
) -> None:
    """Tool-event fabrication: claimed hash must be on the trusted tool-side chain.

    For tool-executor IPC responses, hash_key is ``event_hash`` and the body self-hash
    is verified. For MCP evidence lines, pass ``hash_key="sidecar_event_hash"`` and
    ``verify_self_hash=False`` so membership checks the tool-sealed identity, not the
    forgeable transport JSONL self-hash alone.
    """
    if not isinstance(event, Mapping):
        raise NativeSessionError("TOOL_EVENT_INVALID", "not object")
    claimed = event.get(hash_key)
    if not isinstance(claimed, str) or HEX_SHA256.fullmatch(claimed) is None:
        raise NativeSessionError("TOOL_EVENT_HASH_MISSING", f"{hash_key}={claimed}")
    trusted = set(trusted_event_hashes)
    if verify_self_hash:
        body = {k: v for k, v in event.items() if k != hash_key}
        observed = _sha256_bytes(_canonical_bytes(body))
        if claimed != observed:
            raise NativeSessionError(
                "TOOL_EVENT_FABRICATED",
                f"claimed={claimed} observed={observed}",
            )
    if claimed not in trusted:
        raise NativeSessionError(
            "TOOL_EVENT_UNTRUSTED",
            f"{hash_key} not in trusted tool-side event chain",
        )


def collect_tool_sidecar_evidence_delta(
    path: Path | str,
    prior_cursor: Mapping[str, Any] | None,
    *,
    expected_episode_id: str | None = None,
) -> dict[str, Any]:
    """Cursor-bounded read of tool-executor-only evidence (not transport-writable).

    ``events`` retains the full audit delta. ``trusted_event_hashes`` /
    ``successful_productive_event_hashes`` are success-only productive membership
    sets used by live attach/resume gates (denied/error/timeout never enter).
    """
    evidence = Path(path)
    prior_size = int((prior_cursor or {}).get("size") or 0)
    if not evidence.is_file():
        return {
            "events": [],
            "trusted_event_hashes": [],
            "successful_productive_event_hashes": [],
            "all_event_hashes": [],
            "status": "EMPTY_DELTA",
            "prior_size": prior_size,
            "new_size": 0,
        }
    raw = evidence.read_bytes()
    new_size = len(raw)
    if new_size < prior_size:
        raise NativeSessionError(
            "TOOL_SIDECAR_TRUNCATED",
            f"prior={prior_size} now={new_size}",
        )
    delta = raw[prior_size:]
    events: list[dict[str, Any]] = []
    all_hashes: list[str] = []
    productive_hashes: list[str] = []
    if not delta:
        return {
            "events": [],
            "trusted_event_hashes": [],
            "successful_productive_event_hashes": [],
            "all_event_hashes": [],
            "status": "STALE_ONLY" if prior_size > 0 else "EMPTY_DELTA",
            "prior_size": prior_size,
            "new_size": new_size,
        }
    text = delta.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise NativeSessionError("TOOL_SIDECAR_JSON_INVALID", str(exc)[:200]) from exc
        if not isinstance(obj, dict):
            raise NativeSessionError("TOOL_SIDECAR_JSON_INVALID", "object required")
        if expected_episode_id is not None and obj.get("episode_id") not in {
            None,
            expected_episode_id,
        }:
            if obj.get("episode_id") != expected_episode_id:
                raise NativeSessionError(
                    "TOOL_SIDECAR_FOREIGN_EPISODE",
                    str(obj.get("episode_id")),
                )
        event_hash = obj.get("event_hash")
        if isinstance(event_hash, str) and HEX_SHA256.fullmatch(event_hash):
            all_hashes.append(event_hash)
            # Trusted productivity set is success-only; audit retains all events.
            if is_successful_productive_event(obj):
                productive_hashes.append(event_hash)
        events.append(obj)
    status = "DELTA_OK" if events else "EMPTY_DELTA"
    return {
        "events": events,
        "trusted_event_hashes": list(productive_hashes),
        "successful_productive_event_hashes": list(productive_hashes),
        "all_event_hashes": list(all_hashes),
        "status": status,
        "prior_size": prior_size,
        "new_size": new_size,
    }


def capture_tool_sidecar_cursor(path: Path | str) -> dict[str, Any]:
    evidence = Path(path)
    if not evidence.is_file():
        return {"size": 0, "path": str(evidence)}
    return {"size": evidence.stat().st_size, "path": str(evidence)}


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
        "mcp_tools_allowlist": OPEN_RESEARCH_TOOLS_ALLOWLIST,
        "research_profile_default": DEFAULT_RESEARCH_PROFILE,
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
        profile = normalize_research_profile(
            str(binding.get("research_profile") or DEFAULT_RESEARCH_PROFILE)
        )
        argv = build_genuine_session_argv(
            grok_bin=self.grok_bin,
            session_id=self.session_id,
            resume=False,
            model=self.model,
            max_turns=self.max_turns,
            prompt=prompt,
            agent_profile=CANONICAL_AGENT_PROFILE,
            research_profile=profile,
            cwd=CANONICAL_LAB_CWD,
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
            "research_profile": profile,
            "env": {
                "GROK_HOME": CANONICAL_GROK_HOME,
                "XINAO_MCP_BINDING": "1",
                "XINAO_MCP_SERVER": "episode_lab",
                "XINAO_MCP_TOOLS": tools_allowlist_csv(profile),
                "XINAO_MCP_EVENT_LOG": CANONICAL_MCP_EVENTS,
                "XINAO_RESEARCH_PROFILE": profile,
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
            research_profile=DEFAULT_RESEARCH_PROFILE,
            cwd=CANONICAL_LAB_CWD,
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
            if any(marker in key_part or marker in key_norm for marker in SECRET_ARGV_MARKERS):
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


def capture_mcp_event_cursor(path: Path) -> dict[str, Any]:
    """Capture size/head of MCP event file before attach/resume."""
    p = Path(path)
    if not p.is_file():
        return {
            "path": str(p),
            "exists": False,
            "size": 0,
            "line_count": 0,
            "head_sha256": None,
            "tail_sha256": None,
        }
    raw = p.read_bytes()
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    head = raw[:64] if raw else b""
    tail = raw[-64:] if raw else b""
    return {
        "path": str(p),
        "exists": True,
        "size": len(raw),
        "line_count": len(lines),
        "head_sha256": _sha256_bytes(head) if head else None,
        "tail_sha256": _sha256_bytes(tail) if tail else None,
        "full_sha256": _sha256_bytes(raw),
    }


def collect_attempt_mcp_delta(
    path: Path,
    prior_cursor: Mapping[str, Any] | None,
    *,
    expected_episode_id: str | None = None,
) -> dict[str, Any]:
    """Bind only appended MCP event delta from this attempt; reject truncation/stale."""
    p = Path(path)
    prior = dict(prior_cursor or {})
    prior_size = int(prior.get("size") or 0)
    prior_head = prior.get("head_sha256")
    prior_full = prior.get("full_sha256")
    if not p.is_file():
        if prior_size > 0:
            raise NativeSessionError("MCP_EVENT_FILE_MISSING", str(p))
        return {
            "events": [],
            "mcp_event_hashes": [],
            "productive_ops": [],
            "delta_bytes": 0,
            "status": "EMPTY_DELTA",
        }
    raw = p.read_bytes()
    if prior_size > 0:
        if len(raw) < prior_size:
            raise NativeSessionError(
                "MCP_EVENT_TRUNCATED",
                f"size {len(raw)} < prior {prior_size}",
            )
        head = raw[:64] if raw else b""
        if prior_head and _sha256_bytes(head) != prior_head:
            raise NativeSessionError("MCP_EVENT_REWRITTEN", "head sha256 mismatch")
        if prior_full and len(raw) == prior_size and _sha256_bytes(raw) == prior_full:
            return {
                "events": [],
                "mcp_event_hashes": [],
                "productive_ops": [],
                "delta_bytes": 0,
                "status": "STALE_ONLY",
            }
        delta = raw[prior_size:]
    else:
        delta = raw
    events: list[dict[str, Any]] = []
    hashes: list[str] = []
    productive: list[str] = []
    for line in delta.splitlines():
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            raise NativeSessionError("MCP_EVENT_MALFORMED", str(exc)[:200]) from exc
        if not isinstance(event, dict):
            raise NativeSessionError("MCP_EVENT_MALFORMED", "not object")
        if expected_episode_id is not None:
            eid = event.get("episode_id")
            if eid is not None and str(eid) != str(expected_episode_id):
                raise NativeSessionError(
                    "MCP_EVENT_FOREIGN_EPISODE",
                    f"event={eid} expected={expected_episode_id}",
                )
        claimed = event.get("event_hash")
        body = {k: v for k, v in event.items() if k != "event_hash"}
        observed = _sha256_bytes(_canonical_bytes(body))
        if isinstance(claimed, str) and HEX_SHA256.fullmatch(claimed):
            if claimed != observed:
                raise NativeSessionError(
                    "MCP_EVENT_HASH_MISMATCH",
                    f"claimed={claimed} observed={observed}",
                )
            hashes.append(claimed)
        else:
            hashes.append(observed)
            event = {**event, "event_hash": observed}
        # Success-only: never count denied/error/timeout/malformed/unknown, even if
        # event.productive is True or a lab file was planted.
        if is_successful_productive_event(event):
            productive.append(str(event.get("op") or ""))
        events.append(event)
    status = "DELTA_OK" if events else "EMPTY_DELTA"
    if prior_size > 0 and not events:
        status = "STALE_ONLY"
    return {
        "events": events,
        "mcp_event_hashes": hashes,
        "productive_ops": productive,
        "delta_bytes": len(delta),
        "status": status,
        "prior_size": prior_size,
        "new_size": len(raw),
    }


def require_productive_lab_delta(
    delta: Mapping[str, Any],
    *,
    trusted_event_hashes: Sequence[str] | None = None,
    require_trusted_tool_chain: bool = False,
) -> None:
    """Success requires at least one write_file/shell_exec from this attempt delta.

    JSONL self-hash alone is insufficient: each productive event must carry a
    non-empty sidecar_event_hash from the tool-executor response. When
    ``require_trusted_tool_chain`` is true (live attach/resume), each
    sidecar_event_hash must be a member of the tool-executor-only evidence log.
    """
    status = str(delta.get("status") or "")
    if status in {"STALE_ONLY", "EMPTY_DELTA"}:
        raise NativeSessionError("MCP_DELTA_STALE_OR_EMPTY", status)
    productive = list(delta.get("productive_ops") or [])
    if not productive:
        events = list(delta.get("events") or [])
        kinds = [str(e.get("event") or e.get("op") or "") for e in events if isinstance(e, dict)]
        raise NativeSessionError(
            "PRODUCTIVE_LAB_OP_MISSING",
            f"events={kinds[:12]}",
        )
    events = [e for e in (delta.get("events") or []) if isinstance(e, dict)]
    # Success-only bodies; never accept productive=True with failed/denied/timeout status.
    productive_events = [e for e in events if is_successful_productive_event(e)]
    if not productive_events:
        raise NativeSessionError("PRODUCTIVE_LAB_EVENT_MISSING", "no productive event bodies")
    trusted = list(trusted_event_hashes or [])
    if require_trusted_tool_chain and not trusted:
        raise NativeSessionError(
            "TOOL_EVENT_UNTRUSTED",
            "trusted tool-side event set empty",
        )
    for event in productive_events:
        sidecar = event.get("sidecar_event_hash")
        if not isinstance(sidecar, str) or HEX_SHA256.fullmatch(sidecar) is None:
            raise NativeSessionError(
                "PRODUCTIVE_SIDECAR_HASH_MISSING",
                f"op={event.get('op')} missing tool-sidecar event_hash",
            )
        claimed = event.get("event_hash")
        if isinstance(claimed, str) and HEX_SHA256.fullmatch(claimed):
            body = {k: v for k, v in event.items() if k != "event_hash"}
            observed = _sha256_bytes(_canonical_bytes(body))
            if claimed != observed:
                raise NativeSessionError(
                    "TOOL_EVENT_FABRICATED",
                    f"claimed={claimed} observed={observed}",
                )
        if require_trusted_tool_chain or trusted:
            reject_fabricated_tool_event(
                event=event,
                trusted_event_hashes=trusted,
                hash_key="sidecar_event_hash",
                verify_self_hash=False,
            )


def _normalize_lab_rel_path(rel_raw: object) -> str | None:
    if not isinstance(rel_raw, str) or not rel_raw.strip():
        return None
    return str(rel_raw).replace("\\", "/").lstrip("./")


def _content_digest_from_effect_identity(effect_identity: object) -> str | None:
    """Extract content sha256 from tool effect_identity forms when present."""
    if not isinstance(effect_identity, str) or not effect_identity.strip():
        return None
    text = effect_identity.strip()
    # write_file form: write:{rel}:{content_sha}
    if text.startswith("write:"):
        parts = text.split(":")
        if len(parts) >= 3:
            digest = parts[-1]
            if HEX_SHA256.fullmatch(digest):
                return digest
    if HEX_SHA256.fullmatch(text):
        return text
    return None


def require_lab_effect_binding(
    *,
    delta: Mapping[str, Any],
    lab_artifact_manifest: Mapping[str, Any] | None,
    prior_lab_artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind successful productive MCP ops to real lab filesystem effects.

    write_file with a path-bearing event must bind the exact normalized path (and
    content/effect hash when recorded). Broad “any changed path” is not accepted
    for path-bearing write events. shell_exec requires successful status and
    honest lab effect evidence; timeout is never productive.
    """
    artifacts = list((lab_artifact_manifest or {}).get("artifacts") or [])
    current_paths = {
        str(a.get("path")).replace("\\", "/").lstrip("./"): str(a.get("sha256") or "")
        for a in artifacts
        if isinstance(a, Mapping) and a.get("path")
    }
    prior_paths = {
        str(a.get("path")).replace("\\", "/").lstrip("./"): str(a.get("sha256") or "")
        for a in list((prior_lab_artifact_manifest or {}).get("artifacts") or [])
        if isinstance(a, Mapping) and a.get("path")
    }
    changed = sorted(p for p, digest in current_paths.items() if prior_paths.get(p) != digest)
    events = [e for e in (delta.get("events") or []) if isinstance(e, dict)]
    productive_events = [e for e in events if is_successful_productive_event(e)]
    if not productive_events:
        if list(delta.get("productive_ops") or []):
            raise NativeSessionError(
                "LAB_EFFECT_MISSING",
                "productive ops claimed without successful productive event bodies",
            )
        return {
            "changed_paths": changed,
            "bound": False,
            "write_bound": False,
            "shell_bound": False,
        }
    write_bound = False
    shell_bound = False
    for event in productive_events:
        op = str(event.get("op") or "")
        if op == "write_file":
            rel = _normalize_lab_rel_path(
                event.get("path_relative") or event.get("path") or event.get("lab_path")
            )
            if not rel:
                raise NativeSessionError(
                    "LAB_EFFECT_WRITE_UNBOUND",
                    "write_file event missing path_relative; refuse any-changed fallback",
                )
            if rel not in current_paths:
                raise NativeSessionError(
                    "LAB_EFFECT_WRITE_UNBOUND",
                    f"write_file path not in lab artifacts path={rel!r}",
                )
            current_digest = current_paths.get(rel) or ""
            if prior_paths.get(rel) == current_digest:
                raise NativeSessionError(
                    "LAB_EFFECT_WRITE_UNBOUND",
                    f"write_file path present but unchanged path={rel!r}",
                )
            expected_content = _content_digest_from_effect_identity(
                event.get("effect_identity") or event.get("content_sha256")
            )
            if (
                expected_content is not None
                and current_digest
                and current_digest != expected_content
            ):
                raise NativeSessionError(
                    "LAB_EFFECT_WRITE_HASH_MISMATCH",
                    f"path={rel!r} lab={current_digest} event={expected_content}",
                )
            write_bound = True
        elif op == "shell_exec":
            # Only successful shell_exec reaches here (status==ok). Timeout/error excluded.
            if event.get("lab_effect") is True:
                shell_bound = True
            elif changed:
                shell_bound = True
            elif current_paths and not prior_paths:
                # First attempt may only create via shell; allow non-empty lab.
                shell_bound = True
            else:
                raise NativeSessionError(
                    "LAB_EFFECT_SHELL_UNBOUND",
                    "shell_exec without lab artifact delta or effect marker",
                )
    if not write_bound and not shell_bound and productive_events:
        raise NativeSessionError("LAB_EFFECT_MISSING", "no bound lab effect")
    return {
        "changed_paths": changed,
        "bound": True,
        "write_bound": write_bound,
        "shell_bound": shell_bound,
    }


def extract_web_use_trace(parsed: Mapping[str, Any] | None) -> dict[str, Any]:
    """Best-effort web-use trace from provider machine output; never fabricate."""
    if not parsed:
        return {"web_use_observed": None, "web_search_requests": None, "actual_turns": None}
    actual_turns = parsed.get("actual_turns")
    web_search_requests = None
    web_use_observed = None
    for record in parsed.get("records") or []:
        if not isinstance(record, dict):
            continue
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        stu = usage.get("server_tool_use") if isinstance(usage.get("server_tool_use"), dict) else {}
        if "web_search_requests" in stu:
            try:
                web_search_requests = int(stu["web_search_requests"])
                web_use_observed = web_search_requests > 0
            except (TypeError, ValueError):
                pass
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("name") == "web_search":
                    web_use_observed = True
    return {
        "web_use_observed": web_use_observed,
        "web_search_requests": web_search_requests,
        "actual_turns": actual_turns,
    }


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

    session_raw = _pick(("session_id", "sessionId", "session_uuid", "conversation_id", "id"))
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
    research_profile: str | None = None,
    productive_lab_ops: Sequence[str] | None = None,
    mcp_delta_status: str | None = None,
    web_use_trace: Mapping[str, Any] | None = None,
    require_productive_lab_op: bool = True,
) -> dict[str, Any]:
    """Assemble attempt evidence. Does not claim success if provider/plumbing failed."""
    profile = normalize_research_profile(research_profile)
    reject_non_live_driver(
        synthetic=synthetic,
        driver=driver,
        planned_only=not live_executed,
        host_fallback="host" in driver.lower() and "docker" not in driver.lower(),
    )
    assert_live_research_argv(list(argv), research_profile=profile)
    redacted = redact_argv(argv)
    stdout_sha = _sha256_bytes(stdout)
    stderr_sha = _sha256_bytes(stderr)
    tool_trace_sha = _sha256_bytes(_canonical_bytes({"mcp_event_hashes": list(mcp_event_hashes)}))
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
            success_gates_ok = False
            failure_reasons.append("MCP_EVENTS_MISSING")
        if require_productive_lab_op:
            productive = [
                str(x) for x in (productive_lab_ops or []) if str(x) in PRODUCTIVE_LAB_OPS
            ]
            if not productive:
                success_gates_ok = False
                failure_reasons.append("PRODUCTIVE_LAB_OP_MISSING")
            if mcp_delta_status in {"STALE_ONLY", "EMPTY_DELTA"}:
                success_gates_ok = False
                failure_reasons.append(f"MCP_DELTA_{mcp_delta_status}")
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
        "research_profile": profile,
        "web_enabled": web_enabled_for_profile(profile),
        "productive_lab_ops": list(productive_lab_ops or []),
        "mcp_delta_status": mcp_delta_status,
        "web_use_trace": dict(web_use_trace or extract_web_use_trace(parsed)),
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
    if (
        not attempt.get("raw_stdout_sha256")
        or HEX_SHA256.fullmatch(str(attempt.get("raw_stdout_sha256"))) is None
    ):
        raise NativeSessionError("RAW_STDOUT_MISSING", "hash")
    if not attempt.get("mcp_event_hashes"):
        raise NativeSessionError("MCP_EVENTS_MISSING", "empty tool trace")
    productive = [
        str(x) for x in (attempt.get("productive_lab_ops") or []) if str(x) in PRODUCTIVE_LAB_OPS
    ]
    if not productive:
        raise NativeSessionError("PRODUCTIVE_LAB_OP_MISSING", "export")
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


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    try:
        import stat as _stat

        st = path.lstat()
        # Windows reparse point bit (IO_REPARSE_TAG) surfaces as FILE_ATTRIBUTE_REPARSE_POINT.
        if getattr(st, "st_file_attributes", 0) & 0x400:
            return True
        if _stat.S_ISLNK(st.st_mode):
            return True
    except OSError:
        return True
    return False


def load_lab_candidate_manifest_bytes(
    *,
    lab_root: Path,
    relative_path: str = CANDIDATE_MANIFEST_RELATIVE,
) -> bytes:
    """Read exact lab bytes for the sealed candidate manifest; refuse aliases/symlinks."""
    root = Path(lab_root).resolve()
    rel = str(relative_path or CANDIDATE_MANIFEST_RELATIVE).replace("\\", "/").lstrip("/")
    if rel != CANDIDATE_MANIFEST_RELATIVE:
        raise NativeSessionError(
            "CANDIDATE_MANIFEST_PATH_FORBIDDEN",
            f"only fixed path {CANDIDATE_MANIFEST_RELATIVE} accepted, got {rel}",
        )
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise NativeSessionError("CANDIDATE_MANIFEST_ESCAPE", str(path)) from exc
    if _is_reparse_or_symlink(path) or any(
        _is_reparse_or_symlink(parent)
        for parent in path.parents
        if str(parent).startswith(str(root))
    ):
        raise NativeSessionError("CANDIDATE_MANIFEST_SYMLINK_REFUSED", str(path))
    if not path.is_file():
        raise NativeSessionError("CANDIDATE_MANIFEST_MISSING", str(path))
    return path.read_bytes()


def _load_package_candidate_manifest_module() -> Any:
    """Load package-owned pure validator (exact source of truth; no rule fork)."""
    # 1) Normal installed / PYTHONPATH package import.
    try:
        import xinao.science.research_episode_candidate_manifest as package_mod

        return package_mod
    except ImportError:
        pass
    # 2) Image sibling COPY of the same package file next to this module.
    sibling = Path(__file__).resolve().parent / "research_episode_candidate_manifest.py"
    if sibling.is_file():
        name = "xinao_research_episode_candidate_manifest_image"
        if name in sys.modules:
            return sys.modules[name]
        import importlib.util

        spec = importlib.util.spec_from_file_location(name, sibling)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
    # 3) Monorepo layout: docker/... -> repo/xinao_discovery/src
    for parent in Path(__file__).resolve().parents:
        candidate = (
            parent
            / "xinao_discovery"
            / "src"
            / "xinao"
            / "science"
            / "research_episode_candidate_manifest.py"
        )
        if candidate.is_file():
            src_root = str(candidate.parents[2])  # .../xinao_discovery/src
            if src_root not in sys.path:
                sys.path.insert(0, src_root)
            import xinao.science.research_episode_candidate_manifest as package_mod

            return package_mod
    raise NativeSessionError(
        "CANDIDATE_VALIDATOR_UNAVAILABLE",
        "package research_episode_candidate_manifest not importable",
    )


def validate_candidate_manifest(
    payload: Mapping[str, Any] | bytes,
    *,
    expected_episode_id: str | None = None,
    expected_attempt_cas_digest: str | None = None,
) -> dict[str, Any]:
    """Thin re-export of package-owned pure validator (no second rule body)."""
    package_mod = _load_package_candidate_manifest_module()
    try:
        return package_mod.validate_candidate_manifest(
            payload,
            expected_episode_id=expected_episode_id,
            expected_attempt_cas_digest=expected_attempt_cas_digest,
        )
    except Exception as exc:
        reason = getattr(exc, "reason_code", None)
        detail = getattr(exc, "detail", None)
        if isinstance(reason, str) and reason:
            raise NativeSessionError(reason, str(detail or exc)[:2000]) from exc
        raise NativeSessionError("CANDIDATE_MANIFEST_INVALID", str(exc)[:2000]) from exc


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
    lab_root: Path | None = None,
    candidate_manifest_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Export closed-schema candidate-only bundle from canonical attempt CAS.

    Derives identities from stored attempt evidence; rejects forged caller hashes.
    Requires lab-authored candidate manifest bytes (exact lab path or pre-read
    bytes that must match lab). Idempotent for identical inputs; never writes
    shadow/adoption/freeze state.
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
    if (
        expected_pair_receipt_sha256
        and attempt.get("pair_receipt_sha256") != expected_pair_receipt_sha256
    ):
        raise NativeSessionError("PAIR_RECEIPT_MISMATCH", "export")
    if (
        expected_namespace_receipt_sha256
        and attempt.get("namespace_receipt_sha256") != expected_namespace_receipt_sha256
    ):
        raise NativeSessionError("NAMESPACE_RECEIPT_MISMATCH", "export")
    if (
        expected_transport_image_id
        and attempt.get("transport_image_id") != expected_transport_image_id
    ):
        raise NativeSessionError("TRANSPORT_IMAGE_MISMATCH", "export")
    if expected_tool_image_id and attempt.get("tool_image_id") != expected_tool_image_id:
        raise NativeSessionError("TOOL_IMAGE_MISMATCH", "export")
    # Caller package identity must not override attempt-sealed identity when present.
    release_id = attempt.get("release_id") or package_release_id
    release_identity = attempt.get("release_identity_sha256") or package_release_identity_sha256
    if (
        package_release_id
        and attempt.get("release_id")
        and package_release_id != attempt.get("release_id")
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
    # Candidate manifest: exact lab bytes after productive attempt (not host-forged).
    if lab_root is None and candidate_manifest_bytes is None:
        raise NativeSessionError(
            "CANDIDATE_MANIFEST_MISSING",
            "lab_root or candidate_manifest_bytes required",
        )
    if lab_root is not None:
        lab_bytes = load_lab_candidate_manifest_bytes(lab_root=Path(lab_root))
        if candidate_manifest_bytes is not None and bytes(candidate_manifest_bytes) != lab_bytes:
            raise NativeSessionError(
                "CANDIDATE_MANIFEST_DRIFT",
                "caller bytes != lab candidate/candidate_manifest.v1.json",
            )
        manifest_bytes = lab_bytes
    else:
        manifest_bytes = bytes(candidate_manifest_bytes or b"")
    if not manifest_bytes:
        raise NativeSessionError("CANDIDATE_MANIFEST_MISSING", "empty bytes")
    manifest_obj = validate_candidate_manifest(
        manifest_bytes,
        expected_episode_id=episode_id,
        expected_attempt_cas_digest=attempt_cas_digest,
    )
    # Manifest must appear in the sealed lab artifact manifest from the attempt.
    artifact_manifest = attempt.get("artifact_manifest") or {}
    artifact_paths = {
        str(a.get("path")).replace("\\", "/")
        for a in list(artifact_manifest.get("artifacts") or [])
        if isinstance(a, Mapping)
    }
    if CANDIDATE_MANIFEST_RELATIVE not in artifact_paths:
        raise NativeSessionError(
            "CANDIDATE_MANIFEST_NOT_IN_ARTIFACTS",
            f"{CANDIDATE_MANIFEST_RELATIVE} missing from attempt lab artifact manifest",
        )
    # Hash in artifact list must match exact lab bytes.
    for entry in list(artifact_manifest.get("artifacts") or []):
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("path")).replace("\\", "/") == CANDIDATE_MANIFEST_RELATIVE:
            expected_digest = str(entry.get("sha256") or "")
            observed_digest = _sha256_bytes(manifest_bytes)
            if expected_digest != observed_digest:
                raise NativeSessionError(
                    "CANDIDATE_MANIFEST_HASH_MISMATCH",
                    f"artifact={expected_digest} bytes={observed_digest}",
                )
            break
    manifest_sha256 = _sha256_bytes(manifest_bytes)
    manifest_cas = write_cas_blob(root, "manifests", manifest_bytes)
    if (
        manifest_obj.get("attempt_cas_digest")
        and manifest_obj.get("attempt_cas_digest") != attempt_cas_digest
    ):
        raise NativeSessionError(
            "CANDIDATE_MANIFEST_STALE_ATTEMPT",
            str(manifest_obj.get("attempt_cas_digest")),
        )
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
        "candidate_manifest_sha256": manifest_sha256,
        "candidate_manifest_cas_digest": manifest_cas,
        "candidate_manifest_path": CANDIDATE_MANIFEST_RELATIVE,
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
        "research_profile": attempt.get("research_profile"),
        "web_enabled": attempt.get("web_enabled"),
        "productive_lab_ops": list(attempt.get("productive_lab_ops") or []),
        "web_use_trace": dict(attempt.get("web_use_trace") or {}),
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
        if prior.get("attempt_cas_digest") == attempt_cas_digest and prior.get(
            "bundle_sha256"
        ) not in {None, bundle_hash}:
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
