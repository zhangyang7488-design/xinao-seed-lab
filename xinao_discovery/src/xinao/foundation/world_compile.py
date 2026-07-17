"""Compile the 913 x 416 F1 physical event surface in memory.

The event surface binds every historical draw to the 416 active settlement rows.
The 17 B rows remain catalog-only frozen agent-route quotes and never enter the
semantic registry, selection gate, physical event cells, or replay work.
It deliberately does not expand the 21.6 billion conceptual atomic tickets.
Instead, each functional cell binds a draw replay input, one canonical semantic
record, and one independently partitioned selection-domain descriptor.  A
caller can lazily construct and settle any valid ticket from those bindings.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xinao.canonical import canonical_sha256, ordered_json_stream_sha256
from xinao.foundation.selection_manifest import (
    EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
    AtomicTicketBindingDescriptor,
    AtomicTicketBindingVersion,
    AtomicTicketSelection,
    IndependentExpectedSelectionDomainManifestVersion,
    SelectionManifestComparisonVersion,
    assert_registry_manifest_matches,
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    iter_atomic_ticket_selections,
    load_play_catalog,
)
from xinao.foundation.semantics_basic import settle_basic_record
from xinao.foundation.semantics_combinations import settle_combination
from xinao.foundation.semantics_linked import settle_linked_ticket, settle_parlay_ticket
from xinao.foundation.semantics_registry import (
    EXPECTED_ACTIVE_FAMILY_COUNTS,
    FoundationSemanticsRegistry,
)
from xinao.foundation.semantics_sets import settle_rule

DEFAULT_AUTHORITY_DATASET_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\03正式数据"
    r"\新澳门六合彩_macaujc2_完整权威数据_2024-01-01_至_2026-07-01.txt"
)
JSONL_SECTION_PREFIX = "【API完整字段 JSONL"
PURE_ASCII_STREAM_WORKER = Path(__file__).with_name("f1_pure_ascii_stream_worker.py")
PURE_ASCII_STREAM_PROJECTION_SCHEMA = "xinao.f1_pure_ascii_stream_projection.v1"
PURE_ASCII_STREAM_RESULT_SCHEMA = "xinao.f1_pure_ascii_stream_result.v1"


@dataclass(frozen=True, slots=True)
class DatasetExpectation:
    draw_count: int
    first_draw_id: str
    last_draw_id: str
    first_draw_date: str
    last_draw_date: str
    require_consecutive_dates: bool = True


FORMAL_913_EXPECTATION = DatasetExpectation(
    draw_count=913,
    first_draw_id="2024001",
    last_draw_id="2026182",
    first_draw_date="2024-01-01",
    last_draw_date="2026-07-01",
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> _ContentHashedModel:
        body = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(body) != self.content_hash:
            raise ValueError("content_hash does not bind the canonical payload")
        return self


class DrawReplayInput(_ContentHashedModel):
    schema_version: Literal["xinao.draw_replay_input.v1"] = "xinao.draw_replay_input.v1"
    draw_id: str = Field(pattern=r"^\d{7}$")
    open_time: str
    draw_date: str
    source_open_code_raw: str
    numbers: tuple[int, ...] = Field(min_length=7, max_length=7)
    source_zodiac_raw: str
    source_zodiac_values: tuple[str, ...] = Field(min_length=7, max_length=7)
    source_wave_raw: str
    source_wave_values: tuple[str, ...] = Field(min_length=7, max_length=7)
    source_type: str
    source_verify: bool
    source_payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    zodiac_basis_ref: Literal["SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"] = (
        "SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"
    )
    draw_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("numbers")
    @classmethod
    def validate_numbers(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(isinstance(value, bool) or not 1 <= value <= 49 for value in values):
            raise ValueError("draw numbers must be integers from 1 to 49")
        if len(values) != len(set(values)):
            raise ValueError("draw numbers must be unique")
        return values

    @model_validator(mode="after")
    def validate_raw_bindings(self) -> DrawReplayInput:
        if tuple(int(value) for value in self.source_open_code_raw.split(",")) != self.numbers:
            raise ValueError("raw openCode does not reproduce parsed numbers")
        if tuple(self.source_zodiac_raw.split(",")) != self.source_zodiac_values:
            raise ValueError("raw zodiac field was not preserved exactly")
        if tuple(self.source_wave_raw.split(",")) != self.source_wave_values:
            raise ValueError("raw wave field was not preserved exactly")
        parsed = datetime.strptime(self.open_time, "%Y-%m-%d %H:%M:%S")
        if parsed.date().isoformat() != self.draw_date:
            raise ValueError("openTime and draw_date disagree")
        return self


@dataclass(frozen=True, slots=True)
class LoadedDrawDataset:
    draws: tuple[DrawReplayInput, ...]
    raw_json_line_count: int
    duplicate_json_line_count: int
    source_annual_endpoints: tuple[int, ...]
    dataset_semantic_hash: str


class FunctionalEventCell(_FrozenModel):
    schema_version: Literal["xinao.functional_event_cell.v1"] = "xinao.functional_event_cell.v1"
    surface_kind: Literal["FUNCTIONAL_EVENT_SURFACE"] = "FUNCTIONAL_EVENT_SURFACE"
    physical_role: Literal["ACTIVE_SETTLEMENT"] = "ACTIVE_SETTLEMENT"
    draw_id: str = Field(pattern=r"^\d{7}$")
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    semantic_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_domain_spec_id: str
    selection_domain_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_selection_domain_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atomic_ticket_binding_id: str | None
    atomic_ticket_binding_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    settlement_function_ref: str
    draw_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    draw_replay_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draw_date: str
    zodiac_basis_ref: Literal["SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"] = (
        "SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"
    )


class LazyDomainProof(_ContentHashedModel):
    schema_version: Literal["xinao.lazy_domain_proof.v1"] = "xinao.lazy_domain_proof.v1"
    active_selection_domain_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_manifest_exact_match: Literal[True] = True
    atomic_ticket_binding_ref: str
    active_atomic_ticket_binding_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atomic_ticket_binding_count: Literal[37] = 37
    composite_exact_atomic_ticket_count: Literal[21652539822] = 21652539822
    descriptor_count: Literal[233] = 233
    component_baseline_count: Literal[416] = 416
    component_binding_count: Literal[416] = 416
    exact_conceptual_atomic_selection_count: Literal[21652542248] = 21652542248
    expanded_atomic_ticket_keys_materialized: Literal[False] = False
    materialized_atomic_ticket_key_count: Literal[0] = 0
    binding_method: Literal["INDEPENDENT_MANIFEST_PARTITION_REBOUND_BY_BASELINE"] = (
        "INDEPENDENT_MANIFEST_PARTITION_REBOUND_BY_BASELINE"
    )
    active_baseline_to_descriptor_ordered_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_binding_complete: Literal[True] = True


class FamilyReplayCoverage(_FrozenModel):
    family_id: str
    required_case_kinds: tuple[Literal["POSITIVE", "NEGATIVE", "BOUNDARY"], ...] = (
        "POSITIVE",
        "NEGATIVE",
        "BOUNDARY",
    )
    executed_case_kinds: tuple[Literal["POSITIVE", "NEGATIVE", "BOUNDARY"], ...]
    passed_case_kinds: tuple[Literal["POSITIVE", "NEGATIVE", "BOUNDARY"], ...]
    failed_case_ids: tuple[str, ...]
    status: Literal["VERIFIED", "PARTIAL", "FAILED"]


class RepresentativeReplayEvidenceSummary(_ContentHashedModel):
    schema_version: Literal["xinao.representative_replay_evidence.v1"] = (
        "xinao.representative_replay_evidence.v1"
    )
    replay_interface_ref: Literal["replay_family_case.v1"] = "replay_family_case.v1"
    family_count: Literal[13] = 13
    required_case_kinds_per_family: tuple[Literal["POSITIVE", "NEGATIVE", "BOUNDARY"], ...] = (
        "POSITIVE",
        "NEGATIVE",
        "BOUNDARY",
    )
    executed_case_count: int = Field(ge=0)
    asserted_pass_count: int = Field(ge=0)
    asserted_fail_count: int = Field(ge=0)
    result_status: Literal["VERIFIED", "PARTIAL", "FAILED"]
    family_coverage: tuple[FamilyReplayCoverage, ...]
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    limitation: str


class FunctionalCoverage(_FrozenModel):
    coverage_mode: Literal["FUNCTIONAL_EVENT_SURFACE"] = "FUNCTIONAL_EVENT_SURFACE"
    draw_count: int = Field(gt=0)
    active_settlement_component_count: Literal[416] = 416
    expected_functional_cell_count: int = Field(gt=0)
    actual_functional_cell_count: int = Field(gt=0)
    missing_functional_key_count: Literal[0] = 0
    unexpected_functional_key_count: Literal[0] = 0
    duplicate_functional_key_count: Literal[0] = 0
    expanded_atomic_ticket_keys_materialized: Literal[False] = False
    expanded_ticket_coverage_status: Literal["NOT_MATERIALIZED_BY_DESIGN"] = (
        "NOT_MATERIALIZED_BY_DESIGN"
    )
    functional_component_coverage_status: Literal["VERIFIED"] = "VERIFIED"

    @model_validator(mode="after")
    def validate_count(self) -> FunctionalCoverage:
        if (
            self.expected_functional_cell_count
            != self.draw_count * self.active_settlement_component_count
        ):
            raise ValueError("expected functional cell count is not draw x active component")
        if self.actual_functional_cell_count != self.expected_functional_cell_count:
            raise ValueError("functional event surface is incomplete")
        return self


class EventMatrixSnapshot(_ContentHashedModel):
    schema_version: Literal["xinao.event_matrix_snapshot.functional.v1"] = (
        "xinao.event_matrix_snapshot.functional.v1"
    )
    snapshot_ref: Literal["event-matrix.all-416-active.functional.verified-draws.v1"] = (
        "event-matrix.all-416-active.functional.verified-draws.v1"
    )
    surface_kind: Literal["FUNCTIONAL_EVENT_SURFACE"] = "FUNCTIONAL_EVENT_SURFACE"
    dataset_semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_semantics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_selection_domain_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_atomic_ticket_binding_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_draw_id: str
    last_draw_id: str
    first_draw_date: str
    last_draw_date: str
    family_cell_counts: dict[str, int]
    coverage: FunctionalCoverage
    cell_stream_encoding: Literal["JCS_LENGTH_PREFIXED_V1"] = "JCS_LENGTH_PREFIXED_V1"
    ordered_cell_stream_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_merkle_method: Literal["ORDERED_MERKLE_FRONTIER_V1"] = "ORDERED_MERKLE_FRONTIER_V1"
    ordered_merkle_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    cells_materialized: Literal[False] = False
    lazy_domain_proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_replay_status: Literal["VERIFIED", "PARTIAL", "FAILED"]
    f1_status: Literal["PARTIAL"] = "PARTIAL"
    f1_limitation: str


class WorldSnapshot(_ContentHashedModel):
    schema_version: Literal["xinao.world_snapshot.functional.v1"] = (
        "xinao.world_snapshot.functional.v1"
    )
    world_ref: Literal["world.all-416-active.functional.verified-draws.v1"] = (
        "world.all-416-active.functional.verified-draws.v1"
    )
    event_matrix_snapshot_ref: str
    event_matrix_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_semantics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_selection_domain_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_atomic_ticket_binding_structural_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draw_inputs: tuple[DrawReplayInput, ...]
    lazy_domain_proof: LazyDomainProof
    representative_replay_evidence: RepresentativeReplayEvidenceSummary
    knowledge_cutoff_at: str
    world_mode: Literal["FUNCTIONAL_EVENT_SURFACE_WITH_LAZY_ATOMIC_TICKETS"] = (
        "FUNCTIONAL_EVENT_SURFACE_WITH_LAZY_ATOMIC_TICKETS"
    )
    expanded_atomic_ticket_keys_materialized: Literal[False] = False
    f1_status: Literal["PARTIAL"] = "PARTIAL"


@dataclass(frozen=True, slots=True)
class FunctionalWorldCompilation:
    loaded_dataset: LoadedDrawDataset
    event_matrix_snapshot: EventMatrixSnapshot
    world_snapshot: WorldSnapshot
    functional_key_proof: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _SelectionOracle:
    independent_manifest: IndependentExpectedSelectionDomainManifestVersion
    manifest_comparison: SelectionManifestComparisonVersion
    atomic_ticket_bindings: AtomicTicketBindingVersion
    active_selection_domain_structural_hash: str
    active_atomic_ticket_binding_structural_hash: str
    domain_by_baseline: dict[str, tuple[Any, Any, AtomicTicketBindingDescriptor | None]]
    lazy_domain_proof: LazyDomainProof


class FamilyReplayCase(_FrozenModel):
    schema_version: Literal["xinao.family_replay_case.v1"] = "xinao.family_replay_case.v1"
    case_id: str
    case_kind: Literal["POSITIVE", "NEGATIVE", "BOUNDARY"]
    draw_id: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    selection: tuple[int | str, ...] = ()
    expected_outcome: Literal["HIT", "MISS", "VOID"] | None = None


class FamilyReplayResult(_ContentHashedModel):
    schema_version: Literal["xinao.family_replay_result.v1"] = "xinao.family_replay_result.v1"
    case_id: str
    case_kind: Literal["POSITIVE", "NEGATIVE", "BOUNDARY"]
    family_id: str
    draw_id: str
    component_baseline_ids: tuple[str, ...]
    selection: tuple[int | str, ...]
    outcome: Literal["HIT", "MISS", "VOID"]
    unit_payout: str | None
    expected_outcome: Literal["HIT", "MISS", "VOID"] | None
    assertion_status: Literal["PASS", "FAIL", "NOT_ASSERTED"]
    draw_replay_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_record_hashes: tuple[str, ...]
    atomic_ticket_binding_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    draft = model.model_construct(**dict(payload), content_hash="0" * 64)
    body = draft.model_dump(mode="json", exclude={"content_hash"})
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


def _draw_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = {str(key): value for key, value in raw.items() if key != "_annual_endpoint"}
    required = {"expect", "openTime", "openCode", "zodiac", "wave", "type", "verify"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"authority JSON draw is missing fields: {missing}")
    return payload


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty source text")
    return value


def _compile_draw(raw: Mapping[str, Any]) -> DrawReplayInput:
    source_payload = _draw_payload(raw)
    draw_id = _text(source_payload, "expect")
    open_time = _text(source_payload, "openTime")
    parsed_time = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
    open_code = _text(source_payload, "openCode")
    try:
        numbers = tuple(int(value) for value in open_code.split(","))
    except ValueError as exc:
        raise ValueError("openCode contains a non-integer value") from exc
    zodiac_raw = _text(source_payload, "zodiac")
    zodiac_values = tuple(zodiac_raw.split(","))
    wave_raw = _text(source_payload, "wave")
    wave_values = tuple(wave_raw.split(","))
    source_type = _text(source_payload, "type")
    source_verify = source_payload.get("verify")
    if not isinstance(source_verify, bool):
        raise ValueError("verify must preserve the source boolean")
    source_payload_hash = canonical_sha256(source_payload)
    fingerprint_payload = {
        "draw_id": draw_id,
        "open_time": open_time,
        "source_open_code_raw": open_code,
        "source_zodiac_raw": zodiac_raw,
        "source_wave_raw": wave_raw,
        "source_type": source_type,
        "source_verify": source_verify,
    }
    return _with_hash(
        DrawReplayInput,
        {
            "draw_id": draw_id,
            "open_time": open_time,
            "draw_date": parsed_time.date().isoformat(),
            "source_open_code_raw": open_code,
            "numbers": numbers,
            "source_zodiac_raw": zodiac_raw,
            "source_zodiac_values": zodiac_values,
            "source_wave_raw": wave_raw,
            "source_wave_values": wave_values,
            "source_type": source_type,
            "source_verify": source_verify,
            "source_payload_hash": source_payload_hash,
            "draw_fingerprint": canonical_sha256(fingerprint_payload),
        },
    )


def _validate_draw_expectation(
    draws: Sequence[DrawReplayInput], expectation: DatasetExpectation
) -> None:
    if len(draws) != expectation.draw_count:
        raise ValueError(
            f"formal draw count must be {expectation.draw_count}, observed {len(draws)}"
        )
    if not draws:
        raise ValueError("draw dataset is empty")
    if draws[0].draw_id != expectation.first_draw_id:
        raise ValueError("first draw identity does not match the fixed dataset")
    if draws[-1].draw_id != expectation.last_draw_id:
        raise ValueError("last draw identity does not match the fixed dataset")
    if draws[0].draw_date != expectation.first_draw_date:
        raise ValueError("first Gregorian draw date does not match the fixed dataset")
    if draws[-1].draw_date != expectation.last_draw_date:
        raise ValueError("last Gregorian draw date does not match the fixed dataset")
    ids = [draw.draw_id for draw in draws]
    dates = [draw.draw_date for draw in draws]
    if len(ids) != len(set(ids)):
        raise ValueError("deduplicated draw ids are not unique")
    if len(dates) != len(set(dates)):
        raise ValueError("deduplicated Gregorian draw dates are not unique")
    if expectation.require_consecutive_dates:
        first = date.fromisoformat(expectation.first_draw_date)
        expected_dates = tuple(
            (first + timedelta(days=index)).isoformat() for index in range(expectation.draw_count)
        )
        if tuple(dates) != expected_dates:
            raise ValueError("Gregorian draw dates are not a consecutive fixed range")


def load_authority_draws(
    path: Path = DEFAULT_AUTHORITY_DATASET_PATH,
    *,
    expectation: DatasetExpectation = FORMAL_913_EXPECTATION,
) -> LoadedDrawDataset:
    """Parse only the raw JSONL section and deduplicate its formal draw identity."""

    in_jsonl = False
    raw_line_count = 0
    annual_endpoints: set[int] = set()
    by_identity: dict[tuple[str, str, tuple[int, ...]], DrawReplayInput] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_number, source_line in enumerate(stream, start=1):
            line = source_line.strip()
            if not in_jsonl:
                if line.startswith(JSONL_SECTION_PREFIX):
                    in_jsonl = True
                continue
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid authority JSONL at line {line_number}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"authority JSONL line {line_number} is not an object")
            raw_line_count += 1
            annual = raw.get("_annual_endpoint")
            if isinstance(annual, int) and not isinstance(annual, bool):
                annual_endpoints.add(annual)
            draw = _compile_draw(raw)
            identity = (draw.draw_id, draw.draw_date, draw.numbers)
            previous = by_identity.get(identity)
            if previous is not None and previous.source_payload_hash != draw.source_payload_hash:
                raise ValueError(
                    "duplicate period/date/seven-number identity has conflicting source fields"
                )
            by_identity.setdefault(identity, draw)
    if not in_jsonl:
        raise ValueError("authority text does not contain the raw JSONL section")

    draws = tuple(sorted(by_identity.values(), key=lambda item: (item.draw_date, item.draw_id)))
    _validate_draw_expectation(draws, expectation)
    dataset_semantic_hash = canonical_sha256(
        {
            "schema_version": "xinao.authority_draw_dataset.semantic.v1",
            "draws": [draw.model_dump(mode="json") for draw in draws],
        }
    )
    return LoadedDrawDataset(
        draws=draws,
        raw_json_line_count=raw_line_count,
        duplicate_json_line_count=raw_line_count - len(draws),
        source_annual_endpoints=tuple(sorted(annual_endpoints)),
        dataset_semantic_hash=dataset_semantic_hash,
    )


def _compile_selection_oracle(registry: FoundationSemanticsRegistry) -> _SelectionOracle:
    catalog = load_play_catalog()
    independent = compile_independent_selection_manifest(catalog)
    if (
        independent.active_catalog_projection_hash
        != registry.rule_semantic_map.active_catalog_projection_hash
    ):
        raise ValueError("independent manifest and registry use different ACTIVE catalogs")
    comparison = assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    atomic_bindings = compile_atomic_ticket_bindings(catalog, independent)
    manifest = registry.expected_selection_domain
    semantic_by_id = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    registry_spec_by_id = {spec.spec_id: spec for spec in manifest.specifications}
    atomic_by_baseline: dict[str, AtomicTicketBindingDescriptor] = {}
    for atomic in atomic_bindings.bindings:
        for baseline_id in atomic.component_baseline_ids:
            if baseline_id in atomic_by_baseline:
                raise ValueError(f"atomic ticket binding overlaps {baseline_id}")
            atomic_by_baseline[baseline_id] = atomic
            semantic = semantic_by_id.get(baseline_id)
            if semantic is None:
                raise ValueError(f"atomic ticket binding contains unknown {baseline_id}")
            if semantic.settlement_function_ref != atomic.settlement_function_ref:
                raise ValueError(f"atomic ticket settlement function drifted for {baseline_id}")

    binding: dict[str, tuple[Any, Any, AtomicTicketBindingDescriptor | None]] = {}
    binding_rows = []
    for independent_spec in independent.specifications:
        registry_spec = registry_spec_by_id[independent_spec.spec_id]
        for baseline_id in independent_spec.component_baseline_ids:
            if baseline_id in binding:
                raise ValueError(f"selection domain overlaps baseline {baseline_id}")
            semantic = semantic_by_id.get(baseline_id)
            if semantic is None:
                raise ValueError(f"selection domain contains unknown baseline {baseline_id}")
            if semantic.selection_domain_spec_id != independent_spec.spec_id:
                raise ValueError(f"semantic/domain binding disagrees for {baseline_id}")
            atomic = atomic_by_baseline.get(baseline_id)
            binding[baseline_id] = (independent_spec, registry_spec, atomic)
            binding_rows.append(
                {
                    "baseline_id": baseline_id,
                    "semantic_record_hash": semantic.content_hash,
                    "independent_selection_domain_spec_id": independent_spec.spec_id,
                    "independent_selection_domain_hash": independent_spec.content_hash,
                    "registry_selection_domain_hash": registry_spec.content_hash,
                    "atomic_ticket_binding_id": (atomic.binding_id if atomic is not None else None),
                    "atomic_ticket_binding_hash": (
                        atomic.content_hash if atomic is not None else None
                    ),
                }
            )
    if set(binding) != set(semantic_by_id) or len(binding) != 416:
        raise ValueError("selection domain does not independently bind all 416 ACTIVE baselines")
    binding_rows.sort(key=lambda item: item["baseline_id"])
    active_ids = set(semantic_by_id)
    active_selection_domain_structural_hash = ordered_json_stream_sha256(
            {
                "spec_id": spec.spec_id,
                "family_id": spec.family_id,
                "play_id": spec.play_id,
                "component_baseline_ids": spec.component_baseline_ids,
                "domain_kind": spec.domain_kind,
                "arity_min": spec.arity_min,
                "arity_max": spec.arity_max,
                "exact_atomic_selection_count": spec.exact_atomic_selection_count,
                "canonical_encoding": spec.canonical_encoding,
                "participating_baseline_ids_rule": spec.participating_baseline_ids_rule,
            }
            for spec in independent.specifications
    )
    active_atomic_ticket_binding_structural_hash = ordered_json_stream_sha256(
        binding.content_hash for binding in atomic_bindings.bindings
    )
    active_binding_rows = [row for row in binding_rows if str(row["baseline_id"]) in active_ids]
    proof = _with_hash(
        LazyDomainProof,
        {
            "active_selection_domain_structural_hash": (active_selection_domain_structural_hash),
            "registry_manifest_exact_match": comparison.exact_match,
            "atomic_ticket_binding_ref": atomic_bindings.binding_ref,
            "active_atomic_ticket_binding_structural_hash": (
                active_atomic_ticket_binding_structural_hash
            ),
            "atomic_ticket_binding_count": atomic_bindings.binding_count,
            "composite_exact_atomic_ticket_count": (atomic_bindings.exact_atomic_ticket_count),
            "descriptor_count": len(independent.specifications),
            "component_baseline_count": 416,
            "component_binding_count": len(binding),
            "exact_conceptual_atomic_selection_count": independent.exact_atomic_selection_count,
            "expanded_atomic_ticket_keys_materialized": False,
            "materialized_atomic_ticket_key_count": 0,
            "active_baseline_to_descriptor_ordered_digest": ordered_json_stream_sha256(
                active_binding_rows
            ),
            "component_binding_complete": True,
        },
    )
    return _SelectionOracle(
        independent_manifest=independent,
        manifest_comparison=comparison,
        atomic_ticket_bindings=atomic_bindings,
        active_selection_domain_structural_hash=active_selection_domain_structural_hash,
        active_atomic_ticket_binding_structural_hash=(active_atomic_ticket_binding_structural_hash),
        domain_by_baseline=binding,
        lazy_domain_proof=proof,
    )


def _iter_functional_event_payloads(
    registry: FoundationSemanticsRegistry,
    draws: Sequence[DrawReplayInput],
    *,
    oracle: _SelectionOracle | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield only active physical cells without allocating temporary models."""

    selection_oracle = oracle or _compile_selection_oracle(registry)
    records = tuple(sorted(registry.rule_semantic_map.records, key=lambda item: item.baseline_id))
    if len(records) != EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT:
        raise ValueError("physical event surface requires exactly 416 active records")
    for draw in sorted(draws, key=lambda item: (item.draw_date, item.draw_id)):
        for semantic in records:
            independent, registry_domain, atomic = selection_oracle.domain_by_baseline[
                semantic.baseline_id
            ]
            yield {
                "schema_version": "xinao.functional_event_cell.v1",
                "surface_kind": "FUNCTIONAL_EVENT_SURFACE",
                "physical_role": "ACTIVE_SETTLEMENT",
                "draw_id": draw.draw_id,
                "baseline_id": semantic.baseline_id,
                "semantic_record_hash": semantic.content_hash,
                "selection_domain_spec_id": independent.spec_id,
                "selection_domain_hash": independent.content_hash,
                "registry_selection_domain_hash": registry_domain.content_hash,
                "atomic_ticket_binding_id": (atomic.binding_id if atomic is not None else None),
                "atomic_ticket_binding_hash": (atomic.content_hash if atomic is not None else None),
                "settlement_function_ref": semantic.settlement_function_ref,
                "draw_fingerprint": draw.draw_fingerprint,
                "draw_replay_input_hash": draw.content_hash,
                "draw_date": draw.draw_date,
                "zodiac_basis_ref": "SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1",
            }


