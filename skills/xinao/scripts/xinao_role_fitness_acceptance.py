"""Executable harness: role-fitness evidence + prospective shadow consumer.

Candidate-only acceptance runner. Codex is the sole Owner/adopter/final verifier.
Drives the real file-backed shadow lifecycle consumer for account continuity.

Scientist-episode evidence is a real trace/verifier contract: multi-turn claims,
tool calls, fail→revise, and resume must bind to hashed raw Grok session and MCP
sidecar event artifacts. Bare transcript assertions without those hashes fail closed.
Dependency-injected narrative-only seams are rejected (not live role fitness).

United Owner vertical (bounded, no daemon/Goal; sole prospective join surface):
  admitted future ProtocolPin → immutable genuine episode candidate →
  authentic Codex disposition → independent science/account decisions →
  pre-outcome ACTION/NO_ACTION freeze and stop → independent outcome →
  settle-all/replay/feedback/same-seat carry and stop.

One native episode receipt interface (``consume_native_episode_receipt``) and
the existing ``xinao.shadow_lifecycle`` portfolio consumer. A separate ~1.3k-line
two-phase ``live_runner`` is deliberately not product: it duplicated validation,
canonicalization, receipt schemas, CLI, and transaction orchestration.

Does not create a second ledger, mutate installed XINAO state, claim parent
completion, or promote account P&L into science.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Prefer discovery package source over skills/xinao directory name collision.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISCOVERY_SRC = _REPO_ROOT / "xinao_discovery" / "src"
if _DISCOVERY_SRC.is_dir():
    _src = str(_DISCOVERY_SRC)
    if _src in sys.path:
        sys.path.remove(_src)
    sys.path.insert(0, _src)
    # Drop a non-package `xinao` module shadow if one was imported earlier.
    _existing = sys.modules.get("xinao")
    if _existing is not None and not hasattr(_existing, "shadow_lifecycle"):
        del sys.modules["xinao"]

from xinao.canonical import canonical_sha256  # noqa: E402
from xinao.science.candidate_pool import ingest_verified_research_result  # noqa: E402
from xinao.science.freeze_adapter import (  # noqa: E402
    FreezeAdapterError,
    apply_freeze_from_disposition,
    build_freeze_request_from_disposition,
    build_portfolio_binding_from_shadow,
    build_research_freeze_binding,
    write_research_binding_exclusive,
)
from xinao.science.owner_disposition import (  # noqa: E402
    CODEX_OWNER_CHANNEL_SOURCE,
    DISPOSITION_MARKER,
    DISPOSITION_SCHEMA_VERSION,
    SCIENCE_ABSORB_NO_ACTION,
    SCIENCE_RETAIN_FOR_SHADOW,
    OwnerDispositionError,
    load_and_verify_disposition,
    write_owner_disposition_artifact,
)
from xinao.shadow_lifecycle import (  # noqa: E402
    FeedbackKind,
    feedback_portfolio_period,
    freeze_portfolio_period,
    init_portfolio,
    inspect_portfolio,
    replay_portfolio_period,
    settle_portfolio_period,
)
from xinao.shadow_lifecycle.consumer import (  # noqa: E402
    OWNER_FREEZE_AUTHORITY_MARKER,
    OWNER_FREEZE_AUTHORITY_SCHEMA,
)
from xinao.shadow_lifecycle.store import (  # noqa: E402
    StoreError,
    load_frozen,
    load_seat,
    period_directory,
)

RECEIPT_SCHEMA = "xinao.role_fitness_acceptance_receipt.v1"
VERTICAL_RECEIPT_SCHEMA = "xinao.role_fitness_vertical_receipt.v1"
PRE_OUTCOME_RECEIPT_SCHEMA = "xinao.role_fitness_pre_outcome_freeze_receipt.v1"
CONTINUATION_RECEIPT_SCHEMA = "xinao.role_fitness_outcome_continuation_receipt.v1"
INSTRUMENT_CANARY_ROUTE = "INSTRUMENT_CANARY"
GENUINE_SCIENTIST_ROUTE = "GENUINE_SCIENTIST"
OWNER_ROLE = "codex"
MECHANICAL_RULE_REF = "special-number-rule.v1"
ODDS_VERSION_REF = "odds.special-number.20260731.v1"

# Proof-class labels (independent axes; never cross-green).
PROOF_DI_SCIENTIST_SEAM = "DI_GENUINE_SCIENTIST_SEAM"  # retired; rejected by verifier
PROOF_NATIVE_SESSION_MCP = "NATIVE_GROK_SESSION_MCP_TRACE"
PROOF_REAL_SHADOW_CONSUMER = "REAL_SHADOW_LIFECYCLE_CONSUMER"
PROOF_PROTOCOL_PIN_SHAPE = "PROTOCOL_PIN_SHAPE_GATE_ONLY"
PROOF_PROTOCOL_PIN_FORMAL = "SCIENCE_EPISODE_ADMISSION_FILE"
PROOF_OWNER_DISPOSITION_STRUCTURE = "OWNER_DISPOSITION_STRUCTURE_ONLY"
PROOF_OWNER_DISPOSITION_CHANNEL = "CODEX_OWNER_CHANNEL"
PROOF_FUTURE_OUTCOME = "FUTURE_OUTCOME_ONLY"
PROOF_PRE_OUTCOME_FREEZE = "PRE_OUTCOME_FREEZE_RECEIPT"
PROOF_OWNER_VERTICAL = "OWNER_INVOKED_ROLE_FITNESS_VERTICAL"

# Exact first live episode command (Owner-integrated; worker cannot claim RF alone).
# Structured scientist evidence is required: never glue synthetic fixtures onto live hashes.
FIRST_LIVE_EPISODE_COMMAND = (
    "python -I skills/xinao/scripts/xinao_role_fitness_acceptance.py "
    "owner-vertical "
    '--work-root "$XINAO_RF_WORK_ROOT" '
    "--mode pre_outcome "
    "--require-live-research "
    '--protocol-pin-path "$PROTOCOL_PIN_PATH" '
    '--protocol-pin-sha256 "$PROTOCOL_PIN_SHA256" '
    '--active-parent-sha256 "$ACTIVE_PARENT_SHA256" '
    '--session-artifact "$GROK_SESSION_JSON" '
    '--mcp-events "$MCP_EVENTS_JSONL" '
    '--scientist-evidence "$SCIENTIST_EVIDENCE_JSON" '
    '--codex-disposition "$CODEX_DISPOSITION_JSON" '
    '--research-question "$UNEXPOSED_TARGET_QUESTION" '
    '--receipt-out "$XINAO_RF_WORK_ROOT/pre_outcome_receipt.json"'
)
FIRST_LIVE_EPISODE_CONTINUATION_COMMAND = (
    "python -I skills/xinao/scripts/xinao_role_fitness_acceptance.py "
    "owner-vertical "
    '--work-root "$XINAO_RF_WORK_ROOT" '
    "--mode continue_outcome "
    '--pre-outcome-receipt "$XINAO_RF_WORK_ROOT/pre_outcome_receipt.json" '
    '--external-outcome "$INDEPENDENT_OUTCOME_JSON" '
    '--receipt-out "$XINAO_RF_WORK_ROOT/continuation_receipt.json"'
)
# Host ResearchEpisode start (leg-A durable home; separate from canary research invoke).
FIRST_LIVE_RESEARCH_EPISODE_HOST_COMMAND = (
    "python -I skills/xinao/scripts/xinao.py research-episode start "
    '--root "$XINAO_EPISODE_HOME" '
    '--question "$UNEXPOSED_TARGET_QUESTION" '
    "--lease-seconds 3600"
)

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

ALLOWED_SCIENCE_IDENTITIES = frozenset({"SCIENCE_CANDIDATE", "POLICY_NO_ACTION"})
ALLOWED_ACCOUNT_IDENTITIES = frozenset({"ACTION", "RESEARCHER_ACCOUNT_NO_ACTION"})
ALLOWED_OWNER_DISPOSITIONS = frozenset(
    {"ADOPT", "REJECT", "DEFER", "NO_ACTION", "ABSORB_NO_ACTION"}
)
ALLOWED_TOOL_KINDS = frozenset({"shell", "python", "code", "data_compute", "bounded_lab"})
WORKER_DISPOSITION_SOURCES = frozenset(
    {"worker", "worker_fixture", "harness", "test", "mock", "self"}
)
_SYNTHETIC_OUTCOME_MARKERS = (
    "synthetic",
    "fixture",
    "harness",
    "mock",
    "test-only",
    "test_only",
    "unit-fixture",
    "unit_fixture",
)
# Deliberately not installed: sealed lifecycle live_runner was a duplicate stack.
RETIRED_LIVE_RUNNER_MODULE = "xinao.shadow_lifecycle.live_runner"


class RoleFitnessAcceptanceError(ValueError):
    """Typed harness failure; never auto-greens parent completion."""


def two_owner_commands() -> dict[str, str]:
    """Exact two Owner commands for the united consumer path (no second CLI)."""

    return {
        "pre_outcome": FIRST_LIVE_EPISODE_COMMAND,
        "post_outcome": FIRST_LIVE_EPISODE_CONTINUATION_COMMAND,
    }


def self_audit_hidden_human_burden() -> dict[str, Any]:
    """Honest residual Owner steps; runner does not invent targets or outcomes."""

    return {
        "schema_version": "xinao.role_fitness.united_consumer_self_audit.v1",
        "hidden_human_burden": [
            {
                "item": "formal_protocol_pin_admission",
                "owner_step": (
                    "Admit unexposed ProtocolPin via science episode admission before pre_outcome"
                ),
                "runner_does_not": "Mint or choose a target; only consumes admission/shape",
            },
            {
                "item": "genuine_scientist_episode",
                "owner_step": (
                    "Run ResearchEpisode; supply hashed session+MCP + structured "
                    "scientist-evidence JSON"
                ),
                "runner_does_not": "Invoke model/tools or glue fixture narrative onto live hashes",
            },
            {
                "item": "codex_owner_disposition",
                "owner_step": "Write authentic Codex disposition (codex_owner_channel artifact)",
                "runner_does_not": "Accept worker-controlled disposition as authentic live",
            },
            {
                "item": "independent_outcome_observation",
                "owner_step": "After target open, supply verified independent outcome JSON",
                "runner_does_not": "Fabricate outcome or treat synthetic source_ref as live",
            },
        ],
        "automation_boundary": (
            "Owner-vertical freezes/settles/replays/feedbacks only on the existing "
            "shadow portfolio store after gates pass; no second ledger or live_runner CLI."
        ),
        "two_phase_commands": two_owner_commands(),
        "retired_duplicate_stack": RETIRED_LIVE_RUNNER_MODULE,
        "native_receipt_interface": "consume_native_episode_receipt",
        "shadow_consumer": "xinao.shadow_lifecycle",
        "awaiting_real_future_target_and_outcome": True,
        "completion_claim_allowed": False,
        "parent_completion": False,
        "hidden_technical_burden_returned_to_human": False,
        "why_no_hidden_technical_burden": (
            "Human retains only irreducible Owner steps (admit pin, run episode, "
            "disposition, independent outcome). Validation, freeze, settle-all, "
            "replay, feedback, and same-seat carry stay in one CLI over the existing "
            "shadow store — not a second runner/ledger/daemon for the human to operate."
        ),
    }


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RoleFitnessAcceptanceError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoleFitnessAcceptanceError(f"{label} must be a non-empty string")
    return value.strip()


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise RoleFitnessAcceptanceError(f"{label} must be a boolean")
    return value


def _require_hash(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not _HASH_PATTERN.fullmatch(text):
        raise RoleFitnessAcceptanceError(f"{label} must be lowercase sha256")
    return text


def _require_aware(value: Any, label: str) -> datetime:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RoleFitnessAcceptanceError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RoleFitnessAcceptanceError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    body = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((body + "\n").encode("utf-8")).hexdigest()


def _event_seal_hash(
    *,
    seq: int,
    event_type: str,
    payload_hash: str,
    predecessor_hash: str | None,
    episode_id: str,
    session_id: str,
) -> str:
    return _canonical_sha256(
        {
            "episode_id": episode_id,
            "event_type": event_type,
            "payload_hash": payload_hash,
            "predecessor_hash": predecessor_hash,
            "seq": seq,
            "session_id": session_id,
        }
    )


def _times(open_at: datetime) -> tuple[datetime, datetime, datetime]:
    return (
        open_at - timedelta(minutes=10),
        open_at - timedelta(minutes=6),
        open_at - timedelta(minutes=5),
    )


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _harness_action_core(
    *,
    target_ref: str,
    open_at: datetime,
    selected_number: int,
    panel: str,
    stake: str,
) -> dict[str, Any]:
    cutoff, _frozen_at, deadline = _times(open_at)
    baseline = "BO0013" if panel == "B" else "BO0001"
    return {
        "panel": panel,
        "selected_number": selected_number,
        "stake": stake,
        "target_ref": target_ref,
        "target_open_time": _iso_z(open_at),
        "freeze_deadline": _iso_z(deadline),
        "knowledge_cutoff": _iso_z(cutoff),
        "odds_version_ref": ODDS_VERSION_REF,
        "baseline_ref": baseline,
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": MECHANICAL_RULE_REF,
    }


# Sealed production-shaped research evidence used only to construct formal pool
# entries for the acceptance harness (not a freeze-gate bypass).
_HARNESS_RESEARCH_FIXTURE_DIR = (
    _REPO_ROOT / "xinao_discovery" / "tests" / "unit" / "science" / "fixtures" / "rq008_live"
)


def ensure_harness_research_pool(
    pool_root: Path,
    *,
    executable_account_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest formal verified research into a harness pool (content-addressed).

    Returns the sealed pool entry. Reuses the same CAS root across periods so
    multi-period freezes share one research identity without fixture freezes.
    """

    pool_root = pool_root.expanduser().resolve()
    pool_root.mkdir(parents=True, exist_ok=True)
    fixture_dir = _HARNESS_RESEARCH_FIXTURE_DIR
    result_path = fixture_dir / "result.json"
    receipt_path = fixture_dir / "receipt.json"
    if not result_path.is_file() or not receipt_path.is_file():
        raise RoleFitnessAcceptanceError(f"harness research fixture missing under {fixture_dir}")
    result_bytes = result_path.read_bytes()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise RoleFitnessAcceptanceError("harness research receipt must be a JSON object")
    if executable_account_decision is not None:
        # Acceptance-only derived fixture: producer bytes and receipt both carry
        # the same explicit execution core, then receive a new content identity.
        result = json.loads(result_bytes.decode("utf-8"))
        candidate = result.get("candidate") if isinstance(result, dict) else None
        if not isinstance(candidate, dict):
            raise RoleFitnessAcceptanceError("harness research candidate missing")
        candidate["executable_account_decision"] = dict(executable_account_decision)
        receipt["candidate"] = json.loads(json.dumps(candidate))
        result_bytes = (
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        result_sha256 = hashlib.sha256(result_bytes).hexdigest()
        receipt["result_sha256"] = result_sha256
        terminal = receipt.get("container_terminal_attestation")
        if not isinstance(terminal, dict):
            raise RoleFitnessAcceptanceError("harness terminal attestation missing")
        terminal["result_sha256"] = result_sha256
    try:
        return ingest_verified_research_result(
            pool_root=pool_root,
            result_bytes=result_bytes,
            receipt=receipt,
        )
    except Exception as exc:  # noqa: BLE001 - surface as harness failure
        raise RoleFitnessAcceptanceError(f"harness pool ingest failed: {exc}") from exc


def write_harness_owner_disposition_for_portfolio_freeze(
    *,
    owner_state_root: Path,
    pool_root: Path,
    pool_entry: Mapping[str, Any],
    portfolio_root: Path,
    account_identity: str,
    open_at: datetime,
    selected_number: int = 1,
    episode_prefix: str = "episode.role-fitness",
    panel: str = "B",
    stake: str = "1.0000",
) -> dict[str, Any]:
    """Write a disposition-bound Owner CAS artifact for the live portfolio head.

    ACTION uses RETAIN_FOR_SHADOW (shadow production without science ADOPT).
    NO_ACTION uses ABSORB_NO_ACTION. Both seal closed portfolio_binding from live head.
    """

    if account_identity not in ALLOWED_ACCOUNT_IDENTITIES:
        raise RoleFitnessAcceptanceError(f"unsupported account identity: {account_identity}")
    cutoff, frozen_at, deadline = _times(open_at)
    portfolio_binding = build_portfolio_binding_from_shadow(portfolio_root)
    period_index = int(portfolio_binding["intended_next_period_index"])
    target_ref = f"draw.role-fitness.p{period_index:02d}"
    episode_ref = f"{episode_prefix}.p{period_index}"
    science_disposition = (
        SCIENCE_RETAIN_FOR_SHADOW if account_identity == "ACTION" else SCIENCE_ABSORB_NO_ACTION
    )
    body: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        "disposition_source": CODEX_OWNER_CHANNEL_SOURCE,
        "owner_role": OWNER_ROLE,
        "worker_controlled": False,
        "result_sha256": pool_entry["result_sha256"],
        "receipt_content_sha256": pool_entry["receipt_content_sha256"],
        "pool_entry_content_hash": pool_entry["content_hash"],
        "period_index": period_index,
        "episode_ref": episode_ref,
        "target_ref": target_ref,
        "knowledge_cutoff": _iso_z(cutoff),
        "science_disposition": science_disposition,
        "account_identity": account_identity,
        "portfolio_binding": portfolio_binding,
        "rationale_ref": "role-fitness-acceptance-harness-owner-disposition",
    }
    if account_identity == "ACTION":
        body["executable_account_decision"] = {
            **_harness_action_core(
                target_ref=target_ref,
                open_at=open_at,
                selected_number=selected_number,
                panel=panel,
                stake=stake,
            ),
            "frozen_at": _iso_z(frozen_at),
        }
    else:
        body["no_action_period_binding"] = {
            "target_ref": target_ref,
            "target_open_time": _iso_z(open_at),
            "freeze_deadline": _iso_z(deadline),
            "frozen_at": _iso_z(frozen_at),
            "knowledge_cutoff": _iso_z(cutoff),
            "rule_ref": MECHANICAL_RULE_REF,
            "odds_version_ref": ODDS_VERSION_REF,
        }
    try:
        written = write_owner_disposition_artifact(
            owner_state_root=owner_state_root,
            payload=body,
            pool_root=pool_root,
        )
    except OwnerDispositionError as exc:
        raise RoleFitnessAcceptanceError(f"owner disposition write rejected: {exc}") from exc
    return {
        **written,
        "period_index": period_index,
        "target_ref": target_ref,
        "episode_ref": episode_ref,
        "account_identity": account_identity,
        "frozen_at": frozen_at,
        "freeze_deadline": deadline,
        "portfolio_binding": portfolio_binding,
    }


