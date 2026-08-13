"""Durable, append-only generations for the single logical XINAO root.

This module is intentionally not wired into the perpetual controller.  It is a
mechanical adoption surface for a root-main output that an experiment/effect
owner has already selected.  The store:

* verifies one completed per-run late-fusion commit and its hash-bound inputs;
* treats ``account_slot`` (A or C) as provenance, never as a root namespace;
* copies the selected root output and verification evidence into a local CAS;
* appends one atomically committed, predecessor-bound generation receipt; and
* reconstructs the sole current generation from those receipts alone.

It does not compare scientific content, choose between runs, write to a lineage
workspace, or write to a shared research repository.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_LOGICAL_ROOT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_logical_root")

GENERATION_RECEIPT_SCHEMA = "xinao.logical-root-generation-receipt.v1"
CURRENT_PROJECTION_SCHEMA = "xinao.logical-root-current-projection.v1"
FROZEN_WORLD_SEED_SCHEMA = "xinao.logical-root-frozen-world-seed.v1"

_RUN_V1 = "xinao.cleanroom-c.perpetual-run.v1"
_RUN_V2 = "xinao.cleanroom.perpetual-world-compute-run.v2"
_SCHEMA_FAMILIES = {
    _RUN_V1: {
        "packet": "xinao.cleanroom-c.late-fusion-packet.v1",
        "lineage": "xinao.cleanroom-c.perpetual-lineage-state.v1",
        "turn": "xinao.cleanroom-c.perpetual-turn-receipt.v1",
    },
    _RUN_V2: {
        "packet": "xinao.cleanroom.perpetual-world-compute-late-fusion-packet.v2",
        "lineage": "xinao.cleanroom.perpetual-world-compute-lineage-state.v2",
        "turn": "xinao.cleanroom.perpetual-world-compute-turn-receipt.v2",
    },
}
_DEEP_EVIDENCE_SCHEMA = "xinao.cleanroom.world-compute-deep-evidence-ref.v1"

_GENERATION_RE = re.compile(r"^generation-(?P<number>[0-9]{20})$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,191}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_HEAD_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_TURN_RE = re.compile(r"^turn-(?P<number>[0-9]{6})$")
_ATTEMPT_RE = re.compile(r"^attempt-(?P<number>[0-9]{2})$")


class LogicalRootError(RuntimeError):
    """Base class for typed, fail-closed logical-root errors."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class LogicalRootEvidenceError(LogicalRootError):
    """The proposed per-run output is absent, incomplete, or unverifiable."""


class LogicalRootConflict(LogicalRootError):
    """The caller's optimistic or idempotency identity conflicts with the store."""


class LogicalRootIntegrityError(LogicalRootError):
    """Committed store bytes do not reconstruct as one valid generation chain."""


