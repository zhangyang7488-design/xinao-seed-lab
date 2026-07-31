"""Test-only portfolio freeze helper for shadow continuity/fraud fixtures.

Not a production API and not importable as a public package surface.
Production ``freeze_portfolio_period`` always requires a sealed Owner disposition
envelope/CAS. These helpers compose period preparation + episode freeze for unit
tests that intentionally skip Owner disposition evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from xinao.shadow_lifecycle.consumer import (
    _receipt_base,
    _resolve_freeze_request,
    freeze_episode,
)
from xinao.shadow_lifecycle.lifecycle import AccountingBasis
from xinao.shadow_lifecycle.store import (
    PortfolioPeriodPhase,
    prepare_next_period_root,
    resolve_root,
    write_portfolio_manifest,
    write_receipt_exclusive_or_replace,
)


def freeze_portfolio_period_for_fixture(
    *,
    root: Path,
    request_path: Path | None = None,
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze next portfolio period for unit fixtures without Owner disposition CAS.

    Production callers must use ``freeze_portfolio_period`` with a sealed
    ``owner_authority`` envelope. This helper exists only under ``tests/``.
    """

    closed_request = _resolve_freeze_request(request_path=request_path, request=request)
    base = resolve_root(root)
    period_root, period_index, prior_settled = prepare_next_period_root(base)
    result = freeze_episode(
        root=period_root,
        request=closed_request,
        period_index=period_index,
        prior_settled=prior_settled,
        accounting_basis=AccountingBasis.CARRIED_BALANCE_SNAPSHOT,
        _continuity_internal=True,
    )
    receipt = _receipt_base(
        root=base,
        phase=PortfolioPeriodPhase.FROZEN,
        head_period_index=period_index,
        period_root=str(period_root),
        episode_ref=result["episode_ref"],
        frozen_episode_hash=result["frozen_episode_hash"],
        account_identity=result["account_identity"],
        next_action="portfolio-settle",
    )
    write_receipt_exclusive_or_replace(base, receipt, replace=True)
    write_portfolio_manifest(base)
    return {
        **result,
        "phase": PortfolioPeriodPhase.FROZEN.value,
        "root": str(base),
        "period_root": str(period_root),
        "period_index": period_index,
        "next_action": "portfolio-settle",
        "fixture_construction": True,
        "production_owner_authority_required": False,
    }
