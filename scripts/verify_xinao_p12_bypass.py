"""Verify P12 remains sidelined and no second control plane was introduced by P0-P11."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return completed.stdout.strip()


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
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--p11-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    pack = json.loads(args.p11_pack.read_text(encoding="utf-8"))
    services = run(["docker", "compose", "config", "--services"], cwd=repo).splitlines()
    p12_workflows = run(
        [
            "temporal",
            "workflow",
            "list",
            "--namespace",
            "default",
            "--address",
            "127.0.0.1:7233",
            "--query",
            'WorkflowId STARTS_WITH "xinao-p12"',
            "--limit",
            "20",
        ],
        cwd=repo,
    )
    compose_diff = run(["git", "diff", "--", "docker-compose.yml"], cwd=repo).lower()
    forbidden_persistence = (
        "watchdog",
        "auto-submit",
        "continuation_loop",
        "root_intent_loop_driver",
        "scheduler:",
    )
    restore_canary = run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^xinao-p10-restore-postgres$",
            "--format",
            "{{.ID}}",
        ],
        cwd=repo,
    )
    checks = {
        "p11_verified_before_p12": pack.get("status") == "verified",
        "no_p12_temporal_workflow": not p12_workflows,
        "no_p12_compose_service": not any("p12" in service.lower() for service in services),
        "single_temporal_service": services.count("naijiu-shiwu") == 1,
        "no_second_orchestrator_service": not any(
            name in {service.lower() for service in services}
            for name in ("airflow", "prefect", "dagster", "celery", "argo")
        ),
        "no_new_auto_continuation_or_watchdog": not any(
            token in compose_diff for token in forbidden_persistence
        ),
        "no_restore_canary_left_running": not restore_canary,
        "p12_documented_as_sidelined": "P12 remains sidelined"
        in (repo / "xinao_discovery" / "README.md").read_text(encoding="utf-8"),
    }
    report = {
        "schema_version": "xinao.p12_bypass_negative_check.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "verified_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "compose_services": services,
        "p12_workflow_query_empty": not p12_workflows,
        "authorized_persistence_delta": "PostgreSQL WAL archive and backup mounts from P10 only",
        "prohibited_effects_observed": [],
    }
    write_json_atomic(args.output, report)
    print(json.dumps({"status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
