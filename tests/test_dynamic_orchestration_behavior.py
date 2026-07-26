from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / "evals" / "dynamic_orchestration"
ASSERTION_PATH = SUITE_ROOT / "assert_behavior.js"
CASES_PATH = SUITE_ROOT / "cases.yaml"
CONFIG_PATH = SUITE_ROOT / "promptfooconfig.yaml"
PROMPT_PATH = SUITE_ROOT / "prompt.txt"
SUITE_JSON_PATH = SUITE_ROOT / "suite.json"

AUTHORITY_PATH = r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt"
AUTHORITY_SENTINEL = "SENTINEL:XINAO_SOFTWARE_TOOL_GLUE_CONSTITUTION_V2"
AUTHORITY_SECTION = "## 3. 主管—工人、动态路由与额度"
AUTHORITY_OWNER = "Codex 是唯一 Owner"
AUTHORITY_PACKAGE = "普通封印整包"
AUTHORITY_CONTAINER = "隔离容器分支"
AUTHORITY_PERMISSION = "域外写入必须被拒绝"
AUTHORITY_TERMINAL = "candidate-ready waiting owner"

REQUIRED_CASE_IDS = [
    "POS_TIGHT_COUPLED_AUTHORITY_OWNER_DIRECT",
    "POS_ONE_BOUNDED_ORDINARY_PACKAGE",
    "POS_THREE_INDEPENDENT_ORDINARY_PACKAGES",
    "POS_ONE_THICK_ISOLATED_CONTAINER_BRANCH",
    "POS_THREE_INDEPENDENT_ISOLATED_BRANCHES",
    "POS_NO_POSITIVE_UNRESOLVED_ACTION",
    "REG_REJECT_SAFE_TEMPLATE_SERIALIZATION",
    "REG_REJECT_VALUELESS_PARALLELISM",
    "REG_REJECT_READONLY_COMMENTATOR_WORKER",
    "REG_FANIN_CAPACITY_ONE_THICK_BRANCH",
    "REG_FAILED_BRANCH_KEEP_HEALTHY_TWO",
    "REG_CANDIDATE_WAITING_OWNER_VERIFY",
    "REG_QUOTA_SHIFT_NARROWS_TO_OWNER_DIRECT",
]

EXECUTION_SHAPES = {
    "owner_direct",
    "single_ordinary_package",
    "multiple_ordinary_packages",
    "single_isolated_container_branch",
    "multiple_isolated_container_branches",
    "no_action",
}
CARRIER_KINDS = {"none", "ordinary_sealed_package", "isolated_container_branch"}
WORKER_EFFECTS = {"not_applicable", "candidate_read_write_test_in_domain"}
OUTSIDE_DOMAINS = {"not_applicable", "denied"}
INTEGRATION_GATES = {
    "owner_direct_completion",
    "codex_verify_adopt_formal_write_effect_verify",
    "candidate_ready_waiting_owner",
    "no_action",
}
RECOMPUTE_SCOPES = {"none", "remaining_dag", "failed_dependency_cone"}

EXPECTED_FIELD_KEYS = [
    "expected_execution_shape",
    "expected_worker_count",
    "expected_carrier_kind",
    "expected_owner_authority",
    "expected_worker_effect",
    "expected_outside_domain",
    "expected_integration_gate",
    "expected_recompute_scope",
    "expected_codex_subagent_default",
    "expected_readonly_worker_counted",
    "expected_valueless_parallelism",
    "expected_worker_self_promotes",
    "expected_formal_writer",
]

AUTHORITY_BODY = (
    f"{AUTHORITY_SENTINEL}\n"
    f"{AUTHORITY_SECTION}\n"
    f"{AUTHORITY_OWNER}、正式写者、采纳者、整合者与效果终验者。\n"
    f"一个任务使用{AUTHORITY_PACKAGE}，厚任务使用{AUTHORITY_CONTAINER}。\n"
    f"实现型工人{AUTHORITY_PERMISSION}；暂时不能验收时保持{AUTHORITY_TERMINAL}。\n"
)


def _load_cases() -> list[dict[str, Any]]:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(cases, list)
    return cases


def _cases_by_id() -> dict[str, dict[str, Any]]:
    return {case["vars"]["case_id"]: case for case in _load_cases()}


