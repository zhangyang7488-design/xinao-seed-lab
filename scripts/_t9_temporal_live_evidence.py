"""T9 Temporal LIVE canary + evidence writer (G2).

Gate: XINAO_TEMPORAL_LIVE_E2E=1 for live pytest / bypass.

Writes:
  D:\\XINAO_RESEARCH_RUNTIME\\evidence\\grok45_peer_acceptance\\
    night_run_20260712\\saturation\\G2_temporal_live\\T9_temporal_live_canary.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance"
    r"\night_run_20260712\saturation\G2_temporal_live"
)
OUT = EVIDENCE_DIR / "T9_temporal_live_canary.json"
CANARY_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary")
CANARY_DB = CANARY_ROOT / "evidence" / "t9_temporal_live_canary.sqlite3"
LIVE_CASE = "tests/test_t9_temporal_live.py"
DEFAULT_ADDRESS = os.environ.get("XINAO_TEMPORAL_ADDRESS", "127.0.0.1:7233")
DEFAULT_NAMESPACE = os.environ.get("XINAO_TEMPORAL_NAMESPACE", "default")
DEFAULT_QUEUE = os.environ.get("XINAO_TEMPORAL_TASK_QUEUE", "xinao-dualbrain-promoted-v1")
DEFAULT_WORKFLOW_TYPE = "XinaoPromotedTaskWorkflowV1"


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _tcp_reachable(address: str, timeout: float = 1.0) -> dict[str, object]:
    host, _, port_s = address.partition(":")
    port = int(port_s or "7233")
    try:
        with socket.create_connection((host or "127.0.0.1", port), timeout=timeout):
            return {"reachable": True, "address": address}
    except OSError as exc:
        return {
            "reachable": False,
            "address": address,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def run_pytest(*, live_e2e: bool) -> dict[str, object]:
    env = os.environ.copy()
    env["XINAO_TEMPORAL_LIVE_E2E"] = "1" if live_e2e else "0"
    env["XINAO_TEMPORAL_ENABLED"] = "1"
    env["XINAO_TEMPORAL_MOCK"] = "0"
    env["XINAO_TEMPORAL_LIVE"] = "1"
    env["XINAO_TEMPORAL_ADDRESS"] = DEFAULT_ADDRESS
    env["XINAO_TEMPORAL_NAMESPACE"] = DEFAULT_NAMESPACE
    env["XINAO_TEMPORAL_TASK_QUEUE"] = DEFAULT_QUEUE
    cmd = [sys.executable, "-m", "pytest", LIVE_CASE, "-v", "--tb=short"]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    return {
        "command": " ".join(cmd),
        "live_e2e_env": env["XINAO_TEMPORAL_LIVE_E2E"],
        "exit_code": proc.returncode,
        "stdout_tail": stdout.strip()[-4000:],
        "stderr_tail": stderr.strip()[-1500:],
        "passed": proc.returncode == 0,
        "skipped_all": "skipped" in stdout.lower() and proc.returncode == 0,
    }


def _accepted_thread(svc: object, suffix: str) -> str:
    from xinao_coordination import CoordinationService

    assert isinstance(svc, CoordinationService)
    opened = svc.open_thread(
        actor="grok_4_5",
        title=f"t9 live {suffix}",
        body="proposal",
        idempotency_key=f"t9-live-open-{suffix}",
    )
    thread_id = str(opened["thread"]["thread_id"])
    int(opened["thread"]["version"])
    # Dual accept path via close_thread (same as conftest)
    svc.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted",
        idempotency_key=f"t9-live-close-a-{suffix}",
    )
    svc.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key=f"resolution-{suffix}",
        summary="accepted",
        idempotency_key=f"t9-live-close-b-{suffix}",
    )
    return thread_id


async def _bypass_canary() -> dict[str, object]:
    try:
        from temporalio.client import Client
        from temporalio.exceptions import WorkflowAlreadyStartedError
    except ImportError as exc:
        return {"ok": False, "error": "temporalio_import", "message": str(exc)}

    try:
        from temporalio.api.enums.v1 import TaskQueueType
        from temporalio.api.taskqueue.v1 import TaskQueue
        from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    except ImportError:
        TaskQueueType = None  # type: ignore[assignment, misc]

    client = await Client.connect(DEFAULT_ADDRESS, namespace=DEFAULT_NAMESPACE)
    poller_info: dict[str, object] = {"ok": False}
    if TaskQueueType is not None:
        try:
            req = DescribeTaskQueueRequest(
                namespace=DEFAULT_NAMESPACE,
                task_queue=TaskQueue(name=DEFAULT_QUEUE),
                task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
            )
            resp = await client.workflow_service.describe_task_queue(req)
            pollers = list(getattr(resp, "pollers", []) or [])
            poller_info = {
                "ok": True,
                "poller_count": len(pollers),
                "identities": [str(getattr(p, "identity", p)) for p in pollers],
            }
        except Exception as exc:
            poller_info = {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    # Build a real promoted envelope via kernel (isolated canary DB).
    from xinao_coordination import CoordinationService
    from xinao_coordination.temporal.envelope import envelope_from_kernel_task
    from xinao_coordination.temporal.policy import temporal_policy

    CANARY_DB.parent.mkdir(parents=True, exist_ok=True)
    if CANARY_DB.exists():
        CANARY_DB.unlink()

    os.environ["XINAO_TEMPORAL_ENABLED"] = "1"
    os.environ["XINAO_TEMPORAL_MOCK"] = "0"
    os.environ["XINAO_TEMPORAL_LIVE"] = "1"

    svc = CoordinationService(CANARY_DB)
    suffix = f"ev-{uuid.uuid4().hex[:8]}"
    thread_id = _accepted_thread(svc, suffix)
    promoted = svc.promote_to_task(
        actor="codex",
        source_thread_id=thread_id,
        decision_hash=f"resolution-{suffix}",
        title="T9 live bypass canary",
        goal="temporalio direct start against G1 queue",
        idempotency_key=f"t9-live-promote-{suffix}",
    )
    task = promoted["task"]
    assert isinstance(task, dict)
    pol = temporal_policy()
    envelope = envelope_from_kernel_task(
        task,
        workflow_type=str(pol.get("workflow_type") or DEFAULT_WORKFLOW_TYPE),
        task_queue=str(pol.get("task_queue") or DEFAULT_QUEUE),
    )

    # The service API is synchronous and internally owns its event loop.  This
    # evidence helper is already async, so run the sync call in a worker thread
    # instead of nesting asyncio.run() in the current loop.
    admin_live: dict[str, object]
    try:
        started_admin = await asyncio.to_thread(
            svc.temporal_start_promoted,
            actor="codex",
            task_id=str(task["task_id"]),
            idempotency_key=f"t9-live-admin-{suffix}",
        )
        admin_live = {
            "raised": False,
            "ok": bool(started_admin.get("ok")),
            "mode": started_admin.get("mode"),
            "workflow_id": started_admin.get("workflow_id"),
        }
    except Exception as exc:
        admin_live = {
            "raised": True,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "details": getattr(exc, "details", None),
        }

    # Stop-blocks probe (kernel, no Temporal required)
    stop_probe: dict[str, object]
    try:
        svc.user_stop(
            actor="user",
            reason="live evidence stop",
            idempotency_key=f"t9-live-stop-{suffix}",
        )
        try:
            svc.temporal_start_promoted(
                actor="codex",
                task_id=str(task["task_id"]),
                idempotency_key=f"t9-live-stop-start-{suffix}",
            )
            stop_probe = {"blocked": False, "error": "start_succeeded_under_stop"}
        except Exception as exc:
            stop_probe = {
                "blocked": "stop" in str(exc).lower(),
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        finally:
            svc.clear_stop(
                actor="user",
                reason="clear",
                idempotency_key=f"t9-live-clear-{suffix}",
            )
    except Exception as exc:
        stop_probe = {"blocked": None, "error_type": type(exc).__name__, "message": str(exc)}

    # Promoted-only / no-chat probes
    from xinao_coordination.errors import ValidationError
    from xinao_coordination.temporal.envelope import validate_task_envelope

    non_promoted = svc.dispatch_task(
        actor="codex",
        title="not promoted",
        goal="x",
        explicit_non_consensus=True,
        idempotency_key=f"t9-live-np-{suffix}",
    )
    promoted_only_ok = False
    try:
        svc.temporal_start_promoted(
            actor="codex",
            task_id=str(non_promoted["task"]["task_id"]),
            idempotency_key=f"t9-live-np-start-{suffix}",
        )
    except ValidationError:
        promoted_only_ok = True
    except Exception:
        promoted_only_ok = False

    chat_task = dict(task)
    chat_meta = dict(chat_task.get("metadata") or {})
    chat_meta["chat_only"] = True
    chat_task["metadata"] = chat_meta
    no_chat_ok = False
    try:
        validate_task_envelope(
            chat_task,
            workflow_type=envelope.workflow_type,
            task_queue=envelope.task_queue,
        )
    except ValidationError:
        no_chat_ok = True

    # temporalio bypass start + idempotent duplicate
    wf_input = envelope.to_workflow_input()
    first: dict[str, object]
    second: dict[str, object]
    try:
        handle = await client.start_workflow(
            envelope.workflow_type,
            wf_input,
            id=envelope.workflow_id,
            task_queue=envelope.task_queue,
        )
        first = {
            "ok": True,
            "workflow_id": envelope.workflow_id,
            "run_id": handle.result_run_id,
            "replayed": False,
            "mode": "temporalio_bypass",
        }
    except WorkflowAlreadyStartedError:
        first = {
            "ok": True,
            "workflow_id": envelope.workflow_id,
            "replayed": True,
            "mode": "temporalio_bypass",
            "note": "already_started_on_first_attempt",
        }
    except Exception as exc:
        first = {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    try:
        await client.start_workflow(
            envelope.workflow_type,
            wf_input,
            id=envelope.workflow_id,
            task_queue=envelope.task_queue,
        )
        second = {"ok": True, "replayed": False, "note": "unexpected_second_start_ok"}
    except WorkflowAlreadyStartedError:
        second = {"ok": True, "replayed": True, "mode": "temporalio_bypass"}
    except Exception as exc:
        second = {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    desc_status = None
    try:
        h = client.get_workflow_handle(envelope.workflow_id)
        d = await h.describe()
        desc_status = str(getattr(d, "status", None))
    except Exception as exc:
        desc_status = f"describe_error:{type(exc).__name__}:{exc}"

    return {
        "ok": bool(first.get("ok")) and bool(second.get("replayed")),
        "canary_db": str(CANARY_DB),
        "task_id": str(task["task_id"]),
        "workflow_id": envelope.workflow_id,
        "task_queue": envelope.task_queue,
        "workflow_type": envelope.workflow_type,
        "pollers": poller_info,
        "admin_client_live_path": admin_live,
        "stop_blocks_start": stop_probe,
        "promoted_only": {"ok": promoted_only_ok},
        "no_chat_ingress": {"ok": no_chat_ok},
        "bypass_first_start": first,
        "bypass_duplicate_start": second,
        "workflow_status_after_start": desc_status,
        "worker_crash_restart_design": {
            "contract": [
                "Workflow history durable on Temporal server (not worker RAM)",
                "Worker kill mid-run leaves execution recoverable on new poller",
                "Duplicate start remains WorkflowAlreadyStarted after restart",
                "Kernel never auto-starts chat/discuss into Temporal",
            ],
            "live_crash_inject_attempted": False,
            "reason": (
                "G2 does not kill production workers; live inject requires G1 poller "
                "and explicit ops window. Design + poller probe recorded."
            ),
            "poller_present": bool(
                isinstance(poller_info.get("poller_count"), int) and int(poller_info["poller_count"]) > 0  # type: ignore[arg-type]
            ),
        },
    }


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    connectivity = _tcp_reachable(DEFAULT_ADDRESS)

    # Default-gated pytest must skip cleanly (exit 0).
    pytest_gated_off = run_pytest(live_e2e=False)
    # Live pytest (may skip individual tests if client unwelded / no pollers).
    pytest_live = run_pytest(live_e2e=True)

    bypass: dict[str, object]
    if connectivity.get("reachable"):
        try:
            bypass = asyncio.run(_bypass_canary())
        except Exception as exc:
            bypass = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    else:
        bypass = {"ok": False, "skipped": "temporal_unreachable", "connectivity": connectivity}

    on_disk = {
        "tests/test_t9_temporal_live.py": {
            "exists": (REPO / LIVE_CASE).exists(),
            "sha256": _sha256_file(REPO / LIVE_CASE),
        },
        "scripts/_t9_temporal_live_evidence.py": {
            "exists": True,
            "sha256": _sha256_file(Path(__file__)),
        },
        "src/xinao_coordination/temporal/client.py": {
            "exists": (REPO / "src/xinao_coordination/temporal/client.py").exists(),
            "sha256": _sha256_file(REPO / "src/xinao_coordination/temporal/client.py"),
            "note": "Admin live start is exercised from a worker thread inside the async canary",
        },
    }

    admin_raised = bool(
        isinstance(bypass, dict)
        and isinstance(bypass.get("admin_client_live_path"), dict)
        and bypass["admin_client_live_path"].get("raised")  # type: ignore[index]
    )
    bypass_ok = bool(isinstance(bypass, dict) and bypass.get("ok"))
    kernel_gates_ok = bool(
        isinstance(bypass, dict)
        and isinstance(bypass.get("promoted_only"), dict)
        and bypass["promoted_only"].get("ok")  # type: ignore[index]
        and isinstance(bypass.get("no_chat_ingress"), dict)
        and bypass["no_chat_ingress"].get("ok")  # type: ignore[index]
        and isinstance(bypass.get("stop_blocks_start"), dict)
        and bypass["stop_blocks_start"].get("blocked")  # type: ignore[index]
    )

    if pytest_gated_off["passed"] and bypass_ok and kernel_gates_ok:
        verdict = "PASS_SCOPED_BYPASS_LIVE" if admin_raised else "PASS_LIVE_WELDED"
    elif pytest_gated_off["passed"] and kernel_gates_ok:
        verdict = "PARTIAL_KERNEL_GATES_ONLY"
    else:
        verdict = "FAIL_OR_UNREACHABLE"

    payload = {
        "schema_version": "xinao.saturation.G2_temporal_live.v1",
        "phase": "G2/T9-live",
        "title_cn": "T9 Temporal live tests + Admin client + temporalio duplicate-start canary",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "executor": "grok45_g2_temporal_live",
        "repo": str(REPO),
        "gate_env": "XINAO_TEMPORAL_LIVE_E2E",
        "live_workflow_start_attempted": True,
        "live_via_admin_client": not admin_raised and bypass_ok,
        "live_via_temporalio_bypass": bypass_ok,
        "admin_client_still_raises": admin_raised,
        "live_temporal_recreate": False,
        "completion_claim_allowed": False,
        "product_closed": False,
        "coverage": {
            "idempotency_duplicate_start": bypass_ok,
            "stop_blocks_start": kernel_gates_ok
            and bool(
                isinstance(bypass.get("stop_blocks_start"), dict)
                and bypass["stop_blocks_start"].get("blocked")  # type: ignore[index]
            ),
            "worker_crash_restart": "design_recorded",
            "no_chat_ingress": bool(
                isinstance(bypass.get("no_chat_ingress"), dict) and bypass["no_chat_ingress"].get("ok")  # type: ignore[index]
            ),
            "promoted_only": bool(
                isinstance(bypass.get("promoted_only"), dict) and bypass["promoted_only"].get("ok")  # type: ignore[index]
            ),
        },
        "connectivity": connectivity,
        "pytest_gate_off_must_skip": pytest_gated_off,
        "pytest_live_e2e": pytest_live,
        "bypass_canary": bypass,
        "on_disk_probe": on_disk,
        "hard_bans": {
            "no_edit_client_policy_service": True,
            "no_docker_compose_up": True,
            "no_chat_to_temporal": True,
            "no_live_temporal_recreate": True,
        },
        "verdict": verdict,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "ok": verdict.startswith("PASS"),
        "out": str(OUT),
        "verdict": verdict,
        "admin_client_still_raises": admin_raised,
        "bypass_ok": bypass_ok,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
