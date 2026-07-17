"""Provider-agnostic preference resolution for eligible model workers.

The policy layer consumes stable operator preference and normalized capacity
telemetry.  It neither invokes a provider nor selects a model or transport;
those remain adapter and exact-candidate decisions owned by the supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_percent(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number or null")
    normalized = float(value)
    if not 0 <= normalized <= 100:
        raise ValueError(f"{field} must be between 0 and 100")
    return normalized


def _optional_reset(value: object, *, field: str) -> tuple[str, datetime | None]:
    if value in (None, ""):
        return "", None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO-8601 string or null")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return raw, parsed


@dataclass(frozen=True, slots=True)
class ProviderCapacitySignal:
    """Current advisory capacity for one provider identity."""

    provider_id: str
    remaining_percent: float | None = None
    reset_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_id",
            _required_text(self.provider_id, field="provider_id"),
        )
        object.__setattr__(
            self,
            "remaining_percent",
            _optional_percent(self.remaining_percent, field="remaining_percent"),
        )
        reset_at, _ = _optional_reset(self.reset_at, field="reset_at")
        object.__setattr__(self, "reset_at", reset_at)

    @classmethod
    def from_value(
        cls,
        provider_id: str,
        value: ProviderCapacitySignal | Mapping[str, Any],
    ) -> ProviderCapacitySignal:
        if isinstance(value, cls):
            if value.provider_id != provider_id:
                raise ValueError("capacity signal provider_id does not match its mapping key")
            return value
        if not isinstance(value, Mapping):
            raise TypeError("provider capacity signal must be an object")
        return cls(
            provider_id=provider_id,
            remaining_percent=value.get("remaining_percent", value.get("remainingPercent")),
            reset_at=str(value.get("reset_at", value.get("resetAt")) or ""),
        )

    @property
    def reset_time(self) -> datetime | None:
        return _optional_reset(self.reset_at, field="reset_at")[1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "remaining_percent": self.remaining_percent,
            "reset_at": self.reset_at or None,
        }


def resolve_provider_preference(
    eligible_provider_ids: Iterable[str],
    *,
    stable_preferred_provider_id: str = "",
    capacity_by_provider: Mapping[str, ProviderCapacitySignal | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a provider preference without choosing its model or transport.

    The stable preference is the normal default.  Current remaining capacity
    and, when available, the reset horizon provide independent evidence.  No
    weekly burn forecast or fixed composite score is required.
    """

    providers = sorted(
        {
            _required_text(provider_id, field="eligible_provider_id")
            for provider_id in eligible_provider_ids
        }
    )
    if capacity_by_provider is not None and not isinstance(capacity_by_provider, Mapping):
        raise TypeError("capacity_by_provider must be an object or null")

    raw_capacity = capacity_by_provider or {}
    signals = [
        ProviderCapacitySignal.from_value(provider_id, raw_capacity[provider_id])
        for provider_id in providers
        if provider_id in raw_capacity
    ]
    signal_by_provider = {signal.provider_id: signal for signal in signals}

    stable = stable_preferred_provider_id.strip()
    selected = stable if stable and stable in providers else ""
    basis: list[str] = []
    if stable:
        basis.append("stable_default" if selected else "stable_default_ineligible")

    remaining = [signal for signal in signals if signal.remaining_percent is not None]
    remaining_leaders: list[ProviderCapacitySignal] = []
    remaining_conflicts_with_default = False
    if remaining:
        maximum = max(float(signal.remaining_percent) for signal in remaining)
        remaining_leaders = [
            signal for signal in remaining if float(signal.remaining_percent) == maximum
        ]
        remaining_is_comparative = len(remaining) >= 2 and len(remaining_leaders) == 1
        if selected and remaining_is_comparative:
            if remaining_leaders[0].provider_id == selected:
                basis.append("remaining_capacity_reinforces_default")
            else:
                selected = ""
                remaining_conflicts_with_default = True
                basis.append("remaining_capacity_conflicts_with_default")
        elif not selected and not stable and remaining_is_comparative:
            selected = remaining_leaders[0].provider_id
            basis.append("remaining_capacity")

    reset_candidates = [signal for signal in signals if signal.reset_time is not None]
    if reset_candidates:
        earliest = min(signal.reset_time for signal in reset_candidates if signal.reset_time)
        reset_leaders = [signal for signal in reset_candidates if signal.reset_time == earliest]
        reset_is_comparative = len(reset_candidates) >= 2 and len(reset_leaders) == 1
        remaining_already_decided = len(remaining) >= 2 and len(remaining_leaders) == 1
        if selected and reset_is_comparative and reset_leaders[0].provider_id == selected:
            basis.append("earlier_reset_reinforces_preference")
        elif selected and reset_is_comparative and not remaining_already_decided:
            selected = ""
            basis.append("reset_horizon_conflicts_with_default")
        elif (
            not selected
            and not stable
            and not remaining_conflicts_with_default
            and reset_is_comparative
        ):
            selected = reset_leaders[0].provider_id
            basis.append("earlier_reset")

    return {
        "strategy": "stable_default_reconciled_with_current_capacity",
        "preferred_provider_id": selected or None,
        "preference_basis": basis,
        "eligible_provider_ids": providers,
        "capacity_signals": [
            signal_by_provider[provider_id].as_dict()
            for provider_id in providers
            if provider_id in signal_by_provider
        ],
    }
