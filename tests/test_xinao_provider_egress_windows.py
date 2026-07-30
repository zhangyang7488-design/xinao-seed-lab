"""Offline static + safe subprocess tests for Windows Owner egress carriers.

Never mutates Docker. Never requires WSL. Never claims completion.
Cross-contract checks import the checked-in sealer and runtime validators.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EGRESS_ROOT = ROOT / "docker" / "xinao-researcher-egress"
SCRIPTS = EGRESS_ROOT / "scripts"
SKILL_ROOT = ROOT / "skills" / "xinao"
PWSH = os.environ.get("XINAO_PWSH") or "pwsh"
RUNTIME_LOCK = SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json"
_RUNTIME_LOCK_OBJ = json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
PINNED_DONOR_IMAGE_ID = _RUNTIME_LOCK_OBJ["grok_donor_image_id"]
PINNED_MODEL = _RUNTIME_LOCK_OBJ.get("model") or "grok-4.5"
# Synthetic active researcher image (distinct from extraction donor).
ACTIVE_RESEARCHER_IMAGE_ID = "sha256:" + ("b" * 64)
SYNTHETIC_DONOR_BINARY_SHA = "c" * 64


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sealer():
    return _load(SCRIPTS / "owner_seal_live_egress.py", "xinao_owner_seal_live_egress_windows_test")


def _runtime():
    return _load(SKILL_ROOT / "scripts" / "xinao_runtime.py", "xinao_runtime_windows_egress_test")

OWNER_SCRIPTS = [
    "XinaoEgressOwner.Common.ps1",
    "Resolve-ProxyImagePin.ps1",
    "Owner-ProvisionEgress.ps1",
    "Owner-LiveNegativeSuite.ps1",
    "Owner-EngineeringCanary.ps1",
    "Owner-CleanupEgress.ps1",
    "Owner-FreshProcessReadback.ps1",
    "Owner-DiscoverProviderEndpoints.ps1",
]


def _pwsh_available() -> bool:
    try:
        proc = subprocess.run(
            [PWSH, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.returncode == 0 and proc.stdout.strip().isdigit() and int(proc.stdout.strip()) >= 7
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


requires_pwsh = pytest.mark.skipif(not _pwsh_available(), reason="PowerShell 7 (pwsh) required")


def _run_pwsh(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Ensure scripts cannot pick live D-state accidentally in tests.
    full_env.setdefault("XINAO_EGRESS_STATE_ROOT", str(ROOT / ".pytest_egress_state_should_not_use"))
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=full_env,
        cwd=str(ROOT),
    )


def _run_pwsh_command(command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PWSH, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=str(ROOT),
    )


def _file_sha256_hex(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_synthetic_v2_researcher_state(
    state_root: Path,
    *,
    image_id: str = ACTIVE_RESEARCHER_IMAGE_ID,
    donor_image_id: str = PINNED_DONOR_IMAGE_ID,
    donor_binary_sha: str = SYNTHETIC_DONOR_BINARY_SHA,
    requested_model: str = PINNED_MODEL,
    legacy_pointer: bool = False,
    release_schema: str = "xinao.researcher_release.v2",
    pointer_schema: str = "xinao.researcher_current_pointer.v2",
    corrupt_manifest_hash: bool = False,
) -> dict:
    """Write minimal pointer+release for offline canary admission tests."""
    state_root.mkdir(parents=True, exist_ok=True)
    release_id = "researcher-1.1.0-synth000000000001"
    release_dir = state_root / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": donor_image_id,
        "io.xinao.researcher.grok-donor-binary.sha256": donor_binary_sha,
        "io.xinao.researcher.requested-model": requested_model,
    }
    manifest = {
        "schema_version": release_schema,
        "release_id": release_id,
        "package_version": "1.1.0",
        "capability_id": "researcher-container",
        "capability_version": "1.1.0",
        "charter_version": "1.1.0",
        "runtime_version": "1.1.0",
        "release_identity_sha256": "a" * 64,
        "source_identity": {
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "source_dirty": False,
            "grok_donor_image_id": donor_image_id,
            "grok_donor_binary_sha256": donor_binary_sha,
        },
        "skill_bundle_path": str(release_dir / "skill-bundle"),
        "skill_bundle_manifest_path": str(release_dir / "skill-bundle.manifest.json"),
        "skill_bundle_manifest_sha256": "d" * 64,
        "skill_bundle_tree_sha256": "e" * 64,
        "image_tag_observational": f"xinao-researcher:{release_id}",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_labels": labels,
        "skill_hashes": {},
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    manifest_path = release_dir / "release.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_sha = _file_sha256_hex(manifest_path)
    if legacy_pointer:
        pointer = {
            "schema_version": "xinao.researcher_current_pointer.v1",
            "release_id": release_id,
            "release_manifest_path": str(manifest_path),
            "release_manifest_sha256": manifest_sha,
            "promoted_at": "2026-07-29T00:00:00.000000Z",
            "previous_pointer_sha256": "f" * 64,
            "previous_release_id": None,
            "previous_release_manifest_path": None,
            "previous_release_manifest_sha256": None,
        }
    else:
        pointer = {
            "schema_version": pointer_schema,
            "generation": 1,
            "active": {
                "release_id": release_id,
                "release_manifest_path": str(manifest_path),
                "release_manifest_sha256": (
                    ("0" * 64) if corrupt_manifest_hash else manifest_sha
                ),
                "skill_bundle_manifest_sha256": "d" * 64,
                "skill_bundle_tree_sha256": "e" * 64,
                "capability_version": "1.1.0",
                "package_version": "1.1.0",
                "required_bootstrap_protocol": 2,
                "activation_txn_id": "xra_20260730T000000_0123456789abcdef",
            },
            "previous_verified": None,
            "switched_at": "2026-07-30T00:00:00.000000Z",
        }
    (state_root / "current.json").write_text(
        json.dumps(pointer, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "state_root": state_root,
        "image_id": image_id,
        "donor_image_id": donor_image_id,
        "donor_binary_sha": donor_binary_sha,
        "release_id": release_id,
        "manifest_path": manifest_path,
        "manifest_sha": manifest_sha,
    }


def _parse_last_json(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        raise AssertionError("empty stdout")
    # Scripts may print host messages before JSON; take the last JSON object.
    decoder = json.JSONDecoder()
    last = None
    idx = 0
    while idx < len(text):
        brace = text.find("{", idx)
        if brace < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[brace:])
            last = obj
            idx = brace + end
        except json.JSONDecodeError:
            idx = brace + 1
    if last is None:
        raise AssertionError(f"no JSON object in stdout: {text[:500]}")
    return last


def test_owner_scripts_exist() -> None:
    for name in OWNER_SCRIPTS:
        path = SCRIPTS / name
        assert path.is_file(), name
        raw = path.read_bytes()
        # No bash shebang dependency for Windows carriers.
        assert not raw.startswith(b"#!/usr/bin/env bash")
        text = raw.decode("utf-8-sig")
        lower = text.lower()
        # Carriers must not invoke WSL/Git Bash binaries.
        assert "wsl.exe" not in lower
        assert "bash.exe" not in lower
        assert "/bin/bash" not in lower
        assert "git-bash" not in lower
        # Any prose mention of WSL must be a non-dependency statement.
        for match in re.finditer(r".{0,40}wsl.{0,40}", lower):
            window = match.group(0)
            assert any(
                marker in window
                for marker in (
                    "no wsl",
                    "not use wsl",
                    "without wsl",
                    "wsl_required",
                    "wsl_used",
                    "wsl distribution",
                    "wsl-compatible",
                    "wsl compatible",
                )
            ), f"{name} unexpected WSL context: {window!r}"


def test_runbook_documents_windows_path_without_wsl_prerequisite() -> None:
    runbook = (EGRESS_ROOT / "OWNER_RUNBOOK.md").read_text(encoding="utf-8")
    assert "PowerShell 7" in runbook
    assert "Docker Desktop" in runbook
    assert "No normal user WSL" in runbook or "No WSL" in runbook
    assert "Resolve-ProxyImagePin.ps1" in runbook
    assert "Owner-EngineeringCanary.ps1" in runbook
    assert "Owner-CleanupEgress.ps1" in runbook
    assert "Owner-FreshProcessReadback.ps1" in runbook
    assert "research()" in runbook
    assert "completion_claim_allowed=false" in runbook
    assert "planned" in runbook and "observed" in runbook and "failed" in runbook


@requires_pwsh
def test_powershell_scripts_parse() -> None:
    for name in OWNER_SCRIPTS:
        path = SCRIPTS / name
        # Parser API: non-zero errors fail.
        cmd = textwrap.dedent(
            f"""
            $errors = $null
            $tokens = $null
            [void][System.Management.Automation.Language.Parser]::ParseFile(
                '{path.as_posix()}',
                [ref]$tokens,
                [ref]$errors
            )
            if ($errors -and $errors.Count -gt 0) {{
                $errors | ForEach-Object {{ $_.ToString() }} | Write-Output
                exit 1
            }}
            'PARSE_OK'
            """
        )
        proc = _run_pwsh_command(cmd)
        assert proc.returncode == 0, f"{name}: {proc.stdout}\n{proc.stderr}"
        assert "PARSE_OK" in proc.stdout


@requires_pwsh
def test_common_quoting_and_path_spaces() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $q1 = Format-XinaoQuotedArgument -Value 'C:\\path with spaces\\pin.json'
        if ($q1 -notmatch '"') {{ throw 'expected quotes for spaces' }}
        $q2 = Format-XinaoQuotedArgument -Value 'plain'
        if ($q2 -ne 'plain') {{ throw 'plain should stay unquoted' }}
        $paths = Get-XinaoEgressPathContract -StateRoot 'D:\\XINAO_RESEARCH_RUNTIME\\state\\xinao_skill\\researcher_container\\egress'
        if ($paths.wsl_required -ne $false) {{ throw 'wsl_required must be false' }}
        if ($paths.git_bash_required -ne $false) {{ throw 'git_bash_required must be false' }}
        if ($paths.completion_claim_allowed -ne $false) {{ throw 'completion claim must be false' }}
        if ($paths.posture_path -notmatch 'current_posture') {{ throw 'posture path missing' }}
        'OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout


@requires_pwsh
def test_null_image_pin_readback_fails_closed(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    # Use real package pin (null ids) via -ReadbackOnly.
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Resolve-ProxyImagePin.ps1"),
            "-ReadbackOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-PinPath",
            str(EGRESS_ROOT / "image-pin.v1.json"),
        ]
    )
    assert proc.returncode != 0
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") in {"failed", "FAILED"} or payload.get("pin_resolved") is False
    assert payload.get("provider_egress_runtime_verified") is False
    assert payload.get("completion_claim_allowed") is False
    assert payload.get("wsl_used") is False
    receipt_path = state / "image_pin_readback.v1.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt.get("reason_code") == "IMAGE_PIN_UNRESOLVED" or receipt.get("pin_resolved") is False


@requires_pwsh
def test_resolved_pin_preflight_and_null_pin_provision_fail(tmp_path: Path) -> None:
    state = tmp_path / "state"
    temp = tmp_path / "temp"
    state.mkdir()
    temp.mkdir()
    # Provision with unresolved pin must fail without docker mutation.
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-ProvisionEgress.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-TempRoot",
            str(temp),
            "-PythonPath",
            sys.executable,
        ]
    )
    assert proc.returncode != 0
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") in {"failed", "FAILED"} or "IMAGE_PIN_UNRESOLVED" in json.dumps(payload)
    assert payload.get("docker_mutated") in (False, None) or payload.get("status") == "failed"

    # With a temp resolved pin + empty allowlist, preflight should succeed offline.
    pin_src = json.loads((EGRESS_ROOT / "image-pin.v1.json").read_text(encoding="utf-8"))
    pin_src["image_id"] = "sha256:" + ("a" * 64)
    pin_src["image_digest"] = "ubuntu/squid@sha256:" + ("b" * 64)
    pin_src["floating_tag_as_authority"] = False
    pin_src["authority"] = "immutable_digest_or_image_id_only"
    pkg = tmp_path / "pkg"
    # Minimal package mirror for pin override while reusing render assets via copy of needed files.
    import shutil

    shutil.copytree(EGRESS_ROOT, pkg, ignore=shutil.ignore_patterns("scripts"))
    (pkg / "scripts").mkdir()
    for name in OWNER_SCRIPTS:
        shutil.copy2(SCRIPTS / name, pkg / "scripts" / name)
    (pkg / "image-pin.v1.json").write_text(json.dumps(pin_src, indent=2) + "\n", encoding="utf-8")

    proc2 = _run_pwsh(
        [
            str(pkg / "scripts" / "Owner-ProvisionEgress.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(pkg),
            "-StateRoot",
            str(state),
            "-TempRoot",
            str(temp),
            "-PythonPath",
            sys.executable,
        ]
    )
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    payload2 = _parse_last_json(proc2.stdout)
    assert payload2.get("status") in {"PREFLIGHT_OK", "observed", "OBSERVED"}
    assert payload2.get("provider_egress_runtime_verified") is False
    assert payload2.get("docker_mutated") is False
    assert payload2.get("domain_count") == 0


@requires_pwsh
def test_empty_allowlist_engineering_canary_fails_honestly(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-AllowlistPath",
            str(EGRESS_ROOT / "allowlist.v1.json"),
        ]
    )
    assert proc.returncode != 0
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") == "failed"
    assert payload.get("reason_code") == "EMPTY_ALLOWLIST_NO_POSITIVE_CANARY"
    assert payload.get("research_invoked") is False
    assert payload.get("is_research_call") is False
    assert payload.get("scientific_adoption") is False
    assert payload.get("completion_claim_allowed") is False
    assert payload.get("provider_egress_runtime_verified") is False
    evidence = payload.get("engineering_evidence") or {}
    assert evidence.get("positive_token_value") is None
    assert evidence.get("redaction", {}).get("token_values_forbidden") is True


@requires_pwsh
def test_negative_suite_preflight_plans_cases_without_docker(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-LiveNegativeSuite.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") == "PLANNED"
    assert payload.get("docker_mutated") is False
    assert payload.get("provider_egress_runtime_verified") is False
    receipt = json.loads((state / "negative_suite_receipt.v1.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "planned"
    ids = {c["id"] for c in receipt["cases"]}
    assert "N3" in ids and "N15" in ids and "N17" in ids
    assert all(c.get("result") == "planned" for c in receipt["cases"])


@requires_pwsh
def test_foreign_dify_and_label_mismatch_cleanup_rejection(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $failed = 0
        foreach ($n in @('ssrf_proxy','ssrf_proxy_network','docker_ssrf_proxy_network','dify-worker')) {{
          try {{
            Assert-XinaoNotForbiddenDockerTarget -Name $n | Out-Null
            Write-Output "UNEXPECTED_ALLOW:$n"
            $failed = 1
          }} catch {{
            Write-Output "REJECTED:$n"
          }}
        }}
        $okProxy = Test-XinaoExactCleanupCandidate -Name 'xinao-researcher-egress-proxy' -Kind container
        $badLabel = Test-XinaoExactCleanupCandidate -Name 'xinao-researcher-run-1' -Labels @{{'io.xinao.researcher.chain'='other'}} -Kind container
        $goodLabel = Test-XinaoExactCleanupCandidate -Name 'xinao-researcher-run-1' -Labels @{{'io.xinao.researcher.chain'='dedicated-xinao-science'}} -Kind container
        $foreignNet = Test-XinaoExactCleanupCandidate -Name 'bridge' -Kind network
        if (-not $okProxy) {{ Write-Output 'proxy_should_be_eligible'; $failed = 1 }}
        if ($badLabel) {{ Write-Output 'label_mismatch_should_reject'; $failed = 1 }}
        if (-not $goodLabel) {{ Write-Output 'good_label_should_accept'; $failed = 1 }}
        if ($foreignNet) {{ Write-Output 'foreign_net_should_reject'; $failed = 1 }}
        if ($failed -ne 0) {{ exit 1 }}
        'CLEANUP_RULES_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "REJECTED:ssrf_proxy" in proc.stdout
    assert "CLEANUP_RULES_OK" in proc.stdout

    # Preflight cleanup writes planned receipt without docker mutation.
    proc2 = _run_pwsh(
        [
            str(SCRIPTS / "Owner-CleanupEgress.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
        ]
    )
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    payload = _parse_last_json(proc2.stdout)
    assert payload.get("status") == "PLANNED"
    assert payload.get("dify_objects_touched") is False
    assert payload.get("docker_mutated") is False
    receipt = json.loads((state / "cleanup_receipt.v1.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "planned"
    assert receipt["proxy_removed_observed"] is False
    assert receipt["removed_networks_observed"] == []
    assert receipt["dify_objects_touched"] is False
    names = {x["name"] for x in receipt.get("foreign_name_static_rejections", [])}
    assert "ssrf_proxy" in names
    assert all(x.get("rejected") for x in receipt.get("foreign_name_static_rejections", []))


@requires_pwsh
def test_secret_redaction_helpers_and_receipt_invariant() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        if (-not (Test-XinaoSecretLeakText -Text 'Authorization: Bearer abcdefghijklmnop')) {{ throw 'should detect bearer' }}
        if (-not (Test-XinaoSecretLeakText -Text 'api_key=sk-1234567890abcdef')) {{ throw 'should detect api key' }}
        if (Test-XinaoSecretLeakText -Text 'status=observed allowlist_sha256=abc') {{ throw 'false positive' }}
        try {{
          New-XinaoBaseReceipt -SchemaVersion 'x.v1' -Status 'observed' -Extra @{{ note = 'Authorization: Bearer secretvalue123' }} | Out-Null
          throw 'receipt should reject secret'
        }} catch {{
          if ($_.Exception.Message -notmatch 'SECRET_LEAK') {{ throw $_ }}
        }}
        $r = New-XinaoBaseReceipt -SchemaVersion 'x.v1' -Status 'planned' -Extra @{{ note = 'clean' }}
        if ($r.completion_claim_allowed -ne $false) {{ throw 'completion claim' }}
        if ($r.provider_egress_runtime_verified -ne $false) {{ throw 'verified claim' }}
        if ($r.wsl_used -ne $false) {{ throw 'wsl flag' }}
        'REDACTION_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "REDACTION_OK" in proc.stdout


@requires_pwsh
def test_missing_evidence_fresh_process_readback_partial(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-FreshProcessReadback.ps1"),
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") in {"PARTIAL", "OBSERVED"}
    assert payload.get("completion_claim_allowed") is False
    assert payload.get("provider_egress_runtime_verified") is False
    assert payload.get("docker_mutated") is False
    # posture/negative/canary missing under empty state
    missing = payload.get("missing_keys") or []
    assert "posture" in missing
    assert "negative_suite_receipt" in missing
    assert "engineering_canary_receipt" in missing
    receipt = json.loads((state / "fresh_process_readback.v1.json").read_text(encoding="utf-8"))
    assert receipt["status"] in {"partial", "observed"}
    assert receipt.get("live_seal_consumer_ready_claim") is False
    assert receipt.get("wsl_used") is False


@requires_pwsh
def test_fresh_process_switch_spawns_child(tmp_path: Path) -> None:
    state = tmp_path / "state"
    temp = tmp_path / "temp"
    state.mkdir()
    temp.mkdir()
    # Seed one receipt so present_keys non-empty.
    seed = {
        "schema_version": "xinao.provider_egress_negative_suite_receipt.v1",
        "status": "planned",
        "provider_egress_runtime_verified": False,
        "completion_claim_allowed": False,
        "secrets_present": False,
    }
    (state / "negative_suite_receipt.v1.json").write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    env = {
        "XINAO_EGRESS_TEMP_ROOT": str(temp),
        "XINAO_EGRESS_STATE_ROOT": str(state),
    }
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-FreshProcessReadback.ps1"),
            "-FreshProcess",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
        ],
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("completion_claim_allowed") is False
    assert "negative_suite_receipt" in (payload.get("present_keys") or [])


@requires_pwsh
def test_discovery_scaffold_no_secrets_no_completion(tmp_path: Path) -> None:
    state = tmp_path / "state"
    out = tmp_path / "discovery"
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-DiscoverProviderEndpoints.ps1"),
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-OutDir",
            str(out),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") == "SCAFFOLD_READY"
    assert payload.get("completion_claim_allowed") is False
    receipt = json.loads((out / "discovery_receipt.v1.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "planned"
    assert receipt["provider_egress_runtime_verified"] is False
    assert receipt["secrets_present"] is False
    blob = json.dumps(receipt).lower()
    assert "authorization: bearer" not in blob
    assert "api_key=" not in blob


@requires_pwsh
def test_compose_safety_detects_host_ports_and_dify() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $good = Get-Content -LiteralPath '{(EGRESS_ROOT / "docker-compose.yaml").as_posix()}' -Raw
        $issues = Test-XinaoComposeSafetyText -ComposeText $good
        if ($issues.Count -ne 0) {{ throw ("unexpected issues: " + ($issues -join ',')) }}
        $bad = @"
        services:
          ssrf_proxy:
            container_name: ssrf_proxy
            ports:
              - "3128:3128"
        networks:
          ssrf_proxy_network:
        "@
        $badIssues = Test-XinaoComposeSafetyText -ComposeText $bad
        if ($badIssues.Count -lt 3) {{ throw ("expected multiple issues, got: " + ($badIssues -join ',')) }}
        'COMPOSE_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COMPOSE_OK" in proc.stdout


def test_no_wsl_dependency_in_scripts_static() -> None:
    for name in OWNER_SCRIPTS:
        text = (SCRIPTS / name).read_text(encoding="utf-8-sig").lower()
        assert "wsl.exe" not in text
        assert "bash.exe" not in text
        assert "/bin/bash" not in text
        assert "git-bash" not in text
        # Must not require wsl as true.
        assert "wsl_required = $true" not in text
        assert "wsl_required=$true" not in text


def test_scripts_do_not_claim_completion_or_verified_true_literals() -> None:
    for name in OWNER_SCRIPTS:
        text = (SCRIPTS / name).read_text(encoding="utf-8-sig")
        # Disallow assigning verified true in carriers.
        assert not re.search(r"provider_egress_runtime_verified\s*=\s*\$true", text)
        assert not re.search(r"completion_claim_allowed\s*=\s*\$true", text)
        assert "science_restored                   = $true" not in text
        assert "parent_complete                    = $true" not in text


def test_image_pin_file_still_unresolved_in_source() -> None:
    pin = json.loads((EGRESS_ROOT / "image-pin.v1.json").read_text(encoding="utf-8"))
    assert pin.get("image_id") is None
    assert pin.get("image_digest") is None
    assert pin.get("floating_tag_as_authority") is False


def test_allowlist_empty_is_fail_closed_default() -> None:
    allow = json.loads((EGRESS_ROOT / "allowlist.v1.json").read_text(encoding="utf-8"))
    assert allow.get("domains") == []


FIXTURE_CLI = ROOT / "tests" / "fixtures" / "engineering_canary_cli"


def test_engineering_canary_script_documents_real_provider_path() -> None:
    text = (SCRIPTS / "Owner-EngineeringCanary.ps1").read_text(encoding="utf-8-sig")
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").read_text(encoding="utf-8-sig")
    assert "-RealProviderCall" in text
    assert "AuthFilePath" in text
    assert "CanaryImageId" in text
    assert "ResearcherContainerStateRoot" in text
    assert "Resolve-XinaoCanaryImageAgainstActiveResearcherRelease" in common
    assert "CANARY_IMAGE_IS_DONOR_NOT_RESEARCHER" in common
    assert "ACTIVE_RESEARCHER_RELEASE_V2_ABSENT" in common
    assert "REAL_PROVIDER_CALL_NOT_IMPLEMENTED" not in text
    assert "cli-chat-proxy.grok.com" in text or "cli-chat-proxy.grok.com" in common
    assert "grok-4.5-build" in common
    assert "provider_effect_verified" in text
    assert "connect_only" in text
    # CONNECT-only must not claim seal-eligible true.
    assert "execute_connect_only" in text
    assert "provider_effect_verified" in text and "$false" in text
    # Must not re-bind canary to donor-only equality.
    assert "CANARY_IMAGE_ID_NOT_PINNED_DONOR" not in text
    assert "EGRESS_CANARY_IMAGE_NOT_PINNED_DONOR" not in text
    assert "active dedicated researcher" in text.lower() or "active researcher" in text.lower()


@requires_pwsh
def test_real_provider_preflight_requires_auth_and_image(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    rc_state = tmp_path / "researcher_container"
    synth = _write_synthetic_v2_researcher_state(rc_state)
    # Missing auth/image → fail without docker.
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(EGRESS_ROOT / "allowlist.v1.json"),
        ]
    )
    # Empty allowlist fails first.
    assert proc.returncode != 0
    payload = _parse_last_json(proc.stdout)
    assert payload.get("completion_claim_allowed") is False
    assert payload.get("provider_effect_verified") is False

    # With domains but missing image/auth.
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps(
            {
                "schema_version": "xinao.provider_egress_allowlist.v1",
                "ports": [443],
                "methods": ["CONNECT"],
                "domains": ["cli-chat-proxy.grok.com"],
            }
        ),
        encoding="utf-8",
    )
    proc2 = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc2.returncode != 0
    p2 = _parse_last_json(proc2.stdout)
    assert p2.get("reason_code") in {
        "CANARY_IMAGE_ID_REQUIRED",
        "EGRESS_AUTH_PATH_REQUIRED",
        "EGRESS_AUTH_PATH_MISSING",
    }
    assert p2.get("real_provider_call") is False
    assert p2.get("provider_effect_verified") is False

    auth = tmp_path / "auth.json"
    auth.write_text('{"dummy":true}\n', encoding="utf-8")
    # Unrelated immutable image must fail active-release bind.
    proc_bad_pin = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-AuthFilePath",
            str(auth),
            "-CanaryImageId",
            "sha256:" + ("a" * 64),
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc_bad_pin.returncode != 0
    p_bad = _parse_last_json(proc_bad_pin.stdout)
    assert p_bad.get("reason_code") == "CANARY_IMAGE_ID_NOT_ACTIVE_RELEASE"

    # Extraction donor is not a valid canary when active researcher image differs.
    proc_donor = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-AuthFilePath",
            str(auth),
            "-CanaryImageId",
            PINNED_DONOR_IMAGE_ID,
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc_donor.returncode != 0
    p_donor = _parse_last_json(proc_donor.stdout)
    assert p_donor.get("reason_code") == "CANARY_IMAGE_IS_DONOR_NOT_RESEARCHER"

    image = synth["image_id"]
    proc3 = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-AuthFilePath",
            str(auth),
            "-CanaryImageId",
            image,
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc3.returncode == 0, proc3.stdout + proc3.stderr
    p3 = _parse_last_json(proc3.stdout)
    assert p3.get("status") == "planned"
    assert p3.get("allow_real_provider_call_requested") is True
    assert p3.get("real_provider_call") is False  # not executed
    assert p3.get("provider_effect_verified") is False
    assert p3.get("canary_image_id") == image
    assert p3.get("canary_image_id") != PINNED_DONOR_IMAGE_ID
    assert p3.get("active_researcher_image_id") == image
    assert p3.get("pinned_donor_image_id") == PINNED_DONOR_IMAGE_ID
    assert p3.get("labels_verified") is False
    assert p3.get("auth_content_persisted") is False
    assert p3.get("docker_mutated") is False
    blob = json.dumps(p3).lower()
    assert "bearer" not in blob
    assert '"dummy"' not in blob
    # Auth host path must never appear in receipt.
    assert str(auth).lower() not in blob
    assert "auth.json" not in blob or "auth_json_bytes_forbidden" in blob


@requires_pwsh
def test_real_provider_rejects_floating_image_tag(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    rc_state = tmp_path / "researcher_container"
    _write_synthetic_v2_researcher_state(rc_state)
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"schema_version": "xinao.provider_egress_allowlist.v1", "domains": ["cli-chat-proxy.grok.com"]}),
        encoding="utf-8",
    )
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-RealProviderCall",
            "-AuthFilePath",
            str(auth),
            "-CanaryImageId",
            "xinao-researcher:latest",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-ResearcherContainerStateRoot",
            str(rc_state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc.returncode != 0
    payload = _parse_last_json(proc.stdout)
    assert payload.get("reason_code") == "CANARY_IMAGE_ID_NOT_IMMUTABLE"


@requires_pwsh
def test_canary_image_admission_rejection_matrix(tmp_path: Path) -> None:
    """Decisive offline preflight rejects: donor, unrelated, mismatch, legacy, hash, floating."""
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps(
            {
                "schema_version": "xinao.provider_egress_allowlist.v1",
                "domains": ["cli-chat-proxy.grok.com"],
            }
        ),
        encoding="utf-8",
    )
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    egress_state = tmp_path / "egress"
    egress_state.mkdir()

    def _run(canary: str, rc: Path) -> dict:
        proc = _run_pwsh(
            [
                str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
                "-PreflightOnly",
                "-RealProviderCall",
                "-AuthFilePath",
                str(auth),
                "-CanaryImageId",
                canary,
                "-PackageRoot",
                str(EGRESS_ROOT),
                "-StateRoot",
                str(egress_state),
                "-ResearcherContainerStateRoot",
                str(rc),
                "-AllowlistPath",
                str(allow),
            ]
        )
        assert proc.returncode != 0, proc.stdout + proc.stderr
        return _parse_last_json(proc.stdout)

    # Missing pointer entirely.
    empty_rc = tmp_path / "rc_empty"
    empty_rc.mkdir()
    p = _run(ACTIVE_RESEARCHER_IMAGE_ID, empty_rc)
    assert p.get("reason_code") == "ACTIVE_RESEARCHER_POINTER_ABSENT"

    # Legacy v1 pointer: honest failed, not donor-as-canary.
    legacy_rc = tmp_path / "rc_legacy"
    _write_synthetic_v2_researcher_state(legacy_rc, legacy_pointer=True)
    p = _run(ACTIVE_RESEARCHER_IMAGE_ID, legacy_rc)
    assert p.get("reason_code") == "ACTIVE_RESEARCHER_RELEASE_V2_ABSENT"

    # Manifest hash mismatch.
    bad_hash_rc = tmp_path / "rc_bad_hash"
    _write_synthetic_v2_researcher_state(bad_hash_rc, corrupt_manifest_hash=True)
    p = _run(ACTIVE_RESEARCHER_IMAGE_ID, bad_hash_rc)
    assert p.get("reason_code") == "ACTIVE_RESEARCHER_RELEASE_MANIFEST_HASH_MISMATCH"

    # Good v2; wrong donor in source identity.
    bad_donor_rc = tmp_path / "rc_bad_donor"
    _write_synthetic_v2_researcher_state(
        bad_donor_rc, donor_image_id="sha256:" + ("9" * 64)
    )
    p = _run(ACTIVE_RESEARCHER_IMAGE_ID, bad_donor_rc)
    assert p.get("reason_code") == "RELEASE_SOURCE_DONOR_MISMATCH"

    # Floating tag already covered; keep matrix self-contained.
    good_rc = tmp_path / "rc_good"
    _write_synthetic_v2_researcher_state(good_rc)
    p = _run("xinao-researcher:latest", good_rc)
    assert p.get("reason_code") == "CANARY_IMAGE_ID_NOT_IMMUTABLE"
    p = _run(PINNED_DONOR_IMAGE_ID, good_rc)
    assert p.get("reason_code") == "CANARY_IMAGE_IS_DONOR_NOT_RESEARCHER"
    p = _run("sha256:" + ("a" * 64), good_rc)
    assert p.get("reason_code") == "CANARY_IMAGE_ID_NOT_ACTIVE_RELEASE"


@requires_pwsh
def test_canary_execute_label_admission_mocked_docker(tmp_path: Path) -> None:
    """Execute-path label checks via mocked Invoke-XinaoDocker (no real Docker mutation)."""
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    rc_state = tmp_path / "researcher_container"
    synth = _write_synthetic_v2_researcher_state(rc_state)
    image = synth["image_id"]
    donor = synth["donor_image_id"]
    binary = synth["donor_binary_sha"]
    model = PINNED_MODEL
    pkg = EGRESS_ROOT.as_posix()
    rc = rc_state.as_posix()

    def _case(inspect_line: str, expect_reason: str | None) -> None:
        # Escape for single-quoted PowerShell string.
        line = inspect_line.replace("'", "''")
        cmd = textwrap.dedent(
            f"""
            . '{common}'
            function Invoke-XinaoDocker {{
              param([string[]]$ArgumentList, [switch]$AllowNonZero, [switch]$WhatIfPlan)
              return [pscustomobject]@{{
                ExitCode = 0
                StdOut = '{line}'
                StdErr = ''
                Planned = @()
              }}
            }}
            try {{
              $r = Resolve-XinaoCanaryImageAgainstActiveResearcherRelease `
                -ImageRef '{image}' `
                -PackageRoot '{pkg}' `
                -ResearcherContainerStateRoot '{rc}'
              if ($null -eq $r) {{ throw 'NULL_RESULT' }}
              $obj = [ordered]@{{
                ok = $true
                canary_image_id = [string]$r.canary_image_id
                labels_verified = [bool]$r.labels_verified
                pinned_donor_image_id = [string]$r.pinned_donor_image_id
              }}
              $obj | ConvertTo-Json -Compress
            }} catch {{
              $obj = [ordered]@{{ ok = $false; reason_code = [string]$_.Exception.Message }}
              $obj | ConvertTo-Json -Compress
              exit 0
            }}
            """
        )
        proc = _run_pwsh_command(cmd)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        if expect_reason is None:
            assert payload.get("ok") is True, payload
            assert payload.get("canary_image_id") == image
            assert payload.get("canary_image_id") != PINNED_DONOR_IMAGE_ID
            assert payload.get("labels_verified") is True
            assert payload.get("pinned_donor_image_id") == donor
        else:
            assert payload.get("ok") is False, payload
            assert payload.get("reason_code") == expect_reason

    good = f"{image}|{donor}|{binary}|{model}|dedicated-xinao-science|forbidden"
    _case(good, None)
    # Donor label mismatch.
    _case(
        f"{image}|sha256:{'9' * 64}|{binary}|{model}|dedicated-xinao-science|forbidden",
        "EGRESS_CANARY_DONOR_LABEL_MISMATCH",
    )
    # Binary label mismatch.
    _case(
        f"{image}|{donor}|{'d' * 64}|{model}|dedicated-xinao-science|forbidden",
        "EGRESS_CANARY_DONOR_BINARY_LABEL_MISMATCH",
    )
    # Missing labels (empty donor).
    _case(
        f"{image}|||{model}|dedicated-xinao-science|forbidden",
        "EGRESS_CANARY_DONOR_LABEL_MISSING",
    )
    # Observed image id mismatch vs active release.
    _case(
        f"sha256:{'e' * 64}|{donor}|{binary}|{model}|dedicated-xinao-science|forbidden",
        "EGRESS_CANARY_IMAGE_ID_MISMATCH",
    )
    # Chain / generic-worker-route required.
    _case(
        f"{image}|{donor}|{binary}|{model}||forbidden",
        "EGRESS_CANARY_CHAIN_LABEL_MISSING",
    )
    _case(
        f"{image}|{donor}|{binary}|{model}|dedicated-xinao-science|",
        "EGRESS_CANARY_GENERIC_WORKER_ROUTE_LABEL_MISSING",
    )
    # Preflight still admits without docker when v2 present.
    cmd_pre = textwrap.dedent(
        f"""
        . '{common}'
        $r = Resolve-XinaoCanaryImageAgainstActiveResearcherRelease `
          -ImageRef '{image}' `
          -PackageRoot '{pkg}' `
          -ResearcherContainerStateRoot '{rc}' `
          -Preflight
        $obj = [ordered]@{{
          canary_image_id = [string]$r.canary_image_id
          labels_verified = [bool]$r.labels_verified
          release_id = [string]$r.release_id
        }}
        $obj | ConvertTo-Json -Compress
        """
    )
    proc_pre = _run_pwsh_command(cmd_pre)
    assert proc_pre.returncode == 0, proc_pre.stderr + proc_pre.stdout
    pre = json.loads(proc_pre.stdout.strip().splitlines()[-1])
    assert pre["canary_image_id"] == image
    assert pre["labels_verified"] is False


@requires_pwsh
def test_cli_fixture_parse_matrix() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cases = [
        ("ok_endturn.json", True, None),
        ("wrong_model.json", False, "OBSERVED_BACKEND_MODEL_MISMATCH"),
        ("zero_output_tokens.json", False, "OUTPUT_TOKENS_NOT_POSITIVE"),
        ("incomplete_usage.json", False, "USAGE_ACCOUNTING_INCOMPLETE"),
        ("timeout_cancelled.json", False, "STOP_REASON_NOT_ENDTURN"),
        ("auth_path_leak.json", False, "CLI_OUTPUT_SECRET_LEAK"),
    ]
    for name, expect_ok, expect_reason in cases:
        path = (FIXTURE_CLI / name).as_posix()
        cmd = textwrap.dedent(
            f"""
            . '{common}'
            $raw = Get-Content -LiteralPath '{path}' -Raw
            $meta = ConvertFrom-XinaoGrokCliJsonText -JsonText $raw
            $obj = [ordered]@{{
              ok = [bool]$meta.ok
              reason_code = $meta.reason_code
              stop_reason = $meta.stop_reason
              observed_backend_model = $meta.observed_backend_model
              output_tokens = [int]$meta.output_tokens
              usage_accounting_complete = [bool]$meta.usage_accounting_complete
              text_persisted = $meta.text_persisted
            }}
            $obj | ConvertTo-Json -Compress
            """
        )
        proc = _run_pwsh_command(cmd)
        assert proc.returncode == 0, f"{name}: {proc.stderr}\n{proc.stdout}"
        meta = json.loads(proc.stdout.strip().splitlines()[-1])
        assert meta["ok"] is expect_ok, name
        if expect_reason:
            assert meta["reason_code"] == expect_reason, name
        if expect_ok:
            assert meta["stop_reason"] == "EndTurn"
            assert meta["observed_backend_model"] == "grok-4.5-build"
            assert meta["output_tokens"] > 0
            assert meta["usage_accounting_complete"] is True
        # Never echo model text body as a field.
        assert "text" not in meta or meta.get("text_persisted") is False


@requires_pwsh
def test_strict_seal_receipt_keys_and_connect_only_rejection() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    ok_path = (FIXTURE_CLI / "seal_receipt_ok.json").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $ok = Get-Content -LiteralPath '{ok_path}' -Raw | ConvertFrom-Json -Depth 40
        $r1 = Test-XinaoEngineeringCanarySealReceipt -Receipt $ok
        if ($r1.seal_eligible -ne $true) {{ throw ("ok should seal: " + $r1.reason_code) }}
        if ($null -eq $ok.usage) {{ throw 'usage required' }}
        if ($ok.usage.output_tokens -ne $ok.output_tokens) {{ throw 'usage.output mismatch' }}

        # Unknown key rejected.
        $extra = $ok | ConvertTo-Json -Depth 40 | ConvertFrom-Json
        $extra | Add-Member -NotePropertyName cleanup_observed -NotePropertyValue @{{x=1}} -Force
        $rx = Test-XinaoEngineeringCanarySealReceipt -Receipt $extra
        if ($rx.seal_eligible -ne $false -or $rx.reason_code -ne 'SEAL_RECEIPT_UNKNOWN_KEY') {{ throw 'unknown key must reject' }}

        # CONNECT-only style receipt must never be seal-eligible.
        $connect = [pscustomobject]@{{
          schema_version = 'xinao.provider_egress_engineering_canary_receipt.v1'
          status = 'observed'
          path_class = 'engineering_canary'
          real_provider_call = $false
          provider_effect_verified = $false
          requested_model = 'grok-4.5'
          observed_backend_model = $null
          stop_reason = $null
          output_tokens = 0
          usage_accounting_complete = $false
          usage = [ordered]@{{ input_tokens = 0; output_tokens = 0; total_tokens = 0 }}
          endpoint_host = 'cli-chat-proxy.grok.com'
          internal_network_id = 'net_x'
          proxy_container_id = 'ctr_x'
          proxy_image_id = 'sha256:' + ('c' * 64)
          allowlist_sha256 = ('d' * 64)
          proxy_config_sha256 = ('e' * 64)
          canary_image_id = 'sha256:' + ('f' * 64)
          internal_network_only = $true
          auth_mounted_read_only = $false
          auth_content_persisted = $false
          raw_output_persisted = $false
          research_invoked = $false
          is_research_call = $false
          scientific_research = $false
          masquerades_as_research = $false
          scientific_adoption = $false
          science_restored = $false
          parent_complete = $false
          authority = $false
          completion_claim_allowed = $false
          secrets_present = $false
          provider_egress_runtime_verified = $false
          provider_egress_live_verified = $false
          observed_at = (New-XinaoUtcNowIso)
          connect_only = $true
        }}
        $r2 = Test-XinaoEngineeringCanarySealReceipt -Receipt $connect
        if ($r2.seal_eligible -ne $false) {{ throw 'connect-only must reject seal' }}

        # Wrong model
        $bad = $ok | ConvertTo-Json -Depth 40 | ConvertFrom-Json
        $bad.observed_backend_model = 'grok-composer-2.5-fast'
        $r3 = Test-XinaoEngineeringCanarySealReceipt -Receipt $bad
        if ($r3.seal_eligible -ne $false) {{ throw 'wrong model must reject' }}

        # Zero tokens
        $bad2 = $ok | ConvertTo-Json -Depth 40 | ConvertFrom-Json
        $bad2.output_tokens = 0
        $bad2.usage.output_tokens = 0
        $r4 = Test-XinaoEngineeringCanarySealReceipt -Receipt $bad2
        if ($r4.seal_eligible -ne $false) {{ throw 'zero tokens must reject' }}

        'SEAL_MATRIX_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "SEAL_MATRIX_OK" in proc.stdout


@requires_pwsh
def test_raw_cleanup_target_containment(tmp_path: Path) -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    temp = tmp_path / "owned_temp_root"
    temp.mkdir()
    good_dir = temp / "engineering_canary_raw"
    good_dir.mkdir()
    good = good_dir / "canary_test.stdout.json"
    good.write_text("{}\n", encoding="utf-8")
    # Prefix sibling: owned root + "-evil" must reject.
    evil_sibling = tmp_path / (temp.name + "-evil")
    evil_sibling.mkdir()
    evil_file = evil_sibling / "x.json"
    evil_file.write_text("{}\n", encoding="utf-8")
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $temp = '{temp.as_posix()}'
        $good = '{good.as_posix()}'
        $resolved = Assert-XinaoRawCleanupTargetContained -RawPath $good -OwnedTempRoot $temp
        if ($resolved -notmatch 'engineering_canary_raw') {{ throw 'path rewrite failed' }}
        $failed = 0
        foreach ($bad in @(
          'C:\\Windows\\Temp\\evil.json',
          'D:\\XINAO_RESEARCH_RUNTIME\\state\\secret.json',
          'E:\\elsewhere\\x.json',
          '{evil_file.as_posix()}',
          '$temp'
        )) {{
          try {{
            Assert-XinaoRawCleanupTargetContained -RawPath $bad -OwnedTempRoot $temp | Out-Null
            Write-Output "UNEXPECTED_ALLOW:$bad"
            $failed = 1
          }} catch {{
            Write-Output "REJECTED_OK"
          }}
        }}
        # Directory target must reject (delete no directory).
        try {{
          Assert-XinaoRawCleanupTargetContained -RawPath '{good_dir.as_posix()}' -OwnedTempRoot $temp | Out-Null
          Write-Output 'UNEXPECTED_ALLOW_DIR'
          $failed = 1
        }} catch {{
          Write-Output 'REJECTED_DIR_OK'
        }}
        if ($failed -ne 0) {{ exit 1 }}
        'RAW_CONTAINMENT_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "RAW_CONTAINMENT_OK" in proc.stdout
    assert proc.stdout.count("REJECTED_OK") >= 4
    assert "REJECTED_DIR_OK" in proc.stdout


@requires_pwsh
def test_raw_cleanup_rejects_reparse_junction(tmp_path: Path) -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    temp = tmp_path / "owned_temp_root"
    temp.mkdir()
    real_dir = tmp_path / "real_outside"
    real_dir.mkdir()
    real_file = real_dir / "raw.json"
    real_file.write_text("{}\n", encoding="utf-8")
    link_dir = temp / "engineering_canary_raw"
    # Junction/reparse into outside tree.
    mk = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_dir), str(real_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if mk.returncode != 0:
        pytest.skip(f"junction creation unavailable: {(mk.stdout or '')} {(mk.stderr or '')}")
    target = link_dir / "raw.json"
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        try {{
          Assert-XinaoRawCleanupTargetContained -RawPath '{target}' -OwnedTempRoot '{temp}' | Out-Null
          Write-Output 'UNEXPECTED_ALLOW_REPARSE'
          exit 1
        }} catch {{
          Write-Output ('REJECTED_REPARSE:' + $_.Exception.Message)
        }}
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "REJECTED_REPARSE" in proc.stdout
    assert "UNEXPECTED_ALLOW_REPARSE" not in proc.stdout


@requires_pwsh
def test_auth_admission_hardens_without_path_leak(tmp_path: Path) -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    missing = tmp_path / "no_such_auth_file.json"
    cmd = textwrap.dedent(
        f"""
        $OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
        . '{common}'
        $ok = Assert-XinaoAuthFilePathLiteral -AuthFilePath '{auth.as_posix()}'
        if (-not (Test-Path -LiteralPath $ok -PathType Leaf)) {{ throw 'resolved missing' }}
        $failed = 0
        $cases = @(
          [pscustomobject]@{{ Path = ''; Code = 'EGRESS_AUTH_PATH_REQUIRED' }},
          [pscustomobject]@{{ Path = '%TEMP%\\auth.json'; Code = 'EGRESS_AUTH_PATH_UNRESOLVED_VARIABLE' }},
          [pscustomobject]@{{ Path = 'relative\\auth.json'; Code = 'EGRESS_AUTH_PATH_NOT_ABSOLUTE' }},
          [pscustomobject]@{{ Path = '{missing.as_posix()}'; Code = 'EGRESS_AUTH_PATH_MISSING' }}
        )
        foreach ($pair in $cases) {{
          try {{
            Assert-XinaoAuthFilePathLiteral -AuthFilePath $pair.Path | Out-Null
            Write-Output ("UNEXPECTED_ALLOW:" + $pair.Code)
            $failed = 1
          }} catch {{
            $msg = [string]$_.Exception.Message
            if ($msg -ne $pair.Code) {{ Write-Output ("WRONG_CODE expected=" + $pair.Code + " got=" + $msg); $failed = 1 }}
            else {{ Write-Output ("REJECTED:" + $pair.Code) }}
            if ($msg -match '[A-Za-z]:\\\\') {{ Write-Output 'PATH_LEAK'; $failed = 1 }}
          }}
        }}
        if ($failed -ne 0) {{ exit 1 }}
        Write-Output 'AUTH_ADMISSION_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out
    assert "AUTH_ADMISSION_OK" in out
    assert "PATH_LEAK" not in out


@requires_pwsh
def test_negative_suite_seal_fields_helper() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $ids = [ordered]@{{
          internal_network_id = 'net1'
          proxy_container_id = 'ctr1'
          proxy_image_id = 'sha256:' + ('a' * 64)
          allowlist_sha256 = ('b' * 64)
          proxy_config_sha256 = ('c' * 64)
        }}
        $ok = Get-XinaoNegativeSuiteSealFields -ObjectIdentities $ids -PassCount 13 -FailCount 0 -CaseCount 13 -UnauthorizedDomainReachable:$false -DirectNoProxyEscape:$false
        if ($ok.status -ne 'observed') {{ throw 'expected observed' }}
        if ($ok.suite_passed -ne $true) {{ throw 'suite should pass' }}
        if ($ok.all_cases_passed -ne $true) {{ throw 'all cases' }}
        $partialIds = [ordered]@{{
          internal_network_id = $null
          proxy_container_id = 'ctr1'
          proxy_image_id = 'sha256:' + ('a' * 64)
          allowlist_sha256 = ('b' * 64)
          proxy_config_sha256 = ('c' * 64)
        }}
        $p = Get-XinaoNegativeSuiteSealFields -ObjectIdentities $partialIds -PassCount 13 -FailCount 0 -CaseCount 13 -UnauthorizedDomainReachable:$false -DirectNoProxyEscape:$false
        if ($p.status -ne 'partial') {{ throw 'missing ids => partial' }}
        if ($p.suite_passed -ne $false) {{ throw 'suite must not pass without ids' }}
        $fail = Get-XinaoNegativeSuiteSealFields -ObjectIdentities $ids -PassCount 10 -FailCount 3 -CaseCount 13 -UnauthorizedDomainReachable:$false -DirectNoProxyEscape:$false
        if ($fail.status -ne 'partial') {{ throw 'mixed => partial' }}
        $escapeOpen = Get-XinaoNegativeSuiteSealFields -ObjectIdentities $ids -PassCount 13 -FailCount 0 -CaseCount 13 -UnauthorizedDomainReachable:$true -DirectNoProxyEscape:$false
        if ($escapeOpen.suite_passed -ne $false) {{ throw 'open unauthorized must not seal' }}
        'NEG_SEAL_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "NEG_SEAL_OK" in proc.stdout


@requires_pwsh
def test_connect_only_preflight_never_seal_eligible(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps({"schema_version": "xinao.provider_egress_allowlist.v1", "domains": ["cli-chat-proxy.grok.com"]}),
        encoding="utf-8",
    )
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-EngineeringCanary.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
            "-AllowlistPath",
            str(allow),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("status") == "planned"
    assert payload.get("real_provider_call") is False
    assert payload.get("provider_effect_verified") is False
    assert payload.get("connect_only") is True
    assert payload.get("completion_claim_allowed") is False
    assert payload.get("scientific_research") is False
    assert payload.get("scientific_adoption") is False


@requires_pwsh
def test_floating_client_image_rejected_on_execute_helpers() -> None:
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        if (Test-XinaoImmutableImageIdFormat -ImageId 'busybox:1.36') {{ throw 'floating tag accepted' }}
        if (Test-XinaoImmutableImageIdFormat -ImageId 'ubuntu/squid:latest') {{ throw 'latest accepted' }}
        if (-not (Test-XinaoImmutableImageIdFormat -ImageId ('sha256:' + ('a' * 64)))) {{ throw 'immutable rejected' }}
        try {{
          ConvertTo-XinaoCanonicalImageId -ImageId 'busybox:1.36' | Out-Null
          throw 'should reject floating'
        }} catch {{
          if ($_.Exception.Message -notmatch 'NOT_IMMUTABLE') {{ throw $_ }}
        }}
        'FLOATING_CLIENT_OK'
        """
    )
    proc = _run_pwsh_command(cmd)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "FLOATING_CLIENT_OK" in proc.stdout


@requires_pwsh
def test_negative_preflight_reports_missing_client_image(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    proc = _run_pwsh(
        [
            str(SCRIPTS / "Owner-LiveNegativeSuite.ps1"),
            "-PreflightOnly",
            "-PackageRoot",
            str(EGRESS_ROOT),
            "-StateRoot",
            str(state),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = _parse_last_json(proc.stdout)
    assert payload.get("client_image_reason_code") == "CLIENT_IMAGE_ID_MISSING"
    receipt = json.loads((state / "negative_suite_receipt.v1.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "planned"
    assert len(receipt["cases"]) == 13
    ids = {c["id"] for c in receipt["cases"]}
    assert ids == {
        "N1",
        "N3",
        "N4",
        "N5",
        "N6",
        "N7",
        "N8",
        "N9",
        "N15",
        "N17",
        "N17b",
        "N17c",
        "N17d",
    }


@requires_pwsh
def test_cross_contract_offline_receipt_handshake(tmp_path: Path) -> None:
    """Build receipts via PowerShell pure builders; validate with sealer + runtime."""
    common = (SCRIPTS / "XinaoEgressOwner.Common.ps1").as_posix()
    out_dir = tmp_path / "built"
    out_dir.mkdir()
    canary_path = out_dir / "canary.json"
    negative_path = out_dir / "negative.json"
    fixture_cli = (FIXTURE_CLI / "ok_endturn.json").as_posix()
    cmd = textwrap.dedent(
        f"""
        . '{common}'
        $meta = ConvertFrom-XinaoGrokCliJsonText -JsonText (Get-Content -LiteralPath '{fixture_cli}' -Raw)
        if ($meta.ok -ne $true) {{ throw ('meta not ok: ' + $meta.reason_code) }}
        $postureIds = [ordered]@{{
          internal_network_id = 'net_' + ('a' * 16)
          proxy_container_id = 'ctr_' + ('b' * 16)
          proxy_image_id = 'sha256:' + ('c' * 64)
          allowlist_sha256 = ('d' * 64)
          proxy_config_sha256 = ('e' * 64)
        }}
        $objectIds = [ordered]@{{
          internal_network_id = $postureIds.internal_network_id
          proxy_container_id = $postureIds.proxy_container_id
          proxy_image_id = $postureIds.proxy_image_id
          allowlist_sha256 = $postureIds.allowlist_sha256
          proxy_config_sha256 = $postureIds.proxy_config_sha256
          client_image_id = 'sha256:' + ('1' * 64)
        }}
        $canary = New-XinaoEngineeringCanarySealReceipt `
          -Meta $meta `
          -PostureIds $postureIds `
          -CanaryImageId ('sha256:' + ('f' * 64)) `
          -ConnectProbeOk:$true `
          -CanaryContainerId 'ctr_canary_test' `
          -CanaryContainerRemoved:$true `
          -RawOutputSha256 $meta.raw_sha256 `
          -ObjectIdentities $objectIds `
          -ObservedAt (New-XinaoUtcNowIso)
        Write-XinaoJsonFile -Path '{canary_path.as_posix()}' -Object $canary | Out-Null

        $cases = @()
        foreach ($id in $script:XinaoRequiredNegativeCaseIds) {{
          $cases += [ordered]@{{ id = $id; ok = $true; title = $id; expect = 'denied'; mode = 'proxy'; target = 'https://example.com/'; got_signal = 'match_expected_fail_closed' }}
        }}
        $neg = New-XinaoNegativeSuiteSealReceipt -Cases $cases -ObjectIdentities $objectIds -ObservedAt (New-XinaoUtcNowIso)
        $negCheck = Test-XinaoNegativeSuiteSealReceipt -Receipt $neg
        if ($negCheck.seal_eligible -ne $true) {{ throw ('neg builder not sealable: ' + $negCheck.reason_code) }}
        Write-XinaoJsonFile -Path '{negative_path.as_posix()}' -Object $neg | Out-Null
        'BUILD_OK'
        """
    )
    proc = _run_pwsh_command(cmd, timeout=90)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "BUILD_OK" in proc.stdout

    canary = json.loads(canary_path.read_text(encoding="utf-8"))
    negative = json.loads(negative_path.read_text(encoding="utf-8"))
    posture = {
        "schema_version": "xinao.provider_egress_posture.v1",
        "lifecycle_state": "HEALTHY",
        "internal_network_name": "xinao_researcher_internal",
        "internal_network_id": "net_" + "a" * 16,
        "external_network_name": "xinao_provider_egress_ext",
        "proxy_container_name": "xinao-researcher-egress-proxy",
        "proxy_container_id": "ctr_" + "b" * 16,
        "proxy_image_id": "sha256:" + "c" * 64,
        "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "proxy_listen_port": 3128,
        "allowlist_sha256": "d" * 64,
        "proxy_config_sha256": "e" * 64,
        "provider_domains": [],
        "host_port_published": False,
        "dify_cross_project": False,
        "tls_interception": False,
        "provider_egress_runtime_verified": False,
        "verification_evidence": {"negative_suite": None, "positive_canary": None},
        "secrets_present": False,
    }
    now = dt.datetime.now(dt.UTC)
    sealer = _sealer()
    runtime = _runtime()

    # Valid receipts must pass both consumers.
    sealer.validate_engineering_canary_receipt(canary, posture=posture, now=now)
    sealer.validate_negative_suite_receipt(negative, posture=posture, now=now)
    runtime._validate_engineering_canary_receipt_semantics(
        canary,
        posture=posture,
        reason_code="TEST_CANARY",
        now=now,
        max_age_seconds=24 * 3600,
    )
    runtime._validate_negative_suite_receipt_semantics(
        negative,
        posture=posture,
        reason_code="TEST_NEG",
        now=now,
        max_age_seconds=24 * 3600,
    )

    def _both_canary_fail(receipt: dict) -> None:
        with pytest.raises(sealer.SealError):
            sealer.validate_engineering_canary_receipt(receipt, posture=posture, now=now)
        with pytest.raises(runtime.XinaoError):
            runtime._validate_engineering_canary_receipt_semantics(
                receipt,
                posture=posture,
                reason_code="TEST_CANARY_FAIL",
                now=now,
                max_age_seconds=24 * 3600,
            )

    def _both_neg_fail(receipt: dict) -> None:
        with pytest.raises(sealer.SealError):
            sealer.validate_negative_suite_receipt(receipt, posture=posture, now=now)
        with pytest.raises(runtime.XinaoError):
            runtime._validate_negative_suite_receipt_semantics(
                receipt,
                posture=posture,
                reason_code="TEST_NEG_FAIL",
                now=now,
                max_age_seconds=24 * 3600,
            )

    # Delete usage -> both fail.
    bad_usage = json.loads(json.dumps(canary))
    del bad_usage["usage"]
    _both_canary_fail(bad_usage)

    # Unknown field -> both fail.
    bad_unknown = json.loads(json.dumps(canary))
    bad_unknown["cleanup_observed"] = {"x": 1}
    _both_canary_fail(bad_unknown)

    # CONNECT-only -> both fail.
    connect_only = json.loads(json.dumps(canary))
    connect_only["real_provider_call"] = False
    connect_only["provider_effect_verified"] = False
    connect_only["connect_only"] = True
    connect_only["output_tokens"] = 0
    connect_only["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    connect_only["usage_accounting_complete"] = False
    _both_canary_fail(connect_only)

    # Wrong posture binding -> both fail.
    bad_posture = json.loads(json.dumps(canary))
    bad_posture["internal_network_id"] = "replayed_net"
    _both_canary_fail(bad_posture)

    # Stale observation -> both fail.
    stale = json.loads(json.dumps(canary))
    stale["observed_at"] = "2020-01-01T00:00:00.000Z"
    _both_canary_fail(stale)

    # Incomplete negative suite -> both fail.
    incomplete_neg = json.loads(json.dumps(negative))
    incomplete_neg["cases"] = incomplete_neg["cases"][:10]
    incomplete_neg["pass_count"] = 10
    _both_neg_fail(incomplete_neg)

    # Negative unknown key -> both fail.
    neg_unknown = json.loads(json.dumps(negative))
    neg_unknown["case_count"] = 13
    _both_neg_fail(neg_unknown)

    # Negative wrong posture -> both fail.
    neg_posture = json.loads(json.dumps(negative))
    neg_posture["proxy_container_id"] = "replayed"
    _both_neg_fail(neg_posture)


def test_runbook_documents_real_provider_canary() -> None:
    runbook = (EGRESS_ROOT / "OWNER_RUNBOOK.md").read_text(encoding="utf-8")
    assert "-RealProviderCall" in runbook
    assert "CanaryImageId" in runbook or "canary image" in runbook.lower()
    assert "cli-chat-proxy.grok.com" in runbook
    assert "grok-4.5-build" in runbook
    assert "CONNECT-only" in runbook or "CONNECT only" in runbook or "not seal-eligible" in runbook.lower()
    assert "usage" in runbook.lower()
    assert "ClientImageId" in runbook or "client image" in runbook.lower() or "immutable" in runbook.lower()
    assert "protocol-v2" in runbook or "protocol-v2" in runbook.lower() or "researcher_current_pointer.v2" in runbook
    assert "ResearcherContainerStateRoot" in runbook
    assert "active dedicated researcher" in runbook.lower() or "active researcher" in runbook.lower()
    assert "grok_donor_image_id" in runbook  # still documented as provenance
    assert "not the unlabeled extraction donor" in runbook.lower() or "not extraction donor" in runbook.lower() or "provenance only" in runbook.lower()
    # Must not instruct owners to pass donor as CanaryImageId.
    assert "CanaryImageId 'sha256:<pinned grok_donor_image_id>'" not in runbook
    assert "migrate" in runbook.lower() or "activate" in runbook.lower()
