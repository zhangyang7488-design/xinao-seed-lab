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
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

DOCKER_PKG = Path(__file__).resolve().parents[3] / "docker" / "xinao-researcher"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
PAIR_LEASE_SCHEMA = "xinao.dual_container_pair_lease.v1"
SESSION_INVENTORY_SCHEMA = "xinao.dual_container_session_inventory.v1"
CHECKPOINT_BIND_SCHEMA = "xinao.dual_container_checkpoint_bind.v1"
PAIR_RECEIPT_SCHEMA = "xinao.dual_container_pair_receipt.v1"
LEASE_FILENAME = "dual_container_pair_lease.json"
SESSION_INVENTORY_FILENAME = "session_inventory.json"
PAIR_RECEIPT_FILENAME = "dual_container_pair_receipt.json"
MCP_EVENTS_FILENAME = "mcp_events.jsonl"
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
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
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

    path = DOCKER_PKG / "docker_create_specs.py"
    name = "xinao_docker_create_specs_host"
    if name in sys.modules:
        return sys.modules[name]
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
    network: str = "none"
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

    def _append_journal(self, entry: Mapping[str, Any]) -> None:
        self.paths["journal"].parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.paths["journal"].open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def _ensure_layout(self) -> None:
        for key in ("lab", "inputs", "output", "sessions", "attempt", "ipc_bind"):
            self.paths[key].mkdir(parents=True, exist_ok=True)

    def _load_mcp_binding(self) -> Any:
        import sys

        path = DOCKER_PKG / "episode_mcp_binding.py"
        name = "xinao_episode_mcp_binding_host"
        if name in sys.modules:
            return sys.modules[name]
        pkg = str(DOCKER_PKG)
        if pkg not in sys.path:
            sys.path.insert(0, pkg)
        if not path.is_file():
            raise DualHostError("DUAL_HOST_MCP_BINDING_MISSING", str(path))
        if not (DOCKER_PKG / "mcp_episode_lab_server.py").is_file():
            raise DualHostError(
                "DUAL_HOST_MCP_SERVER_MISSING",
                str(DOCKER_PKG / "mcp_episode_lab_server.py"),
            )
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise DualHostError("DUAL_HOST_MCP_BINDING_LOAD_FAILED", str(path))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def _materialize_attempt_mcp(self, episode_id: str) -> dict[str, Any]:
        """Materialize attempt-local native Grok MCP (episode_lab only; no fake bridge)."""
        bind_mod = self._load_mcp_binding()
        grok_home = self.paths["attempt"] / "grok-home"
        grok_home.mkdir(parents=True, exist_ok=True)
        receipt = bind_mod.materialize_attempt_local_binding(
            root=self.paths["attempt"],
            episode_id=episode_id,
            socket_path="/ipc/tool.sock",
            server_path="/opt/xinao-researcher/mcp_episode_lab_server.py",
            pythonpath="/opt/xinao-researcher",
            grok_home=grok_home,
        )
        config_path = Path(receipt["config_toml"])
        profile_path = Path(receipt["agent_profile"])
        if "mcp_servers.episode_lab" not in config_path.read_text(encoding="utf-8"):
            raise DualHostError("DUAL_HOST_MCP_CONFIG_INVALID", "episode_lab missing")
        if "mcp_episode_lab_server.py" not in config_path.read_text(encoding="utf-8"):
            raise DualHostError("DUAL_HOST_MCP_CONFIG_INVALID", "native server missing")
        # Keep a lab-local mirror for hosts that still scan project-scoped .grok.
        lab_grok = self.paths["lab"] / ".grok"
        lab_grok.mkdir(parents=True, exist_ok=True)
        (lab_grok / "config.toml").write_text(
            config_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        return {
            "mcp_config": config_path,
            "agent_profile": profile_path,
            "grok_home": grok_home,
            "binding_receipt": receipt,
            "binding_receipt_sha256": str(receipt.get("receipt_sha256") or ""),
            "evidence_path": Path(receipt["evidence_path"]),
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
    ) -> dict[str, Any]:
        """Create IPC volume, materialize attempt MCP, create both containers (not start)."""
        if not episode_id or not session_id:
            raise DualHostError("DUAL_HOST_IDENTITY_INVALID", "episode/session required")
        existing = self.load_lease()
        if existing and existing.get("phase") not in {"cancelled", "retired"}:
            raise DualHostError("DUAL_HOST_LEASE_EXISTS", str(self.paths["lease"]))
        self._ensure_layout()
        attempt = self._materialize_attempt_mcp(episode_id)
        names = self.specs.pair_resource_names(episode_id)
        transport_image_id = self.resolve_image_id(self.config.transport_image)
        tool_image_id = self.resolve_image_id(self.config.tool_image)

        # IPC: prefer named volume; also keep bind dir for host-side socket observation.
        ipc_volume = names["ipc_volume"]
        if not self.config.synthetic:
            # Idempotent volume create.
            probe = self.runner([self.config.docker, "volume", "inspect", ipc_volume])
            if probe.returncode != 0:
                self._run(
                    [self.config.docker, "volume", "create", ipc_volume],
                    reason="DUAL_HOST_VOLUME_CREATE_FAILED",
                )
            ipc_mount_source = ipc_volume
            ipc_mount_type = "volume"
        else:
            ipc_mount_source = str(self.paths["ipc_bind"])
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

        bundle = self.specs.dual_container_bundle(
            transport_image=transport_image_id,
            tool_image=tool_image_id,
            auth_host_path=str(self.config.auth_host_path),
            input_host_path=str(self.paths["inputs"]),
            output_host_path=str(self.paths["output"]),
            episode_lab_host_path=str(self.paths["lab"]),
            ipc_host_dir=ipc_for_spec,
            run_id=names["run_id"],
            session_host_path=str(self.paths["sessions"]),
            material_host_path=material_path,
            # Native MCP: image-baked server; attempt-local GROK_HOME config + profile.
            attempt_grok_config_host_path=str(attempt["mcp_config"]),
            attempt_agent_profile_host_path=str(attempt["agent_profile"]),
            episode_id=episode_id,
            use_episode_entrypoint=True,
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
        else:
            # Remove leftovers with exact names only if prior lease retired (best-effort).
            tool_id = self._run(tool_argv, reason="DUAL_HOST_TOOL_CREATE_FAILED").stdout.strip()
            transport_id = self._run(
                transport_argv, reason="DUAL_HOST_TRANSPORT_CREATE_FAILED"
            ).stdout.strip()
            if not tool_id or not transport_id:
                # Partial create: mark fail and attempt retire of what exists.
                self._append_journal(
                    {
                        "verb": "create_pair_partial_fail",
                        "tool_id": tool_id,
                        "transport_id": transport_id,
                    }
                )
                raise DualHostError("DUAL_HOST_CREATE_INCOMPLETE", f"{tool_id}/{transport_id}")

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
            "completion_claim_allowed": False,
        }
        self._save_session_inventory(inventory)
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
            "socket_basename": "tool.sock",
            "mcp_server": "episode_lab",
            "mcp_config_sha256": _sha256_bytes(attempt["mcp_config"].read_bytes()),
            "mcp_binding_receipt_sha256": attempt.get("binding_receipt_sha256"),
            "generic_file_shell_tools": False,
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
            tool_inspect = _synthetic_tool_inspect(lease)
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
        if lease.get("phase") in {"cancelled", "retired"}:
            raise DualHostError("DUAL_HOST_LEASE_TERMINAL", str(lease.get("phase")))
        if lease.get("phase") in {"running", "transport_started"}:
            return {
                "status": "START_IDEMPOTENT",
                "lease": lease,
                "completion_claim_allowed": False,
            }

        # Validate sealed pair receipt + inspect before any start.
        self.validate_before_start()

        # Phase: tool first.
        try:
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
        if not self.config.synthetic:
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

    def build_grok_session_argv(
        self,
        *,
        resume: bool,
        session_id: str,
        extra: Sequence[str] | None = None,
        tools: str = "search_tool,use_tool",
    ) -> list[str]:
        """Real Grok headless session rules: --session-id / --resume + MCP discovery tools.

        Dual-container genuine path allowlists only search_tool,use_tool (native MCP).
        Canary remains separate with --tools '' on its own entrypoint.
        """
        argv = [
            "/usr/local/bin/grok",
            "--output-format",
            "json",
            "--tools",
            tools,
            "--max-turns",
            "16",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
        ]
        if resume:
            argv.extend(["--resume", session_id])
        else:
            argv.extend(["--session-id", session_id])
        if extra:
            argv.extend(list(extra))
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
        if mark_interrupted_first:
            lease["phase"] = "interrupted"
            lease["updated_at"] = _utc_now()
            self._save_lease(lease)
        grok_session = str(inventory.get("grok_session_id") or expected_session_id)
        resume_argv = self.build_grok_session_argv(resume=True, session_id=grok_session)
        # Ensure containers are running: tool first.
        if lease.get("phase") in {"created", "interrupted", "checkpointed", "tool_started"}:
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
                    self.runner(
                        [self.config.docker, "start", str(lease["transport_container_id"])]
                    )
                lease["phase"] = "running"
                lease["updated_at"] = _utc_now()
                self._save_lease(lease)
        inventory = dict(inventory)
        inventory["resume_mode"] = "resume"
        inventory["updated_at"] = _utc_now()
        inventory["last_resume_argv_markers"] = {
            "resume": grok_session,
            "tools": "",
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
            return {"status": "RETIRE_NO_LEASE", "cancel": cancelled, "completion_claim_allowed": False}
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


def _replace_ipc_bind_with_volume(argv: list[str], volume: str) -> list[str]:
    """Swap bind mount to /ipc for a named volume mount."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--mount" and i + 1 < len(argv) and ",dst=/ipc," in argv[i + 1]:
            out.extend(
                [
                    "--mount",
                    f"type=volume,src={volume},dst=/ipc,volume-nocopy",
                ]
            )
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


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


def _synthetic_tool_inspect(lease: Mapping[str, Any]) -> dict[str, Any]:
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
                "XINAO_IPC_PEER_UIDS=",
                "XINAO_REPLAY_STATE_DIR=/ipc/.xinao-replay",
            ],
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
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
            "User": "",
            "Image": lease.get("transport_image_id"),
            "Entrypoint": [
                "python",
                "-I",
                "/opt/xinao-researcher/episode_entrypoint.py",
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
            {"Destination": "/grok-home/.grok", "Source": "/host/auth", "Type": "bind"},
            {"Destination": "/input", "Source": "/host/input", "Type": "bind"},
            {"Destination": "/output", "Source": "/host/output", "Type": "bind"},
            {"Destination": "/ipc", "Source": "/host/ipc", "Type": "bind"},
            {
                "Destination": "/grok-home/.grok/sessions",
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
    return DualContainerHost(
        DualHostConfig(
            transport_image=transport,
            tool_image=tool,
            auth_host_path=Path(auth),
            episode_root=episode_root,
            network=os.environ.get("XINAO_TRANSPORT_NETWORK", "none"),
            material_host_path=Path(os.environ["XINAO_MATERIAL_HOST_PATH"])
            if os.environ.get("XINAO_MATERIAL_HOST_PATH")
            else None,
            synthetic=synthetic,
        )
    )
