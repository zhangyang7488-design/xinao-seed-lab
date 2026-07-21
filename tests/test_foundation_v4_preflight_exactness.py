from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import xinao.foundation.foundation_v4_replay_runtime as replay_runtime

F1_BLOCK_ID = "F1_settlement_world"
CAPSULE_BLOCK_IDS = (
    F1_BLOCK_ID,
    "F2_issuer_settlement_cost_space",
    "F3_research_weight",
)
ADAPTERS = ("public", "execution")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _path_key(path: os.PathLike[str] | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _payload_row(relative_path: str, raw: bytes) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "size_bytes": len(raw),
        "sha256": _sha256_bytes(raw),
    }


def _copy_capsule(tmp_path: Path, block_id: str, *, name: str = "pack") -> Path:
    """Build a minimal sealed capsule without depending on machine-local evidence."""

    spec = replay_runtime._replay_block_spec(block_id)
    pack = tmp_path / name
    foundation = pack / "foundation"

    request_relative = f"assertion_requests/{block_id}.json"
    request_raw = _json_bytes(
        {
            "block_id": block_id,
            "assertion_ids": list(spec.assertion_ids),
            "input_evidence": {key: {} for key in spec.input_names},
            "input_hashes": {key: "0" * 64 for key in spec.input_names},
            "artifacts": {key: {} for key in spec.artifact_names},
        }
    )
    blueprint_relative = spec.execution_excluded_payload_paths[0]
    blueprint_raw = _json_bytes(
        {
            "schema": "test.blueprint.v1",
            "block_id": block_id,
            "purpose": "sealed execution-exclusion canary",
        }
    )
    runtime_relative = "runtime_buildinfo.json"
    runtime_raw = _json_bytes({"schema_version": "test.runtime_buildinfo.v1"})
    authority_relative = "authority_snapshot/authority_manifest.json"
    authority_raw = _json_bytes(
        {
            "schema_version": "xinao.compiler_code_manifest.v3",
            "entries": [],
            "runtime_buildinfo_ref": {
                "relative_path": runtime_relative,
                "size": len(runtime_raw),
                "sha256": _sha256_bytes(runtime_raw),
            },
        }
    )

    # Deliberately retain a non-sorted manifest order so the order-binding
    # regression remains observable without copying multi-megabyte D: evidence.
    payloads = (
        (request_relative, request_raw),
        (blueprint_relative, blueprint_raw),
        (authority_relative, authority_raw),
        (f"authority_snapshot/{runtime_relative}", runtime_raw),
    )
    rows = [_payload_row(relative, raw) for relative, raw in payloads]
    for relative, raw in payloads:
        destination = foundation / Path(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    manifest = {
        "schema_version": spec.capsule_schema_version,
        "block_id": block_id,
        "request": {
            "block_id": block_id,
            "relative_path": request_relative,
            "size_bytes": len(request_raw),
            "sha256": _sha256_bytes(request_raw),
            "assertion_count": len(spec.assertion_ids),
        },
        "payload": {
            "files": rows,
            "exact_inventory_sha256": _inventory_sha256(rows),
            "total_size_bytes": sum(len(raw) for _, raw in payloads),
        },
    }
    _write_manifest(pack, manifest)
    return pack


def _load_manifest(pack: Path) -> dict[str, object]:
    return json.loads((pack / "foundation" / "capsule_manifest.json").read_text(encoding="utf-8"))


def _write_manifest(pack: Path, manifest: dict[str, object]) -> None:
    (pack / "foundation" / "capsule_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _inventory_sha256(rows: list[dict[str, object]]) -> str:
    raw = "\n".join(
        f"{row['relative_path']}\t{row['size_bytes']}\t{row['sha256']}" for row in rows
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _call_adapter(adapter: str, *, pack: Path, block_id: str = F1_BLOCK_ID):
    if adapter == "public":
        return replay_runtime.preflight_relocated_foundation_v4(
            pack_root=pack,
            block_id=block_id,
        )
    if adapter == "execution":
        return replay_runtime._execution_preflight(
            pack_root=pack,
            spec=replay_runtime._replay_block_spec(block_id),
        )
    raise AssertionError(f"unknown test adapter: {adapter}")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_common_preflight_rejects_undeclared_regular_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: str,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    undeclared = pack / "foundation" / "UNDECLARED_PREFLIGHT_CANARY.bin"
    undeclared.write_bytes(b"undeclared-preflight-canary")
    output = tmp_path / "output-must-not-exist"
    authority_marker = tmp_path / "authority-import-must-not-happen.marker"
    original_read_json = replay_runtime._read_json_object

    def tracked_read_json(path: Path, *, label: str):
        if label == "authority manifest":
            authority_marker.write_text("authority reached", encoding="utf-8")
        return original_read_json(path, label=label)

    monkeypatch.setattr(replay_runtime, "_read_json_object", tracked_read_json)
    with pytest.raises(
        replay_runtime.FoundationV4ReplayError,
        match="payload tree is not exact",
    ):
        _call_adapter(adapter, pack=pack)
    assert not output.exists()
    assert not authority_marker.exists()


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("relative_path", "message"),
    (
        (Path("assertions/__pycache__/canary.cpython-312.pyc"), "cache directory"),
        (Path("assertions/canary.pyc"), "bytecode"),
        (Path("assertions/canary.pyo"), "bytecode"),
    ),
    ids=("pycache", "pyc", "pyo"),
)
def test_common_preflight_rejects_cache_or_bytecode(
    tmp_path: Path,
    adapter: str,
    relative_path: Path,
    message: str,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    dangerous = pack / "foundation" / relative_path
    dangerous.parent.mkdir(parents=True, exist_ok=True)
    dangerous.write_bytes(b"quarantine-cannot-hide-bytecode")

    with pytest.raises(replay_runtime.FoundationV4ReplayError, match=message):
        _call_adapter(adapter, pack=pack)


def test_nonfollowing_scan_rejects_reparse_flag_before_target_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foundation = tmp_path / "foundation"
    foundation.mkdir()
    calls = {"stat": 0, "target_read": 0}

    class FakeReparseEntry:
        name = "junction-canary"
        path = os.fspath(foundation / name)

        @staticmethod
        def stat(*, follow_symlinks: bool):
            assert follow_symlinks is False
            calls["stat"] += 1
            return SimpleNamespace(st_file_attributes=0x400)

        @staticmethod
        def is_symlink() -> bool:
            return False

        @staticmethod
        def is_dir(*, follow_symlinks: bool) -> bool:
            del follow_symlinks
            calls["target_read"] += 1
            pytest.fail("the reparse target shape must not be read")

        @staticmethod
        def is_file(*, follow_symlinks: bool) -> bool:
            del follow_symlinks
            calls["target_read"] += 1
            pytest.fail("the reparse target shape must not be read")

    def fake_scandir(path: os.PathLike[str] | str):
        assert _path_key(path) == _path_key(foundation)
        return [FakeReparseEntry()]

    monkeypatch.setattr(replay_runtime.os, "scandir", fake_scandir)
    with pytest.raises(replay_runtime.FoundationV4ReplayError, match="reparse entry"):
        replay_runtime._scan_payload_tree_nonfollowing(foundation=foundation)
    assert calls == {"stat": 1, "target_read": 0}


def _tree_inventory(root: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.stat().st_size, _sha256_file(path))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction integration")
@pytest.mark.parametrize("adapter", ADAPTERS)
def test_windows_junction_is_rejected_without_target_read(
    tmp_path: Path,
    adapter: str,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    outside = tmp_path / "outside-target"
    outside.mkdir()
    canary = outside / "target-canary.bin"
    canary.write_bytes(b"outside-junction-target-must-remain-untouched")
    before = _tree_inventory(outside)
    before_canary_sha256 = _sha256_file(canary)

    quarantine = pack / "foundation" / "assertions"
    quarantine.mkdir()
    junction = quarantine / "junction-canary"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=creation_flags,
    )
    if created.returncode != 0 or not os.path.lexists(junction):
        pytest.skip(
            "junction creation unavailable: "
            f"returncode={created.returncode}, stderr={created.stderr.strip()}"
        )

    try:
        with pytest.raises(replay_runtime.FoundationV4ReplayError, match="reparse entry"):
            _call_adapter(adapter, pack=pack)
        assert _sha256_file(canary) == before_canary_sha256
        assert _tree_inventory(outside) == before
    finally:
        os.rmdir(junction)
    assert not os.path.lexists(junction)


def test_execution_preflight_rejects_payload_total_size_drift(tmp_path: Path) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    manifest = _load_manifest(pack)
    payload = manifest["payload"]
    assert isinstance(payload, dict)
    payload["total_size_bytes"] += 1
    _write_manifest(pack, manifest)

    with pytest.raises(
        replay_runtime.FoundationV4ReplayError,
        match=r"^relocated payload total size drift$",
    ):
        _call_adapter("execution", pack=pack)


def test_execution_preflight_rejects_request_row_binding_drift_before_second_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    manifest = _load_manifest(pack)
    request_ref = manifest["request"]
    assert isinstance(request_ref, dict)
    request_relative = request_ref["relative_path"]
    assert isinstance(request_relative, str)
    request_path = pack / "foundation" / Path(*request_relative.split("/"))
    request_ref["size_bytes"] += 1
    _write_manifest(pack, manifest)

    original_verify = replay_runtime._verify_file_identity
    request_reads = 0

    def tracked_verify(path: Path, **kwargs: object) -> bytes:
        nonlocal request_reads
        if _path_key(path) == _path_key(request_path):
            request_reads += 1
        return original_verify(path, **kwargs)

    monkeypatch.setattr(replay_runtime, "_verify_file_identity", tracked_verify)
    with pytest.raises(
        replay_runtime.FoundationV4ReplayError,
        match=r"^relocated request manifest binding drifted$",
    ):
        _call_adapter("execution", pack=pack)
    assert request_reads == 1


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_common_preflight_never_reads_ordinary_legacy_quarantine_poison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: str,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    poison_files = (
        pack / "foundation" / "assertions" / "ordinary-poison.json",
        pack / "foundation" / "foundation_closure_report.json",
    )
    poison_files[0].parent.mkdir()
    poison_files[0].write_bytes(b"ordinary legacy directory poison")
    poison_files[1].write_bytes(b"ordinary legacy file poison")
    expected = {path: path.read_bytes() for path in poison_files}
    poison_keys = {_path_key(path) for path in poison_files}
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if _path_key(path) in poison_keys:
            pytest.fail("ordinary legacy quarantine poison must remain unread")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    assert _call_adapter(adapter, pack=pack)
    for path, raw in expected.items():
        assert original_read_bytes(path) == raw


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_manifest_payload_collision_with_legacy_quarantine_is_rejected(
    tmp_path: Path,
    adapter: str,
) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    declared = pack / "foundation" / "artifacts" / "declared.json"
    declared.parent.mkdir()
    raw = b'{"declared":true}\n'
    declared.write_bytes(raw)

    manifest = _load_manifest(pack)
    payload = manifest["payload"]
    assert isinstance(payload, dict)
    rows = payload["files"]
    assert isinstance(rows, list)
    rows.append(
        {
            "relative_path": "artifacts/declared.json",
            "size_bytes": len(raw),
            "sha256": _sha256_bytes(raw),
        }
    )
    payload["total_size_bytes"] += len(raw)
    payload["exact_inventory_sha256"] = _inventory_sha256(rows)
    _write_manifest(pack, manifest)

    with pytest.raises(
        replay_runtime.FoundationV4ReplayError,
        match="collides with reserved quarantine namespace",
    ):
        _call_adapter(adapter, pack=pack)


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_v1_inventory_uses_existing_manifest_order(tmp_path: Path, adapter: str) -> None:
    pack = _copy_capsule(tmp_path, F1_BLOCK_ID)
    manifest = _load_manifest(pack)
    payload = manifest["payload"]
    assert isinstance(payload, dict)
    rows = payload["files"]
    assert isinstance(rows, list)
    relative_paths = [row["relative_path"] for row in rows]
    assert relative_paths != sorted(relative_paths)
    assert relative_paths[:2] == [
        f"assertion_requests/{F1_BLOCK_ID}.json",
        "blueprint/blueprint.v1_已合并工具与执行纪律.json",
    ]
    manifest_order_sha256 = _inventory_sha256(rows)
    assert payload["exact_inventory_sha256"] == manifest_order_sha256
    sorted_rows = sorted(rows, key=lambda row: row["relative_path"])
    sorted_order_sha256 = _inventory_sha256(sorted_rows)
    assert manifest_order_sha256 != sorted_order_sha256

    assert _call_adapter(adapter, pack=pack)
    rows[0], rows[1] = rows[1], rows[0]
    _write_manifest(pack, manifest)
    with pytest.raises(replay_runtime.FoundationV4ReplayError, match="inventory SHA drift"):
        _call_adapter(adapter, pack=pack)


@pytest.mark.parametrize("block_id", CAPSULE_BLOCK_IDS)
def test_execution_preflight_does_not_read_excluded_blueprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_id: str,
) -> None:
    spec = replay_runtime._replay_block_spec(block_id)
    assert len(spec.execution_excluded_payload_paths) == 1
    excluded_relative = spec.execution_excluded_payload_paths[0]

    execution_pack = _copy_capsule(tmp_path, block_id, name="execution-pack")
    execution_blueprint = execution_pack / "foundation" / Path(*excluded_relative.split("/"))
    original = execution_blueprint.read_bytes()
    assert original
    poisoned = bytes((original[0] ^ 1,)) + original[1:]
    assert len(poisoned) == len(original)
    assert _sha256_bytes(poisoned) != _sha256_bytes(original)
    execution_blueprint.write_bytes(poisoned)

    original_read_bytes = Path.read_bytes
    excluded_key = _path_key(execution_blueprint)

    def guarded_read_bytes(path: Path) -> bytes:
        if _path_key(path) == excluded_key:
            pytest.fail("execution preflight must not read the excluded blueprint")
        return original_read_bytes(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guarded_read_bytes)
        capsule, request, request_raw = _call_adapter(
            "execution",
            pack=execution_pack,
            block_id=block_id,
        )
    capsule_block_id = capsule.get("block_id")
    if capsule_block_id is None:
        capsule_request = capsule["request"]
        assert isinstance(capsule_request, dict)
        capsule_block_id = capsule_request["block_id"]
    assert capsule_block_id == block_id
    assert request["block_id"] == block_id
    assert request_raw

    public_pack = _copy_capsule(tmp_path, block_id, name="public-pack")
    public_blueprint = public_pack / "foundation" / Path(*excluded_relative.split("/"))
    public_blueprint.write_bytes(poisoned)
    with pytest.raises(replay_runtime.FoundationV4ReplayError, match="source SHA drift"):
        _call_adapter("public", pack=public_pack, block_id=block_id)
