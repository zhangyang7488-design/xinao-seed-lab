"""CLI entry: python adapters/temporal/run_worker.py  (or -m with repo root on PYTHONPATH).

Env:
  XINAO_TEMPORAL_ADDRESS          default 127.0.0.1:7233
  XINAO_TEMPORAL_NAMESPACE        default default
  XINAO_TEMPORAL_TASK_QUEUE       default xinao-dualbrain-promoted-v1
  XINAO_TEMPORAL_WORKER_IDENTITY  default xinao-promoted-worker-g1
  XINAO_TEMPORAL_WORKER_VERSIONING 1 enables official Worker Deployments
  XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME stable deployment name
  XINAO_TEMPORAL_WORKER_BUILD_ID  immutable candidate build identity
  XINAO_TEMPORAL_WORKER_LOG       optional path for file logging (G1 evidence dir)
  PYTHONPATH                      prefer repo root + src (see start_worker_hidden.ps1)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    repo = Path(__file__).resolve().parents[2]
    src = repo / "src"
    for p in (str(repo), str(src)):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Prefer package import after path fix; fallback to same-dir load.
    try:
        from adapters.temporal.worker_runtime import WorkerRuntimeConfig, run_promoted_worker
    except ModuleNotFoundError:
        import importlib.util

        wr = Path(__file__).resolve().parent / "worker_runtime.py"
        spec = importlib.util.spec_from_file_location("worker_runtime", wr)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        WorkerRuntimeConfig = mod.WorkerRuntimeConfig
        run_promoted_worker = mod.run_promoted_worker

    cfg = WorkerRuntimeConfig.from_env()
    log_path = os.environ.get("XINAO_TEMPORAL_WORKER_LOG", "").strip()
    if log_path:
        try:
            from logging.handlers import RotatingFileHandler

            fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
            logging.getLogger().addHandler(fh)
        except OSError:
            logging.getLogger(__name__).warning("could not open worker log %s", log_path)

    logging.getLogger(__name__).info(
        "starting promoted worker address=%s namespace=%s task_queue=%s "
        "workflow_type=%s identity=%s versioning=%s deployment=%s build_id=%s",
        cfg.address,
        cfg.namespace,
        cfg.task_queue,
        cfg.workflow_type,
        cfg.identity,
        cfg.use_worker_versioning,
        cfg.deployment_name,
        cfg.worker_build_id,
    )
    asyncio.run(run_promoted_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
