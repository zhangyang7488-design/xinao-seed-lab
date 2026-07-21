from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from scripts import verify_foundation_durability_recovery as subject
from scripts.verify_foundation_durability_recovery import (
    _decode_temporal_input,
    inspect_history_chain,
)


def _continued(workflow_id: str, next_run_id: str, phase: int) -> dict[str, object]:
    return {
        "events": [
            {"eventId": "1", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED"},
            {
                "eventId": "185",
                "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW",
                "workflowExecutionContinuedAsNewEventAttributes": {
                    "newExecutionRunId": next_run_id,
                    "input": [
                        {
                            "continue_as_new_wired": True,
                            "episode_phase": phase,
                            "episode_max_phase": 3,
                            "episode_cache": {
                                "sealed": {
                                    "checkpoint_ok": True,
                                    "checkpoint_thread_id": workflow_id,
                                    "checkpoint_id": f"checkpoint-{phase}",
                                }
                            },
                        }
                    ],
                },
            },
        ]
    }


def _completed() -> dict[str, object]:
    return {
        "events": [
            {"eventId": "1", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED"},
            {"eventId": "9", "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"},
        ]
    }


def test_continue_as_new_chain_carries_checkpoint_and_completes() -> None:
    workflow_id = "workflow-1"
    histories = {
        "run-1": _continued(workflow_id, "run-2", 1),
        "run-2": _continued(workflow_id, "run-3", 2),
        "run-3": _completed(),
    }
    result = inspect_history_chain(
        workflow_id=workflow_id,
        initial_run_id="run-1",
        history_loader=lambda _workflow, run: histories[run],
    )
    assert result["continue_as_new_verified"] is True
    assert result["checkpoint_recovery_verified"] is True
    assert result["continue_as_new_event_count"] == 2
    assert result["run_count"] == 3
    assert result["final_run_id"] == "run-3"


def test_missing_checkpoint_fails_closed() -> None:
    histories = {
        "run-1": {
            "events": [
                {
                    "eventId": "2",
                    "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW",
                    "workflowExecutionContinuedAsNewEventAttributes": {
                        "newExecutionRunId": "run-2",
                        "input": [
                            {
                                "continue_as_new_wired": True,
                                "episode_phase": 1,
                                "episode_max_phase": 3,
                                "episode_cache": {},
                            }
                        ],
                    },
                }
            ]
        },
        "run-2": _completed(),
    }
    result = inspect_history_chain(
        workflow_id="workflow-1",
        initial_run_id="run-1",
        history_loader=lambda _workflow, run: histories[run],
    )
    assert result["continue_as_new_verified"] is True
    assert result["checkpoint_recovery_verified"] is False


def test_failed_workflow_chain_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        inspect_history_chain(
            workflow_id="workflow-1",
            initial_run_id="run-1",
            history_loader=lambda _workflow, _run: {
                "events": [
                    {
                        "eventId": "1",
                        "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
                    }
                ]
            },
        )


def test_temporal_cli_payload_envelope_is_decoded() -> None:
    value = {"continue_as_new_wired": True, "episode_phase": 2}
    encoded = base64.b64encode(json.dumps(value).encode()).decode()
    assert _decode_temporal_input({"payloads": [{"data": encoded}]}) == [value]


@pytest.mark.parametrize(
    ("proof_lines", "expected"),
    [
        (
            "checkpoint_ok=True\ncontinue_as_new_wired=True\n"
            "episode_cache_ref=D:/runtime/checkpoint.json\n",
            True,
        ),
        (
            "checkpoint_ok=False\ncontinue_as_new_wired=True\n"
            "episode_cache_ref=D:/runtime/checkpoint.json\n",
            False,
        ),
        ("checkpoint_ok=True\ncontinue_as_new_wired=True\nepisode_cache_ref=none\n", False),
    ],
)
def test_runtime_proof_must_bind_checkpoint_and_episode_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proof_lines: str,
    expected: bool,
) -> None:
    workflow_id = "workflow-proof"
    histories = {
        "run-1": _continued(workflow_id, "run-2", 1),
        "run-2": _completed(),
    }
    monkeypatch.setattr(
        subject,
        "_temporal_history",
        lambda _workflow, run, *, address: histories[run],
    )
    proof = tmp_path / "state" / "integrated_bus_proof" / f"{workflow_id}.txt"
    proof.parent.mkdir(parents=True)
    proof.write_text(proof_lines, encoding="utf-8")

    report = subject.verify_durability_recovery(
        operation_id="operation-proof",
        workflow_id=workflow_id,
        initial_run_id="run-1",
        output_path=tmp_path / "report.json",
        runtime_root=tmp_path,
    )

    assert report["ok"] is expected
    assert report["checks"]["d_disk_proof_checkpoint_bound"] is (
        "checkpoint_ok=True" in proof_lines
    )
    assert report["proof"]["sha256"]


def test_skipped_continue_as_new_phase_is_not_recovery_proof() -> None:
    workflow_id = "workflow-phase-gap"
    histories = {
        "run-1": _continued(workflow_id, "run-2", 1),
        "run-2": _continued(workflow_id, "run-3", 3),
        "run-3": _completed(),
    }

    result = inspect_history_chain(
        workflow_id=workflow_id,
        initial_run_id="run-1",
        history_loader=lambda _workflow, run: histories[run],
    )

    assert result["phase_progression_ok"] is False
    assert result["checkpoint_recovery_verified"] is False
