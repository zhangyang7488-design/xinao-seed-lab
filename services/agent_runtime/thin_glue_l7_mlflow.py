"""L7 实验追踪薄绑 — MLflow tracking server probe + minimal run."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_RUNTIME,
    SCHEMA_VERSION,
    SENTINEL,
    now_iso,
    write_json,
)

TASK_ID = "thin_glue_mlflow"
REPLACES_MODULE = "progress_self_evolution_handroll"
_DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"
_EXPERIMENT_NAME = "xinao-integrated-bus"


def resolve_tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI", _DEFAULT_TRACKING_URI).rstrip("/")


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_mlflow"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_mlflow_latest.md",
    }


def probe_mlflow_tracking(
    *, tracking_uri: str | None = None, timeout: float = 8.0
) -> dict[str, Any]:
    uri = (tracking_uri or resolve_tracking_uri()).rstrip("/")
    try:
        import httpx
    except ImportError:
        return {
            "adapter": "mlflow",
            "ok": False,
            "skipped": True,
            "reason": "httpx_missing",
            "tracking_uri": uri,
            "status_code": None,
        }
    for path in ("/health", "/version", ""):
        url = f"{uri}{path}"
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        except Exception as exc:
            return {
                "adapter": "mlflow",
                "ok": False,
                "skipped": True,
                "reason": str(exc),
                "tracking_uri": uri,
                "status_code": None,
            }
        if resp.status_code == 200:
            return {
                "adapter": "mlflow",
                "ok": True,
                "skipped": False,
                "tracking_uri": uri,
                "probe_path": path or "/",
                "status_code": resp.status_code,
            }
    return {
        "adapter": "mlflow",
        "ok": False,
        "skipped": True,
        "reason": f"http_{resp.status_code}",
        "tracking_uri": uri,
        "status_code": resp.status_code,
    }


def _log_minimal_run_rest(
    *,
    uri: str,
    experiment_name: str,
    run_name: str,
    probe: dict[str, Any],
) -> dict[str, Any]:
    import httpx

    client = httpx.Client(base_url=uri, timeout=12.0)
    exp_resp = client.post(
        "/api/2.0/mlflow/experiments/create",
        json={"name": experiment_name},
    )
    if exp_resp.status_code == 200:
        experiment_id = str((exp_resp.json().get("experiment") or {}).get("experiment_id") or "")
    else:
        by_name = client.get(
            "/api/2.0/mlflow/experiments/get-by-name",
            params={"experiment_name": experiment_name},
        )
        if by_name.status_code != 200:
            return {
                "adapter": "mlflow_rest",
                "ok": False,
                "skipped": True,
                "reason": f"experiment_http_{by_name.status_code}",
                "tracking_uri": uri,
                "probe": probe,
            }
        experiment_id = str((by_name.json().get("experiment") or {}).get("experiment_id") or "")
    run_resp = client.post(
        "/api/2.0/mlflow/runs/create",
        json={
            "experiment_id": experiment_id,
            "start_time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
    )
    if run_resp.status_code != 200:
        return {
            "adapter": "mlflow_rest",
            "ok": False,
            "skipped": True,
            "reason": f"run_create_http_{run_resp.status_code}",
            "tracking_uri": uri,
            "probe": probe,
        }
    run_info = run_resp.json().get("run") or {}
    run_id = str((run_info.get("info") or {}).get("run_id") or "")
    client.post(
        "/api/2.0/mlflow/runs/log-parameter",
        json={"run_id": run_id, "key": "thin_glue", "value": TASK_ID},
    )
    client.post(
        "/api/2.0/mlflow/runs/log-parameter",
        json={
            "run_id": run_id,
            "key": "probe_path",
            "value": str(probe.get("probe_path") or "/health"),
        },
    )
    client.post(
        "/api/2.0/mlflow/runs/log-metric",
        json={
            "run_id": run_id,
            "key": "smoke_ok",
            "value": 1.0,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
    )
    client.post(
        "/api/2.0/mlflow/runs/update",
        json={
            "run_id": run_id,
            "status": "FINISHED",
            "end_time": int(datetime.now(timezone.utc).timestamp() * 1000),
        },
    )
    return {
        "adapter": "mlflow_rest",
        "ok": True,
        "skipped": False,
        "tracking_uri": uri,
        "experiment_name": experiment_name,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "run_name": run_name,
        "probe": probe,
    }


def log_minimal_run(
    *,
    tracking_uri: str | None = None,
    experiment_name: str = _EXPERIMENT_NAME,
    run_name: str | None = None,
) -> dict[str, Any]:
    uri = (tracking_uri or resolve_tracking_uri()).rstrip("/")
    probe = probe_mlflow_tracking(tracking_uri=uri)
    if not probe.get("ok"):
        return {
            "adapter": "mlflow",
            "ok": False,
            "skipped": True,
            "reason": probe.get("reason") or "probe_failed",
            "tracking_uri": uri,
            "probe": probe,
        }
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    resolved_run_name = run_name or f"thin_glue_smoke_{stamp}"
    try:
        import mlflow

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment_name)
        with mlflow.start_run(run_name=resolved_run_name) as active_run:
            mlflow.log_param("thin_glue", TASK_ID)
            mlflow.log_param("probe_path", str(probe.get("probe_path") or "/health"))
            mlflow.log_metric("smoke_ok", 1.0)
            run_id = active_run.info.run_id
            experiment_id = active_run.info.experiment_id
        return {
            "adapter": "mlflow",
            "ok": True,
            "skipped": False,
            "tracking_uri": uri,
            "experiment_name": experiment_name,
            "experiment_id": experiment_id,
            "run_id": run_id,
            "run_name": resolved_run_name,
            "probe": probe,
        }
    except ImportError:
        try:
            return _log_minimal_run_rest(
                uri=uri,
                experiment_name=experiment_name,
                run_name=resolved_run_name,
                probe=probe,
            )
        except Exception as exc:
            return {
                "adapter": "mlflow_rest",
                "ok": False,
                "skipped": True,
                "reason": str(exc),
                "tracking_uri": uri,
                "probe": probe,
            }
    except Exception as exc:
        return {
            "adapter": "mlflow",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "tracking_uri": uri,
            "probe": probe,
        }


def run_mlflow_smoke(
    *,
    runtime: Path | None = None,
    run_id: str | None = None,
    tracking_uri: str | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    minimal = log_minimal_run(
        tracking_uri=tracking_uri, run_name=f"integrated_bus_{resolved_run_id}"
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L7",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": minimal.get("ok") is True,
        "mlflow_ok": minimal.get("ok") is True,
        "tracking_uri": minimal.get("tracking_uri") or resolve_tracking_uri(),
        "experiment_name": minimal.get("experiment_name"),
        "experiment_id": minimal.get("experiment_id"),
        "mlflow_run_id": minimal.get("run_id"),
        "minimal_run": minimal,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_mlflow",
                    f"- invoke_ok: {payload['invoke_ok']}",
                    f"- tracking_uri: {payload['tracking_uri']}",
                    f"- mlflow_run_id: {payload.get('mlflow_run_id') or 'none'}",
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

    parser = argparse.ArgumentParser(description="MLflow thin-glue smoke")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--tracking-uri", default="")
    args = parser.parse_args()
    payload = run_mlflow_smoke(
        runtime=Path(args.runtime_root),
        tracking_uri=args.tracking_uri or None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("invoke_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
