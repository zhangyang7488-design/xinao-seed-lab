from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import sha256_file
from xinao.science.day1_portfolio import (
    Day1PolicyCompilation,
    SpecialNumberObservation,
    build_day1_policy_compilation,
)
from xinao.science.multipolicy_episode import (
    _artifact_manifest,
    build_episode_package,
    verify_episode_package,
)
from xinao.science.portfolio import PolicyRole


def observations(count: int = 220) -> tuple[SpecialNumberObservation, ...]:
    start = datetime(2026, 1, 1, 13, 32, 32, tzinfo=UTC)
    return tuple(
        SpecialNumberObservation(
            expect=f"2026{index + 1:03d}",
            open_time=start + timedelta(days=index),
            special_number=(index * index * 3 + index * 17 + (index // 7) * 5) % 49 + 1,
            source_row_hash=canonical_sha256(["row", index]),
        )
        for index in range(count)
    )


def build_package(tmp_path, *, synthetic: bool):
    root = tmp_path / ("synthetic" if synthetic else "live")
    root.mkdir()
    source = root / "information_snapshot.v1.json"
    source_payload = {"schema_version": "fixture.v1", "outcome_access": False}
    source_payload["content_hash"] = canonical_sha256(source_payload)
    source.write_text(
        json.dumps(source_payload) + "\n",
        encoding="utf-8",
    )
    history = observations()
    cutoff = history[-1].open_time + timedelta(seconds=1)
    if not synthetic:
        cutoff = cutoff.replace(microsecond=123456)
    target_open = history[-1].open_time + timedelta(days=1)
    result = build_episode_package(
        output_dir=root,
        episode_id="episode.synthetic.v1" if synthetic else "episode.live.v1",
        evidence_class=("EXECUTION_RECOVERY_ONLY" if synthetic else "PROSPECTIVE_EXPERIMENTAL"),
        observations=history,
        source_snapshot_ref=source.name,
        source_snapshot_sha256=sha256_file(source),
        source_captured_at=cutoff,
        active_parent_ref="active-parent.current",
        active_parent_sha256="a" * 64,
        source_contract_ref="macaujc-source-authority-contract.v1",
        source_contract_sha256="b" * 64,
        target_ref=("synthetic/period/1" if synthetic else "macaujc2/expect/2026221"),
        target_open_time=target_open,
        knowledge_cutoff=cutoff,
        freeze_deadline=target_open - timedelta(hours=1),
        horizon_draws=1,
        frozen_at=(history[-1].open_time + timedelta(minutes=10)).replace(
            microsecond=654321 if not synthetic else 0
        ),
        synthetic_outcome_number=17 if synthetic else None,
    )
    return root, result


def test_synthetic_package_proves_settle_all_without_science_promotion(tmp_path) -> None:
    root, result = build_package(tmp_path, synthetic=True)
    readback = verify_episode_package(
        root,
        expected_manifest_sha256=result["manifest_sha256"],
    )

    assert result["state"] == "SYNTHETIC_SETTLE_ALL_VERIFIED"
    assert readback["ok"] is True
    assert readback["eligible_frozen_count"] == 4
    assert readback["freeze_coverage"] == "1.0000"
    assert readback["settlement_set_hash"] is not None
    assert readback["claim_grade"] == "NO_SCIENTIFIC_GRADE_FROM_SYNTHETIC"
    assert readback["real_money_authorized"] is False
    assert readback["parent_complete"] is False


def test_live_package_stops_before_outcome_and_settlement_access(tmp_path) -> None:
    root, result = build_package(tmp_path, synthetic=False)
    readback = verify_episode_package(
        root,
        expected_manifest_sha256=result["manifest_sha256"],
    )

    assert result["state"] == "FROZEN_AWAITING_VERIFIED_OUTCOME"
    assert not (root / "settlement_set.v1.json").exists()
    assert readback["settlement_set_hash"] is None
    assert readback["claim_grade"] == "E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME"
    assert readback["parent_complete"] is False


def test_package_accepts_owner_supplied_external_policy_compilation(tmp_path) -> None:
    root = tmp_path / "external"
    root.mkdir()
    source = root / "information_snapshot.v1.json"
    source_payload = {"schema_version": "fixture.v1", "outcome_access": False}
    source_payload["content_hash"] = canonical_sha256(source_payload)
    source.write_text(json.dumps(source_payload) + "\n", encoding="utf-8")
    history = observations()
    cutoff = history[-1].open_time + timedelta(seconds=1)
    target_open = history[-1].open_time + timedelta(days=1)
    compiled = build_day1_policy_compilation(
        history,
        target_ref="macaujc2/expect/2026221",
        knowledge_cutoff=cutoff,
        horizon_draws=1,
    )
    substantive = next(item for item in compiled.policies if item.role == PolicyRole.SUBSTANTIVE)
    external = substantive.model_copy(
        update={
            "policy_ref": "policy.external.owner-adopted-ai.v1",
            "semantic_config": {
                **substantive.semantic_config,
                "origin": "owner-adopted-external-candidate",
            },
            "content_hash": None,
        }
    ).with_content_hash()
    policies = tuple(
        sorted(
            (
                external if item.role == PolicyRole.SUBSTANTIVE else item
                for item in compiled.policies
            ),
            key=lambda item: item.policy_ref,
        )
    )
    decisions = tuple(
        sorted(
            (
                item.model_copy(update={"policy_ref": external.policy_ref})
                if item.policy_ref == substantive.policy_ref
                else item
                for item in compiled.decisions
            ),
            key=lambda item: item.policy_ref,
        )
    )
    external_compilation = Day1PolicyCompilation(
        **{
            **compiled.model_dump(mode="python", exclude={"policies", "decisions", "content_hash"}),
            "policies": policies,
            "decisions": decisions,
        }
    ).with_content_hash()
    result = build_episode_package(
        output_dir=root,
        episode_id="episode.external.v1",
        evidence_class="PROSPECTIVE_EXPERIMENTAL",
        observations=history,
        source_snapshot_ref=source.name,
        source_snapshot_sha256=sha256_file(source),
        source_captured_at=cutoff,
        active_parent_ref="active-parent.current",
        active_parent_sha256="a" * 64,
        source_contract_ref="macaujc-source-authority-contract.v1",
        source_contract_sha256="b" * 64,
        target_ref="macaujc2/expect/2026221",
        target_open_time=target_open,
        knowledge_cutoff=cutoff,
        freeze_deadline=target_open - timedelta(hours=1),
        horizon_draws=1,
        frozen_at=history[-1].open_time + timedelta(minutes=10),
        policy_compilation=external_compilation,
    )
    readback = verify_episode_package(
        root,
        expected_manifest_sha256=result["manifest_sha256"],
    )

    assert readback["ok"] is True
    active_policy_refs = {
        item["policy_ref"]
        for item in json.loads(
            (root / "active_set.v1.json").read_text(encoding="utf-8")
        )["policies"]
    }
    assert external.policy_ref in active_policy_refs


def test_package_rejects_external_compilation_history_rebinding(tmp_path) -> None:
    root = tmp_path / "rebound"
    root.mkdir()
    source = root / "information_snapshot.v1.json"
    source_payload = {"schema_version": "fixture.v1", "outcome_access": False}
    source_payload["content_hash"] = canonical_sha256(source_payload)
    source.write_text(json.dumps(source_payload) + "\n", encoding="utf-8")
    history = observations()
    cutoff = history[-1].open_time + timedelta(seconds=1)
    compiled = build_day1_policy_compilation(
        history,
        target_ref="macaujc2/expect/2026221",
        knowledge_cutoff=cutoff,
        horizon_draws=1,
    )
    rebound = compiled.model_copy(
        update={"history_identity_hash": "f" * 64, "content_hash": None}
    ).with_content_hash()

    with pytest.raises(ValueError, match="target, cutoff, and history"):
        build_episode_package(
            output_dir=root,
            episode_id="episode.rebound.v1",
            evidence_class="PROSPECTIVE_EXPERIMENTAL",
            observations=history,
            source_snapshot_ref=source.name,
            source_snapshot_sha256=sha256_file(source),
            source_captured_at=cutoff,
            active_parent_ref="active-parent.current",
            active_parent_sha256="a" * 64,
            source_contract_ref="macaujc-source-authority-contract.v1",
            source_contract_sha256="b" * 64,
            target_ref="macaujc2/expect/2026221",
            target_open_time=history[-1].open_time + timedelta(days=1),
            knowledge_cutoff=cutoff,
            freeze_deadline=history[-1].open_time + timedelta(hours=23),
            horizon_draws=1,
            frozen_at=history[-1].open_time + timedelta(minutes=10),
            policy_compilation=rebound,
        )


def test_fresh_readback_rejects_artifact_tampering(tmp_path) -> None:
    root, _ = build_package(tmp_path, synthetic=True)
    target = root / "active_set.v1.json"
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_episode_package(root)


def test_fresh_readback_rejects_self_consistent_compilation_rebinding(tmp_path) -> None:
    root, _ = build_package(tmp_path, synthetic=True)
    target = root / "day1_policy_compilation.v1.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["target_ref"] = "synthetic/period/rebound"
    payload.pop("content_hash")
    payload["content_hash"] = canonical_sha256(payload)
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    (root / "multipolicy_episode_manifest.v1.json").write_text(
        json.dumps(_artifact_manifest(root), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="policy compilation"):
        verify_episode_package(root)


def test_external_manifest_pin_rejects_a_fully_resealed_package(tmp_path) -> None:
    root, result = build_package(tmp_path, synthetic=True)
    target = root / "trial_ledger_frozen_head.v1.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["journal_file_sha256"] = "f" * 64
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    (root / "multipolicy_episode_manifest.v1.json").write_text(
        json.dumps(_artifact_manifest(root), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="external pin"):
        verify_episode_package(
            root,
            expected_manifest_sha256=result["manifest_sha256"],
        )
