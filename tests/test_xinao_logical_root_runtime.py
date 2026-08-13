from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
import services.xinao_perpetual_world_compute.logical_root_runtime as logical_root_module
from services.xinao_perpetual_world_compute.logical_root_runtime import (
    LogicalRootConflict,
    LogicalRootEvidenceError,
    LogicalRootIntegrityError,
    LogicalRootStore,
    RootIdentity,
    validate_frozen_world_seed,
)

RUN_V1 = "xinao.cleanroom-c.perpetual-run.v1"
RUN_V2 = "xinao.cleanroom.perpetual-world-compute-run.v2"
PACKET_V1 = "xinao.cleanroom-c.late-fusion-packet.v1"
PACKET_V2 = "xinao.cleanroom.perpetual-world-compute-late-fusion-packet.v2"
LINEAGE_V1 = "xinao.cleanroom-c.perpetual-lineage-state.v1"
LINEAGE_V2 = "xinao.cleanroom.perpetual-world-compute-lineage-state.v2"
TURN_V1 = "xinao.cleanroom-c.perpetual-turn-receipt.v1"
TURN_V2 = "xinao.cleanroom.perpetual-world-compute-turn-receipt.v2"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


@dataclass(frozen=True)
class RunFixture:
    run_dir: Path
    workspace: Path
    packet_candidate: Path
    root_message: Path
    root_output: bytes


def _make_committed_run(
    tmp_path: Path,
    *,
    account_slot: str,
    run_name: str,
    root_output: bytes,
    legacy: bool = False,
) -> RunFixture:
    state_root = tmp_path / "source-runtime" / f"xinao_perpetual_{account_slot.lower()}"
    run_dir = state_root / "runs" / run_name
    workspace = tmp_path / "cleanroom" / "research-lineages" / run_name / "root-main"
    packet_dir = workspace / "S_CONTROL_INPUTS" / "wave-000001"
    packet_dir.mkdir(parents=True)
    run_dir.mkdir(parents=True)

    schemas = (
        (RUN_V1, PACKET_V1, LINEAGE_V1, TURN_V1)
        if legacy
        else (RUN_V2, PACKET_V2, LINEAGE_V2, TURN_V2)
    )
    run_schema, packet_schema, lineage_schema, turn_schema = schemas
    source_head = ("c" if account_slot == "C" else "a") * 40
    candidate_raw = f"candidate from {account_slot}\n".encode()
    packet_candidate = packet_dir / "CANDIDATE_01.txt"
    packet_candidate.write_bytes(candidate_raw)
    deep_entry: dict[str, object] = {}
    deep_manifest: dict[str, object] = {}
    if not legacy:
        deep_path = packet_dir / "DEEP_EVIDENCE_01.json"
        deep_raw = _write_json(
            deep_path,
            {
                "schema": "xinao.cleanroom.world-compute-deep-evidence-ref.v1",
                "lineage_id": "world-01",
                "turn_number": 1,
                "candidate_authority": False,
                "s_content_adjudication": False,
                "availability": "AVAILABLE",
            },
        )
        deep_entry = {
            "deep_evidence_path": deep_path.name,
            "deep_evidence_sha256": _sha(deep_raw),
            "deep_evidence_availability": "AVAILABLE",
        }
        deep_manifest = {"deep_evidence_mode": "thin_index_on_demand_v1"}
    manifest = {
        "schema": packet_schema,
        "run_id": run_name,
        "wave_number": 1,
        "frozen_at": "2026-08-13T00:00:00+00:00",
        "source_head": source_head,
        "selection_rule": "latest successful completed turn snapshot from every branch",
        "candidate_authority": False,
        "s_content_adjudication": False,
        "entries": [
            {
                "anonymous_index": 1,
                "source_lineage_id": "world-01",
                "source_session_id": f"session-{account_slot.lower()}",
                "source_turn_number": 1,
                "source_last_message_sha256": _sha(candidate_raw),
                "packet_path": packet_candidate.name,
                "source_workspace": str(workspace.parent / "world-01"),
                "source_workspace_head": source_head,
                **deep_entry,
            }
        ],
        **deep_manifest,
    }
    manifest_path = packet_dir / "PACKET_MANIFEST.json"
    manifest_raw = _write_json(manifest_path, manifest)

    root_spec = {
        "lineage_id": "root-main",
        "role": "late_fusion_root",
        "workspace": str(workspace.resolve()),
        "head": source_head,
        "remote_count": "0",
        "status_sha256": _sha(b""),
    }
    _write_json(
        run_dir / "run_config.json",
        {
            "schema": run_schema,
            "run_id": run_name,
            "run_dir": str(run_dir.resolve()),
            "account_slot": account_slot,
            "source_head": source_head,
            "root_lineage": root_spec,
            "branch_lineages": [
                {
                    "lineage_id": "world-01",
                    "role": "independent_world",
                    "workspace": str(workspace.parent / "world-01"),
                }
            ],
        },
    )
    lineage_dir = run_dir / "lineages" / "root-main"
    turn_dir = lineage_dir / "turns" / "turn-000001"
    attempt_dir = turn_dir / "attempt-01"
    attempt_dir.mkdir(parents=True)
    root_message = attempt_dir / "last_message.txt"
    root_message.write_bytes(root_output)
    _write_json(
        attempt_dir / "receipt.json",
        {
            "schema": turn_schema,
            "run_id": run_name,
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "turn_number": 1,
            "attempt_number": 1,
            "started_at": "2026-08-13T00:00:00+00:00",
            "ended_at": "2026-08-13T00:00:01+00:00",
            "error_class": None,
            "exit_code": 0,
            "turn_status": "turn.completed",
            "lifecycle_state": "WAIT",
            "last_message_sha256": _sha(root_output),
        },
    )
    _write_json(
        lineage_dir / "state.json",
        {
            "schema": lineage_schema,
            "run_id": run_name,
            "lineage_id": "root-main",
            "role": "late_fusion_root",
            "workspace": str(workspace.resolve()),
            "source_head": source_head,
            "turns_completed": 1,
            "last_completed_turn_dir": str(turn_dir.resolve()),
            "last_turn_dir": str(turn_dir.resolve()),
            "lifecycle_state": "WAIT",
            "status": "PARKED_WAIT",
            "updated_at": "2026-08-13T00:00:01+00:00",
        },
    )
    _write_json(
        lineage_dir / "fusion_state.json",
        {
            "schema": packet_schema,
            "run_id": run_name,
            "waves_completed": 1,
            "consumed_turns": {"world-01": 1},
            "last_packet": str(packet_dir.resolve()),
            "last_packet_manifest_sha256": _sha(manifest_raw),
            "pending_packet": None,
            "updated_at": "2026-08-13T00:00:02+00:00",
        },
    )
    return RunFixture(run_dir, workspace, packet_candidate, root_message, root_output)


