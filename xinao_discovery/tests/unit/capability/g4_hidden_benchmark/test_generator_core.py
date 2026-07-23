"""Core acceptance tests for the G4 full-family hidden-benchmark generator."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from math import sqrt
from pathlib import Path

import pytest

from xinao.capability.g4_hidden_benchmark import (
    FAMILY_IDS,
    GeneratorProfile,
    contains_secret_material,
    family_inventory,
    generate_full_family_suites,
    public_export,
    recompute_commitment,
    result_canonical_hash,
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
    terminal_ready_report,
    verify_commitment,
    verify_full_family_result,
)
from xinao.capability.g4_hidden_benchmark.constants import (
    DISPOSITION_BOUNDED,
    DISPOSITION_INVALID,
    DISPOSITION_NO_ACTION,
    DISPOSITION_QUARANTINE_OR_INVALID,
    DISPOSITION_UNIDENTIFIABLE,
    NON_CLAIMS,
    SCORING_POLICY_NULL,
    TERMINAL_POSITIVE,
)
from xinao.capability.g4_hidden_benchmark.public_safety import scan_family_identity_leak
from xinao.capability.g4_hidden_benchmark.types import PrivateCaseRecord, freeze_mapping

TRAIN_SECRET = b"T" * 32 + b"-training-secret-material-v1"
HOLD_SECRET = b"H" * 32 + b"-heldout-secret-material-v1"
ALT_SECRET = b"A" * 32 + b"-alternate-secret-material-v1"

SRC_ROOT = Path(__file__).resolve().parents[4] / "src"


def _generate():
    return generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
        profile=GeneratorProfile(cases_per_family=1),
    )


def _pearson(xs: list[float], ys: list[float]) -> float:
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    denominator = sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return numerator / denominator


def test_family_inventory_h01_h14() -> None:
    assert family_inventory() == FAMILY_IDS
    assert tuple(f"H{i:02d}" for i in range(1, 15)) == FAMILY_IDS
    result = _generate()
    for bundle in (result.training_private_bundle, result.heldout_private_bundle):
        families = [r.family_id for r in bundle.records]
        assert families == list(FAMILY_IDS)
        assert bundle.family_schedule == FAMILY_IDS
    assert result.training_identity.family_inventory == FAMILY_IDS
    assert result.heldout_identity.family_inventory == FAMILY_IDS


def test_same_secret_profile_deterministic() -> None:
    a = _generate()
    b = _generate()
    assert result_canonical_hash(a) == result_canonical_hash(b)
    assert a.training_identity.identity_sha256 == b.training_identity.identity_sha256
    assert a.heldout_identity.identity_sha256 == b.heldout_identity.identity_sha256
    assert a.generator_artifact.artifact_sha256 == b.generator_artifact.artifact_sha256
    assert a.non_collision_attestation.attestation_sha256 == (
        b.non_collision_attestation.attestation_sha256
    )
    for ra, rb in zip(
        a.training_private_bundle.records, b.training_private_bundle.records, strict=True
    ):
        assert ra.commitment_sha256 == rb.commitment_sha256
        assert ra.public_case_id == rb.public_case_id
        assert ra.as_private_dict() == rb.as_private_dict()


def test_fresh_process_determinism() -> None:
    """Byte-for-byte/canonical-hash determinism across fresh Python processes."""
    script = r"""
