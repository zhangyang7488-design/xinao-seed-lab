"""Episode export pool entry → Owner disposition seam (Wave124).

Consumer-shaped: ResearchEpisode export → pool-ingest → write-owner-disposition
(→ freeze-from-disposition) for ADOPT / REJECT / RETAIN_FOR_SHADOW.
Pool stays immutable (owner_adopted=false); no auto-settle/next-task.
One-shot loader alone remains fail-closed on episode entries; one-shot
disposition path still works. Attack regressions force remint identity rebind.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.canonical import canonical_sha256
from xinao.cli import main
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
    OWNER_CHANNEL_AUTHORITY_UNPROVEN,
    SCIENCE_ADOPT,
    SCIENCE_REJECT,
    SCIENCE_RETAIN_FOR_SHADOW,
    OwnerDispositionError,
    encode_disposition_bytes,
    load_and_verify_disposition,
    load_verified_pool_entry_for_disposition,
    raw_sha256,
    write_owner_disposition_artifact,
)
from xinao.science.researcher_result_adapter import raw_sha256 as oneshot_raw_sha256
from xinao.shadow_lifecycle import init_episode
from xinao.shadow_lifecycle.store import load_frozen

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


def _manifest(
    *,
    episode_id: str = "ep_owner_disp",
    attempt: str | None = None,
    recommendation: str = "NO_RECOMMENDATION",
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
            "as_of": _iso(CUTOFF),
            "material_refs": [{"id": "seed", "sha256": "aa" * 32}],
        },
        "method_refs": ["wild_multi_turn_export", "lab_manifest"],
        "falsifiers": ["missing export seal", "one-shot loader path"],
        "account_recommendation": recommendation,
        "proposed": {"numbers": [17], "stake": "1.00"},
        "candidate_only": True,
        "owner_adopted": False,
        "completion": False,
    }


def _build_episode_export(
    *,
    episode_id: str = "ep_owner_disp",
    actual_turns: int = 9,
    recommendation: str = "NO_RECOMMENDATION",
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Return (export_bytes, manifest_bytes, export_obj) sealed like native export."""

    attempt = "b" * 64
    manifest = _manifest(
        episode_id=episode_id,
        attempt=attempt,
        recommendation=recommendation,
    )
    man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    body: dict[str, Any] = {
        "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
        "status": "CANDIDATE_EVIDENCE_EXPORTED",
        "episode_id": episode_id,
        "attempt_id": "att_owner_disp_1",
        "attempt_hash": "a" * 64,
        "attempt_cas_digest": attempt,
        "raw_session_hash": "c" * 64,
        "tool_trace_hash": "d" * 64,
        "artifact_manifest_hash": "e" * 64,
        "candidate_manifest_sha256": _sha(man_bytes),
        "pair_receipt_sha256": "11" * 32,
        "namespace_receipt_sha256": "22" * 32,
        "release_identity_sha256": "33" * 32,
        "provider_session_uuid": "00000000-0000-4000-8000-000000000099",
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


# --- Positive: consumer-shaped episode disposition ---------------------------


@pytest.mark.parametrize(
    ("science_disposition", "expected_science_identity"),
    [
        (SCIENCE_ADOPT, "SCIENCE_CANDIDATE"),
        (SCIENCE_REJECT, "POLICY_NO_ACTION"),
        (SCIENCE_RETAIN_FOR_SHADOW, "SCIENCE_CANDIDATE"),
    ],
)
def test_episode_export_write_owner_disposition_library(
    tmp_path: Path,
    science_disposition: str,
    expected_science_identity: str,
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    entry = _ingest_episode(pool, episode_id=f"ep_{science_disposition.lower()}")
    before = _pool_snapshot(pool, entry["result_sha256"])

    payload = _no_action_disposition(entry, science_disposition=science_disposition)
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    assert written["bytes_written"] is True
    digest = written["owner_artifact_sha256"]
    assert digest == raw_sha256(encode_disposition_bytes(payload))
    disp_path = Path(written["disposition_path"])
    assert disp_path.is_file()
    assert disp_path.name == f"{digest}.json"
    assert digest[:2] in disp_path.parts

    verified = load_and_verify_disposition(
        disposition_path=disp_path,
        owner_state_root=owner,
        pool_root=pool,
        result_sha256=entry["result_sha256"],
    )
    assert verified["owner_artifact_sha256"] == digest
    assert verified["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN
    assert verified["owner_disposition_authentic"] is False
    assert verified["path_separated_from_pool"] is True
    disposition = verified["disposition"]
    assert disposition["science_disposition"] == science_disposition
    assert disposition["science_identity"] == expected_science_identity
    assert disposition["result_sha256"] == entry["result_sha256"]
    assert disposition["pool_entry_content_hash"] == entry["content_hash"]
    assert disposition["receipt_content_sha256"] == entry["receipt_content_sha256"]
    assert disposition["account_identity"] == "RESEARCHER_ACCOUNT_NO_ACTION"
    assert verified["pool_entry"]["ingest_kind"] == INGEST_KIND
    assert verified["pool_entry"]["owner_adopted"] is False
    assert verified["pool_entry"]["content_hash"] == entry["content_hash"]

    after = _pool_snapshot(pool, entry["result_sha256"])
    assert after["entry_bytes"] == before["entry_bytes"]
    assert after["entry"]["owner_adopted"] is False
    assert after["entry"]["content_hash"] == before["entry"]["content_hash"]
    # Episode loader still seals; one-shot loader alone must not be required.
    reloaded = load_episode_pool_entry(pool, entry["result_sha256"])
    assert reloaded["owner_adopted"] is False
    _assert_no_freeze_artifacts(owner)
    _assert_no_freeze_artifacts(pool)


@pytest.mark.parametrize(
    "science_disposition",
    [SCIENCE_ADOPT, SCIENCE_REJECT, SCIENCE_RETAIN_FOR_SHADOW],
)
def test_episode_export_write_owner_disposition_cli(
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
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["status"] == "OWNER_DISPOSITION_WRITTEN"
    assert out["science_disposition"] == science_disposition
    assert out["result_sha256"] == entry["result_sha256"]
    assert out["pool_entry_content_hash"] == entry["content_hash"]
    assert out["owner_adopted"] is False
    assert out["freeze_written"] is False
    assert out["settlement_written"] is False
    assert out["auto_freeze"] is False
    assert out["auto_settle"] is False
    assert out["auto_next_period"] is False
    assert out["next_task_created"] is False
    assert out["completion_claim_allowed"] is False
    assert out["owner_channel_authority"] == OWNER_CHANNEL_AUTHORITY_UNPROVEN

    verified = load_and_verify_disposition(
        disposition_path=Path(out["disposition_path"]),
        owner_state_root=owner,
        pool_root=pool,
        result_sha256=entry["result_sha256"],
    )
    assert verified["disposition"]["science_disposition"] == science_disposition
    assert verified["pool_entry"]["ingest_kind"] == INGEST_KIND
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
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
            result_sha256=entry["result_sha256"],
        )
    assert exc.value.reason_code == "DISPOSITION_POOL_ENTRY_HASH_MISMATCH"
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
        science_disposition=SCIENCE_RETAIN_FOR_SHADOW,
        result_sha256=foreign,
    )
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
        )
    assert exc.value.reason_code == "POOL_ENTRY_MISSING"
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
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
            result_sha256=entry["result_sha256"],
        )
    assert exc.value.reason_code == "DISPOSITION_POOL_RECEIPT_MISMATCH"


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
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
            result_sha256=entry["result_sha256"],
        )
    assert exc.value.reason_code in {
        "POOL_RESULT_BYTES_TAMPERED",
        "EPISODE_EXPORT_BUNDLE_HASH_MISMATCH",
        "EPISODE_EXPORT_JSON_INVALID",
    }


