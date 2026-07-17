from __future__ import annotations

import json
import subprocess
from pathlib import Path

from services.agent_runtime import worker_repo_mount_identity as mount_identity

EXPECTED_D_ROOT = r"D:\XINAO_RESEARCH_RUNTIME\worktrees\s-origin-main-20260717"
STALE_E_ROOT = r"E:\XINAO_RESEARCH_WORKSPACES\S"


def _valid_mounts(repo_root: str) -> list[dict[str, object]]:
    return [
        {
            "Type": "bind",
            "Source": source,
            "Destination": destination,
            "RW": False,
        }
        for destination, source in mount_identity.expected_repo_mounts(repo_root).items()
    ]


def _issue_codes(report: dict[str, object]) -> set[str]:
    return {
        str(issue["code"])
        for issue in report["issues"]
        if isinstance(issue, dict) and "code" in issue
    }


def _assert_blocked(report: dict[str, object], expected_code: str) -> None:
    assert report["ok"] is False
    assert report["provider_invocation_allowed"] is False
    assert report["named_blocker"] == mount_identity.NAMED_BLOCKER
    assert expected_code in _issue_codes(report)


def test_windows_path_case_slashes_and_trailing_slashes_are_equivalent() -> None:
    canonical = mount_identity.normalize_windows_host_path(
        r"D:\XINAO_RESEARCH_RUNTIME\WorkTrees\Repo"
    )

    assert canonical == mount_identity.normalize_windows_host_path(
        "d:/xinao_research_runtime/worktrees/repo/"
    )
    assert canonical == mount_identity.normalize_windows_host_path(
        r"\\?\D:\XINAO_RESEARCH_RUNTIME\WORKTREES\REPO\\"
    )


def test_correct_d_repo_root_mounts_pass_with_path_spelling_variants() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    for mount in mounts:
        mount["Source"] = str(mount["Source"]).upper().replace("\\", "/") + "/"
        mount["Destination"] = str(mount["Destination"]).replace("/", "\\")

    report = mount_identity.validate_worker_repo_mounts(
        EXPECTED_D_ROOT.lower().replace("\\", "/") + "/",
        mounts,
    )

    assert report["ok"] is True
    assert report["provider_invocation_allowed"] is True
    assert report["named_blocker"] is None
    assert report["issues"] == []
    assert report["verified_mount_count"] == len(mount_identity.EXPECTED_REPO_MOUNTS)
    assert report["observed_app_mount_count"] == len(mount_identity.EXPECTED_REPO_MOUNTS)


def test_stale_e_repo_root_mounts_fail_against_expected_d_root() -> None:
    report = mount_identity.validate_worker_repo_mounts(
        EXPECTED_D_ROOT,
        _valid_mounts(STALE_E_ROOT),
    )

    _assert_blocked(report, "SOURCE_MISMATCH")
    assert report["verified_mount_count"] == 0


def test_missing_expected_mount_fails_closed() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    missing = mounts.pop()

    report = mount_identity.validate_worker_repo_mounts(EXPECTED_D_ROOT, mounts)

    _assert_blocked(report, "MISSING_MOUNT")
    assert any(
        issue.get("destination") == missing["Destination"]
        for issue in report["issues"]
        if isinstance(issue, dict)
    )


def test_duplicate_expected_mount_fails_closed() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    mounts.append(dict(mounts[0]))

    report = mount_identity.validate_worker_repo_mounts(EXPECTED_D_ROOT, mounts)

    _assert_blocked(report, "DUPLICATE_MOUNT")
    duplicate = next(issue for issue in report["issues"] if issue["code"] == "DUPLICATE_MOUNT")
    assert duplicate["observed_count"] == 2


def test_read_write_expected_mount_fails_closed() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    mounts[0]["RW"] = True

    report = mount_identity.validate_worker_repo_mounts(EXPECTED_D_ROOT, mounts)

    _assert_blocked(report, "MOUNT_NOT_READ_ONLY")


def test_non_bind_expected_mount_fails_closed() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    mounts[0]["Type"] = "volume"

    report = mount_identity.validate_worker_repo_mounts(EXPECTED_D_ROOT, mounts)

    _assert_blocked(report, "NON_BIND_MOUNT")


def test_extra_app_root_cover_mount_fails_closed() -> None:
    mounts = _valid_mounts(EXPECTED_D_ROOT)
    mounts.append(
        {
            "Type": "bind",
            "Source": STALE_E_ROOT,
            "Destination": "/app",
            "RW": False,
        }
    )

    report = mount_identity.validate_worker_repo_mounts(EXPECTED_D_ROOT, mounts)

    _assert_blocked(report, "UNEXPECTED_APP_MOUNT")
    assert any(
        issue.get("destination") == "/app"
        for issue in report["issues"]
        if isinstance(issue, dict)
    )


def test_compose_inspection_decodes_utf8_without_real_docker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    compose_dir = tmp_path / "中文目录"
    compose_dir.mkdir()
    compose_file = compose_dir / "组合.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    expected_mounts = _valid_mounts(r"D:\资料\工程")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        payload = {"services": {"houtai-gongren": {"volumes": expected_mounts}}}
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(mount_identity.subprocess, "run", fake_run)

    observed = mount_identity.inspect_compose_mounts(compose_file)

    assert observed == expected_mounts
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "strict"
    assert calls[0][1]["text"] is True
    assert calls[0][1]["cwd"] == compose_dir.resolve()


def test_container_inspection_decodes_utf8_without_real_docker(monkeypatch) -> None:
    expected_mounts = _valid_mounts(r"D:\资料\工程")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(expected_mounts, ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr(mount_identity.subprocess, "run", fake_run)

    observed = mount_identity.inspect_container_mounts("后台工人")

    assert observed == expected_mounts
    assert calls[0][0][2] == "后台工人"
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "strict"
    assert calls[0][1]["text"] is True


def test_cli_emits_unicode_report_without_real_docker(monkeypatch, capsys) -> None:
    repo_root = r"D:\资料\工程"
    monkeypatch.setattr(
        mount_identity,
        "inspect_container_mounts",
        lambda _container: _valid_mounts(repo_root),
    )

    exit_code = mount_identity.main(
        ["--repo-root", repo_root, "--mode", "actual", "--container", "后台工人"]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["ok"] is True
    assert "资料" in report["expected_repo_root"]
