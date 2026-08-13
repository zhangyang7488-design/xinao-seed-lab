from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping

import pytest
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_qualification import (
    TasteQualificationError,
    build_sealed_taste_outcome,
    build_taste_candidate,
    qualify_taste_candidate,
    validate_taste_candidate,
    validate_taste_qualification_receipt,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _ref(
    label: str, ordinal: int, *, rollout: str = "rollout://taste-fixture"
) -> dict[str, object]:
    payload = label.encode()
    return {
        "source_ref": f"fixture://{label}",
        "byte_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_length": len(payload),
        "rollout_locator": rollout,
        "ordinal": ordinal,
    }


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reseal(value: Mapping[str, object], hash_field: str) -> dict[str, object]:
    result = copy.deepcopy(dict(value))
    result.pop(hash_field, None)
    result[hash_field] = _canonical_hash(result)
    return result


def _prefix() -> list[dict[str, object]]:
    return [_ref("prefix-user", 1), _ref("prefix-assistant", 2)]


def _candidate() -> dict[str, object]:
    prefix = _prefix()
    return build_taste_candidate(
        baseline_prefix=prefix,
        treatment_prefix=copy.deepcopy(prefix),
        bad_continuation={"text": "bad continuation", "source": _ref("bad", 3)},
        desired_continuation={"text": "desired continuation", "source": _ref("desired", 4)},
        model_identity="gpt-5.6-sol",
        body_identity="codex-body-v1",
        config_identity="config-pin-v1",
        baseline_condition_sha256=_digest("cold-baseline"),
        treatment_condition_sha256=_digest("cold-treatment"),
    )


def _metrics(*, target_failure: int, capability_score: int = 2) -> dict[str, object]:
    names = (
        "target_failure",
        "required_tool_use",
        "bounded_action",
        "open_representation_revision",
        "world_revision",
    )
    return {
        name: {
            "score": target_failure if name == "target_failure" else capability_score,
            "evidence_refs": [_ref(f"metric-{name}-{target_failure}", 20 + index)],
        }
        for index, name in enumerate(names)
    }


def _outcome(
    candidate: Mapping[str, object],
    arm: str,
    *,
    target_failure: int,
) -> dict[str, object]:
    return build_sealed_taste_outcome(
        candidate=candidate,
        arm=arm,
        condition_sha256=str(candidate["conditions"][arm]),  # type: ignore[index]
        run_id=f"fresh-{arm}",
        fresh_run=True,
        cache_used=False,
        observed_prefix=_prefix(),
        model_identity="gpt-5.6-sol",
        body_identity="codex-body-v1",
        config_identity="config-pin-v1",
        hooks_enabled=False,
        oracle_exposed=False,
        live_retrieval_used=False,
        hot_mutations={"prompt": False, "skill": False, "agents": False},
        trajectory={"sealed": True, "ref": _ref(f"trajectory-{arm}", 100)},
        metrics=_metrics(target_failure=target_failure),
    )


def _fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    candidate = _candidate()
    return (
        candidate,
        _outcome(candidate, "baseline", target_failure=3),
        _outcome(candidate, "treatment", target_failure=1),
    )


def test_successful_qualification_is_deterministic_and_content_addressed() -> None:
    candidate, baseline, treatment = _fixture()

    receipt = qualify_taste_candidate(
        candidate=candidate,
        baseline_outcome=baseline,
        treatment_outcome=treatment,
    )
    repeated = qualify_taste_candidate(
        candidate=candidate,
        baseline_outcome=baseline,
        treatment_outcome=treatment,
    )

    unsigned_candidate = dict(candidate)
    candidate_hash = unsigned_candidate.pop("candidate_sha256")
    unsigned_receipt = dict(receipt)
    receipt_hash = unsigned_receipt.pop("receipt_sha256")
    assert candidate_hash == _canonical_hash(unsigned_candidate)
    assert receipt_hash == _canonical_hash(unsigned_receipt)
    assert receipt == repeated
    assert receipt["qualified"] is True
    assert receipt["comparisons"]["target_failure"]["improvement"] == 2  # type: ignore[index]
    assert all(
        receipt["comparisons"][name]["delta"] == 0  # type: ignore[index]
        for name in (
            "required_tool_use",
            "bounded_action",
            "open_representation_revision",
            "world_revision",
        )
    )
    assert (
        validate_taste_qualification_receipt(
            receipt,
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=treatment,
        )
        == receipt
    )


def test_candidate_rejects_resealed_prefix_twin_drift() -> None:
    candidate = _candidate()
    drifted = copy.deepcopy(candidate)
    sources = drifted["treatment_prefix"]["sources"]  # type: ignore[index]
    sources[0]["byte_sha256"] = _digest("different-prefix-bytes")
    drifted["treatment_prefix"]["prefix_sha256"] = _canonical_hash(sources)  # type: ignore[index]
    drifted = _reseal(drifted, "candidate_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        validate_taste_candidate(drifted)

    assert raised.value.reason_code == "PREFIX_MISMATCH"


def test_qualifier_rejects_resealed_observed_prefix_drift() -> None:
    candidate, baseline, treatment = _fixture()
    drifted = copy.deepcopy(treatment)
    sources = drifted["observed_prefix"]["sources"]  # type: ignore[index]
    sources[1]["byte_sha256"] = _digest("treatment-saw-other-bytes")
    drifted["observed_prefix"]["prefix_sha256"] = _canonical_hash(sources)  # type: ignore[index]
    drifted = _reseal(drifted, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=drifted,
        )

    assert raised.value.reason_code == "PREFIX_MISMATCH"


@pytest.mark.parametrize("identity", ["body", "config"])
def test_qualifier_rejects_resealed_body_or_config_drift(identity: str) -> None:
    candidate, baseline, treatment = _fixture()
    drifted = copy.deepcopy(treatment)
    drifted["identities"][identity] = f"other-{identity}"  # type: ignore[index]
    drifted = _reseal(drifted, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=drifted,
        )

    assert raised.value.reason_code == "IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    ("section", "field", "value", "reason_code"),
    [
        ("run", "fresh_run", False, "RUN_NOT_FRESH"),
        ("run", "cache_used", True, "CACHE_USED"),
        ("input_controls", "hooks_enabled", True, "HOOKS_ENABLED"),
    ],
)
def test_qualifier_rejects_nonfresh_cached_or_hooked_run(
    section: str, field: str, value: bool, reason_code: str
) -> None:
    candidate, baseline, treatment = _fixture()
    drifted = copy.deepcopy(treatment)
    drifted[section][field] = value  # type: ignore[index]
    drifted = _reseal(drifted, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=drifted,
        )

    assert raised.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("oracle", "ORACLE_LEAK"),
        ("retrieval", "LIVE_RETRIEVAL_USED"),
        ("prompt", "HOT_MUTATION"),
        ("unsealed", "TRAJECTORY_UNSEALED"),
    ],
)
def test_qualifier_rejects_oracle_retrieval_hot_mutation_or_unsealed_trajectory(
    mutation: str, reason_code: str
) -> None:
    candidate, baseline, treatment = _fixture()
    drifted = copy.deepcopy(treatment)
    if mutation == "oracle":
        drifted["input_controls"]["oracle_exposed"] = True  # type: ignore[index]
    elif mutation == "retrieval":
        drifted["input_controls"]["live_retrieval_used"] = True  # type: ignore[index]
    elif mutation == "prompt":
        drifted["input_controls"]["hot_mutations"]["prompt"] = True  # type: ignore[index]
    else:
        drifted["trajectory"]["sealed"] = False  # type: ignore[index]
    drifted = _reseal(drifted, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=drifted,
        )

    assert raised.value.reason_code == reason_code


