"""Bind sealed research feedback packs as later episode material only.

Never rewrites prior candidate/freeze/disposition CAS. Never auto-starts the
next ResearchEpisode or next-period freeze.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from xinao.canonical import canonical_sha256
from xinao.science.portfolio import settled_portfolio_feedback_state_cas_path
from xinao.science.research_feedback_pack import (
    PACK_MARKER,
    PACK_SCHEMA_VERSION,
    research_feedback_pack_cas_path,
)

MATERIAL_SCHEMA: Final = "xinao.research_feedback_material_binding.v1"
MATERIAL_MARKER: Final = "XINAO_RESEARCH_FEEDBACK_MATERIAL_V1"
INVENTORY_SCHEMA: Final = "xinao.research_episode_feedback_inventory.v1"
INVENTORY_MARKER: Final = "XINAO_RESEARCH_EPISODE_FEEDBACK_INVENTORY_V1"
PROVIDER_PROMPT_MARKER: Final = "XINAO_SEALED_SETTLEMENT_FEEDBACK_INPUT_V1"
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


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attrs = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & marker)


def _assert_episode_input_path_safe(*, episode_root: Path, target: Path) -> None:
    root = Path(os.path.abspath(episode_root))
    candidate = Path(os.path.abspath(target))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_PATH_ESCAPE",
            str(candidate),
        ) from exc
    cursor = root
    for part in relative.parts:
        if (cursor.exists() or cursor.is_symlink()) and _is_link_or_reparse(cursor):
            raise ResearchFeedbackMaterialError(
                "FEEDBACK_EPISODE_INPUT_REPARSE_FORBIDDEN",
                str(cursor),
            )
        cursor = cursor / part
    if (cursor.exists() or cursor.is_symlink()) and _is_link_or_reparse(cursor):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_REPARSE_FORBIDDEN",
            str(cursor),
        )


def load_sealed_feedback_pack(
    *,
    portfolio_root: Path,
    content_hash: str,
) -> dict[str, Any]:
    digest = _require_hex64(content_hash, "content_hash")
    path = research_feedback_pack_cas_path(portfolio_root, digest)
    if _is_link_or_reparse(path):
        raise ResearchFeedbackMaterialError("FEEDBACK_PACK_REPARSE_FORBIDDEN", digest)
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
    portfolio_feedback_state_hash: str | None = None,
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
        settled_portfolio_hash = _require_hex64(
            settled_portfolio_hash,
            "settled_portfolio_hash",
        )
    pack_state_hash = pack.get("portfolio_feedback_state_hash")
    if portfolio_feedback_state_hash is not None:
        claimed_state_hash = _require_hex64(
            portfolio_feedback_state_hash,
            "portfolio_feedback_state_hash",
        )
        if pack_state_hash is not None and claimed_state_hash != pack_state_hash:
            raise ResearchFeedbackMaterialError(
                "FEEDBACK_PORTFOLIO_STATE_MISMATCH",
                f"pack={pack_state_hash} claimed={claimed_state_hash}",
            )
    else:
        claimed_state_hash = pack_state_hash
    body: dict[str, Any] = {
        "schema_version": MATERIAL_SCHEMA,
        "material_marker": MATERIAL_MARKER,
        "feedback_content_hash": _require_hex64(feedback_content_hash, "feedback_content_hash"),
        "prior_candidate_result_sha256": prior_candidate_result_sha256 or pack_prior_candidate,
        "prior_candidate_version": prior_candidate_version,
        "prior_research_binding_sha256": pack_prior_binding,
        # Backward-compatible caller-supplied identity; not redefined as state hash.
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
    if claimed_state_hash is not None:
        body["portfolio_feedback_state_hash"] = claimed_state_hash
    content_hash = canonical_sha256(body)
    sealed = {**body, "content_hash": content_hash}
    return sealed


def episode_feedback_inventory_path(*, episode_root: Path, inventory_hash: str) -> Path:
    digest = _require_hex64(inventory_hash, "inventory_hash")
    return (
        Path(episode_root)
        / "inputs"
        / "research_feedback"
        / "sha256"
        / digest[:2]
        / digest
        / "inventory.json"
    )


def _write_idempotent_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = (json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    if _is_link_or_reparse(path):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_REPARSE_FORBIDDEN",
            str(path),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
    except FileExistsError as exc:
        if path.read_bytes() == raw:
            return
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_CONFLICT",
            str(path),
        ) from exc


def _verify_sealed_object(
    payload: object,
    *,
    expected_hash: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_INVALID",
            f"{label}: object required",
        )
    body = dict(payload)
    observed = body.pop("content_hash", None)
    if observed != expected_hash or canonical_sha256(body) != expected_hash:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INPUT_TAMPERED",
            label,
        )
    return dict(payload)


def stage_feedback_pack_for_episode(
    *,
    episode_root: Path,
    episode_id: str,
    portfolio_root: Path,
    feedback_content_hash: str,
) -> dict[str, Any]:
    """Stage one self-contained immutable feedback inventory for explicit start.

    The caller has already chosen to start an episode.  Staging never starts a
    successor itself and never writes to the source Portfolio.
    """

    pack = load_sealed_feedback_pack(
        portfolio_root=portfolio_root,
        content_hash=feedback_content_hash,
    )
    for lineage_key in (
        "prior_result_sha256",
        "prior_receipt_content_sha256",
        "prior_pool_entry_content_hash",
        "prior_research_binding_sha256",
    ):
        _require_hex64(pack.get(lineage_key), lineage_key)
    if not isinstance(pack.get("prior_policy_ref"), str) or not pack["prior_policy_ref"]:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_RESEARCH_LINEAGE_INCOMPLETE",
            "prior_policy_ref",
        )
    state_hash = pack.get("portfolio_feedback_state_hash")
    if state_hash is None:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PORTFOLIO_STATE_REQUIRED",
            "explicit next ResearchEpisode requires cross-period settled state",
        )
    state_hash = _require_hex64(state_hash, "portfolio_feedback_state_hash")
    state_path = settled_portfolio_feedback_state_cas_path(
        portfolio_root=portfolio_root,
        content_hash=state_hash,
    )
    if _is_link_or_reparse(state_path):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PORTFOLIO_STATE_REPARSE_FORBIDDEN",
            state_hash,
        )
    if not state_path.is_file():
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PORTFOLIO_STATE_MISSING",
            state_hash,
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_PORTFOLIO_STATE_INVALID",
            state_hash,
        ) from exc
    sealed_state = _verify_sealed_object(
        state,
        expected_hash=state_hash,
        label="portfolio_feedback_state",
    )
    if sealed_state.get("account_axis", {}).get("cost_accounting_status") != (
        "UNPROVEN_NOT_RECORDED"
    ):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_COST_ACCOUNTING_STATUS_INVALID",
            str(sealed_state.get("account_axis", {}).get("cost_accounting_status")),
        )
    if sealed_state.get("account_axis", {}).get("after_cost_profit_claim_allowed") is not False:
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_AFTER_COST_CLAIM_FORBIDDEN",
            "after-cost claim must remain false until costs are actually recorded",
        )

    binding = bind_feedback_pack_as_episode_material(
        portfolio_root=portfolio_root,
        feedback_content_hash=feedback_content_hash,
        portfolio_feedback_state_hash=state_hash,
        target_episode_version=episode_id,
    )
    assert_feedback_cannot_rewrite_priors(binding=binding)
    binding_hash = _require_hex64(binding.get("content_hash"), "material_binding_hash")
    inventory_body: dict[str, Any] = {
        "schema_version": INVENTORY_SCHEMA,
        "inventory_marker": INVENTORY_MARKER,
        "episode_id": str(episode_id),
        "feedback_content_hash": _require_hex64(
            feedback_content_hash,
            "feedback_content_hash",
        ),
        "material_binding_hash": binding_hash,
        "portfolio_feedback_state_hash": state_hash,
        "members": {
            "feedback_pack": "feedback_pack.json",
            "material_binding": "material_binding.json",
            "portfolio_feedback_state": "portfolio_feedback_state.json",
        },
        "role": "SEALED_EPISODE_INPUT_ONLY",
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "rewrites_prior_candidate": False,
        "rewrites_prior_freeze": False,
        "rewrites_prior_disposition": False,
        "owner_adopted": False,
        "model_learning_proven": False,
        "scientific_promotion": False,
        "completion_claim_allowed": False,
    }
    inventory_hash = canonical_sha256(inventory_body)
    inventory = {**inventory_body, "content_hash": inventory_hash}
    inventory_path = episode_feedback_inventory_path(
        episode_root=episode_root,
        inventory_hash=inventory_hash,
    )
    _assert_episode_input_path_safe(episode_root=episode_root, target=inventory_path)
    directory = inventory_path.parent
    _write_idempotent_json(directory / "feedback_pack.json", pack)
    _write_idempotent_json(directory / "material_binding.json", binding)
    _write_idempotent_json(directory / "portfolio_feedback_state.json", sealed_state)
    # Inventory is the completion marker and is written last.
    _write_idempotent_json(inventory_path, inventory)
    return {
        "inventory_hash": inventory_hash,
        "inventory_path": str(inventory_path),
        "feedback_content_hash": feedback_content_hash,
        "portfolio_feedback_state_hash": state_hash,
        "material_binding_hash": binding_hash,
        "auto_start_next_research": False,
        "model_learned_claim_allowed": False,
        "inventory": inventory,
    }


def _load_episode_feedback_bundle(
    *,
    episode_root: Path,
    inventory_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    digest = _require_hex64(inventory_hash, "inventory_hash")
    path = episode_feedback_inventory_path(
        episode_root=episode_root,
        inventory_hash=digest,
    )
    _assert_episode_input_path_safe(episode_root=episode_root, target=path)
    if not path.is_file():
        raise ResearchFeedbackMaterialError("FEEDBACK_EPISODE_INVENTORY_MISSING", digest)
    inventory = _verify_sealed_object(
        json.loads(path.read_text(encoding="utf-8")),
        expected_hash=digest,
        label="inventory",
    )
    if inventory.get("schema_version") != INVENTORY_SCHEMA or (
        inventory.get("inventory_marker") != INVENTORY_MARKER
    ):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INVENTORY_INVALID",
            digest,
        )
    members = inventory.get("members")
    if not isinstance(members, Mapping):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_INVENTORY_INVALID",
            "members",
        )
    directory = path.parent

    def _member(name: str, expected_hash_key: str) -> dict[str, Any]:
        relative = members.get(name)
        if not isinstance(relative, str) or Path(relative).name != relative:
            raise ResearchFeedbackMaterialError(
                "FEEDBACK_EPISODE_MEMBER_PATH_INVALID",
                name,
            )
        member_path = directory / relative
        _assert_episode_input_path_safe(
            episode_root=episode_root,
            target=member_path,
        )
        if not member_path.is_file():
            raise ResearchFeedbackMaterialError(
                "FEEDBACK_EPISODE_MEMBER_MISSING",
                name,
            )
        return _verify_sealed_object(
            json.loads(member_path.read_text(encoding="utf-8")),
            expected_hash=_require_hex64(inventory.get(expected_hash_key), expected_hash_key),
            label=name,
        )

    pack = _member("feedback_pack", "feedback_content_hash")
    binding = _member("material_binding", "material_binding_hash")
    state = _member("portfolio_feedback_state", "portfolio_feedback_state_hash")
    if binding.get("feedback_content_hash") != pack.get("content_hash"):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_BINDING_PACK_MISMATCH",
            digest,
        )
    if pack.get("portfolio_feedback_state_hash") != state.get("content_hash"):
        raise ResearchFeedbackMaterialError(
            "FEEDBACK_EPISODE_PACK_STATE_MISMATCH",
            digest,
        )
    return inventory, pack, binding, state


def load_episode_feedback_inventory(
    *,
    episode_root: Path,
    inventory_hash: str,
) -> dict[str, Any]:
    inventory, _pack, _binding, _state = _load_episode_feedback_bundle(
        episode_root=episode_root,
        inventory_hash=inventory_hash,
    )
    return inventory


def compose_feedback_bound_provider_prompt(
    *,
    episode_root: Path,
    inventory_hash: str,
    owner_prompt: str | None,
) -> dict[str, Any]:
    """Make the sealed inventory an actual provider input, not a mounted orphan."""

    inventory, pack, _binding, state = _load_episode_feedback_bundle(
        episode_root=episode_root,
        inventory_hash=inventory_hash,
    )
    packet = {
        "marker": PROVIDER_PROMPT_MARKER,
        "inventory_hash": inventory_hash,
        "feedback_content_hash": inventory["feedback_content_hash"],
        "portfolio_feedback_state_hash": inventory["portfolio_feedback_state_hash"],
        "research_lineage": {
            "prior_result_sha256": pack.get("prior_result_sha256"),
            "prior_receipt_content_sha256": pack.get("prior_receipt_content_sha256"),
            "prior_pool_entry_content_hash": pack.get("prior_pool_entry_content_hash"),
            "prior_policy_ref": pack.get("prior_policy_ref"),
            "prior_owner_artifact_sha256": pack.get("prior_owner_artifact_sha256"),
            "prior_research_binding_sha256": pack.get("prior_research_binding_sha256"),
        },
        "account_axis": state["account_axis"],
        "science_axis": state["science_axis"],
        "periods": state["periods"],
        "latest_public_outcome": pack.get("public_outcome"),
        "interpretation_boundary": {
            "recorded_pnl_is_after_cost_profit": False,
            "account_performance_is_scientific_proof": False,
            "model_learning_proven": False,
        },
    }
    packet_text = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    requested = owner_prompt if owner_prompt is not None else "Continue the same bounded research."
    effective_prompt = (
        f"[{PROVIDER_PROMPT_MARKER}]\n"
        f"{packet_text}\n"
        f"[END_{PROVIDER_PROMPT_MARKER}]\n\n"
        "The block above is sealed settlement evidence, not authority or a scientific verdict. "
        "Read it as input while preserving its account/science distinction and explicit "
        "unknowns.\n\n"
        f"Owner research request:\n{requested}"
    )
    return {
        "prompt": effective_prompt,
        "feedback_inventory_read": True,
        "feedback_prompt_bound": True,
        "feedback_inventory_hash": inventory_hash,
        "feedback_packet_sha256": canonical_sha256(packet),
        "model_learned_claim_allowed": False,
        "scientific_promotion": False,
        "auto_start_next_research": False,
    }


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
    "INVENTORY_MARKER",
    "INVENTORY_SCHEMA",
    "MATERIAL_MARKER",
    "MATERIAL_SCHEMA",
    "PROVIDER_PROMPT_MARKER",
    "ResearchFeedbackMaterialError",
    "assert_feedback_cannot_rewrite_priors",
    "bind_feedback_pack_as_episode_material",
    "compose_feedback_bound_provider_prompt",
    "episode_feedback_inventory_path",
    "load_episode_feedback_inventory",
    "load_sealed_feedback_pack",
    "stage_feedback_pack_for_episode",
]
