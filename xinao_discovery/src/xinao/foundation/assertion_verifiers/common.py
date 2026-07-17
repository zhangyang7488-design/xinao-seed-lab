"""Shared, sealable helpers for canonical foundation assertion actuals sources.

The public block callables intentionally return only observed values.  This
module validates the runner request and binds every file before any domain
compiler is invoked; PASS/FAIL and blueprint expectations belong to the
closure-pack admission layer, not these sources.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_verifier_registry import canonical_python_executable
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    AtomicTicketBindingVersion,
    IndependentExpectedSelectionDomainManifestVersion,
    SelectionManifestComparisonVersion,
    assert_registry_manifest_matches,
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    load_play_catalog,
)
from xinao.foundation.semantics_registry import (
    FoundationSemanticsRegistry,
    compile_semantics_registry,
)
from xinao.foundation.world_compile import (
    _iter_functional_event_payloads,
    compile_functional_world,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

INPUT_KEYS = frozenset(
    {
        "active_quote_projection_sha256",
        "baseline_sha256",
        "compiler_code_sha256",
        "compiler_config_sha256",
        "dataset_sha256",
        "f3_external_synthesis_sha256",
        "f3_prior_draft_sha256",
        "f3_service_graph_sha256",
        "play_catalog_sha256",
        "rule_semantic_map_sha256",
    }
)


class AssertionActualsError(ValueError):
    """Raised before an unbound or drifted actuals bundle can be returned."""


@dataclass(frozen=True)
class PreparedRequest:
    """Hash-checked request projection used by one block verifier."""

    block_id: str
    input_paths: dict[str, Path]
    input_hashes: dict[str, str]
    artifact_paths: dict[str, Path]
    artifact_hashes: dict[str, str]
    artifact_versions: dict[str, str | None]
    required_assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompiledFoundationInputs:
    """Current catalog-derived F1 objects shared by F1-F3 replays."""

    catalog: dict[str, Any]
    registry: FoundationSemanticsRegistry
    independent_manifest: IndependentExpectedSelectionDomainManifestVersion
    selection_comparison: SelectionManifestComparisonVersion
    atomic_ticket_bindings: AtomicTicketBindingVersion


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json_object(path: Path, *, label: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionActualsError(
            f"{label or path} must be a readable UTF-8 JSON object"
        ) from exc
    if not isinstance(value, dict):
        raise AssertionActualsError(f"{label or path} must be a JSON object")
    return value


def content_equal(left: Any, right: Any) -> bool:
    try:
        return canonical_dumps(left) == canonical_dumps(right)
    except (TypeError, ValueError) as exc:
        raise AssertionActualsError("value is not canonical JSON") from exc


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssertionActualsError(f"{label} must be an object")
    if not all(isinstance(key, str) and key for key in value):
        raise AssertionActualsError(f"{label} keys must be non-empty strings")
    return value


def _path_ref(
    value: object,
    *,
    label: str,
    version_required: bool,
) -> tuple[Path, str, str | None]:
    ref = _mapping(value, label=label)
    required = {"path", "sha256"} | ({"version"} if version_required else set())
    missing = sorted(required - set(ref))
    if missing:
        raise AssertionActualsError(f"{label} is missing keys: {missing}")
    path_value = ref["path"]
    if not isinstance(path_value, (str, os.PathLike)):
        raise AssertionActualsError(f"{label}.path must be a path")
    path = Path(path_value).resolve()
    if not path.is_file():
        raise AssertionActualsError(f"{label} does not exist: {path}")
    expected_hash = ref["sha256"]
    if not isinstance(expected_hash, str) or SHA256_RE.fullmatch(expected_hash) is None:
        raise AssertionActualsError(f"{label}.sha256 must be lowercase SHA-256")
    actual_hash = file_sha256(path)
    if actual_hash != expected_hash:
        raise AssertionActualsError(
            f"{label} hash mismatch: expected={expected_hash}, actual={actual_hash}"
        )
    raw_version = ref.get("version")
    if raw_version is not None and (not isinstance(raw_version, str) or not raw_version):
        raise AssertionActualsError(f"{label}.version must be non-empty text")
    return path, actual_hash, raw_version


def prepare_request(
    request: Mapping[str, Any],
    *,
    expected_block_id: str,
    expected_artifact_types: frozenset[str],
    expected_assertion_ids: tuple[str, ...],
) -> PreparedRequest:
    source = _mapping(request, label="request")
    if source.get("block_id") != expected_block_id:
        raise AssertionActualsError(f"request block_id must be {expected_block_id!r}")

    input_ref_key = "input_refs" if "input_refs" in source else "input_evidence"
    input_refs = _mapping(source.get(input_ref_key), label=f"request.{input_ref_key}")
    if set(input_refs) != INPUT_KEYS:
        raise AssertionActualsError(
            "request.input_refs key mismatch: "
            f"missing={sorted(INPUT_KEYS - set(input_refs))}, "
            f"extra={sorted(set(input_refs) - INPUT_KEYS)}"
        )
    artifact_ref_key = "artifact_refs" if "artifact_refs" in source else "artifacts"
    raw_artifact_refs = _mapping(source.get(artifact_ref_key), label=f"request.{artifact_ref_key}")
    if artifact_ref_key == "artifact_refs":
        artifact_refs: Mapping[str, Any] = raw_artifact_refs
    else:
        normalized_artifact_refs: dict[str, dict[str, Any]] = {}
        for artifact_type, raw in raw_artifact_refs.items():
            wrapper = _mapping(raw, label=f"request.artifacts[{artifact_type}]")
            envelope = _mapping(
                wrapper.get("staged_envelope"),
                label=f"request.artifacts[{artifact_type}].staged_envelope",
            )
            recorded_envelope_hash = wrapper.get("staged_envelope_content_sha256")
            if (
                not isinstance(recorded_envelope_hash, str)
                or canonical_sha256(envelope) != recorded_envelope_hash
            ):
                raise AssertionActualsError(
                    f"request artifact envelope hash mismatch: {artifact_type}"
                )
            if envelope.get("artifact_type") != artifact_type:
                raise AssertionActualsError(
                    f"request artifact envelope identity mismatch: {artifact_type}"
                )
            envelope_bindings = (
                ("input_hashes", "input_hashes"),
                ("code_hash", "compiler_code_sha256"),
                ("config_hash", "compiler_config_sha256"),
            )
            for envelope_key, request_key in envelope_bindings:
                if envelope.get(envelope_key) != source.get(request_key):
                    raise AssertionActualsError(
                        "request artifact envelope binding mismatch: "
                        f"{artifact_type}.{envelope_key}"
                    )
            payload = _mapping(
                envelope.get("payload"),
                label=f"request.artifacts[{artifact_type}].payload",
            )
            if canonical_sha256(payload) != envelope.get("payload_sha256"):
                raise AssertionActualsError(
                    f"request artifact payload hash mismatch: {artifact_type}"
                )
            source_ref = _mapping(
                envelope.get("source_ref"),
                label=f"request.artifacts[{artifact_type}].source_ref",
            )
            normalized_artifact_refs[artifact_type] = {
                "path": source_ref.get("path"),
                "sha256": source_ref.get("sha256"),
                "version": envelope.get("version"),
                "request_payload": dict(payload),
            }
        artifact_refs = normalized_artifact_refs
    if set(artifact_refs) != expected_artifact_types:
        raise AssertionActualsError(
            "request.artifact_refs key mismatch: "
            f"missing={sorted(expected_artifact_types - set(artifact_refs))}, "
            f"extra={sorted(set(artifact_refs) - expected_artifact_types)}"
        )

    if "required_assertion_ids" in source and "assertion_ids" in source:
        raise AssertionActualsError(
            "request may contain assertion_ids or required_assertion_ids, not both"
        )
    raw_assertion_ids = source.get("assertion_ids", source.get("required_assertion_ids"))
    if (
        not isinstance(raw_assertion_ids, Sequence)
        or isinstance(raw_assertion_ids, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in raw_assertion_ids)
    ):
        raise AssertionActualsError("request.required_assertion_ids must be a text list")
    assertion_ids = tuple(raw_assertion_ids)
    if len(assertion_ids) != len(set(assertion_ids)) or set(assertion_ids) != set(
        expected_assertion_ids
    ):
        raise AssertionActualsError(
            "request.required_assertion_ids does not match the verifier inventory"
        )

    input_paths: dict[str, Path] = {}
    input_hashes: dict[str, str] = {}
    artifact_paths: dict[str, Path] = {}
    artifact_hashes: dict[str, str] = {}
    artifact_versions: dict[str, str | None] = {}
    seen_paths: set[Path] = set()
    for key in sorted(INPUT_KEYS):
        path, digest, _ = _path_ref(
            input_refs[key], label=f"request.input_refs[{key}]", version_required=False
        )
        if path in seen_paths:
            raise AssertionActualsError(f"request path is reused: {path}")
        seen_paths.add(path)
        input_paths[key] = path
        input_hashes[key] = digest
    for artifact_type in sorted(expected_artifact_types):
        path, digest, version = _path_ref(
            artifact_refs[artifact_type],
            label=f"request.artifact_refs[{artifact_type}]",
            version_required=True,
        )
        if path in seen_paths:
            raise AssertionActualsError(f"request path is reused: {path}")
        seen_paths.add(path)
        artifact_paths[artifact_type] = path
        artifact_hashes[artifact_type] = digest
        artifact_versions[artifact_type] = version
        request_payload = artifact_refs[artifact_type].get("request_payload")
        if request_payload is not None and not content_equal(
            load_json_object(path, label=f"artifact {artifact_type}"), request_payload
        ):
            raise AssertionActualsError(
                f"request artifact payload/source mismatch: {artifact_type}"
            )

    request_input_hashes = source.get("input_hashes")
    if request_input_hashes is not None and request_input_hashes != input_hashes:
        raise AssertionActualsError("request input_hashes do not match input evidence")
    if artifact_ref_key == "artifacts":
        if source.get("compiler_code_sha256") != input_hashes["compiler_code_sha256"]:
            raise AssertionActualsError(
                "request compiler_code_sha256 does not match input evidence"
            )
        if source.get("compiler_config_sha256") != input_hashes["compiler_config_sha256"]:
            raise AssertionActualsError(
                "request compiler_config_sha256 does not match input evidence"
            )

    return PreparedRequest(
        block_id=expected_block_id,
        input_paths=input_paths,
        input_hashes=input_hashes,
        artifact_paths=artifact_paths,
        artifact_hashes=artifact_hashes,
        artifact_versions=artifact_versions,
        required_assertion_ids=tuple(sorted(assertion_ids)),
    )


def validate_model_payloads(
    payloads: Mapping[str, dict[str, Any]],
    models: Mapping[str, type[Any]],
    *,
    block_label: str,
) -> None:
    for artifact_type, model in models.items():
        try:
            model.model_validate(payloads[artifact_type])
        except Exception as exc:
            raise AssertionActualsError(
                f"retained {block_label} artifact is invalid: {artifact_type}"
            ) from exc


def recompute_event_key_deltas(registry: Any, world: Any) -> tuple[bool, int, int, int]:
    expected_draw_ids = {draw.draw_id for draw in world.loaded_dataset.draws}
    expected_baselines = set(ACTIVE_SETTLEMENT_BASELINE_IDS)
    expected_count = len(expected_draw_ids) * len(expected_baselines)
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    unexpected_count = 0
    for cell in _iter_functional_event_payloads(registry, world.loaded_dataset.draws):
        key = (str(cell["draw_id"]), str(cell["baseline_id"]))
        if key in seen:
            duplicate_count += 1
        else:
            seen.add(key)
        if key[0] not in expected_draw_ids or key[1] not in expected_baselines:
            unexpected_count += 1
    valid_seen_count = sum(
        draw_id in expected_draw_ids and baseline_id in expected_baselines
        for draw_id, baseline_id in seen
    )
    missing_count = expected_count - valid_seen_count
    return (
        missing_count == unexpected_count == duplicate_count == 0,
        missing_count,
        unexpected_count,
        duplicate_count,
    )


def required_rule_fields_actual(registry: Any, required_rule_fields: Sequence[str]) -> list[str]:
    manifest_by_id = {
        item.spec_id: item for item in registry.expected_selection_domain.specifications
    }
    records = registry.rule_semantic_map.records
    checks = {
        "semantic_evidence_status": all(record.semantic_evidence_statuses for record in records),
        "selection_space": all(
            record.selection_domain_spec_id in manifest_by_id for record in records
        ),
        "settlement_tiers": all(record.settlement_tiers for record in records),
        "snapshot_payout_binding": all(record.snapshot_payout_binding for record in records),
        "principal_refund_on_normal_settlement": all(
            record.principal_refund_on_normal_settlement is False for record in records
        ),
        "void_policy": all(record.void_policy for record in records),
        "rounding_policy": all(record.rounding_policy for record in records),
        "boundary_policy": all(record.boundary_policy for record in records),
        "effective_interval": all(record.effective_interval for record in records),
    }
    return [field for field in required_rule_fields if checks.get(field) is True]


def reordered_world_matches(
    registry: Any,
    world: Any,
    replay: Any,
    dataset_path: Path,
) -> bool:
    lines = dataset_path.read_text(encoding="utf-8").splitlines()
    try:
        marker = next(
            index for index, line in enumerate(lines) if line.startswith("【API完整字段 JSONL")
        )
    except StopIteration as exc:
        raise AssertionActualsError("authority dataset has no JSONL marker") from exc
    with tempfile.TemporaryDirectory(prefix="xinao-f1-reordered-") as temporary:
        reordered_path = Path(temporary) / "authority_reordered.txt"
        reordered_path.write_text(
            "\n".join([*lines[: marker + 1], *reversed(lines[marker + 1 :])]) + "\n",
            encoding="utf-8",
        )
        reordered = compile_functional_world(
            registry,
            reordered_path,
            replay_results=tuple(item.result for item in replay.cases),
        )
    return (
        reordered.event_matrix_snapshot.content_hash == world.event_matrix_snapshot.content_hash
        and reordered.world_snapshot.content_hash == world.world_snapshot.content_hash
    )


def run_f1_isolated_recomputation(prepared: PreparedRequest) -> dict[str, dict[str, Any]]:
    """Run the three independent F1 recomputations in fresh Python processes.

    Seed, final, and reordered phases start from the already hash-bound catalog
    and dataset, persist only JSON primitives, and are discarded before the next
    phase.  Each world compilation obtains event-key completeness from the same
    stdlib-only Cartesian stream proof; there is no redundant fourth traversal.
    """

    module = "xinao.foundation.assertion_verifiers._f1_phase_worker"
    python = canonical_python_executable()
    catalog_path = prepared.input_paths["play_catalog_sha256"]
    dataset_path = prepared.input_paths["dataset_sha256"]
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")
    }

    with tempfile.TemporaryDirectory(prefix="xinao-f1-actuals-") as temporary:
        root = Path(temporary)
        seed_path = root / "seed_results.json"
        final_path = root / "final_recomputation.json"
        reordered_path = root / "reordered_recomputation.json"

        def invoke(phase: str, *paths: Path) -> None:
            completed = subprocess.run(
                [
                    str(python),
                    "-X",
                    "faulthandler",
                    "-I",
                    "-m",
                    module,
                    phase,
                    str(catalog_path),
                    str(dataset_path),
                    *(str(path) for path in paths),
                ],
                capture_output=True,
                check=False,
                encoding="utf-8",
                env=environment,
                timeout=180,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()[-4000:]
                raise AssertionActualsError(
                    f"isolated F1 {phase} recomputation failed "
                    f"with exit {completed.returncode}: {detail}"
                )

        invoke("seed", seed_path)
        invoke("final", seed_path, final_path)
        invoke("reordered", final_path, reordered_path)
        final = load_json_object(final_path, label="isolated F1 final output")
        event_keys = final.get("event_keys")
        if not isinstance(event_keys, dict):
            raise AssertionActualsError("isolated F1 final key proof is absent")
        return {
            "final": final,
            "reordered": load_json_object(reordered_path, label="isolated F1 reordered output"),
            "event_keys": event_keys,
        }


def recursively_has_forbidden_key(value: object, forbidden: frozenset[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or recursively_has_forbidden_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(recursively_has_forbidden_key(item, forbidden) for item in value)
    return False


def load_artifact_payloads(prepared: PreparedRequest) -> dict[str, dict[str, Any]]:
    return {
        artifact_type: load_json_object(path, label=f"artifact {artifact_type}")
        for artifact_type, path in prepared.artifact_paths.items()
    }


def assert_recomputed_artifacts(
    retained: Mapping[str, dict[str, Any]],
    recomputed: Mapping[str, dict[str, Any]],
) -> None:
    if set(retained) != set(recomputed):
        raise AssertionActualsError(
            "recomputed artifact inventory drifted: "
            f"missing={sorted(set(retained) - set(recomputed))}, "
            f"extra={sorted(set(recomputed) - set(retained))}"
        )
    mismatches = [
        artifact_type
        for artifact_type in sorted(retained)
        if not content_equal(retained[artifact_type], recomputed[artifact_type])
    ]
    if mismatches:
        raise AssertionActualsError(
            f"retained artifacts do not equal current recomputation: {mismatches}"
        )


def active_quote_projection(registry: FoundationSemanticsRegistry) -> dict[str, Any]:
    return {
        "schema_version": "xinao.active_default_quote_projection_input.v1",
        "source_registry_hash": registry.content_hash,
        "active_semantics_hash": registry.active_physical_semantics_hash,
        "active_quote_policy": "A_OR_DEFAULT_HIGHEST_ONLY",
        "component_count": 416,
        "components": [
            {
                "baseline_id": record.baseline_id,
                "semantic_record_hash": record.content_hash,
                "quote_components": list(record.quote_components),
                "snapshot_payout_binding": record.snapshot_payout_binding,
            }
            for record in registry.rule_semantic_map.records
        ],
    }


def compile_registry_input(
    prepared: PreparedRequest,
) -> tuple[dict[str, Any], FoundationSemanticsRegistry]:
    """Compile and bind the catalog registry without retaining ticket-domain models."""

    catalog = load_play_catalog(prepared.input_paths["play_catalog_sha256"])
    registry = compile_semantics_registry(catalog)
    retained_semantic_map = load_json_object(
        prepared.input_paths["rule_semantic_map_sha256"],
        label="rule_semantic_map_sha256 input",
    )
    if not content_equal(retained_semantic_map, registry.rule_semantic_map.model_dump(mode="json")):
        raise AssertionActualsError(
            "rule_semantic_map_sha256 input does not equal current catalog compilation"
        )
    retained_projection = load_json_object(
        prepared.input_paths["active_quote_projection_sha256"],
        label="active_quote_projection_sha256 input",
    )
    if not content_equal(retained_projection, active_quote_projection(registry)):
        raise AssertionActualsError(
            "active_quote_projection_sha256 input does not equal current catalog compilation"
        )
    return catalog, registry


def compile_foundation_inputs(prepared: PreparedRequest) -> CompiledFoundationInputs:
    catalog, registry = compile_registry_input(prepared)
    independent = compile_independent_selection_manifest(catalog)
    comparison = assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    atomic = compile_atomic_ticket_bindings(catalog, independent)
    return CompiledFoundationInputs(
        catalog=catalog,
        registry=registry,
        independent_manifest=independent,
        selection_comparison=comparison,
        atomic_ticket_bindings=atomic,
    )


def ensure_exact_actuals(
    actuals: Mapping[str, Any], *, expected_assertion_ids: tuple[str, ...]
) -> dict[str, Any]:
    if set(actuals) != set(expected_assertion_ids):
        raise AssertionActualsError(
            "actual assertion inventory drifted: "
            f"missing={sorted(set(expected_assertion_ids) - set(actuals))}, "
            f"extra={sorted(set(actuals) - set(expected_assertion_ids))}"
        )
    result = {assertion_id: actuals[assertion_id] for assertion_id in sorted(actuals)}
    try:
        canonical_dumps(result)
    except (TypeError, ValueError) as exc:
        raise AssertionActualsError("actual assertion values are not canonical JSON") from exc
    return result
