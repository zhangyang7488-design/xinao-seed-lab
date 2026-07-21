"""Thin contracts for bounded worker packages and dispatch outcome accounting.

This module deliberately does not schedule providers.  It validates immutable
package inputs, computes the next bounded frontier, and projects provider,
owner-adoption, authority-application, and real-effect facts from the existing
task-run event chain.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

from services.agent_runtime.context_slice_manifest import (
    ContextSliceManifestError,
    validate_context_slice_manifest,
)
from services.agent_runtime.execution_contract import artifact_json_bytes

PACKAGE_IDENTITY_SCHEMA = "xinao.worker_package_identity.v2"
PACKAGE_BATCH_SCHEMA = "xinao.worker_package_batch.v3"
DISPATCH_ENVELOPE_SCHEMA = "xinao.worker_dispatch_envelope.v2"
OUTCOME_EVENT_SCHEMA = "xinao.dispatch_outcome_event.v2"
OUTCOME_PROJECTION_SCHEMA = "xinao.dispatch_outcome_projection.v1"
LOGICAL_CANDIDATE_CONSUMER_ID = "worker_candidate_producer"
LOGICAL_CANDIDATE_EFFECT_CONTRACT = {
    "schema_version": "xinao.worker_candidate_effect_contract.v1",
    "effect_kind": "candidate_artifact_write",
    "output_boundary": "allowed_output_root",
    "authority": False,
    "completion_claim_allowed": False,
}
_MAX_OUTCOME_GRAPH_DEPTH = 8

PathResolver = Callable[[str], str | Path]


class DispatchEconomicsError(ValueError):
    """Raised when dispatch inputs or evidence fail closed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def build_neutral_output_contract(acceptance: Mapping[str, object]) -> dict[str, object]:
    """Return the provider-neutral output shape consumed unchanged by leg B."""

    raw = _mapping(acceptance, "acceptance")
    min_result_chars = _int_at_least(
        raw.get("min_result_chars"),
        "acceptance.min_result_chars",
        1,
    )
    if min_result_chars > 200_000:
        raise DispatchEconomicsError("acceptance.min_result_chars must be <= 200000")
    markers_raw = _sequence(
        raw.get("required_result_markers"),
        "acceptance.required_result_markers",
    )
    markers = [str(value).strip() for value in markers_raw]
    if (
        any(not value or len(value) > 256 for value in markers)
        or len(markers) > 32
        or len(markers) != len(set(markers))
        or markers != list(markers_raw)
    ):
        raise DispatchEconomicsError(
            "acceptance.required_result_markers must be unique canonical strings"
        )
    require_json = raw.get("require_json_object")
    if not isinstance(require_json, bool):
        raise DispatchEconomicsError("acceptance.require_json_object must be boolean")
    schema_ref = raw.get("json_schema_ref")
    schema_sha256 = ""
    if schema_ref is not None:
        schema_sha256 = _sha(
            _mapping(schema_ref, "acceptance.json_schema_ref").get("sha256"),
            "acceptance.json_schema_ref.sha256",
        )
    if require_json is True and not schema_sha256:
        raise DispatchEconomicsError("acceptance requires a hash-bound json_schema_ref")
    if require_json is False and schema_sha256:
        raise DispatchEconomicsError("acceptance.json_schema_ref requires require_json_object=true")
    return {
        "result_format": "json_object" if require_json else "text",
        "result_json_schema_sha256": schema_sha256,
        "min_result_chars": min_result_chars,
        "required_result_markers": markers,
    }


def neutral_output_contract_sha256(acceptance: Mapping[str, object]) -> str:
    """Hash the one neutral output contract deterministically from acceptance."""

    return hashlib.sha256(
        artifact_json_bytes(build_neutral_output_contract(acceptance))
    ).hexdigest()


def build_route_choice_identity(
    *,
    package_manifest_sha256: str,
    package_ids: Sequence[str],
    epoch_id: str,
    leg: str,
    selection_decision_sha256: str,
    route_decision_binding_sha256: str,
) -> dict[str, str]:
    """Bind mutually exclusive A/B alternatives without creating a router."""

    normalized_leg = _text(leg, "leg").upper()
    if normalized_leg not in {"A", "B"}:
        raise DispatchEconomicsError("route choice leg must be A or B")
    normalized_packages = sorted({_text(value, "package_ids[]") for value in package_ids})
    if not normalized_packages:
        raise DispatchEconomicsError("route choice requires package_ids")
    alternative_group_sha256 = _canonical_sha(
        {
            "package_manifest_sha256": _sha(
                package_manifest_sha256,
                "package_manifest_sha256",
            ),
            "package_ids": normalized_packages,
            "epoch_id": _text(epoch_id, "epoch_id"),
        }
    )
    choice: dict[str, str] = {
        "schema_version": "xinao.worker_route_choice.v1",
        "alternative_group_sha256": alternative_group_sha256,
        "leg": normalized_leg,
        "selection_decision_sha256": _sha(
            selection_decision_sha256,
            "selection_decision_sha256",
        ),
        "route_decision_binding_sha256": _sha(
            route_decision_binding_sha256,
            "route_decision_binding_sha256",
        ),
    }
    choice["choice_sha256"] = _canonical_sha(choice)
    return choice


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DispatchEconomicsError(f"{label} must be non-empty")
    return text


def _sha(value: object, label: str) -> str:
    text = _text(value, label).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise DispatchEconomicsError(f"{label} must be sha256")
    return text


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DispatchEconomicsError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise DispatchEconomicsError(f"{label} must be an array")
    return value


