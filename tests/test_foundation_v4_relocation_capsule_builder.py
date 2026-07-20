from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import xinao.foundation.foundation_v4_relocation_capsule_builder as builder
from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_verifier_registry import validate_authority_snapshot
from xinao.foundation.f4_evidence_snapshot import verify_snapshot_manifest


@dataclass(frozen=True)
class FixtureRoots:
    closure: Path
    snapshot: Path
    request: Path
    authority_manifest: Path
    runtime_buildinfo: Path
    mutable_source: Path


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_canonical(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(value))


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _ref(path: Path, **extra: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": _sha256(raw),
        "size_bytes": len(raw),
        **extra,
    }


def _projection(name: str) -> dict[str, Any]:
    record = {
        "name": name,
        "version": "1.0",
        "requirements": [],
        "file_count": 1,
        "file_tree_sha256": _sha256(name.encode("utf-8")),
    }
    core = {
        "roots": [name],
        "resolver_distribution": {
            **record,
            "name": "packaging",
        },
        "distributions": [record],
    }
    return {**core, "projection_sha256": canonical_sha256(core)}


def _runtime_profile(name: str, ordinal: int) -> dict[str, Any]:
    return {
        "interpreter": {
            "executable_path": rf"C:\sealed-runtime\{name}\python.exe",
            "executable_sha256": f"{ordinal:x}" * 64,
            "executable_size": ordinal,
            "implementation": "CPython",
            "version": "3.12.10",
            "cache_tag": "cpython-312",
        },
        "distribution_projection": _projection(name),
    }


@pytest.mark.parametrize(
    "value",
    (
        r"C:\sealed-runtime\dual-brain\python.exe",
        r"\\runtime-host\sealed-runtime\python.exe",
        "/opt/sealed-runtime/python",
    ),
)
def test_runtime_interpreter_absolute_path_is_host_independent(value: str) -> None:
    assert builder._is_serialized_absolute_path(value)


@pytest.mark.parametrize("value", ("python", "runtime/python", r"C:runtime\python.exe"))
def test_runtime_interpreter_relative_path_is_rejected_on_every_host(value: str) -> None:
    assert not builder._is_serialized_absolute_path(value)


def _reseal_runtime(path: Path, value: dict[str, Any]) -> None:
    core = dict(value)
    core.pop("content_sha256", None)
    _write_canonical(path, {**core, "content_sha256": canonical_sha256(core)})


def _reseal_authority(fixture: FixtureRoots) -> None:
    authority = _load(fixture.authority_manifest)
    runtime_raw = fixture.runtime_buildinfo.read_bytes()
    authority["runtime_buildinfo_ref"] = {
        "relative_path": "runtime_buildinfo.json",
        "sha256": _sha256(runtime_raw),
        "size": len(runtime_raw),
    }
    authority["authority_tree_sha256"] = canonical_sha256(
        {
            "policy_id": authority["policy_id"],
            "source_tree_sha256": authority["source_tree_sha256"],
            "runtime_buildinfo_ref": authority["runtime_buildinfo_ref"],
        }
    )
    core = dict(authority)
    core.pop("content_sha256", None)
    _write_canonical(fixture.authority_manifest, {**core, "content_sha256": canonical_sha256(core)})