# --- One-shot regression -----------------------------------------------------


def test_oneshot_disposition_path_still_works(tmp_path: Path) -> None:
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

    payload = _no_action_disposition(entry, science_disposition=SCIENCE_RETAIN_FOR_SHADOW)
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    verified = load_and_verify_disposition(
        disposition_path=Path(written["disposition_path"]),
        owner_state_root=owner,
        pool_root=pool,
        result_sha256=EXPECTED_ONESHOT_RESULT_SHA256,
    )
    assert verified["disposition"]["science_disposition"] == SCIENCE_RETAIN_FOR_SHADOW
    assert verified["disposition"]["science_identity"] == "SCIENCE_CANDIDATE"
    assert verified["pool_entry"]["owner_adopted"] is False
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

    for entry, science in (
        (episode_entry, SCIENCE_ADOPT),
        (oneshot_entry, SCIENCE_REJECT),
    ):
        payload = _no_action_disposition(entry, science_disposition=science)
        # Distinct payloads → distinct CAS digests under the same owner root.
        payload = copy.deepcopy(payload)
        payload["rationale_ref"] = f"coexist.{entry['result_sha256'][:8]}"
        written = write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=payload,
            pool_root=pool,
        )
        verified = load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
            result_sha256=entry["result_sha256"],
        )
        assert verified["disposition"]["science_disposition"] == science
        assert verified["pool_entry"]["owner_adopted"] is False

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
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    with pytest.raises(OwnerDispositionError) as verify_exc:
        load_and_verify_disposition(
            disposition_path=Path(written["disposition_path"]),
            owner_state_root=owner,
            pool_root=pool,
            result_sha256=honest["result_sha256"],
        )
    assert verify_exc.value.reason_code == "POOL_ENTRY_IDENTITY_MISMATCH"
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


