from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "safe-cleanup"
MCP_ROOT = PLUGIN_ROOT / "mcp"
sys.path.insert(0, str(MCP_ROOT))


def _service(
    tmp_path: Path,
    *,
    protected: list[Path] | None = None,
    git_roots: list[Path] | None = None,
    quarantine_root: Path | None = None,
):
    from safe_cleanup_core import SafeCleanupService

    config = tmp_path / "safe-cleanup-config.json"
    config.write_text(
        json.dumps(
            {
                "protected_exact": [str(path) for path in protected or []],
                "protected_subtrees": [],
                "git_roots": [str(path) for path in git_roots or []],
                "quarantine_roots": {
                    tmp_path.drive.upper(): str(quarantine_root or tmp_path / "quarantine")
                },
            }
        ),
        encoding="utf-8",
    )
    return SafeCleanupService(state_root=tmp_path / "state", config_path=config)


def _plan(service, target: Path, *, disposition: str = "permanent") -> dict[str, object]:
    return service.plan_cleanup(
        paths=[str(target)],
        disposition=disposition,
        classification="committed_recoverable",
        justification="classified disposable test fixture",
        recovery_basis="recreated by this test",
    )


@pytest.mark.skipif(os.name != "nt", reason="safe-cleanup is a Windows capability")
def test_plan_and_execute_exact_permanent_cleanup(tmp_path: Path) -> None:
    service = _service(tmp_path)
    target = tmp_path / "ordinary-target"
    target.mkdir()
    (target / "payload.bin").write_bytes(b"payload")

    plan = _plan(service, target)
    assert plan["ok"] is True
    assert plan["ready"] is True

    result = service.execute_cleanup(
        plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
    )

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert not target.exists()
    assert result["targets"][0]["source_absent"] is True


@pytest.mark.skipif(os.name != "nt", reason="safe-cleanup is a Windows capability")
def test_completed_plan_never_deletes_a_recreated_target(tmp_path: Path) -> None:
    service = _service(tmp_path)
    target = tmp_path / "recreated-target"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    plan = _plan(service, target)
    first = service.execute_cleanup(
        plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
    )
    assert first["status"] == "completed"

    target.mkdir()
    replacement = target / "new.txt"
    replacement.write_text("new", encoding="utf-8")
    replay = service.execute_cleanup(
        plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
    )

    assert replay["ok"] is False
    assert replay["error_code"] == "TARGET_REAPPEARED"
    assert replacement.read_text(encoding="utf-8") == "new"


@pytest.mark.skipif(os.name != "nt", reason="safe-cleanup is a Windows capability")
def test_protected_path_and_registered_worktree_are_refused(tmp_path: Path) -> None:
    protected = tmp_path / "protected"
    protected.mkdir()
    worktree = tmp_path / "active-worktree"
    worktree.mkdir()
    initialized = subprocess.run(
        ["git", "-C", str(worktree), "init"], capture_output=True, text=True, check=False
    )
    if initialized.returncode != 0:
        pytest.skip(f"git init unavailable: {initialized.stderr}")
    service = _service(tmp_path, protected=[protected], git_roots=[worktree])

    protected_plan = _plan(service, protected)
    worktree_plan = _plan(service, worktree)

    assert protected_plan["ok"] is False
    assert protected_plan["error_code"] == "PROTECTED_PATH"
    assert protected.exists()
    assert worktree_plan["ok"] is False
    assert worktree_plan["error_code"] == "ACTIVE_GIT_WORKTREE"
    assert worktree.exists()


@pytest.mark.skipif(os.name != "nt", reason="safe-cleanup is a Windows capability")
def test_ancestor_of_protected_or_quarantine_root_is_refused(tmp_path: Path) -> None:
    protected = tmp_path / "parent" / "protected"
    protected.mkdir(parents=True)
    quarantine_root = tmp_path / "quarantine-parent" / "safe-cleanup"
    quarantine_root.mkdir(parents=True)
    service = _service(tmp_path, protected=[protected], quarantine_root=quarantine_root)

    protected_ancestor = _plan(service, protected.parent)
    quarantine_ancestor = _plan(service, quarantine_root.parent)

    assert protected_ancestor["ok"] is False
    assert protected_ancestor["error_code"] == "PROTECTED_PATH"
    assert quarantine_ancestor["ok"] is False
    assert quarantine_ancestor["error_code"] == "PROTECTED_PATH"
    assert protected.exists()
    assert quarantine_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="safe-cleanup is a Windows capability")
