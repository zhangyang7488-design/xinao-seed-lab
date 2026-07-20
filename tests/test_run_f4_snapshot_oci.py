from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from scripts import run_f4_snapshot_oci as subject


def _write_content_addressed(path: Path, core: dict[str, object]) -> dict[str, object]:
    value = {**core, "content_sha256": subject._canonical_sha256(core)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(subject._canonical_bytes(value))
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_output(root: Path) -> list[dict[str, object]]:
    assertion_ids = [f"assertion-{index:02d}" for index in range(14)]
    bundle = _write_content_addressed(
        root / "f4_assertion_actual_bundle.v2.json",
        {
            "schema_version": "xinao.assertion_actual_bundle.v2",
            "block_id": "F4_research_factory",
            "assertion_actuals": {key: True for key in assertion_ids},
        },
    )
    bundle_path = root / "f4_assertion_actual_bundle.v2.json"
    _write_content_addressed(
        root / "stage0_result.json",
        {
            "status": "VERIFIED",
            "assertion_count": 14,
            "fallback_count": 0,
            "common_assertion_bundle": {
                "sha256": _sha(bundle_path),
                "size_bytes": bundle_path.stat().st_size,
                "content_sha256": bundle["content_sha256"],
            },
            "common_authority_projection": {
                "schema_version": "xinao.f4_common_authority_projection.v1",
                "status": "VERIFIED",
            },
        },
    )
    _write_content_addressed(
        root / "snapshot_trace_summary.json",
        {
            "status": "VERIFIED",
            "fallback_count": 0,
            "process_count": 5,
        },
    )
    return subject._output_inventory(root)


def test_runner_cli_exposes_only_output_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["runner", "--image", "replacement"])
    with pytest.raises(SystemExit):
        subject.parse_args()

    monkeypatch.setattr(sys, "argv", ["runner", "--output-parent", "D:/evidence/run"])
    assert subject.parse_args().output_parent == Path("D:/evidence/run")


def test_output_parent_cannot_overlap_data_capsule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence"
    capsule = evidence / "capsule"
    capsule.mkdir(parents=True)
    authority = evidence / "authority"
    authority.mkdir()
    monkeypatch.setattr(subject, "ALLOWED_OUTPUT_ROOT", evidence)
    config = {
        "data_manifest_path": str(capsule / "snapshot_manifest.json"),
        "authority_manifest_path": str(authority / "authority_source_manifest.json"),
        "build_receipt_path": str(evidence / "build" / "image_build_receipt.json"),
    }

    with pytest.raises(subject.OciRunnerError, match="overlaps"):
        subject._validate_output_parent(capsule / "new-output", config)
    assert not (capsule / "new-output").exists()


def test_created_container_accepts_normalized_no_new_privileges(
    tmp_path: Path,
) -> None:
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    config = {
        "image_id": "sha256:" + "1" * 64,
        "data_manifest_path": str(capsule / "snapshot_manifest.json"),
    }
    container = {
        "Image": config["image_id"],
        "Config": {
            "Entrypoint": list(subject.EXPECTED_ENTRYPOINT),
            "Cmd": list(subject.EXPECTED_CMD),
            "User": "65532:65532",
            "WorkingDir": "/work",
            "Env": ["PATH=/bin"],
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "NetworkMode": "none",
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "PidsLimit": 256,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=268435456"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(capsule.resolve()),
                "Destination": "/capsule",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(output.resolve()),
                "Destination": "/output",
                "RW": True,
            },
        ],
    }

    observed = subject._verify_created_container(
        container,
        config=config,
        output_dir=output,
    )

    assert observed["readonly_rootfs"] is True
    assert observed["pids_limit"] == 256
    assert observed["user"] == "65532:65532"


def test_relocated_data_root_must_equal_frozen_content_identity(tmp_path: Path) -> None:
    root = tmp_path / "capsule"
    manifest = _write_content_addressed(
        root / "snapshot_manifest.json",
        {"schema_version": "xinao.f4_evidence_snapshot.v1", "entries": []},
    )
    config = {
        "data_manifest_sha256": _sha(root / "snapshot_manifest.json"),
        "data_content_sha256": manifest["content_sha256"],
    }

    assert subject._admit_execution_data_root(config, root) == root.resolve()

    (root / "snapshot_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(subject.OciRunnerError, match="content identity"):
        subject._admit_execution_data_root(config, root)


def test_execution_receipt_revalidates_both_sealed_output_trees(tmp_path: Path) -> None:
    inventories = []
    runs = []
    for ordinal in (1, 2):
        output = tmp_path / f"run-{ordinal}"
        inventory = _sealed_output(output)
        inventories.append(inventory)
        runs.append(
            {
                "ordinal": ordinal,
                "exit_code": 0,
                "output_ref": str(output.resolve()),
                "isolation": {
                    "readonly_rootfs": True,
                    "network_mode": "none",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "xinao_f4_environment_count": 0,
                },
                "semantic_output_file_count": len(inventory),
                "semantic_output_inventory": inventory,
                "semantic_output_set_sha256": subject._canonical_sha256(inventory),
            }
        )
    assert inventories[0] == inventories[1]
    receipt_core = {
        "schema_version": subject.RECEIPT_SCHEMA,
        "status": "VERIFIED",
        "run_count": 2,
        "runs": runs,
        "semantic_output_byte_identical": True,
        "semantic_output_set_sha256": subject._canonical_sha256(inventories[0]),
        "assertion_count": 14,
        "fallback_count": 0,
        "network_mode": "none",
        "readonly_rootfs": True,
        "data_mount_readonly": True,
        "authority_mount_count": 0,
        "host_xinao_f4_environment_forward_count": 0,
    }
    receipt = {
        **receipt_core,
        "content_sha256": subject._canonical_sha256(receipt_core),
    }
    receipt_path = tmp_path / "execution_capsule_receipt.json"
    receipt_path.write_bytes(subject._canonical_bytes(receipt))

    assert subject.verify_execution_receipt(receipt_path) == receipt

    bundle_path = tmp_path / "run-2" / "f4_assertion_actual_bundle.v2.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["assertion_actuals"]["assertion-00"] = False
    bundle_path.write_bytes(subject._canonical_bytes(bundle))
    with pytest.raises(subject.OciRunnerError):
        subject.verify_execution_receipt(receipt_path)
