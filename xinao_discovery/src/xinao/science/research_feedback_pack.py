"""Post-settlement research feedback pack for next research material only.

Emits only after real settled state exists. Prior research identities are
derived from the frozen episode's immutable research-binding refs + side
object — never from free caller-supplied prior hashes.

Never grants scientific promotion. Public settled outcomes may enter; any
future unrevealed outcome must not. Generating a pack does not auto-start the
next research episode or freeze the next period.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.freeze_adapter import (
    FreezeAdapterError,
    extract_research_binding_hash_from_frozen,
    load_research_binding,
)
from xinao.shadow_lifecycle.store import (
    FEEDBACK_NAME,
    EpisodePhase,
    StoreError,
    detect_phase,
    load_frozen,
    load_outcome,
    load_portfolio,
    load_settled,
    period_directory,
    portfolio_artifact_paths,
    read_json,
    resolve_root,
)

PACK_SCHEMA_VERSION: Final = "xinao.research_feedback_pack.v1"
PACK_MARKER: Final = "XINAO_RESEARCH_FEEDBACK_PACK_V1"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ResearchFeedbackPackError(ValueError):
    """Fail-closed feedback pack rejection."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_HASH_INVALID",
            f"{label} must be lowercase sha256",
        )
    return value


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with path.open("xb") as stream:
            stream.write(body.encode("utf-8"))
            stream.flush()
    except FileExistsError as exc:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_EXCLUSIVE_CREATE_REJECTED",
            f"already exists: {path.name}",
        ) from exc


def _load_period_settled_bundle(
    *,
    portfolio_root: Path,
    period_index: int | None,
) -> dict[str, Any]:
    base = resolve_root(portfolio_root)
    portfolio_paths = portfolio_artifact_paths(base)
    if not portfolio_paths["portfolio"].is_file():
        # Flat episode root path.
        phase = detect_phase(base)
        if phase != EpisodePhase.SETTLED:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_REQUIRES_SETTLED",
                f"flat episode phase={phase.value}",
            )
        settled = load_settled(base)
        outcome = load_outcome(base)
        frozen = load_frozen(base)
        feedback_path = base / FEEDBACK_NAME
        feedback = read_json(feedback_path) if feedback_path.is_file() else None
        return {
            "mode": "episode",
            "root": base,
            "period_index": settled.period_index,
            "portfolio_ref": settled.portfolio_ref,
            "portfolio_content_hash": None,
            "settled": settled,
            "outcome": outcome,
            "frozen": frozen,
            "feedback": feedback,
        }

    portfolio = load_portfolio(base)
    if period_index is None:
        # Default: latest settled period that has feedback if present, else latest settled.
        idx = 1
        last: dict[str, Any] | None = None
        while True:
            period_root = period_directory(base, idx)
            if not period_root.is_dir():
                break
            try:
                phase = detect_phase(period_root)
            except StoreError:
                break
            settled_path = period_root / "settled_episode.v1.json"
            # Feedback-sealed periods still have settled artifacts.
            if settled_path.is_file() and (
                phase == EpisodePhase.SETTLED or (period_root / FEEDBACK_NAME).is_file()
            ):
                settled = load_settled(period_root)
                outcome = load_outcome(period_root)
                frozen = load_frozen(period_root)
                feedback_path = period_root / FEEDBACK_NAME
                feedback = read_json(feedback_path) if feedback_path.is_file() else None
                last = {
                    "mode": "portfolio",
                    "root": base,
                    "period_root": period_root,
                    "period_index": idx,
                    "portfolio_ref": portfolio.portfolio_ref,
                    "portfolio_content_hash": portfolio.content_hash,
                    "settled": settled,
                    "outcome": outcome,
                    "frozen": frozen,
                    "feedback": feedback,
                }
            idx += 1
        if last is None:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_REQUIRES_SETTLED",
                "no settled portfolio period found",
            )
        return last

    period_root = period_directory(base, period_index)
    if not (period_root / "settled_episode.v1.json").is_file():
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_REQUIRES_SETTLED",
            f"period {period_index} has no settled episode",
        )
    settled = load_settled(period_root)
    outcome = load_outcome(period_root)
    frozen = load_frozen(period_root)
    feedback_path = period_root / FEEDBACK_NAME
    feedback = read_json(feedback_path) if feedback_path.is_file() else None
    return {
        "mode": "portfolio",
        "root": base,
        "period_root": period_root,
        "period_index": period_index,
        "portfolio_ref": portfolio.portfolio_ref,
        "portfolio_content_hash": portfolio.content_hash,
        "settled": settled,
        "outcome": outcome,
        "frozen": frozen,
        "feedback": feedback,
    }


