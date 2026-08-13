"""Single fail-closed seam from selected cognition to durable shared effects.

This module is intentionally not a general action bus.  Controller, quota,
context-runtime, and other internal single-writer state do not pass through it.
The production registry currently contains exactly one adapter: adoption of an
already committed ``root-main`` output into the canonical logical-root store.

The canonical production factory owns its authority boundary and currently
fails with ``SELECTION_REQUIRED`` because no live selector is installed.  It
does not accept a caller-supplied boundary.  Noncanonical test seams may inject
a process-local grant boundary; merely importing this module, naming an owner,
or reconstructing historical Context cannot mint such a grant.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import portalocker

from services.xinao_perpetual_world_compute.logical_root_runtime import (
    DEFAULT_EFFECT_GATEWAY_RUNTIME,
    DEFAULT_LOGICAL_ROOT_RUNTIME,
    EFFECT_GATEWAY_TRANSACTION_PHASE_SCHEMA,
    LogicalRootError,
    LogicalRootStore,
    RootIdentity,
)

REQUEST_SCHEMA = "xinao.effect-gateway-request.v2"
RECEIPT_SCHEMA = "xinao.effect-gateway-receipt.v2"
TRANSACTION_PHASE_SCHEMA = EFFECT_GATEWAY_TRANSACTION_PHASE_SCHEMA
TRANSACTION_PROJECTION_SCHEMA = "xinao.effect-gateway-transaction-projection.v1"
OWNER_INVOCATION_SCHEMA = "xinao.effect-gateway-current-owner-invocation.v2"
LOGICAL_ROOT_ADOPTION_ADAPTER = "logical-root.adoption.v1"

DEFAULT_WORLD_COMPUTE_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME\state")
DEFAULT_EFFECT_REALITY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_effect_gateway\reality")
DEFAULT_EFFECT_BLIND_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_effect_gateway\blind-boundaries"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,191}$")
_FORBIDDEN_UNIMPLEMENTED_PREFIXES = (
    "capital.",
    "publication.",
    "publish.",
    "public-release.",
)
_LOGICAL_ROOT_REALITY_LABELS = frozenset({"current-reality", "current-price-reality"})
_LOGICAL_ROOT_BLIND_LABELS = frozenset({"blind-boundary", "blind-input-cutoff"})


class EffectGatewayError(RuntimeError):
    """Typed fail-closed gateway error."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        facts: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.facts = dict(facts or {})
        super().__init__(f"{code}: {detail}")


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    text = str(value or "").lower()
    if not _SHA256_RE.fullmatch(text):
        raise EffectGatewayError("REQUEST_INVALID", f"{label} must be a lowercase SHA-256")
    return text