def _snapshot_manifest(
    payload: Path,
    *,
    request: Path,
    authority_manifest: Path,
) -> dict[str, Any]:
    inventory: list[dict[str, Any]] = []
    file_refs: list[dict[str, Any]] = []
    for logical_id, source in (
        ("closure_authority_manifest", authority_manifest),
        ("closure_f4_request", request),
    ):
        destination = payload.parent / "files" / logical_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        raw = destination.read_bytes()
        inventory.append(
            {
                "relative_path": destination.relative_to(payload.parent).as_posix(),
                "sha256": _sha256(raw),
                "size_bytes": len(raw),
            }
        )
        file_refs.append(
            {
                "logical_ref": f"file/{logical_id}",
                "sha256": _sha256(raw),
                "size_bytes": len(raw),
            }
        )
    payload_raw = payload.read_bytes()
    inventory.append(
        {
            "relative_path": payload.name,
            "sha256": _sha256(payload_raw),
            "size_bytes": len(payload_raw),
        }
    )
    inventory.sort(key=lambda row: row["relative_path"])
    roots = [
        {"root_id": name}
        for name in (
            "closure_f4_artifacts",
            "closure_inputs",
            "current_source",
            "independent_support",
            "live_pack",
            "negative_pack",
            "portfolio_pack",
        )
    ]
    logical_refs = [{"logical_ref": f"root/{row['root_id']}"} for row in roots] + file_refs
    core = {
        "schema_version": "xinao.evidence_snapshot.v1",
        "logical_roots": roots,
        "logical_root_count": len(roots),
        "logical_refs": logical_refs,
        "logical_ref_count": len(logical_refs),
        "reference_edge_count": 0,
        "required_reference_match_count": 14,
        "reachable_logical_ref_count": len(logical_refs),
        "full_archival_logical_ref_count": len(logical_refs),
        "cas_object_count": 1,
        "unresolved_metadata_ref_count": 2,
        "unresolved_metadata_refs": [
            {
                "source_ref": "root/current_source/state.json",
                "json_pointer": "/last_decision/frontier_ref",
                "recorded_value": "fixture-invalid-frontier",
                "reason": "invalid_local_identity",
            },
            {
                "source_ref": "root/current_source/state.json",
                "json_pointer": "/last_state_ref",
                "recorded_value": "D:/missing-fixture-state.json",
                "reason": "missing_local_target",
            },
        ],
        "inventory_count": len(inventory),
        "inventory": inventory,
        "inventory_sha256": canonical_sha256(inventory),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def _make_fixture(root: Path) -> FixtureRoots:
    closure = root / "closure"
    snapshot = root / "snapshot"
    closure.mkdir(parents=True)
    snapshot.mkdir()

    actuals_relative = Path(
        "xinao_discovery/src/xinao/foundation/assertion_verifiers/f4_assertion_actuals.py"
    )
    actuals = closure / "authority_snapshot" / "sources" / actuals_relative
    actuals.parent.mkdir(parents=True)
    actuals.write_bytes(b"def build_assertion_actuals_v1(request):\n    return {}\n")
    actuals_raw = actuals.read_bytes()
    actuals_sha256 = _sha256(actuals_raw)

    runtime_buildinfo = closure / "authority_snapshot" / "runtime_buildinfo.json"
    runtime_core = {
        "schema_version": "xinao.foundation_runtime_buildinfo.v1",
        "runtimes": {
            "f4_dual_brain_runtime": _runtime_profile("dual-brain", 1),
            "xinao_assertion_runtime": _runtime_profile("assertion", 2),
        },
    }
    _write_canonical(
        runtime_buildinfo,
        {**runtime_core, "content_sha256": canonical_sha256(runtime_core)},
    )
    runtime_raw = runtime_buildinfo.read_bytes()
    authority_entries = [
        {
            "role": f"source:{actuals_relative.as_posix()}",
            "relative_path": actuals_relative.as_posix(),
            "sha256": actuals_sha256,
            "size": len(actuals_raw),
        }
    ]
    authority_core = {
        "schema_version": "xinao.compiler_code_manifest.v3",
        "policy_id": "xinao.foundation_authority_seal.v1",
        "registry": {
            "F4_research_factory": {
                "module_name": "xinao.foundation.assertion_verifiers.f4_assertion_actuals",
                "relative_source": "xinao/foundation/assertion_verifiers/f4_assertion_actuals.py",
                "checker_version": "xinao.foundation.assertion_actuals.f4.v1",
                "source_sha256": actuals_sha256,
                "checker_id": f"xinao.canonical.F4_research_factory.{actuals_sha256}",
            }
        },
        "entries": authority_entries,
        "source_tree_sha256": canonical_sha256(authority_entries),
        "runtime_buildinfo_ref": {
            "relative_path": "runtime_buildinfo.json",
            "sha256": _sha256(runtime_raw),
            "size": len(runtime_raw),
        },
    }
    authority_core["authority_tree_sha256"] = canonical_sha256(
        {
            "policy_id": authority_core["policy_id"],
            "source_tree_sha256": authority_core["source_tree_sha256"],
            "runtime_buildinfo_ref": authority_core["runtime_buildinfo_ref"],
        }
    )
    authority_manifest = closure / "authority_snapshot" / "authority_manifest.json"
    _write_canonical(
        authority_manifest,
        {**authority_core, "content_sha256": canonical_sha256(authority_core)},
    )

    input_root = closure / "source_materials" / "inputs"
    input_root.mkdir(parents=True)
    input_refs: dict[str, dict[str, Any]] = {}
    mutable_source = input_root / "active_quote_projection_sha256.fixture.json"
    for index, name in enumerate(builder.F4_INPUT_NAMES):
        if name == "compiler_code_sha256":
            input_refs[name] = {
                **_ref(authority_manifest),
                "input_hash_key": name,
            }
            continue
        suffix = ".csv" if name == "baseline_sha256" else ".json"
        path = (
            mutable_source
            if name == "active_quote_projection_sha256"
            else input_root / f"{name}.fixture{suffix}"
        )
        path.write_bytes(f"fixture-input-{index}-{name}\n".encode("utf-8"))
        input_refs[name] = {**_ref(path), "input_hash_key": name}
    input_hashes = {name: row["sha256"] for name, row in input_refs.items()}
    code_hash = input_hashes["compiler_code_sha256"]
    config_hash = input_hashes["compiler_config_sha256"]

    artifacts: dict[str, dict[str, Any]] = {}
    artifact_root = closure / "source_materials" / "artifacts" / builder.F4_BLOCK_ID
    artifact_root.mkdir(parents=True)
    for index, artifact_type in enumerate(builder.F4_ARTIFACT_NAMES):
        source = artifact_root / f"{artifact_type}.fixture.json"
        payload = {"artifact_type": artifact_type, "ordinal": index}
        _write_canonical(source, payload)
        envelope = {
            "artifact_type": artifact_type,
            "version": f"{artifact_type}@fixture-v1",
            "input_hashes": input_hashes,
            "code_hash": code_hash,
            "config_hash": config_hash,
            "source_ref": _ref(source, artifact_type=artifact_type),
            "payload": payload,
            "payload_sha256": canonical_sha256(payload),
        }
        artifacts[artifact_type] = {
            "staged_envelope": envelope,
            "staged_envelope_content_sha256": canonical_sha256(envelope),
        }

    request_value = {
        "schema_version": "xinao.assertion_request.v2",
        "protocol_version": "xinao.assertion_bundle_protocol.v2",
        "block_id": builder.F4_BLOCK_ID,
        "assertion_ids": list(builder.F4_ASSERTION_IDS),
        "input_evidence": input_refs,
        "input_hashes": input_hashes,
        "artifacts": artifacts,
        "compiler_code_sha256": code_hash,
        "compiler_config_sha256": config_hash,
    }
    request = closure / "assertion_requests" / f"{builder.F4_BLOCK_ID}.json"
    _write_canonical(request, request_value)

    blueprint = closure / "fixture_inputs" / "blueprint.json"
    _write_canonical(blueprint, {"fixture": "blueprint"})
    blueprint_ref = _ref(blueprint)
    report_input = {
        "created_at": "2026-07-15T08:25:00+08:00",
        "blueprint_ref": blueprint_ref,
        "input_hashes": input_hashes,
        "code_hash": code_hash,
        "config_hash": config_hash,
    }
    _write_canonical(closure / "foundation_closure_report_input.json", report_input)
    pack_core = {
        "schema_version": "xinao.foundation_closure_pack.v4",
        "blueprint_ref": blueprint_ref,
        "authority_snapshot_manifest_ref": _ref(authority_manifest),
        "compiler_code_manifest_ref": _ref(authority_manifest),
        "source_materials_self_contained": True,
        "foundation_closed": True,
    }
    _write_canonical(
        closure / "foundation_closure_pack.json",
        {**pack_core, "pack_sha256": canonical_sha256(pack_core)},
    )

    snapshot_payload = snapshot / "payload.json"
    _write_canonical(snapshot_payload, {"fixture": "snapshot"})
    _write_canonical(
        snapshot / "snapshot_manifest.json",
        _snapshot_manifest(
            snapshot_payload,
            request=request,
            authority_manifest=authority_manifest,
        ),
    )
    return FixtureRoots(
        closure=closure,
        snapshot=snapshot,
        request=request,
        authority_manifest=authority_manifest,
        runtime_buildinfo=runtime_buildinfo,
        mutable_source=mutable_source,
    )


@pytest.fixture()
def fixture_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FixtureRoots:
    roots = _make_fixture(tmp_path / "fixture")

    def fake_authority(path: Path, *, require_live_match: bool) -> dict[str, Any]:
        assert require_live_match is False
        return _load(path)

    monkeypatch.setattr(builder, "validate_authority_snapshot", fake_authority)
    monkeypatch.setattr(builder, "verify_snapshot_manifest", _load)
    monkeypatch.setattr(
        builder,
        "_run_common_preflight",
        lambda *, pack_root, block_id: {
            "status": "VERIFIED",
            "pack_root": str(pack_root),
            "block_id": block_id,
        },
    )
    return roots


def _tree_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    )