def iter_functional_event_cells(
    registry: FoundationSemanticsRegistry,
    draws: Sequence[DrawReplayInput],
) -> Iterator[FunctionalEventCell]:
    """Yield typed cells on demand; the compiler itself streams raw canonical payloads."""

    oracle = _compile_selection_oracle(registry)
    for payload in _iter_functional_event_payloads(registry, draws, oracle=oracle):
        yield FunctionalEventCell.model_validate(payload)


def summarize_replay_results(
    results: Iterable[FamilyReplayResult],
) -> RepresentativeReplayEvidenceSummary:
    materialized = tuple(sorted(results, key=lambda item: item.case_id))
    if len({result.case_id for result in materialized}) != len(materialized):
        raise ValueError("representative replay case ids must be unique")
    by_family: dict[str, list[FamilyReplayResult]] = defaultdict(list)
    for result in materialized:
        if result.family_id not in EXPECTED_ACTIVE_FAMILY_COUNTS:
            raise ValueError(f"unknown replay family {result.family_id}")
        by_family[result.family_id].append(result)

    coverage = []
    required = ("POSITIVE", "NEGATIVE", "BOUNDARY")
    for family_id in EXPECTED_ACTIVE_FAMILY_COUNTS:
        family_results = by_family[family_id]
        executed = tuple(
            kind for kind in required if any(result.case_kind == kind for result in family_results)
        )
        passed = tuple(
            kind
            for kind in required
            if any(
                result.case_kind == kind and result.assertion_status == "PASS"
                for result in family_results
            )
        )
        failed_ids = tuple(
            result.case_id for result in family_results if result.assertion_status == "FAIL"
        )
        status: Literal["VERIFIED", "PARTIAL", "FAILED"]
        if failed_ids:
            status = "FAILED"
        elif passed == required:
            status = "VERIFIED"
        else:
            status = "PARTIAL"
        coverage.append(
            FamilyReplayCoverage(
                family_id=family_id,
                executed_case_kinds=executed,
                passed_case_kinds=passed,
                failed_case_ids=failed_ids,
                status=status,
            )
        )
    failures = sum(result.assertion_status == "FAIL" for result in materialized)
    passes = sum(result.assertion_status == "PASS" for result in materialized)
    if failures:
        overall: Literal["VERIFIED", "PARTIAL", "FAILED"] = "FAILED"
    elif all(item.status == "VERIFIED" for item in coverage):
        overall = "VERIFIED"
    else:
        overall = "PARTIAL"
    return _with_hash(
        RepresentativeReplayEvidenceSummary,
        {
            "family_count": 13,
            "executed_case_count": len(materialized),
            "asserted_pass_count": passes,
            "asserted_fail_count": failures,
            "result_status": overall,
            "family_coverage": tuple(coverage),
            "result_digest": canonical_sha256(
                [result.model_dump(mode="json") for result in materialized]
            ),
            "limitation": (
                "VERIFIED requires asserted positive, negative, and boundary replay cases "
                "for every one of the 13 families; functional-cell coverage alone is not "
                "that evidence."
            ),
        },
    )


