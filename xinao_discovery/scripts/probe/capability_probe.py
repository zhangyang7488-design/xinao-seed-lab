"""Read-only capability and formal-input probe for CODEX-XINAO-BUILD-001."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION_INPUT = "xinao.input_material_manifest.v1"
SCHEMA_VERSION_CAPABILITY = "xinao.capability_manifest.v1"
EXPECTED_DATASET_SHA256 = "57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"
EXPECTED_BASELINE_SHA256 = "634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parent
RUNTIME_ROOT = Path(os.environ.get("XINAO_RUNTIME_ROOT", r"D:\XINAO_RESEARCH_RUNTIME"))
CANONICAL_TRANSACTIONS = RUNTIME_ROOT / "state" / "canonical_grok_transactions"

MATERIALS = (
    {
        "material_id": "xinao-background-axioms-contract.current",
        "role": "formal_project_axioms_and_acceptance",
        "path": Path(r"C:\Users\xx363\Desktop\主线\02正式合同\新澳背景模型前置约束-与验收定义.txt"),
        "expected_sha256": "114c28c131f5571dfedacc3e2c3684acc4f5b298f8e797c0904a2f958f04f5b0",
    },
    {
        "material_id": "macaujc-source-authority-contract.v1",
        "role": "formal_source_identity_and_admission",
        "path": Path(
            r"C:\Users\xx363\Desktop\主线\02正式合同\新澳门六合彩_macaujc2_来源身份与可信权威合同.txt"
        ),
        "expected_sha256": "70cb5d86a1712501c0fbb934a66abb57d523acbf1dcc680329d69b72834beebd",
    },
    {
        "material_id": "macaujc2-authority-dataset-2024-01-01--2026-07-01",
        "role": "formal_authority_dataset",
        "path": Path(
            r"C:\Users\xx363\Desktop\主线\03正式数据\新澳门六合彩_macaujc2_完整权威数据_2024-01-01_至_2026-07-01.txt"
        ),
        "expected_sha256": EXPECTED_DATASET_SHA256,
    },
    {
        "material_id": "baseline-odds-water.v1",
        "role": "sole_formal_baseline_odds_water_csv",
        "path": Path(r"C:\Users\xx363\Desktop\主线\03正式数据\新澳_默认基础赔率水位表_v1.csv"),
        "expected_sha256": EXPECTED_BASELINE_SHA256,
    },
)


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_read_only(
    command: list[str], *, cwd: Path | None = None, timeout: int = 20
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr_type": "present" if completed.stderr.strip() else "empty",
    }


def git_snapshot() -> dict[str, Any]:
    head = run_read_only(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT)
    branch = run_read_only(["git", "branch", "--show-current"], cwd=REPOSITORY_ROOT)
    status = run_read_only(["git", "status", "--porcelain=v1"], cwd=REPOSITORY_ROOT)
    remotes = run_read_only(["git", "remote"], cwd=REPOSITORY_ROOT)
    status_text = str(status.get("stdout", ""))
    return {
        "root": str(REPOSITORY_ROOT),
        "head": head.get("stdout", ""),
        "branch": branch.get("stdout", ""),
        "dirty_entry_count": len(status_text.splitlines()) if status_text else 0,
        "status_sha256": hashlib.sha256(status_text.encode("utf-8")).hexdigest(),
        "remotes": str(remotes.get("stdout", "")).splitlines(),
        "ok": all(item.get("ok") for item in (head, branch, status, remotes)),
    }


def material_manifest() -> tuple[list[dict[str, Any]], dict[str, Path]]:
    records: list[dict[str, Any]] = []
    by_id: dict[str, Path] = {}
    for material in MATERIALS:
        path = Path(material["path"])
        if not path.is_file():
            records.append(
                {
                    "material_id": material["material_id"],
                    "role": material["role"],
                    "path": str(path),
                    "exists": False,
                    "expected_sha256": material["expected_sha256"],
                }
            )
            continue
        first_hash = sha256_file(path)
        second_hash = sha256_file(path)
        stat = path.stat()
        records.append(
            {
                "material_id": material["material_id"],
                "role": material["role"],
                "path": str(path),
                "size_bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "sha256": first_hash,
                "expected_sha256": material["expected_sha256"],
                "exists": True,
                "stable_during_probe": first_hash == second_hash,
                "expected_sha256_matches": first_hash == material["expected_sha256"],
            }
        )
        by_id[str(material["material_id"])] = path
    return records, by_id


def verify_dataset(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"ok": False, "error": "dataset_missing"}
    text = path.read_text(encoding="utf-8")
    human_records = len(re.findall(r"^第\d+期", text, re.MULTILINE))
    json_records = len(re.findall(r'^\{"suit"', text, re.MULTILINE))
    return {
        "declared_records": 913,
        "human_record_lines": human_records,
        "json_record_lines": json_records,
        "ok": human_records == 913 and json_records == 913,
    }


def verify_baseline(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"ok": False, "error": "baseline_missing"}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups = {row["玩法组"] for row in rows}
    identifiers = [row["基准ID"] for row in rows]
    unique = len(identifiers) == len(set(identifiers))
    return {
        "data_rows": len(rows),
        "play_groups": len(groups),
        "baseline_id_unique": unique,
        "play_group_names": sorted(groups),
        "ok": len(rows) == 433 and len(groups) == 13 and unique,
    }


def tcp_probe(port: int) -> dict[str, Any]:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return {"host": "127.0.0.1", "port": port, "ok": True}
    except OSError as exc:
        return {"host": "127.0.0.1", "port": port, "ok": False, "error": type(exc).__name__}


def docker_service(container: str) -> dict[str, Any]:
    inspected = run_read_only(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container,
        ]
    )
    state, _, health = str(inspected.get("stdout", "")).partition("|")
    return {
        "container": container,
        "state": state,
        "health": health,
        "ok": bool(inspected.get("ok")) and state == "running" and health in {"healthy", "none"},
    }


def _langgraph_child_passed(children: Any) -> bool:
    if isinstance(children, dict):
        return children.get("passed") is True or children.get("ok") is True
    if not isinstance(children, list):
        return False
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("ok") is True or child.get("passed") is True:
            return True
        result = child.get("result")
        if isinstance(result, dict) and (
            result.get("ok") is True or result.get("status") == "passed"
        ):
            return True
    return False


def latest_durable_task() -> dict[str, Any]:
    candidates = sorted(CANONICAL_TRANSACTIONS.glob("canonical-grok-*/result.json"), reverse=True)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        result = payload.get("result")
        if payload.get("ok") is not True or not isinstance(result, dict):
            continue
        lanes = result.get("grok_lanes")
        children = result.get("langgraph_children")
        if (
            not isinstance(lanes, list)
            or not lanes
            or not all(isinstance(lane, dict) and lane.get("ok") is True for lane in lanes)
        ):
            continue
        if not _langgraph_child_passed(children):
            continue
        return {
            "available": True,
            "workflow_id": payload.get("workflow_id"),
            "run_id": payload.get("run_id"),
            "grok_lane_count": len(lanes),
            "langgraph_child_passed": True,
            "result_path": str(path),
            "result_sha256": sha256_file(path),
            "result_status": "verified",
        }
    return {"available": False, "result_status": "unverified"}


def ensure_output_boundary(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("--out must be an absolute path")
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("--out must not point inside the repository project")
    if os.name == "nt" and resolved.drive.upper() != "D:":
        raise ValueError("--out must use the D: runtime/evidence drive")
    return resolved


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_manifests(correlation_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    before = git_snapshot()
    materials, by_id = material_manifest()
    dataset = verify_dataset(by_id.get("macaujc2-authority-dataset-2024-01-01--2026-07-01"))
    baseline = verify_baseline(by_id.get("baseline-odds-water.v1"))
    services = [
        docker_service("shiwu-ku"),
        docker_service("naijiu-shiwu"),
        docker_service("shiwu-mianban"),
        docker_service("houtai-gongren"),
    ]
    ports = [tcp_probe(7233), tcp_probe(8080)]
    durable_task = latest_durable_task()
    after = git_snapshot()
    repository_unchanged = before == after
    materials_ok = len(materials) == 4 and all(
        item.get("exists") is True
        and item.get("stable_during_probe") is True
        and item.get("expected_sha256_matches") is True
        for item in materials
    )
    input_ok = materials_ok and dataset.get("ok") is True and baseline.get("ok") is True
    services_ok = all(item["ok"] for item in services) and all(item["ok"] for item in ports)
    capability_ok = (
        services_ok and durable_task.get("result_status") == "verified" and repository_unchanged
    )
    generated_at = now_utc()
    input_manifest = {
        "schema_version": SCHEMA_VERSION_INPUT,
        "generated_at": generated_at,
        "correlation_id": correlation_id,
        "parent_operation_id": correlation_id,
        "authority_order": [
            "current_user_intent",
            "formal_contracts_by_scope",
            "construction_final_spec",
            "machine_blueprint",
            "formal_data",
            "raw_evidence",
            "archived_inputs",
        ],
        "materials": materials,
        "dataset_verification": dataset,
        "baseline_verification": baseline,
        "result_status": "verified" if input_ok else "blocked",
    }
    capability_manifest = {
        "schema_version": SCHEMA_VERSION_CAPABILITY,
        "generated_at": generated_at,
        "probe_mode": "read_only",
        "correlation_id": correlation_id,
        "repository": {
            **after,
            "unchanged_during_probe": repository_unchanged,
            "mutated_by_probe": False,
        },
        "toolchain": {
            "python": sys.version.split()[0],
            "uv": run_read_only(["uv", "--version"]),
            "docker": run_read_only(["docker", "--version"]),
        },
        "core_service_smoke": {
            "core_ok": services_ok,
            "temporal_ok": ports[0]["ok"],
            "worker_ready": services[-1]["ok"],
            "services": services,
            "tcp": ports,
        },
        "durable_task_entry": durable_task,
        "result_status": "verified" if capability_ok else "partial",
    }
    return input_manifest, capability_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("read-only",))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--correlation-id",
        default=f"xinao-capability-probe-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = ensure_output_boundary(args.out)
    input_manifest, capability_manifest = build_manifests(args.correlation_id)
    write_atomic(output_dir / "input_material_manifest.json", input_manifest)
    write_atomic(output_dir / "capability_manifest.json", capability_manifest)
    summary = {
        "ok": input_manifest["result_status"] == "verified"
        and capability_manifest["result_status"] == "verified",
        "mode": args.mode,
        "output_dir": str(output_dir),
        "input_status": input_manifest["result_status"],
        "capability_status": capability_manifest["result_status"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