def _require_id(value: object, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID_RE.fullmatch(text):
        raise EffectGatewayError("REQUEST_INVALID", f"{label} must be a bounded identifier")
    return text


def _require_owner_scope(value: object) -> str:
    text = str(value or "")
    if not text or len(text) > 256 or any(ord(character) < 32 for character in text):
        raise EffectGatewayError(
            "REQUEST_INVALID", "effect_owner_scope must be nonempty and contain no controls"
        )
    return text


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == os.path.commonpath(
            (str(parent), str(parent))
        )
    except ValueError:
        return False


def _read_stable(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise EffectGatewayError("EVIDENCE_NOT_REGULAR_FILE", str(path))
            raw = stream.read()
            after = os.fstat(stream.fileno())
    except FileNotFoundError as exc:
        raise EffectGatewayError("EVIDENCE_MISSING", str(path)) from exc
    except OSError as exc:
        raise EffectGatewayError("EVIDENCE_READ_FAILED", f"{path}: {exc}") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != after.st_size
    ):
        raise EffectGatewayError("EVIDENCE_CHANGED_DURING_READ", str(path))
    return raw


def _is_regular_single_link_nonreparse(path: Path) -> bool:
    try:
        observed = path.lstat()
    except OSError:
        return False
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return (
        stat.S_ISREG(observed.st_mode)
        and not (reparse_flag and attributes & reparse_flag)
        and observed.st_nlink == 1
    )


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_durable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_durable_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise EffectGatewayError("IMMUTABLE_RECEIPT_ALREADY_EXISTS", str(path)) from exc
    _fsync_directory(path.parent)


def _load_canonical_record(
    path: Path,
    *,
    schema: str,
    seal_field: str,
    error_prefix: str,
) -> dict[str, object]:
    raw = _read_stable(path)
    try:
        record = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EffectGatewayError(f"{error_prefix}_INVALID", str(path)) from exc
    if not isinstance(record, dict) or raw != _canonical_json_bytes(record):
        raise EffectGatewayError(f"{error_prefix}_INVALID", str(path))
    unsigned = dict(record)
    seal = unsigned.pop(seal_field, None)
    if record.get("schema_version") != schema or seal != _sha256(_canonical_json_bytes(unsigned)):
        raise EffectGatewayError(f"{error_prefix}_HASH_MISMATCH", str(path))
    return record


@dataclass(frozen=True)
class HashBoundRef:
    """One exact evidence file under a contract-approved canonical root."""

    label: str
    path: Path
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _require_id(self.label, "evidence label"))
        object.__setattr__(self, "path", Path(self.path).absolute())
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "evidence sha256"))
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or self.bytes < 0:
            raise EffectGatewayError("REQUEST_INVALID", "evidence bytes must be an integer >= 0")

    @classmethod
    def capture(cls, label: str, path: Path | str) -> HashBoundRef:
        normalized = Path(path).absolute()
        raw = _read_stable(normalized)
        return cls(label=label, path=normalized, sha256=_sha256(raw), bytes=len(raw))

    def verify(self) -> None:
        raw = _read_stable(self.path)
        if len(raw) != self.bytes or _sha256(raw) != self.sha256:
            raise EffectGatewayError("EVIDENCE_HASH_DRIFT", str(self.path))

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": str(self.path),
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class EffectGatewayRequest:
    """Hash-bound request for the currently supported logical-root effect."""

    request_id: str
    adapter_kind: str
    effect_owner_scope: str
    source_run_dir: Path
    account_slot: str
    candidate_sha256: str
    source_run_sha256: str
    root_output_sha256: str
    expected_predecessor: RootIdentity
    reality_refs: tuple[HashBoundRef, ...]
    blind_boundary_refs: tuple[HashBoundRef, ...]
    schema_version: str = field(default=REQUEST_SCHEMA, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_id(self.request_id, "request_id"))
        object.__setattr__(self, "adapter_kind", _require_id(self.adapter_kind, "adapter_kind"))
        object.__setattr__(
            self, "effect_owner_scope", _require_owner_scope(self.effect_owner_scope)
        )
        object.__setattr__(self, "source_run_dir", Path(self.source_run_dir).absolute())
        slot = str(self.account_slot or "").upper()
        if slot not in {"A", "C"}:
            raise EffectGatewayError("REQUEST_INVALID", "account_slot must be exactly A or C")
        object.__setattr__(self, "account_slot", slot)
        for name in ("candidate_sha256", "source_run_sha256", "root_output_sha256"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))
        if not isinstance(self.expected_predecessor, RootIdentity):
            raise EffectGatewayError(
                "REQUEST_INVALID", "expected_predecessor must be a RootIdentity"
            )
        try:
            self.expected_predecessor.validate()
        except LogicalRootError as exc:
            raise EffectGatewayError("REQUEST_INVALID", str(exc)) from exc
        object.__setattr__(self, "reality_refs", tuple(self.reality_refs))
        object.__setattr__(self, "blind_boundary_refs", tuple(self.blind_boundary_refs))
        combined = (*self.reality_refs, *self.blind_boundary_refs)
        if not all(isinstance(ref, HashBoundRef) for ref in combined):
            raise EffectGatewayError("REQUEST_INVALID", "evidence refs must be HashBoundRef values")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "adapter_kind": self.adapter_kind,
            "effect_owner_scope": self.effect_owner_scope,
            "source_run_dir": str(self.source_run_dir),
            "account_slot": self.account_slot,
            "candidate_sha256": self.candidate_sha256,
            "source_run_sha256": self.source_run_sha256,
            "root_output_sha256": self.root_output_sha256,
            "expected_predecessor": self.expected_predecessor.to_dict(),
            "reality_refs": [ref.to_dict() for ref in self.reality_refs],
            "blind_boundary_refs": [ref.to_dict() for ref in self.blind_boundary_refs],
        }

    @property
    def sha256(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_dict()))


@dataclass(frozen=True)
class CurrentOwnerGrant:
    """Opaque grant produced only by an injected live authority boundary."""

    grant_id: str
    request_sha256: str
    effect_owner_scope: str
    boundary_id: str
    issued_at: str
    _proof: object = field(repr=False, compare=False)

    def evidence_dict(self) -> dict[str, object]:
        return {
            "schema_version": OWNER_INVOCATION_SCHEMA,
            "grant_id": self.grant_id,
            "request_sha256": self.request_sha256,
            "effect_owner_scope": self.effect_owner_scope,
            "boundary_id": self.boundary_id,
            "issued_at": self.issued_at,
            "current_grant_consumed_once": True,
            "historical_context_can_mint_grant": False,
            "proof_is_not_serialized": True,
        }


class LiveOwnerGrantBoundary(Protocol):
    """Injected boundary owned by the current interactive/effect surface."""

    boundary_id: str

    def issue(
        self,
        *,
        request_sha256: str,
        effect_owner_scope: str,
    ) -> CurrentOwnerGrant: ...

    def consume(
        self,
        *,
        grant: CurrentOwnerGrant,
        request_sha256: str,
        effect_owner_scope: str,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class AdapterOutcome:
    status: str
    effect_identity: Mapping[str, object]
    readback: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "effect_identity": dict(self.effect_identity),
            "readback": dict(self.readback),
        }