def freeze_portfolio_period_with_formal_owner_authority(
    *,
    portfolio_root: Path,
    work_dir: Path,
    account_mode: str,
    open_at: datetime,
    selected_number: int = 1,
    pool_root: Path | None = None,
    owner_state_root: Path | None = None,
    pool_entry: Mapping[str, Any] | None = None,
    episode_prefix: str = "episode.role-fitness",
    panel: str = "B",
    stake: str = "1.0000",
) -> dict[str, Any]:
    """Freeze via formal pool → disposition CAS → research binding → owner_authority.

    Does not use the production freeze fixture bypass. Host freeze-action time is the
    sealed disposition frozen_at (pre-deadline test seam via adapter clock).
    """

    work_dir = work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    mode = account_mode.upper()
    if mode in {"ACTION", "ACTION_HIT"}:
        account_identity = "ACTION"
    elif mode in {"NO_ACTION", "RESEARCHER_ACCOUNT_NO_ACTION"}:
        account_identity = "RESEARCHER_ACCOUNT_NO_ACTION"
    else:
        raise RoleFitnessAcceptanceError(f"unsupported account_mode: {account_mode}")

    pool_root = (pool_root or (work_dir / "research-pool")).expanduser().resolve()
    owner_state_root = (owner_state_root or (work_dir / "owner-state")).expanduser().resolve()
    owner_state_root.mkdir(parents=True, exist_ok=True)
    if pool_entry is not None:
        entry = dict(pool_entry)
    elif account_identity == "ACTION":
        intended = int(
            build_portfolio_binding_from_shadow(portfolio_root)["intended_next_period_index"]
        )
        target_ref = f"draw.role-fitness.p{intended:02d}"
        entry = ensure_harness_research_pool(
            pool_root,
            executable_account_decision=_harness_action_core(
                target_ref=target_ref,
                open_at=open_at,
                selected_number=selected_number,
                panel=panel,
                stake=stake,
            ),
        )
    else:
        entry = ensure_harness_research_pool(pool_root)

    written = write_harness_owner_disposition_for_portfolio_freeze(
        owner_state_root=owner_state_root,
        pool_root=pool_root,
        pool_entry=entry,
        portfolio_root=portfolio_root,
        account_identity=account_identity,
        open_at=open_at,
        selected_number=selected_number,
        episode_prefix=episode_prefix,
        panel=panel,
        stake=stake,
    )
    frozen_at = written["frozen_at"]
    assert isinstance(frozen_at, datetime)
    try:
        result = apply_freeze_from_disposition(
            pool_root=pool_root,
            owner_state_root=owner_state_root,
            disposition_path=Path(str(written["disposition_path"])),
            shadow_root=portfolio_root,
            mode="portfolio",
            # Host freeze-action time must be on/before sealed deadline.
            clock=lambda: frozen_at,
        )
    except (FreezeAdapterError, OwnerDispositionError, StoreError) as exc:
        raise RoleFitnessAcceptanceError(f"formal owner-authority freeze rejected: {exc}") from exc
    if result.get("ok") is not True:
        raise RoleFitnessAcceptanceError("formal owner-authority freeze failed")
    return {
        **result,
        "pool_root": str(pool_root),
        "owner_state_root": str(owner_state_root),
        "pool_entry_result_sha256": entry["result_sha256"],
        "owner_disposition_sha256": written["owner_artifact_sha256"],
        "formal_owner_authority_path": True,
    }


def build_formal_freeze_request_and_owner_authority(
    *,
    portfolio_root: Path,
    work_dir: Path,
    account_mode: str,
    open_at: datetime,
    selected_number: int = 1,
    pool_root: Path | None = None,
    owner_state_root: Path | None = None,
    pool_entry: Mapping[str, Any] | None = None,
    episode_prefix: str = "episode.role-fitness",
) -> dict[str, Any]:
    """Build sealed disposition/binding/request + owner_authority envelope without freezing.

    Used by negative oracles that must prove peek/tamper rejection on the real consumer
    path after legal authority materials exist.
    """

    work_dir = work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    mode = account_mode.upper()
    if mode in {"ACTION", "ACTION_HIT"}:
        account_identity = "ACTION"
    elif mode in {"NO_ACTION", "RESEARCHER_ACCOUNT_NO_ACTION"}:
        account_identity = "RESEARCHER_ACCOUNT_NO_ACTION"
    else:
        raise RoleFitnessAcceptanceError(f"unsupported account_mode: {account_mode}")

    pool_root = (pool_root or (work_dir / "research-pool")).expanduser().resolve()
    owner_state_root = (owner_state_root or (work_dir / "owner-state")).expanduser().resolve()
    owner_state_root.mkdir(parents=True, exist_ok=True)
    if pool_entry is not None:
        entry = dict(pool_entry)
    elif account_identity == "ACTION":
        intended = int(
            build_portfolio_binding_from_shadow(portfolio_root)["intended_next_period_index"]
        )
        target_ref = f"draw.role-fitness.p{intended:02d}"
        entry = ensure_harness_research_pool(
            pool_root,
            executable_account_decision=_harness_action_core(
                target_ref=target_ref,
                open_at=open_at,
                selected_number=selected_number,
                panel="B",
                stake="1.0000",
            ),
        )
    else:
        entry = ensure_harness_research_pool(pool_root)
    written = write_harness_owner_disposition_for_portfolio_freeze(
        owner_state_root=owner_state_root,
        pool_root=pool_root,
        pool_entry=entry,
        portfolio_root=portfolio_root,
        account_identity=account_identity,
        open_at=open_at,
        selected_number=selected_number,
        episode_prefix=episode_prefix,
    )
    verified = load_and_verify_disposition(
        disposition_path=Path(str(written["disposition_path"])),
        owner_state_root=owner_state_root,
        pool_root=pool_root,
        result_sha256=str(entry["result_sha256"]),
    )
    disposition = verified["disposition"]
    frozen_at = written["frozen_at"]
    assert isinstance(frozen_at, datetime)
    binding_body = build_research_freeze_binding(
        pool_entry=entry,
        disposition=disposition,
        owner_artifact_sha256=str(written["owner_artifact_sha256"]),
        researcher_action_binding=verified["researcher_action_binding"],
        portfolio_binding=written["portfolio_binding"],
        freeze_action_time=frozen_at,
    )
    sealed = write_research_binding_exclusive(shadow_root=portfolio_root, body=binding_body)
    binding_hash = str(sealed["research_binding_sha256"])
    request = build_freeze_request_from_disposition(
        pool_entry=entry,
        disposition=disposition,
        owner_artifact_sha256=str(written["owner_artifact_sha256"]),
        research_binding_sha256=binding_hash,
        freeze_action_time=frozen_at,
    )
    owner_authority = {
        "schema_version": OWNER_FREEZE_AUTHORITY_SCHEMA,
        "authority_marker": OWNER_FREEZE_AUTHORITY_MARKER,
        "owner_state_root": str(Path(str(written["owner_state_root"])).expanduser().resolve()),
        "research_pool_root": str(pool_root),
        "owner_disposition_sha256": str(written["owner_artifact_sha256"]),
        "research_binding_sha256": binding_hash,
        "request_content_hash": str(request["request_content_hash"]),
    }
    return {
        "request": request,
        "owner_authority": owner_authority,
        "pool_root": str(pool_root),
        "owner_state_root": str(owner_state_root),
        "pool_entry": entry,
        "disposition_path": str(written["disposition_path"]),
        "owner_disposition_sha256": str(written["owner_artifact_sha256"]),
        "research_binding_sha256": binding_hash,
        "frozen_at": frozen_at,
    }


# ---------------------------------------------------------------------------
# Evidence validators (scientist plane may be DI/faked; must be labeled)
# ---------------------------------------------------------------------------


def reject_one_shot_text_only_transcript(transcript: Mapping[str, Any]) -> None:
    """Reject canary-style one-shot, tool-free, text-only essays as role-fitness."""

    turns = transcript.get("turns")
    tool_actions = transcript.get("tool_actions") or transcript.get("bounded_tool_actions")
    route = str(transcript.get("route") or transcript.get("profile") or "")
    if route == INSTRUMENT_CANARY_ROUTE:
        raise RoleFitnessAcceptanceError(
            "INSTRUMENT_CANARY one-shot/tool-free route cannot claim role fitness"
        )
    if not isinstance(turns, list) or len(turns) < 2:
        raise RoleFitnessAcceptanceError(
            "fake one-shot/text-only transcript rejected: require multi-turn scientist episode"
        )
    if not isinstance(tool_actions, list) or not tool_actions:
        raise RoleFitnessAcceptanceError(
            "fake one-shot/text-only transcript rejected: missing real bounded tool evidence"
        )