def test_builder_never_reads_old_capsule_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_roots: FixtureRoots,
) -> None:
    poison = tmp_path / "historical-capsule" / "capsule_manifest.json"
    poison.parent.mkdir()
    poison.write_bytes(b"POISON-OLD-CAPSULE-MUST-NOT-BE-READ")
    opened: list[Path] = []
    original_open = Path.open

    def tracked_open(self: Path, *args: Any, **kwargs: Any):
        if os.path.normcase(os.path.abspath(self)) == os.path.normcase(os.path.abspath(poison)):
            opened.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    result = builder.build_foundation_v4_relocation_source_capsule(
        closure_root=fixture_roots.closure,
        snapshot_root=fixture_roots.snapshot,
        output_root=tmp_path / "output",
        operation_id="no-old-manifest",
    )

    assert result.capsule_manifest_path.is_file()
    assert opened == []


def test_builder_derives_exact_f4_transport_inventory(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    result = builder.build_foundation_v4_relocation_source_capsule(
        closure_root=fixture_roots.closure,
        snapshot_root=fixture_roots.snapshot,
        output_root=tmp_path / "output",
        operation_id="exact-transport",
    )
    manifest = _load(result.capsule_manifest_path)
    bindings = manifest["reference_bindings"]

    assert manifest["request"]["assertion_ids"] == list(builder.F4_ASSERTION_IDS)
    assert manifest["request"]["input_reference_count"] == 10
    assert manifest["request"]["artifact_reference_count"] == 8
    assert [row["kind"] for row in bindings] == ["input"] * len(builder.F4_INPUT_NAMES) + [
        "artifact"
    ] * len(builder.F4_ARTIFACT_NAMES) + ["blueprint"]
    assert len(bindings) == len(builder.F4_INPUT_NAMES) + len(builder.F4_ARTIFACT_NAMES) + 1
    assert result.build_receipt_path.parent == result.output_root
    assert not result.build_receipt_path.is_relative_to(result.foundation_root)
    rows = manifest["payload"]["files"]
    assert rows == sorted(rows, key=lambda row: row["relative_path"])


def test_builder_rejects_same_bytes_outside_closure_namespaces(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    request = _load(fixture_roots.request)
    name = "active_quote_projection_sha256"
    outside = tmp_path / "same-bytes-outside.json"
    shutil.copyfile(fixture_roots.mutable_source, outside)
    request["input_evidence"][name]["path"] = str(outside)
    _write_canonical(fixture_roots.request, request)

    with pytest.raises(builder.RelocationCapsuleBuildError, match="closure input namespace"):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=tmp_path / "output",
            operation_id="outside-ref",
        )
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("case", ("authority", "runtime-profile"))
def test_builder_rejects_authority_or_runtime_profile_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_roots: FixtureRoots,
    case: str,
) -> None:
    if case == "authority":

        def reject_authority(path: Path, *, require_live_match: bool) -> dict[str, Any]:
            del path, require_live_match
            raise ValueError("authority drift canary")

        monkeypatch.setattr(builder, "validate_authority_snapshot", reject_authority)
        match = "authority drift canary"
    else:
        runtime = _load(fixture_roots.runtime_buildinfo)
        runtime["runtimes"]["xinao_assertion_runtime"]["distribution_projection"] = runtime[
            "runtimes"
        ]["f4_dual_brain_runtime"]["distribution_projection"]
        _reseal_runtime(fixture_roots.runtime_buildinfo, runtime)
        _reseal_authority(fixture_roots)
        match = "runtime dependency profiles collapsed"

    with pytest.raises(builder.RelocationCapsuleBuildError, match=match):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=tmp_path / f"output-{case}",
            operation_id=f"drift-{case}",
        )


