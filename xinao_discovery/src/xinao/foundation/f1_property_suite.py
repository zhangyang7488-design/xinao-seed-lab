"""Execute content-addressed F1 property evidence with independent oracles."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256, ordered_json_stream_sha256
from xinao.foundation.f1_property_oracles import (
    Outcome,
    basic_outcome,
    combination_outcome,
    linked_outcome,
    parlay_outcome,
    set_outcome,
)
from xinao.foundation.f1_replay import (
    CASE_KIND_ORDER,
    FAMILY_ORDER,
    F1RepresentativeReplayEvidence,
)
from xinao.foundation.selection_manifest import (
    ZODIAC_ORDER,
    AtomicTicketBindingDescriptor,
    AtomicTicketBindingVersion,
    AtomicTicketSelection,
    IndependentExpectedSelectionDomainManifestVersion,
    assert_registry_manifest_matches,
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    iter_atomic_ticket_selections,
)
from xinao.foundation.semantics_basic import settle_basic_record
from xinao.foundation.semantics_combinations import settle_combination
from xinao.foundation.semantics_linked import settle_linked_ticket, settle_parlay_ticket
from xinao.foundation.semantics_registry import FoundationSemanticsRegistry
from xinao.foundation.semantics_sets import settle_rule
from xinao.foundation.world_compile import DrawReplayInput, WorldSnapshot

HYPOTHESIS_VERSION = "6.156.6"
MAX_EXAMPLES_PER_CHECK = 64


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ContentHashedModel(_FrozenModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_content_hash(self) -> _ContentHashedModel:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if canonical_sha256(payload) != self.content_hash:
            raise ValueError("content_hash does not bind canonical F1 property evidence")
        return self


class F1PropertyCheckEvidence(_ContentHashedModel):
    schema_version: Literal["xinao.f1_property_check_evidence.v1"] = (
        "xinao.f1_property_check_evidence.v1"
    )
    property_id: str = Field(pattern=r"^f1-property:[a-z-]+:(positive|negative|boundary):v1$")
    family_id: str
    property_kind: Literal["POSITIVE", "NEGATIVE", "BOUNDARY"]
    seed_replay_case_id: str
    seed_replay_case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_draw_id: str
    seed_oracle_outcome: Outcome
    generation_seed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_examples: Literal[64] = 64
    generated_draw_example_count: int = Field(ge=64)
    explicit_seed_example_count: Literal[1] = 1
    settlement_evaluation_count: int = Field(gt=0)
    pass_count: int = Field(gt=0)
    failure_count: Literal[0] = 0
    covered_baseline_ids: tuple[str, ...] = Field(min_length=1)
    covered_semantic_family_refs: tuple[str, ...] = Field(min_length=1)
    covered_settlement_function_refs: tuple[str, ...] = Field(min_length=1)
    covered_atomic_binding_ids: tuple[str, ...] = ()
    observed_outcome_counts: dict[str, int]
    ordered_trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_status: Literal["VERIFIED"] = "VERIFIED"

    @model_validator(mode="after")
    def verify_check_accounting(self) -> F1PropertyCheckEvidence:
        if self.pass_count != self.settlement_evaluation_count:
            raise ValueError("F1 property pass count does not cover every settlement evaluation")
        if sum(self.observed_outcome_counts.values()) != self.settlement_evaluation_count:
            raise ValueError("F1 property outcome counts do not cover every settlement evaluation")
        if self.property_kind == "POSITIVE" and self.seed_oracle_outcome != "HIT":
            raise ValueError("positive F1 property seed is not an independent HIT")
        if self.property_kind == "NEGATIVE" and self.seed_oracle_outcome != "MISS":
            raise ValueError("negative F1 property seed is not an independent MISS")
        for values in (
            self.covered_baseline_ids,
            self.covered_semantic_family_refs,
            self.covered_settlement_function_refs,
            self.covered_atomic_binding_ids,
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError("F1 property coverage identities must be sorted and unique")
        return self


class F1PropertySuiteEvidence(_ContentHashedModel):
    schema_version: Literal["xinao.f1_property_suite_evidence.v1"] = (
        "xinao.f1_property_suite_evidence.v1"
    )
    evidence_ref: Literal["f1-properties.all-13.independent-oracle.hypothesis.v1"] = (
        "f1-properties.all-13.independent-oracle.hypothesis.v1"
    )
    hypothesis_version: Literal["6.156.6"] = "6.156.6"
    hypothesis_settings: dict[str, Any]
    source_hashes: dict[str, str]
    active_catalog_projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    active_semantics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_semantic_map_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    settlement_function_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    atomic_ticket_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_semantic_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ordered_draw_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    representative_replay_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_count: Literal[13] = 13
    property_check_count: Literal[39] = 39
    property_kind_counts: dict[str, int]
    active_component_count: Literal[416] = 416
    semantic_family_ref_count: Literal[30] = 30
    settlement_function_ref_count: Literal[32] = 32
    atomic_ticket_binding_count: Literal[37] = 37
    covered_baseline_ids: tuple[str, ...] = Field(min_length=416, max_length=416)
    covered_semantic_family_refs: tuple[str, ...] = Field(min_length=30, max_length=30)
    covered_settlement_function_refs: tuple[str, ...] = Field(min_length=32, max_length=32)
    covered_atomic_binding_ids: tuple[str, ...] = Field(min_length=37, max_length=37)
    checks: tuple[F1PropertyCheckEvidence, ...] = Field(min_length=39, max_length=39)
    ordered_check_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_status: Literal["VERIFIED"] = "VERIFIED"
    expanded_atomic_tickets_materialized: Literal[False] = False
    foundation_complete: Literal[False] = False
    scope_limitation: str

    @model_validator(mode="after")
    def verify_exact_property_matrix(self) -> F1PropertySuiteEvidence:
        expected_pairs = tuple(
            (family, kind) for family in FAMILY_ORDER for kind in CASE_KIND_ORDER
        )
        observed_pairs = tuple((check.family_id, check.property_kind) for check in self.checks)
        if observed_pairs != expected_pairs:
            raise ValueError("F1 property checks are not the canonical 13 by 3 ordered matrix")
        if self.property_kind_counts != {kind: 13 for kind in CASE_KIND_ORDER}:
            raise ValueError("F1 property kind counts are not exactly 13 each")
        if (
            ordered_json_stream_sha256(check.content_hash for check in self.checks)
            != self.ordered_check_digest
        ):
            raise ValueError("F1 ordered property check digest drifted")
        unions = (
            (
                self.covered_baseline_ids,
                {value for check in self.checks for value in check.covered_baseline_ids},
            ),
            (
                self.covered_semantic_family_refs,
                {value for check in self.checks for value in check.covered_semantic_family_refs},
            ),
            (
                self.covered_settlement_function_refs,
                {
                    value
                    for check in self.checks
                    for value in check.covered_settlement_function_refs
                },
            ),
            (
                self.covered_atomic_binding_ids,
                {value for check in self.checks for value in check.covered_atomic_binding_ids},
            ),
        )
        if any(tuple(sorted(observed)) != expected for expected, observed in unions):
            raise ValueError("F1 property check coverage union drifted from the suite inventory")
        expected_settings = {
            "database": None,
            "deadline": None,
            "derandomize": False,
            "draw_sample_mode": "sha256_ranked_non_seed_draws_v1",
            "max_examples": 64,
            "phases": ["explicit", "generate", "shrink"],
            "seed_mode": "explicit_property_identity_sha256_v1",
        }
        if self.hypothesis_settings != expected_settings:
            raise ValueError("F1 Hypothesis settings drifted")
        if set(self.source_hashes) != {"property_oracles", "property_suite"} or any(
            len(value) != 64 for value in self.source_hashes.values()
        ):
            raise ValueError("F1 property source hashes are incomplete")
        return self


@dataclass(frozen=True, slots=True)
class _PropertyTarget:
    target_id: str
    family_id: str
    records: tuple[Any, ...]
    selection: tuple[int | str, ...]
    baseline_ids: tuple[str, ...]
    atomic_binding_id: str | None


@dataclass(frozen=True, slots=True)
class _PropertyContext:
    catalog: Mapping[str, Any]
    registry: FoundationSemanticsRegistry
    world: WorldSnapshot
    replay: F1RepresentativeReplayEvidence
    independent: IndependentExpectedSelectionDomainManifestVersion
    atomic: AtomicTicketBindingVersion
    records_by_id: dict[str, Any]
    canonical_by_id: dict[str, Any]
    targets_by_family: dict[str, tuple[_PropertyTarget, ...]]


def _with_hash(model: type[_ContentHashedModel], payload: Mapping[str, Any]) -> Any:
    projected = model.model_construct(content_hash="0" * 64, **dict(payload))
    materialized = projected.model_dump(mode="json", exclude={"content_hash"})
    materialized["content_hash"] = canonical_sha256(materialized)
    return model.model_validate(materialized)


def current_property_source_hashes() -> dict[str, str]:
    """Return the two exact source identities executed by the property verifier."""

    oracle_path = Path(__file__).with_name("f1_property_oracles.py")
    return {
        "property_oracles": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        "property_suite": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _all_source_records(registry: FoundationSemanticsRegistry) -> dict[str, Any]:
    source = registry.source_artifacts
    records = (
        *source.basic_records,
        *source.set_compilation.rule_semantic_map.records,
        *source.combination_records,
        *source.linked_compilation.rule_semantic_map.records,
    )
    return {record.baseline_id: record for record in records}


def _selection_from_ticket(
    binding: AtomicTicketBindingDescriptor,
    ticket: AtomicTicketSelection,
) -> tuple[int | str, ...]:
    if binding.participating_baseline_ids_rule == "FIXED_SINGLE_BASELINE":
        return tuple(int(value) for value in ticket.selection_id.split(","))
    return ()


def _coverage_tickets(binding: AtomicTicketBindingDescriptor) -> tuple[AtomicTicketSelection, ...]:
    remaining = set(binding.component_baseline_ids)
    selected: list[AtomicTicketSelection] = []
    for ticket in iter_atomic_ticket_selections(binding):
        if remaining.intersection(ticket.participating_baseline_ids):
            selected.append(ticket)
            remaining.difference_update(ticket.participating_baseline_ids)
            if not remaining:
                break
    if remaining:
        raise ValueError(f"atomic binding coverage did not reach components: {sorted(remaining)}")
    return tuple(selected)


def _property_targets(
    registry: FoundationSemanticsRegistry,
    atomic: AtomicTicketBindingVersion,
    records_by_id: Mapping[str, Any],
) -> dict[str, tuple[_PropertyTarget, ...]]:
    targets: dict[str, list[_PropertyTarget]] = {family: [] for family in FAMILY_ORDER}
    composite_baselines = {
        baseline_id for binding in atomic.bindings for baseline_id in binding.component_baseline_ids
    }
    for record in records_by_id.values():
        if record.baseline_id in composite_baselines:
            continue
        if record.family_id in {"special-number", "regular-number", "regular-position-special"}:
            selection: tuple[int | str, ...] = (record.selection_space[0],)
        elif record.family_id == "six-zodiac":
            selection = ZODIAC_ORDER[:6]
        else:
            selection = ()
        targets[record.family_id].append(
            _PropertyTarget(
                target_id=f"record:{record.baseline_id}",
                family_id=record.family_id,
                records=(record,),
                selection=selection,
                baseline_ids=(record.baseline_id,),
                atomic_binding_id=None,
            )
        )

    for binding in atomic.bindings:
        for ticket in _coverage_tickets(binding):
            records = tuple(records_by_id[value] for value in ticket.participating_baseline_ids)
            targets[binding.family_id].append(
                _PropertyTarget(
                    target_id=ticket.canonical_ticket_id,
                    family_id=binding.family_id,
                    records=records,
                    selection=_selection_from_ticket(binding, ticket),
                    baseline_ids=ticket.participating_baseline_ids,
                    atomic_binding_id=binding.binding_id,
                )
            )
    result = {
        family: tuple(sorted(values, key=lambda item: item.target_id))
        for family, values in targets.items()
    }
    canonical_family_ids = {
        family: {
            record.baseline_id
            for record in registry.rule_semantic_map.records
            if record.family_id == family
        }
        for family in FAMILY_ORDER
    }
    for family, values in result.items():
        covered = {baseline_id for target in values for baseline_id in target.baseline_ids}
        if covered != canonical_family_ids[family]:
            raise ValueError(f"F1 property targets do not cover family {family}")
    return result


def _subject_observation(
    target: _PropertyTarget,
    draw: DrawReplayInput,
) -> tuple[Outcome, str | None]:
    family = target.family_id
    if family in {"special-number", "regular-number", "regular-position-special"}:
        result = settle_basic_record(
            record=target.records[0],
            draw=draw.numbers,
            selection=target.selection[0],
        )
        return result.outcome, result.unit_payout
    if family in {"other-explicit", "one-zodiac-tail", "six-zodiac"}:
        outcome = settle_rule(
            target.records[0],
            draw=draw.numbers,
            draw_date=draw.draw_date,
            selection=tuple(str(value) for value in target.selection) or None,
        )
        return outcome, None
    if family in {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }:
        result = settle_combination(
            entry=target.records[0],
            draw=draw.numbers,
            selection=target.selection,
        )
        return result.outcome, result.unit_payout
    if family in {"linked-zodiac", "linked-tail"}:
        result = settle_linked_ticket(
            target.records,
            draw=draw.numbers,
            draw_date=draw.draw_date,
        )
        return result.outcome, result.unit_payout
    if family == "parlay":
        result = settle_parlay_ticket(target.records, draw=draw.numbers)
        return result.outcome, result.unit_payout
    raise ValueError(f"unsupported F1 property subject family: {family}")


def _oracle_outcome(target: _PropertyTarget, draw: DrawReplayInput) -> Outcome:
    family = target.family_id
    if family in {"special-number", "regular-number", "regular-position-special"}:
        return basic_outcome(target.records[0], draw.numbers, target.selection[0])
    if family in {"other-explicit", "one-zodiac-tail", "six-zodiac"}:
        return set_outcome(
            target.records[0],
            draw.numbers,
            draw.draw_date,
            tuple(str(value) for value in target.selection) or None,
        )
    if family in {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }:
        return combination_outcome(target.records[0], draw.numbers, target.selection)
    if family in {"linked-zodiac", "linked-tail"}:
        return linked_outcome(target.records, draw.numbers, draw.draw_date)
    if family == "parlay":
        return parlay_outcome(target.records, draw.numbers)
    raise ValueError(f"unsupported F1 property oracle family: {family}")


def _assert_payout_coupling(outcome: Outcome, payout: str | None) -> None:
    if payout is None:
        return
    if outcome == "MISS" and payout != "0":
        raise AssertionError("F1 property subject MISS did not pay zero")
    if outcome == "VOID" and payout != "1":
        raise AssertionError("F1 property subject VOID did not refund one")
    if outcome == "HIT" and Decimal(payout) <= 0:
        raise AssertionError("F1 property subject HIT did not expose a positive payout")


def _seed_target(ctx: _PropertyContext, case_evidence: Any) -> _PropertyTarget:
    case = case_evidence.case
    records = tuple(ctx.records_by_id[value] for value in case.component_baseline_ids)
    binding_id = case_evidence.atomic_ticket_binding_id
    return _PropertyTarget(
        target_id=f"seed:{case.case_id}",
        family_id=records[0].family_id,
        records=records,
        selection=case.selection,
        baseline_ids=case.component_baseline_ids,
        atomic_binding_id=binding_id,
    )


def _deterministic_draw_sample(
    world: WorldSnapshot,
    *,
    seed_index: int,
    generation_seed_sha256: str,
) -> tuple[int, ...]:
    """Select the exact finite draw corpus exercised by one Hypothesis check."""

    domain = b"xinao.f1_property_draw_sample.v1\0" + bytes.fromhex(generation_seed_sha256)
    ranked = sorted(
        (index for index in range(len(world.draw_inputs)) if index != seed_index),
        key=lambda index: (
            hashlib.sha256(
                domain + world.draw_inputs[index].content_hash.encode("ascii")
            ).digest(),
            index,
        ),
    )
    if len(ranked) < MAX_EXAMPLES_PER_CHECK:
        raise ValueError("F1 property world has too few non-seed draws")
    return tuple(ranked[:MAX_EXAMPLES_PER_CHECK])


def _run_property_check(ctx: _PropertyContext, case_evidence: Any) -> F1PropertyCheckEvidence:
    try:
        import hypothesis
        from hypothesis import Phase, example, given, seed, settings
        from hypothesis import strategies as st
    except ImportError as exc:  # pragma: no cover - verifier dependency gate
        raise RuntimeError("F1 property verification requires pinned Hypothesis") from exc
    if hypothesis.__version__ != HYPOTHESIS_VERSION:
        raise RuntimeError(
            f"F1 property verification requires Hypothesis {HYPOTHESIS_VERSION}, "
            f"got {hypothesis.__version__}"
        )

    case = case_evidence.case
    family = case_evidence.result.family_id
    kind = case.case_kind
    seed_index = next(
        index for index, draw in enumerate(ctx.world.draw_inputs) if draw.draw_id == case.draw_id
    )
    seed_draw = ctx.world.draw_inputs[seed_index]
    seed_target = _seed_target(ctx, case_evidence)
    seed_oracle = _oracle_outcome(seed_target, seed_draw)
    seed_subject, seed_payout = _subject_observation(seed_target, seed_draw)
    _assert_payout_coupling(seed_subject, seed_payout)
    if seed_oracle != seed_subject or seed_oracle != case.expected_outcome:
        raise AssertionError(f"independent F1 seed oracle disagrees for {case.case_id}")

    trace_rows: set[tuple[str, ...]] = {
        (
            "PINNED_SEED",
            seed_draw.draw_id,
            seed_draw.content_hash,
            seed_target.target_id,
            seed_oracle,
            seed_subject,
            seed_payout or "",
        )
    }
    generated_draw_ids: set[str] = set()
    outcome_counts: Counter[str] = Counter({seed_subject: 1})
    pass_count = 1
    targets = ctx.targets_by_family[family]
    generation_seed_sha256 = canonical_sha256(
        {
            "profile": "xinao.f1_property_generation_seed.v1",
            "property_id": f"f1-property:{family}:{kind.lower()}:v1",
            "seed_replay_case_hash": case_evidence.content_hash,
            "world_snapshot_hash": ctx.world.content_hash,
        }
    )
    generated_indices = _deterministic_draw_sample(
        ctx.world,
        seed_index=seed_index,
        generation_seed_sha256=generation_seed_sha256,
    )

    @seed(int(generation_seed_sha256, 16))
    @settings(
        max_examples=MAX_EXAMPLES_PER_CHECK,
        derandomize=False,
        database=None,
        deadline=None,
        phases=(Phase.explicit, Phase.generate, Phase.shrink),
    )
    @example(draw_index=seed_index)
    @given(draw_index=st.sampled_from(generated_indices))
    def generated_property(draw_index: int) -> None:
        nonlocal pass_count
        draw = ctx.world.draw_inputs[draw_index]
        if draw_index != seed_index:
            generated_draw_ids.add(draw.draw_id)
        for target in targets:
            oracle = _oracle_outcome(target, draw)
            subject, payout = _subject_observation(target, draw)
            _assert_payout_coupling(subject, payout)
            assert subject == oracle
            pass_count += 1
            outcome_counts[subject] += 1
            trace_rows.add(
                (
                    "GENERATED",
                    draw.draw_id,
                    draw.content_hash,
                    target.target_id,
                    oracle,
                    subject,
                    payout or "",
                )
            )

    generated_property()
    if len(generated_draw_ids) < MAX_EXAMPLES_PER_CHECK:
        raise AssertionError(
            f"Hypothesis generated only {len(generated_draw_ids)} distinct non-seed draws"
        )

    covered_baselines = tuple(
        sorted({baseline_id for target in targets for baseline_id in target.baseline_ids})
    )
    canonical_records = [ctx.canonical_by_id[value] for value in covered_baselines]
    covered_bindings = tuple(
        sorted(
            {target.atomic_binding_id for target in targets if target.atomic_binding_id is not None}
        )
    )
    return _with_hash(
        F1PropertyCheckEvidence,
        {
            "property_id": f"f1-property:{family}:{kind.lower()}:v1",
            "family_id": family,
            "property_kind": kind,
            "seed_replay_case_id": case.case_id,
            "seed_replay_case_hash": case_evidence.content_hash,
            "seed_draw_id": seed_draw.draw_id,
            "seed_oracle_outcome": seed_oracle,
            "generation_seed_sha256": generation_seed_sha256,
            "max_examples": MAX_EXAMPLES_PER_CHECK,
            "generated_draw_example_count": len(generated_draw_ids),
            "explicit_seed_example_count": 1,
            "settlement_evaluation_count": pass_count,
            "pass_count": pass_count,
            "failure_count": 0,
            "covered_baseline_ids": covered_baselines,
            "covered_semantic_family_refs": tuple(
                sorted({record.semantic_family_ref for record in canonical_records})
            ),
            "covered_settlement_function_refs": tuple(
                sorted({record.settlement_function_ref for record in canonical_records})
            ),
            "covered_atomic_binding_ids": covered_bindings,
            "observed_outcome_counts": dict(sorted(outcome_counts.items())),
            "ordered_trace_sha256": ordered_json_stream_sha256(sorted(trace_rows)),
            "result_status": "VERIFIED",
        },
    )


def compile_f1_property_suite_evidence(
    *,
    catalog: Mapping[str, Any],
    registry: FoundationSemanticsRegistry,
    world: WorldSnapshot,
    replay: F1RepresentativeReplayEvidence,
) -> F1PropertySuiteEvidence:
    """Run 39 deterministic Hypothesis checks against independent F1 oracles."""

    independent = compile_independent_selection_manifest(catalog)
    comparison = assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    if not comparison.exact_match:
        raise ValueError("F1 property suite selection manifests disagree")
    atomic = compile_atomic_ticket_bindings(catalog, independent)
    if (
        world.active_semantics_hash != registry.active_physical_semantics_hash
        or world.active_selection_domain_structural_hash
        != replay.active_selection_domain_structural_hash
        or world.active_atomic_ticket_binding_structural_hash
        != replay.active_atomic_ticket_binding_structural_hash
    ):
        raise ValueError("F1 property suite identities disagree with replay/world")

    records_by_id = _all_source_records(registry)
    canonical_by_id = {record.baseline_id: record for record in registry.rule_semantic_map.records}
    ctx = _PropertyContext(
        catalog=catalog,
        registry=registry,
        world=world,
        replay=replay,
        independent=independent,
        atomic=atomic,
        records_by_id=records_by_id,
        canonical_by_id=canonical_by_id,
        targets_by_family=_property_targets(registry, atomic, records_by_id),
    )
    checks = tuple(_run_property_check(ctx, case) for case in replay.cases)
    baseline_ids = tuple(sorted(canonical_by_id))
    semantic_refs = tuple(
        sorted({record.semantic_family_ref for record in registry.rule_semantic_map.records})
    )
    function_refs = tuple(
        sorted({record.settlement_function_ref for record in registry.rule_semantic_map.records})
    )
    binding_ids = tuple(sorted(binding.binding_id for binding in atomic.bindings))
    return _with_hash(
        F1PropertySuiteEvidence,
        {
            "hypothesis_version": HYPOTHESIS_VERSION,
            "hypothesis_settings": {
                "database": None,
                "deadline": None,
                "derandomize": False,
                "draw_sample_mode": "sha256_ranked_non_seed_draws_v1",
                "max_examples": MAX_EXAMPLES_PER_CHECK,
                "phases": ["explicit", "generate", "shrink"],
                "seed_mode": "explicit_property_identity_sha256_v1",
            },
            "source_hashes": current_property_source_hashes(),
            "active_catalog_projection_hash": (
                registry.rule_semantic_map.active_catalog_projection_hash
            ),
            "active_semantics_hash": registry.active_physical_semantics_hash,
            "rule_semantic_map_hash": registry.rule_semantic_map.content_hash,
            "settlement_function_set_hash": registry.settlement_function_set.content_hash,
            "registry_selection_manifest_hash": registry.expected_selection_domain.content_hash,
            "independent_selection_manifest_hash": independent.content_hash,
            "atomic_ticket_binding_hash": atomic.content_hash,
            "dataset_semantic_hash": world.dataset_semantic_hash,
            "ordered_draw_input_digest": ordered_json_stream_sha256(
                draw.content_hash for draw in world.draw_inputs
            ),
            "representative_replay_hash": replay.content_hash,
            "family_count": 13,
            "property_check_count": 39,
            "property_kind_counts": {kind: 13 for kind in CASE_KIND_ORDER},
            "active_component_count": len(baseline_ids),
            "semantic_family_ref_count": len(semantic_refs),
            "settlement_function_ref_count": len(function_refs),
            "atomic_ticket_binding_count": len(binding_ids),
            "covered_baseline_ids": baseline_ids,
            "covered_semantic_family_refs": semantic_refs,
            "covered_settlement_function_refs": function_refs,
            "covered_atomic_binding_ids": binding_ids,
            "checks": checks,
            "ordered_check_digest": ordered_json_stream_sha256(
                check.content_hash for check in checks
            ),
            "result_status": "VERIFIED",
            "expanded_atomic_tickets_materialized": False,
            "foundation_complete": False,
            "scope_limitation": (
                "Generated F1 settlement properties plus representative replay are scoped "
                "evidence; F2-F4 remain separate closure blocks."
            ),
        },
    )


__all__ = [
    "HYPOTHESIS_VERSION",
    "MAX_EXAMPLES_PER_CHECK",
    "F1PropertyCheckEvidence",
    "F1PropertySuiteEvidence",
    "compile_f1_property_suite_evidence",
    "current_property_source_hashes",
]
