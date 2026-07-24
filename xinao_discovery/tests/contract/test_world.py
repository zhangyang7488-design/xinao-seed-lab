from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

import xinao.world.builder as world_builder
from xinao.canonical import canonical_sha256
from xinao.science import canonical_world_measurement_bindings, resolve_science_carrier_path
from xinao.world.builder import (
    DEFAULT_DATASET_PATH,
    LEGACY_BLUEPRINT_PATH,
    LEGACY_WORLD_ROOT,
    build_science_episode_world,
    build_world,
    replay_science_episode_world,
    replay_world,
    science_episode_world_root,
)


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _science_materials(tmp_path: Path) -> tuple[Path, str, Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    science = tmp_path / "science.txt"
    entry = tmp_path / "00.txt"
    software = tmp_path / "glue.txt"
    background = tmp_path / "background.txt"
    legacy = tmp_path / "legacy.txt"
    admission = tmp_path / "admission.txt"
    active_hash = _write(
        science,
        "\n".join(
            (
                "CURRENT_ACTIVE_PARENT / XINAO_SCIENCE_PROTOCOL_ACTIVE",
                "LEGACY_PARENT_G0_G8 = SUPERSEDED_AS_ACTIVE_PARENT（当前）",  # noqa: RUF001
                "XINAO_SCIENCE_EPISODE_ALLOWED",
                "ExposureInventory",
                "ProtocolPin",
                "GlobalTrialLedger",
                "knowledge_cutoff < target openTime",
            )
        ),
    )
    projection_payload = {
        "schema_version": "xinao.science_active_parent_projection.v1",
        "sentinel": "SENTINEL:XINAO_SCIENCE_ACTIVE_PARENT_PROJECTION_V1",
        "authority": False,
        "completion_claim_allowed": False,
        "active_parent": {
            "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
            "status": "CURRENT_ACTIVE_PARENT",
            "path": str(science),
            "sha256": active_hash,
        },
        "stable_entry": {
            "path": str(entry),
            "sha256": _write(
                entry,
                "《新澳严格数学科学研究模式——独立融合稿》.txt\n"
                "LEGACY_PARENT_G0_G8 / SUPERSEDED_AS_ACTIVE_PARENT",
            ),
        },
        "software_foundation": {
            "path": str(software),
            "sha256": _write(
                software,
                "当前主线 active-parent 是 "
                "《新澳严格数学科学研究模式——独立融合稿》.txt\n"
                "旧对象完整保留为 LEGACY_PARENT_G0_G8 的可复用仪器，"  # noqa: RUF001
                "不得反向取得当前父目标地位。",
            ),
            "relationship": "REUSABLE_INSTRUMENT_FOUNDATION_NOT_PARENT_GATE",
        },
        "background_contract": {
            "path": str(background),
            "sha256": _write(background, "background"),
        },
        "legacy_parent": {
            "path": str(legacy),
            "sha256": _write(legacy, "legacy"),
            "status": "SUPERSEDED_AS_ACTIVE_PARENT",
            "authority_scope": "LEGACY_PARENT_G0_G8",
        },
        "legacy_admission_contract": {
            "path": str(admission),
            "sha256": _write(admission, "admission"),
            "authority_scope": "LEGACY_PARENT_G0_G8",
        },
        "legacy_status_preservation": {
            "forbidden_equivalence": ["EQUIVALENT_TO_XINAO_SCIENCE_EPISODE_ALLOWED"]
        },
        "science_episode_gate": {
            "id": "XINAO_SCIENCE_EPISODE_ALLOWED",
            "first_frontier": [
                "ExposureInventory",
                "bounded_ResearchQuestion",
                "ProtocolPin",
            ],
            "old_g6_equivalent": False,
        },
        "parent_scope_switch": {},
    }
    switch_evidence = tmp_path / "parent_scope_switch.json"
    switch_evidence.write_text(
        json.dumps(
            {
                "schema_version": "xinao.parent_scope_switch.v1",
                "status": "PERFORMED",
                "active_parent": {"sha256": active_hash},
                "legacy_parent": {"sha256": projection_payload["legacy_parent"]["sha256"]},
                "legacy_status_preservation": {"history_rewritten": False},
            }
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(
            {
                "event_id": "science-parent-switch",
                "kind": "action",
                "phase": "PARENT_SCOPE_SWITCH",
                "run_id": "test-science-parent-switch",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    projection_payload["parent_scope_switch"] = {
        "status": "PERFORMED",
        "run_id": "test-science-parent-switch",
        "event_ref": f"{events}#event_id=science-parent-switch",
        "switch_evidence_ref": str(switch_evidence),
        "switch_evidence_sha256": hashlib.sha256(switch_evidence.read_bytes()).hexdigest(),
        "history_rewritten": False,
    }
    projection = tmp_path / "active_parent.json"
    projection.write_text(json.dumps(projection_payload), encoding="utf-8")
    episode_id = "episode-world-1"
    world_bundle = tmp_path / "world_measurement_bundle.json"
    world_bundle_hash = _write(
        world_bundle,
        json.dumps(
            {
                "schema_version": "xinao.world_measurement_bundle.v1",
                "episode_id": episode_id,
                "status": "WORLD_BOUND",
                "knowledge_cutoff": "2026-07-01T21:32:32Z",
                "target_open_time": "2026-07-25T00:00:00Z",
                "frozen_at": "2026-07-23T23:59:00Z",
                "bindings": canonical_world_measurement_bindings(
                    background_contract_sha256=projection_payload["background_contract"]["sha256"]
                ),
            }
        ),
    )
    exposure_inventory = tmp_path / "exposure_inventory.json"
    exposure_inventory_hash = _write(
        exposure_inventory,
        json.dumps(
            {
                "schema_version": "xinao.exposure_inventory.v1",
                "episode_id": episode_id,
                "status": "UNKNOWN",
                "items": [
                    {
                        "window_id": "startup-world-fixture",
                        "fields": ["world_replay"],
                        "disclosure_granularity": "aggregate-only",
                        "status": "UNKNOWN",
                        "evidence_refs": ["fixture://no-outcome-access"],
                    }
                ],
            }
        ),
    )
    trial_ledger = tmp_path / "science_trial_ledger.json"
    trial_ledger_hash = _write(
        trial_ledger,
        json.dumps(
            {
                "schema_version": "xinao.science_trial_ledger.v1",
                "episode_id": episode_id,
                "append_only": True,
                "entries": [],
            }
        ),
    )
    protocol_pin = tmp_path / "protocol_pin.json"
    protocol_pin.write_text(
        json.dumps(
            {
                "schema_version": "xinao.science_protocol_pin.v1",
                "episode_id": episode_id,
                "protocol_pin_id": "pin-world-1",
                "frozen_at": "2026-07-24T00:00:00Z",
                "active_parent_sha256": active_hash,
                "claim_intent": "STARTUP_VALIDATION",
                "research_question": {
                    "question_id": "world-binding",
                    "target": "verify world binding",
                    "non_goals": ["produce a scientific result"],
                },
                "hypothesis": {
                    "claim": "the world instrument replays under the new parent",
                    "counterexample": "the replay or parent binding fails",
                },
                "null_hypothesis": {
                    "claim": "world replay proves no scientific finding",
                    "falsification_rule": "none; this is startup validation only",
                },
                "world_measurement_bundle": {
                    "ref": str(world_bundle),
                    "sha256": world_bundle_hash,
                },
                "exposure_inventory": {
                    "ref": str(exposure_inventory),
                    "sha256": exposure_inventory_hash,
                    "status": "UNKNOWN",
                },
                "trial_ledger": {
                    "ref": str(trial_ledger),
                    "sha256": trial_ledger_hash,
                },
                "science_instrument_minimum": {
                    "world_replay": True,
                    "worker_bus": True,
                    "checkpoint": True,
                    "append_only_trial_ledger": True,
                },
                "protocol_controls": {
                    "split_id": "startup-validation-no-research-split",
                    "metrics": ["world_replay"],
                    "baselines": ["pre-switch-world-replay"],
                    "negative_controls": ["legacy-blueprint-current-use"],
                    "stopping_rule": "stop after one bounded replay",
                    "trial_family_id": "startup-validation-only",
                    "error_budget_ledger_id": "startup-validation-no-science-error-budget",
                    "e4_eligibility_rule": "never eligible for E4",
                    "confirmation_query_budget": {"total": 0, "remaining": 0},
                    "power_plan": {
                        "power_plan_id": "startup-validation-not-applicable",
                        "status": "NOT_APPLICABLE_STARTUP_VALIDATION",
                    },
                },
                "evaluation_outcome_access": False,
                "startup_validation_contract": {
                    "research_progress_claim_allowed": False,
                    "completion_claim_allowed": False,
                    "pre_registration_claim_allowed": False,
                    "outcome_access_allowed": False,
                    "science_trial_appends": 0,
                    "target_kind": "RUNTIME_CANARY_EVENT",
                },
            }
        ),
        encoding="utf-8",
    )
    return (
        protocol_pin,
        hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
        projection,
        active_hash,
    )


def test_legacy_blueprint_is_explicitly_scoped() -> None:
    assert "mainline_domain_research_current" in str(LEGACY_BLUEPRINT_PATH)
    assert "special-number-settlement.v1" in str(LEGACY_WORLD_ROOT)


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_science_world_binds_protocol_pin_and_independently_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path)
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    output = world_builder.science_episode_world_root("episode-world-1", protocol_hash)
    result = build_science_episode_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        output_root=output,
        correlation_id="0190f9c0-6f4c-7c00-8b22-334455667788",
        workflow_id="fixture-workflow",
        run_id="0190f9c0-6f4c-7c01-8b22-334455667788",
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )
    snapshot = result["event_matrix_snapshot"]
    assert snapshot["draw_count"] == 913
    assert snapshot["row_count"] == 913 * 2 * 49
    assert snapshot["nnz"] == 913 * 2
    assert result["world_snapshot"]["science_episode_binding"]["protocol_pin_sha256"] == (
        protocol_hash
    )
    assert result["evidence_manifest"]["config_hash"] == protocol_hash
    assert result["evidence_manifest"]["session_id"] == "episode-world-1"
    replay = replay_science_episode_world(
        output,
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )
    assert replay["ok"] is True
    assert all(replay["checks"].values())


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_science_replay_rejects_tampered_world_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path)
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    output = world_builder.science_episode_world_root("episode-world-1", protocol_hash)
    build_science_episode_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        output_root=output,
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )
    world_path = output / "world_snapshot.json"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    world["science_episode_binding"]["protocol_pin_sha256"] = "f" * 64
    world_without_hash = dict(world)
    world_without_hash.pop("content_hash")
    world["content_hash"] = canonical_sha256(world_without_hash)
    world_path.write_text(json.dumps(world), encoding="utf-8")
    replay = replay_science_episode_world(
        output,
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )
    assert replay["ok"] is False
    assert replay["checks"]["world_content_hash"] is True
    assert replay["checks"]["world_binding"] is False


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_science_replay_rejects_rebound_matrix_snapshot_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path)
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    result = build_science_episode_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )
    output = Path(result["output_root"])
    snapshot_path = output / "event_matrix_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["snapshot_ref"] = "event-matrix.attacker-rebound.v1"
    without_hash = dict(snapshot)
    without_hash.pop("content_hash")
    snapshot["content_hash"] = canonical_sha256(without_hash)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    replay = replay_science_episode_world(
        output,
        protocol_pin_path=protocol_pin,
        protocol_pin_sha256=protocol_hash,
    )

    assert replay["ok"] is False
    assert replay["checks"]["world_snapshot_binding"] is False