def _validate_event_chain(
    evidence: Mapping[str, Any],
    *,
    episode_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Require cryptographic event binding; bare multi-turn assertions are rejected."""

    chain = evidence.get("event_chain") or evidence.get("events")
    if not isinstance(chain, list) or len(chain) < 2:
        raise RoleFitnessAcceptanceError(
            "mock-shaped transcript rejected: require cryptographic event_chain binding "
            "(multi-turn/tool/failure/revision/resume assertions alone are insufficient)"
        )

    prior_hash: str | None = None
    sealed: list[dict[str, Any]] = []
    by_type: dict[str, list[str]] = {}
    for index, raw in enumerate(chain):
        event = _require_mapping(raw, f"event_chain[{index}]")
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq != index + 1:
            raise RoleFitnessAcceptanceError(
                f"event_chain[{index}].seq must be contiguous one-based int"
            )
        event_type = _require_text(event.get("event_type"), f"event_chain[{index}].event_type")
        payload_hash = _require_hash(
            event.get("payload_hash"), f"event_chain[{index}].payload_hash"
        )
        pred = event.get("predecessor_hash")
        if index == 0:
            if pred is not None:
                raise RoleFitnessAcceptanceError("event_chain[0].predecessor_hash must be null")
            pred_norm: str | None = None
        else:
            pred_norm = _require_hash(pred, f"event_chain[{index}].predecessor_hash")
            if pred_norm != prior_hash:
                raise RoleFitnessAcceptanceError(
                    f"event_chain[{index}] predecessor_hash does not bind prior event"
                )
        expected = _event_seal_hash(
            seq=seq,
            event_type=event_type,
            payload_hash=payload_hash,
            predecessor_hash=pred_norm,
            episode_id=episode_id,
            session_id=session_id,
        )
        observed = _require_hash(event.get("event_hash"), f"event_chain[{index}].event_hash")
        if observed != expected:
            raise RoleFitnessAcceptanceError(
                f"event_chain[{index}] event_hash seal mismatch (forged or unbound event)"
            )
        sealed.append(
            {
                "seq": seq,
                "event_type": event_type,
                "payload_hash": payload_hash,
                "predecessor_hash": pred_norm,
                "event_hash": observed,
            }
        )
        by_type.setdefault(event_type, []).append(observed)
        prior_hash = observed

    required_types = {
        "turn",
        "tool_action",
        "experiment_failed",
        "experiment_revised",
        "interrupt_checkpoint",
        "resume",
    }
    missing = sorted(required_types - set(by_type))
    if missing:
        raise RoleFitnessAcceptanceError(
            "event_chain missing required bound event types: " + ", ".join(missing)
        )
    turn_events = by_type.get("turn") or []
    if len(turn_events) < 2:
        raise RoleFitnessAcceptanceError(
            "event_chain requires >=2 cryptographically bound turn events"
        )
    return {
        "event_count": len(sealed),
        "head_hash": prior_hash,
        "event_hashes_by_type": by_type,
        "cryptographic_binding": True,
    }


def validate_prospective_protocol_pin_shape(pin: Mapping[str, Any]) -> dict[str, Any]:
    """Shape/temporal gate only — not formal science ProtocolPin admission.

    Rejects late freeze, outcome peek, and retrospective sources. Does not verify
    xinao.science_protocol_pin.v1 schema, active-parent binding, world bundle,
    exposure inventory, or trial ledger. That requires verify_science_episode_admission_file.
    """

    pin = _require_mapping(pin, "protocol_pin")
    episode_id = _require_text(pin.get("episode_id"), "protocol_pin.episode_id")
    protocol_pin_id = _require_text(pin.get("protocol_pin_id"), "protocol_pin.protocol_pin_id")
    frozen_at = _require_aware(pin.get("frozen_at"), "protocol_pin.frozen_at")
    target_open_time = _require_aware(pin.get("target_open_time"), "protocol_pin.target_open_time")
    exposure = _require_text(pin.get("exposure_status"), "protocol_pin.exposure_status").upper()
    if exposure != "UNEXPOSED":
        raise RoleFitnessAcceptanceError(
            "prospective ProtocolPin requires UNEXPOSED evaluation target"
        )
    if pin.get("evaluation_outcome_access") is not False:
        raise RoleFitnessAcceptanceError(
            "ProtocolPin evaluation_outcome_access must be explicitly false"
        )
    if not frozen_at < target_open_time:
        raise RoleFitnessAcceptanceError(
            "ProtocolPin must be frozen before target outcome open (late freeze)"
        )
    if pin.get("outcome_present") is True or pin.get("outcome") is not None:
        raise RoleFitnessAcceptanceError(
            "future peek rejected: ProtocolPin freeze must not include outcome material"
        )
    source = str(pin.get("source_class") or "prospective")
    if source.lower() in {"rq008", "retrospective", "backfill", "e1_retrospective"}:
        raise RoleFitnessAcceptanceError(
            "RQ008/retrospective evidence is ineligible for prospective ProtocolPin"
        )
    # Explicitly refuse treating a thin pin-shaped dict as formal admission.
    schema = pin.get("schema_version")
    formal_shape = schema == "xinao.science_protocol_pin.v1"
    return {
        "episode_id": episode_id,
        "protocol_pin_id": protocol_pin_id,
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "target_open_time": target_open_time.isoformat().replace("+00:00", "Z"),
        "exposure_status": exposure,
        "evaluation_outcome_access": False,
        "prospective_shape_ok": True,
        "formal_admission": False,
        "proof_class": PROOF_PROTOCOL_PIN_SHAPE,
        "schema_version": schema,
        "formal_schema_present": formal_shape,
    }


# Backward-compatible name: shape gate only (does not claim formal ProtocolPin).
def validate_prospective_protocol_pin(pin: Mapping[str, Any]) -> dict[str, Any]:
    return validate_prospective_protocol_pin_shape(pin)


def validate_formal_protocol_pin_admission(
    *,
    protocol_pin_path: Path,
    expected_file_sha256: str,
    expected_active_parent_sha256: str,
) -> dict[str, Any]:
    """Drive real science episode admission (schema, cutoff, unexposed target, siblings)."""

    try:
        from xinao.science.episode_admission import (
            ScienceEpisodeAdmissionError,
            verify_science_episode_admission_file,
        )
    except ImportError as exc:
        raise RoleFitnessAcceptanceError(f"science episode admission import failed: {exc}") from exc

    try:
        admitted = verify_science_episode_admission_file(
            Path(protocol_pin_path),
            expected_file_sha256=expected_file_sha256,
            expected_active_parent_sha256=expected_active_parent_sha256,
        )
    except ScienceEpisodeAdmissionError as exc:
        raise RoleFitnessAcceptanceError(f"formal ProtocolPin admission rejected: {exc}") from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RoleFitnessAcceptanceError(
            f"formal ProtocolPin admission failed closed: {exc}"
        ) from exc

    if admitted.get("allowed") is not True:
        raise RoleFitnessAcceptanceError("formal ProtocolPin admission not allowed")
    if admitted.get("evaluation_outcome_access") is not False:
        raise RoleFitnessAcceptanceError(
            "formal ProtocolPin must keep evaluation_outcome_access=false"
        )
    return {
        "formal_admission": True,
        "proof_class": PROOF_PROTOCOL_PIN_FORMAL,
        "episode_id": admitted.get("episode_id"),
        "protocol_pin_id": admitted.get("protocol_pin_id"),
        "protocol_pin_sha256": admitted.get("protocol_pin_sha256"),
        "active_parent_sha256": admitted.get("active_parent_sha256"),
        "exposure_status": admitted.get("exposure_status"),
        "evaluation_outcome_access": False,
        "claim_intent": admitted.get("claim_intent"),
        "prospective_shape_ok": True,
    }


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_raw_artifact_bytes(artifact: Mapping[str, Any], label: str) -> bytes:
    """Load raw bytes from inline content or path; bind declared sha256."""

    artifact = _require_mapping(artifact, label)
    declared = _require_hash(artifact.get("sha256"), f"{label}.sha256")
    if "content_utf8" in artifact:
        text = artifact.get("content_utf8")
        if not isinstance(text, str) or "\x00" in text:
            raise RoleFitnessAcceptanceError(f"{label}.content_utf8 must be plain UTF-8 text")
        payload = text.encode("utf-8")
    elif "content_b64" in artifact:
        import base64

        try:
            payload = base64.b64decode(str(artifact.get("content_b64") or ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise RoleFitnessAcceptanceError(f"{label}.content_b64 invalid") from exc
    elif artifact.get("path") is not None:
        path = Path(str(artifact.get("path")))
        if not path.is_file():
            raise RoleFitnessAcceptanceError(f"{label}.path missing: {path}")
        payload = path.read_bytes()
    else:
        raise RoleFitnessAcceptanceError(
            f"{label} requires content_utf8, content_b64, or path for hashed raw evidence"
        )
    observed = _hash_bytes(payload)
    if observed != declared:
        raise RoleFitnessAcceptanceError(
            f"{label} sha256 mismatch: declared={declared} observed={observed}"
        )
    return payload


def bind_native_session_mcp_paths(
    evidence: Mapping[str, Any],
    *,
    session_artifact: Path | None = None,
    mcp_events: Path | None = None,
) -> dict[str, Any]:
    """Minimum native-receipt interface: attach hashed path artifacts only.

    Does not invent multi-turn narrative, Owner signature, target, outcome, or profit.
    Never sets genuine role fitness. Synthetic fixtures must remain explicit elsewhere.
    """

    out = dict(evidence)
    if session_artifact is not None:
        path = Path(session_artifact)
        if not path.is_file():
            raise RoleFitnessAcceptanceError(f"session_artifact missing: {path}")
        raw = path.read_bytes()
        out["raw_session_artifact"] = {
            "path": str(path),
            "sha256": _hash_bytes(raw),
            "kind": "grok_session_json",
        }
        try:
            session_obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoleFitnessAcceptanceError(
                "session_artifact must be UTF-8 JSON Grok session envelope"
            ) from exc
        if not isinstance(session_obj, Mapping):
            raise RoleFitnessAcceptanceError("session_artifact JSON must be an object")
        sid = (
            session_obj.get("sessionId")
            or session_obj.get("session_id")
            or (session_obj.get("provider") or {}).get("session_id")
        )
        if isinstance(sid, str) and sid.strip():
            out["session_id"] = sid.strip()
        eid = session_obj.get("episode_id") or session_obj.get("bound_episode_id")
        if isinstance(eid, str) and eid.strip():
            out["episode_id"] = eid.strip()
    if mcp_events is not None:
        path = Path(mcp_events)
        if not path.is_file():
            raise RoleFitnessAcceptanceError(f"mcp_events missing: {path}")
        raw = path.read_bytes()
        out["raw_mcp_artifacts"] = [
            {
                "path": str(path),
                "sha256": _hash_bytes(raw),
                "kind": "mcp_ipc_events_jsonl",
            }
        ]
    out["proof_class"] = PROOF_NATIVE_SESSION_MCP
    # Never invent authenticity / RF / Owner authority from path binding alone.
    out.pop("live_episode_attestation", None)
    out.pop("genuine_role_fitness", None)
    out.pop("owner_adopted", None)
    out.pop("parent_complete", None)
    return out


def consume_native_episode_receipt(
    *,
    session_artifact: Path,
    mcp_events: Path,
    scientist_evidence_path: Path | None = None,
) -> dict[str, Any]:
    """Consume native Grok session + MCP traces with structured episode evidence.

    Real consumers (owner-vertical) must supply the structured multi-turn / tool /
    fail→revise / interrupt→resume / event_chain package separately. This refuses
    the fake driver that glued synthetic fixture narrative onto live path hashes.
    """

    if scientist_evidence_path is None:
        raise RoleFitnessAcceptanceError(
            "native episode receipt requires --scientist-evidence JSON "
            "(multi-turn/tool/fail-revise/resume/event_chain); "
            "refusing synthetic fixture narrative glued onto live session/MCP hashes"
        )
    path = Path(scientist_evidence_path)
    if not path.is_file():
        raise RoleFitnessAcceptanceError(f"scientist_evidence missing: {path}")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoleFitnessAcceptanceError(f"scientist_evidence unreadable JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise RoleFitnessAcceptanceError("scientist_evidence must be a JSON object")
    # Fixture markers stay synthetic/false for role fitness.
    if str(body.get("route") or "") == INSTRUMENT_CANARY_ROUTE:
        raise RoleFitnessAcceptanceError(
            "INSTRUMENT_CANARY cannot be consumed as native scientist evidence"
        )
    return bind_native_session_mcp_paths(
        body,
        session_artifact=session_artifact,
        mcp_events=mcp_events,
    )


def validate_native_session_mcp_artifacts(
    evidence: Mapping[str, Any],
    *,
    episode_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Require hashed raw Grok session + MCP sidecar artifacts; reject bare transcripts."""

    evidence = _require_mapping(evidence, "scientist_episode")
    session_art = evidence.get("raw_session_artifact")
    mcp_arts = evidence.get("raw_mcp_artifacts")
    if session_art is None or mcp_arts is None:
        raise RoleFitnessAcceptanceError(
            "transcript assertions without hashed raw session/MCP evidence rejected: "
            "require raw_session_artifact and raw_mcp_artifacts with sha256 bindings"
        )
    session_bytes = _load_raw_artifact_bytes(
        _require_mapping(session_art, "raw_session_artifact"),
        "raw_session_artifact",
    )
    try:
        session_obj = json.loads(session_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoleFitnessAcceptanceError(
            "raw_session_artifact must be UTF-8 JSON Grok session envelope"
        ) from exc
    if not isinstance(session_obj, Mapping):
        raise RoleFitnessAcceptanceError("raw_session_artifact JSON must be an object")
    # Bind session identity: sessionId/session_id and multi-turn surface.
    observed_session = (
        session_obj.get("sessionId")
        or session_obj.get("session_id")
        or (session_obj.get("provider") or {}).get("session_id")
    )
    if str(observed_session or "") != session_id:
        raise RoleFitnessAcceptanceError(
            "raw_session_artifact session id does not bind scientist_episode.session_id"
        )
    num_turns = session_obj.get("num_turns")
    if type(num_turns) is not int or isinstance(num_turns, bool) or num_turns < 2:
        # Also accept explicit turns array inside the session envelope.
        sess_turns = session_obj.get("turns")
        if not isinstance(sess_turns, list) or len(sess_turns) < 2:
            raise RoleFitnessAcceptanceError(
                "raw_session_artifact requires num_turns>=2 (or turns[]) for multi-turn RF"
            )
        num_turns = len(sess_turns)

    if not isinstance(mcp_arts, list) or not mcp_arts:
        raise RoleFitnessAcceptanceError(
            "raw_mcp_artifacts must be a non-empty list of hashed MCP event artifacts"
        )
    mcp_event_hashes: list[str] = []
    real_mcp_tool_calls = 0
    for index, raw in enumerate(mcp_arts):
        art = _require_mapping(raw, f"raw_mcp_artifacts[{index}]")
        payload = _load_raw_artifact_bytes(art, f"raw_mcp_artifacts[{index}]")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RoleFitnessAcceptanceError(f"raw_mcp_artifacts[{index}] must be UTF-8") from exc
        # Accept single JSON object or JSONL of MCP/IPC events.
        events: list[dict[str, Any]] = []
        if "\n" in text.strip() and not text.strip().startswith("["):
            for line_no, line in enumerate(text.splitlines()):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RoleFitnessAcceptanceError(
                        f"raw_mcp_artifacts[{index}] JSONL line {line_no} invalid"
                    ) from exc
                if not isinstance(item, dict):
                    raise RoleFitnessAcceptanceError(
                        f"raw_mcp_artifacts[{index}] JSONL line {line_no} not object"
                    )
                events.append(item)
        else:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RoleFitnessAcceptanceError(
                    f"raw_mcp_artifacts[{index}] must be JSON or JSONL"
                ) from exc
            if isinstance(parsed, list):
                events = [item for item in parsed if isinstance(item, dict)]
            elif isinstance(parsed, dict):
                events = [parsed]
            else:
                raise RoleFitnessAcceptanceError(
                    f"raw_mcp_artifacts[{index}] must be object or array"
                )
        for event in events:
            # MCP sidecar / dual-container IPC response shape.
            op = event.get("op") or event.get("event_type") or event.get("tool")
            status = event.get("status")
            event_hash = event.get("event_hash")
            if event_hash is not None:
                mcp_event_hashes.append(_require_hash(event_hash, "mcp.event_hash"))
            if (
                op
                in {
                    "shell_exec",
                    "read_file",
                    "write_file",
                    "list_dir",
                    "tool_call",
                    "tool_result",
                    "Bash",
                    "python",
                    "code",
                }
                or event.get("tool_call") is True
            ):
                if status in {None, "ok", "success", "executed"} or event.get("executed") is True:
                    real_mcp_tool_calls += 1
            # episode_events.py tool_call / tool_result
            if event.get("event_type") in {"tool_call", "tool_result"}:
                real_mcp_tool_calls += 1
    if real_mcp_tool_calls < 1:
        raise RoleFitnessAcceptanceError(
            "raw_mcp_artifacts require at least one real MCP sidecar tool call event"
        )
    bound_episode = session_obj.get("episode_id") or session_obj.get("bound_episode_id")
    if bound_episode is not None and str(bound_episode) != episode_id:
        raise RoleFitnessAcceptanceError(
            "raw_session_artifact episode_id does not bind scientist_episode.episode_id"
        )
    return {
        "raw_session_sha256": _hash_bytes(session_bytes),
        "mcp_artifact_count": len(mcp_arts),
        "mcp_event_hash_count": len(mcp_event_hashes),
        "mcp_tool_call_count": real_mcp_tool_calls,
        "session_num_turns": num_turns,
        "native_session_mcp_bound": True,
        "proof_class": PROOF_NATIVE_SESSION_MCP,
    }


def validate_scientist_episode_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Multi-turn, tool, fail→revise, interrupt, resume — with raw session/MCP hashes.

    Bare multi-turn/tool/fail/revise/resume transcript fields without hashed raw
    Grok session + MCP sidecar artifacts are rejected. Shape success is not live RF.
    DI_GENUINE_SCIENTIST_SEAM is retired and fail-closed.
    """

    evidence = _require_mapping(evidence, "scientist_episode")
    reject_one_shot_text_only_transcript(evidence)

    route = _require_text(evidence.get("route"), "scientist_episode.route")
    if route != GENUINE_SCIENTIST_ROUTE:
        raise RoleFitnessAcceptanceError(
            f"scientist route must be {GENUINE_SCIENTIST_ROUTE}, not canary"
        )
    episode_id = _require_text(evidence.get("episode_id"), "scientist_episode.episode_id")
    session_id = _require_text(evidence.get("session_id"), "scientist_episode.session_id")
    turns = evidence.get("turns")
    if not isinstance(turns, list) or len(turns) < 2:
        raise RoleFitnessAcceptanceError("scientist episode requires more than one turn")

    # Native session + MCP hashed evidence is mandatory (replaces DI-only assertions).
    native = validate_native_session_mcp_artifacts(
        evidence, episode_id=episode_id, session_id=session_id
    )

    chain_info = _validate_event_chain(evidence, episode_id=episode_id, session_id=session_id)
    tool_event_hashes = set(chain_info["event_hashes_by_type"].get("tool_action") or [])
    fail_event_hashes = set(chain_info["event_hashes_by_type"].get("experiment_failed") or [])
    revise_event_hashes = set(chain_info["event_hashes_by_type"].get("experiment_revised") or [])
    ckpt_event_hashes = set(chain_info["event_hashes_by_type"].get("interrupt_checkpoint") or [])
    resume_event_hashes = set(chain_info["event_hashes_by_type"].get("resume") or [])

    tool_actions = evidence.get("bounded_tool_actions") or evidence.get("tool_actions")
    if not isinstance(tool_actions, list) or not tool_actions:
        raise RoleFitnessAcceptanceError(
            "missing tool evidence: require >=1 bounded code/tool action"
        )
    real_tool = False
    for index, action in enumerate(tool_actions):
        action_map = _require_mapping(action, f"tool_actions[{index}]")
        kind = _require_text(action_map.get("kind"), f"tool_actions[{index}].kind").lower()
        if kind not in ALLOWED_TOOL_KINDS:
            raise RoleFitnessAcceptanceError(f"unsupported tool kind: {kind}")
        if action_map.get("executed") is not True:
            raise RoleFitnessAcceptanceError(
                f"tool_actions[{index}] must record executed=true (real action, not narrative)"
            )
        if not _require_text(action_map.get("receipt_ref"), f"tool_actions[{index}].receipt_ref"):
            raise RoleFitnessAcceptanceError("tool action missing receipt_ref")
        bound = _require_hash(
            action_map.get("event_hash") or action_map.get("bound_event_hash"),
            f"tool_actions[{index}].event_hash",
        )
        if bound not in tool_event_hashes:
            raise RoleFitnessAcceptanceError(
                f"tool_actions[{index}] event_hash not bound in event_chain tool_action"
            )
        real_tool = True
    if not real_tool:
        raise RoleFitnessAcceptanceError("missing tool evidence")

    experiments = evidence.get("experiments")
    if not isinstance(experiments, list) or not experiments:
        raise RoleFitnessAcceptanceError("scientist episode requires experiment registry entries")
    failed_ids: list[str] = []
    revised_after_failure = False
    for index, exp in enumerate(experiments):
        exp_map = _require_mapping(exp, f"experiments[{index}]")
        exp_id = _require_text(exp_map.get("experiment_id"), f"experiments[{index}].experiment_id")
        status = _require_text(exp_map.get("status"), f"experiments[{index}].status").upper()
        bound = _require_hash(
            exp_map.get("event_hash") or exp_map.get("bound_event_hash"),
            f"experiments[{index}].event_hash",
        )
        if status in {"FAILED", "REJECTED", "ERROR"}:
            failed_ids.append(exp_id)
            if bound not in fail_event_hashes:
                raise RoleFitnessAcceptanceError(
                    f"experiments[{index}] failed event_hash not in event_chain"
                )
        prior = exp_map.get("revises_experiment_id")
        if prior is not None and str(prior) in failed_ids:
            revised_after_failure = True
            _require_text(
                exp_map.get("revision_note"),
                f"experiments[{index}].revision_note",
            )
            if bound not in revise_event_hashes:
                raise RoleFitnessAcceptanceError(
                    f"experiments[{index}] revision event_hash not in event_chain"
                )
    if not failed_ids:
        raise RoleFitnessAcceptanceError(
            "no revise-after-failure: require at least one failed experiment"
        )
    if not revised_after_failure:
        raise RoleFitnessAcceptanceError(
            "no revise-after-failure: later experiment must reference a failed prior"
        )

    interruption = _require_mapping(evidence.get("interruption"), "scientist_episode.interruption")
    if interruption.get("interrupted") is not True:
        raise RoleFitnessAcceptanceError("scientist episode requires an interruption")
    checkpoint_id = _require_text(interruption.get("checkpoint_id"), "interruption.checkpoint_id")
    checkpoint_hash = _require_hash(
        interruption.get("checkpoint_content_hash") or interruption.get("content_hash"),
        "interruption.checkpoint_content_hash",
    )
    ckpt_event = _require_hash(
        interruption.get("event_hash") or interruption.get("bound_event_hash"),
        "interruption.event_hash",
    )
    if ckpt_event not in ckpt_event_hashes:
        raise RoleFitnessAcceptanceError(
            "interruption event_hash not bound in event_chain interrupt_checkpoint"
        )

    resume = _require_mapping(evidence.get("resume"), "scientist_episode.resume")
    if resume.get("resumed") is not True:
        raise RoleFitnessAcceptanceError("scientist episode requires exact session resume")
    resume_episode = _require_text(resume.get("episode_id"), "resume.episode_id")
    resume_session = _require_text(resume.get("session_id"), "resume.session_id")
    resume_checkpoint = _require_text(resume.get("checkpoint_id"), "resume.checkpoint_id")
    if resume_episode != episode_id or resume_session != session_id:
        raise RoleFitnessAcceptanceError(
            "forged resume rejected: resume must bind exact episode/session identity"
        )
    if resume_checkpoint != checkpoint_id:
        raise RoleFitnessAcceptanceError(
            "forged resume rejected: checkpoint_id must match interruption checkpoint"
        )
    resume_ckpt_hash = _require_hash(
        resume.get("checkpoint_content_hash") or resume.get("content_hash"),
        "resume.checkpoint_content_hash",
    )
    if resume_ckpt_hash != checkpoint_hash:
        raise RoleFitnessAcceptanceError("forged resume rejected: checkpoint_content_hash mismatch")
    predecessor = _require_hash(resume.get("predecessor_hash"), "resume.predecessor_hash")
    if predecessor != checkpoint_hash and predecessor != chain_info["head_hash"]:
        # Allow binding either sealed checkpoint content or chain head after resume event prep.
        if predecessor not in ckpt_event_hashes:
            raise RoleFitnessAcceptanceError(
                "forged resume rejected: predecessor_hash must bind checkpoint or chain head"
            )
    resume_event = _require_hash(
        resume.get("event_hash") or resume.get("bound_event_hash"),
        "resume.event_hash",
    )
    if resume_event not in resume_event_hashes:
        raise RoleFitnessAcceptanceError("resume event_hash not bound in event_chain resume")

    proof_class = str(evidence.get("proof_class") or PROOF_NATIVE_SESSION_MCP).strip()
    if proof_class == PROOF_DI_SCIENTIST_SEAM:
        raise RoleFitnessAcceptanceError(
            f"{PROOF_DI_SCIENTIST_SEAM} is retired: require hashed raw session/MCP evidence "
            f"({PROOF_NATIVE_SESSION_MCP})"
        )
    if proof_class != PROOF_NATIVE_SESSION_MCP:
        raise RoleFitnessAcceptanceError(
            f"scientist proof_class must be {PROOF_NATIVE_SESSION_MCP}; got {proof_class}"
        )
    live_attestation = evidence.get("live_episode_attestation")
    genuine_role_fitness = False
    if live_attestation is not None:
        # Live RF remains Owner-only; worker-supplied attestation is not accepted.
        raise RoleFitnessAcceptanceError(
            "live_episode_attestation cannot be worker-supplied; "
            "genuine role fitness requires Owner-integrated live episode"
        )

    return {
        "route": route,
        "episode_id": episode_id,
        "session_id": session_id,
        "turn_count": len(turns),
        "tool_action_count": len(tool_actions),
        "failed_experiment_ids": failed_ids,
        "revised_after_failure": True,
        "checkpoint_id": checkpoint_id,
        "checkpoint_content_hash": checkpoint_hash,
        "resume_verified": True,
        "cryptographic_event_binding": True,
        "native_session_mcp_bound": True,
        "raw_session_sha256": native["raw_session_sha256"],
        "mcp_tool_call_count": native["mcp_tool_call_count"],
        "session_num_turns": native["session_num_turns"],
        "event_chain_head_hash": chain_info["head_hash"],
        "event_count": chain_info["event_count"],
        "proof_class": proof_class,
        "scientist_evidence_shape_ok": True,
        "genuine_role_fitness": genuine_role_fitness,
    }


def validate_candidate_and_owner_disposition(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Immutable candidate or typed NO_ACTION; structure + authenticity are separate axes.

    Worker-controlled owner_role/decision fields alone never prove Codex disposition.
    """

    bundle = _require_mapping(bundle, "candidate_disposition")
    science = _require_mapping(bundle.get("science_decision"), "science_decision")
    identity = _require_text(science.get("identity"), "science_decision.identity").upper()
    if identity not in ALLOWED_SCIENCE_IDENTITIES:
        raise RoleFitnessAcceptanceError(f"unsupported science identity: {identity}")
    science_ref = _require_text(
        science.get("science_decision_ref"), "science_decision.science_decision_ref"
    )
    if identity == "SCIENCE_CANDIDATE":
        candidate_ref = _require_text(
            science.get("candidate_ref"), "science_decision.candidate_ref"
        )
        if science.get("immutable") is not True:
            raise RoleFitnessAcceptanceError("SCIENCE_CANDIDATE must be marked immutable")
        candidate_hash = _require_hash(
            science.get("content_hash") or science.get("candidate_hash"),
            "science_decision.content_hash",
        )
    else:
        candidate_ref = None
        candidate_hash = None
        if science.get("candidate_ref") is not None:
            raise RoleFitnessAcceptanceError("POLICY_NO_ACTION must not carry candidate_ref")

    disposition = _require_mapping(bundle.get("owner_disposition"), "owner_disposition")
    owner_role = _require_text(
        disposition.get("owner_role"), "owner_disposition.owner_role"
    ).lower()
    if owner_role != OWNER_ROLE:
        raise RoleFitnessAcceptanceError("owner disposition must be Codex-only (owner_role=codex)")
    decision = _require_text(disposition.get("decision"), "owner_disposition.decision").upper()
    if decision not in ALLOWED_OWNER_DISPOSITIONS:
        raise RoleFitnessAcceptanceError(f"unsupported owner disposition: {decision}")
    if disposition.get("second_owner") is True:
        raise RoleFitnessAcceptanceError("second Owner is forbidden")

    # Authenticity: reject worker-controlled field self-attestation as Codex disposition.
    if disposition.get("worker_controlled") is True:
        raise RoleFitnessAcceptanceError(
            "Codex disposition represented by worker-controlled fields is rejected"
        )
    source = (
        str(
            disposition.get("disposition_source")
            or disposition.get("authority_source")
            or "worker_fixture"
        )
        .strip()
        .lower()
    )
    owner_disposition_authentic = False
    disposition_proof_class = PROOF_OWNER_DISPOSITION_STRUCTURE
    if source in WORKER_DISPOSITION_SOURCES or source == "":
        # Structure may still be validated; authenticity stays false.
        owner_disposition_authentic = False
        disposition_proof_class = PROOF_OWNER_DISPOSITION_STRUCTURE
    elif source == "codex_owner_channel":
        _require_hash(
            disposition.get("owner_artifact_sha256"),
            "owner_disposition.owner_artifact_sha256",
        )
        artifact_ref = disposition.get("owner_artifact_ref") or disposition.get(
            "owner_artifact_path"
        )
        if artifact_ref is None:
            raise RoleFitnessAcceptanceError(
                "CODEX_OWNER_CHANNEL disposition requires owner_artifact_ref"
            )
        # Harness does not mint Owner channel seals; authenticity requires external file
        # that is not under worker write roots — still integration-required when absent.
        artifact_path = Path(str(artifact_ref))
        if not artifact_path.is_file():
            raise RoleFitnessAcceptanceError(
                "CODEX_OWNER_CHANNEL owner_artifact_ref missing on disk "
                "(integration-required Owner channel)"
            )
        observed = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        expected = _require_hash(
            disposition.get("owner_artifact_sha256"),
            "owner_disposition.owner_artifact_sha256",
        )
        if observed != expected:
            raise RoleFitnessAcceptanceError("owner disposition artifact hash mismatch")
        owner_disposition_authentic = True
        disposition_proof_class = PROOF_OWNER_DISPOSITION_CHANNEL
    else:
        raise RoleFitnessAcceptanceError(f"unsupported owner disposition_source: {source}")

    account = _require_mapping(bundle.get("account_decision"), "account_decision")
    account_identity = _require_text(account.get("identity"), "account_decision.identity").upper()
    # Science POLICY_NO_ACTION must never substitute for an account decision.
    if account_identity == "POLICY_NO_ACTION":
        raise RoleFitnessAcceptanceError(
            "science NO_ACTION substituted for account decision rejected "
            "(POLICY_NO_ACTION is not a valid account identity; "
            "require RESEARCHER_ACCOUNT_NO_ACTION or ACTION)"
        )
    if (
        str(account.get("identity_source") or "").upper() == "SCIENCE_POLICY_NO_ACTION"
        or account.get("derived_from_science_policy_no_action") is True
    ):
        raise RoleFitnessAcceptanceError(
            "science NO_ACTION substituted for account decision rejected"
        )
    if account_identity not in ALLOWED_ACCOUNT_IDENTITIES:
        raise RoleFitnessAcceptanceError(f"unsupported account identity: {account_identity}")

    # Orthogonal axes: account ACTION may exist without science ADOPT; P&L never promotes.
    if bundle.get("scientific_promotion_from_pnl") is True:
        raise RoleFitnessAcceptanceError(
            "science/account cross-green: P&L must never promote science"
        )
    if account_identity == "ACTION" and decision not in {
        "ADOPT",
        "DEFER",
        "REJECT",
        "NO_ACTION",
        "ABSORB_NO_ACTION",
    }:
        raise RoleFitnessAcceptanceError("owner disposition missing for account ACTION path")
    science_adopted = decision == "ADOPT"
    account_action = account_identity == "ACTION"
    # ACTION admitted through scientific adoption alone is illegal cross-green.
    if account_action and science_adopted and account.get("admitted_via_science_adopt") is True:
        raise RoleFitnessAcceptanceError(
            "science/account cross-green: account ACTION must not be admitted through scientific adoption"
        )
    if account.get("gated_on_claim_grade") is True or account.get("gated_on_adopt") is True:
        raise RoleFitnessAcceptanceError(
            "science/account cross-green: account admission must not gate on ClaimGrade/ADOPT"
        )

    structure_ok = True
    # candidate_integrity covers structure + orthogonality; not Owner-channel authenticity.
    return {
        "science_identity": identity,
        "science_decision_ref": science_ref,
        "candidate_ref": candidate_ref,
        "candidate_hash": candidate_hash,
        "owner_role": owner_role,
        "owner_decision": decision,
        "account_identity": account_identity,
        "science_adopted": science_adopted,
        "account_action": account_action,
        "orthogonal_axes": True,
        "scientific_promotion_from_pnl": False,
        "structure_ok": structure_ok,
        "owner_disposition_authentic": owner_disposition_authentic,
        "disposition_proof_class": disposition_proof_class,
        "disposition_source": source,
    }


def reject_rq008_retrospective_backfill(evidence: Mapping[str, Any]) -> None:
    """RQ008 retrospective inventory is ineligible for Ticket/Settlement backfill."""

    evidence = _require_mapping(evidence, "rq008_evidence")
    source = (
        str(evidence.get("source") or evidence.get("adapter") or evidence.get("source_class") or "")
        .strip()
        .lower()
    )
    retro_markers = {"rq008", "retrospective", "backfill", "e1_retrospective", "e1"}
    is_rq008 = (
        "rq008" in source
        or source in retro_markers
        or evidence.get("retrospective") is True
        or evidence.get("rq008_backfill") is True
        or evidence.get("prospective_freeze_from_rq008") is True
    )
    if not is_rq008:
        return
    if evidence.get("ticket") is not None or evidence.get("Ticket") is not None:
        raise RoleFitnessAcceptanceError(
            "RQ008 retrospective evidence is ineligible for a backfilled Ticket"
        )
    if evidence.get("settlement") is not None or evidence.get("Settlement") is not None:
        raise RoleFitnessAcceptanceError(
            "RQ008 retrospective evidence is ineligible for a backfilled Settlement"
        )
    if (
        evidence.get("prospective_freeze") is True
        or evidence.get("prospective_freeze_from_rq008") is True
    ):
        raise RoleFitnessAcceptanceError(
            "RQ008 retrospective must not be relabeled as prospective freeze"
        )
    # Honest RQ008: mechanical inventory + Owner NO_ACTION, zero ticket/settlement.
    if evidence.get("owner_decision") not in (None, "NO_ACTION", "ABSORB_NO_ACTION"):
        # Still not a freeze path; allow only if no ticket/settlement (already checked).
        pass


def reject_synthetic_outcome_as_live(outcome: Mapping[str, Any]) -> None:
    """Independent live outcome path rejects synthetic/fixture source material."""

    outcome = _require_mapping(outcome, "outcome")
    source = str(outcome.get("source_ref") or outcome.get("source") or "").strip().lower()
    synthetic = any(marker in source for marker in _SYNTHETIC_OUTCOME_MARKERS)
    synthetic = synthetic or bool(
        outcome.get("synthetic_fixture") or outcome.get("fixture_labeled")
    )
    if synthetic:
        raise RoleFitnessAcceptanceError(
            "synthetic outcome presented as live rejected "
            "(require independent external observation)"
        )
    if outcome.get("verified") is not True:
        raise RoleFitnessAcceptanceError("live outcome observation must be verified=true")
    if not source or source in {"", "unknown"}:
        raise RoleFitnessAcceptanceError("live outcome requires non-empty independent source_ref")


# ---------------------------------------------------------------------------
# Real shadow consumer drivers (no second ledger)
# ---------------------------------------------------------------------------


def build_action_freeze_request(
    path: Path,
    *,
    open_at: datetime,
    period: int,
    selected_number: int = 1,
    panel: str = "B",
    stake: str = "1.0000",
    episode_prefix: str = "episode.role-fitness",
) -> Path:
    cutoff, frozen_at, deadline = _times(open_at)
    target_ref = f"draw.role-fitness.p{period:02d}"
    baseline = "BO0013" if panel == "B" else "BO0001"
    body = {
        "episode_ref": f"{episode_prefix}.p{period}",
        "science_decision": {
            "science_decision_ref": f"science.policy.p{period}",
            "identity": "POLICY_NO_ACTION",
            "knowledge_cutoff": cutoff.isoformat(),
            "rationale_ref": "account-action-without-science-adopt",
        },
        "account_decision": {
            "account_decision_ref": f"account.action.p{period}",
            "identity": "ACTION",
        },
        "bound_account_ticket": {
            "ticket_ref": f"account-ticket.p{period}",
            "target_ref": target_ref,
            "target_open_time": open_at.isoformat(),
            "freeze_deadline": deadline.isoformat(),
            "knowledge_cutoff": cutoff.isoformat(),
            "frozen_at": frozen_at.isoformat(),
            "panel": panel,
            "selected_number": selected_number,
            "stake": stake,
            "rule_ref": MECHANICAL_RULE_REF,
            "odds_version_ref": ODDS_VERSION_REF,
            "baseline_ref": baseline,
            "risk_policy_ref": "shadow-risk.max-one-unit.v1",
            "information_set_ref": f"information.p{period}.v1",
            "information_set_hash": "a" * 64,
        },
        "target_ref": target_ref,
        "target_open_time": open_at.isoformat(),
        "freeze_deadline": deadline.isoformat(),
        "frozen_at": frozen_at.isoformat(),
        "position_journal_group_ref": f"journal.position.p{period}",
    }
    return _write_json(path, body)


def build_no_action_freeze_request(
    path: Path,
    *,
    open_at: datetime,
    period: int,
    episode_prefix: str = "episode.role-fitness",
) -> Path:
    cutoff, frozen_at, deadline = _times(open_at)
    target_ref = f"draw.role-fitness.p{period:02d}"
    body = {
        "episode_ref": f"{episode_prefix}.p{period}",
        "science_decision": {
            "science_decision_ref": f"science.candidate.p{period}",
            "identity": "SCIENCE_CANDIDATE",
            "candidate_ref": "candidate.wild-overfit-is-still-testable",
            "knowledge_cutoff": cutoff.isoformat(),
            "rationale_ref": "account-no-action-does-not-green-or-kill-science",
        },
        "account_decision": {
            "account_decision_ref": f"account.no-action.p{period}",
            "identity": "RESEARCHER_ACCOUNT_NO_ACTION",
            "rule_ref": MECHANICAL_RULE_REF,
            "odds_version_ref": ODDS_VERSION_REF,
        },
        "target_ref": target_ref,
        "target_open_time": open_at.isoformat(),
        "freeze_deadline": deadline.isoformat(),
        "frozen_at": frozen_at.isoformat(),
    }
    return _write_json(path, body)


def build_outcome(
    path: Path,
    *,
    open_at: datetime,
    period: int,
    number: int,
    source_ref: str = "synthetic-harness-fixture-only",
) -> Path:
    return _write_json(
        path,
        {
            "outcome_ref": f"outcome.role-fitness.p{period}",
            "source_ref": source_ref,
            "target_ref": f"draw.role-fitness.p{period:02d}",
            "actual_special_number": number,
            "observed_at": (open_at + timedelta(hours=1)).isoformat(),
            "verified": True,
        },
    )


def run_two_period_shadow_consumer(
    *,
    portfolio_root: Path,
    work_dir: Path,
    seat_id: str = "seat.role-fitness.alpha",
    portfolio_ref: str = "portfolio.role-fitness.alpha",
    p1_mode: str = "ACTION_HIT",
    p2_mode: str = "NO_ACTION",
) -> dict[str, Any]:
    """Drive real shadow consumer: freeze → independent outcome → settle-all → feedback → carry.

    Freezes go through the formal Owner disposition / research-binding / owner_authority
    chain (no production freeze fixture bypass).
    """

    work_dir.mkdir(parents=True, exist_ok=True)
    open_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    open_2 = open_1 + timedelta(days=1)
    pool_root = work_dir / "research-pool"
    owner_state_root = work_dir / "owner-state"
    pool_entry = ensure_harness_research_pool(pool_root)

    initialized = init_portfolio(
        root=portfolio_root,
        seat_id=seat_id,
        portfolio_ref=portfolio_ref,
    )
    genesis_seat = load_seat(portfolio_root)

    if p1_mode == "ACTION_HIT":
        p1_account_mode = "ACTION"
        outcome_number_1 = 1
        expected_result_1 = "HIT"
        selected_1 = 1
    elif p1_mode == "NO_ACTION":
        p1_account_mode = "NO_ACTION"
        outcome_number_1 = 7
        expected_result_1 = "NO_EXPOSURE"
        selected_1 = 1
    else:
        raise RoleFitnessAcceptanceError(f"unsupported p1_mode: {p1_mode}")

    frozen_1 = freeze_portfolio_period_with_formal_owner_authority(
        portfolio_root=portfolio_root,
        work_dir=work_dir / "p1-authority",
        account_mode=p1_account_mode,
        open_at=open_1,
        selected_number=selected_1,
        pool_root=pool_root,
        owner_state_root=owner_state_root,
        pool_entry=None if p1_account_mode == "ACTION" else pool_entry,
    )
    if frozen_1.get("ok") is not True:
        raise RoleFitnessAcceptanceError("period-1 freeze failed")
    # Independent OutcomeObservation (not part of freeze request).
    out1 = build_outcome(
        work_dir / "p1-outcome.json", open_at=open_1, period=1, number=outcome_number_1
    )
    settled_1 = settle_portfolio_period(root=portfolio_root, outcome_path=out1)
    if settled_1.get("statement_result") != expected_result_1:
        raise RoleFitnessAcceptanceError(
            f"period-1 settle result {settled_1.get('statement_result')} != {expected_result_1}"
        )
    if settled_1.get("scientific_promotion") is True:
        raise RoleFitnessAcceptanceError("science/account cross-green on settle receipt")
    # Synthetic HIT must never imply parent completion.
    if settled_1.get("parent_complete") is True or settled_1.get("parent_completion") is True:
        raise RoleFitnessAcceptanceError(
            "parent completion false green: synthetic HIT must not set parent_completion"
        )
    feedback_1 = feedback_portfolio_period(
        root=portfolio_root,
        kind=FeedbackKind.NO_CHANGE_WITH_REASON,
        reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
    )
    if feedback_1.get("scientific_promotion") is True:
        raise RoleFitnessAcceptanceError("feedback must not promote science")

    p1_close = str(settled_1["closing_balance"])
    if p2_mode == "NO_ACTION":
        p2_account_mode = "NO_ACTION"
        outcome_number_2 = 49
        expected_result_2 = "NO_EXPOSURE"
        selected_2 = 1
    elif p2_mode == "ACTION_HIT":
        p2_account_mode = "ACTION"
        outcome_number_2 = 1
        expected_result_2 = "HIT"
        selected_2 = 1
    else:
        raise RoleFitnessAcceptanceError(f"unsupported p2_mode: {p2_mode}")

    frozen_2 = freeze_portfolio_period_with_formal_owner_authority(
        portfolio_root=portfolio_root,
        work_dir=work_dir / "p2-authority",
        account_mode=p2_account_mode,
        open_at=open_2,
        selected_number=selected_2,
        pool_root=pool_root,
        owner_state_root=owner_state_root,
        pool_entry=None if p2_account_mode == "ACTION" else pool_entry,
    )
    episode_2 = load_frozen(period_directory(portfolio_root, 2))
    if episode_2.pre_freeze_balance != p1_close:
        raise RoleFitnessAcceptanceError(
            "stale portfolio/research head: period-2 pre_freeze must equal period-1 close"
        )
    if episode_2.prior_close_binding is None:
        raise RoleFitnessAcceptanceError("period-2 missing prior close binding")
    if episode_2.prior_close_binding.prior_closing_balance != p1_close:
        raise RoleFitnessAcceptanceError("prior closing balance mismatch")

    out2 = build_outcome(
        work_dir / "p2-outcome.json", open_at=open_2, period=2, number=outcome_number_2
    )
    settled_2 = settle_portfolio_period(root=portfolio_root, outcome_path=out2)
    if settled_2.get("statement_result") != expected_result_2:
        raise RoleFitnessAcceptanceError(
            f"period-2 settle result {settled_2.get('statement_result')} != {expected_result_2}"
        )
    feedback_2 = feedback_portfolio_period(
        root=portfolio_root,
        kind=FeedbackKind.TYPED_FEEDBACK,
        notes="carry same-seat closing balance; no science promotion",
    )
    if feedback_2.get("scientific_promotion") is True:
        raise RoleFitnessAcceptanceError("period-2 feedback promoted science")

    replay_1 = replay_portfolio_period(root=portfolio_root, period_index=1)
    replay_2 = replay_portfolio_period(root=portfolio_root, period_index=2)
    if replay_1.get("replay_match") is not True or replay_2.get("replay_match") is not True:
        raise RoleFitnessAcceptanceError("replay mismatch on sealed periods")

    final = inspect_portfolio(root=portfolio_root)
    if final.get("scientific_promotion") is True:
        raise RoleFitnessAcceptanceError("portfolio inspect promoted science")
    if final.get("completion_claim_allowed") is not False:
        raise RoleFitnessAcceptanceError("completion_claim_allowed must remain false")
    if final.get("parent_complete") is True or final.get("parent_completion") is True:
        raise RoleFitnessAcceptanceError(
            "parent completion false green from synthetic settlement path"
        )
    if load_seat(portfolio_root) != genesis_seat:
        raise RoleFitnessAcceptanceError("seat identity drift / recapitalization detected")

    return {
        "ok": True,
        "initialized": initialized,
        "period_1": {
            "frozen": frozen_1,
            "settled": settled_1,
            "feedback_hash": feedback_1.get("feedback_hash"),
        },
        "period_2": {
            "frozen": frozen_2,
            "settled": settled_2,
            "pre_freeze_balance": episode_2.pre_freeze_balance,
            "prior_closing_balance": episode_2.prior_close_binding.prior_closing_balance,
            "feedback_hash": feedback_2.get("feedback_hash"),
        },
        "replay_match": {"period_1": True, "period_2": True},
        "inspect": final,
        "closing_balance_carried": final.get("closing_balance") == settled_2.get("closing_balance"),
        "scientific_promotion": False,
        "same_seat": True,
        "parent_completion": False,
        "proof_class": PROOF_REAL_SHADOW_CONSUMER,
        "formal_owner_authority": True,
        # HIT/MISS here is synthetic fixture outcome only — not a real future draw.
        "outcome_proof_class": PROOF_FUTURE_OUTCOME
        if p1_mode != "ACTION_HIT" and p2_mode != "ACTION_HIT"
        else "SYNTHETIC_FIXTURE_OUTCOME",
    }


# ---------------------------------------------------------------------------
# Negative oracles (public for tests)
# ---------------------------------------------------------------------------


def negative_future_peek_freeze(portfolio_root: Path, work_dir: Path) -> None:
    """Future outcome material must be rejected even with a legal owner_authority envelope."""

    init_portfolio(
        root=portfolio_root,
        seat_id="seat.neg.peek",
        portfolio_ref="portfolio.neg.peek",
    )
    open_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    materials = build_formal_freeze_request_and_owner_authority(
        portfolio_root=portfolio_root,
        work_dir=work_dir,
        account_mode="ACTION",
        open_at=open_at,
        selected_number=1,
    )
    request = dict(materials["request"])
    request["outcome"] = {"actual_special_number": 1}
    request["actual_special_number"] = 1
    # Re-seal content hash so the authority envelope binds the peek-tainted request;
    # rejection must still come from no-peek, not envelope hash drift.
    request.pop("request_content_hash", None)
    request["request_content_hash"] = canonical_sha256(
        {k: v for k, v in request.items() if k != "request_content_hash"}
    )
    owner_authority = dict(materials["owner_authority"])
    owner_authority["request_content_hash"] = request["request_content_hash"]
    try:
        freeze_portfolio_period(
            root=portfolio_root,
            request=request,
            owner_authority=owner_authority,
        )
    except (StoreError, ValueError, FreezeAdapterError) as exc:
        text = str(exc).lower()
        if "no-peek" in text or "peek" in text:
            return
        raise RoleFitnessAcceptanceError(f"expected no-peek rejection, got: {exc}") from exc
    raise RoleFitnessAcceptanceError("future peek freeze was incorrectly accepted")


def negative_late_freeze_protocol_pin() -> None:
    open_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    pin = {
        "episode_id": "ep.late",
        "protocol_pin_id": "pin.late",
        "frozen_at": (open_at + timedelta(hours=1)).isoformat(),
        "target_open_time": open_at.isoformat(),
        "exposure_status": "UNEXPOSED",
        "evaluation_outcome_access": False,
    }
    try:
        validate_prospective_protocol_pin(pin)
    except RoleFitnessAcceptanceError as exc:
        if "late freeze" in str(exc).lower() or "before target" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("late freeze was incorrectly accepted")


def negative_missing_tool_evidence() -> None:
    evidence = _minimal_scientist_evidence()
    evidence["bounded_tool_actions"] = []
    try:
        validate_scientist_episode_evidence(evidence)
    except RoleFitnessAcceptanceError as exc:
        if "tool" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("missing tool evidence was incorrectly accepted")


def negative_no_revise_after_failure() -> None:
    evidence = _minimal_scientist_evidence()
    evidence["experiments"] = [
        {
            "experiment_id": "e1",
            "status": "FAILED",
            "event_hash": evidence["experiments"][0]["event_hash"],
        },
        {"experiment_id": "e2", "status": "SUCCEEDED", "event_hash": "d" * 64},
    ]
    try:
        validate_scientist_episode_evidence(evidence)
    except RoleFitnessAcceptanceError as exc:
        if "revise" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("no revise-after-failure was incorrectly accepted")


def negative_forged_resume() -> None:
    evidence = _minimal_scientist_evidence()
    evidence["resume"]["session_id"] = "forged-session"
    try:
        validate_scientist_episode_evidence(evidence)
    except RoleFitnessAcceptanceError as exc:
        if "forged resume" in str(exc).lower() or "resume" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("forged resume was incorrectly accepted")


def negative_unbound_transcript_assertions() -> None:
    """Bare multi-turn/tool/fail/revise/resume without event_chain must fail closed."""

    evidence = _minimal_scientist_evidence()
    evidence.pop("event_chain", None)
    try:
        validate_scientist_episode_evidence(evidence)
    except RoleFitnessAcceptanceError as exc:
        if "event_chain" in str(exc).lower() or "cryptographic" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("unbound transcript assertions were incorrectly accepted")


def negative_mock_protocol_pin_as_formal() -> None:
    """ProtocolPin-shaped dict must not claim formal admission."""

    pin = build_fixture_protocol_pin()
    result = validate_prospective_protocol_pin_shape(pin)
    if result.get("formal_admission") is True:
        raise RoleFitnessAcceptanceError(
            "ProtocolPin-shaped dict incorrectly claimed formal admission"
        )
    if result.get("proof_class") != PROOF_PROTOCOL_PIN_SHAPE:
        raise RoleFitnessAcceptanceError("expected shape-only proof class on thin pin")


def negative_worker_controlled_disposition() -> None:
    bundle = build_fixture_candidate_disposition()
    bundle["owner_disposition"]["worker_controlled"] = True
    try:
        validate_candidate_and_owner_disposition(bundle)
    except RoleFitnessAcceptanceError as exc:
        if "worker-controlled" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("worker-controlled Codex disposition was incorrectly accepted")


def negative_selective_settlement(portfolio_root: Path, work_dir: Path) -> None:
    """Settle-all once-only: second settle on same head must fail closed."""

    init_portfolio(
        root=portfolio_root,
        seat_id="seat.neg.selective",
        portfolio_ref="portfolio.neg.selective",
    )
    open_at = datetime(2026, 8, 1, 8, tzinfo=UTC)
    freeze_portfolio_period_with_formal_owner_authority(
        portfolio_root=portfolio_root,
        work_dir=work_dir,
        account_mode="ACTION",
        open_at=open_at,
        selected_number=1,
    )
    out1 = build_outcome(work_dir / "sel-out1.json", open_at=open_at, period=1, number=1)
    settle_portfolio_period(root=portfolio_root, outcome_path=out1)
    out2 = build_outcome(work_dir / "sel-out2.json", open_at=open_at, period=1, number=2)
    try:
        settle_portfolio_period(root=portfolio_root, outcome_path=out2)
    except (StoreError, ValueError):
        return
    raise RoleFitnessAcceptanceError("selective/double settlement was incorrectly accepted")


def negative_recapitalization(portfolio_root: Path) -> None:
    init_portfolio(
        root=portfolio_root,
        seat_id="seat.neg.recap",
        portfolio_ref="portfolio.neg.recap",
    )
    try:
        init_portfolio(
            root=portfolio_root,
            seat_id="seat.neg.recap2",
            portfolio_ref="portfolio.neg.recap2",
            opening_balance="50000.0000",
        )
    except (StoreError, ValueError):
        return
    raise RoleFitnessAcceptanceError("recapitalization/second genesis was incorrectly accepted")


def negative_stale_portfolio_head(portfolio_root: Path, work_dir: Path) -> None:
    """Period-2 freezes only after feedback; early freeze must fail (stale/open head)."""

    init_portfolio(
        root=portfolio_root,
        seat_id="seat.neg.stale",
        portfolio_ref="portfolio.neg.stale",
    )
    open_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    open_2 = open_1 + timedelta(days=1)
    pool_root = work_dir / "research-pool"
    owner_state_root = work_dir / "owner-state"
    pool_entry = ensure_harness_research_pool(pool_root)
    freeze_portfolio_period_with_formal_owner_authority(
        portfolio_root=portfolio_root,
        work_dir=work_dir / "p1",
        account_mode="ACTION",
        open_at=open_1,
        selected_number=1,
        pool_root=pool_root,
        owner_state_root=owner_state_root,
        pool_entry=None,
    )
    try:
        freeze_portfolio_period_with_formal_owner_authority(
            portfolio_root=portfolio_root,
            work_dir=work_dir / "p2-early",
            account_mode="NO_ACTION",
            open_at=open_2,
            pool_root=pool_root,
            owner_state_root=owner_state_root,
            pool_entry=pool_entry,
        )
    except (StoreError, ValueError, RoleFitnessAcceptanceError, FreezeAdapterError):
        return
    raise RoleFitnessAcceptanceError("stale portfolio head advance was incorrectly accepted")


def negative_science_account_cross_green() -> None:
    bundle = {
        "science_decision": {
            "identity": "POLICY_NO_ACTION",
            "science_decision_ref": "sci.1",
        },
        "account_decision": {
            "identity": "ACTION",
            "gated_on_adopt": True,
        },
        "owner_disposition": {
            "owner_role": "codex",
            "decision": "DEFER",
            "disposition_source": "worker_fixture",
        },
        "scientific_promotion_from_pnl": True,
    }
    try:
        validate_candidate_and_owner_disposition(bundle)
    except RoleFitnessAcceptanceError as exc:
        if "cross-green" in str(exc).lower() or "promote" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("science/account cross-green was incorrectly accepted")


def negative_rq008_backfill() -> None:
    try:
        reject_rq008_retrospective_backfill(
            {
                "source": "RQ008",
                "retrospective": True,
                "ticket": {"ticket_ref": "forged"},
                "settlement": {"settlement_ref": "forged"},
            }
        )
    except RoleFitnessAcceptanceError as exc:
        if "RQ008" in str(exc) or "ineligible" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("RQ008 retrospective backfill was incorrectly accepted")


def _build_bound_event(
    *,
    seq: int,
    event_type: str,
    payload: Mapping[str, Any],
    predecessor_hash: str | None,
    episode_id: str,
    session_id: str,
) -> dict[str, Any]:
    payload_hash = _canonical_sha256(dict(payload))
    event_hash = _event_seal_hash(
        seq=seq,
        event_type=event_type,
        payload_hash=payload_hash,
        predecessor_hash=predecessor_hash,
        episode_id=episode_id,
        session_id=session_id,
    )
    return {
        "seq": seq,
        "event_type": event_type,
        "payload_hash": payload_hash,
        "predecessor_hash": predecessor_hash,
        "event_hash": event_hash,
    }


def _minimal_scientist_evidence() -> dict[str, Any]:
    episode_id = "ep.scientist.demo"
    session_id = "sess.scientist.demo"
    checkpoint_id = "ckpt.1"
    checkpoint_content = {
        "checkpoint_id": checkpoint_id,
        "episode_id": episode_id,
        "session_id": session_id,
        "phase": "interrupted",
    }
    checkpoint_hash = _canonical_sha256(checkpoint_content)

    specs: list[tuple[str, dict[str, Any]]] = [
        ("turn", {"turn": 1, "role": "scientist", "content": "plan experiment"}),
        ("turn", {"turn": 2, "role": "scientist", "content": "revise after failure"}),
        (
            "tool_action",
            {"kind": "python", "executed": True, "receipt_ref": "tool.receipt.1"},
        ),
        ("experiment_failed", {"experiment_id": "e1", "status": "FAILED"}),
        (
            "experiment_revised",
            {
                "experiment_id": "e2",
                "status": "SUCCEEDED",
                "revises_experiment_id": "e1",
                "revision_note": "fixed parameter bound after e1 failure",
            },
        ),
        (
            "interrupt_checkpoint",
            {
                "checkpoint_id": checkpoint_id,
                "checkpoint_content_hash": checkpoint_hash,
            },
        ),
        (
            "resume",
            {
                "episode_id": episode_id,
                "session_id": session_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_content_hash": checkpoint_hash,
            },
        ),
    ]
    chain: list[dict[str, Any]] = []
    pred: str | None = None
    for index, (event_type, payload) in enumerate(specs, start=1):
        event = _build_bound_event(
            seq=index,
            event_type=event_type,
            payload=payload,
            predecessor_hash=pred,
            episode_id=episode_id,
            session_id=session_id,
        )
        chain.append(event)
        pred = event["event_hash"]

    by_type: dict[str, str] = {}
    for event in chain:
        by_type.setdefault(event["event_type"], event["event_hash"])
        # keep first for tool/fail; last for resume-like
        by_type[event["event_type"]] = event["event_hash"]

    # Map types to the specific events we need (tool is 3rd, fail 4th, revise 5th, ckpt 6th, resume 7th)
    tool_hash = chain[2]["event_hash"]
    fail_hash = chain[3]["event_hash"]
    revise_hash = chain[4]["event_hash"]
    ckpt_hash = chain[5]["event_hash"]
    resume_hash = chain[6]["event_hash"]

    # Hashed raw Grok session + MCP sidecar artifacts (fixture-shaped, not live RF).
    session_envelope = {
        "schema_version": "xinao.grok_session_envelope.fixture.v1",
        "sessionId": session_id,
        "episode_id": episode_id,
        "num_turns": 2,
        "requested_model": "grok-4.5",
        "stopReason": "EndTurn",
        "turns": [
            {"turn": 1, "role": "scientist", "content": "plan experiment"},
            {"turn": 2, "role": "scientist", "content": "revise after failure"},
        ],
        "provider": {"session_id": session_id, "bound_episode_id": episode_id},
        "completion_claim_allowed": False,
    }
    session_text = json.dumps(session_envelope, ensure_ascii=False, sort_keys=True) + "\n"
    session_sha = hashlib.sha256(session_text.encode("utf-8")).hexdigest()

    mcp_event = {
        "schema_version": "xinao.dual_container_ipc_response.v1",
        "request_id": "req.fixture.tool.1",
        "episode_id": episode_id,
        "op": "shell_exec",
        "status": "ok",
        "exit_code": 0,
        "stdout": "experiment e1 failed; revised inputs written",
        "stderr": "",
        "reason_code": None,
        "event_hash": "b" * 64,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
        "executed": True,
        "tool_call": True,
    }
    # Recompute a stable fixture event_hash from core fields (not full IPC verify).
    mcp_core = {
        "episode_id": episode_id,
        "exit_code": 0,
        "op": "shell_exec",
        "request_id": "req.fixture.tool.1",
        "status": "ok",
        "stdout": mcp_event["stdout"],
        "stderr": "",
        "reason_code": None,
        "args": {"argv": ["python", "lab/run_e1.py"], "cwd_relative": "lab"},
    }
    mcp_event["event_hash"] = _canonical_sha256(mcp_core)
    mcp_text = json.dumps(mcp_event, ensure_ascii=False, sort_keys=True) + "\n"
    mcp_sha = hashlib.sha256(mcp_text.encode("utf-8")).hexdigest()

    return {
        "route": GENUINE_SCIENTIST_ROUTE,
        "episode_id": episode_id,
        "session_id": session_id,
        "proof_class": PROOF_NATIVE_SESSION_MCP,
        "raw_session_artifact": {
            "sha256": session_sha,
            "content_utf8": session_text,
            "kind": "grok_session_json",
        },
        "raw_mcp_artifacts": [
            {
                "sha256": mcp_sha,
                "content_utf8": mcp_text,
                "kind": "mcp_ipc_response_jsonl",
                "event_hash": mcp_event["event_hash"],
            }
        ],
        "turns": [
            {"turn": 1, "role": "scientist", "content": "plan experiment"},
            {"turn": 2, "role": "scientist", "content": "revise after failure"},
        ],
        "bounded_tool_actions": [
            {
                "kind": "python",
                "executed": True,
                "receipt_ref": "tool.receipt.1",
                "event_hash": tool_hash,
            }
        ],
        "experiments": [
            {
                "experiment_id": "e1",
                "status": "FAILED",
                "event_hash": fail_hash,
            },
            {
                "experiment_id": "e2",
                "status": "SUCCEEDED",
                "revises_experiment_id": "e1",
                "revision_note": "fixed parameter bound after e1 failure",
                "event_hash": revise_hash,
            },
        ],
        "interruption": {
            "interrupted": True,
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_hash": checkpoint_hash,
            "event_hash": ckpt_hash,
        },
        "resume": {
            "resumed": True,
            "episode_id": episode_id,
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_hash": checkpoint_hash,
            "predecessor_hash": checkpoint_hash,
            "event_hash": resume_hash,
        },
        "event_chain": chain,
    }


def build_fixture_protocol_pin(*, open_at: datetime | None = None) -> dict[str, Any]:
    open_at = open_at or datetime(2026, 9, 1, 8, tzinfo=UTC)
    frozen_at = open_at - timedelta(hours=2)
    return {
        "episode_id": "ep.prospective.fixture",
        "protocol_pin_id": "pin.prospective.fixture",
        "frozen_at": frozen_at.isoformat().replace("+00:00", "Z"),
        "target_open_time": open_at.isoformat().replace("+00:00", "Z"),
        "exposure_status": "UNEXPOSED",
        "evaluation_outcome_access": False,
        "outcome_present": False,
        "source_class": "prospective",
        # Intentionally not xinao.science_protocol_pin.v1 full pin — shape gate only.
        "proof_class": PROOF_PROTOCOL_PIN_SHAPE,
    }


def build_fixture_candidate_disposition(
    *,
    science_identity: str = "SCIENCE_CANDIDATE",
    account_identity: str = "ACTION",
    owner_decision: str = "DEFER",
) -> dict[str, Any]:
    science: dict[str, Any] = {
        "science_decision_ref": "science.fixture.1",
        "identity": science_identity,
    }
    if science_identity == "SCIENCE_CANDIDATE":
        science["candidate_ref"] = "candidate.fixture.wild"
        science["immutable"] = True
        science["content_hash"] = "c" * 64
    account = {"identity": account_identity, "account_decision_ref": "account.fixture.1"}
    return {
        "science_decision": science,
        "account_decision": account,
        "owner_disposition": {
            "owner_role": "codex",
            "decision": owner_decision,
            "second_owner": False,
            # Structure fixture only — not Codex channel authenticity.
            "disposition_source": "worker_fixture",
            "worker_controlled": False,
        },
        "scientific_promotion_from_pnl": False,
    }


# ---------------------------------------------------------------------------
# Integrated acceptance run + receipt
# ---------------------------------------------------------------------------


@dataclass
class AcceptanceAxes:
    carrier_control: bool = False
    role_fitness: bool = False
    candidate_integrity: bool = False
    account_continuity: bool = False
    parent_completion: bool = False  # always false in candidate harness

    def as_dict(self) -> dict[str, bool]:
        return {
            "carrier_control": self.carrier_control,
            "role_fitness": self.role_fitness,
            "candidate_integrity": self.candidate_integrity,
            "account_continuity": self.account_continuity,
            "parent_completion": False,
        }


def _evaluate_protocol_pin_block(
    *,
    protocol_pin: Mapping[str, Any] | None,
    formal_protocol_pin_path: Path | None,
    formal_protocol_pin_sha256: str | None,
    formal_active_parent_sha256: str | None,
    details: dict[str, Any],
    failures: list[str],
) -> bool:
    """Shared ProtocolPin shape + optional formal admission (no second pin driver)."""

    pin = protocol_pin or build_fixture_protocol_pin()
    formal_admission = False
    try:
        shape = validate_prospective_protocol_pin_shape(pin)
        details["protocol_pin_shape"] = shape
        details["proof_classes"]["protocol_pin_shape"] = shape.get("proof_class")
        if shape.get("formal_admission") is True:
            failures.append("protocol_pin shape incorrectly claimed formal_admission")
    except RoleFitnessAcceptanceError as exc:
        failures.append(f"protocol_pin_shape: {exc}")
        details["protocol_pin_shape"] = {"allowed": False, "error": str(exc)}

    if (
        formal_protocol_pin_path is not None
        and formal_protocol_pin_sha256
        and formal_active_parent_sha256
    ):
        try:
            formal = validate_formal_protocol_pin_admission(
                protocol_pin_path=formal_protocol_pin_path,
                expected_file_sha256=formal_protocol_pin_sha256,
                expected_active_parent_sha256=formal_active_parent_sha256,
            )
            details["protocol_pin_formal"] = formal
            details["proof_classes"]["protocol_pin_formal"] = formal.get("proof_class")
            formal_admission = formal.get("formal_admission") is True
        except RoleFitnessAcceptanceError as exc:
            failures.append(f"protocol_pin_formal: {exc}")
            details["protocol_pin_formal"] = {"formal_admission": False, "error": str(exc)}
            formal_admission = False
    else:
        details["protocol_pin_formal"] = {
            "formal_admission": False,
            "proof_class": PROOF_PROTOCOL_PIN_SHAPE,
            "reason": "no formal ProtocolPin path/hashes supplied; shape gate only",
        }
        details["proof_classes"]["protocol_pin_formal"] = PROOF_PROTOCOL_PIN_SHAPE
    details["formal_protocol_pin_admitted"] = formal_admission
    return formal_admission


def is_fixture_scientist_evidence(evidence: Mapping[str, Any] | None) -> bool:
    """True when evidence is synthetic/fixture-shaped (not live long research)."""

    if evidence is None:
        return True
    evidence = _require_mapping(evidence, "scientist_evidence")
    session = evidence.get("raw_session_artifact") or {}
    if isinstance(session, Mapping):
        schema = str(session.get("schema_version") or "")
        if "fixture" in schema.lower():
            return True
        raw = session.get("utf8") or session.get("text") or ""
        if isinstance(raw, str) and "fixture" in raw.lower() and "schema_version" in raw:
            return True
    for key in ("source_class", "evidence_class", "proof_label", "route"):
        value = str(evidence.get(key) or "").lower()
        if any(marker in value for marker in _SYNTHETIC_OUTCOME_MARKERS):
            return True
        if value == INSTRUMENT_CANARY_ROUTE.lower():
            return True
    if evidence.get("fixture_labeled") is True or evidence.get("synthetic_fixture") is True:
        return True
    # Demo episode ids used by the unit fixture helper.
    episode_id = str(evidence.get("episode_id") or "")
    session_id = str(evidence.get("session_id") or "")
    if episode_id.endswith(".demo") or session_id.endswith(".demo"):
        return True
    if episode_id == "ep.scientist.demo" or session_id == "sess.scientist.demo":
        return True
    return False


def _evaluate_scientist_block(
    *,
    scientist_evidence: Mapping[str, Any] | None,
    details: dict[str, Any],
    failures: list[str],
    require_full_shape: bool = False,
    require_live_research: bool = False,
) -> bool:
    """Shared scientist validator; synthetic fixtures stay role_fitness false.

    When ``require_live_research`` is true (Owner live commissioning), missing or
    fixture-shaped evidence fails closed — never silent demo fallback.
    """

    if require_live_research:
        if scientist_evidence is None:
            failures.append(
                "live research required: refuse silent fixture scientist fallback "
                "(supply native session+MCP+structured multi-turn/tool/fail-revise/resume)"
            )
            details["scientist_episode"] = {
                "allowed": False,
                "error": "missing live scientist evidence",
            }
            details["scientist_evidence_shape_ok"] = False
            details["genuine_role_fitness"] = False
            details["live_research_required"] = True
            return False
        if is_fixture_scientist_evidence(scientist_evidence):
            failures.append("live research required: fixture/synthetic scientist evidence rejected")
            details["scientist_episode"] = {
                "allowed": False,
                "error": "fixture scientist evidence rejected for live path",
            }
            details["scientist_evidence_shape_ok"] = False
            details["genuine_role_fitness"] = False
            details["live_research_required"] = True
            return False

    sci = scientist_evidence or _minimal_scientist_evidence()
    scientist_shape_ok = False
    try:
        details["scientist_episode"] = validate_scientist_episode_evidence(sci)
        scientist_shape_ok = (
            details["scientist_episode"].get("scientist_evidence_shape_ok") is True
            and details["scientist_episode"].get("cryptographic_event_binding") is True
            and details["scientist_episode"].get("native_session_mcp_bound") is True
            and details["scientist_episode"].get("proof_class") == PROOF_NATIVE_SESSION_MCP
        )
        if require_full_shape:
            scientist_shape_ok = scientist_shape_ok and (
                int(details["scientist_episode"].get("turn_count") or 0) > 1
                and int(details["scientist_episode"].get("tool_action_count") or 0) >= 1
                and details["scientist_episode"].get("revised_after_failure") is True
                and details["scientist_episode"].get("resume_verified") is True
            )
        details["proof_classes"]["scientist"] = PROOF_NATIVE_SESSION_MCP
        if details["scientist_episode"].get("genuine_role_fitness") is True:
            failures.append("harness incorrectly claimed genuine_role_fitness")
            scientist_shape_ok = False
        if require_live_research and is_fixture_scientist_evidence(sci):
            failures.append("live research required: fixture/synthetic scientist evidence rejected")
            scientist_shape_ok = False
    except RoleFitnessAcceptanceError as exc:
        failures.append(f"scientist_episode: {exc}")
        details["scientist_episode"] = {"allowed": False, "error": str(exc)}
        scientist_shape_ok = False
    details["scientist_evidence_shape_ok"] = scientist_shape_ok
    details["genuine_role_fitness"] = False
    details["live_research_required"] = require_live_research
    details["fixture_scientist_used"] = (
        is_fixture_scientist_evidence(scientist_evidence if scientist_evidence is not None else sci)
        and scientist_evidence is None
    )
    return scientist_shape_ok


def run_integrated_acceptance(
    *,
    work_root: Path,
    protocol_pin: Mapping[str, Any] | None = None,
    scientist_evidence: Mapping[str, Any] | None = None,
    candidate_disposition: Mapping[str, Any] | None = None,
    p1_mode: str = "ACTION_HIT",
    p2_mode: str = "NO_ACTION",
    canary_route_preserved: bool = True,
    rq008_evidence: Mapping[str, Any] | None = None,
    formal_protocol_pin_path: Path | None = None,
    formal_protocol_pin_sha256: str | None = None,
    formal_active_parent_sha256: str | None = None,
) -> dict[str, Any]:
    """Run the integrated proof and return a structured acceptance receipt.

    parent_completion is always false. Scientist evidence must bind hashed raw
    Grok session + MCP artifacts (NATIVE_GROK_SESSION_MCP_TRACE) and never greens
    live role fitness. Account path always drives the real shadow consumer.
    Formal ProtocolPin requires real admission.
    No DI scientist_runner: narrative seams are retired.
    """

    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    axes = AcceptanceAxes()
    details: dict[str, Any] = {
        "proof_classes": {},
    }
    failures: list[str] = []

    # 0) RQ008 ineligibility check (always run when provided or default honest NO_ACTION).
    if rq008_evidence is None:
        rq008_evidence = {
            "source": "RQ008",
            "retrospective": True,
            "owner_decision": "NO_ACTION",
            "ticket": None,
            "settlement": None,
            "prospective_freeze": False,
        }
    try:
        reject_rq008_retrospective_backfill(rq008_evidence)
        details["rq008_ineligible_for_backfill"] = True
    except RoleFitnessAcceptanceError as exc:
        failures.append(str(exc))
        details["rq008_ineligible_for_backfill"] = False

    # 1) Carrier control: canary preserved; no second ledger (we only call existing consumer).
    if canary_route_preserved:
        axes.carrier_control = True
        details["instrument_canary"] = INSTRUMENT_CANARY_ROUTE
        details["second_ledger_created"] = False
    else:
        failures.append("INSTRUMENT_CANARY not preserved")
        details["instrument_canary"] = None

    # 2) Prospective ProtocolPin — shape gate + optional formal admission
    formal_admission = _evaluate_protocol_pin_block(
        protocol_pin=protocol_pin,
        formal_protocol_pin_path=formal_protocol_pin_path,
        formal_protocol_pin_sha256=formal_protocol_pin_sha256,
        formal_active_parent_sha256=formal_active_parent_sha256,
        details=details,
        failures=failures,
    )

    # 3) Scientist episode — native session/MCP hashed trace (not DI narrative)
    scientist_shape_ok = _evaluate_scientist_block(
        scientist_evidence=scientist_evidence,
        details=details,
        failures=failures,
    )
    axes.role_fitness = False

    # 4) Candidate structure + disposition authenticity (separate)
    cand = candidate_disposition or build_fixture_candidate_disposition(
        science_identity="SCIENCE_CANDIDATE",
        account_identity="ACTION",
        owner_decision="DEFER",  # ACTION without ADOPT is legal
    )
    try:
        details["candidate_disposition"] = validate_candidate_and_owner_disposition(cand)
        details["proof_classes"]["owner_disposition"] = details["candidate_disposition"].get(
            "disposition_proof_class"
        )
        # Structure integrity: orthogonal axes + no P&L promotion.
        # Does not require Owner-channel authenticity (that is integration-required).
        axes.candidate_integrity = (
            details["candidate_disposition"]["orthogonal_axes"] is True
            and details["candidate_disposition"]["owner_role"] == OWNER_ROLE
            and details["candidate_disposition"]["scientific_promotion_from_pnl"] is False
            and details["candidate_disposition"]["structure_ok"] is True
        )
        # If worker claims authentic disposition without channel proof, fail closed.
        if (
            details["candidate_disposition"].get("owner_disposition_authentic") is True
            and details["candidate_disposition"].get("disposition_proof_class")
            != PROOF_OWNER_DISPOSITION_CHANNEL
        ):
            failures.append("owner disposition authenticity claim without CODEX_OWNER_CHANNEL")
            axes.candidate_integrity = False
    except RoleFitnessAcceptanceError as exc:
        failures.append(f"candidate_disposition: {exc}")
        details["candidate_disposition"] = {"allowed": False, "error": str(exc)}
        axes.candidate_integrity = False

    # 5) Real shadow account continuity
    portfolio_root = work_root / "portfolio"
    shadow_work = work_root / "shadow-work"
    try:
        if portfolio_root.exists() and any(portfolio_root.iterdir()):
            # isolated empty root required
            portfolio_root = work_root / f"portfolio-{_canonical_sha256({'t': str(work_root)})[:8]}"
        details["shadow_consumer"] = run_two_period_shadow_consumer(
            portfolio_root=portfolio_root,
            work_dir=shadow_work,
            p1_mode=p1_mode,
            p2_mode=p2_mode,
        )
        details["proof_classes"]["account"] = PROOF_REAL_SHADOW_CONSUMER
        axes.account_continuity = (
            details["shadow_consumer"].get("ok") is True
            and details["shadow_consumer"].get("closing_balance_carried") is True
            and details["shadow_consumer"].get("scientific_promotion") is False
            and details["shadow_consumer"].get("same_seat") is True
            and details["shadow_consumer"].get("parent_completion") is False
        )
        # Synthetic HIT must not green parent completion.
        p1_settled = details["shadow_consumer"].get("period_1", {}).get("settled", {})
        if p1_settled.get("statement_result") == "HIT" and (
            p1_settled.get("parent_complete") is True
            or details["shadow_consumer"].get("parent_completion") is True
        ):
            failures.append("parent completion became true from synthetic HIT")
            axes.account_continuity = False
            axes.parent_completion = False
    except Exception as exc:  # noqa: BLE001 - surface as harness failure
        failures.append(f"shadow_consumer: {exc}")
        details["shadow_consumer"] = {"ok": False, "error": str(exc)}
        axes.account_continuity = False

    axes.parent_completion = False

    # Honest harness pass: real account path + labeled DI scientist shape + structure +
    # canary + RQ008, without false-greening live role fitness (always false here).
    axes.role_fitness = False
    honest_harness_pass = (
        axes.carrier_control
        and scientist_shape_ok
        and axes.candidate_integrity
        and axes.account_continuity
        and not axes.parent_completion
        and not axes.role_fitness  # must remain false without Owner live RF
        and details.get("rq008_ineligible_for_backfill") is True
        and not failures
    )

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "status": "PASS" if honest_harness_pass else "FAIL",
        "carrier_control": axes.carrier_control,
        "role_fitness": False,
        "candidate_integrity": axes.candidate_integrity,
        "account_continuity": axes.account_continuity,
        "parent_completion": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "instrument_canary_preserved": canary_route_preserved,
        "genuine_scientist_route": GENUINE_SCIENTIST_ROUTE,
        "second_ledger_created": False,
        "rq008_retrospective_backfill_eligible": False,
        "scientist_evidence_shape_ok": scientist_shape_ok,
        "formal_protocol_pin_admitted": formal_admission,
        "genuine_role_fitness": False,
        "proof_classes": details.get("proof_classes", {}),
        "axes": axes.as_dict(),
        "details": details,
        "failures": failures,
        "candidate_only": True,
        "owner": OWNER_ROLE,
        "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
        "first_live_research_episode_host_command": FIRST_LIVE_RESEARCH_EPISODE_HOST_COMMAND,
        "notes": (
            "role_fitness remains false: NATIVE_GROK_SESSION_MCP_TRACE is evidence-shape only; "
            "formal ProtocolPin uses verify_science_episode_admission_file when supplied; "
            "Owner disposition channel and live RF are integration-required; "
            "synthetic HIT never sets parent_completion."
        ),
    }
    receipt["content_hash"] = _canonical_sha256(
        {k: v for k, v in receipt.items() if k != "content_hash"}
    )
    return receipt


def negative_transcript_without_raw_session_mcp() -> None:
    """Bare event_chain multi-turn/tool assertions without raw hashes must fail closed."""

    evidence = _minimal_scientist_evidence()
    evidence.pop("raw_session_artifact", None)
    evidence.pop("raw_mcp_artifacts", None)
    try:
        validate_scientist_episode_evidence(evidence)
    except RoleFitnessAcceptanceError as exc:
        text = str(exc).lower()
        if "raw" in text or "session" in text or "mcp" in text:
            return
        raise
    raise RoleFitnessAcceptanceError(
        "transcript without hashed raw session/MCP evidence was incorrectly accepted"
    )


def negative_fake_owner_fields() -> None:
    """Worker-minted owner_role/decision without channel proof cannot claim authenticity."""

    bundle = build_fixture_candidate_disposition()
    bundle["owner_disposition"]["owner_role"] = "codex"
    bundle["owner_disposition"]["decision"] = "ADOPT"
    bundle["owner_disposition"]["disposition_source"] = "worker"
    bundle["owner_disposition"]["worker_controlled"] = False
    result = validate_candidate_and_owner_disposition(bundle)
    if result.get("owner_disposition_authentic") is True:
        raise RoleFitnessAcceptanceError(
            "fake Owner fields incorrectly greened owner_disposition_authentic"
        )
    if result.get("disposition_proof_class") != PROOF_OWNER_DISPOSITION_STRUCTURE:
        raise RoleFitnessAcceptanceError("expected structure-only disposition proof class")


def negative_synthetic_hit_parent_completion(portfolio_root: Path, work_dir: Path) -> None:
    """Synthetic HIT settlement must never set parent_completion."""

    result = run_two_period_shadow_consumer(
        portfolio_root=portfolio_root,
        work_dir=work_dir,
        p1_mode="ACTION_HIT",
        p2_mode="NO_ACTION",
    )
    if result.get("parent_completion") is True:
        raise RoleFitnessAcceptanceError("synthetic HIT incorrectly set parent_completion")
    settled = result.get("period_1", {}).get("settled", {})
    if settled.get("parent_complete") is True or settled.get("parent_completion") is True:
        raise RoleFitnessAcceptanceError(
            "synthetic HIT incorrectly set parent_complete on settle receipt"
        )


def negative_fixture_glued_to_live_paths(tmp_root: Path) -> None:
    """Refuse synthetic fixture narrative glued onto live session/MCP path hashes."""

    tmp_root.mkdir(parents=True, exist_ok=True)
    fixture = _minimal_scientist_evidence()
    session_path = tmp_root / "grok-session.json"
    mcp_path = tmp_root / "mcp-events.jsonl"
    session_path.write_text(fixture["raw_session_artifact"]["content_utf8"], encoding="utf-8")
    mcp_path.write_text(fixture["raw_mcp_artifacts"][0]["content_utf8"], encoding="utf-8")
    try:
        consume_native_episode_receipt(
            session_artifact=session_path,
            mcp_events=mcp_path,
            scientist_evidence_path=None,
        )
    except RoleFitnessAcceptanceError as exc:
        text = str(exc).lower()
        if "scientist-evidence" in text or "fixture" in text or "refusing" in text:
            return
        raise
    raise RoleFitnessAcceptanceError(
        "fixture glued onto live session/MCP paths was incorrectly accepted"
    )


def negative_synthetic_profit_promotion() -> None:
    """Account P&L / synthetic HIT must never promote science (alias for cross-green)."""

    negative_science_account_cross_green()
    bundle = build_fixture_candidate_disposition(
        science_identity="POLICY_NO_ACTION",
        account_identity="ACTION",
        owner_decision="DEFER",
    )
    bundle["scientific_promotion_from_pnl"] = True
    try:
        validate_candidate_and_owner_disposition(bundle)
    except RoleFitnessAcceptanceError as exc:
        if "cross-green" in str(exc).lower() or "promote" in str(exc).lower():
            return
        raise
    raise RoleFitnessAcceptanceError("synthetic profit promotion was incorrectly accepted")


# ---------------------------------------------------------------------------
# Owner-invoked vertical (pre-outcome freeze + optional outcome continuation)
# ---------------------------------------------------------------------------


def seal_immutable_candidate_or_no_action(
    *,
    work_dir: Path,
    science_identity: str = "SCIENCE_CANDIDATE",
    account_identity: str = "ACTION",
    summary: str = "immutable candidate for Codex review only",
) -> dict[str, Any]:
    """Seal candidate bytes or typed researcher NO_ACTION for Codex review only."""

    work_dir.mkdir(parents=True, exist_ok=True)
    if science_identity == "SCIENCE_CANDIDATE":
        body = {
            "schema_version": "xinao.research_episode_candidate.v1",
            "status": "CANDIDATE_FOR_CODEX_REVIEW",
            "identity": "SCIENCE_CANDIDATE",
            "summary": summary,
            "immutable": True,
            "owner_adopted": False,
            "scientific_grade": None,
            "profitability_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "completion_claim_allowed": False,
        }
    else:
        body = {
            "schema_version": "xinao.research_episode_candidate.v1",
            "status": "TYPED_RESEARCHER_NO_ACTION",
            "identity": "POLICY_NO_ACTION",
            "summary": summary,
            "immutable": True,
            "owner_adopted": False,
            "scientific_grade": None,
            "profitability_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "completion_claim_allowed": False,
        }
    content_hash = _canonical_sha256(body)
    body["content_hash"] = content_hash
    path = work_dir / "sealed_candidate.json"
    _write_json(path, body)
    return {
        "science_identity": science_identity,
        "account_identity": account_identity,
        "candidate_path": str(path),
        "content_hash": content_hash,
        "codex_review_only": True,
        "owner_adopted": False,
        "parent_complete": False,
        "completion_claim_allowed": False,
    }


def run_owner_invoked_vertical_pre_outcome(
    *,
    work_root: Path,
    research_question: str = "Prospective unexposed target: special-number draw period-1",
    protocol_pin: Mapping[str, Any] | None = None,
    scientist_evidence: Mapping[str, Any] | None = None,
    codex_disposition: Mapping[str, Any] | None = None,
    formal_protocol_pin_path: Path | None = None,
    formal_protocol_pin_sha256: str | None = None,
    formal_active_parent_sha256: str | None = None,
    p1_account_mode: str = "ACTION",
    canary_route_preserved: bool = True,
    require_live_research: bool = False,
) -> dict[str, Any]:
    """Bounded Owner vertical through pre-outcome freeze (future outcome unavailable).

    Order: unexposed target/ProtocolPin → scientist episode (native session/MCP) →
    immutable candidate or typed NO_ACTION → Codex disposition → independent science
    and account decisions → pre-outcome freeze. Does not settle; parent_completion false.

    ``require_live_research=True`` (commissioning live path) refuses silent fixture
    scientist fallback and keeps completion_claim_allowed false.
    """

    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    details: dict[str, Any] = {
        "proof_classes": {},
        "phase": "pre_outcome",
        "research_question": research_question,
        "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
        "first_live_research_episode_host_command": FIRST_LIVE_RESEARCH_EPISODE_HOST_COMMAND,
        "continuation_command": FIRST_LIVE_EPISODE_CONTINUATION_COMMAND,
        "require_live_research": require_live_research,
    }

    # 0) Canary preserved
    if not canary_route_preserved:
        failures.append("INSTRUMENT_CANARY not preserved")
    details["instrument_canary"] = INSTRUMENT_CANARY_ROUTE if canary_route_preserved else None
    details["second_ledger_created"] = False

    # 1) ProtocolPin — shared shape + optional formal admission (no duplicate driver)
    formal_admission = _evaluate_protocol_pin_block(
        protocol_pin=protocol_pin,
        formal_protocol_pin_path=formal_protocol_pin_path,
        formal_protocol_pin_sha256=formal_protocol_pin_sha256,
        formal_active_parent_sha256=formal_active_parent_sha256,
        details=details,
        failures=failures,
    )

    # 2) Scientist episode — live path refuses fixture fallback; tests may supply fixtures.
    scientist_ok = _evaluate_scientist_block(
        scientist_evidence=scientist_evidence,
        details=details,
        failures=failures,
        require_full_shape=True,
        require_live_research=require_live_research,
    )

    # Live commissioning fail-closed: no account freeze without real research evidence.
    # Harness/test paths (require_live_research=False) may still exercise freeze with fixtures.
    if require_live_research and not scientist_ok:
        receipt: dict[str, Any] = {
            "schema_version": PRE_OUTCOME_RECEIPT_SCHEMA,
            "vertical_schema_version": VERTICAL_RECEIPT_SCHEMA,
            "status": "FAIL",
            "phase": "pre_outcome",
            "carrier_control": canary_route_preserved,
            "role_fitness": False,
            "genuine_role_fitness": False,
            "formal_protocol_pin_admitted": formal_admission,
            "scientist_evidence_shape_ok": False,
            "candidate_sealed_for_codex_review": False,
            "pre_outcome_freeze_ok": False,
            "awaiting_external_outcome": False,
            "account_continuity": False,
            "parent_completion": False,
            "completion_claim_allowed": False,
            "scientific_promotion": False,
            "instrument_canary_preserved": canary_route_preserved,
            "second_ledger_created": False,
            "rq008_retrospective_backfill_eligible": False,
            "require_live_research": True,
            "proof_classes": details.get("proof_classes", {}),
            "details": details,
            "failures": failures,
            "candidate_only": True,
            "owner": OWNER_ROLE,
            "next_action": "supply_native_live_research_then_retry_pre_outcome",
            "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
            "first_live_research_episode_host_command": FIRST_LIVE_RESEARCH_EPISODE_HOST_COMMAND,
            "continuation_command": FIRST_LIVE_EPISODE_CONTINUATION_COMMAND,
            "proof_class": PROOF_OWNER_VERTICAL,
        }
        receipt["content_hash"] = _canonical_sha256(
            {k: v for k, v in receipt.items() if k != "content_hash"}
        )
        _write_json(work_root / "pre_outcome_receipt.json", receipt)
        return receipt

    # 3) Seal immutable candidate or typed NO_ACTION (Codex review only)
    science_identity = "SCIENCE_CANDIDATE"
    account_identity = "ACTION" if p1_account_mode == "ACTION" else "RESEARCHER_ACCOUNT_NO_ACTION"
    sealed = seal_immutable_candidate_or_no_action(
        work_dir=work_root / "outbox",
        science_identity=science_identity,
        account_identity=account_identity,
        summary=f"candidate for: {research_question}",
    )
    details["sealed_candidate"] = sealed

    # 4) Codex disposition (structure vs authenticity orthogonal)
    cand = codex_disposition or build_fixture_candidate_disposition(
        science_identity=science_identity,
        account_identity=account_identity,
        owner_decision="DEFER",
    )
    try:
        details["candidate_disposition"] = validate_candidate_and_owner_disposition(cand)
        details["proof_classes"]["owner_disposition"] = details["candidate_disposition"].get(
            "disposition_proof_class"
        )
        if details["candidate_disposition"].get("scientific_promotion_from_pnl") is True:
            failures.append("science/account cross-green on disposition")
    except RoleFitnessAcceptanceError as exc:
        failures.append(f"candidate_disposition: {exc}")
        details["candidate_disposition"] = {"allowed": False, "error": str(exc)}

    # 5) Pre-outcome freeze only (real shadow consumer; no settle yet)
    # Formal chain: pool → Owner disposition CAS → research binding → owner_authority.
    portfolio_root = work_root / "portfolio"
    freeze_work = work_root / "freeze-work"
    freeze_work.mkdir(parents=True, exist_ok=True)
    open_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    try:
        init_portfolio(
            root=portfolio_root,
            seat_id="seat.role-fitness.vertical",
            portfolio_ref="portfolio.role-fitness.vertical",
        )
        frozen = freeze_portfolio_period_with_formal_owner_authority(
            portfolio_root=portfolio_root,
            work_dir=freeze_work,
            account_mode=p1_account_mode,
            open_at=open_1,
            selected_number=1,
            pool_root=work_root / "research-pool",
            owner_state_root=work_root / "owner-state",
        )
        if frozen.get("ok") is not True:
            raise RoleFitnessAcceptanceError("pre-outcome freeze failed")
        # no-peek: freeze must not include outcome
        details["pre_outcome_freeze"] = {
            "ok": True,
            "phase": frozen.get("phase"),
            "frozen_episode_hash": frozen.get("frozen_episode_hash"),
            "period_index": frozen.get("period_index"),
            "outcome_present": False,
            "next_action": "portfolio-settle",
            "proof_class": PROOF_PRE_OUTCOME_FREEZE,
            "formal_owner_authority": True,
            "research_binding_sha256": frozen.get("research_binding_sha256"),
            "owner_disposition_sha256": frozen.get("owner_disposition_sha256")
            or frozen.get("bound_owner_artifact_sha256"),
        }
        details["proof_classes"]["account_freeze"] = PROOF_PRE_OUTCOME_FREEZE
        details["portfolio_root"] = str(portfolio_root)
        details["research_pool_root"] = str(work_root / "research-pool")
        details["owner_state_root"] = str(work_root / "owner-state")
        details["target_open_time"] = open_1.isoformat().replace("+00:00", "Z")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"pre_outcome_freeze: {exc}")
        details["pre_outcome_freeze"] = {"ok": False, "error": str(exc)}

    # RQ008 ineligible
    try:
        reject_rq008_retrospective_backfill(
            {
                "source": "RQ008",
                "retrospective": True,
                "owner_decision": "NO_ACTION",
                "ticket": None,
                "settlement": None,
                "prospective_freeze": False,
            }
        )
        details["rq008_ineligible_for_backfill"] = True
    except RoleFitnessAcceptanceError as exc:
        failures.append(str(exc))
        details["rq008_ineligible_for_backfill"] = False

    honest_pass = (
        canary_route_preserved
        and scientist_ok
        and details.get("pre_outcome_freeze", {}).get("ok") is True
        and details.get("rq008_ineligible_for_backfill") is True
        and not failures
        and details.get("candidate_disposition", {}).get("scientific_promotion_from_pnl")
        is not True
    )
    receipt: dict[str, Any] = {
        "schema_version": PRE_OUTCOME_RECEIPT_SCHEMA,
        "vertical_schema_version": VERTICAL_RECEIPT_SCHEMA,
        "status": "PRE_OUTCOME_PASS" if honest_pass else "FAIL",
        "phase": "pre_outcome",
        "carrier_control": canary_route_preserved,
        "role_fitness": False,
        "genuine_role_fitness": False,
        "formal_protocol_pin_admitted": formal_admission,
        "scientist_evidence_shape_ok": scientist_ok,
        "candidate_sealed_for_codex_review": True,
        "pre_outcome_freeze_ok": details.get("pre_outcome_freeze", {}).get("ok") is True,
        "awaiting_external_outcome": True,
        "account_continuity": False,  # settle/feedback not yet run
        "parent_completion": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "instrument_canary_preserved": canary_route_preserved,
        "second_ledger_created": False,
        "rq008_retrospective_backfill_eligible": False,
        "proof_classes": details.get("proof_classes", {}),
        "details": details,
        "failures": failures,
        "candidate_only": True,
        "owner": OWNER_ROLE,
        "next_action": "continue_outcome_after_independent_observation",
        "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
        "continuation_command": FIRST_LIVE_EPISODE_CONTINUATION_COMMAND,
        "two_phase_commands": two_owner_commands(),
        "retired_duplicate_stack": RETIRED_LIVE_RUNNER_MODULE,
    }
    receipt["content_hash"] = _canonical_sha256(
        {k: v for k, v in receipt.items() if k != "content_hash"}
    )
    _write_json(work_root / "pre_outcome_receipt.json", receipt)
    return receipt