def _adopt(
    store: LogicalRootStore,
    fixture: RunFixture,
    *,
    slot: str,
    predecessor: RootIdentity,
    adoption_id: str,
):
    return store.adopt(
        source_run_dir=fixture.run_dir,
        account_slot=slot,
        expected_predecessor=predecessor,
        adoption_id=adoption_id,
        selection_ref=f"owner-selection-{adoption_id}",
        selected_by="experiment-effect-owner",
    )


def test_two_account_runs_form_one_generation_chain_and_reconstruct(tmp_path: Path) -> None:
    a_run = _make_committed_run(
        tmp_path,
        account_slot="A",
        run_name="a-run-001",
        root_output=b"root world after A\n",
    )
    c_run = _make_committed_run(
        tmp_path,
        account_slot="C",
        run_name="c-run-001",
        root_output=b"root world after C\n",
        legacy=True,
    )
    store_root = tmp_path / "logical-root-store"
    store = LogicalRootStore(store_root, clock=lambda: "2026-08-13T01:00:00+00:00")

    first = _adopt(
        store,
        a_run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="adopt-a-001",
    )
    second = _adopt(
        store,
        c_run,
        slot="C",
        predecessor=first.adopted.identity,
        adoption_id="adopt-c-001",
    )

    assert first.adopted.identity.generation == 1
    assert second.adopted.identity.generation == 2
    assert second.adopted.receipt["predecessor"] == first.adopted.identity.to_dict()
    assert first.adopted.receipt["source"]["account_slot"] == "A"
    assert second.adopted.receipt["source"]["account_slot"] == "C"
    assert second.adopted.receipt["account_slot_is_provenance_only"] is True
    assert second.adopted.receipt["store_scientific_adjudication"] is False
    assert second.adopted.receipt["shared_repository_writes"] is False
    assert first.adopted.artifact_path != second.adopted.artifact_path
    assert second.adopted.artifact_path.read_bytes() == c_run.root_output

    reopened = LogicalRootStore(store_root)
    reconstructed = reopened.reconstruct_current()
    assert reconstructed.identity == second.adopted.identity
    assert reopened.read_current_artifact() == c_run.root_output
    assert len(list((store_root / "generation_receipts").iterdir())) == 2


