"""Docker create/mount/network specifications for dual-container fallback.

No Compose, Kubernetes, daemon, Temporal, scheduler, or resident service.
These are pure data + helpers that Owner/Codex may pass to `docker create`
or equivalent one-shot runners.

Transport container: may hold Grok auth; exposes no generic file/shell tool.
Tool executor: no auth/config/provider session; episode lab + private tmp only;
network denied; uid/gid 65532; zero caps; NNP; no host socket/root/ledger/outcome.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

TOOL_UID = 65532
TOOL_GID = 65532
TRANSPORT_UID = 0
TRANSPORT_GID = 0
TRANSPORT_USER = f"{TRANSPORT_UID}:{TRANSPORT_GID}"
TOOL_BWRAP_SECCOMP_PROFILE_FILENAME = "seccomp.bwrap.json"
TOOL_BWRAP_SECCOMP_PROFILE_SHA256 = (
    "e25af138916a2459ed396eb7787d4a71c8c0ecd6daad6a5b57d103a3271fefc9"
)

# Paths inside tool-executor container.
TOOL_LAB_MOUNT = "/episode-lab"
TOOL_IPC_MOUNT = "/ipc"
TOOL_TMP = "/tmp"
TOOL_REPLAY_STATE = f"{TOOL_IPC_MOUNT}/.xinao-replay"
# Tool-executor-only evidence volume (NOT mounted writable on transport).
TOOL_SIDECAR_EVIDENCE_MOUNT = "/sidecar-evidence"
TOOL_SIDECAR_EVENTS_FILENAME = "tool_events.jsonl"
TOOL_SIDECAR_EVENTS_PATH = f"{TOOL_SIDECAR_EVIDENCE_MOUNT}/{TOOL_SIDECAR_EVENTS_FILENAME}"

# Explicitly forbidden mount sources/targets for tool executor.
FORBIDDEN_TOOL_MOUNTS = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/var/run/podman/podman.sock",
    "/grok-home",
    "/root/.grok",
    "/ledger",
    "/outcomes",
    "/freeze",
    "/settlement",
    "/shadow",
    "/",  # host root
)


# Transport container internal mounts for dual-host orchestration.
# Grok 0.2.117: auth.json + sessions live flat under GROK_HOME (not nested .grok/).
TRANSPORT_AUTH_MOUNT = "/grok-home/auth.json"
TRANSPORT_INPUT_MOUNT = "/input"
TRANSPORT_OUTPUT_MOUNT = "/output"
TRANSPORT_SESSION_MOUNT = "/grok-home/sessions"
TRANSPORT_MATERIAL_MOUNT = "/material"
LEGACY_NESTED_AUTH_MOUNT = "/grok-home/.grok"
LEGACY_NESTED_SESSION_MOUNT = "/grok-home/.grok/sessions"
TRANSPORT_MCP_BRIDGE_MOUNT = "/opt/xinao-attempt/mcp_tool_bridge.py"  # legacy bridge (optional)
TRANSPORT_MCP_IPC_CONTRACT_MOUNT = "/opt/xinao-attempt/ipc_contract.py"
# Native attempt-local Grok user config (preferred over project-scoped lab config).
TRANSPORT_ATTEMPT_GROK_CONFIG_MOUNT = "/grok-home/config.toml"
TRANSPORT_ATTEMPT_AGENT_PROFILE_MOUNT = "/grok-home/agents/genuine_scientist_mcp.md"
TRANSPORT_MCP_SERVER_IMAGE_PATH = "/opt/xinao-researcher/mcp_episode_lab_server.py"
TRANSPORT_MCP_EVENT_LOG = "/output/mcp_events.jsonl"
# Canonical only — do not use fragmented aliases (mcp-evidence.jsonl / attempt/...).
TRANSPORT_MCP_EVIDENCE_MOUNT = TRANSPORT_MCP_EVENT_LOG

# Provider egress routing (must match skills/xinao/scripts/xinao_runtime.py).
# Internal-network transport has no default route/DNS for provider hosts; Grok CLI
# (reqwest) reaches cli-chat-proxy.grok.com only via this dedicated Squid CONNECT
# proxy. Offline network=none seats must not inject these keys.
DEFAULT_PROVIDER_EGRESS_NETWORK = "xinao_researcher_internal"
DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT = "http://xinao-researcher-egress-proxy:3128"
PROVIDER_EGRESS_ENV_POLICY_GENERATION = "sealed-env-v1"
PROVIDER_EGRESS_PROXY_URL_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
)
PROVIDER_EGRESS_CLEAR_ENV_KEYS = (
    "NO_PROXY",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
)
PROVIDER_EGRESS_CONTROLLED_ENV_KEYS = (
    *PROVIDER_EGRESS_PROXY_URL_ENV_KEYS,
    *PROVIDER_EGRESS_CLEAR_ENV_KEYS,
)


def provider_egress_proxy_env(
    *,
    network: str | None,
    endpoint: str = DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT,
) -> dict[str, str]:
    """Return proxy routing env when transport is on the sealed internal net.

    Empty when network is none/empty so offline/fake-client seats stay offline.
    """
    net = str(network or "").strip().lower()
    if net != DEFAULT_PROVIDER_EGRESS_NETWORK:
        return {}
    ep = str(endpoint or "").strip()
    if not ep:
        return {}
    return {
        **{key: ep for key in PROVIDER_EGRESS_PROXY_URL_ENV_KEYS},
        **{key: "" for key in PROVIDER_EGRESS_CLEAR_ENV_KEYS},
    }


# Mount targets that must never appear on either container.
FORBIDDEN_MOUNT_MARKERS = (
    "docker.sock",
    "podman.sock",
    "/ledger",
    "/outcomes",
    "/outcome",
    "/freeze",
    "/settlement",
    "/shadow",
    "shadow_ledger",
)

ALLOWED_TRANSPORT_BIND_TARGETS = frozenset(
    {
        TRANSPORT_AUTH_MOUNT,
        TRANSPORT_INPUT_MOUNT,
        TRANSPORT_OUTPUT_MOUNT,
        TOOL_IPC_MOUNT,
        TRANSPORT_SESSION_MOUNT,
        TRANSPORT_MATERIAL_MOUNT,
        TRANSPORT_MCP_BRIDGE_MOUNT,
        TRANSPORT_MCP_IPC_CONTRACT_MOUNT,
        TRANSPORT_ATTEMPT_GROK_CONFIG_MOUNT,
        TRANSPORT_ATTEMPT_AGENT_PROFILE_MOUNT,
        "/episode-lab",
        "/episode-lab/.grok/config.toml",  # legacy project-scoped path
        "/episode-scratch",
        "/episode-state",
        # Explicitly NOT including TOOL_SIDECAR_EVIDENCE_MOUNT: transport must not
        # write tool-side sealed evidence.
    }
)


class ToolSpecDriftError(RuntimeError):
    def __init__(self, reason_code: str, violations: list[str]) -> None:
        super().__init__(f"{reason_code}: {violations}")
        self.reason_code = reason_code
        self.violations = list(violations)


def load_tool_bwrap_seccomp_profile() -> tuple[Path, dict[str, Any]]:
    """Load the sealed Docker profile that permits only bwrap setup namespaces.

    The profile preserves Moby seccomp/v0.2.2's hardened default-deny shape and
    adds one bounded bubblewrap setup allowance: one exact combined namespace
    clone, mount, pivot_root and umount2. It keeps clone3 forced to ENOSYS and
    closes both direct AF_ALG sockets and the 32-bit socketcall multiplexer,
    alongside bpf, perf and the other default-denied syscalls.
    """
    path = Path(__file__).resolve().with_name(TOOL_BWRAP_SECCOMP_PROFILE_FILENAME)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ToolSpecDriftError("TOOL_SECCOMP_PROFILE_MISSING", [str(path)]) from exc
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256 != TOOL_BWRAP_SECCOMP_PROFILE_SHA256:
        raise ToolSpecDriftError(
            "TOOL_SECCOMP_PROFILE_DRIFT",
            [f"sha256={observed_sha256}"],
        )
    try:
        profile = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolSpecDriftError("TOOL_SECCOMP_PROFILE_INVALID", [str(exc)]) from exc
    if not isinstance(profile, dict) or profile.get("defaultAction") != "SCMP_ACT_ERRNO":
        raise ToolSpecDriftError("TOOL_SECCOMP_PROFILE_INVALID", ["defaultAction"])
    return path, profile


def tool_bwrap_seccomp_create_opt() -> str:
    path, _profile = load_tool_bwrap_seccomp_profile()
    return f"seccomp={path}"


def tool_bwrap_seccomp_inspect_opt() -> str:
    """Return Docker inspect's embedded-json representation for tests/readback."""
    _path, profile = load_tool_bwrap_seccomp_profile()
    return "seccomp=" + json.dumps(profile, sort_keys=False, separators=(",", ":"))