def _reject_future_outcomes(payload: Mapping[str, Any]) -> None:
    """Refuse smuggled future/unrevealed outcome material on the pack surface."""

    forbidden_keys = (
        "future_outcome",
        "next_period_outcome",
        "unrevealed_outcome",
        "peeked_outcome",
    )
    for key in forbidden_keys:
        if key in payload:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_FUTURE_OUTCOME_FORBIDDEN",
                key,
            )


def _build_research_feedback_pack_body(
    *,
    prior_result_sha256: str,
    prior_receipt_content_sha256: str,
    prior_pool_entry_content_hash: str,
    prior_policy_ref: str,
    prior_owner_artifact_sha256: str | None,
    prior_research_binding_sha256: str,
    portfolio_ref: str,
    period_index: int,
    settled_episode_hash: str,
    frozen_episode_hash: str,
    statement_result: str,
    account_pnl_echo: str,
    closing_balance: str,
    account_feedback_hash: str | None,
    public_outcome: Mapping[str, Any],
    next_research_material_hints: list[str] | None = None,
) -> dict[str, Any]:
    """Private pure builder. Not a production settled proof by itself.

    Callers must obtain prior identities from frozen binding + side object.
    This function does not claim settled authority and must not be used to mint
    a feedback pack from free-form forged prior hashes in production paths.
    """

    _require_hex64(prior_result_sha256, "prior_result_sha256")
    _require_hex64(prior_receipt_content_sha256, "prior_receipt_content_sha256")
    _require_hex64(prior_pool_entry_content_hash, "prior_pool_entry_content_hash")
    _require_hex64(prior_research_binding_sha256, "prior_research_binding_sha256")
    _require_hex64(settled_episode_hash, "settled_episode_hash")
    _require_hex64(frozen_episode_hash, "frozen_episode_hash")
    if type(period_index) is not int or period_index < 1:
        raise ResearchFeedbackPackError("FEEDBACK_PACK_PERIOD_INVALID", str(period_index))
    if not isinstance(public_outcome, Mapping):
        raise ResearchFeedbackPackError("FEEDBACK_PACK_OUTCOME_INVALID", "object required")
    required_outcome = {
        "target_ref",
        "actual_special_number",
        "outcome_result_hash",
        "observed_at",
    }
    missing = sorted(required_outcome - set(public_outcome))
    if missing:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_OUTCOME_INCOMPLETE",
            f"missing={missing}",
        )
    number = public_outcome.get("actual_special_number")
    if type(number) is not int or not (1 <= number <= 49):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_OUTCOME_NUMBER_INVALID",
            str(number),
        )
    _require_hex64(public_outcome.get("outcome_result_hash"), "outcome_result_hash")

    body: dict[str, Any] = {
        "schema_version": PACK_SCHEMA_VERSION,
        "pack_marker": PACK_MARKER,
        "prior_result_sha256": prior_result_sha256,
        "prior_receipt_content_sha256": prior_receipt_content_sha256,
        "prior_pool_entry_content_hash": prior_pool_entry_content_hash,
        "prior_policy_ref": prior_policy_ref,
        "prior_owner_artifact_sha256": prior_owner_artifact_sha256,
        "prior_research_binding_sha256": prior_research_binding_sha256,
        "portfolio_ref": portfolio_ref,
        "period_index": period_index,
        "settled_episode_hash": settled_episode_hash,
        "frozen_episode_hash": frozen_episode_hash,
        "statement_result": statement_result,
        "account_pnl_echo": account_pnl_echo,
        "closing_balance": closing_balance,
        "account_feedback_hash": account_feedback_hash,
        "public_outcome": {
            "target_ref": str(public_outcome["target_ref"]),
            "actual_special_number": number,
            "outcome_result_hash": public_outcome["outcome_result_hash"],
            "observed_at": str(public_outcome["observed_at"]),
        },
        "future_outcome_access": False,
        "scientific_promotion": False,
        "completion_claim_allowed": False,
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "next_research_material_hints": list(
            next_research_material_hints
            or [
                "prior_candidate_cas",
                "feedback_pack",
                "limitations",
                "next_evidence",
            ]
        ),
    }
    _reject_future_outcomes(body)
    content_hash = canonical_sha256(body)
    pack_ref = f"feedbackpack.p{period_index}.{content_hash[:16]}"
    sealed = {**body, "pack_ref": pack_ref, "content_hash": content_hash}
    # pack_ref is derived from content_hash of body without pack_ref/content_hash;
    # re-seal with pack_ref included for stable identity.
    final_hash = canonical_sha256({k: v for k, v in sealed.items() if k != "content_hash"})
    sealed["content_hash"] = final_hash
    return sealed


