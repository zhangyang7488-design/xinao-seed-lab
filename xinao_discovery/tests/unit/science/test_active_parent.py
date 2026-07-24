from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from xinao.science.active_parent import (
    ScienceActiveParentError,
    load_science_active_parent,
    resolve_science_carrier_path,
    validate_science_active_parent_projection,
)
from xinao.science.episode_admission import (
    ScienceEpisodeAdmissionError,
    canonical_world_measurement_bindings,
    verify_science_episode_admission_file,
)


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _projection(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    science = tmp_path / "science.txt"
    entry = tmp_path / "00.txt"
    software = tmp_path / "glue.txt"
    background = tmp_path / "background.txt"
    legacy = tmp_path / "legacy.txt"
    admission = tmp_path / "admission.txt"
    science_text = "\n".join(
        (
            "CURRENT_ACTIVE_PARENT / XINAO_SCIENCE_PROTOCOL_ACTIVE",
            "LEGACY_PARENT_G0_G8 = SUPERSEDED_AS_ACTIVE_PARENT（当前）",  # noqa: RUF001
            "XINAO_SCIENCE_EPISODE_ALLOWED",
            "ExposureInventory",
            "ProtocolPin",
            "GlobalTrialLedger",
            "knowledge_cutoff < target openTime",
        )
    )
    payload: dict[str, object] = {
        "schema_version": "xinao.science_active_parent_projection.v1",
        "sentinel": "SENTINEL:XINAO_SCIENCE_ACTIVE_PARENT_PROJECTION_V1",
        "authority": False,
        "completion_claim_allowed": False,
        "active_parent": {
            "id": "XINAO_SCIENCE_PROTOCOL_ACTIVE",
            "status": "CURRENT_ACTIVE_PARENT",
            "path": str(science),
            "sha256": _write(science, science_text),
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
                "active_parent": {"sha256": payload["active_parent"]["sha256"]},
                "legacy_parent": {"sha256": payload["legacy_parent"]["sha256"]},
                "legacy_status_preservation": {"history_rewritten": False},
            }
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(
            {
                "event_id": "parent-scope-switch",
                "kind": "action",
                "phase": "PARENT_SCOPE_SWITCH",
                "run_id": "test-science-parent-switch",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    payload["parent_scope_switch"] = {
        "status": "PERFORMED",
        "run_id": "test-science-parent-switch",
        "event_ref": f"{events}#event_id=parent-scope-switch",
        "switch_evidence_ref": str(switch_evidence),
        "switch_evidence_sha256": hashlib.sha256(switch_evidence.read_bytes()).hexdigest(),
        "history_rewritten": False,
    }
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps(payload), encoding="utf-8")
    return projection, payload


def test_live_projection_resolves_current_science_parent(tmp_path: Path) -> None:
    projection, _ = _projection(tmp_path)
    result = load_science_active_parent(projection)
    assert result["status"] == "READY"
    assert result["active_parent"]["id"] == "XINAO_SCIENCE_PROTOCOL_ACTIVE"
    assert result["legacy_parent"]["status"] == "SUPERSEDED_AS_ACTIVE_PARENT"
    assert result["science_episode_gate"]["old_g6_equivalent"] is False


def test_source_hash_drift_fails_closed(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    Path(payload["active_parent"]["path"]).write_text("drift", encoding="utf-8")
    with pytest.raises(ScienceActiveParentError, match="source hash drifted"):
        load_science_active_parent(projection)


def test_software_foundation_must_explicitly_demote_legacy_parent(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    software = Path(payload["software_foundation"]["path"])
    payload["software_foundation"]["sha256"] = _write(
        software,
        "《新澳严格数学科学研究模式——独立融合稿》.txt\nLEGACY_PARENT_G0_G8",
    )
    projection.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScienceActiveParentError, match="ambiguous parent authority"):
        load_science_active_parent(projection)


def test_old_g6_equivalence_is_rejected(tmp_path: Path) -> None:
    _, payload = _projection(tmp_path)
    payload["science_episode_gate"]["old_g6_equivalent"] = True
    with pytest.raises(ScienceActiveParentError, match="conflated with old G6"):
        validate_science_active_parent_projection(payload)


def test_pending_parent_scope_switch_event_is_rejected(tmp_path: Path) -> None:
    _, payload = _projection(tmp_path)
    payload["parent_scope_switch"]["event_ref"] = "PENDING_EVENT_APPEND"
    with pytest.raises(ScienceActiveParentError, match="has not been appended"):
        validate_science_active_parent_projection(payload)


def _protocol_pin(
    path: Path,
    active_parent_sha256: str,
    background_contract_sha256: str,
) -> str:
    episode_id = "startup-validation-1"
    world = path.with_name("world_measurement_bundle.json")
    exposure = path.with_name("exposure_inventory.json")
    ledger = path.with_name("science_trial_ledger.json")
    world_hash = _write(
        world,
        json.dumps(
            {
                "schema_version": "xinao.world_measurement_bundle.v1",
                "episode_id": episode_id,
                "status": "WORLD_BOUND",
                "knowledge_cutoff": "2026-07-01T00:00:00Z",
                "target_open_time": "2026-07-25T00:00:00Z",
                "frozen_at": "2026-07-23T23:59:00Z",
                "bindings": canonical_world_measurement_bindings(
                    background_contract_sha256=background_contract_sha256
                ),
            }
        ),
    )
    exposure_hash = _write(
        exposure,
        json.dumps(
            {
                "schema_version": "xinao.exposure_inventory.v1",
                "episode_id": episode_id,
                "status": "UNKNOWN",
                "items": [
                    {
                        "window_id": "startup-fixture",
                        "fields": ["runtime_health"],
                        "disclosure_granularity": "aggregate-only",
                        "status": "UNKNOWN",
                        "evidence_refs": ["fixture://no-outcome-access"],
                    }
                ],
            }
        ),
    )
    ledger_hash = _write(
        ledger,
        json.dumps(
            {
                "schema_version": "xinao.science_trial_ledger.v1",
                "episode_id": episode_id,
                "append_only": True,
                "entries": [],
            }
        ),
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "xinao.science_protocol_pin.v1",
                "episode_id": episode_id,
                "protocol_pin_id": "protocol-pin-1",
                "frozen_at": "2026-07-24T00:00:00Z",
                "active_parent_sha256": active_parent_sha256,
                "claim_intent": "STARTUP_VALIDATION",
                "research_question": {
                    "question_id": "startup-readiness",
                    "target": "verify current science entry without outcome access",
                    "non_goals": ["produce a research finding"],
                },
                "hypothesis": {
                    "claim": "the migrated instruments start and recover",
                    "counterexample": "one required instrument cannot execute or recover",
                },
                "null_hypothesis": {
                    "claim": "startup validation does not establish a science result",
                    "falsification_rule": "none; this is a non-research validation episode",
                },
                "world_measurement_bundle": {
                    "ref": str(world),
                    "sha256": world_hash,
                },
                "exposure_inventory": {
                    "ref": str(exposure),
                    "sha256": exposure_hash,
                    "status": "UNKNOWN",
                },
                "trial_ledger": {
                    "ref": str(ledger),
                    "sha256": ledger_hash,
                },
                "science_instrument_minimum": {
                    "world_replay": True,
                    "worker_bus": True,
                    "checkpoint": True,
                    "append_only_trial_ledger": True,
                },
                "protocol_controls": {
                    "split_id": "startup-validation-no-research-split",
                    "metrics": ["instrument_recovery"],
                    "baselines": ["pre-switch-runtime"],
                    "negative_controls": ["legacy-parent-reverse-takeover"],
                    "stopping_rule": "stop after one bounded recovery cycle",
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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _convert_to_research_pin(
    path: Path,
    *,
    claim_intent: str = "EXPLORATORY",
    power_status: str = "PINNED",
) -> dict[str, object]:
    pin = json.loads(path.read_text(encoding="utf-8"))
    pin["claim_intent"] = claim_intent
    pin.pop("startup_validation_contract")
    pin["protocol_controls"]["power_plan"] = {
        "power_plan_id": "research-power-plan-1",
        "status": power_status,
        "mde": "one predeclared meaningful effect",
        "ess_assumption": "serial dependence is explicitly adjusted",
    }
    path.write_text(json.dumps(pin), encoding="utf-8")
    return pin


def test_science_episode_admission_binds_parent_and_protocol_pin(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    background_hash = str(payload["background_contract"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    protocol_pin_hash = _protocol_pin(protocol_pin, active_hash, background_hash)
    result = verify_science_episode_admission_file(
        protocol_pin,
        expected_file_sha256=protocol_pin_hash,
        expected_active_parent_sha256=active_hash,
        projection_path=projection,
    )
    assert result["allowed"] is True
    assert result["claim_intent"] == "STARTUP_VALIDATION"
    assert result["evaluation_outcome_access"] is False
    assert result["old_g6_equivalent"] is False


def test_exposure_inventory_cannot_hide_a_contaminated_item(
    tmp_path: Path,
) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    exposure_path = tmp_path / "exposure_inventory.json"
    exposure = json.loads(exposure_path.read_text(encoding="utf-8"))
    exposure["status"] = "UNEXPOSED"
    exposure["items"][0]["status"] = "CONTAMINATED"
    exposure_path.write_text(json.dumps(exposure), encoding="utf-8")
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["exposure_inventory"]["status"] = "UNEXPOSED"
    pin["exposure_inventory"]["sha256"] = hashlib.sha256(exposure_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="item-level exposure states"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_protocol_pin_must_precede_target_outcome_time(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["frozen_at"] = "2026-07-26T00:00:00Z"
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="before the target outcome time"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_knowledge_cutoff_must_not_follow_world_freeze(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    world_path = tmp_path / "world_measurement_bundle.json"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    world["knowledge_cutoff"] = "2026-07-24T12:00:00Z"
    world_path.write_text(json.dumps(world), encoding="utf-8")
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["world_measurement_bundle"]["sha256"] = hashlib.sha256(world_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="knowledge_cutoff <= frozen_at"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_confirmatory_claim_requires_unexposed_inventory(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    exposure_path = tmp_path / "exposure_inventory.json"
    exposure = json.loads(exposure_path.read_text(encoding="utf-8"))
    exposure["status"] = "CONTAMINATED"
    exposure["items"][0]["status"] = "CONTAMINATED"
    exposure_path.write_text(json.dumps(exposure), encoding="utf-8")
    pin = _convert_to_research_pin(protocol_pin, claim_intent="CONFIRMATORY")
    pin["exposure_inventory"]["status"] = "CONTAMINATED"
    pin["exposure_inventory"]["sha256"] = hashlib.sha256(exposure_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="requires an UNEXPOSED"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_research_power_plan_rejects_unknown_status(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    _convert_to_research_pin(protocol_pin, power_status="TOTALLY_UNKNOWN")

    with pytest.raises(ScienceEpisodeAdmissionError, match="unsupported research PowerPlan"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_trial_ledger_rejects_untyped_entries(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    ledger_path = tmp_path / "science_trial_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"] = [42]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    pin = _convert_to_research_pin(protocol_pin)
    pin["trial_ledger"]["sha256"] = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="must be an object"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_trial_ledger_accepts_one_strict_immutable_entry(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    ledger_path = tmp_path / "science_trial_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"] = [
        {
            "seq": 1,
            "work_key": "science-trial-1",
            "status": "REGISTERED",
            "family_id": "bounded-family-1",
            "equivalence_cluster_id": None,
            "path_kind": "PRIMARY",
            "failure_reason": None,
            "payload_hash": "0" * 64,
            "meta": {},
            "immutable": True,
        }
    ]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    pin = _convert_to_research_pin(protocol_pin)
    pin["trial_ledger"]["sha256"] = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    result = verify_science_episode_admission_file(
        protocol_pin,
        expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
        expected_active_parent_sha256=active_hash,
        projection_path=projection,
    )
    assert result["trial_ledger"]["entry_count"] == 1


def test_legacy_or_untyped_config_cannot_masquerade_as_protocol_pin(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    legacy = tmp_path / "legacy_blueprint.json"
    legacy.write_text('{"schema_version":"legacy.g0_g8.blueprint.v1"}', encoding="utf-8")
    with pytest.raises(ScienceEpisodeAdmissionError, match="unsupported ProtocolPin schema"):
        verify_science_episode_admission_file(
            legacy,
            expected_file_sha256=hashlib.sha256(legacy.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_startup_validation_outcome_access_is_rejected(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    background_hash = str(payload["background_contract"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(protocol_pin, active_hash, background_hash)
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["evaluation_outcome_access"] = True
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")
    with pytest.raises(ScienceEpisodeAdmissionError, match="must be explicitly false"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing_outcome_field", "ProtocolPin fields do not match"),
        ("extra_top_level_authority", "ProtocolPin fields do not match"),
        ("extra_control_authority", "protocol_controls fields do not match"),
    ],
)
def test_protocol_pin_exact_schema_rejects_fail_open_authority_shapes(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    if case == "missing_outcome_field":
        pin.pop("evaluation_outcome_access")
    elif case == "extra_top_level_authority":
        pin["caller_authority_override"] = True
    else:
        pin["protocol_controls"]["caller_authority_override"] = True
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match=message):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_world_measurement_bundle_hash_drift_is_rejected(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    background_hash = str(payload["background_contract"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    protocol_pin_hash = _protocol_pin(protocol_pin, active_hash, background_hash)
    (tmp_path / "world_measurement_bundle.json").write_text("{}", encoding="utf-8")
    with pytest.raises(
        ScienceEpisodeAdmissionError,
        match="world_measurement_bundle file hash mismatch",
    ):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=protocol_pin_hash,
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


@pytest.mark.parametrize(
    "binding_name", ["dataset", "baseline", "rule", "settlement", "world_axiom"]
)
@pytest.mark.parametrize("field", ["ref", "sha256"])
def test_each_inner_world_binding_drift_is_rejected_after_outer_hashes_are_recomputed(
    tmp_path: Path,
    binding_name: str,
    field: str,
) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    background_hash = str(payload["background_contract"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(protocol_pin, active_hash, background_hash)
    world_path = tmp_path / "world_measurement_bundle.json"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    world["bindings"][binding_name][field] = (
        f"drift://{binding_name}" if field == "ref" else "0" * 64
    )
    world_path.write_text(json.dumps(world), encoding="utf-8")
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["world_measurement_bundle"]["sha256"] = hashlib.sha256(world_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(
        ScienceEpisodeAdmissionError,
        match=rf"WorldMeasurementBundle {binding_name} binding drifted",
    ):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_protocol_pin_bound_files_must_be_direct_siblings(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    background_hash = str(payload["background_contract"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(protocol_pin, active_hash, background_hash)
    nested = tmp_path / "nested"
    nested.mkdir()
    old_world = tmp_path / "world_measurement_bundle.json"
    nested_world = nested / old_world.name
    nested_world.write_bytes(old_world.read_bytes())
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["world_measurement_bundle"] = {
        "ref": str(nested_world),
        "sha256": hashlib.sha256(nested_world.read_bytes()).hexdigest(),
    }
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="direct sibling"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_hashes_must_arrive_in_exact_lowercase(tmp_path: Path) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    protocol_hash = _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    with pytest.raises(ScienceEpisodeAdmissionError, match="lowercase sha256"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=protocol_hash.upper(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_world_binding_rejects_uncontracted_fields_after_outer_hash_rebind(
    tmp_path: Path,
) -> None:
    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    world_path = tmp_path / "world_measurement_bundle.json"
    world = json.loads(world_path.read_text(encoding="utf-8"))
    world["bindings"]["dataset"]["carrier_path"] = "/unexpected"
    world_path.write_text(json.dumps(world), encoding="utf-8")
    pin = json.loads(protocol_pin.read_text(encoding="utf-8"))
    pin["world_measurement_bundle"]["sha256"] = hashlib.sha256(world_path.read_bytes()).hexdigest()
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")

    with pytest.raises(ScienceEpisodeAdmissionError, match="must contain only ref and sha256"):
        verify_science_episode_admission_file(
            protocol_pin,
            expected_file_sha256=hashlib.sha256(protocol_pin.read_bytes()).hexdigest(),
            expected_active_parent_sha256=active_hash,
            projection_path=projection,
        )


def test_carrier_resolver_is_bidirectional_for_runtime_and_mainline_refs() -> None:
    runtime = resolve_science_carrier_path("/evidence/state/projection.json")
    mainline = resolve_science_carrier_path("/mainline/01_主线入口/science.txt")
    if os.name == "nt":
        assert str(runtime).replace("\\", "/") == (
            "D:/XINAO_RESEARCH_RUNTIME/state/projection.json"
        )
        assert str(mainline).replace("\\", "/") == (
            "C:/Users/xx363/Desktop/主线/01_主线入口/science.txt"
        )
    else:
        assert runtime == Path("/evidence/state/projection.json")
        assert mainline == Path("/mainline/01_主线入口/science.txt")


def test_research_pin_survives_transactional_trial_journal_append(
    tmp_path: Path,
) -> None:
    from xinao.science.trial_ledger import (
        EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
        append_science_trial_entry,
    )

    projection, payload = _projection(tmp_path)
    active_hash = str(payload["active_parent"]["sha256"])
    protocol_pin = tmp_path / "protocol_pin.json"
    _protocol_pin(
        protocol_pin,
        active_hash,
        str(payload["background_contract"]["sha256"]),
    )
    pin = _convert_to_research_pin(protocol_pin)
    protocol_pin.write_text(json.dumps(pin), encoding="utf-8")
    protocol_hash = hashlib.sha256(protocol_pin.read_bytes()).hexdigest()
    ledger_path = tmp_path / "science_trial_ledger.json"
    anchor_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()

    initial = verify_science_episode_admission_file(
        protocol_pin,
        expected_file_sha256=protocol_hash,
        expected_active_parent_sha256=active_hash,
        projection_path=projection,
    )
    assert initial["trial_ledger"]["entry_count"] == 0

    appended = append_science_trial_entry(
        ledger_path,
        expected_anchor_sha256=anchor_hash,
        episode_id=str(pin["episode_id"]),
        event_id="science-trial-register-1",
        work_key="science-trial-1",
        status="REGISTERED",
        family_id="bounded-family-1",
        equivalence_cluster_id="variant-1",
        path_kind="PRIMARY",
        failure_reason=None,
        meta={"candidate_id": "variant-1"},
        expected_entry_count=0,
        expected_entries_sha256=EMPTY_SCIENCE_TRIAL_ENTRIES_SHA256,
        terminal=False,
    )

    assert hashlib.sha256(ledger_path.read_bytes()).hexdigest() == anchor_hash
    assert appended["entry_count"] == 1
    assert appended["replayed"] is False

    resumed = verify_science_episode_admission_file(
        protocol_pin,
        expected_file_sha256=protocol_hash,
        expected_active_parent_sha256=active_hash,
        projection_path=projection,
    )
    assert resumed["trial_ledger"]["entry_count"] == 1
    assert resumed["trial_ledger"]["entries_sha256"] == appended["entries_sha256"]
    assert resumed["trial_ledger"]["anchor_sha256"] == anchor_hash
