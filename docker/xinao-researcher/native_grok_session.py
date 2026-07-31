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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "xinao.native_grok_session_contract.v1"
PROBE_SCHEMA = "xinao.native_grok_cli_probe.v1"
DRIVER_SCHEMA = "xinao.native_episode_session_driver.v1"
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
        print(json.dumps(contract, ensure_ascii=False, sort_keys=True))
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
        print(json.dumps(driver.plan_new(prompt=args.prompt), ensure_ascii=False, sort_keys=True))
        return 0
    if args.cmd == "plan-resume":
        print(json.dumps(driver.plan_resume(), ensure_ascii=False, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
