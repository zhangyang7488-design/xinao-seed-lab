from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    canonical_text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical_text.encode()).hexdigest().upper()


def test_toolchain_lock_matches_project_inputs() -> None:
    lock = json.loads((ROOT / "provisioning" / "toolchain-lock.json").read_text())
    assert lock["schema_version"] == 1
    assert lock["uv"]["version"] == "0.11.16"
    assert lock["python"]["request"] == "3.12.13"
    assert lock["policy"] == {
        "frozen_lock": True,
        "hashed_build_dependencies": True,
        "non_editable_project": True,
        "link_mode": "copy",
        "allow_missing_prerequisite_download": True,
        "normal_fast_path_network": False,
    }
    for relative, expected in lock["inputs"].items():
        assert sha256(ROOT / relative) == expected


def test_build_backend_is_exact_and_hash_pinned() -> None:
    constraints = (ROOT / "provisioning" / "build-constraints.txt").read_text()
    assert "hatchling==1.31.0" in constraints
    assert "aac80bec8b6fe35e8480f1c335be8910fa210a0e6f735a139be205dadcacb544" in constraints
    assert "--hash=sha256:" in constraints


def test_acpx_toolchain_is_exact_and_hash_pinned() -> None:
    lock = json.loads((ROOT / "provisioning" / "acpx-toolchain-lock.json").read_text())
    assert lock["schema_version"] == 1
    assert lock["node"]["version"] == "24.16.0"
    assert lock["node"]["archive_sha256"] == (
        "EDACA9BD58EC8E92037DAC4E877D52F6B8F430B81C18B57E264B4E2FB111CD56"
    )
    assert lock["node"]["executable_sha256"] == (
        "B3094D0B49F9AD602262A9921551737BB97637C05DD357A06AE98188D7290AA3"
    )
    assert lock["node"]["npm_cmd_sha256"] == (
        "21B46C69AD6E2F231F02A9E120F4BA6C8E75FEF5A45637103002EAB99F888AB8"
    )
    assert lock["acpx"]["version"] == "0.12.0"
    assert lock["acpx"]["license"] == "MIT"
    assert lock["acpx"]["tarball_integrity"].startswith("sha512-")
    package_lock = json.loads((ROOT / "provisioning" / "acpx-runtime" / "package-lock.json").read_text())
    locked_acpx = package_lock["packages"]["node_modules/acpx"]
    assert locked_acpx["resolved"] == lock["acpx"]["tarball_url"]
    assert locked_acpx["integrity"] == lock["acpx"]["tarball_integrity"]
    assert lock["policy"] == {
        "frozen_lock": True,
        "ignore_install_scripts": True,
        "normal_fast_path_network": False,
        "allow_missing_prerequisite_download": True,
    }
    for relative, expected in lock["inputs"].items():
        assert sha256(ROOT / relative) == expected


def test_acpx_provisioner_has_offline_fast_path_and_safe_repair_guard() -> None:
    provisioner = (ROOT / "provisioning" / "Invoke-XinaoAcpxManaged.ps1").read_text()
    assert "XINAO_ACPX_GENERATION_MISSING_OFFLINE" in provisioner
    assert "XINAO_ACPX_UNSAFE_REPAIR_TARGET" in provisioner
    assert "--ignore-scripts" in provisioner
    assert "Get-ValidGeneration" in provisioner
    assert "Invoke-ExclusiveFileLock" in provisioner
    assert "payload_tree_sha256" in provisioner
    assert "file_index_sha256" in provisioner
    assert "trust\\payload-anchors" in provisioner
    assert "XINAO_ACPX_TRUST_ANCHOR_CONFLICT" in provisioner
    assert "Repair-NpmCommandFromArchive" in provisioner
    assert "XINAO_ACPX_TOP_LEVEL_PACKAGE_LOCK_MISMATCH" in provisioner
    assert "Test-CurrentPointer" in provisioner
    assert "XINAO_ACPX_NPM_CI_FAILED" in provisioner
    assert "Protect-AcpxQueueOwnership\n&" not in provisioner


def test_grok_acp_adapter_bootstraps_missing_runtime_and_uses_d_scratch() -> None:
    adapter = (ROOT / "adapters" / "grok" / "Invoke-XinaoGrokAcp.ps1").read_text()
    assert "-Target acpx -Offline" not in adapter
    assert "Join-Path $AcpxHome 'work'" in adapter
    assert "'--format', 'quiet'" in adapter
    assert "'--suppress-reads'" in adapter
    assert "Test-AcpxQuietMetadataLine" in adapter
    assert "--no-wait" not in adapter


def test_launchers_do_not_depend_on_project_dot_venv() -> None:
    provisioner = (ROOT / "provisioning" / "Invoke-XinaoCoordManaged.ps1").read_text()
    adapter = (ROOT / "adapters" / "grok" / "Invoke-XinaoCoord.ps1").read_text()
    assert ".venv" not in provisioner
    assert ".venv" not in adapter
    assert "Invoke-XinaoCoordManaged.ps1" in adapter


def test_managed_generation_probe_pins_temporal_sdk() -> None:
    provisioner = (ROOT / "provisioning" / "Invoke-XinaoCoordManaged.ps1").read_text()

    assert 'm.version("temporalio")' in provisioner
    assert "$Probe.temporalio -eq '1.30.0'" in provisioner


def test_temporal_pin_generator_is_read_only_and_not_self_referential() -> None:
    generator = (ROOT / "provisioning" / "_lane_c_build_pin.ps1").read_text()
    pin = json.loads((ROOT / "provisioning" / "temporal_mcp_pin.json").read_text())

    assert "uv run" not in generator
    assert "provisioning/temporal_mcp_pin.json" not in pin["key_files_sha256"]
    assert pin["worker_deployment"] == {
        "manifest": "adapters/temporal/worker_deployment.v1.json",
        "deployment_name": "xinao-dualbrain-promoted",
        "build_id": "aaebb0901fdc8afd25d84ce5fa1e9454",
        "default_versioning_behavior": "PINNED",
        "target_server": "1.31.0",
        "replay_gate": "adapters/temporal/replay_promoted_histories.py",
    }
    for relative, expected in pin["key_files_sha256"].items():
        assert sha256(ROOT / relative) == expected


def test_mkeep_default_config_is_forced_into_the_wheel() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    module = (ROOT / "src" / "xinao_coordination" / "m_keep.py").read_text(encoding="utf-8")

    assert '"configs/modules/m_keep.toml" = "xinao_coordination/configs/m_keep.toml"' in pyproject
    assert 'Path(__file__).resolve().parent / "configs" / "m_keep.toml"' in module
