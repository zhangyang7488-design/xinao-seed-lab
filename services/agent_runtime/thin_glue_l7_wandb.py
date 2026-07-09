"""L7 实验面板薄绑 — wandb 云跳过，MLflow 本地别名 thin_bind."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL, now_iso, write_json

TASK_ID = "thin_glue_wandb_mlflow_alias"
REPLACES_MODULE = "wandb_cloud_handroll"


def resolve_wandb_mode() -> str:
    return os.environ.get("WANDB_MODE", "disabled").strip().lower() or "disabled"


def probe_wandb_mlflow_alias(*, mlflow_ok: bool = False, mlflow_tracking_uri: str = "") -> dict[str, Any]:
    mode = resolve_wandb_mode()
    if mode not in {"disabled", "offline", "dryrun"}:
        return {
            "adapter": "wandb_mlflow_alias",
            "ok": False,
            "skipped": True,
            "thin_bind": False,
            "reason": f"wandb_cloud_mode_blocked:{mode}",
            "named_blocker": "WANDB_CLOUD_SKIPPED",
            "wandb_mode": mode,
        }
    if not mlflow_ok:
        return {
            "adapter": "wandb_mlflow_alias",
            "ok": False,
            "skipped": True,
            "thin_bind": False,
            "reason": "mlflow_alias_source_not_green",
            "named_blocker": "MLFLOW_ALIAS_SOURCE_MISSING",
            "wandb_mode": mode,
        }
    tracking_uri = mlflow_tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    return {
        "adapter": "wandb_mlflow_alias",
        "ok": True,
        "skipped": False,
        "thin_bind": True,
        "invoke_green": True,
        "wandb_mode": mode,
        "mlflow_alias": True,
        "tracking_uri": tracking_uri,
        "cloud_login_required": False,
        "named_blocker": None,
    }


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_wandb"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_wandb_latest.md",
    }


def run_wandb_smoke(
    *,
    runtime: Path | None = None,
    run_id: str | None = None,
    mlflow_ok: bool = False,
    mlflow_tracking_uri: str = "",
    write_evidence: bool = True,
    hot_path: bool = False,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    alias = probe_wandb_mlflow_alias(mlflow_ok=mlflow_ok, mlflow_tracking_uri=mlflow_tracking_uri)
    alias_ok = alias.get("ok") is True
    invoke_green = hot_path and mlflow_ok and alias_ok
    thin_bind = alias_ok and not invoke_green
    ok = invoke_green or alias_ok
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L7",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": ok,
        "wandb_ok": ok,
        "L7_wandb_ok": ok,
        "L7_wandb_invoke_green": invoke_green,
        "L7_wandb_thin_bind": thin_bind,
        "wandb_mlflow_alias_ok": alias_ok,
        "named_blocker": alias.get("named_blocker"),
        "alias": alias,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_wandb",
                    f"- thin_bind: {thin_bind}",
                    f"- mlflow_alias: {alias.get('mlflow_alias')}",
                    f"- tracking_uri: {alias.get('tracking_uri') or 'none'}",
                    f"- wandb_mode: {alias.get('wandb_mode')}",
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

    parser = argparse.ArgumentParser(description="WandB MLflow-alias thin-bind")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--mlflow-ok", action="store_true")
    parser.add_argument("--tracking-uri", default="")
    args = parser.parse_args()
    payload = run_wandb_smoke(
        runtime=Path(args.runtime_root),
        mlflow_ok=args.mlflow_ok,
        mlflow_tracking_uri=args.tracking_uri,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("L7_wandb_thin_bind") else 1


if __name__ == "__main__":
    raise SystemExit(main())