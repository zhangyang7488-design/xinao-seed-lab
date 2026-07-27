"""Deterministic Day-1 policies for the first non-vacuous research slice."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.decision import DecisionGateInput, DecisionKind
from xinao.science.portfolio import (
    PolicyCandidateVersion,
    PolicyRole,
)
from xinao.world.builder import DrawRecord

ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY1_POLICY_REFS = (
    "policy.day1.baseline-rolling-marginal-w90.v1",
    "policy.day1.no-action.v1",
    "policy.day1.null-target-prf.v1",
    "policy.day1.substantive-multiscale-overlap-7-14-28.v1",
)
NULL_SEED_REF = "day1-null-target-prf-seed-20260727-v1"


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


class SpecialNumberObservation(BaseModel):
    """One cutoff-safe special-number observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expect: str = Field(pattern=r"^\d{7}$")
    open_time: datetime
    special_number: int = Field(ge=1, le=49)
    source_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        _require_aware(self.open_time, "observation open_time")
        return self


class PolicyDecision(BaseModel):
    """Compiled policy output for one target before mechanical decision gating."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: str = Field(min_length=1)
    requested_decision_kind: DecisionKind
    selected_number: int = Field(ge=1, le=49)


class Day1PolicyCompilation(BaseModel):
    """Hash-sealed policy versions and their one-target decision outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.day1_policy_compilation.v1"] = (
        "xinao.day1_policy_compilation.v1"
    )
    target_ref: str = Field(min_length=1)
    horizon_draws: int = Field(ge=1, le=7)
    knowledge_cutoff: datetime
    history_count: int = Field(ge=180)
    history_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_target_refs: tuple[str, ...] = Field(min_length=32, max_length=64)
    policies: tuple[PolicyCandidateVersion, ...] = Field(min_length=4, max_length=4)
    decisions: tuple[PolicyDecision, ...] = Field(min_length=4, max_length=4)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_compilation(self) -> Self:
        _require_aware(self.knowledge_cutoff, "policy compilation knowledge_cutoff")
        policy_refs = tuple(policy.policy_ref for policy in self.policies)
        if policy_refs != tuple(sorted(policy_refs)) or policy_refs != DAY1_POLICY_REFS:
            raise ValueError("Day-1 policy identities or order drifted")
        if any(policy.content_hash is None for policy in self.policies):
            raise ValueError("Day-1 policies must be hash sealed")
        decision_refs = tuple(decision.policy_ref for decision in self.decisions)
        if decision_refs != policy_refs:
            raise ValueError("Day-1 decisions do not cover the exact policy set")
        if len(set(self.probe_target_refs)) != len(self.probe_target_refs):
            raise ValueError("Day-1 probe target identities must be unique")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("Day-1 compilation content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> Day1PolicyCompilation:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class PolicyHashBinding(BaseModel):
    """ProtocolPin binding to one immutable policy version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: PolicyRole


class RuntimeSourceBinding(BaseModel):
    """ProtocolPin binding to one exact execution-source file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MultipolicyProtocolPin(BaseModel):
    """Small protocol pin for one freeze-all target slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.multipolicy_protocol_pin.v1"] = (
        "xinao.multipolicy_protocol_pin.v1"
    )
    protocol_pin_ref: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    evidence_class: Literal["EXECUTION_RECOVERY_ONLY", "PROSPECTIVE_EXPERIMENTAL"]
    active_parent_ref: str = Field(min_length=1)
    active_parent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_ref: Literal["macaujc-source-authority-contract.v1"]
    source_contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_ref: str = Field(min_length=1)
    source_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_captured_at: datetime
    trial_ledger_anchor_ref: str = Field(min_length=1)
    trial_ledger_anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ledger_prefix_entry_count: int = Field(ge=4)
    trial_ledger_prefix_entries_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_question: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    target_open_time: datetime
    knowledge_cutoff: datetime
    frozen_at: datetime
    freeze_deadline: datetime
    required_roles: tuple[PolicyRole, ...] = Field(min_length=4, max_length=4)
    policy_bindings: tuple[PolicyHashBinding, ...] = Field(min_length=4, max_length=4)
    runtime_source_bindings: tuple[RuntimeSourceBinding, ...] = Field(min_length=7)
    scoring_rule_ref: Literal["special-number-rule.v1"] = "special-number-rule.v1"
    settlement_function_ref: Literal["special-number-settlement.v1"] = (
        "special-number-settlement.v1"
    )
    normalized_shadow_exposure: Literal["1.0000"] = "1.0000"
    outcome_access: Literal[False] = False
    real_money_authorized: Literal[False] = False
    claim_ceiling: Literal["E2"] = "E2"
    residual_axes: tuple[str, ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)
    next_move: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_pin(self) -> Self:
        for label, value in (
            ("source_captured_at", self.source_captured_at),
            ("target_open_time", self.target_open_time),
            ("knowledge_cutoff", self.knowledge_cutoff),
            ("frozen_at", self.frozen_at),
            ("freeze_deadline", self.freeze_deadline),
        ):
            _require_aware(value, label)
        if not (
            self.source_captured_at <= self.knowledge_cutoff <= self.frozen_at
            <= self.freeze_deadline < self.target_open_time
        ):
            raise ValueError("MultipolicyProtocolPin temporal boundaries are invalid")
        expected_roles = tuple(PolicyRole)
        if self.required_roles != expected_roles:
            raise ValueError("MultipolicyProtocolPin required roles drifted")
        binding_refs = tuple(binding.policy_ref for binding in self.policy_bindings)
        if binding_refs != DAY1_POLICY_REFS:
            raise ValueError("MultipolicyProtocolPin policy bindings drifted")
        if {binding.role for binding in self.policy_bindings} != set(PolicyRole):
            raise ValueError("MultipolicyProtocolPin policy role bindings are incomplete")
        if len(set(binding.content_hash for binding in self.policy_bindings)) != 4:
            raise ValueError("MultipolicyProtocolPin policy content hashes are not unique")
        runtime_refs = tuple(binding.ref for binding in self.runtime_source_bindings)
        if runtime_refs != tuple(sorted(runtime_refs)) or len(set(runtime_refs)) != len(
            runtime_refs
        ):
            raise ValueError(
                "MultipolicyProtocolPin runtime source bindings must be sorted and unique"
            )
        if len(set(self.residual_axes)) != len(self.residual_axes):
            raise ValueError("MultipolicyProtocolPin residual axes must be unique")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("MultipolicyProtocolPin content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> MultipolicyProtocolPin:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


def parse_macaujc_history_response(
    raw: bytes,
    *,
    knowledge_cutoff: datetime,
    year_prefix: str = "2026",
) -> tuple[SpecialNumberObservation, ...]:
    """Parse a pinned annual response and retain only cutoff-safe rows."""

    _require_aware(knowledge_cutoff, "history knowledge_cutoff")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("macaujc history response is not UTF-8 JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("result") is not True
        or payload.get("code") != 200
    ):
        raise ValueError("macaujc history response envelope is not successful")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("macaujc history response data is not an array")
    observations: list[SpecialNumberObservation] = []
    for row in data:
        if not isinstance(row, dict) or not str(row.get("expect", "")).startswith(year_prefix):
            continue
        try:
            open_time = datetime.strptime(str(row["openTime"]), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ASIA_SHANGHAI
            )
            numbers = tuple(int(value) for value in str(row["openCode"]).split(","))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("macaujc history row fields are invalid") from exc
        if (
            len(numbers) != 7
            or len(set(numbers)) != 7
            or any(not 1 <= value <= 49 for value in numbers)
        ):
            raise ValueError("macaujc openCode must contain seven unique values from 1 to 49")
        if open_time >= knowledge_cutoff:
            continue
        observations.append(
            SpecialNumberObservation(
                expect=str(row["expect"]),
                open_time=open_time,
                special_number=numbers[-1],
                source_row_hash=canonical_sha256(row),
            )
        )
    return _validate_observations(observations)


def observations_from_draws(
    draws: Sequence[DrawRecord],
) -> tuple[SpecialNumberObservation, ...]:
    """Convert the fixed formal dataset into the same cutoff-safe observation type."""

    observations = []
    for draw in draws:
        open_time = datetime.strptime(draw.openTime, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ASIA_SHANGHAI
        )
        observations.append(
            SpecialNumberObservation(
                expect=draw.expect,
                open_time=open_time,
                special_number=draw.special_number,
                source_row_hash=canonical_sha256(draw.model_dump(mode="json")),
            )
        )
    return _validate_observations(observations)


def _validate_observations(
    observations: Sequence[SpecialNumberObservation],
) -> tuple[SpecialNumberObservation, ...]:
    ordered = tuple(sorted(observations, key=lambda item: (item.open_time, item.expect)))
    if len(ordered) < 180:
        raise ValueError("Day-1 policies require at least 180 cutoff-safe observations")
    if len({item.expect for item in ordered}) != len(ordered):
        raise ValueError("history observations contain duplicate expect identities")
    if any(left.open_time >= right.open_time for left, right in pairwise(ordered)):
        raise ValueError("history observation times must be strictly increasing")
    return ordered


def null_target_prediction(target_ref: str) -> int:
    """Outcome-independent deterministic target PRF negative control."""

    digest = canonical_sha256({"seed_ref": NULL_SEED_REF, "target_ref": target_ref})
    return int(digest[:16], 16) % 49 + 1


def rolling_marginal_prediction(values: Sequence[int], *, window: int = 90) -> int:
    """Most-frequent rolling marginal with a smallest-number tie break."""

    if len(values) < window:
        raise ValueError("rolling marginal history is shorter than its frozen window")
    counts = Counter(values[-window:])
    maximum = max(counts.get(number, 0) for number in range(1, 50))
    return min(number for number in range(1, 50) if counts.get(number, 0) == maximum)


def multiscale_overlap_prediction(
    values: Sequence[int],
    *,
    windows: tuple[int, ...] = (7, 14, 28),
    top_k: int = 7,
) -> int:
    """Bounded set-overlap challenger across three frozen rolling scales."""

    if windows != (7, 14, 28) or top_k != 7:
        raise ValueError("multiscale overlap call differs from the frozen Day-1 policy")
    if len(values) < max(windows):
        raise ValueError("multiscale overlap history is shorter than its largest scale")
    membership = Counter({number: 0 for number in range(1, 50)})
    weighted_frequency = Counter({number: 0 for number in range(1, 50)})
    for window in windows:
        counts = Counter(values[-window:])
        ranked = sorted(range(1, 50), key=lambda number: (-counts.get(number, 0), number))
        for number in ranked[:top_k]:
            membership[number] += 1
        for number in range(1, 50):
            weighted_frequency[number] += counts.get(number, 0) * (28 // window)
    return max(
        range(1, 50),
        key=lambda number: (membership[number], weighted_frequency[number], -number),
    )


def _probe_traces(
    observations: tuple[SpecialNumberObservation, ...],
) -> tuple[tuple[str, ...], dict[PolicyRole, tuple[str, ...]]]:
    start = max(90, len(observations) - 64)
    probe = observations[start:]
    if len(probe) < 32:
        raise ValueError("Day-1 behavioral probe requires at least 32 targets")
    traces: dict[PolicyRole, list[str]] = {role: [] for role in PolicyRole}
    for index in range(start, len(observations)):
        prefix = tuple(item.special_number for item in observations[:index])
        target_ref = f"macaujc2/expect/{observations[index].expect}"
        traces[PolicyRole.NO_ACTION].append("NO_ACTION")
        traces[PolicyRole.NEG_CONTROL].append(f"{null_target_prediction(target_ref):02d}")
        traces[PolicyRole.BASELINE].append(f"{rolling_marginal_prediction(prefix):02d}")
        traces[PolicyRole.SUBSTANTIVE].append(f"{multiscale_overlap_prediction(prefix):02d}")
    return (
        tuple(item.expect for item in probe),
        {role: tuple(values) for role, values in traces.items()},
    )


def build_day1_policy_compilation(
    observations: Sequence[SpecialNumberObservation],
    *,
    target_ref: str,
    knowledge_cutoff: datetime,
    horizon_draws: int,
) -> Day1PolicyCompilation:
    """Compile NO_ACTION, null, baseline, and overlap challenger policies."""

    history = _validate_observations(observations)
    _require_aware(knowledge_cutoff, "policy compilation knowledge_cutoff")
    if history[-1].open_time >= knowledge_cutoff:
        raise ValueError("policy compilation history is not strictly before its cutoff")
    if not 1 <= horizon_draws <= 7:
        raise ValueError("Day-1 target horizon must be between one and seven draws")
    probe_refs, traces = _probe_traces(history)
    history_values = tuple(item.special_number for item in history)
    implementation_sha256 = sha256(Path(__file__).read_bytes()).hexdigest()
    decisions_by_role = {
        PolicyRole.NO_ACTION: (DecisionKind.NO_ACTION, 1),
        PolicyRole.NEG_CONTROL: (
            DecisionKind.FROZEN_EXPERIMENTAL_SHADOW,
            null_target_prediction(target_ref),
        ),
        PolicyRole.BASELINE: (
            DecisionKind.FROZEN_EXPERIMENTAL_SHADOW,
            rolling_marginal_prediction(history_values),
        ),
        PolicyRole.SUBSTANTIVE: (
            DecisionKind.FROZEN_EXPERIMENTAL_SHADOW,
            multiscale_overlap_prediction(history_values),
        ),
    }
    definitions: dict[str, tuple[PolicyRole, str, tuple[str, ...], str, str, dict[str, Any]]] = {
        DAY1_POLICY_REFS[0]: (
            PolicyRole.BASELINE,
            "ROLLING_EMPIRICAL_MARGINAL",
            ("special_number_before_knowledge_cutoff",),
            "NEVER_ABSTAIN_EXPERIMENTAL_SHADOW",
            "decision-map.rolling-marginal-most-w90-smallest-tie.v1",
            {"rolling_window": 90, "direction": "most_frequent", "tie_break": "smallest"},
        ),
        DAY1_POLICY_REFS[1]: (
            PolicyRole.NO_ACTION,
            "ALWAYS_ABSTAIN",
            ("target_identity_only",),
            "ALWAYS_NO_ACTION",
            "decision-map.always-no-action.v1",
            {"action": "NO_ACTION"},
        ),
        DAY1_POLICY_REFS[2]: (
            PolicyRole.NEG_CONTROL,
            "TARGET_IDENTITY_PRF_NULL",
            ("target_identity_only",),
            "NEVER_ABSTAIN_EXPERIMENTAL_SHADOW",
            "decision-map.target-prf-null.v1",
            {"seed_ref": NULL_SEED_REF, "mapping": "sha256-prefix-mod-49-plus-1"},
        ),
        DAY1_POLICY_REFS[3]: (
            PolicyRole.SUBSTANTIVE,
            "MULTISCALE_SET_OVERLAP_MOTIF",
            ("special_number_before_knowledge_cutoff",),
            "NEVER_ABSTAIN_EXPERIMENTAL_SHADOW",
            "decision-map.multiscale-overlap-7-14-28-top7.v1",
            {
                "windows": [7, 14, 28],
                "top_k": 7,
                "score_order": ["set_membership_count", "normalized_frequency", "smallest"],
                "family_truth_status": "FALSIFIABLE_UNCONFIRMED",
            },
        ),
    }
    policies: list[PolicyCandidateVersion] = []
    decisions: list[PolicyDecision] = []
    for policy_ref in DAY1_POLICY_REFS:
        role, mechanism, features, abstention, decision_map, config = definitions[policy_ref]
        trace = traces[role]
        policies.append(
            PolicyCandidateVersion(
                policy_ref=policy_ref,
                family_id={
                    PolicyRole.NO_ACTION: "F-NO-SIGNAL-POLICY-v1",
                    PolicyRole.NEG_CONTROL: "F-TARGET-PRF-NULL-v1",
                    PolicyRole.BASELINE: "F-MARGINAL-FREQ-v1",
                    PolicyRole.SUBSTANTIVE: "F-WAVE-OVERLAP-v1",
                }[role],
                role=role,
                knowledge_cutoff=knowledge_cutoff,
                decision_signature={
                    "mechanism": mechanism,
                    "feature_visibility": features,
                    "time_scale": f"horizon_draws={horizon_draws}",
                    "update_policy": "FROZEN_THROUGH_TARGET",
                    "abstention_rule": abstention,
                    "action_support": (
                        "NONE" if role == PolicyRole.NO_ACTION else "SPECIAL_NUMBER_1_TO_49"
                    ),
                    "decision_map_ref": decision_map,
                    "probe_target_count": len(trace),
                    "probe_action_count": 0 if role == PolicyRole.NO_ACTION else len(trace),
                    "probe_trace_hash": canonical_sha256(trace),
                },
                semantic_config={
                    **config,
                    "target_horizon_draws": horizon_draws,
                    "knowledge_cutoff": knowledge_cutoff.isoformat(),
                    "outcome_access": False,
                    "implementation_ref": "src/xinao/science/day1_portfolio.py",
                    "implementation_sha256": implementation_sha256,
                    "probe_target_start": probe_refs[0],
                    "probe_target_end": probe_refs[-1],
                },
            ).with_content_hash()
        )
        decision_kind, selected_number = decisions_by_role[role]
        decisions.append(
            PolicyDecision(
                policy_ref=policy_ref,
                requested_decision_kind=decision_kind,
                selected_number=selected_number,
            )
        )
    return Day1PolicyCompilation(
        target_ref=target_ref,
        horizon_draws=horizon_draws,
        knowledge_cutoff=knowledge_cutoff,
        history_count=len(history),
        history_identity_hash=canonical_sha256(
            [
                {
                    "expect": item.expect,
                    "open_time": item.open_time,
                    "source_row_hash": item.source_row_hash,
                }
                for item in history
            ]
        ),
        probe_target_refs=probe_refs,
        policies=tuple(policies),
        decisions=tuple(decisions),
    ).with_content_hash()


def build_day1_gates(
    *,
    pin: MultipolicyProtocolPin,
    compilation: Day1PolicyCompilation,
    information_set_ref: str,
    information_set_hash: str,
) -> dict[str, DecisionGateInput]:
    """Build exact existing DecisionGateInput objects for all Day-1 policies."""

    if pin.content_hash is None or compilation.content_hash is None:
        raise ValueError("ProtocolPin and policy compilation must be hash sealed")
    policy_hashes = {binding.policy_ref: binding.content_hash for binding in pin.policy_bindings}
    if policy_hashes != {
        policy.policy_ref: policy.content_hash for policy in compilation.policies
    }:
        raise ValueError("ProtocolPin policy bindings differ from policy compilation")
    decisions = {decision.policy_ref: decision for decision in compilation.decisions}
    gates: dict[str, DecisionGateInput] = {}
    for policy in compilation.policies:
        decision = decisions[policy.policy_ref]
        no_action = decision.requested_decision_kind == DecisionKind.NO_ACTION
        gates[policy.policy_ref] = DecisionGateInput(
            candidate_ref=policy.policy_ref,
            requested_decision_kind=decision.requested_decision_kind,
            candidate_qualification=None if no_action else "SHADOW_EXPERIMENTAL",
            adjudicated_decision_kinds=("FROZEN_EXPERIMENTAL_SHADOW", "NO_ACTION"),
            court_verdict_bundle_ref=f"court-bundle.day1/{policy.policy_ref}",
            court_verdict_bundle_content_hash=canonical_sha256(
                {
                    "policy_ref": policy.policy_ref,
                    "role": policy.role,
                    "experimental_only": True,
                    "trial_registered": True,
                }
            ),
            protocol_pin_ref=pin.protocol_pin_ref,
            protocol_pin_sha256=pin.content_hash,
            information_set_ref=information_set_ref,
            information_set_hash=information_set_hash,
            validation_report_ref=f"validation.day1/{policy.policy_ref}",
            validation_output_hash=canonical_sha256(
                {
                    "policy_ref": policy.policy_ref,
                    "policy_hash": policy.content_hash,
                    "verdict": "EXPERIMENTAL_SHADOW_ONLY",
                    "claim_ceiling": "E2",
                }
            ),
            validation_verdict="ACTION",
            baseline_ref="baseline-odds-water.v1",
            baseline_active=True,
            rule_ref="special-number-rule.v1",
            rule_active=True,
            odds_version_ref="baseline-odds-water.v1",
            cost_version_ref="cost.zero-shadow.v1",
            friction_version_ref="friction.zero-shadow.v1",
            exposure_policy_ref="shadow-exposure.normalized-unit.v1",
            target_ref=pin.target_ref,
            target_window_start=pin.target_open_time,
            target_window_end=pin.target_open_time,
            target_open_time=pin.target_open_time,
            freeze_deadline=pin.freeze_deadline,
            knowledge_cutoff=pin.knowledge_cutoff,
            compiled_at=pin.frozen_at,
            panel="A",
            selected_number=decision.selected_number,
            stake=pin.normalized_shadow_exposure,
            lower_expected_net="0.0000",
            estimated_cost="0.0000",
            risk_limit=pin.normalized_shadow_exposure,
        )
    return gates


__all__ = [
    "ASIA_SHANGHAI",
    "DAY1_POLICY_REFS",
    "NULL_SEED_REF",
    "Day1PolicyCompilation",
    "MultipolicyProtocolPin",
    "PolicyDecision",
    "PolicyHashBinding",
    "RuntimeSourceBinding",
    "SpecialNumberObservation",
    "build_day1_gates",
    "build_day1_policy_compilation",
    "multiscale_overlap_prediction",
    "null_target_prediction",
    "observations_from_draws",
    "parse_macaujc_history_response",
    "rolling_marginal_prediction",
]
