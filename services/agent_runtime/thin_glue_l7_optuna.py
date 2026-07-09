"""L7 超参优化薄绑 — Optuna in-process smoke study."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL, now_iso, write_json

TASK_ID = "thin_glue_optuna"
REPLACES_MODULE = "width_promotion_handroll"


def probe_optuna_import() -> dict[str, Any]:
    try:
        import optuna  # noqa: F401
    except ImportError as exc:
        return {
            "adapter": "optuna",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "OPTUNA_NOT_INSTALLED",
        }
    import optuna as optuna_mod

    return {
        "adapter": "optuna",
        "ok": True,
        "skipped": False,
        "version": getattr(optuna_mod, "__version__", "unknown"),
    }


def run_optuna_smoke_study(*, n_trials: int = 1) -> dict[str, Any]:
    probe = probe_optuna_import()
    if not probe.get("ok"):
        return {
            "adapter": "optuna_study",
            "ok": False,
            "skipped": True,
            "reason": probe.get("reason") or "import_failed",
            "named_blocker": probe.get("named_blocker") or "OPTUNA_IMPORT_FAILED",
            "probe": probe,
        }
    import optuna

    def objective(trial: optuna.Trial) -> float:
        x = trial.suggest_float("x", 0.0, 1.0)
        return (x - 0.42) ** 2

    try:
        study = optuna.create_study(
            study_name="xinao_integrated_bus_smoke",
            direction="minimize",
            storage=None,
        )
        study.optimize(objective, n_trials=max(1, n_trials), show_progress_bar=False)
        best = study.best_trial
    except Exception as exc:
        return {
            "adapter": "optuna_study",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "OPTUNA_STUDY_FAILED",
            "probe": probe,
        }
    return {
        "adapter": "optuna_study",
        "ok": True,
        "skipped": False,
        "study_name": study.study_name,
        "n_trials": len(study.trials),
        "best_value": best.value,
        "best_params": dict(best.params),
        "probe": probe,
    }


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_optuna"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_optuna_latest.md",
    }


def run_optuna_smoke(
    *,
    runtime: Path | None = None,
    run_id: str | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    study = run_optuna_smoke_study()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L7",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": study.get("ok") is True,
        "optuna_ok": study.get("ok") is True,
        "L7_optuna_ok": study.get("ok") is True,
        "named_blocker": study.get("named_blocker"),
        "study": study,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_optuna",
                    f"- invoke_ok: {payload['invoke_ok']}",
                    f"- n_trials: {study.get('n_trials') or 0}",
                    f"- best_value: {study.get('best_value')}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {k: str(v) for k, v in paths.items()}
    return payload


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Optuna thin-glue smoke")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args()
    payload = run_optuna_smoke(runtime=Path(args.runtime_root))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("invoke_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())