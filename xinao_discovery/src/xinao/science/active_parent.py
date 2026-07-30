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

_COMMON_REQUIRED_SCIENCE_MARKERS = (
    "LEGACY_PARENT_G0_G8 = SUPERSEDED_AS_ACTIVE_PARENT（当前）",  # noqa: RUF001
    "XINAO_SCIENCE_EPISODE_ALLOWED",
    "ExposureInventory",
    "ProtocolPin",
    "GlobalTrialLedger",
    "knowledge_cutoff < target openTime",
)
_LEGACY_DEPLOYED_IDENTITY_MARKERS = ("CURRENT_ACTIVE_PARENT / XINAO_SCIENCE_PROTOCOL_ACTIVE",)
_FORMAL_FUSION_VERSION_DECLARATION_PREFIX = "版本：正式融合稿 "  # noqa: RUF001
_OPEN_RESEARCH_VERSION_MARKERS = (
    "版本：正式融合稿 v1.9",  # noqa: RUF001
    "版本：正式融合稿 v1.10",  # noqa: RUF001
)
_OPEN_RESEARCH_CONTENT_ROLE_MARKERS = (
    "文档角色：XINAO_SCIENCE_PARENT_CONTENT",  # noqa: RUF001
    "候选副本不因正文自取部署权威",
    "CAS、外部 revision evidence 与消费者回读共同成立时",
    "该字节实例才取得 CURRENT_ACTIVE_PARENT 身份",
    "ParentRealityObject",
    "APPLICABLE_PRE_PROTOCOL_SET_COMPLETE",
)
_OPEN_RESEARCH_VERSION_REQUIRED_MARKERS = {
    "版本：正式融合稿 v1.10": (  # noqa: RUF001
        "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT",
        "MATURATION_REQUIRED",
        "下一次同依赖生产调用",
    ),
}
_V110_FORMAL_FUSION_VERSION_MARKER = "版本：正式融合稿 v1.10"  # noqa: RUF001
_MATURATION_INVARIANT_MARKER = "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT"
_MATURATION_ENGINEERING_ONE_HOME_MARKER = "本节是该不变量的软件工程唯一正向定义"
_TRANSITION_ACTIVE_PARENT_LABEL = "唯一科学父目标："  # noqa: RUF001
_TRANSITION_SHA256_PREFIX = "SHA256："  # noqa: RUF001
_OPEN_RESEARCH_FORBIDDEN_SELF_DECLARATIONS = _LEGACY_DEPLOYED_IDENTITY_MARKERS
_FORBIDDEN_CURRENT_MARKERS = (
    "DRAFT_FOR_OPERATOR_REVIEW",
    "XINAO_SCIENCE_PROTOCOL_CANDIDATE",
    "尚未执行 ParentScopeSwitch",
    "本次不执行",
)
_LEGACY_FIRST_FRONTIER = [
    "ExposureInventory",
    "bounded_ResearchQuestion",
    "ProtocolPin",
]
_OPEN_RESEARCH_FIRST_FRONTIER = [
    "ParentRealityObject",
    "ObjectContact",
    "ExplorationTrace",
]


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


def _verify_science_text_contract(science_text: str) -> bool:
    """Verify the content-role contract and return whether this is open research."""

    declared_versions = tuple(
        line
        for line in science_text.splitlines()
        if _FORMAL_FUSION_VERSION_DECLARATION_PREFIX in line
    )
    open_research_marker_presence = tuple(
        marker in science_text for marker in _OPEN_RESEARCH_CONTENT_ROLE_MARKERS
    )
    if (any(open_research_marker_presence) or declared_versions) and not all(
        open_research_marker_presence
    ):
        missing_marker = next(
            marker
            for marker, present in zip(
                _OPEN_RESEARCH_CONTENT_ROLE_MARKERS,
                open_research_marker_presence,
                strict=True,
            )
            if not present
        )
        raise ScienceActiveParentError(
            f"incomplete open-research specification marker set; marker missing: {missing_marker}"
        )
    is_open_research_revision = all(open_research_marker_presence)
    if is_open_research_revision:
        if not declared_versions:
            raise ScienceActiveParentError(
                "incomplete open-research specification marker set; marker missing: "
                "supported formal-fusion version"
            )
        if len(declared_versions) != 1:
            raise ScienceActiveParentError(
                "open-research specification has multiple formal-fusion version markers"
            )
        declared_version = declared_versions[0]
        if declared_version not in _OPEN_RESEARCH_VERSION_MARKERS:
            raise ScienceActiveParentError(f"unsupported formal-fusion version: {declared_version}")
        for marker in _OPEN_RESEARCH_VERSION_REQUIRED_MARKERS.get(declared_version, ()):
            if marker not in science_text:
                raise ScienceActiveParentError(f"science specification marker missing: {marker}")
    required_science_markers = _COMMON_REQUIRED_SCIENCE_MARKERS + (
        _OPEN_RESEARCH_CONTENT_ROLE_MARKERS
        if is_open_research_revision
        else _LEGACY_DEPLOYED_IDENTITY_MARKERS
    )
    for marker in required_science_markers:
        if marker not in science_text:
            raise ScienceActiveParentError(f"science specification marker missing: {marker}")
    for marker in _FORBIDDEN_CURRENT_MARKERS:
        if marker in science_text:
            raise ScienceActiveParentError(f"candidate marker remains active: {marker}")
    if is_open_research_revision:
        for marker in _OPEN_RESEARCH_FORBIDDEN_SELF_DECLARATIONS:
            if marker in science_text:
                raise ScienceActiveParentError(
                    f"open-research content self-declares deployment identity: {marker}"
                )
    return is_open_research_revision