@dataclass(frozen=True)
class GatewayResult:
    receipt: Mapping[str, object]
    receipt_path: Path
    replayed: bool


EffectAdapter = Callable[[EffectGatewayRequest, CurrentOwnerGrant, Path], AdapterOutcome]
EffectReadback = Callable[[EffectGatewayRequest], AdapterOutcome]


@dataclass(frozen=True)
class AdapterBinding:
    apply: EffectAdapter
    readback: EffectReadback


class _NoLiveProductionSelection:
    """Fixed production state until a real current-owner selector is installed."""

    boundary_id = "canonical-production-selection-unavailable"
    selection_available = False

    def issue(
        self,
        *,
        request_sha256: str,
        effect_owner_scope: str,
    ) -> CurrentOwnerGrant:
        del request_sha256, effect_owner_scope
        raise EffectGatewayError(
            "SELECTION_REQUIRED",
            "no live current-owner candidate selection is installed",
        )

    def consume(
        self,
        *,
        grant: CurrentOwnerGrant,
        request_sha256: str,
        effect_owner_scope: str,
    ) -> Mapping[str, object]:
        del grant, request_sha256, effect_owner_scope
        raise EffectGatewayError(
            "SELECTION_REQUIRED",
            "no live current-owner candidate selection is installed",
        )


@dataclass(frozen=True)
class EffectGatewayPolicy:
    gateway_root: Path
    logical_root: Path
    allowed_source_roots: tuple[Path, ...]
    allowed_reality_roots: tuple[Path, ...]
    allowed_blind_roots: tuple[Path, ...]
    reality_labels: frozenset[str]
    blind_labels: frozenset[str]

    def __post_init__(self) -> None:
        for name in (
            "gateway_root",
            "logical_root",
        ):
            object.__setattr__(self, name, Path(getattr(self, name)).absolute())
        for name in (
            "allowed_source_roots",
            "allowed_reality_roots",
            "allowed_blind_roots",
        ):
            roots = tuple(Path(root).absolute() for root in getattr(self, name))
            if not roots:
                raise EffectGatewayError("POLICY_INVALID", f"{name} cannot be empty")
            object.__setattr__(self, name, roots)
        if not self.reality_labels or not self.blind_labels:
            raise EffectGatewayError("POLICY_INVALID", "evidence label sets cannot be empty")


def _require_under_one(path: Path, roots: Sequence[Path], label: str) -> None:
    if not any(_is_within(path, root) for root in roots):
        raise EffectGatewayError(
            "EVIDENCE_ROOT_NOT_ALLOWED", f"{label} is outside its canonical roots: {path}"
        )


def _verify_evidence_contract(
    request: EffectGatewayRequest,
    policy: EffectGatewayPolicy,
) -> None:
    if request.adapter_kind != LOGICAL_ROOT_ADOPTION_ADAPTER:
        raise EffectGatewayError("ADAPTER_NOT_REGISTERED", request.adapter_kind)
    _require_under_one(request.source_run_dir, policy.allowed_source_roots, "source run")
    if len(request.reality_refs) != 1 or len(request.blind_boundary_refs) != 1:
        raise EffectGatewayError(
            "EVIDENCE_CONTRACT_INVALID",
            "logical-root adoption requires one reality and one blind-boundary reference",
        )
    reality = request.reality_refs[0]
    blind = request.blind_boundary_refs[0]
    if reality.label not in policy.reality_labels or blind.label not in policy.blind_labels:
        raise EffectGatewayError(
            "EVIDENCE_LABEL_INVALID", "adapter evidence labels do not match the exact contract"
        )
    if _path_key(reality.path) == _path_key(blind.path):
        raise EffectGatewayError(
            "EVIDENCE_ORIGIN_NOT_INDEPENDENT",
            "reality and blind-boundary evidence must come from different files",
        )
    _require_under_one(reality.path, policy.allowed_reality_roots, reality.label)
    _require_under_one(blind.path, policy.allowed_blind_roots, blind.label)
    if _is_within(reality.path, request.source_run_dir) or _is_within(
        blind.path, request.source_run_dir
    ):
        raise EffectGatewayError(
            "EVIDENCE_ORIGIN_NOT_INDEPENDENT",
            "effect evidence cannot be sourced from the candidate run itself",
        )
    for reference in (reality, blind):
        reference.verify()


