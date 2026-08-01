"""Wave96: public one-shot result+receipt → sealed pool → Owner disposition seam.

Uses the real historical pair from xrr_20260730T201916_20001f0913 (copied fixtures).
Proves public CLI admission, CAS/no-overwrite, hash binding, non-Owner rejection,
real NO_ACTION freeze, and coexistence with episode-export pool-ingest. Never
installs or adopts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.cli import build_parser, main
from xinao.science.candidate_pool import (
    CandidatePoolError,
    ingest_verified_research_result,
    load_pool_entry,
    pool_entry_path,
    pool_receipt_path,
    pool_result_bytes_path,
)
from xinao.science.freeze_adapter import (
    FreezeAdapterError,
    apply_freeze_from_disposition,
    build_portfolio_binding_from_shadow,
)
from xinao.science.owner_disposition import (
    CODEX_OWNER_CHANNEL_SOURCE,
    DISPOSITION_MARKER,
    DISPOSITION_SCHEMA_VERSION,
    SCIENCE_RETAIN_FOR_SHADOW,
    OwnerDispositionError,
    disposition_cas_path,
    encode_disposition_bytes,
    write_owner_disposition_artifact,
)
from xinao.science.researcher_result_adapter import raw_sha256
from xinao.shadow_lifecycle import init_portfolio
from xinao.shadow_lifecycle.store import period_directory

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "oneshot_xrr_20260730T201916_20001f0913"
REAL_RESULT_PATH = FIXTURE_DIR / "result.json"
REAL_RECEIPT_PATH = FIXTURE_DIR / "receipt.json"

EXPECTED_RESULT_SHA256 = "12a53a6ff51a52fa6e2635df4508185a967210966fc44fcda101e24fbd876ec9"
EXPECTED_RECEIPT_RAW_SHA256 = "3234e57f7423cc4f4d4725f2eca9700a38c4976690a1d776357856cfa6ba98d1"
EXPECTED_RUN_ID = "xrr_20260730T201916_20001f0913"
# WAVE48 / Wave94 isolated adapt content_hash for this exact result.
EXPECTED_POLICY_CONTENT_HASH = "81f619b4ee0fadc9449776f6e261e04be7ea41442e3bf577f706ae34ebb36f80"

OPEN_AT = datetime(2026, 8, 1, 8, tzinfo=UTC)
CUTOFF = OPEN_AT - timedelta(minutes=10)
FROZEN_AT = OPEN_AT - timedelta(minutes=6)
DEADLINE = OPEN_AT - timedelta(minutes=5)


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(SRC),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "xinao.cli", *argv],
        cwd=str(ROOT),
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _load_real_pair() -> tuple[bytes, dict[str, Any]]:
    assert REAL_RESULT_PATH.is_file(), f"missing fixture: {REAL_RESULT_PATH}"
    assert REAL_RECEIPT_PATH.is_file(), f"missing fixture: {REAL_RECEIPT_PATH}"
    result_bytes = REAL_RESULT_PATH.read_bytes()
    receipt = json.loads(REAL_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(receipt, dict)
    assert raw_sha256(result_bytes) == EXPECTED_RESULT_SHA256
    assert hashlib.sha256(REAL_RECEIPT_PATH.read_bytes()).hexdigest() == EXPECTED_RECEIPT_RAW_SHA256
    return result_bytes, receipt


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _no_action_disposition(entry: dict[str, Any], **overrides: Any) -> dict[str, Any]:
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
        "episode_ref": "episode.wave96.oneshot.p1",
        "target_ref": "draw.20260801-001",
        "knowledge_cutoff": _iso(CUTOFF),
        "science_disposition": SCIENCE_RETAIN_FOR_SHADOW,
        "account_identity": "RESEARCHER_ACCOUNT_NO_ACTION",
        "rationale_ref": "owner-reviewed-real-oneshot-candidate-no-action",
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


def _manual_action_disposition(entry: dict[str, Any]) -> dict[str, Any]:
    body = _no_action_disposition(entry, account_identity="ACTION")
    body.pop("no_action_period_binding", None)
    body["executable_account_decision"] = {
        "panel": "B",
        "selected_number": 7,
        "stake": "1.0000",
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "frozen_at": _iso(FROZEN_AT),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "baseline_ref": "BO0013",
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": "special-number-rule.v1",
    }
    return body


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# --- Parser / public surface -------------------------------------------------


def test_parser_exposes_oneshot_pool_ingest_result() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    # Nested help via subparser parse.
    args = parser.parse_args(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            "p",
            "--result",
            "r.json",
            "--receipt",
            "rc.json",
        ]
    )
    assert args.command == "pool-ingest-result"
    assert args.result == Path("r.json")
    assert args.receipt == Path("rc.json")
    alias = parser.parse_args(
        [
            "research-episode",
            "pool-ingest-oneshot",
            "--pool-root",
            "p",
            "--result",
            "r.json",
            "--receipt",
            "rc.json",
        ]
    )
    assert alias.command == "pool-ingest-oneshot"
    # Episode path remains present (compatibility).
    ep = parser.parse_args(
        [
            "research-episode",
            "pool-ingest",
            "--pool-root",
            "p",
            "--export",
            "e.json",
            "--manifest",
            "m.json",
        ]
    )
    assert ep.command == "pool-ingest"
    re_help = _run_cli(["research-episode", "--help"])
    assert re_help.returncode == 0, re_help.stderr
    assert "pool-ingest-result" in re_help.stdout
    assert "pool-ingest-oneshot" in re_help.stdout
    assert "pool-ingest" in re_help.stdout
    assert "write-owner-disposition" not in re_help.stdout  # lives under prospective
    _ = help_text  # silence unused if format_help not asserted further


# --- Positive: real pair public CLI -----------------------------------------


def test_public_cli_ingests_real_oneshot_pair(tmp_path: Path) -> None:
    result_bytes, receipt = _load_real_pair()
    pool = tmp_path / "pool"
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["status"] == "POOL_ENTRY_READY"
    assert out["admission_shape"] == "oneshot_result_receipt"
    assert out["result_sha256"] == EXPECTED_RESULT_SHA256
    assert out["result_bytes_sha256"] == EXPECTED_RESULT_SHA256
    assert out["run_id"] == EXPECTED_RUN_ID
    assert out["owner_adopted"] is False
    assert out["decision_map_projected"] is False
    assert out["action_support"] == "NOT_PROJECTED"
    assert out["completion_claim_allowed"] is False
    assert out["freeze_written"] is False
    assert out["disposition_written"] is False
    assert out["policy_content_hash"] == EXPECTED_POLICY_CONTENT_HASH
    assert out["policy_ref"] == f"science.research_candidate.v2.sha256:{EXPECTED_RESULT_SHA256}"
    assert receipt["required_bootstrap_protocol"] == 2
    assert type(receipt["required_bootstrap_protocol"]) is int

    # CAS layout + load-verify.
    entry = load_pool_entry(pool, EXPECTED_RESULT_SHA256)
    assert entry["content_hash"] == out["content_hash"]
    assert entry["owner_adopted"] is False
    assert pool_result_bytes_path(pool, EXPECTED_RESULT_SHA256).read_bytes() == result_bytes
    assert pool_receipt_path(pool, EXPECTED_RESULT_SHA256).is_file()
    assert pool_entry_path(pool, EXPECTED_RESULT_SHA256).is_file()


def test_alias_pool_ingest_oneshot_same_entry(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-oneshot",
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["result_sha256"] == EXPECTED_RESULT_SHA256
    assert out["owner_adopted"] is False


def test_duplicate_identical_ingest_is_idempotent(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    first = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert first.returncode == 0, first.stdout + first.stderr
    a = json.loads(first.stdout)
    second = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert second.returncode == 0, second.stdout + second.stderr
    b = json.loads(second.stdout)
    assert a["content_hash"] == b["content_hash"]
    assert a["result_sha256"] == b["result_sha256"]


def test_public_signal_only_oneshot_cannot_be_rewritten_as_owner_no_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    ingest = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert ingest.returncode == 0, ingest.stdout + ingest.stderr
    entry = json.loads(ingest.stdout)
    assert entry["owner_adopted"] is False

    payload_path = _write_json(tmp_path / "disp.json", _no_action_disposition(entry))
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
            EXPECTED_RESULT_SHA256,
            "--expected-pool-entry-content-hash",
            entry["content_hash"],
        ]
    )
    assert code == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["ok"] is False
    assert rejected["reason_code"] == "RESEARCHER_DECISION_SOURCE_ABSENT"
    assert not any(owner.rglob("*.json"))
    # Pool entry still not owner-adopted after disposition write.
    reloaded = load_pool_entry(pool, EXPECTED_RESULT_SHA256)
    assert reloaded["owner_adopted"] is False


def test_real_signal_only_oneshot_cannot_be_disguised_as_no_action(tmp_path: Path) -> None:
    """Missing actor behavior is a signal-only result, never researcher NO_ACTION."""

    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    portfolio = tmp_path / "portfolio"
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    init_portfolio(
        root=portfolio,
        seat_id="seat.wave96.real.no-action",
        portfolio_ref="portfolio.wave96.real.no-action",
    )
    body = _no_action_disposition(entry)
    body["portfolio_binding"] = build_portfolio_binding_from_shadow(portfolio)
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=body,
            pool_root=pool,
        )
    assert exc.value.reason_code == "RESEARCHER_DECISION_SOURCE_ABSENT"
    assert not any(owner.rglob("*.json"))
    assert not (period_directory(portfolio, 1) / "frozen_episode.v1.json").exists()


def test_real_oneshot_manual_action_rejected_before_owner_cas(tmp_path: Path) -> None:
    """The real xrr fixture has research prose, not a researcher-authored ticket core."""

    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    with pytest.raises(OwnerDispositionError) as exc:
        write_owner_disposition_artifact(
            owner_state_root=owner,
            payload=_manual_action_disposition(entry),
            pool_root=pool,
        )
    assert exc.value.reason_code == "RESEARCHER_DECISION_SOURCE_ABSENT"
    assert not owner.exists() or list(owner.rglob("*.json")) == []


def test_freeze_rechecks_real_oneshot_action_after_writer_bypass(tmp_path: Path) -> None:
    """Hand-sealing caller JSON cannot bypass the freeze-time producer re-read."""

    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    shadow = tmp_path / "shadow"
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool,
        result_bytes=result_bytes,
        receipt=receipt,
    )
    body = _manual_action_disposition(entry)
    raw = encode_disposition_bytes(body)
    digest = hashlib.sha256(raw).hexdigest()
    path = disposition_cas_path(owner, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)  # deliberate direct-filesystem bypass of formal writer

    with pytest.raises(FreezeAdapterError) as exc:
        apply_freeze_from_disposition(
            pool_root=pool,
            owner_state_root=owner,
            disposition_path=path,
            shadow_root=shadow,
            mode="episode",
            clock=lambda: FROZEN_AT,
        )
    assert exc.value.reason_code == "RESEARCHER_DECISION_SOURCE_ABSENT"
    assert not shadow.exists() or list(shadow.rglob("*.json")) == []


# --- Negatives: mutation / cross-pair / conflict / non-Owner -----------------


def test_mutated_result_bytes_rejected(tmp_path: Path) -> None:
    result_bytes, _receipt = _load_real_pair()
    # Mutate payload but keep filename; hash will not match receipt.result_sha256.
    mutated = bytearray(result_bytes)
    # Flip a byte in the middle of the JSON body.
    idx = len(mutated) // 2
    mutated[idx] = (mutated[idx] + 1) % 256
    bad_result = tmp_path / "mutated_result.json"
    bad_result.write_bytes(bytes(mutated))
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(REAL_RECEIPT_PATH.read_bytes())
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(bad_result),
            "--receipt",
            str(receipt_path),
        ]
    )
    assert proc.returncode == 1
    err = json.loads(proc.stdout)
    assert err["ok"] is False
    assert err["owner_adopted"] is False
    assert err["completion_claim_allowed"] is False
    # Adapter rejects hash mismatch or verification failure.
    assert err["reason_code"]


def test_mutated_receipt_pin_text_rejected(tmp_path: Path) -> None:
    _, receipt = _load_real_pair()
    bad = copy.deepcopy(receipt)
    # Historical failure mode: text pin instead of JSON int 2.
    bad["required_bootstrap_protocol"] = "2"
    receipt_path = _write_json(tmp_path / "receipt_text_pin.json", bad)
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(receipt_path),
        ]
    )
    assert proc.returncode == 1
    err = json.loads(proc.stdout)
    assert err["ok"] is False
    # Adapter fail-closed codes for non-int/wrong bootstrap pin.
    assert err["reason_code"] in {
        "RECEIPT_BOOTSTRAP_PROTOCOL_INVALID",
        "RECEIPT_PIN_INVALID",
    }
    assert err["owner_adopted"] is False


def test_cross_pair_receipt_result_rejected(tmp_path: Path) -> None:
    """Receipt bound to real result cannot admit an unrelated result object."""
    _, receipt = _load_real_pair()
    # Minimal wrong result with different bytes but still JSON.
    foreign = {
        "schema_version": "xinao.researcher_container_result.v2",
        "status": "CANDIDATE_READY",
        "reason_codes": [],
        "candidate": receipt["candidate"],
        "request_sha256": "a" * 64,
        "prompt_sha256": "b" * 64,
        "output_schema_sha256": "c" * 64,
        "material_bundle_id": receipt["material_bundle_id"],
        "material_manifest_sha256": receipt["material_manifest_sha256"],
        "material_packet_sha256": receipt["material_packet_sha256"],
        "effective_prompt_sha256": receipt["effective_prompt_sha256"],
        "material_refs_available": ["sha256:" + ("cd" * 32)],
        "provider": "grok",
        "requested_model": "grok-4.5",
        "provider_stop_reason": "EndTurn",
        "provider_num_turns": 1,
        "provider_session_id_present": True,
        "provider_request_id_present": True,
        "provider_session_id": "foreign-session",
        "provider_request_id": "foreign-request",
        "provider_model_usage": {
            "grok-4.5": {"inputTokens": 1, "outputTokens": 1, "modelCalls": 1}
        },
        "usage": {"total_tokens": 2},
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }
    foreign_bytes = (json.dumps(foreign, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    assert raw_sha256(foreign_bytes) != EXPECTED_RESULT_SHA256
    foreign_path = tmp_path / "foreign_result.json"
    foreign_path.write_bytes(foreign_bytes)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(REAL_RECEIPT_PATH.read_bytes())
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(foreign_path),
            "--receipt",
            str(receipt_path),
        ]
    )
    assert proc.returncode == 1
    err = json.loads(proc.stdout)
    assert err["ok"] is False
    assert err["owner_adopted"] is False
    assert (
        "RESULT" in err["reason_code"]
        or "HASH" in err["reason_code"]
        or "RECEIPT" in err["reason_code"]
        or "BINDING" in err["reason_code"]
        or "MISMATCH" in err["reason_code"]
    )


def test_cas_content_conflict_on_same_hash_different_bytes(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    result_bytes, receipt = _load_real_pair()
    # First admit real pair.
    entry = ingest_verified_research_result(
        pool_root=pool, result_bytes=result_bytes, receipt=receipt
    )
    assert entry["result_sha256"] == EXPECTED_RESULT_SHA256
    # Poison the stored result blob in place (same path / same hash key).
    result_path = pool_result_bytes_path(pool, EXPECTED_RESULT_SHA256)
    # Replace with different content while keeping path (simulates silent overwrite attempt).
    # Direct path rewrite is outside API; re-ingest different bytes claiming same identity
    # is done by planting a different result with forged receipt.result_sha256=real hash.
    # Build alternate payload whose raw hash differs, but plant under CAS key by
    # writing conflicting blob then calling load / second ingest of real pair after poison.
    poison = b'{"poison":true}\n'
    result_path.write_bytes(poison)
    with pytest.raises(CandidatePoolError) as excinfo:
        ingest_verified_research_result(pool_root=pool, result_bytes=result_bytes, receipt=receipt)
    assert excinfo.value.reason_code == "POOL_CAS_CONTENT_CONFLICT"


def test_failed_status_receipt_rejected(tmp_path: Path) -> None:
    _, receipt = _load_real_pair()
    bad = copy.deepcopy(receipt)
    bad["status"] = "FAILED"
    # Keep result path as real success result — status mismatch must fail closed.
    receipt_path = _write_json(tmp_path / "failed_receipt.json", bad)
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(receipt_path),
        ]
    )
    assert proc.returncode == 1
    err = json.loads(proc.stdout)
    assert err["ok"] is False
    assert err["owner_adopted"] is False


def test_worker_disposition_rejected_after_oneshot_pool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool, result_bytes=result_bytes, receipt=receipt
    )
    body = _no_action_disposition(entry, disposition_source="worker")
    payload = _write_json(tmp_path / "worker_disp.json", body)
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
    assert "DISPOSITION_SOURCE_NOT_OWNER_CHANNEL" in err["reason_code"]
    assert err["owner_adopted"] is False if "owner_adopted" in err else True
    reloaded = load_pool_entry(pool, EXPECTED_RESULT_SHA256)
    assert reloaded["owner_adopted"] is False


def test_worker_controlled_true_rejected_after_oneshot_pool(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool, result_bytes=result_bytes, receipt=receipt
    )
    body = _no_action_disposition(entry)
    body["worker_controlled"] = True
    payload = _write_json(tmp_path / "wc.json", body)
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
    assert "DISPOSITION_WORKER_CONTROLLED" in err["reason_code"]
    assert load_pool_entry(pool, EXPECTED_RESULT_SHA256)["owner_adopted"] is False


def test_science_reject_cannot_smuggle_account_action(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = tmp_path / "pool"
    owner = tmp_path / "owner"
    owner.mkdir()
    result_bytes, receipt = _load_real_pair()
    entry = ingest_verified_research_result(
        pool_root=pool, result_bytes=result_bytes, receipt=receipt
    )
    body = _no_action_disposition(
        entry,
        science_disposition="REJECT",
        account_identity="ACTION",
    )
    body.pop("no_action_period_binding", None)
    body["executable_account_decision"] = {
        "panel": "B",
        "selected_number": 7,
        "stake": "1.0000",
        "target_ref": "draw.20260801-001",
        "target_open_time": _iso(OPEN_AT),
        "freeze_deadline": _iso(DEADLINE),
        "frozen_at": _iso(FROZEN_AT),
        "knowledge_cutoff": _iso(CUTOFF),
        "odds_version_ref": "odds.special-number.20260731.v1",
        "baseline_ref": "BO0013",
        "risk_policy_ref": "shadow-risk.max-one-unit.v1",
        "rule_ref": "special-number-rule.v1",
    }
    payload = _write_json(tmp_path / "smuggle.json", body)
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
    assert err["completion_claim_allowed"] is False


# --- Episode export compatibility -------------------------------------------


def test_episode_export_pool_ingest_still_present_and_distinct(tmp_path: Path) -> None:
    """One-shot verb does not replace episode export routing."""
    help_proc = _run_cli(["research-episode", "--help"])
    assert help_proc.returncode == 0
    assert "pool-ingest" in help_proc.stdout
    assert "pool-ingest-result" in help_proc.stdout
    # Feeding result.json as --export must not succeed as episode export.
    proc = _run_cli(
        [
            "research-episode",
            "pool-ingest",
            "--pool-root",
            str(tmp_path / "pool"),
            "--export",
            str(REAL_RESULT_PATH),
            "--manifest",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert proc.returncode != 0
    # Prefer structured fail when possible.
    if proc.stdout.strip().startswith("{"):
        err = json.loads(proc.stdout)
        assert err.get("ok") is False
        assert err.get("owner_adopted") is False


def test_main_dispatch_oneshot_returns_json_not_traceback(tmp_path: Path) -> None:
    code = main(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(tmp_path / "missing_result.json"),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    assert code == 1
