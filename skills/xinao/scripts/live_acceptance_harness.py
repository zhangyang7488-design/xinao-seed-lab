"""Owner-invoked, non-daemon live-acceptance harness for dual-profile researcher.

Codex runs this on the Windows host after candidate integration/build. Worker seats
exercise control flow with fakes only (synthetic docker, fixture pointer, dry-run
lab task). Live model invocation, activation, shadow ledger writes, and resident
supervisors are out of scope for this module.

Axes (independent; any miss/fail leaves genuine_scientist UNAVAILABLE):
  1 pointer_identity
  2 image_identity
  3 egress_seal
  4 canary_identity
  5 candidate_build_lock
  6 instrument_canary_semantics
  7 dual_container_pair
  8 multi_turn_fail_revise_success
  9 interrupt_resume_fresh_process
 10 immutable_export
 11 non_reachability_negatives
 12 capability_gate

completion_claim_allowed is always false. INSTRUMENT_CANARY is not modified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEALED_CANARY_SHA256 = "c9c1a132ac00ebde9b198db6eb12a1be456cbcfb8c66d892856997595e40c47e"
HARNESS_SCHEMA = "xinao.live_acceptance_harness_result.v1"
AXIS_RECEIPT_SCHEMA = "xinao.live_acceptance_axis_receipt.v1"
BUILD_LOCK_SCHEMA = "xinao.candidate_build_lock.v1"
EXPORT_SCHEMA = "xinao.live_acceptance_immutable_export.v1"
CAPABILITY_UNAVAILABLE = "UNAVAILABLE_AWAITING_LIVE_ACCEPTANCE_RECEIPT"
CAPABILITY_PARTIAL = "PARTIAL_AXES_GREEN_ROLE_FITNESS_NOT_CLAIMED"
PROFILE_GENUINE = "genuine_scientist"
PROFILE_CANARY = "INSTRUMENT_CANARY"

# Dual-profile modules that must be present for candidate build lock (tree hash).
RESEARCHER_IMAGE_MODULE_INVENTORY: tuple[str, ...] = (
    "entrypoint.py",
    "episode_entrypoint.py",
    "episode_boundary.py",
    "episode_events.py",
    "ipc_contract.py",
    "transport_broker.py",
    "episode_mcp_binding.py",
    "mcp_episode_lab_server.py",
    "empty-grok-profile/.gitkeep",
    "grok-bwrap-unprivileged-wrapper.sh",
    "episode-tool-shell-wrapper.sh",
)

AXIS_ORDER: tuple[str, ...] = (
    "pointer_identity",
    "image_identity",
    "egress_seal",
    "canary_identity",
    "candidate_build_lock",
    "instrument_canary_semantics",
    "dual_container_pair",
    "multi_turn_fail_revise_success",
    "interrupt_resume_fresh_process",
    "immutable_export",
    "non_reachability_negatives",
    "capability_gate",
)

DockerRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class HarnessError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(detail or reason_code)
        self.reason_code = reason_code
        self.detail = str(detail)[:2000]


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


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(_canonical_bytes(dict(value)))
    os.replace(temporary, path)


def _utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _lf_bytes(payload: bytes) -> bytes:
    return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


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


def _repo_root() -> Path:
    # skills/xinao/scripts/this_file -> repo root
    return Path(__file__).resolve().parents[3]


def _load_module(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HarnessError("HARNESS_MODULE_LOAD_FAILED", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_dual_container_host() -> Any:
    return _load_module(
        "xinao_dual_container_host_harness",
        Path(__file__).resolve().parent / "dual_container_host.py",
    )


def load_docker_create_specs(repo: Path | None = None) -> Any:
    root = repo or _repo_root()
    return _load_module(
        "xinao_docker_create_specs_harness",
        root / "docker" / "xinao-researcher" / "docker_create_specs.py",
    )


@dataclass
class AxisResult:
    name: str
    status: str  # passed | failed | skipped | not_run
    reason_code: str = ""
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AXIS_RECEIPT_SCHEMA,
            "name": self.name,
            "status": self.status,
            "reason_code": self.reason_code,
            "detail": self.detail[:2000],
            "evidence": dict(self.evidence),
            "completion_claim_allowed": False,
        }


@dataclass
class HarnessConfig:
    """Configuration for one Owner harness invocation."""

    work_root: Path
    repo_root: Path | None = None
    # Modes: synthetic (unit/fakes), live (real docker/host; still may dry-run model),
    # plan (emit exact host commands only).
    mode: str = "synthetic"
    transport_image: str = "xinao-researcher:candidate"
    tool_image: str = "xinao-tool-executor:candidate"
    auth_host_path: Path | None = None
    pointer_path: Path | None = None
    release_path: Path | None = None
    build_lock_path: Path | None = None
    egress_seal_path: Path | None = None
    runtime_lock_path: Path | None = None
    docker: str = "docker"
    runner: DockerRunner | None = None
    # When True (default for synthetic), DualContainerHost uses synthetic IDs.
    synthetic_docker: bool = True
    # Live model multi-turn is Owner-only; harness never calls provider from worker.
    invoke_live_model: bool = False
    # Dry-run canary: only static markers + planned argv, no docker run.
    canary_static_only: bool = True
    # Optional pre-bound image IDs (sha256:...) for identity axis.
    expected_transport_image_id: str | None = None
    expected_tool_image_id: str | None = None
    expected_canary_sha256: str = SEALED_CANARY_SHA256


class LiveAcceptanceHarness:
    """Single Owner-invoked acceptance driver (no daemon, no Goal, no Temporal)."""

    def __init__(self, config: HarnessConfig) -> None:
        if config.mode not in {"synthetic", "live", "plan"}:
            raise HarnessError("HARNESS_MODE_INVALID", config.mode)
        self.config = config
        self.repo = Path(config.repo_root or _repo_root())
        self.work_root = Path(config.work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.axes: dict[str, AxisResult] = {
            name: AxisResult(name=name, status="not_run") for name in AXIS_ORDER
        }
        self.journal: list[dict[str, Any]] = []
        self.export_hashes: dict[str, str] = {}
        self.pair_lease: dict[str, Any] | None = None
        self.episode_meta: dict[str, Any] = {}
        self.host_mod = load_dual_container_host()
        self.specs = load_docker_create_specs(self.repo)
        self.runner = config.runner or default_docker_runner
        self._host: Any | None = None

    def _journal(self, verb: str, **payload: Any) -> None:
        entry = {"verb": verb, "at": _utc_now(), **payload}
        self.journal.append(entry)
        journal_path = self.work_root / "harness_journal.jsonl"
        with journal_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def _set_axis(
        self,
        name: str,
        status: str,
        *,
        reason_code: str = "",
        detail: str = "",
        evidence: Mapping[str, Any] | None = None,
    ) -> AxisResult:
        result = AxisResult(
            name=name,
            status=status,
            reason_code=reason_code,
            detail=detail,
            evidence=dict(evidence or {}),
        )
        self.axes[name] = result
        self._journal("axis", name=name, status=status, reason_code=reason_code)
        return result

    def _researcher_pkg(self) -> Path:
        return self.repo / "docker" / "xinao-researcher"

    def _auth_path(self) -> Path:
        if self.config.auth_host_path is not None:
            return Path(self.config.auth_host_path)
        auth = self.work_root / "auth"
        auth.mkdir(parents=True, exist_ok=True)
        auth_file = auth / "auth.json"
        if not auth_file.is_file():
            auth_file.write_text('{"synthetic":true}\n', encoding="utf-8")
        return auth

    def _episode_root(self) -> Path:
        path = self.work_root / "episode"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _make_host(self) -> Any:
        if self._host is not None:
            return self._host
        cfg = self.host_mod.DualHostConfig(
            transport_image=self.config.transport_image,
            tool_image=self.config.tool_image,
            auth_host_path=self._auth_path(),
            episode_root=self._episode_root(),
            docker=self.config.docker,
            runner=self.runner,
            synthetic=bool(self.config.synthetic_docker or self.config.mode == "synthetic"),
        )
        self._host = self.host_mod.DualContainerHost(cfg)
        return self._host

    # --- Axis implementations -------------------------------------------------

    def axis_pointer_identity(self) -> AxisResult:
        """Verify installed current pointer document shape + digest if provided."""
        pointer_path = self.config.pointer_path
        if pointer_path is None:
            # Synthetic mode may materialize a fixture pointer for control flow.
            if self.config.mode == "synthetic":
                pointer_path = self.work_root / "fixtures" / "current_pointer.json"
                if not pointer_path.is_file():
                    pointer_path.parent.mkdir(parents=True, exist_ok=True)
                    fixture = {
                        "schema_version": "xinao.researcher_current_pointer.v2",
                        "generation": 1,
                        "release_id": "researcher-0.0.0-synthetic00000001",
                        "release_manifest_path": "releases/researcher-0.0.0-synthetic00000001/release.json",
                        "release_manifest_sha256": "a" * 64,
                        "skill_bundle_manifest_sha256": "b" * 64,
                        "skill_bundle_tree_sha256": "c" * 64,
                        "capability_version": "1.2.1",
                        "package_version": "1.2.1",
                        "required_bootstrap_protocol": 2,
                        "activation_txn_id": "xra_20260731T000000_synthetic0001",
                        "completion_claim_allowed": False,
                    }
                    _write_json_atomic(pointer_path, fixture)
            else:
                return self._set_axis(
                    "pointer_identity",
                    "failed",
                    reason_code="POINTER_PATH_MISSING",
                    detail="live mode requires --pointer-path to installed current pointer",
                )
        path = Path(pointer_path)
        if not path.is_file():
            return self._set_axis(
                "pointer_identity",
                "failed",
                reason_code="CURRENT_POINTER_ABSENT",
                detail=str(path),
            )
        try:
            raw = path.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._set_axis(
                "pointer_identity",
                "failed",
                reason_code="CURRENT_POINTER_INVALID",
                detail=str(exc),
            )
        if not isinstance(doc, dict):
            return self._set_axis(
                "pointer_identity",
                "failed",
                reason_code="CURRENT_POINTER_SCHEMA_INVALID",
                detail="object required",
            )
        schema = doc.get("schema_version")
        if schema != "xinao.researcher_current_pointer.v2":
            return self._set_axis(
                "pointer_identity",
                "failed",
                reason_code="CURRENT_POINTER_SCHEMA_INVALID",
                detail=str(schema),
            )
        if type(doc.get("generation")) is not int or doc["generation"] < 1:
            return self._set_axis(
                "pointer_identity",
                "failed",
                reason_code="CURRENT_POINTER_GENERATION_INVALID",
                detail=str(doc.get("generation")),
            )
        if doc.get("required_bootstrap_protocol") is not None and doc.get(
            "required_bootstrap_protocol"
        ) not in (2,):
            # Integer 2 only when present (RQ008-style exactness).
            if type(doc.get("required_bootstrap_protocol")) is not int:
                return self._set_axis(
                    "pointer_identity",
                    "failed",
                    reason_code="BOOTSTRAP_PROTOCOL_TYPE_INVALID",
                    detail=str(type(doc.get("required_bootstrap_protocol"))),
                )
        digest = _sha256_bytes(raw)
        self.export_hashes["pointer_sha256"] = digest
        return self._set_axis(
            "pointer_identity",
            "passed",
            evidence={
                "pointer_path": str(path),
                "pointer_sha256": digest,
                "release_id": doc.get("release_id"),
                "generation": doc.get("generation"),
            },
        )

    def axis_image_identity(self) -> AxisResult:
        host = self._make_host()
        try:
            transport_id = host.resolve_image_id(self.config.transport_image)
            tool_id = host.resolve_image_id(self.config.tool_image)
        except Exception as exc:  # noqa: BLE001 — surface host/docker errors as axis fail
            reason = getattr(exc, "reason_code", "IMAGE_RESOLVE_FAILED")
            return self._set_axis(
                "image_identity",
                "failed",
                reason_code=str(reason),
                detail=str(exc),
            )
        if not str(transport_id).startswith("sha256:") or not str(tool_id).startswith("sha256:"):
            return self._set_axis(
                "image_identity",
                "failed",
                reason_code="IMAGE_ID_INVALID",
                detail=f"transport={transport_id} tool={tool_id}",
            )
        if (
            self.config.expected_transport_image_id
            and transport_id != self.config.expected_transport_image_id
        ):
            return self._set_axis(
                "image_identity",
                "failed",
                reason_code="TRANSPORT_IMAGE_MISMATCH",
                detail=f"expected={self.config.expected_transport_image_id} observed={transport_id}",
            )
        if self.config.expected_tool_image_id and tool_id != self.config.expected_tool_image_id:
            return self._set_axis(
                "image_identity",
                "failed",
                reason_code="TOOL_IMAGE_MISMATCH",
                detail=f"expected={self.config.expected_tool_image_id} observed={tool_id}",
            )
        self.export_hashes["transport_image_id"] = transport_id
        self.export_hashes["tool_image_id"] = tool_id
        return self._set_axis(
            "image_identity",
            "passed",
            evidence={
                "transport_image_ref": self.config.transport_image,
                "tool_image_ref": self.config.tool_image,
                "transport_image_id": transport_id,
                "tool_image_id": tool_id,
                "synthetic": bool(self.config.synthetic_docker or self.config.mode == "synthetic"),
            },
        )

    def axis_egress_seal(self) -> AxisResult:
        """Require live seal document when present; synthetic uses fixture seal."""
        seal_path = self.config.egress_seal_path
        runtime_lock_path = self.config.runtime_lock_path
        if seal_path is None and self.config.mode == "synthetic":
            seal_path = self.work_root / "fixtures" / "current_live_seal.v1.json"
            if not seal_path.is_file():
                seal_path.parent.mkdir(parents=True, exist_ok=True)
                seal = {
                    "schema_version": "xinao.provider_egress_live_seal.v1",
                    "seal_id": "synthetic-seal",
                    "issued_at": _utc_now(),
                    "expires_at": "2099-01-01T00:00:00Z",
                    "internal_network_name": "xinao_researcher_internal",
                    "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
                    "positive_canary_receipt_sha256": "d" * 64,
                    "positive_canary_receipt_relative_path": "synthetic/canary.json",
                    "completion_claim_allowed": False,
                    "synthetic": True,
                }
                _write_json_atomic(seal_path, seal)
        if seal_path is None:
            return self._set_axis(
                "egress_seal",
                "failed",
                reason_code="EGRESS_LIVE_SEAL_MISSING",
                detail="live mode requires --egress-seal-path",
            )
        path = Path(seal_path)
        if not path.is_file():
            return self._set_axis(
                "egress_seal",
                "failed",
                reason_code="EGRESS_LIVE_SEAL_MISSING",
                detail=str(path),
            )
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return self._set_axis(
                "egress_seal",
                "failed",
                reason_code="EGRESS_LIVE_SEAL_INVALID",
                detail=str(exc),
            )
        if (
            not isinstance(doc, dict)
            or doc.get("schema_version") != "xinao.provider_egress_live_seal.v1"
        ):
            return self._set_axis(
                "egress_seal",
                "failed",
                reason_code="EGRESS_LIVE_SEAL_INVALID",
                detail="schema",
            )
        # Runtime lock posture check (source must not claim live verified=true).
        lock_detail: dict[str, Any] = {}
        if runtime_lock_path is None and self.config.mode == "synthetic":
            runtime_lock_path = (
                self.repo / "skills" / "xinao" / "references" / "researcher-runtime-lock.v1.json"
            )
        if runtime_lock_path is not None and Path(runtime_lock_path).is_file():
            lock = json.loads(Path(runtime_lock_path).read_text(encoding="utf-8"))
            if lock.get("network_profile") != "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL":
                return self._set_axis(
                    "egress_seal",
                    "failed",
                    reason_code="EGRESS_BOUNDARY_UNAVAILABLE",
                    detail=str(lock.get("network_profile")),
                )
            if lock.get("provider_egress_runtime_verified") is True:
                return self._set_axis(
                    "egress_seal",
                    "failed",
                    reason_code="EGRESS_SOURCE_CLAIM_FORBIDDEN",
                    detail="source provider_egress_runtime_verified must remain false",
                )
            lock_detail = {
                "network_profile": lock.get("network_profile"),
                "provider_egress_runtime_verified": lock.get("provider_egress_runtime_verified"),
            }
        digest = _sha256_file(path)
        self.export_hashes["egress_live_seal_sha256"] = digest
        return self._set_axis(
            "egress_seal",
            "passed",
            evidence={
                "seal_path": str(path),
                "seal_sha256": digest,
                "synthetic": bool(doc.get("synthetic")),
                "runtime_lock": lock_detail,
                "live_docker_observe": False
                if self.config.mode == "synthetic"
                else "owner_must_reobserve",
            },
        )

    def axis_canary_identity(self) -> AxisResult:
        entry = self._researcher_pkg() / "entrypoint.py"
        if not entry.is_file():
            return self._set_axis(
                "canary_identity",
                "failed",
                reason_code="CANARY_ENTRYPOINT_MISSING",
                detail=str(entry),
            )
        raw = entry.read_bytes()
        digest = _sha256_bytes(raw)
        expected = self.config.expected_canary_sha256
        if digest != expected:
            return self._set_axis(
                "canary_identity",
                "failed",
                reason_code="CANARY_ENTRYPOINT_SHA_MISMATCH",
                detail=f"expected={expected} observed={digest}",
            )
        if b"\r" in raw:
            return self._set_axis(
                "canary_identity",
                "failed",
                reason_code="CANARY_ENTRYPOINT_CRLF_FORBIDDEN",
            )
        text = raw.decode("utf-8")
        if "GENUINE_SCIENTIST_EPISODE" in text or "episode_entrypoint" in text:
            return self._set_axis(
                "canary_identity",
                "failed",
                reason_code="CANARY_ENTRYPOINT_PROFILE_DRIFT",
            )
        self.export_hashes["canary_entrypoint_sha256"] = digest
        return self._set_axis(
            "canary_identity",
            "passed",
            evidence={
                "entrypoint_path": str(entry),
                "sha256": digest,
                "profile": PROFILE_CANARY,
            },
        )

    def compute_candidate_build_lock(self) -> dict[str, Any]:
        pkg = self._researcher_pkg()
        rows: list[dict[str, str]] = []
        for relative in RESEARCHER_IMAGE_MODULE_INVENTORY:
            path = pkg / relative
            if not path.is_file():
                raise HarnessError("CANDIDATE_BUILD_LOCK_MISSING_MODULE", relative)
            payload = path.read_bytes()
            if relative.endswith(
                (".py", ".sh", ".json", ".md", ".txt", ".toml", ".gitkeep", ".keep")
            ):
                payload = _lf_bytes(payload)
            rows.append({"relative_path": relative, "sha256": _sha256_bytes(payload)})
        tree = _sha256_bytes(_canonical_bytes(rows))
        lock = {
            "schema_version": BUILD_LOCK_SCHEMA,
            "package_relative": "docker/xinao-researcher",
            "modules": rows,
            "researcher_image_modules_tree_sha256": tree,
            "canary_entrypoint_sha256": self.export_hashes.get(
                "canary_entrypoint_sha256", SEALED_CANARY_SHA256
            ),
            "default_profile": PROFILE_CANARY,
            "episode_profile": "GENUINE_SCIENTIST_EPISODE",
            "mcp_tools_allowlist": "search_tool,use_tool",
            "completion_claim_allowed": False,
            "created_at": _utc_now(),
        }
        return lock

    def axis_candidate_build_lock(self) -> AxisResult:
        try:
            lock = self.compute_candidate_build_lock()
        except HarnessError as exc:
            return self._set_axis(
                "candidate_build_lock",
                "failed",
                reason_code=exc.reason_code,
                detail=exc.detail,
            )
        lock_path = self.config.build_lock_path or (self.work_root / "candidate_build_lock.json")
        _write_json_atomic(Path(lock_path), lock)
        tree = lock["researcher_image_modules_tree_sha256"]
        if HEX_SHA256.fullmatch(tree) is None:
            return self._set_axis(
                "candidate_build_lock",
                "failed",
                reason_code="CANDIDATE_BUILD_LOCK_TREE_INVALID",
                detail=tree,
            )
        self.export_hashes["candidate_build_lock_sha256"] = _sha256_file(Path(lock_path))
        self.export_hashes["researcher_image_modules_tree_sha256"] = tree
        return self._set_axis(
            "candidate_build_lock",
            "passed",
            evidence={
                "build_lock_path": str(lock_path),
                "researcher_image_modules_tree_sha256": tree,
                "module_count": len(lock["modules"]),
            },
        )

    def axis_instrument_canary_semantics(self) -> AxisResult:
        """Prove canary one-shot / empty-tools / no-web markers; plan host canary argv."""
        entry = self._researcher_pkg() / "entrypoint.py"
        text = entry.read_text(encoding="utf-8")
        markers = {
            "max_turns_1": bool(re.search(r"""["']--max-turns["']\s*,\s*["']1["']""", text)),
            "empty_tools": bool(re.search(r"""["']--tools["']\s*,\s*["']{2}""", text)),
            "disable_web": "--disable-web-search" in text,
            "no_subagents": "--no-subagents" in text,
            "no_memory": "--no-memory" in text,
            "no_genuine_profile": "GENUINE_SCIENTIST_EPISODE" not in text,
        }
        if not all(markers.values()):
            return self._set_axis(
                "instrument_canary_semantics",
                "failed",
                reason_code="CANARY_SEMANTICS_DRIFT",
                detail=json.dumps(markers, sort_keys=True),
            )
        planned_argv = [
            "/usr/local/bin/grok",
            "--prompt-file",
            "/input/prompt.md",
            "--model",
            "grok-4.5",
            "--output-format",
            "json",
            "--no-subagents",
            "--no-memory",
            "--disable-web-search",
            "--max-turns",
            "1",
            "--tools",
            "",
        ]
        # Host command Codex may run for live canary (INSTRUMENT_CANARY image entrypoint).
        host_canary_cmd = [
            self.config.docker,
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            self.config.transport_image,
            # Default ENTRYPOINT is canary; do not override to episode_entrypoint.
        ]
        evidence = {
            "markers": markers,
            "planned_grok_argv": planned_argv,
            "host_canary_command": host_canary_cmd,
            "static_only": self.config.canary_static_only or self.config.mode != "live",
            "live_canary_executed": False,
        }
        if self.config.mode == "live" and not self.config.canary_static_only:
            # Live seat may run the planned docker command; capture return without claiming science.
            completed = self.runner(host_canary_cmd)
            evidence["live_canary_executed"] = True
            evidence["live_canary_returncode"] = completed.returncode
            evidence["live_canary_stderr_tail"] = (completed.stderr or "")[-500:]
            if completed.returncode != 0:
                return self._set_axis(
                    "instrument_canary_semantics",
                    "failed",
                    reason_code="CANARY_LIVE_RUN_FAILED",
                    detail=f"rc={completed.returncode}",
                    evidence=evidence,
                )
        self.export_hashes["canary_planned_argv_sha256"] = _sha256_bytes(
            _canonical_bytes(planned_argv)
        )
        return self._set_axis("instrument_canary_semantics", "passed", evidence=evidence)

    def axis_dual_container_pair(self) -> AxisResult:
        host = self._make_host()
        stamp = _utc_now().replace(":", "").replace("-", "")[:15]
        episode_id = self.episode_meta.get("episode_id") or f"xre_{stamp}_{uuid.uuid4().hex[:12]}"
        session_id = (
            self.episode_meta.get("session_id") or f"xrsess_{stamp}_{uuid.uuid4().hex[:12]}"
        )
        self.episode_meta["episode_id"] = episode_id
        self.episode_meta["session_id"] = session_id
        try:
            created = host.create_pair(episode_id=episode_id, session_id=session_id)
            inspected = host.inspect_pair()
            if not inspected.get("ok"):
                return self._set_axis(
                    "dual_container_pair",
                    "failed",
                    reason_code="DUAL_HOST_PRESTART_INSPECT_FAILED",
                    detail=json.dumps(
                        {
                            "tool": inspected.get("tool_violations"),
                            "transport": inspected.get("transport_violations"),
                        },
                        sort_keys=True,
                    ),
                )
            validated = host.validate_before_start()
            started = host.start_pair()
        except Exception as exc:  # noqa: BLE001
            reason = getattr(exc, "reason_code", "DUAL_HOST_PAIR_FAILED")
            return self._set_axis(
                "dual_container_pair",
                "failed",
                reason_code=str(reason),
                detail=str(exc),
            )
        lease = host.load_lease() or {}
        self.pair_lease = dict(lease)
        receipt = host.load_pair_receipt() or {}
        if receipt.get("pair_receipt_sha256"):
            self.export_hashes["pair_receipt_sha256"] = str(receipt["pair_receipt_sha256"])
        return self._set_axis(
            "dual_container_pair",
            "passed",
            evidence={
                "create_status": created.get("status"),
                "start_status": started.get("status"),
                "validate_status": validated.get("status"),
                "episode_id": episode_id,
                "session_id": session_id,
                "tool_container_id": lease.get("tool_container_id"),
                "transport_container_id": lease.get("transport_container_id"),
                "mcp_server": created.get("mcp_server"),
                "start_order": created.get("start_order"),
                "phase": lease.get("phase"),
                "daemon": False,
            },
        )

    def _run_lab_fail_revise_success(self, lab: Path) -> dict[str, Any]:
        """Bounded lab task: fail once, revise code, succeed (no live model)."""
        lab.mkdir(parents=True, exist_ok=True)
        target = lab / "solve.py"
        # Intentionally wrong first version.
        target.write_text(
            "def answer() -> int:\n    return 41  # deliberate failure\n",
            encoding="utf-8",
        )
        events: list[dict[str, Any]] = []

        def _run_probe() -> tuple[int, str]:
            # Local subprocess only; not model-invoked. Lab-relative experiment.
            code = (
                "import importlib.util,sys\n"
                f"spec=importlib.util.spec_from_file_location('solve', r'{target}')\n"
                "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "print(m.answer())\n"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-c", code],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return completed.returncode, (completed.stdout or "").strip()

        rc1, out1 = _run_probe()
        events.append(
            {
                "kind": "experiment",
                "turn": 1,
                "status": "failed" if out1 != "42" else "ok",
                "stdout": out1,
                "returncode": rc1,
            }
        )
        if out1 == "42":
            raise HarnessError("LAB_TASK_EXPECTED_INITIAL_FAILURE", out1)
        # Revision after failure.
        target.write_text(
            "def answer() -> int:\n    return 42  # revised after failed experiment\n",
            encoding="utf-8",
        )
        events.append(
            {
                "kind": "revision",
                "turn": 2,
                "path_relative": "solve.py",
                "sha256": _sha256_file(target),
            }
        )
        rc2, out2 = _run_probe()
        events.append(
            {
                "kind": "experiment",
                "turn": 3,
                "status": "ok" if out2 == "42" else "failed",
                "stdout": out2,
                "returncode": rc2,
            }
        )
        if out2 != "42":
            raise HarnessError("LAB_TASK_REVISION_FAILED", out2)
        candidate = {
            "schema_version": "xinao.research_episode_terminal_candidate.v1",
            "status": "CANDIDATE_FOR_CODEX_REVIEW",
            "episode_id": self.episode_meta.get("episode_id"),
            "session_id": self.episode_meta.get("session_id"),
            "summary": "Lab task failed once, revised solve.py, succeeded with answer=42.",
            "lab_artifact_sha256s": {"solve.py": _sha256_file(target)},
            "events": events,
            "owner_adopted": False,
            "science_restored": False,
            "parent_complete": False,
            "completion_claim_allowed": False,
        }
        candidate_path = self.work_root / "output" / "terminal_candidate.json"
        _write_json_atomic(candidate_path, candidate)
        candidate_sha = _sha256_file(candidate_path)
        self.export_hashes["terminal_candidate_sha256"] = candidate_sha
        return {
            "events": events,
            "candidate_path": str(candidate_path),
            "candidate_sha256": candidate_sha,
            "multi_turn": True,
            "fail_then_revise": True,
            "success": True,
            "live_model": False,
        }

    def axis_multi_turn_fail_revise_success(self) -> AxisResult:
        if self.config.invoke_live_model:
            # Explicit refusal: this worker/harness seat must not call live provider.
            return self._set_axis(
                "multi_turn_fail_revise_success",
                "failed",
                reason_code="LIVE_MODEL_FORBIDDEN_IN_HARNESS_SEAT",
                detail="set invoke_live_model=false; Owner runs live multi-turn separately",
            )
        host = self._make_host()
        lab = Path(host.paths["lab"])
        try:
            lab_result = self._run_lab_fail_revise_success(lab)
        except HarnessError as exc:
            return self._set_axis(
                "multi_turn_fail_revise_success",
                "failed",
                reason_code=exc.reason_code,
                detail=exc.detail,
            )
        # Bind MCP events scaffold for host checkpoint.
        mcp_events = host.paths["mcp_events"]
        mcp_events.parent.mkdir(parents=True, exist_ok=True)
        for i, event in enumerate(lab_result["events"], start=1):
            line = {
                "schema_version": "xinao.dual_container_mcp_event.v1",
                "kind": event.get("kind"),
                "turn": event.get("turn"),
                "event_hash": _sha256_bytes(_canonical_bytes(event)),
                "completion_claim_allowed": False,
                "index": i,
            }
            with mcp_events.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n")
        return self._set_axis(
            "multi_turn_fail_revise_success",
            "passed",
            evidence=lab_result,
        )

    def axis_interrupt_resume_fresh_process(self) -> AxisResult:
        host = self._make_host()
        session_id = str(self.episode_meta.get("session_id") or "")
        if not session_id:
            return self._set_axis(
                "interrupt_resume_fresh_process",
                "failed",
                reason_code="SESSION_ID_MISSING",
            )
        try:
            solve_path = Path(host.paths["lab"]) / "solve.py"
            if solve_path.is_file():
                solve_digest = _sha256_file(solve_path)
            else:
                solve_digest = "f" * 64
            bound = host.checkpoint_bind(
                cas_sha256s={"solve.py": solve_digest},
                progress_note="durable checkpoint before forced interrupt",
            )
            interrupted = host.interrupt_pair()
            # Remove attempt containers (cancel lease-owned only).
            cancelled = host.cancel_pair()
            # After cancel, phase is terminal. Owner live path recreates the pair with
            # the same session identity in a fresh host process. Synthetic control-flow:
            # 1) checkpoint bind durable
            # 2) interrupt marks phase
            # 3) cancel removes only lease IDs
            # 4) fresh DualContainerHost + create/start/interrupt/resume exact session
            # 5) foreign session rejected
            import shutil

            resume_root = self.work_root / "episode_resume_fresh"
            if resume_root.exists():
                shutil.rmtree(resume_root)
            cfg2 = self.host_mod.DualHostConfig(
                transport_image=self.config.transport_image,
                tool_image=self.config.tool_image,
                auth_host_path=self._auth_path(),
                episode_root=resume_root,
                docker=self.config.docker,
                runner=self.runner,
                synthetic=True,
            )
            resume_host = self.host_mod.DualContainerHost(cfg2)
            resume_host.create_pair(
                episode_id=str(self.episode_meta["episode_id"]),
                session_id=session_id,
                resume_session_id=session_id,
            )
            resume_host.start_pair()
            resume_host.checkpoint_bind(progress_note="fresh-process durable head")
            resume_host.interrupt_pair()
            resumed = resume_host.resume_pair(expected_session_id=session_id)
            try:
                resume_host.resume_pair(expected_session_id="xrsess_FOREIGN_SESSION_DRIFT")
                foreign_rejected = False
            except Exception as exc:  # noqa: BLE001
                foreign_rejected = getattr(exc, "reason_code", "") in {
                    "DUAL_HOST_FOREIGN_SESSION",
                    "DUAL_HOST_RESUME_IDENTITY_DRIFT",
                }
            if not foreign_rejected:
                return self._set_axis(
                    "interrupt_resume_fresh_process",
                    "failed",
                    reason_code="FOREIGN_SESSION_NOT_REJECTED",
                )
        except Exception as exc:  # noqa: BLE001
            reason = getattr(exc, "reason_code", "INTERRUPT_RESUME_FAILED")
            return self._set_axis(
                "interrupt_resume_fresh_process",
                "failed",
                reason_code=str(reason),
                detail=str(exc),
            )
        self.export_hashes["checkpoint_bind_sha256"] = str(
            bound.get("checkpoint_bind_sha256") or ""
        )
        return self._set_axis(
            "interrupt_resume_fresh_process",
            "passed",
            evidence={
                "checkpoint_status": bound.get("status"),
                "checkpoint_bind_sha256": bound.get("checkpoint_bind_sha256"),
                "interrupt_status": interrupted.get("status"),
                "cancel_status": cancelled.get("status"),
                "fresh_resume_status": resumed.get("status"),
                "exact_session_bound": resumed.get("exact_session_bound"),
                "planned_grok_argv": resumed.get("planned_grok_argv"),
                "foreign_session_rejected": True,
                "fresh_host_process": True,
            },
        )

    def axis_immutable_export(self) -> AxisResult:
        export_doc = {
            "schema_version": EXPORT_SCHEMA,
            "created_at": _utc_now(),
            "episode_id": self.episode_meta.get("episode_id"),
            "session_id": self.episode_meta.get("session_id"),
            "hashes": dict(self.export_hashes),
            "axis_statuses": {k: v.status for k, v in self.axes.items()},
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
            "role_fitness_claimed": False,
        }
        export_path = self.work_root / "immutable_export.json"
        _write_json_atomic(export_path, export_doc)
        export_sha = _sha256_file(export_path)
        # Require core hashes present.
        required = (
            "canary_entrypoint_sha256",
            "candidate_build_lock_sha256",
            "terminal_candidate_sha256",
        )
        missing = [k for k in required if k not in self.export_hashes]
        if missing:
            return self._set_axis(
                "immutable_export",
                "failed",
                reason_code="EXPORT_HASHES_INCOMPLETE",
                detail=",".join(missing),
                evidence={"export_path": str(export_path)},
            )
        self.export_hashes["immutable_export_sha256"] = export_sha
        return self._set_axis(
            "immutable_export",
            "passed",
            evidence={
                "export_path": str(export_path),
                "export_sha256": export_sha,
                "hashes": dict(self.export_hashes),
            },
        )

    def axis_non_reachability_negatives(self) -> AxisResult:
        """Credential/path/network/Docker/account/shadow non-reachability (create-spec + inspect)."""
        cases: list[dict[str, Any]] = []

        def _case(case_id: str, ok: bool, detail: str = "") -> None:
            cases.append({"case_id": case_id, "ok": ok, "detail": detail})

        tool = self.specs.tool_executor_container_spec(
            image="img",
            name="n",
            episode_lab_host_path="/host/lab",
            ipc_host_dir="/host/ipc",
        )
        _case("tool_spec_clean", self.specs.validate_tool_spec_invariants(tool) == [])

        poisoned_auth = dict(tool)
        poisoned_auth["binds"] = list(tool["binds"]) + [
            {"host": "/home/user/.grok/auth.json", "container": "/grok-home/.grok", "mode": "ro"}
        ]
        auth_v = self.specs.validate_tool_spec_invariants(poisoned_auth)
        _case(
            "tool_rejects_auth_mount",
            any("forbidden" in v or "unexpected" in v for v in auth_v),
            ",".join(auth_v[:4]),
        )

        docker_sock = dict(tool)
        docker_sock["binds"] = list(tool["binds"]) + [
            {"host": "/var/run/docker.sock", "container": "/var/run/docker.sock", "mode": "rw"}
        ]
        sock_v = self.specs.validate_tool_spec_invariants(docker_sock)
        _case(
            "tool_rejects_docker_socket",
            any("forbidden" in v or "unexpected" in v for v in sock_v),
            ",".join(sock_v[:4]),
        )

        ledger = dict(tool)
        ledger["binds"] = list(tool["binds"]) + [
            {"host": "/accounts/ledger", "container": "/ledger", "mode": "rw"}
        ]
        ledger_v = self.specs.validate_tool_spec_invariants(ledger)
        _case(
            "tool_rejects_ledger",
            any("forbidden" in v or "unexpected" in v or "ledger" in v for v in ledger_v),
            ",".join(ledger_v[:4]),
        )

        shadow = dict(tool)
        shadow["binds"] = list(tool["binds"]) + [
            {"host": "/shadow", "container": "/shadow", "mode": "rw"}
        ]
        shadow_v = self.specs.validate_tool_spec_invariants(shadow)
        _case(
            "tool_rejects_shadow",
            any("forbidden" in v or "unexpected" in v or "shadow" in v for v in shadow_v),
            ",".join(shadow_v[:4]),
        )

        net = dict(tool)
        net["network"] = "bridge"
        net_v = self.specs.validate_tool_spec_invariants(net)
        _case(
            "tool_rejects_bridge_network", any("network" in v for v in net_v), ",".join(net_v[:4])
        )

        # Path traversal markers in forbidden list.
        _case(
            "forbidden_tool_mounts_include_docker_and_auth",
            "/var/run/docker.sock" in self.specs.FORBIDDEN_TOOL_MOUNTS
            and "/grok-home" in self.specs.FORBIDDEN_TOOL_MOUNTS,
        )

        transport = self.specs.transport_container_spec(
            image="img",
            name="t",
            auth_host_path="/host/auth",
            input_host_path="/host/input",
            output_host_path="/host/output",
            ipc_host_dir="/host/ipc",
            use_episode_entrypoint=True,
        )
        broad = dict(transport)
        broad["binds"] = list(transport["binds"]) + [
            {"host": "/workspace", "container": "/workspace", "mode": "rw"}
        ]
        broad_v = self.specs.validate_transport_spec_invariants(broad)
        _case(
            "transport_rejects_broad_workspace",
            any("workspace" in v or "unexpected" in v for v in broad_v),
            ",".join(broad_v[:4]),
        )

        # Inspect-level docker.sock + ledger rejects.
        bad_tool_inspect = {
            "Id": "t1",
            "Image": "sha256:" + "1" * 64,
            "Config": {
                "User": "65532:65532",
                "Entrypoint": ["python", "-I", "/opt/xinao-tool-executor/tool_executor.py"],
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
            },
            "Mounts": [
                {"Destination": "/episode-lab", "Source": "/lab"},
                {"Destination": "/ipc", "Source": "/ipc"},
                {"Destination": "/var/run/docker.sock", "Source": "/var/run/docker.sock"},
            ],
        }
        inspect_v = self.specs.validate_tool_container_inspect(bad_tool_inspect)
        _case(
            "inspect_rejects_docker_socket",
            any("forbidden" in v or "unexpected" in v for v in inspect_v),
            ",".join(inspect_v[:4]),
        )

        failed = [c for c in cases if not c["ok"]]
        if failed:
            return self._set_axis(
                "non_reachability_negatives",
                "failed",
                reason_code="NON_REACHABILITY_CASE_FAILED",
                detail=",".join(c["case_id"] for c in failed),
                evidence={"cases": cases, "live_kernel_namespace_proof": False},
            )
        return self._set_axis(
            "non_reachability_negatives",
            "passed",
            evidence={
                "cases": cases,
                "live_kernel_namespace_proof": False,
                "note": (
                    "Create-spec and inspect validators only. Physical dual-container "
                    "PID/mount non-reachability remains Owner live proof."
                ),
            },
        )

    def axis_capability_gate(self) -> AxisResult:
        """Any missing/failed axis → genuine_scientist UNAVAILABLE; never claim role fitness."""
        blocking = []
        for name, axis in self.axes.items():
            if name == "capability_gate":
                continue
            if axis.status in {"failed", "not_run", "skipped"}:
                blocking.append({"name": name, "status": axis.status, "reason": axis.reason_code})
        if blocking:
            return self._set_axis(
                "capability_gate",
                "passed",
                reason_code="CAPABILITY_UNAVAILABLE",
                detail=f"{len(blocking)} blocking axes",
                evidence={
                    "genuine_scientist_status": CAPABILITY_UNAVAILABLE,
                    "blocking_axes": blocking,
                    "role_fitness_claimed": False,
                    "completion_claim_allowed": False,
                },
            )
        # All prior axes passed: still do NOT claim role fitness / parent completion.
        # Live model multi-turn + kernel isolation remain unresolved by policy.
        return self._set_axis(
            "capability_gate",
            "passed",
            reason_code="PARTIAL_ONLY",
            evidence={
                "genuine_scientist_status": CAPABILITY_PARTIAL,
                "blocking_axes": [],
                "role_fitness_claimed": False,
                "live_model_episode": False,
                "live_docker_kernel_isolation": False,
                "completion_claim_allowed": False,
                "note": (
                    "Harness control-flow green is not role fitness. Owner must still "
                    "run live multi-turn model MCP episode and physical isolation proofs."
                ),
            },
        )

    # --- Orchestration --------------------------------------------------------

    def exact_host_commands(self) -> list[dict[str, Any]]:
        """Exact commands Codex runs on Windows host after integration/build."""
        episode = r"D:\XINAO_RESEARCH_RUNTIME\runs\live_acceptance\episode"
        auth = r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\auth"
        seal = (
            r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container"
            r"\egress\current_live_seal.v1.json"
        )
        pointer = r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\current_pointer.json"
        py = "python"
        harness = r"skills\xinao\scripts\live_acceptance_harness.py"
        return [
            {
                "step": 1,
                "title": "Build tool-executor image (no auth)",
                "shell": "powershell",
                "command": (
                    "docker build -f docker/xinao-researcher/Dockerfile.tool-executor "
                    "-t xinao-tool-executor:candidate ."
                ),
            },
            {
                "step": 2,
                "title": "Build/inspect transport image via existing release pipeline",
                "shell": "powershell",
                "command": (
                    "docker image inspect --format '{{.Id}}' xinao-tool-executor:candidate; "
                    "docker image inspect --format '{{.Id}}' <transport-image-ref>"
                ),
            },
            {
                "step": 3,
                "title": "Run live acceptance harness (Owner seat)",
                "shell": "powershell",
                "command": (
                    f"{py} -I {harness} run-live "
                    f"--work-root {episode}\\harness "
                    f"--transport-image <transport-image-ref> "
                    f"--tool-image xinao-tool-executor:candidate "
                    f"--auth-host-path {auth} "
                    f"--pointer-path {pointer} "
                    f"--egress-seal-path {seal} "
                    f"--expected-transport-image-id sha256:<transport_id> "
                    f"--expected-tool-image-id sha256:<tool_id>"
                ),
            },
            {
                "step": 4,
                "title": "INSTRUMENT_CANARY one-shot (unchanged entrypoint)",
                "shell": "powershell",
                "command": (
                    "python -I skills/xinao/scripts/xinao.py research "
                    "--question 'instrument canary acceptance probe'"
                ),
                "notes": "Default ENTRYPOINT remains entrypoint.py; do not pass episode_entrypoint.",
            },
            {
                "step": 5,
                "title": "Optional dual-host research-episode verbs",
                "shell": "powershell",
                "command": (
                    "$env:XINAO_DUAL_CONTAINER_HOST='1'; "
                    "$env:XINAO_TRANSPORT_IMAGE='sha256:<transport_id>'; "
                    "$env:XINAO_TOOL_EXECUTOR_IMAGE='sha256:<tool_id>'; "
                    f"$env:XINAO_AUTH_HOST_PATH='{auth}'; "
                    f"python -I skills/xinao/scripts/xinao.py research-episode start "
                    f"--root {episode} --question 'live multi-turn MCP lab task'"
                ),
            },
            {
                "step": 6,
                "title": "Interrupt → remove attempt containers → fresh-process resume",
                "shell": "powershell",
                "command": (
                    f"python -I skills/xinao/scripts/xinao.py research-episode checkpoint "
                    f"--root {episode} --expected-head <head> --mark-interrupted; "
                    f"python -I skills/xinao/scripts/xinao.py research-episode cancel --root {episode}; "
                    "# new host process / shell\n"
                    f"python -I skills/xinao/scripts/xinao.py research-episode resume "
                    f"--root {episode} --expected-head <head> --expected-session <session_id>"
                ),
            },
            {
                "step": 7,
                "title": "Rollback / retire if any axis fails",
                "shell": "powershell",
                "command": (
                    "Remove-Item Env:XINAO_DUAL_CONTAINER_HOST -ErrorAction SilentlyContinue; "
                    "Remove-Item Env:XINAO_TRANSPORT_IMAGE -ErrorAction SilentlyContinue; "
                    "Remove-Item Env:XINAO_TOOL_EXECUTOR_IMAGE -ErrorAction SilentlyContinue; "
                    "Remove-Item Env:XINAO_AUTH_HOST_PATH -ErrorAction SilentlyContinue; "
                    "# cancel lease-owned containers/volumes only via harness retire or "
                    "research-episode cancel; never docker system prune; "
                    "# do not touch shadow ledger, freeze, outcome, or Owner text"
                ),
            },
        ]

    def rollback_plan(self) -> dict[str, Any]:
        return {
            "schema_version": "xinao.live_acceptance_rollback.v1",
            "steps": [
                "Unset dual-host env vars (XINAO_DUAL_CONTAINER_HOST, images, auth path).",
                "Leave INSTRUMENT_CANARY as default entrypoint (no pointer change required for harness-only rollback).",
                "Cancel/retire only lease-recorded container IDs and IPC volumes.",
                "Do not docker system prune; do not touch shadow ledger, freeze, outcome, settlement.",
                "Mark genuine_scientist UNAVAILABLE until all live axes pass under Owner seal.",
                "Optional file retirement (Owner decision only): live_acceptance_harness.py, its tests, harness work_root.",
            ],
            "completion_claim_allowed": False,
        }

    def run(self) -> dict[str, Any]:
        if self.config.mode == "plan":
            result = self._result_skeleton(status="PLAN_ONLY")
            result["exact_host_commands"] = self.exact_host_commands()
            result["rollback"] = self.rollback_plan()
            _write_json_atomic(self.work_root / "harness_result.json", result)
            return result

        self._journal("harness_start", mode=self.config.mode)
        ordered = [
            self.axis_pointer_identity,
            self.axis_image_identity,
            self.axis_egress_seal,
            self.axis_canary_identity,
            self.axis_candidate_build_lock,
            self.axis_instrument_canary_semantics,
            self.axis_dual_container_pair,
            self.axis_multi_turn_fail_revise_success,
            self.axis_interrupt_resume_fresh_process,
            self.axis_immutable_export,
            self.axis_non_reachability_negatives,
            self.axis_capability_gate,
        ]
        for fn in ordered:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 — axis fail-closed
                name = fn.__name__.removeprefix("axis_")
                self._set_axis(
                    name,
                    "failed",
                    reason_code=getattr(exc, "reason_code", "AXIS_EXCEPTION"),
                    detail=str(exc),
                )
                # Continue remaining axes so capability gate still runs.
                continue
        # Ensure capability gate runs even if earlier exception skipped it.
        if self.axes["capability_gate"].status == "not_run":
            self.axis_capability_gate()

        failed = [n for n, a in self.axes.items() if a.status == "failed"]
        status = "HARNESS_FAILED" if failed else "HARNESS_PARTIAL_OK"
        result = self._result_skeleton(status=status)
        result["axes"] = {k: v.as_dict() for k, v in self.axes.items()}
        result["export_hashes"] = dict(self.export_hashes)
        result["episode"] = dict(self.episode_meta)
        result["exact_host_commands"] = self.exact_host_commands()
        result["rollback"] = self.rollback_plan()
        result["failed_axes"] = failed
        gate = self.axes["capability_gate"].evidence
        result["genuine_scientist_status"] = gate.get(
            "genuine_scientist_status", CAPABILITY_UNAVAILABLE
        )
        result["role_fitness_claimed"] = False
        _write_json_atomic(self.work_root / "harness_result.json", result)
        self._journal("harness_end", status=status, failed=failed)
        return result

    def _result_skeleton(self, *, status: str) -> dict[str, Any]:
        return {
            "schema_version": HARNESS_SCHEMA,
            "status": status,
            "mode": self.config.mode,
            "work_root": str(self.work_root),
            "repo_root": str(self.repo),
            "daemon": False,
            "goal": False,
            "temporal_leg_b": False,
            "resident_pool": False,
            "shadow_ledger_touched": False,
            "activation_performed": False,
            "live_model_invoked": False,
            "instrument_canary_preserved": True,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
            "created_at": _utc_now(),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live_acceptance_harness",
        description="Owner-invoked non-daemon live acceptance harness (candidate).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--work-root", type=Path, required=True)
        p.add_argument("--repo-root", type=Path, default=None)
        p.add_argument("--transport-image", default="xinao-researcher:candidate")
        p.add_argument("--tool-image", default="xinao-tool-executor:candidate")
        p.add_argument("--auth-host-path", type=Path, default=None)
        p.add_argument("--pointer-path", type=Path, default=None)
        p.add_argument("--egress-seal-path", type=Path, default=None)
        p.add_argument("--runtime-lock-path", type=Path, default=None)
        p.add_argument("--build-lock-path", type=Path, default=None)
        p.add_argument("--expected-transport-image-id", default=None)
        p.add_argument("--expected-tool-image-id", default=None)
        p.add_argument("--expected-canary-sha256", default=SEALED_CANARY_SHA256)
        p.add_argument("--docker", default="docker")

    p_syn = sub.add_parser("run-synthetic", help="Fakes/synthetic docker control-flow only")
    add_common(p_syn)
    p_live = sub.add_parser(
        "run-live",
        help="Host path: real image inspect/create when docker available; no live model",
    )
    add_common(p_live)
    p_live.add_argument(
        "--execute-canary-container",
        action="store_true",
        help="Actually docker-run canary image (Owner only)",
    )
    p_plan = sub.add_parser("plan", help="Emit exact host commands only")
    p_plan.add_argument("--work-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "plan":
        cfg = HarnessConfig(work_root=args.work_root, mode="plan")
        result = LiveAcceptanceHarness(cfg).run()
        _emit_json_stdout(result)
        return 0
    if args.command == "run-synthetic":
        cfg = HarnessConfig(
            work_root=args.work_root,
            repo_root=args.repo_root,
            mode="synthetic",
            transport_image=args.transport_image,
            tool_image=args.tool_image,
            auth_host_path=args.auth_host_path,
            pointer_path=args.pointer_path,
            egress_seal_path=args.egress_seal_path,
            runtime_lock_path=args.runtime_lock_path,
            build_lock_path=args.build_lock_path,
            expected_transport_image_id=args.expected_transport_image_id,
            expected_tool_image_id=args.expected_tool_image_id,
            expected_canary_sha256=args.expected_canary_sha256,
            docker=args.docker,
            synthetic_docker=True,
            canary_static_only=True,
            invoke_live_model=False,
        )
    elif args.command == "run-live":
        cfg = HarnessConfig(
            work_root=args.work_root,
            repo_root=args.repo_root,
            mode="live",
            transport_image=args.transport_image,
            tool_image=args.tool_image,
            auth_host_path=args.auth_host_path,
            pointer_path=args.pointer_path,
            egress_seal_path=args.egress_seal_path,
            runtime_lock_path=args.runtime_lock_path,
            build_lock_path=args.build_lock_path,
            expected_transport_image_id=args.expected_transport_image_id,
            expected_tool_image_id=args.expected_tool_image_id,
            expected_canary_sha256=args.expected_canary_sha256,
            docker=args.docker,
            synthetic_docker=False,
            canary_static_only=not bool(getattr(args, "execute_canary_container", False)),
            invoke_live_model=False,
        )
    else:
        _emit_json_stdout({"error": "unknown command", "completion_claim_allowed": False})
        return 2
    harness = LiveAcceptanceHarness(cfg)
    result = harness.run()
    _emit_json_stdout(result)
    return 0 if result.get("status") in {"HARNESS_PARTIAL_OK", "PLAN_ONLY"} else 1


if __name__ == "__main__":
    sys.exit(main())
