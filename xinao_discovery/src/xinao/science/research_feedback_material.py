"""Bind sealed research feedback packs as later episode material only.

Never rewrites prior candidate/freeze/disposition CAS. Never auto-starts the
next ResearchEpisode or next-period freeze.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.research_feedback_pack import (
    PACK_MARKER,
    PACK_SCHEMA_VERSION,
    research_feedback_pack_cas_path,
)

MATERIAL_SCHEMA: Final = "xinao.research_feedback_material_binding.v1"
MATERIAL_MARKER: Final = "XINAO_RESEARCH_FEEDBACK_MATERIAL_V1"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ResearchFeedbackMaterialError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_MATERIAL_HASH_INVALID",
            f"{label} must be lowercase sha256",
        )
    return value


def load_sealed_feedback_pack(
    *,
    portfolio_root: Path,
    content_hash: str,
) -> dict[str, Any]:
    digest = _require_hex64(content_hash, "content_hash")
    path = research_feedback_pack_cas_path(portfolio_root, digest)
    if not path.is_file():
        raise ResearchFeedbackMaterialError("FEEDBACK_PACK_MISSING", digest)
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, Mapping):
        raise ResearchFeedbackMaterialError("FEEDBACK_PACK_INVALID", "object required")
    body = dict(obj)
    observed = body.pop("content_hash", None)
    expected = canonical_sha256(body)
    if observed != digest or expected != digest:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PACK_TAMPERED",
            f"path={digest} observed={observed} recomputed={expected}",
        )
    if obj.get("schema_version") != PACK_SCHEMA_VERSION:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PACK_SCHEMA_INVALID",
            str(obj.get("schema_version")),
        )
    if obj.get("pack_marker") != PACK_MARKER:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PACK_MARKER_INVALID",
            str(obj.get("pack_marker")),
        )
    if obj.get("auto_start_next_research") is not False:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_AUTO_START_FORBIDDEN",
            "auto_start_next_research must be false",
        )
    if obj.get("scientific_promotion") is not False:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_SCIENTIFIC_PROMOTION_FORBIDDEN",
            "must be false",
        )
    return dict(obj)


def bind_feedback_pack_as_episode_material(
    *,
    portfolio_root: Path,
    feedback_content_hash: str,
    prior_candidate_result_sha256: str | None = None,
    prior_candidate_version: str | None = None,
    settled_portfolio_hash: str | None = None,
    target_episode_version: str | None = None,
) -> dict[str, Any]:
    """Build a sealed material binding for a later episode version.

    Input only: does not mutate pool, freeze, disposition, or the feedback pack.
    Does not start a ResearchEpisode.
    """
    pack = load_sealed_feedback_pack(
        portfolio_root=portfolio_root,
        content_hash=feedback_content_hash,
    )
    # Priors must match pack-derived identities when pack carries them.
    pack_prior_candidate = pack.get("prior_result_sha256") or pack.get("prior_candidate_sha256")
    pack_prior_binding = pack.get("prior_research_binding_sha256")
    if prior_candidate_result_sha256 is not None:
        claimed = _require_hex64(prior_candidate_result_sha256, "prior_candidate_result_sha256")
        if pack_prior_candidate and pack_prior_candidate != claimed:
            raise ResearchFeedbackMaterialError(
                "FEEDBACK_PRIOR_CANDIDATE_MISMATCH",
                f"pack={pack_prior_candidate} claimed={claimed}",
            )
    if settled_portfolio_hash is not None:
        _require_hex64(settled_portfolio_hash, "settled_portfolio_hash")
    body: dict[str, Any] = {
        "schema_version": MATERIAL_SCHEMA,
        "material_marker": MATERIAL_MARKER,
        "feedback_content_hash": _require_hex64(feedback_content_hash, "feedback_content_hash"),
        "prior_candidate_result_sha256": prior_candidate_result_sha256 or pack_prior_candidate,
        "prior_candidate_version": prior_candidate_version,
        "prior_research_binding_sha256": pack_prior_binding,
        "settled_portfolio_hash": settled_portfolio_hash,
        "target_episode_version": target_episode_version,
        "role": "EPISODE_MATERIAL_INPUT_ONLY",
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "rewrites_prior_candidate": False,
        "rewrites_prior_freeze": False,
        "rewrites_prior_disposition": False,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
    }
    content_hash = canonical_sha256(body)
    sealed = {**body, "content_hash": content_hash}
    return sealed


def assert_feedback_cannot_rewrite_priors(
    *,
    binding: Mapping[str, Any],
    existing_pool_entry: Mapping[str, Any] | None = None,
    existing_freeze: Mapping[str, Any] | None = None,
) -> None:
    """Negative gate: material binding must not claim rewrite of prior seals."""
    if binding.get("rewrites_prior_candidate") is not False:
        raise ResearchFeedbackMaterialError("FEEDBACK_REWRITE_CANDIDATE_FORBIDDEN", "candidate")
    if binding.get("rewrites_prior_freeze") is not False:
        raise ResearchFeedbackMaterialError("FEEDBACK_REWRITE_FREEZE_FORBIDDEN", "freeze")
    if binding.get("rewrites_prior_disposition") is not False:
        raise ResearchFeedbackMaterialError("FEEDBACK_REWRITE_DISPOSITION_FORBIDDEN", "disposition")
    if binding.get("auto_start_next_research") is not False:
        raise ResearchFeedbackMaterialError("FEEDBACK_AUTO_START_FORBIDDEN", "auto start")
    if (
        existing_pool_entry is not None
        and existing_pool_entry.get("content_hash")
        and binding.get("prior_candidate_result_sha256")
        and existing_pool_entry.get("result_sha256")
        and binding.get("prior_candidate_result_sha256") != existing_pool_entry.get("result_sha256")
        and binding.get("prior_candidate_result_sha256") == existing_pool_entry.get("content_hash")
    ):
        # Binding must not embed a different seal for the same result identity.
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_REWRITE_CANDIDATE_FORBIDDEN",
            "content_hash used as rewrite handle",
        )
    if existing_freeze is not None and binding.get("rewrites_prior_freeze") is True:
        raise ResearchFeedbackMaterialError("FEEDBACK_REWRITE_FREEZE_FORBIDDEN", "freeze")


__all__ = [
    "MATERIAL_MARKER",
    "MATERIAL_SCHEMA",
    "ResearchFeedbackMaterialError",
    "assert_feedback_cannot_rewrite_priors",
    "bind_feedback_pack_as_episode_material",
    "load_sealed_feedback_pack",
]
