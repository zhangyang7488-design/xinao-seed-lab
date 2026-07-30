#!/usr/bin/env python3
"""CAS-publish an append-only science revision without rewriting ParentScopeSwitch.

The science active-parent projection is non-authoritative, but it is the strict
runtime consumer binding.  This publisher therefore keeps a durable marker and
journal while replacing the active-parent source, projection, archive manifest,
and transition pointer.  Tool-glue is published by its own transaction first;
the v1.10 path consumes only its exact live postimage pin and never implements a
second tool-glue publication engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import portalocker
from xinao.science.active_parent import (
    SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    load_science_active_parent,
    validate_science_archive_publication_binding,
    validate_science_revision_candidate_binding,
    validate_science_transition_active_parent_binding,
)

TRANSACTION_SCHEMA = "xinao.science_revision_transaction.v1"
RESULT_SCHEMA = "xinao.science_revision_publication_result.v2"
V110_VERSION_MARKER = "版本：正式融合稿 v1.10"
DEFAULT_TOOL_GLUE_AUTHORITY_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt"
)
DEFAULT_TOOL_GLUE_VERSION = "v3.4"
DEFAULT_TOOL_GLUE_V34_SHA256 = (
    "eb6677d9cf87d152b91b119f92488e90969145c0dabfc4cb0e3b1d0437643703"
)

PREPARED = "PREPARED"
APPLYING = "APPLYING"
COMMITTED = "COMMITTED"
ROLLING_BACK = "ROLLING_BACK"
ROLLED_BACK = "ROLLED_BACK"
ROLLED_BACK_AFTER_CRASH = "ROLLED_BACK_AFTER_CRASH"


class SciencePublicationError(ValueError):
    """Fail-closed publisher error with a machine-readable receipt."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        defects: Sequence[Mapping[str, Any]] | None = None,
        receipt: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.receipt = {
            "schema_version": RESULT_SCHEMA,
            "status": "FAILED",
            "error_code": code,
            "error": message,
            "defects": [dict(defect) for defect in defects or ()],
            **dict(receipt or {}),
            "completion_claim_allowed": False,
        }


@dataclass
class _PromotionLease:
    handle: Any
    path: Path

    def release(self) -> None:
        if self.handle.closed:
            return
        try:
            portalocker.unlock(self.handle)
        finally:
            self.handle.close()
        # Preflight can fail after open("a+b") creates a 0B cooperative guard.
        # Remove only empty guards so failed preflight leaves no durable residue;
        # a non-empty guard is treated as foreign/tamper material and kept.
        try:
            if self.path.is_file() and self.path.stat().st_size == 0:
                self.path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass(frozen=True)
class _PreparedFileTarget:
    path: Path
    preimage_sha256: str
    candidate_path: Path
    candidate_sha256: str


@dataclass(frozen=True)
class _PreparedPromotion:
    projection: dict[str, Any]
    projection_preimage: bytes
    projection_preimage_sha256: str
    projection_candidate: bytes
    projection_candidate_sha256: str
    active_parent_path: Path
    active_parent_preimage_sha256: str
    active_parent_candidate_path: Path
    active_parent_candidate_sha256: str
    revision_count: int
    v110: bool
    candidate_binding: dict[str, Any] | None
    transition: _PreparedFileTarget | None
    transition_preimage_active_parent_sha256: str | None
    transition_candidate_binding: dict[str, Any] | None
    archive_manifest: _PreparedFileTarget | None
    archive_preimage_binding: dict[str, Any] | None
    archive_candidate_binding: dict[str, Any] | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _normalized_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise SciencePublicationError("INVALID_SHA256", f"{field} must be a SHA256 hex digest")
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _transition_nonpin_lines(text: str) -> tuple[str, ...]:
    """Return exact transition lines with only the labeled parent pin masked."""

    lines = list(text.splitlines())
    label_indexes = [
        index for index, line in enumerate(lines) if line.strip() == "唯一科学父目标："
    ]
    if len(label_indexes) != 1 or label_indexes[0] + 2 >= len(lines):
        raise ValueError("science transition active-parent pin is incomplete")
    label_index = label_indexes[0]
    lines[label_index + 1] = "<ACTIVE_PARENT_PATH>"
    lines[label_index + 2] = "<ACTIVE_PARENT_SHA256>"
    return tuple(lines)


