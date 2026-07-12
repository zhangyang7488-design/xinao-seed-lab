from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c14_supply_chain.py"
    spec = importlib.util.spec_from_file_location("verify_c14_supply_chain_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pointer(path: Path, generation_id: str = "coord-current") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "source_fingerprint": generation_id.removeprefix("coord-").upper(),
                "generation_path": str(path.parent / "generations" / generation_id),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_pointer_snapshot_detects_any_bytes_hash_mtime_or_target_change(tmp_path: Path) -> None:
    module = _module()
    pointer = tmp_path / "current.json"
    _write_pointer(pointer)
    before = module._pointer_snapshot(pointer)

    unchanged = module._compare_pointer_snapshots(before, module._pointer_snapshot(pointer))
    assert unchanged == {
        "bytes_unchanged": True,
        "hash_unchanged": True,
        "mtime_unchanged": True,
        "target_unchanged": True,
        "path_unchanged": True,
        "ok": True,
    }

    original_mtime_ns = pointer.stat().st_mtime_ns
    _write_pointer(pointer, "coord-other")
    os.utime(pointer, ns=(pointer.stat().st_atime_ns, original_mtime_ns))
    changed = module._compare_pointer_snapshots(before, module._pointer_snapshot(pointer))

    assert changed["bytes_unchanged"] is False
    assert changed["hash_unchanged"] is False
    assert changed["mtime_unchanged"] is True
    assert changed["target_unchanged"] is False
    assert changed["ok"] is False


def test_rollback_dry_run_validation_rejects_apply_or_wrong_exact_target(tmp_path: Path) -> None:
    module = _module()
    pointer = tmp_path / "current.json"
    _write_pointer(pointer)
    before = module._pointer_snapshot(pointer)
    after = module._pointer_snapshot(pointer)
    rollback_id = "coord-rollback"
    rollback_root = tmp_path / "generations" / rollback_id
    rollback_manifest = rollback_root / "generation.json"
    rollback_root.mkdir(parents=True)
    rollback_manifest.write_text("{}", encoding="utf-8")
    base = {
        "exit_code": 0,
        "command": ["pwsh.exe", "-File", "rollback.ps1"],
        "executable": {"exists": True},
        "json": {
            "ok": True,
            "applied": False,
            "pointer_path": str(pointer),
            "expected_current": "coord-current",
            "restore": rollback_id,
            "restore_manifest": str(rollback_manifest),
            "replacement": {
                "generation_id": rollback_id,
                "generation_path": str(rollback_root),
                "source_fingerprint": "ROLLBACK",
            },
        },
    }

    valid = module._validate_rollback_dry_run(
        base,
        before=before,
        after=after,
        current_generation="coord-current",
        rollback_generation=rollback_id,
        rollback_root=rollback_root,
        rollback_manifest_path=rollback_manifest,
        rollback_source_fingerprint="ROLLBACK",
    )
    assert valid["ok"] is True
    assert all(valid["checks"].values())

    applied = json.loads(json.dumps(base))
    applied["json"]["applied"] = True
    assert module._validate_rollback_dry_run(
        applied,
        before=before,
        after=after,
        current_generation="coord-current",
        rollback_generation=rollback_id,
        rollback_root=rollback_root,
        rollback_manifest_path=rollback_manifest,
        rollback_source_fingerprint="ROLLBACK",
    )["ok"] is False

    wrong = json.loads(json.dumps(base))
    wrong["json"]["restore"] = "coord-wrong"
    assert module._validate_rollback_dry_run(
        wrong,
        before=before,
        after=after,
        current_generation="coord-current",
        rollback_generation=rollback_id,
        rollback_root=rollback_root,
        rollback_manifest_path=rollback_manifest,
        rollback_source_fingerprint="ROLLBACK",
    )["ok"] is False


def test_lifecycle_interface_requires_a_real_successful_command_result() -> None:
    module = _module()

    assert module._interface_invoked("xinao-coord doctor") is False
    assert module._interface_invoked({"exit_code": 0, "command": []}) is False
    assert module._interface_invoked(
        {
            "exit_code": 0,
            "command": ["xinao-coord", "doctor"],
            "executable": {"exists": False},
        }
    ) is False
    assert module._interface_invoked(
        {
            "exit_code": 0,
            "command": ["xinao-coord", "doctor"],
            "executable": {"exists": True},
        }
    ) is True
