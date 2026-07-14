"""One fresh-process phase of the fixed Optuna RDB resume canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import optuna
from optuna.trial import TrialState


def objective(trial: optuna.Trial) -> float:
    x = trial.suggest_categorical("x", [-3, 0, 3, 6, 9])
    value = -float((x - 3) ** 2)
    if x == -3:
        raise RuntimeError("intentional failed trial canary")
    trial.report(value, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned("intentional threshold-pruned trial canary")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", type=Path, required=True)
    parser.add_argument("--phase", choices=("initial", "resume"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    storage = f"sqlite:///{args.storage.as_posix()}"
    sampler = optuna.samplers.GridSampler({"x": [-3, 0, 3, 6, 9]}, seed=20260714)
    pruner = optuna.pruners.ThresholdPruner(lower=-20.0)
    if args.phase == "initial":
        study = optuna.create_study(
            study_name="xinao-p5-fixed-grid",
            storage=storage,
            direction="maximize",
            sampler=sampler,
            pruner=pruner,
        )
        trials = 2
    else:
        study = optuna.load_study(
            study_name="xinao-p5-fixed-grid",
            storage=storage,
            sampler=sampler,
            pruner=pruner,
        )
        trials = 5
    study.optimize(objective, n_trials=trials, catch=(RuntimeError,))
    states = {state.name: 0 for state in TrialState}
    for trial in study.trials:
        states[trial.state.name] += 1
    try:
        best_params = study.best_params
        best_value = study.best_value
    except ValueError:
        best_params = None
        best_value = None
    payload = {
        "phase": args.phase,
        "trial_count": len(study.trials),
        "states": states,
        "best_params": best_params,
        "best_value": best_value,
    }
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