def _archive_preservation_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mask only the three archive fields a science revision may advance."""

    view = dict(payload)
    publication = view.get("current_publication")
    if not isinstance(publication, Mapping):
        raise ValueError("science archive current_publication is missing")
    preserved_publication = dict(publication)
    for field in (
        "stable_spec_sha256",
        "versioned_snapshot_path",
        "versioned_snapshot_sha256",
    ):
        preserved_publication.pop(field, None)
    view["current_publication"] = preserved_publication
    return view


def _revision_entry(evidence_path: Path, event_ref: str) -> dict[str, str]:
    evidence_path = evidence_path.resolve()
    evidence = _load_json(evidence_path)
    if (
        evidence.get("schema_version") != "xinao.science_revision.v1"
        or evidence.get("status") != "APPLIED"
        or not isinstance(evidence.get("run_id"), str)
        or not evidence["run_id"].strip()
    ):
        raise ValueError(f"unsupported or incomplete science revision evidence: {evidence_path}")
    if not event_ref or "#event_id=" not in event_ref:
        raise ValueError("science revision event ref must contain an event identity")
    return {
        "status": "APPLIED",
        "run_id": evidence["run_id"],
        "event_ref": event_ref,
        "revision_evidence_ref": str(evidence_path),
        "revision_evidence_sha256": _sha256(evidence_path),
    }


def _target_mode(path: Path, fallback: Path | None = None) -> int:
    if path.exists():
        return stat.S_IMODE(path.stat().st_mode)
    if fallback is not None and fallback.exists():
        return stat.S_IMODE(fallback.stat().st_mode)
    return stat.S_IREAD | stat.S_IWRITE


def _atomic_replace_bytes(path: Path, raw: bytes, *, installed_mode: int | None = None) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    effective_mode = installed_mode if installed_mode is not None else _target_mode(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".replace", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, effective_mode | stat.S_IWRITE)
        if path.exists():
            os.chmod(path, _target_mode(path) | stat.S_IWRITE)
        os.replace(temporary_path, path)
        os.chmod(path, effective_mode)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_replace_bytes(path, _json_bytes(payload))


def _replace_file(source: Path, target: Path, *, installed_mode: int | None = None) -> None:
    source = source.resolve()
    target = target.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"replacement source is missing: {source}")
    effective_mode = installed_mode
    if effective_mode is None:
        effective_mode = _target_mode(target, source)
    _atomic_replace_bytes(target, source.read_bytes(), installed_mode=effective_mode)


def _unlink_temporary(path: Path) -> None:
    """Unlink a staging file even when a readonly preimage mode was applied.

    Windows refuses to delete files whose read-only attribute is set. Rollback
    preimages are sealed without write bits, so restore staging temps must clear
    that bit before unlink or a successful restore still fails closed.
    """

    try:
        if path.exists():
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IWRITE)
    except OSError:
        # Best-effort; the subsequent unlink either succeeds or surfaces the error.
        pass
    path.unlink(missing_ok=True)


def _restore_file(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{target.name}.", suffix=".restore", dir=target.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    installed_mode = stat.S_IMODE(source.stat().st_mode)
    primary: BaseException | None = None
    cleanup: BaseException | None = None
    try:
        temporary_path.write_bytes(source.read_bytes())
        # Keep the staging temp writable for Windows unlink; only the installed
        # target receives the sealed preimage mode (often without S_IWRITE).
        os.chmod(temporary_path, installed_mode | stat.S_IWRITE)
        _replace_file(
            temporary_path,
            target,
            installed_mode=installed_mode,
        )
    except BaseException as exc:  # preserve primary and cleanup failures together
        primary = exc
    try:
        _unlink_temporary(temporary_path)
    except BaseException as exc:
        cleanup = exc
    failures = [failure for failure in (primary, cleanup) if failure is not None]
    if len(failures) == 1:
        raise failures[0]
    if failures:
        raise ExceptionGroup("science rollback restore failed", failures)


def _validate_preimages(
    specs: Sequence[tuple[str, Path, Path, str]],
) -> list[RuntimeError]:
    errors: list[RuntimeError] = []
    for label, source, _target, expected in specs:
        if not source.is_file() or _sha256(source) != expected:
            errors.append(RuntimeError(f"{label} rollback preimage is missing or drifted"))
    return errors


def _restore_preimages(
    specs: Sequence[tuple[str, Path, Path, str]],
) -> list[BaseException]:
    errors: list[BaseException] = []
    for label, source, target, expected in specs:
        if not source.is_file() or _sha256(source) != expected:
            errors.append(RuntimeError(f"{label} rollback preimage is missing or drifted"))
            continue
        try:
            _restore_file(source, target)
        except BaseException as exc:
            errors.append(exc)
    return errors


def _seal_preimage(target: Path, archive: Path) -> str:
    target = target.resolve()
    archive = archive.resolve()
    if archive.exists():
        raise FileExistsError(f"rollback copy already exists: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    raw = target.read_bytes()
    _atomic_replace_bytes(
        archive,
        raw,
        installed_mode=stat.S_IMODE(target.stat().st_mode) & ~stat.S_IWRITE,
    )
    digest = _sha256_bytes(raw)
    if _sha256(archive) != digest:
        raise RuntimeError(f"rollback copy failed readback: {archive}")
    return digest


def _promotion_marker_path(projection_path: Path) -> Path:
    return projection_path.with_name(f"{projection_path.name}.promotion.lock")


def _promotion_lease_path(projection_path: Path) -> Path:
    return projection_path.with_name(f"{projection_path.name}.promotion.guard")


def _acquire_promotion_lease(projection_path: Path) -> _PromotionLease:
    lease_path = _promotion_lease_path(projection_path.resolve())
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse non-empty foreign/tampered guards before open/lock. Empty residue
    # from a prior preflight failure is cooperative lock state and is reused.
    if lease_path.exists() and lease_path.stat().st_size != 0:
        raise RuntimeError("science promotion guard is foreign or tampered")
    handle = lease_path.open("a+b")
    try:
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
    except portalocker.exceptions.LockException as exc:
        handle.close()
        raise RuntimeError("science promotion lease is still owned") from exc
    return _PromotionLease(handle=handle, path=lease_path)


def _default_transaction_directory(projection_path: Path, rollback_copy: Path) -> Path:
    return rollback_copy.parent / f"{projection_path.name}.transaction"


def _journal_path(transaction_directory: Path) -> Path:
    return transaction_directory.resolve() / "transaction.v1.json"


def _assert_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or _sha256(path) != expected:
        raise RuntimeError(f"{label} target does not match prepared candidate")


def _existing_chain(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_chain = projection.get("science_revision_chain")
    if raw_chain in (None, []):
        return []
    if not isinstance(raw_chain, list) or not all(isinstance(entry, dict) for entry in raw_chain):
        raise ValueError("live projection science revision chain is invalid")
    return [dict(entry) for entry in raw_chain]


def _append_revision_entries(
    projection: dict[str, Any],
    evidence_paths: Sequence[Path],
    event_refs: Sequence[str],
) -> int:
    additions = [
        _revision_entry(evidence_path, event_ref)
        for evidence_path, event_ref in zip(evidence_paths, event_refs, strict=True)
    ]
    chain = _existing_chain(projection)
    identities = {
        (
            str(entry.get("run_id")),
            str(entry.get("event_ref")),
            str(entry.get("revision_evidence_ref")),
        )
        for entry in chain
    }
    addition_identities = [
        (entry["run_id"], entry["event_ref"], entry["revision_evidence_ref"])
        for entry in additions
    ]
    if len(set(addition_identities)) != len(addition_identities) or any(
        identity in identities for identity in addition_identities
    ):
        raise ValueError("science revision promotion duplicates an existing chain identity")
    projection["science_revision_chain"] = [*chain, *additions]
    return len(projection["science_revision_chain"])


def _is_v110_candidate(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return sum(line == V110_VERSION_MARKER for line in text.splitlines()) == 1


def _dependency_defect(code: str, message: str, **observed: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **observed}


def _prepare_promotion(
    *,
    projection_path: Path,
    evidence_paths: Sequence[Path],
    event_refs: Sequence[str],
    expected_projection_sha256: str | None,
    candidate_active_parent: Path | None,
    expected_candidate_active_parent_sha256: str | None,
    expected_active_parent_sha256: str | None,
    science_episode_gate: Mapping[str, Any] | None,
    tool_glue_authority_path: Path | None,
    expected_tool_glue_authority_sha256: str | None,
    expected_tool_glue_version: str,
    transition_path: Path | None,
    transition_candidate: Path | None,
    expected_transition_sha256: str | None,
    expected_transition_preimage_active_parent_sha256: str | None,
    transition_rollback_copy: Path | None,
    archive_manifest_path: Path | None,
    archive_manifest_candidate: Path | None,
    expected_archive_manifest_sha256: str | None,
    archive_manifest_rollback_copy: Path | None,
) -> _PreparedPromotion:
    projection_path = projection_path.resolve()
    projection_preimage = projection_path.read_bytes()
    projection_preimage_sha256 = _sha256_bytes(projection_preimage)
    if expected_projection_sha256 is not None:
        expected_projection = _normalized_sha256(
            expected_projection_sha256, "expected_projection_sha256"
        )
        if projection_preimage_sha256 != expected_projection:
            raise ValueError("science active-parent projection changed before promotion")
    projection = json.loads(projection_preimage.decode("utf-8"))
    if not isinstance(projection, dict):
        raise ValueError("science active-parent projection root must be an object")

    revision_count = _append_revision_entries(
        projection,
        [path.resolve() for path in evidence_paths],
        list(event_refs),
    )
    if science_episode_gate is not None:
        projection["science_episode_gate"] = dict(science_episode_gate)

    active_binding = projection.get("active_parent")
    if not isinstance(active_binding, dict) or not isinstance(active_binding.get("path"), str):
        raise ValueError("science projection active_parent binding is incomplete")
    active_parent_path = Path(active_binding["path"]).resolve()
    if not active_parent_path.is_file():
        raise FileNotFoundError(f"active-parent source is missing: {active_parent_path}")
    active_parent_preimage_sha256 = _sha256(active_parent_path)
    if expected_active_parent_sha256 is not None:
        expected_parent = _normalized_sha256(
            expected_active_parent_sha256, "expected_active_parent_sha256"
        )
        if active_parent_preimage_sha256 != expected_parent:
            raise ValueError("science active-parent source changed before promotion")

    candidate_parent_path = (
        candidate_active_parent.resolve()
        if candidate_active_parent is not None
        else active_parent_path
    )
    if not candidate_parent_path.is_file():
        raise FileNotFoundError(f"science candidate is missing: {candidate_parent_path}")
    candidate_parent_sha256 = _sha256(candidate_parent_path)
    if expected_candidate_active_parent_sha256 is not None:
        expected_candidate = _normalized_sha256(
            expected_candidate_active_parent_sha256,
            "expected_candidate_active_parent_sha256",
        )
        if candidate_parent_sha256 != expected_candidate:
            raise ValueError("science candidate changed before promotion")
    active_binding["sha256"] = candidate_parent_sha256

    v110 = _is_v110_candidate(candidate_active_parent)
    candidate_binding: dict[str, Any] | None = None
    prepared_transition: _PreparedFileTarget | None = None
    transition_candidate_binding: dict[str, Any] | None = None
    transition_preimage_parent_sha256: str | None = None
    prepared_archive: _PreparedFileTarget | None = None
    archive_preimage_binding: dict[str, Any] | None = None
    archive_candidate_binding: dict[str, Any] | None = None
    if v110:
        defects: list[dict[str, Any]] = []
        if expected_projection_sha256 is None:
            defects.append(
                _dependency_defect(
                    "SCIENCE_PROJECTION_PREIMAGE_UNBOUND",
                    "v1.10 publication requires an exact projection preimage",
                )
            )
        if expected_active_parent_sha256 is None:
            defects.append(
                _dependency_defect(
                    "SCIENCE_PARENT_PREIMAGE_UNBOUND",
                    "v1.10 publication requires the exact v1.9 preimage",
                )
            )
        if expected_candidate_active_parent_sha256 is None:
            defects.append(
                _dependency_defect(
                    "SCIENCE_CANDIDATE_UNBOUND",
                    "v1.10 publication requires the exact candidate digest",
                )
            )
        for value, code, message in (
            (
                transition_path,
                "SCIENCE_TRANSITION_TARGET_MISSING",
                "v1.10 publication requires the current transition target",
            ),
            (
                transition_candidate,
                "SCIENCE_TRANSITION_CANDIDATE_MISSING",
                "v1.10 publication requires a sealed transition candidate",
            ),
            (
                expected_transition_sha256,
                "SCIENCE_TRANSITION_PREIMAGE_UNBOUND",
                "v1.10 publication requires the exact transition preimage",
            ),
            (
                expected_transition_preimage_active_parent_sha256,
                "SCIENCE_TRANSITION_PREIMAGE_PARENT_PIN_UNBOUND",
                "v1.10 publication must explicitly acknowledge the old transition parent pin",
            ),
            (
                transition_rollback_copy,
                "SCIENCE_TRANSITION_ROLLBACK_MISSING",
                "v1.10 publication requires a transition rollback carrier",
            ),
            (
                archive_manifest_path,
                "SCIENCE_ARCHIVE_TARGET_MISSING",
                "v1.10 publication requires the current archive manifest target",
            ),
            (
                archive_manifest_candidate,
                "SCIENCE_ARCHIVE_CANDIDATE_MISSING",
                "v1.10 publication requires a sealed archive manifest candidate",
            ),
            (
                expected_archive_manifest_sha256,
                "SCIENCE_ARCHIVE_PREIMAGE_UNBOUND",
                "v1.10 publication requires the exact archive manifest preimage",
            ),
            (
                archive_manifest_rollback_copy,
                "SCIENCE_ARCHIVE_ROLLBACK_MISSING",
                "v1.10 publication requires an archive manifest rollback carrier",
            ),
        ):
            if value is None:
                defects.append(_dependency_defect(code, message))

        software_binding = projection.get("software_foundation")
        if not isinstance(software_binding, dict):
            defects.append(
                _dependency_defect(
                    "SCIENCE_DEPENDENCY_TOOL_GLUE_BINDING_MISSING",
                    "projection has no software_foundation binding",
                )
            )
        elif tool_glue_authority_path is None or expected_tool_glue_authority_sha256 is None:
            defects.append(
                _dependency_defect(
                    "SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISSING",
                    "v1.10 publication requires the exact live tool-glue pin",
                )
            )
        else:
            glue_path = tool_glue_authority_path.resolve()
            expected_glue = _normalized_sha256(
                expected_tool_glue_authority_sha256,
                "expected_tool_glue_authority_sha256",
            )
            binding_path_value = software_binding.get("path")
            try:
                binding_path = Path(str(binding_path_value)).resolve()
            except (OSError, ValueError):
                binding_path = Path(".").resolve()
            if binding_path != glue_path:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_DEPENDENCY_TOOL_GLUE_PATH_MISMATCH",
                        "projection software_foundation.path does not bind the live authority",
                        expected=str(glue_path),
                        observed=str(binding_path_value),
                    )
                )
            observed_glue = _sha256(glue_path) if glue_path.is_file() else None
            if observed_glue != expected_glue:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_DEPENDENCY_TOOL_GLUE_SHA_MISMATCH",
                        "live tool-glue authority is not the required verified postimage",
                        expected=expected_glue,
                        observed=observed_glue,
                    )
                )
            if str(software_binding.get("sha256", "")).lower() != expected_glue:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_DEPENDENCY_TOOL_GLUE_PROJECTION_SHA_MISMATCH",
                        "projection software_foundation.sha256 is not synchronized",
                        expected=expected_glue,
                        observed=software_binding.get("sha256"),
                    )
                )
            if software_binding.get("version") != expected_tool_glue_version:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
                        "projection software_foundation.version is not synchronized",
                        expected=expected_tool_glue_version,
                        observed=software_binding.get("version"),
                    )
                )
            if not defects:
                try:
                    candidate_binding = validate_science_revision_candidate_binding(
                        projection,
                        science_candidate_path=candidate_parent_path,
                        software_foundation_candidate_path=glue_path,
                    )
                except Exception as exc:
                    defects.append(
                        _dependency_defect(
                            "SCIENCE_CANDIDATE_CONSUMER_REJECTED",
                            str(exc),
                        )
                    )
                else:
                    if candidate_binding.get("science_parent_version") != "v1.10":
                        defects.append(
                            _dependency_defect(
                                "SCIENCE_CANDIDATE_VERSION_MISMATCH",
                                "candidate consumer did not resolve v1.10",
                                observed=candidate_binding.get("science_parent_version"),
                            )
                        )
                    if (
                        candidate_binding.get("software_foundation_version")
                        != expected_tool_glue_version
                    ):
                        defects.append(
                            _dependency_defect(
                                "SCIENCE_DEPENDENCY_TOOL_GLUE_VERSION_MISMATCH",
                                "candidate consumer resolved another tool-glue version",
                                expected=expected_tool_glue_version,
                                observed=candidate_binding.get("software_foundation_version"),
                            )
                        )
                    if candidate_binding.get("maturation_invariant_required") is not True:
                        defects.append(
                            _dependency_defect(
                                "SCIENCE_CANDIDATE_MATURATION_INVARIANT_MISSING",
                                "v1.10 consumer did not require the maturation invariant",
                            )
                        )

        if (
            transition_path is not None
            and transition_candidate is not None
            and expected_transition_sha256 is not None
            and expected_transition_preimage_active_parent_sha256 is not None
        ):
            live_transition = transition_path.resolve()
            candidate_transition = transition_candidate.resolve()
            expected_transition = _normalized_sha256(
                expected_transition_sha256,
                "expected_transition_sha256",
            )
            transition_preimage_parent_sha256 = _normalized_sha256(
                expected_transition_preimage_active_parent_sha256,
                "expected_transition_preimage_active_parent_sha256",
            )
            if live_transition == candidate_transition:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_TRANSITION_CANDIDATE_ALIASES_TARGET",
                        "transition candidate must be isolated from the live target",
                    )
                )
            elif not live_transition.is_file() or not candidate_transition.is_file():
                defects.append(
                    _dependency_defect(
                        "SCIENCE_TRANSITION_CARRIER_MISSING",
                        "transition target or candidate is missing",
                        target=str(live_transition),
                        candidate=str(candidate_transition),
                    )
                )
            else:
                observed_transition = _sha256(live_transition)
                candidate_transition_sha256 = _sha256(candidate_transition)
                if observed_transition != expected_transition:
                    defects.append(
                        _dependency_defect(
                            "SCIENCE_TRANSITION_PREIMAGE_MISMATCH",
                            "transition target changed before promotion",
                            expected=expected_transition,
                            observed=observed_transition,
                        )
                    )
                try:
                    transition_preimage_text = live_transition.read_text(encoding="utf-8")
                    transition_candidate_text = candidate_transition.read_text(encoding="utf-8")
                    validate_science_transition_active_parent_binding(
                        transition_preimage_text,
                        expected_active_parent_path=active_parent_path,
                        expected_active_parent_sha256=transition_preimage_parent_sha256,
                    )
                    transition_candidate_binding = (
                        validate_science_transition_active_parent_binding(
                            transition_candidate_text,
                            expected_active_parent_path=active_parent_path,
                            expected_active_parent_sha256=candidate_parent_sha256,
                        )
                    )
                    if _transition_nonpin_lines(
                        transition_preimage_text
                    ) != _transition_nonpin_lines(transition_candidate_text):
                        raise ValueError(
                            "transition candidate changes content outside the labeled parent pin"
                        )
                except Exception as exc:
                    defects.append(
                        _dependency_defect(
                            "SCIENCE_TRANSITION_CONSUMER_REJECTED",
                            str(exc),
                        )
                    )
                prepared_transition = _PreparedFileTarget(
                    path=live_transition,
                    preimage_sha256=observed_transition,
                    candidate_path=candidate_transition,
                    candidate_sha256=candidate_transition_sha256,
                )

        if (
            archive_manifest_path is not None
            and archive_manifest_candidate is not None
            and expected_archive_manifest_sha256 is not None
        ):
            live_archive = archive_manifest_path.resolve()
            candidate_archive = archive_manifest_candidate.resolve()
            expected_archive = _normalized_sha256(
                expected_archive_manifest_sha256,
                "expected_archive_manifest_sha256",
            )
            if live_archive == candidate_archive:
                defects.append(
                    _dependency_defect(
                        "SCIENCE_ARCHIVE_CANDIDATE_ALIASES_TARGET",
                        "archive manifest candidate must be isolated from the live target",
                    )
                )
            elif not live_archive.is_file() or not candidate_archive.is_file():
                defects.append(
                    _dependency_defect(
                        "SCIENCE_ARCHIVE_CARRIER_MISSING",
                        "archive manifest target or candidate is missing",
                        target=str(live_archive),
                        candidate=str(candidate_archive),
                    )
                )
            else:
                observed_archive = _sha256(live_archive)
                candidate_archive_sha256 = _sha256(candidate_archive)
                if observed_archive != expected_archive:
                    defects.append(
                        _dependency_defect(
                            "SCIENCE_ARCHIVE_PREIMAGE_MISMATCH",
                            "archive manifest changed before promotion",
                            expected=expected_archive,
                            observed=observed_archive,
                        )
                    )
                try:
                    archive_preimage = _load_json(live_archive)
                    archive_candidate_payload = _load_json(candidate_archive)
                    archive_preimage_binding = validate_science_archive_publication_binding(
                        archive_preimage,
                        expected_active_parent_path=active_parent_path,
                        expected_active_parent_sha256=active_parent_preimage_sha256,
                    )
                    archive_candidate_binding = validate_science_archive_publication_binding(
                        archive_candidate_payload,
                        expected_active_parent_path=active_parent_path,
                        expected_active_parent_sha256=candidate_parent_sha256,
                    )
                    if _archive_preservation_view(
                        archive_preimage
                    ) != _archive_preservation_view(archive_candidate_payload):
                        raise ValueError(
                            "archive candidate changes content outside the current publication pin"
                        )
                except Exception as exc:
                    defects.append(
                        _dependency_defect(
                            "SCIENCE_ARCHIVE_CONSUMER_REJECTED",
                            str(exc),
                        )
                    )
                prepared_archive = _PreparedFileTarget(
                    path=live_archive,
                    preimage_sha256=observed_archive,
                    candidate_path=candidate_archive,
                    candidate_sha256=candidate_archive_sha256,
                )
        if defects:
            dependency_mismatch = any("TOOL_GLUE" in str(defect["code"]) for defect in defects)
            code = (
                "SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH"
                if dependency_mismatch
                else "SCIENCE_REVISION_PREFLIGHT_FAILED"
            )
            raise SciencePublicationError(
                code,
                "science v1.10 aggregate preflight rejected before mutation",
                defects=defects,
            )
    else:
        load_science_active_parent(projection_path)

    projection_candidate = _json_bytes(projection)
    return _PreparedPromotion(
        projection=projection,
        projection_preimage=projection_preimage,
        projection_preimage_sha256=projection_preimage_sha256,
        projection_candidate=projection_candidate,
        projection_candidate_sha256=_sha256_bytes(projection_candidate),
        active_parent_path=active_parent_path,
        active_parent_preimage_sha256=active_parent_preimage_sha256,
        active_parent_candidate_path=candidate_parent_path,
        active_parent_candidate_sha256=candidate_parent_sha256,
        revision_count=revision_count,
        v110=v110,
        candidate_binding=candidate_binding,
        transition=prepared_transition,
        transition_preimage_active_parent_sha256=transition_preimage_parent_sha256,
        transition_candidate_binding=transition_candidate_binding,
        archive_manifest=prepared_archive,
        archive_preimage_binding=archive_preimage_binding,
        archive_candidate_binding=archive_candidate_binding,
    )


def _marker_payload(journal_path: Path) -> dict[str, Any]:
    return {
        "schema_version": "xinao.science_revision_marker.v1",
        "journal_path": str(journal_path.resolve()),
        "completion_claim_allowed": False,
    }


def _journal_receipt(journal: Mapping[str, Any], journal_path: Path) -> dict[str, Any]:
    status = str(journal.get("status"))
    rolled_back = status in {ROLLED_BACK, ROLLED_BACK_AFTER_CRASH}
    receipt = {
        "schema_version": RESULT_SCHEMA,
        "status": "VERIFIED" if status == COMMITTED else status,
        "transaction_status": status,
        "projection_path": str(journal.get("projection_path")),
        "projection_sha256": journal.get("projection_committed_sha256"),
        "active_parent_sha256": journal.get("active_parent_committed_sha256"),
        "rollback_copy": str(journal.get("projection_rollback_copy")),
        "rollback_copy_sha256": journal.get("projection_preimage_sha256"),
        "revision_count": int(journal.get("revision_count", 0)),
        "transaction_journal": str(journal_path.resolve()),
        "rollback_order": (
            ["transition", "archive_manifest", "projection", "active_parent"]
            if journal.get("transition_path") is not None
            else ["projection", "active_parent"]
        ),
        "tool_glue_rollback_ready": bool(journal.get("transition_path")) and rolled_back,
        "next_rollback_dependency": (
            "tool-glue-v3.4" if bool(journal.get("transition_path")) and rolled_back else None
        ),
        "completion_claim_allowed": False,
    }
    if journal.get("transition_path") is not None:
        receipt.update(
            {
                "transition_path": str(journal.get("transition_path")),
                "transition_sha256": journal.get("transition_committed_sha256"),
                "transition_preimage_active_parent_sha256": journal.get(
                    "transition_preimage_active_parent_sha256"
                ),
                "transition_candidate_active_parent_sha256": journal.get(
                    "transition_candidate_active_parent_sha256"
                ),
                "archive_manifest_path": str(journal.get("archive_manifest_path")),
                "archive_manifest_sha256": journal.get(
                    "archive_manifest_committed_sha256"
                ),
                "archive_snapshot_path": journal.get("archive_snapshot_path"),
                "archive_snapshot_sha256": journal.get("archive_snapshot_sha256"),
            }
        )
    return receipt


def _preimage_specs(journal: Mapping[str, Any]) -> list[tuple[str, Path, Path, str]]:
    specs: list[tuple[str, Path, Path, str]] = []
    if journal.get("transition_path") is not None:
        specs.extend(
            [
                (
                    "transition",
                    Path(str(journal["transition_rollback_copy"])).resolve(),
                    Path(str(journal["transition_path"])).resolve(),
                    str(journal["transition_preimage_sha256"]),
                ),
                (
                    "archive-manifest",
                    Path(str(journal["archive_manifest_rollback_copy"])).resolve(),
                    Path(str(journal["archive_manifest_path"])).resolve(),
                    str(journal["archive_manifest_preimage_sha256"]),
                ),
            ]
        )
    specs.extend(
        [
        (
            "projection",
            Path(str(journal["projection_rollback_copy"])).resolve(),
            Path(str(journal["projection_path"])).resolve(),
            str(journal["projection_preimage_sha256"]),
        ),
        (
            "active-parent",
            Path(str(journal["active_parent_rollback_copy"])).resolve(),
            Path(str(journal["active_parent_path"])).resolve(),
            str(journal["active_parent_preimage_sha256"]),
        ),
        ]
    )
    return specs


def _raise_group(message: str, failures: Sequence[BaseException]) -> None:
    if len(failures) == 1:
        raise failures[0]
    raise ExceptionGroup(message, list(failures))


def _restore_transaction_preimages(
    journal: dict[str, Any],
    journal_path: Path,
    *,
    status: str,
) -> None:
    specs = _preimage_specs(journal)
    invalid = _validate_preimages(specs)
    if invalid:
        _raise_group("science rollback preimages are invalid", invalid)
    errors = _restore_preimages(specs)
    if errors:
        _raise_group("science rollback could not restore every target", errors)
    for label, _source, target, expected in specs:
        if _sha256(target) != expected:
            raise RuntimeError(f"{label} rollback target failed readback")
    journal["status"] = status
    _write_json_atomic(journal_path, journal)


def _promote_revision_chain_impl(
    *,
    projection_path: Path,
    evidence_paths: list[Path],
    event_refs: list[str],
    rollback_copy: Path,
    expected_projection_sha256: str | None,
    candidate_active_parent: Path | None,
    expected_candidate_active_parent_sha256: str | None,
    expected_active_parent_sha256: str | None,
    active_parent_rollback_copy: Path | None,
    science_episode_gate: Mapping[str, Any] | None,
    transaction_directory: Path | None,
    tool_glue_authority_path: Path | None,
    expected_tool_glue_authority_sha256: str | None,
    expected_tool_glue_version: str,
    transition_path: Path | None,
    transition_candidate: Path | None,
    expected_transition_sha256: str | None,
    expected_transition_preimage_active_parent_sha256: str | None,
    transition_rollback_copy: Path | None,
    archive_manifest_path: Path | None,
    archive_manifest_candidate: Path | None,
    expected_archive_manifest_sha256: str | None,
    archive_manifest_rollback_copy: Path | None,
) -> dict[str, Any]:
    if len(evidence_paths) != len(event_refs) or not evidence_paths:
        raise ValueError("revision evidence and event refs must be paired and non-empty")
    projection_path = projection_path.resolve()
    rollback_copy = rollback_copy.resolve()
    rollback_carriers = [
        ("projection", rollback_copy),
        ("active-parent", active_parent_rollback_copy),
        ("transition", transition_rollback_copy),
        ("archive-manifest", archive_manifest_rollback_copy),
    ]
    for label, carrier in rollback_carriers:
        if carrier is not None and carrier.resolve().exists():
            raise FileExistsError(f"{label} rollback copy already exists: {carrier.resolve()}")
    transaction_directory = (
        transaction_directory.resolve()
        if transaction_directory is not None
        else _default_transaction_directory(projection_path, rollback_copy).resolve()
    )
    journal_path = _journal_path(transaction_directory)
    marker_path = _promotion_marker_path(projection_path).resolve()
    if marker_path.exists():
        raise RuntimeError("an interrupted science promotion requires recovery")
    if journal_path.exists():
        raise FileExistsError(f"transaction journal already exists: {journal_path}")

    lease = _acquire_promotion_lease(projection_path)
    try:
        prepared = _prepare_promotion(
            projection_path=projection_path,
            evidence_paths=evidence_paths,
            event_refs=event_refs,
            expected_projection_sha256=expected_projection_sha256,
            candidate_active_parent=candidate_active_parent,
            expected_candidate_active_parent_sha256=expected_candidate_active_parent_sha256,
            expected_active_parent_sha256=expected_active_parent_sha256,
            science_episode_gate=science_episode_gate,
            tool_glue_authority_path=tool_glue_authority_path,
            expected_tool_glue_authority_sha256=expected_tool_glue_authority_sha256,
            expected_tool_glue_version=expected_tool_glue_version,
            transition_path=transition_path,
            transition_candidate=transition_candidate,
            expected_transition_sha256=expected_transition_sha256,
            expected_transition_preimage_active_parent_sha256=(
                expected_transition_preimage_active_parent_sha256
            ),
            transition_rollback_copy=transition_rollback_copy,
            archive_manifest_path=archive_manifest_path,
            archive_manifest_candidate=archive_manifest_candidate,
            expected_archive_manifest_sha256=expected_archive_manifest_sha256,
            archive_manifest_rollback_copy=archive_manifest_rollback_copy,
        )
        # The complete read-only preflight above precedes every marker, journal,
        # rollback archive, or authority mutation.  Recheck exact bytes while the
        # cooperative lease is held before materializing transaction state.
        if _sha256(projection_path) != prepared.projection_preimage_sha256:
            raise ValueError("science active-parent projection changed before transaction materialization")
        if _sha256(prepared.active_parent_path) != prepared.active_parent_preimage_sha256:
            raise ValueError("science active-parent source changed before transaction materialization")
        if (
            _sha256(prepared.active_parent_candidate_path)
            != prepared.active_parent_candidate_sha256
        ):
            raise ValueError("science candidate changed before transaction materialization")
        if prepared.v110 and tool_glue_authority_path is not None:
            expected_glue = _normalized_sha256(
                str(expected_tool_glue_authority_sha256),
                "expected_tool_glue_authority_sha256",
            )
            if _sha256(tool_glue_authority_path.resolve()) != expected_glue:
                raise SciencePublicationError(
                    "SCIENCE_DEPENDENCY_TOOL_GLUE_PIN_MISMATCH",
                    "tool-glue authority drifted after preflight and before mutation",
                    defects=[
                        _dependency_defect(
                            "SCIENCE_DEPENDENCY_TOOL_GLUE_SHA_MISMATCH",
                            "live tool-glue authority drifted before science transaction",
                        )
                    ],
                )
            if (
                prepared.transition is None
                or prepared.archive_manifest is None
                or prepared.archive_candidate_binding is None
            ):
                raise RuntimeError("science v1.10 coupled target preflight was incomplete")
            for label, target in (
                ("transition", prepared.transition),
                ("archive manifest", prepared.archive_manifest),
            ):
                if _sha256(target.path) != target.preimage_sha256:
                    raise ValueError(f"science {label} changed before transaction materialization")
                if _sha256(target.candidate_path) != target.candidate_sha256:
                    raise ValueError(f"science {label} candidate changed before transaction materialization")
            archive_snapshot_path = Path(
                str(prepared.archive_candidate_binding["versioned_snapshot_path"])
            ).resolve()
            archive_snapshot_sha256 = str(
                prepared.archive_candidate_binding["versioned_snapshot_sha256"]
            )
            if _sha256(archive_snapshot_path) != archive_snapshot_sha256:
                raise ValueError("science archive snapshot drifted before transaction materialization")

        parent_rollback = (
            active_parent_rollback_copy.resolve()
            if active_parent_rollback_copy is not None
            else (transaction_directory / "active-parent.preimage.txt").resolve()
        )
        projection_preimage_sha256 = _seal_preimage(projection_path, rollback_copy)
        active_parent_preimage_sha256 = _seal_preimage(
            prepared.active_parent_path, parent_rollback
        )
        transition_rollback: Path | None = None
        archive_rollback: Path | None = None
        transition_preimage_sha256: str | None = None
        archive_preimage_sha256: str | None = None
        if prepared.v110:
            if (
                prepared.transition is None
                or prepared.archive_manifest is None
                or transition_rollback_copy is None
                or archive_manifest_rollback_copy is None
            ):
                raise RuntimeError("science v1.10 rollback carriers were not prepared")
            transition_rollback = transition_rollback_copy.resolve()
            archive_rollback = archive_manifest_rollback_copy.resolve()
            transition_preimage_sha256 = _seal_preimage(
                prepared.transition.path,
                transition_rollback,
            )
            archive_preimage_sha256 = _seal_preimage(
                prepared.archive_manifest.path,
                archive_rollback,
            )
        candidate_projection_path = (transaction_directory / "projection.candidate.json").resolve()
        _atomic_replace_bytes(
            candidate_projection_path,
            prepared.projection_candidate,
            installed_mode=stat.S_IREAD,
        )
        journal: dict[str, Any] = {
            "schema_version": TRANSACTION_SCHEMA,
            "status": PREPARED,
            "projection_path": str(projection_path),
            "projection_preimage_sha256": projection_preimage_sha256,
            "projection_candidate_sha256": prepared.projection_candidate_sha256,
            "projection_rollback_copy": str(rollback_copy),
            "projection_candidate_path": str(candidate_projection_path),
            "active_parent_path": str(prepared.active_parent_path),
            "active_parent_preimage_sha256": active_parent_preimage_sha256,
            "active_parent_candidate_sha256": prepared.active_parent_candidate_sha256,
            "active_parent_rollback_copy": str(parent_rollback),
            "active_parent_candidate_path": str(prepared.active_parent_candidate_path),
            "revision_count": prepared.revision_count,
            "v110_dependency_pin": (
                {
                    "authority_path": str(tool_glue_authority_path.resolve()),
                    "sha256": str(expected_tool_glue_authority_sha256).lower(),
                    "version": expected_tool_glue_version,
                }
                if prepared.v110 and tool_glue_authority_path is not None
                else None
            ),
            "completion_claim_allowed": False,
        }
        if prepared.v110:
            if (
                prepared.transition is None
                or prepared.archive_manifest is None
                or prepared.transition_preimage_active_parent_sha256 is None
                or prepared.transition_candidate_binding is None
                or prepared.archive_candidate_binding is None
                or transition_rollback is None
                or archive_rollback is None
            ):
                raise RuntimeError("science v1.10 journal binding was incomplete")
            journal.update(
                {
                    "transition_path": str(prepared.transition.path),
                    "transition_preimage_sha256": transition_preimage_sha256,
                    "transition_candidate_sha256": prepared.transition.candidate_sha256,
                    "transition_candidate_path": str(prepared.transition.candidate_path),
                    "transition_rollback_copy": str(transition_rollback),
                    "transition_preimage_active_parent_sha256": (
                        prepared.transition_preimage_active_parent_sha256
                    ),
                    "transition_candidate_active_parent_sha256": (
                        prepared.active_parent_candidate_sha256
                    ),
                    "archive_manifest_path": str(prepared.archive_manifest.path),
                    "archive_manifest_preimage_sha256": archive_preimage_sha256,
                    "archive_manifest_candidate_sha256": (
                        prepared.archive_manifest.candidate_sha256
                    ),
                    "archive_manifest_candidate_path": str(
                        prepared.archive_manifest.candidate_path
                    ),
                    "archive_manifest_rollback_copy": str(archive_rollback),
                    "archive_snapshot_path": prepared.archive_candidate_binding[
                        "versioned_snapshot_path"
                    ],
                    "archive_snapshot_sha256": prepared.archive_candidate_binding[
                        "versioned_snapshot_sha256"
                    ],
                    "rollback_order": [
                        "transition",
                        "archive_manifest",
                        "projection",
                        "active_parent",
                    ],
                }
            )
        _write_json_atomic(journal_path, journal)
        _write_json_atomic(marker_path, _marker_payload(journal_path))
        journal["status"] = APPLYING
        _write_json_atomic(journal_path, journal)

        try:
            if prepared.active_parent_candidate_path != prepared.active_parent_path:
                _replace_file(
                    prepared.active_parent_candidate_path,
                    prepared.active_parent_path,
                )
            _assert_hash(
                prepared.active_parent_path,
                prepared.active_parent_candidate_sha256,
                "active-parent",
            )
            candidate_resolution = load_science_active_parent(candidate_projection_path)
            _replace_file(
                candidate_projection_path,
                projection_path,
                installed_mode=stat.S_IMODE(rollback_copy.stat().st_mode),
            )
            _assert_hash(
                projection_path,
                prepared.projection_candidate_sha256,
                "projection",
            )
            live_archive_binding: dict[str, Any] | None = None
            live_transition_binding: dict[str, Any] | None = None
            if prepared.v110:
                if prepared.archive_manifest is None or prepared.transition is None:
                    raise RuntimeError("science v1.10 coupled targets were not prepared")
                if archive_rollback is None or transition_rollback is None:
                    raise RuntimeError("science v1.10 rollback modes were not prepared")
                _replace_file(
                    prepared.archive_manifest.candidate_path,
                    prepared.archive_manifest.path,
                    installed_mode=stat.S_IMODE(archive_rollback.stat().st_mode),
                )
                _assert_hash(
                    prepared.archive_manifest.path,
                    prepared.archive_manifest.candidate_sha256,
                    "archive-manifest",
                )
                live_archive_binding = validate_science_archive_publication_binding(
                    _load_json(prepared.archive_manifest.path),
                    expected_active_parent_path=prepared.active_parent_path,
                    expected_active_parent_sha256=prepared.active_parent_candidate_sha256,
                )
                _replace_file(
                    prepared.transition.candidate_path,
                    prepared.transition.path,
                    installed_mode=stat.S_IMODE(transition_rollback.stat().st_mode),
                )
                _assert_hash(
                    prepared.transition.path,
                    prepared.transition.candidate_sha256,
                    "transition",
                )
                live_transition_binding = validate_science_transition_active_parent_binding(
                    prepared.transition.path.read_text(encoding="utf-8"),
                    expected_active_parent_path=prepared.active_parent_path,
                    expected_active_parent_sha256=prepared.active_parent_candidate_sha256,
                )
            journal["projection_committed_sha256"] = prepared.projection_candidate_sha256
            journal["active_parent_committed_sha256"] = (
                prepared.active_parent_candidate_sha256
            )
            if prepared.v110:
                journal["archive_manifest_committed_sha256"] = (
                    prepared.archive_manifest.candidate_sha256
                )
                journal["transition_committed_sha256"] = prepared.transition.candidate_sha256
            journal["status"] = COMMITTED
            _write_json_atomic(journal_path, journal)
            live_resolution = load_science_active_parent(projection_path)
        except BaseException as primary:
            if journal.get("status") == COMMITTED:
                if not prepared.v110:
                    raise
                journal["status"] = ROLLING_BACK
                _write_json_atomic(journal_path, journal)
            failures: list[BaseException] = [primary]
            try:
                _restore_transaction_preimages(
                    journal,
                    journal_path,
                    status=ROLLED_BACK,
                )
            except BaseException as rollback_error:
                failures.append(rollback_error)
            if len(failures) == 1:
                raise primary
            raise ExceptionGroup("science promotion and rollback both failed", failures) from primary

        marker_path.unlink(missing_ok=True)
        result = _journal_receipt(journal, journal_path)
        result.update(
            {
                "candidate_resolution_status": candidate_resolution["status"],
                "live_resolution_status": live_resolution["status"],
                "candidate_binding": prepared.candidate_binding,
                "transition_binding": live_transition_binding,
                "archive_binding": live_archive_binding,
            }
        )
        return result
    finally:
        lease.release()


def promote_revision_chain(
    *,
    projection_path: Path,
    evidence_paths: list[Path],
    event_refs: list[str],
    rollback_copy: Path,
    expected_projection_sha256: str | None = None,
    candidate_active_parent: Path | None = None,
    expected_candidate_active_parent_sha256: str | None = None,
    expected_active_parent_sha256: str | None = None,
    active_parent_rollback_copy: Path | None = None,
    science_episode_gate: Mapping[str, Any] | None = None,
    transaction_directory: Path | None = None,
    tool_glue_authority_path: Path | None = None,
    expected_tool_glue_authority_sha256: str | None = None,
    expected_tool_glue_version: str = DEFAULT_TOOL_GLUE_VERSION,
    transition_path: Path | None = None,
    transition_candidate: Path | None = None,
    expected_transition_sha256: str | None = None,
    expected_transition_preimage_active_parent_sha256: str | None = None,
    transition_rollback_copy: Path | None = None,
    archive_manifest_path: Path | None = None,
    archive_manifest_candidate: Path | None = None,
    expected_archive_manifest_sha256: str | None = None,
    archive_manifest_rollback_copy: Path | None = None,
) -> dict[str, Any]:
    """Backward-compatible entry; v1.10 automatically activates the strict pin gate."""

    return _promote_revision_chain_impl(
        projection_path=projection_path,
        evidence_paths=evidence_paths,
        event_refs=event_refs,
        rollback_copy=rollback_copy,
        expected_projection_sha256=expected_projection_sha256,
        candidate_active_parent=candidate_active_parent,
        expected_candidate_active_parent_sha256=expected_candidate_active_parent_sha256,
        expected_active_parent_sha256=expected_active_parent_sha256,
        active_parent_rollback_copy=active_parent_rollback_copy,
        science_episode_gate=science_episode_gate,
        transaction_directory=transaction_directory,
        tool_glue_authority_path=tool_glue_authority_path,
        expected_tool_glue_authority_sha256=expected_tool_glue_authority_sha256,
        expected_tool_glue_version=expected_tool_glue_version,
        transition_path=transition_path,
        transition_candidate=transition_candidate,
        expected_transition_sha256=expected_transition_sha256,
        expected_transition_preimage_active_parent_sha256=(
            expected_transition_preimage_active_parent_sha256
        ),
        transition_rollback_copy=transition_rollback_copy,
        archive_manifest_path=archive_manifest_path,
        archive_manifest_candidate=archive_manifest_candidate,
        expected_archive_manifest_sha256=expected_archive_manifest_sha256,
        archive_manifest_rollback_copy=archive_manifest_rollback_copy,
    )


def publish_science_revision_transaction(
    *,
    projection_path: Path,
    evidence_paths: list[Path],
    event_refs: list[str],
    rollback_copy: Path,
    expected_projection_sha256: str,
    candidate_active_parent: Path,
    expected_candidate_active_parent_sha256: str,
    expected_active_parent_sha256: str,
    active_parent_rollback_copy: Path,
    tool_glue_authority_path: Path,
    expected_tool_glue_authority_sha256: str,
    expected_tool_glue_version: str = DEFAULT_TOOL_GLUE_VERSION,
    science_episode_gate: Mapping[str, Any] | None = None,
    transaction_directory: Path | None = None,
    transition_path: Path | None = None,
    transition_candidate: Path | None = None,
    expected_transition_sha256: str | None = None,
    expected_transition_preimage_active_parent_sha256: str | None = None,
    transition_rollback_copy: Path | None = None,
    archive_manifest_path: Path | None = None,
    archive_manifest_candidate: Path | None = None,
    expected_archive_manifest_sha256: str | None = None,
    archive_manifest_rollback_copy: Path | None = None,
) -> dict[str, Any]:
    """Publish a fully pinned v1.10 revision after tool-glue is independently live."""

    if not _is_v110_candidate(candidate_active_parent):
        raise SciencePublicationError(
            "SCIENCE_REVISION_VERSION_MISMATCH",
            "the strict transaction entry accepts only the v1.10 candidate",
        )
    return _promote_revision_chain_impl(
        projection_path=projection_path,
        evidence_paths=evidence_paths,
        event_refs=event_refs,
        rollback_copy=rollback_copy,
        expected_projection_sha256=expected_projection_sha256,
        candidate_active_parent=candidate_active_parent,
        expected_candidate_active_parent_sha256=expected_candidate_active_parent_sha256,
        expected_active_parent_sha256=expected_active_parent_sha256,
        active_parent_rollback_copy=active_parent_rollback_copy,
        science_episode_gate=science_episode_gate,
        transaction_directory=transaction_directory,
        tool_glue_authority_path=tool_glue_authority_path,
        expected_tool_glue_authority_sha256=expected_tool_glue_authority_sha256,
        expected_tool_glue_version=expected_tool_glue_version,
        transition_path=transition_path,
        transition_candidate=transition_candidate,
        expected_transition_sha256=expected_transition_sha256,
        expected_transition_preimage_active_parent_sha256=(
            expected_transition_preimage_active_parent_sha256
        ),
        transition_rollback_copy=transition_rollback_copy,
        archive_manifest_path=archive_manifest_path,
        archive_manifest_candidate=archive_manifest_candidate,
        expected_archive_manifest_sha256=expected_archive_manifest_sha256,
        archive_manifest_rollback_copy=archive_manifest_rollback_copy,
    )


def _load_marker_and_journal(projection_path: Path) -> tuple[Path, dict[str, Any]] | None:
    marker_path = _promotion_marker_path(projection_path.resolve()).resolve()
    if not marker_path.exists():
        return None
    marker = _load_json(marker_path)
    journal_path = Path(str(marker.get("journal_path", ""))).resolve()
    if not journal_path.is_file():
        raise RuntimeError("science promotion marker journal is missing")
    journal = _load_json(journal_path)
    if journal.get("schema_version") != TRANSACTION_SCHEMA:
        raise RuntimeError("science promotion journal schema is invalid")
    bound_projection = Path(str(journal.get("projection_path", ""))).resolve()
    if bound_projection != projection_path.resolve():
        raise RuntimeError("science promotion journal does not bind recovery target")
    return journal_path, journal


def _journal_target_states(
    journal: Mapping[str, Any],
) -> list[tuple[str, Path, str, str, str | None]]:
    active_committed = (
        str(journal["active_parent_committed_sha256"])
        if journal.get("active_parent_committed_sha256") is not None
        else None
    )
    projection_committed = (
        str(journal["projection_committed_sha256"])
        if journal.get("projection_committed_sha256") is not None
        else None
    )
    targets = [
        (
            "active-parent",
            Path(str(journal["active_parent_path"])).resolve(),
            str(journal.get("active_parent_preimage_sha256", active_committed or "")),
            str(journal.get("active_parent_candidate_sha256", active_committed or "")),
            active_committed,
        ),
        (
            "projection",
            Path(str(journal["projection_path"])).resolve(),
            str(journal.get("projection_preimage_sha256", projection_committed or "")),
            str(journal.get("projection_candidate_sha256", projection_committed or "")),
            projection_committed,
        ),
    ]
    if journal.get("transition_path") is not None:
        targets.extend(
            [
                (
                    "archive-manifest",
                    Path(str(journal["archive_manifest_path"])).resolve(),
                    str(journal["archive_manifest_preimage_sha256"]),
                    str(journal["archive_manifest_candidate_sha256"]),
                    (
                        str(journal["archive_manifest_committed_sha256"])
                        if journal.get("archive_manifest_committed_sha256") is not None
                        else None
                    ),
                ),
                (
                    "transition",
                    Path(str(journal["transition_path"])).resolve(),
                    str(journal["transition_preimage_sha256"]),
                    str(journal["transition_candidate_sha256"]),
                    (
                        str(journal["transition_committed_sha256"])
                        if journal.get("transition_committed_sha256") is not None
                        else None
                    ),
                ),
            ]
        )
    return targets


def _target_state_defects(
    journal: Mapping[str, Any],
    *,
    committed: bool,
) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    for label, path, preimage, candidate, committed_sha256 in _journal_target_states(journal):
        observed = _sha256(path) if path.is_file() else None
        allowed = {committed_sha256} if committed else {preimage, candidate}
        if None in allowed or observed not in allowed:
            defects.append(
                _dependency_defect(
                    "SCIENCE_" + label.upper().replace("-", "_") + "_POSTIMAGE_DRIFT",
                    (
                        f"{label} target does not match COMMITTED postimage"
                        if committed
                        else f"{label} target matches neither transaction preimage nor candidate"
                    ),
                    path=str(path),
                    expected=committed_sha256 if committed else sorted(allowed - {None}),
                    observed=observed,
                )
            )
    return defects


def _verify_target_state(
    journal: Mapping[str, Any],
    *,
    committed: bool,
) -> None:
    defects = _target_state_defects(journal, committed=committed)
    if defects:
        raise RuntimeError("; ".join(str(defect["message"]) for defect in defects))


def _verify_companion_semantics(
    journal: Mapping[str, Any],
    *,
    restored: bool,
) -> dict[str, Any]:
    if journal.get("transition_path") is None:
        return {}
    active_parent_path = Path(str(journal["active_parent_path"])).resolve()
    transition_expected = str(
        journal[
            "transition_preimage_active_parent_sha256"
            if restored
            else "transition_candidate_active_parent_sha256"
        ]
    )
    archive_expected = str(
        journal[
            "active_parent_preimage_sha256"
            if restored
            else "active_parent_candidate_sha256"
        ]
    )
    transition_binding = validate_science_transition_active_parent_binding(
        Path(str(journal["transition_path"])).read_text(encoding="utf-8"),
        expected_active_parent_path=active_parent_path,
        expected_active_parent_sha256=transition_expected,
    )
    archive_binding = validate_science_archive_publication_binding(
        _load_json(Path(str(journal["archive_manifest_path"]))),
        expected_active_parent_path=active_parent_path,
        expected_active_parent_sha256=archive_expected,
    )
    return {
        "transition_binding": transition_binding,
        "archive_binding": archive_binding,
    }


def recover_interrupted_promotion(projection_path: Path) -> dict[str, Any]:
    """Recover or finalize the one durable transaction bound to ``projection_path``."""

    projection_path = projection_path.resolve()
    lease = _acquire_promotion_lease(projection_path)
    try:
        loaded = _load_marker_and_journal(projection_path)
        if loaded is None:
            return {
                "schema_version": RESULT_SCHEMA,
                "status": "NO_INTERRUPTED_TRANSACTION",
                "projection_path": str(projection_path),
                "completion_claim_allowed": False,
            }
        journal_path, journal = loaded
        status_value = str(journal.get("status"))
        marker_path = _promotion_marker_path(projection_path)
        if status_value == COMMITTED:
            _verify_target_state(journal, committed=True)
            companion_bindings = _verify_companion_semantics(journal, restored=False)
            load_science_active_parent(projection_path)
            marker_path.unlink(missing_ok=True)
            result = _journal_receipt(journal, journal_path)
            result["status"] = "COMMITTED_LOCK_CLEARED"
            result.update(companion_bindings)
            return result
        if status_value in {ROLLED_BACK, ROLLED_BACK_AFTER_CRASH}:
            specs = _preimage_specs(journal)
            invalid = _validate_preimages(specs)
            if invalid:
                _raise_group("science rollback preimages are invalid", invalid)
            for label, _source, target, expected in specs:
                if not target.is_file() or _sha256(target) != expected:
                    raise RuntimeError(f"{label} target does not match persisted rollback")
            companion_bindings = _verify_companion_semantics(journal, restored=True)
            marker_path.unlink(missing_ok=True)
            result = _journal_receipt(journal, journal_path)
            result.update(companion_bindings)
            return result
        if status_value not in {PREPARED, APPLYING, ROLLING_BACK}:
            raise RuntimeError(f"unsupported science promotion journal state: {status_value}")

        specs = _preimage_specs(journal)
        invalid = _validate_preimages(specs)
        if invalid:
            _raise_group("science rollback preimages are invalid", invalid)
        _verify_target_state(journal, committed=False)
        errors = _restore_preimages(specs)
        if errors:
            _raise_group("science recovery could not restore every target", errors)
        for label, _source, target, expected in specs:
            if not target.is_file() or _sha256(target) != expected:
                raise RuntimeError(f"{label} recovery target failed readback")
        companion_bindings = _verify_companion_semantics(journal, restored=True)
        journal["status"] = ROLLED_BACK_AFTER_CRASH
        _write_json_atomic(journal_path, journal)
        marker_path.unlink(missing_ok=True)
        result = _journal_receipt(journal, journal_path)
        result.update(companion_bindings)
        return result
    finally:
        lease.release()


def rollback_science_revision_transaction(
    *,
    journal_path: Path,
    projection_path: Path | None = None,
) -> dict[str, Any]:
    """Idempotently restore a committed science transaction's exact preimages."""

    journal_path = journal_path.resolve()
    journal = _load_json(journal_path)
    if journal.get("schema_version") != TRANSACTION_SCHEMA:
        raise RuntimeError("science promotion journal schema is invalid")
    bound_projection = Path(str(journal.get("projection_path", ""))).resolve()
    if projection_path is not None and projection_path.resolve() != bound_projection:
        raise RuntimeError("science promotion journal does not bind rollback target")
    lease = _acquire_promotion_lease(bound_projection)
    try:
        journal = _load_json(journal_path)
        status_value = str(journal.get("status"))
        marker_path = _promotion_marker_path(bound_projection)
        if status_value in {ROLLED_BACK, ROLLED_BACK_AFTER_CRASH}:
            specs = _preimage_specs(journal)
            invalid = _validate_preimages(specs)
            if invalid:
                _raise_group("science rollback preimages are invalid", invalid)
            for label, _source, target, expected in specs:
                if not target.is_file() or _sha256(target) != expected:
                    raise RuntimeError(f"{label} target does not match persisted rollback")
            companion_bindings = _verify_companion_semantics(journal, restored=True)
            marker_path.unlink(missing_ok=True)
            result = _journal_receipt(journal, journal_path)
            result.update(companion_bindings)
            return result
        if status_value != COMMITTED:
            raise RuntimeError("explicit science rollback requires a COMMITTED transaction")
        if marker_path.exists():
            raise RuntimeError("recover the active science transaction before explicit rollback")
        postimage_defects = _target_state_defects(journal, committed=True)
        if postimage_defects:
            raise SciencePublicationError(
                "SCIENCE_ROLLBACK_POSTIMAGE_DRIFT",
                "explicit science rollback refused because a COMMITTED postimage drifted",
                defects=postimage_defects,
                receipt={
                    "transaction_status": status_value,
                    "transaction_journal": str(journal_path),
                },
            )
        try:
            _verify_companion_semantics(journal, restored=False)
        except Exception as exc:
            raise SciencePublicationError(
                "SCIENCE_ROLLBACK_POSTIMAGE_DRIFT",
                "explicit science rollback refused because COMMITTED semantics drifted",
                defects=[
                    _dependency_defect(
                        "SCIENCE_ROLLBACK_SEMANTIC_DRIFT",
                        str(exc),
                    )
                ],
                receipt={
                    "transaction_status": status_value,
                    "transaction_journal": str(journal_path),
                },
            ) from exc
        specs = _preimage_specs(journal)
        invalid = _validate_preimages(specs)
        if invalid:
            _raise_group("science rollback preimages are invalid", invalid)
        _write_json_atomic(marker_path, _marker_payload(journal_path))
        journal["status"] = ROLLING_BACK
        _write_json_atomic(journal_path, journal)
        errors = _restore_preimages(specs)
        if errors:
            _raise_group("science rollback could not restore every target", errors)
        for label, _source, target, expected in specs:
            if not target.is_file() or _sha256(target) != expected:
                raise RuntimeError(f"{label} rollback target failed readback")
        companion_bindings = _verify_companion_semantics(journal, restored=True)
        journal["status"] = ROLLED_BACK
        _write_json_atomic(journal_path, journal)
        marker_path.unlink(missing_ok=True)
        result = _journal_receipt(journal, journal_path)
        result.update(companion_bindings)
        return result
    finally:
        lease.release()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", type=Path, default=SCIENCE_ACTIVE_PARENT_PROJECTION_PATH)
    parser.add_argument("--revision-evidence", type=Path, action="append")
    parser.add_argument("--event-ref", action="append")
    parser.add_argument("--rollback-copy", type=Path)
    parser.add_argument("--expected-projection-sha256")
    parser.add_argument("--candidate-active-parent", type=Path)
    parser.add_argument("--expected-candidate-active-parent-sha256")
    parser.add_argument("--expected-active-parent-sha256")
    parser.add_argument("--active-parent-rollback-copy", type=Path)
    parser.add_argument("--transaction-directory", type=Path)
    parser.add_argument(
        "--tool-glue-authority",
        type=Path,
        default=DEFAULT_TOOL_GLUE_AUTHORITY_PATH,
    )
    parser.add_argument(
        "--expected-tool-glue-authority-sha256",
        default=DEFAULT_TOOL_GLUE_V34_SHA256,
    )
    parser.add_argument("--expected-tool-glue-version", default=DEFAULT_TOOL_GLUE_VERSION)
    parser.add_argument("--transition-path", type=Path)
    parser.add_argument("--transition-candidate", type=Path)
    parser.add_argument("--expected-transition-sha256")
    parser.add_argument("--expected-transition-preimage-active-parent-sha256")
    parser.add_argument("--transition-rollback-copy", type=Path)
    parser.add_argument("--archive-manifest-path", type=Path)
    parser.add_argument("--archive-manifest-candidate", type=Path)
    parser.add_argument("--expected-archive-manifest-sha256")
    parser.add_argument("--archive-manifest-rollback-copy", type=Path)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--rollback-journal", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.recover:
            result = recover_interrupted_promotion(args.projection)
        elif args.rollback_journal is not None:
            result = rollback_science_revision_transaction(
                journal_path=args.rollback_journal,
                projection_path=args.projection,
            )
        else:
            missing = [
                name
                for name, value in (
                    ("--revision-evidence", args.revision_evidence),
                    ("--event-ref", args.event_ref),
                    ("--rollback-copy", args.rollback_copy),
                )
                if not value
            ]
            if missing:
                raise SciencePublicationError(
                    "CLI_ARGUMENTS_INCOMPLETE",
                    "publication arguments are incomplete: " + ", ".join(missing),
                )
            result = promote_revision_chain(
                projection_path=args.projection,
                evidence_paths=args.revision_evidence,
                event_refs=args.event_ref,
                rollback_copy=args.rollback_copy,
                expected_projection_sha256=args.expected_projection_sha256,
                candidate_active_parent=args.candidate_active_parent,
                expected_candidate_active_parent_sha256=(
                    args.expected_candidate_active_parent_sha256
                ),
                expected_active_parent_sha256=args.expected_active_parent_sha256,
                active_parent_rollback_copy=args.active_parent_rollback_copy,
                transaction_directory=args.transaction_directory,
                tool_glue_authority_path=args.tool_glue_authority,
                expected_tool_glue_authority_sha256=(
                    args.expected_tool_glue_authority_sha256
                ),
                expected_tool_glue_version=args.expected_tool_glue_version,
                transition_path=args.transition_path,
                transition_candidate=args.transition_candidate,
                expected_transition_sha256=args.expected_transition_sha256,
                expected_transition_preimage_active_parent_sha256=(
                    args.expected_transition_preimage_active_parent_sha256
                ),
                transition_rollback_copy=args.transition_rollback_copy,
                archive_manifest_path=args.archive_manifest_path,
                archive_manifest_candidate=args.archive_manifest_candidate,
                expected_archive_manifest_sha256=args.expected_archive_manifest_sha256,
                archive_manifest_rollback_copy=args.archive_manifest_rollback_copy,
            )
    except SciencePublicationError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
