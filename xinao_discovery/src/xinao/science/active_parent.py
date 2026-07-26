"""Fail-closed consumer for the current science active-parent projection.

The human science specification is authoritative. The JSON projection is only
an integrity-bound selector that keeps current science and the legacy G0-G8
parent in separate namespaces.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCIENCE_ACTIVE_PARENT_PROJECTION_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\mainline_science_current"
    r"\active_parent.current.json"
)

_REQUIRED_SCIENCE_MARKERS = (
    "CURRENT_ACTIVE_PARENT / XINAO_SCIENCE_PROTOCOL_ACTIVE",
    "LEGACY_PARENT_G0_G8 = SUPERSEDED_AS_ACTIVE_PARENT（当前）",  # noqa: RUF001
    "XINAO_SCIENCE_EPISODE_ALLOWED",
    "ExposureInventory",
    "ProtocolPin",
    "GlobalTrialLedger",
    "knowledge_cutoff < target openTime",
)
_FORBIDDEN_CURRENT_MARKERS = (
    "DRAFT_FOR_OPERATOR_REVIEW",
    "XINAO_SCIENCE_PROTOCOL_CANDIDATE",
    "尚未执行 ParentScopeSwitch",
    "本次不执行",
)


class ScienceActiveParentError(ValueError):
    """Raised when the current science-parent binding is ambiguous or stale."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScienceActiveParentError(f"{label} must be an object")
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScienceActiveParentError(f"{label} must be a non-empty string")
    return value


def _carrier_path(raw: str) -> Path:
    """Resolve host authority refs through the worker's read-only carrier mounts."""

    normalized = raw.replace("\\", "/")
    mainline_host = "C:/Users/xx363/Desktop/主线"
    runtime_host = "D:/XINAO_RESEARCH_RUNTIME"

    def suffix(root: str) -> str | None:
        folded = normalized.casefold()
        root_folded = root.casefold()
        if folded == root_folded:
            return ""
        if folded.startswith(root_folded + "/"):
            return normalized[len(root) + 1 :]
        return None

    mainline_suffix = suffix(mainline_host)
    if mainline_suffix is not None:
        if os.name == "nt":
            return Path(raw)
        return (
            Path("/mainline", *mainline_suffix.split("/")) if mainline_suffix else Path("/mainline")
        )
    runtime_suffix = suffix(runtime_host)
    if runtime_suffix is not None:
        if os.name == "nt":
            return Path(raw)
        return (
            Path("/evidence", *runtime_suffix.split("/")) if runtime_suffix else Path("/evidence")
        )

    if normalized == "/mainline" or normalized.startswith("/mainline/"):
        relative = normalized.removeprefix("/mainline").lstrip("/")
        if os.name == "nt":
            return (
                Path(r"C:\Users\xx363\Desktop\主线", *relative.split("/"))
                if relative
                else Path(r"C:\Users\xx363\Desktop\主线")
            )
        return Path(normalized)
    if normalized == "/evidence" or normalized.startswith("/evidence/"):
        relative = normalized.removeprefix("/evidence").lstrip("/")
        if os.name == "nt":
            return (
                Path(r"D:\XINAO_RESEARCH_RUNTIME", *relative.split("/"))
                if relative
                else Path(r"D:\XINAO_RESEARCH_RUNTIME")
            )
        return Path(normalized)
    return Path(raw)


def resolve_science_carrier_path(raw: str) -> Path:
    """Resolve one authority reference on either the host or worker carrier."""

    return _carrier_path(raw)


