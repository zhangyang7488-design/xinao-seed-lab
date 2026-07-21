from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_SCRIPT = REPO_ROOT / "scripts" / "record_dispatch_outcome.py"
TASK_RUN_SCRIPT = Path(
    os.environ.get(
        "XINAO_TASK_RUN_CLI",
        r"C:\Users\xx363\.codex\skills\verified-agent-loop\scripts\task_run.py",
    )
)

pytestmark = pytest.mark.skipif(
    not TASK_RUN_SCRIPT.is_file(),
    reason="external verified-agent-loop task_run CLI is not installed in this CI image",
)


def _load_record_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_dispatch_outcome_tested", RECORD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_path_resolver_maps_only_container_evidence_root(tmp_path: Path) -> None:
    module = _load_record_module()
    runtime = tmp_path / "runtime"
    expected = runtime / "state" / "attempt.json"
    expected.parent.mkdir(parents=True)
    expected.write_text("{}\n", encoding="utf-8")

    resolver = module._runtime_path_resolver(runtime)

    assert resolver("/evidence/state/attempt.json") == expected.resolve()
    assert resolver(str(expected)) == expected
    with pytest.raises(ValueError, match="cannot traverse"):
        resolver("/evidence/../outside.json")


def _run_task(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TASK_RUN_SCRIPT), "--root", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_task_run(root: Path, run_id: str) -> Path:
    initialized = _run_task(
        root,
        "init",
        "--run-id",
        run_id,
        "--mode",
        "bounded_task",
        "--objective",
        "verify dispatch outcome recording",
        "--risk",
        "reversible_local",
        "--completion",
        "one immutable outcome is appended exactly once",
    )
    assert initialized.returncode == 0, initialized.stderr
    return root / run_id


def _events(run_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _deterministic_event(**request: object) -> dict[str, object]:
    return {
        "schema_version": "xinao.dispatch_outcome_event.test.v1",
        "event_type": "worker_terminal",
        "parent_work_key": "parent:immutable-dispatch",
        "work_key": "wk:immutable-dispatch",
        "package_id": "package-1",
        "request_marker": request["marker"],
    }


def _record(
    *,
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: Path,
    output: Path,
    task_root: Path,
    run_id: str,
    event_builder: Callable[..., dict[str, object]] = _deterministic_event,
) -> tuple[int, str, str]:
    monkeypatch.setattr(module, "build_dispatch_outcome_event", event_builder)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(RECORD_SCRIPT),
            "--request",
            str(request),
            "--output",
            str(output),
            "--task-run-cli",
            str(TASK_RUN_SCRIPT),
            "--task-run-root",
            str(task_root),
            "--task-run-id",
            run_id,
        ],
    )
    result = module.main()
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def test_same_immutable_outcome_reuses_bytes_hash_and_one_keyed_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_root = tmp_path / "runs"
    run_id = "dispatch-outcome-idempotency"
    run_dir = _init_task_run(task_root, run_id)
    request = tmp_path / "request.json"
    request.write_text('{"marker":"immutable-v1"}\n', encoding="utf-8")
    output = tmp_path / "outcome.json"
    module = _load_record_module()

    first_code, first_stdout, first_stderr = _record(
        module=module,
        monkeypatch=monkeypatch,
        capsys=capsys,
        request=request,
        output=output,
        task_root=task_root,
        run_id=run_id,
    )
    first_bytes = output.read_bytes()
    expected_hash = hashlib.sha256(first_bytes).hexdigest()
    expected_event_id = f"evt-dispatch-{expected_hash[:32]}"

    second_code, second_stdout, second_stderr = _record(
        module=module,
        monkeypatch=monkeypatch,
        capsys=capsys,
        request=request,
        output=output,
        task_root=task_root,
        run_id=run_id,
    )

    assert first_code == second_code == 0
    assert first_stderr == second_stderr == ""
    first_result = json.loads(first_stdout)
    second_result = json.loads(second_stdout)
    assert first_result == second_result
    assert first_result["event_sha256"] == expected_hash
    assert output.read_bytes() == first_bytes
    matching = [event for event in _events(run_dir) if event.get("event_id") == expected_event_id]
    assert len(matching) == 1
    assert matching[0]["idempotency_keyed"] is True
    assert matching[0]["evidence_refs"] == [f"{output.resolve()}#sha256={expected_hash}"]
    assert json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["events_count"] == 2


def test_changed_outcome_bytes_fail_closed_without_overwrite_or_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task_root = tmp_path / "runs"
    run_id = "dispatch-outcome-byte-conflict"
    run_dir = _init_task_run(task_root, run_id)
    request = tmp_path / "request.json"
    request.write_text('{"marker":"immutable-v1"}\n', encoding="utf-8")
    output = tmp_path / "outcome.json"
    module = _load_record_module()
    first_code, _, first_stderr = _record(
        module=module,
        monkeypatch=monkeypatch,
        capsys=capsys,
        request=request,
        output=output,
        task_root=task_root,
        run_id=run_id,
    )
    original_output = output.read_bytes()
    original_events = (run_dir / "events.jsonl").read_bytes()

    request.write_text('{"marker":"drifted-v2"}\n', encoding="utf-8")
    changed_code, changed_stdout, changed_stderr = _record(
        module=module,
        monkeypatch=monkeypatch,
        capsys=capsys,
        request=request,
        output=output,
        task_root=task_root,
        run_id=run_id,
    )

    assert first_code == 0
    assert first_stderr == ""
    assert changed_code == 20
    assert changed_stdout == ""
    assert "already exists with different bytes" in changed_stderr
    assert output.read_bytes() == original_output
    assert (run_dir / "events.jsonl").read_bytes() == original_events


def test_task_run_rejects_changed_semantics_and_event_id_for_same_identity(
    tmp_path: Path,
) -> None:
    task_root = tmp_path / "runs"
    run_id = "dispatch-outcome-identity-conflict"
    run_dir = _init_task_run(task_root, run_id)
    common = (
        "--actor",
        "dispatch-outcome-recorder",
        "--kind",
        "result",
        "--phase",
        "worker_terminal",
        "--summary",
        "worker_terminal package package-1",
        "--evidence-ref",
        "D:/evidence/outcome.json#sha256=abc",
        "--target",
        "wk:immutable-dispatch",
        "--exit-code",
        "0",
        "--retry-class",
        "none",
        "--side-effect-id",
        "se:worker_terminal:run:package-1:abc",
    )
    first = _run_task(
        task_root,
        "event",
        "--run-id",
        run_id,
        "--event-id",
        "evt-dispatch-stable-0001",
        *common,
    )
    before = (run_dir / "events.jsonl").read_bytes()

    changed_event_id = _run_task(
        task_root,
        "event",
        "--run-id",
        run_id,
        "--event-id",
        "evt-dispatch-different-0002",
        *common,
    )
    changed_semantics = _run_task(
        task_root,
        "event",
        "--run-id",
        run_id,
        "--event-id",
        "evt-dispatch-stable-0001",
        *common[:-4],
        "--exit-code",
        "1",
        *common[-2:],
    )

    assert first.returncode == 0, first.stderr
    assert changed_event_id.returncode == 2
    assert "different event_id" in changed_event_id.stderr
    assert changed_semantics.returncode == 2
    assert "changed event semantics" in changed_semantics.stderr
    assert (run_dir / "events.jsonl").read_bytes() == before
    assert len(_events(run_dir)) == 2