def _int_at_least(value: object, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DispatchEconomicsError(f"{label} must be an integer >= {minimum}")
    return value


def _physical_path(
    value: object,
    label: str,
    path_resolver: PathResolver | None,
) -> tuple[str, Path]:
    """Resolve a leg-neutral logical path without rewriting the bound bytes."""

    logical = _text(value, label)
    try:
        resolved = path_resolver(logical) if path_resolver is not None else Path(logical)
        physical = Path(resolved).resolve(strict=False)
    except (OSError, TypeError, ValueError) as exc:
        raise DispatchEconomicsError(f"{label} path resolution failed: {logical}: {exc}") from exc
    return logical, physical


def _same_physical_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_link_or_junction(path: Path) -> bool:
    """Reject link-like path components before they can escape a sealed write root."""

    cursor = path
    while True:
        try:
            if cursor.is_symlink():
                return True
            is_junction = getattr(cursor, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
        except OSError:
            return True
        if cursor.parent == cursor:
            return False
        cursor = cursor.parent


def _candidate_output_directory(
    value: object,
    label: str,
    *,
    path_resolver: PathResolver | None,
) -> tuple[str, Path]:
    """Resolve one exact, existing, non-link candidate write boundary."""

    logical = _text(value, label)
    logical_parts = logical.replace("\\", "/").split("/")
    if any(part in {".", ".."} for part in logical_parts):
        raise DispatchEconomicsError(f"{label} cannot contain dot path traversal")
    try:
        resolved_value = path_resolver(logical) if path_resolver is not None else Path(logical)
        lexical = Path(os.path.abspath(os.fspath(resolved_value)))
        if any(part in {".", ".."} for part in Path(resolved_value).parts):
            raise DispatchEconomicsError(f"{label} resolver produced path traversal")
        if not lexical.is_dir():
            raise DispatchEconomicsError(f"{label} missing directory: {lexical}")
        physical = lexical.resolve(strict=True)
    except DispatchEconomicsError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise DispatchEconomicsError(f"{label} path resolution failed: {logical}: {exc}") from exc
    if not _same_physical_path(lexical, physical) or _contains_link_or_junction(lexical):
        raise DispatchEconomicsError(f"{label} cannot traverse a symlink or junction")
    return logical, physical


def _resolved_policy_root(
    logical: str,
    *,
    path_resolver: PathResolver | None,
) -> Path | None:
    try:
        value = path_resolver(logical) if path_resolver is not None else Path(logical)
        return Path(value).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return None


def _validate_candidate_output_isolation(
    *,
    output_root: Path,
    source_cwd: Path,
    label: str,
    path_resolver: PathResolver | None,
) -> None:
    """Keep candidate writes out of source, authority, and canonical root surfaces."""

    if _is_within(output_root, source_cwd):
        raise DispatchEconomicsError(f"{label} must be isolated from source cwd")

    repo_root = Path(__file__).resolve().parents[2]
    forbidden_subtrees = [repo_root]
    forbidden_exact = []
    for logical in (
        "E:/XINAO_RESEARCH_WORKSPACES/S",
        "E:/XINAO_RESEARCH_WORKSPACES/nianhua-new-route-active",
        "C:/Users/xx363/Desktop/主线",
        "/app",
        "/mainline",
    ):
        root = _resolved_policy_root(logical, path_resolver=path_resolver)
        if root is not None:
            forbidden_subtrees.append(root)
    for logical in (
        "D:/XINAO_RESEARCH_RUNTIME",
        "D:/XINAO_RESEARCH_RUNTIME/worktrees",
        "/evidence",
        "/evidence/worktrees",
    ):
        root = _resolved_policy_root(logical, path_resolver=path_resolver)
        if root is not None:
            forbidden_exact.append(root)
    for logical in ("D:/XINAO_RESEARCH_RUNTIME/state", "/evidence/state"):
        root = _resolved_policy_root(logical, path_resolver=path_resolver)
        if root is not None:
            forbidden_subtrees.append(root)
    if any(_is_within(output_root, root) for root in forbidden_subtrees):
        raise DispatchEconomicsError(f"{label} cannot be inside a source or authority root")
    if any(_same_physical_path(output_root, root) for root in forbidden_exact):
        raise DispatchEconomicsError(f"{label} cannot equal a canonical runtime root")


def _default_candidate_policy_bases(
    *,
    path_resolver: PathResolver | None,
) -> list[Path]:
    roots: list[Path] = []
    for logical in (
        "D:/XINAO_RESEARCH_RUNTIME/worktrees",
        "/evidence/worktrees",
    ):
        root = _resolved_policy_root(logical, path_resolver=path_resolver)
        if root is not None and not any(_same_physical_path(root, item) for item in roots):
            roots.append(root)
    return roots


def _load_hash_bound_ref(
    raw: object,
    label: str,
    *,
    expected_schema: str | None = None,
    path_resolver: PathResolver | None = None,
) -> tuple[Path, dict[str, Any]]:
    ref = _mapping(raw, label)
    _, path = _physical_path(ref.get("path"), f"{label}.path", path_resolver)
    expected = _sha(ref.get("sha256"), f"{label}.sha256")
    if not path.is_file():
        raise DispatchEconomicsError(f"{label} missing: {path}")
    observed = _file_sha(path)
    if observed != expected:
        raise DispatchEconomicsError(
            f"{label} sha256 mismatch: expected={expected}; observed={observed}"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DispatchEconomicsError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DispatchEconomicsError(f"{label} JSON must be an object")
    if expected_schema and payload.get("schema_version") != expected_schema:
        raise DispatchEconomicsError(
            f"{label} schema mismatch: expected={expected_schema}; "
            f"observed={payload.get('schema_version')}"
        )
    return path, payload


def _validate_path_ref(
    raw: object,
    label: str,
    *,
    path_resolver: PathResolver | None = None,
) -> dict[str, str]:
    ref = _mapping(raw, label)
    logical, path = _physical_path(ref.get("path"), f"{label}.path", path_resolver)
    expected = _sha(ref.get("sha256"), f"{label}.sha256")
    if not path.is_file():
        raise DispatchEconomicsError(f"{label} missing: {path}")
    observed = _file_sha(path)
    if observed != expected:
        raise DispatchEconomicsError(
            f"{label} sha256 mismatch: expected={expected}; observed={observed}"
        )
    return {"path": logical, "sha256": expected}


def build_worker_package_identity(
    *,
    package_id: str,
    work_key: str,
    parent_work_key: str,
    work_class: str,
    role: str,
    phase: str,
    input_sha256: str,
    context_sha256: str,
    rules_sha256: str,
    output_contract_sha256: str,
    write_domains: Sequence[str],
    candidate_only: bool,
) -> dict[str, object]:
    """Build the immutable identity shared by dispatch and both execution legs."""

    if not isinstance(candidate_only, bool):
        raise DispatchEconomicsError("candidate_only must be boolean")
    if not isinstance(write_domains, Sequence) or isinstance(write_domains, (str, bytes)):
        raise DispatchEconomicsError("write_domains must be an array")
    identity: dict[str, object] = {
        "schema_version": PACKAGE_IDENTITY_SCHEMA,
        "package_id": _text(package_id, "package_id"),
        "work_key": _text(work_key, "work_key"),
        "parent_work_key": _text(parent_work_key, "parent_work_key"),
        "work_class": _text(work_class, "work_class"),
        "role": _text(role, "role"),
        "phase": _text(phase, "phase"),
        # This manifest is transport neutral.  A/B physical consumers are
        # derived only after a route receipt is bound in the dispatch envelope.
        "logical_consumer_id": LOGICAL_CANDIDATE_CONSUMER_ID,
        "logical_effect_contract": dict(LOGICAL_CANDIDATE_EFFECT_CONTRACT),
        "input_sha256": _sha(input_sha256, "input_sha256"),
        "context_sha256": _sha(context_sha256, "context_sha256"),
        "rules_sha256": _sha(rules_sha256, "rules_sha256"),
        "output_contract_sha256": _sha(output_contract_sha256, "output_contract_sha256"),
        "write_domains": sorted({_text(value, "write_domains[]") for value in write_domains}),
        "candidate_only": candidate_only,
        "authority": False,
        "completion_claim_allowed": False,
    }
    identity["package_identity_sha256"] = _canonical_sha(identity)
    return identity


def _validate_context_binding(
    package: Mapping[str, object],
    index: int,
    *,
    path_resolver: PathResolver | None = None,
) -> None:
    label = f"packages[{index}].context_manifest_ref"
    _, context = _load_hash_bound_ref(
        package.get("context_manifest_ref"),
        label,
        path_resolver=path_resolver,
    )
    context_sha = _sha(
        _mapping(package.get("context_manifest_ref"), label).get("sha256"),
        f"{label}.sha256",
    )
    if package.get("context_sha256") != context_sha:
        raise DispatchEconomicsError(
            f"packages[{index}].context_sha256 does not bind context_manifest_ref"
        )
    try:
        validated_context = validate_context_slice_manifest(context)
    except ContextSliceManifestError as exc:
        raise DispatchEconomicsError(f"{label} is not a valid context slice: {exc}") from exc
    if (
        validated_context.get("authority") is not False
        or validated_context.get("completion_claim_allowed") is not False
    ):
        raise DispatchEconomicsError(f"{label} must be non-authoritative")
    input_refs = _sequence(package.get("input_refs"), f"packages[{index}].input_refs")
    if not input_refs:
        raise DispatchEconomicsError(f"packages[{index}].input_refs must be non-empty")
    validated_inputs = [
        _validate_path_ref(
            value,
            f"packages[{index}].input_refs[{ref_index}]",
            path_resolver=path_resolver,
        )
        for ref_index, value in enumerate(input_refs)
    ]
    combined = (
        validated_inputs[0]["sha256"]
        if len(validated_inputs) == 1
        else _canonical_sha(validated_inputs)
    )
    if package.get("input_sha256") != combined:
        raise DispatchEconomicsError(f"packages[{index}].input_sha256 does not bind input_refs")


def _validate_package_identity(package: Mapping[str, object], index: int) -> None:
    label = f"packages[{index}]"
    if package.get("schema_version") != PACKAGE_IDENTITY_SCHEMA:
        raise DispatchEconomicsError(f"{label}.schema_version mismatch")
    for field in (
        "package_id",
        "work_key",
        "parent_work_key",
        "work_class",
        "role",
        "phase",
        "logical_consumer_id",
    ):
        _text(package.get(field), f"{label}.{field}")
    if package.get("logical_consumer_id") != LOGICAL_CANDIDATE_CONSUMER_ID:
        raise DispatchEconomicsError(f"{label}.logical_consumer_id is unsupported")
    if package.get("logical_effect_contract") != LOGICAL_CANDIDATE_EFFECT_CONTRACT:
        raise DispatchEconomicsError(f"{label}.logical_effect_contract is unsupported")
    if "consumer_id" in package:
        raise DispatchEconomicsError(f"{label} cannot bind a physical consumer_id")
    for field in (
        "input_sha256",
        "context_sha256",
        "rules_sha256",
        "output_contract_sha256",
    ):
        _sha(package.get(field), f"{label}.{field}")
    if (
        package.get("authority") is not False
        or package.get("completion_claim_allowed") is not False
    ):
        raise DispatchEconomicsError(f"{label} must be non-authoritative")
    if not isinstance(package.get("candidate_only"), bool):
        raise DispatchEconomicsError(f"{label}.candidate_only must be boolean")
    write_domains = _sequence(package.get("write_domains"), f"{label}.write_domains")
    if package.get("candidate_only") is True and write_domains:
        raise DispatchEconomicsError(
            f"{label} candidate-only package cannot own authority write domains"
        )
    expected_identity = dict(package)
    for key in (
        "prompt_ref",
        "context_manifest_ref",
        "rules_ref",
        "input_refs",
        "allowed_output_root",
        "cwd",
        "depends_on",
        "acceptance",
        "timeout_sec",
        "lane_index",
        "prior_attempt_receipt_ref",
        "package_seal_sha256",
        "execution_seal_ready",
        "resealed_from_package_seal_sha256",
    ):
        expected_identity.pop(key, None)
    observed_identity_sha = _sha(
        expected_identity.pop("package_identity_sha256", None),
        f"{label}.package_identity_sha256",
    )
    if _canonical_sha(expected_identity) != observed_identity_sha:
        raise DispatchEconomicsError(f"{label}.package_identity_sha256 mismatch")


_DEPENDENCY_CONDITIONS = frozenset(
    {"worker_terminal", "owner_adopted", "authority_applied", "effect_verified"}
)
_SELECTOR_ALIASES = {
    "primary_artifact": "primary_artifact",
    "outcome_artifact": "outcome_artifact",
    "outcome_artifacts": "outcome_artifact",
    "authority_artifact": "authority_artifact",
    "applied_artifact": "authority_artifact",
    "effect_artifact": "effect_artifact",
    "consumer_readback": "consumer_readback",
}
_SELECTORS_BY_CONDITION = {
    "worker_terminal": frozenset({"primary_artifact"}),
    "owner_adopted": frozenset({"outcome_artifact"}),
    "authority_applied": frozenset({"authority_artifact"}),
    "effect_verified": frozenset({"effect_artifact", "consumer_readback"}),
}


def _expected_dependency_artifact(
    event: Mapping[str, object], selector: str
) -> Mapping[str, object]:
    if selector == "primary_artifact":
        value = event.get("primary_artifact_ref")
        if not isinstance(value, Mapping):
            raise DispatchEconomicsError("worker terminal pin has no accepted primary artifact")
        return value
    if selector == "outcome_artifact":
        values = event.get("outcome_artifact_refs")
    elif selector == "authority_artifact":
        values = event.get("applied_artifact_refs")
    elif selector == "effect_artifact":
        values = event.get("artifact_refs")
    else:
        value = event.get("consumer_readback_ref")
        if not isinstance(value, Mapping):
            raise DispatchEconomicsError("effect pin has no consumer readback")
        return value
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], Mapping):
        raise DispatchEconomicsError(
            f"{selector} must select exactly one artifact; use a narrower result selector"
        )
    return values[0]


def _event_satisfies_dependency(
    event: Mapping[str, object], *, package_id: str, condition: str
) -> bool:
    if event.get("package_id") != package_id:
        return False
    if condition == "worker_terminal":
        return (
            event.get("event_type") == "worker_terminal"
            and event.get("provider_accepted") is True
            and isinstance(event.get("primary_artifact_ref"), Mapping)
        )
    if condition == "owner_adopted":
        return event.get("event_type") == "owner_adopted" and event.get("owner_adopted") is True
    if condition == "authority_applied":
        return (
            event.get("event_type") == "authority_applied"
            and event.get("authority_applied") is True
        )
    return (
        event.get("event_type") == "effect_verified"
        and event.get("effect_verified") is True
        and isinstance(event.get("authority_applied_event_ref"), Mapping)
    )


def _normalize_dependency(
    raw: object,
    *,
    label: str,
    path_resolver: PathResolver | None,
    validate_pin_event: bool,
    outcome_depth: int,
) -> dict[str, object]:
    if isinstance(raw, str):
        # v1 shorthand never meant provider completion; preserve it fail-closed as
        # an owner-adopted dependency.
        value: dict[str, object] = {
            "package_id": _text(raw, f"{label}.package_id"),
            "condition": "owner_adopted",
            "result_selector": "outcome_artifact",
            "pin": None,
        }
    else:
        dependency = _mapping(raw, label)
        unknown = set(dependency) - {"package_id", "condition", "result_selector", "pin"}
        if unknown:
            raise DispatchEconomicsError(
                f"{label} has unsupported fields: {','.join(sorted(unknown))}"
            )
        condition = _text(dependency.get("condition"), f"{label}.condition")
        if condition not in _DEPENDENCY_CONDITIONS:
            raise DispatchEconomicsError(f"{label}.condition is unsupported")
        selector_raw = _text(dependency.get("result_selector"), f"{label}.result_selector")
        selector = _SELECTOR_ALIASES.get(selector_raw)
        if selector not in _SELECTORS_BY_CONDITION[condition]:
            raise DispatchEconomicsError(
                f"{label}.result_selector is incompatible with {condition}"
            )
        value = {
            "package_id": _text(dependency.get("package_id"), f"{label}.package_id"),
            "condition": condition,
            "result_selector": selector,
            "pin": None,
        }
        if dependency.get("pin") is not None:
            pin = _mapping(dependency.get("pin"), f"{label}.pin")
            if set(pin) != {"event_ref", "artifact_ref"}:
                raise DispatchEconomicsError(
                    f"{label}.pin must contain only event_ref and artifact_ref"
                )
            event_ref = _validate_path_ref(
                pin.get("event_ref"),
                f"{label}.pin.event_ref",
                path_resolver=path_resolver,
            )
            artifact_ref = _validate_path_ref(
                pin.get("artifact_ref"),
                f"{label}.pin.artifact_ref",
                path_resolver=path_resolver,
            )
            if event_ref["sha256"] == artifact_ref["sha256"]:
                raise DispatchEconomicsError(f"{label}.pin cannot borrow its event as a result")
            if validate_pin_event:
                _, event = _load_outcome_event_ref(
                    event_ref,
                    f"{label}.pin.event_ref",
                    depth=outcome_depth,
                    path_resolver=path_resolver,
                )
                if not _event_satisfies_dependency(
                    event,
                    package_id=str(value["package_id"]),
                    condition=str(value["condition"]),
                ):
                    raise DispatchEconomicsError(
                        f"{label}.pin event does not satisfy its typed condition"
                    )
                selected = _expected_dependency_artifact(event, str(value["result_selector"]))
                if _ref_key(selected) != _ref_key(artifact_ref):
                    raise DispatchEconomicsError(
                        f"{label}.pin artifact does not match the selected result"
                    )
            value["pin"] = {"event_ref": event_ref, "artifact_ref": artifact_ref}
    return value


def _package_semantic_body(package: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(dict(package))
    for key in (
        "lane_index",
        "package_seal_sha256",
        "execution_seal_ready",
        "resealed_from_package_seal_sha256",
    ):
        value.pop(key, None)
    return value


def _package_reseal_shape(package: Mapping[str, object]) -> dict[str, object]:
    value = _package_semantic_body(package)
    for dependency in value.get("depends_on", []):
        if isinstance(dependency, dict):
            dependency["pin"] = None
    value.pop("prior_attempt_receipt_ref", None)
    return value


def _manifest_digest_body(manifest: Mapping[str, object]) -> dict[str, object]:
    value = copy.deepcopy(dict(manifest))
    value.pop("lane_index_base", None)
    value.pop("validated_manifest_sha256", None)
    value["packages"] = [
        _package_semantic_body(_mapping(item, "packages[]")) for item in value.get("packages", [])
    ]
    return value


def _affected_cone(packages: Sequence[Mapping[str, object]], root: str) -> set[str]:
    cone = {root}
    changed = True
    while changed:
        changed = False
        for package in packages:
            package_id = str(package["package_id"])
            dependencies = {
                str(_mapping(item, "depends_on[]")["package_id"]) for item in package["depends_on"]
            }
            if package_id not in cone and dependencies & cone:
                cone.add(package_id)
                changed = True
    return cone


def validate_package_batch_manifest(
    manifest: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
    _lineage_depth: int = 0,
    _validation_depth: int = 0,
) -> dict[str, Any]:
    """Validate a neutral logical DAG and any immutable executable result pins."""

    if _lineage_depth > 32:
        raise DispatchEconomicsError("package manifest predecessor lineage is too deep")
    if _validation_depth > _MAX_OUTCOME_GRAPH_DEPTH:
        raise DispatchEconomicsError("package manifest outcome-pin chain is cyclic or too deep")
    if not isinstance(manifest, Mapping):
        raise DispatchEconomicsError("manifest must be an object")
    value: dict[str, Any] = copy.deepcopy(dict(manifest))
    value.pop("lane_index_base", None)
    value.pop("validated_manifest_sha256", None)
    if value.get("schema_version") != PACKAGE_BATCH_SCHEMA:
        raise DispatchEconomicsError("worker package batch schema mismatch")
    if value.get("authority") is not False or value.get("completion_claim_allowed") is not False:
        raise DispatchEconomicsError("worker package batch must be non-authoritative")

    parent_work_key = _text(value.get("parent_work_key"), "parent_work_key")
    logical_candidate_base, physical_candidate_base = _candidate_output_directory(
        value.get("candidate_output_base"),
        "candidate_output_base",
        path_resolver=path_resolver,
    )
    value["candidate_output_base"] = logical_candidate_base
    graph_revision = _int_at_least(value.get("graph_revision", 1), "graph_revision", 1)
    value["graph_revision"] = graph_revision
    value.setdefault("predecessor_manifest_ref", None)
    value.setdefault("reseal_of", None)
    value.setdefault("affected_cone", [])

    limits = dict(_mapping(value.get("limits"), "limits"))
    max_parallel = _int_at_least(limits.get("max_parallel"), "limits.max_parallel", 1)
    _int_at_least(limits.get("fan_in_capacity"), "limits.fan_in_capacity", 1)
    candidate_capacity = _int_at_least(
        limits.get("candidate_ingestion_capacity", max_parallel),
        "limits.candidate_ingestion_capacity",
        1,
    )
    limits["candidate_ingestion_capacity"] = candidate_capacity
    value["limits"] = limits

    packages = _sequence(value.get("packages"), "packages")
    if not packages:
        raise DispatchEconomicsError("packages must be non-empty")
    package_ids: set[str] = set()
    work_keys: set[str] = set()
    candidate_output_roots: list[tuple[str, Path]] = []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(packages):
        package = copy.deepcopy(dict(_mapping(raw, f"packages[{index}]")))
        for derived in (
            "lane_index",
            "package_seal_sha256",
            "execution_seal_ready",
            "resealed_from_package_seal_sha256",
        ):
            package.pop(derived, None)
        package_id = _text(package.get("package_id"), f"packages[{index}].package_id")
        work_key = _text(package.get("work_key"), f"packages[{index}].work_key")
        if package_id in package_ids:
            raise DispatchEconomicsError(f"duplicate package_id: {package_id}")
        if work_key in work_keys:
            raise DispatchEconomicsError(f"duplicate work_key: {work_key}")
        package_ids.add(package_id)
        work_keys.add(work_key)
        _validate_package_identity(package, index)
        if package.get("parent_work_key") != parent_work_key:
            raise DispatchEconomicsError(
                f"packages[{index}].parent_work_key does not bind dispatch epoch"
            )
        package["prompt_ref"] = _validate_path_ref(
            package.get("prompt_ref"),
            f"packages[{index}].prompt_ref",
            path_resolver=path_resolver,
        )
        package["context_manifest_ref"] = _validate_path_ref(
            package.get("context_manifest_ref"),
            f"packages[{index}].context_manifest_ref",
            path_resolver=path_resolver,
        )
        _validate_context_binding(package, index, path_resolver=path_resolver)
        package["rules_ref"] = _validate_path_ref(
            package.get("rules_ref"),
            f"packages[{index}].rules_ref",
            path_resolver=path_resolver,
        )
        if package["rules_sha256"] != package["rules_ref"]["sha256"]:
            raise DispatchEconomicsError(f"packages[{index}].rules_sha256 does not bind rules_ref")
        logical_output_root, physical_output_root = _candidate_output_directory(
            package.get("allowed_output_root"),
            f"packages[{index}].allowed_output_root",
            path_resolver=path_resolver,
        )
        package["allowed_output_root"] = logical_output_root
        logical_cwd, physical_cwd = _physical_path(
            package.get("cwd"), f"packages[{index}].cwd", path_resolver
        )
        if not physical_cwd.is_dir():
            raise DispatchEconomicsError(f"packages[{index}].cwd missing: {physical_cwd}")
        _validate_candidate_output_isolation(
            output_root=physical_output_root,
            source_cwd=physical_cwd,
            label=f"packages[{index}].allowed_output_root",
            path_resolver=path_resolver,
        )
        if _same_physical_path(physical_output_root, physical_candidate_base) or not _is_within(
            physical_output_root, physical_candidate_base
        ):
            raise DispatchEconomicsError(
                f"packages[{index}].allowed_output_root must be a strict child of "
                "candidate_output_base"
            )
        for other_id, other_root in candidate_output_roots:
            if _is_within(physical_output_root, other_root) or _is_within(
                other_root, physical_output_root
            ):
                raise DispatchEconomicsError(
                    f"candidate output roots must be disjoint: {other_id},{package_id}"
                )
        candidate_output_roots.append((package_id, physical_output_root))
        package["cwd"] = logical_cwd
        dependencies = [
            _normalize_dependency(
                dependency,
                label=f"packages[{index}].depends_on[{dependency_index}]",
                path_resolver=path_resolver,
                validate_pin_event=True,
                outcome_depth=_validation_depth,
            )
            for dependency_index, dependency in enumerate(
                _sequence(package.get("depends_on"), f"packages[{index}].depends_on")
            )
        ]
        dependency_ids = [str(item["package_id"]) for item in dependencies]
        if package_id in dependency_ids:
            raise DispatchEconomicsError(f"package depends on itself: {package_id}")
        if len(set(dependency_ids)) != len(dependency_ids):
            raise DispatchEconomicsError(f"duplicate dependency: {package_id}")
        package["depends_on"] = dependencies
        acceptance = dict(_mapping(package.get("acceptance"), f"packages[{index}].acceptance"))
        schema_ref = acceptance.get("json_schema_ref")
        if acceptance.get("require_json_object") is True and schema_ref is None:
            raise DispatchEconomicsError(
                f"packages[{index}].acceptance requires a hash-bound json_schema_ref"
            )
        if schema_ref is not None:
            acceptance["json_schema_ref"] = _validate_path_ref(
                schema_ref,
                f"packages[{index}].acceptance.json_schema_ref",
                path_resolver=path_resolver,
            )
        expected_output_contract_sha256 = neutral_output_contract_sha256(acceptance)
        if package["output_contract_sha256"] != expected_output_contract_sha256:
            raise DispatchEconomicsError(
                f"packages[{index}].output_contract_sha256 does not bind acceptance"
            )
        package["acceptance"] = acceptance
        _int_at_least(package.get("timeout_sec"), f"packages[{index}].timeout_sec", 1)
        if package.get("prior_attempt_receipt_ref") is not None:
            package["prior_attempt_receipt_ref"] = _validate_path_ref(
                package["prior_attempt_receipt_ref"],
                f"packages[{index}].prior_attempt_receipt_ref",
                path_resolver=path_resolver,
            )
        package["lane_index"] = index
        package["execution_seal_ready"] = all(item["pin"] is not None for item in dependencies)
        package["package_seal_sha256"] = _canonical_sha(
            {
                "schema_version": "xinao.worker_package_execution_seal.v1",
                "graph_revision": graph_revision,
                "package_identity_sha256": package["package_identity_sha256"],
                "depends_on": dependencies,
                "prior_attempt_receipt_ref": package.get("prior_attempt_receipt_ref"),
            }
        )
        normalized.append(package)

    for package in normalized:
        dependency_ids = {str(item["package_id"]) for item in package["depends_on"]}
        missing = sorted(dependency_ids - package_ids)
        if missing:
            raise DispatchEconomicsError(
                f"unknown dependency for {package['package_id']}: {','.join(missing)}"
            )
    remaining = {
        str(row["package_id"]): {str(item["package_id"]) for item in row["depends_on"]}
        for row in normalized
    }
    closed: set[str] = set()
    while remaining:
        ready = sorted(key for key, deps in remaining.items() if deps <= closed)
        if not ready:
            raise DispatchEconomicsError("package dependency cycle")
        for key in ready:
            remaining.pop(key)
            closed.add(key)

    affected_raw = _sequence(value.get("affected_cone"), "affected_cone")
    affected = [_text(item, "affected_cone[]") for item in affected_raw]
    if len(affected) != len(set(affected)):
        raise DispatchEconomicsError("affected_cone must be unique")
    if graph_revision == 1:
        if value.get("predecessor_manifest_ref") is not None or value.get("reseal_of") is not None:
            raise DispatchEconomicsError("initial graph revision cannot declare reseal lineage")
        if affected:
            raise DispatchEconomicsError("initial graph revision affected_cone must be empty")
    else:
        predecessor_raw = value.get("predecessor_manifest_ref")
        if predecessor_raw is None:
            raise DispatchEconomicsError("resealed graph requires predecessor_manifest_ref")
        predecessor_ref = _validate_path_ref(
            predecessor_raw,
            "predecessor_manifest_ref",
            path_resolver=path_resolver,
        )
        _, predecessor_raw_value = _load_hash_bound_ref(
            predecessor_ref,
            "predecessor_manifest_ref",
            expected_schema=PACKAGE_BATCH_SCHEMA,
            path_resolver=path_resolver,
        )
        predecessor = validate_package_batch_manifest(
            predecessor_raw_value,
            path_resolver=path_resolver,
            _lineage_depth=_lineage_depth + 1,
            _validation_depth=_validation_depth,
        )
        if predecessor["graph_revision"] + 1 != graph_revision:
            raise DispatchEconomicsError("graph_revision must directly follow its predecessor")
        if predecessor["parent_work_key"] != parent_work_key:
            raise DispatchEconomicsError("predecessor parent_work_key drifted")
        reseal = _mapping(value.get("reseal_of"), "reseal_of")
        if set(reseal) != {"package_id", "package_identity_sha256", "graph_revision"}:
            raise DispatchEconomicsError("reseal_of fields do not match v2")
        root = _text(reseal.get("package_id"), "reseal_of.package_id")
        previous_by_id = {str(row["package_id"]): row for row in predecessor["packages"]}
        current_by_id = {str(row["package_id"]): row for row in normalized}
        if set(previous_by_id) != set(current_by_id) or root not in current_by_id:
            raise DispatchEconomicsError("reseal must preserve the package graph identity set")
        if (
            _int_at_least(reseal.get("graph_revision"), "reseal_of.graph_revision", 1)
            != predecessor["graph_revision"]
        ):
            raise DispatchEconomicsError("reseal_of graph_revision mismatch")
        if (
            _sha(reseal.get("package_identity_sha256"), "reseal_of.package_identity_sha256")
            != previous_by_id[root]["package_identity_sha256"]
        ):
            raise DispatchEconomicsError("reseal_of package identity mismatch")
        expected_cone = _affected_cone(predecessor["packages"], root)
        if set(affected) != expected_cone:
            raise DispatchEconomicsError(
                "affected_cone must equal the resealed package and its transitive dependents"
            )
        for package_id in expected_cone - {root}:
            for dependency in current_by_id[package_id]["depends_on"]:
                if dependency["package_id"] in expected_cone and dependency.get("pin") is not None:
                    raise DispatchEconomicsError(
                        "affected_cone downstream result pins must be cleared before reseal"
                    )
        changed = False
        material_change = False
        for package_id, current in current_by_id.items():
            previous = previous_by_id[package_id]
            if current["work_key"] != previous["work_key"]:
                raise DispatchEconomicsError("same package reseal must preserve work_key")
            if current["package_identity_sha256"] != previous["package_identity_sha256"]:
                raise DispatchEconomicsError("same work_key reseal must preserve package identity")
            if package_id not in expected_cone:
                if _package_semantic_body(current) != _package_semantic_body(previous):
                    raise DispatchEconomicsError("package outside affected_cone changed")
                current["package_seal_sha256"] = previous["package_seal_sha256"]
                current["execution_seal_ready"] = previous["execution_seal_ready"]
                current.pop("resealed_from_package_seal_sha256", None)
                continue
            if _package_reseal_shape(current) != _package_reseal_shape(previous):
                raise DispatchEconomicsError("reseal may change only result pins or prior attempt")
            if _package_semantic_body(current) != _package_semantic_body(previous):
                material_change = True
            if current["package_seal_sha256"] != previous["package_seal_sha256"]:
                changed = True
                current["resealed_from_package_seal_sha256"] = previous["package_seal_sha256"]
        if not changed or not material_change:
            raise DispatchEconomicsError(
                "reseal did not change a result pin or prior attempt in affected_cone"
            )
        if limits != predecessor["limits"]:
            raise DispatchEconomicsError("reseal cannot change graph limits")
        if value["candidate_output_base"] != predecessor["candidate_output_base"]:
            raise DispatchEconomicsError("reseal cannot change candidate_output_base")
        value["predecessor_manifest_ref"] = predecessor_ref
        value["reseal_of"] = {
            "package_id": root,
            "package_identity_sha256": str(reseal["package_identity_sha256"]),
            "graph_revision": int(reseal["graph_revision"]),
        }
    value["affected_cone"] = affected
    value["packages"] = normalized
    value["lane_index_base"] = 0
    value["validated_manifest_sha256"] = _canonical_sha(_manifest_digest_body(value))
    return value


def validate_dispatch_envelope(
    envelope: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
    _validation_depth: int = 0,
) -> dict[str, Any]:
    """Validate one leg-specific admission envelope around a neutral package DAG."""

    if not isinstance(envelope, Mapping):
        raise DispatchEconomicsError("dispatch envelope must be an object")
    value: dict[str, Any] = copy.deepcopy(dict(envelope))
    if value.get("schema_version") != DISPATCH_ENVELOPE_SCHEMA:
        raise DispatchEconomicsError("worker dispatch envelope schema mismatch")
    if value.get("authority") is not False or value.get("completion_claim_allowed") is not False:
        raise DispatchEconomicsError("worker dispatch envelope must be non-authoritative")
    leg = _text(value.get("leg"), "leg").upper()
    if leg not in {"A", "B"}:
        raise DispatchEconomicsError("dispatch envelope leg must be A or B")
    manifest_ref = _validate_path_ref(
        value.get("package_manifest_ref"),
        "package_manifest_ref",
        path_resolver=path_resolver,
    )
    _, manifest_raw = _load_hash_bound_ref(
        manifest_ref,
        "package_manifest_ref",
        expected_schema=PACKAGE_BATCH_SCHEMA,
        path_resolver=path_resolver,
    )
    manifest = validate_package_batch_manifest(
        manifest_raw,
        path_resolver=path_resolver,
        _validation_depth=_validation_depth,
    )

    epoch = _mapping(value.get("dispatch_epoch"), "dispatch_epoch")
    epoch_id = _text(epoch.get("epoch_id"), "dispatch_epoch.epoch_id")
    snapshot_id = _text(epoch.get("quota_snapshot_id"), "dispatch_epoch.quota_snapshot_id")
    quota_ref = {
        "path": _text(epoch.get("quota_snapshot_ref"), "dispatch_epoch.quota_snapshot_ref"),
        "sha256": _sha(epoch.get("quota_snapshot_sha256"), "dispatch_epoch.quota_snapshot_sha256"),
    }
    _, quota = _load_hash_bound_ref(
        quota_ref,
        "dispatch_epoch.quota_snapshot",
        path_resolver=path_resolver,
    )
    if quota.get("snapshot_id") != snapshot_id or quota.get("epoch_id") != epoch_id:
        raise DispatchEconomicsError("dispatch epoch does not bind quota snapshot identity")
    if quota.get("freshness") not in {"fresh", "validated", "unknown"}:
        raise DispatchEconomicsError("quota snapshot freshness is invalid")
    if quota.get("freshness") == "unknown" and quota.get("dispatch_blocked") is not False:
        raise DispatchEconomicsError("unknown quota telemetry cannot become a dispatch gate")

    selection = _mapping(value.get("selection"), "selection")
    selection_ref = {
        "path": _text(selection.get("receipt_ref"), "selection.receipt_ref"),
        "sha256": _sha(selection.get("receipt_sha256"), "selection.receipt_sha256"),
    }
    _, receipt = _load_hash_bound_ref(
        selection_ref,
        "selection.receipt",
        path_resolver=path_resolver,
    )
    if receipt.get("decision") != "selected":
        raise DispatchEconomicsError("selection receipt is not selected")
    decision_sha256 = _sha(
        receipt.get("decision_sha256"),
        "selection.receipt.decision_sha256",
    )
    decision_basis = dict(receipt)
    decision_basis.pop("decision_sha256", None)
    if _canonical_sha(decision_basis) != decision_sha256:
        raise DispatchEconomicsError("selection receipt decision sha256 is not canonical")
    selected = _mapping(receipt.get("selected_candidate"), "selection.selected_candidate")
    if "capability_binding_sha256" in selected:
        raise DispatchEconomicsError(
            "selector candidate cannot claim provider capability_binding_sha256"
        )
    for field in ("provider_id", "profile_ref", "model_id", "transport_id"):
        expected = _text(selection.get(field), f"selection.{field}")
        if selected.get(field) != expected:
            raise DispatchEconomicsError(f"selection receipt {field} mismatch")
    if decision_sha256 != _sha(selection.get("decision_sha256"), "selection.decision_sha256"):
        raise DispatchEconomicsError("selection decision sha256 mismatch")
    route_identity = {
        field: str(selected[field])
        for field in ("provider_id", "profile_ref", "model_id", "transport_id")
    }
    route_identity_sha256 = _canonical_sha(route_identity)
    route_decision_binding_sha256 = _canonical_sha(
        {
            "decision_sha256": decision_sha256,
            "route_identity_sha256": route_identity_sha256,
        }
    )
    for field, observed in (
        ("route_identity_sha256", route_identity_sha256),
        ("route_decision_binding_sha256", route_decision_binding_sha256),
    ):
        claimed = selection.get(field)
        if claimed is not None and _sha(claimed, f"selection.{field}") != observed:
            raise DispatchEconomicsError(f"selection {field} mismatch")

    try:
        from services.agent_runtime.grok_execution_contract_adapter import (
            GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
            GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
            GROK_DOCKER_CONSUMER_ID,
            GROK_DOCKER_ROUTE_TRANSPORT_ID,
            validate_grok_docker_route_adapter_binding,
        )

        expected_route_transport = {
            "A": GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
            "B": GROK_DOCKER_ROUTE_TRANSPORT_ID,
        }[leg]
        if route_identity["transport_id"] != expected_route_transport:
            raise DispatchEconomicsError(
                f"leg-{leg} selector route transport mismatch: "
                f"expected={expected_route_transport};"
                f"observed={route_identity['transport_id']}"
            )
        if leg == "A":
            if value.get("execution_adapter") is not None:
                raise DispatchEconomicsError("leg-A cannot consume a provider route adapter")
            execution_adapter = None
            physical_consumer_id = GROK_DIRECT_WORKER_POOL_CONSUMER_ID
        else:
            execution_adapter = validate_grok_docker_route_adapter_binding(
                _mapping(value.get("execution_adapter"), "execution_adapter"),
                route_selection_receipt=receipt,
            )
            physical_consumer_id = _text(
                execution_adapter.get("consumer_id"),
                "execution_adapter.consumer_id",
            )
            if physical_consumer_id != GROK_DOCKER_CONSUMER_ID:
                raise DispatchEconomicsError("leg-B route adapter derived another consumer")
    except DispatchEconomicsError:
        raise
    except (TypeError, ValueError) as exc:
        raise DispatchEconomicsError(f"dispatch route binding is invalid: {exc}") from exc

    package_ids = [
        _text(item, "package_ids[]") for item in _sequence(value.get("package_ids"), "package_ids")
    ]
    known = {str(row["package_id"]) for row in manifest["packages"]}
    if not package_ids or len(package_ids) != len(set(package_ids)):
        raise DispatchEconomicsError("dispatch envelope package_ids must be unique and non-empty")
    expected_route_choice = build_route_choice_identity(
        package_manifest_sha256=manifest_ref["sha256"],
        package_ids=package_ids,
        epoch_id=epoch_id,
        leg=leg,
        selection_decision_sha256=decision_sha256,
        route_decision_binding_sha256=route_decision_binding_sha256,
    )
    route_choice = dict(_mapping(value.get("route_choice"), "route_choice"))
    if route_choice != expected_route_choice:
        raise DispatchEconomicsError("dispatch route_choice identity drifted")
    unknown = sorted(set(package_ids) - known)
    if unknown:
        raise DispatchEconomicsError(
            f"dispatch envelope has unknown package ids: {','.join(unknown)}"
        )
    admitted_rows = [
        row for row in manifest["packages"] if str(row["package_id"]) in set(package_ids)
    ]
    non_candidate = sorted(
        str(row["package_id"]) for row in admitted_rows if row["candidate_only"] is not True
    )
    if non_candidate:
        raise DispatchEconomicsError(
            "worker dispatch envelope admits owner-authority packages: " + ",".join(non_candidate)
        )
    unsealed = sorted(
        str(row["package_id"]) for row in admitted_rows if row["execution_seal_ready"] is not True
    )
    if unsealed:
        raise DispatchEconomicsError(
            "worker dispatch envelope admits packages without executable result pins: "
            + ",".join(unsealed)
        )
    value.update(
        leg=leg,
        package_manifest_ref=manifest_ref,
        package_ids=package_ids,
        validated_package_seals={
            str(row["package_id"]): str(row["package_seal_sha256"]) for row in admitted_rows
        },
        validated_package_manifest=manifest,
        validated_selected_candidate={
            **route_identity,
            "route_identity_sha256": route_identity_sha256,
            "route_decision_binding_sha256": route_decision_binding_sha256,
        },
        validated_execution_adapter=execution_adapter,
        validated_physical_consumer_id=physical_consumer_id,
        validated_route_choice=expected_route_choice,
        validated_envelope_sha256=_canonical_sha(value),
    )
    return value


def validate_candidate_consumer_binding(
    envelope: Mapping[str, object],
    *,
    physical_consumer_id: str,
    expected_leg: str,
    requested_output_roots: Mapping[str, object] | None = None,
    allowed_candidate_bases: Sequence[object] | None = None,
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Fail closed before A/B starts a model on one neutral candidate manifest."""

    validated = validate_dispatch_envelope(envelope, path_resolver=path_resolver)
    leg = _text(expected_leg, "expected_leg").upper()
    if leg not in {"A", "B"} or validated["leg"] != leg:
        raise DispatchEconomicsError("candidate consumer leg does not match dispatch envelope")
    derived_consumer = _text(
        validated.get("validated_physical_consumer_id"),
        "validated_physical_consumer_id",
    )
    if _text(physical_consumer_id, "physical_consumer_id") != derived_consumer:
        raise DispatchEconomicsError("candidate physical consumer does not match route adapter")

    manifest = _mapping(
        validated.get("validated_package_manifest"),
        "validated_package_manifest",
    )
    logical_candidate_base, physical_candidate_base = _candidate_output_directory(
        manifest.get("candidate_output_base"),
        "candidate_output_base",
        path_resolver=path_resolver,
    )
    if allowed_candidate_bases is None:
        policy_bases = _default_candidate_policy_bases(path_resolver=path_resolver)
    else:
        policy_bases = [
            _candidate_output_directory(
                raw,
                f"allowed_candidate_bases[{index}]",
                path_resolver=path_resolver,
            )[1]
            for index, raw in enumerate(allowed_candidate_bases)
        ]
    if not policy_bases or not any(
        _is_within(physical_candidate_base, root) for root in policy_bases
    ):
        raise DispatchEconomicsError(
            "candidate_output_base is outside the admitted D runtime candidate roots"
        )

    requested = dict(requested_output_roots or {})
    known_ids = {str(item) for item in validated["package_ids"]}
    if set(requested) - known_ids:
        raise DispatchEconomicsError("candidate consumer requested an unadmitted package output")
    boundaries = []
    package_by_id = {str(row["package_id"]): row for row in manifest["packages"]}
    for package_id in validated["package_ids"]:
        package = _mapping(package_by_id.get(str(package_id)), f"package[{package_id}]")
        if (
            package.get("candidate_only") is not True
            or package.get("logical_consumer_id") != LOGICAL_CANDIDATE_CONSUMER_ID
            or package.get("logical_effect_contract") != LOGICAL_CANDIDATE_EFFECT_CONTRACT
        ):
            raise DispatchEconomicsError("candidate consumer received an authority package")
        logical_root, physical_root = _candidate_output_directory(
            package.get("allowed_output_root"),
            f"package[{package_id}].allowed_output_root",
            path_resolver=path_resolver,
        )
        requested_root = requested.get(str(package_id), logical_root)
        requested_logical, requested_physical = _candidate_output_directory(
            requested_root,
            f"requested_output_roots[{package_id}]",
            path_resolver=path_resolver,
        )
        if requested_logical != logical_root or not _same_physical_path(
            requested_physical, physical_root
        ):
            raise DispatchEconomicsError("candidate consumer output root drifted from manifest")
        boundaries.append(
            {
                "package_id": str(package_id),
                "allowed_output_root": logical_root,
                "physical_output_root": str(physical_root),
                "package_seal_sha256": str(package["package_seal_sha256"]),
            }
        )
    return {
        "schema_version": "xinao.worker_candidate_consumer_binding.v1",
        "leg": leg,
        "logical_consumer_id": LOGICAL_CANDIDATE_CONSUMER_ID,
        "logical_effect_contract": dict(LOGICAL_CANDIDATE_EFFECT_CONTRACT),
        "physical_consumer_id": derived_consumer,
        "package_manifest_ref": dict(validated["package_manifest_ref"]),
        "candidate_output_base": logical_candidate_base,
        "route_choice": dict(validated["validated_route_choice"]),
        "boundaries": boundaries,
        "model_invocation_allowed": True,
        "authority": False,
        "completion_claim_allowed": False,
    }


def _atomic_idempotent_json(path: Path, value: Mapping[str, object]) -> str:
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        observed = path.read_bytes()
        if observed != raw:
            raise DispatchEconomicsError(f"immutable route-claim artifact drifted: {path}")
        return hashlib.sha256(observed).hexdigest()
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def _dispatch_claim_identity(envelope: Mapping[str, object]) -> tuple[str, str, str, str]:
    route_choice = _mapping(envelope.get("validated_route_choice"), "validated_route_choice")
    alternative_group = _sha(
        route_choice.get("alternative_group_sha256"),
        "route_choice.alternative_group_sha256",
    )
    choice_sha = _sha(route_choice.get("choice_sha256"), "route_choice.choice_sha256")
    parent_work_key = _text(
        _mapping(
            envelope.get("validated_package_manifest"),
            "validated_package_manifest",
        ).get("parent_work_key"),
        "parent_work_key",
    )
    side_effect_id = f"dispatch-alternative:{alternative_group}"
    return parent_work_key, alternative_group, choice_sha, side_effect_id


def claim_dispatch_route(
    *,
    dispatch_envelope_ref: Mapping[str, object],
    checkpoint_path: Path,
    task_run_dir: Path,
    task_run_cli: Path,
    path_resolver: PathResolver | None = None,
    holder_id: str = "",
) -> dict[str, object]:
    """Atomically claim one A/B alternative on the existing action-resume fact chain."""

    from services.agent_runtime.action_resume_receipt import (
        ActionResumeError,
        action_consumption_path,
        append_pending_action_event_and_reconcile,
        build_action_effect_outcome,
        consume_action_resume_receipt,
        issue_action_resume_receipt,
        write_action_resume_receipt,
    )

    envelope_ref = _validate_path_ref(
        dispatch_envelope_ref,
        "dispatch_envelope_ref",
        path_resolver=path_resolver,
    )
    envelope_logical, envelope_path = _physical_path(
        envelope_ref["path"],
        "dispatch_envelope_ref.path",
        path_resolver,
    )
    _, envelope_raw = _load_hash_bound_ref(
        envelope_ref,
        "dispatch_envelope_ref",
        expected_schema=DISPATCH_ENVELOPE_SCHEMA,
        path_resolver=path_resolver,
    )
    envelope = validate_dispatch_envelope(envelope_raw, path_resolver=path_resolver)
    parent_work_key, alternative_group, choice_sha, side_effect_id = _dispatch_claim_identity(
        envelope
    )
    next_action = f"dispatch-route:{choice_sha}"
    run_dir = Path(task_run_dir).resolve()
    claim_path = action_consumption_path(run_dir, parent_work_key, side_effect_id)

    def existing_result(*, wait_for_same_choice: bool = False) -> dict[str, object] | None:
        deadline = time.monotonic() + (5.0 if wait_for_same_choice else 0.0)
        while True:
            if not claim_path.is_file():
                return None
            try:
                claim = json.loads(claim_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DispatchEconomicsError(f"durable route claim is unreadable: {exc}") from exc
            if not isinstance(claim, dict):
                raise DispatchEconomicsError("durable route claim is not an object")
            if (
                claim.get("work_key") != parent_work_key
                or claim.get("side_effect_id") != side_effect_id
                or claim.get("next_action") != next_action
            ):
                raise DispatchEconomicsError(
                    "alternative group is already claimed by another route choice"
                )
            status = str(claim.get("status") or "")
            if status == "closed":
                break
            if (
                wait_for_same_choice
                and status
                in {
                    "claimed",
                    "effect_in_progress",
                    "readback_verified",
                    "event_pending",
                }
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
                continue
            raise DispatchEconomicsError(
                f"same route claim is not reusable while status={status or 'missing'}"
            )
        outcome = _mapping(claim.get("effect_outcome"), "route_claim.effect_outcome")
        details = _mapping(outcome.get("details"), "route_claim.effect_outcome.details")
        if (
            details.get("alternative_group_sha256") != alternative_group
            or details.get("choice_sha256") != choice_sha
            or details.get("dispatch_envelope_sha256") != envelope_ref["sha256"]
        ):
            raise DispatchEconomicsError("closed route claim identity drifted")
        evidence_refs = _sequence(
            _mapping(outcome.get("readback"), "route_claim.readback").get("evidence_refs"),
            "route_claim.readback.evidence_refs",
        )
        return {
            "schema_version": "xinao.dispatch_route_claim_result.v1",
            "status": "reused",
            "alternative_group_sha256": alternative_group,
            "choice_sha256": choice_sha,
            "leg": envelope["leg"],
            "physical_consumer_id": envelope["validated_physical_consumer_id"],
            "side_effect_id": side_effect_id,
            "claim_path": str(claim_path),
            "route_claim_evidence_ref": str(evidence_refs[0]),
            "model_invocation_allowed": True,
            "authority": False,
            "completion_claim_allowed": False,
        }

    reused = existing_result()
    if reused is not None:
        return reused

    evidence_dir = run_dir / "dispatch_route_claims" / alternative_group
    receipt_path = (
        evidence_dir
        / "receipts"
        / f"{choice_sha}.{os.getpid()}.{os.urandom(8).hex()}.action_resume_receipt.json"
    )
    evidence_path = evidence_dir / f"{choice_sha}.route_claim.json"
    try:
        receipt = issue_action_resume_receipt(
            checkpoint_path=Path(checkpoint_path),
            task_run_dir=run_dir,
            action_kind="dispatch",
            work_key=parent_work_key,
            next_action=next_action,
            side_effect_id=side_effect_id,
            observed_files=[envelope_path],
            work_pin=choice_sha,
            expected_result_phase="worker_route_claimed",
        )
        write_action_resume_receipt(receipt_path, receipt)

        def adapter(context: Mapping[str, object]) -> dict[str, object]:
            evidence = {
                "schema_version": "xinao.work_unit_finalizer_evidence.v1",
                "kind": "dispatch_route_claim",
                "work_key": parent_work_key,
                "subject": alternative_group,
                "observed_value": choice_sha,
                "readback_verified": True,
                "alternative_group_sha256": alternative_group,
                "choice_sha256": choice_sha,
                "leg": envelope["leg"],
                "physical_consumer_id": envelope["validated_physical_consumer_id"],
                "dispatch_envelope_ref": {
                    "path": envelope_logical,
                    "sha256": envelope_ref["sha256"],
                },
                "task_run_path": str(run_dir),
                "side_effect_id": side_effect_id,
                "action_digest": context.get("action_digest"),
                "authority": False,
                "completion_claim_allowed": False,
            }
            evidence_sha = _atomic_idempotent_json(evidence_path, evidence)
            evidence_ref = f"{evidence_path}#sha256={evidence_sha}"
            return build_action_effect_outcome(
                context,
                status="applied",
                adapter_kind="action_resume.dispatch_route_claim.v1",
                observed_before="unclaimed",
                observed_after=choice_sha,
                evidence_refs=[evidence_ref],
                result_phase="worker_route_claimed",
                task_run_evidence_refs=[evidence_ref],
                details={
                    "alternative_group_sha256": alternative_group,
                    "choice_sha256": choice_sha,
                    "dispatch_envelope_sha256": envelope_ref["sha256"],
                    "physical_consumer_id": envelope["validated_physical_consumer_id"],
                },
            )

        consumed = consume_action_resume_receipt(
            receipt_path,
            expected_action_kind="dispatch",
            expected_work_key=parent_work_key,
            expected_side_effect_id=side_effect_id,
            expected_next_action=next_action,
            expected_result_phase="worker_route_claimed",
            consumer=adapter,
            holder_id=holder_id,
        )
        closed = append_pending_action_event_and_reconcile(
            Path(str(consumed["consumption_path"])),
            task_run_cli=task_run_cli,
            actor="dispatch-route-claim-owner",
        )
    except ActionResumeError as exc:
        # A concurrent opposite leg loses at the canonical action-resume claim,
        # before either model process is allowed to start.
        if exc.reason_code == "SIDE_EFFECT_CLAIM_EXISTS":
            reused = existing_result(wait_for_same_choice=True)
            if reused is not None:
                return reused
        raise DispatchEconomicsError(
            f"dispatch alternative claim failed: {exc.reason_code}: {exc}"
        ) from exc
    if closed.get("status") != "closed":
        raise DispatchEconomicsError("dispatch route claim did not close on task-run events")
    evidence_sha = _file_sha(evidence_path)
    return {
        "schema_version": "xinao.dispatch_route_claim_result.v1",
        "status": "won",
        "alternative_group_sha256": alternative_group,
        "choice_sha256": choice_sha,
        "leg": envelope["leg"],
        "physical_consumer_id": envelope["validated_physical_consumer_id"],
        "side_effect_id": side_effect_id,
        "claim_path": str(claim_path),
        "route_claim_evidence_ref": f"{evidence_path}#sha256={evidence_sha}",
        "model_invocation_allowed": True,
        "authority": False,
        "completion_claim_allowed": False,
    }


def validate_dispatch_route_claim(
    *,
    route_claim_evidence_ref: object,
    dispatch_envelope_ref: Mapping[str, object],
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Validate the task-run-backed A/B claim immediately before model start."""

    envelope_ref = _validate_path_ref(
        dispatch_envelope_ref,
        "dispatch_envelope_ref",
        path_resolver=path_resolver,
    )
    _, envelope_raw = _load_hash_bound_ref(
        envelope_ref,
        "dispatch_envelope_ref",
        expected_schema=DISPATCH_ENVELOPE_SCHEMA,
        path_resolver=path_resolver,
    )
    envelope = validate_dispatch_envelope(envelope_raw, path_resolver=path_resolver)
    parent_work_key, alternative_group, choice_sha, side_effect_id = _dispatch_claim_identity(
        envelope
    )
    evidence_path, evidence_sha = _parse_evidence_ref(
        route_claim_evidence_ref,
        path_resolver=path_resolver,
    )
    if not evidence_path.is_file() or _file_sha(evidence_path) != evidence_sha:
        raise DispatchEconomicsError("dispatch route claim evidence is missing or drifted")
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DispatchEconomicsError("dispatch route claim evidence is invalid") from exc
    if not isinstance(evidence, dict):
        raise DispatchEconomicsError("dispatch route claim evidence must be an object")
    expected_envelope_ref = {"path": envelope_ref["path"], "sha256": envelope_ref["sha256"]}
    if (
        evidence.get("schema_version") != "xinao.work_unit_finalizer_evidence.v1"
        or evidence.get("kind") != "dispatch_route_claim"
        or evidence.get("work_key") != parent_work_key
        or evidence.get("subject") != alternative_group
        or evidence.get("observed_value") != choice_sha
        or evidence.get("alternative_group_sha256") != alternative_group
        or evidence.get("choice_sha256") != choice_sha
        or evidence.get("leg") != envelope["leg"]
        or evidence.get("physical_consumer_id") != envelope["validated_physical_consumer_id"]
        or evidence.get("dispatch_envelope_ref") != expected_envelope_ref
        or evidence.get("side_effect_id") != side_effect_id
        or evidence.get("readback_verified") is not True
        or evidence.get("authority") is not False
        or evidence.get("completion_claim_allowed") is not False
    ):
        raise DispatchEconomicsError("dispatch route claim identity drifted")

    _, run_dir = _physical_path(
        evidence.get("task_run_path"),
        "dispatch_route_claim.task_run_path",
        path_resolver,
    )
    events_path = run_dir / "events.jsonl"
    state_path = run_dir / "state.json"
    if not events_path.is_file() or not state_path.is_file():
        raise DispatchEconomicsError("dispatch route claim task-run chain is missing")
    try:
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispatchEconomicsError("dispatch route claim task-run chain is invalid") from exc
    if not isinstance(state, dict) or state.get("events_count") != len(events):
        raise DispatchEconomicsError("dispatch route claim task-run cursor drifted")
    evidence_ref_text = _text(route_claim_evidence_ref, "route_claim_evidence_ref")

    def event_binds_evidence(event: Mapping[str, object]) -> bool:
        for raw_ref in event.get("evidence_refs") or []:
            try:
                bound_path, bound_sha = _parse_evidence_ref(
                    raw_ref,
                    path_resolver=path_resolver,
                )
            except DispatchEconomicsError:
                continue
            if _same_physical_path(bound_path, evidence_path) and bound_sha == evidence_sha:
                return True
        return False

    matching = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("phase") == "worker_route_claimed"
        and event.get("kind") == "result"
        and event.get("target") == parent_work_key
        and event.get("side_effect_id") == side_effect_id
        and event.get("exit_code") == 0
        and event_binds_evidence(event)
    ]
    if len(matching) != 1:
        raise DispatchEconomicsError("dispatch route claim has no unique canonical task-run event")

    from services.agent_runtime.action_resume_receipt import action_consumption_path

    claim_path = action_consumption_path(run_dir, parent_work_key, side_effect_id)
    try:
        claim = json.loads(claim_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispatchEconomicsError("dispatch route action claim is missing or invalid") from exc
    outcome = _mapping(claim.get("effect_outcome"), "dispatch_route_claim.effect_outcome")
    details = _mapping(outcome.get("details"), "dispatch_route_claim.effect_outcome.details")
    if (
        claim.get("status") != "closed"
        or claim.get("work_key") != parent_work_key
        or claim.get("side_effect_id") != side_effect_id
        or claim.get("next_action") != f"dispatch-route:{choice_sha}"
        or outcome.get("expected_result_phase") != "worker_route_claimed"
        or _mapping(
            outcome.get("task_run_result"),
            "dispatch_route_claim.effect_outcome.task_run_result",
        ).get("phase")
        != "worker_route_claimed"
        or details.get("alternative_group_sha256") != alternative_group
        or details.get("choice_sha256") != choice_sha
        or details.get("dispatch_envelope_sha256") != envelope_ref["sha256"]
    ):
        raise DispatchEconomicsError("dispatch route action claim is not closed on this choice")
    return {
        "schema_version": "xinao.dispatch_route_claim_validation.v1",
        "alternative_group_sha256": alternative_group,
        "choice_sha256": choice_sha,
        "leg": envelope["leg"],
        "physical_consumer_id": envelope["validated_physical_consumer_id"],
        "side_effect_id": side_effect_id,
        "route_claim_evidence_ref": evidence_ref_text,
        "model_invocation_allowed": True,
        "authority": False,
        "completion_claim_allowed": False,
    }


def plan_package_frontier(
    manifest: Mapping[str, object],
    *,
    terminal_package_ids: Sequence[str] = (),
    adopted_package_ids: Sequence[str] = (),
    in_flight_package_ids: Sequence[str] = (),
    pending_terminal_count: int | None = None,
    pending_candidate_ingestion_count: int = 0,
    pending_owner_authority_count: int = 0,
    outcome_event_refs: Sequence[Mapping[str, object]] = (),
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Return executable package seals from typed facts and separate capacities."""

    validated = validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    terminal = {_text(value, "terminal_package_ids[]") for value in terminal_package_ids}
    declared_adopted = {_text(value, "adopted_package_ids[]") for value in adopted_package_ids}
    adopted: set[str] = set()
    in_flight = {_text(value, "in_flight_package_ids[]") for value in in_flight_package_ids}
    known = {str(row["package_id"]) for row in validated["packages"]}

    facts: list[tuple[dict[str, str], dict[str, Any]]] = []
    fact_shas: set[str] = set()
    for index, raw_ref in enumerate(outcome_event_refs):
        ref, event = _load_outcome_event_ref(
            raw_ref,
            f"outcome_event_refs[{index}]",
            depth=0,
            path_resolver=path_resolver,
        )
        event_sha = str(event["event_sha256"])
        if event_sha in fact_shas:
            raise DispatchEconomicsError("outcome_event_refs contain duplicate facts")
        if event.get("package_id") not in known:
            raise DispatchEconomicsError("outcome fact refers to an unknown package")
        fact_shas.add(event_sha)
        facts.append((ref, event))
        terminal.add(str(event["package_id"]))
        if event.get("event_type") == "owner_adopted" and event.get("owner_adopted") is True:
            adopted.add(str(event["package_id"]))

    pinned_ref_keys = {_ref_key(ref) for ref, _ in facts}
    for package in validated["packages"]:
        for dependency in package["depends_on"]:
            pin = dependency.get("pin")
            if not isinstance(pin, Mapping):
                continue
            raw_event_ref = _mapping(pin.get("event_ref"), "depends_on.pin.event_ref")
            if _ref_key(raw_event_ref) in pinned_ref_keys:
                continue
            ref, event = _load_outcome_event_ref(
                raw_event_ref,
                "depends_on.pin.event_ref",
                depth=0,
                path_resolver=path_resolver,
            )
            event_sha = str(event["event_sha256"])
            if event_sha not in fact_shas:
                facts.append((ref, event))
                fact_shas.add(event_sha)
            pinned_ref_keys.add(_ref_key(ref))
            terminal.add(str(event["package_id"]))
            if event.get("event_type") == "owner_adopted" and event.get("owner_adopted") is True:
                adopted.add(str(event["package_id"]))

    for label, values in (
        ("terminal", terminal),
        ("adopted", adopted),
        ("declared adopted", declared_adopted),
        ("in_flight", in_flight),
    ):
        unknown = sorted(values - known)
        if unknown:
            raise DispatchEconomicsError(f"unknown {label} package ids: {','.join(unknown)}")
    if declared_adopted - adopted:
        raise DispatchEconomicsError("adopted packages require typed owner_adopted events")
    if not adopted <= terminal:
        raise DispatchEconomicsError("adopted packages must already be terminal")
    candidate_pending = _int_at_least(
        pending_candidate_ingestion_count,
        "pending_candidate_ingestion_count",
        0,
    )
    owner_pending = _int_at_least(
        pending_owner_authority_count,
        "pending_owner_authority_count",
        0,
    )
    if pending_terminal_count is not None:
        legacy_pending = _int_at_least(pending_terminal_count, "pending_terminal_count", 0)
        if pending_owner_authority_count:
            raise DispatchEconomicsError(
                "pending_terminal_count and pending_owner_authority_count cannot both be set"
            )
        owner_pending = legacy_pending
    limits = validated["limits"]
    fan_in_capacity = int(limits["fan_in_capacity"])
    candidate_capacity = int(limits["candidate_ingestion_capacity"])
    max_parallel = int(limits["max_parallel"])
    owner_free = max(0, fan_in_capacity - owner_pending)
    candidate_free = max(0, candidate_capacity - candidate_pending)
    lane_free = max(0, max_parallel - len(in_flight))

    ready: list[dict[str, Any]] = []
    conditionally_ready: list[str] = []
    for source_row in validated["packages"]:
        package_id = str(source_row["package_id"])
        if package_id in terminal or package_id in in_flight:
            continue
        row = copy.deepcopy(source_row)
        resolved_dependencies: list[dict[str, object]] = []
        unresolved = False
        upstream_terminal = True
        for dependency in row["depends_on"]:
            dependency_id = str(dependency["package_id"])
            pin = dependency.get("pin")
            if pin is None:
                matches = [
                    (ref, event)
                    for ref, event in facts
                    if _event_satisfies_dependency(
                        event,
                        package_id=dependency_id,
                        condition=str(dependency["condition"]),
                    )
                ]
                if len(matches) > 1:
                    raise DispatchEconomicsError(
                        f"dependency result is ambiguous for {package_id} <- {dependency_id}"
                    )
                if matches:
                    event_ref, event = matches[0]
                    selected = _expected_dependency_artifact(
                        event, str(dependency["result_selector"])
                    )
                    dependency["pin"] = {
                        "event_ref": event_ref,
                        "artifact_ref": dict(selected),
                    }
                else:
                    unresolved = True
            if dependency_id not in terminal:
                upstream_terminal = False
            resolved_dependencies.append(dependency)
        if unresolved:
            if upstream_terminal:
                conditionally_ready.append(package_id)
            continue
        row["depends_on"] = resolved_dependencies
        old_seal = str(row["package_seal_sha256"])
        row["execution_seal_ready"] = True
        row["package_seal_sha256"] = _canonical_sha(
            {
                "schema_version": "xinao.worker_package_execution_seal.v1",
                "graph_revision": validated["graph_revision"],
                "package_identity_sha256": row["package_identity_sha256"],
                "depends_on": resolved_dependencies,
                "prior_attempt_receipt_ref": row.get("prior_attempt_receipt_ref"),
            }
        )
        if row["package_seal_sha256"] != old_seal:
            row["resealed_from_package_seal_sha256"] = old_seal
        ready.append(row)

    admitted: list[dict[str, Any]] = []
    pending_ready: list[dict[str, Any]] = []
    remaining_parallel = lane_free
    remaining_candidate = candidate_free
    remaining_owner = owner_free
    for row in ready:
        is_candidate = row["candidate_only"] is True
        category_free = remaining_candidate if is_candidate else remaining_owner
        if remaining_parallel > 0 and category_free > 0:
            admitted.append(row)
            remaining_parallel -= 1
            if is_candidate:
                remaining_candidate -= 1
            else:
                remaining_owner -= 1
        else:
            pending_ready.append(row)
    return {
        "schema_version": "xinao.worker_package_frontier.v1",
        "manifest_sha256": validated["validated_manifest_sha256"],
        "graph_revision": validated["graph_revision"],
        "admitted": admitted,
        "pending_ready_package_ids": [str(row["package_id"]) for row in pending_ready],
        "pending_candidate_ready_package_ids": [
            str(row["package_id"]) for row in pending_ready if row["candidate_only"] is True
        ],
        "pending_owner_ready_package_ids": [
            str(row["package_id"]) for row in pending_ready if row["candidate_only"] is False
        ],
        "conditionally_ready_package_ids": conditionally_ready,
        "fan_in_free_slots": remaining_owner,
        "owner_fan_in_free_slots": remaining_owner,
        "candidate_ingestion_free_slots": remaining_candidate,
        "parallel_free_slots": remaining_parallel,
        "backpressure_active": bool(pending_ready),
        "candidate_backpressure_active": bool(
            any(row["candidate_only"] is True for row in pending_ready)
        ),
        "owner_backpressure_active": bool(
            any(row["candidate_only"] is False for row in pending_ready)
        ),
        "terminal_package_ids": sorted(terminal),
        "adopted_package_ids": sorted(adopted),
        "in_flight_package_ids": sorted(in_flight),
        "completion_claim_allowed": False,
    }


def _ref_key(value: Mapping[str, object]) -> tuple[str, str]:
    return (str(value.get("path") or ""), str(value.get("sha256") or ""))


def _validated_artifact_refs(
    values: Sequence[Mapping[str, object]],
    label: str = "artifact_refs",
    *,
    allow_empty: bool = False,
    path_resolver: PathResolver | None = None,
) -> list[dict[str, str]]:
    refs = [
        _validate_path_ref(
            raw,
            f"{label}[{index}]",
            path_resolver=path_resolver,
        )
        for index, raw in enumerate(values)
    ]
    if (not refs and not allow_empty) or len({_ref_key(ref) for ref in refs}) != len(refs):
        suffix = "unique" if allow_empty else "unique and non-empty"
        raise DispatchEconomicsError(f"{label} must be {suffix}")
    return refs


def _load_outcome_event_ref(
    raw: Mapping[str, object],
    label: str,
    *,
    depth: int,
    path_resolver: PathResolver | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    if depth > _MAX_OUTCOME_GRAPH_DEPTH:
        raise DispatchEconomicsError("dispatch outcome reference chain is cyclic or too deep")
    ref = _validate_path_ref(raw, label, path_resolver=path_resolver)
    _, payload = _load_hash_bound_ref(
        ref,
        label,
        expected_schema=OUTCOME_EVENT_SCHEMA,
        path_resolver=path_resolver,
    )
    return ref, validate_dispatch_outcome_event(
        payload,
        _depth=depth + 1,
        path_resolver=path_resolver,
    )


def _package_from_envelope(
    *,
    dispatch_envelope_ref: Mapping[str, object],
    package_manifest_ref: Mapping[str, object],
    package_id: str,
    work_key: str,
    leg: str,
    path_resolver: PathResolver | None = None,
    validation_depth: int = 0,
) -> tuple[dict[str, str], dict[str, str], dict[str, Any], dict[str, Any]]:
    envelope_ref = _validate_path_ref(
        dispatch_envelope_ref,
        "dispatch_envelope_ref",
        path_resolver=path_resolver,
    )
    _, envelope_raw = _load_hash_bound_ref(
        envelope_ref,
        "dispatch_envelope_ref",
        expected_schema=DISPATCH_ENVELOPE_SCHEMA,
        path_resolver=path_resolver,
    )
    envelope = validate_dispatch_envelope(
        envelope_raw,
        path_resolver=path_resolver,
        _validation_depth=validation_depth,
    )
    manifest_ref = _validate_path_ref(
        package_manifest_ref,
        "package_manifest_ref",
        path_resolver=path_resolver,
    )
    if _ref_key(manifest_ref) != _ref_key(envelope["package_manifest_ref"]):
        raise DispatchEconomicsError("dispatch envelope and package manifest binding drifted")
    if envelope["leg"] != leg.upper():
        raise DispatchEconomicsError("dispatch envelope leg mismatch")
    if package_id not in envelope["package_ids"]:
        raise DispatchEconomicsError("package is not admitted by dispatch envelope")
    packages = [
        row
        for row in envelope["validated_package_manifest"]["packages"]
        if row["package_id"] == package_id and row["work_key"] == work_key
    ]
    if len(packages) != 1:
        raise DispatchEconomicsError("package/work_key does not identify one canonical package")
    if envelope["validated_package_seals"].get(package_id) != packages[0]["package_seal_sha256"]:
        raise DispatchEconomicsError("dispatch envelope package execution seal drifted")
    return envelope_ref, manifest_ref, envelope, dict(packages[0])


def _same_identity(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return all(
        left.get(field) == right.get(field)
        for field in (
            "parent_work_key",
            "work_key",
            "package_id",
            "package_manifest_ref",
            "graph_revision",
            "package_seal_sha256",
            "logical_operation_id",
            "leg",
        )
    )


def _validate_consumer_readback(
    raw: Mapping[str, object],
    *,
    work_key: str,
    outcome_refs: Sequence[Mapping[str, object]],
    path_resolver: PathResolver | None = None,
) -> dict[str, str]:
    ref = _validate_path_ref(
        raw,
        "consumer_readback_ref",
        path_resolver=path_resolver,
    )
    _, readback = _load_hash_bound_ref(
        ref,
        "consumer_readback_ref",
        path_resolver=path_resolver,
    )
    if (
        readback.get("schema_version") != "xinao.work_unit_finalizer_evidence.v1"
        or readback.get("authority") is not False
        or readback.get("completion_claim_allowed") is not False
        or readback.get("kind") != "runtime_consumer"
        or readback.get("work_key") != work_key
        or readback.get("readback_verified") is not True
    ):
        raise DispatchEconomicsError("consumer readback is not typed runtime evidence")
    observed = (str(readback.get("subject") or ""), str(readback.get("observed_value") or ""))
    if observed not in {_ref_key(item) for item in outcome_refs}:
        raise DispatchEconomicsError("consumer readback does not bind the adopted artifact")
    return ref


def _validate_authority_readback(
    raw: Mapping[str, object],
    *,
    work_key: str,
    outcome_refs: Sequence[Mapping[str, object]],
    path_resolver: PathResolver | None = None,
) -> dict[str, str]:
    ref = _validate_path_ref(
        raw,
        "authority_readback_ref",
        path_resolver=path_resolver,
    )
    _, readback = _load_hash_bound_ref(
        ref,
        "authority_readback_ref",
        path_resolver=path_resolver,
    )
    raw_applied = readback.get("applied_artifact_refs")
    if not isinstance(raw_applied, list):
        raise DispatchEconomicsError("authority readback is not typed apply evidence")
    applied = _validated_artifact_refs(
        raw_applied,
        "authority_readback_ref.applied_artifact_refs",
        path_resolver=path_resolver,
    )
    if (
        readback.get("schema_version") != "xinao.authority_apply_readback.v1"
        or readback.get("authority") is not False
        or readback.get("completion_claim_allowed") is not False
        or readback.get("work_key") != work_key
        or readback.get("applied") is not True
        or not str(readback.get("subject") or "").strip()
        or not str(readback.get("observed_value") or "").strip()
        or {_ref_key(item) for item in applied} != {_ref_key(item) for item in outcome_refs}
    ):
        raise DispatchEconomicsError("authority readback is not typed apply evidence")
    return ref


def build_dispatch_outcome_event(
    *,
    event_type: str,
    artifact_refs: Sequence[Mapping[str, object]],
    parent_work_key: str = "",
    work_key: str = "",
    package_id: str = "",
    package_manifest_ref: Mapping[str, object] | None = None,
    dispatch_envelope_ref: Mapping[str, object] | None = None,
    logical_operation_id: str = "",
    leg: str = "",
    role: str = "",
    common_attempt_ref: Mapping[str, object] | None = None,
    common_contract_ref: Mapping[str, object] | None = None,
    provider_event_ref: Mapping[str, object] | None = None,
    owner_verdict_event_ref: Mapping[str, object] | None = None,
    owner_adopted_event_ref: Mapping[str, object] | None = None,
    authority_applied_event_ref: Mapping[str, object] | None = None,
    owner_verdict: str | None = None,
    owner_effort: Mapping[str, object] | None = None,
    authority_readback_ref: Mapping[str, object] | None = None,
    consumer_readback_ref: Mapping[str, object] | None = None,
    path_resolver: PathResolver | None = None,
    _validation_depth: int = 0,
    **deprecated: object,
) -> dict[str, object]:
    """Build one typed fact; identity and cost are derived from hash-bound predecessors."""

    if deprecated:
        raise DispatchEconomicsError(
            "unsupported dispatch outcome fields: " + ",".join(sorted(deprecated))
        )
    kind = _text(event_type, "event_type")
    if kind not in {
        "worker_terminal",
        "owner_verdict",
        "owner_adopted",
        "authority_applied",
        "effect_verified",
    }:
        raise DispatchEconomicsError(f"unsupported event_type: {kind}")
    refs = _validated_artifact_refs(
        artifact_refs,
        allow_empty=kind == "worker_terminal",
        path_resolver=path_resolver,
    )

    if kind == "worker_terminal":
        if package_manifest_ref is None or dispatch_envelope_ref is None:
            raise DispatchEconomicsError("worker_terminal requires manifest and dispatch envelope")
        if common_attempt_ref is None or common_contract_ref is None:
            raise DispatchEconomicsError("worker_terminal requires common contract and attempt")
        work = _text(work_key, "work_key")
        package = _text(package_id, "package_id")
        selected_leg = _text(leg, "leg").upper()
        envelope_ref, manifest_ref, envelope, package_row = _package_from_envelope(
            dispatch_envelope_ref=dispatch_envelope_ref,
            package_manifest_ref=package_manifest_ref,
            package_id=package,
            work_key=work,
            leg=selected_leg,
            path_resolver=path_resolver,
            validation_depth=_validation_depth,
        )
        if parent_work_key != package_row["parent_work_key"] or role != package_row["role"]:
            raise DispatchEconomicsError("worker event package parent or role drifted")
        contract_ref = _validate_path_ref(
            common_contract_ref,
            "common_contract_ref",
            path_resolver=path_resolver,
        )
        attempt_ref = _validate_path_ref(
            common_attempt_ref,
            "common_attempt_ref",
            path_resolver=path_resolver,
        )
        _, contract = _load_hash_bound_ref(
            contract_ref,
            "common_contract_ref",
            path_resolver=path_resolver,
        )
        _, attempt = _load_hash_bound_ref(
            attempt_ref,
            "common_attempt_ref",
            path_resolver=path_resolver,
        )
        try:
            from services.agent_runtime.execution_contract import (
                canonical_json_bytes,
                validate_attempt_receipt,
            )

            physical_consumer_id = _text(
                envelope.get("validated_physical_consumer_id"),
                "validated_physical_consumer_id",
            )
            receipt_verdict = validate_attempt_receipt(
                contract,
                attempt,
                expected_consumer_id=physical_consumer_id,
            )
        except (TypeError, ValueError) as exc:
            raise DispatchEconomicsError(
                f"common attempt contract validation failed: {exc}"
            ) from exc
        identity_reasons = {
            reason
            for reason in receipt_verdict.reason_codes
            if reason
            in {
                "CONTRACT_DIGEST_MISMATCH",
                "CONSUMER_MISMATCH",
                "OPERATION_MISMATCH",
                "WORK_KEY_MISMATCH",
                "OBSERVED_RULES_MISMATCH",
                "INVOCATION_MODEL_MISMATCH",
                "OUTPUT_CONTRACT_MISMATCH",
            }
            or reason.startswith("OBSERVED_")
        }
        if identity_reasons:
            raise DispatchEconomicsError(
                "common attempt identity drifted: " + ",".join(sorted(identity_reasons))
            )
        operation = _text(logical_operation_id, "logical_operation_id")
        expected_task_ref = f"{manifest_ref['path']}#sha256={manifest_ref['sha256']}"
        route_selection = envelope["validated_selected_candidate"]
        try:
            from services.agent_runtime.grok_execution_contract_adapter import (
                GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
                direct_worker_pool_capability_binding,
                direct_worker_pool_context_binding_sha256,
                direct_worker_pool_output_contract,
            )

            if selected_leg == "A":
                provider_transport_id = GROK_DIRECT_WORKER_POOL_TRANSPORT_ID
                _, context_manifest = _load_hash_bound_ref(
                    package_row["context_manifest_ref"],
                    "package.context_manifest_ref",
                    path_resolver=path_resolver,
                )
                validated_context = validate_context_slice_manifest(context_manifest)
                acceptance = _mapping(package_row.get("acceptance"), "package.acceptance")
                schema_ref = acceptance.get("json_schema_ref")
                provider_output_contract = direct_worker_pool_output_contract(
                    min_result_chars=int(acceptance["min_result_chars"]),
                    required_result_markers=[
                        str(value) for value in acceptance["required_result_markers"]
                    ],
                    require_json_object=acceptance["require_json_object"] is True,
                    json_schema_sha256=(
                        str(_mapping(schema_ref, "package.acceptance.json_schema_ref")["sha256"])
                        if schema_ref is not None
                        else ""
                    ),
                )
                provider_output_contract_sha256 = hashlib.sha256(
                    canonical_json_bytes(provider_output_contract)
                ).hexdigest()
                provider_context_sha256 = direct_worker_pool_context_binding_sha256(
                    frozen_context_sha256=str(validated_context["context_sha256"]),
                    subject_manifest_sha256=manifest_ref["sha256"],
                )
                provider_capability_binding_sha256 = hashlib.sha256(
                    canonical_json_bytes(
                        direct_worker_pool_capability_binding(
                            selection_decision_sha256=str(envelope["selection"]["decision_sha256"]),
                            output_contract_sha256=provider_output_contract_sha256,
                        )
                    )
                ).hexdigest()
            else:
                adapter = _mapping(
                    envelope.get("validated_execution_adapter"),
                    "validated_execution_adapter",
                )
                provider_transport_id = _text(
                    adapter.get("provider_transport_id"),
                    "validated_execution_adapter.provider_transport_id",
                )
                provider_capability_binding_sha256 = _sha(
                    adapter.get("provider_capability_binding_sha256"),
                    "validated_execution_adapter.provider_capability_binding_sha256",
                )
                provider_context_sha256 = str(package_row["context_sha256"])
                provider_output_contract_sha256 = str(package_row["output_contract_sha256"])
        except (TypeError, ValueError) as exc:
            raise DispatchEconomicsError(
                f"provider capability binding could not be derived: {exc}"
            ) from exc
        provider_selection = {
            "provider_id": route_selection["provider_id"],
            "profile_ref": route_selection["profile_ref"],
            "model_id": route_selection["model_id"],
            "transport_id": provider_transport_id,
            "capability_binding_sha256": provider_capability_binding_sha256,
        }
        if (
            contract.get("logical_operation_id") != operation
            or contract.get("work_key") != work
            or contract.get("task_contract_ref") != expected_task_ref
            or contract.get("input_sha256") != package_row["prompt_ref"]["sha256"]
            or contract.get("context_sha256") != provider_context_sha256
            or contract.get("rules_sha256") != package_row["rules_sha256"]
            or contract.get("output_contract_sha256") != provider_output_contract_sha256
            or package_row.get("logical_consumer_id") != LOGICAL_CANDIDATE_CONSUMER_ID
            or package_row.get("logical_effect_contract") != LOGICAL_CANDIDATE_EFFECT_CONTRACT
            or contract.get("effect_mode") != "authorized_write"
            or any(
                contract.get("selection", {}).get(field) != provider_selection[field]
                for field in (
                    "provider_id",
                    "profile_ref",
                    "model_id",
                    "transport_id",
                    "capability_binding_sha256",
                )
            )
        ):
            raise DispatchEconomicsError("common contract does not bind canonical package dispatch")
        forbidden_control_shas = {
            contract_ref["sha256"],
            attempt_ref["sha256"],
            manifest_ref["sha256"],
            envelope_ref["sha256"],
        }
        if any(ref["sha256"] in forbidden_control_shas for ref in refs):
            raise DispatchEconomicsError(
                "control evidence cannot be borrowed as a provider output artifact"
            )
        primary = next(
            (ref for ref in refs if ref["sha256"] == attempt["output"]["content_sha256"]),
            None,
        )
        if receipt_verdict.accepted and primary is None:
            raise DispatchEconomicsError("accepted provider output artifact is not hash-bound")
        if not receipt_verdict.accepted:
            primary = None
        event: dict[str, object] = {
            "schema_version": OUTCOME_EVENT_SCHEMA,
            "event_type": kind,
            "parent_work_key": parent_work_key,
            "work_key": work,
            "package_id": package,
            "package_manifest_ref": manifest_ref,
            "graph_revision": int(envelope["validated_package_manifest"]["graph_revision"]),
            "package_seal_sha256": str(package_row["package_seal_sha256"]),
            "dispatch_envelope_ref": envelope_ref,
            "logical_operation_id": operation,
            "leg": selected_leg,
            "route_selection": route_selection,
            "provider_selection": provider_selection,
            "logical_consumer_id": package_row["logical_consumer_id"],
            "logical_effect_contract": package_row["logical_effect_contract"],
            "physical_consumer_id": physical_consumer_id,
            "role": role,
            "artifact_refs": refs,
            "primary_artifact_ref": primary,
            "provider_accepted": receipt_verdict.accepted,
            "provider_reason_codes": list(receipt_verdict.reason_codes),
            "common_attempt_ref": attempt_ref,
            "common_contract_ref": contract_ref,
            "attempt_number": int(attempt["attempt"]),
            "attempt_usage": dict(attempt["usage"]),
            "authority": False,
            "completion_claim_allowed": False,
        }
    elif kind == "owner_verdict":
        if provider_event_ref is None:
            raise DispatchEconomicsError("owner verdict requires provider_event_ref")
        provider_ref, provider = _load_outcome_event_ref(
            provider_event_ref,
            "provider_event_ref",
            depth=_validation_depth,
            path_resolver=path_resolver,
        )
        if (
            provider.get("event_type") != "worker_terminal"
            or provider.get("provider_accepted") is not True
        ):
            raise DispatchEconomicsError("owner verdict requires an accepted provider terminal")
        verdict = _text(owner_verdict, "owner_verdict")
        if verdict not in {"adopted", "partially_adopted", "rewritten", "discarded"}:
            raise DispatchEconomicsError("owner_verdict is unsupported")
        provider_artifacts = {_ref_key(item) for item in provider["artifact_refs"]}
        selected_artifacts = {_ref_key(item) for item in refs}
        if provider_ref["sha256"] in {item["sha256"] for item in refs}:
            raise DispatchEconomicsError(
                "provider event control evidence cannot be borrowed as owner output"
            )
        if (
            verdict == "adopted"
            and _ref_key(provider["primary_artifact_ref"]) not in selected_artifacts
        ):
            raise DispatchEconomicsError("adopted verdict must retain provider primary artifact")
        if verdict == "adopted" and not selected_artifacts <= provider_artifacts:
            raise DispatchEconomicsError(
                "adopted verdict can select only provider output artifacts"
            )
        if verdict == "partially_adopted" and not (provider_artifacts & selected_artifacts):
            raise DispatchEconomicsError("partial adoption must retain a provider artifact")
        outcome_refs = [] if verdict == "discarded" else refs
        effort = dict(owner_effort or {})
        redo_tokens = effort.get("redo_tokens", 0)
        if isinstance(redo_tokens, bool) or not isinstance(redo_tokens, int) or redo_tokens < 0:
            raise DispatchEconomicsError("owner_effort.redo_tokens must be >= 0")
        event = {
            **{
                key: provider[key]
                for key in (
                    "parent_work_key",
                    "work_key",
                    "package_id",
                    "package_manifest_ref",
                    "graph_revision",
                    "package_seal_sha256",
                    "dispatch_envelope_ref",
                    "logical_operation_id",
                    "leg",
                )
            },
            "schema_version": OUTCOME_EVENT_SCHEMA,
            "event_type": kind,
            "role": _text(role or "codex_owner", "role"),
            "artifact_refs": refs,
            "provider_event_ref": provider_ref,
            "owner_verdict": verdict,
            "outcome_artifact_refs": outcome_refs,
            "owner_effort": {
                "redo_required": verdict == "rewritten",
                "redo_tokens": redo_tokens,
            },
            "authority": False,
            "completion_claim_allowed": False,
        }
    elif kind == "owner_adopted":
        if owner_verdict_event_ref is None:
            raise DispatchEconomicsError("owner adoption requires owner_verdict_event_ref")
        verdict_ref, verdict_event = _load_outcome_event_ref(
            owner_verdict_event_ref,
            "owner_verdict_event_ref",
            depth=_validation_depth,
            path_resolver=path_resolver,
        )
        if (
            verdict_event.get("event_type") != "owner_verdict"
            or verdict_event.get("owner_verdict") == "discarded"
        ):
            raise DispatchEconomicsError("owner adoption requires a non-discarded owner verdict")
        outcome_refs = list(verdict_event.get("outcome_artifact_refs") or [])
        if {_ref_key(item) for item in refs} != {_ref_key(item) for item in outcome_refs}:
            raise DispatchEconomicsError("owner adoption artifacts differ from verdict outcome")
        if verdict_ref["sha256"] in {item["sha256"] for item in refs}:
            raise DispatchEconomicsError(
                "owner verdict control evidence cannot be borrowed as adopted output"
            )
        event = {
            **{
                key: verdict_event[key]
                for key in (
                    "parent_work_key",
                    "work_key",
                    "package_id",
                    "package_manifest_ref",
                    "graph_revision",
                    "package_seal_sha256",
                    "dispatch_envelope_ref",
                    "logical_operation_id",
                    "leg",
                )
            },
            "schema_version": OUTCOME_EVENT_SCHEMA,
            "event_type": kind,
            "role": _text(role or "codex_owner", "role"),
            "artifact_refs": refs,
            "outcome_artifact_refs": refs,
            "owner_verdict_event_ref": verdict_ref,
            "provider_event_ref": verdict_event["provider_event_ref"],
            "owner_adopted": True,
            "authority": False,
            "completion_claim_allowed": False,
        }
    elif kind == "authority_applied":
        if owner_adopted_event_ref is None or authority_readback_ref is None:
            raise DispatchEconomicsError(
                "authority apply requires owner adoption and authority readback"
            )
        adopted_ref, adopted_event = _load_outcome_event_ref(
            owner_adopted_event_ref,
            "owner_adopted_event_ref",
            depth=_validation_depth,
            path_resolver=path_resolver,
        )
        if (
            adopted_event.get("event_type") != "owner_adopted"
            or adopted_event.get("owner_adopted") is not True
        ):
            raise DispatchEconomicsError("authority apply requires explicit owner adoption")
        outcome_refs = list(adopted_event.get("outcome_artifact_refs") or [])
        if {_ref_key(item) for item in refs} != {_ref_key(item) for item in outcome_refs}:
            raise DispatchEconomicsError("authority artifacts differ from adopted artifacts")
        readback_ref = _validate_authority_readback(
            authority_readback_ref,
            work_key=str(adopted_event["work_key"]),
            outcome_refs=outcome_refs,
            path_resolver=path_resolver,
        )
        control_shas = {adopted_ref["sha256"], readback_ref["sha256"]}
        if any(item["sha256"] in control_shas for item in refs):
            raise DispatchEconomicsError(
                "authority control evidence cannot be borrowed as applied output"
            )
        event = {
            **{
                key: adopted_event[key]
                for key in (
                    "parent_work_key",
                    "work_key",
                    "package_id",
                    "package_manifest_ref",
                    "graph_revision",
                    "package_seal_sha256",
                    "dispatch_envelope_ref",
                    "logical_operation_id",
                    "leg",
                )
            },
            "schema_version": OUTCOME_EVENT_SCHEMA,
            "event_type": kind,
            "role": _text(role or "codex_owner", "role"),
            "artifact_refs": refs,
            "applied_artifact_refs": refs,
            "owner_adopted_event_ref": adopted_ref,
            "owner_verdict_event_ref": adopted_event["owner_verdict_event_ref"],
            "provider_event_ref": adopted_event["provider_event_ref"],
            "authority_applied": True,
            "authority_readback_ref": readback_ref,
            "authority": False,
            "completion_claim_allowed": False,
        }
    else:
        if authority_applied_event_ref is None or consumer_readback_ref is None:
            raise DispatchEconomicsError(
                "effect verification requires authority_applied event and readback"
            )
        authority_ref, authority_event = _load_outcome_event_ref(
            authority_applied_event_ref,
            "authority_applied_event_ref",
            depth=_validation_depth,
            path_resolver=path_resolver,
        )
        if (
            authority_event.get("event_type") != "authority_applied"
            or authority_event.get("authority_applied") is not True
        ):
            raise DispatchEconomicsError("effect requires explicit authority application")
        outcome_refs = list(authority_event.get("applied_artifact_refs") or [])
        if {_ref_key(item) for item in refs} != {_ref_key(item) for item in outcome_refs}:
            raise DispatchEconomicsError("effect artifacts differ from applied artifacts")
        readback_ref = _validate_consumer_readback(
            consumer_readback_ref,
            work_key=str(authority_event["work_key"]),
            outcome_refs=outcome_refs,
            path_resolver=path_resolver,
        )
        control_shas = {authority_ref["sha256"], readback_ref["sha256"]}
        if any(item["sha256"] in control_shas for item in refs):
            raise DispatchEconomicsError(
                "effect control evidence cannot be borrowed as the adopted artifact"
            )
        event = {
            **{
                key: authority_event[key]
                for key in (
                    "parent_work_key",
                    "work_key",
                    "package_id",
                    "package_manifest_ref",
                    "graph_revision",
                    "package_seal_sha256",
                    "dispatch_envelope_ref",
                    "logical_operation_id",
                    "leg",
                )
            },
            "schema_version": OUTCOME_EVENT_SCHEMA,
            "event_type": kind,
            "role": _text(role or "runtime_consumer", "role"),
            "artifact_refs": refs,
            "authority_applied_event_ref": authority_ref,
            "owner_adopted_event_ref": authority_event["owner_adopted_event_ref"],
            "owner_verdict_event_ref": authority_event["owner_verdict_event_ref"],
            "provider_event_ref": authority_event["provider_event_ref"],
            "effect_verified": True,
            "consumer_readback_ref": readback_ref,
            "authority": False,
            "completion_claim_allowed": False,
        }
    event["event_sha256"] = _canonical_sha(event)
    return event


def validate_dispatch_outcome_event(
    payload: Mapping[str, object],
    *,
    _depth: int = 0,
    path_resolver: PathResolver | None = None,
) -> dict[str, Any]:
    """Rebuild one outcome from its evidence graph and reject any caller-authored drift."""

    if not isinstance(payload, Mapping) or payload.get("schema_version") != OUTCOME_EVENT_SCHEMA:
        raise DispatchEconomicsError("dispatch outcome event schema mismatch")
    expected_sha = _sha(payload.get("event_sha256"), "event_sha256")
    body = dict(payload)
    body.pop("event_sha256", None)
    if _canonical_sha(body) != expected_sha:
        raise DispatchEconomicsError("dispatch outcome event_sha256 mismatch")
    kind = str(payload.get("event_type") or "")
    common = {
        "event_type": kind,
        "artifact_refs": list(payload.get("artifact_refs") or []),
        "role": str(payload.get("role") or ""),
        "_validation_depth": _depth,
        "path_resolver": path_resolver,
    }
    if kind == "worker_terminal":
        rebuilt = build_dispatch_outcome_event(
            **common,
            parent_work_key=str(payload.get("parent_work_key") or ""),
            work_key=str(payload.get("work_key") or ""),
            package_id=str(payload.get("package_id") or ""),
            package_manifest_ref=_mapping(
                payload.get("package_manifest_ref"), "package_manifest_ref"
            ),
            dispatch_envelope_ref=_mapping(
                payload.get("dispatch_envelope_ref"), "dispatch_envelope_ref"
            ),
            logical_operation_id=str(payload.get("logical_operation_id") or ""),
            leg=str(payload.get("leg") or ""),
            common_attempt_ref=_mapping(payload.get("common_attempt_ref"), "common_attempt_ref"),
            common_contract_ref=_mapping(payload.get("common_contract_ref"), "common_contract_ref"),
        )
    elif kind == "owner_verdict":
        rebuilt = build_dispatch_outcome_event(
            **common,
            provider_event_ref=_mapping(payload.get("provider_event_ref"), "provider_event_ref"),
            owner_verdict=str(payload.get("owner_verdict") or ""),
            owner_effort=_mapping(payload.get("owner_effort"), "owner_effort"),
        )
    elif kind == "owner_adopted":
        rebuilt = build_dispatch_outcome_event(
            **common,
            owner_verdict_event_ref=_mapping(
                payload.get("owner_verdict_event_ref"), "owner_verdict_event_ref"
            ),
        )
    elif kind == "authority_applied":
        rebuilt = build_dispatch_outcome_event(
            **common,
            owner_adopted_event_ref=_mapping(
                payload.get("owner_adopted_event_ref"), "owner_adopted_event_ref"
            ),
            authority_readback_ref=_mapping(
                payload.get("authority_readback_ref"), "authority_readback_ref"
            ),
        )
    elif kind == "effect_verified":
        rebuilt = build_dispatch_outcome_event(
            **common,
            authority_applied_event_ref=_mapping(
                payload.get("authority_applied_event_ref"), "authority_applied_event_ref"
            ),
            consumer_readback_ref=_mapping(
                payload.get("consumer_readback_ref"), "consumer_readback_ref"
            ),
        )
    else:
        raise DispatchEconomicsError(f"unsupported event_type: {kind}")
    if rebuilt != dict(payload):
        raise DispatchEconomicsError("dispatch outcome contains non-derived or drifted fields")
    return dict(rebuilt)


def _parse_evidence_ref(
    value: object,
    *,
    path_resolver: PathResolver | None = None,
) -> tuple[Path, str]:
    text = _text(value, "evidence_ref")
    marker = "#sha256="
    if marker not in text:
        raise DispatchEconomicsError(f"evidence_ref is not hash-bound: {text}")
    raw_path, raw_sha = text.rsplit(marker, 1)
    _, path = _physical_path(raw_path, "evidence_ref.path", path_resolver)
    return path, _sha(raw_sha, "evidence_ref.sha256")


def project_dispatch_outcomes(
    run_dir: Path,
    *,
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Project non-authoritative economics after validating the existing task-run."""

    resolved = Path(run_dir).resolve(strict=False)
    events_path = resolved / "events.jsonl"
    if not events_path.is_file():
        raise DispatchEconomicsError(f"task-run events missing: {events_path}")
    try:
        task = json.loads((resolved / "task.json").read_text(encoding="utf-8-sig"))
        state = json.loads((resolved / "state.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispatchEconomicsError(f"task-run control files are invalid: {exc}") from exc
    if not isinstance(task, dict) or not isinstance(state, dict):
        raise DispatchEconomicsError("task-run control files must be objects")
    run_id = _text(task.get("run_id"), "task.run_id")
    if state.get("run_id") != run_id:
        raise DispatchEconomicsError("task-run state identity mismatch")
    typed: list[dict[str, Any]] = []
    typed_positions: dict[str, int] = {}
    typed_ref_positions: dict[str, int] = {}
    event_ref_sha_by_event_sha: dict[str, str] = {}
    event_ids: set[str] = set()
    side_effect_ids: set[str] = set()
    legacy_untrusted = 0
    raw_events = []
    for line_number, raw_line in enumerate(
        events_path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            task_event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise DispatchEconomicsError(
                f"invalid task-run event at line {line_number}: {exc}"
            ) from exc
        if not isinstance(task_event, dict):
            raise DispatchEconomicsError(f"task-run event is not an object: line {line_number}")
        raw_events.append(task_event)
        event_id = _text(task_event.get("event_id"), f"events[{line_number}].event_id")
        if event_id in event_ids or task_event.get("run_id") != run_id:
            raise DispatchEconomicsError("task-run event identity is duplicate or drifted")
        event_ids.add(event_id)
        phase = str(task_event.get("phase") or "")
        if phase not in {
            "worker_terminal",
            "owner_verdict",
            "owner_adopted",
            "authority_applied",
            "effect_verified",
        }:
            continue
        side_effect = _text(task_event.get("side_effect_id"), "task_event.side_effect_id")
        if side_effect in side_effect_ids:
            raise DispatchEconomicsError("duplicate typed task-run side_effect_id")
        side_effect_ids.add(side_effect)
        found: dict[str, Any] | None = None
        found_ref_sha: str | None = None
        event_has_legacy = False
        for raw_ref in task_event.get("evidence_refs") or []:
            path, expected = _parse_evidence_ref(raw_ref, path_resolver=path_resolver)
            if not path.is_file():
                raise DispatchEconomicsError(f"dispatch evidence missing: {path}")
            observed = _file_sha(path)
            if observed != expected:
                raise DispatchEconomicsError(
                    f"dispatch evidence sha256 mismatch: expected={expected}; observed={observed}"
                )
            try:
                candidate = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DispatchEconomicsError(f"invalid dispatch evidence: {path}: {exc}") from exc
            if isinstance(candidate, dict):
                if candidate.get("schema_version") == OUTCOME_EVENT_SCHEMA:
                    if found is not None:
                        raise DispatchEconomicsError(
                            "task-run event has multiple dispatch outcomes"
                        )
                    found = validate_dispatch_outcome_event(
                        candidate,
                        path_resolver=path_resolver,
                    )
                    found_ref_sha = expected
                elif str(candidate.get("schema_version") or "").startswith(
                    "xinao.dispatch_outcome_event."
                ):
                    legacy_untrusted += 1
                    event_has_legacy = True
        if found is None:
            if event_has_legacy:
                continue
            raise DispatchEconomicsError(
                f"task-run {phase} event lacks typed dispatch outcome evidence"
            )
        if found.get("event_type") != phase:
            raise DispatchEconomicsError("task-run phase and dispatch event_type mismatch")
        if task_event.get("target") != found.get("work_key"):
            raise DispatchEconomicsError("task-run target and dispatch work_key mismatch")
        event_sha = str(found["event_sha256"])
        if event_sha in typed_positions:
            raise DispatchEconomicsError("duplicate dispatch outcome event")
        assert found_ref_sha is not None
        if found_ref_sha in typed_ref_positions:
            raise DispatchEconomicsError("duplicate dispatch outcome evidence reference")
        typed_positions[event_sha] = line_number
        typed_ref_positions[found_ref_sha] = line_number
        event_ref_sha_by_event_sha[event_sha] = found_ref_sha
        typed.append(found)
    if int(state.get("events_count", -1)) != len(raw_events):
        raise DispatchEconomicsError("task-run state events_count does not match events.jsonl")

    providers = [event for event in typed if event["event_type"] == "worker_terminal"]
    owners = [event for event in typed if event["event_type"] == "owner_verdict"]
    adoptions = [event for event in typed if event["event_type"] == "owner_adopted"]
    authorities = [event for event in typed if event["event_type"] == "authority_applied"]
    effects = [event for event in typed if event["event_type"] == "effect_verified"]
    terminal_work: set[tuple[str, str, str]] = set()
    for event in typed:
        work_identity = (
            str(event["parent_work_key"]),
            str(event["work_key"]),
            str(event["package_id"]),
        )
        if work_identity in terminal_work:
            raise DispatchEconomicsError(
                "typed dispatch outcome mutates a work identity after effect verification"
            )
        if event["event_type"] == "effect_verified":
            terminal_work.add(work_identity)
    provider_by_sha = {
        event_ref_sha_by_event_sha[str(event["event_sha256"])]: event for event in providers
    }
    owner_by_sha = {
        event_ref_sha_by_event_sha[str(event["event_sha256"])]: event for event in owners
    }
    adoption_by_sha = {
        event_ref_sha_by_event_sha[str(event["event_sha256"])]: event for event in adoptions
    }
    authority_by_sha = {
        event_ref_sha_by_event_sha[str(event["event_sha256"])]: event for event in authorities
    }
    last_attempt_by_operation: dict[tuple[str, str, str, str], int] = {}
    for provider in providers:
        operation_key = (
            str(provider["parent_work_key"]),
            str(provider["work_key"]),
            str(provider["package_id"]),
            str(provider["logical_operation_id"]),
        )
        attempt_number = int(provider["attempt_number"])
        previous = last_attempt_by_operation.get(operation_key, 0)
        if attempt_number <= previous:
            raise DispatchEconomicsError(
                "provider attempts are duplicate or out of order for one logical operation"
            )
        last_attempt_by_operation[operation_key] = attempt_number

    seen_provider_links: set[str] = set()
    for owner_event in owners:
        link = str(owner_event["provider_event_ref"]["sha256"])
        if (
            link not in provider_by_sha
            or typed_ref_positions[link] >= typed_positions[str(owner_event["event_sha256"])]
        ):
            raise DispatchEconomicsError("owner verdict predecessor is absent or out of order")
        if link in seen_provider_links:
            raise DispatchEconomicsError("one provider event has conflicting owner verdicts")
        seen_provider_links.add(link)
    seen_verdict_links: set[str] = set()
    for adoption in adoptions:
        link = str(adoption["owner_verdict_event_ref"]["sha256"])
        if (
            link not in owner_by_sha
            or typed_ref_positions[link] >= typed_positions[str(adoption["event_sha256"])]
        ):
            raise DispatchEconomicsError("owner adoption predecessor is absent or out of order")
        if link in seen_verdict_links:
            raise DispatchEconomicsError("one owner verdict has duplicate adoption events")
        seen_verdict_links.add(link)
    seen_adoption_links: set[str] = set()
    for authority_event in authorities:
        link = str(authority_event["owner_adopted_event_ref"]["sha256"])
        if (
            link not in adoption_by_sha
            or typed_ref_positions[link] >= typed_positions[str(authority_event["event_sha256"])]
        ):
            raise DispatchEconomicsError("authority apply predecessor is absent or out of order")
        if link in seen_adoption_links:
            raise DispatchEconomicsError("one owner adoption has duplicate authority events")
        seen_adoption_links.add(link)
    seen_authority_links: set[str] = set()
    for effect in effects:
        link = str(effect["authority_applied_event_ref"]["sha256"])
        if (
            link not in authority_by_sha
            or typed_ref_positions[link] >= typed_positions[str(effect["event_sha256"])]
        ):
            raise DispatchEconomicsError("effect predecessor is absent or out of order")
        if link in seen_authority_links:
            raise DispatchEconomicsError("one authority apply has duplicate effect events")
        seen_authority_links.add(link)

    total_tokens = sum(int(event["attempt_usage"]["total_tokens"]) for event in providers)
    accepted_tokens = sum(int(event["attempt_usage"]["accepted_tokens"]) for event in providers)
    failed_tokens = sum(int(event["attempt_usage"]["failed_tokens"]) for event in providers)
    cancelled_tokens = sum(int(event["attempt_usage"]["cancelled_tokens"]) for event in providers)
    accepted = [event for event in providers if event.get("provider_accepted") is True]
    verdict_counts = {
        verdict: sum(event.get("owner_verdict") == verdict for event in owners)
        for verdict in ("adopted", "partially_adopted", "rewritten", "discarded")
    }
    verified_work_identities = {
        (
            str(event["parent_work_key"]),
            str(event["work_key"]),
            str(event["package_id"]),
        )
        for event in effects
    }
    work_identities = sorted(
        {
            (
                str(event["parent_work_key"]),
                str(event["work_key"]),
                str(event["package_id"]),
            )
            for event in providers
        }
    )
    by_work = []
    for parent_work_key, work_key, package_id in work_identities:
        work_identity = (parent_work_key, work_key, package_id)
        attempts = [
            event
            for event in providers
            if (
                str(event["parent_work_key"]),
                str(event["work_key"]),
                str(event["package_id"]),
            )
            == work_identity
        ]
        attempt_ref_shas = {
            event_ref_sha_by_event_sha[str(attempt["event_sha256"])] for attempt in attempts
        }
        linked_owners = [
            event for event in owners if event["provider_event_ref"]["sha256"] in attempt_ref_shas
        ]
        owner_ref_shas = {
            event_ref_sha_by_event_sha[str(event["event_sha256"])] for event in linked_owners
        }
        linked_adoptions = [
            event
            for event in adoptions
            if event["owner_verdict_event_ref"]["sha256"] in owner_ref_shas
        ]
        adoption_ref_shas = {
            event_ref_sha_by_event_sha[str(event["event_sha256"])] for event in linked_adoptions
        }
        linked_authorities = [
            event
            for event in authorities
            if event["owner_adopted_event_ref"]["sha256"] in adoption_ref_shas
        ]
        if work_identity in verified_work_identities:
            non_conversion_reason = None
        elif any(item.get("owner_verdict") == "discarded" for item in linked_owners):
            non_conversion_reason = "owner_discarded"
        elif any(item.get("provider_accepted") is True for item in attempts) and not linked_owners:
            non_conversion_reason = "owner_verdict_missing"
        elif not any(item.get("provider_accepted") is True for item in attempts):
            non_conversion_reason = "provider_not_accepted"
        elif not linked_adoptions:
            non_conversion_reason = "owner_adoption_missing"
        elif not linked_authorities:
            non_conversion_reason = "authority_apply_missing"
        else:
            non_conversion_reason = "effect_not_verified"
        by_work.append(
            {
                "parent_work_key": parent_work_key,
                "work_key": work_key,
                "package_id": package_id,
                "attempt_count": len(attempts),
                "provider_accepted_attempts": sum(
                    item["provider_accepted"] is True for item in attempts
                ),
                "total_tokens": sum(
                    int(item["attempt_usage"]["total_tokens"]) for item in attempts
                ),
                "accepted_tokens": sum(
                    int(item["attempt_usage"]["accepted_tokens"]) for item in attempts
                ),
                "failed_tokens": sum(
                    int(item["attempt_usage"]["failed_tokens"]) for item in attempts
                ),
                "cancelled_tokens": sum(
                    int(item["attempt_usage"]["cancelled_tokens"]) for item in attempts
                ),
                "owner_verdicts": [str(item["owner_verdict"]) for item in linked_owners],
                "owner_adopted": bool(linked_adoptions),
                "authority_applied": bool(linked_authorities),
                "effect_verified": work_identity in verified_work_identities,
                "non_conversion_reason": non_conversion_reason,
            }
        )
    provider_chain_closed = all(
        (not event["provider_accepted"])
        or event_ref_sha_by_event_sha[str(event["event_sha256"])] in seen_provider_links
        for event in providers
    )
    verdict_chain_closed = all(
        event.get("owner_verdict") == "discarded"
        or event_ref_sha_by_event_sha[str(event["event_sha256"])] in seen_verdict_links
        for event in owners
    )
    adoption_chain_closed = all(
        event_ref_sha_by_event_sha[str(event["event_sha256"])] in seen_adoption_links
        for event in adoptions
    )
    authority_chain_closed = all(
        event_ref_sha_by_event_sha[str(event["event_sha256"])] in seen_authority_links
        for event in authorities
    )
    return {
        "schema_version": OUTCOME_PROJECTION_SCHEMA,
        "run_dir": str(resolved),
        "source": {
            "run_id": run_id,
            "events_sha256": _file_sha(events_path),
            "state_sha256": _file_sha(resolved / "state.json"),
        },
        "event_count": len(typed),
        "summary": {
            "provider_terminal": len(providers),
            "provider_accepted": len(accepted),
            "owner_adopted": len(adoptions),
            "owner_partially_adopted": verdict_counts["partially_adopted"],
            "owner_rewritten": verdict_counts["rewritten"],
            "owner_discarded": verdict_counts["discarded"],
            "authority_applied": len(authorities),
            "effect_verified": len(effects),
            "legacy_untrusted_events": legacy_untrusted,
        },
        "metrics": {
            "total_tokens": total_tokens,
            "accepted_tokens": accepted_tokens,
            "failed_tokens": failed_tokens,
            "cancelled_tokens": cancelled_tokens,
            "accepted_artifact_ratio": (len(adoptions) / len(accepted) if accepted else 0.0),
            "cost_per_verified_work_unit": (
                total_tokens / len(verified_work_identities) if verified_work_identities else None
            ),
            "owner_rewrite_count": verdict_counts["rewritten"],
            "owner_redo_tokens": sum(int(event["owner_effort"]["redo_tokens"]) for event in owners),
        },
        "work_keys": by_work,
        "outcome_chain_closed": bool(providers)
        and provider_chain_closed
        and verdict_chain_closed
        and adoption_chain_closed
        and authority_chain_closed,
        "authority": False,
        "completion_claim_allowed": False,
    }
