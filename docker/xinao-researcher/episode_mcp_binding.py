"""Attempt-local Grok Build MCP binding for ResearchEpisode profiles.

Generates an isolated GROK_HOME (config.toml + agent profile) that:
- registers the transport-side episode_lab stdio MCP server (lab ops only);
- allowlists Grok built-in meta-tools search_tool/use_tool (and web on OPEN_RESEARCH);
- does not modify global host config and does not mount arbitrary host config.

Grok 0.2.117: search_tool discovers MCP tools; use_tool invokes them by
fully-qualified name (e.g. episode_lab__write_file). The MCP server itself
exposes ping/list_dir/read_file/write_file/shell_exec — not meta-tools.

Candidate only. Codex is the sole Owner/adopter.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipc_contract import (
    CONTRACT_ID,
    DEFAULT_TIMEOUT_MS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_TIMEOUT_MS,
    authority_clamp_flags,
    canonical_bytes,
    sha256_bytes,
)

try:
    from episode_boundary import (
        CANONICAL_AGENT_PROFILE,
        CANONICAL_CONFIG_TOML,
        CANONICAL_GROK_HOME,
        CANONICAL_LAB_CWD,
        CANONICAL_MCP_EVENTS,
        CLOSED_LAB_TOOLS_ALLOWLIST,
        DEFAULT_RESEARCH_PROFILE,
        HOST_CONTROL_BUILTINS,
        LAB_MCP_OPS,
        MCP_META_TOOLS,
        OPEN_RESEARCH_TOOLS_ALLOWLIST,
        PROFILE_CLOSED_LAB,
        PROFILE_OPEN_RESEARCH,
        WEB_BUILTIN_TOOLS,
        normalize_research_profile,
        stripped_builtins_for_profile,
        tools_allowlist_for_profile,
        web_enabled_for_profile,
    )
except ImportError:  # pragma: no cover - same-dir import fallback
    CANONICAL_GROK_HOME = "/grok-home"
    CANONICAL_LAB_CWD = "/episode-lab"
    CANONICAL_MCP_EVENTS = "/output/mcp_events.jsonl"
    CANONICAL_AGENT_PROFILE = "/grok-home/agents/genuine_scientist_mcp.md"
    CANONICAL_CONFIG_TOML = "/grok-home/config.toml"
    MCP_META_TOOLS = ("search_tool", "use_tool")
    WEB_BUILTIN_TOOLS = ("web_search", "web_fetch")
    LAB_MCP_OPS = ("ping", "list_dir", "read_file", "write_file", "shell_exec")
    OPEN_RESEARCH_TOOLS_ALLOWLIST = MCP_META_TOOLS + WEB_BUILTIN_TOOLS
    CLOSED_LAB_TOOLS_ALLOWLIST = MCP_META_TOOLS
    HOST_CONTROL_BUILTINS = (
        "run_terminal_cmd",
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
    )
    PROFILE_OPEN_RESEARCH = "OPEN_RESEARCH"
    PROFILE_CLOSED_LAB = "CLOSED_LAB"
    DEFAULT_RESEARCH_PROFILE = PROFILE_OPEN_RESEARCH

    def normalize_research_profile(profile: str | None) -> str:
        if not profile:
            return DEFAULT_RESEARCH_PROFILE
        name = str(profile).strip().upper()
        if name in {"GENUINE_SCIENTIST_EPISODE", "GENUINE", "GENUINE_SCIENTIST"}:
            return PROFILE_OPEN_RESEARCH
        return name

    def tools_allowlist_for_profile(profile: str) -> tuple[str, ...]:
        name = normalize_research_profile(profile)
        if name == PROFILE_CLOSED_LAB:
            return CLOSED_LAB_TOOLS_ALLOWLIST
        return OPEN_RESEARCH_TOOLS_ALLOWLIST

    def stripped_builtins_for_profile(profile: str) -> tuple[str, ...]:
        name = normalize_research_profile(profile)
        if name == PROFILE_CLOSED_LAB:
            return HOST_CONTROL_BUILTINS + WEB_BUILTIN_TOOLS
        return HOST_CONTROL_BUILTINS

    def web_enabled_for_profile(profile: str) -> bool:
        return normalize_research_profile(profile) == PROFILE_OPEN_RESEARCH


MCP_SERVER_NAME = "episode_lab"
# Grok headless built-in meta-tools (always-on unless denied; listed explicitly).
MCP_DISCOVERY_TOOLS = MCP_META_TOOLS
# Host builtins stripped on OPEN_RESEARCH (web remains available).
STRIPPED_BUILTIN_TOOLS = HOST_CONTROL_BUILTINS
# CLOSED_LAB also strips web.
STRIPPED_BUILTIN_TOOLS_CLOSED_LAB = HOST_CONTROL_BUILTINS + WEB_BUILTIN_TOOLS

DEFAULT_MCP_SERVER_PATH = "/opt/xinao-researcher/mcp_episode_lab_server.py"
DEFAULT_SOCKET_PATH = "/ipc/tool.sock"
DEFAULT_PYTHON = "python3"
CANONICAL_EVIDENCE_PATH = CANONICAL_MCP_EVENTS

BINDING_SCHEMA_VERSION = "xinao.episode_mcp_binding.v1"
PROFILE_NAME = "genuine_scientist_mcp"


def mcp_tools_allowlist(profile: str | None = None) -> str:
    return ",".join(tools_allowlist_for_profile(normalize_research_profile(profile)))


def stripped_builtins_csv(profile: str | None = None) -> str:
    return ",".join(stripped_builtins_for_profile(normalize_research_profile(profile)))


def render_config_toml(
    *,
    server_command: str,
    server_args: Sequence[str],
    env: Mapping[str, str] | None = None,
    startup_timeout_sec: int = 15,
    tool_timeout_sec: int | None = None,
    server_name: str = MCP_SERVER_NAME,
) -> str:
    if tool_timeout_sec is None:
        tool_timeout_sec = max(1, min(DEFAULT_TIMEOUT_MS // 1000, MAX_TIMEOUT_MS // 1000))
    lines = [
        f"[mcp_servers.{server_name}]",
        f'command = "{_toml_escape(server_command)}"',
        "args = [" + ", ".join(f'"{_toml_escape(a)}"' for a in server_args) + "]",
        "enabled = true",
        f"startup_timeout_sec = {int(startup_timeout_sec)}",
        f"tool_timeout_sec = {int(tool_timeout_sec)}",
    ]
    if env:
        env_items = ", ".join(
            f'{_toml_escape(k)} = "{_toml_escape(v)}"' for k, v in sorted(env.items())
        )
        lines.append(f"env = {{ {env_items} }}")
    lines.append("")
    lines.extend(
        [
            "[features]",
            "lsp_tools = false",
            "",
            "[subagents]",
            "enabled = false",
            "",
            "[memory]",
            "enabled = false",
            "",
        ]
    )
    return "\n".join(lines)


def render_agent_profile_md(*, profile: str | None = None) -> str:
    """Agent profile frontmatter: MCP meta (+ web on OPEN_RESEARCH); strip host builtins."""
    research_profile = normalize_research_profile(profile)
    allowed = tools_allowlist_for_profile(research_profile)
    denied = stripped_builtins_for_profile(research_profile)
    tools_yaml = "\n".join(f"  - {name}" for name in allowed)
    denied_yaml = "\n".join(f"  - {name}" for name in denied)
    web_note = (
        "Web search/fetch are available for external mature approach lookup."
        if web_enabled_for_profile(research_profile)
        else "Web search/fetch are denied on CLOSED_LAB."
    )
    return (
        "---\n"
        f"name: {PROFILE_NAME}\n"
        f"description: ResearchEpisode {research_profile} — dual-container lab MCP via "
        "search_tool/use_tool; host file/shell stripped.\n"
        "tools:\n"
        f"{tools_yaml}\n"
        "disallowedTools:\n"
        f"{denied_yaml}\n"
        "---\n"
        "\n"
        f"You are a productive research scientist ({research_profile}). Use Grok built-in\n"
        "search_tool / use_tool to discover and invoke episode_lab lab ops\n"
        f"({', '.join(LAB_MCP_OPS)}). {web_note}\n"
        "Do not claim host paths, credentials, Owner adoption, science restoration,\n"
        "or parent completion. Prefer write_file/shell_exec for productive lab work.\n"
        "Historical exploration may fail; revise experiments in the same lab.\n"
    )


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def attempt_local_binding_paths(
    root: Path,
    *,
    grok_home: Path | None = None,
    evidence_path: Path | str | None = None,
) -> dict[str, Path]:
    """Paths for attempt-local binding.

    When ``grok_home`` is provided (typical transport: /grok-home with auth mount
    under .grok/), config.toml is written there so Grok discovers MCP without
    relocating GROK_HOME away from auth. When omitted, a nested grok-home under
    root is used (unit tests / isolated smoke).

    Evidence is always the canonical container path /output/mcp_events.jsonl when
    running under transport mounts; host materialization may write a host-side
    mirror under episode output.
    """
    resolved_home = Path(grok_home) if grok_home is not None else (root / "grok-home")
    if evidence_path is not None:
        evidence = Path(evidence_path)
    else:
        # Prefer canonical container path string when root looks like attempt tree
        # that will be mounted as separate files under /grok-home; host still
        # materializes a local file for planning when not in-container.
        evidence = Path(CANONICAL_EVIDENCE_PATH)
    return {
        "root": root,
        "grok_home": resolved_home,
        "config_toml": resolved_home / "config.toml",
        "agent_profile": resolved_home / "agents" / f"{PROFILE_NAME}.md",
        "evidence": evidence,
    }


def build_server_argv(
    *,
    server_path: str,
    socket_path: str,
    episode_id: str,
    evidence_path: str = CANONICAL_EVIDENCE_PATH,
    timeout_ms: int | None = None,
    python_bin: str = DEFAULT_PYTHON,
    sidecar_identity_expected: str | None = None,
) -> list[str]:
    if timeout_ms is None:
        timeout_ms = DEFAULT_TIMEOUT_MS
    if timeout_ms < 50 or timeout_ms > MAX_TIMEOUT_MS:
        raise ValueError(f"timeout_ms out of range: {timeout_ms}")
    argv = [
        python_bin,
        "-I",
        server_path,
        "--socket",
        socket_path,
        "--episode-id",
        episode_id,
        "--evidence-path",
        evidence_path,
        "--timeout-ms",
        str(int(timeout_ms)),
    ]
    if sidecar_identity_expected:
        argv.extend(["--sidecar-identity-expected", sidecar_identity_expected])
    return argv


def materialize_attempt_local_binding(
    *,
    root: Path,
    episode_id: str,
    socket_path: str = DEFAULT_SOCKET_PATH,
    server_path: str = DEFAULT_MCP_SERVER_PATH,
    python_bin: str = DEFAULT_PYTHON,
    pythonpath: str = "/opt/xinao-researcher",
    timeout_ms: int | None = None,
    sidecar_identity_expected: str | None = None,
    grok_home: Path | str | None = None,
    research_profile: str | None = None,
    evidence_path: str | Path | None = None,
    host_evidence_mirror: Path | str | None = None,
) -> dict[str, Any]:
    """Write attempt-local GROK_HOME config + agent profile; return binding receipt.

    Does not modify host-global operator config. Container-local GROK_HOME
    (auth mount parent) may receive an attempt config.toml overlay.
    MCP evidence path in config is always the canonical container path
    /output/mcp_events.jsonl.
    """
    if timeout_ms is None:
        timeout_ms = DEFAULT_TIMEOUT_MS
    profile = normalize_research_profile(research_profile)
    preferred_home: Path | None
    if grok_home is not None:
        preferred_home = Path(grok_home)
    else:
        env_home = os.environ.get("GROK_HOME")
        preferred_home = Path(env_home) if env_home else None
        if preferred_home is not None:
            looks_like_transport_home = (
                preferred_home == Path(CANONICAL_GROK_HOME)
                or preferred_home.name in {"grok-home", "attempt-grok-home"}
                or (preferred_home / ".grok").exists()
            )
            if not looks_like_transport_home:
                preferred_home = None
    # Config evidence always canonical in-container; optional host mirror for tests.
    paths = attempt_local_binding_paths(
        root,
        grok_home=preferred_home,
        evidence_path=evidence_path or CANONICAL_EVIDENCE_PATH,
    )
    Path(root).mkdir(parents=True, exist_ok=True)
    paths["grok_home"].mkdir(parents=True, exist_ok=True)
    paths["agent_profile"].parent.mkdir(parents=True, exist_ok=True)
    if host_evidence_mirror is not None:
        mirror = Path(host_evidence_mirror)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        paths["host_evidence_mirror"] = mirror
    # Do not create container path /output/... on host windows roots.

    server_args = build_server_argv(
        server_path=server_path,
        socket_path=socket_path,
        episode_id=episode_id,
        evidence_path=str(paths["evidence"]).replace("\\", "/"),
        timeout_ms=timeout_ms,
        python_bin=python_bin,
        sidecar_identity_expected=sidecar_identity_expected,
    )
    command = server_args[0]
    args = server_args[1:]
    env = {
        "PYTHONPATH": pythonpath,
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        "XINAO_TOOL_IPC_SOCKET": socket_path,
        "XINAO_EPISODE_ID": episode_id,
        "XINAO_MCP_EVIDENCE_PATH": CANONICAL_EVIDENCE_PATH,
        "XINAO_MCP_EVENT_LOG": CANONICAL_EVIDENCE_PATH,
        "XINAO_RESEARCH_PROFILE": profile,
    }
    config_text = render_config_toml(
        server_command=command,
        server_args=args,
        env=env,
        tool_timeout_sec=max(1, min(timeout_ms // 1000, MAX_TIMEOUT_MS // 1000)),
    )
    profile_text = render_agent_profile_md(profile=profile)
    paths["config_toml"].write_text(config_text, encoding="utf-8")
    paths["agent_profile"].write_text(profile_text, encoding="utf-8")

    receipt = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_id": uuid.uuid4().hex,
        "episode_id": episode_id,
        "research_profile": profile,
        "web_enabled": web_enabled_for_profile(profile),
        "mcp_server_name": MCP_SERVER_NAME,
        "mcp_lab_ops": list(LAB_MCP_OPS),
        "tools_allowlist": list(tools_allowlist_for_profile(profile)),
        "tools_allowlist_csv": mcp_tools_allowlist(profile),
        "stripped_builtins": list(stripped_builtins_for_profile(profile)),
        "canonical_paths": {
            "GROK_HOME": CANONICAL_GROK_HOME,
            "cwd": CANONICAL_LAB_CWD,
            "mcp_events": CANONICAL_EVIDENCE_PATH,
            "agent_profile": CANONICAL_AGENT_PROFILE,
            "config_toml": CANONICAL_CONFIG_TOML,
        },
        "socket_basename": Path(socket_path).name,
        "contract_id": CONTRACT_ID,
        "max_request_bytes": MAX_REQUEST_BYTES,
        "max_response_bytes": MAX_RESPONSE_BYTES,
        "timeout_ms": int(timeout_ms),
        "default_timeout_ms": DEFAULT_TIMEOUT_MS,
        "max_timeout_ms": MAX_TIMEOUT_MS,
        "grok_home": str(paths["grok_home"]),
        "config_toml": str(paths["config_toml"]),
        "agent_profile": str(paths["agent_profile"]),
        "evidence_path": CANONICAL_EVIDENCE_PATH,
        "config_sha256": sha256_bytes(config_text.encode("utf-8")),
        "agent_profile_sha256": sha256_bytes(profile_text.encode("utf-8")),
        "server_argv": server_args,
        "global_config_modified": False,
        "host_config_mounted": False,
        "lab_dependency_path": {
            "preseeded_venv_supported": True,
            "online_install": False,
            "note": (
                "shell_exec may invoke lab-local .venv/bin/python or wheelhouse "
                "paths under /episode-lab only; no live online installer."
            ),
        },
        **authority_clamp_flags(),
    }
    receipt_path = root / "mcp-binding-receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = sha256_bytes(canonical_bytes(receipt))
    return receipt


def dual_container_socket_available(socket_path: str | None = None) -> bool:
    path = Path(socket_path or os.environ.get("XINAO_TOOL_IPC_SOCKET") or DEFAULT_SOCKET_PATH)
    if os.environ.get("XINAO_DUAL_CONTAINER") == "1":
        return True
    try:
        return path.exists()
    except OSError:
        return False


def binding_env_for_grok(receipt: Mapping[str, Any]) -> dict[str, str]:
    """Env for the grok process.

    Prefer canonical GROK_HOME=/grok-home when config was materialised for that
    mount. Never set GROK_HOME=/attempt/grok-home when mounts live under /grok-home.
    """
    env = {
        "XINAO_MCP_BINDING": "1",
        "XINAO_MCP_SERVER": MCP_SERVER_NAME,
        "XINAO_MCP_TOOLS": str(receipt.get("tools_allowlist_csv") or mcp_tools_allowlist()),
        "XINAO_MCP_EVENT_LOG": CANONICAL_EVIDENCE_PATH,
        "XINAO_MCP_EVIDENCE_PATH": CANONICAL_EVIDENCE_PATH,
        "XINAO_RESEARCH_PROFILE": str(receipt.get("research_profile") or DEFAULT_RESEARCH_PROFILE),
        "GROK_HOME": CANONICAL_GROK_HOME,
    }
    return env


def assert_path_alignment(
    *,
    grok_home: str,
    agent_profile: str | None = None,
    config_toml: str | None = None,
    evidence_path: str | None = None,
    cwd: str | None = None,
) -> None:
    """Fail closed when attach env/paths diverge from physical mounts."""
    gh = str(grok_home).replace("\\", "/").rstrip("/")
    if gh != CANONICAL_GROK_HOME:
        raise ValueError(f"GROK_HOME_MISALIGNED:{gh}!={CANONICAL_GROK_HOME}")
    if agent_profile is not None:
        ap = str(agent_profile).replace("\\", "/")
        if not ap.startswith(CANONICAL_GROK_HOME + "/"):
            raise ValueError(f"AGENT_PROFILE_MISALIGNED:{ap}")
    if config_toml is not None:
        ct = str(config_toml).replace("\\", "/")
        if ct != CANONICAL_CONFIG_TOML and not ct.startswith(CANONICAL_GROK_HOME + "/"):
            raise ValueError(f"CONFIG_TOML_MISALIGNED:{ct}")
    if evidence_path is not None:
        ep = str(evidence_path).replace("\\", "/")
        if ep != CANONICAL_EVIDENCE_PATH:
            raise ValueError(f"EVIDENCE_PATH_MISALIGNED:{ep}")
    if cwd is not None:
        cd = str(cwd).replace("\\", "/").rstrip("/")
        if cd != CANONICAL_LAB_CWD:
            raise ValueError(f"CWD_MISALIGNED:{cd}")
