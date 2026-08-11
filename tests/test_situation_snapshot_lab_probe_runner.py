from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evals.situation_snapshot_lab.codex_exec_driver import (
    CodexExecResult,
    ParsedCodexEvents,
)
from evals.situation_snapshot_lab.probe_runner import (
    ProbeRunConfig,
    ProbeRunError,
    run_action_only_pilot,
    run_first_pilot,
)


def _result(thread_id: str, text: str, *, action: bool = False) -> CodexExecResult:
    item_trace: tuple[dict[str, object], ...]
    tool_trace: tuple[dict[str, object], ...]
    if action:
        action_row = {
            "event_type": "item.completed",
            "item_id": "tool-1",
            "item_type": "command_execution",
        }
        item_trace = (action_row,)
        tool_trace = (action_row,)
    else:
        item_trace = ()
        tool_trace = ()
    parsed = ParsedCodexEvents(
        thread_id=thread_id,
        events=(),
        turn_trace=(),
        item_trace=item_trace,
        tool_trace=tool_trace,
        event_types=("thread.started", "turn.started", "turn.completed"),
        final_agent_text=text,
        terminal_usage={"input_tokens": 1, "output_tokens": 1},
        turn_completed=True,
        turn_failed=False,
        error_seen=False,
    )
    receipt = {
        "status": "completed",
        "trajectory_observation": {"thread_id": thread_id},
        "receipt_sha256": hashlib.sha256(thread_id.encode()).hexdigest(),
    }
    return CodexExecResult(receipt=receipt, raw_jsonl=b"{}\n", stderr=b"", parsed=parsed)


class _FakeInvoker:
    def __init__(self, *, duplicate_threads: bool = False) -> None:
        self._by_home: dict[Path, str] = {}
        self._next = 0
        self.duplicate_threads = duplicate_threads

    def first(self, *, config: object, prompt: str) -> CodexExecResult:
        home = Path(getattr(config, "codex_home"))
        thread_id = "thread-same" if self.duplicate_threads else f"thread-{self._next}"
        self._next += 1
        self._by_home[home] = thread_id
        return self._respond(config=config, prompt=prompt, thread_id=thread_id)

    def resume(self, *, config: object, thread_id: str, prompt: str) -> CodexExecResult:
        home = Path(getattr(config, "codex_home"))
        assert self._by_home[home] == thread_id
        return self._respond(config=config, prompt=prompt, thread_id=thread_id)

    @staticmethod
    def _respond(*, config: object, prompt: str, thread_id: str) -> CodexExecResult:
        action = "现在请执行这个修改" in prompt
        if action:
            meeting = Path(getattr(config, "cwd")) / "notes" / "meeting.md"
            meeting.write_text(
                meeting.read_text(encoding="utf-8").replace("TOKEN_OLD", "TOKEN_NEW"),
                encoding="utf-8",
            )
        return _result(thread_id, f"candidate:{hashlib.sha256(prompt.encode()).hexdigest()}", action=action)


def _config(tmp_path: Path) -> ProbeRunConfig:
    source_root = Path(__file__).resolve().parents[1]
    external = tmp_path / "external"
    allowed_output = tmp_path / "allowed-output"
    external.mkdir()
    allowed_output.mkdir()
    executable = external / "codex.exe"
    executable.write_bytes(b"not-used-by-fake")
    auth_target = external / "auth-source.json"
    auth_target.write_text('{"fake":"credential"}', encoding="utf-8")
    return ProbeRunConfig(
        run_id="unit-pilot",
        run_root=allowed_output / "run",
        allowed_output_parent=allowed_output,
        source_root=source_root,
        codex_executable=executable,
        auth_target=auth_target,
    )


def _fake_version(_config: ProbeRunConfig) -> dict[str, object]:
    return {"path": "fake", "sha256": "0" * 64, "version": "codex-cli 0.147.0"}


def test_first_pilot_records_17_serial_turns_and_action_fidelity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    invoker = _FakeInvoker()

    manifest = run_first_pilot(
        config,
        first_invoker=invoker.first,
        resume_invoker=invoker.resume,
        version_verifier=_fake_version,
    )

    assert manifest["status"] == "transport_completed_pending_human_adjudication"
    assert manifest["turn_count"] == 17
    assert len(manifest["tracks"]) == 7
    thread_ids = [track["thread_id"] for track in manifest["tracks"]]
    assert len(thread_ids) == len(set(thread_ids))
    assert [track["track_id"] for track in manifest["tracks"]] == [
        "continuous-b3",
        "continuous-b4",
        "fresh-none",
        "fresh-snapshot",
        "fresh-dialogue",
        "fresh-both",
        "action-boundary-b4",
    ]

    action = manifest["tracks"][-1]
    assert action["turns"][0]["workspace_unchanged"] is True
    assert action["turns"][1]["workspace_unchanged"] is True
    assert action["turns"][2]["workspace_unchanged"] is False
    assert action["turns"][2]["mechanical_events"]["external_action_item_types"] == [
        "command_execution"
    ]
    meeting = config.run_root / "tracks" / "action-boundary-b4" / "workspace" / "notes" / "meeting.md"
    assert "TOKEN_NEW" in meeting.read_text(encoding="utf-8")
    assert not (config.run_root / "run_manifest.partial.json").exists()
    assert (config.run_root / "run_manifest.json").is_file()
    hashes = json.loads((config.run_root / "artifact_hashes.json").read_text(encoding="utf-8"))
    auth_rows = [
        row for row in hashes["entries"] if row["relative_path"].endswith("home/auth.json")
    ]
    assert auth_rows
    assert all(row["kind"] == "symlink_external_content_not_hashed" for row in auth_rows)


def test_first_pilot_stops_when_fresh_track_reuses_thread_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    invoker = _FakeInvoker(duplicate_threads=True)

    with pytest.raises(ProbeRunError, match="reused"):
        run_first_pilot(
            config,
            first_invoker=invoker.first,
            resume_invoker=invoker.resume,
            version_verifier=_fake_version,
        )

    partial = json.loads(
        (config.run_root / "run_manifest.partial.json").read_text(encoding="utf-8")
    )
    assert partial["status"] == "stopped_on_failure"
    assert partial["production_registered"] is False


def test_run_root_must_be_below_declared_output_parent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    escaped = ProbeRunConfig(
        run_id=config.run_id,
        run_root=tmp_path / "escaped-run",
        allowed_output_parent=config.allowed_output_parent,
        source_root=config.source_root,
        codex_executable=config.codex_executable,
        auth_target=config.auth_target,
    )

    with pytest.raises(ProbeRunError, match="strict descendant"):
        run_first_pilot(escaped, version_verifier=_fake_version)


def test_action_only_pilot_runs_exact_three_turn_twin(tmp_path: Path) -> None:
    config = _config(tmp_path)
    invoker = _FakeInvoker()

    manifest = run_action_only_pilot(
        config,
        first_invoker=invoker.first,
        resume_invoker=invoker.resume,
        version_verifier=_fake_version,
    )

    assert manifest["run_kind"] == "action-only-three-turn-pilot"
    assert manifest["turn_count"] == 3
    assert len(manifest["tracks"]) == 1
    assert manifest["tracks"][0]["turns"][2]["workspace_unchanged"] is False
