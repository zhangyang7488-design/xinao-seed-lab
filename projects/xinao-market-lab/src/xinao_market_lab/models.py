from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SeriesSpec(FrozenModel):
    schema_version: Literal[1] = 1
    series_id: Literal["macaujc2_daily_2132_type8"] = "macaujc2_daily_2132_type8"
    upstream_key: Literal["macaujc2"] = "macaujc2"
    upstream_type: Literal["8"] = "8"
    scheduled_clock: Literal["21:32:32 Asia/Shanghai"] = "21:32:32 Asia/Shanghai"
    number_pool_min: Literal[1] = 1
    number_pool_max: Literal[49] = 49
    regular_count: Literal[6] = 6
    special_position: Literal[7] = 7
    source_confidence: Literal["upstream_unverified"] = "upstream_unverified"


class Draw(FrozenModel):
    series_id: str
    source_expect: str = Field(pattern=r"^\d{7}$")
    open_time: datetime
    regular_numbers: tuple[int, int, int, int, int, int]
    special: int
    wave: tuple[str, str, str, str, str, str, str]
    zodiac: tuple[str, str, str, str, str, str, str]
    source_verified: bool
    flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_draw(self) -> Draw:
        numbers = (*self.regular_numbers, self.special)
        if any(number < 1 or number > 49 for number in numbers):
            raise ValueError("draw numbers must be in 1..49")
        if len(set(numbers)) != 7:
            raise ValueError("draw numbers must be unique within a draw")
        return self

    @property
    def usable_for_replay(self) -> bool:
        return not {"expect_year_mismatch", "duplicate_outcome_repetition"}.intersection(self.flags)


class OddsQuote(FrozenModel):
    quote_id: str
    observed_at: datetime
    page_key: str
    source_file: str
    pan: Literal["A"] = "A"
    selection_min: Literal[1] = 1
    selection_max: Literal[49] = 49
    inclusive_return: Decimal
    quote_kind: Literal["single_non_contemporaneous_candidate_snapshot"] = (
        "single_non_contemporaneous_candidate_snapshot"
    )


class RuleVersion(FrozenModel):
    rule_id: str
    rule_hash: str
    play_family: Literal["special_number"] = "special_number"
    projection: Literal["special"] = "special"
    outcome_space: Literal["1..49"] = "1..49"
    winning_condition: Literal["decision.selection == draw.special"] = "decision.selection == draw.special"
    payout_basis: Literal["inclusive_return"] = "inclusive_return"
    push_policy: Literal["not_applicable_for_exact_number"] = "not_applicable_for_exact_number"
    quote_id: str


class CostModel(FrozenModel):
    cost_model_id: Literal["stake_1_explicit_cost_0_v1"] = "stake_1_explicit_cost_0_v1"
    stake: Decimal = Decimal("1")
    explicit_cost: Decimal = Decimal("0")
    return_basis: Literal["gross_return_includes_stake"] = "gross_return_includes_stake"


class CandidateSpec(FrozenModel):
    candidate_id: str
    kind: Literal["always_no_bet", "fixed_number", "previous_special", "rolling_mode"]
    fixed_number: int | None = None
    window: int | None = None

    @model_validator(mode="after")
    def validate_parameters(self) -> CandidateSpec:
        if self.kind == "fixed_number" and not (self.fixed_number and 1 <= self.fixed_number <= 49):
            raise ValueError("fixed_number candidate requires a selection in 1..49")
        if self.kind == "rolling_mode" and (self.window is None or self.window < 1):
            raise ValueError("rolling_mode candidate requires a positive window")
        return self


class Decision(FrozenModel):
    place_bet: bool
    selection: int | None
    information_cutoff_expect: str | None

    @model_validator(mode="after")
    def validate_selection(self) -> Decision:
        if self.place_bet != (self.selection is not None):
            raise ValueError("place_bet and selection must agree")
        if self.selection is not None and not 1 <= self.selection <= 49:
            raise ValueError("selection must be in 1..49")
        return self


class Settlement(FrozenModel):
    outcome: Literal["no_bet", "win", "lose"]
    stake: Decimal
    explicit_cost: Decimal
    gross_return: Decimal
    net_return: Decimal


class TrialRecord(FrozenModel):
    schema_version: Literal[1] = 1
    run_key: str
    snapshot_id: str
    evaluation_kind: Literal["mechanics_replay_non_contemporaneous_price"] = (
        "mechanics_replay_non_contemporaneous_price"
    )
    candidate_id: str
    draw_index: int
    source_expect: str
    source_verified: bool
    draw_flags: tuple[str, ...]
    decision: Decision
    actual_special: int
    rule_id: str
    rule_hash: str
    quote_id: str
    settlement: Settlement


