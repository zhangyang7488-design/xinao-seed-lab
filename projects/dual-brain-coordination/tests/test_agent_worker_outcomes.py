from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from xinao_coordination.agent_operations import AgentOperationStore
from xinao_coordination.agent_worker import (
    DEFAULT_GROK_MODEL,
    run,
    validate_session_model_evidence,
)


def submit(store: AgentOperationStore, cwd: Path, suffix: str) -> str:
    operation = store.submit(
        actor="codex",
        prompt=f"fake runner {suffix}",
        session_name=f"fake-{suffix}",
        cwd=cwd,
        idempotency_key=f"fake-{suffix}",
    )["operation"]
    return str(operation["operation_id"])


def configure_fake_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    runner = tmp_path / "fake_runner.py"
    runtime = tmp_path / "runtime.js"
    runner.write_text(body, encoding="utf-8")
    runtime.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        "xinao_coordination.agent_worker.read_acpx_runtime",
        lambda: {"node": Path(sys.executable), "runner": runner, "runtime_module": runtime},
    )


def test_post_start_non_authoritative_terminal_is_uncertain(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_fake_runner(
        monkeypatch,
        tmp_path,
        """
import json
import sys
command = json.loads(sys.stdin.readline())
assert command["action"] == "start"
print(json.dumps({"type": "turn_starting", "requestId": "fake"}), flush=True)
print(json.dumps({
    "type": "terminal",
    "status": "failed",
    "turnStarted": True,
    "resultAuthoritative": False,
    "error": {"message": "result stream lost"}
}), flush=True)
raise SystemExit(2)
""".lstrip(),
    )
    store = AgentOperationStore(db_path)
    operation_id = submit(store, tmp_path, "unknown")

    assert run(operation_id, db_path) == 1
    current = store.get(operation_id)["operation"]
    assert current["state"] == "uncertain"
    assert "authoritative ACP result" in current["error"]


def test_prestart_authoritative_failure_is_failed_not_uncertain(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_fake_runner(
        monkeypatch,
        tmp_path,
        """
import json
import sys
command = json.loads(sys.stdin.readline())
assert command["action"] == "start"
print(json.dumps({
    "type": "terminal",
    "status": "failed",
    "turnStarted": False,
    "resultAuthoritative": False,
    "error": {"message": "probe failed"}
}), flush=True)
raise SystemExit(2)
""".lstrip(),
    )
    store = AgentOperationStore(db_path)
    operation_id = submit(store, tmp_path, "prestart")

    assert run(operation_id, db_path) == 1
    current = store.get(operation_id)["operation"]
    assert current["state"] == "failed"
    assert current["error"] is not None


def test_completed_worker_registers_operation_spec_and_observed_model(
    db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_fake_runner(
        monkeypatch,
        tmp_path,
        """
import json
import sys
command = json.loads(sys.stdin.readline())
assert command["action"] == "start"
print(json.dumps({"type": "turn_starting", "requestId": "fake"}), flush=True)
resolved = {
    "acpxRecordId": "acpx-completed",
    "backendSessionId": "backend-completed"
}
print(json.dumps({"type": "session_resolved", "requestId": "fake", **resolved}), flush=True)
print(json.dumps({
    "type": "terminal",
    "turnStarted": True,
    "resultAuthoritative": True,
    "result": {"status": "completed", "stopReason": "end_turn"},
    "finalText": "verified output",
    "requestedModel": "grok-4.5",
    "observedModels": {
        "currentModelId": "grok-4.5",
        "availableModelIds": ["grok-4.5"]
    },
    "acpxRecordId": "acpx-completed",
    "backendSessionId": "backend-completed",
    "resolvedSession": resolved,
    "sessionModelEvidence": {
        "source": "acpx_runtime_status_after_turn",
        "requestedModel": "grok-4.5",
        "currentModelId": "grok-4.5",
        "availableModelIds": ["grok-4.5"],
        "acpxRecordId": "acpx-completed",
        "backendSessionId": "backend-completed"
    }
}), flush=True)
raise SystemExit(0)
""".lstrip(),
    )
    store = AgentOperationStore(db_path)
    operation_id = submit(store, tmp_path, "completed-evidence")

    assert run(operation_id, db_path) == 0
    view = store.get(operation_id)
    artifacts = {str(item["name"]): item for item in view["artifacts"]}
    assert "operation-spec.json" in artifacts
    assert "manifest.json" in artifacts
    manifest = json.loads(Path(str(artifacts["manifest.json"]["uri"])).read_text(encoding="utf-8"))
    assert DEFAULT_GROK_MODEL == "grok-4.5"
    assert manifest["requested_model"] == DEFAULT_GROK_MODEL
    assert manifest["observed_models"]["currentModelId"] == DEFAULT_GROK_MODEL
    assert manifest["session_model_evidence_valid"] is True
    assert manifest["session_model_evidence"]["availableModelIds"] == [DEFAULT_GROK_MODEL]
    assert manifest["operation_spec_sha256"].upper() == artifacts["operation-spec.json"]["sha256"]


@pytest.mark.parametrize(
    ("available", "resolved_backend", "expected"),
    [
        ([], "backend-completed", False),
        (["grok-4.5"], "backend-other", False),
        (["grok-4.5"], "backend-completed", True),
    ],
)
def test_session_model_evidence_requires_advertisement_and_lineage(
    available: list[str],
    resolved_backend: str,
    expected: bool,
) -> None:
    final = {
        "acpxRecordId": "acpx-completed",
        "backendSessionId": "backend-completed",
        "agentSessionId": "",
    }
    resolved = {
        "acpxRecordId": "acpx-completed",
        "backendSessionId": resolved_backend,
        "agentSessionId": "",
    }
    evidence: dict[str, object] = {
        "source": "acpx_runtime_status_after_turn",
        "requestedModel": "grok-4.5",
        "currentModelId": "grok-4.5",
        "availableModelIds": available,
        **final,
    }
    assert (
        validate_session_model_evidence(
            outcome_state="completed",
            spec_model="grok-4.5",
            evidence=evidence,
            resolved_session=resolved,
            terminal_resolved_session=resolved,
            final_session=final,
        )
        is expected
    )


def test_session_model_evidence_treats_empty_optional_agent_id_as_absent() -> None:
    final = {
        "acpxRecordId": "acpx-completed",
        "backendSessionId": "backend-completed",
        "agentSessionId": "",
    }
    evidence: dict[str, object] = {
        "source": "acpx_runtime_status_after_turn",
        "requestedModel": "grok-4.5",
        "currentModelId": "grok-4.5",
        "availableModelIds": ["grok-4.5"],
        "acpxRecordId": "acpx-completed",
        "backendSessionId": "backend-completed",
    }
    assert validate_session_model_evidence(
        outcome_state="completed",
        spec_model="grok-4.5",
        evidence=evidence,
        resolved_session=final,
        terminal_resolved_session={
            "acpxRecordId": "acpx-completed",
            "backendSessionId": "backend-completed",
        },
        final_session=final,
    )
