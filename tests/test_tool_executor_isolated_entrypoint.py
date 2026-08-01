"""Regression: tool-executor default ENTRYPOINT under python -I without PYTHONPATH.

Test classes (do not conflate):

1. Host pure-Python unit — entrypoint import + self-check machinery under
   scrubbed env / empty cwd. Filesystem auth probes use an injected synthetic
   root so the CI runner's own /var/run/docker.sock cannot masquerade as a
   tool-container violation.
2. Dockerfile static contract — ENTRYPOINT / PYTHONPATH shape.
3. Linux container smoke — build candidate image and run under --network none;
   only when docker engine OSType is linux. Proves real container has no
   docker.sock, network none, and entrypoint works with empty workdir.

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
WAVE54_SMOKE_NAME = f"xinao-wave54-tool-smoke-{uuid.uuid4().hex[:12]}"


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


def _docker_engine_ostype() -> tuple[str | None, str]:
    """Return (OSType lowercased or None, evidence reason)."""
    if shutil.which("docker") is None:
        return None, "docker binary not available on PATH"
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"docker info failed: {exc}"
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()[:300]
        return None, f"docker info rc={completed.returncode}: {err}"
    ostype = (completed.stdout or "").strip().lower()
    if not ostype:
        return None, "docker info returned empty OSType"
    return ostype, f"docker engine OSType={ostype!r}"


def _require_linux_container_engine() -> str:
    """Skip with evidence when engine cannot run Linux tool-executor images."""
    ostype, evidence = _docker_engine_ostype()
    if ostype is None:
        pytest.skip(evidence)
    if ostype != "linux":
        pytest.skip(
            f"{evidence}; Linux candidate tool-executor image has no matching "
            f"manifest for windows/amd64 (or other non-linux) engines"
        )
    return evidence


def test_tool_executor_python_isolated_no_pythonpath_empty_cwd(tmp_path: Path) -> None:
    """Host unit: python -I <script> with empty cwd and no PYTHONPATH imports sibling."""
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
    """Host unit: self-check machinery under empty cwd + scrubbed env.

    Filesystem probes use --self-check-fs-root (empty synthetic tree). This is
    NOT a claim that the host is a tool container; runner-host docker.sock must
    not fail this pure-Python contract. Real socket absence is proven only by
    the Linux container smoke below (no fs_root override).
    """
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    probe_root = tmp_path / "self-check-fs-root"
    probe_root.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(TOOL_EXECUTOR.resolve()),
            "--lab-root",
            str(lab),
            "--self-check",
            "--self-check-fs-root",
            str(probe_root),
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
    assert report.get("fs_root") == str(probe_root)
    assert report["violations"] == []


def test_tool_executor_self_check_detects_socket_under_probe_root(tmp_path: Path) -> None:
    """Host unit: injected probe root still detects planted docker.sock (check not deleted)."""
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    home = tmp_path / "clean-home"
    home.mkdir()
    probe_root = tmp_path / "self-check-fs-root"
    sock_dir = probe_root / "var" / "run"
    sock_dir.mkdir(parents=True)
    sock = sock_dir / "docker.sock"
    sock.write_text("planted", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(TOOL_EXECUTOR.resolve()),
            "--lab-root",
            str(lab),
            "--self-check",
            "--self-check-fs-root",
            str(probe_root),
        ],
        cwd=str(empty_cwd),
        env=_scrubbed_isolated_env(home),
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 2, completed.stdout.decode(
        "utf-8", errors="replace"
    ) + completed.stderr.decode("utf-8", errors="replace")
    report = json.loads(completed.stdout.decode("utf-8"))
    assert report["ok"] is False
    joined = " ".join(report["violations"])
    assert "docker.sock" in joined


def test_dockerfile_default_entrypoint_stays_isolated_script() -> None:
    """Static create-image contract: ENTRYPOINT is python -I tool_executor.py."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["python", "-I", "/opt/xinao-tool-executor/tool_executor.py"' in text
    assert "PYTHONPATH=/opt/xinao-tool-executor" in text
    # Isolation preserved: still python -I (not relying on PYTHONPATH at runtime).
    assert 'python", "-I"' in text or '"python", "-I"' in text


def test_candidate_docker_default_entrypoint_smoke() -> None:
    """Linux container smoke: unique image + named container; network none; no sock.

    Evidence-based skip when docker missing or engine OSType is not linux
    (Windows CI daemon windows/amd64 cannot run the Linux tool image). Ubuntu /
    Linux engines must still execute this path — no unconditional skip.
    """
    engine_evidence = _require_linux_container_engine()
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

        # Empty workdir: must not rely on cwd for imports (absolute script path).
        smoke = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                f"{WAVE54_SMOKE_NAME}-help",
                "--network",
                "none",
                "--workdir",
                "/tmp",
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

        # Default image ENTRYPOINT shape from Config.Entrypoint.
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

        # Named container (no --rm) so we can inspect NetworkMode, then clean up.
        # Real self-check: no --self-check-fs-root → probes absolute docker.sock.
        lab_probe = subprocess.run(
            [
                "docker",
                "run",
                "--name",
                WAVE54_SMOKE_NAME,
                "--network",
                "none",
                "--user",
                "65532:65532",
                "--workdir",
                "/tmp",
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
        try:
            net = subprocess.run(
                [
                    "docker",
                    "inspect",
                    WAVE54_SMOKE_NAME,
                    "--format",
                    "{{.HostConfig.NetworkMode}}",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert net.returncode == 0, net.stderr
            assert net.stdout.strip().lower() == "none", (
                f"tool container network must be none; got {net.stdout!r} ({engine_evidence})"
            )
            # Socket absence inside the real container (not host runner).
            sock_probe = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    f"{WAVE54_SMOKE_NAME}-sock",
                    "--network",
                    "none",
                    "--entrypoint",
                    "python",
                    WAVE54_TAG,
                    "-c",
                    (
                        "import os,sys;"
                        "paths=['/var/run/docker.sock','/run/docker.sock',"
                        "'/var/run/podman/podman.sock'];"
                        "hits=[p for p in paths if os.path.exists(p) or os.path.islink(p)];"
                        "sys.exit(0 if not hits else 3);"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert sock_probe.returncode == 0, (
                "tool container must not expose docker/podman sockets\n"
                f"stdout={sock_probe.stdout!r}\nstderr={sock_probe.stderr!r}"
            )
            assert lab_probe.returncode == 0, lab_probe.stderr
            report = json.loads(lab_probe.stdout)
            assert report["ok"] is True
            assert report.get("fs_root") in (None, "")
            violations = report.get("violations") or []
            assert not any("docker.sock" in str(v) for v in violations)
            assert not any("podman.sock" in str(v) for v in violations)
            assert image_id  # retained for evidence in assertion path
        finally:
            subprocess.run(
                ["docker", "rm", "-f", WAVE54_SMOKE_NAME],
                check=False,
                capture_output=True,
                timeout=60,
            )
    finally:
        # Do not remove pre-existing images; only this unique wave54 tag.
        subprocess.run(
            ["docker", "rmi", "-f", WAVE54_TAG],
            check=False,
            capture_output=True,
            timeout=60,
        )
        # Belt-and-suspenders: drop help/sock names if left behind.
        for name in (
            WAVE54_SMOKE_NAME,
            f"{WAVE54_SMOKE_NAME}-help",
            f"{WAVE54_SMOKE_NAME}-sock",
        ):
            subprocess.run(
                ["docker", "rm", "-f", name],
                check=False,
                capture_output=True,
                timeout=30,
            )
