"""One-shot consumer for Day-1 multi-policy freeze and settle recovery.

The command has no scheduler, daemon, or real-money side effect.  Synthetic
mode proves the execution contract only.  Live mode freezes prospective shadow
tickets and deliberately stops before outcome access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import sha256_file
from xinao.decision import DecisionGateInput
from xinao.science.day1_portfolio import (
    ASIA_SHANGHAI,
    Day1PolicyCompilation,
    MultipolicyProtocolPin,
    PolicyHashBinding,
    RuntimeSourceBinding,
    build_day1_gates,
    build_day1_policy_compilation,
    observations_from_draws,
    parse_macaujc_history_response,
)
from xinao.science.portfolio import (
    ActiveSet,
    EligibleSet,
    FrozenDecisionSet,
    PolicyRole,
    SettlementSet,
    admit_active_set,
    admit_eligible_set,
    freeze_all,
    settle_all,
)
from xinao.science.trial_ledger import (
    EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
    append_science_trial_entry,
    load_science_trial_journal,
)
from xinao.settlement import OutcomeObservation, SettlementBundle
from xinao.world.builder import load_draws

HISTORY_ENDPOINT = "https://history.macaumarksix.com/history/macaujc2/y/2026"
SOURCE_CONTRACT_REF = "macaujc-source-authority-contract.v1"
PACKAGE_MANIFEST_NAME = "multipolicy_episode_manifest.v1.json"


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _millisecond_now() -> datetime:
    value = datetime.now(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _write_new_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()


def _write_new_json(path: Path, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write_new_bytes(path, body.encode("utf-8"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_file(path: Path, expected_sha256: str, label: str) -> str:
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(f"{label} sha256 mismatch")
    return observed


def _create_output_dir(path: Path) -> Path:
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _create_trial_ledger(
    output_dir: Path,
    *,
    episode_id: str,
    policies: tuple[Any, ...],
    path_kind: str,
) -> tuple[Path, str, dict[str, Any]]:
    anchor_path = output_dir / "science_trial_ledger.v1.json"
    _write_new_json(
        anchor_path,
        {
            "schema_version": "xinao.science_trial_ledger.v1",
            "episode_id": episode_id,
            "append_only": True,
            "entries": [],
        },
    )
    anchor_sha256 = sha256_file(anchor_path)
    head: dict[str, Any] = {
        "entry_count": 0,
        "entries_sha256": EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
    }
    for policy in policies:
        receipt = append_science_trial_entry(
            anchor_path,
            expected_anchor_sha256=anchor_sha256,
            episode_id=episode_id,
            event_id=f"{episode_id}:registered:{policy.policy_ref}",
            work_key=policy.policy_ref,
            status="REGISTERED",
            family_id=policy.family_id,
            equivalence_cluster_id=policy.decision_signature.signature_hash,
            path_kind=path_kind,
            failure_reason=None,
            meta={
                "policy_ref": policy.policy_ref,
                "policy_content_hash": policy.content_hash,
                "role": policy.role.value,
                "claim_ceiling": policy.claim_ceiling,
            },
            expected_entry_count=int(head["entry_count"]),
            expected_entries_sha256=str(head["entries_sha256"]),
            terminal=False,
        )
        head = receipt
    return anchor_path, anchor_sha256, head


def _advance_trial_ledger(
    anchor_path: Path,
    *,
    anchor_sha256: str,
    episode_id: str,
    policies: tuple[Any, ...],
    phase: str,
    terminal: bool,
    path_kind: str,
) -> dict[str, Any]:
    replay = load_science_trial_journal(
        anchor_path,
        expected_anchor_sha256=anchor_sha256,
        episode_id=episode_id,
    )
    head: dict[str, Any] = replay
    for policy in policies:
        status = (
            "NO_ACTION"
            if terminal and policy.role == PolicyRole.NO_ACTION
            else ("SUCCEEDED" if terminal else "RUNNING")
        )
        receipt = append_science_trial_entry(
            anchor_path,
            expected_anchor_sha256=anchor_sha256,
            episode_id=episode_id,
            event_id=f"{episode_id}:{phase}:{policy.policy_ref}",
            work_key=policy.policy_ref,
            status=status,
            family_id=policy.family_id,
            equivalence_cluster_id=policy.decision_signature.signature_hash,
            path_kind=path_kind,
            failure_reason=None,
            meta={
                "policy_ref": policy.policy_ref,
                "policy_content_hash": policy.content_hash,
                "role": policy.role.value,
                "phase": phase,
                "scientific_promotion": False,
            },
            expected_entry_count=int(head["entry_count"]),
            expected_entries_sha256=str(head["entries_sha256"]),
            terminal=terminal,
        )
        head = receipt
    return head


def _write_model(path: Path, model: Any) -> None:
    _write_new_json(path, model.model_dump(mode="json"))


def _artifact_manifest(output_dir: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == PACKAGE_MANIFEST_NAME:
            continue
        artifacts.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": "xinao.multipolicy_episode_manifest.v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "content_hash": canonical_sha256(artifacts),
    }


def _runtime_source_bindings() -> tuple[RuntimeSourceBinding, ...]:
    xinao_root = Path(__file__).resolve().parent.parent
    paths = {
        "src/xinao/decision/compiler.py": xinao_root / "decision" / "compiler.py",
        "src/xinao/science/day1_portfolio.py": xinao_root / "science" / "day1_portfolio.py",
        "src/xinao/science/multipolicy_episode.py": xinao_root
        / "science"
        / "multipolicy_episode.py",
        "src/xinao/science/portfolio.py": xinao_root / "science" / "portfolio.py",
        "src/xinao/science/trial_ledger.py": xinao_root / "science" / "trial_ledger.py",
        "src/xinao/settlement/shadow.py": xinao_root / "settlement" / "shadow.py",
        "src/xinao/settlement/special_number.py": xinao_root / "settlement" / "special_number.py",
    }
    return tuple(
        RuntimeSourceBinding(ref=ref, sha256=sha256_file(path))
        for ref, path in sorted(paths.items())
    )


def build_episode_package(
    *,
    output_dir: Path,
    episode_id: str,
    evidence_class: str,
    observations: tuple[Any, ...],
    source_snapshot_ref: str,
    source_snapshot_sha256: str,
    source_captured_at: datetime,
    active_parent_ref: str,
    active_parent_sha256: str,
    source_contract_ref: str,
    source_contract_sha256: str,
    target_ref: str,
    target_open_time: datetime,
    knowledge_cutoff: datetime,
    freeze_deadline: datetime,
    horizon_draws: int,
    frozen_at: datetime | None = None,
    synthetic_outcome_number: int | None = None,
    policy_compilation: Day1PolicyCompilation | None = None,
) -> dict[str, Any]:
    """Build one exclusive multi-policy package in an already-created directory."""

    if source_contract_ref != SOURCE_CONTRACT_REF:
        raise ValueError("source contract identity differs from the admitted world")
    snapshot_path = (output_dir / source_snapshot_ref).resolve()
    try:
        snapshot_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise ValueError("source snapshot reference escapes the episode package") from exc
    _verify_file(snapshot_path, source_snapshot_sha256, "source snapshot")
    path_kind = (
        "SYNTHETIC_EXECUTION_RECOVERY"
        if evidence_class == "EXECUTION_RECOVERY_ONLY"
        else "PROSPECTIVE_EXPLORATORY_DAY1"
    )
    expected_history_identity_hash = canonical_sha256(
        [
            {
                "expect": item.expect,
                "open_time": item.open_time,
                "source_row_hash": item.source_row_hash,
            }
            for item in observations
        ]
    )
    compilation = policy_compilation or build_day1_policy_compilation(
        observations,
        target_ref=target_ref,
        knowledge_cutoff=knowledge_cutoff,
        horizon_draws=horizon_draws,
    )
    if (
        compilation.content_hash is None
        or compilation.target_ref != target_ref
        or compilation.horizon_draws != horizon_draws
        or compilation.knowledge_cutoff != knowledge_cutoff
        or compilation.history_count != len(observations)
        or compilation.history_identity_hash != expected_history_identity_hash
    ):
        raise ValueError(
            "supplied policy compilation does not bind the episode target, cutoff, and history"
        )
    _write_model(output_dir / "day1_policy_compilation.v1.json", compilation)

    anchor_path, anchor_sha256, registered_head = _create_trial_ledger(
        output_dir,
        episode_id=episode_id,
        policies=compilation.policies,
        path_kind=path_kind,
    )
    actual_frozen_at = frozen_at or _millisecond_now()
    pin = MultipolicyProtocolPin(
        protocol_pin_ref=f"multipolicy-protocol/{episode_id}",
        episode_id=episode_id,
        evidence_class=evidence_class,
        active_parent_ref=active_parent_ref,
        active_parent_sha256=active_parent_sha256,
        source_contract_ref=source_contract_ref,
        source_contract_sha256=source_contract_sha256,
        source_snapshot_ref=source_snapshot_ref,
        source_snapshot_sha256=source_snapshot_sha256,
        source_captured_at=source_captured_at,
        trial_ledger_anchor_ref=anchor_path.name,
        trial_ledger_anchor_sha256=anchor_sha256,
        trial_ledger_prefix_entry_count=int(registered_head["entry_count"]),
        trial_ledger_prefix_entries_sha256=str(registered_head["entries_sha256"]),
        research_question=(
            "Can a pre-outcome Day-1 set containing a target-only negative control, "
            "rolling marginal baseline, and bounded multiscale-overlap challenger "
            "produce behaviorally non-equivalent shadow decisions and settle them all?"
        ),
        target_ref=target_ref,
        target_open_time=target_open_time,
        knowledge_cutoff=knowledge_cutoff,
        frozen_at=actual_frozen_at,
        freeze_deadline=freeze_deadline,
        required_roles=tuple(PolicyRole),
        policy_bindings=tuple(
            PolicyHashBinding(
                policy_ref=policy.policy_ref,
                content_hash=str(policy.content_hash),
                role=policy.role,
            )
            for policy in compilation.policies
        ),
        runtime_source_bindings=_runtime_source_bindings(),
        residual_axes=(
            "wave-overlap-prospective-score-vs-null-and-baseline",
            "calibration-and-power-after-consecutive-future-settlements",
        ),
        forbidden_claims=(
            "predictive advantage from one target",
            "mechanism truth",
            "real-money recommendation",
            "parent completion",
        ),
        next_move=(
            "Admit the verified target outcome after open, settle every frozen ticket "
            "exactly once, then recompute ClaimGrade and the next bounded question."
        ),
    ).with_content_hash()
    _write_model(output_dir / "multipolicy_protocol_pin.v1.json", pin)

    active_set = admit_active_set(
        active_set_ref=f"active-set/{episode_id}",
        protocol_pin_ref=pin.protocol_pin_ref,
        protocol_pin_sha256=str(pin.content_hash),
        admitted_at=actual_frozen_at,
        policies=compilation.policies,
        residual_axes=pin.residual_axes,
    )
    eligible_set = admit_eligible_set(
        active_set=active_set,
        eligible_set_ref=f"eligible-set/{episode_id}/{target_ref}",
        target_ref=target_ref,
        target_open_time=target_open_time,
        created_at=actual_frozen_at,
    )
    information_set_hash = canonical_sha256(
        {
            "source_snapshot_sha256": source_snapshot_sha256,
            "history_identity_hash": compilation.history_identity_hash,
            "knowledge_cutoff": _iso(knowledge_cutoff),
            "outcome_access": False,
        }
    )
    gates = build_day1_gates(
        pin=pin,
        compilation=compilation,
        information_set_ref=f"information-set/{episode_id}",
        information_set_hash=information_set_hash,
    )
    freeze_set = freeze_all(
        active_set=active_set,
        eligible_set=eligible_set,
        gates=gates,
        freeze_set_ref=f"freeze-set/{episode_id}/{target_ref}",
        frozen_at=actual_frozen_at,
    )
    _write_model(output_dir / "active_set.v1.json", active_set)
    _write_model(output_dir / "eligible_set.v1.json", eligible_set)
    _write_new_json(
        output_dir / "decision_gates.v1.json",
        {policy_ref: gate.model_dump(mode="json") for policy_ref, gate in sorted(gates.items())},
    )
    _write_model(output_dir / "frozen_decision_set.v1.json", freeze_set)
    running_head = _advance_trial_ledger(
        anchor_path,
        anchor_sha256=anchor_sha256,
        episode_id=episode_id,
        policies=compilation.policies,
        phase="frozen",
        terminal=False,
        path_kind=path_kind,
    )
    _write_new_json(
        output_dir / "trial_ledger_frozen_head.v1.json",
        {
            "entry_count": running_head["entry_count"],
            "entries_sha256": running_head["entries_sha256"],
            "journal_file_sha256": running_head["journal_file_sha256"],
        },
    )

    settlement_set: SettlementSet | None = None
    final_head = running_head
    if synthetic_outcome_number is not None:
        if evidence_class != "EXECUTION_RECOVERY_ONLY":
            raise ValueError("synthetic outcome is forbidden outside execution-recovery evidence")
        outcome = OutcomeObservation(
            outcome_ref=f"synthetic-outcome/{episode_id}",
            source_ref="synthetic-settle-all-recovery.v1",
            target_ref=target_ref,
            actual_special_number=synthetic_outcome_number,
            observed_at=target_open_time + timedelta(minutes=1),
            verified=True,
        ).with_hash()
        result = settle_all(
            freeze_set=freeze_set,
            outcome=outcome,
            settlement_set_ref=f"settlement-set/{episode_id}/{target_ref}",
            portfolio_ref=f"shadow-portfolio/{episode_id}",
            occurred_at=target_open_time + timedelta(minutes=2),
        )
        settlement_set = result.settlement_set
        _write_model(output_dir / "synthetic_outcome.v1.json", outcome)
        _write_model(output_dir / "settlement_set.v1.json", settlement_set)
        _write_new_json(
            output_dir / "action_settlement_bundles.v1.json",
            [bundle.model_dump(mode="json") for bundle in result.action_bundles],
        )
        final_head = _advance_trial_ledger(
            anchor_path,
            anchor_sha256=anchor_sha256,
            episode_id=episode_id,
            policies=compilation.policies,
            phase="synthetic-settled",
            terminal=True,
            path_kind=path_kind,
        )

    state = (
        "SYNTHETIC_SETTLE_ALL_VERIFIED"
        if settlement_set is not None
        else "FROZEN_AWAITING_VERIFIED_OUTCOME"
    )
    receipt = {
        "schema_version": "xinao.multipolicy_consumer_receipt.v1",
        "episode_id": episode_id,
        "state": state,
        "evidence_class": evidence_class,
        "active_set_ref": active_set.active_set_ref,
        "active_set_hash": active_set.content_hash,
        "active_set_non_vacuous": True,
        "eligible_set_ref": eligible_set.eligible_set_ref,
        "eligible_set_hash": eligible_set.content_hash,
        "required_roles": [role.value for role in PolicyRole],
        "freeze_set_ref": freeze_set.freeze_set_ref,
        "freeze_set_hash": freeze_set.content_hash,
        "eligible_frozen_count": freeze_set.eligible_frozen_count,
        "freeze_coverage": freeze_set.freeze_coverage,
        "settlement_set_ref": settlement_set.settlement_set_ref if settlement_set else None,
        "settlement_set_hash": settlement_set.content_hash if settlement_set else None,
        "settled_exactly_once_count": (
            settlement_set.settled_exactly_once_count if settlement_set else 0
        ),
        "void_with_reason_count": settlement_set.void_with_reason_count if settlement_set else 0,
        "missing_or_duplicate_count": (
            settlement_set.missing_or_duplicate_count if settlement_set else None
        ),
        "trial_ledger_head": {
            "entry_count": final_head["entry_count"],
            "entries_sha256": final_head["entries_sha256"],
            "journal_file_sha256": final_head["journal_file_sha256"],
        },
        "claim_grade": (
            "NO_SCIENTIFIC_GRADE_FROM_SYNTHETIC"
            if settlement_set is not None
            else "E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME"
        ),
        "scientific_promotion": False,
        "real_money_authorized": False,
        "parent_complete": False,
        "next_move": pin.next_move,
    }
    receipt["content_hash"] = canonical_sha256(receipt)
    _write_new_json(output_dir / "multipolicy_consumer_receipt.v1.json", receipt)
    manifest = _artifact_manifest(output_dir)
    _write_new_json(output_dir / PACKAGE_MANIFEST_NAME, manifest)
    return {
        "ok": True,
        "package_dir": str(output_dir),
        "state": state,
        "evidence_class": evidence_class,
        "manifest_sha256": sha256_file(output_dir / PACKAGE_MANIFEST_NAME),
        "consumer_receipt_sha256": sha256_file(output_dir / "multipolicy_consumer_receipt.v1.json"),
        "freeze_set_hash": freeze_set.content_hash,
        "settlement_set_hash": settlement_set.content_hash if settlement_set else None,
        "parent_complete": False,
    }


def _fetch_live_source(output_dir: Path) -> tuple[bytes, datetime, Path]:
    request = urllib.request.Request(
        HISTORY_ENDPOINT,
        headers={"User-Agent": "xinao-science-multipolicy-freeze/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        status = response.status
        effective_url = response.geturl()
    captured_at = _millisecond_now()
    if status != 200 or effective_url != HISTORY_ENDPOINT:
        raise ValueError("live history source status or effective URL differs from its binding")
    raw_path = output_dir / "macaujc2_history_2026.raw.json"
    _write_new_bytes(raw_path, raw)
    _write_new_json(
        output_dir / "macaujc2_history_2026.capture.v1.json",
        {
            "schema_version": "xinao.source_capture.v1",
            "source_contract_ref": SOURCE_CONTRACT_REF,
            "endpoint": HISTORY_ENDPOINT,
            "effective_url": effective_url,
            "http_status": status,
            "captured_at": _iso(captured_at),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    )
    return raw, captured_at, raw_path


def run_live_freeze(
    *,
    output_dir: Path,
    episode_id: str,
    target_expect: str,
    target_open_time: datetime,
    freeze_deadline: datetime,
    active_parent_path: Path,
    active_parent_sha256: str,
    source_contract_path: Path,
    source_contract_sha256: str,
) -> dict[str, Any]:
    """Capture current history and freeze a live target without reading its outcome."""

    package_dir = _create_output_dir(output_dir)
    _verify_file(active_parent_path, active_parent_sha256, "active parent")
    _verify_file(source_contract_path, source_contract_sha256, "source contract")
    raw, captured_at, raw_path = _fetch_live_source(package_dir)
    observations = parse_macaujc_history_response(raw, knowledge_cutoff=captured_at)
    latest = observations[-1]
    if latest.expect == target_expect or any(item.expect == target_expect for item in observations):
        raise ValueError("live target outcome is already present in the captured source")
    try:
        horizon_draws = int(target_expect) - int(latest.expect)
    except ValueError as exc:
        raise ValueError("live target expect identity is not numeric") from exc
    if not 1 <= horizon_draws <= 7:
        raise ValueError("live target is outside the bounded one-to-seven-draw horizon")
    latest_local = latest.open_time.astimezone(ASIA_SHANGHAI)
    target_local = target_open_time.astimezone(ASIA_SHANGHAI)
    if (
        target_local.date() - latest_local.date()
    ).days != horizon_draws or target_local.timetz().replace(
        tzinfo=None
    ) != latest_local.timetz().replace(tzinfo=None):
        raise ValueError("live target schedule does not follow the captured daily stream identity")
    frozen_at = _millisecond_now()
    if frozen_at > freeze_deadline:
        raise ValueError("live freeze deadline has already passed")
    information_snapshot = {
        "schema_version": "xinao.live_information_snapshot.v1",
        "source_contract_ref": SOURCE_CONTRACT_REF,
        "history_endpoint": HISTORY_ENDPOINT,
        "history_raw_ref": raw_path.name,
        "history_raw_sha256": sha256_file(raw_path),
        "captured_at": _iso(captured_at),
        "cutoff_safe_observation_count": len(observations),
        "latest_observed_expect": latest.expect,
        "latest_observed_open_time": _iso(latest.open_time),
        "target_expect": target_expect,
        "target_ref": f"macaujc2/expect/{target_expect}",
        "target_open_time": _iso(target_open_time),
        "target_schedule_basis": "DAILY_SUCCESSOR_INFERENCE_FROM_PINNED_RESULT_STREAM",
        "target_horizon_draws": horizon_draws,
        "target_outcome_present": False,
        "evaluation_outcome_access": False,
    }
    information_snapshot["content_hash"] = canonical_sha256(information_snapshot)
    information_path = package_dir / "live_information_snapshot.v1.json"
    _write_new_json(information_path, information_snapshot)
    return build_episode_package(
        output_dir=package_dir,
        episode_id=episode_id,
        evidence_class="PROSPECTIVE_EXPERIMENTAL",
        observations=observations,
        source_snapshot_ref=information_path.name,
        source_snapshot_sha256=sha256_file(information_path),
        source_captured_at=captured_at,
        active_parent_ref=str(active_parent_path),
        active_parent_sha256=active_parent_sha256,
        source_contract_ref=SOURCE_CONTRACT_REF,
        source_contract_sha256=source_contract_sha256,
        target_ref=f"macaujc2/expect/{target_expect}",
        target_open_time=target_open_time,
        knowledge_cutoff=captured_at,
        freeze_deadline=freeze_deadline,
        horizon_draws=horizon_draws,
        frozen_at=frozen_at,
    )


def run_synthetic_recovery(
    *,
    output_dir: Path,
    episode_id: str,
    dataset_path: Path,
    dataset_sha256: str,
    active_parent_path: Path,
    active_parent_sha256: str,
    source_contract_path: Path,
    source_contract_sha256: str,
    synthetic_outcome_number: int,
) -> dict[str, Any]:
    """Run the whole consumer on a clearly synthetic one-period time axis."""

    package_dir = _create_output_dir(output_dir)
    _verify_file(dataset_path, dataset_sha256, "formal dataset")
    _verify_file(active_parent_path, active_parent_sha256, "active parent")
    _verify_file(source_contract_path, source_contract_sha256, "source contract")
    observations = observations_from_draws(load_draws(dataset_path))
    latest = observations[-1]
    knowledge_cutoff = latest.open_time + timedelta(seconds=1)
    target_open_time = latest.open_time + timedelta(days=1)
    frozen_at = latest.open_time + timedelta(minutes=10)
    freeze_deadline = target_open_time - timedelta(hours=1)
    information_snapshot = {
        "schema_version": "xinao.synthetic_recovery_information_snapshot.v1",
        "evidence_class": "EXECUTION_RECOVERY_ONLY",
        "formal_dataset_ref": str(dataset_path),
        "formal_dataset_sha256": dataset_sha256,
        "observation_count": len(observations),
        "latest_observed_expect": latest.expect,
        "latest_observed_open_time": _iso(latest.open_time),
        "synthetic_target_ref": "synthetic/macaujc2/recovery/period-001",
        "synthetic_clock": True,
        "synthetic_outcome": True,
        "scientific_evidence_allowed": False,
    }
    information_snapshot["content_hash"] = canonical_sha256(information_snapshot)
    information_path = package_dir / "synthetic_information_snapshot.v1.json"
    _write_new_json(information_path, information_snapshot)
    return build_episode_package(
        output_dir=package_dir,
        episode_id=episode_id,
        evidence_class="EXECUTION_RECOVERY_ONLY",
        observations=observations,
        source_snapshot_ref=information_path.name,
        source_snapshot_sha256=sha256_file(information_path),
        source_captured_at=knowledge_cutoff,
        active_parent_ref=str(active_parent_path),
        active_parent_sha256=active_parent_sha256,
        source_contract_ref=SOURCE_CONTRACT_REF,
        source_contract_sha256=source_contract_sha256,
        target_ref="synthetic/macaujc2/recovery/period-001",
        target_open_time=target_open_time,
        knowledge_cutoff=knowledge_cutoff,
        freeze_deadline=freeze_deadline,
        horizon_draws=1,
        frozen_at=frozen_at,
        synthetic_outcome_number=synthetic_outcome_number,
    )


def _package_file(root: Path, ref: str, label: str) -> Path:
    candidate = (root / Path(ref)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the episode package") from exc
    if not candidate.is_file():
        raise ValueError(f"{label} is missing: {candidate}")
    return candidate


def _verify_snapshot(snapshot_path: Path, expected_sha256: str) -> None:
    _verify_file(snapshot_path, expected_sha256, "source snapshot")
    payload = _read_json(snapshot_path)
    if not isinstance(payload, dict):
        raise ValueError("source snapshot is not an object")
    recorded_hash = payload.pop("content_hash", None)
    if recorded_hash != canonical_sha256(payload):
        raise ValueError("source snapshot content hash mismatch")


def _verify_trial_ledger_shape(
    *,
    ledger: dict[str, Any],
    pin: MultipolicyProtocolPin,
    compiled: Day1PolicyCompilation,
    state: str,
) -> None:
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise ValueError("fresh readback TrialLedger entries are invalid")
    policy_count = len(compiled.policies)
    if (
        pin.trial_ledger_prefix_entry_count != policy_count
        or len(entries) < policy_count
        or canonical_sha256(entries[:policy_count]) != pin.trial_ledger_prefix_entries_sha256
    ):
        raise ValueError("fresh readback TrialLedger registration prefix differs from ProtocolPin")
    expected_phases = [("registered", False), ("frozen", False)]
    if state == "SYNTHETIC_SETTLE_ALL_VERIFIED":
        expected_phases.append(("synthetic-settled", True))
    expected_count = policy_count * len(expected_phases)
    if len(entries) != expected_count:
        raise ValueError("fresh readback TrialLedger phase coverage is incomplete")
    expected_path_kind = (
        "SYNTHETIC_EXECUTION_RECOVERY"
        if pin.evidence_class == "EXECUTION_RECOVERY_ONLY"
        else "PROSPECTIVE_EXPLORATORY_DAY1"
    )
    for phase_index, (phase, terminal) in enumerate(expected_phases):
        for policy_index, policy in enumerate(compiled.policies):
            entry = entries[phase_index * policy_count + policy_index]
            expected_status = "REGISTERED" if phase == "registered" else "RUNNING"
            if terminal:
                expected_status = (
                    "NO_ACTION" if policy.role == PolicyRole.NO_ACTION else "SUCCEEDED"
                )
            meta = entry.get("meta")
            expected_event_id = f"{pin.episode_id}:{phase}:{policy.policy_ref}"
            if (
                entry.get("work_key") != policy.policy_ref
                or entry.get("status") != expected_status
                or entry.get("family_id") != policy.family_id
                or entry.get("equivalence_cluster_id") != policy.decision_signature.signature_hash
                or entry.get("path_kind") != expected_path_kind
                or entry.get("failure_reason") is not None
                or not isinstance(meta, dict)
                or meta.get("event_id") != expected_event_id
                or meta.get("policy_ref") != policy.policy_ref
                or meta.get("policy_content_hash") != policy.content_hash
                or meta.get("role") != policy.role.value
            ):
                raise ValueError("fresh readback TrialLedger policy trajectory differs")


def verify_episode_package(
    package_dir: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Fresh-process readback for hashes, cross-bindings, and terminal state."""

    root = package_dir.resolve()
    manifest_path = root / PACKAGE_MANIFEST_NAME
    manifest = _read_json(manifest_path)
    manifest_sha256 = sha256_file(manifest_path)
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("multipolicy episode manifest differs from its external pin")
    if not isinstance(manifest, dict) or (
        manifest.get("schema_version") != "xinao.multipolicy_episode_manifest.v1"
    ):
        raise ValueError("unsupported multipolicy episode manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or manifest.get("artifact_count") != len(artifacts):
        raise ValueError("multipolicy episode manifest artifact count is invalid")
    if manifest.get("content_hash") != canonical_sha256(artifacts):
        raise ValueError("multipolicy episode manifest content hash mismatch")
    if manifest != _artifact_manifest(root):
        raise ValueError("multipolicy episode manifest sha256 mismatch or exact inventory drift")

    compiled = Day1PolicyCompilation.model_validate(
        _read_json(root / "day1_policy_compilation.v1.json")
    )
    pin = MultipolicyProtocolPin.model_validate(
        _read_json(root / "multipolicy_protocol_pin.v1.json")
    )
    active_set = ActiveSet.model_validate(_read_json(root / "active_set.v1.json"))
    eligible_set = EligibleSet.model_validate(_read_json(root / "eligible_set.v1.json"))
    freeze_set = FrozenDecisionSet.model_validate(_read_json(root / "frozen_decision_set.v1.json"))
    sealed_objects = (compiled, pin, active_set, eligible_set, freeze_set)
    if any(item.content_hash is None for item in sealed_objects):
        raise ValueError("multipolicy package contains an unsealed semantic object")
    if pin.runtime_source_bindings != _runtime_source_bindings():
        raise ValueError("fresh readback runtime source bindings differ from ProtocolPin")
    snapshot_path = _package_file(root, pin.source_snapshot_ref, "source snapshot")
    _verify_snapshot(snapshot_path, pin.source_snapshot_sha256)

    expected_policy_bindings = tuple(
        PolicyHashBinding(
            policy_ref=policy.policy_ref,
            content_hash=str(policy.content_hash),
            role=policy.role,
        )
        for policy in compiled.policies
    )
    if (
        compiled.target_ref != pin.target_ref
        or compiled.knowledge_cutoff != pin.knowledge_cutoff
        or pin.policy_bindings != expected_policy_bindings
    ):
        raise ValueError("policy compilation does not match the packaged ProtocolPin")

    expected_active_set = admit_active_set(
        active_set_ref=f"active-set/{pin.episode_id}",
        protocol_pin_ref=pin.protocol_pin_ref,
        protocol_pin_sha256=str(pin.content_hash),
        admitted_at=pin.frozen_at,
        policies=compiled.policies,
        residual_axes=pin.residual_axes,
    )
    if active_set != expected_active_set:
        raise ValueError("packaged ActiveSet differs from fresh reconstruction")
    expected_eligible_set = admit_eligible_set(
        active_set=active_set,
        eligible_set_ref=f"eligible-set/{pin.episode_id}/{pin.target_ref}",
        target_ref=pin.target_ref,
        target_open_time=pin.target_open_time,
        created_at=pin.frozen_at,
    )
    if eligible_set != expected_eligible_set:
        raise ValueError("packaged EligibleSet differs from fresh reconstruction")

    gate_payload = _read_json(root / "decision_gates.v1.json")
    if not isinstance(gate_payload, dict):
        raise ValueError("packaged decision gates are not an object")
    gates = {
        str(policy_ref): DecisionGateInput.model_validate(payload)
        for policy_ref, payload in gate_payload.items()
    }
    information_set_hash = canonical_sha256(
        {
            "source_snapshot_sha256": pin.source_snapshot_sha256,
            "history_identity_hash": compiled.history_identity_hash,
            "knowledge_cutoff": _iso(pin.knowledge_cutoff),
            "outcome_access": False,
        }
    )
    expected_gates = build_day1_gates(
        pin=pin,
        compilation=compiled,
        information_set_ref=f"information-set/{pin.episode_id}",
        information_set_hash=information_set_hash,
    )
    if gates != expected_gates:
        raise ValueError("packaged decision gates differ from fresh reconstruction")
    expected_freeze_set = freeze_all(
        active_set=active_set,
        eligible_set=eligible_set,
        gates=gates,
        freeze_set_ref=f"freeze-set/{pin.episode_id}/{pin.target_ref}",
        frozen_at=pin.frozen_at,
    )
    if freeze_set != expected_freeze_set:
        raise ValueError("packaged FrozenDecisionSet differs from fresh reconstruction")

    receipt = _read_json(root / "multipolicy_consumer_receipt.v1.json")
    if not isinstance(receipt, dict):
        raise ValueError("multipolicy consumer receipt is not an object")
    receipt_hash = receipt.pop("content_hash", None)
    if receipt_hash != canonical_sha256(receipt):
        raise ValueError("multipolicy consumer receipt content hash mismatch")
    receipt["content_hash"] = receipt_hash
    state = str(receipt.get("state"))
    if state not in {"SYNTHETIC_SETTLE_ALL_VERIFIED", "FROZEN_AWAITING_VERIFIED_OUTCOME"}:
        raise ValueError("multipolicy consumer receipt has an unsupported state")
    common_receipt_expectations = {
        "episode_id": pin.episode_id,
        "evidence_class": pin.evidence_class,
        "active_set_ref": active_set.active_set_ref,
        "active_set_hash": active_set.content_hash,
        "active_set_non_vacuous": True,
        "eligible_set_ref": eligible_set.eligible_set_ref,
        "eligible_set_hash": eligible_set.content_hash,
        "required_roles": [role.value for role in PolicyRole],
        "freeze_set_ref": freeze_set.freeze_set_ref,
        "freeze_set_hash": freeze_set.content_hash,
        "eligible_frozen_count": 4,
        "freeze_coverage": "1.0000",
        "scientific_promotion": False,
        "real_money_authorized": False,
        "parent_complete": False,
        "next_move": pin.next_move,
    }
    if any(receipt.get(key) != value for key, value in common_receipt_expectations.items()):
        raise ValueError("multipolicy consumer receipt differs from packaged objects")

    ledger = load_science_trial_journal(
        _package_file(root, pin.trial_ledger_anchor_ref, "TrialLedger anchor"),
        expected_anchor_sha256=pin.trial_ledger_anchor_sha256,
        episode_id=pin.episode_id,
    )
    if (
        ledger["entry_count"] != receipt["trial_ledger_head"]["entry_count"]
        or ledger["entries_sha256"] != receipt["trial_ledger_head"]["entries_sha256"]
        or ledger["journal_file_sha256"] != receipt["trial_ledger_head"]["journal_file_sha256"]
    ):
        raise ValueError("fresh readback TrialLedger head differs from consumer receipt")
    _verify_trial_ledger_shape(ledger=ledger, pin=pin, compiled=compiled, state=state)
    frozen_head = _read_json(root / "trial_ledger_frozen_head.v1.json")
    frozen_prefix_count = len(compiled.policies) * 2
    if (
        not isinstance(frozen_head, dict)
        or frozen_head.get("entry_count") != frozen_prefix_count
        or frozen_head.get("entries_sha256")
        != canonical_sha256(ledger["entries"][:frozen_prefix_count])
    ):
        raise ValueError("frozen TrialLedger head does not bind the freeze-all prefix")

    settlement_hash = None
    if state == "SYNTHETIC_SETTLE_ALL_VERIFIED":
        if pin.evidence_class != "EXECUTION_RECOVERY_ONLY":
            raise ValueError("synthetic settlement package has the wrong evidence class")
        outcome = OutcomeObservation.model_validate(_read_json(root / "synthetic_outcome.v1.json"))
        if outcome.with_hash() != outcome or outcome.target_ref != freeze_set.target_ref:
            raise ValueError("synthetic outcome identity or hash differs from its freeze target")
        expected_settlement = settle_all(
            freeze_set=freeze_set,
            outcome=outcome,
            settlement_set_ref=f"settlement-set/{pin.episode_id}/{pin.target_ref}",
            portfolio_ref=f"shadow-portfolio/{pin.episode_id}",
            occurred_at=pin.target_open_time + timedelta(minutes=2),
        )
        settlement = SettlementSet.model_validate(_read_json(root / "settlement_set.v1.json"))
        bundle_payload = _read_json(root / "action_settlement_bundles.v1.json")
        if not isinstance(bundle_payload, list):
            raise ValueError("synthetic action settlement bundles are not an array")
        bundles = tuple(SettlementBundle.model_validate(item) for item in bundle_payload)
        if (
            settlement != expected_settlement.settlement_set
            or bundles != expected_settlement.action_bundles
        ):
            raise ValueError("synthetic settle-all artifacts differ from fresh reconstruction")
        settlement_expectations = {
            "settlement_set_ref": settlement.settlement_set_ref,
            "settlement_set_hash": settlement.content_hash,
            "settled_exactly_once_count": 4,
            "void_with_reason_count": 0,
            "missing_or_duplicate_count": 0,
            "claim_grade": "NO_SCIENTIFIC_GRADE_FROM_SYNTHETIC",
        }
        if any(receipt.get(key) != value for key, value in settlement_expectations.items()):
            raise ValueError("synthetic consumer receipt does not bind settle-all closure")
        settlement_hash = settlement.content_hash
    else:
        if pin.evidence_class != "PROSPECTIVE_EXPERIMENTAL":
            raise ValueError("live freeze package has the wrong evidence class")
        forbidden_live_artifacts = (
            "settlement_set.v1.json",
            "synthetic_outcome.v1.json",
            "action_settlement_bundles.v1.json",
        )
        if any((root / name).exists() for name in forbidden_live_artifacts):
            raise ValueError("live freeze package contains premature outcome or settlement access")
        live_expectations = {
            "settlement_set_ref": None,
            "settlement_set_hash": None,
            "settled_exactly_once_count": 0,
            "void_with_reason_count": 0,
            "missing_or_duplicate_count": None,
            "claim_grade": "E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME",
        }
        if any(receipt.get(key) != value for key, value in live_expectations.items()):
            raise ValueError("live consumer receipt differs from freeze-only closure")
        if frozen_head.get("journal_file_sha256") != ledger["journal_file_sha256"]:
            raise ValueError("live TrialLedger changed after the freeze-all head")

    return {
        "ok": True,
        "schema_version": "xinao.multipolicy_fresh_process_readback.v1",
        "package_dir": str(root),
        "state": state,
        "manifest_sha256": manifest_sha256,
        "external_manifest_pin_matched": expected_manifest_sha256 is not None,
        "active_set_hash": active_set.content_hash,
        "eligible_set_hash": eligible_set.content_hash,
        "freeze_set_hash": freeze_set.content_hash,
        "settlement_set_hash": settlement_hash,
        "eligible_frozen_count": freeze_set.eligible_frozen_count,
        "freeze_coverage": freeze_set.freeze_coverage,
        "trial_ledger_entry_count": ledger["entry_count"],
        "claim_grade": receipt["claim_grade"],
        "real_money_authorized": False,
        "parent_complete": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def authority_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--episode-id", required=True)
        command.add_argument("--active-parent", type=Path, required=True)
        command.add_argument("--active-parent-sha256", required=True)
        command.add_argument("--source-contract", type=Path, required=True)
        command.add_argument("--source-contract-sha256", required=True)

    synthetic = commands.add_parser("synthetic-recovery")
    authority_arguments(synthetic)
    synthetic.add_argument("--dataset", type=Path, required=True)
    synthetic.add_argument("--dataset-sha256", required=True)
    synthetic.add_argument("--synthetic-outcome-number", type=int, default=17)

    live = commands.add_parser("freeze-live")
    authority_arguments(live)
    live.add_argument("--target-expect", required=True)
    live.add_argument("--target-open-time", required=True)
    live.add_argument("--freeze-deadline", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--package-dir", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256")
    verify.add_argument("--report-out", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "synthetic-recovery":
        result = run_synthetic_recovery(
            output_dir=args.output_dir,
            episode_id=args.episode_id,
            dataset_path=args.dataset,
            dataset_sha256=args.dataset_sha256,
            active_parent_path=args.active_parent,
            active_parent_sha256=args.active_parent_sha256,
            source_contract_path=args.source_contract,
            source_contract_sha256=args.source_contract_sha256,
            synthetic_outcome_number=args.synthetic_outcome_number,
        )
    elif args.command == "freeze-live":
        result = run_live_freeze(
            output_dir=args.output_dir,
            episode_id=args.episode_id,
            target_expect=args.target_expect,
            target_open_time=_parse_time(args.target_open_time),
            freeze_deadline=_parse_time(args.freeze_deadline),
            active_parent_path=args.active_parent,
            active_parent_sha256=args.active_parent_sha256,
            source_contract_path=args.source_contract,
            source_contract_sha256=args.source_contract_sha256,
        )
    else:
        result = verify_episode_package(
            args.package_dir,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
        if args.report_out is not None:
            _write_new_json(args.report_out, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