def _run_js_assertion(
    output: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    node = shutil.which("node")
    assert node, "Node.js is required to execute Promptfoo JavaScript assertions"
    program = """
const fs = require("fs");
const assertion = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const result = assertion(JSON.stringify(payload.output), payload.context);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", program, str(ASSERTION_PATH)],
        input=json.dumps({"output": output, "context": context}, ensure_ascii=False),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _output_from_case(case: dict[str, Any]) -> dict[str, object]:
    vars_ = case["vars"]
    return {
        "case_id": vars_["case_id"],
        "execution_shape": vars_["expected_execution_shape"],
        "worker_count": vars_["expected_worker_count"],
        "carrier_kind": vars_["expected_carrier_kind"],
        "owner_authority": vars_["expected_owner_authority"],
        "worker_effect": vars_["expected_worker_effect"],
        "outside_domain": vars_["expected_outside_domain"],
        "integration_gate": vars_["expected_integration_gate"],
        "recompute_scope": vars_["expected_recompute_scope"],
        "codex_subagent_default": vars_["expected_codex_subagent_default"],
        "readonly_worker_counted": vars_["expected_readonly_worker_counted"],
        "valueless_parallelism": vars_["expected_valueless_parallelism"],
        "worker_self_promotes": vars_["expected_worker_self_promotes"],
        "formal_writer": vars_["expected_formal_writer"],
        "reason": "Synthetic shape decision grounded in authority and current frontier facts.",
    }


def _base_context(
    *,
    case: dict[str, Any],
    items: list[dict[str, Any]],
    item_counts: dict[str, int],
    sandbox_mode: str = "read-only",
    approval_policy: str = "never",
    prompt_tokens: int = 120,
    completion_tokens: int = 40,
    total_tokens: int | None = None,
) -> dict[str, object]:
    total = prompt_tokens + completion_tokens if total_tokens is None else total_tokens
    return {
        "vars": case["vars"],
        "providerResponse": {
            "tokenUsage": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total,
            }
        },
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-dynamic-1",
                "turnId": "turn-dynamic-1",
                "sandboxMode": sandbox_mode,
                "approvalPolicy": approval_policy,
                "itemCounts": item_counts,
                "items": items,
            }
        },
    }


def _command_authority_item(
    *,
    command: str | None = None,
    output: str | None = None,
    exit_code: int = 0,
) -> dict[str, Any]:
    return {
        "type": "commandExecution",
        "command": command or f'Get-Content -LiteralPath "{AUTHORITY_PATH}" -Encoding UTF8',
        "aggregatedOutput": output if output is not None else AUTHORITY_BODY,
        "exitCode": exit_code,
    }


_UNSET: object = object()


def _node_repl_authority_item(
    *,
    status: str = "completed",
    error: object = None,
    include_path: bool = True,
    include_read_primitive: bool = True,
    result_text: Any = _UNSET,
    server: str = "node_repl",
    tool: str = "js",
    code: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if code is None:
        path_literal = json.dumps(AUTHORITY_PATH, ensure_ascii=False)
        body_literal = json.dumps(AUTHORITY_BODY, ensure_ascii=False)
        if include_path and include_read_primitive:
            code = (
                "var fs = await import('node:fs/promises'); "
                f"var authorityPath = {path_literal}; "
                "var text = await fs.readFile(authorityPath, 'utf8'); "
                "nodeRepl.write(text);"
            )
        elif include_path and not include_read_primitive:
            code = f"var authorityPath = {path_literal}; nodeRepl.write({body_literal});"
        else:
            code = "nodeRepl.write('hello');"
    body = AUTHORITY_BODY if result_text is _UNSET else result_text
    item: dict[str, Any] = {
        "type": "mcpToolCall",
        "status": status,
        "server": server,
        "tool": tool,
        "arguments": arguments
        if arguments is not None
        else {
            "title": "Read software tool glue constitution",
            "code": code,
        },
        "error": error,
        "durationMs": 18,
    }
    if body is None:
        item["result"] = {"content": [], "structuredContent": None, "_meta": None}
    else:
        item["result"] = {
            "content": [{"type": "text", "text": body}],
            "structuredContent": None,
            "_meta": None,
        }
    return item


def _positive_context(case: dict[str, Any], *, via: str = "command") -> dict[str, object]:
    if via == "command":
        items = [
            {"type": "userMessage"},
            _command_authority_item(),
            {"type": "agentMessage", "text": json.dumps(_output_from_case(case))},
        ]
        counts = {"userMessage": 1, "commandExecution": 1, "agentMessage": 1}
    else:
        items = [
            {"type": "userMessage"},
            _node_repl_authority_item(),
            {"type": "agentMessage", "text": json.dumps(_output_from_case(case))},
        ]
        counts = {"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1}
    return _base_context(case=case, items=items, item_counts=counts)


def test_suite_files_present() -> None:
    for path in (
        CONFIG_PATH,
        CASES_PATH,
        PROMPT_PATH,
        ASSERTION_PATH,
        SUITE_JSON_PATH,
    ):
        assert path.is_file(), f"missing suite file: {path}"


def test_promptfooconfig_sealed_interface() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["description"] == "Dynamic orchestration execution-shape regressions"
    provider = config["providers"][0]
    assert provider["id"] == "openai:codex-app-server"
    cfg = provider["config"]
    assert cfg["working_dir"] == "../.."
    assert cfg["sandbox_mode"] == "read-only"
    assert cfg["approval_policy"] == "never"
    assert cfg["ephemeral"] is True
    assert cfg["reuse_server"] is False
    assert cfg["cli_config"]["features"]["hooks"] is False
    assert cfg["turn_timeout_ms"] == 360000
    schema = cfg["output_schema"]
    required = set(schema["required"])
    assert required == set(schema["properties"])
    assert schema["properties"]["owner_authority"] == {
        "type": "string",
        "const": "codex_only",
    }
    assert schema["properties"]["formal_writer"] == {
        "type": "string",
        "const": "codex_main",
    }
    assert set(schema["properties"]["execution_shape"]["enum"]) == EXECUTION_SHAPES
    assert set(schema["properties"]["carrier_kind"]["enum"]) == CARRIER_KINDS
    assert set(schema["properties"]["worker_effect"]["enum"]) == WORKER_EFFECTS
    assert set(schema["properties"]["outside_domain"]["enum"]) == OUTSIDE_DOMAINS
    assert set(schema["properties"]["integration_gate"]["enum"]) == INTEGRATION_GATES
    assert set(schema["properties"]["recompute_scope"]["enum"]) == RECOMPUTE_SCOPES
    assert schema["properties"]["worker_count"]["minimum"] == 0
    assert schema["properties"]["worker_count"]["maximum"] == 8
    assert config["tests"] == "file://cases.yaml"
    assert config["defaultTest"]["assert"][1]["value"] == "file://assert_behavior.js"


def test_prompt_requires_real_authority_path() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert AUTHORITY_PATH in prompt
    assert "software-tool authority" in prompt or "authority" in prompt
    assert "codex_subagent_default: must be false" in prompt
    assert "worker_self_promotes: must be false" in prompt
    assert "AGENTS.md and local notes are not substitutes" in prompt


def test_case_count_ids_and_profile_distribution() -> None:
    cases = _load_cases()
    assert len(cases) == 13
    ids = [case["vars"]["case_id"] for case in cases]
    assert ids == REQUIRED_CASE_IDS
    assert len(set(ids)) == 13

    smoke_ids = {
        case["vars"]["case_id"] for case in cases if "smoke" in case["metadata"]["profiles"]
    }
    core_ids = {case["vars"]["case_id"] for case in cases if "core" in case["metadata"]["profiles"]}
    deep_ids = {case["vars"]["case_id"] for case in cases if "deep" in case["metadata"]["profiles"]}
    assert len(smoke_ids) == 7
    assert core_ids == set(REQUIRED_CASE_IDS)
    assert deep_ids == set(REQUIRED_CASE_IDS)
    # Smoke is representative subset; orchestration profile runs all without filter.
    assert smoke_ids <= core_ids <= deep_ids

    suite_meta = json.loads(SUITE_JSON_PATH.read_text(encoding="utf-8"))
    assert suite_meta["id"] == "dynamic_orchestration"
    assert suite_meta["case_count"] == 13
    assert "orchestration" in suite_meta["profiles"]


def test_expected_field_and_enum_coverage() -> None:
    cases = _cases_by_id()
    shapes_seen: set[str] = set()
    carriers_seen: set[str] = set()
    gates_seen: set[str] = set()
    recomputes_seen: set[str] = set()

    for case_id, case in cases.items():
        vars_ = case["vars"]
        assert vars_["case_id"] == case_id
        assert case["metadata"]["id"] == case_id
        for key in EXPECTED_FIELD_KEYS:
            assert key in vars_, f"{case_id} missing {key}"

        shape = vars_["expected_execution_shape"]
        assert shape in EXECUTION_SHAPES
        shapes_seen.add(shape)

        carrier = vars_["expected_carrier_kind"]
        assert carrier in CARRIER_KINDS
        carriers_seen.add(carrier)

        gate = vars_["expected_integration_gate"]
        assert gate in INTEGRATION_GATES
        gates_seen.add(gate)

        recompute = vars_["expected_recompute_scope"]
        assert recompute in RECOMPUTE_SCOPES
        recomputes_seen.add(recompute)

        assert vars_["expected_owner_authority"] == "codex_only"
        assert vars_["expected_formal_writer"] == "codex_main"
        assert vars_["expected_codex_subagent_default"] is False
        assert vars_["expected_readonly_worker_counted"] is False
        assert vars_["expected_valueless_parallelism"] is False
        assert vars_["expected_worker_self_promotes"] is False
        assert isinstance(vars_["expected_worker_count"], int)
        assert 0 <= vars_["expected_worker_count"] <= 8
        assert vars_["expected_worker_effect"] in WORKER_EFFECTS
        assert vars_["expected_outside_domain"] in OUTSIDE_DOMAINS

        if vars_["expected_worker_count"] == 0:
            assert vars_["expected_carrier_kind"] == "none"
            assert vars_["expected_worker_effect"] == "not_applicable"
            assert vars_["expected_outside_domain"] == "not_applicable"
        else:
            assert vars_["expected_worker_effect"] == "candidate_read_write_test_in_domain"
            assert vars_["expected_outside_domain"] == "denied"
            assert vars_["expected_carrier_kind"] in {
                "ordinary_sealed_package",
                "isolated_container_branch",
            }

    assert shapes_seen == EXECUTION_SHAPES
    assert carriers_seen == CARRIER_KINDS
    assert gates_seen == INTEGRATION_GATES
    assert recomputes_seen == RECOMPUTE_SCOPES


def test_positive_and_prohibited_shape_expectations() -> None:
    cases = _cases_by_id()

    assert (
        cases["POS_TIGHT_COUPLED_AUTHORITY_OWNER_DIRECT"]["vars"]["expected_execution_shape"]
        == "owner_direct"
    )
    assert cases["POS_TIGHT_COUPLED_AUTHORITY_OWNER_DIRECT"]["vars"]["expected_worker_count"] == 0

    assert (
        cases["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]["vars"]["expected_execution_shape"]
        == "single_ordinary_package"
    )
    assert cases["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]["vars"]["expected_worker_count"] == 1

    assert (
        cases["POS_THREE_INDEPENDENT_ORDINARY_PACKAGES"]["vars"]["expected_execution_shape"]
        == "multiple_ordinary_packages"
    )
    assert cases["POS_THREE_INDEPENDENT_ORDINARY_PACKAGES"]["vars"]["expected_worker_count"] == 3

    assert (
        cases["POS_ONE_THICK_ISOLATED_CONTAINER_BRANCH"]["vars"]["expected_execution_shape"]
        == "single_isolated_container_branch"
    )
    assert cases["POS_THREE_INDEPENDENT_ISOLATED_BRANCHES"]["vars"]["expected_worker_count"] == 3
    assert (
        cases["POS_NO_POSITIVE_UNRESOLVED_ACTION"]["vars"]["expected_execution_shape"]
        == "no_action"
    )

    assert (
        cases["REG_REJECT_SAFE_TEMPLATE_SERIALIZATION"]["vars"]["expected_execution_shape"]
        == "single_ordinary_package"
    )
    assert (
        cases["REG_REJECT_VALUELESS_PARALLELISM"]["vars"]["expected_execution_shape"]
        == "owner_direct"
    )
    assert cases["REG_REJECT_READONLY_COMMENTATOR_WORKER"]["vars"]["expected_worker_count"] == 0
    assert (
        cases["REG_REJECT_READONLY_COMMENTATOR_WORKER"]["vars"]["expected_readonly_worker_counted"]
        is False
    )

    assert (
        cases["REG_FANIN_CAPACITY_ONE_THICK_BRANCH"]["vars"]["expected_execution_shape"]
        == "single_isolated_container_branch"
    )
    assert (
        cases["REG_FANIN_CAPACITY_ONE_THICK_BRANCH"]["vars"]["expected_recompute_scope"]
        == "remaining_dag"
    )
    assert cases["REG_FAILED_BRANCH_KEEP_HEALTHY_TWO"]["vars"]["expected_worker_count"] == 2
    assert (
        cases["REG_FAILED_BRANCH_KEEP_HEALTHY_TWO"]["vars"]["expected_recompute_scope"]
        == "failed_dependency_cone"
    )
    assert (
        cases["REG_CANDIDATE_WAITING_OWNER_VERIFY"]["vars"]["expected_integration_gate"]
        == "candidate_ready_waiting_owner"
    )
    assert (
        cases["REG_CANDIDATE_WAITING_OWNER_VERIFY"]["vars"]["expected_worker_self_promotes"]
        is False
    )
    assert (
        cases["REG_QUOTA_SHIFT_NARROWS_TO_OWNER_DIRECT"]["vars"]["expected_execution_shape"]
        == "owner_direct"
    )


def test_assertion_source_binds_authority_trace_predicates() -> None:
    source = ASSERTION_PATH.read_text(encoding="utf-8")
    for required in (
        AUTHORITY_SENTINEL,
        AUTHORITY_SECTION,
        AUTHORITY_PACKAGE,
        AUTHORITY_CONTAINER,
        AUTHORITY_PERMISSION,
        AUTHORITY_TERMINAL,
        "commandExecution",
        "node_repl",
        "readFile",
        "commandInvokesFilesystemRead",
        "resultHasAuthorityBody",
        "worker_self_promotes",
        "codex_subagent_default",
        "readonly_worker_counted",
        "valueless_parallelism",
        "formal_writer",
        "owner_authority",
    ):
        assert required in source


def test_assertion_accepts_command_execution_authority_read() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    result = _run_js_assertion(output, _positive_context(case, via="command"))
    assert result["pass"] is True
    assert result["score"] == 1
    assert "authorityCommandReads" in result["reason"]


def test_assertion_accepts_node_repl_mcp_authority_read() -> None:
    case = _cases_by_id()["POS_THREE_INDEPENDENT_ISOLATED_BRANCHES"]
    output = _output_from_case(case)
    result = _run_js_assertion(output, _positive_context(case, via="mcp"))
    assert result["pass"] is True
    assert result["score"] == 1
    assert "authorityMcpReads" in result["reason"]


def test_assertion_rejects_missing_authority_read_trace() -> None:
    case = _cases_by_id()["POS_TIGHT_COUPLED_AUTHORITY_OWNER_DIRECT"]
    output = _output_from_case(case)
    items = [
        {"type": "userMessage"},
        {"type": "agentMessage", "text": json.dumps(output)},
    ]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "agentMessage": 1},
    )
    result = _run_js_assertion(output, context)
    assert result["pass"] is False


def test_assertion_rejects_path_only_command_echo() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    items = [
        {"type": "userMessage"},
        _command_authority_item(output=AUTHORITY_PATH),
        {"type": "agentMessage"},
    ]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_marker_only_command_echo() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    items = [
        {"type": "userMessage"},
        _command_authority_item(output=AUTHORITY_SENTINEL),
        {"type": "agentMessage"},
    ]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_full_constant_command_echo_without_read() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    fake_command = f'Write-Output "{AUTHORITY_PATH}"'
    items = [
        {"type": "userMessage"},
        _command_authority_item(command=fake_command, output=AUTHORITY_BODY),
        {"type": "agentMessage"},
    ]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_stale_authority_body_without_new_shape_contract() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    stale_body = (
        f"{AUTHORITY_SENTINEL}\n{AUTHORITY_SECTION}\n"
        f"{AUTHORITY_OWNER}、权威写者、整合者与终验者；动态 DAG。\n"
    )
    items = [
        {"type": "userMessage"},
        _command_authority_item(output=stale_body),
        {"type": "agentMessage"},
    ]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_path_only_mcp_false_green() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    item = _node_repl_authority_item(
        server="fake_server",
        tool="echo",
        arguments={"title": AUTHORITY_PATH},
        result_text=AUTHORITY_SENTINEL,
    )
    items = [{"type": "userMessage"}, item, {"type": "agentMessage"}]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_marker_only_mcp_result() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    item = _node_repl_authority_item(result_text=AUTHORITY_SENTINEL)
    items = [{"type": "userMessage"}, item, {"type": "agentMessage"}]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_constant_write_without_filesystem_read() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    item = _node_repl_authority_item(
        include_path=True,
        include_read_primitive=False,
        result_text=AUTHORITY_BODY,
    )
    items = [{"type": "userMessage"}, item, {"type": "agentMessage"}]
    context = _base_context(
        case=case,
        items=items,
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_wrong_server_or_tool() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)
    wrong_server = _node_repl_authority_item(server="filesystem")
    wrong_tool = _node_repl_authority_item(tool="python")
    for item in (wrong_server, wrong_tool):
        context = _base_context(
            case=case,
            items=[{"type": "userMessage"}, item, {"type": "agentMessage"}],
            item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
        )
        assert _run_js_assertion(output, context)["pass"] is False


def test_assertion_rejects_authority_and_self_promotion_loopholes() -> None:
    case = _cases_by_id()["REG_CANDIDATE_WAITING_OWNER_VERIFY"]
    good = _output_from_case(case)
    context = _positive_context(case, via="command")
    assert _run_js_assertion(good, context)["pass"] is True

    self_promote = deepcopy(good)
    self_promote["worker_self_promotes"] = True
    self_promote["integration_gate"] = "codex_verify_adopt_formal_write_effect_verify"
    assert _run_js_assertion(self_promote, context)["pass"] is False

    subagent_default = deepcopy(good)
    subagent_default["codex_subagent_default"] = True
    assert _run_js_assertion(subagent_default, context)["pass"] is False

    readonly_counted = deepcopy(good)
    readonly_counted["readonly_worker_counted"] = True
    assert _run_js_assertion(readonly_counted, context)["pass"] is False

    valueless = deepcopy(good)
    valueless["valueless_parallelism"] = True
    assert _run_js_assertion(valueless, context)["pass"] is False

    wrong_owner = deepcopy(good)
    wrong_owner["owner_authority"] = "shared"
    assert _run_js_assertion(wrong_owner, context)["pass"] is False

    wrong_writer = deepcopy(good)
    wrong_writer["formal_writer"] = "worker"
    assert _run_js_assertion(wrong_writer, context)["pass"] is False


def test_assertion_rejects_shape_mismatch_and_zero_tokens() -> None:
    case = _cases_by_id()["POS_THREE_INDEPENDENT_ORDINARY_PACKAGES"]
    output = _output_from_case(case)
    context = _positive_context(case, via="command")
    assert _run_js_assertion(output, context)["pass"] is True

    wrong_shape = deepcopy(output)
    wrong_shape["execution_shape"] = "owner_direct"
    wrong_shape["worker_count"] = 0
    wrong_shape["carrier_kind"] = "none"
    wrong_shape["worker_effect"] = "not_applicable"
    wrong_shape["outside_domain"] = "not_applicable"
    wrong_shape["integration_gate"] = "owner_direct_completion"
    assert _run_js_assertion(wrong_shape, context)["pass"] is False

    zero_prompt = _base_context(
        case=case,
        items=context["metadata"]["codexAppServer"]["items"],
        item_counts=context["metadata"]["codexAppServer"]["itemCounts"],
        prompt_tokens=0,
        completion_tokens=10,
    )
    assert _run_js_assertion(output, zero_prompt)["pass"] is False

    wrong_sandbox = _base_context(
        case=case,
        items=context["metadata"]["codexAppServer"]["items"],
        item_counts=context["metadata"]["codexAppServer"]["itemCounts"],
        sandbox_mode="workspace-write",
    )
    assert _run_js_assertion(output, wrong_sandbox)["pass"] is False


def test_assertion_rejects_failed_command_or_empty_mcp() -> None:
    case = _cases_by_id()["POS_ONE_BOUNDED_ORDINARY_PACKAGE"]
    output = _output_from_case(case)

    failed_cmd = _base_context(
        case=case,
        items=[
            {"type": "userMessage"},
            _command_authority_item(exit_code=1),
            {"type": "agentMessage"},
        ],
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, failed_cmd)["pass"] is False

    empty_mcp = _base_context(
        case=case,
        items=[
            {"type": "userMessage"},
            _node_repl_authority_item(result_text=None),
            {"type": "agentMessage"},
        ],
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(output, empty_mcp)["pass"] is False


def test_all_cases_pass_synthetic_positive_trace() -> None:
    for case in _load_cases():
        output = _output_from_case(case)
        via = "mcp" if "ISOLATED" in case["vars"]["case_id"] else "command"
        result = _run_js_assertion(output, _positive_context(case, via=via))
        assert result["pass"] is True, case["vars"]["case_id"]
