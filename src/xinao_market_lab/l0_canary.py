from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import binomtest

from .inputs import (
    InputLayout,
    assert_snapshot_unchanged,
    audit_inputs_p2,
    build_snapshot_manifest,
    canonical_json_bytes,
    sha256_file,
    write_json_atomic,
)
from .models import Draw

CANONICAL_INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
CANONICAL_EVIDENCE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab")
MODEL_IDS = (
    "H1_expanding_frequency",
    "H2_rolling_100_frequency",
    "H3_lag1_markov",
)
POOL_SIZE = 49
TOP_K = 5
SMOOTHING_ALPHA = 1.0
CONFIDENCE_LEVEL = 0.95


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _source_fingerprint() -> str:
    project_root = Path(__file__).resolve().parents[2]
    paths = [
        project_root / "pyproject.toml",
        project_root / "uv.lock",
        project_root / "README.md",
        project_root / "src" / "xinao_market_lab" / "cli.py",
        project_root / "src" / "xinao_market_lab" / "inputs.py",
        project_root / "src" / "xinao_market_lab" / "models.py",
        Path(__file__).resolve(),
    ]
    rows = [
        {
            "relative_path": path.relative_to(project_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


def _artifact_hashes(run_dir: Path, names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": name,
            "size_bytes": (run_dir / name).stat().st_size,
            "sha256": sha256_file(run_dir / name),
        }
        for name in names
    ]


def walk_forward_windows(
    sample_size: int,
    *,
    initial_train: int = 180,
    test_size: int = 20,
    step: int = 20,
) -> tuple[dict[str, int], ...]:
    if min(sample_size, initial_train, test_size, step) <= 0:
        raise ValueError("walk-forward sizes must be positive")
    windows: list[dict[str, int]] = []
    train_end = initial_train
    while train_end + test_size <= sample_size:
        windows.append(
            {
                "cycle": len(windows) + 1,
                "train_start": 0,
                "train_end_exclusive": train_end,
                "test_start": train_end,
                "test_end_exclusive": train_end + test_size,
            }
        )
        train_end += step
    return tuple(windows)


def _smoothed_frequency(values: list[int], *, alpha: float = SMOOTHING_ALPHA) -> np.ndarray:
    counts = np.full(POOL_SIZE, alpha, dtype=float)
    for value in values:
        counts[value - 1] += 1.0
    return counts / counts.sum()


def _markov_predictor(train: list[int], *, alpha: float = SMOOTHING_ALPHA) -> Callable[[int], np.ndarray]:
    transitions: dict[int, np.ndarray] = defaultdict(lambda: np.full(POOL_SIZE, alpha, dtype=float))
    for previous, current in pairwise(train):
        transitions[previous][current - 1] += 1.0
    fallback = _smoothed_frequency(train, alpha=alpha)

    def predict(previous: int) -> np.ndarray:
        row = transitions.get(previous)
        if row is None:
            return fallback
        return row / row.sum()

    return predict


def _top_k(probabilities: np.ndarray, k: int = TOP_K) -> list[int]:
    return [
        index + 1
        for index in sorted(
            range(POOL_SIZE),
            key=lambda index: (-float(probabilities[index]), index),
        )[:k]
    ]


def _score(probabilities: np.ndarray, actual: int) -> tuple[float, float]:
    actual_index = actual - 1
    log_loss = -math.log(float(probabilities[actual_index]))
    target = np.zeros(POOL_SIZE, dtype=float)
    target[actual_index] = 1.0
    brier = float(np.square(probabilities - target).sum())
    return log_loss, brier


def _bh_adjust(rows: list[dict[str, Any]], alpha: float = 0.05) -> None:
    ordered = sorted(range(len(rows)), key=lambda index: rows[index]["top5_p_value_one_sided"])
    running = 1.0
    adjusted: dict[int, float] = {}
    for reverse_rank, index in enumerate(reversed(ordered), start=1):
        rank = len(rows) - reverse_rank + 1
        raw = float(rows[index]["top5_p_value_one_sided"])
        running = min(running, raw * len(rows) / rank)
        adjusted[index] = running
    rejected_through = 0
    for rank, index in enumerate(ordered, start=1):
        if float(rows[index]["top5_p_value_one_sided"]) <= alpha * rank / len(rows):
            rejected_through = rank
    for rank, index in enumerate(ordered, start=1):
        rows[index]["top5_p_value_bh"] = adjusted[index]
        rows[index]["top5_bh_reject"] = rank <= rejected_through


def hypothesis_register() -> dict[str, Any]:
    return {
        "schema_version": "xinao.biz_l0.hypothesis_register.v1",
        "question_lock": "A_next_draw_judgment",
        "target": "next unseen canonical draw special number (49-class categorical)",
        "sample_policy": "last 300 canonical lineage-v2 draws by strictly increasing open_time",
        "max_hypotheses": 3,
        "registered_count": 3,
        "shared": {
            "smoothing": "symmetric Dirichlet/Laplace alpha=1 fixed before scoring",
            "walk_forward": "expanding train=180, test=20, step=20; six OOS cycles",
            "primary_score": "mean multiclass log loss versus uniform 1/49",
            "secondary_scores": [
                "multiclass Brier score versus uniform 1/49",
                "top-5 hit rate versus exact 5/49 baseline",
            ],
            "uncertainty": "two-sided 95% exact Clopper-Pearson interval for OOS top-5 hit rate",
            "multiplicity": "Benjamini-Hochberg across the three registered top-5 tests",
        },
        "hypotheses": [
            {
                "id": MODEL_IDS[0],
                "method": "expanding empirical categorical frequency",
                "information": "all canonical draws in the current training prefix",
                "prediction": "Dirichlet-smoothed probability for each special number 1..49",
            },
            {
                "id": MODEL_IDS[1],
                "method": "rolling empirical categorical frequency",
                "information": "last 100 canonical draws inside the current training prefix",
                "prediction": "Dirichlet-smoothed probability for each special number 1..49",
            },
            {
                "id": MODEL_IDS[2],
                "method": "first-order categorical Markov",
                "information": "training-prefix transition counts conditioned on the latest observed special",
                "prediction": "Dirichlet-smoothed transition probability for each special number 1..49",
            },
        ],
        "promotion_gate": {
            "all_required_per_model": [
                "mean OOS log loss lower than uniform",
                "mean OOS Brier score lower than uniform",
                "log loss lower than uniform in at least five of six cycles",
                "top-5 exact 95% interval lower bound above 5/49",
                "top-5 one-sided test remains significant after BH correction",
            ],
            "meaning": "research expansion only; never a betting or edge claim",
        },
    }


def evaluate_special_models(
    draws: tuple[Draw, ...],
    *,
    sample_size: int = 300,
    initial_train: int = 180,
    test_size: int = 20,
    step: int = 20,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if len(draws) < sample_size:
        raise ValueError(f"need at least {sample_size} canonical draws, got {len(draws)}")
    sample = draws[-sample_size:]
    specials = [draw.special for draw in sample]
    windows = walk_forward_windows(
        sample_size,
        initial_train=initial_train,
        test_size=test_size,
        step=step,
    )
    if len(windows) < 5:
        raise ValueError(f"need at least five OOS cycles, got {len(windows)}")

    baseline = np.full(POOL_SIZE, 1.0 / POOL_SIZE, dtype=float)
    baseline_log_loss, baseline_brier = _score(baseline, 1)
    predictions: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []

    for window in windows:
        train = specials[window["train_start"] : window["train_end_exclusive"]]
        fixed = {
            MODEL_IDS[0]: _smoothed_frequency(train),
            MODEL_IDS[1]: _smoothed_frequency(train[-100:]),
        }
        markov = _markov_predictor(train)
        for model_id in MODEL_IDS:
            cycle_scores: list[dict[str, Any]] = []
            for target_index in range(window["test_start"], window["test_end_exclusive"]):
                probabilities = (
                    markov(specials[target_index - 1]) if model_id == MODEL_IDS[2] else fixed[model_id]
                )
                actual = specials[target_index]
                log_loss, brier = _score(probabilities, actual)
                top5 = _top_k(probabilities)
                row = {
                    "cycle": window["cycle"],
                    "model_id": model_id,
                    "target_sample_index": target_index,
                    "target_expect": sample[target_index].source_expect,
                    "information_cutoff_sample_index": target_index - 1,
                    "actual_special": actual,
                    "actual_probability": float(probabilities[actual - 1]),
                    "top5": top5,
                    "top5_hit": actual in top5,
                    "log_loss": log_loss,
                    "brier": brier,
                }
                predictions.append(row)
                cycle_scores.append(row)
            cycle_rows.append(
                {
                    "cycle": window["cycle"],
                    "model_id": model_id,
                    "train_n": window["train_end_exclusive"] - window["train_start"],
                    "test_n": len(cycle_scores),
                    "train_first_expect": sample[window["train_start"]].source_expect,
                    "train_last_expect": sample[window["train_end_exclusive"] - 1].source_expect,
                    "test_first_expect": sample[window["test_start"]].source_expect,
                    "test_last_expect": sample[window["test_end_exclusive"] - 1].source_expect,
                    "mean_log_loss": float(np.mean([row["log_loss"] for row in cycle_scores])),
                    "mean_brier": float(np.mean([row["brier"] for row in cycle_scores])),
                    "top5_hits": sum(row["top5_hit"] for row in cycle_scores),
                    "top5_hit_rate": sum(row["top5_hit"] for row in cycle_scores) / len(cycle_scores),
                    "uniform_log_loss": baseline_log_loss,
                    "uniform_brier": baseline_brier,
                }
            )

    aggregate_rows: list[dict[str, Any]] = []
    for model_id in MODEL_IDS:
        model_predictions = [row for row in predictions if row["model_id"] == model_id]
        model_cycles = [row for row in cycle_rows if row["model_id"] == model_id]
        hits = sum(row["top5_hit"] for row in model_predictions)
        trials = len(model_predictions)
        exact = binomtest(hits, trials, p=TOP_K / POOL_SIZE, alternative="greater")
        interval = binomtest(hits, trials).proportion_ci(
            confidence_level=CONFIDENCE_LEVEL,
            method="exact",
        )
        mean_log_loss = float(np.mean([row["log_loss"] for row in model_predictions]))
        mean_brier = float(np.mean([row["brier"] for row in model_predictions]))
        aggregate_rows.append(
            {
                "model_id": model_id,
                "oos_cycles": len(model_cycles),
                "oos_trials": trials,
                "mean_log_loss": mean_log_loss,
                "uniform_log_loss": baseline_log_loss,
                "log_loss_delta_model_minus_uniform": mean_log_loss - baseline_log_loss,
                "cycles_better_log_loss": sum(
                    row["mean_log_loss"] < row["uniform_log_loss"] for row in model_cycles
                ),
                "mean_brier": mean_brier,
                "uniform_brier": baseline_brier,
                "brier_delta_model_minus_uniform": mean_brier - baseline_brier,
                "top5_hits": hits,
                "top5_hit_rate": hits / trials,
                "top5_uniform_baseline": TOP_K / POOL_SIZE,
                "top5_exact_ci_95": {"low": float(interval.low), "high": float(interval.high)},
                "top5_p_value_one_sided": float(exact.pvalue),
            }
        )
    _bh_adjust(aggregate_rows)
    for row in aggregate_rows:
        row["numeric_promotion_gate"] = bool(
            row["log_loss_delta_model_minus_uniform"] < 0
            and row["brier_delta_model_minus_uniform"] < 0
            and row["cycles_better_log_loss"] >= 5
            and row["top5_exact_ci_95"]["low"] > row["top5_uniform_baseline"]
            and row["top5_bh_reject"]
        )

    current_models: list[dict[str, Any]] = []
    current_fixed = {
        MODEL_IDS[0]: _smoothed_frequency(specials),
        MODEL_IDS[1]: _smoothed_frequency(specials[-100:]),
    }
    current_markov = _markov_predictor(specials)
    for model_id in MODEL_IDS:
        probabilities = current_markov(specials[-1]) if model_id == MODEL_IDS[2] else current_fixed[model_id]
        top5 = _top_k(probabilities)
        current_models.append(
            {
                "model_id": model_id,
                "condition_previous_special": specials[-1] if model_id == MODEL_IDS[2] else None,
                "top5": [
                    {"number": number, "probability": float(probabilities[number - 1])} for number in top5
                ],
                "probability_sum": float(probabilities.sum()),
            }
        )

    admitted = [row["model_id"] for row in aggregate_rows if row["numeric_promotion_gate"]]
    judgment = {
        "schema_version": "xinao.biz_l0.next_draw_judgment.v1",
        "question": "A_next_draw_judgment",
        "target": "next unseen canonical draw special number",
        "after_expect": sample[-1].source_expect,
        "after_open_time": sample[-1].open_time.isoformat(),
        "selected_distribution": "uniform_1_over_49" if not admitted else admitted[0],
        "admitted_models": admitted,
        "judgment_cn": (
            "三项预登记薄模型均未通过时, 下一期无可靠号码排序; 保留每号 1/49 的均匀基线。"
            if not admitted
            else "至少一项预登记模型通过数值门; 仅允许进入下一研究级, 仍不构成下注或优势结论。"
        ),
        "uniform_per_number_probability": 1.0 / POOL_SIZE,
        "uniform_top5_hit_probability": TOP_K / POOL_SIZE,
        "ranked_numbers": [] if not admitted else current_models[MODEL_IDS.index(admitted[0])]["top5"],
        "rank_withheld_reason": (
            "all numbers tie under the admitted uniform baseline" if not admitted else None
        ),
        "model_current_outputs_for_audit_only": current_models,
        "action": {
            "mode": "observe_only_no_bet" if not admitted else "research_only_no_bet",
            "stake_units": 0,
            "recommendation_claim": False,
            "edge_claim": False,
        },
        "uncertainty": {
            "kind": "OOS exact top-5 intervals are reported per model; no model interval is promoted",
            "source_rows_upstream_verified": False,
            "note_cn": "数据行均为上游 verify=false; 区间只描述该快照上的回测不确定度。",
        },
    }
    table = {
        "schema_version": "xinao.biz_l0.walkforward_table.v1",
        "sample": {
            "canonical_draw_count": len(draws),
            "N": sample_size,
            "first_expect": sample[0].source_expect,
            "last_expect": sample[-1].source_expect,
            "first_open_time": sample[0].open_time.isoformat(),
            "last_open_time": sample[-1].open_time.isoformat(),
        },
        "walk_forward": {
            "scheme": "expanding",
            "initial_train": initial_train,
            "test_size": test_size,
            "step": step,
            "oos_cycles": len(windows),
            "oos_trials_per_model": sum(
                window["test_end_exclusive"] - window["test_start"] for window in windows
            ),
        },
        "aggregate": aggregate_rows,
        "cycles": cycle_rows,
    }
    return table, predictions, judgment


def _build_artifacts(layout: InputLayout) -> dict[str, Any]:
    snapshot_before = build_snapshot_manifest(layout)
    draws, _quote, audit, lineage, _catalog = audit_inputs_p2(layout)
    table, predictions, judgment = evaluate_special_models(draws)
    snapshot_after = build_snapshot_manifest(layout)
    assert_snapshot_unchanged(snapshot_before, snapshot_after)
    quarantines = [record.model_dump(mode="json") for record in lineage if record.status == "quarantined"]
    input_pin = {
        "schema_version": "xinao.biz_l0.input_pin.v1",
        "snapshot_id": snapshot_before["snapshot_id"],
        "history_tsv": {
            "path": str(layout.history_tsv),
            "sha256": sha256_file(layout.history_tsv),
        },
        "history_jsonl": {
            "path": str(layout.history_jsonl),
            "sha256": sha256_file(layout.history_jsonl),
        },
        "raw_draw_count": audit["lineage_v2"]["source_draws"],
        "canonical_draw_count": audit["lineage_v2"]["usable_draws"],
        "source_verify_true": audit["lineage_v2"]["source_verify_true"],
        "lineage_policy": "validation-ranked exact-time alias, then earliest full-outcome repetition v2",
        "quarantines": quarantines,
        "read_only_snapshot_unchanged": True,
    }
    register = hypothesis_register()
    no_model_admitted = not judgment["admitted_models"]
    checks = {
        "schema_version": "xinao.biz_l0.checks.v1",
        "question_A_locked": True,
        "raw_1209_canonical_1204": (
            input_pin["raw_draw_count"] == 1_209 and input_pin["canonical_draw_count"] == 1_204
        ),
        "input_snapshot_unchanged": True,
        "recent_N_300": table["sample"]["N"] == 300,
        "hypotheses_at_most_3": register["registered_count"] <= register["max_hypotheses"],
        "oos_cycles_at_least_5": table["walk_forward"]["oos_cycles"] >= 5,
        "all_predictions_prequential": all(
            row["information_cutoff_sample_index"] < row["target_sample_index"] for row in predictions
        ),
        "all_models_have_explicit_baselines": all(
            row["uniform_log_loss"] > 0 and row["top5_uniform_baseline"] == TOP_K / POOL_SIZE
            for row in table["aggregate"]
        ),
        "all_models_have_exact_uncertainty": all(
            0 <= row["top5_exact_ci_95"]["low"] <= row["top5_exact_ci_95"]["high"] <= 1
            for row in table["aggregate"]
        ),
        "multiplicity_recorded": all("top5_p_value_bh" in row for row in table["aggregate"]),
        "negative_fallback_is_uniform": (
            not no_model_admitted or judgment["selected_distribution"] == "uniform_1_over_49"
        ),
        "stake_zero": judgment["action"]["stake_units"] == 0,
        "edge_claim_false": judgment["action"]["edge_claim"] is False,
        "recommendation_claim_false": judgment["action"]["recommendation_claim"] is False,
        "biz_l0_numeric_slice_complete": True,
        "promote_L1_allowed": not no_model_admitted,
        "edge_claim": False,
        "completion_claim_allowed": True,
    }
    return {
        "input_pin.json": input_pin,
        "hypothesis_register.json": register,
        "walkforward_table.json": table,
        "oos_predictions.json": predictions,
        "next_draw_judgment.json": judgment,
        "checks.json": checks,
    }


def run_l0_next_draw(*, input_root: Path, evidence_root: Path, run_name: str) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if _is_under(run_dir, layout.root):
        raise ValueError("evidence output must not be inside the input tree")
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    artifacts = _build_artifacts(layout)
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    for name, value in artifacts.items():
        write_json_atomic(run_dir / name, value)
    artifact_names = tuple(artifacts)
    manifest = {
        "schema_version": "xinao.biz_l0.run_manifest.v1",
        "status": "verified_negative_or_research_only",
        "run_name": run_name,
        "producer_source_fingerprint": _source_fingerprint(),
        "artifacts": _artifact_hashes(run_dir, artifact_names),
        "claims": {
            "biz_l0_numeric_slice_complete": True,
            "edge_claim": False,
            "recommendation_claim": False,
            "real_money_action": False,
        },
        "rerun": {
            "command": (
                "xinao-market-lab l0-next-draw --input-root "
                f"'{input_root}' --evidence-root '{evidence_root}' --run-name <new-unique-name>"
            )
        },
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    result = {
        "status": "verified",
        "run_dir": str(run_dir),
        "input_snapshot_id": artifacts["input_pin.json"]["snapshot_id"],
        "canonical_draw_count": artifacts["input_pin.json"]["canonical_draw_count"],
        "oos_cycles": artifacts["walkforward_table.json"]["walk_forward"]["oos_cycles"],
        "selected_distribution": artifacts["next_draw_judgment.json"]["selected_distribution"],
        "promote_L1_allowed": artifacts["checks.json"]["promote_L1_allowed"],
        "edge_claim": False,
        "completion_claim_allowed": True,
    }
    return result


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_l0_next_draw_run(*, input_root: Path, run_dir: Path) -> dict[str, Any]:
    layout = InputLayout.from_root(input_root)
    run_dir = run_dir.resolve()
    if layout.root == CANONICAL_INPUT_ROOT.resolve() and not _is_under(
        run_dir, CANONICAL_EVIDENCE_ROOT.resolve()
    ):
        raise ValueError(f"canonical input evidence must stay under {CANONICAL_EVIDENCE_ROOT}")
    expected = _build_artifacts(layout)
    manifest = _read_json(run_dir / "run_manifest.json")
    content_matches = {
        name: (run_dir / name).read_bytes() == canonical_json_bytes(value) for name, value in expected.items()
    }
    listed = {row["relative_path"]: row for row in manifest["artifacts"]}
    hash_matches = {
        name: (
            name in listed
            and listed[name]["sha256"] == sha256_file(run_dir / name)
            and listed[name]["size_bytes"] == (run_dir / name).stat().st_size
        )
        for name in expected
    }
    checks = {
        "all_semantic_artifacts_recomputed_equal": all(content_matches.values()),
        "all_manifest_hashes_match": all(hash_matches.values()),
        "producer_source_fingerprint_current": (
            manifest.get("producer_source_fingerprint") == _source_fingerprint()
        ),
        "edge_claim_false": manifest.get("claims", {}).get("edge_claim") is False,
        "recommendation_claim_false": manifest.get("claims", {}).get("recommendation_claim") is False,
    }
    verified = all(checks.values())
    return {
        "status": "verified" if verified else "failed",
        "verified": verified,
        "run_dir": str(run_dir),
        "checks": checks,
        "content_matches": content_matches,
        "hash_matches": hash_matches,
    }