def test_episode_export_disposition_freeze_consumer_no_auto_settle(
    tmp_path: Path,
) -> None:
    """Real consumer-shaped chain stops at freeze; pool immutable; no auto-settle/next."""

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
    written = write_owner_disposition_artifact(
        owner_state_root=owner,
        payload=payload,
        pool_root=pool,
    )
    verified = load_and_verify_disposition(
        disposition_path=Path(written["disposition_path"]),
        owner_state_root=owner,
        pool_root=pool,
        result_sha256=entry["result_sha256"],
    )
    assert verified["pool_entry"]["ingest_kind"] == INGEST_KIND
    assert verified["pool_entry"]["content_hash"] == entry["content_hash"]
    assert verified["pool_entry"]["policy_ref"] == entry["policy_ref"]
    assert verified["pool_entry"]["policy_content_hash"] == entry["policy_content_hash"]

    freeze = apply_freeze_from_disposition(
        pool_root=pool,
        owner_state_root=owner,
        disposition_path=Path(written["disposition_path"]),
        shadow_root=episode_root,
        mode="episode",
        result_sha256=entry["result_sha256"],
        clock=lambda: FROZEN_AT,
    )
    assert freeze.get("ok", True) is True
    assert freeze["mode"] == "episode"
    assert freeze["auto_settle"] is False
    assert freeze["auto_next_period"] is False
    assert freeze["completion_claim_allowed"] is False
    assert freeze["bound_result_sha256"] == entry["result_sha256"]
    assert freeze["bound_pool_entry_content_hash"] == entry["content_hash"]
    assert freeze["frozen_episode_hash"]
    frozen = load_frozen(episode_root)
    assert frozen.content_hash == freeze["frozen_episode_hash"]

    after = _pool_snapshot(pool, entry["result_sha256"])
    assert after["entry_bytes"] == before["entry_bytes"]
    assert after["entry"]["owner_adopted"] is False
    assert after["entry"]["content_hash"] == before["entry"]["content_hash"]
    reloaded = load_episode_pool_entry(pool, entry["result_sha256"])
    assert reloaded["owner_adopted"] is False
    assert reloaded == entry