@pytest.mark.parametrize("case", ("validator", "projection"))
def test_builder_reuses_snapshot_validator_and_f4_projection_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_roots: FixtureRoots,
    case: str,
) -> None:
    if case == "validator":

        def reject_snapshot(path: Path) -> dict[str, Any]:
            del path
            raise ValueError("snapshot tamper canary")

        monkeypatch.setattr(builder, "verify_snapshot_manifest", reject_snapshot)
        match = "snapshot tamper canary"
    else:
        manifest_path = fixture_roots.snapshot / "snapshot_manifest.json"
        manifest = _load(manifest_path)
        manifest["required_reference_match_count"] = 13
        core = dict(manifest)
        core.pop("content_sha256", None)
        _write_canonical(manifest_path, {**core, "content_sha256": canonical_sha256(core)})
        match = "required reference match count"

    with pytest.raises(builder.RelocationCapsuleBuildError, match=match):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=tmp_path / f"output-{case}",
            operation_id=f"snapshot-{case}",
        )


def test_builder_rejects_snapshot_bound_to_another_closure_request(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    manifest_path = fixture_roots.snapshot / "snapshot_manifest.json"
    manifest = _load(manifest_path)
    request_ref = next(
        row
        for row in manifest["logical_refs"]
        if row.get("logical_ref") == "file/closure_f4_request"
    )
    request_ref["sha256"] = "f" * 64
    core = dict(manifest)
    core.pop("content_sha256", None)
    _write_canonical(manifest_path, {**core, "content_sha256": canonical_sha256(core)})

    with pytest.raises(
        builder.RelocationCapsuleBuildError,
        match="differs from admitted closure identity",
    ):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=tmp_path / "output-mismatched-closure",
            operation_id="mismatched-closure",
        )


