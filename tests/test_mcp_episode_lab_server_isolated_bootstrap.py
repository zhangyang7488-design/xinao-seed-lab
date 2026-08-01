"""Regression: MCP episode_lab server under python -I without PYTHONPATH.

Production argv is ``python -I /opt/xinao-researcher/mcp_episode_lab_server.py ...``
(from episode_mcp_binding.build_server_argv). Isolated mode drops script dir and
PYTHONPATH, so bare sibling imports must use the controlled same-directory loader
(already proven for tool_executor). Candidate-only host pure-Python proofs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "docker" / "xinao-researcher"
MCP_SERVER = PKG / "mcp_episode_lab_server.py"
IPC_CONTRACT = PKG / "ipc_contract.py"
TRANSPORT_BROKER = PKG / "transport_broker.py"
BINDING = PKG / "episode_mcp_binding.py"


def _scrubbed_isolated_env(home_root: Path) -> dict[str, str]:
    """Empty PYTHONPATH + drop auth-like keys so the child cannot lean on env."""
    deny_prefixes = ("GROK_", "XAI_", "OPENAI_", "ANTHROPIC_", "AWS_", "AZURE_")
    deny_keys = {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "HOME",
        "GROK_HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "DOCKER_HOST",
        "SSH_AUTH_SOCK",
        "KUBECONFIG",
    }
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in deny_keys or key.startswith(deny_prefixes):
            continue
        env[key] = value
    clean = home_root.resolve()
    clean.mkdir(parents=True, exist_ok=True)
    clean_home = str(clean)
    env["PYTHONPATH"] = ""
    env["HOME"] = clean_home
    env["USERPROFILE"] = clean_home
    if clean.drive:
        env["HOMEDRIVE"] = clean.drive
        env["HOMEPATH"] = "\\" + "\\".join(clean.parts[1:])
    env["TMPDIR"] = clean_home
    env["TEMP"] = clean_home
    env["TMP"] = clean_home
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_mcp_server_python_isolated_help_empty_cwd_no_pythonpath(tmp_path: Path) -> None:
    """Host unit: python -I <mcp_server> --help with empty cwd and no PYTHONPATH."""
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    completed = subprocess.run(
        [sys.executable, "-I", str(MCP_SERVER.resolve()), "--help"],
        cwd=str(empty_cwd),
        env=_scrubbed_isolated_env(home),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        "isolated MCP server must import sibling ipc_contract + transport_broker "
        "without PYTHONPATH\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    assert "ModuleNotFoundError" not in completed.stderr
    assert "No module named 'ipc_contract'" not in completed.stderr
    assert "No module named 'transport_broker'" not in completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "episode_lab" in completed.stdout.lower() or "mcp" in completed.stdout.lower()


def test_mcp_server_python_isolated_stdio_initialize_boundary(tmp_path: Path) -> None:
    """Host unit: fresh -I process reaches MCP initialize protocol boundary."""
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    evidence = tmp_path / "output" / "mcp_events.jsonl"
    evidence.parent.mkdir(parents=True)
    # Feed one initialize request then close stdin so serve_stdio exits cleanly.
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "isolated-bootstrap-test", "version": "0"},
            },
        },
        separators=(",", ":"),
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(MCP_SERVER.resolve()),
            "--socket",
            str(tmp_path / "tool.sock"),
            "--episode-id",
            "ep-isolated-bootstrap",
            "--evidence-path",
            str(evidence),
            "--timeout-ms",
            "1000",
        ],
        input=request + "\n",
        cwd=str(empty_cwd),
        env=_scrubbed_isolated_env(home),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    assert "ModuleNotFoundError" not in completed.stderr
    lines = [ln for ln in completed.stdout.splitlines() if ln.strip()]
    assert lines, f"expected JSON-RPC response, got {completed.stdout!r}"
    payload = json.loads(lines[0])
    assert payload.get("jsonrpc") == "2.0"
    assert payload.get("id") == 1
    result = payload.get("result") or {}
    assert result.get("serverInfo", {}).get("name") == "episode_lab"
    assert "tools" in (result.get("capabilities") or {})


def test_mcp_server_does_not_import_cwd_poison_siblings(tmp_path: Path) -> None:
    """Negative: poisoned same-name modules in cwd must not be injected under -I."""
    poison_cwd = tmp_path / "poison-cwd"
    poison_cwd.mkdir()
    # If loader ever put cwd on sys.path (or relied on bare import from cwd),
    # these modules would win and fail the process with a unique marker.
    (poison_cwd / "ipc_contract.py").write_text(
        "raise SystemExit('CWD_INJECTED_IPC_CONTRACT')\n",
        encoding="utf-8",
    )
    (poison_cwd / "transport_broker.py").write_text(
        "raise SystemExit('CWD_INJECTED_TRANSPORT_BROKER')\n",
        encoding="utf-8",
    )
    home = tmp_path / "clean-home"
    home.mkdir()
    completed = subprocess.run(
        [sys.executable, "-I", str(MCP_SERVER.resolve()), "--help"],
        cwd=str(poison_cwd),
        env=_scrubbed_isolated_env(home),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        "must load trusted same-dir siblings, not cwd poison modules\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    assert "CWD_INJECTED_IPC_CONTRACT" not in completed.stdout
    assert "CWD_INJECTED_IPC_CONTRACT" not in completed.stderr
    assert "CWD_INJECTED_TRANSPORT_BROKER" not in completed.stdout
    assert "CWD_INJECTED_TRANSPORT_BROKER" not in completed.stderr
    assert "usage:" in completed.stdout.lower()


def test_mcp_server_source_keeps_python_i_and_sibling_bootstrap() -> None:
    """Static contract: argv remains python -I; server uses controlled sibling loader."""
    server_text = MCP_SERVER.read_text(encoding="utf-8")
    assert "def _bootstrap_sibling_module" in server_text
    assert '_bootstrap_sibling_module("ipc_contract")' in server_text
    assert '_bootstrap_sibling_module("transport_broker")' in server_text
    # Must not widen import surface via sys.path mutation.
    assert "sys.path.insert" not in server_text
    assert "sys.path.append" not in server_text
    assert "PYTHONPATH" not in server_text or "ignores PYTHONPATH" in server_text

    binding_text = BINDING.read_text(encoding="utf-8")
    assert '"-I"' in binding_text or "'-I'" in binding_text
    # build_server_argv shape must keep isolated interpreter flag.
    assert "python_bin" in binding_text
    assert IPC_CONTRACT.is_file()
    assert TRANSPORT_BROKER.is_file()
