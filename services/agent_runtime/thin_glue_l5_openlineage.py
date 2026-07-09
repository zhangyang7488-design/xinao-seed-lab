"""L5 血缘薄绑 — OpenLineage event emit → Marquez."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL, now_iso, write_json

TASK_ID = "thin_glue_openlineage"
REPLACES_MODULE = "openlineage_facade_handroll"
_DEFAULT_MARQUEZ_URL = "http://127.0.0.1:5001"
_JOB_NAMESPACE = "xinao"
_JOB_NAME = "integrated_bus_thin_glue_smoke"
_PRODUCER = "https://github.com/xinao/integrated-bus"


def resolve_marquez_url() -> str:
    return (
        os.environ.get("MARQUEZ_URL")
        or os.environ.get("OPENLINEAGE_URL")
        or _DEFAULT_MARQUEZ_URL
    ).rstrip("/")


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_openlineage"
    facade = runtime / "state" / "openlineage_facade"
    return {
        "latest": state / "latest.json",
        "facade_latest": facade / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_openlineage_latest.md",
    }


def probe_marquez_api(*, marquez_url: str | None = None, timeout: float = 8.0) -> dict[str, Any]:
    base = (marquez_url or resolve_marquez_url()).rstrip("/")
    try:
        import httpx
    except ImportError:
        return {
            "adapter": "marquez",
            "ok": False,
            "skipped": True,
            "reason": "httpx_missing",
            "marquez_url": base,
            "status_code": None,
        }
    for path in ("/api/v1/namespaces", "/healthcheck"):
        url = f"{base}{path}"
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        except Exception as exc:
            return {
                "adapter": "marquez",
                "ok": False,
                "skipped": True,
                "reason": str(exc),
                "marquez_url": base,
                "status_code": None,
            }
        if resp.status_code == 200:
            return {
                "adapter": "marquez",
                "ok": True,
                "skipped": False,
                "marquez_url": base,
                "probe_path": path,
                "status_code": resp.status_code,
            }
    return {
        "adapter": "marquez",
        "ok": False,
        "skipped": True,
        "reason": f"http_{resp.status_code}",
        "marquez_url": base,
        "status_code": resp.status_code,
    }


def _minimal_run_event(*, run_id: str | None = None) -> dict[str, Any]:
    event_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    resolved_run_id = run_id or str(uuid.uuid4())
    return {
        "eventType": "COMPLETE",
        "eventTime": event_time,
        "producer": _PRODUCER,
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent",
        "run": {
            "runId": resolved_run_id,
            "facets": {},
        },
        "job": {
            "namespace": _JOB_NAMESPACE,
            "name": _JOB_NAME,
        },
    }


def emit_openlineage_event(
    *,
    marquez_url: str | None = None,
    run_id: str | None = None,
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = (marquez_url or resolve_marquez_url()).rstrip("/")
    probe = probe_marquez_api(marquez_url=base)
    if not probe.get("ok"):
        return {
            "adapter": "openlineage",
            "ok": False,
            "skipped": True,
            "reason": probe.get("reason") or "probe_failed",
            "marquez_url": base,
            "probe": probe,
        }
    payload = event or _minimal_run_event(run_id=run_id)
    lineage_url = f"{base}/api/v1/lineage"
    try:
        import httpx

        resp = httpx.post(
            lineage_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=12.0,
        )
    except Exception as exc:
        return {
            "adapter": "openlineage",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "marquez_url": base,
            "lineage_url": lineage_url,
            "probe": probe,
            "event": payload,
        }
    if resp.status_code not in {200, 201, 204}:
        return {
            "adapter": "openlineage",
            "ok": False,
            "skipped": True,
            "reason": f"http_{resp.status_code}",
            "marquez_url": base,
            "lineage_url": lineage_url,
            "status_code": resp.status_code,
            "response_excerpt": (resp.text or "")[:500],
            "probe": probe,
            "event": payload,
        }
    return {
        "adapter": "openlineage",
        "ok": True,
        "skipped": False,
        "marquez_url": base,
        "lineage_url": lineage_url,
        "status_code": resp.status_code,
        "run_id": str(payload.get("run", {}).get("runId") or ""),
        "job_namespace": str(payload.get("job", {}).get("namespace") or ""),
        "job_name": str(payload.get("job", {}).get("name") or ""),
        "probe": probe,
        "event": payload,
    }


def run_openlineage_smoke(
    *,
    runtime: Path | None = None,
    run_id: str | None = None,
    marquez_url: str | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    emitted = emit_openlineage_event(
        marquez_url=marquez_url,
        run_id=f"xinao-{resolved_run_id}",
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L5",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": emitted.get("ok") is True,
        "openlineage_ok": emitted.get("ok") is True,
        "marquez_url": emitted.get("marquez_url") or resolve_marquez_url(),
        "openlineage_run_id": emitted.get("run_id"),
        "emit": emitted,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        facade_payload = {
            "schema_version": "xinao.openlineage_facade.v1",
            "sentinel": "SENTINEL:XINAO_OPENLINEAGE_FACADE_READY",
            "run_id": resolved_run_id,
            "timestamp": now_iso(),
            "invoke_ok": payload["invoke_ok"],
            "marquez_url": payload["marquez_url"],
            "openlineage_run_id": payload.get("openlineage_run_id"),
            "thin_glue_ref": str(paths["latest"]),
        }
        write_json(paths["facade_latest"], facade_payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_openlineage",
                    f"- invoke_ok: {payload['invoke_ok']}",
                    f"- marquez_url: {payload['marquez_url']}",
                    f"- openlineage_run_id: {payload.get('openlineage_run_id') or 'none'}",
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

    parser = argparse.ArgumentParser(description="OpenLineage thin-glue smoke")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--marquez-url", default="")
    args = parser.parse_args()
    payload = run_openlineage_smoke(
        runtime=Path(args.runtime_root),
        marquez_url=args.marquez_url or None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("invoke_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())