def _derive_priors_from_frozen_binding(
    *,
    shadow_root: Path,
    frozen: Any,
    settled: Any,
    outcome: Any,
    portfolio_ref: str,
    period_index: int,
) -> dict[str, Any]:
    """Load prior identities from frozen decision refs → binding side object."""

    try:
        binding_hash = extract_research_binding_hash_from_frozen(frozen)
        binding = load_research_binding(shadow_root, binding_hash)
    except FreezeAdapterError as exc:
        raise ResearchFeedbackPackError(exc.reason_code, exc.detail) from exc

    # Verify binding against settled/frozen/outcome/portfolio facts.
    if int(binding.get("period_index", -1)) != int(period_index):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_BINDING_PERIOD_MISMATCH",
            f"binding={binding.get('period_index')} period={period_index}",
        )
    if int(frozen.period_index) != int(period_index):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_FROZEN_PERIOD_MISMATCH",
            f"frozen={frozen.period_index} period={period_index}",
        )
    if str(binding.get("target_ref")) != str(frozen.target_ref):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_BINDING_TARGET_MISMATCH",
            "binding target_ref disagrees with frozen episode",
        )
    if str(outcome.target_ref) != str(frozen.target_ref):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_OUTCOME_TARGET_MISMATCH",
            "public outcome target_ref disagrees with frozen episode",
        )
    if str(settled.portfolio_ref) != str(portfolio_ref):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_PORTFOLIO_MISMATCH",
            "settled portfolio_ref disagrees",
        )
    if str(binding.get("account_identity")) != str(frozen.account_decision.identity.value):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_BINDING_ACCOUNT_MISMATCH",
            "binding account_identity disagrees with frozen account decision",
        )
    if str(binding.get("science_identity")) != str(frozen.science_decision.identity.value):
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_BINDING_SCIENCE_MISMATCH",
            "binding science_identity disagrees with frozen science decision",
        )
    if frozen.content_hash is None or settled.content_hash is None:
        raise ResearchFeedbackPackError("FEEDBACK_PACK_SEAL_MISSING", "settled/frozen unsealed")
    if settled.frozen_episode_hash != frozen.content_hash:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_SETTLED_FROZEN_MISMATCH",
            "settled.frozen_episode_hash disagrees with loaded frozen",
        )

    return {
        "prior_result_sha256": _require_hex64(binding.get("result_sha256"), "result_sha256"),
        "prior_receipt_content_sha256": _require_hex64(
            binding.get("receipt_content_sha256"),
            "receipt_content_sha256",
        ),
        "prior_pool_entry_content_hash": _require_hex64(
            binding.get("pool_entry_content_hash"),
            "pool_entry_content_hash",
        ),
        "prior_policy_ref": str(binding.get("policy_ref") or ""),
        "prior_owner_artifact_sha256": (
            _require_hex64(binding.get("owner_artifact_sha256"), "owner_artifact_sha256")
            if binding.get("owner_artifact_sha256") is not None
            else None
        ),
        "prior_research_binding_sha256": binding_hash,
        "science_disposition": binding.get("science_disposition"),
        "account_identity": binding.get("account_identity"),
    }


