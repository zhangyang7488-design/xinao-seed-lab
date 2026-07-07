import datetime as dt
import json
import pathlib
from typing import Any

GATE_WAITING_STATUS = "WAITING_GROK_SEGMENT_AUDIT"
GATE_PASS_STATUS = "GROK_SEGMENT_AUDIT_PASS"
GATE_FAIL_STATUS = "GROK_SEGMENT_AUDIT_FAIL"
GATE_HOLD_STATUS = "GROK_SEGMENT_AUDIT_HOLD"
GATE_TIMEOUT_CODEXA_BRAIN_FALLBACK_STATUS = "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK"
GATE_READY_STATUS = "SEGMENT_COMPLETE_WAITING_GROK_HOTPATH_READY"
SEGMENT_GATE_PASS = "pass"
SEGMENT_GATE_NOT_READY = "segment_audit_not_ready"
SEGMENT_AUDIT_REQUIRED_BLOCKER = "GROK_SEGMENT_AUDIT_REQUIRED"
SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED_BLOCKER = "GROK_SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED"
SEGMENT_AUDIT_WAITING_BLOCKER = "WAITING_GROK_SEGMENT_AUDIT"
SEGMENT_AUDIT_VERDICT_REQUIRED_BLOCKER = "GROK_SEGMENT_AUDIT_VERDICT_REQUIRED"
SEGMENT_AUDIT_TIMEOUT_FALLBACK_BLOCKER = "GROK_180S_NO_REPLY_CODEXA_BRAIN_FALLBACK_L1"
SEGMENT_SUMMON_REQUIRED_BLOCKER = "CODEX_TO_GROK_SEGMENT_AUDIT_SUMMON_REQUIRED"
SEGMENT_LEG2_REQUIRED_BLOCKER = "GROK_SEGMENT_AUDIT_LEG2_EVIDENCE_REQUIRED"
GROK_REPLY_TIMEOUT_SECONDS = 180
CONTINUATION_AUTHORIZATION_LANE = "codex_a_brain_dispatch"
CONTINUATION_GATE_OWNER = "codex_a_brain_plus_temporal_assignment_dag"
SEGMENT_AUDIT_REVIEWER_LANE = "grok_segment_audit"
SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE = "grok_segment_audit_dual_visible_and_backend_verdict"
SEGMENT_AUDIT_AUTHORIZATION_LANE = SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE


def _authorization_fields() -> dict[str, Any]:
    return {
        "reviewer_lane": SEGMENT_AUDIT_REVIEWER_LANE,
        "authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_verdict_authorization_lane": SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE,
        "segment_audit_scope": "phase_exit_only",
        "mainchain_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_gate_owner": CONTINUATION_GATE_OWNER,
        "waiting_grok_blocks_continuation": False,
        "waiting_grok_blocks_completion_stop_l2": True,
        "grok_mainchain_authorization_allowed": False,
    }