def validate_science_active_parent_projection(payload: Mapping[str, Any]) -> None:
    """Validate the current/legacy scope split without touching the filesystem."""

    if payload.get("schema_version") != "xinao.science_active_parent_projection.v1":
        raise ScienceActiveParentError("unsupported science active-parent projection schema")
    if payload.get("sentinel") != "SENTINEL:XINAO_SCIENCE_ACTIVE_PARENT_PROJECTION_V1":
        raise ScienceActiveParentError("science active-parent sentinel mismatch")
    if (
        payload.get("authority") is not False
        or payload.get("completion_claim_allowed") is not False
    ):
        raise ScienceActiveParentError("science projection must be non-authoritative")

    active = _mapping(payload.get("active_parent"), "active_parent")
    if (
        active.get("id") != "XINAO_SCIENCE_PROTOCOL_ACTIVE"
        or active.get("status") != "CURRENT_ACTIVE_PARENT"
    ):
        raise ScienceActiveParentError("current science parent is not uniquely active")
    _required_text(active.get("path"), "active_parent.path")
    _required_text(active.get("sha256"), "active_parent.sha256")

    legacy = _mapping(payload.get("legacy_parent"), "legacy_parent")
    if (
        legacy.get("status") != "SUPERSEDED_AS_ACTIVE_PARENT"
        or legacy.get("authority_scope") != "LEGACY_PARENT_G0_G8"
    ):
        raise ScienceActiveParentError("legacy mixed parent regained current authority")

    legacy_contract = _mapping(
        payload.get("legacy_admission_contract"), "legacy_admission_contract"
    )
    if legacy_contract.get("authority_scope") != "LEGACY_PARENT_G0_G8":
        raise ScienceActiveParentError("legacy G0-G8 admission contract escaped its scope")

    gate = _mapping(payload.get("science_episode_gate"), "science_episode_gate")
    if (
        gate.get("id") != "XINAO_SCIENCE_EPISODE_ALLOWED"
        or gate.get("old_g6_equivalent") is not False
    ):
        raise ScienceActiveParentError("science episode gate was conflated with old G6")
    if list(gate.get("first_frontier") or [])[:3] != [
        "ExposureInventory",
        "bounded_ResearchQuestion",
        "ProtocolPin",
    ]:
        raise ScienceActiveParentError("first science frontier is not pinned")

    switch = _mapping(payload.get("parent_scope_switch"), "parent_scope_switch")
    _required_text(switch.get("run_id"), "parent_scope_switch.run_id")
    if switch.get("status") != "PERFORMED" or switch.get("history_rewritten") is not False:
        raise ScienceActiveParentError("ParentScopeSwitch is incomplete or rewrote history")
    event_ref = _required_text(switch.get("event_ref"), "parent_scope_switch.event_ref")
    if event_ref == "PENDING_EVENT_APPEND":
        raise ScienceActiveParentError("ParentScopeSwitch event has not been appended")

    forbidden = set(
        _mapping(payload.get("legacy_status_preservation"), "legacy_status_preservation").get(
            "forbidden_equivalence"
        )
        or []
    )
    if "EQUIVALENT_TO_XINAO_SCIENCE_EPISODE_ALLOWED" not in forbidden:
        raise ScienceActiveParentError("legacy/current equivalence guard is missing")


