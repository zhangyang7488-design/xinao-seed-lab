"""Public value models and the advisory coordination-benefit router."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Actor(StrEnum):
    USER = "user"
    GROK = "grok_4_5"
    CODEX = "codex"
    ADMIN = "admin"


class ThreadState(StrEnum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EACH_CLOSED = "EACH_CLOSED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class TaskState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class RouteSignals(BaseModel):
    """Signals for an advisory decision; values are normalized to 0..1."""

    model_config = ConfigDict(extra="forbid")

    uncertainty: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    impact: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    disagreement: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    complementarity: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    parallelism: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    novelty: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    latency_cost: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    coordination_cost: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    context_cost: float = Field(0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    needs_artifact: bool = False
    requested_mode: (
        Literal["direct", "discuss", "task", "discuss_then_task", "background", "hybrid"] | None
    ) = None
    benefit_weights: dict[str, float] | None = None
    cost_weights: dict[str, float] | None = None
    discussion_margin: float = Field(0.0, ge=-1.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_contextual_weights(self) -> RouteSignals:
        allowed_benefit = {
            "uncertainty",
            "impact",
            "disagreement",
            "complementarity",
            "parallelism",
            "novelty",
        }
        allowed_cost = {"latency", "coordination", "context"}
        for label, weights, allowed in (
            ("benefit_weights", self.benefit_weights, allowed_benefit),
            ("cost_weights", self.cost_weights, allowed_cost),
        ):
            if weights is None:
                continue
            unknown = set(weights) - allowed
            invalid = (
                unknown
                or any(not math.isfinite(value) or value < 0 for value in weights.values())
                or sum(weights.values()) <= 0
            )
            if invalid:
                raise ValueError(
                    f"{label} must use known keys, non-negative values, and positive total; "
                    f"unknown={sorted(unknown)}"
                )
        # All-zero signals are valid and intentionally recommend the lowest-overhead path.
        return self


class RouteAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["direct", "discuss", "task", "discuss_then_task", "background", "hybrid"]
    expected_gain: float
    expected_cost: float
    net_benefit: float
    overridden_by_request: bool
    advisory_only: bool = True
    policy_id: str = "replaceable_contextual_net_benefit_v1"
    score_controls_execution: bool = False
    reasons: list[str]
    hard_invariants: list[str]


def assess_route(signals: RouteSignals) -> RouteAssessment:
    """Return an explainable recommendation that never gates execution.

    The caller may provide task-specific weights and a margin. Without them, every normalized
    signal is weighted equally; there is no globally privileged fixed score. User choice always
    wins, and callers remain free to override the recommendation.
    """

    reasons: list[str] = []
    positive = {
        "uncertainty": signals.uncertainty,
        "impact": signals.impact,
        "disagreement": signals.disagreement,
        "complementarity": signals.complementarity,
        "parallelism": signals.parallelism,
        "novelty": signals.novelty,
    }
    costly = {
        "latency": signals.latency_cost,
        "coordination": signals.coordination_cost,
        "context": signals.context_cost,
    }
    benefit_weights = signals.benefit_weights or {name: 1.0 for name in positive}
    cost_weights = signals.cost_weights or {name: 1.0 for name in costly}
    gain = sum(positive[name] * weight for name, weight in benefit_weights.items()) / sum(
        benefit_weights.values()
    )
    cost = sum(costly[name] * weight for name, weight in cost_weights.items()) / sum(cost_weights.values())
    net = gain - cost
    if max(positive.values()) > 0:
        reasons.append("highest_gain_signal=" + max(positive, key=positive.get))
    if max(costly.values()) > 0:
        reasons.append("highest_cost_signal=" + max(costly, key=costly.get))

    if signals.requested_mode:
        recommendation = signals.requested_mode
        reasons.append("explicit_current_request")
        overridden = True
    elif (
        signals.complementarity >= 0.55
        and signals.parallelism >= 0.55
        and (signals.novelty >= 0.4 or signals.needs_artifact)
    ):
        # T6 混合：窗内核心 + 后台检索/回测；仍 advisory
        recommendation = "hybrid"
        reasons.append("hybrid_window_core_plus_background_aux")
        overridden = False
    elif (
        signals.parallelism >= 0.7
        and signals.uncertainty <= 0.35
        and signals.latency_cost <= 0.45
        and not (signals.disagreement >= 0.7 and signals.complementarity >= 0.7)
    ):
        # T6 后台：可丢/批处理/并行友好；仍 advisory，不硬闸执行
        recommendation = "background"
        reasons.append("disposable_or_batch_background_fit")
        overridden = False
    elif signals.needs_artifact:
        recommendation = "discuss_then_task" if net > signals.discussion_margin else "task"
        reasons.append("durable_artifact_required")
        overridden = False
    elif net > signals.discussion_margin:
        recommendation = "discuss"
        reasons.append("second_brain_expected_value_positive")
        overridden = False
    else:
        recommendation = "direct"
        reasons.append("coordination_overhead_not_justified")
        overridden = False

    return RouteAssessment(
        recommendation=recommendation,
        expected_gain=round(gain, 4),
        expected_cost=round(cost, 4),
        net_benefit=round(net, 4),
        overridden_by_request=overridden,
        reasons=[
            *reasons,
            "contextual_weights" if signals.benefit_weights or signals.cost_weights else "equal_weight_prior",
            f"discussion_margin={signals.discussion_margin}",
        ],
        hard_invariants=[
            "current_user_authority",
            "actor_permissions",
            "valid_state_transition",
            "idempotency_and_fencing",
            "evidence_before_completion_claim",
        ],
    )