def inspect_uses_tool_bwrap_seccomp_profile(security_opt: list[Any]) -> bool:
    """Match semantic profile bytes after Docker replaces its path with JSON."""
    _path, expected = load_tool_bwrap_seccomp_profile()
    for raw in security_opt:
        value = str(raw)
        if not value.lower().startswith("seccomp="):
            continue
        encoded = value.split("=", 1)[1].strip()
        if encoded.lower() == "unconfined":
            return False
        try:
            observed = json.loads(encoded)
        except json.JSONDecodeError:
            return False
        return observed == expected
    return False


def transport_container_spec(
    *,
    image: str,
    name: str,
    auth_host_path: str,
    input_host_path: str,
    output_host_path: str,
    ipc_host_dir: str,
    network: str = "none",
    session_host_path: str | None = None,
    material_host_path: str | None = None,
    mcp_bridge_host_path: str | None = None,
    ipc_contract_host_path: str | None = None,
    attempt_grok_config_host_path: str | None = None,
    attempt_agent_profile_host_path: str | None = None,
    episode_lab_host_path: str | None = None,
    episode_id: str | None = None,
    use_episode_entrypoint: bool = False,
    entrypoint: list[str] | None = None,
    provider_egress_proxy_endpoint: str = DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT,
) -> dict[str, Any]:
    """Spec for the model/transport container.

    Network may be switched by Owner to a provider egress network when live
    model calls are required. Default is none for offline/fake-client seats.
    Generic file/shell tools must remain disabled in the model invocation;
    tools reach the sidecar only via attempt-local native MCP config.

    Auth host path may be either the auth.json file or a directory containing
    auth.json; both bind flat to /grok-home/auth.json (Grok 0.2.117 layout).
    """
    from pathlib import Path as _Path

    auth_src = str(auth_host_path)
    auth_p = _Path(auth_src)
    if auth_p.is_dir() or auth_src.rstrip("\\/").endswith((".grok", "auth", "credentials")):
        # Prefer directory/auth.json when caller still passes legacy auth dir.
        candidate = auth_p / "auth.json"
        if candidate.is_file() or not auth_p.is_file():
            auth_src = str(candidate)
    binds: list[dict[str, str]] = [
        {"host": auth_src, "container": TRANSPORT_AUTH_MOUNT, "mode": "ro"},
        {"host": input_host_path, "container": TRANSPORT_INPUT_MOUNT, "mode": "ro"},
        {"host": output_host_path, "container": TRANSPORT_OUTPUT_MOUNT, "mode": "rw"},
        {"host": ipc_host_dir, "container": TOOL_IPC_MOUNT, "mode": "rw"},
    ]
    if session_host_path:
        binds.append(
            {
                "host": session_host_path,
                "container": TRANSPORT_SESSION_MOUNT,
                "mode": "rw",
            }
        )
    if material_host_path:
        binds.append(
            {
                "host": material_host_path,
                "container": TRANSPORT_MATERIAL_MOUNT,
                "mode": "ro",
            }
        )
    # Legacy optional bridge mount (native MCP uses image-baked server instead).
    if mcp_bridge_host_path:
        binds.append(
            {
                "host": mcp_bridge_host_path,
                "container": TRANSPORT_MCP_BRIDGE_MOUNT,
                "mode": "ro",
            }
        )
    if ipc_contract_host_path:
        binds.append(
            {
                "host": ipc_contract_host_path,
                "container": TRANSPORT_MCP_IPC_CONTRACT_MOUNT,
                "mode": "ro",
            }
        )
    if attempt_grok_config_host_path:
        binds.append(
            {
                "host": attempt_grok_config_host_path,
                "container": TRANSPORT_ATTEMPT_GROK_CONFIG_MOUNT,
                "mode": "ro",
            }
        )
    if attempt_agent_profile_host_path:
        binds.append(
            {
                "host": attempt_agent_profile_host_path,
                "container": TRANSPORT_ATTEMPT_AGENT_PROFILE_MOUNT,
                "mode": "ro",
            }
        )
    if episode_lab_host_path:
        binds.append(
            {
                "host": episode_lab_host_path,
                "container": "/episode-lab",
                "mode": "rw",
            }
        )
    env: dict[str, str] = {
        # Auth material is file-mounted, not injected as raw secret env by default.
        "HOME": "/grok-home",
        "GROK_HOME": "/grok-home",
        "XINAO_DUAL_CONTAINER": "1",
        "XINAO_TOOL_IPC_SOCKET": f"{TOOL_IPC_MOUNT}/tool.sock",
        "XINAO_GENERIC_FILE_SHELL_TOOLS": "0",
        "XINAO_MCP_EVENT_LOG": TRANSPORT_MCP_EVENT_LOG,
        "XINAO_MCP_BINDING": "1",
        "XINAO_MCP_SERVER": "episode_lab",
    }
    # Live provider path: dual-host puts transport on xinao_researcher_internal.
    # Without HTTP(S)_PROXY, Grok cannot resolve/CONNECT cli-chat-proxy.grok.com
    # and fails with reqwest "error sending request" after -p headless attach.
    proxy_env = provider_egress_proxy_env(
        network=network,
        endpoint=provider_egress_proxy_endpoint,
    )
    env.update(proxy_env)
    if proxy_env:
        env["XINAO_EGRESS_ENV_POLICY_GENERATION"] = PROVIDER_EGRESS_ENV_POLICY_GENERATION
    if episode_id:
        env["XINAO_EPISODE_ID"] = episode_id
    if entrypoint is not None:
        resolved_entrypoint = list(entrypoint)
        episode_entrypoint_selected = any(
            "episode_entrypoint.py" in str(part) for part in resolved_entrypoint
        )
    elif use_episode_entrypoint:
        # --hold: explicit idle-hold until Owner docker-exec attach / docker stop.
        # Must stay running; bare episode_entrypoint without --hold exits immediately
        # and breaks require_live_pair_ready (needs docker exec into a live transport).
        resolved_entrypoint = [
            "python",
            "-I",
            "/opt/xinao-researcher/episode_entrypoint.py",
            "--hold",
        ]
        episode_entrypoint_selected = True
    else:
        # Default canary ENTRYPOINT identity preserved for non-episode seats.
        resolved_entrypoint = ["python", "-I", "/opt/xinao-researcher/entrypoint.py"]
        episode_entrypoint_selected = False
    return {
        "schema_version": "xinao.dual_container_create_spec.v1",
        "role": "transport_model",
        "image": image,
        "name": name,
        # Explicitly pin the peer identity consumed by the tool-side Linux
        # SO_PEERCRED gate. Image-default drift must not silently change it.
        "user": TRANSPORT_USER,
        "network": network,
        "read_only_rootfs": False,
        "cap_drop": ["ALL"],
        "cap_add": [],  # Owner may add minimal set for model binary only under separate proof
        "security_opt": ["no-new-privileges:true"],
        "env": env,
        "binds": binds,
        "tmpfs": [f"{TOOL_TMP}:rw,nosuid,nodev,size=64m"],
        "entrypoint": resolved_entrypoint,
        "episode_entrypoint_selected": episode_entrypoint_selected,
        "episode_idle_hold": episode_entrypoint_selected
        and any(str(part) == "--hold" for part in resolved_entrypoint),
        "generic_file_shell_tools": False,
        "mcp_tools_via_sidecar": True,
        "mcp_server": "episode_lab",
        "mcp_server_image_path": TRANSPORT_MCP_SERVER_IMAGE_PATH,
        "mcp_binding": {
            "server": "episode_lab",
            "lab_ops": ["ping", "list_dir", "read_file", "write_file", "shell_exec"],
            "tools_allowlist": [
                "search_tool",
                "use_tool",
                "web_search",
                "web_fetch",
            ],
            "research_profile_default": "OPEN_RESEARCH",
            "mcp_events_path": TRANSPORT_MCP_EVENT_LOG,
            "global_config_modified": False,
            "host_config_mounted": False,
        },
        "notes": (
            "Canary ENTRYPOINT remains the default image entrypoint. Dual-host "
            "episode seats select episode_entrypoint --hold (idle until Owner "
            "docker exec attach; no research/schedule/freeze/settle) plus "
            "attempt-local native MCP (episode_lab lab ops via Grok built-in "
            "search_tool/use_tool). OPEN_RESEARCH also allows web_search/web_fetch; "
            "host file/shell stay stripped. restart policy remains no."
        ),
        "forbidden": {
            "mount_docker_sock": True,
            "mount_ledger_outcome": True,
            "write_owner_science_account_authority": True,
        },
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def tool_executor_container_spec(
    *,
    image: str,
    name: str,
    episode_lab_host_path: str,
    ipc_host_dir: str,
    sidecar_evidence_host_path: str | None = None,
    ipc_peer_uids: str | None = str(TRANSPORT_UID),
    bwrap_mode: str = "require",
) -> dict[str, Any]:
    """Spec for the tool executor container (physical separation).

    Genuine dual-container defaults:
    - XINAO_TOOL_EXEC_BWRAP=require (bubblewrap shell confinement)
    - XINAO_IPC_PEER_REQUIRE=1 (fail-closed peer identity)
    - XINAO_REPLAY_STATE_DIR under IPC volume (durable anti-replay)
    - XINAO_IPC_PEER_UIDS set by Owner to transport container uid(s)
    - tool-only /sidecar-evidence volume (not mounted on transport)
    """
    env: dict[str, str] = {
        "HOME": TOOL_TMP,
        "TMPDIR": TOOL_TMP,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XINAO_TOOL_EXEC_BWRAP": bwrap_mode,
        "XINAO_IPC_PEER_REQUIRE": "1",
        "XINAO_REPLAY_STATE_DIR": TOOL_REPLAY_STATE,
        "XINAO_TOOL_SIDECAR_EVIDENCE_DIR": TOOL_SIDECAR_EVIDENCE_MOUNT,
        "XINAO_TOOL_SIDECAR_EVENTS_PATH": TOOL_SIDECAR_EVENTS_PATH,
    }
    if ipc_peer_uids is not None:
        env["XINAO_IPC_PEER_UIDS"] = str(ipc_peer_uids)
    else:
        # Empty + require=1 → fail-closed until Owner pins transport peer uid.
        env["XINAO_IPC_PEER_UIDS"] = ""
    binds: list[dict[str, str]] = [
        {
            "host": episode_lab_host_path,
            "container": TOOL_LAB_MOUNT,
            "mode": "rw",
        },
        {
            "host": ipc_host_dir,
            "container": TOOL_IPC_MOUNT,
            "mode": "rw",
        },
    ]
    if sidecar_evidence_host_path:
        binds.append(
            {
                "host": sidecar_evidence_host_path,
                "container": TOOL_SIDECAR_EVIDENCE_MOUNT,
                "mode": "rw",
            }
        )
    entrypoint = [
        "python",
        "-I",
        "/opt/xinao-tool-executor/tool_executor.py",
        "--lab-root",
        TOOL_LAB_MOUNT,
        "--socket",
        f"{TOOL_IPC_MOUNT}/tool.sock",
        "--replay-state-dir",
        TOOL_REPLAY_STATE,
        "--sidecar-evidence-dir",
        TOOL_SIDECAR_EVIDENCE_MOUNT,
    ]
    return {
        "schema_version": "xinao.dual_container_create_spec.v1",
        "role": "tool_executor",
        "image": image,
        "name": name,
        "user": f"{TOOL_UID}:{TOOL_GID}",
        "network": "none",
        "read_only_rootfs": True,
        "cap_drop": ["ALL"],
        "cap_add": [],
        "security_opt": ["no-new-privileges:true", tool_bwrap_seccomp_create_opt()],
        "pids_limit": 256,
        "memory": "512m",
        "cpus": 1.0,
        "env": env,
        "binds": binds,
        "tmpfs": [f"{TOOL_TMP}:rw,nosuid,nodev,noexec,size=64m"],
        "entrypoint": entrypoint,
        "forbidden_binds": list(FORBIDDEN_TOOL_MOUNTS),
        "must_not_contain": [
            "grok binary",
            "auth.json",
            "provider session files",
            "ledger mounts",
            "outcome mounts",
            "freeze mounts",
            "host root mount",
            "docker/podman sockets",
        ],
        "response_bounds": {
            "max_request_bytes": 65536,
            "max_response_bytes": 262144,
            "default_timeout_ms": 600000,
            "max_timeout_ms": 3600000,
        },
        "security_profile": {
            "shell_bwrap": bwrap_mode,
            "ipc_peer_require": True,
            "durable_replay": True,
            "replay_state_dir": TOOL_REPLAY_STATE,
            "sidecar_evidence_mount": TOOL_SIDECAR_EVIDENCE_MOUNT,
            "sidecar_events_path": TOOL_SIDECAR_EVENTS_PATH,
        },
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def docker_create_process_argv(spec: dict[str, Any]) -> list[str]:
    """Return the intended container process argv (Entrypoint-only form)."""
    entry = spec.get("entrypoint") or []
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, list):
        return [str(x) for x in entry]
    return []


def bind_mount_cli_value(bind: dict[str, Any]) -> str:
    """Materialize one Docker CLI ``--mount`` value for a bind.

    Docker ``--mount`` accepts key=value fields (and a few bare flags such as
    ``readonly`` / ``ro``). Writable is the default: omit the mode field.
    Bare ``rw`` is **not** valid for ``--mount`` (it is a ``-v`` volume-mode
    token) and fails on current Docker CLI with
    ``invalid field 'rw' must be a key=value pair``.

    Spec data may still use inspect-style ``mode`` tokens ``rw`` / ``ro``;
    only CLI materialization normalizes them.
    """
    host = bind["host"]
    container = bind["container"]
    mode = str(bind.get("mode") or "rw").strip().lower()
    base = f"type=bind,src={host},dst={container}"
    if mode in {"", "rw", "readwrite", "read-write", "read_write"}:
        return base
    if mode in {"ro", "readonly", "read-only", "read_only"}:
        return f"{base},readonly"
    raise ValueError(f"unsupported bind mode for docker --mount: {mode!r}")


def docker_create_argv(spec: dict[str, Any]) -> list[str]:
    """Materialize a `docker create` argv list from a create spec.

    Real Docker CLI semantics for multi-arg process identity:
    - ``--entrypoint <first-token> IMAGE <rest-as-Cmd>`` yields
      ``Config.Entrypoint=[first]`` + ``Config.Cmd=rest`` (executable form).
    - Docker CLI does **not** parse a JSON-array string as ``--entrypoint``;
      a token like ``'["python",...]'`` is treated as a single executable path
      and fails with OCI ``executable file not found``.
    - Omitting ``--entrypoint`` keeps the image's sealed ENTRYPOINT (also valid).

    Bind mounts use :func:`bind_mount_cli_value` (writable omits mode; readonly
    uses ``,readonly`` — never bare ``,rw``).
    """
    argv = ["docker", "create", "--name", spec["name"]]
    if spec.get("user"):
        argv.extend(["--user", str(spec["user"])])
    network = spec.get("network")
    if network is not None:
        argv.extend(["--network", str(network)])
    if spec.get("read_only_rootfs"):
        argv.append("--read-only")
    for cap in spec.get("cap_drop") or []:
        argv.extend(["--cap-drop", cap])
    for cap in spec.get("cap_add") or []:
        argv.extend(["--cap-add", cap])
    for opt in spec.get("security_opt") or []:
        argv.extend(["--security-opt", opt])
    if spec.get("pids_limit") is not None:
        argv.extend(["--pids-limit", str(spec["pids_limit"])])
    if spec.get("memory"):
        argv.extend(["--memory", str(spec["memory"])])
    if spec.get("cpus") is not None:
        argv.extend(["--cpus", str(spec["cpus"])])
    for key, value in (spec.get("env") or {}).items():
        argv.extend(["--env", f"{key}={value}"])
    for bind in spec.get("binds") or []:
        argv.extend(["--mount", bind_mount_cli_value(bind)])
    for tmp in spec.get("tmpfs") or []:
        # docker create --tmpfs /tmp:opts
        argv.extend(["--tmpfs", tmp])
    entry = docker_create_process_argv(spec)
    if entry:
        # Real CLI: first token is Entrypoint; remaining tokens become Cmd.
        argv.extend(["--entrypoint", entry[0]])
        argv.append(spec["image"])
        argv.extend(entry[1:])
    else:
        argv.append(spec["image"])
    return argv


def process_argv_from_inspect(inspect_doc: dict[str, Any]) -> list[str]:
    """Reconstruct process argv from live inspect Entrypoint+Cmd (real Docker shapes).

    Accepted shapes (neither is drift by itself):
    1. Image sealed ENTRYPOINT: Entrypoint=full list, Cmd=null/[]
    2. CLI override ``--entrypoint first IMAGE rest``: Entrypoint=[first], Cmd=rest
    3. Single-string Entrypoint/Cmd tokens (Docker may emit either form)
    """
    cfg = _config(inspect_doc)
    entrypoint = cfg.get("Entrypoint") or []
    cmd = cfg.get("Cmd") or []
    if isinstance(entrypoint, str):
        entrypoint = [entrypoint]
    if isinstance(cmd, str):
        cmd = [cmd]
    if not isinstance(entrypoint, list):
        entrypoint = []
    if not isinstance(cmd, list):
        cmd = []
    return [str(x) for x in entrypoint] + [str(x) for x in cmd]


def validate_tool_spec_invariants(spec: dict[str, Any]) -> list[str]:
    """Return violation strings if tool executor spec drifts.

    Axes must match validate_tool_container_inspect (live receipt agreement).
    """
    violations: list[str] = []
    if spec.get("role") != "tool_executor":
        violations.append("role!=tool_executor")
    if spec.get("network") != "none":
        violations.append("network!=none")
    if spec.get("user") != f"{TOOL_UID}:{TOOL_GID}":
        violations.append("user!=65532:65532")
    if "ALL" not in (spec.get("cap_drop") or []):
        violations.append("cap_drop missing ALL")
    if list(spec.get("cap_add") or []):
        violations.append("cap_add must be empty")
    if "no-new-privileges:true" not in (spec.get("security_opt") or []):
        violations.append("missing no-new-privileges")
    try:
        expected_seccomp = tool_bwrap_seccomp_create_opt()
    except ToolSpecDriftError:
        expected_seccomp = ""
    if not expected_seccomp or expected_seccomp not in (spec.get("security_opt") or []):
        violations.append("bwrap_seccomp_profile_missing_or_wrong")
    if not spec.get("read_only_rootfs"):
        violations.append("read_only_rootfs required")
    env = spec.get("env") or {}
    for key in env:
        upper = str(key).upper()
        if upper.startswith(("GROK_", "XAI_")) or upper in {
            "GROK_HOME",
            "GROK_API_KEY",
            "XAI_API_KEY",
            "DOCKER_HOST",
            "SSH_AUTH_SOCK",
        }:
            violations.append(f"forbidden_env:{key}")
    bwrap = str(env.get("XINAO_TOOL_EXEC_BWRAP", "")).strip().lower()
    if bwrap not in {"auto", "require", "1", "on", "true", "yes"}:
        violations.append("bwrap_env_missing_or_off")
    if str(env.get("XINAO_IPC_PEER_REQUIRE", "")).strip() not in {"1", "true", "yes"}:
        violations.append("ipc_peer_require_missing")
    if str(env.get("XINAO_IPC_PEER_UIDS", "")).strip() != str(TRANSPORT_UID):
        violations.append(f"ipc_peer_uids!={TRANSPORT_UID}")
    replay_dir = str(env.get("XINAO_REPLAY_STATE_DIR", "")).strip()
    if not replay_dir or TOOL_IPC_MOUNT not in replay_dir:
        violations.append("durable_replay_state_not_on_ipc")
    allowed_tool_binds = {TOOL_LAB_MOUNT, TOOL_IPC_MOUNT, TOOL_SIDECAR_EVIDENCE_MOUNT}
    for bind in spec.get("binds") or []:
        host = str(bind.get("host", ""))
        container = str(bind.get("container", ""))
        for forbidden in FORBIDDEN_TOOL_MOUNTS:
            if forbidden in (host, container) and container not in allowed_tool_binds:
                violations.append(f"forbidden_bind:{container}")
        if container not in allowed_tool_binds:
            violations.append(f"unexpected_bind:{container}")
        lowered = container.lower()
        if any(
            token in lowered
            for token in (
                "docker.sock",
                "podman.sock",
                "grok-home",
                "/ledger",
                "/outcome",
                "/freeze",
                "/settlement",
                "/shadow",
            )
        ):
            violations.append(f"forbidden_bind:{container}")
    for field in (
        "completion_claim_allowed",
        "science_restored",
        "parent_complete",
        "owner_adopted",
    ):
        if spec.get(field) is not False:
            violations.append(f"authority_field:{field}")
    return violations


def assert_tool_spec_fail_closed(spec: dict[str, Any]) -> None:
    violations = validate_tool_spec_invariants(spec)
    if violations:
        raise ToolSpecDriftError("TOOL_SPEC_DRIFT", violations)


def assert_transport_spec_fail_closed(spec: dict[str, Any]) -> None:
    violations = validate_transport_spec_invariants(spec)
    if violations:
        raise ToolSpecDriftError("TRANSPORT_SPEC_DRIFT", violations)


def dual_container_bundle(
    *,
    transport_image: str,
    tool_image: str,
    auth_host_path: str,
    input_host_path: str,
    output_host_path: str,
    episode_lab_host_path: str,
    ipc_host_dir: str,
    sidecar_evidence_host_path: str | None = None,
    run_id: str = "dual-1",
    session_host_path: str | None = None,
    material_host_path: str | None = None,
    mcp_bridge_host_path: str | None = None,
    ipc_contract_host_path: str | None = None,
    attempt_grok_config_host_path: str | None = None,
    attempt_agent_profile_host_path: str | None = None,
    episode_id: str | None = None,
    use_episode_entrypoint: bool = False,
    ipc_peer_uids: str | None = str(TRANSPORT_UID),
    bwrap_mode: str = "require",
    # Transport-only; tool executor create spec always forces network=none.
    network: str = "none",
    provider_egress_proxy_endpoint: str = DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT,
) -> dict[str, Any]:
    transport = transport_container_spec(
        image=transport_image,
        name=f"xinao-transport-{run_id}",
        auth_host_path=auth_host_path,
        input_host_path=input_host_path,
        output_host_path=output_host_path,
        ipc_host_dir=ipc_host_dir,
        network=network,
        session_host_path=session_host_path,
        material_host_path=material_host_path,
        mcp_bridge_host_path=mcp_bridge_host_path,
        ipc_contract_host_path=ipc_contract_host_path,
        attempt_grok_config_host_path=attempt_grok_config_host_path,
        attempt_agent_profile_host_path=attempt_agent_profile_host_path,
        episode_lab_host_path=episode_lab_host_path,
        episode_id=episode_id,
        use_episode_entrypoint=use_episode_entrypoint,
        provider_egress_proxy_endpoint=provider_egress_proxy_endpoint,
    )
    tool = tool_executor_container_spec(
        image=tool_image,
        name=f"xinao-tool-{run_id}",
        episode_lab_host_path=episode_lab_host_path,
        ipc_host_dir=ipc_host_dir,
        sidecar_evidence_host_path=sidecar_evidence_host_path,
        ipc_peer_uids=ipc_peer_uids,
        bwrap_mode=bwrap_mode,
    )
    tool_violations = validate_tool_spec_invariants(tool)
    transport_violations = validate_transport_spec_invariants(transport)
    return {
        "schema_version": "xinao.dual_container_bundle.v1",
        "transport": transport,
        "tool_executor": tool,
        "transport_docker_create_argv": docker_create_argv(transport),
        "tool_docker_create_argv": docker_create_argv(tool),
        "tool_spec_violations": tool_violations,
        "transport_spec_violations": transport_violations,
        "fail_closed_before_provider": not tool_violations and not transport_violations,
        "ipc": {
            "transport": "unix_socket_or_stdio",
            "socket_container_path": f"{TOOL_IPC_MOUNT}/tool.sock",
            "contract": "xinao.dual_container_ipc.v1",
            "mcp_server_name": "episode_lab",
            "mcp_server_image_path": TRANSPORT_MCP_SERVER_IMAGE_PATH,
            "peer_require": True,
            "durable_replay_dir": TOOL_REPLAY_STATE,
        },
        "minimal_integrator_interface": {
            "tool_env_required": [
                "XINAO_TOOL_EXEC_BWRAP=require",
                "XINAO_IPC_PEER_REQUIRE=1",
                f"XINAO_IPC_PEER_UIDS={TRANSPORT_UID}",
                f"XINAO_REPLAY_STATE_DIR={TOOL_REPLAY_STATE}",
            ],
            "transport_mcp": {
                "tools_allowlist": [
                    "search_tool",
                    "use_tool",
                    "web_search",
                    "web_fetch",
                ],
                "lab_ops": ["ping", "list_dir", "read_file", "write_file", "shell_exec"],
                "server": "episode_lab",
                "mcp_events_path": TRANSPORT_MCP_EVENT_LOG,
                "research_profile_default": "OPEN_RESEARCH",
                "generic_file_shell_tools": False,
            },
            "validators": {
                "create_tool": "assert_tool_spec_fail_closed",
                "create_transport": "assert_transport_spec_fail_closed",
                "live_tool": "validate_tool_container_inspect",
                "live_transport": "validate_transport_container_inspect",
                "agreement": "create_spec_matches_inspect",
            },
        },
        "start_order": ["tool_executor", "transport_model"],
        "delta_vs_same_container": {
            "credential_co_location": "split: auth only in transport",
            "tool_namespace": "separate container; no shared PID/user/mount with auth",
            "network": "tool network=none by create spec",
            "writable_surface": "tool: episode-lab + private tmp only",
            "same_container_bwrap": "tool path uses bubblewrap require inside tool container",
            "ipc_peer": (f"XINAO_IPC_PEER_REQUIRE=1 + exact SO_PEERCRED uid={TRANSPORT_UID}"),
            "durable_replay_dir": TOOL_REPLAY_STATE,
            "model_tools": "attempt-local native MCP episode_lab → sidecar; no built-in generic file/shell",
        },
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }


def validate_transport_spec_invariants(spec: dict[str, Any]) -> list[str]:
    """Return violation strings if transport create spec drifts."""
    violations: list[str] = []
    if spec.get("role") != "transport_model":
        violations.append("role!=transport_model")
    if str(spec.get("user") or "") != TRANSPORT_USER:
        violations.append(f"user!={TRANSPORT_USER}")
    if "ALL" not in (spec.get("cap_drop") or []):
        violations.append("cap_drop missing ALL")
    if "no-new-privileges:true" not in (spec.get("security_opt") or []):
        violations.append("missing no-new-privileges")
    if spec.get("generic_file_shell_tools") is not False:
        violations.append("generic_file_shell_tools must be false")
    env = spec.get("env") or {}
    if env.get("XINAO_GENERIC_FILE_SHELL_TOOLS") != "0":
        violations.append("XINAO_GENERIC_FILE_SHELL_TOOLS must be 0")
    if env.get("XINAO_DUAL_CONTAINER") != "1":
        violations.append("XINAO_DUAL_CONTAINER must be 1")
    network = str(spec.get("network") or "none").strip().lower()
    expected_proxy = provider_egress_proxy_env(network=network)
    if network == DEFAULT_PROVIDER_EGRESS_NETWORK:
        if env.get("XINAO_EGRESS_ENV_POLICY_GENERATION") != PROVIDER_EGRESS_ENV_POLICY_GENERATION:
            violations.append("provider_egress_env_policy_generation_missing_or_wrong")
        for key, value in expected_proxy.items():
            if env.get(key) != value:
                violations.append(f"proxy_env_missing_or_wrong:{key}")
    elif network in {"", "none"}:
        if "XINAO_EGRESS_ENV_POLICY_GENERATION" in env:
            violations.append("provider_egress_env_policy_unexpected_on_offline_network")
        for key in PROVIDER_EGRESS_CONTROLLED_ENV_KEYS:
            if key in env:
                violations.append(f"proxy_env_unexpected_on_offline_network:{key}")
    else:
        violations.append(f"provider_egress_network_unsupported:{network}")
        if "XINAO_EGRESS_ENV_POLICY_GENERATION" in env:
            violations.append("provider_egress_env_policy_unexpected_on_unsupported_network")
        for key in PROVIDER_EGRESS_CONTROLLED_ENV_KEYS:
            if key in env:
                violations.append(f"proxy_env_unexpected_on_unsupported_network:{key}")
    entry = spec.get("entrypoint") or []
    entry_tokens = [str(x) for x in entry] if isinstance(entry, list) else [str(entry)]
    joined = " ".join(entry_tokens)
    canary_path = "/opt/xinao-researcher/entrypoint.py"
    episode_path = "/opt/xinao-researcher/episode_entrypoint.py"
    if episode_path in joined and not spec.get("episode_entrypoint_selected"):
        # Poisoned swap of canary→episode without explicit dual-host selection.
        violations.append("entrypoint!=canary")
    elif canary_path not in joined and episode_path not in joined:
        violations.append("entrypoint!=canary")
    # Episode transport must idle-hold until Owner attach; bare exit breaks docker exec.
    if episode_path in joined and "--self-describe" not in entry_tokens:
        if "--hold" not in entry_tokens:
            violations.append("episode_entrypoint_requires_hold")
        if spec.get("episode_entrypoint_selected") and not spec.get("episode_idle_hold", True):
            violations.append("episode_idle_hold_flag_missing")
    for bind in spec.get("binds") or []:
        host = str(bind.get("host", ""))
        container = str(bind.get("container", ""))
        lowered = f"{host}|{container}".lower()
        for marker in FORBIDDEN_MOUNT_MARKERS:
            if marker in lowered:
                violations.append(f"forbidden_bind:{container}")
        if container not in ALLOWED_TRANSPORT_BIND_TARGETS:
            violations.append(f"unexpected_bind:{container}")
        if (
            container == "/workspace"
            or host.rstrip("/").endswith("/workspace")
            or container.endswith("/workspace")
        ):
            violations.append(f"unexpected_bind_workspace:{container}")
    for field in (
        "completion_claim_allowed",
        "science_restored",
        "parent_complete",
        "owner_adopted",
    ):
        if spec.get(field) is not False:
            violations.append(f"authority_field:{field}")
    return violations


def _mounts_from_inspect(inspect_doc: dict[str, Any]) -> list[dict[str, Any]]:
    mounts = inspect_doc.get("Mounts") or inspect_doc.get("mounts") or []
    if not isinstance(mounts, list):
        return []
    return [m for m in mounts if isinstance(m, dict)]


def _host_config(inspect_doc: dict[str, Any]) -> dict[str, Any]:
    hc = inspect_doc.get("HostConfig") or inspect_doc.get("host_config") or {}
    return hc if isinstance(hc, dict) else {}


def _config(inspect_doc: dict[str, Any]) -> dict[str, Any]:
    cfg = inspect_doc.get("Config") or inspect_doc.get("config") or {}
    return cfg if isinstance(cfg, dict) else {}


def validate_tool_container_inspect(
    inspect_doc: dict[str, Any],
    *,
    expected_image_id: str | None = None,
    expected_episode_lab: str | None = None,
    expected_ipc: str | None = None,
) -> list[str]:
    """Prove live tool-executor container identity and isolation invariants."""
    violations: list[str] = []
    cfg = _config(inspect_doc)
    hc = _host_config(inspect_doc)
    image = str(inspect_doc.get("Image") or cfg.get("Image") or "")
    if expected_image_id and expected_image_id not in image and image != expected_image_id:
        # Accept prefix match when inspect returns short id.
        if not (
            expected_image_id.startswith(image)
            or image.startswith(expected_image_id.removeprefix("sha256:"))
        ):
            violations.append(f"image_id_mismatch:{image}")
    user = str(cfg.get("User") or "")
    if user not in {f"{TOOL_UID}:{TOOL_GID}", str(TOOL_UID), f"{TOOL_UID}:{TOOL_UID}"}:
        violations.append(f"user!={TOOL_UID}:{TOOL_GID}:{user}")
    network_mode = str(hc.get("NetworkMode") or "")
    if network_mode not in {"none", "None"}:
        violations.append(f"network!={network_mode}")
    if hc.get("ReadonlyRootfs") is not True:
        violations.append("read_only_rootfs required")
    cap_drop = {str(x).upper() for x in (hc.get("CapDrop") or [])}
    if "ALL" not in cap_drop:
        violations.append("cap_drop missing ALL")
    security_opt = [str(x) for x in (hc.get("SecurityOpt") or [])]
    if not any("no-new-privileges" in x.lower() for x in security_opt):
        violations.append("missing no-new-privileges")
    try:
        if not inspect_uses_tool_bwrap_seccomp_profile(security_opt):
            violations.append("bwrap_seccomp_profile_missing_or_wrong")
    except ToolSpecDriftError:
        violations.append("bwrap_seccomp_profile_missing_or_wrong")
    # Real Docker may place process tokens in Entrypoint only (image ENTRYPOINT)
    # or split across Entrypoint+Cmd (CLI --entrypoint first + args). Both are
    # valid; reconstruct via process_argv_from_inspect and never flag split as drift.
    process_argv = process_argv_from_inspect(inspect_doc)
    joined = " ".join(process_argv)
    if "tool_executor.py" not in joined:
        violations.append(f"entrypoint_unexpected:{joined}")
    # Reject the non-executable JSON-text shape that Docker CLI stores when a
    # caller passes a JSON array string as --entrypoint (physical start fails).
    raw_ep = cfg.get("Entrypoint") or []
    if isinstance(raw_ep, str) and raw_ep.lstrip().startswith("["):
        violations.append("entrypoint_json_text_not_executable")
    elif (
        isinstance(raw_ep, list)
        and len(raw_ep) == 1
        and isinstance(raw_ep[0], str)
        and raw_ep[0].lstrip().startswith("[")
    ):
        violations.append("entrypoint_json_text_not_executable")
    env_map: dict[str, str] = {}
    for item in cfg.get("Env") or []:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            env_map[k] = v
    for key in env_map:
        upper = key.upper()
        if upper.startswith(("GROK_", "XAI_")) or upper in {
            "GROK_HOME",
            "GROK_API_KEY",
            "XAI_API_KEY",
            "DOCKER_HOST",
            "SSH_AUTH_SOCK",
        }:
            violations.append(f"forbidden_env:{key}")
    bwrap = str(env_map.get("XINAO_TOOL_EXEC_BWRAP", "")).strip().lower()
    if bwrap not in {"auto", "require", "1", "on", "true", "yes"}:
        violations.append("bwrap_env_missing_or_off")
    if str(env_map.get("XINAO_IPC_PEER_REQUIRE", "")).strip() not in {
        "1",
        "true",
        "yes",
    }:
        violations.append("ipc_peer_require_missing")
    if str(env_map.get("XINAO_IPC_PEER_UIDS", "")).strip() != str(TRANSPORT_UID):
        violations.append(f"ipc_peer_uids!={TRANSPORT_UID}")
    replay_dir = str(env_map.get("XINAO_REPLAY_STATE_DIR", "")).strip()
    if not replay_dir or TOOL_IPC_MOUNT not in replay_dir:
        violations.append("durable_replay_state_not_on_ipc")
    destinations: set[str] = set()
    for mount in _mounts_from_inspect(inspect_doc):
        dest = str(mount.get("Destination") or mount.get("Target") or "")
        source = str(mount.get("Source") or mount.get("source") or "")
        destinations.add(dest)
        combined = f"{source}|{dest}".lower()
        for marker in FORBIDDEN_MOUNT_MARKERS:
            if marker in combined:
                violations.append(f"forbidden_mount:{dest}")
        if dest and dest not in {
            TOOL_LAB_MOUNT,
            TOOL_IPC_MOUNT,
            TOOL_TMP,
            TOOL_SIDECAR_EVIDENCE_MOUNT,
        }:
            # tmpfs /tmp may appear as mount
            if dest != TOOL_TMP:
                violations.append(f"unexpected_mount:{dest}")
    if expected_episode_lab and TOOL_LAB_MOUNT not in destinations:
        violations.append("missing_lab_mount")
    if expected_ipc and TOOL_IPC_MOUNT not in destinations:
        violations.append("missing_ipc_mount")
    return violations


def validate_transport_container_inspect(
    inspect_doc: dict[str, Any],
    *,
    expected_image_id: str | None = None,
    require_auth_mount: bool = True,
    require_ipc_mount: bool = True,
) -> list[str]:
    """Prove live transport container has exact mounts and no socket/ledger roots."""
    violations: list[str] = []
    cfg = _config(inspect_doc)
    hc = _host_config(inspect_doc)
    image = str(inspect_doc.get("Image") or cfg.get("Image") or "")
    if expected_image_id and expected_image_id not in image and image != expected_image_id:
        if not (
            expected_image_id.startswith(image)
            or image.startswith(expected_image_id.removeprefix("sha256:"))
        ):
            violations.append(f"image_id_mismatch:{image}")
    if str(cfg.get("User") or "") != TRANSPORT_USER:
        violations.append(f"user!={TRANSPORT_USER}:{cfg.get('User')}")
    cap_drop = {str(x).upper() for x in (hc.get("CapDrop") or [])}
    if "ALL" not in cap_drop:
        violations.append("cap_drop missing ALL")
    security_opt = [str(x).lower() for x in (hc.get("SecurityOpt") or [])]
    if not any("no-new-privileges" in x for x in security_opt):
        violations.append("missing no-new-privileges")
    env_list = cfg.get("Env") or []
    env_map: dict[str, str] = {}
    for item in env_list:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            env_map[key] = value
    if env_map.get("XINAO_GENERIC_FILE_SHELL_TOOLS") not in {None, "0"}:
        if env_map.get("XINAO_GENERIC_FILE_SHELL_TOOLS") != "0":
            violations.append("generic_file_shell_tools_env")
    # New pairs declare a policy generation and must preserve the exact create-time
    # route. Pre-fix pairs have no marker and remain recoverable through sealed
    # docker-exec env without stop/recreate.
    policy_generation = env_map.get("XINAO_EGRESS_ENV_POLICY_GENERATION")
    if policy_generation is not None:
        if policy_generation != PROVIDER_EGRESS_ENV_POLICY_GENERATION:
            violations.append("provider_egress_env_policy_generation")
        expected_proxy = provider_egress_proxy_env(
            network=DEFAULT_PROVIDER_EGRESS_NETWORK,
            endpoint=DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT,
        )
        for key, value in expected_proxy.items():
            if env_map.get(key) != value:
                violations.append(f"provider_egress_env:{key}")
    destinations: set[str] = set()
    for mount in _mounts_from_inspect(inspect_doc):
        dest = str(mount.get("Destination") or mount.get("Target") or "")
        source = str(mount.get("Source") or mount.get("source") or "")
        destinations.add(dest)
        combined = f"{source}|{dest}".lower()
        for marker in FORBIDDEN_MOUNT_MARKERS:
            if marker in combined:
                violations.append(f"forbidden_mount:{dest}")
        if dest == "/var/run/docker.sock" or dest.endswith("docker.sock"):
            violations.append("docker_socket_mounted")
    if require_auth_mount and TRANSPORT_AUTH_MOUNT not in destinations:
        # Accept flat auth.json or legacy nested .grok dir during transition.
        if not any(
            d in {TRANSPORT_AUTH_MOUNT, LEGACY_NESTED_AUTH_MOUNT}
            or d.rstrip("/").endswith("auth.json")
            or d.rstrip("/").endswith(".grok")
            for d in destinations
        ):
            violations.append("missing_auth_mount")
    if require_ipc_mount and TOOL_IPC_MOUNT not in destinations:
        violations.append("missing_ipc_mount")
    return violations


def ipc_volume_name(episode_id: str) -> str:
    """Stable docker volume name for one episode lease (no daemon)."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in episode_id)
    return f"xinao-ipc-{safe}"[:120]


def attempt_local_mcp_config_toml(
    *,
    episode_id: str,
    bridge_command: str = "python",
    bridge_args: list[str] | None = None,
    socket_path: str = f"{TOOL_IPC_MOUNT}/tool.sock",
) -> str:
    """Materialize attempt-local GROK_HOME config.toml for native episode_lab MCP.

    Prefer episode_mcp_binding.materialize_attempt_local_binding for full receipts.
    Built-in generic file/shell tools remain disabled separately via tools allowlist.
    """
    args = bridge_args or [
        "-I",
        TRANSPORT_MCP_SERVER_IMAGE_PATH,
        "--socket",
        socket_path,
        "--episode-id",
        episode_id,
        "--evidence-path",
        TRANSPORT_MCP_EVENT_LOG,
        "--timeout-ms",
        "600000",
    ]
    # TOML array of quoted strings.
    args_toml = ", ".join(f'"{a}"' for a in args)
    return (
        f"# Attempt-local dual-container native MCP (episode {episode_id})\n"
        f"[mcp_servers.episode_lab]\n"
        f'command = "{bridge_command}"\n'
        f"args = [{args_toml}]\n"
        f"enabled = true\n"
        f"startup_timeout_sec = 15\n"
        f"tool_timeout_sec = 600\n"
        f'env = {{ PYTHONPATH = "/opt/xinao-researcher", PYTHONUNBUFFERED = "1", '
        f'PYTHONUTF8 = "1", XINAO_EPISODE_ID = "{episode_id}", '
        f'XINAO_TOOL_IPC_SOCKET = "{socket_path}", '
        f'XINAO_MCP_EVIDENCE_PATH = "{TRANSPORT_MCP_EVENT_LOG}", '
        f'XINAO_MCP_EVENT_LOG = "{TRANSPORT_MCP_EVENT_LOG}" }}\n'
        f"\n"
        f"[features]\n"
        f"lsp_tools = false\n"
        f"\n"
        f"[subagents]\n"
        f"enabled = false\n"
        f"\n"
        f"[memory]\n"
        f"enabled = false\n"
    )


def pair_resource_names(episode_id: str) -> dict[str, str]:
    """Canonical names for containers/volumes owned by one episode lease."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in episode_id)
    short = safe[:80]
    return {
        "tool_name": f"xinao-tool-{short}",
        "transport_name": f"xinao-transport-{short}",
        "ipc_volume": ipc_volume_name(episode_id),
        "run_id": short,
    }


def create_spec_matches_inspect(
    create_spec: dict[str, Any],
    inspect_doc: dict[str, Any],
    *,
    role: str = "tool_executor",
) -> list[str]:
    """Return axes where create-spec validation and live inspect disagree.

    Empty list means create-spec fail-closed gates and inspect validators agree.
    """
    disagreements: list[str] = []
    if role == "tool_executor":
        create_v = set(validate_tool_spec_invariants(create_spec))
        live_v = set(validate_tool_container_inspect(inspect_doc))
        # Compare shared security axes present in either set.
        shared = {
            "network!=none",
            "user!=65532:65532",
            "cap_drop missing ALL",
            "cap_add must be empty",
            "missing no-new-privileges",
            "bwrap_seccomp_profile_missing_or_wrong",
            "read_only_rootfs required",
            "bwrap_env_missing_or_off",
            "ipc_peer_require_missing",
            "durable_replay_state_not_on_ipc",
        }
        for axis in sorted(shared):
            in_create = any(axis in v or v == axis for v in create_v)
            in_live = any(axis in v or v == axis for v in live_v)
            # Also match prefix-style violations
            in_create = in_create or axis in create_v
            in_live = in_live or axis in live_v
            if (axis in create_v) != (axis in live_v):
                disagreements.append(axis)
        # forbidden_env axes
        create_forbidden = {v for v in create_v if v.startswith("forbidden_env:")}
        live_forbidden = {v for v in live_v if v.startswith("forbidden_env:")}
        if create_forbidden != live_forbidden:
            disagreements.append("forbidden_env")
    else:
        create_v = validate_transport_spec_invariants(create_spec)
        live_v = validate_transport_container_inspect(inspect_doc)
        if bool(create_v) != bool(live_v):
            disagreements.append("transport_fail_closed_disagreement")
    return disagreements


def minimal_integrator_interface() -> dict[str, Any]:
    """Document the minimal dual-container security integrator surface."""
    return {
        "schema_version": "xinao.dual_container_security_interface.v1",
        "tool_env_required": [
            "XINAO_TOOL_EXEC_BWRAP=require",
            "XINAO_IPC_PEER_REQUIRE=1",
            f"XINAO_IPC_PEER_UIDS={TRANSPORT_UID}",
            f"XINAO_REPLAY_STATE_DIR={TOOL_REPLAY_STATE}",
        ],
        "durable_replay_dir": TOOL_REPLAY_STATE,
        "create_validators": {
            "create_tool": "assert_tool_spec_fail_closed",
            "create_transport": "assert_transport_spec_fail_closed",
            "inspect_tool": "validate_tool_container_inspect",
            "inspect_transport": "validate_transport_container_inspect",
            "agreement": "create_spec_matches_inspect",
        },
        "ipc_peer": f"XINAO_IPC_PEER_REQUIRE=1 + exact SO_PEERCRED uid={TRANSPORT_UID}",
        "network": "tool network=none by create spec",
        "completion_claim_allowed": False,
    }