def build_logical_root_adoption_request(
    store: LogicalRootStore,
    *,
    request_id: str,
    effect_owner_scope: str,
    source_run_dir: Path | str,
    account_slot: str,
    expected_predecessor: RootIdentity,
    reality_refs: Sequence[HashBoundRef],
    blind_boundary_refs: Sequence[HashBoundRef],
) -> EffectGatewayRequest:
    """Capture exact candidate hashes without granting permission to adopt it."""

    normalized_run = Path(source_run_dir).absolute()
    slot = str(account_slot or "").upper()
    try:
        verified = store._verify_source(normalized_run, account_slot=slot)  # noqa: SLF001
    except LogicalRootError as exc:
        raise EffectGatewayError(
            "CANDIDATE_EVIDENCE_INVALID", exc.detail, facts={"source_code": exc.code}
        ) from exc
    return EffectGatewayRequest(
        request_id=request_id,
        adapter_kind=LOGICAL_ROOT_ADOPTION_ADAPTER,
        effect_owner_scope=effect_owner_scope,
        source_run_dir=normalized_run,
        account_slot=slot,
        candidate_sha256=str(verified.source["source_output_identity"]),
        source_run_sha256=_sha256(verified.evidence_blobs["run_config"]),
        root_output_sha256=_sha256(verified.artifact),
        expected_predecessor=expected_predecessor,
        reality_refs=tuple(reality_refs),
        blind_boundary_refs=tuple(blind_boundary_refs),
    )


def _candidate_hashes(store: LogicalRootStore, request: EffectGatewayRequest) -> dict[str, str]:
    try:
        verified = store._verify_source(  # noqa: SLF001
            request.source_run_dir, account_slot=request.account_slot
        )
    except LogicalRootError as exc:
        raise EffectGatewayError(
            "CANDIDATE_EVIDENCE_INVALID", exc.detail, facts={"source_code": exc.code}
        ) from exc
    return {
        "candidate_sha256": str(verified.source["source_output_identity"]),
        "source_run_sha256": _sha256(verified.evidence_blobs["run_config"]),
        "root_output_sha256": _sha256(verified.artifact),
    }


def _expected_candidate_hashes(request: EffectGatewayRequest) -> dict[str, str]:
    return {
        "candidate_sha256": request.candidate_sha256,
        "source_run_sha256": request.source_run_sha256,
        "root_output_sha256": request.root_output_sha256,
    }


def _logical_root_outcome(
    store: LogicalRootStore,
    request: EffectGatewayRequest,
) -> AdapterOutcome:
    try:
        adopted = store.read_adoption(request.request_id)
    except LogicalRootError as exc:
        if exc.code == "ADOPTION_NOT_FOUND":
            raise EffectGatewayError(
                "EFFECT_NOT_APPLIED", "logical root has no matching generation"
            ) from exc
        raise EffectGatewayError(
            "ADAPTER_READBACK_MISMATCH", exc.detail, facts={"source_code": exc.code}
        ) from exc
    if adopted.receipt is None or adopted.receipt_path is None or adopted.artifact_path is None:
        raise EffectGatewayError("EFFECT_NOT_APPLIED", "logical root has no matching generation")
    source = adopted.receipt.get("source")
    request_value = adopted.receipt.get("request")
    if not isinstance(source, Mapping) or not isinstance(request_value, Mapping):
        raise EffectGatewayError("ADAPTER_READBACK_MISMATCH", str(adopted.receipt_path))
    if request_value.get("adoption_id") != request.request_id:
        raise EffectGatewayError("ADAPTER_READBACK_MISMATCH", str(adopted.receipt_path))
    evidence_refs = adopted.receipt.get("evidence_refs")
    if not isinstance(evidence_refs, Mapping) or not isinstance(
        evidence_refs.get("run_config"), Mapping
    ):
        raise EffectGatewayError("ADAPTER_READBACK_MISMATCH", str(adopted.receipt_path))
    observed = {
        "candidate_sha256": str(source.get("source_output_identity") or ""),
        "source_run_sha256": str(evidence_refs["run_config"].get("sha256") or ""),
        "root_output_sha256": str(source.get("root_output_sha256") or ""),
    }
    if observed != _expected_candidate_hashes(request):
        raise EffectGatewayError(
            "ADAPTER_READBACK_MISMATCH",
            "logical-root receipt does not match the gateway request",
            facts={"expected": _expected_candidate_hashes(request), "observed": observed},
        )
    receipt_raw = _read_stable(adopted.receipt_path)
    artifact_raw = _read_stable(adopted.artifact_path)
    if _sha256(artifact_raw) != request.root_output_sha256:
        raise EffectGatewayError("ADAPTER_READBACK_MISMATCH", str(adopted.artifact_path))
    current = store.reconstruct_current()
    return AdapterOutcome(
        status="already_applied",
        effect_identity={"kind": "logical_xinao_root_generation", **adopted.identity.to_dict()},
        readback={
            "generation_receipt_path": str(adopted.receipt_path),
            "generation_receipt_file_sha256": _sha256(receipt_raw),
            "artifact_path": str(adopted.artifact_path),
            "artifact_sha256": _sha256(artifact_raw),
            "current_identity": current.identity.to_dict(),
            "logical_root_replayed": True,
        },
    )