class RuleSemantics(FrozenModel):
    schema_version: Literal[1] = 1
    semantics_id: str
    semantics_hash: str
    play_family: Literal["special_number", "regular_number"]
    projection: Literal["special", "regular_set"]
    selection_domain: Literal["1..49"] = "1..49"
    winning_condition: Literal[
        "decision.selection == draw.special",
        "decision.selection in draw.regular_numbers",
    ]
    outcome_space: Literal["no_bet|win|lose"] = "no_bet|win|lose"
    push_policy: Literal["not_applicable_for_exact_number"] = "not_applicable_for_exact_number"

    @model_validator(mode="after")
    def validate_projection_contract(self) -> RuleSemantics:
        allowed = {
            ("special_number", "special", "decision.selection == draw.special"),
            ("regular_number", "regular_set", "decision.selection in draw.regular_numbers"),
        }
        actual = (self.play_family, self.projection, self.winning_condition)
        if actual not in allowed:
            raise ValueError("play family, projection, and winning condition must form a known contract")
        return self


class RuleClaim(FrozenModel):
    schema_version: Literal[1] = 1
    claim_id: str
    subject: Literal[
        "special_exact_membership",
        "regular_set_membership",
        "payout_basis",
        "special_two_sided_49_policy",
    ]
    status: Literal["spec_pinned_mechanics_candidate", "unresolved"]
    source_truth_status: Literal["unverified"] = "unverified"
    semantics_hash: str | None = None
    assumption_id: str | None = None
    reason_code: str
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def validate_claim_state(self) -> RuleClaim:
        if self.status == "spec_pinned_mechanics_candidate" and self.semantics_hash is None:
            raise ValueError("compiled mechanics candidates require a semantics hash")
        if self.status == "unresolved" and self.semantics_hash is not None:
            raise ValueError("unresolved claims must not bind executable semantics")
        return self


class DisplayedOddsQuote(FrozenModel):
    schema_version: Literal[1] = 1
    quote_id: str
    captured_at: datetime
    bundle_created_at: datetime
    page_key: str
    alias_page_keys: tuple[str, ...]
    source_file: str
    raw_source_file: str
    raw_source_sha256: str
    group: Literal["正码"] = "正码"
    pid: Literal["2"] = "2"
    tid: Literal["16"] = "16"
    pan: Literal["A"] = "A"
    title: Literal["正码A盘"] = "正码A盘"
    accepted_numbers: tuple[int, ...]
    displayed_odds: Decimal
    payout_basis_status: Literal["unresolved"] = "unresolved"
    quote_kind: Literal["single_non_contemporaneous_candidate_snapshot"] = (
        "single_non_contemporaneous_candidate_snapshot"
    )

    @model_validator(mode="after")
    def validate_number_space(self) -> DisplayedOddsQuote:
        if self.accepted_numbers != tuple(range(1, 50)):
            raise ValueError("regular A quote must cover exactly the canonical number space 1..49")
        if self.page_key in self.alias_page_keys:
            raise ValueError("canonical page key must not be repeated as an alias")
        return self


class LineageRecord(FrozenModel):
    schema_version: Literal[2] = 2
    source_index: int
    source_expect: str
    open_time: datetime
    outcome_sha256: str
    source_verified: bool
    source_flags: tuple[str, ...]
    status: Literal["canonical", "quarantined"]
    canonical_expect: str
    reason_code: Literal[
        "canonical_unique",
        "canonical_validation_ranked_exact_time_alias",
        "expect_year_mismatch",
        "expect_year_mismatch_exact_time_alias",
        "later_full_outcome_repetition",
    ]


class ProjectionTrialRecord(FrozenModel):
    schema_version: Literal[2] = 2
    run_key: str
    snapshot_id: str
    evaluation_kind: Literal["mechanics_replay_spec_pinned_non_contemporaneous_price"] = (
        "mechanics_replay_spec_pinned_non_contemporaneous_price"
    )
    candidate_id: str
    draw_index: int
    source_expect: str
    source_verified: bool
    lineage_reason_code: str
    decision: Decision
    actual_regular_set: tuple[int, int, int, int, int, int]
    actual_special: int
    semantics_id: str
    semantics_hash: str
    rule_claim_id: str
    quote_id: str
    payout_assumption_id: str
    settlement: Settlement


