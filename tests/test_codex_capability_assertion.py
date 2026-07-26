from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSERTION_PATH = REPO_ROOT / "evals" / "codex_capability" / "assert_capability.js"
FIXTURE_BODY = "HUMAN_CAPABILITY_EVAL_OK\r\nThis fixture has exactly two non-empty lines.\r\n"
SUCCESS_OUTPUT = {
    "marker": "HUMAN_CAPABILITY_EVAL_OK",
    "non_empty_line_count": 2,
    "mode": "read-only",
}


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
        input=json.dumps({"output": output, "context": context}),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(completed.stdout)


def _base_context(
    *,
    items: list[dict[str, Any]],
    item_counts: dict[str, int],
    sandbox_mode: str = "read-only",
    approval_policy: str = "never",
    prompt_tokens: int = 100,
    completion_tokens: int = 10,
    total_tokens: int | None = None,
) -> dict[str, object]:
    total = prompt_tokens + completion_tokens if total_tokens is None else total_tokens
    return {
        "providerResponse": {
            "tokenUsage": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total,
            }
        },
        "metadata": {
            "codexAppServer": {
                "threadId": "thread-test-1",
                "turnId": "turn-test-1",
                "sandboxMode": sandbox_mode,
                "approvalPolicy": approval_policy,
                "itemCounts": item_counts,
                "items": items,
            }
        },
    }


def _command_execution_item() -> dict[str, Any]:
    return {
        "type": "commandExecution",
        "command": "Get-Content evals/codex_capability/fixture.txt",
        "aggregatedOutput": FIXTURE_BODY,
        "exitCode": 0,
    }