def _stream_surface(
    registry: FoundationSemanticsRegistry,
    draws: Sequence[DrawReplayInput],
    oracle: _SelectionOracle,
) -> tuple[int, str, str, dict[str, int], dict[str, Any]]:
    """Compile the Cartesian stream in a sealed stdlib-only child.

    The parent validates Pydantic registry/oracle/draw objects and projects only
    the 416 record primitives plus the current draw primitives.  The child has a
    deliberately narrower contract than a general JCS encoder: fixed ASCII keys
    and safe ASCII-or-null values.  Dynamic values are pre-encoded before its hot
    loop, which then performs only byte joins, SHA-256, and Merkle accumulation.
    """

    records = tuple(sorted(registry.rule_semantic_map.records, key=lambda item: item.baseline_id))
    ordered_draws = tuple(sorted(draws, key=lambda item: (item.draw_date, item.draw_id)))
    baselines = []
    for semantic in records:
        independent, registry_domain, atomic = oracle.domain_by_baseline[semantic.baseline_id]
        baselines.append(
            {
                "family_id": semantic.family_id,
                "payload": {
                    "atomic_ticket_binding_hash": (
                        atomic.content_hash if atomic is not None else None
                    ),
                    "atomic_ticket_binding_id": atomic.binding_id if atomic is not None else None,
                    "baseline_id": semantic.baseline_id,
                    "registry_selection_domain_hash": registry_domain.content_hash,
                    "selection_domain_hash": independent.content_hash,
                    "selection_domain_spec_id": independent.spec_id,
                    "semantic_record_hash": semantic.content_hash,
                    "settlement_function_ref": semantic.settlement_function_ref,
                },
            }
        )
    draw_projection = [
        {
            "draw_date": draw.draw_date,
            "draw_fingerprint": draw.draw_fingerprint,
            "draw_id": draw.draw_id,
            "draw_replay_input_hash": draw.content_hash,
        }
        for draw in ordered_draws
    ]
    expected_baselines = len(baselines)
    expected_draws = len(draw_projection)
    expected_cells = expected_baselines * expected_draws
    projection = {
        "schema_version": PURE_ASCII_STREAM_PROJECTION_SCHEMA,
        "expected_baseline_count": expected_baselines,
        "expected_draw_count": expected_draws,
        "expected_cell_count": expected_cells,
        "baselines": baselines,
        "draws": draw_projection,
    }
    projection_bytes = json.dumps(
        projection,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    projection_sha256 = hashlib.sha256(projection_bytes).hexdigest()

    worker = PURE_ASCII_STREAM_WORKER.resolve()
    if worker.parent != Path(__file__).resolve().parent or not worker.is_file():
        raise ValueError(f"F1 pure stream worker is unavailable: {worker}")
    worker_before = worker.read_bytes()
    worker_sha256 = hashlib.sha256(worker_before).hexdigest()
    environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")
    }
    try:
        completed = subprocess.run(
            [
                str(Path(sys.executable).resolve()),
                "-X",
                "faulthandler",
                "-I",
                "-S",
                str(worker),
            ],
            input=projection_bytes,
            capture_output=True,
            check=False,
            env=environment,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("F1 pure stream worker timed out") from exc
    try:
        worker_after = worker.read_bytes()
    except OSError as exc:
        raise ValueError("F1 pure stream worker disappeared after execution") from exc
    if worker_after != worker_before:
        raise ValueError("F1 pure stream worker changed during execution")
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[-4000:]
        raise ValueError(f"F1 pure stream worker failed with exit {completed.returncode}: {detail}")
    try:
        result = json.loads(completed.stdout.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("F1 pure stream worker output is invalid") from exc
    if (
        not isinstance(result, dict)
        or json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        != completed.stdout
    ):
        raise ValueError("F1 pure stream worker output is not canonical JSON")
    expected_result_keys = {
        "schema_version",
        "projection_sha256",
        "projection_size_bytes",
        "worker_sha256",
        "worker_size_bytes",
        "baseline_count",
        "draw_count",
        "cell_count",
        "ordered_cell_stream_sha256",
        "ordered_merkle_root",
        "family_cell_counts",
        "key_proof",
        "isolated_mode",
        "no_site",
        "forbidden_module_count",
        "content_sha256",
    }
    if set(result) != expected_result_keys:
        raise ValueError("F1 pure stream worker result keys are not exact")
    result_core = dict(result)
    result_content_sha256 = result_core.pop("content_sha256", None)
    result_core_bytes = json.dumps(
        result_core,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    if result_content_sha256 != hashlib.sha256(result_core_bytes).hexdigest():
        raise ValueError("F1 pure stream worker result content hash drifted")
    expected_family_counts = dict(
        sorted(
            {
                family_id: count * expected_draws
                for family_id, count in Counter(
                    str(item["family_id"]) for item in baselines
                ).items()
            }.items()
        )
    )
    expected_first_key = [ordered_draws[0].draw_id, records[0].baseline_id]
    expected_last_key = [ordered_draws[-1].draw_id, records[-1].baseline_id]
    expected_key_proof = {
        "expected_cartesian_key_count": expected_cells,
        "actual_stream_key_count": expected_cells,
        "missing_cartesian_keys": 0,
        "unexpected_cartesian_keys": 0,
        "duplicate_cartesian_keys": 0,
        "strictly_ordered": True,
        "first_canonical_key": expected_first_key,
        "last_canonical_key": expected_last_key,
    }
    fixed_expected = {
        "schema_version": PURE_ASCII_STREAM_RESULT_SCHEMA,
        "projection_sha256": projection_sha256,
        "projection_size_bytes": len(projection_bytes),
        "worker_sha256": worker_sha256,
        "worker_size_bytes": len(worker_before),
        "baseline_count": expected_baselines,
        "draw_count": expected_draws,
        "cell_count": expected_cells,
        "family_cell_counts": expected_family_counts,
        "key_proof": expected_key_proof,
        "isolated_mode": True,
        "no_site": True,
        "forbidden_module_count": 0,
    }
    if any(result.get(key) != value for key, value in fixed_expected.items()):
        raise ValueError("F1 pure stream worker result bindings drifted")
    for field in ("ordered_cell_stream_sha256", "ordered_merkle_root"):
        digest = result.get(field)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(item not in "0123456789abcdef" for item in digest)
        ):
            raise ValueError(f"F1 pure stream worker {field} is invalid")
    key_proof = {
        "keys_equal": True,
        "expected_key_count": expected_cells,
        "actual_key_count": expected_cells,
        "missing_keys": 0,
        "unexpected_keys": 0,
        "duplicate_keys": 0,
        "strictly_ordered": True,
        "first_canonical_key": expected_first_key,
        "last_canonical_key": expected_last_key,
        "projection_sha256": projection_sha256,
        "worker_sha256": worker_sha256,
    }
    return (
        expected_cells,
        str(result["ordered_cell_stream_sha256"]),
        str(result["ordered_merkle_root"]),
        expected_family_counts,
        key_proof,
    )


def compile_functional_world(
    registry: FoundationSemanticsRegistry,
    dataset_path: Path = DEFAULT_AUTHORITY_DATASET_PATH,
    *,
    expectation: DatasetExpectation = FORMAL_913_EXPECTATION,
    replay_results: Iterable[FamilyReplayResult] = (),
) -> FunctionalWorldCompilation:
    """Compile content-addressed snapshots without writing cells or artifacts to disk."""

    loaded = load_authority_draws(dataset_path, expectation=expectation)
    oracle = _compile_selection_oracle(registry)
    lazy_proof = oracle.lazy_domain_proof
    (
        cell_count,
        stream_hash,
        merkle_root,
        family_cell_counts,
        functional_key_proof,
    ) = _stream_surface(registry, loaded.draws, oracle)
    # Replay summaries do not participate in event-cell bytes.  Build them only
    # after the sealed child has returned the complete Cartesian stream proof.
    replay_summary = summarize_replay_results(replay_results)
    expected_cells = len(loaded.draws) * EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT
    expected_family_cells = {
        family_id: count * len(loaded.draws)
        for family_id, count in EXPECTED_ACTIVE_FAMILY_COUNTS.items()
    }
    if family_cell_counts != expected_family_cells:
        raise ValueError("functional event surface family coverage is incomplete")
    coverage = FunctionalCoverage(
        draw_count=len(loaded.draws),
        active_settlement_component_count=416,
        expected_functional_cell_count=expected_cells,
        actual_functional_cell_count=cell_count,
        missing_functional_key_count=functional_key_proof["missing_keys"],
        unexpected_functional_key_count=functional_key_proof["unexpected_keys"],
        duplicate_functional_key_count=functional_key_proof["duplicate_keys"],
    )
    event_snapshot = _with_hash(
        EventMatrixSnapshot,
        {
            "dataset_semantic_hash": loaded.dataset_semantic_hash,
            "active_semantics_hash": registry.active_physical_semantics_hash,
            "active_selection_domain_structural_hash": (
                oracle.active_selection_domain_structural_hash
            ),
            "active_atomic_ticket_binding_structural_hash": (
                oracle.active_atomic_ticket_binding_structural_hash
            ),
            "first_draw_id": loaded.draws[0].draw_id,
            "last_draw_id": loaded.draws[-1].draw_id,
            "first_draw_date": loaded.draws[0].draw_date,
            "last_draw_date": loaded.draws[-1].draw_date,
            "family_cell_counts": family_cell_counts,
            "coverage": coverage,
            "ordered_cell_stream_sha256": stream_hash,
            "ordered_merkle_root": merkle_root,
            "cells_materialized": False,
            "lazy_domain_proof_hash": lazy_proof.content_hash,
            "representative_replay_status": replay_summary.result_status,
            "f1_status": "PARTIAL",
            "f1_limitation": (
                "The 416-row physical surface is verified; the 17 frozen route quotes "
                "create no cells or replay work. Expanded ticket keys are lazy by design "
                "and the 13-family "
                "positive/negative/boundary replay "
                f"summary is {replay_summary.result_status}."
            ),
        },
    )
    world = _with_hash(
        WorldSnapshot,
        {
            "event_matrix_snapshot_ref": event_snapshot.snapshot_ref,
            "event_matrix_snapshot_hash": event_snapshot.content_hash,
            "active_semantics_hash": registry.active_physical_semantics_hash,
            "dataset_semantic_hash": loaded.dataset_semantic_hash,
            "active_selection_domain_structural_hash": (
                oracle.active_selection_domain_structural_hash
            ),
            "active_atomic_ticket_binding_structural_hash": (
                oracle.active_atomic_ticket_binding_structural_hash
            ),
            "draw_inputs": loaded.draws,
            "lazy_domain_proof": lazy_proof,
            "representative_replay_evidence": replay_summary,
            "knowledge_cutoff_at": loaded.draws[-1].open_time,
            "expanded_atomic_ticket_keys_materialized": False,
            "f1_status": "PARTIAL",
        },
    )
    return FunctionalWorldCompilation(
        loaded_dataset=loaded,
        event_matrix_snapshot=event_snapshot,
        world_snapshot=world,
        functional_key_proof=functional_key_proof,
    )


def replay_functional_cell(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
    *,
    draw_id: str,
    baseline_id: str,
) -> FunctionalEventCell:
    """Reconstruct one cell from the hashes and inputs retained by the world."""

    if world.active_semantics_hash != registry.active_physical_semantics_hash:
        raise ValueError("world and active semantics identity disagree")
    oracle = _compile_selection_oracle(registry)
    if (
        world.active_selection_domain_structural_hash
        != oracle.active_selection_domain_structural_hash
        or world.active_atomic_ticket_binding_structural_hash
        != oracle.active_atomic_ticket_binding_structural_hash
    ):
        raise ValueError("world and independent selection oracle identity disagree")
    draw = next((item for item in world.draw_inputs if item.draw_id == draw_id), None)
    if baseline_id in FROZEN_ROUTE_QUOTE_BASELINE_IDS:
        raise ValueError(
            f"baseline {baseline_id} is a catalog-only frozen agent-route quote; "
            "it has no F1 semantic or physical event cell"
        )
    semantic = next(
        (item for item in registry.rule_semantic_map.records if item.baseline_id == baseline_id),
        None,
    )
    if draw is None or semantic is None:
        raise KeyError("unknown draw or baseline identity")
    domain = oracle.domain_by_baseline.get(baseline_id)
    if domain is None:
        raise ValueError("world cannot reproduce the semantic/domain binding")
    independent, registry_domain, atomic = domain
    if independent.spec_id != semantic.selection_domain_spec_id:
        raise ValueError("world cannot reproduce the semantic/domain binding")
    return FunctionalEventCell(
        draw_id=draw.draw_id,
        physical_role="ACTIVE_SETTLEMENT",
        baseline_id=semantic.baseline_id,
        semantic_record_hash=semantic.content_hash,
        selection_domain_spec_id=independent.spec_id,
        selection_domain_hash=independent.content_hash,
        registry_selection_domain_hash=registry_domain.content_hash,
        atomic_ticket_binding_id=atomic.binding_id if atomic is not None else None,
        atomic_ticket_binding_hash=atomic.content_hash if atomic is not None else None,
        settlement_function_ref=semantic.settlement_function_ref,
        draw_fingerprint=draw.draw_fingerprint,
        draw_replay_input_hash=draw.content_hash,
        draw_date=draw.draw_date,
    )


def resolve_atomic_ticket_binding(
    registry: FoundationSemanticsRegistry,
    baseline_id: str,
) -> AtomicTicketBindingDescriptor:
    """Resolve the independent lazy-ticket binding for one composite component."""

    oracle = _compile_selection_oracle(registry)
    domain = oracle.domain_by_baseline.get(baseline_id)
    if domain is None:
        raise KeyError(f"unknown baseline identity {baseline_id}")
    atomic = domain[2]
    if atomic is None:
        raise ValueError(f"baseline {baseline_id} has no composite atomic-ticket binding")
    return atomic


def iter_atomic_ticket_replay_selections(
    registry: FoundationSemanticsRegistry,
    baseline_id: str,
) -> Iterator[AtomicTicketSelection]:
    """Lazily expose canonical ticket identities bound to the world compiler oracle."""

    binding = resolve_atomic_ticket_binding(registry, baseline_id)
    yield from iter_atomic_ticket_selections(binding)


def replay_family_case(
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
    case: FamilyReplayCase,
) -> FamilyReplayResult:
    """Execute one asserted representative case through its native strict compiler."""

    if world.active_semantics_hash != registry.active_physical_semantics_hash:
        raise ValueError("world and active semantics identity disagree")
    oracle = _compile_selection_oracle(registry)
    if (
        world.active_selection_domain_structural_hash
        != oracle.active_selection_domain_structural_hash
        or world.active_atomic_ticket_binding_structural_hash
        != oracle.active_atomic_ticket_binding_structural_hash
    ):
        raise ValueError("world and independent selection oracle identity disagree")
    draw = next((item for item in world.draw_inputs if item.draw_id == case.draw_id), None)
    if draw is None:
        raise KeyError(f"unknown draw id {case.draw_id}")
    frozen = sorted(set(case.component_baseline_ids) & FROZEN_ROUTE_QUOTE_BASELINE_IDS)
    if frozen:
        raise ValueError(
            "representative physical replay cannot use catalog-only frozen route quotes: "
            + ",".join(frozen)
        )

    source = registry.source_artifacts
    basic = {record.baseline_id: record for record in source.basic_records}
    sets = {
        record.baseline_id: record for record in source.set_compilation.rule_semantic_map.records
    }
    combinations = {record.baseline_id: record for record in source.combination_records}
    linked = {
        record.baseline_id: record for record in source.linked_compilation.rule_semantic_map.records
    }
    all_source = {**basic, **sets, **combinations, **linked}
    try:
        records = tuple(all_source[baseline_id] for baseline_id in case.component_baseline_ids)
    except KeyError as exc:
        raise KeyError(f"unknown replay baseline {exc.args[0]}") from exc
    family_ids = {record.family_id for record in records}
    if len(family_ids) != 1:
        raise ValueError("representative case cannot mix semantic families")
    family_id = next(iter(family_ids))

    atomic: AtomicTicketBindingDescriptor | None = None
    atomic_candidates = {
        oracle.domain_by_baseline[baseline_id][2] for baseline_id in case.component_baseline_ids
    }
    if None not in atomic_candidates:
        atomic_bindings = {
            candidate.content_hash: candidate
            for candidate in atomic_candidates
            if candidate is not None
        }
        if len(atomic_bindings) != 1:
            raise ValueError("representative case mixes independent atomic-ticket bindings")
        atomic = next(iter(atomic_bindings.values()))
        selected_ids = set(case.component_baseline_ids)
        if not selected_ids <= set(atomic.component_baseline_ids):
            raise ValueError("representative case escapes its atomic-ticket component universe")
        if atomic.family_id != family_id:
            raise ValueError("representative case family and atomic-ticket binding disagree")
    elif len(atomic_candidates) != 1:
        raise ValueError("representative case mixes atomic and non-atomic components")

    outcome: Literal["HIT", "MISS", "VOID"]
    payout: str | None
    if family_id in {"special-number", "regular-number", "regular-position-special"}:
        if len(records) != 1 or len(case.selection) != 1:
            raise ValueError("basic replay requires one component and one selection")
        result = settle_basic_record(
            record=records[0], draw=draw.numbers, selection=case.selection[0]
        )
        outcome, payout = result.outcome, result.unit_payout
    elif family_id in {"other-explicit", "one-zodiac-tail", "six-zodiac"}:
        if len(records) != 1:
            raise ValueError("set-family replay requires one component")
        selection = tuple(str(value) for value in case.selection) or None
        outcome = settle_rule(
            records[0],
            draw=draw.numbers,
            draw_date=draw.draw_date,
            selection=selection,
        )
        payout = (
            records[0].raw_site_fields["baseline_odds_components"][0]
            if outcome == "HIT"
            else "1"
            if outcome == "VOID"
            else "0"
        )
    elif family_id in {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }:
        if len(records) != 1:
            raise ValueError("number-combination replay requires one component")
        if atomic is None or not atomic.arity_min <= len(case.selection) <= atomic.arity_max:
            raise ValueError("number-combination selection violates its atomic-ticket arity")
        result = settle_combination(entry=records[0], draw=draw.numbers, selection=case.selection)
        outcome, payout = result.outcome, result.unit_payout
    elif family_id in {"linked-zodiac", "linked-tail"}:
        if case.selection:
            raise ValueError("linked component baselines are the selection; payload must be empty")
        if atomic is None or not atomic.arity_min <= len(records) <= atomic.arity_max:
            raise ValueError("linked selection violates its atomic-ticket arity")
        result = settle_linked_ticket(records, draw=draw.numbers, draw_date=draw.draw_date)
        outcome, payout = result.outcome, result.unit_payout
    elif family_id == "parlay":
        if case.selection:
            raise ValueError("parlay component baselines are the selection; payload must be empty")
        if atomic is None or not atomic.arity_min <= len(records) <= atomic.arity_max:
            raise ValueError("parlay selection violates its atomic-ticket arity")
        result = settle_parlay_ticket(records, draw=draw.numbers)
        outcome, payout = result.outcome, result.unit_payout
    else:  # pragma: no cover - registry rejects unknown families before this point
        raise ValueError(f"unsupported replay family {family_id}")

    assertion_status: Literal["PASS", "FAIL", "NOT_ASSERTED"]
    if case.expected_outcome is None:
        assertion_status = "NOT_ASSERTED"
    elif case.expected_outcome == outcome:
        assertion_status = "PASS"
    else:
        assertion_status = "FAIL"
    canonical_records = {
        record.baseline_id: record for record in registry.rule_semantic_map.records
    }
    return _with_hash(
        FamilyReplayResult,
        {
            "case_id": case.case_id,
            "case_kind": case.case_kind,
            "family_id": family_id,
            "draw_id": case.draw_id,
            "component_baseline_ids": case.component_baseline_ids,
            "selection": case.selection,
            "outcome": outcome,
            "unit_payout": payout,
            "expected_outcome": case.expected_outcome,
            "assertion_status": assertion_status,
            "draw_replay_input_hash": draw.content_hash,
            "semantic_record_hashes": tuple(
                canonical_records[baseline_id].content_hash
                for baseline_id in case.component_baseline_ids
            ),
            "atomic_ticket_binding_hash": (atomic.content_hash if atomic is not None else None),
        },
    )


__all__ = [
    "DEFAULT_AUTHORITY_DATASET_PATH",
    "FORMAL_913_EXPECTATION",
    "DatasetExpectation",
    "DrawReplayInput",
    "EventMatrixSnapshot",
    "FamilyReplayCase",
    "FamilyReplayResult",
    "FunctionalEventCell",
    "FunctionalWorldCompilation",
    "LazyDomainProof",
    "RepresentativeReplayEvidenceSummary",
    "WorldSnapshot",
    "compile_functional_world",
    "iter_atomic_ticket_replay_selections",
    "iter_functional_event_cells",
    "load_authority_draws",
    "replay_family_case",
    "replay_functional_cell",
    "resolve_atomic_ticket_binding",
    "summarize_replay_results",
]