def _read_json(path: pathlib.Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(default or {})
    return payload if isinstance(payload, dict) else dict(default or {})


def _normalize_delivery_mode(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed


def _age_seconds(value: Any) -> int | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    now = dt.datetime.now(parsed.tzinfo)
    return max(0, int((now - parsed).total_seconds()))


def _write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _worker_evidence_success(worker: dict[str, Any]) -> bool:
    if not isinstance(worker, dict) or not worker:
        return False
    if worker.get("ok") is False:
        return False
    if str(worker.get("status") or "").upper() == "FAIL":
        return False
    if str(worker.get("named_blocker") or "").strip():
        return False
    exit_code = worker.get("exit_code")
    if exit_code is not None and str(exit_code) not in {"", "0"}:
        return False
    return bool(
        worker.get("status") == "activity_gate_checked"
        or worker.get("expected_marker_seen") is True
        or worker.get("ok") is True
        or str(worker.get("status") or "").upper() in {"PASS", "SUCCESS"}
    )


def _safe_task_file_id(task_id: str) -> str:
    safe = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in "-_.")
    return safe or str(abs(hash(str(task_id))))


def _codex_to_grok_segment_audit_summon_valid(
    runtime: pathlib.Path,
    task_id: str,
    segment_id: str = "",
) -> tuple[bool, dict[str, Any]]:
    safe_task_id = _safe_task_file_id(task_id)
    summon_root = runtime / "state" / "codex_to_grok_segment_audit_summon"
    summon = _read_json(summon_root / "tasks" / f"{safe_task_id}.json", {})
    if not summon or str(summon.get("task_id") or "") != str(task_id):
        return False, summon
    delivery_mode = _normalize_delivery_mode(summon.get("delivery_mode"))
    if delivery_mode not in {"backend_only_state", "dual_visible_and_backend"}:
        return False, summon
    if segment_id and str(summon.get("segment_id") or "") and str(summon.get("segment_id") or "") != str(segment_id):
        return False, summon
    if delivery_mode == "backend_only_state":
        action_trace_ref = pathlib.Path(
            str(summon.get("action_delivery_trace_ref") or runtime / "state" / "action_delivery_trace" / f"{safe_task_id}.jsonl")
        )
        window_id = str(summon.get("window_id") or "")
        try:
            lines = action_trace_ref.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return False, summon
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if (
                str(event.get("task_id") or "") == str(task_id)
                and str(event.get("window_id") or "") == window_id
                and str(event.get("event_name") or "") == "codex_to_grok_segment_audit_summon.backend_state_written"
            ):
                summon["frontend_tui_cross_check_valid"] = False
                summon["backend_state_cross_check_valid"] = True
                summon["leg1_cross_check_valid"] = True
                summon["visible_frontend_disabled_by_stop_order"] = True
                return True, summon
        return False, summon
    visible_trace_ref = pathlib.Path(
        str(summon.get("visible_trace_task_ref") or summon.get("visible_trace_ref") or summon_root / "visible_trace" / "latest.json")
    )
    visible_trace = _read_json(visible_trace_ref, {})
    if str(visible_trace.get("task_id") or "") != str(task_id):
        return False, summon
    if segment_id and str(visible_trace.get("segment_id") or "") and str(visible_trace.get("segment_id") or "") != str(segment_id):
        return False, summon
    if str(visible_trace.get("action_delivery_trace_task_id") or "") != str(task_id):
        return False, summon
    if visible_trace.get("session_modified_or_inbox_written") is not True:
        return False, summon
    if visible_trace.get("action_delivery_trace_same_window") is not True:
        return False, summon
    window_id = str(summon.get("window_id") or visible_trace.get("window_id") or "")
    if not window_id or str(visible_trace.get("window_id") or "") != window_id:
        return False, summon
    action_trace_ref = pathlib.Path(
        str(summon.get("action_delivery_trace_ref") or runtime / "state" / "action_delivery_trace" / f"{safe_task_id}.jsonl")
    )
    try:
        lines = action_trace_ref.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return False, summon
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        if (
            str(event.get("task_id") or "") == str(task_id)
            and str(event.get("window_id") or "") == window_id
            and str(event.get("event_name") or "") == "codex_to_grok_segment_audit_summon.sent"
        ):
            runtime_default = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
            is_default_runtime = runtime.resolve() == runtime_default
            frontend_ref = pathlib.Path(
                str(
                    summon.get("frontend_tui_send_ref")
                    or summon_root / "frontend_tui_send" / "tasks" / f"{safe_task_id}.json"
                )
            )
            frontend = _read_json(frontend_ref, {})
            if str(frontend.get("task_id") or "") != str(task_id):
                return False, summon
            required_frontend_flags = (
                "frontend_tui_sent",
                "session_modified_after_send",
                "input_area_clicked_before_paste",
                "submit_enter_sent_after_paste",
                "native_keybd_event_typeahead",
                "old_inbox_only_is_not_full_visible_delivery",
                "rescue_cockpit_channel_preserved",
            )
            for flag in required_frontend_flags:
                if frontend.get(flag) is not True:
                    return False, summon
            summon["frontend_tui_cross_check_valid"] = bool(
                str(frontend.get("task_id") or "") == str(task_id)
                and frontend.get("frontend_tui_sent") is True
                and frontend.get("session_modified_after_send") is True
            )
            return True, summon
    return False, summon


def _grok_segment_verdict_leg2_valid(
    runtime: pathlib.Path,
    task_id: str,
    grok_task: dict[str, Any],
    leg1_summon: dict[str, Any],
    segment_id: str = "",
) -> tuple[bool, dict[str, Any]]:
    if not grok_task or str(grok_task.get("task_id") or "") != str(task_id):
        return False, {"reason": "missing_task_scoped_grok_verdict"}
    if segment_id and str(grok_task.get("segment_id") or "") and str(grok_task.get("segment_id") or "") != str(segment_id):
        return False, {"reason": "segment_mismatch"}
    if _normalize_delivery_mode(grok_task.get("verdict_delivery_mode") or grok_task.get("delivery_mode")) != "dual_visible_and_backend":
        return False, {"reason": "leg2_not_dual_visible_and_backend"}
    if grok_task.get("dual_visible_and_backend_verdict") is not True:
        return False, {"reason": "leg2_dual_flag_missing"}
    if grok_task.get("backend_only_verdict") is True or grok_task.get("backend_only_verdict_seen") is True:
        return False, {"reason": "backend_only_verdict_seen"}
    leg1_ref = str(leg1_summon.get("backend_task_ref") or leg1_summon.get("task_ref") or "")
    grok_leg1_ref = str(grok_task.get("leg1_summon_ref") or "")
    if not leg1_ref or not grok_leg1_ref or pathlib.Path(grok_leg1_ref) != pathlib.Path(leg1_ref):
        return False, {"reason": "leg1_ref_mismatch", "expected": leg1_ref, "actual": grok_leg1_ref}
    if grok_task.get("leg1_summon_cross_check_valid") is not True:
        return False, {"reason": "leg1_cross_check_missing_in_leg2"}
    evidence_refs = [str(item) for item in grok_task.get("evidence_refs", []) if item]
    if not any("codexa_managed_visible_inject" in item for item in evidence_refs) and not str(grok_task.get("visible_inject_sha256") or ""):
        return False, {"reason": "leg2_visible_delivery_missing"}
    if not any("action_delivery_trace" in item for item in evidence_refs):
        return False, {"reason": "leg2_action_trace_missing"}
    return True, {
        "reason": "",
        "grok_verdict_ref": str(runtime / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{_safe_task_file_id(task_id)}.json"),
        "leg1_summon_ref": grok_leg1_ref,
        "visible_inject_sha256": str(grok_task.get("visible_inject_sha256") or ""),
        "evidence_refs": evidence_refs,
    }


def write_grok_segment_audit_request(
    runtime_root: pathlib.Path | str,
    task_id: str,
    *,
    segment_id: str = "phase0_phase1",
    source_activity: str = "segment_audit_gate_activity",
    notify_source: str = "segment_audit_ready_projection",
) -> dict[str, Any]:
    runtime = pathlib.Path(runtime_root)
    task_id = str(task_id)
    payload = {
        "schema_version": "xinao.grok_segment_audit_request.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        **_authorization_fields(),
        "task_id": task_id,
        "source_task_id": task_id,
        "predecessor_task_id": task_id,
        "segment_id": segment_id,
        "status": "grok_segment_audit_request_rescue_read_model",
        "request_state": "rescue_read_model_waiting_full_dual_delivery",
        "segment_audit_ready": True,
        "grok_notified": True,
        "notification_mode": "read_model_notify_no_chat_window_push",
        "notify_v1_default_retired": True,
        "notify_pending_as_mainline": False,
        "not_leg1": True,
        "not_full_visible": True,
        "release_requires_bidirectional_dual_delivery_full_ring": True,
        "grok_chat_window_push_allowed": False,
        "automatic_verdict_allowed": False,
        "verdict": "",
        "grok_verdict": "",
        "verdict_delivery_mode": "",
        "source_activity": source_activity,
        "notify_source": notify_source,
        "panel_reminder_cn": "系统已写 rescue 通知；用户无需复制 TUI 全文。",
        "next_machine_action_cn": "等待 Grok 双通道 verdict；无 verdict 前禁止 L2/Stop/completion claim。",
        "tui_self_stop_allowed": False,
        "completion_claim_allowed": False,
        "stop_allowed_without_grok_pass": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    task_path = runtime / "state" / "grok_segment_audit_request" / "tasks" / f"{task_id}.json"
    latest_path = runtime / "state" / "grok_segment_audit_request" / "latest.json"
    _write_json(task_path, payload)
    _write_json(latest_path, payload)
    payload["request_ref"] = str(task_path)
    payload["latest_ref"] = str(latest_path)
    return payload


def write_segment_complete_ready_gate(
    runtime_root: pathlib.Path | str,
    task_id: str,
    *,
    segment_id: str = "phase0_phase1",
    worker_evidence: dict[str, Any] | None = None,
    completion_decision: dict[str, Any] | None = None,
    source_activity: str = "segment_audit_gate_activity",
) -> dict[str, Any]:
    runtime = pathlib.Path(runtime_root)
    task_id = str(task_id)
    worker = dict(worker_evidence or {})
    decision = dict(completion_decision or {})
    worker_evidence_persisted = _worker_evidence_success(worker)
    decision_status = str(decision.get("status") or "")
    segment_verifier_pass = bool(decision and decision_status in {"partial", "complete_allowed"})
    brain_closeout_reached = True
    ready = bool(worker_evidence_persisted and segment_verifier_pass and brain_closeout_reached)
    payload = {
        "schema_version": "xinao.l1_l2_segment_gate.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        **_authorization_fields(),
        "task_id": task_id,
        "source_task_id": task_id,
        "predecessor_task_id": task_id,
        "segment_id": segment_id,
        "worker_task_id": str(worker.get("worker_task_id") or worker.get("task_id") or worker.get("codex_worker_task_id") or ""),
        "worker_jsonl_path": str(worker.get("jsonl_path") or worker.get("worker_jsonl_path") or ""),
        "worker_result_path": str(worker.get("result_path") or ""),
        "status": GATE_READY_STATUS if ready else SEGMENT_GATE_NOT_READY,
        "segment_complete_seen": ready,
        "segment_audit_ready": ready,
        "workflow_waiting_grok_segment_audit": ready,
        "segment_complete_definition": {
            "worker_evidence_persisted": worker_evidence_persisted,
            "segment_verifier_pass": segment_verifier_pass,
            "brain_closeout_reached": brain_closeout_reached,
            "tui_report_is_not_segment_complete": True,
        },
        "source_activity": source_activity,
        "panel_lines_cn": {
            "current_segment_cn": f"当前段：{segment_id}；task={task_id}。",
            "waiting_grok_cn": "段审就绪：系统等待 Grok 双通道审查。",
            "grok_channel_cn": "用户无需复制 TUI 全文；notify v1 只作 rescue。",
        },
        "typeahead_packet_cn": [
            "段审就绪",
            f"task={task_id}",
            "等Grok",
            "勿自停",
            "Grok已notify",
        ],
        "stop_allowed": False,
        "completion_claim_allowed": False,
        "l2_release_allowed": False,
        "backend_only_verdict_allowed": False,
        "worker_pass_as_l2": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    task_path = runtime / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
    latest_path = runtime / "state" / "l1_l2_segment_gate" / "latest.json"
    _write_json(task_path, payload)
    _write_json(latest_path, payload)
    payload["task_ref"] = str(task_path)
    payload["latest_ref"] = str(latest_path)
    if ready:
        request = write_grok_segment_audit_request(
            runtime_root=runtime,
            task_id=task_id,
            segment_id=segment_id,
            source_activity=source_activity,
            notify_source="l1_l2_segment_gate_ready",
        )
        payload["grok_segment_audit_request_ref"] = request["request_ref"]
        payload["grok_notified"] = True
    return payload


def _grok_transport_failed(grok_state: dict[str, Any], gate_latest: dict[str, Any]) -> bool:
    text = " ".join(
        str(item or "")
        for item in (
            grok_state.get("status"),
            grok_state.get("named_blocker"),
            grok_state.get("message"),
            gate_latest.get("status"),
            gate_latest.get("named_blocker"),
            gate_latest.get("message"),
        )
    ).upper()
    return "GROK" in text and any(marker in text for marker in ("TIMEOUT", "UNAVAILABLE", "CONNECTION", "CONNECT", "NOT_INSTALLED", "NO_REPLY"))


def evaluate_task_l1_l2_segment_gate(runtime_root: pathlib.Path | str, task_id: str) -> dict[str, Any]:
    runtime = pathlib.Path(runtime_root)
    gate_task_path = runtime / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
    gate_task = _read_json(gate_task_path, {})
    gate_latest = _read_json(runtime / "state" / "l1_l2_segment_gate" / "latest.json", {})
    gate_state = gate_task if gate_task else gate_latest
    grok_task = _read_json(runtime / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json", {})
    grok_latest = _read_json(runtime / "state" / "grok_l1_l2_segment_gate" / "latest.json", {})
    grok_latest_matches = task_id in {
        str(grok_latest.get("task_id") or ""),
        str(grok_latest.get("source_task_id") or ""),
        str(grok_latest.get("predecessor_task_id") or ""),
        str(grok_latest.get("ingress_task_id") or ""),
    }
    grok_latest_stale_for_task = bool(grok_latest and not grok_task and not grok_latest_matches)
    grok_state = grok_task if grok_task else (grok_latest if grok_latest_matches else {})
    gate_task_matches = task_id in {
        str(gate_state.get("task_id") or ""),
        str(gate_state.get("source_task_id") or ""),
        str(gate_state.get("predecessor_task_id") or ""),
        str(gate_latest.get("task_id") or ""),
        str(gate_latest.get("source_task_id") or ""),
        str(gate_latest.get("predecessor_task_id") or ""),
    }
    gate_latest_matches = bool(
        gate_latest
        and task_id in {
            str(gate_latest.get("task_id") or ""),
            str(gate_latest.get("source_task_id") or ""),
            str(gate_latest.get("predecessor_task_id") or ""),
            str(gate_latest.get("ingress_task_id") or ""),
        }
    )
    task_scoped_ready = bool(
        gate_task
        and str(gate_task.get("task_id") or gate_task.get("source_task_id") or gate_task.get("predecessor_task_id") or "") == str(task_id)
        and gate_task.get("segment_audit_ready") is True
    )
    latest_ready_for_current_task = bool(
        not gate_task
        and gate_latest_matches
        and gate_latest.get("segment_audit_ready") is True
    )
    audit_ready = bool(
        task_scoped_ready
        or latest_ready_for_current_task
        or grok_state.get("segment_audit_ready") is True
        or grok_state.get("audit_ready") is True
    )
    verdict = str(grok_state.get("grok_verdict") or grok_state.get("verdict") or "").strip().lower()
    delivery_mode = _normalize_delivery_mode(grok_state.get("verdict_delivery_mode") or grok_state.get("delivery_mode") or "")
    dual_visible_and_backend = delivery_mode == "dual_visible_and_backend"
    backend_only_seen = (
        delivery_mode in {"backend_only", "backend-only", "backendonly"}
        or grok_state.get("backend_only_verdict") is True
    )
    skip_visible_seen = delivery_mode in {"skip_visible", "skip-visible", "skipvisible"}
    request_age_seconds = _age_seconds(
        grok_state.get("generated_at")
        or grok_state.get("updated_at")
        or gate_latest.get("generated_at")
        or gate_latest.get("updated_at")
    )
    grok_timeout_fallback = bool(
        (request_age_seconds is not None and request_age_seconds >= GROK_REPLY_TIMEOUT_SECONDS and audit_ready and not verdict)
        or _grok_transport_failed(grok_state, gate_latest)
    )
    current_segment_id = str(gate_state.get("segment_id") or gate_latest.get("segment_id") or "phase0_phase1")
    grok_segment_id = str(grok_state.get("segment_id") or "")
    if grok_state and grok_segment_id and grok_segment_id != current_segment_id:
        grok_state = {}
        verdict = ""
        delivery_mode = ""
        dual_visible_and_backend = False
        backend_only_seen = False
        skip_visible_seen = False
        request_age_seconds = _age_seconds(gate_state.get("generated_at") or gate_latest.get("generated_at"))
        grok_timeout_fallback = bool(
            (request_age_seconds is not None and request_age_seconds >= GROK_REPLY_TIMEOUT_SECONDS and audit_ready)
            or _grok_transport_failed(grok_state, gate_latest)
        )
    leg1_summon_valid, leg1_summon = _codex_to_grok_segment_audit_summon_valid(runtime, task_id, current_segment_id)
    leg2_verdict_valid, leg2_evidence = _grok_segment_verdict_leg2_valid(runtime, task_id, grok_task, leg1_summon, current_segment_id)

    output = {
        **_authorization_fields(),
        "task_id": task_id,
        "segment_id": current_segment_id,
        "worker_task_id": str(gate_state.get("worker_task_id") or gate_latest.get("worker_task_id") or ""),
        "worker_jsonl_path": str(gate_state.get("worker_jsonl_path") or gate_latest.get("worker_jsonl_path") or ""),
        "segment_audit_ready": audit_ready,
        "segment_gate_source": "task_file" if gate_task else "latest_file" if gate_latest else "",
        "l1_ready_source": "task_file" if task_scoped_ready else "latest_matching_task" if latest_ready_for_current_task else "grok_verdict_task" if grok_state.get("segment_audit_ready") is True else "",
        "l1_latest_stale_for_task": bool(gate_latest and not gate_latest_matches and not gate_task),
        "grok_gate_source": "task_file" if grok_task else "latest_file" if grok_latest_matches else "",
        "grok_latest_stale_for_task": grok_latest_stale_for_task,
        "grok_gate_ref": str(runtime / "state" / "grok_l1_l2_segment_gate" / "tasks" / f"{task_id}.json") if grok_task else "",
        "gate_task_ref": str(gate_task_path) if gate_task else "",
        "gate_latest_ref": str(runtime / "state" / "l1_l2_segment_gate" / "latest.json") if gate_latest else "",
        "grok_verdict": verdict,
        "verdict_delivery_mode": delivery_mode,
        "workflow_waiting_grok_segment_audit": False,
        "dual_visible_and_backend_required": True,
        "backend_only_verdict_allowed": False,
        "backend_only_verdict_seen": backend_only_seen or skip_visible_seen,
        "dual_visible_and_backend_verdict": dual_visible_and_backend,
        "continuation_n_segment_audit_pass_allowed": False,
        "next_lane": "L1",
        "grok_reply_timeout_seconds": GROK_REPLY_TIMEOUT_SECONDS,
        "grok_request_age_seconds": request_age_seconds,
        "codexa_brain_fallback_allowed": False,
        "codexa_brain_fallback_active": False,
        "codexa_brain_fallback_is_l2": False,
        "codex_to_grok_segment_audit_summon_required": True,
        "codex_to_grok_segment_audit_summon_valid": leg1_summon_valid,
        "codex_to_grok_segment_audit_summon_ref": str(leg1_summon.get("backend_task_ref") or leg1_summon.get("task_ref") or ""),
        "codex_to_grok_segment_audit_summon_delivery_mode": str(leg1_summon.get("delivery_mode") or ""),
        "codex_to_grok_visible_frontend_required": False,
        "codex_to_grok_visible_frontend_disabled_by_stop_order": leg1_summon.get("visible_frontend_disabled_by_stop_order") is True,
        "codex_to_grok_backend_state_cross_check_valid": leg1_summon.get("backend_state_cross_check_valid") is True,
        "grok_segment_verdict_leg2_required": True,
        "grok_segment_verdict_leg2_valid": leg2_verdict_valid,
        "grok_segment_verdict_leg2_evidence": leg2_evidence,
        "bidirectional_dual_delivery_full_ring_valid": bool(leg1_summon_valid and leg2_verdict_valid),
        "l2_release_allowed": False,
    }

    if audit_ready and verdict in {"pass", "fail", "hold"} and dual_visible_and_backend is True and not leg1_summon_valid:
        output.update({
            "status": GATE_WAITING_STATUS,
            "next_lane": "L1",
            "workflow_waiting_grok_segment_audit": True,
            "named_blocker": SEGMENT_SUMMON_REQUIRED_BLOCKER,
        })
        return output

    if audit_ready and verdict in {"pass", "fail", "hold"} and dual_visible_and_backend is True and not leg2_verdict_valid:
        output.update({
            "status": GATE_WAITING_STATUS,
            "next_lane": "L1",
            "workflow_waiting_grok_segment_audit": True,
            "named_blocker": SEGMENT_LEG2_REQUIRED_BLOCKER,
        })
        return output

    if audit_ready and verdict == SEGMENT_GATE_PASS and dual_visible_and_backend is True:
        output.update({
            "status": GATE_PASS_STATUS,
            "next_lane": "L2",
            "workflow_waiting_grok_segment_audit": False,
            "named_blocker": "",
            "l2_release_allowed": True,
        })
        return output

    if audit_ready and verdict == "fail" and dual_visible_and_backend is True:
        output.update({
            "status": GATE_FAIL_STATUS,
            "next_lane": "L1",
            "workflow_waiting_grok_segment_audit": False,
            "named_blocker": "GROK_SEGMENT_AUDIT_FAILED_CONTINUE_L1",
        })
        return output

    if audit_ready and verdict == "hold" and dual_visible_and_backend is True:
        output.update({
            "status": GATE_HOLD_STATUS,
            "next_lane": "L1",
            "workflow_waiting_grok_segment_audit": False,
            "named_blocker": "GROK_SEGMENT_AUDIT_HOLD_CONTINUE_L1",
        })
        return output

    if audit_ready:
        if grok_timeout_fallback:
            output.update({
                "status": GATE_TIMEOUT_CODEXA_BRAIN_FALLBACK_STATUS,
                "next_lane": "L1",
                "workflow_waiting_grok_segment_audit": False,
                "named_blocker": SEGMENT_AUDIT_TIMEOUT_FALLBACK_BLOCKER,
                "codexa_brain_fallback_allowed": True,
                "codexa_brain_fallback_active": True,
                "codexa_brain_fallback_reason": "grok_no_reply_or_transport_failure_after_180s",
            })
            return output
        output["status"] = GATE_WAITING_STATUS
        output["next_lane"] = "L1"
        output["workflow_waiting_grok_segment_audit"] = True
        output["grok_waiting_does_not_block_continuation"] = True
        output["grok_segment_verdict_gates_completion_stop_l2_only"] = True
        output["grok_segment_verdict_wait_blocking"] = False
        if verdict in {"pass", "fail", "hold"} and not dual_visible_and_backend:
            output["named_blocker"] = SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED_BLOCKER
        elif backend_only_seen or skip_visible_seen:
            output["named_blocker"] = SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED_BLOCKER
        elif verdict:
            output["named_blocker"] = ""
        else:
            output["named_blocker"] = ""
        return output

    output["status"] = SEGMENT_GATE_NOT_READY
    output["next_lane"] = "L1"
    output["workflow_waiting_grok_segment_audit"] = False
    output["named_blocker"] = SEGMENT_AUDIT_REQUIRED_BLOCKER
    return output


def is_grok_segment_gate_pass(segment_gate: dict[str, Any]) -> bool:
    return (
        str(segment_gate.get("status") or "") == GATE_PASS_STATUS
        and str(segment_gate.get("grok_verdict") or "").lower() == SEGMENT_GATE_PASS
        and bool(segment_gate.get("dual_visible_and_backend_verdict"))
        and bool(segment_gate.get("codex_to_grok_segment_audit_summon_valid"))
        and bool(segment_gate.get("grok_segment_verdict_leg2_valid"))
        and bool(segment_gate.get("bidirectional_dual_delivery_full_ring_valid"))
        and bool(segment_gate.get("l2_release_allowed"))
    )