def run_owner_invoked_vertical_continue_outcome(
    *,
    work_root: Path,
    pre_outcome_receipt: Mapping[str, Any] | None = None,
    external_outcome_path: Path | None = None,
    outcome_number: int = 1,
    synthetic_fixture_outcome: bool = True,
) -> dict[str, Any]:
    """Continue after independent external outcome: settle-all → replay → feedback → next head.

    Live path (``external_outcome_path`` set): one settle-all, replay, feedback, then stop
    with same-seat bankroll carry readiness — never fabricates the next period freeze or
    outcome. Synthetic fixture path may run a second period only to prove carry mechanics
    and remains labeled (never greens prospective equity or parent completion).
    """

    work_root = work_root.resolve()
    failures: list[str] = []
    if pre_outcome_receipt is None:
        path = work_root / "pre_outcome_receipt.json"
        if not path.is_file():
            raise RoleFitnessAcceptanceError("pre_outcome receipt missing for continuation")
        pre_outcome_receipt = json.loads(path.read_text(encoding="utf-8"))
    pre = _require_mapping(pre_outcome_receipt, "pre_outcome_receipt")
    if (
        pre.get("phase") != "pre_outcome"
        and pre.get("schema_version") != PRE_OUTCOME_RECEIPT_SCHEMA
    ):
        # Allow either field binding.
        if pre.get("schema_version") != PRE_OUTCOME_RECEIPT_SCHEMA:
            raise RoleFitnessAcceptanceError("invalid pre_outcome receipt schema")
    if pre.get("parent_completion") is True or pre.get("completion_claim_allowed") is True:
        raise RoleFitnessAcceptanceError("pre_outcome receipt falsely greened completion")

    portfolio_root = Path(
        str((pre.get("details") or {}).get("portfolio_root") or (work_root / "portfolio"))
    )
    freeze_work = work_root / "freeze-work"
    freeze_work.mkdir(parents=True, exist_ok=True)
    open_1 = datetime(2026, 8, 1, 8, tzinfo=UTC)
    open_2 = open_1 + timedelta(days=1)
    live_single_period = external_outcome_path is not None

    details: dict[str, Any] = {
        "phase": "continue_outcome",
        "pre_outcome_content_hash": pre.get("content_hash"),
        "proof_classes": dict(pre.get("proof_classes") or {}),
        "live_single_period_stop": live_single_period,
    }

    try:
        seat_before = load_seat(portfolio_root)
        if external_outcome_path is not None:
            out1 = Path(external_outcome_path)
            if not out1.is_file():
                raise RoleFitnessAcceptanceError(f"external outcome missing: {out1}")
            outcome_body = json.loads(out1.read_text(encoding="utf-8"))
            if not isinstance(outcome_body, dict):
                raise RoleFitnessAcceptanceError("external outcome must be a JSON object")
            reject_synthetic_outcome_as_live(outcome_body)
            synthetic_fixture_outcome = False
        else:
            out1 = build_outcome(
                freeze_work / "p1-outcome.json",
                open_at=open_1,
                period=1,
                number=outcome_number,
                source_ref=(
                    "synthetic-harness-fixture-only"
                    if synthetic_fixture_outcome
                    else "independent-external-observation"
                ),
            )
        settled_1 = settle_portfolio_period(root=portfolio_root, outcome_path=out1)
        if settled_1.get("parent_complete") is True or settled_1.get("parent_completion") is True:
            raise RoleFitnessAcceptanceError(
                "parent completion false green: outcome path must not set parent_completion"
            )
        if settled_1.get("scientific_promotion") is True:
            raise RoleFitnessAcceptanceError("science/account cross-green on settle")

        # Duplicate settle-all must fail closed (partial/double settlement).
        try:
            settle_portfolio_period(root=portfolio_root, outcome_path=out1)
            raise RoleFitnessAcceptanceError(
                "duplicate outcome/settlement was incorrectly accepted"
            )
        except RoleFitnessAcceptanceError:
            raise
        except (StoreError, ValueError, TypeError, KeyError):
            pass

        feedback_1 = feedback_portfolio_period(
            root=portfolio_root,
            kind=FeedbackKind.NO_CHANGE_WITH_REASON,
            reason_code="CONTINUE_TO_NEXT_PROSPECTIVE_PERIOD",
        )
        if feedback_1.get("scientific_promotion") is True:
            raise RoleFitnessAcceptanceError("feedback promoted science")
        p1_close = str(settled_1["closing_balance"])
        replay_1 = replay_portfolio_period(root=portfolio_root, period_index=1)
        if replay_1.get("replay_match") is not True:
            raise RoleFitnessAcceptanceError("replay mismatch after settle-all")

        details["period_1"] = {
            "settled": settled_1,
            "feedback_hash": feedback_1.get("feedback_hash"),
            "closing_balance": p1_close,
            "replay_match": True,
        }

        if live_single_period:
            # Live path: stop. Do not freeze next period or fabricate next outcome.
            final = inspect_portfolio(root=portfolio_root)
            if final.get("next_action") != "portfolio-freeze":
                raise RoleFitnessAcceptanceError(
                    "same-seat next-period head not ready "
                    f"(expected next_action=portfolio-freeze, got {final.get('next_action')!r})"
                )
            seat_after = load_seat(portfolio_root)
            if seat_after.seat_id != seat_before.seat_id:
                raise RoleFitnessAcceptanceError(
                    "cross-seat bankroll reset rejected after settlement"
                )
            if seat_after.opening_balance != seat_before.opening_balance:
                raise RoleFitnessAcceptanceError(
                    "cross-seat bankroll reset rejected: seat opening_balance mutated"
                )
            if seat_after.content_hash != seat_before.content_hash:
                raise RoleFitnessAcceptanceError(
                    "cross-seat bankroll reset rejected: seat content seal mutated"
                )
            if final.get("parent_complete") is True or final.get("parent_completion") is True:
                raise RoleFitnessAcceptanceError("parent completion greened on portfolio inspect")
            if final.get("completion_claim_allowed") is not False:
                raise RoleFitnessAcceptanceError("completion_claim_allowed must remain false")
            if final.get("scientific_promotion") is True:
                raise RoleFitnessAcceptanceError("portfolio inspect promoted science")
            details["period_2"] = None
            details["replay_match"] = {"period_1": True}
            details["inspect"] = final
            details["closing_balance_carried"] = (
                str(final.get("closing_balance") or p1_close) == p1_close
            )
            details["same_seat"] = True
            details["bankroll_carried_to_next_period_head"] = True
            details["next_period_ready"] = True
            details["stopped_without_fabricating_next_period"] = True
            details["proof_classes"]["account"] = PROOF_REAL_SHADOW_CONSUMER
            details["outcome_proof_class"] = PROOF_FUTURE_OUTCOME
        else:
            # Harness-only: bind same-seat closing balance through a second period.
            # Reuse formal pool/owner roots from pre_outcome when present.
            pre_details = pre.get("details") if isinstance(pre.get("details"), Mapping) else {}
            pool_root = Path(
                str(pre_details.get("research_pool_root") or (work_root / "research-pool"))
            )
            owner_state_root = Path(
                str(pre_details.get("owner_state_root") or (work_root / "owner-state"))
            )
            freeze_portfolio_period_with_formal_owner_authority(
                portfolio_root=portfolio_root,
                work_dir=freeze_work / "p2-authority",
                account_mode="NO_ACTION",
                open_at=open_2,
                pool_root=pool_root,
                owner_state_root=owner_state_root,
            )
            episode_2 = load_frozen(period_directory(portfolio_root, 2))
            if episode_2.pre_freeze_balance != p1_close:
                raise RoleFitnessAcceptanceError(
                    "next research/period head pre_freeze must equal prior closing balance"
                )
            out2 = build_outcome(
                freeze_work / "p2-outcome.json",
                open_at=open_2,
                period=2,
                number=49,
                source_ref=(
                    "synthetic-harness-fixture-only"
                    if synthetic_fixture_outcome
                    else "independent-external-observation"
                ),
            )
            settled_2 = settle_portfolio_period(root=portfolio_root, outcome_path=out2)
            feedback_2 = feedback_portfolio_period(
                root=portfolio_root,
                kind=FeedbackKind.TYPED_FEEDBACK,
                notes="carry same-seat closing balance; no science promotion",
            )
            replay_2 = replay_portfolio_period(root=portfolio_root, period_index=2)
            if replay_2.get("replay_match") is not True:
                raise RoleFitnessAcceptanceError("replay mismatch")
            final = inspect_portfolio(root=portfolio_root)
            if final.get("parent_complete") is True or final.get("parent_completion") is True:
                raise RoleFitnessAcceptanceError("parent completion greened on portfolio inspect")
            if final.get("completion_claim_allowed") is not False:
                raise RoleFitnessAcceptanceError("completion_claim_allowed must remain false")
            if final.get("scientific_promotion") is True:
                raise RoleFitnessAcceptanceError("portfolio inspect promoted science")

            details["period_2"] = {
                "settled": settled_2,
                "feedback_hash": feedback_2.get("feedback_hash"),
                "pre_freeze_balance": episode_2.pre_freeze_balance,
                "prior_closing_balance": (
                    episode_2.prior_close_binding.prior_closing_balance
                    if episode_2.prior_close_binding is not None
                    else None
                ),
            }
            details["replay_match"] = {"period_1": True, "period_2": True}
            details["inspect"] = final
            details["closing_balance_carried"] = final.get("closing_balance") == settled_2.get(
                "closing_balance"
            )
            details["same_seat"] = True
            details["stopped_without_fabricating_next_period"] = False
            details["proof_classes"]["account"] = PROOF_REAL_SHADOW_CONSUMER
            details["outcome_proof_class"] = (
                "SYNTHETIC_FIXTURE_OUTCOME" if synthetic_fixture_outcome else PROOF_FUTURE_OUTCOME
            )
        account_ok = True
    except Exception as exc:  # noqa: BLE001
        failures.append(f"continue_outcome: {exc}")
        details["error"] = str(exc)
        account_ok = False

    honest_pass = (
        account_ok
        and not failures
        and pre.get("status")
        in {
            "PRE_OUTCOME_PASS",
            "PASS",
        }
    )
    receipt: dict[str, Any] = {
        "schema_version": CONTINUATION_RECEIPT_SCHEMA,
        "vertical_schema_version": VERTICAL_RECEIPT_SCHEMA,
        "status": "CONTINUATION_PASS" if honest_pass else "FAIL",
        "phase": "continue_outcome",
        "role_fitness": False,
        "genuine_role_fitness": False,
        "account_continuity": account_ok,
        "closing_balance_carried": details.get("closing_balance_carried") is True,
        "same_seat": details.get("same_seat") is True,
        "parent_completion": False,
        "completion_claim_allowed": False,
        "scientific_promotion": False,
        "awaiting_external_outcome": False,
        "live_single_period_stop": live_single_period,
        "stopped_without_fabricating_next_period": details.get(
            "stopped_without_fabricating_next_period"
        )
        is True,
        "outcome_proof_class": details.get("outcome_proof_class"),
        "proof_classes": details.get("proof_classes", {}),
        "details": details,
        "failures": failures,
        "candidate_only": True,
        "owner": OWNER_ROLE,
        "pre_outcome_content_hash": pre.get("content_hash"),
        "two_phase_commands": two_owner_commands(),
        "retired_duplicate_stack": RETIRED_LIVE_RUNNER_MODULE,
    }
    receipt["content_hash"] = _canonical_sha256(
        {k: v for k, v in receipt.items() if k != "content_hash"}
    )
    _write_json(work_root / "continuation_receipt.json", receipt)
    return receipt


