from __future__ import annotations

import copy
from pathlib import Path

import pytest
from services.xinao_perpetual_world_compute.runtime_binding import (
    WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA,
    WORLD_RUNTIME_BINDING_SCHEMA,
    WorldRuntimeBindingError,
    build_world_runtime_binding,
    build_world_runtime_binding_applied_receipt,
    canonical_json_bytes,
    environment_projection,
    expected_applied_receipt_path,
    expected_codex_args_path,
    expected_runtime_binding_path,
    sha256_bytes,
    sha256_file,
    validate_world_runtime_binding,
    validate_world_runtime_binding_applied_receipt,
    validate_world_runtime_binding_bytes,
    world_runtime_binding_bytes,
    world_runtime_binding_file_sha256,
)


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path.resolve()


def _reseal(value: dict[str, object], field: str) -> dict[str, object]:
    result = copy.deepcopy(value)
    result.pop(field, None)
    result[field] = sha256_bytes(canonical_json_bytes(result))
    return result


def _material(
    tmp_path: Path,
    *,
    lineage_id: str = "world-01",
    role: str = "independent_world",
    owner_lineage_id: str | None = None,
    private_live_root: Path | None = None,
    live_seed_scope: str = "compute",
) -> dict[str, object]:
    run_id = "run-001"
    run_dir = tmp_path / "control" / "runs" / run_id
    workspace = tmp_path / "research-lineages" / run_id / lineage_id
    effective_code_root = tmp_path / "world-compute" / "effective" / run_id / lineage_id
    effective_python_path = effective_code_root / "code"
    private_live = private_live_root or workspace / ".xinao-world-runtime" / "live-reality"
    for directory in (run_dir, workspace, effective_python_path, private_live):
        directory.mkdir(parents=True, exist_ok=True)

    launcher = _write(run_dir / "controller-releases" / "world-isolated.ps1", b"launcher-v1\n")
    controller = _write(run_dir / "controller-releases" / "controller.py", b"controller-v1\n")
    controller_python = _write(run_dir / "controller-releases" / "python.exe", b"python-v1\n")
    runtime_binding_release = _write(
        run_dir / "controller-releases" / "runtime_binding.py", b"binding-validator-v1\n"
    )
    base = _write(
        tmp_path / "world-compute" / "base" / "BASE_MANIFEST.json",
        canonical_json_bytes({"schema": "xinao.base-code-bundle.v1"}),
    )
    effective_entries: list[dict[str, object]] = []
    effective_tree_sha = sha256_bytes(b"")
    effective = _write(
        effective_code_root.parent / f"{lineage_id}-EFFECTIVE_MANIFEST.json",
        canonical_json_bytes(
            {
                "schema": "xinao.lineage-effective-code.v1",
                "payload_tree_sha256": effective_tree_sha,
                "legacy_namespace": "xinao",
                "base_fallback_permitted": False,
                "entries": effective_entries,
            }
        ),
    )
    world_compute_root = (tmp_path / "world-compute").resolve()
    live_seed_parent = {
        "compute": world_compute_root / "private-live-initialization" / run_id / lineage_id,
        "outside": tmp_path / "outside-world-compute" / run_id / lineage_id,
        "workspace": workspace / ".xinao-world-runtime" / "initialization",
    }[live_seed_scope]
    live_seed = _write(
        live_seed_parent / "PRIVATE_LIVE_INITIALIZATION_RECEIPT.json",
        b'{"schema":"live-seed"}\n',
    )
    owner = owner_lineage_id or lineage_id
    migration_payload = {
        "schema": "xinao.reality-live-copy-first-migration.v1",
        "migration_id": "migration-001",
        "source_deletion_permitted": False,
        "live_reality_root_runtime_bindable": False,
        "world_compute_root": str(world_compute_root),
        "base_bundle": {
            "manifest_path": str(base),
            "manifest_sha256": sha256_file(base),
            "runtime_bindable": False,
        },
        "workspace_overlays": [
            {
                "workspace_key": owner,
                "workspace_root": str(workspace.resolve()),
                "runtime_view": "lineage_effective_view_only",
                "python_path_order": [str(effective_python_path.resolve())],
                "effective_python_path": str(effective_python_path.resolve()),
                "effective_code_root": str(effective_code_root.resolve()),
                "effective_code_payload_tree_sha256": effective_tree_sha,
                "effective_code_manifest_path": str(effective),
                "effective_code_manifest_sha256": sha256_file(effective),
                "private_effective_live_root": str(private_live.resolve()),
                "runtime_environment": {
                    "PYTHONPATH": str(effective_python_path.resolve()),
                    "XINAO_WORLD_WORKSPACE": str(workspace.resolve()),
                    "XINAO_LIVE_REALITY_ROOT": str(private_live.resolve()),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                "private_live_materialization": {
                    "root": str(private_live.resolve()),
                    "receipt_path": str(live_seed),
                    "receipt_sha256": sha256_file(live_seed),
                },
            }
        ],
    }
    migration = _write(
        tmp_path / "world-compute" / "migrations" / "migration-001" / "MANIFEST.json",
        canonical_json_bytes(migration_payload),
    )
    turn_number = 7
    attempt_number = 2
    attempt_dir = (
        run_dir
        / "lineages"
        / lineage_id
        / "turns"
        / f"turn-{turn_number:06d}"
        / f"attempt-{attempt_number:02d}"
    )
    attempt_dir.mkdir(parents=True)
    codex_args = _write(
        expected_codex_args_path(
            run_dir=run_dir,
            lineage_id=lineage_id,
            turn_number=turn_number,
            attempt_number=attempt_number,
        ),
        canonical_json_bytes(
            [
                "exec",
                "--strict-config",
                "--json",
                "-m",
                "gpt-5.6-sol",
                "-c",
                'model_reasoning_effort="max"',
                "-",
            ]
        ),
    )
    inputs: dict[str, object] = {
        "run_id": run_id,
        "run_dir": run_dir.resolve(),
        "account_slot": "A",
        "lineage_id": lineage_id,
        "role": role,
        "workspace": workspace.resolve(),
        "source_head": "a" * 40,
        "turn_number": turn_number,
        "attempt_number": attempt_number,
        "invocation_nonce": "1" * 32,
        "codex_args_path": codex_args,
        "codex_args_sha256": sha256_file(codex_args),
        "frozen_launcher_path": launcher,
        "frozen_launcher_sha256": sha256_file(launcher),
        "controller_release_path": controller,
        "controller_release_sha256": sha256_file(controller),
        "controller_python": controller_python,
        "controller_python_sha256": sha256_file(controller_python),
        "runtime_binding_release_path": runtime_binding_release,
        "runtime_binding_release_sha256": sha256_file(runtime_binding_release),
        "migration_manifest_path": migration,
        "migration_manifest_sha256": sha256_file(migration),
        "migration_id": "migration-001",
        "base_manifest_path": base,
        "base_manifest_sha256": sha256_file(base),
        "effective_code_root": effective_code_root.resolve(),
        "effective_python_path": effective_python_path.resolve(),
        "effective_code_manifest_path": effective,
        "effective_code_manifest_sha256": sha256_file(effective),
        "effective_code_tree_sha256": effective_tree_sha,
        "effective_code_owner_run_id": run_id,
        "effective_code_owner_lineage_id": owner_lineage_id or lineage_id,
        "private_live_root": private_live.resolve(),
        "live_seed_receipt_path": live_seed,
        "live_seed_receipt_sha256": sha256_file(live_seed),
    }
    return {
        "inputs": inputs,
        "run_dir": run_dir.resolve(),
        "workspace": workspace.resolve(),
        "effective_code_root": effective_code_root.resolve(),
        "effective_python_path": effective_python_path.resolve(),
        "world_compute_root": world_compute_root,
        "migration": migration,
        "base": base,
        "effective": effective,
        "live_seed": live_seed,
        "launcher": launcher,
        "controller_python": controller_python,
        "runtime_binding_release": runtime_binding_release,
        "codex_args": codex_args,
    }


def _binding(material: dict[str, object]) -> dict[str, object]:
    return build_world_runtime_binding(**material["inputs"])  # type: ignore[arg-type]


def _persist_binding(material: dict[str, object], binding: dict[str, object]) -> tuple[Path, str]:
    inputs = material["inputs"]
    path = expected_runtime_binding_path(
        run_dir=material["run_dir"],  # type: ignore[arg-type]
        lineage_id=str(inputs["lineage_id"]),  # type: ignore[index]
        turn_number=int(inputs["turn_number"]),  # type: ignore[index]
        attempt_number=int(inputs["attempt_number"]),  # type: ignore[index]
    )
    raw = world_runtime_binding_bytes(binding)
    path.write_bytes(raw)
    return path, sha256_bytes(raw)


def test_builds_single_effective_path_binding_and_exact_applied_receipt(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    binding_path, binding_file_sha = _persist_binding(material, binding)

    assert binding["schema"] == WORLD_RUNTIME_BINDING_SCHEMA
    assert binding["python_path_order"] == [str(material["effective_python_path"])]
    assert binding["cross_lineage_overlay_count"] == 0
    assert binding["legacy_live_runtime_dependency"] is False
    assert binding["binding_path"] == str(binding_path)
    assert binding["applied_receipt_path"] == str(
        expected_applied_receipt_path(
            run_dir=material["run_dir"],  # type: ignore[arg-type]
            lineage_id="world-01",
            turn_number=7,
            attempt_number=2,
        )
    )
    assert environment_projection(binding) == {
        "PYTHONPATH": str(material["effective_python_path"]),
        "XINAO_WORLD_WORKSPACE": str(material["workspace"]),
        "XINAO_LIVE_REALITY_ROOT": str(
            material["workspace"] / ".xinao-world-runtime" / "live-reality"  # type: ignore[operator]
        ),
    }
    assert world_runtime_binding_file_sha256(binding) == binding_file_sha
    assert validate_world_runtime_binding_bytes(
        binding_path.read_bytes(), expected_file_sha256=binding_file_sha
    ) == binding

    receipt = build_world_runtime_binding_applied_receipt(
        binding=binding,
        binding_file_sha256=binding_file_sha,
        observed_environment=environment_projection(binding),
        launcher_pid=4321,
    )
    assert set(receipt) == {
        "applied",
        "applied_receipt_path",
        "attempt_number",
        "binding_file_sha256",
        "binding_path",
        "binding_schema",
        "binding_sha256",
        "codex_args_path",
        "codex_args_sha256",
        "controller_release_path",
        "controller_release_sha256",
        "environment",
        "environment_sha256",
        "frozen_launcher_path",
        "frozen_launcher_sha256",
        "invocation_nonce",
        "launcher_pid",
        "lineage_id",
        "receipt_sha256",
        "role",
        "run_id",
        "schema",
        "turn_number",
    }
    assert receipt["schema"] == WORLD_RUNTIME_APPLIED_RECEIPT_SCHEMA
    assert receipt["invocation_nonce"] == "1" * 32
    assert receipt["turn_number"] == 7
    assert receipt["attempt_number"] == 2
    assert receipt["codex_args_sha256"] == sha256_file(material["codex_args"])  # type: ignore[arg-type]
    assert receipt["frozen_launcher_sha256"] == sha256_file(material["launcher"])  # type: ignore[arg-type]
    assert (
        validate_world_runtime_binding_applied_receipt(
            receipt,
            binding=binding,
            binding_file_sha256=binding_file_sha,
        )
        == receipt
    )


def test_effective_code_tree_drift_or_extra_file_fails_closed(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    extra = Path(material["effective_code_root"]) / "code" / "unexpected.py"
    extra.write_text("UNEXPECTED = True\n", encoding="utf-8")
    with pytest.raises(WorldRuntimeBindingError, match="exact file set differs"):
        validate_world_runtime_binding(binding)


def test_binding_file_byte_drift_fails_before_json_adoption(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    raw = world_runtime_binding_bytes(binding)

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding_bytes(
            raw + b" ", expected_file_sha256=sha256_bytes(raw)
        )

    assert raised.value.reason_code == "BINDING_FILE_HASH_MISMATCH"


def test_cross_lineage_effective_code_is_rejected(tmp_path: Path) -> None:
    material = _material(tmp_path, owner_lineage_id="world-02")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "CROSS_LINEAGE_EFFECTIVE_CODE"


def test_root_main_cannot_consume_branch_effective_code(tmp_path: Path) -> None:
    material = _material(
        tmp_path,
        lineage_id="root-main",
        role="late_fusion_root",
        owner_lineage_id="world-01",
    )

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "ROOT_MAIN_BRANCH_OVERLAY_FORBIDDEN"


def test_reversed_or_fallback_python_paths_are_rejected_even_when_resealed(
    tmp_path: Path,
) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    fallback = tmp_path / "world-compute" / "legacy-base-code"
    fallback.mkdir(parents=True)
    drifted = copy.deepcopy(binding)
    drifted["python_path_order"] = [
        str(fallback.resolve()),
        str(material["effective_python_path"]),
    ]
    drifted = _reseal(drifted, "binding_sha256")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding(drifted)

    assert raised.value.reason_code == "PYTHON_PATH_ORDER_MISMATCH"


def test_private_live_root_cannot_be_a_concrete_store(tmp_path: Path) -> None:
    workspace = tmp_path / "research-lineages" / "run-001" / "world-01"
    concrete = workspace / ".xinao-world-runtime" / "live-reality" / "pre203_holdout_1"
    material = _material(tmp_path, private_live_root=concrete)

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "CONCRETE_STORE_ROOT_FORBIDDEN"


def test_live_seed_receipt_outside_manifest_compute_root_is_rejected(
    tmp_path: Path,
) -> None:
    material = _material(tmp_path, live_seed_scope="outside")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "LIVE_SEED_RECEIPT_OUTSIDE_COMPUTE_ROOT"


def test_live_seed_receipt_inside_lineage_workspace_is_rejected(tmp_path: Path) -> None:
    material = _material(tmp_path, live_seed_scope="workspace")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "LIVE_SEED_RECEIPT_WRITABLE"


@pytest.mark.parametrize("manifest_name", ["migration", "base", "effective"])
def test_manifest_byte_drift_invalidates_binding(tmp_path: Path, manifest_name: str) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    Path(material[manifest_name]).write_bytes(b"drifted\n")  # type: ignore[arg-type]

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding(binding)

    assert raised.value.reason_code == "EXTERNAL_IDENTITY_DRIFT"


def test_controller_python_byte_drift_invalidates_binding(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    Path(material["controller_python"]).write_bytes(b"replacement-that-returns-zero\n")  # type: ignore[arg-type]

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding(binding)

    assert raised.value.reason_code == "EXTERNAL_IDENTITY_DRIFT"


def test_cross_lineage_fallback_count_is_rejected_even_when_resealed(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    drifted = copy.deepcopy(binding)
    drifted["cross_lineage_overlay_count"] = 1
    drifted = _reseal(drifted, "binding_sha256")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding(drifted)

    assert raised.value.reason_code == "CROSS_LINEAGE_FALLBACK_FORBIDDEN"


def test_applied_receipt_is_required(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    _, binding_file_sha = _persist_binding(material, binding)

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding_applied_receipt(
            None,
            binding=binding,
            binding_file_sha256=binding_file_sha,
        )

    assert raised.value.reason_code == "APPLIED_RECEIPT_MISSING"


def test_resealed_applied_receipt_invocation_drift_is_rejected(tmp_path: Path) -> None:
    material = _material(tmp_path)
    binding = _binding(material)
    _, binding_file_sha = _persist_binding(material, binding)
    receipt = build_world_runtime_binding_applied_receipt(
        binding=binding,
        binding_file_sha256=binding_file_sha,
        observed_environment=environment_projection(binding),
        launcher_pid=4321,
    )
    drifted = copy.deepcopy(receipt)
    drifted["invocation_nonce"] = "2" * 32
    drifted = _reseal(drifted, "receipt_sha256")

    with pytest.raises(WorldRuntimeBindingError) as raised:
        validate_world_runtime_binding_applied_receipt(
            drifted,
            binding=binding,
            binding_file_sha256=binding_file_sha,
        )

    assert raised.value.reason_code == "APPLIED_RECEIPT_MISMATCH"


def test_binding_does_not_reuse_legacy_live_tree(tmp_path: Path) -> None:
    legacy = tmp_path / "research-lineages" / "run-001" / "world-01" / "xinao" / "reality" / "live"
    material = _material(tmp_path, private_live_root=legacy)

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "LEGACY_LIVE_RUNTIME_DEPENDENCY"


@pytest.mark.parametrize(
    "override",
    [
        ["exec", "--sandbox", "danger-full-access", "-"],
        ["exec", "--add-dir", "D:/shared", "-"],
        ["exec", "--cd", "D:/shared", "-"],
        ["exec", "-c", 'approval_policy="on-request"', "-"],
        ["exec", "-c", 'sandbox_workspace_write.writable_roots=["D:/shared"]', "-"],
    ],
)
def test_codex_args_cannot_override_body_boundary(
    tmp_path: Path, override: list[str]
) -> None:
    material = _material(tmp_path)
    codex_args = Path(material["codex_args"])  # type: ignore[arg-type]
    codex_args.write_bytes(canonical_json_bytes(override))
    inputs = material["inputs"]
    inputs["codex_args_sha256"] = sha256_file(codex_args)  # type: ignore[index]

    with pytest.raises(WorldRuntimeBindingError) as raised:
        _binding(material)

    assert raised.value.reason_code == "CODEX_ARGS_BOUNDARY_OVERRIDE"
