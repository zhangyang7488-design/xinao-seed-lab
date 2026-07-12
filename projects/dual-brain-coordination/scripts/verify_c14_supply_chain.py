#!/usr/bin/env python3
"""C14 v3: immutable-generation and module lifecycle evidence.

The verifier mutates only an explicitly supplied sandbox runtime.  The live
generation pointer is sampled before/after and must remain byte-identical.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination")
UV = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\uv\0.11.16\uv.exe")
DB = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3")
AUTHORITY = Path(r"C:\Users\xx363\Desktop\主线\双脑\双脑主线_超级详细施工包.txt")
ACPX_CURRENT = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\acpx\current.json")
DEFAULT_ROLLBACK = "coord-8c21bc4227d36b2c353c7a86"
DEFAULT_ROLLBACK_SCRIPT = REPO / "provisioning" / "Test-XinaoCoordGenerationRollback.ps1"
DEFAULT_SANDBOX = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs"
    r"\continuous-relay-20260712-019f5302\c14-sandbox-20260712T0908\runtime"
)
DEFAULT_RUN_ROOT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs"
    r"\continuous-relay-20260712-019f5302"
)
DEFAULT_OUT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712"
    r"\saturation\G10_generation_pin\pin_audit_current.json"
)
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
SCHEMA_VERSION = "xinao.c14.supply_chain.v3"
REQUIRED_MODULE_IDS = (
    "coordination_kernel",
    "amq",
    "temporal",
    "m_bg",
    "m_keep",
    "headless_worker_acpx",
    "readback_cli_mcp",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _meta(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _pointer_snapshot(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    stat = path.stat()
    pointer = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(pointer, dict):
        raise TypeError(f"expected pointer JSON object: {path}")
    return {
        "path": _normalized_path(path),
        "bytes": raw,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mtime_ns": stat.st_mtime_ns,
        "target": {
            "generation_id": pointer.get("generation_id"),
            "source_fingerprint": pointer.get("source_fingerprint"),
            "generation_path": pointer.get("generation_path"),
        },
    }


def _public_pointer_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "bytes"}


def _compare_pointer_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, bool]:
    checks = {
        "bytes_unchanged": before.get("bytes") == after.get("bytes"),
        "hash_unchanged": before.get("sha256") == after.get("sha256"),
        "mtime_unchanged": before.get("mtime_ns") == after.get("mtime_ns"),
        "target_unchanged": before.get("target") == after.get("target"),
        "path_unchanged": before.get("path") == after.get("path"),
    }
    return {**checks, "ok": all(checks.values())}


def _interface_invoked(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    command = value.get("command")
    executable = value.get("executable")
    return bool(
        isinstance(command, list)
        and command
        and all(isinstance(item, str) and item for item in command)
        and value.get("exit_code") == 0
        and isinstance(executable, dict)
        and executable.get("exists") is True
    )


def _validate_rollback_dry_run(
    result: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    current_generation: str,
    rollback_generation: str,
    rollback_root: Path,
    rollback_manifest_path: Path,
    rollback_source_fingerprint: str,
) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else {}
    replacement = payload.get("replacement") if isinstance(payload.get("replacement"), dict) else {}
    pointer_checks = _compare_pointer_snapshots(before, after)
    command = result.get("command") if isinstance(result.get("command"), list) else []
    checks = {
        "interface_invoked": _interface_invoked(result),
        "reported_ok": payload.get("ok") is True,
        "dry_run_not_applied": payload.get("applied") is False
        and "-Apply" not in command
        and "-AllowLivePointer" not in command,
        "live_pointer_exact": _normalized_path(str(payload.get("pointer_path") or ""))
        == str(before.get("path") or ""),
        "current_generation_exact": payload.get("expected_current") == current_generation,
        "rollback_generation_distinct": rollback_generation != current_generation,
        "rollback_generation_exact": payload.get("restore") == rollback_generation
        and replacement.get("generation_id") == rollback_generation,
        "rollback_root_exact": _normalized_path(str(replacement.get("generation_path") or ""))
        == _normalized_path(rollback_root),
        "rollback_manifest_exact": _normalized_path(str(payload.get("restore_manifest") or ""))
        == _normalized_path(rollback_manifest_path),
        "rollback_fingerprint_exact": str(replacement.get("source_fingerprint") or "").upper()
        == rollback_source_fingerprint.upper(),
        "pointer_bytes_unchanged": pointer_checks["bytes_unchanged"],
        "pointer_hash_unchanged": pointer_checks["hash_unchanged"],
        "pointer_mtime_unchanged": pointer_checks["mtime_unchanged"],
        "pointer_target_unchanged": pointer_checks["target_unchanged"],
        "pointer_path_unchanged": pointer_checks["path_unchanged"],
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "pointer_before": _public_pointer_snapshot(before),
        "pointer_after": _public_pointer_snapshot(after),
        "pointer_comparison": pointer_checks,
    }


def _write_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class Runner:
    def __init__(self, root: Path) -> None:
        self.root = root / "commands"
        self.root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        label: str,
        command: list[str],
        *,
        cwd: Path = REPO,
        env: dict[str, str] | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        child_env = os.environ.copy()
        child_env.update(env or {})
        proc = subprocess.run(
            command,
            cwd=cwd,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=WINDOWLESS,
        )
        stdout_path = self.root / f"{label}.stdout.txt"
        stderr_path = self.root / f"{label}.stderr.txt"
        stdout_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")
        executable = Path(command[0])
        if not executable.is_file():
            resolved = shutil.which(command[0])
            executable = Path(resolved) if resolved else executable
        payload: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        return {
            "command": command,
            "cwd": str(cwd),
            "executable": _meta(executable),
            "exit_code": proc.returncode,
            "json": payload,
            "stdout": _meta(stdout_path),
            "stderr": _meta(stderr_path),
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }


def _source_inputs() -> dict[str, Any]:
    relatives = {
        "pyproject.toml",
        "README.md",
        "uv.lock",
        "provisioning/build-constraints.txt",
        "provisioning/toolchain-lock.json",
        "provisioning/Invoke-XinaoCoordManaged.ps1",
        "provisioning/Invoke-XinaoCoordReconcile.ps1",
        "configs/modules/amq.toml",
        "configs/modules/m_keep.toml",
        "configs/modules/temporal.toml",
    }
    for path in (REPO / "src").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            relatives.add(path.relative_to(REPO).as_posix())
    rows: list[dict[str, Any]] = []
    material: list[str] = []
    # PowerShell's Sort-Object (used by the managed provisioner) is
    # case-insensitive by default.  Match that ordering exactly so the
    # independent verifier recomputes the same source fingerprint.
    for relative in sorted(relatives, key=str.casefold):
        path = REPO / relative
        digest = _sha256(path).upper()
        rows.append(
            {
                "relative_path": relative.replace("\\", "/"),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
        material.append(f"{relative.replace('\\', '/')}|{path.stat().st_size}|{digest}")
    fingerprint = hashlib.sha256("\n".join(material).encode()).hexdigest().upper()
    return {"fingerprint": fingerprint, "files": rows}


def _generation(root: Path, generation_id: str | None = None) -> dict[str, Any]:
    pointer_path = root / "current.json"
    pointer = _load(pointer_path)
    selected = generation_id or str(pointer["generation_id"])
    generation_root = root / "generations" / selected
    manifest_path = generation_root / "generation.json"
    manifest = _load(manifest_path)
    return {
        "pointer_path": pointer_path,
        "pointer": pointer,
        "root": generation_root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "python": generation_root / "venv" / "Scripts" / "python.exe",
        "cli": generation_root / "venv" / "Scripts" / "xinao-coord.exe",
        "mcp": generation_root / "venv" / "Scripts" / "xinao-coord-mcp.exe",
    }


def _doctor(runner: Runner, label: str, generation: dict[str, Any], db: Path) -> dict[str, Any]:
    manifest = generation["manifest"]
    return runner.run(
        label,
        [str(generation["cli"]), "--db", str(db), "doctor"],
        env={
            "XINAO_COORD_GENERATION_ID": str(manifest["generation_id"]),
            "XINAO_COORD_SOURCE_FINGERPRINT": str(manifest["source_fingerprint"]),
        },
    )


def _module(
    module_id: str,
    *,
    version_pin: object,
    config: object,
    health: object,
    deactivate: object,
    rollback: object,
    checks: dict[str, bool],
) -> dict[str, Any]:
    invoked = all(_interface_invoked(value) for value in (health, deactivate, rollback))
    bound_checks = {**checks, "interfaces_invoked": invoked}
    return {
        "module_id": module_id,
        "version_pin": version_pin,
        "effective_config": config,
        "health": health,
        "deactivate_or_uninstall": deactivate,
        "rollback": rollback,
        "checks": bound_checks,
        "ok": bool(bound_checks) and all(bound_checks.values()),
    }


def build_evidence(
    *,
    rollback_generation: str,
    rollback_script: Path,
    sandbox_runtime: Path,
    run_dir: Path,
) -> dict[str, Any]:
    runner = Runner(run_dir)
    live_pointer_initial = _pointer_snapshot(RUNTIME / "current.json")
    current = _generation(RUNTIME)
    rollback = _generation(RUNTIME, rollback_generation)
    sandbox = _generation(sandbox_runtime)
    current_manifest = current["manifest"]
    sandbox_manifest = sandbox["manifest"]
    source_inputs = _source_inputs()
    toolchain = _load(REPO / "provisioning" / "toolchain-lock.json")
    lock_inputs = toolchain.get("inputs") if isinstance(toolchain.get("inputs"), dict) else {}
    lock_inputs_match = all(
        (REPO / relative).is_file() and _sha256(REPO / relative).upper() == str(expected).upper()
        for relative, expected in lock_inputs.items()
    )
    authority_text = AUTHORITY.read_text(encoding="utf-8-sig") if AUTHORITY.is_file() else ""

    current_doctor = _doctor(runner, "current_doctor", current, DB)
    rollback_doctor = _doctor(runner, "rollback_doctor", rollback, run_dir / "rollback.sqlite3")
    uv_lock = runner.run("uv_lock_check", [str(UV), "lock", "--check"], timeout=120)
    uv_list = runner.run(
        "uv_pip_list",
        [str(UV), "pip", "list", "--python", str(current["python"]), "--format", "json"],
    )
    uv_check = runner.run("uv_pip_check", [str(UV), "pip", "check", "--python", str(current["python"])])
    sbom = runner.run(
        "uv_cyclonedx",
        [str(UV), "export", "--frozen", "--format", "cyclonedx1.5"],
        timeout=180,
    )
    installed: dict[str, str] = {}
    with contextlib.suppress(json.JSONDecodeError):
        parsed = json.loads((runner.root / "uv_pip_list.stdout.txt").read_text(encoding="utf-8"))
        if isinstance(parsed, list):
            installed = {
                str(item.get("name")): str(item.get("version")) for item in parsed if isinstance(item, dict)
            }
    expected_versions = {
        "xinao-dual-brain-coordination": str(current_manifest["versions"]["project"]),
        "mcp": str(current_manifest["versions"]["mcp"]),
        "a2a-sdk": str(current_manifest["versions"]["a2a-sdk"]),
        "apsw": str(current_manifest["versions"]["apsw"]),
        "opentelemetry-api": str(current_manifest["versions"]["opentelemetry-api"]),
        "temporalio": str(current_manifest["versions"]["temporalio"]),
    }
    versions_match = all(installed.get(name) == value for name, value in expected_versions.items())

    policy_code = (
        "from xinao_coordination.amq.transport import amq_policy;"
        "from xinao_coordination.temporal.policy import temporal_policy;"
        "from xinao_coordination.m_keep import m_keep_policy;import json;"
        "print(json.dumps({'amq':amq_policy(),'temporal':temporal_policy(),'mkeep':m_keep_policy()}))"
    )
    policies = runner.run("effective_policies", [str(current["python"]), "-c", policy_code])
    policy_data = policies["json"]
    source_config_hashes = {
        name: _sha256(REPO / "configs" / "modules" / f"{name}.toml") for name in ("amq", "temporal", "m_keep")
    }
    policy_keys = {"amq": "amq", "temporal": "temporal", "m_keep": "mkeep"}
    configs_effective = all(
        str(
            ((policy_data.get(policy_keys[name]) or {}).get("config_provenance") or {}).get("sha256") or ""
        ).lower()
        == digest.lower()
        for name, digest in source_config_hashes.items()
    )

    amq_policy = policy_data.get("amq") if isinstance(policy_data.get("amq"), dict) else {}
    amq_bin = Path(str(amq_policy.get("bin") or ""))
    amq_health = runner.run("amq_version", [str(amq_bin), "--version"])
    amq_negative_code = (
        "from pathlib import Path;"
        "from xinao_coordination.amq.transport import AmqTransport,AmqTransportError;"
        "import json,sys;"
        "\ntry: AmqTransport(bin_path=Path(sys.argv[1]),root=Path(sys.argv[2])).version()"
        "\nexcept AmqTransportError: print(json.dumps({'missing_binary_rejected':True}))"
        "\nelse: raise SystemExit(3)"
    )
    amq_off = runner.run(
        "amq_deactivate_missing_binary",
        [
            str(current["python"]),
            "-c",
            amq_negative_code,
            str(run_dir / "missing-amq.exe"),
            str(run_dir / "amq-off"),
        ],
    )
    amq_restore = runner.run("amq_restore_version", [str(amq_bin), "--version"])

    disabled_env = {"XINAO_TEMPORAL_ENABLED": "0", "XINAO_TEMPORAL_MOCK": "1", "XINAO_TEMPORAL_LIVE": "0"}
    mock_env = {"XINAO_TEMPORAL_ENABLED": "1", "XINAO_TEMPORAL_MOCK": "1", "XINAO_TEMPORAL_LIVE": "0"}
    temporal_off = runner.run(
        "temporal_disabled",
        [str(current["cli"]), "--db", str(run_dir / "temporal-off.sqlite3"), "temporal-status"],
        env=disabled_env,
    )
    temporal_on = runner.run(
        "temporal_mock_restore",
        [str(current["cli"]), "--db", str(run_dir / "temporal-on.sqlite3"), "temporal-status"],
        env=mock_env,
    )
    mbg_on = runner.run(
        "mbg_enabled",
        [str(current["cli"]), "--db", str(run_dir / "mbg.sqlite3"), "mbg-status"],
        env={"XINAO_MBG_ENABLED": "1"},
    )
    mbg_off = runner.run(
        "mbg_disabled",
        [str(current["cli"]), "--db", str(run_dir / "mbg.sqlite3"), "mbg-status"],
        env={"XINAO_MBG_ENABLED": "0"},
    )
    mkeep_status = runner.run(
        "mkeep_status",
        [str(current["cli"]), "--db", str(run_dir / "mkeep.sqlite3"), "mkeep-status"],
    )
    binding = json.dumps(
        {
            "session_id": "c14-disposable",
            "generation": 1,
            "pid": os.getpid(),
            "process_created_at": "bounded-canary",
            "executable_path": str(current["python"]),
            "command_line_marker": "c14-disposable",
            "logon_session": "current",
            "parent_pid": os.getppid(),
        },
        separators=(",", ":"),
    )
    mkeep_observe = runner.run(
        "mkeep_observe",
        [
            str(current["cli"]),
            "--db",
            str(run_dir / "mkeep.sqlite3"),
            "mkeep-observe",
            "--snapshot",
            '{"managed_session":true,"ready":true}',
            "--binding",
            binding,
        ],
    )
    mkeep_restore = runner.run(
        "mkeep_observe_after_disabled_status",
        [
            str(current["cli"]),
            "--db",
            str(run_dir / "mkeep.sqlite3"),
            "mkeep-observe",
            "--snapshot",
            '{"managed_session":true,"ready":true}',
            "--binding",
            binding,
        ],
    )

    acpx_status = runner.run(
        "acpx_status",
        [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(REPO / "provisioning" / "Invoke-XinaoAcpxManaged.ps1"),
            "-Target",
            "status",
        ],
        timeout=180,
    )
    pester_command = (
        "$r=Invoke-Pester -Path '"
        + str(REPO / "tests" / "AcpxProvisioning.Tests.ps1").replace("'", "''")
        + "' -CI -PassThru -Output None;"
        "$r|Select-Object Result,TotalCount,PassedCount,FailedCount,SkippedCount|ConvertTo-Json -Compress;"
        "if($r.FailedCount -gt 0){exit 1}"
    )
    acpx_pester = runner.run(
        "acpx_pester",
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", pester_command],
        timeout=300,
    )
    acpx_status_after = runner.run(
        "acpx_status_after_lifecycle_tests",
        [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(REPO / "provisioning" / "Invoke-XinaoAcpxManaged.ps1"),
            "-Target",
            "status",
        ],
        timeout=180,
    )

    sandbox_fingerprint_matches = sandbox_manifest.get("source_fingerprint") == current_manifest.get(
        "source_fingerprint"
    )
    wheel_cache = (
        Path(str(toolchain["wheel_cache_root"])) / str(sandbox_manifest["source_fingerprint"]).lower()
    )
    wheel_manifest = _load(wheel_cache / "wheel.json")
    wheel = wheel_cache / str(wheel_manifest["filename"])
    package_before = runner.run(
        "sandbox_package_before",
        [
            str(sandbox["python"]),
            "-c",
            "import importlib.metadata as m,json;"
            "print(json.dumps({'version':m.version('xinao-dual-brain-coordination')}))",
        ],
    )
    uninstall = runner.run(
        "sandbox_uninstall",
        [
            str(UV),
            "pip",
            "uninstall",
            "--python",
            str(sandbox["python"]),
            "xinao-dual-brain-coordination",
        ],
    )
    absent = runner.run(
        "sandbox_absent",
        [
            str(sandbox["python"]),
            "-c",
            "import importlib.util,json;"
            "print(json.dumps({'module_present':"
            "importlib.util.find_spec('xinao_coordination') is not None}))",
        ],
    )
    cli_absent = not Path(sandbox["cli"]).exists()
    reinstall = runner.run(
        "sandbox_reinstall",
        [
            str(UV),
            "pip",
            "install",
            "--python",
            str(sandbox["python"]),
            "--no-deps",
            "--no-index",
            "--reinstall",
            "--link-mode",
            "copy",
            str(wheel),
        ],
    )
    sandbox_rebuild = runner.run(
        "sandbox_managed_rebuild_restore",
        [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO / "provisioning" / "Invoke-XinaoCoordManaged.ps1"),
            "-RuntimeRoot",
            str(sandbox_runtime),
            "-Target",
            "ensure",
            "-RebuildGeneration",
            "-Offline",
        ],
        timeout=600,
    )
    sandbox_restored = _generation(sandbox_runtime)
    sandbox_doctor = _doctor(
        runner,
        "sandbox_doctor_after_restore",
        sandbox_restored,
        run_dir / "sandbox.sqlite3",
    )
    sandbox_status = runner.run(
        "sandbox_generation_status",
        [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(REPO / "provisioning" / "Invoke-XinaoCoordManaged.ps1"),
            "-RuntimeRoot",
            str(sandbox_runtime),
            "-Target",
            "status",
            "-Offline",
        ],
        timeout=180,
    )
    package_lifecycle_ok = bool(
        sandbox_fingerprint_matches
        and wheel.is_file()
        and _sha256(wheel).upper() == str(sandbox_manifest["wheel"]["sha256"]).upper()
        and package_before["exit_code"] == 0
        and uninstall["exit_code"] == 0
        and absent["exit_code"] == 0
        and absent["json"].get("module_present") is False
        and cli_absent
        and reinstall["exit_code"] == 0
        and sandbox_rebuild["exit_code"] == 0
        and sandbox_restored["manifest"].get("source_fingerprint")
        == current_manifest.get("source_fingerprint")
        and sandbox_restored["pointer"].get("generation_id") == current_manifest.get("generation_id")
        and sandbox_doctor["exit_code"] == 0
        and sandbox_doctor["json"].get("ok") is True
        and sandbox_status["json"].get("status") == "verified"
    )

    # Exercise the real rollback entrypoint in dry-run mode against the live pointer.
    # Capture it immediately before and after; no -Apply and no canary pointer rewrite.
    rollback_pointer_before = _pointer_snapshot(RUNTIME / "current.json")
    rollback_base = [
        "pwsh.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(rollback_script),
        "-PointerPath",
        str(RUNTIME / "current.json"),
        "-RuntimeRoot",
        str(RUNTIME),
        "-ExpectedCurrentGeneration",
        str(current_manifest["generation_id"]),
        "-RestoreGeneration",
        rollback_generation,
    ]
    rollback_dry = runner.run("rollback_dry_run", rollback_base)
    rollback_pointer_after = _pointer_snapshot(RUNTIME / "current.json")
    rollback_validation = _validate_rollback_dry_run(
        rollback_dry,
        before=rollback_pointer_before,
        after=rollback_pointer_after,
        current_generation=str(current_manifest["generation_id"]),
        rollback_generation=rollback_generation,
        rollback_root=Path(rollback["root"]),
        rollback_manifest_path=Path(rollback["manifest_path"]),
        rollback_source_fingerprint=str(rollback["manifest"]["source_fingerprint"]),
    )
    rollback_dry_run_ok = bool(
        rollback_validation["ok"]
        and rollback_doctor["json"].get("ok") is True
        and rollback_doctor["json"].get("generation_id") == rollback_generation
    )

    project_version = str(current_manifest["versions"]["project"])
    restored = package_lifecycle_ok
    modules = [
        _module(
            "coordination_kernel",
            version_pin={"project": project_version, "wheel": _meta(wheel)},
            config={"toolchain": _meta(REPO / "provisioning" / "toolchain-lock.json")},
            health=current_doctor,
            deactivate=uninstall,
            rollback=sandbox_doctor,
            checks={
                "pinned": versions_match,
                "configured": lock_inputs_match,
                "health_ok": current_doctor["json"].get("ok") is True,
                "uninstall_ok": absent["json"].get("module_present") is False and cli_absent,
                "rollback_ok": restored,
            },
        ),
        _module(
            "amq",
            version_pin={
                "version": amq_policy.get("version_pinned"),
                "binary": _meta(amq_bin),
                "license": amq_policy.get("license"),
            },
            config=amq_policy.get("config_provenance"),
            health=amq_health,
            deactivate=amq_off,
            rollback=amq_restore,
            checks={
                "pinned": amq_bin.is_file()
                and _sha256(amq_bin).upper() == str(amq_policy.get("sha256") or "").upper(),
                "configured": configs_effective,
                "health_ok": amq_health["exit_code"] == 0
                and str(amq_policy.get("version_pinned") or "") in amq_health["stdout_tail"],
                "deactivate_ok": amq_off["json"].get("missing_binary_rejected") is True,
                "rollback_ok": amq_restore["exit_code"] == 0,
            },
        ),
        _module(
            "temporal",
            version_pin={"temporalio": current_manifest["versions"]["temporalio"]},
            config=(policy_data.get("temporal") or {}).get("config_provenance"),
            health=temporal_on,
            deactivate=temporal_off,
            rollback=temporal_on,
            checks={
                "pinned": installed.get("temporalio") == str(current_manifest["versions"]["temporalio"]),
                "configured": configs_effective,
                "health_ok": temporal_on["json"].get("mode") == "mock",
                "deactivate_ok": temporal_off["json"].get("mode") == "disabled",
                "rollback_ok": temporal_on["json"].get("mode") == "mock",
            },
        ),
        _module(
            "m_bg",
            version_pin={
                "project": project_version,
                "source": _meta(REPO / "src" / "xinao_coordination" / "m_bg.py"),
            },
            config=mbg_on["json"].get("policy"),
            health=mbg_on,
            deactivate=mbg_off,
            rollback=mbg_on,
            checks={
                "pinned": source_inputs["fingerprint"] == current_manifest["source_fingerprint"],
                "configured": mbg_on["json"].get("auto_dispatch") is False,
                "health_ok": (mbg_on["json"].get("policy") or {}).get("enabled") is True,
                "deactivate_ok": (mbg_off["json"].get("policy") or {}).get("enabled") is False,
                "rollback_ok": (mbg_on["json"].get("policy") or {}).get("enabled") is True,
            },
        ),
        _module(
            "m_keep",
            version_pin={
                "project": project_version,
                "source": _meta(REPO / "src" / "xinao_coordination" / "m_keep.py"),
            },
            config=(policy_data.get("mkeep") or {}).get("config_provenance"),
            health=mkeep_observe,
            deactivate=mkeep_status,
            rollback=mkeep_restore,
            checks={
                "pinned": source_inputs["fingerprint"] == current_manifest["source_fingerprint"],
                "configured": configs_effective,
                "health_ok": mkeep_observe["json"].get("observation_valid") is True,
                "deactivate_ok": ((mkeep_status["json"].get("policy") or {}).get("enabled") is False),
                "rollback_ok": mkeep_restore["json"].get("observation_valid") is True
                and ((mkeep_restore["json"].get("policy") or {}).get("enabled") is False),
            },
        ),
        _module(
            "headless_worker_acpx",
            version_pin={
                "lock": _meta(REPO / "provisioning" / "acpx-toolchain-lock.json"),
                "current": _meta(ACPX_CURRENT),
            },
            config=_meta(REPO / "provisioning" / "acpx-grok-config.json"),
            health=acpx_status,
            deactivate=acpx_pester,
            rollback=acpx_status_after,
            checks={
                "pinned": acpx_status["json"].get("status") == "verified",
                "configured": (REPO / "provisioning" / "acpx-grok-config.json").is_file(),
                "health_ok": acpx_status["exit_code"] == 0,
                "deactivate_ok": acpx_pester["exit_code"] == 0
                and int(acpx_pester["json"].get("FailedCount") or 0) == 0,
                "rollback_ok": acpx_status_after["exit_code"] == 0
                and acpx_status_after["json"].get("status") == "verified"
                and int(acpx_pester["json"].get("PassedCount") or 0) >= 7,
            },
        ),
        _module(
            "readback_cli_mcp",
            version_pin={"project": project_version, "mcp": current_manifest["versions"]["mcp"]},
            config={"cli": _meta(current["cli"]), "mcp": _meta(current["mcp"])},
            health=current_doctor,
            deactivate=uninstall,
            rollback=sandbox_doctor,
            checks={
                "pinned": versions_match,
                "configured": Path(current["cli"]).is_file() and Path(current["mcp"]).is_file(),
                "health_ok": current_doctor["json"].get("ok") is True,
                "uninstall_ok": cli_absent,
                "rollback_ok": restored,
            },
        ),
    ]

    live_pointer_final = _pointer_snapshot(RUNTIME / "current.json")
    live_pointer_comparison = _compare_pointer_snapshots(live_pointer_initial, live_pointer_final)
    module_ids = tuple(str(item.get("module_id") or "") for item in modules)
    checks = {
        "authority_c14_bound": "C14 所有模块有 pinned 版本、配置、健康检查、卸载和独立回滚" in authority_text,
        "source_fingerprint_recomputed": source_inputs["fingerprint"]
        == current_manifest.get("source_fingerprint"),
        "current_pointer_matches_manifest": current["pointer"].get("generation_id")
        == current_manifest.get("generation_id"),
        "current_fresh_doctor_bound": current_doctor["json"].get("ok") is True
        and current_doctor["json"].get("generation_id") == current_manifest.get("generation_id"),
        "toolchain_inputs_hashed": bool(lock_inputs) and lock_inputs_match,
        "uv_lock_current": uv_lock["exit_code"] == 0,
        "installed_versions_match_manifest": versions_match and uv_check["exit_code"] == 0,
        "cyclonedx_exported": sbom["exit_code"] == 0 and int(sbom["stdout"]["size_bytes"] or 0) > 0,
        "effective_configs_match_source": configs_effective,
        "sandbox_package_uninstall_restore": package_lifecycle_ok,
        "rollback_dry_run_exact_and_non_mutating": rollback_dry_run_ok,
        "rollback_apply_not_attempted": rollback_validation["checks"]["dry_run_not_applied"],
        "current_pointer_bytes_unchanged_during_dry_run": rollback_validation["checks"][
            "pointer_bytes_unchanged"
        ],
        "current_pointer_hash_unchanged_during_dry_run": rollback_validation["checks"][
            "pointer_hash_unchanged"
        ],
        "current_pointer_mtime_unchanged_during_dry_run": rollback_validation["checks"][
            "pointer_mtime_unchanged"
        ],
        "current_pointer_target_unchanged_during_dry_run": rollback_validation["checks"][
            "pointer_target_unchanged"
        ],
        "rollback_target_exact": rollback_validation["checks"]["rollback_generation_exact"]
        and rollback_validation["checks"]["rollback_root_exact"]
        and rollback_validation["checks"]["rollback_manifest_exact"]
        and rollback_validation["checks"]["rollback_fingerprint_exact"],
        "module_ids_exact": module_ids == REQUIRED_MODULE_IDS,
        "module_interfaces_invoked": all(
            item.get("checks", {}).get("interfaces_invoked") is True for item in modules
        ),
        "all_modules_lifecycle_verified": all(item["ok"] for item in modules),
        "live_pointer_unchanged": live_pointer_comparison["ok"],
    }
    bindings = {
        name: _meta(path)
        for name, path in {
            "authority": AUTHORITY,
            "verifier": Path(__file__).resolve(),
            "c14_gate": REPO / "scripts" / "verify_c01_c15.py",
            "coord_managed": REPO / "provisioning" / "Invoke-XinaoCoordManaged.ps1",
            "acpx_managed": REPO / "provisioning" / "Invoke-XinaoAcpxManaged.ps1",
            "rollback_script": rollback_script,
            "toolchain_lock": REPO / "provisioning" / "toolchain-lock.json",
            "acpx_toolchain_lock": REPO / "provisioning" / "acpx-toolchain-lock.json",
            "pyproject": REPO / "pyproject.toml",
            "uv_lock": REPO / "uv.lock",
            "amq_source": REPO / "src" / "xinao_coordination" / "amq" / "transport.py",
            "mbg_source": REPO / "src" / "xinao_coordination" / "m_bg.py",
            "mkeep_source": REPO / "src" / "xinao_coordination" / "m_keep.py",
            "temporal_policy_source": REPO / "src" / "xinao_coordination" / "temporal" / "policy.py",
            "service_source": REPO / "src" / "xinao_coordination" / "service.py",
            "cli_source": REPO / "src" / "xinao_coordination" / "cli.py",
            "amq_config": REPO / "configs" / "modules" / "amq.toml",
            "mkeep_config": REPO / "configs" / "modules" / "m_keep.toml",
            "temporal_config": REPO / "configs" / "modules" / "temporal.toml",
            "current_pointer": RUNTIME / "current.json",
            "current_manifest": current["manifest_path"],
            "rollback_manifest": rollback["manifest_path"],
            "current_python": current["python"],
            "current_cli": current["cli"],
            "current_mcp": current["mcp"],
            "uv": UV,
        }.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": all(checks.values()),
        "checks": checks,
        "bindings": bindings,
        "source_inputs": source_inputs,
        "current": current["pointer"],
        "current_manifest": current_manifest,
        "rollback_generation_id": rollback_generation,
        "sandbox_runtime": str(sandbox_runtime),
        "dependency_inventory": {
            "expected": expected_versions,
            "installed": installed,
            "versions_match": versions_match,
            "uv_pip_list": uv_list,
            "uv_lock_check": uv_lock,
            "uv_pip_check": uv_check,
            "cyclonedx": sbom,
        },
        "package_lifecycle": {
            "ok": package_lifecycle_ok,
            "wheel": _meta(wheel),
            "before": package_before,
            "uninstall": uninstall,
            "absent": absent,
            "cli_absent": cli_absent,
            "reinstall": reinstall,
            "managed_rebuild_restore": sandbox_rebuild,
            "doctor_after": sandbox_doctor,
            "generation_status_after": sandbox_status,
        },
        "rollback_lifecycle": {
            "ok": rollback_dry_run_ok,
            "apply_attempted": False,
            "dry_run": rollback_dry,
            "validation": rollback_validation,
            "target": {
                "generation_id": rollback_generation,
                "generation_path": str(rollback["root"]),
                "manifest_path": str(rollback["manifest_path"]),
                "source_fingerprint": rollback["manifest"].get("source_fingerprint"),
            },
            "rollback_doctor": rollback_doctor,
        },
        "modules": modules,
        "live_pointer": {
            "initial": _public_pointer_snapshot(live_pointer_initial),
            "final": _public_pointer_snapshot(live_pointer_final),
            "comparison": live_pointer_comparison,
        },
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback-generation", default=DEFAULT_ROLLBACK)
    parser.add_argument("--rollback-script", type=Path, default=DEFAULT_ROLLBACK_SCRIPT)
    parser.add_argument("--sandbox-runtime", type=Path, default=DEFAULT_SANDBOX)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    run_name = f"c14-audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = args.run_root / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = build_evidence(
        rollback_generation=args.rollback_generation,
        rollback_script=args.rollback_script.resolve(),
        sandbox_runtime=args.sandbox_runtime.resolve(),
        run_dir=run_dir,
    )
    _write_atomic(args.output, payload)
    index = {
        "schema_version": "xinao.c14.supply_chain.index.v1",
        "evidence": _meta(args.output),
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    index_path = args.output.with_name(f"{args.output.stem}.index.json")
    _write_atomic(index_path, index)
    print(
        json.dumps(
            {"ok": payload["ok"], "output": str(args.output), "index": str(index_path)},
            ensure_ascii=False,
        )
    )
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