@pytest.mark.parametrize(
    ("episode_id", "protocol_sha", "message"),
    [
        ("../escape", "a" * 64, "safe path component"),
        ("nested/episode", "a" * 64, "safe path component"),
        ("episode", "not-a-sha", "sha256 is invalid"),
    ],
)
def test_science_world_root_rejects_unsafe_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    episode_id: str,
    protocol_sha: str,
    message: str,
) -> None:
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    with pytest.raises(ValueError, match=message):
        science_episode_world_root(episode_id, protocol_sha)


def test_science_world_root_rejects_arbitrary_requested_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    with pytest.raises(ValueError, match="canonical episode root"):
        science_episode_world_root(
            "episode-world-1",
            "a" * 64,
            requested=tmp_path / "arbitrary-output",
        )


def test_invalid_protocol_pin_writes_no_science_world_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path)
    protocol_pin.write_text('{"schema_version":"legacy.g0_g8.blueprint.v1"}', encoding="utf-8")
    output = tmp_path / "science-world-root"
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", output)
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    with pytest.raises(ValueError, match="ProtocolPin"):
        build_science_episode_world(
            dataset="verified-913",
            baseline="baseline-odds-water.v1",
            rule="special-number-rule.v1",
            protocol_pin_path=protocol_pin,
            protocol_pin_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
        )
    assert not output.exists()
    assert protocol_hash != hashlib.sha256(protocol_pin.read_bytes()).hexdigest()


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_legacy_world_remains_replayable_but_not_current_science(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_world(
        dataset="verified-913",
        baseline="baseline-odds-water.v1",
        rule="special-number-rule.v1",
        output_root=tmp_path,
    )
    assert result["evidence_manifest"]["config_authority_scope"] == "LEGACY_PARENT_G0_G8"
    assert result["evidence_manifest"]["usable_as_current_science_episode"] is False
    assert replay_world(tmp_path)["ok"] is True
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path / "science-materials")
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    with pytest.raises(ValueError, match="canonical episode root"):
        replay_science_episode_world(
            tmp_path,
            protocol_pin_path=protocol_pin,
            protocol_pin_sha256=protocol_hash,
        )


