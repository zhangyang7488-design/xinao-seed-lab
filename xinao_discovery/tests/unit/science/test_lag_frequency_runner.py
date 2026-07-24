from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

import xinao.science.lag_frequency_runner as runner
from xinao.catalog.compiler import sha256_file
from xinao.science.trial_ledger import (
    append_science_trial_entry,
    load_science_trial_journal,
)
from xinao.world.builder import DrawRecord


def test_lag_predictions_use_only_prior_window_and_smallest_tie() -> None:
    outcomes = np.asarray([1, 2, 2, 3, 4, 5], dtype=np.int64)

    least, eligible = runner.lag_predictions(
        outcomes,
        window=3,
        direction="least_frequent",
    )
    most, most_eligible = runner.lag_predictions(
        outcomes,
        window=3,
        direction="most_frequent",
    )

    assert least.tolist() == [0, 0, 0, 3, 1, 1]
    assert most.tolist() == [0, 0, 0, 2, 2, 2]
    assert eligible.tolist() == [False, False, False, True, True, True]
    assert np.array_equal(eligible, most_eligible)


def test_a_default_payoff_and_concentration_are_exact() -> None:
    predictions = np.asarray([0, 1, 2], dtype=np.int64)
    targets = np.asarray([9, 1, 3], dtype=np.int64)
    eligible = np.asarray([False, True, True])

    payoffs = runner.payoff_vector(predictions, targets, eligible)

    assert payoffs.tolist() == [46.285, -1.0]
    assert runner.concentration_share(payoffs) == 1.0
    assert runner.concentration_share(np.asarray([46.285, 46.285, -1.0])) == 0.5
    assert runner.concentration_share(np.asarray([-1.0, -1.0])) == 1.0


def test_family_null_uses_finite_correction_and_higher_quantile() -> None:
    maxima = [float(value) for value in range(256)]

    pvalue, threshold, passed = runner.family_null_decision(232.0, maxima)

    assert pvalue == 25 / 257
    assert threshold == 230.0
    assert passed is True
    assert runner.family_null_decision(230.0, maxima)[2] is False


def test_moving_circular_block_has_frozen_canary() -> None:
    values = np.asarray([1, -1, 2, -2, 3, -3, 4, -4, 5, -5], dtype=np.float64)

    lower, vector_hash = runner.moving_circular_block_lower_bound(
        values,
        root_entropy=123,
        variant_index=0,
        block_length=7,
    )

    assert lower == -0.6
    assert vector_hash == "4c434fb6b60adfd2bc724327ada2b3f47c034444fc0e68de0b517a26f65cf5e8"


def test_frozen_json_material_rejects_hash_drift(tmp_path: Path) -> None:
    material = tmp_path / "material.json"
    material.write_text('{"frozen":true}\n', encoding="utf-8")

    with pytest.raises(runner.LagFrequencyRunnerError, match="sha256 mismatch"):
        runner._read_json(material, "0" * 64, "material")


@pytest.mark.parametrize(
    ("candidates", "empty_window", "expected"),
    [
        (
            [
                {
                    "support_pass": True,
                    "primary_statistic": "0.03",
                    "block_pass": True,
                    "concentration_share": "0.1",
                }
            ],
            False,
            "E2_HISTORICAL_EXPLORATORY_SUPPORT",
        ),
        (
            [
                {
                    "support_pass": False,
                    "primary_statistic": "-0.01",
                    "block_pass": False,
                    "concentration_share": "1",
                }
            ],
            False,
            "REFUTED",
        ),
        (
            [
                {
                    "support_pass": False,
                    "primary_statistic": "0.01",
                    "block_pass": True,
                    "concentration_share": "0.1",
                }
            ],
            True,
            "UNIDENTIFIABLE",
        ),
        (
            [
                {
                    "support_pass": False,
                    "primary_statistic": "0.01",
                    "block_pass": True,
                    "concentration_share": "0.1",
                }
            ],
            False,
            "UNDERPOWERED",
        ),
    ],
)
def test_terminal_label_is_single_and_ordered(
    candidates: list[dict[str, object]],
    empty_window: bool,
    expected: str,
) -> None:
    assert runner.ordered_terminal_label(candidates, any_empty_window=empty_window) == expected


