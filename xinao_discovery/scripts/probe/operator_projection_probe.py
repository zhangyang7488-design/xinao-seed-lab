"""Run the P9 read-only Temporal/evidence projection as a live probe."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from xinao.projection import (
    build_workflow_projection,
    describe_temporal_workflow,
    render_tui,
)


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    args = parser.parse_args()
    description = describe_temporal_workflow(
        workflow_id=args.workflow_id,
        run_id=args.run_id,
        address=args.address,
        namespace=args.namespace,
    )
    projection = build_workflow_projection(
        args.report,
        temporal_description=description,
        runtime_root=args.runtime_root,
    )
    checks = {
        "read_only_projection": projection["read_only"] is True,
        "no_domain_write_credentials": projection["domain_write_credentials"] is False,
        "temporal_status_visible": bool(projection["workflow"]["status"]),
        "evidence_verified": projection["evidence"]["ok"] is True,
        "pause_visible": projection["pause_visible"] is True,
        "resume_visible": projection["resume_visible"] is True,
        "terminal_projection_marks_read_only": "[READ ONLY]" in render_tui(projection),
    }
    result = {
        "schema_version": "xinao.p9_operator_projection_probe.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "verified_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "projection": projection,
        "tui": render_tui(projection),
    }
    write_json_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