def _verify_parent_scope_switch(
    payload: Mapping[str, Any],
    active: Mapping[str, Any],
    legacy: Mapping[str, Any],
) -> None:
    switch = _mapping(payload.get("parent_scope_switch"), "parent_scope_switch")
    switch_run_id = _required_text(switch.get("run_id"), "parent_scope_switch.run_id")
    event_ref = _required_text(switch.get("event_ref"), "parent_scope_switch.event_ref")
    marker = "#event_id="
    if marker not in event_ref:
        raise ScienceActiveParentError("ParentScopeSwitch event ref has no event identity")
    raw_event_path, event_id = event_ref.rsplit(marker, 1)
    event_path = _carrier_path(raw_event_path)
    if not event_path.is_file():
        raise ScienceActiveParentError("ParentScopeSwitch event log is missing")
    found = False
    for line in event_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_id") == event_id:
            found = (
                event.get("kind") == "action"
                and event.get("phase") == "PARENT_SCOPE_SWITCH"
                and event.get("run_id") == switch_run_id
            )
            break
    if not found:
        raise ScienceActiveParentError("ParentScopeSwitch event identity is not present")

    evidence_path = _carrier_path(
        _required_text(
            switch.get("switch_evidence_ref"),
            "parent_scope_switch.switch_evidence_ref",
        )
    )
    expected_evidence_hash = _required_text(
        switch.get("switch_evidence_sha256"),
        "parent_scope_switch.switch_evidence_sha256",
    ).lower()
    if not evidence_path.is_file() or _sha256(evidence_path) != expected_evidence_hash:
        raise ScienceActiveParentError("ParentScopeSwitch evidence is missing or drifted")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScienceActiveParentError("ParentScopeSwitch evidence is invalid") from exc
    if (
        evidence.get("schema_version") != "xinao.parent_scope_switch.v1"
        or evidence.get("status") != "PERFORMED"
        or evidence.get("legacy_parent", {}).get("sha256") != legacy.get("sha256")
        or evidence.get("legacy_status_preservation", {}).get("history_rewritten") is not False
    ):
        raise ScienceActiveParentError(
            "ParentScopeSwitch evidence does not bind its immutable identities"
        )

    switch_active_hash = _required_text(
        _mapping(evidence.get("active_parent"), "ParentScopeSwitch.active_parent").get("sha256"),
        "ParentScopeSwitch.active_parent.sha256",
    ).lower()
    current_active_hash = _required_text(active.get("sha256"), "active_parent.sha256").lower()
    revisions = payload.get("science_revision_chain")
    if switch_active_hash == current_active_hash and revisions in (None, []):
        return
    if not isinstance(revisions, list) or not revisions:
        raise ScienceActiveParentError(
            "current science identity drifted without an append-only revision chain"
        )

    expected_predecessor = switch_active_hash
    seen_hashes = {switch_active_hash}
    switch_evidence_ref = str(switch.get("switch_evidence_ref"))
    switch_evidence_sha256 = expected_evidence_hash
    for index, raw_revision in enumerate(revisions):
        revision = _mapping(raw_revision, f"science_revision_chain[{index}]")
        if revision.get("status") != "APPLIED":
            raise ScienceActiveParentError("science revision is not applied")
        revision_run_id = _required_text(
            revision.get("run_id"), f"science_revision_chain[{index}].run_id"
        )
        revision_event_ref = _required_text(
            revision.get("event_ref"), f"science_revision_chain[{index}].event_ref"
        )
        revision_evidence_ref = _required_text(
            revision.get("revision_evidence_ref"),
            f"science_revision_chain[{index}].revision_evidence_ref",
        )
        revision_evidence_hash = _required_text(
            revision.get("revision_evidence_sha256"),
            f"science_revision_chain[{index}].revision_evidence_sha256",
        ).lower()

        revision_evidence_path = _carrier_path(revision_evidence_ref)
        if (
            not revision_evidence_path.is_file()
            or _sha256(revision_evidence_path) != revision_evidence_hash
        ):
            raise ScienceActiveParentError("science revision evidence is missing or drifted")
        try:
            revision_evidence = json.loads(revision_evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScienceActiveParentError("science revision evidence is invalid") from exc

        predecessor = _mapping(
            revision_evidence.get("predecessor_active_parent"),
            "science_revision.predecessor_active_parent",
        )
        revised_active = _mapping(
            revision_evidence.get("active_parent"), "science_revision.active_parent"
        )
        revised_hash = _required_text(
            revised_active.get("sha256"), "science_revision.active_parent.sha256"
        ).lower()
        switch_binding = _mapping(
            revision_evidence.get("parent_scope_switch"),
            "science_revision.parent_scope_switch",
        )
        if (
            revision_evidence.get("schema_version") != "xinao.science_revision.v1"
            or revision_evidence.get("status") != "APPLIED"
            or revision_evidence.get("run_id") != revision_run_id
            or _required_text(
                predecessor.get("sha256"),
                "science_revision.predecessor_active_parent.sha256",
            ).lower()
            != expected_predecessor
            or revised_active.get("id") != active.get("id")
            or revised_active.get("status") != active.get("status")
            or revised_active.get("path") != active.get("path")
            or switch_binding.get("evidence_ref") != switch_evidence_ref
            or str(switch_binding.get("evidence_sha256", "")).lower() != switch_evidence_sha256
            or revision_evidence.get("legacy_status_preservation", {}).get("history_rewritten")
            is not False
            or revision_evidence.get("completion_claim_allowed") is not False
        ):
            raise ScienceActiveParentError("science revision identity chain is inconsistent")
        if revised_hash in seen_hashes:
            raise ScienceActiveParentError("science revision identity chain contains a cycle")

        snapshot = _mapping(
            revision_evidence.get("frozen_snapshot"), "science_revision.frozen_snapshot"
        )
        snapshot_path = _carrier_path(
            _required_text(snapshot.get("path"), "science_revision.frozen_snapshot.path")
        )
        if (
            str(snapshot.get("sha256", "")).lower() != revised_hash
            or not snapshot_path.is_file()
            or _sha256(snapshot_path) != revised_hash
        ):
            raise ScienceActiveParentError("science revision snapshot is missing or drifted")

        maintenance_record = _mapping(
            revision_evidence.get("maintenance_record"),
            "science_revision.maintenance_record",
        )
        maintenance_path = _carrier_path(
            _required_text(
                maintenance_record.get("path"),
                "science_revision.maintenance_record.path",
            )
        )
        maintenance_hash = _required_text(
            maintenance_record.get("sha256"),
            "science_revision.maintenance_record.sha256",
        ).lower()
        if not maintenance_path.is_file() or _sha256(maintenance_path) != maintenance_hash:
            raise ScienceActiveParentError(
                "science revision maintenance record is missing or drifted"
            )

        marker = "#event_id="
        if marker not in revision_event_ref:
            raise ScienceActiveParentError("science revision event ref has no event identity")
        raw_revision_event_path, revision_event_id = revision_event_ref.rsplit(marker, 1)
        revision_event_path = _carrier_path(raw_revision_event_path)
        if not revision_event_path.is_file():
            raise ScienceActiveParentError("science revision event log is missing")
        revision_event = None
        for line in revision_event_path.read_text(encoding="utf-8").splitlines():
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("event_id") == revision_event_id:
                revision_event = candidate
                break
        expected_evidence_ref = f"{revision_evidence_ref}#sha256={revision_evidence_hash}"
        if (
            revision_event is None
            or revision_event.get("kind") != "action"
            or revision_event.get("phase") != "SCIENCE_REVISION"
            or revision_event.get("run_id") != revision_run_id
            or expected_evidence_ref not in (revision_event.get("evidence_refs") or [])
        ):
            raise ScienceActiveParentError("science revision event identity is not present")

        expected_predecessor = revised_hash
        seen_hashes.add(revised_hash)

    if expected_predecessor != current_active_hash:
        raise ScienceActiveParentError(
            "science revision chain does not terminate at the current active parent"
        )


def load_science_active_parent(
    projection_path: Path = SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
) -> dict[str, Any]:
    """Load and verify the live projection and every referenced human source."""

    projection_path = _carrier_path(str(projection_path))
    try:
        payload = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceActiveParentError(
            f"cannot load science active-parent projection: {projection_path}"
        ) from exc
    validate_science_active_parent_projection(payload)
    _verify_parent_scope_switch(
        payload,
        _mapping(payload.get("active_parent"), "active_parent"),
        _mapping(payload.get("legacy_parent"), "legacy_parent"),
    )

    for key in (
        "active_parent",
        "stable_entry",
        "software_foundation",
        "background_contract",
        "legacy_parent",
        "legacy_admission_contract",
    ):
        binding = _mapping(payload.get(key), key)
        path = _carrier_path(_required_text(binding.get("path"), f"{key}.path"))
        expected = _required_text(binding.get("sha256"), f"{key}.sha256").lower()
        if not path.is_file():
            raise ScienceActiveParentError(f"{key} source is missing: {path}")
        if _sha256(path) != expected:
            raise ScienceActiveParentError(f"{key} source hash drifted: {path}")

    science_text = _carrier_path(str(payload["active_parent"]["path"])).read_text(encoding="utf-8")
    for marker in _REQUIRED_SCIENCE_MARKERS:
        if marker not in science_text:
            raise ScienceActiveParentError(f"science specification marker missing: {marker}")
    for marker in _FORBIDDEN_CURRENT_MARKERS:
        if marker in science_text:
            raise ScienceActiveParentError(f"candidate marker remains active: {marker}")

    entry_text = _carrier_path(str(payload["stable_entry"]["path"])).read_text(encoding="utf-8")
    if (
        "《新澳严格数学科学研究模式——独立融合稿》.txt" not in entry_text
        or "LEGACY_PARENT_G0_G8 / SUPERSEDED_AS_ACTIVE_PARENT" not in entry_text
    ):
        raise ScienceActiveParentError("stable entry does not select the science parent")

    software_text = _carrier_path(str(payload["software_foundation"]["path"])).read_text(
        encoding="utf-8"
    )
    required_software_markers = (
        "科学 active-parent",
        "LEGACY_PARENT_G0_G8",
        "不取得当前父目标或全局启动门地位",
    )
    if payload["software_foundation"][
        "relationship"
    ] != "REUSABLE_INSTRUMENT_FOUNDATION_NOT_PARENT_GATE" or any(
        marker not in software_text for marker in required_software_markers
    ):
        raise ScienceActiveParentError("software foundation still has ambiguous parent authority")

    return {
        "schema_version": "xinao.science_active_parent_resolution.v1",
        "status": "READY",
        "active_parent": dict(payload["active_parent"]),
        "background_contract": dict(payload["background_contract"]),
        "legacy_parent": dict(payload["legacy_parent"]),
        "science_episode_gate": dict(payload["science_episode_gate"]),
        "parent_scope_switch": dict(payload["parent_scope_switch"]),
        "science_revision_chain": list(payload.get("science_revision_chain") or []),
        "completion_claim_allowed": False,
    }


__all__ = [
    "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH",
    "ScienceActiveParentError",
    "load_science_active_parent",
    "resolve_science_carrier_path",
    "validate_science_active_parent_projection",
]
