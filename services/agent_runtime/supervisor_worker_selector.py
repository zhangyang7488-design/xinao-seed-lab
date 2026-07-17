"""Pure, deterministic selection for an already-authorized worker frontier.

This module only evaluates candidate facts supplied by the supervisor.  It
does not discover candidates, perform I/O, call a provider, persist a choice,
or invent a provider/model fallback.  A candidate identity is the exact
``provider/profile/model/transport`` tuple; no field may be omitted or aliased.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from services.agent_runtime.provider_routing_preference import (
    ProviderCapacitySignal,
    resolve_provider_preference,
)

DECISION_SELECTED = "selected"
DECISION_NO_ACTION = "no_action"
DECISION_REQUIRED = "decision_required"

_EXCLUSION_ORDER = (
    "not_declared_active",
    "unhealthy",
    "no_positive_benefit",
    "context_inheritance_unsupported",
)


def _required_identity_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate identity field {field!r} must be a non-empty string")
    return value.strip()


def _boolean_fact(payload: Mapping[str, Any], field: str, *, default: bool = False) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise TypeError(f"candidate fact {field!r} must be a bool")
    return value


@dataclass(frozen=True, order=True, slots=True)
class CandidateIdentity:
    """Exact identity of one selectable execution candidate."""

    provider_id: str
    profile_ref: str
    model_id: str
    transport_id: str

    def __post_init__(self) -> None:
        for field in ("provider_id", "profile_ref", "model_id", "transport_id"):
            value = _required_identity_text(getattr(self, field), field=field)
            object.__setattr__(self, field, value)

    @classmethod
    def from_value(cls, value: CandidateIdentity | Mapping[str, Any]) -> CandidateIdentity:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("candidate identity must be CandidateIdentity or a mapping")
        nested = value.get("identity")
        payload = nested if isinstance(nested, Mapping) else value
        return cls(
            provider_id=_required_identity_text(payload.get("provider_id"), field="provider_id"),
            profile_ref=_required_identity_text(payload.get("profile_ref"), field="profile_ref"),
            model_id=_required_identity_text(payload.get("model_id"), field="model_id"),
            transport_id=_required_identity_text(payload.get("transport_id"), field="transport_id"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "profile_ref": self.profile_ref,
            "model_id": self.model_id,
            "transport_id": self.transport_id,
        }


@dataclass(frozen=True, slots=True)
class WorkerCandidate:
    """Supervisor-observed facts for one exact candidate identity."""

    identity: CandidateIdentity
    declared_active: bool
    healthy: bool
    positive_benefit: bool
    context_capable: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CandidateIdentity):
            raise TypeError("identity must be CandidateIdentity")
        for field in (
            "declared_active",
            "healthy",
            "positive_benefit",
            "context_capable",
        ):
            if not isinstance(getattr(self, field), bool):
                raise TypeError(f"candidate fact {field!r} must be a bool")

    @classmethod
    def from_value(cls, value: WorkerCandidate | Mapping[str, Any]) -> WorkerCandidate:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("worker candidate must be WorkerCandidate or a mapping")
        return cls(
            identity=CandidateIdentity.from_value(value),
            declared_active=_boolean_fact(value, "declared_active"),
            healthy=_boolean_fact(value, "healthy"),
            positive_benefit=_boolean_fact(value, "positive_benefit"),
            context_capable=_boolean_fact(value, "context_capable"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.identity.as_dict(),
            "declared_active": self.declared_active,
            "healthy": self.healthy,
            "positive_benefit": self.positive_benefit,
            "context_capable": self.context_capable,
        }


def _normalize_candidates(
    candidates: Iterable[WorkerCandidate | Mapping[str, Any]],
) -> list[WorkerCandidate]:
    normalized = [WorkerCandidate.from_value(candidate) for candidate in candidates]
    normalized.sort(key=lambda candidate: candidate.identity)
    identities = [candidate.identity for candidate in normalized]
    if len(set(identities)) != len(identities):
        raise ValueError("candidate identities must be unique")
    return normalized


def _exclusion_reasons(
    candidate: WorkerCandidate,
    *,
    context_inheritance_required: bool,
) -> list[str]:
    reasons: set[str] = set()
    if not candidate.declared_active:
        reasons.add("not_declared_active")
    if not candidate.healthy:
        reasons.add("unhealthy")
    if not candidate.positive_benefit:
        reasons.add("no_positive_benefit")
    if context_inheritance_required and not candidate.context_capable:
        reasons.add("context_inheritance_unsupported")
    return [reason for reason in _EXCLUSION_ORDER if reason in reasons]


def _result(
    *,
    decision: str,
    selected: WorkerCandidate | None,
    eligible: list[WorkerCandidate],
    excluded: list[tuple[WorkerCandidate, list[str]]],
    decision_reason: str,
    provider_preference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "selected_candidate": selected.as_dict() if selected is not None else None,
        "eligible_candidates": [candidate.as_dict() for candidate in eligible],
        "excluded_reasons": [
            {"candidate": candidate.as_dict(), "reasons": reasons}
            for candidate, reasons in excluded
        ],
        "decision_reason": decision_reason,
        "provider_preference": dict(provider_preference or {}),
    }


def select_supervisor_worker(
    candidates: Iterable[WorkerCandidate | Mapping[str, Any]],
    *,
    task_separable: bool,
    supervisor_choice: CandidateIdentity | Mapping[str, Any] | None = None,
    context_inheritance_required: bool = False,
    stable_preferred_provider_id: str = "",
    capacity_by_provider: Mapping[
        str, ProviderCapacitySignal | Mapping[str, Any]
    ]
    | None = None,
) -> dict[str, Any]:
    """Select a candidate only when current facts make the choice deterministic.

    Selection precedence is explicit supervisor choice, sole eligibility, then
    the provider-agnostic stable/capacity preference policy.  Provider choice
    never guesses a model or transport: multiple exact candidates within the
    preferred provider still return ``decision_required``.
    """

    for field, value in (
        ("task_separable", task_separable),
        ("context_inheritance_required", context_inheritance_required),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{field} must be a bool")
    if not isinstance(stable_preferred_provider_id, str):
        raise TypeError("stable_preferred_provider_id must be a string")

    normalized = _normalize_candidates(candidates)
    eligible: list[WorkerCandidate] = []
    excluded: list[tuple[WorkerCandidate, list[str]]] = []
    for candidate in normalized:
        reasons = _exclusion_reasons(
            candidate,
            context_inheritance_required=context_inheritance_required,
        )
        if reasons:
            excluded.append((candidate, reasons))
        else:
            eligible.append(candidate)

    if not task_separable:
        return _result(
            decision=DECISION_NO_ACTION,
            selected=None,
            eligible=eligible,
            excluded=excluded,
            decision_reason="task_not_separable",
        )
    if not eligible:
        reason = (
            "no_positive_benefit_candidate"
            if normalized and not any(candidate.positive_benefit for candidate in normalized)
            else "no_eligible_candidate"
        )
        return _result(
            decision=DECISION_NO_ACTION,
            selected=None,
            eligible=eligible,
            excluded=excluded,
            decision_reason=reason,
        )

    if supervisor_choice is not None:
        choice = CandidateIdentity.from_value(supervisor_choice)
        selected = next(
            (candidate for candidate in eligible if candidate.identity == choice),
            None,
        )
        if selected is not None:
            return _result(
                decision=DECISION_SELECTED,
                selected=selected,
                eligible=eligible,
                excluded=excluded,
                decision_reason="explicit_supervisor_choice",
            )
        return _result(
            decision=DECISION_REQUIRED,
            selected=None,
            eligible=eligible,
            excluded=excluded,
            decision_reason="explicit_supervisor_choice_not_eligible",
        )

    if len(eligible) == 1:
        return _result(
            decision=DECISION_SELECTED,
            selected=eligible[0],
            eligible=eligible,
            excluded=excluded,
            decision_reason="sole_eligible_candidate",
        )

    provider_preference = resolve_provider_preference(
        (candidate.identity.provider_id for candidate in eligible),
        stable_preferred_provider_id=stable_preferred_provider_id,
        capacity_by_provider=capacity_by_provider,
    )
    preferred_provider = str(provider_preference.get("preferred_provider_id") or "")
    if preferred_provider:
        preferred = [
            candidate
            for candidate in eligible
            if candidate.identity.provider_id == preferred_provider
        ]
        if len(preferred) == 1:
            basis = set(provider_preference.get("preference_basis") or [])
            return _result(
                decision=DECISION_SELECTED,
                selected=preferred[0],
                eligible=eligible,
                excluded=excluded,
                decision_reason=(
                    "stable_provider_preference"
                    if "stable_default" in basis
                    else "capacity_provider_preference"
                ),
                provider_preference=provider_preference,
            )
        if preferred:
            return _result(
                decision=DECISION_REQUIRED,
                selected=None,
                eligible=eligible,
                excluded=excluded,
                decision_reason="preferred_provider_requires_exact_candidate_choice",
                provider_preference=provider_preference,
            )

    return _result(
        decision=DECISION_REQUIRED,
        selected=None,
        eligible=eligible,
        excluded=excluded,
        decision_reason="insufficient_facts_for_multiple_candidates",
        provider_preference=provider_preference,
    )
