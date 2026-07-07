import json
from pathlib import Path

from services.agent_runtime import overnight_supervisor_loop as loop


def test_overnight_supervisor_loop_run_once_writes_watchdog_artifacts(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    intent_package = tmp_path / "grok_overnight_supervisor_loop_phase0_batch_20260704.json"
    intent_package.write_text(
        json.dumps(
            {
                "schema_version": "xinao.grok_intent_package.v1",
                "task_id": loop.TASK_ID,
                "work_id": loop.WORK_ID,
                "route_profile": loop.ROUTE_PROFILE,
                "productivity_mode_v2": True,
                "must_close": ["Run S-native Temporal overnight"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = loop.run_once(
        runtime=runtime,
        repo=repo,
        intent_package=intent_package,
        duration_hours=10,
        deadline_at="2026-07-04T20:53:00+08:00",
        wave_interval_seconds=60,
        heartbeat_seconds=30,
        invoke_runtime=False,
        write=True,
    )

    paths = loop.state_paths(runtime)
    assert payload["schema_version"] == loop.SCHEMA_VERSION
    assert payload["sentinel"] == loop.SENTINEL
    assert payload["task_id"] == loop.TASK_ID
    assert payload["should_continue_loop"] is True
    assert payload["foreground_poll_required"] is True
    assert payload["poll_owner"] == "codex_s"
    assert payload["user_prompts_required"] is False
    assert payload["deadline_at"] == "2026-07-04T20:53:00+08:00"
    assert payload["wave_count"] == 1
    assert payload["completion_claim_allowed"] is False
    assert paths["latest"].is_file()
    assert paths["heartbeat_latest"].is_file()
    assert paths["readback"].is_file()
    assert paths["worker_assignment"].is_file()

    assignment = json.loads(paths["worker_assignment"].read_text(encoding="utf-8"))
    assert assignment["source_intent_package_ref"] == str(intent_package)
    assert assignment["foreground_poll_required"] is True
    assert assignment["poll_owner"] == "codex_s"
    assert assignment["completion_claim_allowed"] is False
    assert len(assignment["assignment_dag"]["nodes"]) == 6

    manifest = (
        runtime / "capabilities" / "codex_s.overnight_supervisor_loop_watchdog" / "manifest.json"
    )
    invoke = (
        runtime
        / "capabilities"
        / "codex_s.overnight_supervisor_loop_watchdog"
        / "invoke_evidence"
        / "latest.json"
    )
    assert manifest.is_file()
    assert invoke.is_file()
    invoke_payload = json.loads(invoke.read_text(encoding="utf-8"))
    assert invoke_payload["invoke_performed"] is True
    assert invoke_payload["completion_claim_allowed"] is False

    a4_latest = paths["a4_default_shape_latest"]
    assert a4_latest.is_file()
    a4_payload = json.loads(a4_latest.read_text(encoding="utf-8"))
    assert a4_payload["stage_order"] == ["parallel_draft", "merge", "writer"]
    assert a4_payload["meta_rsi_role"] == "evidence_only_not_main_worker"
    assert a4_payload["foreground_poll_required"] is True

    readback = paths["readback"].read_text(encoding="utf-8")
    assert "wave_count: 1" in readback
    assert "现在能 invoke 什么" in readback
    assert "parallel_draft -> merge -> writer" in readback
    assert "candidate_registered" in readback


def test_overnight_supervisor_schema_locks_no_prompt_poll_owner() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "schemas"
        / "codex_s_overnight_supervisor_loop.v1.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == loop.SCHEMA_VERSION
    assert schema["properties"]["sentinel"]["const"] == loop.SENTINEL
    assert schema["properties"]["foreground_poll_required"]["const"] is True
    assert schema["properties"]["poll_owner"]["const"] == "codex_s"
    assert schema["properties"]["user_prompts_required"]["const"] is False
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert "external_search" in schema["required"]
    assert "capabilities" in schema["required"]
    assert "a4_default_shape" in schema["required"]
    assert "a4_default_shape_latest" in schema["properties"]["can_invoke_now"]["required"]