def test_historical_window_means_use_inclusive_frozen_dates() -> None:
    draws = [
        DrawRecord(expect="2024001", openTime="2024-01-01 21:32:32", openCode="1,2,3,4,5,6,7"),
        DrawRecord(expect="2025001", openTime="2025-07-01 21:32:32", openCode="1,2,3,4,5,6,8"),
        DrawRecord(expect="2026001", openTime="2026-01-01 21:32:32", openCode="1,2,3,4,5,6,9"),
        DrawRecord(expect="2026182", openTime="2026-07-01 21:32:32", openCode="1,2,3,4,5,6,10"),
    ]
    split = {
        "windows": [
            {"window_id": "a", "start_date": "2024-01-01", "end_date": "2025-06-30"},
            {"window_id": "b", "start_date": "2025-07-01", "end_date": "2025-12-31"},
            {"window_id": "c", "start_date": "2026-01-01", "end_date": "2026-05-31"},
            {"window_id": "d", "start_date": "2026-06-01", "end_date": "2026-07-01"},
        ]
    }

    observed = runner.historical_window_means(
        draws=draws,
        eligible=np.asarray([True, True, True, True]),
        values=np.asarray([1.0, -1.0, 2.0, 3.0]),
        dataset_split=split,
    )

    assert observed == {"a": 1.0, "b": -1.0, "c": 2.0, "d": 3.0}


def test_full_family_scoring_runs_only_the_frozen_synthetic_path() -> None:
    start = datetime(2024, 1, 1, 21, 32, 32)
    draws = []
    for index in range(913):
        expect = "2024001" if index == 0 else "2026182" if index == 912 else f"3{index:06d}"
        special = index % 43 + 1
        draws.append(
            DrawRecord(
                expect=expect,
                openTime=(start + timedelta(days=index)).strftime("%Y-%m-%d %H:%M:%S"),
                openCode=f"44,45,46,47,48,49,{special}",
            )
        )
    variants = []
    for variant_index, (window, direction) in enumerate(
        [
            (30, "least_frequent"),
            (30, "most_frequent"),
            (90, "least_frequent"),
            (90, "most_frequent"),
            (180, "least_frequent"),
            (180, "most_frequent"),
        ]
    ):
        trial_id = f"trial-{variant_index}"
        work_key = f"work-{variant_index}"
        variants.append(
            {
                "variant_index": variant_index,
                "trial_id": trial_id,
                "work_key": work_key,
                "registration_event_id": f"{work_key}:REGISTERED",
                "equivalence_cluster_id": f"window-{window}",
                "path_kind": "PRIMARY",
                "rolling_window_draws": window,
                "direction": direction,
            }
        )
    details = {
        "episode_id": "synthetic-episode",
        "candidate_family": {
            "family_id": runner.PRIMARY_FAMILY_ID,
            "variant_order_is_frozen": True,
            "variants": variants,
        },
    }
    seed = {
        "root_entropy": {"decimal": "123"},
        "whole_pipeline_null": {
            "circular_shift_offsets": [index % 912 + 1 for index in range(256)]
        },
    }
    split = {
        "windows": [
            {"window_id": "a", "start_date": "2024-01-01", "end_date": "2025-06-30"},
            {"window_id": "b", "start_date": "2025-07-01", "end_date": "2025-12-31"},
            {"window_id": "c", "start_date": "2026-01-01", "end_date": "2026-05-31"},
            {"window_id": "d", "start_date": "2026-06-01", "end_date": "2026-07-01"},
        ]
    }

    result = runner._score_family(
        draws=draws,
        details=details,
        seed_receipt=seed,
        dataset_split=split,
    )

    assert result["draw_count"] == 913
    assert result["candidate_count"] == 6
    assert len(result["candidates"]) == 6
    assert result["whole_pipeline_null"]["replicate_count"] == 256
    assert len(result["whole_pipeline_null"]["family_maxima"]) == 256
    assert result["terminal_label"] in runner.TERMINAL_LABELS
    assert result["historical_score_accessed"] is True
    assert result["future_outcome_accessed"] is False
    assert result["research_result_claimed"] is False