def run_owner_invoked_vertical(
    *,
    work_root: Path,
    mode: str = "pre_outcome",
    **kwargs: Any,
) -> dict[str, Any]:
    """Entry for Owner-invoked vertical; mode selects pre-outcome vs continuation."""

    mode = str(mode).strip().lower()
    if mode == "pre_outcome":
        return run_owner_invoked_vertical_pre_outcome(work_root=work_root, **kwargs)
    if mode == "continue_outcome":
        return run_owner_invoked_vertical_continue_outcome(work_root=work_root, **kwargs)
    if mode == "full_synthetic":
        # Test/dev only: pre-outcome then synthetic outcome continuation (labeled).
        # Live commissioning must never use this mode as a production green path.
        if kwargs.get("require_live_research") is True:
            raise RoleFitnessAcceptanceError(
                "full_synthetic forbidden when require_live_research=true "
                "(no silent fixture production path)"
            )
        pre = run_owner_invoked_vertical_pre_outcome(
            work_root=work_root,
            **{
                k: v
                for k, v in kwargs.items()
                if k
                in {
                    "research_question",
                    "protocol_pin",
                    "scientist_evidence",
                    "codex_disposition",
                    "formal_protocol_pin_path",
                    "formal_protocol_pin_sha256",
                    "formal_active_parent_sha256",
                    "p1_account_mode",
                    "canary_route_preserved",
                    "require_live_research",
                }
            },
        )
        cont = run_owner_invoked_vertical_continue_outcome(
            work_root=work_root,
            pre_outcome_receipt=pre,
            synthetic_fixture_outcome=True,
            outcome_number=1,
        )
        return {
            "schema_version": VERTICAL_RECEIPT_SCHEMA,
            "status": (
                "PASS"
                if pre.get("status") == "PRE_OUTCOME_PASS"
                and cont.get("status") == "CONTINUATION_PASS"
                else "FAIL"
            ),
            "phase": "full_synthetic",
            "pre_outcome": pre,
            "continuation": cont,
            "role_fitness": False,
            "genuine_role_fitness": False,
            "parent_completion": False,
            "completion_claim_allowed": False,
            "scientific_promotion": False,
            "outcome_proof_class": "SYNTHETIC_FIXTURE_OUTCOME",
            "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
            "proof_class": PROOF_OWNER_VERTICAL,
            "candidate_only": True,
            "owner": OWNER_ROLE,
        }
    raise RoleFitnessAcceptanceError(
        f"unsupported owner-vertical mode: {mode} (use pre_outcome|continue_outcome|full_synthetic)"
    )