@dataclass(frozen=True)
class RootIdentity:
    """Optimistic identity of one logical-root generation."""

    generation: int
    receipt_sha256: str | None
    artifact_sha256: str | None

    @classmethod
    def genesis(cls) -> RootIdentity:
        return cls(generation=0, receipt_sha256=None, artifact_sha256=None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RootIdentity:
        try:
            identity = cls(
                generation=int(value["generation"]),
                receipt_sha256=value.get("receipt_sha256"),
                artifact_sha256=value.get("artifact_sha256"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootConflict(
                "PREDECESSOR_IDENTITY_INVALID", "predecessor identity is malformed"
            ) from exc
        identity.validate(error_type=LogicalRootConflict)
        return identity

    def validate(self, *, error_type: type[LogicalRootError] = LogicalRootIntegrityError) -> None:
        if self.generation < 0:
            raise error_type("ROOT_IDENTITY_INVALID", "generation cannot be negative")
        if self.generation == 0:
            if self.receipt_sha256 is not None or self.artifact_sha256 is not None:
                raise error_type(
                    "ROOT_IDENTITY_INVALID", "genesis cannot carry receipt or artifact hashes"
                )
            return
        for name, value in (
            ("receipt_sha256", self.receipt_sha256),
            ("artifact_sha256", self.artifact_sha256),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise error_type("ROOT_IDENTITY_INVALID", f"{name} is not a lowercase SHA-256")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "generation": self.generation,
            "receipt_sha256": self.receipt_sha256,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True)
class LogicalRootSnapshot:
    """One reconstructed generation and its local durable references."""

    identity: RootIdentity
    receipt: Mapping[str, Any] | None
    receipt_path: Path | None
    artifact_path: Path | None

    @classmethod
    def genesis(cls) -> LogicalRootSnapshot:
        return cls(RootIdentity.genesis(), None, None, None)


@dataclass(frozen=True)
class AdoptionResult:
    """Result of an adoption or an exact idempotent replay."""

    adopted: LogicalRootSnapshot
    current: LogicalRootSnapshot
    replayed: bool


@dataclass(frozen=True)
class _VerifiedSource:
    artifact: bytes
    source: dict[str, Any]
    evidence_blobs: Mapping[str, bytes]
    evidence_paths: Mapping[str, Path]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _require_sha256(value: object, *, label: str, error_type: type[LogicalRootError]) -> str:
    normalized = str(value or "").lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise error_type("SHA256_INVALID", f"{label} is not a SHA-256")
    return normalized


def _require_identifier(value: object, *, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID_RE.fullmatch(text):
        raise LogicalRootConflict(
            "ADOPTION_REQUEST_INVALID", f"{label} must be a bounded non-path identifier"
        )
    return text


def _require_owner_label(value: object) -> str:
    text = str(value or "")
    if not text or len(text) > 256 or any(ord(character) < 32 for character in text):
        raise LogicalRootConflict(
            "ADOPTION_REQUEST_INVALID", "selected_by must be nonempty and contain no controls"
        )
    return text


def _read_stable(path: Path, *, error_type: type[LogicalRootError]) -> bytes:
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise error_type("EVIDENCE_NOT_REGULAR_FILE", str(path))
            raw = stream.read()
            after = os.fstat(stream.fileno())
    except FileNotFoundError as exc:
        raise error_type("EVIDENCE_FILE_MISSING", str(path)) from exc
    except OSError as exc:
        raise error_type("EVIDENCE_READ_FAILED", f"{path}: {exc}") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != after.st_size
    ):
        raise error_type("EVIDENCE_CHANGED_DURING_READ", str(path))
    return raw


def _read_json(path: Path, *, error_type: type[LogicalRootError]) -> tuple[dict[str, Any], bytes]:
    raw = _read_stable(path, error_type=error_type)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error_type("JSON_EVIDENCE_INVALID", str(path)) from exc
    if not isinstance(value, dict):
        raise error_type("JSON_EVIDENCE_INVALID", f"object required: {path}")
    return value, raw


def _resolve_existing_directory(path: Path, *, label: str) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise LogicalRootEvidenceError("EVIDENCE_DIRECTORY_MISSING", f"{label}: {path}") from exc
    if not resolved.is_dir():
        raise LogicalRootEvidenceError("EVIDENCE_DIRECTORY_MISSING", f"{label}: {path}")
    return resolved


def _same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(parent))) == os.path.commonpath(
            (str(parent), str(parent))
        )
    except ValueError:
        return False


def _parse_time(value: object, *, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise LogicalRootEvidenceError("EVIDENCE_TIMESTAMP_INVALID", label) from exc
    if parsed.tzinfo is None:
        raise LogicalRootEvidenceError("EVIDENCE_TIMESTAMP_INVALID", f"{label} is naive")
    return parsed


def _frozen_seed_file_is_regular_single_link(path: Path) -> bool:
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


def _validate_frozen_seed_inventory(seed_root: Path, expected_files: set[str]) -> None:
    observed_files: set[str] = set()
    observed_directories: set[str] = set()

    def visit(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise LogicalRootIntegrityError(
                "FROZEN_WORLD_SEED_INVENTORY_UNREADABLE", str(directory)
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(seed_root).as_posix()
            try:
                # CPython's Windows DirEntry.stat can report st_nlink=0 even
                # for an ordinary single-link NTFS file; Path.lstat returns
                # the file identity needed by this boundary check.
                observed = path.lstat()
            except OSError as exc:
                raise LogicalRootIntegrityError(
                    "FROZEN_WORLD_SEED_INVENTORY_UNREADABLE", str(path)
                ) from exc
            attributes = int(getattr(observed, "st_file_attributes", 0))
            reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
            if reparse_flag and attributes & reparse_flag:
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_INVENTORY_NONREGULAR", str(path))
            if stat.S_ISDIR(observed.st_mode):
                observed_directories.add(relative)
                visit(path)
            elif stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1:
                observed_files.add(relative)
            else:
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_INVENTORY_NONREGULAR", str(path))

    visit(seed_root)
    expected_directories: set[str] = set()
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent
    if observed_files != expected_files or observed_directories != expected_directories:
        raise LogicalRootIntegrityError(
            "FROZEN_WORLD_SEED_INVENTORY_MISMATCH",
            f"expected_files={sorted(expected_files)} observed_files={sorted(observed_files)} ",
        )


def validate_frozen_world_seed(root: Path | str) -> dict[str, Any]:
    """Validate only frozen bytes; never follow the production logical store."""

    seed_root = _resolve_existing_directory(Path(root), label="frozen world seed")
    manifest_path = seed_root / "manifest.json"
    if not _frozen_seed_file_is_regular_single_link(manifest_path):
        raise LogicalRootIntegrityError(
            "FROZEN_WORLD_SEED_INVENTORY_NONREGULAR", str(manifest_path)
        )
    manifest, raw = _read_json(manifest_path, error_type=LogicalRootIntegrityError)
    if raw != _canonical_json_bytes(manifest) or manifest.get("schema") != FROZEN_WORLD_SEED_SCHEMA:
        raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_MANIFEST_INVALID", str(manifest_path))
    seal = _require_sha256(
        manifest.get("manifest_sha256"),
        label="frozen world seed manifest",
        error_type=LogicalRootIntegrityError,
    )
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if _sha256(_canonical_json_bytes(unsigned)) != seal:
        raise LogicalRootIntegrityError(
            "FROZEN_WORLD_SEED_MANIFEST_HASH_MISMATCH", str(manifest_path)
        )
    if (
        manifest.get("working_world_is_revisable") is not True
        or manifest.get("truth_or_instruction") is not False
        or manifest.get("automatic_adoption_allowed") is not False
        or manifest.get("live_store_following") is not False
    ):
        raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_BOUNDARY_INVALID", str(manifest_path))
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_SOURCE_INVALID", str(manifest_path))
    try:
        identity = RootIdentity.from_mapping(source.get("identity", {}))
    except LogicalRootConflict as exc:
        raise LogicalRootIntegrityError(
            "FROZEN_WORLD_SEED_SOURCE_INVALID", str(manifest_path)
        ) from exc
    status = source.get("status")
    artifact_ref = manifest.get("root_world_artifact")
    receipt_ref = manifest.get("source_generation_receipt")
    evidence_copies = manifest.get("source_evidence")
    if not isinstance(evidence_copies, Mapping):
        raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_EVIDENCE_INVALID", str(manifest_path))
    if status == "genesis":
        if (
            identity != RootIdentity.genesis()
            or artifact_ref is not None
            or receipt_ref is not None
            or evidence_copies
        ):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_GENESIS_INVALID", str(manifest_path))
        if any(
            source.get(field) is not None
            for field in (
                "source_output_identity",
                "source_run_id",
                "source_account_slot",
                "artifact_sha256",
                "receipt_sha256",
            )
        ):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_GENESIS_INVALID", str(manifest_path))
        _validate_frozen_seed_inventory(seed_root, {"manifest.json"})
    elif status == "generation":
        if (
            identity.generation < 1
            or not isinstance(artifact_ref, Mapping)
            or not isinstance(receipt_ref, Mapping)
        ):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_SOURCE_INVALID", str(manifest_path))

        expected_files = {
            "manifest.json",
            "XINAO_ROOT_WORLD.txt",
            "source_generation_receipt.json",
        }
        for label, copied_raw in evidence_copies.items():
            if not isinstance(copied_raw, Mapping):
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_EVIDENCE_INVALID", str(label))
            relative = copied_raw.get("relative_path")
            if not isinstance(relative, str):
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_REF_INVALID", str(label))
            relative_path = Path(relative)
            if (
                relative_path.is_absolute()
                or relative_path.as_posix() != relative
                or ".." in relative_path.parts
                or (label == "root_last_message" and relative != "XINAO_ROOT_WORLD.txt")
                or (
                    label != "root_last_message" and relative_path.parts[:1] != ("source_evidence",)
                )
            ):
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_REF_INVALID", relative)
            expected_files.add(relative)
        _validate_frozen_seed_inventory(seed_root, expected_files)

        def validate_ref(reference: Mapping[str, Any], expected_name: str) -> Path:
            if reference.get("relative_path") != expected_name:
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_REF_INVALID", expected_name)
            path = seed_root / expected_name
            content = _read_stable(path, error_type=LogicalRootIntegrityError)
            digest = _require_sha256(
                reference.get("sha256"),
                label=f"frozen {expected_name}",
                error_type=LogicalRootIntegrityError,
            )
            if _sha256(content) != digest or len(content) != reference.get("bytes"):
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_REF_HASH_MISMATCH", str(path))
            return path

        artifact_path = validate_ref(artifact_ref, "XINAO_ROOT_WORLD.txt")
        receipt_path = validate_ref(receipt_ref, "source_generation_receipt.json")
        receipt, receipt_raw = _read_json(receipt_path, error_type=LogicalRootIntegrityError)
        if receipt_raw != _canonical_json_bytes(receipt):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_RECEIPT_INVALID", str(receipt_path))
        receipt_seal = _require_sha256(
            receipt.get("receipt_sha256"),
            label="frozen generation receipt",
            error_type=LogicalRootIntegrityError,
        )
        receipt_unsigned = dict(receipt)
        receipt_unsigned.pop("receipt_sha256", None)
        receipt_source = receipt.get("source")
        receipt_evidence = receipt.get("evidence_refs")
        if (
            not isinstance(receipt_source, Mapping)
            or _sha256(_canonical_json_bytes(receipt_unsigned)) != receipt_seal
        ):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_RECEIPT_INVALID", str(receipt_path))
        if not isinstance(receipt_evidence, Mapping) or set(evidence_copies) != set(
            receipt_evidence
        ):
            raise LogicalRootIntegrityError(
                "FROZEN_WORLD_SEED_EVIDENCE_INVALID", str(manifest_path)
            )
        for label, copied_raw in evidence_copies.items():
            original_raw = receipt_evidence[label]
            if not isinstance(copied_raw, Mapping) or not isinstance(original_raw, Mapping):
                raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_EVIDENCE_INVALID", str(label))
            relative = str(copied_raw.get("relative_path") or "")
            copied_path = seed_root / relative
            try:
                expected_evidence_root = (seed_root / "source_evidence").resolve()
                if (label == "root_last_message" and relative != "XINAO_ROOT_WORLD.txt") or (
                    label != "root_last_message"
                    and not copied_path.resolve().is_relative_to(expected_evidence_root)
                ):
                    raise LogicalRootIntegrityError(
                        "FROZEN_WORLD_SEED_REF_INVALID", str(copied_path)
                    )
            except (OSError, ValueError) as exc:
                raise LogicalRootIntegrityError(
                    "FROZEN_WORLD_SEED_REF_INVALID", str(copied_path)
                ) from exc
            copied_content = _read_stable(copied_path, error_type=LogicalRootIntegrityError)
            if (
                _sha256(copied_content) != copied_raw.get("sha256")
                or len(copied_content) != copied_raw.get("bytes")
                or copied_raw.get("sha256") != original_raw.get("sha256")
                or copied_raw.get("bytes") != original_raw.get("bytes")
            ):
                raise LogicalRootIntegrityError(
                    "FROZEN_WORLD_SEED_EVIDENCE_HASH_MISMATCH", str(label)
                )
        if (
            receipt_seal != identity.receipt_sha256
            or _sha256(_read_stable(artifact_path, error_type=LogicalRootIntegrityError))
            != identity.artifact_sha256
            or source.get("source_output_identity") != receipt_source.get("source_output_identity")
            or source.get("source_run_id") != receipt_source.get("run_id")
            or source.get("source_account_slot") != receipt_source.get("account_slot")
            or source.get("artifact_sha256") != artifact_ref.get("sha256")
            or source.get("receipt_sha256") != receipt_ref.get("sha256")
        ):
            raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_SOURCE_MISMATCH", str(manifest_path))
    else:
        raise LogicalRootIntegrityError("FROZEN_WORLD_SEED_SOURCE_INVALID", str(manifest_path))
    return {
        "root": str(seed_root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(raw),
        "status": status,
        "identity": identity.to_dict(),
        "source_output_identity": source.get("source_output_identity"),
        "artifact_path": str(seed_root / "XINAO_ROOT_WORLD.txt")
        if status == "generation"
        else None,
        "artifact_sha256": source.get("artifact_sha256"),
        "receipt_path": (
            str(seed_root / "source_generation_receipt.json") if status == "generation" else None
        ),
        "receipt_sha256": source.get("receipt_sha256"),
        "evidence_count": len(evidence_copies),
    }


def _write_durable_file(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    # Windows has no portable directory fsync.  Every payload file itself is
    # flushed before the atomic rename; POSIX additionally flushes directory
    # metadata so tests and non-Windows readers preserve the same contract.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class LogicalRootStore:
    """Append and reconstruct a single predecessor-linked logical root."""

    def __init__(
        self,
        root: Path | str = DEFAULT_LOGICAL_ROOT_RUNTIME,
        *,
        clock: Callable[[], str] | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root).absolute()
        self._clock = clock or (
            lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        )
        self._fault_injector = fault_injector

    @property
    def receipts_dir(self) -> Path:
        return self.root / "generation_receipts"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts" / "sha256"

    @property
    def staging_dir(self) -> Path:
        return self.root / ".staging"

    @property
    def current_projection_path(self) -> Path:
        return self.root / "current.json"

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _ensure_layout(self) -> None:
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def _cas_path(self, digest: str) -> Path:
        return self.artifacts_dir / digest[:2] / digest

    def _cas_ref(self, raw: bytes) -> dict[str, Any]:
        digest = _sha256(raw)
        path = self._cas_path(digest)
        return {
            "sha256": digest,
            "bytes": len(raw),
            "relative_path": path.relative_to(self.root).as_posix(),
        }

    def _install_cas_blob(self, raw: bytes) -> dict[str, Any]:
        reference = self._cas_ref(raw)
        destination = self.root / str(reference["relative_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = _read_stable(destination, error_type=LogicalRootIntegrityError)
            if existing != raw:
                raise LogicalRootIntegrityError(
                    "CAS_CONTENT_CONFLICT",
                    f"content-address path has different bytes: {destination}",
                )
            return reference
        temporary = self.staging_dir / f"cas-{reference['sha256']}-{uuid.uuid4().hex}.tmp"
        try:
            _write_durable_file(temporary, raw)
            if destination.exists():
                existing = _read_stable(destination, error_type=LogicalRootIntegrityError)
                if existing != raw:
                    raise LogicalRootIntegrityError(
                        "CAS_CONTENT_CONFLICT",
                        f"content-address path has different bytes: {destination}",
                    )
            else:
                os.rename(temporary, destination)
                _fsync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        persisted = _read_stable(destination, error_type=LogicalRootIntegrityError)
        if persisted != raw:
            raise LogicalRootIntegrityError("CAS_WRITE_READBACK_FAILED", str(destination))
        return reference

    def _validate_cas_ref(self, value: object, *, label: str) -> Path:
        if not isinstance(value, Mapping):
            raise LogicalRootIntegrityError("CAS_REF_INVALID", label)
        digest = _require_sha256(
            value.get("sha256"), label=f"{label}.sha256", error_type=LogicalRootIntegrityError
        )
        try:
            byte_count = int(value["bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootIntegrityError("CAS_REF_INVALID", f"{label}.bytes") from exc
        expected = self._cas_path(digest)
        expected_relative = expected.relative_to(self.root).as_posix()
        if value.get("relative_path") != expected_relative:
            raise LogicalRootIntegrityError("CAS_REF_PATH_MISMATCH", label)
        raw = _read_stable(expected, error_type=LogicalRootIntegrityError)
        if len(raw) != byte_count or _sha256(raw) != digest:
            raise LogicalRootIntegrityError("CAS_HASH_MISMATCH", str(expected))
        return expected

    def _validate_packet_entry(
        self,
        *,
        packet_dir: Path,
        entry: Mapping[str, Any],
        index: int,
        source_head: str,
        evidence_blobs: dict[str, bytes],
        evidence_paths: dict[str, Path],
        deep_mode: object,
    ) -> dict[str, Any]:
        lineage_id = str(entry.get("source_lineage_id") or "")
        if not lineage_id or lineage_id == "root-main":
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_ENTRY_INVALID", f"entry {index} has invalid source lineage"
            )
        try:
            turn_number = int(entry["source_turn_number"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_ENTRY_INVALID", f"entry {index} has invalid turn"
            ) from exc
        if turn_number < 1 or entry.get("source_workspace_head") != source_head:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_ENTRY_INVALID", f"entry {index} provenance mismatch"
            )
        candidate_name = str(entry.get("packet_path") or "")
        if Path(candidate_name).name != candidate_name or not candidate_name:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_ENTRY_INVALID", f"entry {index} candidate path is not local"
            )
        candidate_path = packet_dir / candidate_name
        candidate_raw = _read_stable(candidate_path, error_type=LogicalRootEvidenceError)
        candidate_sha = _require_sha256(
            entry.get("source_last_message_sha256"),
            label=f"packet entry {index} candidate",
            error_type=LogicalRootEvidenceError,
        )
        if _sha256(candidate_raw) != candidate_sha:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_CANDIDATE_HASH_MISMATCH", str(candidate_path)
            )
        candidate_label = f"packet_candidate_{index:04d}"
        evidence_blobs[candidate_label] = candidate_raw
        evidence_paths[candidate_label] = candidate_path
        result = {
            "index": index,
            "source_lineage_id": lineage_id,
            "source_turn_number": turn_number,
            "candidate_evidence_label": candidate_label,
        }
        if deep_mode == "thin_index_on_demand_v1":
            deep_name = str(entry.get("deep_evidence_path") or "")
            if Path(deep_name).name != deep_name or not deep_name:
                raise LogicalRootEvidenceError(
                    "FUSION_PACKET_DEEP_EVIDENCE_INVALID", f"entry {index} path"
                )
            deep_path = packet_dir / deep_name
            deep, deep_raw = _read_json(deep_path, error_type=LogicalRootEvidenceError)
            deep_sha = _require_sha256(
                entry.get("deep_evidence_sha256"),
                label=f"packet entry {index} deep evidence",
                error_type=LogicalRootEvidenceError,
            )
            if _sha256(deep_raw) != deep_sha:
                raise LogicalRootEvidenceError(
                    "FUSION_PACKET_DEEP_EVIDENCE_HASH_MISMATCH", str(deep_path)
                )
            if (
                deep.get("schema") != _DEEP_EVIDENCE_SCHEMA
                or deep.get("lineage_id") != lineage_id
                or int(deep.get("turn_number", -1)) != turn_number
                or deep.get("candidate_authority") is not False
                or deep.get("s_content_adjudication") is not False
            ):
                raise LogicalRootEvidenceError(
                    "FUSION_PACKET_DEEP_EVIDENCE_INVALID", str(deep_path)
                )
            deep_label = f"packet_deep_evidence_{index:04d}"
            evidence_blobs[deep_label] = deep_raw
            evidence_paths[deep_label] = deep_path
            result["deep_evidence_label"] = deep_label
        return result

    def _verify_source(self, source_run_dir: Path, *, account_slot: str) -> _VerifiedSource:
        run_dir = _resolve_existing_directory(source_run_dir, label="source run")
        if run_dir.parent.name != "runs":
            raise LogicalRootEvidenceError(
                "RUN_ISOLATION_INVALID", "source run must be one exact child of a runs directory"
            )
        config_path = run_dir / "run_config.json"
        config, config_raw = _read_json(config_path, error_type=LogicalRootEvidenceError)
        run_schema = str(config.get("schema") or "")
        family = _SCHEMA_FAMILIES.get(run_schema)
        if family is None:
            raise LogicalRootEvidenceError("RUN_SCHEMA_UNSUPPORTED", run_schema)
        run_id = str(config.get("run_id") or "")
        if not _SAFE_ID_RE.fullmatch(run_id) or run_dir.name != run_id:
            raise LogicalRootEvidenceError("RUN_IDENTITY_MISMATCH", str(run_dir))
        configured_run_dir = config.get("run_dir")
        if not configured_run_dir or not _same_path(configured_run_dir, run_dir):
            raise LogicalRootEvidenceError("RUN_IDENTITY_MISMATCH", "run_config.run_dir")
        observed_slot = str(config.get("account_slot") or "").upper()
        if observed_slot not in {"A", "C"} or observed_slot != account_slot:
            raise LogicalRootEvidenceError(
                "ACCOUNT_SLOT_MISMATCH", f"requested={account_slot} observed={observed_slot}"
            )
        source_head = str(config.get("source_head") or "").lower()
        if not _SOURCE_HEAD_RE.fullmatch(source_head):
            raise LogicalRootEvidenceError("SOURCE_HEAD_INVALID", source_head)
        root_spec = config.get("root_lineage")
        if not isinstance(root_spec, Mapping):
            raise LogicalRootEvidenceError("ROOT_LINEAGE_SPEC_MISSING", str(config_path))
        if (
            root_spec.get("lineage_id") != "root-main"
            or root_spec.get("role") != "late_fusion_root"
            or str(root_spec.get("head") or "").lower() != source_head
            or str(root_spec.get("remote_count")) != "0"
        ):
            raise LogicalRootEvidenceError("ROOT_LINEAGE_SPEC_INVALID", str(config_path))
        root_workspace = _resolve_existing_directory(
            Path(str(root_spec.get("workspace") or "")), label="root-main workspace"
        )
        if root_workspace.name != "root-main" or root_workspace.parent.name != run_id:
            raise LogicalRootEvidenceError(
                "RUN_ISOLATION_INVALID", "root-main workspace is not isolated by run identity"
            )
        if _is_within(root_workspace, self.root) or _is_within(self.root, root_workspace):
            raise LogicalRootEvidenceError(
                "STORE_SOURCE_OVERLAP", "logical store and root-main workspace must be disjoint"
            )

        fusion_path = run_dir / "lineages" / "root-main" / "fusion_state.json"
        fusion, fusion_raw = _read_json(fusion_path, error_type=LogicalRootEvidenceError)
        try:
            wave_number = int(fusion["waves_completed"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootEvidenceError("FUSION_STATE_INVALID", str(fusion_path)) from exc
        if (
            fusion.get("schema") != family["packet"]
            or fusion.get("run_id") != run_id
            or wave_number < 1
        ):
            raise LogicalRootEvidenceError("FUSION_NOT_COMMITTED", str(fusion_path))
        if fusion.get("pending_packet") is not None:
            raise LogicalRootEvidenceError(
                "FUSION_COMMIT_AMBIGUOUS",
                "a pending packet exists; the prior committed root output is not guessed",
            )
        packet_value = fusion.get("last_packet")
        if not packet_value:
            raise LogicalRootEvidenceError("FUSION_NOT_COMMITTED", "last_packet is absent")
        packet_dir = _resolve_existing_directory(Path(str(packet_value)), label="fusion packet")
        expected_packet_dir = (
            root_workspace / "S_CONTROL_INPUTS" / f"wave-{wave_number:06d}"
        ).resolve()
        if not _same_path(packet_dir, expected_packet_dir):
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_IDENTITY_MISMATCH", "last_packet is outside the isolated root"
            )
        manifest_path = packet_dir / "PACKET_MANIFEST.json"
        manifest, manifest_raw = _read_json(manifest_path, error_type=LogicalRootEvidenceError)
        manifest_sha = _sha256(manifest_raw)
        expected_manifest_sha = _require_sha256(
            fusion.get("last_packet_manifest_sha256"),
            label="fusion last packet manifest",
            error_type=LogicalRootEvidenceError,
        )
        if manifest_sha != expected_manifest_sha:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_MANIFEST_HASH_MISMATCH", str(manifest_path)
            )
        if (
            manifest.get("schema") != family["packet"]
            or manifest.get("run_id") != run_id
            or int(manifest.get("wave_number", -1)) != wave_number
            or str(manifest.get("source_head") or "").lower() != source_head
            or manifest.get("candidate_authority") is not False
            or manifest.get("s_content_adjudication") is not False
        ):
            raise LogicalRootEvidenceError("FUSION_PACKET_IDENTITY_MISMATCH", str(manifest_path))
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise LogicalRootEvidenceError("FUSION_PACKET_ENTRIES_MISSING", str(manifest_path))
        deep_mode = manifest.get("deep_evidence_mode")
        if deep_mode not in {None, "thin_index_on_demand_v1"}:
            raise LogicalRootEvidenceError(
                "FUSION_PACKET_DEEP_EVIDENCE_MODE_INVALID", str(deep_mode)
            )
        evidence_blobs = {
            "run_config": config_raw,
            "fusion_state": fusion_raw,
            "packet_manifest": manifest_raw,
        }
        evidence_paths = {
            "run_config": config_path,
            "fusion_state": fusion_path,
            "packet_manifest": manifest_path,
        }
        packet_entries: list[dict[str, Any]] = []
        seen_lineages: set[str] = set()
        for index, raw_entry in enumerate(entries, 1):
            if not isinstance(raw_entry, Mapping):
                raise LogicalRootEvidenceError(
                    "FUSION_PACKET_ENTRY_INVALID", f"entry {index} is not an object"
                )
            entry = self._validate_packet_entry(
                packet_dir=packet_dir,
                entry=raw_entry,
                index=index,
                source_head=source_head,
                evidence_blobs=evidence_blobs,
                evidence_paths=evidence_paths,
                deep_mode=deep_mode,
            )
            if entry["source_lineage_id"] in seen_lineages:
                raise LogicalRootEvidenceError(
                    "FUSION_PACKET_ENTRY_INVALID", "duplicate source lineage"
                )
            seen_lineages.add(entry["source_lineage_id"])
            packet_entries.append(entry)

        root_state_path = run_dir / "lineages" / "root-main" / "state.json"
        root_state, root_state_raw = _read_json(
            root_state_path, error_type=LogicalRootEvidenceError
        )
        try:
            root_turn_number = int(root_state["turns_completed"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootEvidenceError("ROOT_STATE_INVALID", str(root_state_path)) from exc
        if (
            root_state.get("schema") != family["lineage"]
            or root_state.get("run_id") != run_id
            or root_state.get("lineage_id") != "root-main"
            or root_state.get("role") != "late_fusion_root"
            or str(root_state.get("source_head") or "").lower() != source_head
            or not _same_path(str(root_state.get("workspace") or ""), root_workspace)
            or root_turn_number < 1
            or root_state.get("lifecycle_state") in {None, "CONTINUE"}
        ):
            raise LogicalRootEvidenceError("ROOT_STATE_INVALID", str(root_state_path))
        turn_dir = run_dir / "lineages" / "root-main" / "turns" / f"turn-{root_turn_number:06d}"
        last_completed = root_state.get("last_completed_turn_dir")
        if not last_completed or not _same_path(str(last_completed), turn_dir):
            raise LogicalRootEvidenceError(
                "ROOT_COMMITTED_TURN_IDENTITY_MISMATCH", str(root_state_path)
            )
        commit_time = _parse_time(fusion.get("updated_at"), label="fusion_state.updated_at")
        attempts = sorted(
            (
                path
                for path in turn_dir.glob("attempt-*")
                if path.is_dir() and _ATTEMPT_RE.fullmatch(path.name)
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        selected_attempt: tuple[Path, dict[str, Any], bytes, bytes] | None = None
        for attempt_dir in attempts:
            receipt_path = attempt_dir / "receipt.json"
            if not receipt_path.is_file():
                continue
            turn_receipt, turn_receipt_raw = _read_json(
                receipt_path, error_type=LogicalRootEvidenceError
            )
            if (
                turn_receipt.get("schema") != family["turn"]
                or turn_receipt.get("run_id") != run_id
                or turn_receipt.get("lineage_id") != "root-main"
                or turn_receipt.get("role") != "late_fusion_root"
                or int(turn_receipt.get("turn_number", -1)) != root_turn_number
                or int(turn_receipt.get("attempt_number", -1))
                != int(_ATTEMPT_RE.fullmatch(attempt_dir.name).group("number"))
                or turn_receipt.get("error_class") is not None
                or turn_receipt.get("turn_status") != "turn.completed"
                or turn_receipt.get("lifecycle_state") in {None, "CONTINUE"}
            ):
                continue
            normal_success = (
                turn_receipt.get("process_exit_code_observed") is not False
                and turn_receipt.get("exit_code") == 0
            )
            recovered_success = (
                turn_receipt.get("recovered_from_incomplete_attempt") is True
                and turn_receipt.get("process_exit_code_observed") is False
                and turn_receipt.get("exit_code") is None
                and turn_receipt.get("inferred_process_success") is True
                and turn_receipt.get("completion_basis")
                == "RECOVERED_TURN_COMPLETED_EVENT_AND_LIFECYCLE"
            )
            if not normal_success and not recovered_success:
                continue
            if (
                _parse_time(turn_receipt.get("ended_at"), label="turn receipt ended_at")
                > commit_time
            ):
                continue
            message_path = attempt_dir / "last_message.txt"
            message_raw = _read_stable(message_path, error_type=LogicalRootEvidenceError)
            message_sha = _require_sha256(
                turn_receipt.get("last_message_sha256"),
                label="root-main last_message",
                error_type=LogicalRootEvidenceError,
            )
            if _sha256(message_raw) != message_sha:
                raise LogicalRootEvidenceError("ROOT_OUTPUT_HASH_MISMATCH", str(message_path))
            selected_attempt = (attempt_dir, turn_receipt, turn_receipt_raw, message_raw)
            break
        if selected_attempt is None:
            raise LogicalRootEvidenceError("ROOT_COMMITTED_OUTPUT_MISSING", str(turn_dir))
        attempt_dir, turn_receipt, turn_receipt_raw, message_raw = selected_attempt
        root_receipt_path = attempt_dir / "receipt.json"
        root_message_path = attempt_dir / "last_message.txt"
        evidence_blobs.update(
            {
                "root_lineage_state": root_state_raw,
                "root_turn_receipt": turn_receipt_raw,
                "root_last_message": message_raw,
            }
        )
        evidence_paths.update(
            {
                "root_lineage_state": root_state_path,
                "root_turn_receipt": root_receipt_path,
                "root_last_message": root_message_path,
            }
        )

        # A single coherent evidence snapshot is required.  Advancing controller
        # state during this read is a retryable evidence conflict, not permission
        # to combine bytes from two waves.
        for label, path in evidence_paths.items():
            if _read_stable(path, error_type=LogicalRootEvidenceError) != evidence_blobs[label]:
                raise LogicalRootEvidenceError("EVIDENCE_CHANGED_DURING_VERIFICATION", str(path))

        root_receipt_sha = _sha256(turn_receipt_raw)
        root_output_sha = _sha256(message_raw)
        source_identity_core = {
            "run_id": run_id,
            "account_slot": observed_slot,
            "fusion_wave_number": wave_number,
            "fusion_packet_manifest_sha256": manifest_sha,
            "root_turn_number": root_turn_number,
            "root_attempt_number": int(turn_receipt["attempt_number"]),
            "root_turn_receipt_sha256": root_receipt_sha,
            "root_output_sha256": root_output_sha,
        }
        source_output_identity = _sha256(_canonical_json_bytes(source_identity_core))
        source = {
            **source_identity_core,
            "source_output_identity": source_output_identity,
            "run_schema": run_schema,
            "source_head": source_head,
            "source_run_dir": str(run_dir),
            "root_workspace": str(root_workspace),
            "fusion_packet_dir": str(packet_dir),
            "packet_entries": packet_entries,
            "evidence_source_paths": {
                label: str(path) for label, path in sorted(evidence_paths.items())
            },
        }
        return _VerifiedSource(
            artifact=message_raw,
            source=source,
            evidence_blobs=evidence_blobs,
            evidence_paths=evidence_paths,
        )

    def _receipt_snapshot(
        self, generation_dir: Path, expected_generation: int
    ) -> LogicalRootSnapshot:
        entries = list(generation_dir.iterdir())
        if len(entries) != 1 or not entries[0].is_file() or entries[0].suffix != ".json":
            raise LogicalRootIntegrityError(
                "GENERATION_RECEIPT_LAYOUT_INVALID", str(generation_dir)
            )
        receipt_path = entries[0]
        receipt, raw = _read_json(receipt_path, error_type=LogicalRootIntegrityError)
        if raw != _canonical_json_bytes(receipt):
            raise LogicalRootIntegrityError("GENERATION_RECEIPT_NOT_CANONICAL", str(receipt_path))
        if receipt.get("schema") != GENERATION_RECEIPT_SCHEMA:
            raise LogicalRootIntegrityError("GENERATION_RECEIPT_SCHEMA_INVALID", str(receipt_path))
        try:
            generation = int(receipt["generation"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LogicalRootIntegrityError(
                "GENERATION_RECEIPT_INVALID", str(receipt_path)
            ) from exc
        if generation != expected_generation:
            raise LogicalRootIntegrityError("GENERATION_NUMBER_MISMATCH", str(receipt_path))
        seal = _require_sha256(
            receipt.get("receipt_sha256"),
            label="generation receipt",
            error_type=LogicalRootIntegrityError,
        )
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if _sha256(_canonical_json_bytes(unsigned)) != seal or receipt_path.name != f"{seal}.json":
            raise LogicalRootIntegrityError("GENERATION_RECEIPT_HASH_MISMATCH", str(receipt_path))
        request = receipt.get("request")
        if not isinstance(request, Mapping):
            raise LogicalRootIntegrityError("GENERATION_RECEIPT_INVALID", "request")
        request_sha = _require_sha256(
            receipt.get("request_sha256"),
            label="request_sha256",
            error_type=LogicalRootIntegrityError,
        )
        if _sha256(_canonical_json_bytes(dict(request))) != request_sha:
            raise LogicalRootIntegrityError("GENERATION_REQUEST_HASH_MISMATCH", str(receipt_path))
        if (
            receipt.get("account_slot_is_provenance_only") is not True
            or receipt.get("store_scientific_adjudication") is not False
            or receipt.get("shared_repository_writes") is not False
        ):
            raise LogicalRootIntegrityError("GENERATION_BOUNDARY_INVALID", str(receipt_path))
        source = receipt.get("source")
        if not isinstance(source, Mapping) or source.get("account_slot") not in {"A", "C"}:
            raise LogicalRootIntegrityError("GENERATION_SOURCE_INVALID", str(receipt_path))
        source_identity_core = {
            key: source.get(key)
            for key in (
                "run_id",
                "account_slot",
                "fusion_wave_number",
                "fusion_packet_manifest_sha256",
                "root_turn_number",
                "root_attempt_number",
                "root_turn_receipt_sha256",
                "root_output_sha256",
            )
        }
        if _sha256(_canonical_json_bytes(source_identity_core)) != source.get(
            "source_output_identity"
        ):
            raise LogicalRootIntegrityError(
                "GENERATION_SOURCE_IDENTITY_MISMATCH", str(receipt_path)
            )
        evidence_refs = receipt.get("evidence_refs")
        if not isinstance(evidence_refs, Mapping) or "root_last_message" not in evidence_refs:
            raise LogicalRootIntegrityError("GENERATION_EVIDENCE_REFS_INVALID", str(receipt_path))
        for label, reference in evidence_refs.items():
            self._validate_cas_ref(reference, label=f"evidence_refs.{label}")
        artifact_ref = receipt.get("root_artifact")
        artifact_path = self._validate_cas_ref(artifact_ref, label="root_artifact")
        if dict(artifact_ref) != dict(evidence_refs["root_last_message"]):
            raise LogicalRootIntegrityError(
                "ROOT_ARTIFACT_EVIDENCE_REF_MISMATCH", str(receipt_path)
            )
        artifact_sha = _require_sha256(
            artifact_ref.get("sha256"),
            label="root_artifact.sha256",
            error_type=LogicalRootIntegrityError,
        )
        if source.get("root_output_sha256") != artifact_sha:
            raise LogicalRootIntegrityError("ROOT_ARTIFACT_SOURCE_MISMATCH", str(receipt_path))
        identity = RootIdentity(generation, seal, artifact_sha)
        identity.validate()
        return LogicalRootSnapshot(identity, receipt, receipt_path, artifact_path)

    def _load_chain_unlocked(self) -> list[LogicalRootSnapshot]:
        if not self.receipts_dir.exists():
            return []
        generation_dirs: list[tuple[int, Path]] = []
        for entry in self.receipts_dir.iterdir():
            match = _GENERATION_RE.fullmatch(entry.name)
            if match is None or not entry.is_dir():
                raise LogicalRootIntegrityError("GENERATION_RECEIPT_LAYOUT_INVALID", str(entry))
            generation_dirs.append((int(match.group("number")), entry))
        generation_dirs.sort()
        chain: list[LogicalRootSnapshot] = []
        predecessor = RootIdentity.genesis()
        seen_adoptions: set[str] = set()
        seen_outputs: set[str] = set()
        for expected, (observed, generation_dir) in enumerate(generation_dirs, 1):
            if observed != expected:
                raise LogicalRootIntegrityError(
                    "GENERATION_SEQUENCE_GAP", f"expected {expected}, observed {observed}"
                )
            snapshot = self._receipt_snapshot(generation_dir, expected)
            receipt = snapshot.receipt
            assert receipt is not None
            predecessor_value = receipt.get("predecessor")
            if not isinstance(predecessor_value, Mapping):
                raise LogicalRootIntegrityError(
                    "GENERATION_PREDECESSOR_INVALID", str(snapshot.receipt_path)
                )
            try:
                observed_predecessor = RootIdentity.from_mapping(predecessor_value)
            except LogicalRootConflict as exc:
                raise LogicalRootIntegrityError(
                    "GENERATION_PREDECESSOR_INVALID", str(snapshot.receipt_path)
                ) from exc
            if observed_predecessor != predecessor:
                raise LogicalRootIntegrityError(
                    "GENERATION_PREDECESSOR_MISMATCH", str(snapshot.receipt_path)
                )
            adoption_id = str(receipt["request"].get("adoption_id") or "")
            output_id = str(receipt["source"].get("source_output_identity") or "")
            if adoption_id in seen_adoptions or output_id in seen_outputs:
                raise LogicalRootIntegrityError(
                    "GENERATION_DUPLICATE_IDENTITY", str(snapshot.receipt_path)
                )
            seen_adoptions.add(adoption_id)
            seen_outputs.add(output_id)
            chain.append(snapshot)
            predecessor = snapshot.identity
        return chain

    def reconstruct_current(self, *, repair_projection: bool = False) -> LogicalRootSnapshot:
        """Derive the current root only from committed receipts and CAS bytes."""

        if repair_projection:
            self._ensure_layout()
            with _exclusive_file_lock(self.root / ".logical-root.lock"):
                chain = self._load_chain_unlocked()
                current = chain[-1] if chain else LogicalRootSnapshot.genesis()
                self._write_projection(current)
                return current
        chain = self._load_chain_unlocked()
        return chain[-1] if chain else LogicalRootSnapshot.genesis()

    def read_current_artifact(self) -> bytes | None:
        current = self.reconstruct_current()
        if current.artifact_path is None:
            return None
        return _read_stable(current.artifact_path, error_type=LogicalRootIntegrityError)

    def freeze_current_world_seed(self, destination: Path | str) -> dict[str, Any]:
        """Freeze exactly one current ``Omega(g)`` for a future run.

        The returned seed is a copied, self-verifying input.  It is not a live
        pointer, authority, scientific truth, or instruction.  Genesis is
        explicit and carries no invented artifact.  Once frozen, recovery can
        validate the destination without consulting this store again.
        """

        target = Path(destination).absolute()
        if target.exists():
            raise LogicalRootConflict("FROZEN_WORLD_SEED_EXISTS", str(target))
        current = self.reconstruct_current()
        target.mkdir(parents=True)
        try:
            if current.identity.generation == 0:
                source = {
                    "status": "genesis",
                    "identity": current.identity.to_dict(),
                    "source_output_identity": None,
                    "source_run_id": None,
                    "source_account_slot": None,
                    "artifact_sha256": None,
                    "receipt_sha256": None,
                }
                artifact_ref = None
                receipt_ref = None
            else:
                assert current.receipt is not None
                assert current.receipt_path is not None
                assert current.artifact_path is not None
                receipt_raw = _read_stable(
                    current.receipt_path, error_type=LogicalRootIntegrityError
                )
                artifact_raw = _read_stable(
                    current.artifact_path, error_type=LogicalRootIntegrityError
                )
                receipt_path = target / "source_generation_receipt.json"
                artifact_path = target / "XINAO_ROOT_WORLD.txt"
                _write_durable_file(receipt_path, receipt_raw)
                _write_durable_file(artifact_path, artifact_raw)
                artifact_sha = _sha256(artifact_raw)
                receipt_file_sha = _sha256(receipt_raw)
                if (
                    artifact_sha != current.identity.artifact_sha256
                    or str(current.receipt.get("receipt_sha256") or "")
                    != current.identity.receipt_sha256
                ):
                    raise LogicalRootIntegrityError(
                        "FROZEN_WORLD_SEED_SOURCE_DRIFT", str(current.receipt_path)
                    )
                source_record = current.receipt["source"]
                source = {
                    "status": "generation",
                    "identity": current.identity.to_dict(),
                    "source_output_identity": source_record["source_output_identity"],
                    "source_run_id": source_record["run_id"],
                    "source_account_slot": source_record["account_slot"],
                    "artifact_sha256": artifact_sha,
                    "receipt_sha256": receipt_file_sha,
                }
                artifact_ref = {
                    "relative_path": artifact_path.relative_to(target).as_posix(),
                    "bytes": len(artifact_raw),
                    "sha256": artifact_sha,
                }
                receipt_ref = {
                    "relative_path": receipt_path.relative_to(target).as_posix(),
                    "bytes": len(receipt_raw),
                    "sha256": receipt_file_sha,
                }
                evidence_copies: dict[str, dict[str, Any]] = {}
                evidence_refs = current.receipt.get("evidence_refs")
                if not isinstance(evidence_refs, Mapping):
                    raise LogicalRootIntegrityError(
                        "FROZEN_WORLD_SEED_SOURCE_DRIFT", "generation evidence refs are absent"
                    )
                for index, (label, reference) in enumerate(sorted(evidence_refs.items()), start=1):
                    if not isinstance(reference, Mapping):
                        raise LogicalRootIntegrityError(
                            "FROZEN_WORLD_SEED_SOURCE_DRIFT", f"evidence ref: {label}"
                        )
                    evidence_raw = _read_stable(
                        self.root / str(reference.get("relative_path") or ""),
                        error_type=LogicalRootIntegrityError,
                    )
                    evidence_sha = _sha256(evidence_raw)
                    if evidence_sha != reference.get("sha256") or len(
                        evidence_raw
                    ) != reference.get("bytes"):
                        raise LogicalRootIntegrityError(
                            "FROZEN_WORLD_SEED_SOURCE_DRIFT", f"evidence ref: {label}"
                        )
                    if label == "root_last_message":
                        copy_path = artifact_path
                    else:
                        copy_path = target / "source_evidence" / f"{index:04d}.blob"
                        _write_durable_file(copy_path, evidence_raw)
                    evidence_copies[str(label)] = {
                        "relative_path": copy_path.relative_to(target).as_posix(),
                        "bytes": len(evidence_raw),
                        "sha256": evidence_sha,
                    }
            if current.identity.generation == 0:
                evidence_copies = {}
            core = {
                "schema": FROZEN_WORLD_SEED_SCHEMA,
                "frozen_from_logical_root": str(self.root),
                "source": source,
                "root_world_artifact": artifact_ref,
                "source_generation_receipt": receipt_ref,
                "source_evidence": evidence_copies,
                "working_world_is_revisable": True,
                "truth_or_instruction": False,
                "automatic_adoption_allowed": False,
                "live_store_following": False,
            }
            manifest = {**core, "manifest_sha256": _sha256(_canonical_json_bytes(core))}
            manifest_path = target / "manifest.json"
            _write_durable_file(manifest_path, _canonical_json_bytes(manifest))
            _fsync_directory(target)
            return validate_frozen_world_seed(target)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def _write_projection(self, snapshot: LogicalRootSnapshot) -> None:
        core = {
            "schema": CURRENT_PROJECTION_SCHEMA,
            "derived_from_append_only_receipts": True,
            "current": snapshot.identity.to_dict(),
            "receipt_relative_path": (
                snapshot.receipt_path.relative_to(self.root).as_posix()
                if snapshot.receipt_path is not None
                else None
            ),
            "artifact_relative_path": (
                snapshot.artifact_path.relative_to(self.root).as_posix()
                if snapshot.artifact_path is not None
                else None
            ),
        }
        projection = {**core, "projection_sha256": _sha256(_canonical_json_bytes(core))}
        raw = _canonical_json_bytes(projection)
        temporary = self.root / f".current.{uuid.uuid4().hex}.tmp"
        try:
            _write_durable_file(temporary, raw)
            os.replace(temporary, self.current_projection_path)
            _fsync_directory(self.root)
        finally:
            temporary.unlink(missing_ok=True)

    def _commit_receipt(self, core: Mapping[str, Any], generation: int) -> LogicalRootSnapshot:
        unsigned = dict(core)
        seal = _sha256(_canonical_json_bytes(unsigned))
        receipt = {**unsigned, "receipt_sha256": seal}
        receipt_raw = _canonical_json_bytes(receipt)
        final_dir = self.receipts_dir / f"generation-{generation:020d}"
        if final_dir.exists():
            raise LogicalRootConflict("GENERATION_ALREADY_EXISTS", str(final_dir))
        staging = self.staging_dir / f"generation-{generation:020d}-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            _write_durable_file(staging / f"{seal}.json", receipt_raw)
            _fsync_directory(staging)
            self._fault("before_receipt_commit")
            os.rename(staging, final_dir)
            _fsync_directory(self.receipts_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self._fault("after_receipt_commit")
        return self._receipt_snapshot(final_dir, generation)

    def adopt(
        self,
        *,
        source_run_dir: Path | str,
        account_slot: str,
        expected_predecessor: RootIdentity | Mapping[str, Any],
        adoption_id: str,
        selection_ref: str,
        selected_by: str,
    ) -> AdoptionResult:
        """Append one owner-selected, already-committed root-main output.

        ``expected_predecessor`` is an optimistic CAS identity.  Exact replay of
        the same ``adoption_id`` and request is idempotent even after later
        generations; reuse with different request bytes fails closed.
        """

        slot = str(account_slot or "").upper()
        if slot not in {"A", "C"}:
            raise LogicalRootConflict(
                "ADOPTION_REQUEST_INVALID", "account_slot must be exactly A or C"
            )
        if isinstance(expected_predecessor, RootIdentity):
            predecessor = expected_predecessor
            predecessor.validate(error_type=LogicalRootConflict)
        elif isinstance(expected_predecessor, Mapping):
            predecessor = RootIdentity.from_mapping(expected_predecessor)
        else:
            raise LogicalRootConflict(
                "PREDECESSOR_IDENTITY_INVALID", "RootIdentity or mapping required"
            )
        normalized_run = Path(source_run_dir).absolute()
        request = {
            "adoption_id": _require_identifier(adoption_id, label="adoption_id"),
            "selection_ref": _require_identifier(selection_ref, label="selection_ref"),
            "selected_by": _require_owner_label(selected_by),
            "source_run_dir": str(normalized_run),
            "account_slot": slot,
            "expected_predecessor": predecessor.to_dict(),
        }
        request_sha = _sha256(_canonical_json_bytes(request))
        self._ensure_layout()
        with _exclusive_file_lock(self.root / ".logical-root.lock"):
            chain = self._load_chain_unlocked()
            current = chain[-1] if chain else LogicalRootSnapshot.genesis()
            for snapshot in chain:
                receipt = snapshot.receipt
                assert receipt is not None
                if receipt["request"].get("adoption_id") != request["adoption_id"]:
                    continue
                if (
                    receipt.get("request_sha256") != request_sha
                    or dict(receipt["request"]) != request
                ):
                    raise LogicalRootConflict(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        f"adoption_id {request['adoption_id']} is bound to different request bytes",
                    )
                self._write_projection(current)
                return AdoptionResult(snapshot, current, True)
            if predecessor != current.identity:
                raise LogicalRootConflict(
                    "STALE_PREDECESSOR",
                    f"expected {predecessor.to_dict()} current {current.identity.to_dict()}",
                )

            verified = self._verify_source(normalized_run, account_slot=slot)
            for snapshot in chain:
                assert snapshot.receipt is not None
                if (
                    snapshot.receipt["source"].get("source_output_identity")
                    == verified.source["source_output_identity"]
                ):
                    raise LogicalRootConflict(
                        "SOURCE_OUTPUT_ALREADY_ADOPTED",
                        str(verified.source["source_output_identity"]),
                    )
            evidence_refs = {
                label: self._install_cas_blob(raw)
                for label, raw in sorted(verified.evidence_blobs.items())
            }
            self._fault("after_cas_persisted")
            generation = current.identity.generation + 1
            committed_at = self._clock()
            _parse_time(committed_at, label="logical root committed_at")
            receipt_core = {
                "schema": GENERATION_RECEIPT_SCHEMA,
                "generation": generation,
                "committed_at": committed_at,
                "predecessor": current.identity.to_dict(),
                "request": request,
                "request_sha256": request_sha,
                "source": verified.source,
                "root_artifact": evidence_refs["root_last_message"],
                "evidence_refs": evidence_refs,
                "account_slot_is_provenance_only": True,
                "store_scientific_adjudication": False,
                "shared_repository_writes": False,
            }
            adopted = self._commit_receipt(receipt_core, generation)
            rebuilt = self._load_chain_unlocked()
            reconstructed_current = rebuilt[-1]
            if reconstructed_current.identity != adopted.identity:
                raise LogicalRootIntegrityError(
                    "POST_COMMIT_RECONSTRUCTION_MISMATCH", str(adopted.receipt_path)
                )
            self._write_projection(reconstructed_current)
            return AdoptionResult(adopted, reconstructed_current, False)


__all__ = [
    "AdoptionResult",
    "CURRENT_PROJECTION_SCHEMA",
    "DEFAULT_LOGICAL_ROOT_RUNTIME",
    "FROZEN_WORLD_SEED_SCHEMA",
    "GENERATION_RECEIPT_SCHEMA",
    "LogicalRootConflict",
    "LogicalRootError",
    "LogicalRootEvidenceError",
    "LogicalRootIntegrityError",
    "LogicalRootSnapshot",
    "LogicalRootStore",
    "RootIdentity",
    "validate_frozen_world_seed",
]
