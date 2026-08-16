from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.research_sol.runtime import (
    FROZEN_AUDIT,
    WORLD_LIVE,
    ResearchSolRuntimeError,
    build_carrier_envelope,
    build_live_contact_prompt,
    build_world_pin,
    list_cognition_objects,
    open_cognition_object,
    reconcile_carrier_truth,
    seal_cognition_object,
    validate_carrier_envelope,
    validate_world_pin,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "world"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "research-sol-test@example.invalid")
    _git(repo, "config", "user.name", "Research Sol Test")
    (repo / "README.md").write_text("world\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "world")
    return repo, _git(repo, "rev-parse", "HEAD")


def _artifact_manifest(
    tmp_path: Path,
    *,
    workspace: Path,
    source_head: str,
    relative_path: str = "research/arbitrary.bin",
    raw: bytes = b"arbitrary\x00cognition\xffbytes",
    complete: bool = True,
) -> Path:
    digest = hashlib.sha256(raw).hexdigest()
    blob_root = tmp_path / "source-blobs"
    blob = blob_root / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(raw)
    manifest = {
        "schema": "test-artifact-manifest.v1",
        "captured_at": "2026-08-15T08:00:00+00:00",
        "source_workspace": str(workspace.resolve()),
        "source_head": source_head,
        "content_addressed_blob_root": str(blob_root.resolve()),
        "complete": complete,
        "entries": [
            {
                "relative_path": relative_path,
                "source_class": "ARBITRARY",
                "state": "PRESENT",
                "sha256": digest,
                "bytes": len(raw),
                "blob_path": str(blob.resolve()),
            }
        ],
    }
    path = tmp_path / "artifact_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def _world_pin(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    repo, head = _repo(tmp_path)
    manifest = _artifact_manifest(tmp_path, workspace=repo, source_head=head)
    store = tmp_path / "carrier"
    pin = build_world_pin(
        store,
        activity_id="activity-1",
        contact_id="contact-1",
        source_repo=repo,
        source_head=head,
        workspace=repo,
        overlay_manifest_path=manifest,
        required_surface_ids=[
            "repo",
            "workspace_overlay",
            "external_reality",
            "prior_objects",
        ],
        surface_catalog=[
            {
                "surface_id": "external_reality",
                "status": "UNKNOWN",
                "reason": "not sampled at the pre-contact cutoff",
            },
            {
                "surface_id": "prior_objects",
                "status": "OMITTED",
                "reason": "first contact has no prior object generation",
            },
        ],
        runtime_identity={"account_slot": "A", "run_id": "run-1"},
    )
    return pin, manifest, store


def test_live_and_audit_carrier_classes_are_sealed_and_cannot_be_smeared() -> None:
    live = build_carrier_envelope(
        WORLD_LIVE,
        network_access=True,
        fresh_session=True,
        world_surface="LINEAGE_WORLD",
        output_contract="MECHANICAL_TERMINAL_AND_ARBITRARY_ARTIFACTS",
    )
    audit = build_carrier_envelope(
        FROZEN_AUDIT,
        network_access=False,
        fresh_session=True,
        world_surface="CONTRACT_SELECTED_FROZEN_EVIDENCE",
        output_contract="OPAQUE_CANDIDATE_PAYLOAD",
    )
    assert validate_carrier_envelope(live, expected_class=WORLD_LIVE) == live
    assert validate_carrier_envelope(audit, expected_class=FROZEN_AUDIT) == audit
    assert live["envelope_id"] != audit["envelope_id"]
    assert live["shared_effect_authorized"] is False
    with pytest.raises(ResearchSolRuntimeError) as caught:
        build_carrier_envelope(
            WORLD_LIVE,
            network_access=False,
            fresh_session=True,
            world_surface="LINEAGE_WORLD",
            output_contract="MECHANICAL_TERMINAL_AND_ARBITRARY_ARTIFACTS",
        )
    assert caught.value.reason_code == "CONTACT_CLASS_ENVELOPE_MISMATCH"


def test_world_pin_is_coverage_closed_hash_bound_and_restart_idempotent(tmp_path: Path) -> None:
    pin, manifest, store = _world_pin(tmp_path)
    repo = tmp_path / "world"
    head = _git(repo, "rev-parse", "HEAD")
    repeated = build_world_pin(
        store,
        activity_id="activity-1",
        contact_id="contact-1",
        source_repo=repo,
        source_head=head,
        workspace=repo,
        overlay_manifest_path=manifest,
        required_surface_ids=[
            "repo",
            "workspace_overlay",
            "external_reality",
            "prior_objects",
        ],
        surface_catalog=[
            {
                "surface_id": "external_reality",
                "status": "UNKNOWN",
                "reason": "not sampled at the pre-contact cutoff",
            },
            {
                "surface_id": "prior_objects",
                "status": "OMITTED",
                "reason": "first contact has no prior object generation",
            },
        ],
        runtime_identity={"account_slot": "A", "run_id": "run-1"},
    )
    assert repeated == pin
    assert Path(str(pin["path"])).read_text(encoding="utf-8")
    assert validate_world_pin(store, pin_id=str(pin["pin_id"])) == pin
    coverage = pin["coverage"]
    assert isinstance(coverage, dict)
    assert {row["surface_id"] for rows in coverage.values() for row in rows} == {
        "repo",
        "workspace_overlay",
        "external_reality",
        "prior_objects",
    }


def test_world_pin_refuses_incomplete_overlay(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manifest = _artifact_manifest(tmp_path, workspace=repo, source_head=head, complete=False)
    with pytest.raises(ResearchSolRuntimeError) as caught:
        build_world_pin(
            tmp_path / "carrier",
            activity_id="activity-1",
            contact_id="contact-1",
            source_repo=repo,
            source_head=head,
            workspace=repo,
            overlay_manifest_path=manifest,
            required_surface_ids=["repo", "workspace_overlay"],
            surface_catalog=[],
        )
    assert caught.value.reason_code == "WORLD_PIN_OVERLAY_INCOMPLETE"


def test_world_pin_refuses_an_underreported_registered_surface(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path)
    manifest = _artifact_manifest(tmp_path, workspace=repo, source_head=head)
    with pytest.raises(ResearchSolRuntimeError) as caught:
        build_world_pin(
            tmp_path / "carrier",
            activity_id="activity-1",
            contact_id="contact-1",
            source_repo=repo,
            source_head=head,
            workspace=repo,
            overlay_manifest_path=manifest,
            required_surface_ids=["repo", "workspace_overlay", "runtime_reality"],
            surface_catalog=[],
        )
    assert caught.value.reason_code == "WORLD_PIN_COVERAGE_NOT_CLOSED"


def test_world_pin_validation_recomputes_the_complete_envelope(tmp_path: Path) -> None:
    pin, _, store = _world_pin(tmp_path)
    path = Path(pin["path"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["runtime_identity"]["run_id"] = "forged-run"
    path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ResearchSolRuntimeError) as failure:
        validate_world_pin(store, pin_id=str(pin["pin_id"]))
    assert failure.value.reason_code == "WORLD_PIN_DIGEST_DRIFT"


def test_arbitrary_object_is_exact_list_is_not_open_and_open_is_idempotent(
    tmp_path: Path,
) -> None:
    pin, manifest, store = _world_pin(tmp_path)
    generation = seal_cognition_object(
        store / "objects",
        artifact_manifest_path=manifest,
        contact_id="contact-1",
        world_pin_id=str(pin["pin_id"]),
        lineage_id="lineage-live",
        turn_id="turn-1",
    )
    repeated = seal_cognition_object(
        store / "objects",
        artifact_manifest_path=manifest,
        contact_id="contact-1",
        world_pin_id=str(pin["pin_id"]),
        lineage_id="lineage-live",
        turn_id="turn-1",
    )
    assert repeated == generation
    rows = list_cognition_objects(store / "objects")
    assert rows == [
        {
            "object_id": generation["object_id"],
            "root_digest": generation["root_digest"],
            "file_count": 1,
            "byte_count": len(b"arbitrary\x00cognition\xffbytes"),
            "generated_by": generation["generated_by"],
        }
    ]
    assert not (store / "objects" / "opens").exists()
    receipt = open_cognition_object(
        store / "objects",
        object_id=str(generation["object_id"]),
        contact_id="contact-2",
        world_pin_id="pin-2",
        requested_paths=["research/arbitrary.bin"],
        destination_root=tmp_path / "opened",
    )
    repeated_receipt = open_cognition_object(
        store / "objects",
        object_id=str(generation["object_id"]),
        contact_id="contact-2",
        world_pin_id="pin-2",
        requested_paths=["research/arbitrary.bin"],
        destination_root=tmp_path / "opened",
    )
    assert repeated_receipt == receipt
    opened = Path(receipt["opened"][0]["destination"])
    assert opened.read_bytes() == b"arbitrary\x00cognition\xffbytes"


def test_concurrent_identical_object_seal_is_one_write_once_generation(tmp_path: Path) -> None:
    pin, manifest, store = _world_pin(tmp_path)

    def seal() -> dict[str, object]:
        return seal_cognition_object(
            store / "objects",
            artifact_manifest_path=manifest,
            contact_id="contact-1",
            world_pin_id=str(pin["pin_id"]),
            lineage_id="lineage-live",
            turn_id="turn-1",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        generations = list(pool.map(lambda _index: seal(), range(32)))
    assert len({str(value["object_id"]) for value in generations}) == 1
    assert len(list((store / "objects" / "generations").glob("*.json"))) == 1


def test_cognition_source_blob_path_is_bound_to_declared_store(tmp_path: Path) -> None:
    pin, manifest_path, store = _world_pin(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    escaped = tmp_path / "outside.bin"
    escaped.write_bytes(b"arbitrary\x00cognition\xffbytes")
    manifest["entries"][0]["blob_path"] = str(escaped)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ResearchSolRuntimeError) as failure:
        seal_cognition_object(
            store / "objects",
            artifact_manifest_path=manifest_path,
            contact_id="contact-1",
            world_pin_id=str(pin["pin_id"]),
            lineage_id="lineage-live",
            turn_id="turn-1",
        )
    assert failure.value.reason_code == "COGNITION_SOURCE_BLOB_PATH_ESCAPE"


def test_object_open_fails_closed_on_tree_tamper_and_path_traversal(tmp_path: Path) -> None:
    pin, manifest, store = _world_pin(tmp_path)
    generation = seal_cognition_object(
        store / "objects",
        artifact_manifest_path=manifest,
        contact_id="contact-1",
        world_pin_id=str(pin["pin_id"]),
        lineage_id="lineage-live",
        turn_id="turn-1",
    )
    with pytest.raises(ResearchSolRuntimeError) as traversal:
        open_cognition_object(
            store / "objects",
            object_id=str(generation["object_id"]),
            contact_id="contact-2",
            world_pin_id="pin-2",
            requested_paths=["../escape"],
            destination_root=tmp_path / "opened",
        )
    assert traversal.value.reason_code == "OBJECT_PATH_INVALID"
    tree = store / "objects" / str(generation["tree_manifest_path"])
    tree.write_text(tree.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ResearchSolRuntimeError) as tamper:
        open_cognition_object(
            store / "objects",
            object_id=str(generation["object_id"]),
            contact_id="contact-2",
            world_pin_id="pin-2",
            requested_paths=["research/arbitrary.bin"],
            destination_root=tmp_path / "opened",
        )
    assert tamper.value.reason_code == "COGNITION_TREE_MANIFEST_DIGEST_DRIFT"


def test_object_open_recomputes_birth_provenance_identity(tmp_path: Path) -> None:
    pin, manifest, store = _world_pin(tmp_path)
    generation = seal_cognition_object(
        store / "objects",
        artifact_manifest_path=manifest,
        contact_id="contact-1",
        world_pin_id=str(pin["pin_id"]),
        lineage_id="lineage-live",
        turn_id="turn-1",
    )
    generation_path = Path(generation["path"])
    stored = json.loads(generation_path.read_text(encoding="utf-8"))
    stored["generated_by"]["world_pin_id"] = "forged-pin"
    generation_path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ResearchSolRuntimeError) as failure:
        open_cognition_object(
            store / "objects",
            object_id=str(generation["object_id"]),
            contact_id="contact-2",
            world_pin_id="pin-2",
            requested_paths=["research/arbitrary.bin"],
            destination_root=tmp_path / "opened",
        )
    assert failure.value.reason_code == "COGNITION_OBJECT_DIGEST_DRIFT"


@pytest.mark.parametrize(
    ("job_state", "child", "lease", "phase", "action", "release"),
    [
        ("PRESENT_NONEMPTY", "ALIVE", "BOUND", "TURN_RUNNING", "WAIT_FOR_CARRIER", False),
        ("UNKNOWN", "UNKNOWN", "BOUND", "TURN_RUNNING", "HOLD_UNKNOWN", False),
        ("PRESENT_EMPTY", "DEAD", "BOUND", "TURN_RUNNING", "SEAL_AND_RELEASE", False),
        ("PRESENT_EMPTY", "DEAD", "BOUND", "TERMINAL", "SEAL_AND_RELEASE", True),
        ("ABSENT", "DEAD", "RELEASED", "TERMINAL", "ALREADY_TERMINAL", False),
    ],
)
def test_restart_equivalent_terminal_law(
    job_state: str,
    child: str,
    lease: str,
    phase: str,
    action: str,
    release: bool,
) -> None:
    outcome = reconcile_carrier_truth(
        job_state=job_state,
        child_liveness=child,
        lease_status=lease,
        turn_phase=phase,
    )
    assert outcome["action"] == action
    assert outcome["release_allowed"] is release
    assert outcome["duplicate_launch_allowed"] is (lease == "RELEASED" and phase == "TERMINAL")
    if phase == "TERMINAL":
        assert outcome["next_turn_phase"] == "TERMINAL"


def test_terminal_law_holds_contradictory_job_and_pid_truth() -> None:
    outcome = reconcile_carrier_truth(
        job_state="ABSENT",
        child_liveness="ALIVE",
        lease_status="BOUND",
        turn_phase="TURN_RUNNING",
    )
    assert outcome["action"] == "HOLD_CONTRADICTORY"
    assert outcome["release_allowed"] is False
    assert outcome["duplicate_launch_allowed"] is False


def test_live_prompt_is_thin_delivery_not_a_research_workflow(tmp_path: Path) -> None:
    pin, _, _ = _world_pin(tmp_path)
    prompt = build_live_contact_prompt(
        activity_id="activity-1",
        contact_id="contact-1",
        world_pin=pin,
        object_map_path=tmp_path / "objects.json",
        object_open_command="python research_sol_runtime.py open-object ...",
    )
    assert "You own representation, question formation, research method" in prompt
    assert "hypothesis" not in prompt.casefold()
    assert "soft attractor" not in prompt.casefold()
    assert "cognition phenotype" not in prompt.casefold()
    assert "selective-invariance" not in prompt.casefold()
    assert "Shared production/effect/adoption" in prompt
    assert str(pin["pin_id"]) in prompt