def acceptance_receipt_schema() -> dict[str, Any]:
    """Exact acceptance receipt schema document for Owner integration."""

    return {
        "schema_version": "xinao.role_fitness_acceptance_receipt_schema.v1",
        "integrated_receipt_schema": RECEIPT_SCHEMA,
        "vertical_receipt_schema": VERTICAL_RECEIPT_SCHEMA,
        "pre_outcome_receipt_schema": PRE_OUTCOME_RECEIPT_SCHEMA,
        "continuation_receipt_schema": CONTINUATION_RECEIPT_SCHEMA,
        "required_false_fields": [
            "parent_completion",
            "completion_claim_allowed",
            "scientific_promotion",
            "genuine_role_fitness",
            "role_fitness",
        ],
        "scientist_proof_class": PROOF_NATIVE_SESSION_MCP,
        "account_proof_class": PROOF_REAL_SHADOW_CONSUMER,
        "pre_outcome_proof_class": PROOF_PRE_OUTCOME_FREEZE,
        "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
        "first_live_research_episode_host_command": FIRST_LIVE_RESEARCH_EPISODE_HOST_COMMAND,
        "continuation_command": FIRST_LIVE_EPISODE_CONTINUATION_COMMAND,
        "native_receipt_interface": [
            "session_artifact.sha256",
            "mcp_events.sha256",
            "scientist_evidence multi-turn/tool/fail-revise/resume/event_chain",
            "consume_native_episode_receipt",
        ],
        "order": [
            "unexposed_target_and_formal_ProtocolPin",
            "scientist_episode_native_session_mcp",
            "immutable_candidate_or_typed_NO_ACTION",
            "Codex_disposition",
            "independent_science_and_account_decisions",
            "pre_outcome_freeze",
            "external_outcome",
            "settle_all_replay_feedback",
            "same_seat_next_research_head",
        ],
        "two_phase_commands": two_owner_commands(),
        "retired_duplicate_stack": RETIRED_LIVE_RUNNER_MODULE,
        "shadow_consumer": "xinao.shadow_lifecycle",
        "second_ledger_forbidden": True,
        "completion_claim_allowed": False,
        "parent_completion": False,
        "authority": False,
        "owner": OWNER_ROLE,
    }