def test_builder_rejects_unsafe_or_reserved_destination_topology(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    manifest_path = fixture_roots.snapshot / "snapshot_manifest.json"
    manifest = _load(manifest_path)
    unsafe = fixture_roots.snapshot / "__pycache__" / "poison.pyc"
    unsafe.parent.mkdir()
    unsafe.write_bytes(b"unsafe-bytecode")
    manifest["inventory"].append(
        {
            "relative_path": "__pycache__/poison.pyc",
            "sha256": _sha256(unsafe.read_bytes()),
            "size_bytes": unsafe.stat().st_size,
        }
    )
    manifest["inventory"] = sorted(manifest["inventory"], key=lambda row: row["relative_path"])
    manifest["inventory_count"] = len(manifest["inventory"])
    manifest["inventory_sha256"] = canonical_sha256(manifest["inventory"])
    core = dict(manifest)
    core.pop("content_sha256", None)
    _write_canonical(manifest_path, {**core, "content_sha256": canonical_sha256(core)})

    with pytest.raises(builder.RelocationCapsuleBuildError, match="cache|bytecode"):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=tmp_path / "output",
            operation_id="unsafe-topology",
        )
    assert not (tmp_path / "output").exists()


def test_builder_detects_source_drift_during_copy_and_cleans_only_owned_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_roots: FixtureRoots,
) -> None:
    original_copyfile = builder.shutil.copyfile
    mutated = False

    def mutate_after_copy(source: Any, destination: Any, *args: Any, **kwargs: Any):
        nonlocal mutated
        result = original_copyfile(source, destination, *args, **kwargs)
        if not mutated and Path(source) == fixture_roots.mutable_source:
            fixture_roots.mutable_source.write_bytes(b"source-drift-after-copy")
            mutated = True
        return result

    monkeypatch.setattr(builder.shutil, "copyfile", mutate_after_copy)
    output = tmp_path / "output"
    with pytest.raises(builder.RelocationCapsuleBuildError, match="source drifted during copy"):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=output,
            operation_id="source-drift",
        )

    assert mutated is True
    assert not output.exists()
    assert not any("source-drift" in path.name for path in tmp_path.iterdir())


