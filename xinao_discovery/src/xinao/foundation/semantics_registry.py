"""Canonical in-memory F1 registry over 416 ACTIVE settlement rows.

The four family compilers intentionally keep their own strict source models.
This module preserves those models and projects them into one deterministic
schema.  The projection distinguishes catalog *component rows* from expanded
atomic tickets: it records exact selection-domain counts and hashes, but never
materialises the combined atomic universe.

This is a semantic-registry artifact, not the whole F1 gate.  In particular it
does not claim that the 913-draw event matrix, replay/property evidence, or F2
probability/cost artifacts have been compiled.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xinao.canonical import canonical_sha256
from xinao.foundation.f4_snapshot_runtime import load_object as load_snapshot_object
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    EXPECTED_ACTIVE_ATOMIC_SELECTION_COUNT,
    active_catalog_projection_hash,
)
from xinao.foundation.semantics_basic import (
    RuleSemanticRecord as BasicRuleSemanticRecord,
)
from xinao.foundation.semantics_basic import (
    compile_basic_semantics,
)
from xinao.foundation.semantics_basic import (
    semantic_records_hash as basic_records_hash,
)
from xinao.foundation.semantics_combinations import (
    CombinationSemanticRecord,
    combination_records_hash,
    compile_combination_catalog,
)
from xinao.foundation.semantics_linked import (
    LinkedSemanticsCompilation,
    compile_linked_semantics,
)
from xinao.foundation.semantics_sets import (
    SetFamilySemanticsCompilation,
    compile_set_family_semantics,
)

DEFAULT_PLAY_CATALOG_PATH = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\state\catalog\play_catalog.v1.json"
)

EXPECTED_FAMILY_COUNTS = {
    "special-number": 24,
    "regular-number": 10,
    "regular-position-special": 60,
    "other-explicit": 95,
    "one-zodiac-tail": 22,
    "six-zodiac": 2,
    "linked-number": 5,
    "multi-select-no-hit": 6,
    "multi-select-one-hit": 6,
    "special-regular-hit": 5,
    "linked-zodiac": 96,
    "linked-tail": 60,
    "parlay": 42,
}
EXPECTED_FAMILY_IDS = frozenset(EXPECTED_FAMILY_COUNTS)
EXPECTED_CATALOG_ROWS = 433
EXPECTED_ACTIVE_FAMILY_COUNTS = {
    **EXPECTED_FAMILY_COUNTS,
    "special-number": EXPECTED_FAMILY_COUNTS["special-number"] - 12,
    "regular-number": EXPECTED_FAMILY_COUNTS["regular-number"] - 5,
}

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
_LINKED_FAMILIES = frozenset({"linked-zodiac", "linked-tail", "parlay"})
_BASELINE_PATTERN = re.compile(r"^BO\d{4}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


class CatalogRowBinding(_ContentHashedModel):
    """Exact typed preservation of the 16 fields in one catalog row."""

    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    play_group: str
    family_id: str
    play_id: str
    option_id: str
    play_name: str
    pid: int = Field(gt=0)
    tid: int = Field(gt=0)
    panel: str | None
    bet_shape: str | None
    option_name: str
    option_range: str | None
    baseline_odds_components: tuple[str, ...] = Field(min_length=1)
    compilation_status: str
    settlement_function_ref: str | None
    not_compiled_reason: str | None

    @field_validator("baseline_odds_components")
    @classmethod
    def validate_quote_components(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("catalog quote components must be non-empty decimal strings")
            try:
                number = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("catalog quote component is not decimal") from exc
            if not number.is_finite() or number <= 0:
                raise ValueError("catalog quote components must be finite and positive")
        return values


class CanonicalSettlementTier(_FrozenModel):
    tier_id: str
    terminal_role: Literal["HIT", "MISS", "VOID"]
    predicate_ref: str
    payout_kind: Literal[
        "QUOTE_COMPONENT",
        "QUOTE_AGGREGATION",
        "ZERO",
        "REFUND_STAKE",
    ]
    payout_component_index: int | None = Field(default=None, ge=0)


class CanonicalSelectionDomainSpec(_ContentHashedModel):
    """Compact domain descriptor; no expanded atomic ticket payload is stored."""

    spec_id: str
    family_id: str
    play_id: str
    component_baseline_ids: tuple[str, ...] = Field(min_length=1)
    domain_kind: str
    arity_min: int = Field(ge=1)
    arity_max: int = Field(ge=1)
    exact_atomic_selection_count: int = Field(gt=0)
    expansion_policy: Literal[
        "FINITE_SOURCE_DOMAIN_DESCRIPTOR",
        "LAZY_COMBINATORIAL",
    ]
    canonical_manifest_materialized_atomic_selection_count: Literal[0] = 0
    source_materialized_atomic_selection_count: int = Field(ge=0)
    canonical_encoding: str
    constraint_ref: str
    source_domain_ref: str
    source_domain_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_domain_shape(self) -> CanonicalSelectionDomainSpec:
        if self.arity_min > self.arity_max:
            raise ValueError("selection-domain arity_min cannot exceed arity_max")
        if len(self.component_baseline_ids) != len(set(self.component_baseline_ids)):
            raise ValueError("selection-domain component baseline ids must be unique")
        return self


class ExpectedSelectionDomainManifestVersion(_ContentHashedModel):
    schema_version: Literal["xinao.expected_selection_domain_manifest.v1"] = (
        "xinao.expected_selection_domain_manifest.v1"
    )
    manifest_ref: Literal["xinao-416-active-selection-domain.v1"] = (
        "xinao-416-active-selection-domain.v1"
    )
    source_catalog_ref: str
    active_catalog_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_catalog_row_count: Literal[416] = 416
    selection_domain_spec_count: Literal[233] = 233
    exact_atomic_selection_count: Literal[21652542248] = 21652542248
    canonical_materialized_atomic_selection_count: Literal[0] = 0
    source_materialized_atomic_selection_count: int = Field(ge=0)
    expansion_policy: Literal["COMPACT_DESCRIPTOR_WITH_LAZY_EXPANSION"] = (
        "COMPACT_DESCRIPTOR_WITH_LAZY_EXPANSION"
    )
    specifications: tuple[CanonicalSelectionDomainSpec, ...]
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_component_partition(self) -> ExpectedSelectionDomainManifestVersion:
        if self.selection_domain_spec_count != len(self.specifications):
            raise ValueError("selection-domain spec count does not match specifications")
        component_ids = [
            baseline_id
            for spec in self.specifications
            for baseline_id in spec.component_baseline_ids
        ]
        if len(component_ids) != self.component_catalog_row_count:
            raise ValueError("selection-domain specs do not cover 416 ACTIVE rows")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("selection-domain specs overlap component rows")
        if set(component_ids) != ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("selection-domain specs contain a frozen or unknown baseline")
        if self.exact_atomic_selection_count != sum(
            spec.exact_atomic_selection_count for spec in self.specifications
        ):
            raise ValueError("exact atomic selection count does not match specifications")
        if self.source_materialized_atomic_selection_count != sum(
            spec.source_materialized_atomic_selection_count for spec in self.specifications
        ):
            raise ValueError("source materialized count does not match specifications")
        return self


class CanonicalRuleSemanticRecord(_ContentHashedModel):
    schema_version: Literal["xinao.canonical_rule_semantic_record.v1"] = (
        "xinao.canonical_rule_semantic_record.v1"
    )
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: str
    physical_role: Literal["ACTIVE_SETTLEMENT"] = "ACTIVE_SETTLEMENT"
    source_module: Literal["basic", "sets", "combinations", "linked"]
    source_schema_version: str
    source_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog: CatalogRowBinding
    semantic_family_ref: str
    rule_version_ref: str
    settlement_function_ref: str
    predicate_ref: str
    predicate_parameters: dict[str, Any]
    selection_domain_spec_id: str
    settlement_tiers: tuple[CanonicalSettlementTier, ...] = Field(min_length=2)
    snapshot_payout_binding: str
    quote_components: tuple[str, ...] = Field(min_length=1)
    principal_refund_on_normal_settlement: Literal[False] = False
    void_policy: str
    rounding_policy: str
    boundary_policy: str
    effective_interval: dict[str, Any]
    probability_formula_ref: str
    probability_artifact_status: Literal["FORMULA_REF_ONLY_NOT_F2_COMPILED"] = (
        "FORMULA_REF_ONLY_NOT_F2_COMPILED"
    )
    semantic_evidence_statuses: tuple[str, ...] = Field(min_length=1)
    evidence_basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog_binding(self) -> CanonicalRuleSemanticRecord:
        if self.baseline_id != self.catalog.baseline_id:
            raise ValueError("semantic baseline does not match bound catalog row")
        if self.family_id != self.catalog.family_id:
            raise ValueError("semantic family does not match bound catalog row")
        if self.baseline_id not in ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("catalog-only frozen quote entered ACTIVE semantics")
        if self.quote_components != self.catalog.baseline_odds_components:
            raise ValueError("semantic quote components do not match catalog row")
        tier_roles = {tier.terminal_role for tier in self.settlement_tiers}
        if not {"HIT", "MISS"}.issubset(tier_roles):
            raise ValueError("every semantic must expose HIT and MISS terminal roles")
        if ("VOID" in tier_roles) != (
            self.void_policy != "NO_VOID"
        ) and self.void_policy != "PROPERTY_49_LEG_MULTIPLIER_ONE":
            raise ValueError("ticket VOID tier and void policy disagree")
        return self


class RuleSemanticMapVersion(_ContentHashedModel):
    schema_version: Literal["xinao.rule_semantic_map.v1"] = "xinao.rule_semantic_map.v1"
    map_ref: Literal["xinao-416-active-rule-semantic-map.v1"] = (
        "xinao-416-active-rule-semantic-map.v1"
    )
    source_catalog_ref: str
    active_catalog_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_slice_hashes: dict[str, str]
    semantic_record_count: Literal[416] = 416
    family_counts: dict[str, int]
    records: tuple[CanonicalRuleSemanticRecord, ...]
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_coverage(self) -> RuleSemanticMapVersion:
        if len(self.records) != self.semantic_record_count:
            raise ValueError("semantic record count does not equal 416")
        ids = [record.baseline_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("canonical semantic records contain duplicate baseline ids")
        observed = dict(Counter(record.family_id for record in self.records))
        if observed != self.family_counts:
            raise ValueError("canonical semantic family counts are inconsistent")
        if {record.baseline_id for record in self.records} != ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("canonical active semantic identities drifted")
        return self


class CanonicalRuleBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: str
    physical_role: Literal["ACTIVE_SETTLEMENT"] = "ACTIVE_SETTLEMENT"
    semantic_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version_ref: str
    predicate_ref: str
    selection_domain_spec_id: str
    evidence_basis: tuple[str, ...]


class RuleSetVersion(_ContentHashedModel):
    schema_version: Literal["xinao.rule_set.v1"] = "xinao.rule_set.v1"
    rule_set_ref: Literal["xinao-416-active-rule-set.v1"] = "xinao-416-active-rule-set.v1"
    semantic_map_ref: Literal["xinao-416-active-rule-semantic-map.v1"] = (
        "xinao-416-active-rule-semantic-map.v1"
    )
    semantic_map_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_count: Literal[416] = 416
    rules: tuple[CanonicalRuleBinding, ...]
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_rule_count(self) -> RuleSetVersion:
        if len(self.rules) != self.rule_count:
            raise ValueError("rule set must bind exactly 416 ACTIVE component rows")
        if len({rule.baseline_id for rule in self.rules}) != self.rule_count:
            raise ValueError("rule set baseline ids are not unique")
        if {rule.baseline_id for rule in self.rules} != ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("rule set contains a catalog-only frozen route quote")
        return self


class CanonicalSettlementFunctionBinding(_FrozenModel):
    baseline_id: str = Field(pattern=r"^BO\d{4}$")
    family_id: str
    semantic_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    settlement_function_ref: str
    settlement_tiers: tuple[CanonicalSettlementTier, ...]
    void_policy: str
    quote_components: tuple[str, ...]
    snapshot_payout_binding: str
    principal_refund_on_normal_settlement: Literal[False] = False
    probability_artifact_status: Literal["FORMULA_REF_ONLY_NOT_F2_COMPILED"] = (
        "FORMULA_REF_ONLY_NOT_F2_COMPILED"
    )


class SettlementFunctionSetVersion(_ContentHashedModel):
    schema_version: Literal["xinao.settlement_function_set.v1"] = "xinao.settlement_function_set.v1"
    function_set_ref: Literal["xinao-416-active-settlement-function-set.v1"] = (
        "xinao-416-active-settlement-function-set.v1"
    )
    rule_set_ref: Literal["xinao-416-active-rule-set.v1"] = "xinao-416-active-rule-set.v1"
    rule_set_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    function_count: Literal[416] = 416
    bindings: tuple[CanonicalSettlementFunctionBinding, ...]
    probability_artifacts_compiled: Literal[False] = False
    foundation_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_binding_count(self) -> SettlementFunctionSetVersion:
        if len(self.bindings) != self.function_count:
            raise ValueError("settlement function set must contain 416 active functions")
        if len({binding.baseline_id for binding in self.bindings}) != 416:
            raise ValueError("settlement function bindings contain duplicate baseline ids")
        if {binding.baseline_id for binding in self.bindings} != ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError(
                "settlement function set contains a frozen route quote or misses an active row"
            )
        return self


@dataclass(frozen=True, slots=True)
class SourceSemanticArtifacts:
    """The unmodified strict results produced by each bounded compiler."""

    basic_records: tuple[BasicRuleSemanticRecord, ...]
    set_compilation: SetFamilySemanticsCompilation
    combination_records: tuple[CombinationSemanticRecord, ...]
    linked_compilation: LinkedSemanticsCompilation


@dataclass(frozen=True, slots=True)
class FoundationSemanticsRegistry:
    """Source artifacts plus four canonical, content-addressed projections."""

    source_artifacts: SourceSemanticArtifacts
    rule_semantic_map: RuleSemanticMapVersion
    expected_selection_domain: ExpectedSelectionDomainManifestVersion
    rule_set: RuleSetVersion
    settlement_function_set: SettlementFunctionSetVersion
    active_physical_semantics_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        expected = canonical_sha256(
            {
                "schema_version": "xinao.foundation_semantics_registry.v1",
                "active_physical_semantics_hash": self.active_physical_semantics_hash,
                "rule_semantic_map_hash": self.rule_semantic_map.content_hash,
                "expected_selection_domain_hash": self.expected_selection_domain.content_hash,
                "rule_set_hash": self.rule_set.content_hash,
                "settlement_function_set_hash": self.settlement_function_set.content_hash,
            }
        )
        if self.content_hash != expected:
            raise ValueError("registry content_hash does not bind canonical artifacts")
        active_record_hashes = [record.content_hash for record in self.rule_semantic_map.records]
        active_spec_hashes = [
            spec.content_hash for spec in self.expected_selection_domain.specifications
        ]
        observed_active_hash = canonical_sha256(
            {
                "schema_version": "xinao.active_physical_semantics.v1",
                "active_record_hashes": active_record_hashes,
                "active_selection_domain_spec_hashes": active_spec_hashes,
                "settlement_function_set_hash": self.settlement_function_set.content_hash,
            }
        )
        if observed_active_hash != self.active_physical_semantics_hash:
            raise ValueError("active physical semantics hash drifted")


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    # ``model_construct`` applies declared defaults without running the hash
    # validator.  Hashing that fully materialised body avoids the subtle bug
    # where an omitted default (for example ``schema_version``) appears only
    # after validation and therefore changes the canonical payload.
    draft = model.model_construct(**dict(payload), content_hash="0" * 64)
    body = draft.model_dump(mode="json", exclude={"content_hash"})
    body["content_hash"] = canonical_sha256(body)
    return model.model_validate(body)


def load_play_catalog(path: Path = DEFAULT_PLAY_CATALOG_PATH) -> dict[str, Any]:
    raw = load_snapshot_object(path)
    if not isinstance(raw, dict):
        raise ValueError("play catalog must be a JSON object")
    return raw


def _catalog_row(row: Mapping[str, Any]) -> CatalogRowBinding:
    payload = dict(row)
    payload["content_hash"] = canonical_sha256(payload)
    return CatalogRowBinding.model_validate(payload)


def _normalize_catalog(
    catalog: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, CatalogRowBinding]]:
    if catalog.get("schema_version") != "xinao.play_catalog.v1":
        raise ValueError("unsupported play catalog schema_version")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise TypeError("play catalog entries must be a list")
    if catalog.get("entry_count") != EXPECTED_CATALOG_ROWS or len(entries) != EXPECTED_CATALOG_ROWS:
        raise ValueError("formal play catalog must contain exactly 433 rows")
    if any(not isinstance(row, Mapping) for row in entries):
        raise TypeError("every play catalog entry must be an object")

    raw_rows = [dict(row) for row in entries]
    baseline_ids = [row.get("baseline_id") for row in raw_rows]
    if any(
        not isinstance(value, str) or not _BASELINE_PATTERN.fullmatch(value)
        for value in baseline_ids
    ):
        raise ValueError("every catalog row must have a BO plus four-digit baseline id")
    if len(baseline_ids) != len(set(baseline_ids)):
        raise ValueError("play catalog contains duplicate baseline ids")

    family_ids = [row.get("family_id") for row in raw_rows]
    unknown = sorted({str(value) for value in family_ids if value not in EXPECTED_FAMILY_IDS})
    if unknown:
        raise ValueError(f"play catalog contains unknown families: {unknown}")
    observed_counts = dict(Counter(str(value) for value in family_ids))
    if observed_counts != EXPECTED_FAMILY_COUNTS:
        raise ValueError(
            f"play catalog family coverage drifted: expected={EXPECTED_FAMILY_COUNTS}, "
            f"observed={observed_counts}"
        )

    ordered_rows = sorted(raw_rows, key=lambda row: row["baseline_id"])
    normalized = {
        key: value for key, value in catalog.items() if key not in {"entries", "content_hash"}
    }
    normalized["entries"] = ordered_rows
    expected_hash = canonical_sha256(normalized)
    content_hash = catalog.get("content_hash")
    if not isinstance(content_hash, str) or not _HASH_PATTERN.fullmatch(content_hash):
        raise ValueError("play catalog content_hash is missing or malformed")
    if expected_hash != content_hash:
        raise ValueError("play catalog content_hash does not bind normalized catalog content")
    normalized["content_hash"] = content_hash

    typed_rows = tuple(_catalog_row(row) for row in ordered_rows)
    by_id = {row.baseline_id: row for row in typed_rows}
    if len(by_id) != EXPECTED_CATALOG_ROWS:
        raise ValueError("typed catalog projection lost or duplicated a baseline")
    return normalized, by_id


def _claim_nodes(value: Any) -> Iterable[Any]:
    """Walk source artifacts without relying on one modelling library."""

    if isinstance(value, BaseModel):
        yield from _claim_nodes(value.model_dump(mode="python"))
        return
    if isinstance(value, Mapping):
        if value.get("foundation_complete") is True:
            yield value
        for child in value.values():
            yield from _claim_nodes(child)
        return
    if is_dataclass(value) and not isinstance(value, type):
        yield from _claim_nodes(asdict(value))
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _claim_nodes(child)


def assert_bounded_source_claims(*artifacts: Any) -> None:
    """Reject any bounded source slice that claims the whole Foundation is complete."""

    if any(True for artifact in artifacts for _ in _claim_nodes(artifact)):
        raise ValueError("bounded semantics module cannot claim foundation_complete=true")


def _row_json(row: CatalogRowBinding) -> dict[str, Any]:
    return row.model_dump(mode="json", exclude={"content_hash"})


def _domain_spec(payload: Mapping[str, Any]) -> CanonicalSelectionDomainSpec:
    return _with_hash(CanonicalSelectionDomainSpec, payload)


def _basic_domain_specs(
    records: Sequence[BasicRuleSemanticRecord],
) -> tuple[CanonicalSelectionDomainSpec, ...]:
    specs = []
    for record in records:
        source_payload = {
            "baseline_id": record.baseline_id,
            "selection_space": record.selection_space,
            "selection_space_source": record.selection_space_source,
        }
        specs.append(
            _domain_spec(
                {
                    "spec_id": f"selection-domain:basic:{record.baseline_id}",
                    "family_id": record.family_id,
                    "play_id": record.play_id,
                    "component_baseline_ids": (record.baseline_id,),
                    "domain_kind": "FINITE_CATALOG_OPTION_SELECTION",
                    "arity_min": 1,
                    "arity_max": 1,
                    "exact_atomic_selection_count": len(record.selection_space),
                    "expansion_policy": "FINITE_SOURCE_DOMAIN_DESCRIPTOR",
                    "canonical_manifest_materialized_atomic_selection_count": 0,
                    "source_materialized_atomic_selection_count": len(record.selection_space),
                    "canonical_encoding": "source-canonical-option-string",
                    "constraint_ref": record.predicate_ref,
                    "source_domain_ref": record.selection_space_source,
                    "source_domain_hash": canonical_sha256(source_payload),
                    "evidence_basis": record.evidence_refs,
                }
            )
        )
    return tuple(specs)


def _set_domain_specs(
    compilation: SetFamilySemanticsCompilation,
) -> tuple[CanonicalSelectionDomainSpec, ...]:
    entries_by_baseline: dict[str, list[Any]] = defaultdict(list)
    for entry in compilation.expected_selection_domain.entries:
        entries_by_baseline[entry.baseline_id].append(entry)
    specs = []
    for record in compilation.rule_semantic_map.records:
        entries = sorted(
            entries_by_baseline[record.baseline_id], key=lambda item: item.selection_key
        )
        if not entries:
            raise ValueError(f"set-family selection domain is missing {record.baseline_id}")
        arities = {len(entry.selected_values) for entry in entries}
        if len(arities) != 1:
            raise ValueError(f"set-family selection arity drifted for {record.baseline_id}")
        arity = next(iter(arities))
        source_payload = [entry.model_dump(mode="json") for entry in entries]
        specs.append(
            _domain_spec(
                {
                    "spec_id": f"selection-domain:sets:{record.baseline_id}",
                    "family_id": record.family_id,
                    "play_id": str(record.raw_site_fields["play_id"]),
                    "component_baseline_ids": (record.baseline_id,),
                    "domain_kind": (
                        "DISTINCT_ZODIAC_LABEL_COMBINATION"
                        if record.family_id == "six-zodiac"
                        else "FINITE_CATALOG_OPTION_SELECTION"
                    ),
                    "arity_min": arity,
                    "arity_max": arity,
                    "exact_atomic_selection_count": len(entries),
                    "expansion_policy": "FINITE_SOURCE_DOMAIN_DESCRIPTOR",
                    "canonical_manifest_materialized_atomic_selection_count": 0,
                    "source_materialized_atomic_selection_count": len(entries),
                    "canonical_encoding": "source-selection-key",
                    "constraint_ref": record.interpretation_ref,
                    "source_domain_ref": record.selection_domain_ref,
                    "source_domain_hash": canonical_sha256(source_payload),
                    "evidence_basis": record.source_refs,
                }
            )
        )
    if set(entries_by_baseline) != {
        record.baseline_id for record in compilation.rule_semantic_map.records
    }:
        raise ValueError("set-family selection domain contains unknown baselines")
    return tuple(specs)


def _combination_domain_specs(
    records: Sequence[CombinationSemanticRecord],
) -> tuple[CanonicalSelectionDomainSpec, ...]:
    specs = []
    for record in records:
        domain = record.selection_domain
        domain_payload = asdict(domain)
        specs.append(
            _domain_spec(
                {
                    "spec_id": f"selection-domain:combinations:{record.baseline_id}",
                    "family_id": record.family_id,
                    "play_id": record.play_id,
                    "component_baseline_ids": (record.baseline_id,),
                    "domain_kind": domain.kind,
                    "arity_min": domain.arity,
                    "arity_max": domain.arity,
                    "exact_atomic_selection_count": domain.atomic_selection_count,
                    "expansion_policy": "LAZY_COMBINATORIAL",
                    "canonical_manifest_materialized_atomic_selection_count": 0,
                    "source_materialized_atomic_selection_count": 0,
                    "canonical_encoding": domain.canonical_encoding,
                    "constraint_ref": record.atomic_expansion_rule,
                    "source_domain_ref": f"combination-domain:{record.baseline_id}",
                    "source_domain_hash": canonical_sha256(domain_payload),
                    "evidence_basis": record.semantic_basis,
                }
            )
        )
    return tuple(specs)


def _linked_domain_specs(
    compilation: LinkedSemanticsCompilation,
) -> tuple[CanonicalSelectionDomainSpec, ...]:
    specs = []
    for source in compilation.expected_selection_domain.specifications:
        specs.append(
            _domain_spec(
                {
                    "spec_id": source.spec_id,
                    "family_id": source.family_id,
                    "play_id": source.play_id,
                    "component_baseline_ids": source.component_baseline_ids,
                    "domain_kind": source.atomic_selection_kind,
                    "arity_min": source.arity_min,
                    "arity_max": source.arity_max,
                    "exact_atomic_selection_count": source.exact_atomic_selection_count,
                    "expansion_policy": source.expansion_policy,
                    "canonical_manifest_materialized_atomic_selection_count": 0,
                    "source_materialized_atomic_selection_count": (
                        source.materialized_atomic_selection_count
                    ),
                    "canonical_encoding": "source-selection-key",
                    "constraint_ref": source.constraint_ref,
                    "source_domain_ref": compilation.expected_selection_domain.domain_ref,
                    "source_domain_hash": source.content_hash,
                    "evidence_basis": (
                        source.interpretation_ref,
                        *source.alternative_interpretation_refs,
                    ),
                }
            )
        )
    return tuple(specs)


def _selection_spec_index(
    specifications: Sequence[CanonicalSelectionDomainSpec],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for spec in specifications:
        for baseline_id in spec.component_baseline_ids:
            if baseline_id in result:
                raise ValueError(f"selection-domain overlap for {baseline_id}")
            result[baseline_id] = spec.spec_id
    return result


def _tier(
    tier_id: str,
    terminal_role: Literal["HIT", "MISS", "VOID"],
    predicate_ref: str,
    payout_kind: Literal["QUOTE_COMPONENT", "QUOTE_AGGREGATION", "ZERO", "REFUND_STAKE"],
    payout_component_index: int | None = None,
) -> CanonicalSettlementTier:
    return CanonicalSettlementTier(
        tier_id=tier_id,
        terminal_role=terminal_role,
        predicate_ref=predicate_ref,
        payout_kind=payout_kind,
        payout_component_index=payout_component_index,
    )


def _semantic_record(payload: Mapping[str, Any]) -> CanonicalRuleSemanticRecord:
    body = dict(payload)
    baseline_id = str(body["baseline_id"])
    if baseline_id not in ACTIVE_SETTLEMENT_BASELINE_IDS:
        raise ValueError(f"catalog-only frozen quote cannot compile semantics: {baseline_id}")
    body["physical_role"] = "ACTIVE_SETTLEMENT"
    return _with_hash(CanonicalRuleSemanticRecord, body)


def _basic_records(
    records: Sequence[BasicRuleSemanticRecord],
    rows: Mapping[str, CatalogRowBinding],
    domain_index: Mapping[str, str],
) -> tuple[CanonicalRuleSemanticRecord, ...]:
    result = []
    for source in records:
        row = rows[source.baseline_id]
        source_hash = canonical_sha256(source.model_dump(mode="json"))
        tiers = tuple(
            _tier(
                tier.tier_id,
                tier.tier_id,
                (
                    source.predicate_ref
                    if tier.tier_id == "HIT"
                    else f"{source.rule_version_ref}#{tier.tier_id}"
                ),
                tier.payout_kind,
                tier.payout_component_index,
            )
            for tier in source.terminal_tiers
        )
        result.append(
            _semantic_record(
                {
                    "baseline_id": source.baseline_id,
                    "family_id": source.family_id,
                    "source_module": "basic",
                    "source_schema_version": source.schema_version,
                    "source_record_hash": source_hash,
                    "catalog": row,
                    "semantic_family_ref": source.semantic_family,
                    "rule_version_ref": source.rule_version_ref,
                    "settlement_function_ref": f"settle-basic-{source.semantic_family}.v1",
                    "predicate_ref": source.predicate_ref,
                    "predicate_parameters": {
                        "draw_anchor": source.draw_anchor,
                        "position": source.position,
                    },
                    "selection_domain_spec_id": domain_index[source.baseline_id],
                    "settlement_tiers": tiers,
                    "snapshot_payout_binding": "HIT_PAYS_BOUND_QUOTE_COMPONENT_INCLUDING_STAKE",
                    "quote_components": source.snapshot_payout_components,
                    "principal_refund_on_normal_settlement": False,
                    "void_policy": source.void_policy,
                    "rounding_policy": source.rounding_policy,
                    "boundary_policy": source.boundary_policy,
                    "effective_interval": source.effective.model_dump(mode="json"),
                    "probability_formula_ref": source.probability_formula_ref,
                    "semantic_evidence_statuses": source.semantic_status,
                    "evidence_basis": source.evidence_refs,
                }
            )
        )
    return tuple(result)


def _set_records(
    compilation: SetFamilySemanticsCompilation,
    rows: Mapping[str, CatalogRowBinding],
    domain_index: Mapping[str, str],
) -> tuple[CanonicalRuleSemanticRecord, ...]:
    result = []
    for source in compilation.rule_semantic_map.records:
        row = rows[source.baseline_id]
        if source.raw_site_fields != _row_json(row):
            raise ValueError(f"set-family raw catalog binding drifted for {source.baseline_id}")
        tiers = []
        for tier_id in source.settlement_tiers:
            if tier_id == "HIT":
                tiers.append(
                    _tier(
                        "HIT",
                        "HIT",
                        f"{source.settlement_function_ref}#HIT",
                        "QUOTE_COMPONENT",
                        0,
                    )
                )
            elif tier_id == "MISS":
                tiers.append(
                    _tier("MISS", "MISS", f"{source.settlement_function_ref}#MISS", "ZERO")
                )
            else:
                tiers.append(
                    _tier(
                        "VOID",
                        "VOID",
                        f"{source.settlement_function_ref}#VOID",
                        "REFUND_STAKE",
                    )
                )
        void_policy = (
            "SOURCE_INTERPRETATION_VOID_REFUND_STAKE"
            if "VOID" in source.settlement_tiers
            else "NO_VOID"
        )
        result.append(
            _semantic_record(
                {
                    "baseline_id": source.baseline_id,
                    "family_id": source.family_id,
                    "source_module": "sets",
                    "source_schema_version": source.schema_version,
                    "source_record_hash": source.content_hash,
                    "catalog": row,
                    "semantic_family_ref": source.semantic_family_ref,
                    "rule_version_ref": source.rule_version_ref,
                    "settlement_function_ref": source.settlement_function_ref,
                    "predicate_ref": source.settlement_function_ref,
                    "predicate_parameters": source.semantic_parameters,
                    "selection_domain_spec_id": domain_index[source.baseline_id],
                    "settlement_tiers": tuple(tiers),
                    "snapshot_payout_binding": "HIT_PAYS_BOUND_QUOTE_COMPONENT_INCLUDING_STAKE",
                    "quote_components": row.baseline_odds_components,
                    "principal_refund_on_normal_settlement": False,
                    "void_policy": void_policy,
                    "rounding_policy": "NO_PREDICATE_ROUNDING_QUOTE_DECIMAL_PRESERVED",
                    "boundary_policy": source.interpretation_ref,
                    "effective_interval": {
                        "source_snapshot_ref": "xinao-target-market-page-snapshot.2026-05-12.v1"
                    },
                    "probability_formula_ref": source.probability_formula_ref,
                    "semantic_evidence_statuses": source.semantic_evidence_statuses,
                    "evidence_basis": source.source_refs,
                }
            )
        )
    return tuple(result)


def _combination_records(
    records: Sequence[CombinationSemanticRecord],
    rows: Mapping[str, CatalogRowBinding],
    domain_index: Mapping[str, str],
) -> tuple[CanonicalRuleSemanticRecord, ...]:
    result = []
    for source in records:
        row = rows[source.baseline_id]
        source_hash = canonical_sha256(source.canonical_dict())
        tiers = [
            _tier(
                tier.tier_id,
                "HIT",
                tier.predicate,
                "QUOTE_COMPONENT",
                tier.payout_component_index,
            )
            for tier in source.paying_tiers
        ]
        tiers.append(
            _tier(
                "MISS",
                "MISS",
                f"not-any-paying-tier:{source.semantic_kind}",
                "ZERO",
            )
        )
        result.append(
            _semantic_record(
                {
                    "baseline_id": source.baseline_id,
                    "family_id": source.family_id,
                    "source_module": "combinations",
                    "source_schema_version": "xinao.combination_semantic_record.v1",
                    "source_record_hash": source_hash,
                    "catalog": row,
                    "semantic_family_ref": source.semantic_kind,
                    "rule_version_ref": f"combination-rule:{source.semantic_kind}.v1",
                    "settlement_function_ref": f"settle-combination:{source.semantic_kind}.v1",
                    "predicate_ref": f"combination-predicate:{source.semantic_kind}.v1",
                    "predicate_parameters": {
                        "target_set": source.target_set,
                        "tier_order_basis": source.tier_order_basis,
                        "atomic_expansion_rule": source.atomic_expansion_rule,
                    },
                    "selection_domain_spec_id": domain_index[source.baseline_id],
                    "settlement_tiers": tuple(tiers),
                    "snapshot_payout_binding": (
                        "PAYING_TIER_INDEX_BINDS_CATALOG_QUOTE_INCLUDING_STAKE"
                    ),
                    "quote_components": source.quote_components,
                    "principal_refund_on_normal_settlement": False,
                    "void_policy": "NO_VOID",
                    "rounding_policy": "NO_PREDICATE_ROUNDING_QUOTE_DECIMAL_PRESERVED",
                    "boundary_policy": source.atomic_expansion_rule,
                    "effective_interval": {
                        "source_snapshot_ref": "xinao-target-market-page-snapshot.2026-05-12.v1"
                    },
                    "probability_formula_ref": source.probability_formula_ref,
                    "semantic_evidence_statuses": (
                        "EXPLICIT_PAGE",
                        "RESEARCH_CONVENTION",
                    ),
                    "evidence_basis": source.semantic_basis,
                }
            )
        )
    return tuple(result)


def _linked_records(
    compilation: LinkedSemanticsCompilation,
    rows: Mapping[str, CatalogRowBinding],
    domain_index: Mapping[str, str],
) -> tuple[CanonicalRuleSemanticRecord, ...]:
    result = []
    for source in compilation.rule_semantic_map.records:
        row = rows[source.baseline_id]
        if source.raw_site_fields != _row_json(row):
            raise ValueError(f"linked/parlay raw catalog binding drifted for {source.baseline_id}")
        result.append(
            _semantic_record(
                {
                    "baseline_id": source.baseline_id,
                    "family_id": source.family_id,
                    "source_module": "linked",
                    "source_schema_version": source.schema_version,
                    "source_record_hash": source.content_hash,
                    "catalog": row,
                    "semantic_family_ref": source.semantic_family_ref,
                    "rule_version_ref": source.rule_version_ref,
                    "settlement_function_ref": source.settlement_function_ref,
                    "predicate_ref": f"{source.settlement_function_ref}#{source.polarity}",
                    "predicate_parameters": {
                        "draw_scope": source.draw_scope,
                        "polarity": source.polarity,
                        "component_label": source.component_label,
                        "component_position": source.component_position,
                        "component_attribute": source.component_attribute,
                        "catalog_number_set_snapshot": source.catalog_number_set_snapshot,
                        "quote_aggregation_ref": source.quote_aggregation_ref,
                    },
                    "selection_domain_spec_id": domain_index[source.baseline_id],
                    "settlement_tiers": (
                        _tier(
                            "HIT",
                            "HIT",
                            f"{source.settlement_function_ref}#HIT",
                            "QUOTE_AGGREGATION",
                        ),
                        _tier(
                            "MISS",
                            "MISS",
                            f"{source.settlement_function_ref}#MISS",
                            "ZERO",
                        ),
                    ),
                    "snapshot_payout_binding": (
                        f"{source.quote_aggregation_ref}:PAYOUT_INCLUDES_STAKE"
                    ),
                    "quote_components": source.snapshot_payout_components,
                    "principal_refund_on_normal_settlement": False,
                    "void_policy": source.void_policy,
                    "rounding_policy": "NO_PREDICATE_ROUNDING_QUOTE_DECIMAL_PRESERVED",
                    "boundary_policy": source.interpretation_ref,
                    "effective_interval": {
                        "source_snapshot_ref": "xinao-target-market-page-snapshot.2026-05-12.v1"
                    },
                    "probability_formula_ref": source.probability_formula_ref,
                    "semantic_evidence_statuses": source.semantic_evidence_statuses,
                    "evidence_basis": (*source.assumption_refs, *source.source_refs),
                }
            )
        )
    return tuple(result)


def _validate_source_partition(
    catalog_rows: Mapping[str, CatalogRowBinding],
    source_records: Mapping[str, Any],
) -> None:
    expected_ids = set(catalog_rows)
    actual_ids = set(source_records)
    if expected_ids != actual_ids:
        raise ValueError(
            "source semantic coverage is not exact: "
            f"missing={sorted(expected_ids - actual_ids)}, "
            f"unexpected={sorted(actual_ids - expected_ids)}"
        )
    for baseline_id, source in source_records.items():
        if getattr(source, "family_id", None) != catalog_rows[baseline_id].family_id:
            raise ValueError(f"source semantic family drifted for {baseline_id}")


def compile_semantics_registry(
    catalog: Mapping[str, Any],
) -> FoundationSemanticsRegistry:
    """Compile and strictly aggregate all four bounded family slices in memory."""

    normalized_catalog, catalog_rows = _normalize_catalog(catalog)
    entries = normalized_catalog["entries"]

    active_catalog_rows = {
        baseline_id: row
        for baseline_id, row in catalog_rows.items()
        if baseline_id in ACTIVE_SETTLEMENT_BASELINE_IDS
    }
    basic = compile_basic_semantics(
        row
        for row in entries
        if row["family_id"] in _BASIC_FAMILIES
        and row["baseline_id"] in ACTIVE_SETTLEMENT_BASELINE_IDS
    )
    sets = compile_set_family_semantics(normalized_catalog)
    combinations = compile_combination_catalog(normalized_catalog)
    linked = compile_linked_semantics(normalized_catalog)
    assert_bounded_source_claims(basic, sets, combinations, linked)

    source_record_sequence: tuple[Any, ...] = (
        *basic,
        *sets.rule_semantic_map.records,
        *combinations,
        *linked.rule_semantic_map.records,
    )
    source_ids = [record.baseline_id for record in source_record_sequence]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("bounded semantics modules overlap baseline ids")
    source_record_map = {record.baseline_id: record for record in source_record_sequence}
    _validate_source_partition(active_catalog_rows, source_record_map)

    specifications = tuple(
        sorted(
            (
                *_basic_domain_specs(basic),
                *_set_domain_specs(sets),
                *_combination_domain_specs(combinations),
                *_linked_domain_specs(linked),
            ),
            key=lambda spec: spec.spec_id,
        )
    )
    domain_index = _selection_spec_index(specifications)
    if set(domain_index) != ACTIVE_SETTLEMENT_BASELINE_IDS:
        raise ValueError("canonical selection domain does not cover 416 ACTIVE rows")

    canonical_records = tuple(
        sorted(
            (
                *_basic_records(basic, catalog_rows, domain_index),
                *_set_records(sets, catalog_rows, domain_index),
                *_combination_records(combinations, catalog_rows, domain_index),
                *_linked_records(linked, catalog_rows, domain_index),
            ),
            key=lambda record: record.baseline_id,
        )
    )
    canonical_ids = [record.baseline_id for record in canonical_records]
    if canonical_ids != sorted(ACTIVE_SETTLEMENT_BASELINE_IDS):
        raise ValueError("canonical records do not provide exact sorted 416-row coverage")

    source_slice_hashes = {
        "basic": basic_records_hash(basic),
        "sets": canonical_sha256(
            [record.model_dump(mode="json") for record in sets.rule_semantic_map.records]
        ),
        "combinations": combination_records_hash(combinations),
        "linked": canonical_sha256(
            [record.model_dump(mode="json") for record in linked.rule_semantic_map.records]
        ),
    }
    source_catalog_ref = str(normalized_catalog.get("catalog_ref") or "play-catalog.v1")
    active_projection_hash = active_catalog_projection_hash(normalized_catalog)
    semantic_map = _with_hash(
        RuleSemanticMapVersion,
        {
            "source_catalog_ref": source_catalog_ref,
            "active_catalog_projection_hash": active_projection_hash,
            "source_slice_hashes": source_slice_hashes,
            "semantic_record_count": 416,
            "family_counts": EXPECTED_ACTIVE_FAMILY_COUNTS,
            "records": canonical_records,
            "foundation_complete": False,
        },
    )
    manifest = _with_hash(
        ExpectedSelectionDomainManifestVersion,
        {
            "source_catalog_ref": source_catalog_ref,
            "active_catalog_projection_hash": active_projection_hash,
            "component_catalog_row_count": 416,
            "selection_domain_spec_count": len(specifications),
            "exact_atomic_selection_count": EXPECTED_ACTIVE_ATOMIC_SELECTION_COUNT,
            "canonical_materialized_atomic_selection_count": 0,
            "source_materialized_atomic_selection_count": sum(
                spec.source_materialized_atomic_selection_count for spec in specifications
            ),
            "specifications": specifications,
            "foundation_complete": False,
        },
    )
    rules = tuple(
        CanonicalRuleBinding(
            baseline_id=record.baseline_id,
            family_id=record.family_id,
            physical_role=record.physical_role,
            semantic_record_hash=record.content_hash,
            rule_version_ref=record.rule_version_ref,
            predicate_ref=record.predicate_ref,
            selection_domain_spec_id=record.selection_domain_spec_id,
            evidence_basis=record.evidence_basis,
        )
        for record in canonical_records
    )
    rule_set = _with_hash(
        RuleSetVersion,
        {
            "semantic_map_content_hash": semantic_map.content_hash,
            "rule_count": 416,
            "rules": rules,
            "foundation_complete": False,
        },
    )
    bindings = tuple(
        CanonicalSettlementFunctionBinding(
            baseline_id=record.baseline_id,
            family_id=record.family_id,
            semantic_record_hash=record.content_hash,
            settlement_function_ref=record.settlement_function_ref,
            settlement_tiers=record.settlement_tiers,
            void_policy=record.void_policy,
            quote_components=record.quote_components,
            snapshot_payout_binding=record.snapshot_payout_binding,
            principal_refund_on_normal_settlement=False,
        )
        for record in canonical_records
    )
    function_set = _with_hash(
        SettlementFunctionSetVersion,
        {
            "rule_set_content_hash": rule_set.content_hash,
            "function_count": 416,
            "bindings": bindings,
            "probability_artifacts_compiled": False,
            "foundation_complete": False,
        },
    )
    active_physical_semantics_hash = canonical_sha256(
        {
            "schema_version": "xinao.active_physical_semantics.v1",
            "active_record_hashes": [record.content_hash for record in canonical_records],
            "active_selection_domain_spec_hashes": [spec.content_hash for spec in specifications],
            "settlement_function_set_hash": function_set.content_hash,
        }
    )
    registry_hash = canonical_sha256(
        {
            "schema_version": "xinao.foundation_semantics_registry.v1",
            "active_physical_semantics_hash": active_physical_semantics_hash,
            "rule_semantic_map_hash": semantic_map.content_hash,
            "expected_selection_domain_hash": manifest.content_hash,
            "rule_set_hash": rule_set.content_hash,
            "settlement_function_set_hash": function_set.content_hash,
        }
    )
    return FoundationSemanticsRegistry(
        source_artifacts=SourceSemanticArtifacts(
            basic_records=basic,
            set_compilation=sets,
            combination_records=combinations,
            linked_compilation=linked,
        ),
        rule_semantic_map=semantic_map,
        expected_selection_domain=manifest,
        rule_set=rule_set,
        settlement_function_set=function_set,
        active_physical_semantics_hash=active_physical_semantics_hash,
        content_hash=registry_hash,
    )


def compile_default_semantics_registry(
    path: Path = DEFAULT_PLAY_CATALOG_PATH,
) -> FoundationSemanticsRegistry:
    return compile_semantics_registry(load_play_catalog(path))


__all__ = [
    "DEFAULT_PLAY_CATALOG_PATH",
    "EXPECTED_ACTIVE_FAMILY_COUNTS",
    "EXPECTED_FAMILY_COUNTS",
    "CanonicalRuleSemanticRecord",
    "CanonicalSelectionDomainSpec",
    "ExpectedSelectionDomainManifestVersion",
    "FoundationSemanticsRegistry",
    "RuleSemanticMapVersion",
    "RuleSetVersion",
    "SettlementFunctionSetVersion",
    "SourceSemanticArtifacts",
    "assert_bounded_source_claims",
    "compile_default_semantics_registry",
    "compile_semantics_registry",
    "load_play_catalog",
]
