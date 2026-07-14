"""Run the fixed P4/P5 statistical court and persist reproducible evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from xinao.catalog.compiler import write_atomic
from xinao.validation import (
    PROTOCOL,
    FeatureObservation,
    apply_multiple_testing,
    build_split_version,
    circular_shift_permutation_pvalue,
    validate_candidate,
    validate_temporal_features,
)
from xinao.world.builder import load_draws


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def null_control() -> dict[str, Any]:
    rng = np.random.default_rng(PROTOCOL.random_seed)
    holm_families = []
    holm_rejections = 0
    bh_proportions = []
    for _ in range(400):
        pvalues = rng.uniform(size=20)
        holm, _ = apply_multiple_testing(pvalues, method="HOLM")
        bh, _ = apply_multiple_testing(pvalues, method="BH")
        holm_families.append(bool(np.any(holm)))
        holm_rejections += int(np.sum(holm))
        bh_proportions.append(float(np.mean(bh)))
    result = {
        "seed": PROTOCOL.random_seed,
        "families": 400,
        "family_size": 20,
        "holm_family_error": float(np.mean(holm_families)),
        "holm_total_rejections": holm_rejections,
        "bh_mean_rejection_proportion": float(np.mean(bh_proportions)),
    }
    if result["holm_family_error"] > 0.07 or result["bh_mean_rejection_proportion"] > 0.01:
        raise AssertionError("fixed null simulation exceeded its control envelope")
    return result


def known_signal() -> dict[str, Any]:
    pvalues = np.asarray([1e-12, 0.2, 0.4, 0.8])
    bh, bh_adjusted = apply_multiple_testing(pvalues, method="BH")
    holm, holm_adjusted = apply_multiple_testing(pvalues, method="HOLM")
    scores = np.sin(np.arange(200) / 7)
    outcomes = scores + np.cos(np.arange(200) / 11) * 0.05
    permutation = circular_shift_permutation_pvalue(scores, outcomes)
    if bh.tolist() != holm.tolist() or bh.tolist() != [True, False, False, False]:
        raise AssertionError("known signal was not isolated")
    if permutation > 0.01:
        raise AssertionError("known aligned signal failed permutation detection")
    return {
        "bh_rejected": bh.tolist(),
        "holm_rejected": holm.tolist(),
        "bh_adjusted": bh_adjusted.tolist(),
        "holm_adjusted": holm_adjusted.tolist(),
        "circular_shift_pvalue": permutation,
    }


def leakage_gate() -> dict[str, str]:
    target = datetime(2026, 7, 15, tzinfo=UTC)
    validate_temporal_features(
        [
            FeatureObservation(
                feature_name="safe-history",
                feature_timestamp=target - timedelta(milliseconds=1),
                target_open_time=target,
            )
        ]
    )
    try:
        validate_temporal_features(
            [
                FeatureObservation(
                    feature_name="future-outcome",
                    feature_timestamp=target,
                    target_open_time=target,
                )
            ]
        )
    except ValueError as exc:
        return {"safe": "PASS", "leak": "REJECTED", "reason": str(exc)}
    raise AssertionError("future leakage candidate was accepted")


def optuna_rdb(out: Path) -> dict[str, Any]:
    storage_path = out / "optuna-validation.db"
    storage_path.unlink(missing_ok=True)
    helper = Path(__file__).with_name("optuna_resume_worker.py")
    initial_report = out / "optuna-initial-process.json"
    resume_report = out / "optuna-resume-process.json"
    for phase, report in (("initial", initial_report), ("resume", resume_report)):
        subprocess.run(
            [
                sys.executable,
                str(helper),
                "--storage",
                str(storage_path),
                "--phase",
                phase,
                "--report",
                str(report),
            ],
            check=True,
            text=True,
        )
    initial = json.loads(initial_report.read_text(encoding="utf-8"))
    resumed = json.loads(resume_report.read_text(encoding="utf-8"))
    if initial["trial_count"] != 2 or resumed["trial_count"] != 5:
        raise AssertionError("Optuna RDB fresh-process resume did not complete all trials")
    if resumed["best_params"] != {"x": 3}:
        raise AssertionError("Optuna RDB resume changed the deterministic best parameters")
    if resumed["states"]["FAIL"] != 1 or resumed["states"]["PRUNED"] != 1:
        raise AssertionError("Optuna failed/pruned trial evidence is incomplete")
    return {
        "storage": str(storage_path),
        "study_name": "xinao-p5-fixed-grid",
        "initial_process": initial,
        "resume_process": resumed,
    }


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    draws = load_draws()
    split = build_split_version(draws)
    first = validate_candidate(draws)
    second = validate_candidate(draws)
    if first != second or first.output_hash is None:
        raise AssertionError("candidate validation is not repeatable")
    if first.verdict != "NO_ACTION":
        raise AssertionError("the fixed baseline candidate unexpectedly passed the mechanical gate")
    write_atomic(args.out / "dataset_split_version.json", split.model_dump(mode="json"))
    write_atomic(
        args.out / "validation_protocol_version.json",
        {**PROTOCOL.model_dump(mode="json"), "content_hash": PROTOCOL.content_hash},
    )
    write_atomic(args.out / "candidate_validation_report.json", first.model_dump(mode="json"))
    report = {
        "schema_version": "xinao.validation_court_probe.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "split_hash": split.content_hash,
        "protocol_hash": PROTOCOL.content_hash,
        "candidate_output_hash": first.output_hash,
        "candidate_verdict": first.verdict,
        "candidate_no_action_reasons": list(first.no_action_reasons),
        "null_control": null_control(),
        "known_signal": known_signal(),
        "leakage_gate": leakage_gate(),
        "optuna_rdb": optuna_rdb(args.out),
        "status": "verified",
    }
    write_atomic(args.out / "validation_court_probe_report.json", report)
    print(json.dumps({"status": "verified", "output": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