def _verify_v110_software_foundation_contract(software_text: str) -> None:
    """Bind v1.10 to one semantic engineering home without pinning carrier bytes."""

    for label, marker in (
        ("maturation invariant", _MATURATION_INVARIANT_MARKER),
        ("maturation engineering one-home", _MATURATION_ENGINEERING_ONE_HOME_MARKER),
    ):
        marker_count = software_text.count(marker)
        if marker_count != 1:
            raise ScienceActiveParentError(
                f"v1.10 software foundation must contain exactly one {label} marker; "
                f"observed {marker_count}: {marker}"
            )


def _verify_software_foundation_contract(
    software_binding: Mapping[str, Any],
    software_text: str,
    *,
    requires_maturation_invariant: bool,
) -> None:
    required_software_markers = (
        "科学 active-parent",
        "LEGACY_PARENT_G0_G8",
        "不取得当前父目标或全局启动门地位",
    )
    if software_binding.get(
        "relationship"
    ) != "REUSABLE_INSTRUMENT_FOUNDATION_NOT_PARENT_GATE" or any(
        marker not in software_text for marker in required_software_markers
    ):
        raise ScienceActiveParentError("software foundation still has ambiguous parent authority")
    if requires_maturation_invariant:
        _verify_v110_software_foundation_contract(software_text)