@pytest.mark.parametrize(
    "metric",
    [
        "required_tool_use",
        "bounded_action",
        "open_representation_revision",
        "world_revision",
    ],
)
def test_qualifier_rejects_any_required_capability_degradation(metric: str) -> None:
    candidate, baseline, treatment = _fixture()
    degraded = copy.deepcopy(treatment)
    degraded["metrics"][metric]["score"] = 1  # type: ignore[index]
    degraded = _reseal(degraded, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=degraded,
        )

    assert raised.value.reason_code == "CAPABILITY_DEGRADED"


def test_qualifier_requires_strict_target_failure_reduction() -> None:
    candidate, baseline, treatment = _fixture()
    unchanged = copy.deepcopy(treatment)
    unchanged["metrics"]["target_failure"]["score"] = 3  # type: ignore[index]
    unchanged = _reseal(unchanged, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=unchanged,
        )

    assert raised.value.reason_code == "TARGET_FAILURE_NOT_REDUCED"


def test_qualifier_rejects_missing_metric_evidence_even_when_resealed() -> None:
    candidate, baseline, treatment = _fixture()
    missing = copy.deepcopy(treatment)
    missing["metrics"]["world_revision"]["evidence_refs"] = []  # type: ignore[index]
    missing = _reseal(missing, "outcome_sha256")

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=missing,
        )

    assert raised.value.reason_code == "EVIDENCE_MISSING"


def test_self_hash_tampering_fails_before_comparison() -> None:
    candidate, baseline, treatment = _fixture()
    treatment["metrics"]["target_failure"]["score"] = 0  # type: ignore[index]

    with pytest.raises(TasteQualificationError) as raised:
        qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline,
            treatment_outcome=treatment,
        )

    assert raised.value.reason_code == "HASH_MISMATCH"