def logical_root_adoption_binding(store: LogicalRootStore) -> AdapterBinding:
    """Build the logical-root apply plus readback-only recovery binding."""

    def apply(
        request: EffectGatewayRequest,
        grant: CurrentOwnerGrant,
        prepared_receipt_path: Path,
    ) -> AdapterOutcome:
        if request.adapter_kind != LOGICAL_ROOT_ADOPTION_ADAPTER:
            raise EffectGatewayError("ADAPTER_REQUEST_MISMATCH", request.adapter_kind)
        observed = _candidate_hashes(store, request)
        if observed != _expected_candidate_hashes(request):
            raise EffectGatewayError(
                "CANDIDATE_HASH_MISMATCH",
                "the current committed source no longer matches the selected candidate",
                facts={"expected": _expected_candidate_hashes(request), "observed": observed},
            )
        try:
            result = store._adopt_from_effect_gateway(  # noqa: SLF001
                source_run_dir=request.source_run_dir,
                account_slot=request.account_slot,
                expected_predecessor=request.expected_predecessor,
                adoption_id=request.request_id,
                selection_ref=f"effect-gateway-request-sha256:{request.sha256}",
                selected_by=request.effect_owner_scope,
                prepared_receipt_path=prepared_receipt_path,
            )
        except LogicalRootError as exc:
            raise EffectGatewayError(
                "ADAPTER_REJECTED", exc.detail, facts={"source_code": exc.code}
            ) from exc
        outcome = _logical_root_outcome(store, request)
        return AdapterOutcome(
            status="already_applied" if result.replayed else "applied",
            effect_identity=outcome.effect_identity,
            readback={
                **outcome.readback,
                "logical_root_replayed": result.replayed,
                "owner_grant_id": grant.grant_id,
            },
        )

    return AdapterBinding(
        apply=apply, readback=lambda request: _logical_root_outcome(store, request)
    )