def emit_research_feedback_pack(
    *,
    portfolio_root: Path,
    period_index: int | None = None,
    output_path: Path | None = None,
    require_account_feedback: bool = False,
) -> dict[str, Any]:
    """Read settled state, derive priors from frozen binding, emit one pack.

    Does **not** accept free caller ``prior_*`` hashes. Forged priors cannot be
    mixed with real P&L to mint a sealed research feedback pack.
    """

    bundle = _load_period_settled_bundle(
        portfolio_root=portfolio_root,
        period_index=period_index,
    )
    settled = bundle["settled"]
    outcome = bundle["outcome"]
    frozen = bundle["frozen"]
    feedback = bundle["feedback"]
    shadow_root = Path(bundle["root"])

    if require_account_feedback and feedback is None:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_REQUIRES_ACCOUNT_FEEDBACK",
            "account feedback not sealed yet",
        )

    if settled.content_hash is None or frozen.content_hash is None:
        raise ResearchFeedbackPackError("FEEDBACK_PACK_SEAL_MISSING", "settled/frozen unsealed")

    if not outcome.verified:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_OUTCOME_NOT_VERIFIED",
            "unverified outcome cannot enter feedback pack",
        )
    outcome.require_valid_result_hash()
    if outcome.result_hash is None:
        raise ResearchFeedbackPackError("FEEDBACK_PACK_OUTCOME_HASH_MISSING", "result_hash")

    priors = _derive_priors_from_frozen_binding(
        shadow_root=shadow_root,
        frozen=frozen,
        settled=settled,
        outcome=outcome,
        portfolio_ref=str(bundle["portfolio_ref"]),
        period_index=int(bundle["period_index"]),
    )

    account_feedback_hash = None
    if feedback is not None:
        if not isinstance(feedback, Mapping):
            raise ResearchFeedbackPackError("FEEDBACK_PACK_FEEDBACK_INVALID", "object required")
        if feedback.get("scientific_promotion") is not False:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_SCIENTIFIC_PROMOTION_FORBIDDEN",
                "account feedback must not promote science",
            )
        account_feedback_hash = feedback.get("content_hash")
        if account_feedback_hash is not None:
            _require_hex64(account_feedback_hash, "account_feedback_hash")

    pack = _build_research_feedback_pack_body(
        prior_result_sha256=priors["prior_result_sha256"],
        prior_receipt_content_sha256=priors["prior_receipt_content_sha256"],
        prior_pool_entry_content_hash=priors["prior_pool_entry_content_hash"],
        prior_policy_ref=priors["prior_policy_ref"],
        prior_owner_artifact_sha256=priors["prior_owner_artifact_sha256"],
        prior_research_binding_sha256=priors["prior_research_binding_sha256"],
        portfolio_ref=str(bundle["portfolio_ref"]),
        period_index=int(bundle["period_index"]),
        settled_episode_hash=str(settled.content_hash),
        frozen_episode_hash=str(frozen.content_hash),
        statement_result=str(settled.statement.result.value),
        account_pnl_echo=str(settled.statement.pnl),
        closing_balance=str(settled.statement.closing_balance),
        account_feedback_hash=account_feedback_hash,
        public_outcome={
            "target_ref": outcome.target_ref,
            "actual_special_number": outcome.actual_special_number,
            "outcome_result_hash": outcome.result_hash,
            "observed_at": outcome.observed_at.isoformat().replace("+00:00", "Z")
            if hasattr(outcome.observed_at, "isoformat")
            else str(outcome.observed_at),
        },
    )

    if output_path is None:
        if bundle["mode"] == "portfolio":
            output_path = Path(bundle["period_root"]) / "research_feedback_pack.v1.json"
        else:
            output_path = Path(bundle["root"]) / "research_feedback_pack.v1.json"
    _write_new_json(output_path, pack)

    return {
        "ok": True,
        "pack_ref": pack["pack_ref"],
        "content_hash": pack["content_hash"],
        "path": str(output_path),
        "period_index": pack["period_index"],
        "scientific_promotion": False,
        "future_outcome_access": False,
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "prior_research_binding_sha256": priors["prior_research_binding_sha256"],
        "pack": pack,
    }


def reject_pre_outcome_emit(*, portfolio_root: Path, period_index: int | None = None) -> None:
    """Explicit guard used by tests: pre-outcome roots must not emit packs."""

    base = resolve_root(portfolio_root)
    portfolio_paths = portfolio_artifact_paths(base)
    if portfolio_paths["portfolio"].is_file():
        idx = period_index if period_index is not None else 1
        period_root = period_directory(base, idx)
        if not period_root.is_dir():
            raise ResearchFeedbackPackError("FEEDBACK_PACK_REQUIRES_SETTLED", "period missing")
        phase = detect_phase(period_root)
        if phase in {EpisodePhase.INIT, EpisodePhase.FROZEN, EpisodePhase.MISSING}:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_ABSENT_PRE_OUTCOME",
                f"phase={phase.value}",
            )
        settled_exists = (period_root / "settled_episode.v1.json").is_file()
        if phase != EpisodePhase.SETTLED and not settled_exists:
            raise ResearchFeedbackPackError(
                "FEEDBACK_PACK_ABSENT_PRE_OUTCOME",
                f"phase={phase.value}",
            )
        return
    phase = detect_phase(base)
    if phase != EpisodePhase.SETTLED:
        raise ResearchFeedbackPackError(
            "FEEDBACK_PACK_ABSENT_PRE_OUTCOME",
            f"phase={phase.value}",
        )


__all__ = [
    "PACK_MARKER",
    "PACK_SCHEMA_VERSION",
    "ResearchFeedbackPackError",
    "emit_research_feedback_pack",
    "reject_pre_outcome_emit",
]