def test_builder_refuses_existing_output_and_preserves_canary(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    canary = output / "canary.bin"
    canary.write_bytes(b"existing-output-must-remain")

    with pytest.raises(builder.RelocationCapsuleBuildError, match="output root already exists"):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=output,
            operation_id="existing-output",
        )
    assert canary.read_bytes() == b"existing-output-must-remain"
    assert [path.name for path in output.iterdir()] == ["canary.bin"]


def test_builder_rejects_output_inside_a_sealed_input(
    fixture_roots: FixtureRoots,
) -> None:
    output = fixture_roots.closure / "forbidden-output"
    with pytest.raises(builder.RelocationCapsuleBuildError, match="overlaps a sealed input"):
        builder.build_foundation_v4_relocation_source_capsule(
            closure_root=fixture_roots.closure,
            snapshot_root=fixture_roots.snapshot,
            output_root=output,
            operation_id="input-overlap",
        )
    assert not output.exists()


def test_two_builds_from_identical_inputs_have_identical_foundation_trees(
    tmp_path: Path,
    fixture_roots: FixtureRoots,
) -> None:
    first = builder.build_foundation_v4_relocation_source_capsule(
        closure_root=fixture_roots.closure,
        snapshot_root=fixture_roots.snapshot,
        output_root=tmp_path / "first",
        operation_id="determinism-a",
    )
    second = builder.build_foundation_v4_relocation_source_capsule(
        closure_root=fixture_roots.closure,
        snapshot_root=fixture_roots.snapshot,
        output_root=tmp_path / "second",
        operation_id="determinism-b",
    )

    assert _tree_bytes(first.foundation_root) == _tree_bytes(second.foundation_root)
    assert first.capsule_manifest_sha256 == second.capsule_manifest_sha256
    assert first.payload_exact_inventory_sha256 == second.payload_exact_inventory_sha256
    assert first.build_receipt_path.read_bytes() != second.build_receipt_path.read_bytes()


def test_real_fresh_closure_and_snapshot_pass_public_validators(tmp_path: Path) -> None:
    closure_raw = os.environ.get("XINAO_F4_CLOSURE_ROOT")
    snapshot_raw = os.environ.get("XINAO_F4_SNAPSHOT_ROOT")
    if not closure_raw or not snapshot_raw:
        pytest.skip("set XINAO_F4_CLOSURE_ROOT and XINAO_F4_SNAPSHOT_ROOT")
    output = tmp_path / "real-f4-source-capsule"
    result = builder.build_foundation_v4_relocation_source_capsule(
        closure_root=Path(closure_raw),
        snapshot_root=Path(snapshot_raw),
        output_root=output,
        operation_id="real-fresh-integration",
    )

    authority = validate_authority_snapshot(
        result.foundation_root / "authority_snapshot" / "authority_manifest.json",
        require_live_match=False,
    )
    snapshot = verify_snapshot_manifest(
        result.foundation_root / "f4_snapshot" / "snapshot_manifest.json"
    )
    preflight = builder._run_common_preflight(
        pack_root=result.output_root,
        block_id=builder.F4_BLOCK_ID,
    )
    manifest = _load(result.capsule_manifest_path)

    assert authority["schema_version"] == "xinao.compiler_code_manifest.v3"
    assert snapshot["schema_version"] == "xinao.evidence_snapshot.v1"
    assert preflight["status"] == "VERIFIED"
    assert len(manifest["reference_bindings"]) == (
        len(builder.F4_INPUT_NAMES) + len(builder.F4_ARTIFACT_NAMES) + 1
    )
    assert manifest["static_runtime_audit"]["old_capsule_manifest_read_count"] == 0