def _verify_committed_promotion_visibility(
    projection_path: Path,
    payload: Mapping[str, Any],
) -> None:
    """Fail closed while a live projection replacement is not durably committed."""

    marker_path = projection_path.with_name(f"{projection_path.name}.promotion.lock")
    if not marker_path.exists():
        return
    if not marker_path.is_file():
        raise ScienceActiveParentError("science active-parent promotion marker is invalid")
    try:
        marker = _mapping(
            json.loads(marker_path.read_text(encoding="utf-8")),
            "science active-parent promotion marker",
        )
        journal_path = _carrier_path(
            _required_text(marker.get("journal_path"), "promotion journal path")
        )
        journal = _mapping(
            json.loads(journal_path.read_text(encoding="utf-8")),
            "science active-parent promotion journal",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceActiveParentError(
            "science active-parent promotion marker is unresolved"
        ) from exc

    if (
        journal.get("schema_version") != "xinao.science_revision_transaction.v1"
        or journal.get("status") != "COMMITTED"
    ):
        raise ScienceActiveParentError(
            "science active-parent promotion transaction is not committed"
        )

    journal_projection_path = _carrier_path(
        _required_text(journal.get("projection_path"), "promotion projection path")
    )
    if journal_projection_path.resolve() != projection_path.resolve():
        raise ScienceActiveParentError(
            "science active-parent promotion journal targets another projection"
        )
    expected_projection_sha256 = _required_text(
        journal.get("projection_committed_sha256"),
        "promotion projection committed sha256",
    ).lower()
    if _sha256(projection_path) != expected_projection_sha256:
        raise ScienceActiveParentError(
            "science active-parent committed projection postimage drifted"
        )

    active_parent_path_value = journal.get("active_parent_path")
    if active_parent_path_value is None:
        active_parent_path_value = _mapping(payload.get("active_parent"), "active_parent").get(
            "path"
        )
    active_parent_path = _carrier_path(
        _required_text(active_parent_path_value, "promotion active-parent path")
    )
    expected_active_parent_sha256 = _required_text(
        journal.get("active_parent_committed_sha256"),
        "promotion active-parent committed sha256",
    ).lower()
    if (
        not active_parent_path.is_file()
        or _sha256(active_parent_path) != expected_active_parent_sha256
    ):
        raise ScienceActiveParentError("science active-parent committed source postimage drifted")


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
    if list(gate.get("first_frontier") or [])[:3] not in (
        _LEGACY_FIRST_FRONTIER,
        _OPEN_RESEARCH_FIRST_FRONTIER,
    ):
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


def validate_science_revision_candidate_binding(
    payload: Mapping[str, Any],
    *,
    science_candidate_path: Path,
    software_foundation_candidate_path: Path,
) -> dict[str, Any]:
    """Read-only preflight for candidate bytes named by a proposed projection.

    Expected digests come from the proposed projection. This deliberately does
    not pin a particular software-foundation release hash in the consumer.
    """

    validate_science_active_parent_projection(payload)
    active = _mapping(payload.get("active_parent"), "active_parent")
    legacy = _mapping(payload.get("legacy_parent"), "legacy_parent")
    software_binding = _mapping(payload.get("software_foundation"), "software_foundation")
    _verify_parent_scope_switch(payload, active, legacy)

    science_candidate_path = _carrier_path(str(science_candidate_path))
    software_foundation_candidate_path = _carrier_path(str(software_foundation_candidate_path))
    expected_science_sha256 = _required_text(active.get("sha256"), "active_parent.sha256").lower()
    expected_software_sha256 = _required_text(
        software_binding.get("sha256"), "software_foundation.sha256"
    ).lower()
    if (
        not science_candidate_path.is_file()
        or _sha256(science_candidate_path) != expected_science_sha256
    ):
        raise ScienceActiveParentError(
            "science candidate does not match the proposed active-parent binding"
        )
    if (
        not software_foundation_candidate_path.is_file()
        or _sha256(software_foundation_candidate_path) != expected_software_sha256
    ):
        raise ScienceActiveParentError(
            "software candidate does not match the proposed foundation binding"
        )

    science_text = science_candidate_path.read_text(encoding="utf-8")
    software_text = software_foundation_candidate_path.read_text(encoding="utf-8")
    is_open_research_revision = _verify_science_text_contract(science_text)
    requires_maturation_invariant = _V110_FORMAL_FUSION_VERSION_MARKER in science_text
    expected_first_frontier = (
        _OPEN_RESEARCH_FIRST_FRONTIER if is_open_research_revision else _LEGACY_FIRST_FRONTIER
    )
    gate = _mapping(payload.get("science_episode_gate"), "science_episode_gate")
    if list(gate.get("first_frontier") or [])[:3] != expected_first_frontier:
        raise ScienceActiveParentError("science text revision and first science frontier disagree")
    _verify_software_foundation_contract(
        software_binding,
        software_text,
        requires_maturation_invariant=requires_maturation_invariant,
    )

    declared_science_version = next(
        (
            line.removeprefix(_FORMAL_FUSION_VERSION_DECLARATION_PREFIX).strip()
            for line in science_text.splitlines()
            if line.startswith(_FORMAL_FUSION_VERSION_DECLARATION_PREFIX)
        ),
        None,
    )
    declared_software_versions = tuple(
        line.removeprefix("版本：").strip()  # noqa: RUF001
        for line in software_text.splitlines()
        if line.startswith("版本：")  # noqa: RUF001
    )
    return {
        "schema_version": "xinao.science_revision_candidate_binding.v1",
        "status": "READY",
        "science_parent_version": declared_science_version,
        "active_parent_sha256": expected_science_sha256,
        "software_foundation_version": (
            declared_software_versions[0] if len(declared_software_versions) == 1 else None
        ),
        "software_foundation_sha256": expected_software_sha256,
        "maturation_invariant_required": requires_maturation_invariant,
        "completion_claim_allowed": False,
    }


def validate_science_transition_active_parent_binding(
    transition_text: str,
    *,
    expected_active_parent_path: Path,
    expected_active_parent_sha256: str,
) -> dict[str, Any]:
    """Parse and verify the transition entry's uniquely labeled parent pin."""

    lines = tuple(line.strip() for line in transition_text.splitlines())
    label_indexes = tuple(
        index for index, line in enumerate(lines) if line == _TRANSITION_ACTIVE_PARENT_LABEL
    )
    if len(label_indexes) != 1:
        raise ScienceActiveParentError(
            "science transition entry must contain exactly one active-parent label"
        )
    label_index = label_indexes[0]
    if label_index + 2 >= len(lines):
        raise ScienceActiveParentError("science transition active-parent pin is incomplete")

    raw_path = lines[label_index + 1]
    raw_sha256 = lines[label_index + 2]
    if len(raw_path) < 3 or not raw_path.startswith("`") or not raw_path.endswith("`"):
        raise ScienceActiveParentError("science transition active-parent path is malformed")
    declared_path = raw_path[1:-1]
    if (
        _carrier_path(declared_path).resolve()
        != _carrier_path(str(expected_active_parent_path)).resolve()
    ):
        raise ScienceActiveParentError("science transition active-parent path does not match")

    expected_sha256 = expected_active_parent_sha256.lower()
    sha256_prefix = f"{_TRANSITION_SHA256_PREFIX}`"
    if not raw_sha256.startswith(sha256_prefix) or not raw_sha256.endswith("`"):
        raise ScienceActiveParentError("science transition active-parent SHA256 is malformed")
    declared_sha256 = raw_sha256[len(sha256_prefix) : -1].lower()
    if len(declared_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in declared_sha256
    ):
        raise ScienceActiveParentError("science transition active-parent SHA256 is malformed")
    if declared_sha256 != expected_sha256:
        raise ScienceActiveParentError("science transition active-parent SHA256 does not match")

    return {
        "schema_version": "xinao.science_transition_active_parent_binding.v1",
        "status": "READY",
        "active_parent_path": str(_carrier_path(declared_path).resolve()),
        "active_parent_sha256": declared_sha256,
        "completion_claim_allowed": False,
    }


def validate_science_archive_publication_binding(
    archive_manifest: Mapping[str, Any],
    *,
    expected_active_parent_path: Path,
    expected_active_parent_sha256: str,
) -> dict[str, Any]:
    """Verify the archive manifest's current publication and immutable snapshot."""

    if (
        archive_manifest.get("schema_version") != "xinao.archive-relocation-manifest.v1"
        or archive_manifest.get("status") != "ARCHIVE_RELOCATION_VERIFIED"
    ):
        raise ScienceActiveParentError("science archive manifest identity is invalid")
    publication = _mapping(
        archive_manifest.get("current_publication"),
        "archive_manifest.current_publication",
    )
    stable_spec_path = _carrier_path(
        _required_text(
            publication.get("stable_spec_path"),
            "archive_manifest.current_publication.stable_spec_path",
        )
    )
    expected_path = _carrier_path(str(expected_active_parent_path))
    if stable_spec_path.resolve() != expected_path.resolve():
        raise ScienceActiveParentError("science archive stable spec path does not match")

    expected_sha256 = expected_active_parent_sha256.lower()
    stable_spec_sha256 = _required_text(
        publication.get("stable_spec_sha256"),
        "archive_manifest.current_publication.stable_spec_sha256",
    ).lower()
    snapshot_sha256 = _required_text(
        publication.get("versioned_snapshot_sha256"),
        "archive_manifest.current_publication.versioned_snapshot_sha256",
    ).lower()
    if stable_spec_sha256 != expected_sha256 or snapshot_sha256 != expected_sha256:
        raise ScienceActiveParentError("science archive publication SHA256 does not match")

    snapshot_path = _carrier_path(
        _required_text(
            publication.get("versioned_snapshot_path"),
            "archive_manifest.current_publication.versioned_snapshot_path",
        )
    )
    if not snapshot_path.is_file() or _sha256(snapshot_path) != expected_sha256:
        raise ScienceActiveParentError("science archive snapshot is missing or drifted")

    return {
        "schema_version": "xinao.science_archive_publication_binding.v1",
        "status": "READY",
        "stable_spec_path": str(stable_spec_path.resolve()),
        "stable_spec_sha256": stable_spec_sha256,
        "versioned_snapshot_path": str(snapshot_path.resolve()),
        "versioned_snapshot_sha256": snapshot_sha256,
        "completion_claim_allowed": False,
    }


def validate_science_checkpoint_active_parent_binding(
    checkpoint: Mapping[str, Any],
    *,
    expected_projection_path: Path,
    expected_active_parent_path: Path,
    expected_active_parent_sha256: str,
) -> dict[str, Any]:
    """Verify the non-authoritative checkpoint against the published identities."""

    if checkpoint.get("schema_version") != "xinao.codex_session_checkpoint.v2":
        raise ScienceActiveParentError("science checkpoint schema is invalid")
    parent_scope = _mapping(checkpoint.get("parent_scope"), "checkpoint.parent_scope")
    if (
        parent_scope.get("authority") is not False
        or parent_scope.get("active_parent_id") != "XINAO_SCIENCE_PROTOCOL_ACTIVE"
        or parent_scope.get("active_parent_status") != "CURRENT_ACTIVE_PARENT"
        or parent_scope.get("parent_scope_switch_status") != "PERFORMED"
    ):
        raise ScienceActiveParentError("science checkpoint parent scope is invalid")
    if (
        _carrier_path(
            _required_text(parent_scope.get("projection_path"), "checkpoint.projection_path")
        ).resolve()
        != _carrier_path(str(expected_projection_path)).resolve()
    ):
        raise ScienceActiveParentError("science checkpoint projection path does not match")
    if (
        _carrier_path(
            _required_text(parent_scope.get("active_parent_path"), "checkpoint.active_parent_path")
        ).resolve()
        != _carrier_path(str(expected_active_parent_path)).resolve()
    ):
        raise ScienceActiveParentError("science checkpoint active-parent path does not match")
    active_parent_sha256 = _required_text(
        parent_scope.get("active_parent_sha256"),
        "checkpoint.active_parent_sha256",
    ).lower()
    if active_parent_sha256 != expected_active_parent_sha256.lower():
        raise ScienceActiveParentError("science checkpoint active-parent SHA256 does not match")

    return {
        "schema_version": "xinao.science_checkpoint_active_parent_binding.v1",
        "status": "READY",
        "projection_path": str(_carrier_path(str(expected_projection_path)).resolve()),
        "active_parent_path": str(_carrier_path(str(expected_active_parent_path)).resolve()),
        "active_parent_sha256": active_parent_sha256,
        "completion_claim_allowed": False,
    }


def load_science_active_parent(
    projection_path: Path = SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
) -> dict[str, Any]:
    """Load and verify the live projection and every referenced human source."""

    projection_path = _carrier_path(str(projection_path))
    try:
        projection_bytes = projection_path.read_bytes()
        observed_projection_sha256 = hashlib.sha256(projection_bytes).hexdigest()
        payload = json.loads(projection_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScienceActiveParentError(
            f"cannot load science active-parent projection: {projection_path}"
        ) from exc
    _verify_committed_promotion_visibility(projection_path, payload)
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
    is_open_research_revision = _verify_science_text_contract(science_text)
    expected_first_frontier = (
        _OPEN_RESEARCH_FIRST_FRONTIER if is_open_research_revision else _LEGACY_FIRST_FRONTIER
    )
    if (
        list(payload["science_episode_gate"].get("first_frontier") or [])[:3]
        != expected_first_frontier
    ):
        raise ScienceActiveParentError("science text revision and first science frontier disagree")

    entry_text = _carrier_path(str(payload["stable_entry"]["path"])).read_text(encoding="utf-8")
    if (
        "《新澳严格数学科学研究模式——独立融合稿》.txt" not in entry_text
        or "LEGACY_PARENT_G0_G8 / SUPERSEDED_AS_ACTIVE_PARENT" not in entry_text
    ):
        raise ScienceActiveParentError("stable entry does not select the science parent")

    software_text = _carrier_path(str(payload["software_foundation"]["path"])).read_text(
        encoding="utf-8"
    )
    _verify_software_foundation_contract(
        _mapping(payload.get("software_foundation"), "software_foundation"),
        software_text,
        requires_maturation_invariant=(_V110_FORMAL_FUSION_VERSION_MARKER in science_text),
    )

    if _sha256(projection_path) != observed_projection_sha256:
        raise ScienceActiveParentError(
            "science active-parent projection changed while it was being loaded"
        )
    _verify_committed_promotion_visibility(projection_path, payload)

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
    "validate_science_archive_publication_binding",
    "validate_science_checkpoint_active_parent_binding",
    "validate_science_revision_candidate_binding",
    "validate_science_transition_active_parent_binding",
]
