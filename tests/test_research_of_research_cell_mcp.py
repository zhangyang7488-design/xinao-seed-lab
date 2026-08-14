from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from services.research_of_research.archive_query import catalog_archive
from services.research_of_research.cell import _codex_arguments
from services.research_of_research.research_cell_mcp import CONFIG_SCHEMA

SERVER_SOURCE = (
    Path(__file__).parents[1]
    / "services"
    / "research_of_research"
    / "research_cell_mcp.py"
)
ARCHIVE_SOURCE = SERVER_SOURCE.with_name("archive_query.py")


def _invoke_server(root: Path, requests: list[dict[str, object]]) -> list[dict[str, object]]:
    payload = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in requests)
    completed = subprocess.run(
        [sys.executable, "research_cell_mcp.py", "--config", "research-cell-tools.json"],
        cwd=root,
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stderr == ""
    return [json.loads(line) for line in completed.stdout.splitlines() if line]


def _write_server(root: Path) -> None:
    (root / "research_cell_mcp.py").write_bytes(SERVER_SOURCE.read_bytes())


def test_archive_stdio_mcp_uses_the_sealed_query_ledger(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    store = root / "archive" / "store"
    private = root / "archive" / "private"
    store.mkdir(parents=True)
    private.mkdir()
    (store / "alpha.txt").write_text("needle and evidence", encoding="utf-8")
    catalog = root / "archive" / "catalog.json"
    archive_config = private / "config.json"
    ledger = root / "archive" / "query-ledger.jsonl"
    catalog_archive(
        store_root=store,
        catalog_path=catalog,
        config_path=archive_config,
        ledger_path=ledger,
        portable_root=root,
        max_open_count=3,
    )
    ledger.write_text("", encoding="utf-8")
    _write_server(root)
    (root / "archive_query.py").write_bytes(ARCHIVE_SOURCE.read_bytes())
    (root / "research-cell-tools.json").write_text(
        json.dumps(
            {
                "schema": CONFIG_SCHEMA,
                "mode": "archive-query",
                "archive": {
                    "catalog_path": "archive/catalog.json",
                    "config_path": "archive/private/config.json",
                    "ledger_path": "archive/query-ledger.jsonl",
                },
            }
        ),
        encoding="utf-8",
    )

    responses = _invoke_server(
        root,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "archive_find",
                    "arguments": {"fixed_string": "needle"},
                },
            },
        ],
    )

    assert [row["id"] for row in responses] == [1, 2, 3]
    tools = responses[1]["result"]["tools"]
    assert {row["name"] for row in tools} == {
        "archive_list",
        "archive_metadata",
        "archive_find",
        "archive_open",
    }
    assert responses[2]["result"]["isError"] is False
    events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["phase"] for row in events] == ["request", "result"]
    assert events[-1]["operation"] == "find"


def test_commit_choice_writes_one_preregistered_path_and_rejects_a_second(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    _write_server(root)
    (root / "research-cell-tools.json").write_text(
        json.dumps(
            {
                "schema": CONFIG_SCHEMA,
                "mode": "commit-choice",
                "choices": {
                    "external-survey": "NEXT_EXTERNAL_SURVEY.md",
                    "algorithm-structure": "NEXT_ALGORITHM_STRUCTURE.md",
                },
                "max_content_bytes": 4096,
            }
        ),
        encoding="utf-8",
    )
    first = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "commit_choice",
            "arguments": {"choice": "algorithm-structure", "content": "rationale\n"},
        },
    }
    second = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "commit_choice",
            "arguments": {"choice": "external-survey", "content": "other\n"},
        },
    }

    responses = _invoke_server(root, [first, second])

    assert responses[0]["result"]["isError"] is False
    assert responses[1]["result"]["isError"] is True
    assert (root / "NEXT_ALGORITHM_STRUCTURE.md").read_text(encoding="utf-8") == "rationale\n"
    assert not (root / "NEXT_EXTERNAL_SURVEY.md").exists()


def test_codex_arguments_bind_only_the_frozen_local_mcp(tmp_path: Path) -> None:
    workspace = tmp_path / "isolated workspace"
    arguments = _codex_arguments(
        model="gpt-5.6-sol",
        effort="max",
        web_search="disabled",
        last_message_path=tmp_path / "last.txt",
        workspace=workspace,
        local_mcp={
            "server_id": "research_cell",
            "command": "python",
            "script_path": "research_cell_mcp.py",
            "config_path": "research-cell-tools.json",
            "enabled_tools": ["commit_choice"],
            "startup_timeout_sec": 20.0,
            "tool_timeout_sec": 120.0,
        },
    )
    rendered = "\n".join(arguments)

    assert "mcp_servers.research_cell.command='python'" in rendered
    assert "mcp_servers.research_cell.enabled_tools=['commit_choice']" in rendered
    assert "mcp_servers.research_cell.required=true" in rendered
    assert "mcp_servers.research_cell.default_tools_approval_mode='approve'" in rendered
    assert str(workspace) in rendered
    assert arguments[-1] == "-"