def test_stale_predecessor_fails_closed_without_a_generation(tmp_path: Path) -> None:
    a_run = _make_committed_run(
        tmp_path, account_slot="A", run_name="a-run-stale", root_output=b"A root\n"
    )
    c_run = _make_committed_run(
        tmp_path,
        account_slot="C",
        run_name="c-run-stale",
        root_output=b"C root\n",
        legacy=True,
    )
    store = LogicalRootStore(tmp_path / "store")
    first = _adopt(
        store,
        a_run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="stale-a",
    )

    with pytest.raises(LogicalRootConflict) as raised:
        _adopt(
            store,
            c_run,
            slot="C",
            predecessor=RootIdentity.genesis(),
            adoption_id="stale-c",
        )

    assert raised.value.code == "STALE_PREDECESSOR"
    assert store.reconstruct_current().identity == first.adopted.identity
    assert len(list(store.receipts_dir.iterdir())) == 1


def test_exact_replay_is_idempotent_and_key_reuse_conflicts(tmp_path: Path) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="a-run-replay", root_output=b"stable root\n"
    )
    store = LogicalRootStore(tmp_path / "store")
    first = _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="replay-001",
    )
    replay = _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="replay-001",
    )

    assert replay.replayed is True
    assert replay.adopted.identity == first.adopted.identity
    assert len(list(store.receipts_dir.iterdir())) == 1

    with pytest.raises(LogicalRootConflict) as raised:
        store.adopt(
            source_run_dir=run.run_dir,
            account_slot="A",
            expected_predecessor=RootIdentity.genesis(),
            adoption_id="replay-001",
            selection_ref="different-owner-selection",
            selected_by="experiment-effect-owner",
        )
    assert raised.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(list(store.receipts_dir.iterdir())) == 1


def test_canonical_store_rejects_direct_adopt_before_creating_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical-logical-root"
    monkeypatch.setattr(logical_root_module, "DEFAULT_LOGICAL_ROOT_RUNTIME", canonical)
    store = LogicalRootStore(canonical)

    with pytest.raises(LogicalRootConflict) as rejected:
        store.adopt(
            source_run_dir=tmp_path / "unused-source",
            account_slot="A",
            expected_predecessor=RootIdentity.genesis(),
            adoption_id="direct-canonical",
            selection_ref="direct-selection",
            selected_by="direct-caller",
        )

    assert rejected.value.code == "CANONICAL_ADOPTION_REQUIRES_EFFECT_GATEWAY"
    assert not canonical.exists()


def test_canonical_store_rejects_direct_adopt_through_filesystem_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical-logical-root"
    alias = tmp_path / "canonical-alias"
    canonical.mkdir()
    try:
        alias.symlink_to(canonical, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory alias unavailable: {exc}")
    monkeypatch.setattr(logical_root_module, "DEFAULT_LOGICAL_ROOT_RUNTIME", canonical)
    store = LogicalRootStore(alias)

    with pytest.raises(LogicalRootConflict) as rejected:
        store.adopt(
            source_run_dir=tmp_path / "unused-source",
            account_slot="C",
            expected_predecessor=RootIdentity.genesis(),
            adoption_id="direct-canonical-alias",
            selection_ref="direct-selection",
            selected_by="direct-caller",
        )

    assert rejected.value.code == "CANONICAL_ADOPTION_REQUIRES_EFFECT_GATEWAY"
    assert list(canonical.iterdir()) == []


@pytest.mark.parametrize("tamper_target", ["artifact", "receipt"])
def test_committed_tamper_is_detected_from_receipts_and_cas(
    tmp_path: Path, tamper_target: str
) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name=f"a-run-tamper-{tamper_target}", root_output=b"root\n"
    )
    store = LogicalRootStore(tmp_path / "store")
    result = _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id=f"tamper-{tamper_target}",
    )
    if tamper_target == "artifact":
        result.adopted.artifact_path.write_bytes(b"evil\n")
    else:
        receipt = json.loads(result.adopted.receipt_path.read_text(encoding="utf-8"))
        receipt["request"]["selected_by"] = "tampered-owner"
        result.adopted.receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(LogicalRootIntegrityError):
        LogicalRootStore(store.root).reconstruct_current()


