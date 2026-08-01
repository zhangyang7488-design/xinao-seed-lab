"""Episode export pool entry → Owner disposition seam (Wave124).

Consumer-shaped: ResearchEpisode export → pool-ingest → write-owner-disposition
(→ freeze-from-disposition only after ADOPT) for ADOPT / REJECT / DEFER.
Pool stays immutable (owner_adopted=false); no auto-settle/next-task.
One-shot loader alone remains fail-closed on episode entries; one-shot
disposition path still works. Attack regressions force remint identity rebind.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xinao.canonical import canonical_sha256
from xinao.cli import main
from xinao.science import owner_disposition as owner_disposition_module
from xinao.science.candidate_pool import (
    CandidatePoolError,
    ingest_verified_research_result,
    load_pool_entry,
    pool_entry_path,
    pool_receipt_path,
    pool_result_bytes_path,
)
from xinao.science.episode_export_pool_adapter import (
    INGEST_KIND,
    EpisodeExportAdapterError,
    ingest_verified_episode_export,
    load_episode_pool_entry,
    remint_episode_pool_entry_from_raw,
)
from xinao.science.freeze_adapter import apply_freeze_from_disposition
from xinao.science.owner_disposition import (
    CODEX_OWNER_CHANNEL_SOURCE,
    DISPOSITION_MARKER,
    DISPOSITION_SCHEMA_VERSION,
    SCIENCE_ADOPT,
    SCIENCE_DEFER,
    SCIENCE_REJECT,
    OwnerDispositionError,
    draft_owner_disposition,
    load_and_verify_disposition,
    load_verified_pool_entry_for_disposition,
    write_owner_disposition_artifact,
)
from xinao.science.researcher_result_adapter import raw_sha256 as oneshot_raw_sha256
from xinao.shadow_lifecycle import consumer as shadow_consumer
from xinao.shadow_lifecycle import init_episode
from xinao.shadow_lifecycle.store import StoreError, load_frozen, period_directory

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "oneshot_xrr_20260730T201916_20001f0913"
REAL_RESULT_PATH = FIXTURE_DIR / "result.json"
REAL_RECEIPT_PATH = FIXTURE_DIR / "receipt.json"
EXPECTED_ONESHOT_RESULT_SHA256 = "12a53a6ff51a52fa6e2635df4508185a967210966fc44fcda101e24fbd876ec9"

OPEN_AT = datetime(2026, 8, 1, 8, tzinfo=UTC)
CUTOFF = OPEN_AT - timedelta(minutes=10)
FROZEN_AT = OPEN_AT - timedelta(minutes=6)
DEADLINE = OPEN_AT - timedelta(minutes=5)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _researcher_no_action_core() -> dict[str, Any]:
    return {
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "knowledge_cutoff": _iso(CUTOFF),
        "rule_ref": "special-number-rule.v1",
        "odds_version_ref": "odds.special-number.20260731.v1",
    }


def _manifest(
    *,
    episode_id: str = "ep_owner_disp",
    attempt: str | None = None,
    recommendation: str = "NO_RECOMMENDATION",
    executable: dict[str, Any] | None = None,
    actor_intent: dict[str, Any] | None = None,
    data_cutoff_as_of: datetime = CUTOFF,
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.research_episode_candidate_manifest.v1",
        "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        "candidate_id": "cand_episode_owner_disp",
        "candidate_version": "v1",
        "episode_id": episode_id,
        "attempt_cas_digest": attempt or ("b" * 64),
        "research_question": "can Codex dispose a real episode export pool entry?",
        "research_object": "episode export → pool → owner disposition",
        "data_cutoff": {
            "as_of": _iso(data_cutoff_as_of),
            "material_refs": [{"id": "seed", "sha256": "aa" * 32}],
        },
        "method_refs": ["wild_multi_turn_export", "lab_manifest"],
        "falsifiers": ["missing export seal", "one-shot loader path"],
        "account_recommendation": recommendation,
        "proposed": (
            actor_intent
            if actor_intent is not None
            else (
                {"executable_account_decision": executable}
                if executable is not None
                else {"no_action_intent": _researcher_no_action_core()}
            )
        ),
        "candidate_only": True,
        "owner_adopted": False,
        "completion": False,
    }


def _build_episode_export(
    *,
    episode_id: str = "ep_owner_disp",
    actual_turns: int = 9,
    recommendation: str = "NO_RECOMMENDATION",
    executable: dict[str, Any] | None = None,
    actor_intent: dict[str, Any] | None = None,
    attempt_cas_digest: str = "b" * 64,
    attempt_hash: str = "a" * 64,
    cas_head_sha256: str = "f" * 64,
    host_session_id: str = "host.owner-disposition-fixture",
    provider_session_uuid: str = "00000000-0000-4000-8000-000000000099",
    data_cutoff_as_of: datetime = CUTOFF,
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Return (export_bytes, manifest_bytes, export_obj) sealed like native export."""

    attempt = attempt_cas_digest
    manifest = _manifest(
        episode_id=episode_id,
        attempt=attempt,
        recommendation=recommendation,
        executable=executable,
        actor_intent=actor_intent,
        data_cutoff_as_of=data_cutoff_as_of,
    )
    man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    body: dict[str, Any] = {
        "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
        "status": "CANDIDATE_EVIDENCE_EXPORTED",
        "episode_id": episode_id,
        "attempt_id": "att_owner_disp_1",
        "attempt_hash": attempt_hash,
        "attempt_cas_digest": attempt,
        "cas_head_sha256": cas_head_sha256,
        "host_session_id": host_session_id,
        "raw_session_hash": "c" * 64,
        "tool_trace_hash": "d" * 64,
        "artifact_manifest_hash": "e" * 64,
        "candidate_manifest_sha256": _sha(man_bytes),
        "pair_receipt_sha256": "11" * 32,
        "namespace_receipt_sha256": "22" * 32,
        "release_identity_sha256": "33" * 32,
        "provider_session_uuid": provider_session_uuid,
        "research_profile": "OPEN_RESEARCH",
        "actual_turns": actual_turns,
        "max_turns": 16,
        "candidate_only": True,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "shadow_write": False,
        "next_task_created": False,
        "disposition_written": False,
        "freeze_written": False,
        "settlement_written": False,
        "portfolio_updated": False,
    }
    bundle_hash = _sha(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    export = {**body, "bundle_sha256": bundle_hash}
    export_bytes = (json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return export_bytes, man_bytes, export


def _ingest_episode(pool: Path, **kwargs: Any) -> dict[str, Any]:
    export_bytes, man_bytes, _ = _build_episode_export(**kwargs)
    entry = ingest_verified_episode_export(
        pool_root=pool,
        export=export_bytes,
        manifest_bytes=man_bytes,
    )
    assert entry["ingest_kind"] == INGEST_KIND
    assert entry["owner_adopted"] is False
    return entry


def _no_action_disposition(
    entry: dict[str, Any],
    *,
    science_disposition: str,
    **overrides: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": DISPOSITION_SCHEMA_VERSION,
        "disposition_marker": DISPOSITION_MARKER,
        "disposition_source": CODEX_OWNER_CHANNEL_SOURCE,
        "owner_role": "codex",
        "worker_controlled": False,
        "result_sha256": entry["result_sha256"],
        "receipt_content_sha256": entry["receipt_content_sha256"],
        "pool_entry_content_hash": entry["content_hash"],
        "period_index": 1,
        "episode_ref": (
            f"episode.wave124.{entry.get('lab_provenance', {}).get('episode_id', 'x')}.p1"
        ),
        "target_ref": "draw.20260801-001",
        "knowledge_cutoff": _iso(CUTOFF),
        "science_disposition": science_disposition,
        "account_identity": "RESEARCHER_ACCOUNT_NO_ACTION",
        "rationale_ref": f"owner-disposition.episode.{science_disposition.lower()}",
        "no_action_period_binding": {
            "target_ref": "draw.20260801-001",
            "target_open_time": _iso(OPEN_AT),
            "freeze_deadline": _iso(DEADLINE),
            "frozen_at": _iso(FROZEN_AT),
            "knowledge_cutoff": _iso(CUTOFF),
            "rule_ref": "special-number-rule.v1",
            "odds_version_ref": "odds.special-number.20260731.v1",
        },
    }
    body.update(overrides)
    return body


def _researcher_action_core(*, selected_number: int = 17) -> dict[str, Any]:
    return {
        "panel": "B",
        "selected_number": selected_number,
        "stake": "1.0000",
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "baseline_ref": "BO0013",
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": "special-number-rule.v1",
    }


def _action_disposition(
    entry: dict[str, Any],
    *,
    selected_number: int = 17,
) -> dict[str, Any]:
    body = _no_action_disposition(
        entry,
        science_disposition=SCIENCE_ADOPT,
        account_identity="ACTION",
    )
    body.pop("no_action_period_binding", None)
    body["executable_account_decision"] = {
        **_researcher_action_core(selected_number=selected_number),
        "frozen_at": _iso(FROZEN_AT),
    }
    return body


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _pool_snapshot(pool: Path, result_sha256: str) -> dict[str, Any]:
    entry_path = pool_entry_path(pool, result_sha256)
    raw = entry_path.read_bytes()
    return {
        "entry_bytes": raw,
        "entry": json.loads(raw.decode("utf-8")),
        "entry_sha256": _sha(raw),
    }


def _assert_no_freeze_artifacts(root: Path) -> None:
    """Disposition write must not mint freeze / settle / next-task trees."""

    forbidden_names = {
        "frozen_episode",
        "settled_episode",
        "freeze",
        "settlement",
        "next_task",
    }
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_dir() and path.name in forbidden_names:
            raise AssertionError(f"unexpected freeze-ish dir: {path}")
        # Disposition CAS lives under owner/objects/sha256 — name is hash only.
        if (
            path.is_file()
            and "sha256" not in path.parts
            and any(token in path.name.lower() for token in ("freeze", "settle"))
        ):
            raise AssertionError(f"unexpected freeze-ish file: {path}")


def _reseal_pool_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Attack helper: recompute content_hash after field rewrite (entry-only forge)."""

    body = {k: v for k, v in entry.items() if k != "content_hash"}
    return {**body, "content_hash": canonical_sha256(body)}


def _overwrite_pool_entry(pool: Path, entry: dict[str, Any]) -> None:
    path = pool_entry_path(pool, str(entry["result_sha256"]))
    path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_pool_ingest_accepts_native_seal_with_windows_provenance_integers(
    tmp_path: Path,
) -> None:
    """Opaque Windows file identity may exceed RFC 8785's integer domain."""

    export_bytes, manifest_bytes, export = _build_episode_export(episode_id="ep_windows_provenance")
    del export_bytes
    export["prompt_material_cutoff"] = {
        "active_material_binding": {
            "material_source_refs": [
                {
                    "st_dev": 13599825006036549566,
                    "st_ino": 9007199254864121,
                    "st_mtime_ns": 1785573664473036700,
                }
            ]
        }
    }
    body = {key: value for key, value in export.items() if key != "bundle_sha256"}
    export["bundle_sha256"] = _sha(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    sealed_export = (
        json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    pool = tmp_path / "pool"
    entry = ingest_verified_episode_export(
        pool_root=pool,
        export=sealed_export,
        manifest_bytes=manifest_bytes,
    )

    assert pool_result_bytes_path(pool, entry["result_sha256"]).read_bytes() == sealed_export
    assert load_episode_pool_entry(pool, entry["result_sha256"]) == entry

    tampered = {**export, "bundle_sha256": "0" * 64}
    tampered_export = (
        json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with pytest.raises(EpisodeExportAdapterError) as exc:
        ingest_verified_episode_export(
            pool_root=tmp_path / "tampered_pool",
            export=tampered_export,
            manifest_bytes=manifest_bytes,
        )
    assert exc.value.reason_code == "EPISODE_EXPORT_BUNDLE_HASH_MISMATCH"
    assert not (tmp_path / "tampered_pool").exists()


# --- Positive: consumer-shaped episode disposition ---------------------------


@pytest.mark.parametrize(
    "science_disposition",
    [SCIENCE_ADOPT, SCIENCE_REJECT],
)
def test_legacy_episode_branch_cannot_become_new_formal_disposition(
    tmp_path: Path,
    science_disposition: str,
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool, episode_id=f"ep_{science_disposition.lower()}")
    before = _pool_snapshot(pool, entry["result_sha256"])

    payload = _no_action_disposition(entry, science_disposition=science_disposition)
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "PRODUCTION_ACTOR_INTENT_REQUIRED"
    assert list(owner.rglob("*.json")) == []

    after = _pool_snapshot(pool, entry["result_sha256"])
    assert after["entry_bytes"] == before["entry_bytes"]
    assert after["entry"]["owner_adopted"] is False
    assert after["entry"]["content_hash"] == before["entry"]["content_hash"]
    # History stays readable, but it cannot masquerade as a new actor Episode.
    reloaded = load_episode_pool_entry(pool, entry["result_sha256"])
    assert reloaded["owner_adopted"] is False
    _assert_no_freeze_artifacts(owner)
    _assert_no_freeze_artifacts(pool)


def test_episode_action_rejects_legacy_platform_completed_execution_core(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    core = _researcher_action_core(selected_number=17)
    with pytest.raises(EpisodeExportAdapterError) as exc:
        _ingest_episode(
            pool,
            episode_id="ep_manifest_action",
            recommendation="ACTION_CANDIDATE",
            executable=core,
        )
    assert exc.value.reason_code == "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID"
    assert not pool.exists()


def test_freeze_consumer_rejects_unknown_episode_recommendation_explicitly(
    tmp_path: Path,
) -> None:
    """An unknown value can never fall through and make ``proposed`` a producer."""

    pool = tmp_path / "pool_unknown_recommendation"
    valid_entry = _ingest_episode(pool, episode_id="ep_unknown_recommendation")
    export_raw = pool_result_bytes_path(pool, valid_entry["result_sha256"]).read_bytes()
    manifest_raw = pool_receipt_path(pool, valid_entry["result_sha256"]).read_bytes()
    export = json.loads(export_raw)
    manifest = json.loads(manifest_raw)
    manifest["account_recommendation"] = "UNKNOWN_BRANCH"
    forged_manifest_raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    manifest_sha = _sha(forged_manifest_raw)
    export["candidate_manifest_sha256"] = manifest_sha
    export_body = {key: value for key, value in export.items() if key != "bundle_sha256"}
    export["bundle_sha256"] = _sha(
        (
            json.dumps(
                export_body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    forged_export_raw = (
        json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    result_sha = _sha(forged_export_raw)
    forged_entry = copy.deepcopy(valid_entry)
    forged_entry.update(
        {
            "result_sha256": result_sha,
            "receipt_content_sha256": manifest_sha,
            "receipt_raw_sha256": manifest_sha,
            "export_bundle_sha256": result_sha,
            "candidate_manifest_sha256": manifest_sha,
        }
    )
    forged_entry["content_hash"] = canonical_sha256(
        {key: value for key, value in forged_entry.items() if key != "content_hash"}
    )
    for path, raw in (
        (pool_entry_path(pool, result_sha), json.dumps(forged_entry, sort_keys=True).encode()),
        (pool_result_bytes_path(pool, result_sha), forged_export_raw),
        (pool_receipt_path(pool, result_sha), forged_manifest_raw),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    with pytest.raises(StoreError, match="PRODUCTION_FREEZE_EPISODE_RECOMMENDATION_INVALID"):
        shadow_consumer._load_pool_and_research_source(
            research_pool_root=pool,
            result_sha256=result_sha,
        )


@pytest.mark.parametrize(
    "science_disposition",
    [SCIENCE_ADOPT, SCIENCE_REJECT, SCIENCE_DEFER],
)
def test_cli_rejects_legacy_episode_branch_as_new_formal_disposition(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    science_disposition: str,
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool, episode_id=f"ep_cli_{science_disposition.lower()}")
    before = _pool_snapshot(pool, entry["result_sha256"])
    payload_path = _write_json(
        tmp_path / f"disp_{science_disposition}.json",
        _no_action_disposition(entry, science_disposition=science_disposition),
    )
    code = main(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(owner),
            "--pool-root",
            str(pool),
            "--payload",
            str(payload_path),
            "--expected-result-sha256",
            entry["result_sha256"],
            "--expected-pool-entry-content-hash",
            entry["content_hash"],
        ]
    )
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["reason_code"] == "PRODUCTION_ACTOR_INTENT_REQUIRED"
    assert list(owner.rglob("*.json")) == []
    assert _pool_snapshot(pool, entry["result_sha256"])["entry_bytes"] == before["entry_bytes"]


def test_dispatch_prefers_episode_loader_for_export_ingest(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    entry = _ingest_episode(pool)
    loaded = load_verified_pool_entry_for_disposition(pool, entry["result_sha256"])
    assert loaded["ingest_kind"] == INGEST_KIND
    assert loaded["content_hash"] == entry["content_hash"]
    # Control: bare one-shot loader still rejects episode CAS (wrong verifier).
    with pytest.raises(CandidatePoolError) as exc:
        load_pool_entry(pool, entry["result_sha256"])
    assert exc.value.reason_code in {
        "RECEIPT_RESULT_HASH_INVALID",
        "RESULT_RECEIPT_MISMATCH",
        "RESULT_SCHEMA_INVALID",
        "POOL_RESULT_HASH_DRIFT",
    }


# --- Negatives ---------------------------------------------------------------


def test_worker_disposition_source_rejected_on_episode_entry(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool)
    before = _pool_snapshot(pool, entry["result_sha256"])
    payload = _no_action_disposition(
        entry,
        science_disposition=SCIENCE_ADOPT,
        disposition_source="worker",
    )
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL"
    assert list(owner.rglob("*.json")) == []
    assert _pool_snapshot(pool, entry["result_sha256"])["entry_bytes"] == before["entry_bytes"]


def test_worker_controlled_true_rejected_on_episode_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool)
    body = _no_action_disposition(entry, science_disposition=SCIENCE_REJECT)
    body["worker_controlled"] = True
    payload = _write_json(tmp_path / "worker_controlled.json", body)
    code = main(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(owner),
            "--pool-root",
            str(pool),
            "--payload",
            str(payload),
        ]
    )
    assert code == 1
    err = json.loads(capsys.readouterr().out)
    assert err["ok"] is False
    assert "DISPOSITION_WORKER_CONTROLLED" in err["reason_code"]
    reloaded = load_episode_pool_entry(pool, entry["result_sha256"])
    assert reloaded["owner_adopted"] is False


def test_pool_entry_content_hash_drift_rejected(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool)
    payload = _no_action_disposition(
        entry,
        science_disposition=SCIENCE_ADOPT,
        pool_entry_content_hash="ff" * 32,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "DISPOSITION_POOL_ENTRY_HASH_MISMATCH"
    assert list(owner.rglob("*.json")) == []
    assert load_episode_pool_entry(pool, entry["result_sha256"])["owner_adopted"] is False


def test_result_sha256_hash_drift_rejected(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool)
    # Bind a foreign result hash that does not exist under the pool.
    foreign = "ab" * 32
    payload = _no_action_disposition(
        entry,
        science_disposition=SCIENCE_ADOPT,
        result_sha256=foreign,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "POOL_ENTRY_MISSING"
    assert list(owner.rglob("*.json")) == []
    assert load_episode_pool_entry(pool, entry["result_sha256"])["owner_adopted"] is False


def test_receipt_content_hash_drift_rejected(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool)
    payload = _no_action_disposition(
        entry,
        science_disposition=SCIENCE_REJECT,
        receipt_content_sha256="cc" * 32,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "DISPOSITION_POOL_RECEIPT_MISMATCH"
    assert list(owner.rglob("*.json")) == []


def test_tampered_export_blob_fails_closed_on_verify(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    export_bytes, man_bytes, _ = _build_episode_export()
    entry = ingest_verified_episode_export(
        pool_root=pool,
        export=export_bytes,
        manifest_bytes=man_bytes,
    )
    # Corrupt CAS result blob after exclusive create (simulates wrong loader/CAS drift).
    from xinao.science.candidate_pool import pool_result_bytes_path

    result_path = pool_result_bytes_path(pool, entry["result_sha256"])
    mutated = bytearray(result_path.read_bytes())
    mutated[len(mutated) // 2] = (mutated[len(mutated) // 2] + 1) % 256
    # Force overwrite outside pool API (attack surface).
    result_path.write_bytes(bytes(mutated))
    payload = _no_action_disposition(entry, science_disposition=SCIENCE_ADOPT)
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code in {
        "POOL_RESULT_BYTES_TAMPERED",
        "EPISODE_EXPORT_BUNDLE_HASH_MISMATCH",
        "EPISODE_EXPORT_JSON_INVALID",
    }
    assert list(owner.rglob("*.json")) == []


# --- One-shot regression -----------------------------------------------------


def test_legacy_oneshot_without_researcher_decision_cannot_be_disposed(tmp_path: Path) -> None:
    assert REAL_RESULT_PATH.is_file(), f"missing fixture: {REAL_RESULT_PATH}"
    assert REAL_RECEIPT_PATH.is_file(), f"missing fixture: {REAL_RECEIPT_PATH}"
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    result_bytes = REAL_RESULT_PATH.read_bytes()
    receipt = json.loads(REAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert oneshot_raw_sha256(result_bytes) == EXPECTED_ONESHOT_RESULT_SHA256
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    assert entry.get("ingest_kind") != INGEST_KIND
    # Dispatch helper must route to one-shot loader.
    loaded = load_verified_pool_entry_for_disposition(pool, entry["result_sha256"])
    assert loaded["result_sha256"] == EXPECTED_ONESHOT_RESULT_SHA256
    assert loaded["owner_adopted"] is False
    assert (
        load_pool_entry(pool, EXPECTED_ONESHOT_RESULT_SHA256)["content_hash"]
        == entry["content_hash"]
    )

    payload = _no_action_disposition(entry, science_disposition=SCIENCE_ADOPT)
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "RESEARCHER_DECISION_SOURCE_ABSENT"
    assert list(owner.rglob("*.json")) == []
    reloaded = load_pool_entry(pool, EXPECTED_ONESHOT_RESULT_SHA256)
    assert reloaded["owner_adopted"] is False
    assert reloaded["content_hash"] == entry["content_hash"]


def test_episode_and_oneshot_coexist_under_same_pool(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    episode_entry = _ingest_episode(pool, episode_id="ep_coexist")
    result_bytes = REAL_RESULT_PATH.read_bytes()
    receipt = json.loads(REAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    oneshot_entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    assert episode_entry["result_sha256"] != oneshot_entry["result_sha256"]

    with pytest.raises(OwnerDispositionError) as episode_exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=_no_action_disposition(episode_entry, science_disposition=SCIENCE_ADOPT),
            pool_root=pool,
        )
    assert episode_exc.value.reason_code == "PRODUCTION_ACTOR_INTENT_REQUIRED"

    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=_no_action_disposition(oneshot_entry, science_disposition=SCIENCE_REJECT),
            pool_root=pool,
        )
    assert exc.value.reason_code == "RESEARCHER_DECISION_SOURCE_ABSENT"

    assert load_episode_pool_entry(pool, episode_entry["result_sha256"])["owner_adopted"] is False
    assert load_pool_entry(pool, oneshot_entry["result_sha256"])["owner_adopted"] is False


def test_missing_pool_entry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(OwnerDispositionError) as exc:
        load_verified_pool_entry_for_disposition(tmp_path / "empty_pool", "aa" * 32)
    assert exc.value.reason_code == "POOL_ENTRY_MISSING"


# --- Attack: entry-only rewrite / receipt forge / policy remint forge --------


def test_entry_only_candidate_rewrite_reseal_fails_load(tmp_path: Path) -> None:
    """Attack: rewrite candidate (+ policy) on entry, reseal content_hash; CAS intact.

    Pre-harden load only checked entry seal + export/manifest pin, so Owner
    disposition could bind a forged identity. Remint from CAS must fail closed.
    """

    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    honest = _ingest_episode(pool, episode_id="ep_entry_only_forge")
    honest_before = _pool_snapshot(pool, honest["result_sha256"])

    forged = copy.deepcopy(honest)
    forged["candidate"] = {
        **dict(forged["candidate"]),
        "candidate_id": "attacker_smuggled_candidate",
        "research_question": "forged research question for owner smuggle",
        "proposed": {"numbers": [49], "stake": "999.00"},
    }
    forged["policy_ref"] = "science.research_episode_export.v1.sha256:" + ("0" * 64)
    forged["policy_content_hash"] = "11" * 32
    forged = _reseal_pool_entry(forged)
    assert forged["content_hash"] != honest["content_hash"]
    _overwrite_pool_entry(pool, forged)

    with pytest.raises(EpisodeExportAdapterError) as load_exc:
        load_episode_pool_entry(pool, honest["result_sha256"])
    assert load_exc.value.reason_code == "POOL_ENTRY_IDENTITY_MISMATCH"

    with pytest.raises(OwnerDispositionError) as disp_exc:
        load_verified_pool_entry_for_disposition(pool, honest["result_sha256"])
    assert disp_exc.value.reason_code == "POOL_ENTRY_IDENTITY_MISMATCH"

    # Disposition that pins the forged entry hash must also fail on verify.
    payload = _no_action_disposition(
        forged,
        science_disposition=SCIENCE_ADOPT,
    )
    with pytest.raises(OwnerDispositionError) as verify_exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert verify_exc.value.reason_code == "POOL_ENTRY_IDENTITY_MISMATCH"
    assert list(owner.rglob("*.json")) == []
    # CAS blobs (result/receipt) unchanged; only entry JSON was rewritten.
    assert pool_result_bytes_path(pool, honest["result_sha256"]).is_file()
    assert pool_receipt_path(pool, honest["result_sha256"]).is_file()
    assert honest_before["entry_sha256"] != _sha(
        pool_entry_path(pool, honest["result_sha256"]).read_bytes()
    )


def test_entry_receipt_field_forge_reseal_fails_load(tmp_path: Path) -> None:
    """Attack: forge receipt_content/raw/candidate_manifest hashes on entry only."""

    pool = tmp_path / "pool"
    honest = _ingest_episode(pool, episode_id="ep_receipt_forge")
    forged_hash = "dd" * 32
    forged = copy.deepcopy(honest)
    forged["receipt_content_sha256"] = forged_hash
    forged["receipt_raw_sha256"] = forged_hash
    forged["candidate_manifest_sha256"] = forged_hash
    forged = _reseal_pool_entry(forged)
    _overwrite_pool_entry(pool, forged)

    with pytest.raises(EpisodeExportAdapterError) as exc:
        load_episode_pool_entry(pool, honest["result_sha256"])
    assert exc.value.reason_code == "POOL_ENTRY_RECEIPT_HASH_MISMATCH"

    with pytest.raises(OwnerDispositionError) as od_exc:
        load_verified_pool_entry_for_disposition(pool, honest["result_sha256"])
    assert od_exc.value.reason_code == "POOL_ENTRY_RECEIPT_HASH_MISMATCH"


def test_policy_remint_forge_fails_when_entry_diverges(tmp_path: Path) -> None:
    """Attack: keep receipt hashes honest but swap policy_ref/content_hash + reseal."""

    pool = tmp_path / "pool"
    export_bytes, man_bytes, _ = _build_episode_export(episode_id="ep_policy_forge")
    honest = ingest_verified_episode_export(
        pool_root=pool,
        export=export_bytes,
        manifest_bytes=man_bytes,
    )
    reminted = remint_episode_pool_entry_from_raw(
        export_raw=export_bytes,
        manifest_raw=man_bytes,
    )
    assert reminted["expected_entry"] == honest

    forged = copy.deepcopy(honest)
    forged["policy_ref"] = "science.forged.policy.v1.sha256:" + ("ab" * 32)
    forged["policy_content_hash"] = "ef" * 32
    forged["decision_map_ref"] = "xinao.not_projected.forged.v1:" + ("cd" * 32)
    forged = _reseal_pool_entry(forged)
    _overwrite_pool_entry(pool, forged)

    with pytest.raises(EpisodeExportAdapterError) as exc:
        load_episode_pool_entry(pool, honest["result_sha256"])
    assert exc.value.reason_code == "POOL_ENTRY_IDENTITY_MISMATCH"
    # Remint ground truth unchanged (attack only touched entry JSON).
    remint_again = remint_episode_pool_entry_from_raw(
        export_raw=pool_result_bytes_path(pool, honest["result_sha256"]).read_bytes(),
        manifest_raw=pool_receipt_path(pool, honest["result_sha256"]).read_bytes(),
    )
    assert remint_again["expected_entry"]["policy_ref"] == honest["policy_ref"]
    assert remint_again["expected_entry"]["policy_content_hash"] == honest["policy_content_hash"]


def test_missing_result_or_receipt_maps_to_pool_cas_partial_state(tmp_path: Path) -> None:
    """Missing CAS blobs must not surface bare FileNotFoundError/OSError."""

    # Drop result blob only.
    pool_result = tmp_path / "pool_result"
    entry_result = _ingest_episode(pool_result, episode_id="ep_partial_result")
    digest_result = entry_result["result_sha256"]
    pool_result_bytes_path(pool_result, digest_result).unlink()
    with pytest.raises(EpisodeExportAdapterError) as miss_result:
        load_episode_pool_entry(pool_result, digest_result)
    assert miss_result.value.reason_code == "POOL_CAS_PARTIAL_STATE"
    with pytest.raises(OwnerDispositionError) as od_result:
        load_verified_pool_entry_for_disposition(pool_result, digest_result)
    assert od_result.value.reason_code == "POOL_CAS_PARTIAL_STATE"

    # Drop receipt/manifest blob only.
    pool_receipt = tmp_path / "pool_receipt"
    entry_receipt = _ingest_episode(pool_receipt, episode_id="ep_partial_receipt")
    digest_receipt = entry_receipt["result_sha256"]
    pool_receipt_path(pool_receipt, digest_receipt).unlink()
    with pytest.raises(EpisodeExportAdapterError) as miss_receipt:
        load_episode_pool_entry(pool_receipt, digest_receipt)
    assert miss_receipt.value.reason_code == "POOL_CAS_PARTIAL_STATE"
    with pytest.raises(OwnerDispositionError) as od_receipt:
        load_verified_pool_entry_for_disposition(pool_receipt, digest_receipt)
    assert od_receipt.value.reason_code == "POOL_CAS_PARTIAL_STATE"


# --- Full consumer: export → pool → disposition → freeze-from-disposition ----


def test_legacy_episode_branch_cannot_reach_freeze_consumer(
    tmp_path: Path,
) -> None:
    """Flat production freeze is unavailable until it has a source-bound settle path."""

    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    episode_root = tmp_path / "episode_shadow"
    init_episode(
        root=episode_root,
        seat_id="seat.episode.owner.disp",
        portfolio_ref="portfolio.episode.owner.disp",
    )
    entry = _ingest_episode(pool, episode_id="ep_freeze_consumer")
    before = _pool_snapshot(pool, entry["result_sha256"])

    payload = _no_action_disposition(entry, science_disposition=SCIENCE_ADOPT)
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
    assert exc.value.reason_code == "PRODUCTION_ACTOR_INTENT_REQUIRED"
    assert not (episode_root / "frozen.json").exists()

    after = _pool_snapshot(pool, entry["result_sha256"])
    assert after["entry_bytes"] == before["entry_bytes"]
    assert after["entry"]["owner_adopted"] is False
    assert after["entry"]["content_hash"] == before["entry"]["content_hash"]
    reloaded = load_episode_pool_entry(pool, entry["result_sha256"])
    assert reloaded["owner_adopted"] is False
    assert reloaded == entry


def test_current_episode_actor_intent_projects_and_reaches_portfolio_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact actor intent joins fresh runtime reality and survives final re-read."""

    # Reuse the real actor/reality fixture so target, account, authority packet,
    # objective terms, active material bundle, and prompt identities all agree.
    from xinao.shadow_lifecycle.actor_reality import ActorRealityContract

    actor_fixture_path = (
        Path(__file__).resolve().parents[1] / "shadow_lifecycle" / ("test_actor_reality.py")
    )
    actor_fixture_spec = importlib.util.spec_from_file_location(
        "_actor_reality_test_fixture",
        actor_fixture_path,
    )
    assert actor_fixture_spec is not None and actor_fixture_spec.loader is not None
    actor_fixture = importlib.util.module_from_spec(actor_fixture_spec)
    actor_fixture_spec.loader.exec_module(actor_fixture)

    pool = tmp_path / "pool_episode_action"
    owner = tmp_path / "owner_episode_action"
    portfolio = actor_fixture._portfolio_root(tmp_path, suffix="episode-action")
    episode_root, authority_root, verified_material, _packet_id, _terms_id = (
        actor_fixture._active_material_fixture(
            tmp_path,
            open_at=actor_fixture.P1_OPEN,
            portfolio_root=portfolio,
        )
    )
    reality = ActorRealityContract._from_verified_material_reality(
        portfolio_root=portfolio,
        episode_root=episode_root,
        authority_root=authority_root,
        verified_material_reality=verified_material,
    )
    intent = actor_fixture._intent(reality, selected_number=17, stake="100.0000")
    material = reality.material_reality
    cutoff, authored_at, _deadline = actor_fixture._times(actor_fixture.P1_OPEN)
    entry = _ingest_episode(
        pool,
        episode_id=material.episode_id,
        recommendation="ACTION_CANDIDATE",
        actor_intent=intent.model_dump(mode="json"),
        attempt_cas_digest=material.attempt_cas_digest,
        attempt_hash=material.attempt_hash,
        cas_head_sha256=material.cas_head_sha256,
        host_session_id=material.host_session_id,
        provider_session_uuid=material.provider_session_uuid,
        data_cutoff_as_of=cutoff,
    )

    runtime_calls: list[dict[str, Any]] = []

    def build_live_reality(**kwargs: Any) -> ActorRealityContract:
        runtime_calls.append(dict(kwargs))
        assert kwargs == {
            "root": episode_root.resolve(),
            "portfolio_root": portfolio.resolve(),
            "authority_root": authority_root.resolve(),
            "attempt_cas_digest": material.attempt_cas_digest,
            "expected_head_sha256": material.cas_head_sha256,
            "expected_provider_session_uuid": material.provider_session_uuid,
            "expected_host_session_id": material.host_session_id,
            "attempt_hash": material.attempt_hash,
        }
        return reality

    monkeypatch.setattr(
        owner_disposition_module,
        "_load_xinao_runtime_module",
        lambda: SimpleNamespace(research_episode_build_actor_reality=build_live_reality),
    )

    draft = draft_owner_disposition(
        pool_root=pool,
        result_sha256=entry["result_sha256"],
        episode_root=episode_root,
        portfolio_root=portfolio,
        authority_root=authority_root,
        packet_content_hash=material.prospective_packet_content_hash,
    )
    payload = copy.deepcopy(draft["payload_draft"])
    payload.update(
        {
            "disposition_source": CODEX_OWNER_CHANNEL_SOURCE,
            "owner_role": "codex",
            "worker_controlled": False,
            "science_disposition": SCIENCE_ADOPT,
            "rationale_ref": "owner.current-episode.actor-intent.accepted",
        }
    )
    branch = copy.deepcopy(draft["branch_templates"]["ACTION"])
    branch["executable_account_decision"]["frozen_at"] = _iso(authored_at)
    payload.update(branch)

    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
        episode_root=episode_root,
        portfolio_root=portfolio,
        authority_root=authority_root,
    )
    verified = load_and_verify_disposition(
        disposition_path=Path(written["disposition_path"]),
        owner_state_root=owner,
        pool_root=pool,
        episode_root=episode_root,
        portfolio_root=portfolio,
        authority_root=authority_root,
    )
    binding = verified["researcher_action_binding"]
    assert binding["actor_authored_intent_hash"] == intent.content_hash
    assert binding["episode_id"] == material.episode_id
    assert binding["attempt_cas_digest"] == material.attempt_cas_digest
    assert binding["information_set_ref"] == material.material_bundle_id
    assert binding["effective_prompt_sha256"] == material.effective_prompt_sha256

    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=portfolio,
        mode="portfolio",
        episode_root=episode_root,
        authority_root=authority_root,
        clock=lambda: authored_at,
    )
    assert freeze["ok"] is True
    assert freeze["researcher_action_binding"] == binding
    frozen = load_frozen(period_directory(portfolio, 1))
    assert frozen.bound_account_ticket is not None
    assert frozen.bound_account_ticket.selected_number == 17
    assert str(frozen.bound_account_ticket.stake) == "100.0000"
    assert frozen.bound_account_ticket.information_set_ref == material.material_bundle_id
    # draft, formal write, explicit readback, freeze adapter, and the independent
    # portfolio consumer each re-enter the exact runtime producer identity.
    assert len(runtime_calls) >= 5