class SourceHashPin(FrozenModel):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExactRuleDefinition(FrozenModel):
    schema_version: Literal[1] = 1
    rule_key: str = Field(pattern=r"^[a-z0-9-]+$")
    rule_revision: Literal["p2-rule-catalog-pure-settle-v1"] = "p2-rule-catalog-pure-settle-v1"
    family: Literal["special_exact", "regular_set_exact", "regular_position_exact"]
    projection: Literal["special", "regular_set", "regular_position"]
    position: int | None = Field(default=None, ge=1, le=6)
    pid: str = Field(pattern=r"^\d+$")
    tid: str = Field(pattern=r"^\d+$")
    pan: Literal["A"] = "A"
    group: Literal["特码", "正码", "正码特"]
    expected_modal_odds: Literal["47.285", "7.850", "42.300"]
    winning_condition: Literal[
        "decision.selection == draw.special",
        "decision.selection in draw.regular_numbers",
        "decision.selection == draw.regular_numbers[position - 1]",
    ]
    source_truth_status: Literal["unverified"] = "unverified"
    price_status: Literal["snapshot_candidate_not_forward_price"] = "snapshot_candidate_not_forward_price"
    implementation_status: Literal["spec_pinned_mechanics_candidate"] = "spec_pinned_mechanics_candidate"
    push_policy: Literal["not_applicable_for_exact_number"] = "not_applicable_for_exact_number"

    @model_validator(mode="after")
    def validate_exact_projection(self) -> ExactRuleDefinition:
        if self.family == "special_exact":
            expected = (
                "special",
                None,
                "1",
                "14",
                "特码",
                "47.285",
                "decision.selection == draw.special",
            )
        elif self.family == "regular_set_exact":
            expected = (
                "regular_set",
                None,
                "2",
                "16",
                "正码",
                "7.850",
                "decision.selection in draw.regular_numbers",
            )
        else:
            if self.position is None:
                raise ValueError("regular-position rules require position 1..6")
            expected = (
                "regular_position",
                self.position,
                "3",
                str(17 + self.position),
                "正码特",
                "42.300",
                "decision.selection == draw.regular_numbers[position - 1]",
            )
        actual = (
            self.projection,
            self.position,
            self.pid,
            self.tid,
            self.group,
            self.expected_modal_odds,
            self.winning_condition,
        )
        if actual != expected:
            raise ValueError("rule identity and pure projection contract disagree")
        expected_key = {
            "special_exact": "special-a",
            "regular_set_exact": "regular-a",
        }.get(self.family, f"regular-position-{self.position}-a")
        if self.rule_key != expected_key:
            raise ValueError("rule_key does not identify the declared projection")
        return self


class ExactRuleBundle(FrozenModel):
    schema_version: Literal[1] = 1
    bundle_id: Literal["p2-rule-catalog-pure-settle-v1"] = "p2-rule-catalog-pure-settle-v1"
    source_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hashes: tuple[SourceHashPin, ...]
    rules: tuple[ExactRuleDefinition, ...]

    @model_validator(mode="after")
    def validate_bundle_surface(self) -> ExactRuleBundle:
        if len(self.rules) != 8 or len({rule.rule_key for rule in self.rules}) != 8:
            raise ValueError("P2 bundle must contain exactly eight unique rules")
        expected_keys = {
            "special-a",
            "regular-a",
            *(f"regular-position-{position}-a" for position in range(1, 7)),
        }
        if {rule.rule_key for rule in self.rules} != expected_keys:
            raise ValueError("P2 bundle rule surface is incomplete")
        paths = [pin.relative_path for pin in self.source_hashes]
        if len(paths) != len(set(paths)) or len(paths) < 4:
            raise ValueError("source hash pins must be unique and cover the catalog evidence")
        return self


class CompiledExactRule(FrozenModel):
    definition: ExactRuleDefinition
    rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quote_evidence: dict[str, Any]


class PlayStructureClassification(FrozenModel):
    schema_version: Literal[1] = 1
    row_number: int = Field(ge=2)
    play_id: str
    pid: str
    tid: str
    pan: str
    status: Literal["IMPLEMENTED", "UNRESOLVED"]
    rule_key: str | None = None
    reason_code: str

    @model_validator(mode="after")
    def validate_resolution(self) -> PlayStructureClassification:
        if (self.status == "IMPLEMENTED") != (self.rule_key is not None):
            raise ValueError("implemented classifications require exactly one rule_key")
        return self


