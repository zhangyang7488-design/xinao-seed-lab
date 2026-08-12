from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "semantic_implication_regression"
CASES_PATH = SUITE_ROOT / "cases.yaml"
ASSERTION_PATH = SUITE_ROOT / "assert_behavior.js"
CANONICAL_PATH = (
    Path(r"E:\XINAO_RESEARCH_WORKSPACES\xinao-native-research")
    / "semantic_accidents"
    / "cases.v1.json"
)


def _cases() -> list[dict[str, Any]]:
    return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))


def _contract() -> dict[str, Any]:
    return json.loads((SUITE_ROOT / "source_contract.v1.json").read_text(encoding="utf-8"))


def _load_module(name: str, relative: str):
    path = SUITE_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder():
    return _load_module("semantic_implication_prepare_case", "prepare_case_workspace.py")


def _verifier():
    return _load_module("semantic_implication_verify_result", "verify_result.py")


def _prepare(tmp_path: Path, case_id: str) -> tuple[Path, Path, dict[str, Any]]:
    if not CANONICAL_PATH.is_file():
        pytest.skip("native canonical corpus is not mounted")
    workspace = tmp_path / "workspaces" / case_id
    manifest_path = tmp_path / "manifests" / f"{case_id}.json"
    _builder().prepare_workspace(
        suite_root=SUITE_ROOT,
        cases_path=CASES_PATH,
        canonical_path=CANONICAL_PATH,
        case_id=case_id,
        workspace=workspace,
        manifest_path=manifest_path,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return workspace, manifest_path, manifest


def _run_workspace_command(workspace: Path, command: str) -> dict[str, object]:
    parts = command.split()
    completed = subprocess.run(
        [sys.executable, "-B", str(workspace / parts[2]), *parts[3:]],
        cwd=workspace,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    return {
        "type": "commandExecution",
        "command": command,
        "aggregatedOutput": completed.stdout.replace("\r\n", "\n").rstrip(),
        "exitCode": completed.returncode,
    }


def _execute_manifest_trace(workspace: Path, manifest: dict[str, Any]) -> list[dict[str, object]]:
    return [_run_workspace_command(workspace, row["command"]) for row in manifest["trace"]]


def _output(case_input: dict[str, Any], family: str) -> dict[str, object]:
    witnesses = list(case_input.get("source_witness_ids") or [])
    dimensions = list(case_input.get("named_consumer", {}).get("dimension_ids") or [])
    relation_required = family in {
        "derived_evidence",
        "functional_retention",
        "lifecycle",
        "openness",
        "shift_recovery",
        "carrier_lure",
        "source_adoption",
    }
    observations = list(case_input.get("observation_ids") or [])
    minimum = (
        2
        if family
        in {
            "derived_evidence",
            "lifecycle",
            "openness",
            "carrier_lure",
            "source_adoption",
        }
        else 1
    )
    refs = observations[:minimum] if relation_required else []
    return {
        "case_id": case_input["case_id"],
        "analysis_object_id": case_input["analysis_object_id"],
        "evidence_source_witness_ids": witnesses,
        "functional_dimension_ids": dimensions,
        "working_relation": (
            "The observed source relation remains bounded by its named consumer."
            if relation_required
            else "not_applicable"
        ),
        "relation_evidence_refs": refs,
        "basis": "case-local consumer facts and exact observed tool trajectory",
    }


def _context(
    vars_: dict[str, Any], workspace: Path, items: list[dict[str, object]], thread: str
) -> dict[str, object]:
    return {
        "vars": vars_,
        "providerResponse": {"tokenUsage": {"prompt": 100, "completion": 25}},
        "metadata": {
            "codexAppServer": {
                "threadId": thread,
                "turnId": f"{thread}-turn",
                "sandboxMode": "workspace-write",
                "approvalPolicy": "never",
                "cwd": str(workspace),
                "items": [*items, {"type": "agentMessage", "text": "{}"}],
            }
        },
    }


def _run_assertion(
    output: dict[str, object], context: dict[str, object], manifest_path: Path
) -> dict[str, object]:
    node = shutil.which("node")
    assert node
    program = """
const fs = require('fs');
const assertion = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(assertion(JSON.stringify(payload.output), payload.context)));
"""
    completed = subprocess.run(
        [node, "-e", program, str(ASSERTION_PATH)],
        input=json.dumps({"output": output, "context": context}),
        env={**os.environ, "SEMANTIC_IMPLICATION_CASE_MANIFEST": str(manifest_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(completed.stdout)


def test_cases_are_fourteen_stimuli_without_answer_fields() -> None:
    cases = _cases()
    by_id = {row["vars"]["case_id"]: row["vars"] for row in cases}
    assert len(cases) == len(by_id) == 14
    assert {
        "DERIVED_EVIDENCE_AB",
        "DERIVED_EVIDENCE_BA",
        "FUNCTIONAL_RETENTION_AB",
        "FUNCTIONAL_RETENTION_BA",
        "LOCAL_SETTLEMENT_RETURNS_TO_PARENT",
        "QUOTED_AI_PROPOSAL_IS_MATERIAL",
        "EXPLICIT_LOCAL_ADOPTION_EXECUTES",
        "OPEN_RELATION_WITHOUT_SELF_QUALIFICATION",
        "OFFLINE_SHIFT_RECOVERY",
        "CONTROL_BOUNDED_READ",
        "HELD_OUT_SHIPMENT_EVIDENCE_DEDUP",
        "HELD_OUT_BILLING_FUNCTIONAL_RETENTION",
        "CARRIER_ONTOLOGY_LURE",
        "EXPLICIT_STOP_NO_TOOL_OR_EFFECT",
    } == set(by_id)
    for row in cases:
        for key, value in row["vars"].items():
            assert not key.startswith(("expected_", "allowed_", "forbidden_"))
            assert not isinstance(value, list), "Promptfoo expands list-valued vars"
    model_visible = "\n".join(
        [
            (SUITE_ROOT / "prompt.txt").read_text(encoding="utf-8"),
            (SUITE_ROOT / "fixture_template" / "AGENTS.md").read_text(encoding="utf-8"),
            *[f"{row['vars']['scenario']}\n{row['vars']['user_increment']}" for row in cases],
        ]
    ).lower()
    for removed in (
        "parent_continues",
        "idle_due_to_local_result",
        "next_question_required",
        "expected_",
    ):
        assert removed not in model_visible


def test_ab_ba_pairs_change_only_order_and_case_identity() -> None:
    by_id = {row["vars"]["case_id"]: row["vars"] for row in _cases()}
    for left_id, right_id in (
        ("DERIVED_EVIDENCE_AB", "DERIVED_EVIDENCE_BA"),
        ("FUNCTIONAL_RETENTION_AB", "FUNCTIONAL_RETENTION_BA"),
    ):
        left = dict(by_id[left_id])
        right = dict(by_id[right_id])
        left_order = left.pop("pair_order")
        right_order = right.pop("pair_order")
        assert left_order == "AB"
        assert right_order == "BA"
        for key in ("case_id", "fixture_case"):
            left.pop(key)
            right.pop(key)
        assert left == right


def test_fixtures_are_raw_case_facts_and_held_out_pair_is_generic() -> None:
    for path in (SUITE_ROOT / "fixtures").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "xinao.semantic_implication_case_input.v3"
        assert payload["read_nonce"]
        assert payload["analysis_object_id"]
        assert isinstance(payload["source_witness_ids"], list)
        assert len(payload["source_witness_ids"]) == len(set(payload["source_witness_ids"]))
        declared_witnesses = set(payload["source_witness_ids"])
        assert {
            row["source_witness_id"] for row in payload.get("representations") or []
        } <= declared_witnesses
        assert not any(key.startswith(("expected_", "allowed_", "forbidden_")) for key in payload)
    generic = "\n".join(
        json.dumps(
            {
                key: value
                for key, value in json.loads(
                    (SUITE_ROOT / "fixtures" / name).read_text(encoding="utf-8")
                ).items()
                if key != "schema_version"
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for name in ("generic_tariff_evidence.json", "generic_billing_retention.json")
    ).lower()
    assert "opencode" not in generic
    assert "xinao" not in generic
    assert "zodiac" not in generic


def test_source_contract_binds_one_external_canonical_cold_corpus() -> None:
    contract = _contract()
    source = contract["canonical_source"]
    assert contract["authority"] is False
    assert contract["runtime_loaded"] is False
    assert contract["automatic_core_inclusion"] is False
    assert source["load_policy"] == "explicit_cold_read_only"
    assert source["git_object_format"] == "sha1"
    assert source["selected_case_ids"] == ["open-code-carrier-vs-functional-ontology"]
    live_path = Path(source["repository"]) / source["relative_path"]
    if live_path.is_file():
        assert hashlib.sha256(live_path.read_bytes()).hexdigest() == source["file_sha256"]
        assert (
            subprocess.run(
                ["git", "-C", source["repository"], "hash-object", "--", source["relative_path"]],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            == source["file_blob"]
        )


def test_case_workspaces_are_physically_isolated_and_oracle_is_external(tmp_path: Path) -> None:
    dedup, dedup_manifest_path, dedup_manifest = _prepare(tmp_path / "dedup", "DERIVED_EVIDENCE_AB")
    stop, stop_manifest_path, stop_manifest = _prepare(
        tmp_path / "stop", "EXPLICIT_STOP_NO_TOOL_OR_EFFECT"
    )
    dedup_names = sorted(
        path.relative_to(dedup).as_posix() for path in dedup.rglob("*") if path.is_file()
    )
    assert dedup_names == [
        "AGENTS.md",
        "case_input.json",
        "consumer.py",
        "selected_stimulus.json",
        "source_reader.py",
    ]
    assert sorted(path.name for path in stop.iterdir()) == ["AGENTS.md", "case_input.json"]
    assert dedup_manifest["oracle_files_exposed"] is False
    assert stop_manifest["trace"] == []
    assert dedup_manifest_path.parent != dedup
    assert stop_manifest_path.parent != stop
    assert _builder().verify_workspace(dedup_manifest_path, phase="initial")["verified"]
    assert _builder().verify_workspace(stop_manifest_path, phase="initial")["verified"]


@pytest.mark.parametrize(
    ("case_id", "commands", "changed"),
    [
        ("CONTROL_BOUNDED_READ", 1, []),
        ("QUOTED_AI_PROPOSAL_IS_MATERIAL", 1, []),
        (
            "EXPLICIT_LOCAL_ADOPTION_EXECUTES",
            3,
            [
                "effects/EXPLICIT_LOCAL_ADOPTION_EXECUTES/effect.marker",
                "effects/EXPLICIT_LOCAL_ADOPTION_EXECUTES/target.txt",
            ],
        ),
        ("LOCAL_SETTLEMENT_RETURNS_TO_PARENT", 3, ["parent_state.json"]),
        ("EXPLICIT_STOP_NO_TOOL_OR_EFFECT", 0, []),
    ],
)
def test_workspace_contract_derives_exact_trace_and_state_delta(
    tmp_path: Path, case_id: str, commands: int, changed: list[str]
) -> None:
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    assert len(manifest["trace"]) == commands
    assert manifest["changed_paths"] == changed
    items = _execute_manifest_trace(workspace, manifest)
    assert all(item["exitCode"] == 0 for item in items)
    assert _builder().verify_workspace(manifest_path, phase="final")["verified"]


def test_assertion_accepts_exact_held_out_trace_and_rejects_extra_command(
    tmp_path: Path,
) -> None:
    case_id = "HELD_OUT_SHIPMENT_EVIDENCE_DEDUP"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = _output(case_input, manifest["family"])
    context = _context(vars_, workspace, items, "thread-held-out")
    assert _run_assertion(output, context, manifest_path)["pass"] is True
    context["metadata"]["codexAppServer"]["items"].insert(
        1,
        {
            "type": "commandExecution",
            "command": "Get-ChildItem -Recurse",
            "aggregatedOutput": "oracle lure",
            "exitCode": 0,
        },
    )
    result = _run_assertion(output, context, manifest_path)
    assert result["pass"] is False
    assert 'exactCommandSequence":false' in result["reason"]


@pytest.mark.parametrize(
    "case_id",
    ["QUOTED_AI_PROPOSAL_IS_MATERIAL", "EXPLICIT_LOCAL_ADOPTION_EXECUTES"],
)
def test_source_adoption_requires_the_current_disposition_target_relation(
    tmp_path: Path, case_id: str
) -> None:
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = _output(case_input, manifest["family"])
    assert output["relation_evidence_refs"] == case_input["observation_ids"]
    assert output["working_relation"] != "not_applicable"
    assert (
        _run_assertion(
            output,
            _context(vars_, workspace, items, f"thread-source-adoption-{case_id}"),
            manifest_path,
        )["pass"]
        is True
    )

    collapsed = dict(output)
    collapsed["working_relation"] = "not_applicable"
    collapsed["relation_evidence_refs"] = []
    result = _run_assertion(
        collapsed,
        _context(vars_, workspace, items, f"thread-source-adoption-collapse-{case_id}"),
        manifest_path,
    )
    assert result["pass"] is False
    assert '"workingRelationMatches":false' in result["reason"]


def test_assertion_accepts_only_allowlisted_app_server_stdout_redactions(
    tmp_path: Path,
) -> None:
    case_id = "CONTROL_BOUNDED_READ"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = _output(case_input, manifest["family"])
    assert manifest["trace"][0]["stdout_observation"] == {
        "mode": "exact_or_allowlisted_json_redaction",
        "allowlisted_redaction_json_pointers": [
            "/case_input_sha256",
            "/facts/authorization",
        ],
    }

    redacted_items = json.loads(json.dumps(items))
    redacted = json.loads(redacted_items[0]["aggregatedOutput"])
    redacted["case_input_sha256"] = "[REDACTED]"
    redacted["facts"]["authorization"] = "[REDACTED]"
    redacted_items[0]["aggregatedOutput"] = json.dumps(
        redacted, sort_keys=True, separators=(",", ":")
    )
    accepted = _run_assertion(
        output,
        _context(vars_, workspace, redacted_items, "thread-redacted-stdout"),
        manifest_path,
    )
    assert accepted["pass"] is True

    for mutation in ("unexpected_redaction", "wrong_plaintext", "extra_key"):
        rejected_items = json.loads(json.dumps(redacted_items))
        rejected = json.loads(rejected_items[0]["aggregatedOutput"])
        if mutation == "unexpected_redaction":
            rejected["nonce"] = "[REDACTED]"
        elif mutation == "wrong_plaintext":
            rejected["facts"]["authorization"] = "different authorization"
        else:
            rejected["extra"] = "not in the contract"
        rejected_items[0]["aggregatedOutput"] = json.dumps(
            rejected, sort_keys=True, separators=(",", ":")
        )
        result = _run_assertion(
            output,
            _context(vars_, workspace, rejected_items, f"thread-{mutation}"),
            manifest_path,
        )
        assert result["pass"] is False
        assert '"exactCommandSequence":true' in result["reason"]
        assert '"exactExitSequence":true' in result["reason"]
        assert '"stdoutObservationMatches":false' in result["reason"]


def test_assertion_accepts_only_the_two_declared_source_reader_hash_redactions(
    tmp_path: Path,
) -> None:
    case_id = "DERIVED_EVIDENCE_AB"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    source_index = next(
        index for index, row in enumerate(manifest["trace"]) if "source_reader.py" in row["command"]
    )
    assert manifest["trace"][source_index]["stdout_observation"] == {
        "mode": "exact_or_allowlisted_json_redaction",
        "allowlisted_redaction_json_pointers": [
            "/selected_file_sha256",
            "/selected_stimulus_sha256",
        ],
    }
    redacted_items = json.loads(json.dumps(items))
    payload = json.loads(redacted_items[source_index]["aggregatedOutput"])
    payload["selected_file_sha256"] = "[REDACTED]"
    payload["selected_stimulus_sha256"] = "[REDACTED]"
    redacted_items[source_index]["aggregatedOutput"] = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    result = _run_assertion(
        _output(case_input, manifest["family"]),
        _context(vars_, workspace, redacted_items, "thread-source-redaction"),
        manifest_path,
    )
    assert result["pass"] is True


def test_functional_retention_stdout_remains_leaf_observable_and_rejects_display_collapse(
    tmp_path: Path,
) -> None:
    case_id = "FUNCTIONAL_RETENTION_AB"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    consumer_contract = manifest["trace"][0]
    expected_stdout = json.loads(consumer_contract["stdout"])
    assert [
        candidate["settlement_effect"]
        for candidate in expected_stdout["facts"]["candidate_substitutions"]
    ] == [
        "zodiac_product=win;color_product=win",
        "zodiac_product=win;color_product=lose",
    ]
    assert consumer_contract["stdout_observation"] == {
        "mode": "exact_or_allowlisted_json_redaction",
        "allowlisted_redaction_json_pointers": ["/case_input_sha256"],
    }

    items = _execute_manifest_trace(workspace, manifest)
    collapsed_items = json.loads(json.dumps(items))
    collapsed = json.loads(collapsed_items[0]["aggregatedOutput"])
    for candidate in collapsed["facts"]["candidate_substitutions"]:
        candidate["settlement_effect"] = "[...]"
    collapsed_items[0]["aggregatedOutput"] = json.dumps(
        collapsed, sort_keys=True, separators=(",", ":")
    )
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    result = _run_assertion(
        _output(case_input, manifest["family"]),
        _context(vars_, workspace, collapsed_items, "thread-collapsed-stdout"),
        manifest_path,
    )
    assert result["pass"] is False
    assert '"exactCommandSequence":true' in result["reason"]
    assert '"exactExitSequence":true' in result["reason"]
    assert '"stdoutObservationMatches":false' in result["reason"]
    assert '"failurePath":"/facts/candidate_substitutions/0/settlement_effect"' in result["reason"]


@pytest.mark.parametrize(
    "rewrite",
    [
        lambda contract: f"\"D:\\Runtime\\PowerShell\\pwsh.exe\" -Command '{contract}'; whoami",
        lambda contract: f"\"D:\\Runtime\\PowerShell\\pwsh.exe\" -Command '{contract}; whoami'",
        lambda contract: f"\"D:\\Runtime\\PowerShell\\powershell.exe\" -Command '{contract}'",
        lambda contract: f"\"D:\\Runtime\\PowerShell\\pwsh.exe\" -NoProfile -Command '{contract}'",
    ],
)
def test_assertion_only_unwraps_one_exact_pwsh_command_form(tmp_path: Path, rewrite: Any) -> None:
    case_id = "CONTROL_BOUNDED_READ"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    direct_items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = _output(case_input, manifest["family"])

    wrapped_items = [
        {
            **item,
            "command": (
                f"\"D:\\Runtime\\PowerShell\\pwsh.exe\" -Command '{str(item['command']).replace(chr(39), chr(39) * 2)}'"
            ),
        }
        for item in direct_items
    ]
    assert (
        _run_assertion(
            output,
            _context(vars_, workspace, wrapped_items, "thread-pwsh-wrapper"),
            manifest_path,
        )["pass"]
        is True
    )

    rejected_items = [dict(item) for item in wrapped_items]
    rejected_items[0]["command"] = rewrite(manifest["trace"][0]["command"])
    result = _run_assertion(
        output,
        _context(vars_, workspace, rejected_items, "thread-rejected-wrapper"),
        manifest_path,
    )
    assert result["pass"] is False
    assert 'exactCommandSequence":false' in result["reason"]


def test_assertion_rejects_unlisted_workspace_delta(tmp_path: Path) -> None:
    case_id = "CONTROL_BOUNDED_READ"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    (workspace / "unlisted.txt").write_text("unexpected", encoding="utf-8")
    result = _run_assertion(
        _output(case_input, manifest["family"]),
        _context(vars_, workspace, items, "thread-delta"),
        manifest_path,
    )
    assert result["pass"] is False
    assert 'exactInventory":false' in result["reason"]


def test_stop_oracle_is_zero_tool_and_zero_effect_not_a_status_self_report(
    tmp_path: Path,
) -> None:
    case_id = "EXPLICIT_STOP_NO_TOOL_OR_EFFECT"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = {
        "case_id": case_id,
        "analysis_object_id": "stop",
        "evidence_source_witness_ids": [],
        "functional_dimension_ids": [],
        "working_relation": "not_applicable",
        "relation_evidence_refs": [],
        "basis": "current explicit stop",
    }
    context = _context(vars_, workspace, [], "thread-stop")
    assert manifest["trace"] == []
    assert _run_assertion(output, context, manifest_path)["pass"] is True
    context["metadata"]["codexAppServer"]["items"].insert(
        0,
        {
            "type": "commandExecution",
            "command": f"python -B consumer.py --case {case_id}",
            "aggregatedOutput": "continued",
            "exitCode": 1,
        },
    )
    assert _run_assertion(output, context, manifest_path)["pass"] is False


def test_local_result_is_consumed_and_read_back_without_parent_status_fields(
    tmp_path: Path,
) -> None:
    case_id = "LOCAL_SETTLEMENT_RETURNS_TO_PARENT"
    workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
    items = _execute_manifest_trace(workspace, manifest)
    case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
    state = json.loads((workspace / "parent_state.json").read_text(encoding="utf-8"))
    assert (
        state["unresolved_relation_ids"]
        == case_input["initial_parent_state"]["unresolved_relation_ids"]
    )
    assert state["returned_result_ids"] == [case_input["local_result"]["claim_id"]]
    vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
    output = _output(case_input, manifest["family"])
    assert output["working_relation"] != "not_applicable"
    assert output["relation_evidence_refs"] == [
        "settled-local-claim",
        "continuing-parent-state",
    ]
    assert not {"parent_continues", "idle_due_to_local_result", "next_question_required"} & set(
        output
    )
    assert (
        _run_assertion(
            output,
            _context(vars_, workspace, items, "thread-local-return"),
            manifest_path,
        )["pass"]
        is True
    )


def test_promptfoo_adapter_is_fresh_and_output_schema_has_no_status_answers() -> None:
    config = yaml.safe_load((SUITE_ROOT / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    provider = config["providers"][0]
    settings = provider["config"]
    assert provider["id"] == "openai:codex-app-server"
    assert settings["working_dir"] == "{{env.SEMANTIC_IMPLICATION_WORKSPACE}}"
    assert settings["skip_git_repo_check"] is True
    assert settings["sandbox_mode"] == "workspace-write"
    assert settings["approval_policy"] == "never"
    assert settings["model"] == "{{env.SEMANTIC_IMPLICATION_MODEL}}"
    assert settings["model_reasoning_effort"] == (
        "{{env.SEMANTIC_IMPLICATION_MODEL_REASONING_EFFORT}}"
    )
    assert settings["ephemeral"] is True
    assert settings["reuse_server"] is False
    assert settings["inherit_process_env"] is False
    properties = settings["output_schema"]["properties"]
    assert {
        "case_id",
        "analysis_object_id",
        "evidence_source_witness_ids",
        "functional_dimension_ids",
        "working_relation",
        "relation_evidence_refs",
        "basis",
    } == set(properties)
    prompt = (SUITE_ROOT / "prompt.txt").read_text(encoding="utf-8")
    assert "When `working_relation` is `not_applicable`" in prompt
    assert "`relation_evidence_refs` must be `[]`" in prompt
    assert {
        "parent_continues",
        "idle_due_to_local_result",
        "next_question_required",
        "source_disposition",
        "durable_effect_observation",
        "consumer_action",
        "independent_evidence_count",
    }.isdisjoint(properties)


def _fake_row(
    vars_: dict[str, Any], output: dict[str, Any], workspace: Path, thread: str
) -> dict[str, Any]:
    source_items: list[dict[str, Any]] = []
    source_command = next(
        (
            row
            for row in json.loads(
                (workspace.parent.parent / "manifests" / f"{vars_['case_id']}.json").read_text(
                    encoding="utf-8"
                )
            )["trace"]
            if "source_reader.py" in row["command"]
        ),
        None,
    )
    if source_command:
        source_items.append(
            {
                "type": "commandExecution",
                "command": source_command["command"],
                "aggregatedOutput": source_command["stdout"],
                "exitCode": 0,
            }
        )
    return {
        "success": True,
        "prompt": {"raw": f"fresh scenario {vars_['case_id']}"},
        "provider": {"id": "provider:test"},
        "vars": vars_,
        "response": {
            "output": json.dumps(output),
            "metadata": {
                "codexAppServer": {
                    "threadId": thread,
                    "turnId": f"{thread}-turn",
                    "cwd": str(workspace),
                    "items": source_items,
                }
            },
        },
    }


def test_post_run_verifier_enforces_fresh_workspace_and_semantic_pair_equivalence(
    tmp_path: Path,
) -> None:
    prepared = {}
    for case_id in ("DERIVED_EVIDENCE_AB", "DERIVED_EVIDENCE_BA"):
        workspace, manifest_path, manifest = _prepare(tmp_path, case_id)
        case_input = json.loads((workspace / "case_input.json").read_text(encoding="utf-8"))
        vars_ = next(row["vars"] for row in _cases() if row["vars"]["case_id"] == case_id)
        prepared[case_id] = (
            workspace,
            manifest_path,
            manifest,
            vars_,
            _output(case_input, manifest["family"]),
        )
    rows = [
        _fake_row(
            prepared[case_id][3], prepared[case_id][4], prepared[case_id][0], f"thread-{index}"
        )
        for index, case_id in enumerate(prepared, start=1)
    ]
    for row in rows:
        source_item = row["response"]["metadata"]["codexAppServer"]["items"][0]
        source_payload = json.loads(source_item["aggregatedOutput"])
        source_payload["selected_file_sha256"] = "[REDACTED]"
        source_payload["selected_stimulus_sha256"] = "[REDACTED]"
        source_item["aggregatedOutput"] = json.dumps(
            source_payload, sort_keys=True, separators=(",", ":")
        )
    result_paths = []
    for index, row in enumerate(rows, start=1):
        path = tmp_path / f"result-{index}.json"
        path.write_text(json.dumps({"results": {"results": [row]}}), encoding="utf-8")
        result_paths.append(path)
    receipt = _verifier().verify_results(
        result_paths,
        [prepared[case_id][1] for case_id in prepared],
        required_case_count=2,
        canonical_source_sha256="a" * 64,
    )
    assert receipt["checked_metamorphic_pairs"] == ["derived-evidence-order"]
    assert receipt["fresh_thread_count"] == receipt["fresh_turn_count"] == 2
    assert receipt["fresh_workspace_count"] == 2
    changed = json.loads(result_paths[1].read_text(encoding="utf-8"))
    changed_output = json.loads(changed["results"]["results"][0]["response"]["output"])
    changed_output["functional_dimension_ids"] = ["wrong"]
    changed["results"]["results"][0]["response"]["output"] = json.dumps(changed_output)
    result_paths[1].write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="changed under AB/BA order"):
        _verifier().verify_results(result_paths, [prepared[case_id][1] for case_id in prepared])


def test_formal_suite_runner_is_dedicated_cold_and_causal_body_bound() -> None:
    readme = (SUITE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Formal suite identity: `semantic_implication_regression`" in readme
    assert "only live semantic-accident behavior suite" in readme
    runner = (REPO_ROOT / "scripts" / "run_semantic_implication_regression_eval.ps1").read_text(
        encoding="utf-8"
    )
    for required in (
        "0.121.18",
        "source_contract.v1.json",
        "repository_commit",
        "repository_tree",
        "file_blob",
        "source-snapshot.v2.json",
        "Get-CausalFileState",
        "Assert-CausalFileStatesUnchanged",
        "$liveCodexHome",
        "$evalCodexHome",
        "New-Item -ItemType SymbolicLink",
        "Remove-VerifiedAuthSymbolicLink",
        "SEMANTIC_IMPLICATION_MODEL",
        "SEMANTIC_IMPLICATION_MODEL_REASONING_EFFORT",
        "eval_codex_config",
        "codex_auth",
        "auth_bytes_copied = $false",
        'sandbox = "unelevated"',
        "snapshotSuiteStatesBefore",
        "prepare_case_workspace.py",
        "case-workspaces",
        "case-manifests",
        "--required-case-count', '14'",
        "fresh_workspace_count",
        "causal_file_stability_verified = $true",
        "$SourceContractPath",
    ):
        assert required in runner
    assert "run_behavior_regression.ps1" not in runner
    assert "git -C $workspace init" not in runner
    assert "Join-Path $nativeRepo" not in runner


def test_runner_isolates_live_home_and_rejects_eval_config_drift_before_summary(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("the canonical semantic runner is a Windows PowerShell consumer")
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    runtime_root = tmp_path / "runtime"
    package_root = runtime_root / "tools" / "promptfoo" / "node_modules" / "promptfoo"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps(
            {"name": "promptfoo", "version": "0.121.18", "bin": {"promptfoo": "fake_promptfoo.js"}}
        ),
        encoding="utf-8",
    )
    (package_root / "fake_promptfoo.js").write_text(
        """
const fs = require('fs');
const path = require('path');
const args = process.argv.slice(2);
const outputIndex = args.indexOf('--output');
if (outputIndex < 0 || !args[outputIndex + 1]) process.exit(31);
const outputPath = args[outputIndex + 1];
const authPath = path.join(process.env.CODEX_HOME, 'auth.json');
if (!fs.lstatSync(authPath).isSymbolicLink()) process.exit(32);
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(
  path.join(path.dirname(outputPath), 'auth-link-observed.json'),
  JSON.stringify({ isSymbolicLink: true, resolvesToFile: fs.statSync(authPath).isFile() }),
  'utf8',
);
const configPath = path.join(process.env.CODEX_HOME, 'config.toml');
fs.appendFileSync(configPath, '\\n# deterministic in-run drift\\n', 'utf8');
fs.writeFileSync(outputPath, '{}', 'utf8');
console.log('fake promptfoo completed');
""".strip()
        + "\n",
        encoding="utf-8",
    )
    native_repo = tmp_path / "native-source"
    native_repo.mkdir()

    def git_output(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(native_repo), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return completed.stdout.strip()

    git_output("init", "--quiet")
    git_output("config", "user.name", "Semantic Regression Fixture")
    git_output("config", "user.email", "semantic-regression@example.invalid")
    git_output("config", "commit.gpgsign", "false")
    git_output("config", "core.autocrlf", "false")
    corpus_seal = "a" * 64
    case_seal = "b" * 64
    corpus_relative = Path("semantic_accidents") / "cases.v1.json"
    corpus_path = native_repo / corpus_relative
    corpus_path.parent.mkdir()
    corpus_bytes = (
        json.dumps(
            {
                "schema_version": "xinao.semantic-accident-corpus.v1",
                "corpus_id": "semantic-regression-fixture",
                "load_policy": "explicit_cold_read_only",
                "seal": {"sha256": corpus_seal},
                "cases": [{"case_id": "fixture-case", "seal": {"sha256": case_seal}}],
            },
            indent=2,
        )
        + "\n"
    ).encode()
    corpus_path.write_bytes(corpus_bytes)
    git_output("add", "--", corpus_relative.as_posix())
    git_output("commit", "--quiet", "-m", "semantic regression fixture")
    repository_commit = git_output("rev-parse", "HEAD")
    source_contract = tmp_path / "source-contract.v1.json"
    source_contract.write_text(
        json.dumps(
            {
                "schema_version": "xinao.semantic_implication_source_contract.v1",
                "authority": False,
                "runtime_loaded": False,
                "canonical_source": {
                    "repository": str(native_repo),
                    "relative_path": corpus_relative.as_posix(),
                    "git_object_format": git_output("rev-parse", "--show-object-format"),
                    "repository_commit": repository_commit,
                    "repository_tree": git_output("rev-parse", f"{repository_commit}^{{tree}}"),
                    "file_blob": git_output(
                        "rev-parse", f"{repository_commit}:{corpus_relative.as_posix()}"
                    ),
                    "schema_version": "xinao.semantic-accident-corpus.v1",
                    "corpus_id": "semantic-regression-fixture",
                    "load_policy": "explicit_cold_read_only",
                    "file_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
                    "corpus_seal_sha256": corpus_seal,
                    "selected_case_ids": ["fixture-case"],
                    "selected_case_seals": {"fixture-case": case_seal},
                },
                "automatic_core_inclusion": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n',
        encoding="utf-8",
    )
    auth_path = codex_home / "auth.json"
    auth_path.write_text('{"test_only":"not-a-real-secret"}\n', encoding="utf-8")
    live_auth_sha256_before = hashlib.sha256(auth_path.read_bytes()).hexdigest()
    live_auth_mtime_ns_before = auth_path.stat().st_mtime_ns
    live_config_before = (codex_home / "config.toml").read_bytes()
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "uv.cmd").write_text("@exit /b 0\n", encoding="ascii")
    (fake_bin / "codex.cmd").write_text("@exit /b 0\n", encoding="ascii")
    fake_codex_package = fake_bin / "node_modules" / "@openai" / "codex"
    fake_codex_package.mkdir(parents=True)
    node_executable = shutil.which("node")
    assert node_executable is not None
    shutil.copy2(node_executable, fake_codex_package / "codex.exe")
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    runner = REPO_ROOT / "scripts" / "run_semantic_implication_regression_eval.ps1"
    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            "-SourceContractPath",
            str(source_contract),
            "-RuntimeRoot",
            str(runtime_root),
            "-CodexHome",
            str(codex_home),
            "-CasePattern",
            "^CONTROL_BOUNDED_READ$",
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )
    console = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode != 0
    assert "Causal file drifted during fresh evaluation (eval_codex_config)" in console
    assert (codex_home / "config.toml").read_bytes() == live_config_before
    assert hashlib.sha256(auth_path.read_bytes()).hexdigest() == live_auth_sha256_before
    assert auth_path.stat().st_mtime_ns == live_auth_mtime_ns_before
    run_roots = list(
        (
            runtime_root
            / "state"
            / "human-capabilities"
            / "evals"
            / "semantic-implication-regression"
        ).glob("*")
    )
    assert len(run_roots) == 1
    eval_home = run_roots[0] / "tmp" / "codex-home"
    eval_auth = eval_home / "auth.json"
    assert json.loads((run_roots[0] / "auth-link-observed.json").read_text(encoding="utf-8")) == {
        "isSymbolicLink": True,
        "resolvesToFile": True,
    }
    assert not eval_auth.exists()
    assert not eval_auth.is_symlink()
    eval_config = (eval_home / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-5.6-sol"' in eval_config
    assert 'model_reasoning_effort = "high"' in eval_config
    assert '[windows]\nsandbox = "unelevated"' in eval_config.replace("\r\n", "\n")
    assert "CONTROL_BOUNDED_READ" in eval_config
    assert list(run_roots[0].rglob("auth.json")) == []
    source_snapshot = json.loads(
        (run_roots[0] / "source-snapshot" / "source-snapshot.v2.json").read_text(encoding="utf-8")
    )
    assert source_snapshot["consumer_identity"]["authentication"] == {"auth_bytes_copied": False}
    assert not (run_roots[0] / "summary.json").exists()


def test_javascript_parses_and_contains_exact_trace_state_oracles() -> None:
    completed = subprocess.run(
        ["node", "--check", str(ASSERTION_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    text = ASSERTION_PATH.read_text(encoding="utf-8")
    for required in (
        "SEMANTIC_IMPLICATION_CASE_MANIFEST",
        "exactCommandSequence",
        "exactInventory",
        "fs.openSync(absolute, 'r')",
        "fs.fstatSync(descriptor)",
        "fs.readFileSync(descriptor)",
        "lifecycleReadback",
        "threadId",
        "turnId",
        "dynamicToolCall",
    ):
        assert required in text
    assert "fs.readFileSync(absolute)" not in text


def test_suite_contains_no_real_result_or_forbidden_future_scope() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SUITE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".txt", ".md", ".py", ".js"}
    )
    assert "2026203" not in text
    assert "2026204" not in text
    assert "2026205" not in text
    assert "history_2024-01-01_to_2026-07-01" not in text
