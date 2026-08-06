from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = REPO_ROOT / "evals/native_subagent_trajectory"
FIXTURE_ROOT = EVAL_ROOT / "fixture_template"


def test_native_subagent_profile_is_ephemeral_and_local() -> None:
    config = yaml.safe_load((EVAL_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    provider_config = provider["config"]
    assert provider_config["working_dir"] == "{{env.XINAO_NATIVE_SUBAGENT_WORKSPACE}}"
    assert provider_config["sandbox_mode"] == "workspace-write"
    assert provider_config["approval_policy"] == "never"
    assert provider_config["ephemeral"] is True
    assert provider_config["reuse_server"] is False
    assert provider_config["inherit_process_env"] is False
    assert provider_config["include_raw_events"] is True
    assert provider_config["cli_config"] == {
        "features": {"hooks": False, "multi_agent": True, "multi_agent_v2": True}
    }
    assert provider_config["cli_env"]["CODEX_HOME"] == "{{env.CODEX_HOME}}"


def test_case_uses_standing_delegation_without_one_off_authorization() -> None:
    prompt = (EVAL_ROOT / "prompt.txt").read_text(encoding="utf-8")
    fixture_rules = (FIXTURE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    combined = f"{prompt}\n{fixture_rules}".lower()

    assert "explicitly authoriz" not in combined
    assert "one-off" not in prompt.lower()
    prompt_lower = prompt.lower()
    assert "codex-native collaboration" in prompt_lower
    assert "one separable native child contribution" in prompt_lower
    assert "real consumer invocation" in prompt_lower


def test_fixture_consumer_rejects_relay_and_accepts_exact_adoption(tmp_path: Path) -> None:
    for source in FIXTURE_ROOT.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_bytes(source.read_bytes())

    rejected = tmp_path / "rejected.json"
    rejected.write_text(
        json.dumps(
            {
                "owner_anchor": "owner-cobalt-41",
                "worker_alpha": 0,
            }
        ),
        encoding="utf-8",
    )
    rejected_run = subprocess.run(
        [
            sys.executable,
            "consumer.py",
            rejected.name,
            "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53",
        ],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    assert rejected_run.returncode == 2
    assert "NATIVE_SUBAGENT_CONSUMER_REJECTED" in rejected_run.stdout

    adopted = tmp_path / "adoption.json"
    adopted.write_text(
        json.dumps(
            {
                "owner_anchor": "owner-cobalt-41",
                "worker_alpha": 17,
            }
        ),
        encoding="utf-8",
    )
    accepted_run = subprocess.run(
        [
            sys.executable,
            "consumer.py",
            adopted.name,
            "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53",
        ],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    assert accepted_run.returncode == 0
    assert json.loads(accepted_run.stdout) == {
        "adoption_verified": True,
        "consumer_marker": "NATIVE_SUBAGENT_CONSUMER_OK",
        "followup_nonce": "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53",
    }


def test_assertion_binds_parent_commands_child_terminals_and_order() -> None:
    assertion = (EVAL_ROOT / "assert_trajectory.js").read_text(encoding="utf-8")
    for required in (
        "item/completed",
        "collabAgentToolCall",
        "spawnAgent",
        "agentsStates",
        "owner_anchor\\.txt",
        "directWorkerReads.length === 0",
        "adoptionAfterTerminal",
        "consumerAfterTerminals",
        "spawnedTerminals.length === 1",
        "emptyTerminalWaits",
        "subAgentStarts",
    ):
        assert required in assertion


def _score_notifications(notifications: list[dict[str, object]]) -> dict[str, object]:
    output = json.dumps(
        {
            "case_id": "NATIVE_SUBAGENT_OWNER_WORKER_CONSUMER",
            "owner_anchor": "owner-cobalt-41",
            "worker_alpha": 17,
            "delegated_threads": 1,
            "consumer_marker": "NATIVE_SUBAGENT_CONSUMER_OK",
            "followup_nonce": "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53",
            "adoption_status": "adopted_after_child_terminals",
            "status": "verified",
        },
        separators=(",", ":"),
    )
    payload = {
        "output": output,
        "notifications": notifications,
        "metadata": {
            "codexAppServer": {
                "threadId": "root-thread",
                "turnId": "root-turn",
                "sandboxMode": "workspace-write",
                "approvalPolicy": "never",
            }
        },
    }
    program = """
const score = require(process.argv[1]);
const payload = JSON.parse(process.argv[2]);
const result = score(payload.output, {
  providerResponse: {raw: JSON.stringify({notifications: payload.notifications})},
  metadata: payload.metadata,
});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [
            "node",
            "-e",
            program,
            str(EVAL_ROOT / "assert_trajectory.js"),
            json.dumps(payload, separators=(",", ":")),
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)


def _completed(item: dict[str, object]) -> dict[str, object]:
    return {"method": "item/completed", "params": {"item": item}}


def test_assertion_accepts_only_the_complete_root_lifecycle() -> None:
    output = json.dumps(
        {
            "case_id": "NATIVE_SUBAGENT_OWNER_WORKER_CONSUMER",
            "owner_anchor": "owner-cobalt-41",
            "worker_alpha": 17,
            "delegated_threads": 1,
            "consumer_marker": "NATIVE_SUBAGENT_CONSUMER_OK",
            "followup_nonce": "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53",
            "adoption_status": "adopted_after_child_terminals",
            "status": "verified",
        },
        separators=(",", ":"),
    )
    score = _score_notifications(
        [
            _completed(
                {
                    "type": "commandExecution",
                    "status": "completed",
                    "exitCode": 0,
                    "command": "Get-Content owner_anchor.txt",
                    "aggregatedOutput": (
                        "OWNER_DIRECT_ANCHOR=owner-cobalt-41\\n"
                        "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53"
                    ),
                }
            ),
            _completed(
                {
                    "type": "collabAgentToolCall",
                    "status": "completed",
                    "tool": "spawnAgent",
                    "receiverThreadIds": ["child-1"],
                    "prompt": "Read only worker_alpha.txt",
                }
            ),
            _completed(
                {
                    "type": "collabAgentToolCall",
                    "status": "completed",
                    "tool": "wait",
                    "receiverThreadIds": ["child-1"],
                    "agentsStates": {
                        "child-1": {
                            "status": "completed",
                            "message": "ALPHA_SOURCE_CANDIDATE=17",
                        }
                    },
                }
            ),
            _completed(
                {
                    "type": "fileChange",
                    "status": "completed",
                    "changes": [{"path": "C:/fixture/adoption.json", "kind": "add"}],
                }
            ),
            _completed(
                {
                    "type": "commandExecution",
                    "status": "completed",
                    "exitCode": 0,
                    "command": (
                        "python consumer.py adoption.json ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53"
                    ),
                    "aggregatedOutput": (
                        "NATIVE_SUBAGENT_CONSUMER_OK ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53"
                    ),
                }
            ),
            _completed(
                {
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": output,
                }
            ),
        ]
    )
    assert score["pass"] is True


def test_assertion_rejects_observed_started_child_with_empty_wait() -> None:
    score = _score_notifications(
        [
            _completed(
                {
                    "type": "commandExecution",
                    "status": "completed",
                    "exitCode": 0,
                    "command": "Get-Content owner_anchor.txt",
                    "aggregatedOutput": (
                        "OWNER_DIRECT_ANCHOR=owner-cobalt-41\\n"
                        "ROOT_OWNER_FOLLOWUP_NONCE=root-ember-53"
                    ),
                }
            ),
            _completed(
                {
                    "type": "subAgentActivity",
                    "kind": "started",
                    "agentThreadId": "child-1",
                }
            ),
            _completed(
                {
                    "type": "collabAgentToolCall",
                    "status": "completed",
                    "tool": "wait",
                    "receiverThreadIds": [],
                    "agentsStates": {},
                }
            ),
        ]
    )
    assert score["pass"] is False
    assert '"emptyTerminalWaits":1' in score["reason"]
    assert '"threadId":"child-1"' in score["reason"]


def test_assertion_rejects_owner_doing_the_worker_read() -> None:
    score = _score_notifications(
        [
            _completed(
                {
                    "type": "commandExecution",
                    "status": "completed",
                    "exitCode": 0,
                    "command": "Get-Content worker_alpha.txt",
                    "aggregatedOutput": "ALPHA_SOURCE_CANDIDATE=17",
                }
            )
        ]
    )
    assert score["pass"] is False
    assert '"directWorkerReads":1' in score["reason"]


def test_assertion_rejects_child_relay_without_owner_consumer_followup() -> None:
    score = _score_notifications(
        [
            _completed(
                {
                    "type": "collabAgentToolCall",
                    "status": "completed",
                    "tool": "spawnAgent",
                    "receiverThreadIds": ["child-1"],
                    "prompt": "Read only worker_alpha.txt",
                }
            ),
            _completed(
                {
                    "type": "collabAgentToolCall",
                    "status": "completed",
                    "tool": "wait",
                    "receiverThreadIds": ["child-1"],
                    "agentsStates": {
                        "child-1": {
                            "status": "completed",
                            "message": "ALPHA_SOURCE_CANDIDATE=17",
                        }
                    },
                }
            ),
        ]
    )
    assert score["pass"] is False
    assert '"consumerCalls":0' in score["reason"]