def test_wrong_world_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported dataset"):
        build_world(
            dataset="wrong",
            baseline="baseline-odds-water.v1",
            rule="special-number-rule.v1",
            output_root=tmp_path,
        )


def test_current_science_world_api_does_not_accept_caller_authority() -> None:
    build_parameters = inspect.signature(build_science_episode_world).parameters
    replay_parameters = inspect.signature(replay_science_episode_world).parameters
    for parameters in (build_parameters, replay_parameters):
        assert "active_parent_sha256" not in parameters
        assert "projection_path" not in parameters


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_late_build_failure_leaves_no_partial_episode_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path / "materials")
    science_root = tmp_path / "science-world-root"
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", science_root)
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    target = science_episode_world_root("episode-world-1", protocol_hash)

    with pytest.raises(ValueError, match="code_git_sha"):
        build_science_episode_world(
            dataset="verified-913",
            baseline="baseline-odds-water.v1",
            rule="special-number-rule.v1",
            protocol_pin_path=protocol_pin,
            protocol_pin_sha256=protocol_hash,
            code_git_sha="bad",
        )

    assert not target.exists()
    assert not list(target.parent.glob(f".{target.name}.staging-*"))


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_science_world_rebuild_replaces_the_whole_episode_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path / "materials")
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "science-world-root")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    kwargs = {
        "dataset": "verified-913",
        "baseline": "baseline-odds-water.v1",
        "rule": "special-number-rule.v1",
        "protocol_pin_path": protocol_pin,
        "protocol_pin_sha256": protocol_hash,
    }
    first = build_science_episode_world(**kwargs)
    target = Path(first["output_root"])
    (target / "stale-from-prior-build.txt").write_text("stale", encoding="utf-8")

    second = build_science_episode_world(**kwargs)

    assert Path(second["output_root"]) == target
    assert not (target / "stale-from-prior-build.txt").exists()
    assert {path.name for path in target.iterdir()} == {
        "event_matrix.jsonl",
        "event_matrix_snapshot.json",
        "evidence_manifest.json",
        "world_snapshot.json",
    }