def test_stale_plan_fails_before_any_mutation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    target = tmp_path / "stale-target"
    target.mkdir()
    (target / "before.txt").write_text("before", encoding="utf-8")
    plan = _plan(service, target)
    (target / "after.txt").write_text("after", encoding="utf-8")

    result = service.execute_cleanup(
        plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
    )

    assert result["ok"] is False
    assert result["error_code"] == "PLAN_STALE"
    assert target.exists()
    assert (target / "before.txt").exists()
    assert (target / "after.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="junction semantics are Windows-specific")
def test_cleanup_never_traverses_reparse_points(tmp_path: Path) -> None:
    service = _service(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "must-survive.txt"
    sentinel.write_text("keep", encoding="utf-8")
    target = tmp_path / "reparse-target"
    target.mkdir()
    junction = target / "outside-link"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr or created.stdout}")

    plan = _plan(service, target)
    result = service.execute_cleanup(
        plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
    )

    assert result["ok"] is True
    assert not target.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(os.name != "nt", reason="ACL repair is Windows-specific")
def test_access_denied_tree_is_repaired_and_deleted_when_elevated(tmp_path: Path) -> None:
    from safe_cleanup_core import current_process_is_administrator

    if not current_process_is_administrator():
        pytest.skip("elevated Windows token is required for the ACL repair integration test")
    service = _service(tmp_path)
    target = tmp_path / "acl-target"
    target.mkdir()
    (target / "denied.txt").write_text("blocked", encoding="utf-8")
    locked = subprocess.run(
        [
            "icacls.exe",
            str(target),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "/T",
            "/C",
            "/Q",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if locked.returncode != 0:
        pytest.skip(f"could not create ACL fixture: {locked.stderr or locked.stdout}")

    try:
        plan = _plan(service, target)
        assert plan["ready"] is True
        result = service.execute_cleanup(
            plan_id=str(plan["plan_id"]), plan_sha256=str(plan["plan_sha256"])
        )
        assert result["ok"] is True, result
        assert result["targets"][0]["acl_repair_attempted"] is True
        assert not target.exists()
    finally:
        if target.exists():
            subprocess.run(
                ["takeown.exe", "/F", str(target), "/A", "/R", "/D", "Y"],
                capture_output=True,
                check=False,
            )
            subprocess.run(
                [
                    "icacls.exe",
                    str(target),
                    "/grant:r",
                    "*S-1-5-32-544:(OI)(CI)F",
                    "/T",
                    "/C",
                    "/Q",
                ],
                capture_output=True,
                check=False,
            )
            shutil.rmtree(target, ignore_errors=True)


@pytest.mark.skipif(os.name != "nt", reason="plugin MCP entry is Windows-specific")
def test_mcp_server_advertises_only_typed_plan_and_execute_tools() -> None:
    from mcp.client.stdio import stdio_client

    from mcp import ClientSession, StdioServerParameters

    async def exercise() -> list[str]:
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(MCP_ROOT / "server.py")],
            cwd=str(PLUGIN_ROOT),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    assert asyncio.run(exercise()) == ["safe_cleanup_plan", "safe_cleanup_execute"]


def test_plugin_manifest_and_skill_are_validation_ready() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    mcp_config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    skill = (PLUGIN_ROOT / "skills" / "safe-cleanup" / "SKILL.md").read_text(encoding="utf-8")

    assert manifest["name"] == "safe-cleanup"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert set(mcp_config["mcpServers"]) == {"safe-cleanup"}
    assert "arbitrary command" in skill.lower()
    assert "[TODO:" not in skill
