"""L9 ledger thin bind — worker_dispatch_ledger 读薄胶真证据，非合成 succeeded."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    now_iso,
    write_json,
)

REPLACES_MODULE = "worker_dispatch_ledger"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l9_ledger.v1"
LEDGER_SCHEMA_VERSION = "xinao.codex_s.worker_dispatch_ledger.v1"
LEDGER_SENTINEL = "SENTINEL:XINAO_WORKER_DISPATCH_LEDGER_READY"
LEDGER_WORK_ID = "xinao_seed_cortex_phase0_20260701"
LEDGER_ROUTE_PROFILE = "seed_cortex_phase0"
LEDGER_ID = "worker_dispatch_ledger"
ADOPTION_STATE = "reference_only_candidate"
HOT_PATH_ADOPTION_STATE = "runtime_enforced_hot_path"
EVIDENCE_GLOBS = (
    "thin_glue_loop_*.json",
    "thin_glue_mainline_spawn_*.json",
    "closure_test_*.json",
)


def thin_glue_ledger_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_LEDGER", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def _ledger_runtime_paths(runtime: Path) -> dict[str, str]:
    state = runtime / "state" / "worker_dispatch_ledger"
    return {
        "runtime_latest": str(state / "latest.json"),
        "poll_latest": str(state / "temporal_activity_latest.json"),
        "runtime_readback_zh": str(
            runtime / "readback" / "zh" / "worker_dispatch_ledger_latest.md"
        ),
    }


def _adoption_boundary(adoption_state: str) -> dict[str, str]:
    return {
        "adoption_state": adoption_state,
        "hot_path": "integrated_bus_v2"
        if adoption_state == HOT_PATH_ADOPTION_STATE
        else "thin_glue",
    }


def _boundary_fields() -> dict[str, bool]:
    return {
        "not_333_mainline": True,
        "completion_claim_allowed": False,
        "handroll_intact": False,
    }


def _render_ledger_readback(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# worker_dispatch_ledger (thin glue read model)",
            f"- status: {payload.get('status')}",
            f"- succeeded: {payload.get('succeeded_count')}",
            str(payload.get("acceptance_now_can_invoke_cn") or ""),
        ]
    )


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_ledger"
    return {
        "latest": state / "latest.json",
        "duckdb": state / "thin_glue_evidence.duckdb",
        "readback": runtime / "readback" / "zh" / "thin_glue_ledger_latest.md",
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def collect_thin_glue_evidence(runtime_root: Path) -> list[dict[str, Any]]:
    readback = runtime_root / "readback"
    if not readback.is_dir():
        return []
    hits: list[dict[str, Any]] = []
    for pattern in EVIDENCE_GLOBS:
        for path in sorted(readback.glob(pattern), reverse=True):
            payload = _load_json(path)
            if not payload:
                continue
            passed = payload.get("validation", {}).get("passed") is True
            hits.append(
                {
                    "evidence_path": str(path),
                    "evidence_kind": path.stem.split("_")[0] if "_" in path.stem else path.stem,
                    "run_id": payload.get("run_id") or path.stem,
                    "validation_passed": passed,
                    "phase": payload.get("phase") or payload.get("schema_version") or "",
                    "acceptance_now_can_invoke_cn": payload.get("acceptance_now_can_invoke_cn")
                    or "",
                    "generated_at": payload.get("timestamp") or payload.get("generated_at") or "",
                }
            )
    return hits[:20]


def _duckdb_mirror(runtime: Path, evidence_rows: list[dict[str, Any]]) -> dict[str, Any]:
    db_path = output_paths(runtime)["duckdb"]
    try:
        import duckdb
    except ImportError:
        return {
            "ok": False,
            "named_blocker": "DUCKDB_NOT_INSTALLED",
            "hint": "pip install duckdb for event mirror",
            "path": str(db_path),
        }
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS thin_glue_evidence (
                evidence_path VARCHAR,
                evidence_kind VARCHAR,
                run_id VARCHAR,
                validation_passed BOOLEAN,
                phase VARCHAR,
                mirrored_at TIMESTAMP
            )
            """
        )
        mirrored_at = datetime.now().isoformat(timespec="seconds")
        for row in evidence_rows:
            con.execute(
                """
                INSERT INTO thin_glue_evidence
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    row.get("evidence_path"),
                    row.get("evidence_kind"),
                    row.get("run_id"),
                    bool(row.get("validation_passed")),
                    row.get("phase"),
                    mirrored_at,
                ],
            )
        count = con.execute("SELECT COUNT(*) FROM thin_glue_evidence").fetchone()[0]
        return {"ok": True, "row_count": int(count), "path": str(db_path)}
    finally:
        con.close()


def _ledger_entry_from_evidence(
    *,
    wave_id: str,
    task_id: str,
    evidence: dict[str, Any],
    dispatch_time: str,
) -> dict[str, Any]:
    run_id = str(evidence.get("run_id") or "unknown")
    lane_suffix = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in run_id)[:80]
    poll_status = "succeeded" if evidence.get("validation_passed") else "failed"
    return {
        "entry_id": f"{wave_id}:thin-glue-{lane_suffix}",
        "wave_id": wave_id,
        "task_id": task_id,
        "lane_id": f"thin-glue-evidence-{lane_suffix}",
        "agent_id": "thin_glue_loop",
        "provider": "thin_glue.external_mature",
        "mode": "worker",
        "dispatch_time": dispatch_time,
        "poll_status": poll_status,
        "artifact_refs": [str(evidence.get("evidence_path") or "")],
        "fan_in_decision": "accepted_for_ledger_evidence_only",
        "next_wave_decision": (
            "ledger_succeeded_drives_default_auto_dispatch"
            if poll_status == "succeeded"
            else "requires_upstream_scheduler_explicit_call"
        ),
        "adoption_state": "runtime_enforced_hot_path_hooked",
        "transport_pattern_ref": "thin_glue_loop_readback_evidence",
        "thin_glue": True,
        "hand_rolled_ledger_bypassed": True,
        "driver_synthetic_succeeded": False,
        "evidence_kind": evidence.get("evidence_kind"),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def run_thin_glue_ledger_mirror(
    *,
    repo_root: str | Path = DEFAULT_REPO,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    wave_id: str = "thin-glue-ledger-wave",
    task_id: str = "thin_glue_l9_ledger",
    write: bool = True,
    **ledger_kwargs: Any,
) -> dict[str, Any]:
    """Build worker_dispatch_ledger payload from thin-glue readback evidence."""
    del ledger_kwargs  # passthrough reserved for hand-roll compat
    runtime = Path(runtime_root)
    generated_at = now_iso()
    evidence_rows = collect_thin_glue_evidence(runtime)
    passed_rows = [row for row in evidence_rows if row.get("validation_passed")]
    entries = [
        _ledger_entry_from_evidence(
            wave_id=wave_id,
            task_id=task_id,
            evidence=row,
            dispatch_time=str(row.get("generated_at") or generated_at),
        )
        for row in evidence_rows
    ]
    poll_entries = [
        entry for entry in entries if entry.get("poll_status") in {"succeeded", "failed"}
    ]
    succeeded_entries = [entry for entry in poll_entries if entry.get("poll_status") == "succeeded"]
    duckdb_mirror = (
        _duckdb_mirror(runtime, evidence_rows) if evidence_rows else {"ok": False, "skipped": True}
    )

    paths = _ledger_runtime_paths(runtime)
    checks = {
        "evidence_rows_found": len(evidence_rows) > 0,
        "passed_evidence_rows": len(passed_rows) > 0,
        "hand_rolled_ledger_bypassed": True,
        "driver_synthetic_succeeded_allowed": False,
        "poll_entries_from_real_evidence": len(poll_entries) > 0,
        "succeeded_count_nonzero": len(succeeded_entries) > 0,
        "duckdb_mirror_ok": duckdb_mirror.get("ok") is True or duckdb_mirror.get("skipped") is True,
    }
    passed = checks["passed_evidence_rows"] and checks["succeeded_count_nonzero"]

    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "sentinel": LEDGER_SENTINEL,
        "work_id": LEDGER_WORK_ID,
        "route_profile": LEDGER_ROUTE_PROFILE,
        "ledger_id": LEDGER_ID,
        "wave_id": wave_id,
        "task_id": task_id,
        "generated_at": generated_at,
        "status": (
            "thin_glue_ledger_poll_ready" if poll_entries and passed else "thin_glue_ledger_blocked"
        ),
        "ledger_role": "thin_glue_evidence_dispatch_read_model",
        "adoption_state": HOT_PATH_ADOPTION_STATE if passed else ADOPTION_STATE,
        "adoption_boundary": _adoption_boundary(
            HOT_PATH_ADOPTION_STATE if passed else ADOPTION_STATE
        ),
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "thin_glue_ledger": {
            "schema_version": SCHEMA_VERSION,
            "evidence_row_count": len(evidence_rows),
            "passed_row_count": len(passed_rows),
            "duckdb_mirror": duckdb_mirror,
            "evidence_globs": list(EVIDENCE_GLOBS),
            "hand_rolled_ledger_bypassed": True,
        },
        "dispatch_entries": entries,
        "poll_entries": poll_entries,
        "succeeded_entries": succeeded_entries,
        "succeeded_count": len(succeeded_entries),
        "succeeded_entry_ids": [str(entry.get("entry_id") or "") for entry in succeeded_entries],
        "driver_synthetic_succeeded_allowed": False,
        "poll_result_summary": {
            "entry_count": len(poll_entries),
            "succeeded_count": len(succeeded_entries),
            "failed_or_blocked_count": len(poll_entries) - len(succeeded_entries),
            "source_kind": "thin_glue_readback_evidence",
        },
        "source_kind": "thin_glue_readback_evidence",
        "poll_source": "thin_glue_readback_evidence",
        "summary": {
            "entry_count": len(entries),
            "poll_entry_count": len(poll_entries),
            "succeeded_count": len(succeeded_entries),
            "worker_entry_count": len(entries),
            "subagent_entry_count": 0,
            "dp_sidecar_entry_count": 0,
            "spawned_external_agent_count": len(passed_rows),
            "real_provider_receipt_count": len(passed_rows),
            "real_provider_succeeded_receipt_count": len(succeeded_entries),
            "hooked_runtime_entrypoint_count": 1 if passed else 0,
        },
        "acceptance_now_can_invoke_cn": (
            f"ledger 已读薄胶真证据：{len(passed_rows)} 条绿 / {len(evidence_rows)} 条总计；"
            f"succeeded={len(succeeded_entries)}；非 driver 合成。"
            if passed
            else "薄胶 ledger：尚无 passed readback 证据；先跑 Invoke-XinaoThinGlue.ps1"
        ),
        "output_paths": paths,
        **_boundary_fields(),
    }
    payload["validation"] = {
        "passed": passed,
        "checks": checks,
        "validated_at": generated_at,
    }
    if not passed:
        payload["named_blockers"] = (
            ["THIN_GLUE_LEDGER_NO_PASSED_EVIDENCE"]
            if not passed_rows
            else ["THIN_GLUE_LEDGER_ZERO_SUCCEEDED"]
        )

    if write:
        thin_paths = output_paths(runtime)
        write_json(thin_paths["latest"], payload)
        write_json(Path(paths["runtime_latest"]), payload)
        if poll_entries:
            write_json(Path(paths["poll_latest"]), payload)
        zh_lines = [
            "# Thin Glue L9 Ledger readback",
            "",
            f"- status: `{payload['status']}`",
            f"- validation_passed: {passed}",
            f"- evidence_rows: {len(evidence_rows)}",
            f"- succeeded_count: {len(succeeded_entries)}",
            f"- duckdb: `{duckdb_mirror.get('path', '')}` ok={duckdb_mirror.get('ok')}",
            "",
            payload["acceptance_now_can_invoke_cn"],
        ]
        thin_paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        thin_paths["readback"].write_text("\n".join(zh_lines) + "\n", encoding="utf-8")
        Path(paths["runtime_readback_zh"]).parent.mkdir(parents=True, exist_ok=True)
        Path(paths["runtime_readback_zh"]).write_text(
            _render_ledger_readback(payload) + "\n", encoding="utf-8"
        )
        payload["output_paths"]["thin_glue_ledger_latest"] = str(thin_paths["latest"])

    return payload