class EffectGateway:
    """Receipt store and fixed adapter contract for durable effects."""

    def __init__(
        self,
        policy: EffectGatewayPolicy,
        *,
        adapters: Mapping[str, AdapterBinding],
        owner_boundary: LiveOwnerGrantBoundary,
        clock: Callable[[], str] | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.policy = policy
        self.root = policy.gateway_root
        self._adapters = dict(adapters)
        self._owner_boundary = owner_boundary
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._fault_injector = fault_injector
        if set(self._adapters) != {LOGICAL_ROOT_ADOPTION_ADAPTER}:
            raise EffectGatewayError(
                "REGISTRY_INVALID", "the canonical registry has exactly logical-root adoption"
            )
        if not str(getattr(owner_boundary, "boundary_id", "")).strip():
            raise EffectGatewayError("OWNER_BOUNDARY_INVALID", "boundary_id is required")
        targets_canonical_runtime = _path_key(policy.gateway_root) == _path_key(
            DEFAULT_EFFECT_GATEWAY_RUNTIME
        ) or _path_key(policy.logical_root) == _path_key(DEFAULT_LOGICAL_ROOT_RUNTIME)
        if targets_canonical_runtime and not isinstance(owner_boundary, _NoLiveProductionSelection):
            raise EffectGatewayError(
                "PRODUCTION_AUTHORITY_BOUNDARY_FIXED",
                "canonical Effect Gateway authority cannot be supplied by a caller",
            )

    @property
    def receipts_dir(self) -> Path:
        return self.root / "receipts"

    @property
    def transactions_dir(self) -> Path:
        return self.root / "transactions"

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _require_adapter(self, kind: str) -> AdapterBinding:
        if kind.casefold().startswith(_FORBIDDEN_UNIMPLEMENTED_PREFIXES):
            raise EffectGatewayError(
                "ADAPTER_NOT_IMPLEMENTED",
                f"capital/publication effects have no installed adapter: {kind}",
            )
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise EffectGatewayError("ADAPTER_NOT_REGISTERED", kind)
        return adapter

    def invoke_as_current_owner(self, request: EffectGatewayRequest) -> GatewayResult:
        """The only public effect method: request a grant from the live boundary."""

        if not isinstance(request, EffectGatewayRequest):
            raise EffectGatewayError("REQUEST_INVALID", "typed EffectGatewayRequest required")
        if getattr(self._owner_boundary, "selection_available", True) is False:
            raise EffectGatewayError(
                "SELECTION_REQUIRED",
                "no live current-owner candidate selection is installed",
            )
        self._require_adapter(request.adapter_kind)
        grant = self._owner_boundary.issue(
            request_sha256=request.sha256,
            effect_owner_scope=request.effect_owner_scope,
        )
        return self._invoke_with_live_grant(request, grant)

    def _consume_grant(
        self,
        request: EffectGatewayRequest,
        grant: CurrentOwnerGrant,
    ) -> Mapping[str, object]:
        if not isinstance(grant, CurrentOwnerGrant):
            raise EffectGatewayError(
                "CURRENT_OWNER_GRANT_REQUIRED",
                "durable or Context-reconstructed data cannot invoke an effect",
            )
        if grant.boundary_id != self._owner_boundary.boundary_id:
            raise EffectGatewayError("CURRENT_OWNER_BOUNDARY_MISMATCH", grant.boundary_id)
        evidence = self._owner_boundary.consume(
            grant=grant,
            request_sha256=request.sha256,
            effect_owner_scope=request.effect_owner_scope,
        )
        if (
            grant.request_sha256 != request.sha256
            or grant.effect_owner_scope != request.effect_owner_scope
        ):
            raise EffectGatewayError("CURRENT_OWNER_GRANT_MISMATCH", grant.grant_id)
        return dict(evidence)

    def _load_receipt(self, path: Path) -> dict[str, object]:
        return _load_canonical_record(
            path,
            schema=RECEIPT_SCHEMA,
            seal_field="receipt_sha256",
            error_prefix="RECEIPT",
        )

    def _load_transaction_phase(
        self,
        path: Path,
        *,
        expected_phase: str,
    ) -> dict[str, object]:
        if not _is_regular_single_link_nonreparse(path):
            raise EffectGatewayError("TRANSACTION_PHASE_NOT_IMMUTABLE", str(path))
        phase = _load_canonical_record(
            path,
            schema=TRANSACTION_PHASE_SCHEMA,
            seal_field="phase_receipt_sha256",
            error_prefix="TRANSACTION_PHASE",
        )
        if phase.get("phase") != expected_phase:
            raise EffectGatewayError("TRANSACTION_PHASE_INVALID", str(path))
        return phase

    def _write_transaction_projection(
        self,
        *,
        request: EffectGatewayRequest,
        phase_path: Path,
        phase: Mapping[str, object],
    ) -> None:
        core: dict[str, object] = {
            "schema_version": TRANSACTION_PROJECTION_SCHEMA,
            "request_id": request.request_id,
            "request_sha256": request.sha256,
            "latest_phase": phase["phase"],
            "phase_receipt_relative_path": phase_path.relative_to(self.root).as_posix(),
            "phase_receipt_sha256": phase["phase_receipt_sha256"],
            "updated_at": self._clock(),
            "projection_is_authority": False,
        }
        projection = {
            **core,
            "projection_sha256": _sha256(_canonical_json_bytes(core)),
        }
        _replace_durable(
            phase_path.parent / "current.json",
            _canonical_json_bytes(projection),
        )

    def _write_transaction_phase(
        self,
        transaction_dir: Path,
        *,
        request: EffectGatewayRequest,
        grant_evidence: Mapping[str, object],
        phase: str,
        predecessor_phase: Mapping[str, object] | None,
        outcome: AdapterOutcome | None,
    ) -> dict[str, object]:
        path = transaction_dir / f"{phase}.json"
        predecessor_ref = (
            {
                "phase": predecessor_phase["phase"],
                "phase_receipt_sha256": predecessor_phase["phase_receipt_sha256"],
            }
            if predecessor_phase is not None
            else None
        )
        core: dict[str, object] = {
            "schema_version": TRANSACTION_PHASE_SCHEMA,
            "phase": phase,
            "request": request.to_dict(),
            "request_sha256": request.sha256,
            "owner_grant_evidence": dict(grant_evidence),
            "adapter_outcome": outcome.to_dict() if outcome is not None else None,
            "predecessor_phase": predecessor_ref,
            "created_at": self._clock(),
        }
        record = {
            **core,
            "phase_receipt_sha256": _sha256(_canonical_json_bytes(core)),
        }
        _write_durable_new(path, _canonical_json_bytes(record))
        self._write_transaction_projection(
            request=request,
            phase_path=path,
            phase=record,
        )
        return record

    def _load_transaction_phases(
        self,
        transaction_dir: Path,
        request: EffectGatewayRequest,
    ) -> list[tuple[Path, dict[str, object]]]:
        if not transaction_dir.exists():
            return []
        if not transaction_dir.is_dir():
            raise EffectGatewayError("TRANSACTION_LAYOUT_INVALID", str(transaction_dir))
        allowed_names = {
            "PREPARED.json",
            "EFFECT_APPLIED.json",
            "COMPLETED.json",
            "current.json",
        }
        extras = sorted(
            entry.name for entry in transaction_dir.iterdir() if entry.name not in allowed_names
        )
        if extras:
            raise EffectGatewayError(
                "TRANSACTION_LAYOUT_INVALID",
                f"unexpected transaction entries: {extras}",
            )
        result: list[tuple[Path, dict[str, object]]] = []
        previous: Mapping[str, object] | None = None
        missing_seen = False
        for phase_name in ("PREPARED", "EFFECT_APPLIED", "COMPLETED"):
            path = transaction_dir / f"{phase_name}.json"
            if not path.exists():
                missing_seen = True
                continue
            if missing_seen:
                raise EffectGatewayError("TRANSACTION_PHASE_GAP", str(path))
            phase = self._load_transaction_phase(path, expected_phase=phase_name)
            if (
                phase.get("request_sha256") != request.sha256
                or phase.get("request") != request.to_dict()
            ):
                raise EffectGatewayError("IDEMPOTENCY_KEY_CONFLICT", str(path))
            expected_predecessor = (
                {
                    "phase": previous["phase"],
                    "phase_receipt_sha256": previous["phase_receipt_sha256"],
                }
                if previous is not None
                else None
            )
            if phase.get("predecessor_phase") != expected_predecessor:
                raise EffectGatewayError("TRANSACTION_PHASE_CHAIN_MISMATCH", str(path))
            if (phase_name == "PREPARED") != (phase.get("adapter_outcome") is None):
                raise EffectGatewayError("TRANSACTION_PHASE_INVALID", str(path))
            if previous is not None and phase.get("owner_grant_evidence") != result[0][1].get(
                "owner_grant_evidence"
            ):
                raise EffectGatewayError("TRANSACTION_GRANT_CHAIN_MISMATCH", str(path))
            result.append((path, phase))
            previous = phase
        return result

    @staticmethod
    def _outcome_matches_mapping(
        outcome: AdapterOutcome,
        stored: Mapping[str, object],
    ) -> bool:
        readback = stored.get("readback")
        if not isinstance(readback, Mapping):
            return False
        stable_keys = (
            "generation_receipt_path",
            "generation_receipt_file_sha256",
            "artifact_path",
            "artifact_sha256",
        )
        return stored.get("effect_identity") == dict(outcome.effect_identity) and all(
            readback.get(key) == outcome.readback.get(key) for key in stable_keys
        )

    @classmethod
    def _outcome_matches_receipt(
        cls,
        outcome: AdapterOutcome,
        receipt: Mapping[str, object],
    ) -> bool:
        stored = receipt.get("adapter_outcome")
        return isinstance(stored, Mapping) and cls._outcome_matches_mapping(outcome, stored)

    def _complete_receipt(
        self,
        *,
        path: Path,
        request: EffectGatewayRequest,
        grant_evidence: Mapping[str, object],
        outcome: AdapterOutcome,
    ) -> dict[str, object]:
        core: dict[str, object] = {
            "schema_version": RECEIPT_SCHEMA,
            "request": request.to_dict(),
            "request_sha256": request.sha256,
            "owner_grant_evidence": dict(grant_evidence),
            "adapter_outcome": outcome.to_dict(),
            "effect_boundary": {
                "candidate_cognition_has_direct_effect_authority": False,
                "context_history_can_invoke_effect": False,
                "internal_controller_quota_context_writers_routed_here": False,
                "capital_adapter_installed": False,
                "publication_adapter_installed": False,
                "process_acl_boundary_proven": False,
            },
        }
        receipt = {**core, "receipt_sha256": _sha256(_canonical_json_bytes(core))}
        _write_durable_new(path, _canonical_json_bytes(receipt))
        return receipt

    def _invoke_with_live_grant(
        self,
        request: EffectGatewayRequest,
        grant: CurrentOwnerGrant,
    ) -> GatewayResult:
        adapter = self._require_adapter(request.adapter_kind)
        grant_evidence = self._consume_grant(request, grant)
        self.root.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self.transactions_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = self.receipts_dir / f"{request.request_id}.json"
        transaction_dir = self.transactions_dir / request.request_id
        with portalocker.Lock(self.root / ".effect-gateway.lock", mode="a+b", timeout=30):
            _verify_evidence_contract(request, self.policy)
            phases = self._load_transaction_phases(transaction_dir, request)
            transaction_was_completed = len(phases) == 3 and receipt_path.exists()
            if not phases:
                transaction_dir.mkdir(parents=True, exist_ok=False)
                prepared = self._write_transaction_phase(
                    transaction_dir,
                    request=request,
                    grant_evidence=grant_evidence,
                    phase="PREPARED",
                    predecessor_phase=None,
                    outcome=None,
                )
                phases = [(transaction_dir / "PREPARED.json", prepared)]
                self._fault("after_prepared")
            prepared_path, prepared = phases[0]
            selected_grant_evidence = prepared.get("owner_grant_evidence")
            if not isinstance(selected_grant_evidence, Mapping):
                raise EffectGatewayError("TRANSACTION_PHASE_INVALID", str(prepared_path))

            if len(phases) == 1:
                try:
                    outcome = adapter.readback(request)
                except EffectGatewayError as exc:
                    if exc.code != "EFFECT_NOT_APPLIED":
                        raise
                    outcome = adapter.apply(request, grant, prepared_path)
                self._fault("after_adapter_apply")
                effect_phase = self._write_transaction_phase(
                    transaction_dir,
                    request=request,
                    grant_evidence=selected_grant_evidence,
                    phase="EFFECT_APPLIED",
                    predecessor_phase=prepared,
                    outcome=outcome,
                )
                phases.append((transaction_dir / "EFFECT_APPLIED.json", effect_phase))
                self._fault("after_effect")
            else:
                effect_path, effect_phase = phases[1]
                stored_outcome = effect_phase.get("adapter_outcome")
                if not isinstance(stored_outcome, Mapping):
                    raise EffectGatewayError("TRANSACTION_PHASE_INVALID", str(effect_path))
                outcome = adapter.readback(request)
                if not self._outcome_matches_mapping(outcome, stored_outcome):
                    raise EffectGatewayError("EFFECT_READBACK_DRIFT", str(effect_path))
                if len(phases) == 3:
                    completed_outcome = phases[2][1].get("adapter_outcome")
                    if not isinstance(
                        completed_outcome, Mapping
                    ) or not self._outcome_matches_mapping(outcome, completed_outcome):
                        raise EffectGatewayError("EFFECT_READBACK_DRIFT", str(phases[2][0]))

            if receipt_path.exists():
                receipt = self._load_receipt(receipt_path)
                if (
                    receipt.get("request_sha256") != request.sha256
                    or receipt.get("request") != request.to_dict()
                ):
                    raise EffectGatewayError(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        f"request_id {request.request_id} is bound to different request bytes",
                    )
                if not self._outcome_matches_receipt(outcome, receipt):
                    raise EffectGatewayError("EFFECT_READBACK_DRIFT", str(receipt_path))
            else:
                if len(phases) == 3:
                    raise EffectGatewayError(
                        "COMPLETED_TRANSACTION_RECEIPT_MISSING", str(receipt_path)
                    )
                receipt = self._complete_receipt(
                    path=receipt_path,
                    request=request,
                    grant_evidence=selected_grant_evidence,
                    outcome=outcome,
                )
                self._fault("after_receipt")

            if len(phases) == 2:
                completed = self._write_transaction_phase(
                    transaction_dir,
                    request=request,
                    grant_evidence=selected_grant_evidence,
                    phase="COMPLETED",
                    predecessor_phase=phases[1][1],
                    outcome=outcome,
                )
                phases.append((transaction_dir / "COMPLETED.json", completed))
            elif len(phases) != 3:
                raise EffectGatewayError("TRANSACTION_PHASE_INVALID", str(transaction_dir))

            if self._load_receipt(receipt_path) != receipt:
                raise EffectGatewayError("RECEIPT_READBACK_FAILED", str(receipt_path))
            latest_path, latest_phase = phases[-1]
            self._write_transaction_projection(
                request=request,
                phase_path=latest_path,
                phase=latest_phase,
            )
            return GatewayResult(
                receipt=receipt,
                receipt_path=receipt_path,
                replayed=transaction_was_completed,
            )


def production_effect_gateway() -> EffectGateway:
    """Build the fixed canonical broker with no caller-mintable selection."""

    policy = EffectGatewayPolicy(
        gateway_root=DEFAULT_EFFECT_GATEWAY_RUNTIME,
        logical_root=DEFAULT_LOGICAL_ROOT_RUNTIME,
        allowed_source_roots=(DEFAULT_WORLD_COMPUTE_RUNTIME,),
        allowed_reality_roots=(DEFAULT_EFFECT_REALITY_ROOT,),
        allowed_blind_roots=(DEFAULT_EFFECT_BLIND_ROOT,),
        reality_labels=_LOGICAL_ROOT_REALITY_LABELS,
        blind_labels=_LOGICAL_ROOT_BLIND_LABELS,
    )
    store = LogicalRootStore(policy.logical_root)
    return EffectGateway(
        policy,
        adapters={LOGICAL_ROOT_ADOPTION_ADAPTER: logical_root_adoption_binding(store)},
        owner_boundary=_NoLiveProductionSelection(),
    )


def invoke_logical_root_adoption_as_current_owner(
    request: EffectGatewayRequest,
) -> GatewayResult:
    """Canonical live handler used by the formal CLI/action surface."""

    return production_effect_gateway().invoke_as_current_owner(request)


__all__ = [
    "AdapterBinding",
    "AdapterOutcome",
    "CurrentOwnerGrant",
    "DEFAULT_EFFECT_BLIND_ROOT",
    "DEFAULT_EFFECT_GATEWAY_RUNTIME",
    "DEFAULT_EFFECT_REALITY_ROOT",
    "DEFAULT_WORLD_COMPUTE_RUNTIME",
    "EffectGateway",
    "EffectGatewayError",
    "EffectGatewayPolicy",
    "EffectGatewayRequest",
    "GatewayResult",
    "HashBoundRef",
    "LOGICAL_ROOT_ADOPTION_ADAPTER",
    "LiveOwnerGrantBoundary",
    "OWNER_INVOCATION_SCHEMA",
    "RECEIPT_SCHEMA",
    "REQUEST_SCHEMA",
    "TRANSACTION_PHASE_SCHEMA",
    "TRANSACTION_PROJECTION_SCHEMA",
    "build_logical_root_adoption_request",
    "invoke_logical_root_adoption_as_current_owner",
    "logical_root_adoption_binding",
    "production_effect_gateway",
]
