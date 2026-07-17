"""Independent ACTIVE selection-domain and atomic-ticket identity compiler.

This module is intentionally upstream of every settlement semantic compiler.  It
validates the 433-row source catalog, classifies 17 B rows as catalog-only frozen
agent-route quotes, and compiles expected domains only for the 416 ACTIVE rows.  It
must not import ``semantics_*`` modules or the semantic registry: otherwise a
selection bug could rewrite both the implementation and its expected-domain oracle.

Large domains are represented by exact combinatorial counts and canonical lazy
generator rules.  No 21-billion-element collection is materialised.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from hashlib import sha256
from itertools import combinations, product
from math import comb
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.foundation.f4_snapshot_runtime import load_object as load_snapshot_object

DEFAULT_PLAY_CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)

GRAMMAR_VERSION_REF = "xinao.independent-selection-domain-grammar.v1"
COMBINATION_FIXTURE_REF = "xinao.independent-combination-arity-fixture.v1"
LINKED_FIXTURE_REF = "xinao.independent-linked-arity-fixture.v1"
SIX_ZODIAC_FIXTURE_REF = "xinao.independent-six-zodiac-active-fixture.v1"
PARLAY_FIXTURE_REF = "xinao.independent-parlay-ticket-fixture.v1"

EXPECTED_FAMILY_COUNTS: dict[str, int] = {
    "special-number": 24,
    "regular-number": 10,
    "regular-position-special": 60,
    "other-explicit": 95,
    "one-zodiac-tail": 22,
    "linked-number": 5,
    "six-zodiac": 2,
    "parlay": 42,
    "multi-select-no-hit": 6,
    "linked-zodiac": 96,
    "linked-tail": 60,
    "multi-select-one-hit": 6,
    "special-regular-hit": 5,
}
EXPECTED_ACTIVE_FAMILY_COUNTS: dict[str, int] = {
    **EXPECTED_FAMILY_COUNTS,
    "special-number": 12,
    "regular-number": 5,
}
EXPECTED_BASELINE_IDS = tuple(f"BO{number:04d}" for number in range(1, 434))

# These 17 identities remain untouched in the source catalog.  Their only F1
# meaning is the catalog-level classification below: they do not point to A,
# define a hit semantic, create a selection, or enter any Foundation gate.
FROZEN_ROUTE_QUOTE_BASELINE_IDS = frozenset(
    f"BO{number:04d}" for number in (*range(13, 25), *range(30, 35))
)
ACTIVE_SETTLEMENT_BASELINE_IDS = frozenset(EXPECTED_BASELINE_IDS) - FROZEN_ROUTE_QUOTE_BASELINE_IDS
EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT = 416
EXPECTED_FROZEN_ROUTE_QUOTE_COMPONENT_COUNT = 17
EXPECTED_ACTIVE_ATOMIC_SELECTION_COUNT = 21_652_542_248

_BASIC_FAMILIES = frozenset({"special-number", "regular-number", "regular-position-special"})
_SET_FAMILIES = frozenset({"other-explicit", "one-zodiac-tail", "six-zodiac"})
_COMBINATION_FAMILIES = frozenset(
    {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }
)
_LINKED_FAMILIES = frozenset({"linked-zodiac", "linked-tail"})
_COMPOSITE_FAMILIES = _COMBINATION_FAMILIES | _LINKED_FAMILIES | {"parlay"}

_RANGE_PATTERN = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PARLAY_OPTION_PATTERN = re.compile(r"^正([1-6])-(单|双|大|小|红波|绿波|蓝波)$")

ZODIAC_ORDER = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
TAIL_ORDER = tuple(f"{tail}尾" for tail in range(10))
PARLAY_ATTRIBUTE_ORDER = ("ODD", "EVEN", "BIG", "SMALL", "RED", "GREEN", "BLUE")
_PARLAY_ATTRIBUTE_BY_LABEL = {
    "单": "ODD",
    "双": "EVEN",
    "大": "BIG",
    "小": "SMALL",
    "红波": "RED",
    "绿波": "GREEN",
    "蓝波": "BLUE",
}

# These fixtures are deliberately local, explicit, and versioned.  They are not read
# back from settlement records.  The catalog supplies identity; the fixture supplies
# the atomic selection arity where a row's ``01-49`` range alone is insufficient.
_COMBINATION_ARITY_BY_BASELINE: dict[str, int] = {
    "BO0212": 2,
    "BO0213": 2,
    "BO0214": 2,
    "BO0215": 3,
    "BO0216": 3,
    **{f"BO{number:04d}": number - 256 for number in range(261, 267)},
    **{f"BO{number:04d}": number - 418 for number in range(423, 429)},
    **{f"BO{number:04d}": number - 428 for number in range(429, 434)},
}

_COMBINATION_SEMANTIC_BY_BASELINE = {
    "BO0212": "ALL_SELECTED_REGULAR",
    "BO0213": "TWO_REGULAR_OR_REGULAR_SPECIAL",
    "BO0214": "REGULAR_SPECIAL",
    "BO0215": "ALL_SELECTED_REGULAR",
    "BO0216": "THREE_OR_TWO_REGULAR",
}

_LINKED_ARITY_BY_PID_TID: dict[tuple[int, int], int] = {
    (10, 47): 2,
    (10, 48): 3,
    (10, 49): 4,
    (10, 50): 5,
    (10, 51): 2,
    (10, 52): 3,
    (10, 53): 4,
    (10, 54): 5,
    (11, 55): 2,
    (11, 56): 3,
    (11, 57): 4,
    (11, 58): 2,
    (11, 59): 3,
    (11, 60): 4,
}

EvidenceStatus = Literal["EXPLICIT_PAGE", "RESEARCH_CONVENTION"]
ExpansionPolicy = Literal["LAZY_CANONICAL_GENERATOR"]
QuoteAggregation = Literal[
    "BOUND_BASELINE_TIER_COMPONENT",
    "MIN_SELECTED_COMPONENT",
    "PRODUCT_NON_VOID_LEGS",
]


def canonical_sha256(value: Any) -> str:
    """Hash JSON-compatible content with stable key and Unicode handling."""

    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_hash(self) -> _ContentHashedModel:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(payload) != self.content_hash:
            raise ValueError("content_hash does not bind canonical model content")
        return self


class IndependentSelectionDomainSpec(_ContentHashedModel):
    schema_version: Literal["xinao.independent_selection_domain_spec.v1"] = (
        "xinao.independent_selection_domain_spec.v1"
    )
    spec_id: str
    family_id: str
    play_id: str
    play_name: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    domain_kind: Literal[
        "FINITE_CATALOG_OPTION_SELECTION",
        "DISTINCT_ZODIAC_LABEL_COMBINATION",
        "UNORDERED_NUMBER_COMBINATION",
        "DISTINCT_LABEL_COMBINATION",
        "UNIQUE_POSITION_LEG_PRODUCT",
    ]
    arity_min: int = Field(ge=1, le=10)
    arity_max: int = Field(ge=1, le=10)
    exact_atomic_selection_count: int = Field(gt=0)
    expansion_policy: ExpansionPolicy = "LAZY_CANONICAL_GENERATOR"
    materialized_atomic_selection_count: Literal[0] = 0
    canonical_encoding: str
    canonical_selection_id_rule: str
    participating_baseline_ids_rule: str
    grammar_ref: Literal["xinao.independent-selection-domain-grammar.v1"] = GRAMMAR_VERSION_REF
    fixture_ref: str
    semantic_evidence_statuses: tuple[EvidenceStatus, ...] = Field(min_length=1)
    source_scope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_shape(self) -> IndependentSelectionDomainSpec:
        if self.arity_min > self.arity_max:
            raise ValueError("selection arity_min cannot exceed arity_max")
        if tuple(sorted(self.component_baseline_ids)) != self.component_baseline_ids:
            raise ValueError("component baseline ids must be sorted")
        if len(self.component_baseline_ids) != len(set(self.component_baseline_ids)):
            raise ValueError("component baseline ids must be unique")
        return self


class IndependentExpectedSelectionDomainManifestVersion(_ContentHashedModel):
    schema_version: Literal["xinao.independent_expected_selection_domain_manifest.v1"] = (
        "xinao.independent_expected_selection_domain_manifest.v1"
    )
    manifest_ref: Literal["xinao-independent-416-active-selection-domain.v1"] = (
        "xinao-independent-416-active-selection-domain.v1"
    )
    grammar_ref: Literal["xinao.independent-selection-domain-grammar.v1"] = GRAMMAR_VERSION_REF
    source_catalog_ref: str
    active_catalog_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_catalog_row_count: Literal[416] = 416
    family_counts: dict[str, int]
    selection_domain_spec_count: Literal[233] = 233
    exact_atomic_selection_count: Literal[21652542248] = 21652542248
    materialized_atomic_selection_count: Literal[0] = 0
    specifications: tuple[IndependentSelectionDomainSpec, ...]
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_partition(self) -> IndependentExpectedSelectionDomainManifestVersion:
        derived_family_counts: Counter[str] = Counter()
        for specification in self.specifications:
            derived_family_counts[specification.family_id] += len(
                specification.component_baseline_ids
            )
        if dict(derived_family_counts) != self.family_counts:
            raise ValueError("manifest family counts do not match its specifications")
        if self.family_counts != EXPECTED_ACTIVE_FAMILY_COUNTS:
            raise ValueError("manifest family counts are not the 416-row ACTIVE partition")
        if len(self.specifications) != self.selection_domain_spec_count:
            raise ValueError("manifest must contain exactly 233 ACTIVE domain specs")
        spec_ids = [spec.spec_id for spec in self.specifications]
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("manifest contains duplicate spec ids")
        component_ids = [
            baseline_id
            for spec in self.specifications
            for baseline_id in spec.component_baseline_ids
        ]
        if set(component_ids) != ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("manifest must partition the 416 ACTIVE baselines exactly once")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("manifest ACTIVE component partition overlaps")
        if sum(spec.exact_atomic_selection_count for spec in self.specifications) != (
            self.exact_atomic_selection_count
        ):
            raise ValueError("manifest exact atomic selection total drifted")
        if any(
            set(spec.component_baseline_ids) & FROZEN_ROUTE_QUOTE_BASELINE_IDS
            for spec in self.specifications
        ):
            raise ValueError("catalog-only frozen route quotes entered the ACTIVE manifest")
        return self


class ComponentKeyBinding(_FrozenModel):
    component_key: str
    baseline_id: str = Field(pattern=r"^BO\d{4}$")


class AtomicTicketBindingDescriptor(_ContentHashedModel):
    schema_version: Literal["xinao.atomic_ticket_binding_descriptor.v1"] = (
        "xinao.atomic_ticket_binding_descriptor.v1"
    )
    binding_id: str
    domain_spec_id: str
    family_id: str
    play_id: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    component_key_bindings: tuple[ComponentKeyBinding, ...] = Field(min_length=1)
    arity_min: int = Field(ge=1, le=10)
    arity_max: int = Field(ge=1, le=10)
    exact_atomic_ticket_count: int = Field(gt=0)
    selection_id_grammar_ref: str
    lazy_generator_ref: str
    canonical_ticket_identity_rule: Literal["play_id::selection_id"] = "play_id::selection_id"
    participating_baseline_ids_rule: Literal[
        "FIXED_SINGLE_BASELINE",
        "SELECTED_LABEL_COMPONENT_BASELINES",
        "SELECTED_POSITION_ATTRIBUTE_COMPONENT_BASELINES",
    ]
    quote_aggregation_ref: QuoteAggregation
    settlement_family_ref: str
    settlement_function_ref: str
    fixture_ref: str
    semantic_evidence_statuses: tuple[EvidenceStatus, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_binding(self) -> AtomicTicketBindingDescriptor:
        if self.arity_min > self.arity_max:
            raise ValueError("ticket arity_min cannot exceed arity_max")
        if tuple(sorted(self.component_baseline_ids)) != self.component_baseline_ids:
            raise ValueError("ticket component baseline ids must be sorted")
        indexed_ids = [item.baseline_id for item in self.component_key_bindings]
        if len(indexed_ids) != len(set(indexed_ids)):
            raise ValueError("ticket component index repeats a baseline")
        if set(indexed_ids) != set(self.component_baseline_ids):
            raise ValueError("ticket component index does not bind its component universe")
        keys = [item.component_key for item in self.component_key_bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("ticket component index repeats a component key")
        return self


class AtomicTicketBindingVersion(_ContentHashedModel):
    schema_version: Literal["xinao.atomic_ticket_binding.v1"] = "xinao.atomic_ticket_binding.v1"
    binding_ref: Literal["xinao-composite-atomic-ticket-binding.v1"] = (
        "xinao-composite-atomic-ticket-binding.v1"
    )
    source_manifest_ref: Literal["xinao-independent-416-active-selection-domain.v1"] = (
        "xinao-independent-416-active-selection-domain.v1"
    )
    source_manifest_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_catalog_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_count: Literal[37] = 37
    exact_atomic_ticket_count: Literal[21652539822] = 21652539822
    materialized_atomic_ticket_count: Literal[0] = 0
    bindings: tuple[AtomicTicketBindingDescriptor, ...]
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_bindings(self) -> AtomicTicketBindingVersion:
        if len(self.bindings) != self.binding_count:
            raise ValueError("atomic ticket version must contain exactly 37 bindings")
        binding_ids = [binding.binding_id for binding in self.bindings]
        spec_ids = [binding.domain_spec_id for binding in self.bindings]
        if len(binding_ids) != len(set(binding_ids)) or len(spec_ids) != len(set(spec_ids)):
            raise ValueError("atomic ticket bindings contain duplicate identities")
        if sum(binding.exact_atomic_ticket_count for binding in self.bindings) != (
            self.exact_atomic_ticket_count
        ):
            raise ValueError("atomic ticket total drifted")
        if {binding.family_id for binding in self.bindings} != _COMPOSITE_FAMILIES:
            raise ValueError("atomic ticket bindings do not cover every composite family")
        return self


class AtomicTicketSelection(_FrozenModel):
    binding_id: str
    selection_id: str
    canonical_ticket_id: str
    participating_baseline_ids: tuple[str, ...] = Field(min_length=1)
    quote_aggregation_ref: QuoteAggregation
    settlement_family_ref: str
    settlement_function_ref: str


class SelectionManifestComparisonVersion(_ContentHashedModel):
    schema_version: Literal["xinao.selection_manifest_comparison.v1"] = (
        "xinao.selection_manifest_comparison.v1"
    )
    independent_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compared_spec_count: Literal[233] = 233
    compared_component_count: Literal[416] = 416
    compared_fields: tuple[str, ...]
    exact_match: Literal[True] = True


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    # Include schema/default fields in the hash exactly as they appear after validation.
    # ``model_construct`` is used only to project defaults; the final object still goes
    # through ordinary strict validation and its hash validator below.
    projected = model.model_construct(content_hash="0" * 64, **dict(payload))
    materialized = projected.model_dump(mode="json", exclude={"content_hash"})
    materialized["content_hash"] = canonical_sha256(materialized)
    return model.model_validate(materialized)


def load_play_catalog(path: Path = DEFAULT_PLAY_CATALOG_PATH) -> dict[str, Any]:
    payload = load_snapshot_object(path)
    if not isinstance(payload, dict):
        raise TypeError("play catalog must be a JSON object")
    return payload


def _required_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"catalog row requires non-empty text field {key}")
    return value


def _required_int(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"catalog row requires integer field {key}")
    return value


def _normalize_catalog(
    catalog: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    if catalog.get("schema_version") != "xinao.play_catalog.v1":
        raise ValueError("unsupported play catalog schema_version")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or any(not isinstance(row, Mapping) for row in entries):
        raise TypeError("play catalog entries must be a list of objects")
    if catalog.get("entry_count") != 433 or len(entries) != 433:
        raise ValueError("independent manifest requires exactly 433 catalog rows")
    rows = tuple(
        sorted((dict(row) for row in entries), key=lambda row: str(row.get("baseline_id")))
    )
    ids = tuple(_required_text(row, "baseline_id") for row in rows)
    if ids != EXPECTED_BASELINE_IDS:
        raise ValueError("catalog baseline ids must be exactly BO0001..BO0433")
    family_counts = dict(Counter(_required_text(row, "family_id") for row in rows))
    if family_counts != EXPECTED_FAMILY_COUNTS:
        raise ValueError("catalog family counts drifted from the frozen 13-family partition")
    for row in rows:
        _required_text(row, "play_id")
        _required_text(row, "play_name")
        _required_text(row, "option_id")
        _required_text(row, "option_name")
        _required_int(row, "pid")
        _required_int(row, "tid")
        if row["option_id"] != f"baseline-option:{row['baseline_id']}":
            raise ValueError(f"catalog option identity drifted for {row['baseline_id']}")
    normalized = {
        key: value for key, value in catalog.items() if key not in {"entries", "content_hash"}
    }
    normalized["entries"] = list(rows)
    observed_hash = catalog.get("content_hash")
    if not isinstance(observed_hash, str) or not _HASH_PATTERN.fullmatch(observed_hash):
        raise ValueError("catalog content_hash is missing or malformed")
    if canonical_sha256(normalized) != observed_hash:
        raise ValueError("catalog content_hash does not bind normalized catalog content")
    normalized["content_hash"] = observed_hash
    baseline_hash = normalized.get("baseline_sha256")
    if not isinstance(baseline_hash, str) or not _HASH_PATTERN.fullmatch(baseline_hash):
        raise ValueError("catalog baseline_sha256 is missing or malformed")
    _required_text(normalized, "catalog_ref")
    _required_text(normalized, "baseline_ref")
    return normalized, rows


def classify_catalog_physical_roles(
    catalog: Mapping[str, Any],
) -> dict[str, Literal["ACTIVE_SETTLEMENT", "FROZEN_AGENT_ROUTE_QUOTE"]]:
    """Classify all 433 source identities without creating semantic bindings."""

    _, rows = _normalize_catalog(catalog)
    return {
        _required_text(row, "baseline_id"): (
            "FROZEN_AGENT_ROUTE_QUOTE"
            if row["baseline_id"] in FROZEN_ROUTE_QUOTE_BASELINE_IDS
            else "ACTIVE_SETTLEMENT"
        )
        for row in rows
    }


def active_catalog_projection_hash(catalog: Mapping[str, Any]) -> str:
    """Hash only the 416 source rows admitted to ACTIVE settlement semantics."""

    _, rows = _normalize_catalog(catalog)
    active_rows = [
        dict(row)
        for row in rows
        if _required_text(row, "baseline_id") in ACTIVE_SETTLEMENT_BASELINE_IDS
    ]
    if len(active_rows) != EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT:
        raise ValueError("source catalog does not classify exactly 416 ACTIVE rows")
    return canonical_sha256(
        {
            "schema_version": "xinao.active_catalog_projection.v1",
            "physical_role": "ACTIVE_SETTLEMENT",
            "rows": active_rows,
        }
    )


def _source_scope_hash(rows: Sequence[Mapping[str, Any]], *, fixture_ref: str) -> str:
    return canonical_sha256(
        {
            "grammar_ref": GRAMMAR_VERSION_REF,
            "fixture_ref": fixture_ref,
            "rows": [dict(row) for row in sorted(rows, key=lambda row: str(row["baseline_id"]))],
        }
    )


def _spec(payload: Mapping[str, Any]) -> IndependentSelectionDomainSpec:
    return _with_hash(IndependentSelectionDomainSpec, payload)


def _basic_spec(row: Mapping[str, Any]) -> IndependentSelectionDomainSpec:
    baseline_id = _required_text(row, "baseline_id")
    option_range = row.get("option_range")
    count = 1
    rule = "literal-option-name.v1"
    if option_range is not None:
        if not isinstance(option_range, str):
            raise TypeError(f"{baseline_id}.option_range must be text or null")
        match = _RANGE_PATTERN.fullmatch(option_range)
        if match is None:
            raise ValueError(f"unsupported basic option range for {baseline_id}")
        start, end = (int(value) for value in match.groups())
        if start < 1 or end > 49 or start > end:
            raise ValueError(f"invalid numeric option range for {baseline_id}")
        count = end - start + 1
        rule = f"zero-padded-inclusive-range:{start:02d}-{end:02d}.v1"
    fixture_ref = "xinao.independent-basic-catalog-option-grammar.v1"
    return _spec(
        {
            "spec_id": f"selection-domain:basic:{baseline_id}",
            "family_id": row["family_id"],
            "play_id": row["play_id"],
            "play_name": row["play_name"],
            "component_baseline_ids": (baseline_id,),
            "domain_kind": "FINITE_CATALOG_OPTION_SELECTION",
            "arity_min": 1,
            "arity_max": 1,
            "exact_atomic_selection_count": count,
            "canonical_encoding": "source-canonical-option-string",
            "canonical_selection_id_rule": rule,
            "participating_baseline_ids_rule": "FIXED_SINGLE_BASELINE",
            "fixture_ref": fixture_ref,
            "semantic_evidence_statuses": ("EXPLICIT_PAGE",),
            "source_scope_hash": _source_scope_hash((row,), fixture_ref=fixture_ref),
        }
    )


def _set_spec(row: Mapping[str, Any]) -> IndependentSelectionDomainSpec:
    baseline_id = _required_text(row, "baseline_id")
    if row["family_id"] == "six-zodiac":
        count = comb(12, 6)
        kind = "DISTINCT_ZODIAC_LABEL_COMBINATION"
        arity = 6
        rule = "six-distinct-labels-in-zodiac-order.v1"
        fixture_ref = SIX_ZODIAC_FIXTURE_REF
        statuses: tuple[EvidenceStatus, ...] = ("EXPLICIT_PAGE", "RESEARCH_CONVENTION")
    else:
        count = 1
        kind = "FINITE_CATALOG_OPTION_SELECTION"
        arity = 1
        rule = "literal-catalog-option-name.v1"
        fixture_ref = "xinao.independent-set-row-option-grammar.v1"
        statuses = ("EXPLICIT_PAGE",)
    return _spec(
        {
            "spec_id": f"selection-domain:sets:{baseline_id}",
            "family_id": row["family_id"],
            "play_id": row["play_id"],
            "play_name": row["play_name"],
            "component_baseline_ids": (baseline_id,),
            "domain_kind": kind,
            "arity_min": arity,
            "arity_max": arity,
            "exact_atomic_selection_count": count,
            "canonical_encoding": "source-selection-key",
            "canonical_selection_id_rule": rule,
            "participating_baseline_ids_rule": "FIXED_SINGLE_BASELINE",
            "fixture_ref": fixture_ref,
            "semantic_evidence_statuses": statuses,
            "source_scope_hash": _source_scope_hash((row,), fixture_ref=fixture_ref),
        }
    )


def _combination_semantic_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    baseline_id = _required_text(row, "baseline_id")
    family_id = _required_text(row, "family_id")
    semantic = _COMBINATION_SEMANTIC_BY_BASELINE.get(baseline_id)
    if semantic is None:
        semantic = {
            "multi-select-no-hit": "NO_SELECTED_IN_SEVEN",
            "multi-select-one-hit": "EXACTLY_ONE_SELECTED_IN_SEVEN",
            "special-regular-hit": "ANY_SELECTED_IN_SEVEN",
        }.get(family_id)
    if semantic is None:
        raise ValueError(f"combination semantic fixture is missing {baseline_id}")
    return semantic, f"settle-combination:{semantic}.v1"


def _combination_spec(row: Mapping[str, Any]) -> IndependentSelectionDomainSpec:
    baseline_id = _required_text(row, "baseline_id")
    try:
        arity = _COMBINATION_ARITY_BY_BASELINE[baseline_id]
    except KeyError as exc:
        raise ValueError(f"combination arity fixture is missing {baseline_id}") from exc
    if row.get("option_range") != "01-49":
        raise ValueError(f"combination source universe drifted for {baseline_id}")
    fixture_ref = f"{COMBINATION_FIXTURE_REF}#{baseline_id}"
    return _spec(
        {
            "spec_id": f"selection-domain:combinations:{baseline_id}",
            "family_id": row["family_id"],
            "play_id": row["play_id"],
            "play_name": row["play_name"],
            "component_baseline_ids": (baseline_id,),
            "domain_kind": "UNORDERED_NUMBER_COMBINATION",
            "arity_min": arity,
            "arity_max": arity,
            "exact_atomic_selection_count": comb(49, arity),
            "canonical_encoding": "ascending-zero-padded-2-digit-csv",
            "canonical_selection_id_rule": "ascending-distinct-number-csv-01-to-49.v1",
            "participating_baseline_ids_rule": "FIXED_SINGLE_BASELINE",
            "fixture_ref": fixture_ref,
            "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
            "source_scope_hash": _source_scope_hash((row,), fixture_ref=fixture_ref),
        }
    )


def _linked_spec(rows: Sequence[Mapping[str, Any]]) -> IndependentSelectionDomainSpec:
    first = rows[0]
    family_id = _required_text(first, "family_id")
    play_id = _required_text(first, "play_id")
    if any(row["play_id"] != play_id or row["family_id"] != family_id for row in rows):
        raise ValueError("linked domain rows must belong to one play and family")
    key = (_required_int(first, "pid"), _required_int(first, "tid"))
    try:
        arity = _LINKED_ARITY_BY_PID_TID[key]
    except KeyError as exc:
        raise ValueError(f"linked arity fixture is missing {key}") from exc
    labels = ZODIAC_ORDER if family_id == "linked-zodiac" else TAIL_ORDER
    if {row["option_name"] for row in rows} != set(labels) or len(rows) != len(labels):
        raise ValueError(f"linked label component partition drifted for {play_id}")
    ordered_ids = tuple(sorted(_required_text(row, "baseline_id") for row in rows))
    fixture_ref = f"{LINKED_FIXTURE_REF}#pid={key[0]};tid={key[1]}"
    return _spec(
        {
            "spec_id": f"selection-domain:{family_id}:{play_id}",
            "family_id": family_id,
            "play_id": play_id,
            "play_name": first["play_name"],
            "component_baseline_ids": ordered_ids,
            "domain_kind": "DISTINCT_LABEL_COMBINATION",
            "arity_min": arity,
            "arity_max": arity,
            "exact_atomic_selection_count": comb(len(labels), arity),
            "canonical_encoding": "source-selection-key",
            "canonical_selection_id_rule": (
                "distinct-zodiac-labels-in-fixed-order.v1"
                if family_id == "linked-zodiac"
                else "distinct-tail-labels-in-numeric-order.v1"
            ),
            "participating_baseline_ids_rule": "SELECTED_LABEL_COMPONENT_BASELINES",
            "fixture_ref": fixture_ref,
            "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
            "source_scope_hash": _source_scope_hash(rows, fixture_ref=fixture_ref),
        }
    )


def _parlay_component_index(rows: Sequence[Mapping[str, Any]]) -> tuple[ComponentKeyBinding, ...]:
    result = []
    observed: set[tuple[int, str]] = set()
    for row in rows:
        match = _PARLAY_OPTION_PATTERN.fullmatch(_required_text(row, "option_name"))
        if match is None:
            raise ValueError(f"invalid parlay option {row.get('baseline_id')}")
        position = int(match.group(1))
        attribute = _PARLAY_ATTRIBUTE_BY_LABEL[match.group(2)]
        pair = (position, attribute)
        if pair in observed:
            raise ValueError("parlay component index contains a duplicate position/attribute")
        observed.add(pair)
        result.append(
            ComponentKeyBinding(
                component_key=f"P{position:02d}:{attribute}",
                baseline_id=_required_text(row, "baseline_id"),
            )
        )
    expected = {
        (position, attribute) for position in range(1, 7) for attribute in PARLAY_ATTRIBUTE_ORDER
    }
    if observed != expected:
        raise ValueError("parlay rows must cover 6 positions by 7 attributes exactly")
    return tuple(sorted(result, key=lambda item: item.component_key))


def _parlay_spec(rows: Sequence[Mapping[str, Any]]) -> IndependentSelectionDomainSpec:
    if len(rows) != 42 or len({row["play_id"] for row in rows}) != 1:
        raise ValueError("parlay domain requires one complete 42-component play")
    _parlay_component_index(rows)
    first = rows[0]
    ordered_ids = tuple(sorted(_required_text(row, "baseline_id") for row in rows))
    count = sum(comb(6, arity) * 7**arity for arity in range(2, 7))
    return _spec(
        {
            "spec_id": f"selection-domain:parlay:{first['play_id']}",
            "family_id": "parlay",
            "play_id": first["play_id"],
            "play_name": first["play_name"],
            "component_baseline_ids": ordered_ids,
            "domain_kind": "UNIQUE_POSITION_LEG_PRODUCT",
            "arity_min": 2,
            "arity_max": 6,
            "exact_atomic_selection_count": count,
            "canonical_encoding": "source-selection-key",
            "canonical_selection_id_rule": "ascending-position-equals-attribute-plus-joined.v1",
            "participating_baseline_ids_rule": ("SELECTED_POSITION_ATTRIBUTE_COMPONENT_BASELINES"),
            "fixture_ref": PARLAY_FIXTURE_REF,
            "semantic_evidence_statuses": ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"),
            "source_scope_hash": _source_scope_hash(rows, fixture_ref=PARLAY_FIXTURE_REF),
        }
    )


def compile_independent_selection_manifest(
    catalog: Mapping[str, Any],
) -> IndependentExpectedSelectionDomainManifestVersion:
    """Compile the independent expected domain for the 416 ACTIVE rows only."""

    normalized, rows = _normalize_catalog(catalog)
    active_rows = tuple(row for row in rows if row["baseline_id"] in ACTIVE_SETTLEMENT_BASELINE_IDS)
    specifications: list[IndependentSelectionDomainSpec] = []
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in active_rows:
        family_id = row["family_id"]
        if family_id in _BASIC_FAMILIES:
            specifications.append(_basic_spec(row))
        elif family_id in _SET_FAMILIES:
            specifications.append(_set_spec(row))
        elif family_id in _COMBINATION_FAMILIES:
            specifications.append(_combination_spec(row))
        elif family_id in _LINKED_FAMILIES or family_id == "parlay":
            grouped[row["play_id"]].append(row)
        else:  # pragma: no cover - family partition validation is exhaustive
            raise ValueError(f"unrouted family: {family_id}")
    for play_id in sorted(grouped):
        group = tuple(sorted(grouped[play_id], key=lambda row: row["baseline_id"]))
        if group[0]["family_id"] == "parlay":
            specifications.append(_parlay_spec(group))
        else:
            specifications.append(_linked_spec(group))
    ordered = tuple(sorted(specifications, key=lambda spec: spec.spec_id))
    return _with_hash(
        IndependentExpectedSelectionDomainManifestVersion,
        {
            "source_catalog_ref": normalized["catalog_ref"],
            "active_catalog_projection_hash": active_catalog_projection_hash(normalized),
            "component_catalog_row_count": 416,
            "family_counts": EXPECTED_ACTIVE_FAMILY_COUNTS,
            "selection_domain_spec_count": 233,
            "exact_atomic_selection_count": EXPECTED_ACTIVE_ATOMIC_SELECTION_COUNT,
            "materialized_atomic_selection_count": 0,
            "specifications": ordered,
            "foundation_complete": False,
        },
    )


def compile_default_independent_selection_manifest(
    path: Path = DEFAULT_PLAY_CATALOG_PATH,
) -> IndependentExpectedSelectionDomainManifestVersion:
    return compile_independent_selection_manifest(load_play_catalog(path))


def _component_index_for_linked(
    rows: Sequence[Mapping[str, Any]], *, labels: Sequence[str]
) -> tuple[ComponentKeyBinding, ...]:
    by_label = {_required_text(row, "option_name"): row for row in rows}
    if set(by_label) != set(labels):
        raise ValueError("linked ticket component labels drifted")
    return tuple(
        ComponentKeyBinding(
            component_key=label,
            baseline_id=_required_text(by_label[label], "baseline_id"),
        )
        for label in labels
    )


def _binding(payload: Mapping[str, Any]) -> AtomicTicketBindingDescriptor:
    return _with_hash(AtomicTicketBindingDescriptor, payload)


def compile_atomic_ticket_bindings(
    catalog: Mapping[str, Any],
    manifest: IndependentExpectedSelectionDomainManifestVersion | None = None,
) -> AtomicTicketBindingVersion:
    """Compile one canonical ticket identity per composite domain, never per component."""

    normalized, rows = _normalize_catalog(catalog)
    independent = manifest or compile_independent_selection_manifest(normalized)
    projection_hash = active_catalog_projection_hash(normalized)
    if independent.active_catalog_projection_hash != projection_hash:
        raise ValueError("atomic ticket binding manifest belongs to another ACTIVE catalog")
    specs = {spec.spec_id: spec for spec in independent.specifications}
    active_rows = tuple(row for row in rows if row["baseline_id"] in ACTIVE_SETTLEMENT_BASELINE_IDS)
    rows_by_id = {row["baseline_id"]: row for row in active_rows}
    rows_by_play: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in active_rows:
        rows_by_play[row["play_id"]].append(row)
    bindings: list[AtomicTicketBindingDescriptor] = []

    for baseline_id in sorted(_COMBINATION_ARITY_BY_BASELINE):
        row = rows_by_id[baseline_id]
        spec_id = f"selection-domain:combinations:{baseline_id}"
        spec = specs[spec_id]
        semantic, settlement = _combination_semantic_identity(row)
        bindings.append(
            _binding(
                {
                    "binding_id": f"atomic-ticket-binding:{row['play_id']}",
                    "domain_spec_id": spec_id,
                    "family_id": row["family_id"],
                    "play_id": row["play_id"],
                    "component_baseline_ids": (baseline_id,),
                    "component_key_bindings": (
                        ComponentKeyBinding(component_key="BOUND", baseline_id=baseline_id),
                    ),
                    "arity_min": spec.arity_min,
                    "arity_max": spec.arity_max,
                    "exact_atomic_ticket_count": spec.exact_atomic_selection_count,
                    "selection_id_grammar_ref": spec.canonical_selection_id_rule,
                    "lazy_generator_ref": "iter-independent-number-combinations.v1",
                    "participating_baseline_ids_rule": "FIXED_SINGLE_BASELINE",
                    "quote_aggregation_ref": "BOUND_BASELINE_TIER_COMPONENT",
                    "settlement_family_ref": semantic,
                    "settlement_function_ref": settlement,
                    "fixture_ref": spec.fixture_ref,
                    "semantic_evidence_statuses": (
                        "EXPLICIT_PAGE",
                        "RESEARCH_CONVENTION",
                    ),
                }
            )
        )

    for spec in independent.specifications:
        if spec.family_id not in _LINKED_FAMILIES | {"parlay"}:
            continue
        group = tuple(sorted(rows_by_play[spec.play_id], key=lambda row: row["baseline_id"]))
        if spec.family_id == "linked-zodiac":
            index = _component_index_for_linked(group, labels=ZODIAC_ORDER)
            settlement_family = "zodiac-link-all-seven.v1"
            settlement_function = "settle-linked-zodiac-atomic-ticket.v1"
            participant_rule = "SELECTED_LABEL_COMPONENT_BASELINES"
            quote_aggregation = "MIN_SELECTED_COMPONENT"
            generator = "iter-independent-linked-label-combinations.v1"
        elif spec.family_id == "linked-tail":
            index = _component_index_for_linked(group, labels=TAIL_ORDER)
            settlement_family = "tail-link-all-seven.v1"
            settlement_function = "settle-linked-tail-atomic-ticket.v1"
            participant_rule = "SELECTED_LABEL_COMPONENT_BASELINES"
            quote_aggregation = "MIN_SELECTED_COMPONENT"
            generator = "iter-independent-linked-label-combinations.v1"
        else:
            index = _parlay_component_index(group)
            settlement_family = "ordered-regular-position-parlay.v1"
            settlement_function = "settle-ordered-regular-position-parlay.v1"
            participant_rule = "SELECTED_POSITION_ATTRIBUTE_COMPONENT_BASELINES"
            quote_aggregation = "PRODUCT_NON_VOID_LEGS"
            generator = "iter-independent-unique-position-leg-products.v1"
        bindings.append(
            _binding(
                {
                    "binding_id": f"atomic-ticket-binding:{spec.play_id}",
                    "domain_spec_id": spec.spec_id,
                    "family_id": spec.family_id,
                    "play_id": spec.play_id,
                    "component_baseline_ids": spec.component_baseline_ids,
                    "component_key_bindings": index,
                    "arity_min": spec.arity_min,
                    "arity_max": spec.arity_max,
                    "exact_atomic_ticket_count": spec.exact_atomic_selection_count,
                    "selection_id_grammar_ref": spec.canonical_selection_id_rule,
                    "lazy_generator_ref": generator,
                    "participating_baseline_ids_rule": participant_rule,
                    "quote_aggregation_ref": quote_aggregation,
                    "settlement_family_ref": settlement_family,
                    "settlement_function_ref": settlement_function,
                    "fixture_ref": spec.fixture_ref,
                    "semantic_evidence_statuses": (
                        "EXPLICIT_PAGE",
                        "RESEARCH_CONVENTION",
                    ),
                }
            )
        )
    ordered = tuple(sorted(bindings, key=lambda binding: binding.binding_id))
    return _with_hash(
        AtomicTicketBindingVersion,
        {
            "source_manifest_content_hash": independent.content_hash,
            "active_catalog_projection_hash": projection_hash,
            "binding_count": 37,
            "exact_atomic_ticket_count": 21652539822,
            "materialized_atomic_ticket_count": 0,
            "bindings": ordered,
            "foundation_complete": False,
        },
    )


def compile_default_atomic_ticket_bindings(
    path: Path = DEFAULT_PLAY_CATALOG_PATH,
) -> AtomicTicketBindingVersion:
    catalog = load_play_catalog(path)
    manifest = compile_independent_selection_manifest(catalog)
    return compile_atomic_ticket_bindings(catalog, manifest)


def iter_atomic_ticket_selections(
    binding: AtomicTicketBindingDescriptor,
) -> Iterator[AtomicTicketSelection]:
    """Lazily yield canonical tickets for one composite binding."""

    index = {item.component_key: item.baseline_id for item in binding.component_key_bindings}

    def selection(selection_id: str, participating: Sequence[str]) -> AtomicTicketSelection:
        return AtomicTicketSelection(
            binding_id=binding.binding_id,
            selection_id=selection_id,
            canonical_ticket_id=f"{binding.play_id}::{selection_id}",
            participating_baseline_ids=tuple(participating),
            quote_aggregation_ref=binding.quote_aggregation_ref,
            settlement_family_ref=binding.settlement_family_ref,
            settlement_function_ref=binding.settlement_function_ref,
        )

    if binding.participating_baseline_ids_rule == "FIXED_SINGLE_BASELINE":
        baseline_id = index["BOUND"]
        for numbers in combinations(range(1, 50), binding.arity_min):
            selection_id = ",".join(f"{number:02d}" for number in numbers)
            yield selection(selection_id, (baseline_id,))
        return
    if binding.participating_baseline_ids_rule == "SELECTED_LABEL_COMPONENT_BASELINES":
        labels = ZODIAC_ORDER if binding.family_id == "linked-zodiac" else TAIL_ORDER
        for selected_labels in combinations(labels, binding.arity_min):
            selection_id = "+".join(selected_labels)
            yield selection(selection_id, tuple(index[label] for label in selected_labels))
        return
    for arity in range(binding.arity_min, binding.arity_max + 1):
        for positions in combinations(range(1, 7), arity):
            for attributes in product(PARLAY_ATTRIBUTE_ORDER, repeat=arity):
                keys = tuple(
                    f"P{position:02d}:{attribute}"
                    for position, attribute in zip(positions, attributes, strict=True)
                )
                selection_id = "+".join(key.replace(":", "=") for key in keys)
                yield selection(selection_id, tuple(index[key] for key in keys))


def _manifest_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
    raise TypeError("registry manifest must be a mapping or a Pydantic model")


_COMPARISON_FIELDS = (
    "family_id",
    "play_id",
    "component_baseline_ids",
    "domain_kind",
    "arity_min",
    "arity_max",
    "exact_atomic_selection_count",
    "canonical_encoding",
)


def assert_registry_manifest_matches(
    independent: IndependentExpectedSelectionDomainManifestVersion,
    registry_manifest: Any,
) -> SelectionManifestComparisonVersion:
    """Fail closed unless the semantic registry matches this independent oracle."""

    observed = _manifest_payload(registry_manifest)
    if observed.get("active_catalog_projection_hash") != independent.active_catalog_projection_hash:
        raise ValueError("registry manifest is bound to a different ACTIVE catalog")
    if observed.get("selection_domain_spec_count") != independent.selection_domain_spec_count:
        raise ValueError("registry selection-domain spec count drifted")
    if observed.get("exact_atomic_selection_count") != independent.exact_atomic_selection_count:
        raise ValueError("registry exact atomic selection total drifted")
    raw_specs = observed.get("specifications")
    if not isinstance(raw_specs, (list, tuple)):
        raise TypeError("registry specifications must be a sequence")
    observed_specs = [_manifest_payload(spec) for spec in raw_specs]
    observed_ids = [spec.get("spec_id") for spec in observed_specs]
    if any(not isinstance(spec_id, str) for spec_id in observed_ids):
        raise ValueError("registry manifest contains a malformed spec id")
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("registry manifest contains duplicate spec ids")
    expected_by_id = {spec.spec_id: spec for spec in independent.specifications}
    observed_by_id = {str(spec["spec_id"]): spec for spec in observed_specs}
    missing = sorted(set(expected_by_id) - set(observed_by_id))
    unexpected = sorted(set(observed_by_id) - set(expected_by_id))
    if missing or unexpected:
        raise ValueError(
            f"registry domain identity drift: missing={missing}, unexpected={unexpected}"
        )
    for spec_id, expected in expected_by_id.items():
        expected_payload = expected.model_dump(mode="json")
        actual = observed_by_id[spec_id]
        for field in _COMPARISON_FIELDS:
            expected_value = expected_payload[field]
            actual_value = actual.get(field)
            if field == "component_baseline_ids" and isinstance(actual_value, (list, tuple)):
                actual_value = list(actual_value)
            if actual_value != expected_value:
                raise ValueError(
                    f"registry domain scope drift at {spec_id}.{field}: "
                    f"expected={expected_value!r}, observed={actual_value!r}"
                )
    observed_components = [
        baseline_id
        for spec in observed_specs
        for baseline_id in spec.get("component_baseline_ids", ())
    ]
    if set(observed_components) != ACTIVE_SETTLEMENT_BASELINE_IDS or len(
        observed_components
    ) != len(set(observed_components)):
        raise ValueError(
            "registry ACTIVE component partition has a missing, duplicate, or foreign baseline"
        )
    registry_hash = observed.get("content_hash")
    if not isinstance(registry_hash, str) or not _HASH_PATTERN.fullmatch(registry_hash):
        registry_hash = canonical_sha256(
            {key: value for key, value in observed.items() if key != "content_hash"}
        )
    return _with_hash(
        SelectionManifestComparisonVersion,
        {
            "independent_manifest_hash": independent.content_hash,
            "registry_manifest_hash": registry_hash,
            "compared_spec_count": 233,
            "compared_component_count": 416,
            "compared_fields": _COMPARISON_FIELDS,
            "exact_match": True,
        },
    )


__all__ = [
    "ACTIVE_SETTLEMENT_BASELINE_IDS",
    "DEFAULT_PLAY_CATALOG_PATH",
    "EXPECTED_ACTIVE_ATOMIC_SELECTION_COUNT",
    "EXPECTED_ACTIVE_FAMILY_COUNTS",
    "EXPECTED_ACTIVE_SETTLEMENT_COMPONENT_COUNT",
    "EXPECTED_FAMILY_COUNTS",
    "EXPECTED_FROZEN_ROUTE_QUOTE_COMPONENT_COUNT",
    "FROZEN_ROUTE_QUOTE_BASELINE_IDS",
    "AtomicTicketBindingDescriptor",
    "AtomicTicketBindingVersion",
    "AtomicTicketSelection",
    "IndependentExpectedSelectionDomainManifestVersion",
    "IndependentSelectionDomainSpec",
    "SelectionManifestComparisonVersion",
    "active_catalog_projection_hash",
    "assert_registry_manifest_matches",
    "classify_catalog_physical_roles",
    "compile_atomic_ticket_bindings",
    "compile_default_atomic_ticket_bindings",
    "compile_default_independent_selection_manifest",
    "compile_independent_selection_manifest",
    "iter_atomic_ticket_selections",
    "load_play_catalog",
]