def run_negatives_suite(work_root: Path) -> dict[str, Any]:
    """Execute negative oracles; each must fail closed."""

    work_root = work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    def _run(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            results[name] = "PASS"
        except Exception as exc:  # noqa: BLE001
            results[name] = f"FAIL:{exc}"

    _run(
        "future_peek",
        lambda: negative_future_peek_freeze(work_root / "neg-peek", work_root / "neg-peek-w"),
    )
    _run("late_freeze", negative_late_freeze_protocol_pin)
    _run("missing_tool_evidence", negative_missing_tool_evidence)
    _run("no_revise_after_failure", negative_no_revise_after_failure)
    _run("forged_resume", negative_forged_resume)
    _run("unbound_transcript", negative_unbound_transcript_assertions)
    _run("transcript_without_raw_session_mcp", negative_transcript_without_raw_session_mcp)
    _run("mock_protocol_pin_formal", negative_mock_protocol_pin_as_formal)
    _run("worker_controlled_disposition", negative_worker_controlled_disposition)
    _run("fake_owner_fields", negative_fake_owner_fields)
    _run(
        "selective_settlement",
        lambda: negative_selective_settlement(work_root / "neg-sel", work_root / "neg-sel-w"),
    )
    _run("recapitalization", lambda: negative_recapitalization(work_root / "neg-recap"))
    _run(
        "stale_portfolio_head",
        lambda: negative_stale_portfolio_head(work_root / "neg-stale", work_root / "neg-stale-w"),
    )
    _run("science_account_cross_green", negative_science_account_cross_green)
    _run("rq008_backfill", negative_rq008_backfill)
    _run(
        "synthetic_hit_parent_completion",
        lambda: negative_synthetic_hit_parent_completion(
            work_root / "neg-hit", work_root / "neg-hit-w"
        ),
    )
    _run(
        "fixture_glued_to_live_paths",
        lambda: negative_fixture_glued_to_live_paths(work_root / "neg-glue"),
    )
    _run("synthetic_profit_promotion", negative_synthetic_profit_promotion)

    all_pass = all(v == "PASS" for v in results.values())
    return {
        "schema_version": "xinao.role_fitness_negative_suite.v1",
        "status": "PASS" if all_pass else "FAIL",
        "cases": results,
        "completion_claim_allowed": False,
        "parent_completion": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xinao-role-fitness-acceptance",
        description="Role-fitness + prospective shadow consumer acceptance harness (candidate-only).",
    )
    sub = parser.add_subparsers(dest="command")

    # Backward-compatible flat flags (no subcommand) for integrated/negatives suite.
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="Empty/isolated work directory for portfolio + fixtures",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "integrated",
            "negatives",
            "both",
            "pre_outcome",
            "continue_outcome",
            "full_synthetic",
            "schema",
        ),
        default="both",
    )
    parser.add_argument(
        "--p1-mode",
        choices=("ACTION_HIT", "NO_ACTION"),
        default="ACTION_HIT",
    )
    parser.add_argument(
        "--p2-mode",
        choices=("ACTION_HIT", "NO_ACTION"),
        default="NO_ACTION",
    )
    parser.add_argument("--receipt-out", type=Path, default=None)
    parser.add_argument("--research-question", default=None)
    parser.add_argument("--protocol-pin-path", type=Path, default=None)
    parser.add_argument("--protocol-pin-sha256", default=None)
    parser.add_argument("--active-parent-sha256", default=None)
    parser.add_argument("--session-artifact", type=Path, default=None)
    parser.add_argument("--mcp-events", type=Path, default=None)
    parser.add_argument(
        "--scientist-evidence",
        type=Path,
        default=None,
        help="Structured multi-turn/tool/revise/resume/event_chain JSON (required with live session/MCP)",
    )
    parser.add_argument("--codex-disposition", type=Path, default=None)
    parser.add_argument("--pre-outcome-receipt", type=Path, default=None)
    parser.add_argument("--external-outcome", type=Path, default=None)

    # Explicit subcommand for Owner vertical (same flags; documents first live command).
    ov = sub.add_parser("owner-vertical", help="Owner-invoked RF vertical (pre/continue)")
    ov.add_argument("--work-root", type=Path, required=True)
    ov.add_argument(
        "--mode",
        choices=("pre_outcome", "continue_outcome", "full_synthetic"),
        default="pre_outcome",
    )
    ov.add_argument("--receipt-out", type=Path, default=None)
    ov.add_argument("--research-question", default=None)
    ov.add_argument("--protocol-pin-path", type=Path, default=None)
    ov.add_argument("--protocol-pin-sha256", default=None)
    ov.add_argument("--active-parent-sha256", default=None)
    ov.add_argument("--session-artifact", type=Path, default=None)
    ov.add_argument("--mcp-events", type=Path, default=None)
    ov.add_argument(
        "--scientist-evidence",
        type=Path,
        default=None,
        help="Structured scientist evidence; required when session/MCP paths are supplied",
    )
    ov.add_argument("--codex-disposition", type=Path, default=None)
    ov.add_argument("--pre-outcome-receipt", type=Path, default=None)
    ov.add_argument("--external-outcome", type=Path, default=None)
    ov.add_argument(
        "--require-live-research",
        action="store_true",
        help="Refuse silent fixture scientist fallback (Owner live commissioning)",
    )

    schema_cmd = sub.add_parser("print-schema", help="Print acceptance receipt schema JSON")
    schema_cmd.add_argument("--receipt-out", type=Path, default=None)

    parser.add_argument(
        "--require-live-research",
        action="store_true",
        help="Refuse silent fixture scientist fallback (Owner live commissioning)",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "print-schema" or args.mode == "schema":
        output = acceptance_receipt_schema()
        if getattr(args, "receipt_out", None) is not None:
            _write_json(args.receipt_out, output)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0

    vertical_mode = None
    if args.command == "owner-vertical":
        vertical_mode = args.mode
    elif args.mode in {"pre_outcome", "continue_outcome", "full_synthetic"}:
        vertical_mode = args.mode

    if vertical_mode is not None:
        if args.work_root is None:
            raise SystemExit("--work-root is required for owner-vertical modes")
        work = args.work_root
        work.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {}
        if vertical_mode == "pre_outcome" or vertical_mode == "full_synthetic":
            if args.research_question:
                kwargs["research_question"] = args.research_question
            if args.protocol_pin_path and args.protocol_pin_sha256 and args.active_parent_sha256:
                kwargs["formal_protocol_pin_path"] = args.protocol_pin_path
                kwargs["formal_protocol_pin_sha256"] = args.protocol_pin_sha256
                kwargs["formal_active_parent_sha256"] = args.active_parent_sha256
            # Native episode receipt: session+MCP hashes + structured evidence.
            # Never glue synthetic fixture narrative onto live path hashes alone.
            if args.session_artifact is not None or args.mcp_events is not None:
                if args.session_artifact is None or args.mcp_events is None:
                    raise SystemExit(
                        "native receipt requires both --session-artifact and --mcp-events"
                    )
                kwargs["scientist_evidence"] = consume_native_episode_receipt(
                    session_artifact=args.session_artifact,
                    mcp_events=args.mcp_events,
                    scientist_evidence_path=args.scientist_evidence,
                )
            elif args.scientist_evidence is not None:
                # Structured evidence without live paths (inline raw artifacts allowed).
                kwargs["scientist_evidence"] = json.loads(
                    Path(args.scientist_evidence).read_text(encoding="utf-8")
                )
            if args.codex_disposition is not None:
                kwargs["codex_disposition"] = json.loads(
                    args.codex_disposition.read_text(encoding="utf-8")
                )
            if getattr(args, "require_live_research", False):
                kwargs["require_live_research"] = True
            output = run_owner_invoked_vertical(work_root=work, mode=vertical_mode, **kwargs)
        else:
            pre = None
            if args.pre_outcome_receipt is not None:
                pre = json.loads(args.pre_outcome_receipt.read_text(encoding="utf-8"))
            output = run_owner_invoked_vertical(
                work_root=work,
                mode="continue_outcome",
                pre_outcome_receipt=pre,
                external_outcome_path=args.external_outcome,
                synthetic_fixture_outcome=args.external_outcome is None,
            )
        if args.receipt_out is not None:
            _write_json(args.receipt_out, output)
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        status = str(output.get("status", "FAIL"))
        return 0 if status.endswith("PASS") or status == "PASS" else 1

    if args.work_root is None:
        raise SystemExit("--work-root is required")
    work = args.work_root
    work.mkdir(parents=True, exist_ok=True)
    output = {
        "schema_version": "xinao.role_fitness_acceptance_cli.v1",
        "completion_claim_allowed": False,
        "parent_completion": False,
        "first_live_episode_command": FIRST_LIVE_EPISODE_COMMAND,
        "acceptance_receipt_schema": acceptance_receipt_schema(),
    }

    if args.mode in {"integrated", "both"}:
        output["integrated"] = run_integrated_acceptance(
            work_root=work / "integrated",
            p1_mode=args.p1_mode,
            p2_mode=args.p2_mode,
        )
    if args.mode in {"negatives", "both"}:
        output["negatives"] = run_negatives_suite(work / "negatives")

    if args.receipt_out is not None:
        _write_json(args.receipt_out, output)

    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    integrated_ok = output.get("integrated", {}).get("status", "PASS") == "PASS"
    negatives_ok = output.get("negatives", {}).get("status", "PASS") == "PASS"
    if args.mode == "integrated":
        return 0 if integrated_ok else 1
    if args.mode == "negatives":
        return 0 if negatives_ok else 1
    return 0 if integrated_ok and negatives_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
