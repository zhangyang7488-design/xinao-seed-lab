"""Host-side dual-container ResearchEpisode pair orchestration (no daemon).

Owner-invoked one-shot verbs only (no resident controller):
- create exactly one authful transport + one no-auth tool sidecar with narrow IPC;
- validate image IDs, mounts, caps, NNP, network, identities, session UUID, and
  sealed pair receipt before start;
- materialize attempt-local native Grok MCP config (episode_lab only);
- status / checkpoint / forced interruption / fresh-process resume / cancel / retire.

Does not re-implement ResearchEpisode CAS/chain (lives in xinao_runtime).
Genuine scientist remains unavailable until live tool-namespace + model receipts.
completion_claim_allowed is always false. INSTRUMENT_CANARY is untouched.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Packaged host modules live under the Skill tree (skill-bundle / installed projection).
# Never walk monorepo parents or ~/.codex/docker for runtime resolution.
HOST_MODULES_DIRNAME = "host_modules"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_TRANSPORT_NETWORK = "xinao_researcher_internal"
TOOL_SOCKET_READY_TIMEOUT_SECONDS = 10.0
TOOL_SOCKET_READY_POLL_SECONDS = 0.05
TOOL_SOCKET_EXPECTED_MODE = 0o666
TOOL_IPC_DIRECTORY_EXPECTED_MODE = 0o711


def host_modules_dir() -> Path:
    """Resolve dual-host Python modules from the sealed Skill tree only.

    Preferred: ``scripts/host_modules`` co-located with this file (installed /
    skill-bundle). Source-tree unit tests may fall back to the monorepo
    ``docker/xinao-researcher`` cone only when that co-located package is
    absent and SKILL.md is co-located (authoring layout). Installed Skill under
    ``~/.codex/skills/xinao`` never has a monorepo docker sibling.
    """
    here = Path(__file__).resolve()
    scripts = here.parent
    packaged = scripts / HOST_MODULES_DIRNAME
    if (packaged / "docker_create_specs.py").is_file():
        return packaged
    skill_md = scripts.parent / "SKILL.md"
    # dual_container_host.py under skills/xinao/scripts → parents[3] = monorepo root.
    monorepo = here.parents[3] / "docker" / "xinao-researcher"
    if skill_md.is_file() and (monorepo / "docker_create_specs.py").is_file():
        return monorepo
    return packaged


PAIR_LEASE_SCHEMA = "xinao.dual_container_pair_lease.v1"
SESSION_INVENTORY_SCHEMA = "xinao.dual_container_session_inventory.v1"
CHECKPOINT_BIND_SCHEMA = "xinao.dual_container_checkpoint_bind.v1"
PAIR_RECEIPT_SCHEMA = "xinao.dual_container_pair_receipt.v1"
LEASE_FILENAME = "dual_container_pair_lease.json"
SESSION_INVENTORY_FILENAME = "session_inventory.json"
PAIR_RECEIPT_FILENAME = "dual_container_pair_receipt.json"
MCP_EVENTS_FILENAME = "mcp_events.jsonl"
CANONICAL_GROK_HOME = "/grok-home"
CANONICAL_LAB_CWD = "/episode-lab"
CANONICAL_MCP_EVENTS = "/output/mcp_events.jsonl"
CANONICAL_AGENT_PROFILE = "/grok-home/agents/genuine_scientist_mcp.md"
DEFAULT_RESEARCH_PROFILE = "OPEN_RESEARCH"
PAIR_PHASES = frozenset(
    {
        "created",
        "tool_started",
        "transport_started",
        "running",
        "interrupted",
        "checkpointed",
        "cancelled",
        "retired",
        "failed_retire_pending",
    }
)


class DualHostError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


DockerRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(dict(value)))
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise DualHostError("DUAL_HOST_JSON_INVALID", str(path))
    return value


def default_docker_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _load_specs_module() -> Any:
    import importlib.util
    import sys

    pkg = host_modules_dir()
    path = pkg / "docker_create_specs.py"
    name = "xinao_docker_create_specs_host"
    if name in sys.modules:
        return sys.modules[name]
    if not path.is_file():
        raise DualHostError("DUAL_HOST_SPECS_MISSING", str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise DualHostError("DUAL_HOST_SPECS_MISSING", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class DualHostConfig:
    transport_image: str
    tool_image: str
    auth_host_path: Path
    episode_root: Path
    # Live default: sealed provider egress internal network (tool stays network=none).
    network: str = DEFAULT_TRANSPORT_NETWORK
    # Supplied by xinao_runtime's live-seal observation for real provider work.
    egress_proxy_endpoint: str | None = None
    egress_live_seal_sha256: str | None = None
    material_host_path: Path | None = None
    docker: str = "docker"
    runner: DockerRunner | None = None
    # When true, skip docker engine and use synthetic IDs (unit tests).
    synthetic: bool = False


class DualContainerHost:
    """Lease-scoped create/inspect/start/attach/checkpoint/resume/cancel/retire."""

    def __init__(self, config: DualHostConfig) -> None:
        self.config = config
        self.runner = config.runner or default_docker_runner
        self.specs = _load_specs_module()
        self.episode_root = Path(config.episode_root)
        self.paths = {
            "root": self.episode_root,
            "lab": self.episode_root / "lab",
            "inputs": self.episode_root / "inputs",
            "output": self.episode_root / "output",
            "sessions": self.episode_root / "sessions",
            "attempt": self.episode_root / "attempt",
            "ipc_bind": self.episode_root / "ipc",
            # Tool-executor-only evidence (NOT mounted on transport).
            "sidecar_evidence": self.episode_root / "sidecar_evidence",
            "tool_events": self.episode_root / "sidecar_evidence" / "tool_events.jsonl",
            "lease": self.episode_root / LEASE_FILENAME,
            "session_inventory": self.episode_root / SESSION_INVENTORY_FILENAME,
            "pair_receipt": self.episode_root / PAIR_RECEIPT_FILENAME,
            "mcp_events": self.episode_root / "output" / MCP_EVENTS_FILENAME,
            "journal": self.episode_root / "dual_host_journal.jsonl",
        }

    def _run(self, argv: Sequence[str], *, reason: str) -> subprocess.CompletedProcess[str]:
        completed = self.runner(list(argv))
        if completed.returncode != 0:
            raise DualHostError(
                reason,
                f"argv={argv!r} rc={completed.returncode} stderr={completed.stderr!r}",
            )
        return completed

    def _wait_for_tool_socket_ready(
        self,
        container_id: str,
        *,
        timeout_seconds: float = TOOL_SOCKET_READY_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Prove the started tool can materialize its socket on the shared volume."""
        expected_uid = int(self.specs.TOOL_UID)
        expected_gid = int(self.specs.TOOL_GID)
        expected_mode = TOOL_SOCKET_EXPECTED_MODE
        probe = (
            "import json,os,stat;"
            "d=os.lstat('/ipc');s=os.lstat('/ipc/tool.sock');"
            "print(json.dumps({'uid':s.st_uid,'gid':s.st_gid,"
            "'mode':stat.S_IMODE(s.st_mode),'is_socket':stat.S_ISSOCK(s.st_mode),"
            "'directory_uid':d.st_uid,'directory_gid':d.st_gid,"
            "'directory_mode':stat.S_IMODE(d.st_mode),"
            "'directory_is_dir':stat.S_ISDIR(d.st_mode)},sort_keys=True))"
        )
        argv = [
            self.config.docker,
            "exec",
            str(container_id),
            "python",
            "-I",
            "-c",
            probe,
        ]
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        last_detail = "not attempted"
        while True:
            completed = self.runner(argv)
            if completed.returncode == 0:
                try:
                    observed = json.loads((completed.stdout or "").strip())
                except (TypeError, ValueError, json.JSONDecodeError):
                    observed = None
                if isinstance(observed, dict):
                    exact = {
                        "uid": expected_uid,
                        "gid": expected_gid,
                        "mode": expected_mode,
                        "is_socket": True,
                        "directory_uid": expected_uid,
                        "directory_gid": expected_gid,
                        "directory_mode": TOOL_IPC_DIRECTORY_EXPECTED_MODE,
                        "directory_is_dir": True,
                    }
                    normalized = {key: observed.get(key) for key in exact}
                    if normalized == exact:
                        return normalized
                    last_detail = f"socket stat mismatch:{normalized!r}"
                else:
                    last_detail = "socket stat output invalid"
            else:
                last_detail = (
                    f"rc={completed.returncode}:"
                    f"{(completed.stderr or completed.stdout or '')[:300]}"
                )
            if time.monotonic() >= deadline:
                raise DualHostError("DUAL_HOST_TOOL_SOCKET_NOT_READY", last_detail)
            time.sleep(TOOL_SOCKET_READY_POLL_SECONDS)

    def _best_effort_cleanup_create_partial(
        self,
        *,
        tool_id: str,
        transport_id: str,
        ipc_volume: str | None,
    ) -> list[str]:
        """Remove only containers/volume created in this create_pair attempt.

        Container rm requires a non-empty ID returned by a successful create in this
        call. Expected names are never delete authority (name conflict must not rm a
        pre-existing foreign container). Volume rm is allowed only when the caller
        proves this call created the volume (inspect-miss then create). Idempotent
        when targets are already gone.
        """
        errors: list[str] = []
        if self.config.synthetic:
            return errors
        seen: set[str] = set()
        # Ownership = concrete create stdout IDs only; never name fallback.
        for value in (tool_id, transport_id):
            target = str(value or "").strip()
            if not target or target in seen:
                continue
            seen.add(target)
            completed = self.runner([self.config.docker, "rm", "-f", target])
            if completed.returncode != 0:
                err = (completed.stderr or "").lower()
                if "no such container" not in err and "not found" not in err:
                    errors.append(f"rm:{target}:{completed.stderr}")
        if ipc_volume:
            vol = self.runner([self.config.docker, "volume", "rm", "-f", str(ipc_volume)])
            if vol.returncode != 0:
                err = (vol.stderr or "").lower()
                if "no such volume" not in err and "not found" not in err:
                    errors.append(f"volume:{ipc_volume}:{vol.stderr}")
        return errors

    def _append_journal(self, entry: Mapping[str, Any]) -> None:
        self.paths["journal"].parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.paths["journal"].open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def _ensure_layout(self) -> None:
        for key in (
            "lab",
            "inputs",
            "output",
            "sessions",
            "attempt",
            "ipc_bind",
            "sidecar_evidence",
        ):
            self.paths[key].mkdir(parents=True, exist_ok=True)

    def _load_mcp_binding(self) -> Any:
        import sys

        docker_pkg = host_modules_dir()
        path = docker_pkg / "episode_mcp_binding.py"
        name = "xinao_episode_mcp_binding_host"
        if name in sys.modules:
            return sys.modules[name]
        pkg = str(docker_pkg)
        if pkg not in sys.path:
            sys.path.insert(0, pkg)
        if not path.is_file():
            raise DualHostError("DUAL_HOST_MCP_BINDING_MISSING", str(path))
        if not (docker_pkg / "mcp_episode_lab_server.py").is_file():
            raise DualHostError(
                "DUAL_HOST_MCP_SERVER_MISSING",
                str(docker_pkg / "mcp_episode_lab_server.py"),
            )
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise DualHostError("DUAL_HOST_MCP_BINDING_LOAD_FAILED", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def _materialize_attempt_mcp(
        self,
        episode_id: str,
        *,
        research_profile: str = DEFAULT_RESEARCH_PROFILE,
    ) -> dict[str, Any]:
        """Materialize attempt-local native Grok MCP (episode_lab only; no fake bridge)."""
        bind_mod = self._load_mcp_binding()
        # Host files are bind-mounted onto /grok-home/*; container GROK_HOME must be /grok-home.
        grok_home = self.paths["attempt"] / "grok-home"
        grok_home.mkdir(parents=True, exist_ok=True)
        host_evidence = self.paths["mcp_events"]
        host_evidence.parent.mkdir(parents=True, exist_ok=True)
        receipt = bind_mod.materialize_attempt_local_binding(
            root=self.paths["attempt"],
            episode_id=episode_id,
            socket_path="/ipc/tool.sock",
            server_path="/opt/xinao-researcher/mcp_episode_lab_server.py",
            pythonpath="/opt/xinao-researcher",
            grok_home=grok_home,
            research_profile=research_profile,
            evidence_path=CANONICAL_MCP_EVENTS,
            host_evidence_mirror=host_evidence,
        )
        config_path = Path(receipt["config_toml"])
        profile_path = Path(receipt["agent_profile"])
        cfg_text = config_path.read_text(encoding="utf-8")
        if "mcp_servers.episode_lab" not in cfg_text:
            raise DualHostError("DUAL_HOST_MCP_CONFIG_INVALID", "episode_lab missing")
        if "mcp_episode_lab_server.py" not in cfg_text:
            raise DualHostError("DUAL_HOST_MCP_CONFIG_INVALID", "native server missing")
        if CANONICAL_MCP_EVENTS not in cfg_text:
            raise DualHostError("DUAL_HOST_MCP_EVIDENCE_PATH", "canonical events path missing")
        for bad in ("/output/mcp-evidence.jsonl", "/attempt/mcp-evidence.jsonl"):
            if bad in cfg_text:
                raise DualHostError("DUAL_HOST_MCP_EVIDENCE_FRAGMENT", bad)
        lab_grok = self.paths["lab"] / ".grok"
        lab_grok.mkdir(parents=True, exist_ok=True)
        (lab_grok / "config.toml").write_text(cfg_text, encoding="utf-8")
        return {
            "mcp_config": config_path,
            "agent_profile": profile_path,
            "grok_home": grok_home,
            "binding_receipt": receipt,
            "binding_receipt_sha256": str(receipt.get("receipt_sha256") or ""),
            "evidence_path": host_evidence,
            "canonical_evidence_path": CANONICAL_MCP_EVENTS,
            "research_profile": receipt.get("research_profile") or research_profile,
        }

    def load_lease(self) -> dict[str, Any] | None:
        if not self.paths["lease"].is_file():
            return None
        lease = _load_json(self.paths["lease"])
        if lease.get("schema_version") != PAIR_LEASE_SCHEMA:
            raise DualHostError("DUAL_HOST_LEASE_INVALID", "schema")
        return lease

    def _save_lease(self, lease: dict[str, Any]) -> None:
        _write_json_atomic(self.paths["lease"], lease)

    def _save_session_inventory(self, inventory: dict[str, Any]) -> None:
        _write_json_atomic(self.paths["session_inventory"], inventory)

    def load_session_inventory(self) -> dict[str, Any] | None:
        if not self.paths["session_inventory"].is_file():
            return None
        inv = _load_json(self.paths["session_inventory"])
        if inv.get("schema_version") != SESSION_INVENTORY_SCHEMA:
            raise DualHostError("DUAL_HOST_SESSION_INVENTORY_INVALID", "schema")
        return inv

    def resolve_image_id(self, image_ref: str) -> str:
        if self.config.synthetic:
            digest = _sha256_bytes(image_ref.encode("utf-8"))
            return f"sha256:{digest}"
        completed = self._run(
            [self.config.docker, "image", "inspect", "--format", "{{.Id}}", image_ref],
            reason="DUAL_HOST_IMAGE_INSPECT_FAILED",
        )
        image_id = completed.stdout.strip()
        if not image_id.startswith("sha256:"):
            raise DualHostError("DUAL_HOST_IMAGE_ID_INVALID", image_id)
        return image_id

    def create_pair(
        self,
        *,
        episode_id: str,
        session_id: str,
        resume_session_id: str | None = None,
        new_session_id: str | None = None,
        research_profile: str = DEFAULT_RESEARCH_PROFILE,
    ) -> dict[str, Any]:
        """Create IPC volume, materialize attempt MCP, create both containers (not start)."""
        if not episode_id or not session_id:
            raise DualHostError("DUAL_HOST_IDENTITY_INVALID", "episode/session required")
        existing = self.load_lease()
        if existing and existing.get("phase") not in {"cancelled", "retired"}:
            raise DualHostError("DUAL_HOST_LEASE_EXISTS", str(self.paths["lease"]))
        self._ensure_layout()
        profile = str(research_profile or DEFAULT_RESEARCH_PROFILE).strip().upper()
        if profile in {"GENUINE_SCIENTIST_EPISODE", "GENUINE", "GENUINE_SCIENTIST"}:
            profile = DEFAULT_RESEARCH_PROFILE
        if profile not in {"OPEN_RESEARCH", "CLOSED_LAB"}:
            raise DualHostError("DUAL_HOST_UNKNOWN_PROFILE", profile)
        attempt = self._materialize_attempt_mcp(episode_id, research_profile=profile)
        names = self.specs.pair_resource_names(episode_id)
        transport_image_id = self.resolve_image_id(self.config.transport_image)
        tool_image_id = self.resolve_image_id(self.config.tool_image)

        # IPC: prefer named volume; also keep bind dir for host-side socket observation.
        ipc_volume = names["ipc_volume"]
        volume_created_this_call = False
        if not self.config.synthetic:
            # Idempotent volume create; track ownership so partial fail only rm ours.
            probe = self.runner([self.config.docker, "volume", "inspect", ipc_volume])
            if probe.returncode != 0:
                self._run(
                    [self.config.docker, "volume", "create", ipc_volume],
                    reason="DUAL_HOST_VOLUME_CREATE_FAILED",
                )
                volume_created_this_call = True
            ipc_mount_type = "volume"
        else:
            ipc_mount_type = "bind"

        material_path = (
            str(self.config.material_host_path)
            if self.config.material_host_path is not None
            else str(self.paths["inputs"])
        )
        # Build create specs (bind ipc host dir for synthetic; volume for live).
        if ipc_mount_type == "volume":
            # docker create --mount type=volume for IPC; use host ipc_bind as volume mount
            # point via volume driver path is opaque — we mount volume at /ipc in containers.
            # For create argv we need a host path in current helper; materialize via
            # volume mount options in custom argv below.
            ipc_for_spec = str(self.paths["ipc_bind"])
        else:
            ipc_for_spec = str(self.paths["ipc_bind"])

        ipc_peer_uids = str(self.specs.TRANSPORT_UID)
        bundle = self.specs.dual_container_bundle(
            transport_image=transport_image_id,
            tool_image=tool_image_id,
            auth_host_path=str(self.config.auth_host_path),
            input_host_path=str(self.paths["inputs"]),
            output_host_path=str(self.paths["output"]),
            episode_lab_host_path=str(self.paths["lab"]),
            ipc_host_dir=ipc_for_spec,
            sidecar_evidence_host_path=str(self.paths["sidecar_evidence"]),
            run_id=names["run_id"],
            session_host_path=str(self.paths["sessions"]),
            material_host_path=material_path,
            # Native MCP: image-baked server; attempt-local GROK_HOME config + profile.
            attempt_grok_config_host_path=str(attempt["mcp_config"]),
            attempt_agent_profile_host_path=str(attempt["agent_profile"]),
            episode_id=episode_id,
            use_episode_entrypoint=True,
            ipc_peer_uids=ipc_peer_uids,
            # Synthetic/fake-client seats are always offline. Real transport consumes
            # only the live-seal-bound internal network supplied by xinao_runtime.
            network=(
                "none"
                if self.config.synthetic
                else str(self.config.network or DEFAULT_TRANSPORT_NETWORK)
            ),
            provider_egress_proxy_endpoint=str(self.config.egress_proxy_endpoint or ""),
        )
        if bundle["tool_spec_violations"] or bundle["transport_spec_violations"]:
            raise DualHostError(
                "DUAL_HOST_SPEC_VIOLATION",
                f"tool={bundle['tool_spec_violations']} transport={bundle['transport_spec_violations']}",
            )
        if not bundle.get("fail_closed_before_provider", False):
            raise DualHostError("DUAL_HOST_SPEC_NOT_FAIL_CLOSED", "pair specs")

        # Override names to lease-canonical.
        tool_spec = dict(bundle["tool_executor"])
        transport_spec = dict(bundle["transport"])
        tool_spec["name"] = names["tool_name"]
        transport_spec["name"] = names["transport_name"]
        # Live volume: replace ipc bind with volume mount in argv construction.
        tool_argv = self.specs.docker_create_argv(tool_spec)
        transport_argv = self.specs.docker_create_argv(transport_spec)
        if ipc_mount_type == "volume":
            tool_argv = _replace_ipc_bind_with_volume(tool_argv, ipc_volume)
            transport_argv = _replace_ipc_bind_with_volume(transport_argv, ipc_volume)

        if self.config.synthetic:
            tool_id = f"synthetic-tool-{_sha256_bytes(episode_id.encode())[:12]}"
            transport_id = f"synthetic-transport-{_sha256_bytes(session_id.encode())[:12]}"
            ipc_volume_source: str | None = None
        else:
            tool_id = ""
            transport_id = ""
            ipc_volume_source = None
            try:
                tool_id = self._run(tool_argv, reason="DUAL_HOST_TOOL_CREATE_FAILED").stdout.strip()
                transport_id = self._run(
                    transport_argv, reason="DUAL_HOST_TRANSPORT_CREATE_FAILED"
                ).stdout.strip()
                if not tool_id or not transport_id:
                    raise DualHostError("DUAL_HOST_CREATE_INCOMPLETE", f"{tool_id}/{transport_id}")
                if ipc_mount_type == "volume":
                    ipc_volume_source = _require_exact_ipc_volume_mounts(
                        tool_inspect=self._docker_inspect(tool_id),
                        transport_inspect=self._docker_inspect(transport_id),
                        expected_volume=ipc_volume,
                    )
            except DualHostError as exc:
                # Best-effort cleanup of only this call's owned containers/volume.
                # Container ownership = create-returned IDs only (names are journal-only).
                # Never touch foreign resources; preserve original failure reason.
                cleanup_errors = self._best_effort_cleanup_create_partial(
                    tool_id=tool_id,
                    transport_id=transport_id,
                    ipc_volume=ipc_volume if volume_created_this_call else None,
                )
                self._append_journal(
                    {
                        "verb": "create_pair_partial_fail",
                        "tool_id": tool_id,
                        "transport_id": transport_id,
                        # Names recorded for diagnosis only — not delete authority.
                        "tool_name": names["tool_name"],
                        "transport_name": names["transport_name"],
                        "ipc_volume": ipc_volume if volume_created_this_call else None,
                        "reason_code": exc.reason_code,
                        "detail": exc.detail,
                        "cleanup_errors": cleanup_errors,
                    }
                )
                raise DualHostError(exc.reason_code, exc.detail) from exc

        # Host ResearchEpisode session ids may be non-UUID tokens (xrsess_*).
        # Grok headless --session-id/--resume requires a UUID; keep both identities.
        def _as_uuid_session(value: str | None) -> str | None:
            if not value:
                return None
            try:
                return str(uuid.UUID(str(value)))
            except (ValueError, TypeError, AttributeError):
                return None

        grok_session = (
            _as_uuid_session(new_session_id)
            or _as_uuid_session(resume_session_id)
            or _as_uuid_session(session_id)
            or str(uuid.uuid4())
        )
        inventory = {
            "schema_version": SESSION_INVENTORY_SCHEMA,
            "episode_id": episode_id,
            "host_session_id": session_id,
            "grok_session_id": grok_session,
            "resume_mode": "resume" if resume_session_id else "session-id",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "transport_container_id": transport_id,
            "tool_container_id": tool_id,
            "durable_session_dir": str(self.paths["sessions"]),
            "authority": "host_episode_head_not_provider_memory",
            "research_profile": profile,
            "completion_claim_allowed": False,
        }
        self._save_session_inventory(inventory)
        # Bind supported CLI identity into pair receipt (fail closed on live probe mismatch).
        native_mod = self._load_native_session()
        supported_cli = getattr(native_mod, "SUPPORTED_GROK_CLI_VERSION", "0.2.117")
        if not self.config.synthetic:
            try:
                probe = native_mod.probe_grok_cli(require_supported_version=True)
                if probe.auth_error and str(probe.auth_error).startswith(
                    "GROK_CLI_VERSION_UNSUPPORTED"
                ):
                    raise DualHostError("GROK_CLI_VERSION_UNSUPPORTED", probe.auth_error)
            except DualHostError:
                raise
            except Exception:
                # Host probe optional when binary unavailable offline; receipt still pins version.
                pass
        pair_receipt = {
            "schema_version": PAIR_RECEIPT_SCHEMA,
            "episode_id": episode_id,
            "session_id": session_id,
            "tool_container_id": tool_id,
            "transport_container_id": transport_id,
            "tool_image_id": tool_image_id,
            "transport_image_id": transport_image_id,
            "tool_container_name": names["tool_name"],
            "transport_container_name": names["transport_name"],
            "ipc_volume": ipc_volume if ipc_mount_type == "volume" else None,
            "ipc_host_dir": str(self.paths["ipc_bind"]),
            "ipc_mount_type": ipc_mount_type,
            "ipc_volume_source": ipc_volume_source,
            "ipc_peer_uids": ipc_peer_uids,
            "sidecar_evidence_host_dir": str(self.paths["sidecar_evidence"]),
            "tool_sidecar_events_path": str(self.paths["tool_events"]),
            "socket_basename": "tool.sock",
            "mcp_server": "episode_lab",
            "mcp_config_sha256": _sha256_bytes(attempt["mcp_config"].read_bytes()),
            "mcp_binding_receipt_sha256": attempt.get("binding_receipt_sha256"),
            "generic_file_shell_tools": False,
            "supported_grok_cli_version": supported_cli,
            "daemon": False,
            "created_at": _utc_now(),
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        pair_receipt_bytes = _canonical_bytes(pair_receipt)
        pair_receipt_sha256 = _sha256_bytes(pair_receipt_bytes)
        pair_receipt["pair_receipt_sha256"] = pair_receipt_sha256
        _write_json_atomic(self.paths["pair_receipt"], pair_receipt)

        lease = {
            "schema_version": PAIR_LEASE_SCHEMA,
            "episode_id": episode_id,
            "session_id": session_id,
            "phase": "created",
            "ipc_volume": ipc_volume if ipc_mount_type == "volume" else None,
            "ipc_host_dir": str(self.paths["ipc_bind"]),
            "ipc_mount_type": ipc_mount_type,
            "ipc_volume_source": ipc_volume_source,
            "ipc_peer_uids": ipc_peer_uids,
            "tool_container_name": names["tool_name"],
            "transport_container_name": names["transport_name"],
            "tool_container_id": tool_id,
            "transport_container_id": transport_id,
            "tool_image_id": tool_image_id,
            "transport_image_id": transport_image_id,
            "tool_create_argv_sha256": _sha256_bytes(
                json.dumps(tool_argv, separators=(",", ":")).encode()
            ),
            "transport_create_argv_sha256": _sha256_bytes(
                json.dumps(transport_argv, separators=(",", ":")).encode()
            ),
            "mcp_config_sha256": _sha256_bytes(attempt["mcp_config"].read_bytes()),
            "mcp_binding_receipt_sha256": attempt.get("binding_receipt_sha256"),
            "pair_receipt_sha256": pair_receipt_sha256,
            "mcp_server": "episode_lab",
            "research_profile": profile,
            "generic_file_shell_tools": False,
            "daemon": False,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        self._save_lease(lease)
        self._append_journal(
            {
                "verb": "create_pair",
                "at": _utc_now(),
                "episode_id": episode_id,
                "session_id": session_id,
                "phase": "created",
                "tool_container_id": tool_id,
                "transport_container_id": transport_id,
                "pair_receipt_sha256": pair_receipt_sha256,
                "mcp_server": "episode_lab",
            }
        )
        return {
            "status": "PAIR_CREATED",
            "lease": lease,
            "session_inventory": inventory,
            "pair_receipt": pair_receipt,
            "tool_create_argv": tool_argv,
            "transport_create_argv": transport_argv,
            "start_order": ["tool_executor", "transport_model"],
            "mcp_server": "episode_lab",
            "completion_claim_allowed": False,
        }

    def inspect_pair(self) -> dict[str, Any]:
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", str(self.paths["lease"]))
        if self.config.synthetic:
            tool_inspect = _synthetic_tool_inspect(
                lease,
                seccomp_inspect_opt=self.specs.tool_bwrap_seccomp_inspect_opt(),
            )
            transport_inspect = _synthetic_transport_inspect(lease)
        else:
            tool_inspect = self._docker_inspect(str(lease["tool_container_id"]))
            transport_inspect = self._docker_inspect(str(lease["transport_container_id"]))
        tool_violations = self.specs.validate_tool_container_inspect(
            tool_inspect,
            expected_image_id=lease.get("tool_image_id"),
            expected_episode_lab=str(self.paths["lab"]),
            expected_ipc=str(self.paths["ipc_bind"]),
        )
        transport_violations = self.specs.validate_transport_container_inspect(
            transport_inspect,
            expected_image_id=lease.get("transport_image_id"),
        )
        expected_mount_type = "bind" if self.config.synthetic else "volume"
        if str(lease.get("ipc_mount_type") or "") != expected_mount_type:
            violation = (
                "ipc_mount_type_mismatch:"
                f"expected={expected_mount_type}:observed={lease.get('ipc_mount_type')}"
            )
            tool_violations.append(violation)
            transport_violations.append(violation)
        if str(lease.get("ipc_peer_uids") or "") != str(self.specs.TRANSPORT_UID):
            tool_violations.append(
                f"ipc_peer_lease!={self.specs.TRANSPORT_UID}:{lease.get('ipc_peer_uids')}"
            )
        if not self.config.synthetic and lease.get("ipc_mount_type") == "volume":
            expected_volume = str(lease.get("ipc_volume") or "")
            if not expected_volume:
                violation = "ipc_volume_missing_from_lease"
                tool_violations.append(violation)
                transport_violations.append(violation)
            else:
                try:
                    observed_source = _require_exact_ipc_volume_mounts(
                        tool_inspect=tool_inspect,
                        transport_inspect=transport_inspect,
                        expected_volume=expected_volume,
                    )
                except DualHostError as exc:
                    violation = f"{exc.reason_code}:{exc.detail}"
                    tool_violations.append(violation)
                    transport_violations.append(violation)
                else:
                    if observed_source != str(lease.get("ipc_volume_source") or ""):
                        violation = (
                            "ipc_volume_source_mismatch:"
                            f"lease={lease.get('ipc_volume_source')!r}:"
                            f"inspect={observed_source!r}"
                        )
                        tool_violations.append(violation)
                        transport_violations.append(violation)
        # Exact paired identity.
        identity_ok = (
            lease.get("episode_id")
            and lease.get("session_id")
            and lease.get("tool_container_id")
            and lease.get("transport_container_id")
        )
        inventory = self.load_session_inventory()
        if inventory and inventory.get("episode_id") != lease.get("episode_id"):
            tool_violations.append("session_inventory_episode_mismatch")
        if inventory and inventory.get("host_session_id") != lease.get("session_id"):
            tool_violations.append("session_inventory_session_mismatch")
        ok = not tool_violations and not transport_violations and bool(identity_ok)
        return {
            "status": "INSPECT_OK" if ok else "INSPECT_FAILED",
            "ok": ok,
            "lease": lease,
            "session_inventory": inventory,
            "tool_violations": tool_violations,
            "transport_violations": transport_violations,
            "tool_inspect_summary": _inspect_summary(tool_inspect),
            "transport_inspect_summary": _inspect_summary(transport_inspect),
            "paired_episode_id": lease.get("episode_id"),
            "paired_session_id": lease.get("session_id"),
            "completion_claim_allowed": False,
        }

    def _docker_inspect(self, container: str) -> dict[str, Any]:
        completed = self._run(
            [self.config.docker, "inspect", container],
            reason="DUAL_HOST_INSPECT_FAILED",
        )
        payload = json.loads(completed.stdout)
        if isinstance(payload, list):
            if not payload:
                raise DualHostError("DUAL_HOST_INSPECT_EMPTY", container)
            doc = payload[0]
        else:
            doc = payload
        if not isinstance(doc, dict):
            raise DualHostError("DUAL_HOST_INSPECT_INVALID", container)
        return doc

    def load_pair_receipt(self) -> dict[str, Any] | None:
        if not self.paths["pair_receipt"].is_file():
            return None
        receipt = _load_json(self.paths["pair_receipt"])
        if receipt.get("schema_version") != PAIR_RECEIPT_SCHEMA:
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_INVALID", "schema")
        return receipt

    def validate_before_start(self) -> dict[str, Any]:
        """Validate image IDs, inspect mounts/caps/NNP/network, identities, sealed receipt."""
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "validate_before_start")
        receipt = self.load_pair_receipt()
        if receipt is None:
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISSING", "validate_before_start")
        # Stale / swapped receipt attacks.
        for key in (
            "episode_id",
            "session_id",
            "tool_container_id",
            "transport_container_id",
            "tool_image_id",
            "transport_image_id",
            "ipc_mount_type",
            "ipc_volume",
            "ipc_volume_source",
            "ipc_peer_uids",
        ):
            if receipt.get(key) != lease.get(key):
                raise DualHostError(
                    "DUAL_HOST_PAIR_RECEIPT_MISMATCH",
                    f"{key}: receipt={receipt.get(key)} lease={lease.get(key)}",
                )
        expected_sha = lease.get("pair_receipt_sha256")
        # Recompute without embedded digest field for stability.
        body = {k: v for k, v in receipt.items() if k != "pair_receipt_sha256"}
        observed = _sha256_bytes(_canonical_bytes(body))
        if expected_sha and observed != expected_sha:
            raise DualHostError(
                "DUAL_HOST_PAIR_RECEIPT_STALE",
                f"expected={expected_sha} observed={observed}",
            )
        if expected_sha and receipt.get("pair_receipt_sha256") not in {None, expected_sha}:
            raise DualHostError(
                "DUAL_HOST_PAIR_RECEIPT_STALE",
                f"embedded={receipt.get('pair_receipt_sha256')} lease={expected_sha}",
            )
        inventory = self.load_session_inventory()
        if inventory is None:
            raise DualHostError("DUAL_HOST_SESSION_INVENTORY_MISSING", "validate_before_start")
        if inventory.get("host_session_id") != lease.get("session_id"):
            raise DualHostError("DUAL_HOST_SESSION_DRIFT", "inventory/lease session")
        if inventory.get("episode_id") != lease.get("episode_id"):
            raise DualHostError("DUAL_HOST_EPISODE_DRIFT", "inventory/lease episode")
        # UUID-ish session identity must be non-empty stable token.
        session_id = str(lease.get("session_id") or "")
        if len(session_id) < 8:
            raise DualHostError("DUAL_HOST_SESSION_UUID_INVALID", session_id)
        inspected = self.inspect_pair()
        if not inspected.get("ok"):
            raise DualHostError(
                "DUAL_HOST_PRESTART_INSPECT_FAILED",
                f"tool={inspected.get('tool_violations')} transport={inspected.get('transport_violations')}",
            )
        # Socket basename sealed on receipt.
        if receipt.get("socket_basename") not in {None, "tool.sock"}:
            raise DualHostError(
                "DUAL_HOST_SOCKET_BASENAME_INVALID", str(receipt.get("socket_basename"))
            )
        return {
            "status": "PRESTART_VALIDATED",
            "lease": lease,
            "pair_receipt": receipt,
            "inspect": inspected,
            "completion_claim_allowed": False,
        }

    def start_pair(self) -> dict[str, Any]:
        """Start tool sidecar first, then transport. Crash-safe journaling."""
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "start")
        if lease.get("phase") in {"cancelled", "retired", "failed_retire_pending"}:
            raise DualHostError("DUAL_HOST_LEASE_TERMINAL", str(lease.get("phase")))
        if lease.get("phase") == "running":
            return {
                "status": "START_IDEMPOTENT",
                "lease": lease,
                "completion_claim_allowed": False,
            }
        # Mid-crash after transport start but before phase=running was sealed:
        # both containers should already be up — advance lease only (idempotent).
        if lease.get("phase") == "transport_started":
            try:
                self.validate_before_start()
                if not self.config.synthetic:
                    socket_ready = self._wait_for_tool_socket_ready(str(lease["tool_container_id"]))
                    lease["tool_socket_ready"] = {
                        **socket_ready,
                        "observed_at": _utc_now(),
                    }
            except DualHostError as exc:
                lease["phase"] = "failed_retire_pending"
                lease["failure_reason"] = exc.reason_code
                lease["updated_at"] = _utc_now()
                self._save_lease(lease)
                self._append_journal(
                    {
                        "verb": "start_pair_failed",
                        "at": _utc_now(),
                        "reason_code": exc.reason_code,
                        "detail": exc.detail,
                        "phase": "failed_retire_pending",
                    }
                )
                raise
            lease["phase"] = "running"
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
            self._append_journal(
                {
                    "verb": "start_pair",
                    "at": _utc_now(),
                    "phase": "running",
                    "recovered_from": "transport_started",
                    "tool_container_id": lease["tool_container_id"],
                    "transport_container_id": lease["transport_container_id"],
                }
            )
            return {
                "status": "PAIR_STARTED",
                "lease": lease,
                "start_order": ["tool_executor", "transport_model"],
                "completion_claim_allowed": False,
            }

        # Validate sealed pair receipt + inspect before any start.
        self.validate_before_start()

        # Phase: tool first. tool_started resumes by starting transport only.
        try:
            if lease.get("phase") != "tool_started":
                if not self.config.synthetic:
                    if lease.get("phase") == "created":
                        self._run(
                            [self.config.docker, "start", str(lease["tool_container_id"])],
                            reason="DUAL_HOST_TOOL_START_FAILED",
                        )
                lease["phase"] = "tool_started"
                lease["updated_at"] = _utc_now()
                self._save_lease(lease)
                self._append_journal(
                    {
                        "verb": "start_tool",
                        "at": _utc_now(),
                        "tool_container_id": lease["tool_container_id"],
                        "phase": "tool_started",
                    }
                )
            if not self.config.synthetic:
                socket_ready = self._wait_for_tool_socket_ready(str(lease["tool_container_id"]))
                lease["tool_socket_ready"] = {
                    **socket_ready,
                    "observed_at": _utc_now(),
                }
                lease["updated_at"] = _utc_now()
                self._save_lease(lease)
                self._append_journal(
                    {
                        "verb": "tool_socket_ready",
                        "at": _utc_now(),
                        "tool_container_id": lease["tool_container_id"],
                        "socket": "/ipc/tool.sock",
                        "uid": socket_ready["uid"],
                        "gid": socket_ready["gid"],
                        "mode": socket_ready["mode"],
                    }
                )
            if not self.config.synthetic:
                self._run(
                    [self.config.docker, "start", str(lease["transport_container_id"])],
                    reason="DUAL_HOST_TRANSPORT_START_FAILED",
                )
            lease["phase"] = "transport_started"
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
            self._append_journal(
                {
                    "verb": "start_transport",
                    "at": _utc_now(),
                    "transport_container_id": lease["transport_container_id"],
                    "phase": "transport_started",
                }
            )
            lease["phase"] = "running"
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
            self._append_journal(
                {
                    "verb": "start_pair",
                    "at": _utc_now(),
                    "phase": "running",
                    "tool_container_id": lease["tool_container_id"],
                    "transport_container_id": lease["transport_container_id"],
                }
            )
            return {
                "status": "PAIR_STARTED",
                "lease": lease,
                "start_order": ["tool_executor", "transport_model"],
                "completion_claim_allowed": False,
            }
        except DualHostError as exc:
            lease["phase"] = "failed_retire_pending"
            lease["failure_reason"] = exc.reason_code
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
            self._append_journal(
                {
                    "verb": "start_pair_failed",
                    "at": _utc_now(),
                    "reason_code": exc.reason_code,
                    "detail": exc.detail,
                    "phase": "failed_retire_pending",
                }
            )
            raise

    def recover_or_retire_after_crash(self) -> dict[str, Any]:
        """If start crashed mid-way, either resume remaining start or safely retire."""
        lease = self.load_lease()
        if lease is None:
            return {"status": "NO_LEASE", "completion_claim_allowed": False}
        phase = lease.get("phase")
        if phase == "created":
            # Containers exist but never started — safe to start or retire.
            return {
                "status": "RECOVERABLE_CREATED",
                "lease": lease,
                "actions": ["start_pair", "retire_pair"],
                "completion_claim_allowed": False,
            }
        if phase == "tool_started":
            # Tool running; transport not started — may continue start or cancel.
            return {
                "status": "RECOVERABLE_TOOL_STARTED",
                "lease": lease,
                "actions": ["start_transport_only", "cancel_pair"],
                "completion_claim_allowed": False,
            }
        if phase == "failed_retire_pending":
            retired = self.retire_pair()
            return {
                "status": "RETIRED_AFTER_FAILURE",
                "retire": retired,
                "completion_claim_allowed": False,
            }
        if phase in {"running", "transport_started", "checkpointed", "interrupted"}:
            return {
                "status": "RECOVERABLE_RUNNING",
                "lease": lease,
                "actions": ["inspect_pair", "checkpoint_bind", "resume_pair", "cancel_pair"],
                "completion_claim_allowed": False,
            }
        if phase in {"cancelled", "retired"}:
            return {
                "status": "ALREADY_TERMINAL",
                "lease": lease,
                "completion_claim_allowed": False,
            }
        return {
            "status": "UNKNOWN_PHASE",
            "lease": lease,
            "completion_claim_allowed": False,
        }

    def start_transport_only(self) -> dict[str, Any]:
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "start_transport_only")
        if lease.get("phase") != "tool_started":
            raise DualHostError("DUAL_HOST_PHASE_INVALID", str(lease.get("phase")))
        self.validate_before_start()
        if not self.config.synthetic:
            socket_ready = self._wait_for_tool_socket_ready(str(lease["tool_container_id"]))
            lease["tool_socket_ready"] = {
                **socket_ready,
                "observed_at": _utc_now(),
            }
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
            self._run(
                [self.config.docker, "start", str(lease["transport_container_id"])],
                reason="DUAL_HOST_TRANSPORT_START_FAILED",
            )
        lease["phase"] = "running"
        lease["updated_at"] = _utc_now()
        self._save_lease(lease)
        self._append_journal(
            {
                "verb": "start_transport_only",
                "at": _utc_now(),
                "phase": "running",
            }
        )
        return {"status": "TRANSPORT_STARTED", "lease": lease, "completion_claim_allowed": False}

    def attach_pair(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Bounded non-daemon attach/log probe for both containers."""
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "attach")
        logs: dict[str, str] = {}
        if self.config.synthetic:
            logs = {
                "tool": "synthetic-tool-ready\n",
                "transport": "synthetic-transport-ready\n",
            }
        else:
            for role, cid in (
                ("tool", lease["tool_container_id"]),
                ("transport", lease["transport_container_id"]),
            ):
                completed = self.runner(
                    [
                        self.config.docker,
                        "logs",
                        "--tail",
                        "50",
                        str(cid),
                    ]
                )
                logs[role] = (completed.stdout or "")[:8000]
        return {
            "status": "ATTACH_PROBED",
            "timeout_seconds": timeout_seconds,
            "logs": logs,
            "tool_container_id": lease["tool_container_id"],
            "transport_container_id": lease["transport_container_id"],
            "completion_claim_allowed": False,
        }

    def collect_mcp_event_hashes(self) -> list[str]:
        path = self.paths["mcp_events"]
        if not path.is_file():
            return []
        hashes: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and isinstance(event.get("event_hash"), str):
                hashes.append(event["event_hash"])
            else:
                hashes.append(_sha256_bytes(line.encode("utf-8")))
        return hashes

    def capture_mcp_event_cursor(self) -> dict[str, Any]:
        native = self._load_native_session()
        return native.capture_mcp_event_cursor(self.paths["mcp_events"])

    def collect_attempt_mcp_delta(
        self,
        prior_cursor: Mapping[str, Any] | None,
        *,
        expected_episode_id: str | None = None,
    ) -> dict[str, Any]:
        native = self._load_native_session()
        try:
            return native.collect_attempt_mcp_delta(
                self.paths["mcp_events"],
                prior_cursor,
                expected_episode_id=expected_episode_id,
            )
        except native.NativeSessionError as exc:
            raise DualHostError(exc.reason_code, exc.detail) from exc

    def sealed_research_profile(self) -> str:
        lease = self.load_lease() or {}
        inv = self.load_session_inventory() or {}
        profile = (
            lease.get("research_profile") or inv.get("research_profile") or DEFAULT_RESEARCH_PROFILE
        )
        return str(profile).strip().upper()

    def checkpoint_bind(
        self,
        *,
        cas_sha256s: Mapping[str, str] | None = None,
        progress_note: str = "dual-container checkpoint",
    ) -> dict[str, Any]:
        """Bind both container IDs, MCP server/tool events, and CAS digests."""
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "checkpoint")
        inventory = self.load_session_inventory()
        mcp_hashes = self.collect_mcp_event_hashes()
        cas = dict(cas_sha256s or {})
        for digest in cas.values():
            if not isinstance(digest, str) or HEX_SHA256.fullmatch(digest) is None:
                raise DualHostError("DUAL_HOST_CAS_DIGEST_INVALID", str(digest))
        bind = {
            "schema_version": CHECKPOINT_BIND_SCHEMA,
            "episode_id": lease["episode_id"],
            "session_id": lease["session_id"],
            "tool_container_id": lease["tool_container_id"],
            "transport_container_id": lease["transport_container_id"],
            "tool_image_id": lease.get("tool_image_id"),
            "transport_image_id": lease.get("transport_image_id"),
            "mcp_event_hashes": mcp_hashes,
            "mcp_event_log_sha256": (
                _sha256_bytes(self.paths["mcp_events"].read_bytes())
                if self.paths["mcp_events"].is_file()
                else None
            ),
            "cas_sha256s": cas,
            "session_inventory_sha256": (
                _sha256_bytes(self.paths["session_inventory"].read_bytes())
                if self.paths["session_inventory"].is_file()
                else None
            ),
            "progress_note": progress_note,
            "created_at": _utc_now(),
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        bind_bytes = _canonical_bytes(bind)
        bind_sha256 = _sha256_bytes(bind_bytes)
        bind_path = self.paths["output"] / f"checkpoint_bind_{bind_sha256[:16]}.json"
        bind_path.write_bytes(bind_bytes)
        lease["phase"] = "checkpointed"
        lease["last_checkpoint_bind_sha256"] = bind_sha256
        lease["updated_at"] = _utc_now()
        self._save_lease(lease)
        if inventory is not None:
            inventory = dict(inventory)
            inventory["updated_at"] = _utc_now()
            inventory["last_checkpoint_bind_sha256"] = bind_sha256
            self._save_session_inventory(inventory)
        self._append_journal(
            {
                "verb": "checkpoint_bind",
                "at": _utc_now(),
                "checkpoint_bind_sha256": bind_sha256,
                "tool_container_id": lease["tool_container_id"],
                "transport_container_id": lease["transport_container_id"],
                "mcp_event_count": len(mcp_hashes),
            }
        )
        return {
            "status": "CHECKPOINT_BOUND",
            "checkpoint_bind": bind,
            "checkpoint_bind_sha256": bind_sha256,
            "lease": lease,
            "completion_claim_allowed": False,
        }

    def _load_native_session(self) -> Any:
        import sys

        docker_pkg = host_modules_dir()
        path = docker_pkg / "native_grok_session.py"
        name = "xinao_native_grok_session_host"
        if name in sys.modules:
            return sys.modules[name]
        if not path.is_file():
            raise DualHostError("DUAL_HOST_NATIVE_SESSION_MISSING", str(path))
        pkg = str(docker_pkg)
        if pkg not in sys.path:
            sys.path.insert(0, pkg)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise DualHostError("DUAL_HOST_NATIVE_SESSION_LOAD_FAILED", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def build_grok_session_argv(
        self,
        *,
        resume: bool,
        session_id: str,
        extra: Sequence[str] | None = None,
        tools: str | None = None,
        max_turns: int | None = None,
        model: str | None = None,
        prompt: str | None = None,
        prompt_file: str | None = None,
        agent_profile: str | None = None,
        research_profile: str | None = None,
    ) -> list[str]:
        """Real Grok headless session rules: --session-id / --resume + MCP meta (+ web).

        OPEN_RESEARCH (default): search_tool,use_tool,web_search,web_fetch; no --disable-web-search.
        CLOSED_LAB: search_tool,use_tool; --disable-web-search; web stripped.
        Canary remains separate with --tools '' on its own entrypoint.
        --cwd is the mounted lab path; --agent is the mounted profile path.
        """
        native = self._load_native_session()
        profile = native.normalize_research_profile(
            research_profile or self.sealed_research_profile()
        )
        expected_tools = native.tools_allowlist_csv(profile)
        if tools is not None and tools != expected_tools:
            raise DualHostError("DUAL_HOST_TOOLS_NOT_GENUINE", f"{tools}!={expected_tools}")
        turns = native.clamp_live_max_turns(max_turns)
        model_name = model or native.DEFAULT_LIVE_MODEL
        agent = agent_profile if agent_profile is not None else CANONICAL_AGENT_PROFILE
        argv = native.build_genuine_session_argv(
            grok_bin="/usr/local/bin/grok",
            session_id=session_id,
            resume=resume,
            model=model_name,
            max_turns=turns,
            prompt=prompt,
            prompt_file=prompt_file,
            agent_profile=agent,
            cwd=CANONICAL_LAB_CWD,
            include_disallowed_builtins=True,
            research_profile=profile,
            extra=extra,
        )
        native.assert_live_research_argv(argv, research_profile=profile)
        return argv

    def interrupt_pair(self) -> dict[str, Any]:
        """Forced interruption: stop transport first (keep tool optional), mark interrupted."""
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "interrupt")
        if lease.get("phase") in {"cancelled", "retired"}:
            raise DualHostError("DUAL_HOST_LEASE_TERMINAL", str(lease.get("phase")))
        if not self.config.synthetic:
            # Prefer stopping transport so model process ends; tool may remain for checkpoint.
            cid = lease.get("transport_container_id")
            if cid:
                self.runner([self.config.docker, "stop", "-t", "2", str(cid)])
        lease["phase"] = "interrupted"
        lease["updated_at"] = _utc_now()
        self._save_lease(lease)
        self._append_journal(
            {
                "verb": "interrupt_pair",
                "at": _utc_now(),
                "phase": "interrupted",
                "transport_container_id": lease.get("transport_container_id"),
                "tool_container_id": lease.get("tool_container_id"),
            }
        )
        return {
            "status": "PAIR_INTERRUPTED",
            "lease": lease,
            "completion_claim_allowed": False,
        }

    def resume_pair(
        self,
        *,
        expected_session_id: str,
        mark_interrupted_first: bool = False,
    ) -> dict[str, Any]:
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "resume")
        if lease.get("phase") in {"cancelled", "retired"}:
            raise DualHostError("DUAL_HOST_LEASE_TERMINAL", str(lease.get("phase")))
        inventory = self.load_session_inventory()
        if inventory is None:
            raise DualHostError("DUAL_HOST_SESSION_INVENTORY_MISSING", "resume")
        if inventory.get("host_session_id") != expected_session_id:
            raise DualHostError(
                "DUAL_HOST_FOREIGN_SESSION",
                f"expected={expected_session_id} actual={inventory.get('host_session_id')}",
            )
        if lease.get("session_id") != expected_session_id:
            raise DualHostError(
                "DUAL_HOST_RESUME_IDENTITY_DRIFT",
                f"lease_session={lease.get('session_id')} expected={expected_session_id}",
            )
        if inventory.get("episode_id") != lease.get("episode_id"):
            raise DualHostError("DUAL_HOST_FOREIGN_EPISODE", "inventory/lease mismatch")
        # Fresh-process resume also re-validates sealed pair receipt identities.
        receipt = self.load_pair_receipt()
        if receipt is not None:
            if receipt.get("session_id") != expected_session_id:
                raise DualHostError("DUAL_HOST_RESUME_IDENTITY_DRIFT", "receipt session")
            if receipt.get("tool_container_id") != lease.get("tool_container_id"):
                raise DualHostError("DUAL_HOST_SWAPPED_CONTAINER", "tool")
            if receipt.get("transport_container_id") != lease.get("transport_container_id"):
                raise DualHostError("DUAL_HOST_SWAPPED_CONTAINER", "transport")
            if receipt.get("tool_image_id") != lease.get("tool_image_id"):
                raise DualHostError("DUAL_HOST_WRONG_IMAGE", "tool")
            if receipt.get("transport_image_id") != lease.get("transport_image_id"):
                raise DualHostError("DUAL_HOST_WRONG_IMAGE", "transport")
            for key in (
                "ipc_mount_type",
                "ipc_volume",
                "ipc_volume_source",
                "ipc_peer_uids",
            ):
                if receipt.get(key) != lease.get(key):
                    raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISMATCH", key)
        if mark_interrupted_first:
            lease["phase"] = "interrupted"
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
        grok_session = str(inventory.get("grok_session_id") or expected_session_id)
        resume_argv = self.build_grok_session_argv(resume=True, session_id=grok_session)
        # Ensure containers are running: tool first.
        if lease.get("phase") in {"created", "interrupted", "checkpointed", "tool_started"}:
            self.validate_before_start()
            if lease.get("phase") == "created":
                self.start_pair()
                lease = self.load_lease() or lease
            elif lease.get("phase") == "tool_started":
                self.start_transport_only()
                lease = self.load_lease() or lease
            else:
                # Restart both if needed (idempotent docker start).
                if not self.config.synthetic:
                    self.runner([self.config.docker, "start", str(lease["tool_container_id"])])
                    socket_ready = self._wait_for_tool_socket_ready(str(lease["tool_container_id"]))
                    lease["tool_socket_ready"] = {
                        **socket_ready,
                        "observed_at": _utc_now(),
                    }
                    self.runner([self.config.docker, "start", str(lease["transport_container_id"])])
                lease["phase"] = "running"
                lease["updated_at"] = _utc_now()
                self._save_lease(lease)
        inventory = dict(inventory)
        inventory["resume_mode"] = "resume"
        inventory["updated_at"] = _utc_now()
        inventory["last_resume_argv_markers"] = {
            "resume": grok_session,
            "tools": "profile_sealed",
            "research_profile": self.sealed_research_profile(),
            "generic_file_shell_tools": False,
        }
        self._save_session_inventory(inventory)
        self._append_journal(
            {
                "verb": "resume_pair",
                "at": _utc_now(),
                "session_id": expected_session_id,
                "grok_session_id": grok_session,
                "planned_grok_argv": resume_argv,
            }
        )
        return {
            "status": "PAIR_RESUMED",
            "lease": lease,
            "session_inventory": inventory,
            "planned_grok_argv": resume_argv,
            "exact_session_bound": True,
            "completion_claim_allowed": False,
        }

    def require_live_pair_ready(
        self,
        *,
        expected_episode_id: str | None = None,
        expected_host_session_id: str | None = None,
        expected_provider_session_uuid: str | None = None,
        expected_pair_receipt_sha256: str | None = None,
        expected_transport_image_id: str | None = None,
        expected_tool_image_id: str | None = None,
        allow_synthetic: bool = False,
    ) -> dict[str, Any]:
        """Fail closed before any live docker exec attach/run/resume."""
        if self.config.synthetic and not allow_synthetic:
            raise DualHostError("DUAL_HOST_SYNTHETIC_LIVE_REFUSED", "synthetic=true")
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "live_ready")
        inventory = self.load_session_inventory()
        if inventory is None:
            raise DualHostError("DUAL_HOST_SESSION_INVENTORY_MISSING", "live_ready")
        receipt = self.load_pair_receipt()
        if receipt is None:
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISSING", "live_ready")
        if lease.get("phase") in {"cancelled", "retired", "failed_retire_pending"}:
            raise DualHostError("DUAL_HOST_LEASE_TERMINAL", str(lease.get("phase")))
        if expected_episode_id and lease.get("episode_id") != expected_episode_id:
            raise DualHostError("DUAL_HOST_FOREIGN_EPISODE", str(lease.get("episode_id")))
        if expected_host_session_id and lease.get("session_id") != expected_host_session_id:
            raise DualHostError("DUAL_HOST_FOREIGN_SESSION", str(lease.get("session_id")))
        if inventory.get("episode_id") != lease.get("episode_id"):
            raise DualHostError("DUAL_HOST_EPISODE_DRIFT", "inventory/lease")
        if inventory.get("host_session_id") != lease.get("session_id"):
            raise DualHostError("DUAL_HOST_SESSION_DRIFT", "inventory/lease")
        if receipt.get("episode_id") != lease.get("episode_id"):
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISMATCH", "episode_id")
        if receipt.get("session_id") != lease.get("session_id"):
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISMATCH", "session_id")
        for key in (
            "tool_container_id",
            "transport_container_id",
            "tool_image_id",
            "transport_image_id",
            "ipc_mount_type",
            "ipc_volume",
            "ipc_volume_source",
            "ipc_peer_uids",
        ):
            if receipt.get(key) != lease.get(key):
                raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISMATCH", key)
        body = {k: v for k, v in receipt.items() if k != "pair_receipt_sha256"}
        observed_receipt = _sha256_bytes(_canonical_bytes(body))
        if lease.get("pair_receipt_sha256") and observed_receipt != lease.get(
            "pair_receipt_sha256"
        ):
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_STALE", observed_receipt)
        if expected_pair_receipt_sha256 and observed_receipt != expected_pair_receipt_sha256:
            raise DualHostError("DUAL_HOST_PAIR_RECEIPT_MISMATCH", "caller hash")
        if (
            expected_transport_image_id
            and lease.get("transport_image_id") != expected_transport_image_id
        ):
            raise DualHostError("DUAL_HOST_WRONG_IMAGE", "transport")
        if expected_tool_image_id and lease.get("tool_image_id") != expected_tool_image_id:
            raise DualHostError("DUAL_HOST_WRONG_IMAGE", "tool")
        grok_session = str(inventory.get("grok_session_id") or "")
        if expected_provider_session_uuid:
            if (
                not grok_session
                or grok_session.lower() != str(expected_provider_session_uuid).lower()
            ):
                raise DualHostError(
                    "DUAL_HOST_PROVIDER_SESSION_MISMATCH",
                    f"inventory={grok_session} expected={expected_provider_session_uuid}",
                )
        # Live path must not expose auth to tool sidecar (inspect mounts).
        # Synthetic never pretends to satisfy live network/running proofs.
        if not self.config.synthetic:
            tool_inspect = self._docker_inspect(str(lease["tool_container_id"]))
            transport_inspect = self._docker_inspect(str(lease["transport_container_id"]))
            tool_mounts = [
                str(m.get("Destination") or m.get("Target") or "").lower()
                for m in (tool_inspect.get("Mounts") or [])
                if isinstance(m, dict)
            ]
            for bad in ("/grok-home", "auth.json", "docker.sock"):
                if any(bad in m for m in tool_mounts):
                    raise DualHostError("DUAL_HOST_AUTH_ON_TOOL", bad)
            if lease.get("ipc_mount_type") != "volume":
                raise DualHostError(
                    "DUAL_HOST_IPC_VOLUME_MISMATCH",
                    f"lease mount type={lease.get('ipc_mount_type')!r}",
                )
            if str(lease.get("ipc_peer_uids") or "") != str(self.specs.TRANSPORT_UID):
                raise DualHostError(
                    "DUAL_HOST_IPC_PEER_MISMATCH",
                    f"lease={lease.get('ipc_peer_uids')!r}",
                )
            expected_volume = str(lease.get("ipc_volume") or "")
            if not expected_volume:
                raise DualHostError("DUAL_HOST_IPC_VOLUME_MISMATCH", "lease volume missing")
            observed_volume_source = _require_exact_ipc_volume_mounts(
                tool_inspect=tool_inspect,
                transport_inspect=transport_inspect,
                expected_volume=expected_volume,
            )
            if observed_volume_source != str(lease.get("ipc_volume_source") or ""):
                raise DualHostError(
                    "DUAL_HOST_IPC_VOLUME_MISMATCH",
                    f"lease source={lease.get('ipc_volume_source')!r}:"
                    f"inspect source={observed_volume_source!r}",
                )
            # Network fail-closed: tool must stay none; transport must match config.
            tool_hc = tool_inspect.get("HostConfig") or {}
            transport_hc = transport_inspect.get("HostConfig") or {}
            tool_network = str(tool_hc.get("NetworkMode") or "")
            if tool_network not in {"none", "None"}:
                raise DualHostError("DUAL_HOST_TOOL_NETWORK_NOT_NONE", tool_network)
            expected_transport_network = str(
                self.config.network or DEFAULT_TRANSPORT_NETWORK
            ).strip()
            transport_network = str(transport_hc.get("NetworkMode") or "")
            transport_networks = (transport_inspect.get("NetworkSettings") or {}).get(
                "Networks"
            ) or {}
            if not expected_transport_network or expected_transport_network in {
                "none",
                "None",
            }:
                # Mis-set XINAO_TRANSPORT_NETWORK=none (or empty) must not go live offline.
                raise DualHostError(
                    "DUAL_HOST_TRANSPORT_NETWORK_MISMATCH",
                    f"expected_live_network invalid={expected_transport_network!r} "
                    f"observed={transport_network!r}",
                )
            network_ok = transport_network == expected_transport_network or (
                isinstance(transport_networks, dict)
                and expected_transport_network in transport_networks
            )
            if not network_ok:
                raise DualHostError(
                    "DUAL_HOST_TRANSPORT_NETWORK_MISMATCH",
                    f"expected={expected_transport_network} observed={transport_network}",
                )
            for role, doc, expected_image in (
                ("tool", tool_inspect, lease.get("tool_image_id")),
                ("transport", transport_inspect, lease.get("transport_image_id")),
            ):
                image = doc.get("Image") or (doc.get("Config") or {}).get("Image")
                if expected_image and image and image != expected_image:
                    # Docker may report short ids; still require exact sealed match when present.
                    if not str(image).startswith(str(expected_image)) and not str(
                        expected_image
                    ).startswith(str(image)):
                        raise DualHostError("DUAL_HOST_WRONG_IMAGE", f"{role}:{image}")
                state = doc.get("State") or {}
                running = state.get("Running")
                if running is not True:
                    raise DualHostError(
                        "DUAL_HOST_CONTAINER_STOPPED",
                        f"{role}:running={running!r}",
                    )
            socket_ready = self._wait_for_tool_socket_ready(str(lease["tool_container_id"]))
        else:
            socket_ready = None
        return {
            "status": "LIVE_PAIR_READY",
            "lease": lease,
            "session_inventory": inventory,
            "pair_receipt": receipt,
            "pair_receipt_sha256": observed_receipt,
            "provider_session_uuid": grok_session,
            "tool_socket_ready": socket_ready,
            "completion_claim_allowed": False,
        }

    def exec_transport_grok(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Real docker exec into transport container; never host Grok fallback."""
        if self.config.synthetic:
            raise DualHostError("DUAL_HOST_SYNTHETIC_LIVE_REFUSED", "exec")
        lease = self.load_lease()
        if lease is None:
            raise DualHostError("DUAL_HOST_LEASE_MISSING", "exec")
        transport_id = str(lease.get("transport_container_id") or "")
        if not transport_id or transport_id.startswith("synthetic-"):
            raise DualHostError("DUAL_HOST_TRANSPORT_INVALID", transport_id)
        native = self._load_native_session()
        # Profile is sealed into argv; assert without forcing a mismatched profile.
        native.assert_live_research_argv(
            list(argv), research_profile=self.sealed_research_profile()
        )
        docker_argv: list[str] = [self.config.docker, "exec", "-i"]
        env_map = dict(env or {})
        if env_map.get("GROK_HOME", CANONICAL_GROK_HOME) != CANONICAL_GROK_HOME:
            raise DualHostError(
                "DUAL_HOST_GROK_HOME_MISALIGNED",
                str(env_map.get("GROK_HOME")),
            )
        env_map.setdefault("GROK_HOME", CANONICAL_GROK_HOME)
        env_map.setdefault("XINAO_MCP_EVENT_LOG", CANONICAL_MCP_EVENTS)
        env_map.setdefault("XINAO_MCP_EVIDENCE_PATH", CANONICAL_MCP_EVENTS)
        network = str(self.config.network or "").strip().lower()
        if network != DEFAULT_TRANSPORT_NETWORK:
            raise DualHostError(
                "DUAL_HOST_TRANSPORT_NETWORK_UNSUPPORTED",
                network or "none",
            )
        endpoint = str(self.config.egress_proxy_endpoint or "").strip()
        seal_sha256 = str(self.config.egress_live_seal_sha256 or "").strip().lower()
        if not endpoint or HEX_SHA256.fullmatch(seal_sha256) is None:
            raise DualHostError("DUAL_HOST_EGRESS_POLICY_UNBOUND", "live seal endpoint/hash")
        # Live dual transport sits on internal net without default DNS/route to
        # provider hosts. Inject sealed HTTP(S)_PROXY on every exec so headless
        # grok -p can CONNECT via xinao-researcher-egress-proxy even when the
        # container was created without proxy Config.Env (pre-fix pairs).
        proxy_env = self.specs.provider_egress_proxy_env(network=network, endpoint=endpoint)
        if not proxy_env:
            raise DualHostError("DUAL_HOST_EGRESS_POLICY_UNBOUND", network)
        for key, value in proxy_env.items():
            # These keys are part of the sealed egress route. Caller values must
            # never override the endpoint or bypass it through NO/ALL_PROXY.
            env_map[key] = value
        for key, value in env_map.items():
            docker_argv.extend(["-e", f"{key}={value}"])
        docker_argv.append(transport_id)
        docker_argv.extend(list(argv))
        try:
            return subprocess.run(
                docker_argv,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=float(timeout_seconds),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            if isinstance(stdout, str):
                stdout = stdout.encode("utf-8", errors="replace")
            if isinstance(stderr, str):
                stderr = stderr.encode("utf-8", errors="replace")
            return subprocess.CompletedProcess(
                args=list(docker_argv),
                returncode=124,
                stdout=stdout,
                stderr=stderr + b"\nDUAL_HOST_OUTER_TIMEOUT\n",
            )
        except OSError as exc:
            raise DualHostError("DUAL_HOST_DOCKER_EXEC_FAILED", str(exc)) from exc

    def _scan_lab_artifact_manifest(self) -> dict[str, Any]:
        lab = self.paths["lab"]
        artifacts: list[dict[str, str]] = []
        if lab.is_dir():
            for path in sorted(lab.rglob("*")):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(lab)).replace("\\", "/")
                if rel.startswith("."):
                    continue
                payload = path.read_bytes()
                artifacts.append(
                    {
                        "path": rel,
                        "sha256": _sha256_bytes(payload),
                        "size": str(len(payload)),
                    }
                )
        return {"artifacts": artifacts}

    def attach_run_live(
        self,
        *,
        prompt: str,
        max_turns: int | None = None,
        timeout_seconds: float | None = None,
        expected_episode_id: str | None = None,
        expected_host_session_id: str | None = None,
        cas_head_sha256: str | None = None,
        namespace_receipt_sha256: str | None = None,
        release_id: str | None = None,
        release_identity_sha256: str | None = None,
        plan_only: bool = False,
    ) -> dict[str, Any]:
        """Owner one-shot: validate live pair and docker-exec multi-turn Grok in transport."""
        native = self._load_native_session()
        ready = self.require_live_pair_ready(
            expected_episode_id=expected_episode_id,
            expected_host_session_id=expected_host_session_id,
            allow_synthetic=False,
        )
        lease = ready["lease"]
        inventory = ready["session_inventory"]
        grok_session = str(inventory.get("grok_session_id") or "")
        if not native.is_uuid(grok_session):
            raise DualHostError("DUAL_HOST_PROVIDER_SESSION_NOT_UUID", grok_session)
        research_profile = self.sealed_research_profile()
        turns = native.clamp_live_max_turns(max_turns)
        timeout = native.clamp_outer_timeout(timeout_seconds)
        argv = self.build_grok_session_argv(
            resume=False,
            session_id=grok_session,
            max_turns=turns,
            prompt=prompt,
            agent_profile=CANONICAL_AGENT_PROFILE,
            research_profile=research_profile,
        )
        if plan_only:
            return {
                "status": native.STATUS_PLANNED,
                "planned_grok_argv": argv,
                "provider_session_uuid": grok_session,
                "research_profile": research_profile,
                "live_executed": False,
                "completion_claim_allowed": False,
                "science_restored": False,
                "owner_adopted": False,
                "parent_complete": False,
            }
        prior_cursor = self.capture_mcp_event_cursor()
        prior_tool_cursor = native.capture_tool_sidecar_cursor(self.paths["tool_events"])
        prior_lab_manifest = self._scan_lab_artifact_manifest()
        started_at = _utc_now()
        docker_exec_failed = False
        timed_out = False
        try:
            completed = self.exec_transport_grok(
                argv,
                timeout_seconds=timeout,
                env={
                    "GROK_HOME": CANONICAL_GROK_HOME,
                    "XINAO_MCP_BINDING": "1",
                    "XINAO_MCP_SERVER": "episode_lab",
                    "XINAO_MCP_TOOLS": native.tools_allowlist_csv(research_profile),
                    "XINAO_MCP_EVENT_LOG": CANONICAL_MCP_EVENTS,
                    "XINAO_MCP_EVIDENCE_PATH": CANONICAL_MCP_EVENTS,
                    "XINAO_RESEARCH_PROFILE": research_profile,
                },
            )
        except DualHostError:
            docker_exec_failed = True
            completed = subprocess.CompletedProcess(
                args=list(argv),
                returncode=125,
                stdout=b"",
                stderr=b"DUAL_HOST_DOCKER_EXEC_FAILED",
            )
        finished_at = _utc_now()
        if completed.returncode == 124 and b"DUAL_HOST_OUTER_TIMEOUT" in (completed.stderr or b""):
            timed_out = True
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8", errors="replace")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8", errors="replace")
        try:
            delta = self.collect_attempt_mcp_delta(
                prior_cursor, expected_episode_id=str(lease["episode_id"])
            )
        except DualHostError as exc:
            delta = {
                "events": [],
                "mcp_event_hashes": [],
                "productive_ops": [],
                "status": exc.reason_code,
            }
        try:
            tool_delta = native.collect_tool_sidecar_evidence_delta(
                self.paths["tool_events"],
                prior_tool_cursor,
                expected_episode_id=str(lease["episode_id"]),
            )
            trusted_hashes = list(tool_delta.get("trusted_event_hashes") or [])
        except native.NativeSessionError as exc:
            tool_delta = {"trusted_event_hashes": [], "status": exc.reason_code}
            trusted_hashes = []
            delta = {
                **delta,
                "productive_ops": [],
                "status": str(exc.reason_code),
                "evidence_reject": str(exc.reason_code),
            }
        lab_manifest = self._scan_lab_artifact_manifest()
        # Fail closed: productive MCP events must match tool-executor sealed evidence + lab FS.
        try:
            native.require_productive_lab_delta(
                delta,
                trusted_event_hashes=trusted_hashes,
                require_trusted_tool_chain=True,
            )
            native.require_lab_effect_binding(
                delta=delta,
                lab_artifact_manifest=lab_manifest,
                prior_lab_artifact_manifest=prior_lab_manifest,
            )
        except native.NativeSessionError as exc:
            # Record failed productivity gate into attempt failure path below via empty ops.
            delta = {
                **delta,
                "productive_ops": [],
                "status": str(getattr(exc, "reason_code", None) or "PRODUCTIVE_EVIDENCE_REJECTED"),
                "evidence_reject": str(getattr(exc, "reason_code", None) or exc),
                "trusted_tool_event_count": len(trusted_hashes),
                "tool_sidecar_status": tool_delta.get("status"),
            }
        mcp_hashes = list(delta.get("mcp_event_hashes") or [])
        productive_ops = list(delta.get("productive_ops") or [])
        attempt_id = f"att_{uuid.uuid4().hex}"
        prior_success = None
        success_ptr = self.paths["output"] / "attempts" / "last_successful.json"
        if success_ptr.is_file():
            try:
                prior_success = json.loads(success_ptr.read_text(encoding="utf-8")).get(
                    "attempt_hash"
                )
            except (OSError, json.JSONDecodeError):
                prior_success = None
        web_trace = None
        try:
            parsed = native.parse_provider_machine_output(stdout, stderr)
            web_trace = native.extract_web_use_trace(parsed)
        except native.NativeSessionError:
            web_trace = None
        attempt = native.build_live_attempt_record(
            episode_id=str(lease["episode_id"]),
            host_session_id=str(lease["session_id"]),
            provider_session_uuid=grok_session,
            attempt_id=attempt_id,
            argv=argv,
            stdout=stdout,
            stderr=stderr,
            exit_code=int(completed.returncode),
            model=native.DEFAULT_LIVE_MODEL,
            max_turns=turns,
            timeout_seconds=timeout,
            started_at=started_at,
            finished_at=finished_at,
            transport_container_id=str(lease["transport_container_id"]),
            tool_container_id=str(lease["tool_container_id"]),
            transport_image_id=str(lease["transport_image_id"]),
            tool_image_id=str(lease["tool_image_id"]),
            pair_receipt_sha256=str(ready["pair_receipt_sha256"]),
            namespace_receipt_sha256=namespace_receipt_sha256,
            release_id=release_id,
            release_identity_sha256=release_identity_sha256,
            cas_head_sha256=cas_head_sha256,
            mcp_event_hashes=mcp_hashes,
            lab_artifact_manifest=lab_manifest,
            prior_attempt_hash=prior_success,
            resume=False,
            live_executed=True,
            driver="dual_container_host_docker_exec",
            synthetic=False,
            timed_out=timed_out,
            docker_exec_failed=docker_exec_failed,
            research_profile=research_profile,
            productive_lab_ops=productive_ops,
            mcp_delta_status=str(delta.get("status") or ""),
            web_use_trace=web_trace,
            require_productive_lab_op=True,
        )
        persisted = native.persist_live_attempt(self.paths["output"], attempt)
        # Persist provider session UUID from successful attempt only.
        if persisted.get("status") == native.STATUS_LIVE_ATTEMPT_RECORDED:
            bound = str(persisted.get("provider_session_uuid") or grok_session)
            inventory = dict(inventory)
            inventory["grok_session_id"] = bound
            inventory["last_live_attempt_hash"] = persisted.get("attempt_hash")
            inventory["last_live_attempt_cas"] = persisted.get("attempt_cas_digest")
            inventory["updated_at"] = _utc_now()
            self._save_session_inventory(inventory)
        self._append_journal(
            {
                "verb": "attach_run_live",
                "at": finished_at,
                "status": persisted.get("status"),
                "attempt_cas_digest": persisted.get("attempt_cas_digest"),
                "attempt_hash": persisted.get("attempt_hash"),
                "exit_code": int(completed.returncode),
            }
        )
        return {
            "status": persisted.get("status"),
            "live_executed": True,
            "attempt_cas_digest": persisted.get("attempt_cas_digest"),
            "attempt_hash": persisted.get("attempt_hash"),
            "provider_session_uuid": persisted.get("provider_session_uuid"),
            "exit_code": int(completed.returncode),
            "argv_digest": attempt.get("argv_digest"),
            "failure_reasons": attempt.get("failure_reasons") or [],
            "pair_receipt_sha256": ready["pair_receipt_sha256"],
            "mcp_event_count": len(mcp_hashes),
            "productive_lab_ops": productive_ops,
            "research_profile": research_profile,
            "mcp_delta_status": delta.get("status"),
            "completion_claim_allowed": False,
            "science_restored": False,
            "owner_adopted": False,
            "parent_complete": False,
        }

    def resume_live(
        self,
        *,
        expected_provider_session_uuid: str,
        expected_host_session_id: str | None = None,
        expected_episode_id: str | None = None,
        expected_cas_head_sha256: str | None = None,
        prior_attempt_hash: str | None = None,
        prompt: str | None = None,
        max_turns: int | None = None,
        timeout_seconds: float | None = None,
        namespace_receipt_sha256: str | None = None,
        release_id: str | None = None,
        release_identity_sha256: str | None = None,
        plan_only: bool = False,
    ) -> dict[str, Any]:
        """Owner one-shot resume: bind exact provider session UUID and docker-exec --resume."""
        native = self._load_native_session()
        if not native.is_uuid(expected_provider_session_uuid):
            raise DualHostError(
                "DUAL_HOST_PROVIDER_SESSION_NOT_UUID", expected_provider_session_uuid
            )
        # Ensure pair is running with exact host session binding first.
        if expected_host_session_id:
            pair = self.resume_pair(expected_session_id=expected_host_session_id)
        else:
            lease0 = self.load_lease()
            if lease0 is None:
                raise DualHostError("DUAL_HOST_LEASE_MISSING", "resume_live")
            pair = self.resume_pair(expected_session_id=str(lease0["session_id"]))
        ready = self.require_live_pair_ready(
            expected_episode_id=expected_episode_id,
            expected_host_session_id=expected_host_session_id,
            expected_provider_session_uuid=expected_provider_session_uuid,
            allow_synthetic=False,
        )
        lease = ready["lease"]
        inventory = ready["session_inventory"]
        # Prior successful attempt binding (when provided).
        if prior_attempt_hash:
            success_ptr = self.paths["output"] / "attempts" / "last_successful.json"
            if not success_ptr.is_file():
                raise DualHostError("DUAL_HOST_PRIOR_ATTEMPT_MISSING", prior_attempt_hash)
            prior = json.loads(success_ptr.read_text(encoding="utf-8"))
            if prior.get("attempt_hash") != prior_attempt_hash:
                raise DualHostError(
                    "DUAL_HOST_PRIOR_ATTEMPT_MISMATCH",
                    f"last={prior.get('attempt_hash')} expected={prior_attempt_hash}",
                )
            if (
                str(prior.get("provider_session_uuid") or "").lower()
                != str(expected_provider_session_uuid).lower()
            ):
                raise DualHostError("DUAL_HOST_PROVIDER_SESSION_MISMATCH", "prior attempt")
        research_profile = self.sealed_research_profile()
        inv_profile = (
            str((inventory or {}).get("research_profile") or research_profile).strip().upper()
        )
        if inv_profile not in {research_profile, "GENUINE_SCIENTIST_EPISODE", "GENUINE"}:
            if inv_profile != research_profile:
                raise DualHostError("DUAL_HOST_PROFILE_DRIFT", inv_profile)
        turns = native.clamp_live_max_turns(max_turns)
        timeout = native.clamp_outer_timeout(timeout_seconds)
        argv = self.build_grok_session_argv(
            resume=True,
            session_id=expected_provider_session_uuid,
            max_turns=turns,
            prompt=prompt,
            agent_profile=CANONICAL_AGENT_PROFILE,
            research_profile=research_profile,
        )
        if plan_only:
            return {
                "status": native.STATUS_PLANNED,
                "planned_grok_argv": argv,
                "provider_session_uuid": expected_provider_session_uuid,
                "exact_session_bound": True,
                "pair_resume": pair,
                "research_profile": research_profile,
                "live_executed": False,
                "completion_claim_allowed": False,
                "science_restored": False,
                "owner_adopted": False,
                "parent_complete": False,
            }
        prior_cursor = self.capture_mcp_event_cursor()
        prior_tool_cursor = native.capture_tool_sidecar_cursor(self.paths["tool_events"])
        prior_lab_manifest = self._scan_lab_artifact_manifest()
        started_at = _utc_now()
        docker_exec_failed = False
        timed_out = False
        try:
            completed = self.exec_transport_grok(
                argv,
                timeout_seconds=timeout,
                env={
                    "GROK_HOME": CANONICAL_GROK_HOME,
                    "XINAO_MCP_BINDING": "1",
                    "XINAO_MCP_SERVER": "episode_lab",
                    "XINAO_MCP_TOOLS": native.tools_allowlist_csv(research_profile),
                    "XINAO_MCP_EVENT_LOG": CANONICAL_MCP_EVENTS,
                    "XINAO_MCP_EVIDENCE_PATH": CANONICAL_MCP_EVENTS,
                    "XINAO_RESEARCH_PROFILE": research_profile,
                },
            )
        except DualHostError:
            docker_exec_failed = True
            completed = subprocess.CompletedProcess(
                args=list(argv),
                returncode=125,
                stdout=b"",
                stderr=b"DUAL_HOST_DOCKER_EXEC_FAILED",
            )
        finished_at = _utc_now()
        if completed.returncode == 124 and b"DUAL_HOST_OUTER_TIMEOUT" in (completed.stderr or b""):
            timed_out = True
        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        if isinstance(stdout, str):
            stdout = stdout.encode("utf-8", errors="replace")
        if isinstance(stderr, str):
            stderr = stderr.encode("utf-8", errors="replace")
        try:
            delta = self.collect_attempt_mcp_delta(
                prior_cursor, expected_episode_id=str(lease["episode_id"])
            )
        except DualHostError as exc:
            delta = {
                "events": [],
                "mcp_event_hashes": [],
                "productive_ops": [],
                "status": exc.reason_code,
            }
        try:
            tool_delta = native.collect_tool_sidecar_evidence_delta(
                self.paths["tool_events"],
                prior_tool_cursor,
                expected_episode_id=str(lease["episode_id"]),
            )
            trusted_hashes = list(tool_delta.get("trusted_event_hashes") or [])
        except native.NativeSessionError as exc:
            tool_delta = {"trusted_event_hashes": [], "status": exc.reason_code}
            trusted_hashes = []
            delta = {
                **delta,
                "productive_ops": [],
                "status": str(exc.reason_code),
                "evidence_reject": str(exc.reason_code),
            }
        lab_manifest = self._scan_lab_artifact_manifest()
        try:
            native.require_productive_lab_delta(
                delta,
                trusted_event_hashes=trusted_hashes,
                require_trusted_tool_chain=True,
            )
            native.require_lab_effect_binding(
                delta=delta,
                lab_artifact_manifest=lab_manifest,
                prior_lab_artifact_manifest=prior_lab_manifest,
            )
        except native.NativeSessionError as exc:
            delta = {
                **delta,
                "productive_ops": [],
                "status": str(getattr(exc, "reason_code", None) or "PRODUCTIVE_EVIDENCE_REJECTED"),
                "evidence_reject": str(getattr(exc, "reason_code", None) or exc),
                "trusted_tool_event_count": len(trusted_hashes),
                "tool_sidecar_status": tool_delta.get("status"),
            }
        mcp_hashes = list(delta.get("mcp_event_hashes") or [])
        productive_ops = list(delta.get("productive_ops") or [])
        attempt_id = f"att_{uuid.uuid4().hex}"
        web_trace = None
        try:
            parsed = native.parse_provider_machine_output(stdout, stderr)
            web_trace = native.extract_web_use_trace(parsed)
        except native.NativeSessionError:
            web_trace = None
        attempt = native.build_live_attempt_record(
            episode_id=str(lease["episode_id"]),
            host_session_id=str(lease["session_id"]),
            provider_session_uuid=expected_provider_session_uuid,
            attempt_id=attempt_id,
            argv=argv,
            stdout=stdout,
            stderr=stderr,
            exit_code=int(completed.returncode),
            model=native.DEFAULT_LIVE_MODEL,
            max_turns=turns,
            timeout_seconds=timeout,
            started_at=started_at,
            finished_at=finished_at,
            transport_container_id=str(lease["transport_container_id"]),
            tool_container_id=str(lease["tool_container_id"]),
            transport_image_id=str(lease["transport_image_id"]),
            tool_image_id=str(lease["tool_image_id"]),
            pair_receipt_sha256=str(ready["pair_receipt_sha256"]),
            namespace_receipt_sha256=namespace_receipt_sha256,
            release_id=release_id,
            release_identity_sha256=release_identity_sha256,
            cas_head_sha256=expected_cas_head_sha256,
            mcp_event_hashes=mcp_hashes,
            lab_artifact_manifest=lab_manifest,
            prior_attempt_hash=prior_attempt_hash,
            resume=True,
            live_executed=True,
            driver="dual_container_host_docker_exec",
            synthetic=False,
            timed_out=timed_out,
            docker_exec_failed=docker_exec_failed,
            research_profile=research_profile,
            productive_lab_ops=productive_ops,
            mcp_delta_status=str(delta.get("status") or ""),
            web_use_trace=web_trace,
            require_productive_lab_op=True,
        )
        persisted = native.persist_live_attempt(self.paths["output"], attempt)
        # Failed resume must not overwrite successful provider session binding.
        if persisted.get("status") == native.STATUS_LIVE_ATTEMPT_RECORDED:
            inventory = dict(inventory)
            inventory["grok_session_id"] = expected_provider_session_uuid
            inventory["last_live_attempt_hash"] = persisted.get("attempt_hash")
            inventory["last_live_attempt_cas"] = persisted.get("attempt_cas_digest")
            inventory["updated_at"] = _utc_now()
            self._save_session_inventory(inventory)
        self._append_journal(
            {
                "verb": "resume_live",
                "at": finished_at,
                "status": persisted.get("status"),
                "attempt_cas_digest": persisted.get("attempt_cas_digest"),
                "provider_session_uuid": expected_provider_session_uuid,
                "exit_code": int(completed.returncode),
            }
        )
        return {
            "status": persisted.get("status"),
            "live_executed": True,
            "exact_session_bound": True,
            "attempt_cas_digest": persisted.get("attempt_cas_digest"),
            "attempt_hash": persisted.get("attempt_hash"),
            "provider_session_uuid": expected_provider_session_uuid,
            "exit_code": int(completed.returncode),
            "argv_digest": attempt.get("argv_digest"),
            "failure_reasons": attempt.get("failure_reasons") or [],
            "pair_receipt_sha256": ready["pair_receipt_sha256"],
            "mcp_event_count": len(mcp_hashes),
            "productive_lab_ops": productive_ops,
            "research_profile": research_profile,
            "mcp_delta_status": delta.get("status"),
            "completion_claim_allowed": False,
            "science_restored": False,
            "owner_adopted": False,
            "parent_complete": False,
        }

    def export_candidate_evidence(
        self,
        *,
        attempt_cas_digest: str,
        episode_id: str,
        cas_head_sha256: str,
        expected_provider_session_uuid: str | None = None,
        namespace_receipt_sha256: str | None = None,
        release_id: str | None = None,
        release_identity_sha256: str | None = None,
        prompt_material_cutoff: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Export candidate-only evidence bundle from recorded live attempt CAS."""
        native = self._load_native_session()
        receipt = self.load_pair_receipt()
        lease = self.load_lease()
        pair_sha = None
        transport_image = None
        tool_image = None
        if receipt is not None:
            body = {k: v for k, v in receipt.items() if k != "pair_receipt_sha256"}
            pair_sha = _sha256_bytes(_canonical_bytes(body))
            transport_image = receipt.get("transport_image_id")
            tool_image = receipt.get("tool_image_id")
        if lease is not None:
            if episode_id and lease.get("episode_id") != episode_id:
                raise DualHostError("DUAL_HOST_FOREIGN_EPISODE", str(lease.get("episode_id")))
            transport_image = transport_image or lease.get("transport_image_id")
            tool_image = tool_image or lease.get("tool_image_id")
        return native.export_candidate_evidence_bundle(
            episode_output_root=self.paths["output"],
            attempt_cas_digest=attempt_cas_digest,
            episode_id=episode_id,
            cas_head_sha256=cas_head_sha256,
            expected_provider_session_uuid=expected_provider_session_uuid,
            expected_pair_receipt_sha256=pair_sha,
            expected_namespace_receipt_sha256=namespace_receipt_sha256,
            expected_transport_image_id=transport_image,
            expected_tool_image_id=tool_image,
            package_release_id=release_id,
            package_release_identity_sha256=release_identity_sha256,
            prompt_material_cutoff=prompt_material_cutoff,
            lab_root=self.paths["lab"],
        )

    def cancel_pair(self) -> dict[str, Any]:
        """Idempotent stop/rm of only lease-owned containers/volumes."""
        lease = self.load_lease()
        if lease is None:
            return {"status": "CANCEL_NO_LEASE", "completion_claim_allowed": False}
        if lease.get("phase") in {"cancelled", "retired"}:
            return {
                "status": "CANCEL_IDEMPOTENT",
                "lease": lease,
                "completion_claim_allowed": False,
            }
        errors: list[str] = []
        for cid in (lease.get("transport_container_id"), lease.get("tool_container_id")):
            if not cid:
                continue
            if self.config.synthetic:
                continue
            stop = self.runner([self.config.docker, "rm", "-f", str(cid)])
            if stop.returncode != 0:
                # Already gone is OK.
                err = (stop.stderr or "").lower()
                if "no such container" not in err and "not found" not in err:
                    errors.append(f"rm:{cid}:{stop.stderr}")
        volume = lease.get("ipc_volume")
        if volume and not self.config.synthetic:
            vol = self.runner([self.config.docker, "volume", "rm", "-f", str(volume)])
            if vol.returncode != 0:
                err = (vol.stderr or "").lower()
                if "no such volume" not in err and "not found" not in err:
                    errors.append(f"volume:{volume}:{vol.stderr}")
        lease["phase"] = "cancelled"
        lease["updated_at"] = _utc_now()
        lease["cancel_errors"] = errors
        self._save_lease(lease)
        self._append_journal(
            {
                "verb": "cancel_pair",
                "at": _utc_now(),
                "phase": "cancelled",
                "errors": errors,
                "tool_container_id": lease.get("tool_container_id"),
                "transport_container_id": lease.get("transport_container_id"),
                "ipc_volume": volume,
            }
        )
        return {
            "status": "CANCELLED" if not errors else "CANCELLED_WITH_ERRORS",
            "lease": lease,
            "errors": errors,
            "completion_claim_allowed": False,
        }

    def retire_pair(self) -> dict[str, Any]:
        """Full retire: cancel containers/volumes and mark retired (idempotent)."""
        cancelled = self.cancel_pair()
        lease = self.load_lease()
        if lease is None:
            return {
                "status": "RETIRE_NO_LEASE",
                "cancel": cancelled,
                "completion_claim_allowed": False,
            }
        lease["phase"] = "retired"
        lease["updated_at"] = _utc_now()
        self._save_lease(lease)
        self._append_journal({"verb": "retire_pair", "at": _utc_now(), "phase": "retired"})
        return {
            "status": "RETIRED",
            "lease": lease,
            "cancel": cancelled,
            "completion_claim_allowed": False,
        }


def _utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _mount_cli_fields(value: str) -> dict[str, list[str]]:
    """Parse the canonical key=value fields emitted by docker_create_argv."""
    fields: dict[str, list[str]] = {}
    for token in str(value).split(","):
        if "=" not in token:
            continue
        key, item = token.split("=", 1)
        fields.setdefault(key.strip().lower(), []).append(item)
    return fields


def _replace_ipc_bind_with_volume(argv: list[str], volume: str) -> list[str]:
    """Replace exactly one generated bind whose exact target is ``/ipc``."""
    out: list[str] = []
    i = 0
    replaced = 0
    while i < len(argv):
        if argv[i] == "--mount" and i + 1 < len(argv):
            fields = _mount_cli_fields(argv[i + 1])
            kinds = fields.get("type", [])
            targets = [
                *fields.get("dst", []),
                *fields.get("destination", []),
                *fields.get("target", []),
            ]
            if kinds == ["bind"] and targets == ["/ipc"]:
                # Deliberately retain Docker's default volume copy-up. The tool
                # image owns /ipc as 65532:65532; copy-up initializes a fresh
                # named volume for the non-root tool before transport starts.
                out.extend(["--mount", f"type=volume,src={volume},dst=/ipc"])
                replaced += 1
                i += 2
                continue
        out.append(argv[i])
        i += 1
    if replaced != 1:
        raise DualHostError(
            "DUAL_HOST_IPC_MOUNT_REWRITE_FAILED",
            f"expected one exact bind target /ipc, observed={replaced}",
        )
    return out


def _exact_ipc_volume_mount(
    inspect_doc: Mapping[str, Any], *, role: str, expected_volume: str
) -> dict[str, str]:
    mounts = [
        mount
        for mount in (inspect_doc.get("Mounts") or [])
        if isinstance(mount, Mapping)
        and str(mount.get("Destination") or mount.get("Target") or "") == "/ipc"
    ]
    if len(mounts) != 1:
        raise DualHostError(
            "DUAL_HOST_IPC_VOLUME_MISMATCH", f"{role}:ipc_mount_count={len(mounts)}"
        )
    mount = mounts[0]
    kind = str(mount.get("Type") or "").lower()
    name = str(mount.get("Name") or "")
    source = str(mount.get("Source") or "")
    if kind != "volume" or name != expected_volume or not source or mount.get("RW") is not True:
        raise DualHostError(
            "DUAL_HOST_IPC_VOLUME_MISMATCH",
            f"{role}:type={kind!r}:name={name!r}:source={source!r}:rw={mount.get('RW')!r}",
        )
    return {"name": name, "source": source}


def _require_exact_ipc_volume_mounts(
    *,
    tool_inspect: Mapping[str, Any],
    transport_inspect: Mapping[str, Any],
    expected_volume: str,
) -> str:
    tool = _exact_ipc_volume_mount(tool_inspect, role="tool", expected_volume=expected_volume)
    transport = _exact_ipc_volume_mount(
        transport_inspect, role="transport", expected_volume=expected_volume
    )
    if tool != transport:
        raise DualHostError(
            "DUAL_HOST_IPC_VOLUME_MISMATCH",
            f"tool={tool!r}:transport={transport!r}",
        )
    return tool["source"]


def _inspect_summary(doc: dict[str, Any]) -> dict[str, Any]:
    cfg = doc.get("Config") or {}
    hc = doc.get("HostConfig") or {}
    return {
        "Id": doc.get("Id"),
        "Image": doc.get("Image") or cfg.get("Image"),
        "User": cfg.get("User"),
        "NetworkMode": hc.get("NetworkMode"),
        "ReadonlyRootfs": hc.get("ReadonlyRootfs"),
        "CapDrop": hc.get("CapDrop"),
        "SecurityOpt": hc.get("SecurityOpt"),
        "Entrypoint": cfg.get("Entrypoint"),
        "Mounts": [
            {
                "Destination": m.get("Destination") or m.get("Target"),
                "Source": m.get("Source"),
                "Type": m.get("Type"),
            }
            for m in (doc.get("Mounts") or [])
            if isinstance(m, dict)
        ],
    }


def _synthetic_tool_inspect(
    lease: Mapping[str, Any], *, seccomp_inspect_opt: str
) -> dict[str, Any]:
    return {
        "Id": lease.get("tool_container_id"),
        "Image": lease.get("tool_image_id"),
        "Config": {
            "User": "65532:65532",
            "Image": lease.get("tool_image_id"),
            "Entrypoint": [
                "python",
                "-I",
                "/opt/xinao-tool-executor/tool_executor.py",
                "--lab-root",
                "/episode-lab",
                "--socket",
                "/ipc/tool.sock",
            ],
            "Env": [
                "HOME=/tmp",
                "TMPDIR=/tmp",
                "XINAO_TOOL_EXEC_BWRAP=require",
                "XINAO_IPC_PEER_REQUIRE=1",
                f"XINAO_IPC_PEER_UIDS={lease.get('ipc_peer_uids', 0)}",
                "XINAO_REPLAY_STATE_DIR=/ipc/.xinao-replay",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true", seccomp_inspect_opt],
        },
        "Mounts": [
            {"Destination": "/episode-lab", "Source": "/host/lab", "Type": "bind"},
            {"Destination": "/ipc", "Source": "/host/ipc", "Type": "bind"},
        ],
    }


def _synthetic_transport_inspect(lease: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "Id": lease.get("transport_container_id"),
        "Image": lease.get("transport_image_id"),
        "Config": {
            "User": "0:0",
            "Image": lease.get("transport_image_id"),
            "Entrypoint": [
                "python",
                "-I",
                "/opt/xinao-researcher/episode_entrypoint.py",
                "--hold",
            ],
            "Env": [
                "XINAO_DUAL_CONTAINER=1",
                "XINAO_GENERIC_FILE_SHELL_TOOLS=0",
                "XINAO_TOOL_IPC_SOCKET=/ipc/tool.sock",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": [
            {
                "Destination": "/grok-home/auth.json",
                "Source": "/host/auth/auth.json",
                "Type": "bind",
            },
            {"Destination": "/input", "Source": "/host/input", "Type": "bind"},
            {"Destination": "/output", "Source": "/host/output", "Type": "bind"},
            {"Destination": "/ipc", "Source": "/host/ipc", "Type": "bind"},
            {
                "Destination": "/grok-home/sessions",
                "Source": "/host/sessions",
                "Type": "bind",
            },
            {"Destination": "/episode-lab", "Source": "/host/lab", "Type": "bind"},
        ],
    }


def research_episode_dual_container_driver(
    *,
    verb: str,
    episode_id: str,
    session_id: str,
    generation: int,
    lab_root: Path,
    profile_status: str,
    host: DualContainerHost | None = None,
) -> dict[str, Any]:
    """Container driver callback for ResearchEpisode when dual-host is enabled."""
    if host is None:
        # Deferred identity only — full orchestration is verb-driven by host APIs.
        return {
            "schema_version": "xinao.research_episode_container_contract.v1",
            "driver": "dual_container_host",
            "verb": verb,
            "episode_id": episode_id,
            "session_id": session_id,
            "generation": generation,
            "container_id": None,
            "tool_container_id": None,
            "transport_container_id": None,
            "image_id": None,
            "profile_status": profile_status,
            "writable_mounts": ["episode_lab", "outbox_candidates", "ipc"],
            "forbidden_mounts": [
                "shadow_ledger",
                "freeze_store",
                "outcome_store",
                "settlement",
                "auth_secrets_on_tool",
                "owner_adoption",
                "docker_socket",
            ],
            "network_mode": "tool=none;transport=configurable",
            "restart_policy": "no",
            "daemon": False,
            "goal": False,
            "temporal_leg_b": False,
            "generic_file_shell_tools": False,
            "mcp_tools_via_sidecar": True,
            "lab_root": str(lab_root),
            "completion_claim_allowed": False,
        }
    lease = host.load_lease()
    if verb == "start" and lease is None:
        created = host.create_pair(episode_id=episode_id, session_id=session_id)
        host.start_pair()
        lease = host.load_lease()
        return {
            "schema_version": "xinao.research_episode_container_contract.v1",
            "driver": "dual_container_host",
            "verb": verb,
            "episode_id": episode_id,
            "session_id": session_id,
            "generation": generation,
            "container_id": (lease or {}).get("transport_container_id"),
            "tool_container_id": (lease or {}).get("tool_container_id"),
            "transport_container_id": (lease or {}).get("transport_container_id"),
            "tool_image_id": (lease or {}).get("tool_image_id"),
            "transport_image_id": (lease or {}).get("transport_image_id"),
            "image_id": (lease or {}).get("transport_image_id"),
            "profile_status": profile_status,
            "writable_mounts": ["episode_lab", "outbox_candidates", "ipc"],
            "forbidden_mounts": [
                "shadow_ledger",
                "freeze_store",
                "outcome_store",
                "settlement",
                "auth_secrets_on_tool",
                "owner_adoption",
                "docker_socket",
            ],
            "network_mode": "tool=none;transport=configurable",
            "restart_policy": "no",
            "daemon": False,
            "goal": False,
            "temporal_leg_b": False,
            "generic_file_shell_tools": False,
            "mcp_tools_via_sidecar": True,
            "pair_create": {
                "status": created.get("status"),
                "phase": (lease or {}).get("phase"),
            },
            "completion_claim_allowed": False,
        }
    if verb == "resume" and lease is not None:
        host.resume_pair(expected_session_id=session_id)
        lease = host.load_lease()
    if verb == "cancel" and lease is not None:
        host.cancel_pair()
        lease = host.load_lease()
    if verb == "checkpoint" and lease is not None:
        host.checkpoint_bind(progress_note=f"generation={generation}")
        lease = host.load_lease()
    if verb == "absorb" and lease is not None:
        # Absorb does not auto-retire; Owner may retire after review.
        pass
    lease = lease or host.load_lease() or {}
    return {
        "schema_version": "xinao.research_episode_container_contract.v1",
        "driver": "dual_container_host",
        "verb": verb,
        "episode_id": episode_id,
        "session_id": session_id,
        "generation": generation,
        "container_id": lease.get("transport_container_id"),
        "tool_container_id": lease.get("tool_container_id"),
        "transport_container_id": lease.get("transport_container_id"),
        "tool_image_id": lease.get("tool_image_id"),
        "transport_image_id": lease.get("transport_image_id"),
        "image_id": lease.get("transport_image_id"),
        "profile_status": profile_status,
        "phase": lease.get("phase"),
        "writable_mounts": ["episode_lab", "outbox_candidates", "ipc"],
        "forbidden_mounts": [
            "shadow_ledger",
            "freeze_store",
            "outcome_store",
            "settlement",
            "auth_secrets_on_tool",
            "owner_adoption",
            "docker_socket",
        ],
        "network_mode": "tool=none;transport=configurable",
        "restart_policy": "no",
        "daemon": False,
        "goal": False,
        "temporal_leg_b": False,
        "generic_file_shell_tools": False,
        "mcp_tools_via_sidecar": True,
        "completion_claim_allowed": False,
    }


def dual_host_enabled() -> bool:
    """Enable real dual-container host driver when explicitly requested."""
    return os.environ.get("XINAO_DUAL_CONTAINER_HOST", "").strip() in {"1", "true", "TRUE", "yes"}


def build_host_from_env(episode_root: Path) -> DualContainerHost | None:
    if not dual_host_enabled():
        return None
    transport = os.environ.get("XINAO_TRANSPORT_IMAGE", "").strip()
    tool = os.environ.get("XINAO_TOOL_EXECUTOR_IMAGE", "").strip()
    auth = os.environ.get("XINAO_AUTH_HOST_PATH", "").strip()
    if not transport or not tool or not auth:
        raise DualHostError(
            "DUAL_HOST_CONFIG_INCOMPLETE",
            "XINAO_TRANSPORT_IMAGE, XINAO_TOOL_EXECUTOR_IMAGE, XINAO_AUTH_HOST_PATH required",
        )
    synthetic = os.environ.get("XINAO_DUAL_CONTAINER_SYNTHETIC", "").strip() in {
        "1",
        "true",
        "TRUE",
    }
    network = os.environ.get("XINAO_TRANSPORT_NETWORK", "").strip()
    if not network:
        network = "none" if synthetic else DEFAULT_TRANSPORT_NETWORK
    return DualContainerHost(
        DualHostConfig(
            transport_image=transport,
            tool_image=tool,
            auth_host_path=Path(auth),
            episode_root=episode_root,
            network=network,
            material_host_path=Path(os.environ["XINAO_MATERIAL_HOST_PATH"])
            if os.environ.get("XINAO_MATERIAL_HOST_PATH")
            else None,
            synthetic=synthetic,
        )
    )