def test_missing_fusion_evidence_is_rejected_before_adoption(tmp_path: Path) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="C", run_name="c-run-missing", root_output=b"root\n", legacy=True
    )
    run.packet_candidate.unlink()
    store = LogicalRootStore(tmp_path / "store")

    with pytest.raises(LogicalRootEvidenceError) as raised:
        _adopt(
            store,
            run,
            slot="C",
            predecessor=RootIdentity.genesis(),
            adoption_id="missing-evidence",
        )

    assert raised.value.code == "EVIDENCE_FILE_MISSING"
    assert store.reconstruct_current().identity == RootIdentity.genesis()
    assert list(store.receipts_dir.iterdir()) == []


class SimulatedCrash(RuntimeError):
    pass


def test_crash_before_receipt_commit_leaves_no_generation_and_retry_commits(
    tmp_path: Path,
) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="a-run-crash-before", root_output=b"root before\n"
    )
    store_root = tmp_path / "store"

    def crash(point: str) -> None:
        if point == "before_receipt_commit":
            raise SimulatedCrash(point)

    crashing = LogicalRootStore(store_root, fault_injector=crash)
    with pytest.raises(SimulatedCrash, match="before_receipt_commit"):
        _adopt(
            crashing,
            run,
            slot="A",
            predecessor=RootIdentity.genesis(),
            adoption_id="crash-before",
        )

    reopened = LogicalRootStore(store_root)
    assert reopened.reconstruct_current().identity == RootIdentity.genesis()
    assert list(reopened.receipts_dir.iterdir()) == []
    assert any(reopened.artifacts_dir.rglob("*"))

    committed = _adopt(
        reopened,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="crash-before",
    )
    assert committed.replayed is False
    assert committed.adopted.identity.generation == 1


def test_crash_after_receipt_commit_reconstructs_and_retry_is_replay(tmp_path: Path) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="C", run_name="c-run-crash-after", root_output=b"root after\n"
    )
    store_root = tmp_path / "store"

    def crash(point: str) -> None:
        if point == "after_receipt_commit":
            raise SimulatedCrash(point)

    crashing = LogicalRootStore(store_root, fault_injector=crash)
    with pytest.raises(SimulatedCrash, match="after_receipt_commit"):
        _adopt(
            crashing,
            run,
            slot="C",
            predecessor=RootIdentity.genesis(),
            adoption_id="crash-after",
        )

    reopened = LogicalRootStore(store_root)
    reconstructed = reopened.reconstruct_current()
    assert reconstructed.identity.generation == 1
    assert not reopened.current_projection_path.exists()

    replay = _adopt(
        reopened,
        run,
        slot="C",
        predecessor=RootIdentity.genesis(),
        adoption_id="crash-after",
    )
    assert replay.replayed is True
    assert replay.adopted.identity == reconstructed.identity
    assert replay.current.identity == reconstructed.identity
    assert reopened.current_projection_path.is_file()
    assert len(list(reopened.receipts_dir.iterdir())) == 1


def test_pending_fusion_packet_is_not_guessed_as_a_committed_root(tmp_path: Path) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="a-run-pending", root_output=b"root\n"
    )
    fusion_path = run.run_dir / "lineages" / "root-main" / "fusion_state.json"
    fusion = json.loads(fusion_path.read_text(encoding="utf-8"))
    fusion["pending_packet"] = {
        "wave_number": 2,
        "packet_dir": str(run.workspace / "S_CONTROL_INPUTS" / "wave-000002"),
        "manifest_sha256": "0" * 64,
        "selected_turns": {"world-01": 2},
    }
    _write_json(fusion_path, fusion)
    store = LogicalRootStore(tmp_path / "store")

    with pytest.raises(LogicalRootEvidenceError) as raised:
        _adopt(
            store,
            run,
            slot="A",
            predecessor=RootIdentity.genesis(),
            adoption_id="pending-not-committed",
        )

    assert raised.value.code == "FUSION_COMMIT_AMBIGUOUS"
    assert store.reconstruct_current().identity == RootIdentity.genesis()


def test_freeze_genesis_world_seed_is_explicit_and_self_verifying(tmp_path: Path) -> None:
    store = LogicalRootStore(tmp_path / "store")
    target = tmp_path / "frozen"

    frozen = store.freeze_current_world_seed(target)

    assert frozen["status"] == "genesis"
    assert frozen["identity"] == RootIdentity.genesis().to_dict()
    assert frozen["artifact_path"] is None
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["truth_or_instruction"] is False
    assert manifest["working_world_is_revisable"] is True
    assert manifest["automatic_adoption_allowed"] is False
    assert manifest["live_store_following"] is False
    assert not (target / "XINAO_ROOT_WORLD.txt").exists()