def _node_repl_mcp_item(
    *,
    status: str = "completed",
    error: object = None,
    include_fixture_path: bool = True,
    include_read_primitive: bool = True,
    result_text: str | None = FIXTURE_BODY,
    server: str = "node_repl",
    tool: str = "js",
    code: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if code is None:
        if include_fixture_path and include_read_primitive:
            code = (
                "var fs = await import('node:fs/promises'); "
                "var fixturePath = 'evals/codex_capability/fixture.txt'; "
                "var fixtureText = await fs.readFile(fixturePath, 'utf8'); "
                "nodeRepl.write(fixtureText);"
            )
        elif include_fixture_path and not include_read_primitive:
            # Path present but no filesystem read — constant write / echo.
            code = (
                "var fixturePath = 'evals/codex_capability/fixture.txt'; "
                "nodeRepl.write('HUMAN_CAPABILITY_EVAL_OK\\n"
                "This fixture has exactly two non-empty lines.\\n');"
            )
        else:
            code = "nodeRepl.write('hello');"
    item: dict[str, Any] = {
        "type": "mcpToolCall",
        "status": status,
        "server": server,
        "tool": tool,
        "arguments": arguments
        if arguments is not None
        else {
            "title": "Read fixture",
            "code": code,
        },
        "error": error,
        "durationMs": 12,
    }
    if result_text is None:
        item["result"] = {"content": [], "structuredContent": None, "_meta": None}
    else:
        item["result"] = {
            "content": [{"type": "text", "text": result_text}],
            "structuredContent": None,
            "_meta": None,
        }
    return item


def _mcp_only_context(item: dict[str, Any]) -> dict[str, object]:
    return _base_context(
        items=[
            {"type": "userMessage"},
            item,
            {"type": "agentMessage", "text": json.dumps(SUCCESS_OUTPUT)},
        ],
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )


def test_assertion_accepts_command_execution_local_read() -> None:
    items = [
        {"type": "userMessage"},
        _command_execution_item(),
        {
            "type": "agentMessage",
            "text": json.dumps(SUCCESS_OUTPUT),
        },
    ]
    context = _base_context(
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    result = _run_js_assertion(SUCCESS_OUTPUT, context)
    assert result["pass"] is True
    assert result["score"] == 1


def test_assertion_accepts_completed_node_repl_mcp_fixture_read() -> None:
    items = [
        {"type": "userMessage"},
        {"type": "reasoning", "summary": [], "content": []},
        _node_repl_mcp_item(),
        {
            "type": "agentMessage",
            "text": json.dumps(SUCCESS_OUTPUT),
        },
    ]
    context = _base_context(
        items=items,
        item_counts={
            "userMessage": 1,
            "reasoning": 1,
            "mcpToolCall": 1,
            "agentMessage": 1,
        },
    )
    result = _run_js_assertion(SUCCESS_OUTPUT, context)
    assert result["pass"] is True
    assert result["score"] == 1
    assert "mcpFixtureReads" in result["reason"]


def test_assertion_rejects_agent_message_only_without_local_read() -> None:
    items = [
        {"type": "userMessage"},
        {
            "type": "agentMessage",
            "text": json.dumps(SUCCESS_OUTPUT),
        },
    ]
    context = _base_context(
        items=items,
        item_counts={"userMessage": 1, "agentMessage": 1},
    )
    result = _run_js_assertion(SUCCESS_OUTPUT, context)
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_failed_or_empty_mcp_tool_call() -> None:
    failed_items = [
        {"type": "userMessage"},
        _node_repl_mcp_item(status="failed", error={"message": "boom"}),
        {
            "type": "agentMessage",
            "text": json.dumps(SUCCESS_OUTPUT),
        },
    ]
    failed_context = _base_context(
        items=failed_items,
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, failed_context)["pass"] is False

    errored = _node_repl_mcp_item(error="read failed")
    errored_context = _base_context(
        items=[{"type": "userMessage"}, errored, {"type": "agentMessage"}],
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, errored_context)["pass"] is False

    empty = _node_repl_mcp_item(result_text=None)
    empty_context = _base_context(
        items=[{"type": "userMessage"}, empty, {"type": "agentMessage"}],
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, empty_context)["pass"] is False

    no_path = _node_repl_mcp_item(
        include_fixture_path=False,
        result_text="HUMAN_CAPABILITY_EVAL_OK\n",
    )
    no_path_context = _base_context(
        items=[{"type": "userMessage"}, no_path, {"type": "agentMessage"}],
        item_counts={"userMessage": 1, "mcpToolCall": 1, "agentMessage": 1},
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, no_path_context)["pass"] is False


def test_assertion_rejects_wrong_server_mcp_tool_call() -> None:
    item = _node_repl_mcp_item(server="fake_server")
    result = _run_js_assertion(SUCCESS_OUTPUT, _mcp_only_context(item))
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_wrong_tool_mcp_tool_call() -> None:
    item = _node_repl_mcp_item(tool="echo")
    result = _run_js_assertion(SUCCESS_OUTPUT, _mcp_only_context(item))
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_path_only_echo_mcp_false_green() -> None:
    """Owner-reproduced false green: fake_server/echo with fixture path in title only."""
    item = _node_repl_mcp_item(
        server="fake_server",
        tool="echo",
        arguments={"title": "fixture.txt"},
        result_text="HUMAN_CAPABILITY_EVAL_OK",
    )
    result = _run_js_assertion(SUCCESS_OUTPUT, _mcp_only_context(item))
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_marker_only_mcp_result() -> None:
    item = _node_repl_mcp_item(result_text="HUMAN_CAPABILITY_EVAL_OK")
    result = _run_js_assertion(SUCCESS_OUTPUT, _mcp_only_context(item))
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_constant_write_without_filesystem_read() -> None:
    item = _node_repl_mcp_item(
        include_fixture_path=True,
        include_read_primitive=False,
        result_text=FIXTURE_BODY,
    )
    result = _run_js_assertion(SUCCESS_OUTPUT, _mcp_only_context(item))
    assert result["pass"] is False
    assert result["score"] == 0


def test_assertion_rejects_wrong_sandbox_and_zero_tokens() -> None:
    items = [
        {"type": "userMessage"},
        _node_repl_mcp_item(),
        {"type": "agentMessage", "text": json.dumps(SUCCESS_OUTPUT)},
    ]
    good_counts = {
        "userMessage": 1,
        "mcpToolCall": 1,
        "agentMessage": 1,
    }
    wrong_sandbox = _base_context(
        items=items,
        item_counts=good_counts,
        sandbox_mode="workspace-write",
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, wrong_sandbox)["pass"] is False

    wrong_approval = _base_context(
        items=items,
        item_counts=good_counts,
        approval_policy="on-request",
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, wrong_approval)["pass"] is False

    zero_prompt = _base_context(
        items=items,
        item_counts=good_counts,
        prompt_tokens=0,
        completion_tokens=10,
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, zero_prompt)["pass"] is False

    zero_completion = _base_context(
        items=items,
        item_counts=good_counts,
        prompt_tokens=10,
        completion_tokens=0,
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, zero_completion)["pass"] is False

    undercounted_total = _base_context(
        items=items,
        item_counts=good_counts,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=10,
    )
    assert _run_js_assertion(SUCCESS_OUTPUT, undercounted_total)["pass"] is False


def test_assertion_still_requires_marker_line_count_mode_and_thread_ids() -> None:
    items = [
        {"type": "userMessage"},
        _command_execution_item(),
        {"type": "agentMessage"},
    ]
    context = _base_context(
        items=items,
        item_counts={"userMessage": 1, "commandExecution": 1, "agentMessage": 1},
    )
    bad_marker = deepcopy(SUCCESS_OUTPUT)
    bad_marker["marker"] = "NOPE"
    assert _run_js_assertion(bad_marker, context)["pass"] is False

    bad_count = deepcopy(SUCCESS_OUTPUT)
    bad_count["non_empty_line_count"] = 1
    assert _run_js_assertion(bad_count, context)["pass"] is False

    bad_mode = deepcopy(SUCCESS_OUTPUT)
    bad_mode["mode"] = "workspace-write"
    assert _run_js_assertion(bad_mode, context)["pass"] is False

    missing_thread = deepcopy(context)
    missing_thread["metadata"]["codexAppServer"]["threadId"] = ""
    assert _run_js_assertion(SUCCESS_OUTPUT, missing_thread)["pass"] is False

    missing_turn = deepcopy(context)
    missing_turn["metadata"]["codexAppServer"]["turnId"] = None
    assert _run_js_assertion(SUCCESS_OUTPUT, missing_turn)["pass"] is False