class RuleResolution(FrozenModel):
    schema_version: Literal[1] = 1
    status: Literal["IMPLEMENTED", "UNRESOLVED"]
    rule_key: str | None = None
    rule_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_code: str

    @model_validator(mode="after")
    def validate_resolution(self) -> RuleResolution:
        has_rule = self.rule_key is not None and self.rule_hash is not None
        if (self.status == "IMPLEMENTED") != has_rule:
            raise ValueError("implemented resolution requires a rule key and hash")
        if self.status == "UNRESOLVED" and (self.rule_key is not None or self.rule_hash is not None):
            raise ValueError("unresolved resolution must not expose executable identity")
        return self


class ConformanceEvent(FrozenModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=0)
    case_id: str
    rule_key: str
    rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cost_model_id: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuleHashPin(FrozenModel):
    rule_key: str
    rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class P2EvidencePin(FrozenModel):
    run_directory: str
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conformance_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conformance_chain_tip: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["verified_rule_catalog_pure_settle_with_lineage_v2"]


class ChronologicalFold(FrozenModel):
    fold_id: str = Field(pattern=r"^fold-[1-9]\d*$")
    start_index: int = Field(ge=0)
    end_index_exclusive: int = Field(gt=0)
    start_expect: str
    end_expect: str
    start_time: datetime
    end_time: datetime
    context_end_index: int | None = Field(default=None, ge=0)
    context_end_expect: str | None = None
    context_end_time: datetime | None = None

    @model_validator(mode="after")
    def validate_fold(self) -> ChronologicalFold:
        if self.end_index_exclusive <= self.start_index:
            raise ValueError("chronological fold must contain at least one draw")
        if self.start_time > self.end_time:
            raise ValueError("chronological fold times must be ordered")
        context_values = (self.context_end_index, self.context_end_expect, self.context_end_time)
        if self.start_index == 0:
            if any(value is not None for value in context_values):
                raise ValueError("first fold cannot have earlier context")
        elif any(value is None for value in context_values):
            raise ValueError("later folds require an explicit prior context boundary")
        elif self.context_end_index != self.start_index - 1:
            raise ValueError("fold context must end immediately before the evaluation window")
        return self