def test_freeze_generation_copies_exact_artifact_receipt_and_source_identity(
    tmp_path: Path,
) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="seed-a-run", root_output=b"Omega one\n"
    )
    store = LogicalRootStore(tmp_path / "store")
    adopted = _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="seed-generation-one",
    )
    target = tmp_path / "frozen"

    frozen = store.freeze_current_world_seed(target)

    assert frozen["status"] == "generation"
    assert frozen["identity"] == adopted.adopted.identity.to_dict()
    assert Path(frozen["artifact_path"]).read_bytes() == b"Omega one\n"
    assert (
        frozen["source_output_identity"]
        == adopted.adopted.receipt["source"]["source_output_identity"]
    )
    assert Path(frozen["receipt_path"]).read_bytes() == adopted.adopted.receipt_path.read_bytes()
    assert validate_frozen_world_seed(target) == frozen


def test_frozen_seed_does_not_follow_later_logical_root_generation(tmp_path: Path) -> None:
    first_run = _make_committed_run(
        tmp_path, account_slot="A", run_name="seed-a-first", root_output=b"Omega one\n"
    )
    second_run = _make_committed_run(
        tmp_path,
        account_slot="C",
        run_name="seed-c-second",
        root_output=b"Omega two\n",
        legacy=True,
    )
    store = LogicalRootStore(tmp_path / "store")
    first = _adopt(
        store,
        first_run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="seed-first",
    )
    target = tmp_path / "frozen"
    frozen = store.freeze_current_world_seed(target)
    _adopt(
        store,
        second_run,
        slot="C",
        predecessor=first.adopted.identity,
        adoption_id="seed-second",
    )

    assert store.reconstruct_current().identity.generation == 2
    assert validate_frozen_world_seed(target) == frozen
    assert Path(frozen["artifact_path"]).read_bytes() == b"Omega one\n"


def test_frozen_seed_tamper_fails_closed_without_reading_live_store(tmp_path: Path) -> None:
    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="seed-tamper", root_output=b"Omega\n"
    )
    store = LogicalRootStore(tmp_path / "store")
    _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="seed-tamper",
    )
    target = tmp_path / "frozen"
    store.freeze_current_world_seed(target)
    (target / "XINAO_ROOT_WORLD.txt").write_bytes(b"tampered\n")

    with pytest.raises(LogicalRootIntegrityError) as raised:
        validate_frozen_world_seed(target)

    assert raised.value.code == "FROZEN_WORLD_SEED_REF_HASH_MISMATCH"


def test_frozen_seed_inventory_rejects_extra_or_missing_bytes(tmp_path: Path) -> None:
    genesis = tmp_path / "genesis"
    LogicalRootStore(tmp_path / "genesis-store").freeze_current_world_seed(genesis)
    (genesis / "unlisted.txt").write_text("extra\n", encoding="utf-8")

    with pytest.raises(LogicalRootIntegrityError) as extra:
        validate_frozen_world_seed(genesis)

    assert extra.value.code == "FROZEN_WORLD_SEED_INVENTORY_MISMATCH"

    run = _make_committed_run(
        tmp_path, account_slot="A", run_name="seed-inventory", root_output=b"Omega\n"
    )
    store = LogicalRootStore(tmp_path / "generation-store")
    _adopt(
        store,
        run,
        slot="A",
        predecessor=RootIdentity.genesis(),
        adoption_id="seed-inventory",
    )
    generation = tmp_path / "generation"
    store.freeze_current_world_seed(generation)
    (generation / "source_generation_receipt.json").unlink()

    with pytest.raises(LogicalRootIntegrityError) as missing:
        validate_frozen_world_seed(generation)

    assert missing.value.code in {
        "EVIDENCE_FILE_MISSING",
        "FROZEN_WORLD_SEED_INVENTORY_MISMATCH",
    }


def test_frozen_seed_inventory_rejects_hardlinked_manifest(tmp_path: Path) -> None:
    target = tmp_path / "frozen"
    LogicalRootStore(tmp_path / "store").freeze_current_world_seed(target)
    alias = tmp_path / "manifest-hardlink.json"
    os.link(target / "manifest.json", alias)

    with pytest.raises(LogicalRootIntegrityError) as raised:
        validate_frozen_world_seed(target)

    assert raised.value.code == "FROZEN_WORLD_SEED_INVENTORY_NONREGULAR"