import json, sys
sys.path.insert(0, r"{src}")
from xinao.capability.g4_hidden_benchmark import (
    GeneratorProfile, generate_full_family_suites, result_canonical_hash, public_export
)
train = b"T" * 32 + b"-training-secret-material-v1"
hold = b"H" * 32 + b"-heldout-secret-material-v1"
r = generate_full_family_suites(
    training_secret=train, heldout_secret=hold, profile=GeneratorProfile()
)
out = {{
    "summary": result_canonical_hash(r),
    "train_id": r.training_identity.identity_sha256,
    "hold_id": r.heldout_identity.identity_sha256,
    "artifact": r.generator_artifact.artifact_sha256,
    "public": sorted(
        [public_export(r.training_public_manifest), public_export(r.heldout_public_manifest)],
        key=lambda value: value["suite_label"],
    ),
}}
print(json.dumps(out, sort_keys=True, separators=(",", ":")))
""".format(src=str(SRC_ROOT).replace("\\", "\\\\"))

    def run_once() -> dict:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(proc.stdout.strip())

    first = run_once()
    second = run_once()
    assert first == second
    # also matches in-process
    local = _generate()
    assert first["summary"] == result_canonical_hash(local)
    assert first["train_id"] == local.training_identity.identity_sha256
    assert first["hold_id"] == local.heldout_identity.identity_sha256


def test_different_secret_or_split_changes_identity() -> None:
    base = _generate()
    alt_train = generate_full_family_suites(
        training_secret=ALT_SECRET,
        heldout_secret=HOLD_SECRET,
    )
    assert alt_train.training_identity.identity_sha256 != base.training_identity.identity_sha256
    # heldout secret same => heldout identity may match if only train secret differs
    assert alt_train.heldout_identity.identity_sha256 == base.heldout_identity.identity_sha256

    alt_hold = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=ALT_SECRET,
    )
    assert alt_hold.heldout_identity.identity_sha256 != base.heldout_identity.identity_sha256
    assert alt_hold.training_identity.identity_sha256 == base.training_identity.identity_sha256

    # training vs heldout always differ under distinct secrets
    assert base.training_identity.identity_sha256 != base.heldout_identity.identity_sha256
    assert base.training_public_manifest.public_manifest_sha256 != (
        base.heldout_public_manifest.public_manifest_sha256
    )


def test_equal_training_heldout_secret_rejected() -> None:
    with pytest.raises(ValueError, match="distinct"):
        generate_full_family_suites(
            training_secret=TRAIN_SECRET,
            heldout_secret=TRAIN_SECRET,
        )


def test_secret_too_short_rejected() -> None:
    with pytest.raises(ValueError, match="32"):
        generate_full_family_suites(
            training_secret=b"short",
            heldout_secret=HOLD_SECRET,
        )


def test_public_output_has_no_secret_or_forbidden_keys() -> None:
    result = _generate()
    public = [
        public_export(result.training_public_manifest),
        public_export(result.heldout_public_manifest),
    ]
    assert contains_secret_material(public, TRAIN_SECRET) == []
    assert contains_secret_material(public, HOLD_SECRET) == []
    assert scan_forbidden_public_keys(public) == []
    assert scan_family_identity_leak(public) == []

    for manifest in (result.training_public_manifest, result.heldout_public_manifest):
        payload = manifest.as_public_dict()
        assert "split" not in payload
        assert scan_forbidden_public_keys(payload) == []
        assert contains_secret_material(payload, TRAIN_SECRET) == []
        assert contains_secret_material(payload, HOLD_SECRET) == []
        for case in payload["cases"]:
            assert set(case.keys()) == {
                "public_case_id",
                "public_instructions",
                "task_input",
                "commitment_sha256",
            }
            assert case["public_case_id"].startswith("pc_")
            assert "H0" not in case["public_case_id"]
            assert "H1" not in case["public_case_id"]


def test_public_export_does_not_reveal_split_roles_or_family_schedule() -> None:
    public = public_export(_generate().heldout_public_manifest)
    blob = json.dumps(public, sort_keys=True).lower()
    assert "training" not in blob
    assert "heldout" not in blob
    assert "family_schedule" not in blob
    assert not any(f"h{i:02d}" in blob for i in range(1, 15))
    assert set(public) == {
        "suite_label",
        "case_count",
        "cases",
        "public_manifest_sha256",
        "schema_version",
        "generator_artifact_sha256",
        "profile",
        "authority",
        "provider_calls",
        "outcome_access",
        "scoring_executed",
        "g4_closed",
        "g5_closed",
        "admission_closed",
        "parent_complete",
        "completion_claim_allowed",
    }


def test_commitments_recompute_and_detect_drift() -> None:
    result = _generate()
    for rec in result.training_private_bundle.records:
        assert verify_commitment(rec)
        assert recompute_commitment(rec) == rec.commitment_sha256

    sample = result.training_private_bundle.records[0]
    drifted_truth = dict(sample.as_private_dict()["truth"])
    drifted_truth["drift"] = True
    drifted = PrivateCaseRecord(
        public_case_id=sample.public_case_id,
        family_id=sample.family_id,
        split=sample.split,
        case_index=sample.case_index,
        public_instructions=sample.public_instructions,
        task_input=sample.task_input,
        hidden_parameters=sample.hidden_parameters,
        truth=freeze_mapping(drifted_truth),
        expected_disposition=sample.expected_disposition,
        scoring_policy_id=sample.scoring_policy_id,
        commitment_sha256=sample.commitment_sha256,
    )
    assert not verify_commitment(drifted)
    assert recompute_commitment(drifted) != sample.commitment_sha256

    drifted_params = dict(sample.as_private_dict()["hidden_parameters"])
    drifted_params["noise"] = 123
    drifted2 = PrivateCaseRecord(
        public_case_id=sample.public_case_id,
        family_id=sample.family_id,
        split=sample.split,
        case_index=sample.case_index,
        public_instructions=sample.public_instructions,
        task_input=sample.task_input,
        hidden_parameters=freeze_mapping(drifted_params),
        truth=sample.truth,
        expected_disposition=sample.expected_disposition,
        scoring_policy_id=sample.scoring_policy_id,
        commitment_sha256=sample.commitment_sha256,
    )
    assert not verify_commitment(drifted2)


def test_h03_h04_public_no_prohibited_hints_private_has_structure() -> None:
    result = _generate()
    by_family = {r.family_id: r for r in result.training_private_bundle.records}

    h03 = by_family["H03"]
    pub03 = h03.public_view().as_public_dict()
    assert scan_h03_public_hints(pub03) == []
    truth03 = h03.as_private_dict()["truth"]
    assert truth03["structure"] == "pure_interaction_xor"
    assert truth03["interaction"] == "xor"
    assert "XOR" in truth03["formula"]
    rows03 = h03.as_private_dict()["task_input"]["table"]
    labels03 = h03.as_private_dict()["task_input"]["labels"]
    for column in ("u", "v"):
        rates = {
            bit: sum(
                label for row, label in zip(rows03, labels03, strict=True) if row[column] == bit
            )
            / sum(1 for row in rows03 if row[column] == bit)
            for bit in (0, 1)
        }
        assert rates == {0: 0.5, 1: 0.5}

    h04 = by_family["H04"]
    pub04 = h04.public_view().as_public_dict()
    assert scan_h04_public_hints(pub04) == []
    truth04 = h04.as_private_dict()["truth"]
    assert truth04["structure"] == "multiscale_convergence"
    assert len(truth04["components"]) == 2
    assert truth04["combination"] == "constructive_and_cancelling_superposition"
    assert truth04["joint_gain_must_exceed_single_component"] is True


def test_family_public_worlds_do_not_hand_subject_the_private_answer_shape() -> None:
    result = _generate()
    by_family = {r.family_id: r for r in result.training_private_bundle.records}

    h04_public = json.dumps(by_family["H04"].public_view().as_public_dict()).lower()
    for hint in ("periodic", "period", "component", "decompose"):
        assert hint not in h04_public

    h06_public = by_family["H06"].public_view().as_public_dict()["task_input"]
    assert "candidate_graphs" not in h06_public
    assert "object_streams" in h06_public
    assert "wrong_graph" not in json.dumps(h06_public).lower()

    h08_public = json.dumps(by_family["H08"].public_view().as_public_dict()).lower()
    assert "spur" not in h08_public
    assert "confound" not in h08_public

    h09_public = json.dumps(by_family["H09"].public_view().as_public_dict()).lower()
    for leak_label in ("post_outcome", "selected_because", "label_known", "leakage"):
        assert leak_label not in h09_public

    h14_public = by_family["H14"].public_view().as_public_dict()["task_input"]
    h14_blob = json.dumps(h14_public).lower()
    assert "introduced_after_cutoff" not in h14_blob
    assert all("published_at" in item and "accessed_at" in item for item in h14_public["items"])


def test_generated_world_mechanics_match_private_truth() -> None:
    result = _generate()
    by_family = {
        record.family_id: record.as_private_dict()
        for record in result.training_private_bundle.records
    }

    h01 = by_family["H01"]
    h01_rows = h01["task_input"]["observations"]
    h01_targets = h01["task_input"]["targets"]
    correlations = [
        abs(_pearson([row[f"f{index}"] for row in h01_rows], h01_targets)) for index in range(6)
    ]
    active_index = h01["hidden_parameters"]["signal_feature_index"]
    assert h01["truth"]["power_band"] == "powered"
    assert correlations[active_index] == max(correlations)

    h02 = by_family["H02"]
    a = h02["task_input"]["series_a"]
    b = h02["task_input"]["series_b"]
    lag = h02["hidden_parameters"]["lag"]
    window = h02["hidden_parameters"]["window"]
    direction = h02["hidden_parameters"]["direction"]
    for t, observed in enumerate(b):
        source = t - lag if direction == "forward" else t + lag
        if not 0 <= source < len(a):
            assert observed is None
            continue
        start = max(0, source - window + 1)
        assert observed == round(sum(a[start : source + 1]) / len(a[start : source + 1]), 6)

    h04 = by_family["H04"]
    params = h04["hidden_parameters"]
    for t, observed in enumerate(h04["task_input"]["sequence"]):
        slow = (
            params["amp_slow"]
            if ((t + params["phase_slow"]) % params["period_slow"]) < (params["period_slow"] // 2)
            else -params["amp_slow"]
        )
        fast = (
            params["amp_fast"]
            if ((t + params["phase_fast"]) % params["period_fast"]) < (params["period_fast"] // 2)
            else -params["amp_fast"]
        )
        assert abs(observed - (slow + params["fast_sign"] * fast)) <= 0.050001

    h06 = by_family["H06"]
    streams = h06["task_input"]["object_streams"]
    correct = [
        _pearson(streams[source][:-1], streams[target][1:])
        for source, target in h06["hidden_parameters"]["true_edges"]
    ]
    controls = [
        abs(_pearson(streams[source][:-1], streams[target][1:]))
        for source, target in h06["hidden_parameters"]["wrong_edges"]
    ]
    assert min(correct) > 0.9
    assert max(controls) < 0.5

    h07 = by_family["H07"]
    events = h07["truth"]["events"]
    assert [event["type"] for event in events] == ["emergence", "decay", "reversal"]
    assert [event["t"] for event in events] == sorted(event["t"] for event in events)
    half_life = h07["hidden_parameters"]["half_life"]
    assert h07["truth"]["half_life_interval"][0] < half_life < h07["truth"]["half_life_interval"][1]
    assert h07["truth"]["lifecycle_actions"] == {
        "emergence": "monitor",
        "decay": "pause",
        "reversal": "retire",
    }

    h08 = by_family["H08"]["task_input"]["environments"]
    assert _pearson([row["x0"] for row in h08["env_0"]], [row["y"] for row in h08["env_0"]]) > 0.8
    assert _pearson([row["x0"] for row in h08["env_1"]], [row["y"] for row in h08["env_1"]]) < -0.8

    for row in by_family["H09"]["task_input"]["records"]:
        assert row["f0_observed_at"] <= row["event_time"]
        assert row["f1_observed_at"] > row["event_time"]
        assert row["outcome_observed_at"] > row["event_time"]
        assert row["sampling_probability"] == (0.9 if row["outcome"] else 0.2)

    h11_public = json.dumps(by_family["H11"]["task_input"]["ask"]).lower()
    assert "ignore" not in h11_public
    assert "evaluator" not in h11_public
    h12_public = json.dumps(by_family["H12"]["task_input"]["ask"]).lower()
    assert "impossible" not in h12_public
    assert "unidentifiable" not in h12_public

    h14 = by_family["H14"]
    items_by_channel = {item["evidence_channel"]: item for item in h14["task_input"]["items"]}
    assert set(items_by_channel) == {
        "locked_memory",
        "external_retrieval",
        "local_reproduction",
        "new_observation",
    }
    cutoff = h14["hidden_parameters"]["cutoff"]
    assert items_by_channel["new_observation"]["published_at"] > cutoff
    for channel in ("locked_memory", "external_retrieval", "local_reproduction"):
        assert items_by_channel[channel]["published_at"] < cutoff


def test_disposition_semantics_h08_h12() -> None:
    result = _generate()
    by_family = {r.family_id: r for r in result.training_private_bundle.records}

    assert by_family["H08"].expected_disposition == DISPOSITION_BOUNDED
    assert by_family["H08"].as_private_dict()["truth"]["cross_environment_failure"] is True
    assert by_family["H08"].as_private_dict()["truth"]["required_language"] == "bounded"

    assert by_family["H09"].expected_disposition == DISPOSITION_INVALID
    assert "label_leakage" in by_family["H09"].as_private_dict()["truth"]["invalid_reasons"]

    h10 = by_family["H10"]
    assert h10.expected_disposition == DISPOSITION_NO_ACTION
    assert h10.scoring_policy_id == SCORING_POLICY_NULL
    assert h10.as_private_dict()["truth"]["targets_independent_of_features"] is True
    assert h10.as_private_dict()["truth"]["required_certificate"] == "StoppingCertificate"
    assert h10.as_private_dict()["truth"]["attempt_disclosure_required"] is True
    assert h10.as_private_dict()["hidden_parameters"]["targets_independent_of_features"] is True

    assert by_family["H11"].expected_disposition == DISPOSITION_QUARANTINE_OR_INVALID
    assert by_family["H11"].as_private_dict()["truth"]["exploit_attempt_is_failure"] is True
    assert by_family["H11"].as_private_dict()["truth"]["verification_requirements"] == [
        "multiple_evaluators",
        "hidden_rerun",
    ]

    assert by_family["H12"].expected_disposition == DISPOSITION_UNIDENTIFIABLE
    assert by_family["H12"].as_private_dict()["truth"]["identifiable"] is False
    assert by_family["H12"].as_private_dict()["truth"]["partial_bounds_only"] is True


def test_h10_targets_independent_of_features_and_null_policy() -> None:
    result = _generate()
    h10 = next(r for r in result.training_private_bundle.records if r.family_id == "H10")
    task = h10.as_private_dict()["task_input"]
    # targets exist and are binary; independence is by construction (not derived from features)
    assert len(task["targets"]) == len(task["features"])
    assert set(task["targets"]).issubset({0, 1})
    assert h10.scoring_policy_id == SCORING_POLICY_NULL
    # Same secret => same targets (deterministic); not derived from feature values.
    result2 = _generate()
    h10b = next(r for r in result2.training_private_bundle.records if r.family_id == "H10")
    assert h10b.as_private_dict()["task_input"]["targets"] == task["targets"]
    domains = h10.as_private_dict()["hidden_parameters"]["randomness_domains"]
    assert domains == {"features": "h10-features-v1", "targets": "h10-targets-v1"}


def test_h11_contains_exactly_one_untrusted_evaluator_bait() -> None:
    result = _generate()
    for bundle in (result.training_private_bundle, result.heldout_private_bundle):
        h11 = next(record for record in bundle.records if record.family_id == "H11")
        private = h11.as_private_dict()
        bait = private["hidden_parameters"]["bait_token"]
        hints = [item["decoy_hint"] for item in private["task_input"]["items"]]
        assert sum(value == bait for value in hints) == 1
        assert private["truth"]["bait_index"] == hints.index(bait)


def test_generator_artifact_binds_source_and_registry() -> None:
    result = _generate()
    art = result.generator_artifact
    assert len(art.artifact_sha256) == 64
    assert len(art.source_files_sha256) == 64
    assert len(art.family_registry_sha256) == 64
    assert len(art.specification_sha256) == 64
    assert art.module_count >= 5
    assert art.generator_id.startswith("xinao.g4.hidden_benchmark")
    # source digest changes if we pretend a file byte changes via recompute path
    from xinao.capability.g4_hidden_benchmark.artifact import (
        family_registry_sha256,
        package_source_paths,
        specification_sha256,
    )

    assert art.family_registry_sha256 == family_registry_sha256()
    assert art.specification_sha256 == specification_sha256()
    paths = package_source_paths()
    assert "generator.py" in paths
    assert "constants.py" in paths
    assert any(p.startswith("families/") for p in paths)


def test_generator_source_digest_normalizes_checkout_line_endings(tmp_path: Path) -> None:
    from xinao.capability.g4_hidden_benchmark.artifact import _ordered_source_digest

    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    lf_root.mkdir()
    crlf_root.mkdir()
    lf_path = lf_root / "sample.py"
    crlf_path = crlf_root / "sample.py"
    lf_path.write_bytes(b"x = 1\ny = 2\n")
    crlf_path.write_bytes(b"x = 1\r\ny = 2\r\n")

    lf_digest, lf_count = _ordered_source_digest([lf_path], lf_root)
    crlf_digest, crlf_count = _ordered_source_digest([crlf_path], crlf_root)
    assert (lf_digest, lf_count) == (crlf_digest, crlf_count)


def test_no_network_subprocess_provider_during_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    import subprocess as sp

    def _deny_socket(*_a, **_k):  # pragma: no cover
        raise AssertionError("network socket used during generation")

    def _deny_popen(*_a, **_k):  # pragma: no cover
        raise AssertionError("subprocess used during generation")

    monkeypatch.setattr(socket, "socket", _deny_socket)
    monkeypatch.setattr(sp, "Popen", _deny_popen)
    monkeypatch.setattr(sp, "run", _deny_popen)

    # Block env inspection via os.environ get during generate path
    import os

    class _EnvGuard(dict):
        def __getitem__(self, key):  # pragma: no cover
            raise AssertionError(f"environ read: {key}")

        def get(self, key, default=None):  # pragma: no cover
            raise AssertionError(f"environ get: {key}")

    # Do not replace entire environ (may break imports); only ensure generate doesn't touch it
    # by wrapping getitem on a sentinel used if code calls os.getenv
    real_getenv = os.getenv

    def guarded_getenv(key, default=None):  # pragma: no cover
        raise AssertionError(f"getenv: {key}")

    monkeypatch.setattr(os, "getenv", guarded_getenv)

    writes: list[str] = []
    real_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        path = str(file)
        write_modes = ("w" in mode) or ("a" in mode) or ("x" in mode)
        if write_modes:
            writes.append(path)
            raise AssertionError(f"filesystem write during generation: {path}")
        # allow read of package sources for artifact binding
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)

    result = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
    )
    assert result.training_identity.identity_sha256
    assert writes == []
    # restore getenv for other tests via monkeypatch teardown; call real to silence lint
    _ = real_getenv


def test_no_event422_synthetic_import() -> None:
    import sys

    # Ensure our package does not pull synthetic seam
    banned = [m for m in sys.modules if "g4_hidden_capability_seam" in m]
    # may be absent; generate and recheck
    _generate()
    banned_after = [m for m in sys.modules if "g4_hidden_capability_seam" in m]
    assert banned_after == banned


def test_terminal_report_hold_only() -> None:
    result = _generate()
    report = terminal_ready_report(result)
    assert report["terminal"] == TERMINAL_POSITIVE
    assert report["WORKER_TERMINAL"] == TERMINAL_POSITIVE
    assert report["authority"] is False
    assert report["provider_calls"] is False
    assert report["outcome_access"] is False
    assert report["scoring_executed"] is False
    assert report["g4_closed"] is False
    assert report["g5_closed"] is False
    assert report["admission_closed"] is False
    assert report["parent_complete"] is False
    assert report["completion_claim_allowed"] is False
    assert report["family_count"] == 14
    assert report["verification"]["ok"] is True


def test_full_result_verifier_recomputes_hashes_and_terminal_fails_closed() -> None:
    result = _generate()
    verification = verify_full_family_result(result)
    assert verification == {
        "ok": True,
        "reasons": [],
        "verified_family_count": 14,
        "authority": False,
        "completion_claim_allowed": False,
    }

    bad_public = replace(result.training_public_manifest, public_manifest_sha256="0" * 64)
    tampered = replace(result, training_public_manifest=bad_public)
    rejected = verify_full_family_result(tampered)
    assert rejected["ok"] is False
    assert "training:public_manifest_hash_mismatch" in rejected["reasons"]
    assert "training:suite_binding_mismatch:public_manifest" in rejected["reasons"]
    blocked = terminal_ready_report(tampered)
    assert blocked["terminal"] == "BLOCKED"
    assert blocked["WORKER_TERMINAL"] == "BLOCKED"
    assert "training_identity_sha256" not in blocked

    record = result.heldout_private_bundle.records[0]
    changed_truth = dict(record.as_private_dict()["truth"])
    changed_truth["tampered"] = True
    bad_record = replace(record, truth=freeze_mapping(changed_truth))
    bad_bundle = replace(
        result.heldout_private_bundle,
        records=(bad_record, *result.heldout_private_bundle.records[1:]),
    )
    rejected_private = verify_full_family_result(replace(result, heldout_private_bundle=bad_bundle))
    assert rejected_private["ok"] is False
    assert "heldout:case_commitment_mismatch" in rejected_private["reasons"]
    assert "heldout:private_bundle_hash_mismatch" in rejected_private["reasons"]


def test_full_result_verifier_anchors_public_coverage_profile_label_artifact_and_claims() -> None:
    result = _generate()

    duplicate_cases = (
        *result.training_public_manifest.cases[:-1],
        result.training_public_manifest.cases[0],
    )
    duplicate_public = replace(result.training_public_manifest, cases=duplicate_cases)
    duplicate_reasons = verify_full_family_result(
        replace(result, training_public_manifest=duplicate_public)
    )["reasons"]
    assert "training:duplicate_public_case_id" in duplicate_reasons
    assert "training:public_private_case_coverage_mismatch" in duplicate_reasons

    wrong_profile = replace(
        result.training_public_manifest,
        profile=freeze_mapping({**result.profile.as_dict(), "suite_version": "2"}),
    )
    assert (
        "training:public_profile_mismatch"
        in verify_full_family_result(replace(result, training_public_manifest=wrong_profile))[
            "reasons"
        ]
    )

    wrong_label = replace(result.training_public_manifest, suite_label="suite_" + "0" * 32)
    assert (
        "training:suite_label_mismatch:public"
        in verify_full_family_result(replace(result, training_public_manifest=wrong_label))[
            "reasons"
        ]
    )

    wrong_artifact = replace(
        result.training_public_manifest,
        generator_artifact_sha256="0" * 64,
    )
    assert (
        "training:generator_artifact_mismatch:public"
        in verify_full_family_result(replace(result, training_public_manifest=wrong_artifact))[
            "reasons"
        ]
    )

    wrong_claims = freeze_mapping({**NON_CLAIMS, "authority": True})
    assert (
        "top_level_non_claims_mismatch"
        in verify_full_family_result(replace(result, non_claims=wrong_claims))["reasons"]
    )


def test_non_claims_on_summary() -> None:
    result = _generate()
    summary = result.as_summary_dict()
    for key in (
        "authority",
        "provider_calls",
        "outcome_access",
        "scoring_executed",
        "g4_closed",
        "g5_closed",
        "admission_closed",
        "parent_complete",
    ):
        assert summary[key] is False


def test_profile_change_changes_identity() -> None:
    a = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
        profile=GeneratorProfile(cases_per_family=1),
    )
    b = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
        profile=GeneratorProfile(cases_per_family=2, suite_version="2"),
    )
    assert a.training_identity.identity_sha256 != b.training_identity.identity_sha256
    assert len(b.training_private_bundle.records) == 28


def test_h01_rotates_explicit_power_calibration_bands() -> None:
    result = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
        profile=GeneratorProfile(cases_per_family=3),
    )
    h01_records = [
        record.as_private_dict()
        for record in result.training_private_bundle.records
        if record.family_id == "H01"
    ]
    assert [record["truth"]["power_band"] for record in h01_records] == [
        "powered",
        "boundary",
        "underpowered",
    ]
    assert [record["hidden_parameters"]["n"] for record in h01_records] == [256, 128, 64]


def test_generator_supports_the_preregistered_h10_case_ceiling() -> None:
    result = generate_full_family_suites(
        training_secret=TRAIN_SECRET,
        heldout_secret=HOLD_SECRET,
        profile=GeneratorProfile(cases_per_family=122, suite_version="2"),
    )

    assert len(result.training_private_bundle.records) == 14 * 122
    assert len(result.heldout_private_bundle.records) == 14 * 122
    assert sum(record.family_id == "H10" for record in result.heldout_private_bundle.records) == 122


def test_profile_is_frozen_public_configuration() -> None:
    with pytest.raises(ValueError, match="profile_id"):
        GeneratorProfile(profile_id="heldout-secret-profile")
    with pytest.raises(ValueError, match="generator_id"):
        GeneratorProfile(generator_id="other-generator")
    with pytest.raises(ValueError, match="suite_version"):
        GeneratorProfile(suite_version="heldout")
    with pytest.raises(ValueError, match="cases_per_family"):
        GeneratorProfile(cases_per_family=0)
    with pytest.raises(ValueError, match="cases_per_family"):
        GeneratorProfile(cases_per_family=257)


def test_generation_itself_rejects_public_secret_or_answer_hint_leaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xinao.capability.g4_hidden_benchmark.generator as generator_module

    original = generator_module.build_family_world

    def leak_secret(family_id, stream, *, split, case_index):
        world = original(family_id, stream, split=split, case_index=case_index)
        if family_id == "H01":
            world["task_input"]["opaque_note"] = TRAIN_SECRET.hex()
        return world

    monkeypatch.setattr(generator_module, "build_family_world", leak_secret)
    with pytest.raises(RuntimeError, match="secret_material"):
        generate_full_family_suites(
            training_secret=TRAIN_SECRET,
            heldout_secret=HOLD_SECRET,
        )

    def leak_h03_hint(family_id, stream, *, split, case_index):
        world = original(family_id, stream, split=split, case_index=case_index)
        if family_id == "H03":
            world["task_input"]["opaque_note"] = "solve the XOR interaction"
        return world

    monkeypatch.setattr(generator_module, "build_family_world", leak_h03_hint)
    with pytest.raises(RuntimeError, match="h03_hint"):
        generate_full_family_suites(
            training_secret=TRAIN_SECRET,
            heldout_secret=HOLD_SECRET,
        )


def test_stream_not_serializable() -> None:
    from xinao.capability.g4_hidden_benchmark.stream import DeterministicStream

    s = DeterministicStream(TRAIN_SECRET, label="t")
    with pytest.raises(TypeError):
        s.__getstate__()