@pytest.mark.skipif(
    not resolve_science_carrier_path(str(DEFAULT_DATASET_PATH)).is_file(),
    reason="formal dataset is not mounted",
)
def test_science_world_hashes_are_carrier_neutral_and_report_is_confined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_pin, protocol_hash, projection, _ = _science_materials(tmp_path / "materials")
    monkeypatch.setattr(world_builder, "SCIENCE_ACTIVE_PARENT_PROJECTION_PATH", projection)
    kwargs = {
        "dataset": "verified-913",
        "baseline": "baseline-odds-water.v1",
        "rule": "special-number-rule.v1",
        "protocol_pin_path": protocol_pin,
        "protocol_pin_sha256": protocol_hash,
    }
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "carrier-a")
    first = build_science_episode_world(**kwargs)
    monkeypatch.setattr(world_builder, "SCIENCE_WORLD_ROOT", tmp_path / "carrier-b")
    second = build_science_episode_world(**kwargs)

    assert (
        first["event_matrix_snapshot"]["content_hash"]
        == second["event_matrix_snapshot"]["content_hash"]
    )
    assert first["world_snapshot"]["content_hash"] == second["world_snapshot"]["content_hash"]
    with pytest.raises(ValueError, match="canonical episode report path"):
        replay_science_episode_world(
            Path(second["output_root"]),
            protocol_pin_path=protocol_pin,
            protocol_pin_sha256=protocol_hash,
            report_path=tmp_path / "escaped-report.json",
        )
    assert not (tmp_path / "escaped-report.json").exists()
