"""Regression: tool-executor default ENTRYPOINT under python -I without PYTHONPATH.

Candidate-only. Does not claim live install/activate/campaign completion.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "docker" / "xinao-researcher"
TOOL_EXECUTOR = PKG / "tool_executor.py"
DOCKERFILE = PKG / "Dockerfile.tool-executor"
WAVE54_TAG = f"xinao-tool-executor:wave54-entrypoint-{uuid.uuid4().hex[:12]}"


def _scrubbed_isolated_env(home_root: Path | None = None) -> dict[str, str]:
    """Empty PYTHONPATH + drop transport/auth-like keys so self-check can pass.

    Wave59 correction vs wave54: on Windows Path.home() follows USERPROFILE
    (not HOME). Point host-home probes at a clean empty home so real
    `%USERPROFILE%\\.grok\\auth.json` cannot poison host-side isolation checks.
    """
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
    clean = (home_root or Path("/tmp")).resolve()
    clean.mkdir(parents=True, exist_ok=True)
    clean_home = str(clean)
    env["PYTHONPATH"] = ""
    env["HOME"] = clean_home
    # Windows Path.home() prefers USERPROFILE over HOME.
    env["USERPROFILE"] = clean_home
    if clean.drive:
        env["HOMEDRIVE"] = clean.drive
        env["HOMEPATH"] = "\\" + "\\".join(clean.parts[1:])
    env["TMPDIR"] = clean_home
    env["TEMP"] = clean_home
    env["TMP"] = clean_home
    env["XINAO_TOOL_EXEC_BWRAP"] = "off"
    return env


def test_tool_executor_python_isolated_no_pythonpath_empty_cwd(tmp_path: Path) -> None:
    """Default image entry shape: python -I <script> with empty cwd and no PYTHONPATH."""
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    env = _scrubbed_isolated_env(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-I", str(TOOL_EXECUTOR.resolve()), "--help"],
        cwd=str(empty_cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, (
        "isolated entrypoint must import sibling ipc_contract without PYTHONPATH\n"
        f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
    )
    assert "ModuleNotFoundError" not in completed.stderr
    assert "ipc_contract" in completed.stdout or "tool executor" in completed.stdout.lower()
    assert "usage:" in completed.stdout.lower()


def test_tool_executor_python_isolated_self_check_empty_cwd(tmp_path: Path) -> None:
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(TOOL_EXECUTOR.resolve()),
            "--lab-root",
            str(lab),
            "--self-check",
        ],
        cwd=str(empty_cwd),
        env=_scrubbed_isolated_env(home),
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout.decode(
        "utf-8", errors="replace"
    ) + completed.stderr.decode("utf-8", errors="replace")
    report = json.loads(completed.stdout.decode("utf-8"))
    assert report["schema_version"] == "xinao.tool_executor_self_check.v1"
    assert report["ok"] is True


def test_dockerfile_default_entrypoint_stays_isolated_script() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["python", "-I", "/opt/xinao-tool-executor/tool_executor.py"' in text
    assert "PYTHONPATH=/opt/xinao-tool-executor" in text
    # Isolation preserved: still python -I (not relying on PYTHONPATH at runtime).
    assert 'python", "-I"' in text or '"python", "-I"' in text


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_candidate_docker_default_entrypoint_smoke() -> None:
    """Build candidate tool image with unique wave54 tag; default ENTRYPOINT --help."""
    build = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(DOCKERFILE),
            "-t",
            WAVE54_TAG,
            str(ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, build.stderr[-4000:]
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", WAVE54_TAG, "--format", "{{.Id}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert inspect.returncode == 0
        image_id = inspect.stdout.strip()
        assert image_id.startswith("sha256:")

        smoke = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                WAVE54_TAG,
                "-I",
                "/opt/xinao-tool-executor/tool_executor.py",
                "--help",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert smoke.returncode == 0, smoke.stderr
        assert "ModuleNotFoundError" not in smoke.stderr
        assert "usage:" in smoke.stdout.lower()

        # Default image ENTRYPOINT (no override) must also boot past imports.
        # Override only argv after entrypoint via docker run <image> --help is
        # not valid for exec-form ENTRYPOINT that already ends with fixed flags;
        # probe with explicit same argv the Dockerfile declares plus --self-check
        # by replacing entrypoint args is done above. Here: inspect Config.Entrypoint.
        cfg = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                WAVE54_TAG,
                "--format",
                "{{json .Config.Entrypoint}}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert cfg.returncode == 0
        entrypoint = json.loads(cfg.stdout)
        assert entrypoint[:3] == [
            "python",
            "-I",
            "/opt/xinao-tool-executor/tool_executor.py",
        ]

        # Run default ENTRYPOINT with --self-check by appending is not possible
        # without replacing entrypoint; re-run with full default path + self-check.
        lab_probe = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "65532:65532",
                "--entrypoint",
                "python",
                "-e",
                "XINAO_TOOL_EXEC_BWRAP=off",
                WAVE54_TAG,
                "-I",
                "/opt/xinao-tool-executor/tool_executor.py",
                "--lab-root",
                "/episode-lab",
                "--self-check",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert lab_probe.returncode == 0, lab_probe.stderr
        report = json.loads(lab_probe.stdout)
        assert report["ok"] is True
        assert image_id  # retained for evidence in assertion path
    finally:
        # Do not remove pre-existing images; only this unique wave54 tag.
        subprocess.run(
            ["docker", "rmi", "-f", WAVE54_TAG],
            check=False,
            capture_output=True,
            timeout=60,
        )