def test_journal_orchestration_reuses_single_cas_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode_id = "episode-journal-test"
    anchor = tmp_path / "science_trial_ledger.json"
    anchor.write_text(
        json.dumps(
            {
                "schema_version": "xinao.science_trial_ledger.v1",
                "episode_id": episode_id,
                "append_only": True,
                "entries": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    anchor_sha = sha256_file(anchor)
    variants = []
    for variant_index, (window, direction) in enumerate(
        [
            (30, "least_frequent"),
            (30, "most_frequent"),
            (90, "least_frequent"),
            (90, "most_frequent"),
            (180, "least_frequent"),
            (180, "most_frequent"),
        ]
    ):
        trial_id = f"trial-{variant_index}"
        work_key = f"science-trial:{episode_id}:{trial_id}"
        variants.append(
            {
                "variant_index": variant_index,
                "trial_id": trial_id,
                "work_key": work_key,
                "registration_event_id": f"{work_key}:REGISTERED",
                "equivalence_cluster_id": f"window-{window}",
                "path_kind": "PRIMARY",
                "rolling_window_draws": window,
                "direction": direction,
            }
        )
    details = {
        "episode_id": episode_id,
        "candidate_family": {
            "family_id": runner.PRIMARY_FAMILY_ID,
            "variant_order_is_frozen": True,
            "variants": variants,
        },
        "trial_journal_contract": {
            "anchor_ref": str(anchor),
            "anchor_sha256": anchor_sha,
        },
    }
    seed = {
        "whole_pipeline_null": {"circular_shift_offsets": [index % 912 + 1 for index in range(256)]}
    }
    materials = {
        "details": details,
        "seed_receipt": seed,
        "protocol_pin_path": str(tmp_path / "pin.json"),
        "protocol_pin_sha256": "a" * 64,
        "protocol_details_path": str(tmp_path / "details.json"),
        "protocol_details_sha256": "b" * 64,
        "seed_receipt_path": str(tmp_path / "seed.json"),
        "seed_receipt_sha256": "c" * 64,
        "dataset_split": {},
        "dataset_split_path": str(tmp_path / "split.json"),
        "dataset_split_sha256": "2" * 64,
    }
    identities = runner._identity_rows(details, seed)
    head = load_science_trial_journal(
        anchor,
        expected_anchor_sha256=anchor_sha,
        episode_id=episode_id,
    )
    for identity in identities[:6]:
        event_id = str(identity["registration_event_id"])
        append_science_trial_entry(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
            event_id=event_id,
            work_key=str(identity["work_key"]),
            status="REGISTERED",
            family_id=str(identity["family_id"]),
            equivalence_cluster_id=str(identity["equivalence_cluster_id"]),
            path_kind=str(identity["path_kind"]),
            failure_reason=None,
            meta=runner._identity_meta(
                identity,
                materials=materials,
                world_root=tmp_path / "world",
                world_content_hash="d" * 64,
                historical_score_accessed=False,
                event_id=event_id,
            ),
            expected_entry_count=head["entry_count"],
            expected_entries_sha256=head["entries_sha256"],
            terminal=False,
        )
        head = load_science_trial_journal(
            anchor,
            expected_anchor_sha256=anchor_sha,
            episode_id=episode_id,
        )
    registered = runner.ensure_null_trials_registered(
        materials=materials,
        world_root=tmp_path / "world",
        world_content_hash="d" * 64,
    )
    monkeypatch.setattr(
        runner,
        "verify_lag_frequency_materials",
        lambda *_args, **_kwargs: materials,
    )
    monkeypatch.setattr(
        runner,
        "replay_science_episode_world",
        lambda *_args, **_kwargs: {
            "ok": True,
            "world_content_hash": "d" * 64,
        },
    )
    monkeypatch.setattr(runner, "load_draws", lambda: [])
    with pytest.raises(
        runner.LagFrequencyRunnerError,
        match="all 262 frozen identities must be RUNNING",
    ):
        runner.run_lag_frequency_protocol(
            tmp_path / "pin.json",
            expected_protocol_pin_sha256="a" * 64,
            expected_active_parent_sha256="1" * 64,
            protocol_details_path=tmp_path / "details.json",
            expected_protocol_details_sha256="b" * 64,
            seed_receipt_path=tmp_path / "seed.json",
            expected_seed_receipt_sha256="c" * 64,
            dataset_split_path=tmp_path / "split.json",
            expected_dataset_split_sha256="2" * 64,
            world_root=tmp_path / "world",
            expected_world_content_hash="d" * 64,
        )
    running = runner.transition_lag_frequency_trials(
        materials=materials,
        world_root=tmp_path / "world",
        world_content_hash="d" * 64,
        status="RUNNING",
    )
    monkeypatch.setattr(
        runner,
        "_score_family",
        lambda **_kwargs: {
            "terminal_label": "UNDERPOWERED",
            "historical_score_accessed": True,
            "future_outcome_accessed": False,
            "research_result_claimed": False,
        },
    )
    score = runner.run_lag_frequency_protocol(
        tmp_path / "pin.json",
        expected_protocol_pin_sha256="a" * 64,
        expected_active_parent_sha256="1" * 64,
        protocol_details_path=tmp_path / "details.json",
        expected_protocol_details_sha256="b" * 64,
        seed_receipt_path=tmp_path / "seed.json",
        expected_seed_receipt_sha256="c" * 64,
        dataset_split_path=tmp_path / "split.json",
        expected_dataset_split_sha256="2" * 64,
        world_root=tmp_path / "world",
        expected_world_content_hash="d" * 64,
    )
    assert (
        runner.run_lag_frequency_protocol(
            tmp_path / "pin.json",
            expected_protocol_pin_sha256="a" * 64,
            expected_active_parent_sha256="1" * 64,
            protocol_details_path=tmp_path / "details.json",
            expected_protocol_details_sha256="b" * 64,
            seed_receipt_path=tmp_path / "seed.json",
            expected_seed_receipt_sha256="c" * 64,
            dataset_split_path=tmp_path / "split.json",
            expected_dataset_split_sha256="2" * 64,
            world_root=tmp_path / "world",
            expected_world_content_hash="d" * 64,
        )
        == score
    )
    result_path = Path(score["result_ref"])
    exact_result = result_path.read_bytes()
    result_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        runner.LagFrequencyRunnerError,
        match="existing blind-score artifact conflicts",
    ):
        runner.run_lag_frequency_protocol(
            tmp_path / "pin.json",
            expected_protocol_pin_sha256="a" * 64,
            expected_active_parent_sha256="1" * 64,
            protocol_details_path=tmp_path / "details.json",
            expected_protocol_details_sha256="b" * 64,
            seed_receipt_path=tmp_path / "seed.json",
            expected_seed_receipt_sha256="c" * 64,
            dataset_split_path=tmp_path / "split.json",
            expected_dataset_split_sha256="2" * 64,
            world_root=tmp_path / "world",
            expected_world_content_hash="d" * 64,
        )
    result_path.write_bytes(exact_result)
    succeeded = runner.transition_lag_frequency_trials(
        materials=materials,
        world_root=tmp_path / "world",
        world_content_hash="d" * 64,
        status="SUCCEEDED",
        result_ref=score["result_ref"],
        result_file_sha256=score["result_file_sha256"],
        result_content_hash=score["result_content_hash"],
    )
    replayed = runner.transition_lag_frequency_trials(
        materials=materials,
        world_root=tmp_path / "world",
        world_content_hash="d" * 64,
        status="SUCCEEDED",
        result_ref=score["result_ref"],
        result_file_sha256=score["result_file_sha256"],
        result_content_hash=score["result_content_hash"],
    )

    assert registered["entry_count"] == 262
    assert running["entry_count"] == 524
    assert succeeded["entry_count"] == 786
    assert replayed["entry_count"] == 786
    terminal_entries = replayed["entries"][-262:]
    assert set(entry["status"] for entry in terminal_entries) == {"SUCCEEDED"}
    assert all(entry["meta"]["historical_score_accessed"] is True for entry in terminal_entries)


def test_failed_transition_requires_explicit_score_access_state(tmp_path: Path) -> None:
    with pytest.raises(
        runner.LagFrequencyRunnerError,
        match="explicit historical_score_accessed boolean",
    ):
        runner.transition_lag_frequency_trials(
            materials={},
            world_root=tmp_path / "world",
            world_content_hash="d" * 64,
            status="FAILED",
            failure_reason="deterministic failure",
        )