class ResearchProtocolSpec(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal["p3-research-protocol-judge-gate-v1"] = "p3-research-protocol-judge-gate-v1"
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    p2_evidence: P2EvidencePin
    candidates: tuple[CandidateSpec, ...]
    rules: tuple[RuleHashPin, ...]
    cost_model: CostModel
    payout_assumption_id: Literal["mechanics-assumption-inclusive-return-v1"] = (
        "mechanics-assumption-inclusive-return-v1"
    )
    source_draw_count: int = Field(gt=0)
    folds: tuple[ChronologicalFold, ...]
    declared_cell_budget: int = Field(gt=0)
    declared_trial_row_budget: int = Field(gt=0)
    metrics: tuple[
        Literal[
            "draws",
            "bets",
            "wins",
            "total_stake",
            "mechanics_gross_return_under_assumption",
            "mechanics_net_return_under_assumption",
        ],
        ...,
    ]
    ranking_permitted: Literal[False] = False
    candidate_selection_permitted: Literal[False] = False
    economic_claim_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False

    @model_validator(mode="after")
    def validate_finite_protocol(self) -> ResearchProtocolSpec:
        expected_candidates = (
            "always_no_bet",
            "fixed_01",
            "previous_special",
            "rolling_mode_49",
        )
        if tuple(candidate.candidate_id for candidate in self.candidates) != expected_candidates:
            raise ValueError("P3 candidate set must be the four existing mechanical baselines")
        if len(self.rules) != 8 or len({rule.rule_key for rule in self.rules}) != 8:
            raise ValueError("P3 protocol requires eight unique typed rules")
        expected_cells = len(self.candidates) * len(self.rules)
        if self.declared_cell_budget != expected_cells:
            raise ValueError("declared cell budget must equal candidates x rules")
        if self.declared_trial_row_budget != expected_cells * self.source_draw_count:
            raise ValueError("declared trial-row budget must cover every declared cell and draw")
        if not self.folds or self.folds[0].start_index != 0:
            raise ValueError("chronological folds must begin at the first draw")
        for left, right in zip(self.folds, self.folds[1:], strict=False):
            if left.end_index_exclusive != right.start_index:
                raise ValueError("chronological folds must be contiguous and non-overlapping")
        if self.folds[-1].end_index_exclusive != self.source_draw_count:
            raise ValueError("chronological folds must cover every source draw")
        return self


class ResearchProtocol(FrozenModel):
    spec: ResearchProtocolSpec
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_id: str = Field(pattern=r"^experiment-p3-[0-9a-f]{24}$")


class ResearchTrialEvent(FrozenModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=0)
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_id: str
    rule_key: str
    rule_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cost_model_id: str
    payout_assumption_id: str
    fold_id: str
    draw_index: int = Field(ge=0)
    source_expect: str
    open_time: datetime
    source_verified: bool
    input_payload: dict[str, Any]
    decision_payload: dict[str, Any]
    output_payload: dict[str, Any]
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanics_status: Literal["MECHANICS_REPLAY_ONLY"] = "MECHANICS_REPLAY_ONLY"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"


class JudgeGateResult(FrozenModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanics_status: Literal["MECHANICS_ACCEPTED"] = "MECHANICS_ACCEPTED"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    expected_trial_rows: int = Field(gt=0)
    observed_trial_rows: int = Field(gt=0)
    declared_cells: int = Field(gt=0)
    completed_cells: int = Field(gt=0)
    trial_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_chain_tip: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    economic_blockers: tuple[str, ...]
    ranking_permitted: Literal[False] = False
    candidate_selection_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False
    source_truth_verified: Literal[False] = False
    historical_price_availability_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_gate(self) -> JudgeGateResult:
        if self.observed_trial_rows != self.expected_trial_rows:
            raise ValueError("Judge cannot accept incomplete trial coverage")
        if self.completed_cells != self.declared_cells:
            raise ValueError("Judge cannot accept incomplete cell coverage")
        if not self.checks or not all(self.checks.values()):
            raise ValueError("Judge mechanics acceptance requires every declared check")
        required = {
            "payout_basis_unresolved",
            "historical_price_availability_unverified",
            "contemporaneous_quote_fill_absent",
            "source_truth_unverified",
        }
        if set(self.economic_blockers) != required:
            raise ValueError("Judge economic blockers are incomplete")
        return self


class TombstoneRecord(FrozenModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tombstone_id: str
    subject: Literal[
        "economic_candidate_ranking",
        "historical_edge_claim",
        "forward_market_or_liability_claim",
    ]
    status: Literal["BLOCKED_BY_EVIDENCE"] = "BLOCKED_BY_EVIDENCE"
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class P3AcceptancePin(FrozenModel):
    schema_version: Literal[1] = 1
    run_directory: str
    status: Literal["verified"] = "verified"
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_chain_tip: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_gate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mechanics_status: Literal["MECHANICS_ACCEPTED"] = "MECHANICS_ACCEPTED"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"


class ContaminationMappingPin(FrozenModel):
    source_expect: str
    canonical_expect: str
    reason_code: Literal[
        "expect_year_mismatch_exact_time_alias",
        "later_full_outcome_repetition",
    ]


class P4TestDefinition(FrozenModel):
    test_id: Literal["T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold"]
    statistic: str
    null_projection: str
    tail: Literal["greater_or_equal"] = "greater_or_equal"


class P4ProtocolSpec(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal["p4-exact-null-contamination-structure-v1"] = (
        "p4-exact-null-contamination-structure-v1"
    )
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    p3_evidence: P3AcceptancePin
    source_draw_count: Literal[1209] = 1209
    canonical_draw_count: Literal[1204] = 1204
    lineage_policy_id: Literal["validation-ranked-exact-time-alias-then-chronological-outcome-v2"] = (
        "validation-ranked-exact-time-alias-then-chronological-outcome-v2"
    )
    contamination_pin: tuple[ContaminationMappingPin, ...]
    family: tuple[P4TestDefinition, ...]
    family_size: Literal[5] = 5
    alpha_fwer_fraction: Literal["1/20"] = "1/20"
    rng_bit_generator: Literal["PCG64"] = "PCG64"
    rng_seed: Literal[2026071104] = 2026071104
    numpy_version: Literal["2.5.1"] = "2.5.1"
    sampler_algorithm_id: Literal["pcg64_rejection_ordered7_int16_le_c_v1"] = (
        "pcg64_rejection_ordered7_int16_le_c_v1"
    )
    sampler_dtype: Literal["int16"] = "int16"
    sampler_byte_order: Literal["little"] = "little"
    stream_traversal: Literal["batch_draw_position_c_order"] = "batch_draw_position_c_order"
    sampler_api: Literal["Generator.integers_rejection_rows_v1"] = "Generator.integers_rejection_rows_v1"
    null_ledger_contract: Literal["hash_chained_canonical_jsonl_v1"] = "hash_chained_canonical_jsonl_v1"
    fold_sizes: tuple[Literal[301], Literal[301], Literal[301], Literal[301]] = (
        301,
        301,
        301,
        301,
    )
    n_mc: Literal[19999] = 19999
    batch_size: Literal[128] = 128
    p_value_method: Literal["plus_one_exceedance_(b+1)/(n_mc+1)"] = "plus_one_exceedance_(b+1)/(n_mc+1)"
    multiplicity_method: Literal["holm_step_down_exact_fraction"] = "holm_step_down_exact_fraction"
    shared_null_stream: Literal[True] = True
    economic_claim_permitted: Literal[False] = False
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False

    @model_validator(mode="after")
    def validate_frozen_p4_surface(self) -> P4ProtocolSpec:
        expected_pins = (
            ("2023004", "2024004", "expect_year_mismatch_exact_time_alias"),
            ("2024185", "2024156", "later_full_outcome_repetition"),
            ("2025259", "2024340", "later_full_outcome_repetition"),
            ("2025287", "2024335", "later_full_outcome_repetition"),
            ("2026019", "2024300", "later_full_outcome_repetition"),
        )
        actual_pins = tuple(
            (pin.source_expect, pin.canonical_expect, pin.reason_code) for pin in self.contamination_pin
        )
        if actual_pins != expected_pins:
            raise ValueError("P4 contamination pin must be the five accepted lineage-v2 mappings")
        expected_family = (
            (
                "T_special",
                "49*sum(special_count^2)-n^2",
                "special marginal under joint ordered 6+1 without-replacement null",
            ),
            (
                "T_pos_max",
                "max_position[49*sum(position_count^2)-n^2]",
                "maximum of six ordered regular-position marginals under the shared joint null",
            ),
            (
                "T_regular_incl",
                "49*sum(regular_inclusion_count^2)-(6*n)^2",
                "regular-set inclusion marginal under the shared joint null",
            ),
            (
                "T_lag1",
                "abs(49*equal_adjacent_special-(n-1))",
                "event-order adjacent-special equality under the shared joint null",
            ),
            (
                "T_fold",
                "max_fold[49*sum(fold_special_count^2)-fold_n^2]",
                "maximum special marginal across the four frozen 301-event folds",
            ),
        )
        actual_family = tuple((test.test_id, test.statistic, test.null_projection) for test in self.family)
        if actual_family != expected_family:
            raise ValueError("P4 statistical family must be exactly the accepted five-test surface")
        return self


class P4Protocol(FrozenModel):
    spec: P4ProtocolSpec
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_id: str = Field(pattern=r"^experiment-p4-[0-9a-f]{24}$")


class P4TestResult(FrozenModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_id: Literal["T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold"]
    observed_statistic: int = Field(ge=0)
    exceedance_count: int = Field(ge=0, le=19999)
    raw_p_numerator: int = Field(ge=1, le=20000)
    raw_p_denominator: Literal[20000] = 20000
    raw_p_fraction: str
    holm_rank: int = Field(ge=1, le=5)
    holm_multiplier: int = Field(ge=1, le=5)
    adjusted_p_fraction: str
    decision: Literal["REJECT_FWER", "RETAIN"]
    null_score_stream_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    economic_interpretation_permitted: Literal[False] = False


class P4JudgeGateResult(FrozenModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contamination_status: Literal["CONTAMINATION_PIN_MATCHED"] = "CONTAMINATION_PIN_MATCHED"
    structure_status: Literal["STRUCTURE_NULL_RETAINED", "STRUCTURE_NULL_REJECTED_FWER"]
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    family_size: Literal[5] = 5
    rejected_tests: tuple[Literal["T_special", "T_pos_max", "T_regular_incl", "T_lag1", "T_fold"], ...]
    checks: dict[str, bool]
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False
    source_truth_verified: Literal[False] = False
    historical_price_availability_verified: Literal[False] = False
    generator_mechanism_claim_permitted: Literal[False] = False

    @model_validator(mode="after")
    def validate_p4_gate(self) -> P4JudgeGateResult:
        if not self.checks or not all(self.checks.values()):
            raise ValueError("P4 Judge requires every declared mechanical check")
        rejected = bool(self.rejected_tests)
        if rejected != (self.structure_status == "STRUCTURE_NULL_REJECTED_FWER"):
            raise ValueError("P4 Judge status must agree with the rejected test set")
        return self


class P4TombstoneRecord(FrozenModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tombstone_id: str
    subject: Literal[
        "p3_candidate_ranking",
        "structure_rejection_as_edge",
        "quote_fill_claim",
        "source_truth_claim",
    ]
    status: Literal["BLOCKED_BY_EVIDENCE"] = "BLOCKED_BY_EVIDENCE"
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class P5SourceInventoryEntry(FrozenModel):
    schema_version: Literal[1] = 1
    relative_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    source_role: (
        Literal[
            "captured_page_snapshot",
            "package_manifest",
            "human_context_hypothesis",
            "derived_catalog",
        ]
        | None
    )
    document_kind: Literal["text", "json", "jsonl", "csv", "binary_archive", "executable_helper"]
    disposition: Literal["SCANNED", "EXCLUDED"]
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> P5SourceInventoryEntry:
        excluded = self.disposition == "EXCLUDED"
        if excluded != (self.exclusion_reason is not None):
            raise ValueError("excluded sources require exactly one frozen exclusion reason")
        if excluded != (self.source_role is None):
            raise ValueError("only scanned evidence sources may carry a source role")
        if self.disposition == "SCANNED" and self.document_kind in {
            "binary_archive",
            "executable_helper",
        }:
            raise ValueError("binary archives and executable helpers cannot enter the semantic scan")
        return self


class P5AcceptancePin(FrozenModel):
    schema_version: Literal[1] = 1
    p4_run_directory: str
    p4_run_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    p4_protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    p4_judge_gate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    structure_status: Literal["STRUCTURE_NULL_RETAINED"] = "STRUCTURE_NULL_RETAINED"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    trusted_anchor_path: str
    trusted_anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admin_acceptance_path: str
    admin_acceptance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admin_task_id: str
    admin_verdict: Literal["accepted"] = "accepted"
    p3_run_directory: str
    p2_run_directory: str
    p2_rule_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class P5ProtocolSpec(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal["p5-unresolved-semantics-evidence-catalog-v1"] = (
        "p5-unresolved-semantics-evidence-catalog-v1"
    )
    input_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    p4_acceptance: P5AcceptancePin
    rule_claim_subjects: tuple[
        Literal["payout_basis", "special_two_sided_49_policy"],
        Literal["payout_basis", "special_two_sided_49_policy"],
    ]
    play_structure_rows: Literal[136] = 136
    implemented_reference_rows: Literal[16] = 16
    unresolved_rows: Literal[120] = 120
    query_terms: tuple[str, ...]
    query_vocabulary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unicode_policy: Literal["utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"] = (
        "utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"
    )
    structured_selector: Literal["rfc6901_json_pointer_with_value_offsets_v1"] = (
        "rfc6901_json_pointer_with_value_offsets_v1"
    )
    text_selectors: tuple[
        Literal["w3c_text_quote_selector"],
        Literal["w3c_text_position_selector"],
    ] = ("w3c_text_quote_selector", "w3c_text_position_selector")
    provenance_concepts: tuple[
        Literal["prov_entity"],
        Literal["prov_activity"],
        Literal["prov_wasDerivedFrom"],
    ] = ("prov_entity", "prov_activity", "prov_wasDerivedFrom")
    source_inventory: tuple[P5SourceInventoryEntry, ...]
    network_permitted: Literal[False] = False
    semantics_compilation_permitted: Literal[False] = False
    operator_truth_upgrade_permitted: Literal[False] = False
    economic_claim_permitted: Literal[False] = False
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False

    @model_validator(mode="after")
    def validate_p5_surface(self) -> P5ProtocolSpec:
        if self.rule_claim_subjects != ("payout_basis", "special_two_sided_49_policy"):
            raise ValueError("P5 must bind exactly the two unresolved P2 RuleClaim subjects")
        expected_terms = (
            "含本",
            "不含本",
            "本金",
            "返还",
            "净赢",
            "退码",
            "和局",
            "走盘",
            "派彩",
            "赔付",
            "输赢",
            "结算",
            "49算和",
            "49为和",
            "49和局",
            "49退码",
            "49走盘",
            "49赔付",
            "49不计",
            "49不算",
            "特码两面",
            "49号",
        )
        if self.query_terms != expected_terms:
            raise ValueError("P5 query vocabulary and order must equal the frozen 22-term surface")
        paths = [entry.relative_path for entry in self.source_inventory]
        if len(paths) != 33 or len(paths) != len(set(paths)) or paths != sorted(paths):
            raise ValueError("P5 source inventory must be the sorted exact 33-file surface")
        if sum(entry.disposition == "SCANNED" for entry in self.source_inventory) != 27:
            raise ValueError("P5 must scan exactly 27 declared evidence sources")
        if sum(entry.disposition == "EXCLUDED" for entry in self.source_inventory) != 6:
            raise ValueError("P5 must retain exactly six hash-pinned exclusions")
        return self


class P5Protocol(FrozenModel):
    spec: P5ProtocolSpec
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_id: str = Field(pattern=r"^catalog-p5-[0-9a-f]{24}$")


class P5TextQuoteSelector(FrozenModel):
    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"
    exact: str
    prefix: str
    suffix: str


class P5TextPositionSelector(FrozenModel):
    type: Literal["TextPositionSelector"] = "TextPositionSelector"
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_half_open_interval(self) -> P5TextPositionSelector:
        if self.end <= self.start:
            raise ValueError("TextPositionSelector must be a non-empty half-open interval")
        return self


class P5TextSelectorSet(FrozenModel):
    type: Literal["TextSelectorSet"] = "TextSelectorSet"
    normalization_profile: Literal["utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"] = (
        "utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"
    )
    text_quote: P5TextQuoteSelector
    text_position: P5TextPositionSelector


class P5JsonValueSelector(FrozenModel):
    type: Literal["JsonValueSelector"] = "JsonValueSelector"
    json_pointer: str
    normalization_profile: Literal["utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"] = (
        "utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"
    )
    text_quote: P5TextQuoteSelector
    text_position: P5TextPositionSelector


class P5JsonlValueSelector(P5JsonValueSelector):
    type: Literal["JsonlValueSelector"] = "JsonlValueSelector"
    record_index: int = Field(ge=0)
    line_number: int = Field(ge=1)


class P5CsvValueSelector(P5JsonValueSelector):
    type: Literal["CsvValueSelector"] = "CsvValueSelector"
    record_index: int = Field(ge=0)
    header_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    column_name: str


class P5EvidenceRecord(FrozenModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=0)
    catalog_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_id: str
    query_term: str
    claim_relevance: tuple[Literal["payout_basis", "special_two_sided_49_policy"], ...]
    source_path: str
    source_role: Literal[
        "captured_page_snapshot",
        "package_manifest",
        "human_context_hypothesis",
        "derived_catalog",
    ]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_kind: Literal["text", "json", "jsonl", "csv"]
    selector: P5TextSelectorSet | P5JsonValueSelector | P5JsonlValueSelector | P5CsvValueSelector
    selected_text: str
    selected_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    interpretation_code: Literal["marker_only_not_semantic_resolution"] = (
        "marker_only_not_semantic_resolution"
    )
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class P5JudgeGateResult(FrozenModel):
    schema_version: Literal[1] = 1
    catalog_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_status: Literal["EVIDENCE_CATALOG_VERIFIED"] = "EVIDENCE_CATALOG_VERIFIED"
    semantics_status: Literal["SEMANTICS_STILL_UNRESOLVED", "SEMANTICS_CONFLICT_RECORDED"]
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    rule_claim_statuses: dict[
        Literal["payout_basis", "special_two_sided_49_policy"],
        Literal["INSUFFICIENT_LOCAL_EVIDENCE", "CONFLICT"],
    ]
    checks: dict[str, bool]
    source_truth_verified: Literal[False] = False
    semantics_compilation_permitted: Literal[False] = False
    historical_price_availability_verified: Literal[False] = False
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False
    whole_project_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_p5_gate(self) -> P5JudgeGateResult:
        expected = {"payout_basis", "special_two_sided_49_policy"}
        if set(self.rule_claim_statuses) != expected:
            raise ValueError("P5 Judge must retain both unresolved RuleClaims")
        if not self.checks or not all(self.checks.values()):
            raise ValueError("P5 Judge requires every catalog integrity check")
        conflict = "CONFLICT" in self.rule_claim_statuses.values()
        if conflict != (self.semantics_status == "SEMANTICS_CONFLICT_RECORDED"):
            raise ValueError("P5 semantics status must agree with the claim register")
        return self


class P5TombstoneRecord(FrozenModel):
    schema_version: Literal[1] = 1
    catalog_id: str
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tombstone_id: str
    subject: Literal[
        "operator_rule_truth",
        "semantic_resolution",
        "economic_edge_or_ranking",
        "real_money_action",
        "quote_fill_liability",
        "whole_project_completion",
    ]
    status: Literal["BLOCKED_BY_EVIDENCE"] = "BLOCKED_BY_EVIDENCE"
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
