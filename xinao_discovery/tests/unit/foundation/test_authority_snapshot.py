from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation import assertion_verifier_registry as registry_module
from xinao.foundation import closure as closure_module
from xinao.foundation import closure_pack as closure_pack_module
from xinao.foundation.assertion_verifier_registry import (
    AUTHORITY_MANIFEST_SCHEMA_VERSION,
    AUTHORITY_SEAL_POLICY_ID,
    RUNTIME_BUILDINFO_SCHEMA_VERSION,
    CanonicalVerifierError,
    build_canonical_code_manifest,
    build_foundation_runtime_buildinfo,
    canonical_blueprint_path,
    canonical_verifier,
    materialize_authority_snapshot,
    validate_authority_snapshot,
)
from xinao.foundation.assertion_verifiers import common as verifier_common
from xinao.foundation.closure import evidence_ref, load_foundation_profile
from xinao.foundation.closure_pack import ClosurePackError


@pytest.fixture(scope="module")
def authority_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("authority-template") / "authority_snapshot"
    return materialize_authority_snapshot(root)["root"]


def _clone_snapshot(authority_template: Path, tmp_path: Path) -> Path:
    target = tmp_path / "authority_snapshot"
    shutil.copytree(authority_template, target)
    return target


def _manifest_path(root: Path) -> Path:
    return root / "authority_manifest.json"


def _load_manifest(root: Path) -> dict[str, Any]:
    return json.loads(_manifest_path(root).read_bytes())


def _write_rehashed_manifest(root: Path, manifest: dict[str, Any]) -> None:
    manifest["source_tree_sha256"] = canonical_sha256(manifest["entries"])
    manifest["authority_tree_sha256"] = canonical_sha256(
        {
            "policy_id": manifest["policy_id"],
            "source_tree_sha256": manifest["source_tree_sha256"],
            "runtime_buildinfo_ref": manifest["runtime_buildinfo_ref"],
        }
    )
    core = dict(manifest)
    core.pop("content_sha256", None)
    manifest["content_sha256"] = canonical_sha256(core)
    _manifest_path(root).write_bytes(canonical_dumps(manifest))


def _first_snapshot_source(root: Path) -> Path:
    entry = _load_manifest(root)["entries"][0]
    return root / "sources" / Path(*entry["relative_path"].split("/"))


def test_authority_allowlist_is_exact_f1_f4_transitive_source_closure() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    xinao_src = repo_root / "xinao_discovery" / "src"
    expected = {xinao_src / "xinao" / "__init__.py"}
    for root in (
        xinao_src / "xinao" / "canonical",
        xinao_src / "xinao" / "foundation",
        xinao_src / "xinao" / "contracts",
        xinao_src / "xinao" / "lineage",
        repo_root / "projects" / "dual-brain-coordination" / "src",
    ):
        expected.update(root.rglob("*.py"))
    expected.update(
        {
            repo_root / "services" / "__init__.py",
            repo_root / "services" / "agent_runtime" / "__init__.py",
            repo_root / "services" / "agent_runtime" / "foundation_continuous_workflow.py",
            repo_root / "services" / "agent_runtime" / "foundation_continuous_workflow_v2.py",
            repo_root / "scripts" / "build_current_foundation_closure_pack.py",
            repo_root / "scripts" / "export_current_foundation_materials.py",
            repo_root / "scripts" / "verify_f4_live_canary_pack.py",
            repo_root / "scripts" / "verify_f4_negative_companion_pack.py",
            repo_root / "scripts" / "verify_f4_portfolio_source_canary_pack.py",
            repo_root / "scripts" / "run_foundation_v2_f4_negative_companion.py",
            repo_root / "scripts" / "promote_foundation_authority_generation.py",
        }
    )
    manifest = build_canonical_code_manifest()
    actual = {repo_root / Path(*entry["relative_path"].split("/")) for entry in manifest["entries"]}

    assert manifest["schema_version"] == AUTHORITY_MANIFEST_SCHEMA_VERSION
    assert manifest["policy_id"] == AUTHORITY_SEAL_POLICY_ID
    assert actual == {path.resolve() for path in expected}
    relative_paths = {entry["relative_path"] for entry in manifest["entries"]}
    assert not any("/validation/" in path for path in relative_paths)
    assert not any("/tests/" in path for path in relative_paths)
    assert not any(path.endswith(("pyproject.toml", "uv.lock")) for path in relative_paths)
    assert not any(
        path.startswith("services/agent_runtime/")
        and path
        not in {
            "services/agent_runtime/__init__.py",
            "services/agent_runtime/foundation_continuous_workflow.py",
            "services/agent_runtime/foundation_continuous_workflow_v2.py",
        }
        for path in relative_paths
    )


def test_runtime_buildinfo_is_recursive_distribution_file_tree_projection() -> None:
    buildinfo = build_foundation_runtime_buildinfo()

    assert buildinfo["schema_version"] == RUNTIME_BUILDINFO_SCHEMA_VERSION
    core = dict(buildinfo)
    recorded = core.pop("content_sha256")
    assert recorded == canonical_sha256(core)
    expected_roots = {
        "xinao_assertion_runtime": ["hypothesis", "pydantic", "rfc8785", "uuid6"],
            "f4_workflow_runtime": [
                "temporalio",
                "mlflow",
                "pydantic",
            "rfc8785",
            "uuid6",
            "apsw",
            "jsonschema",
            "opentelemetry-api",
        ],
    }
    for runtime_name, roots in expected_roots.items():
        runtime = buildinfo["runtimes"][runtime_name]
        interpreter = runtime["interpreter"]
        assert Path(interpreter["executable_path"]).is_file()
        assert len(interpreter["executable_sha256"]) == 64
        projection = runtime["distribution_projection"]
        projection_core = dict(projection)
        projection_hash = projection_core.pop("projection_sha256")
        assert projection_hash == canonical_sha256(projection_core)
        assert projection["roots"] == roots
        names = {item["name"] for item in projection["distributions"]}
        assert set(roots) <= names
        for item in [
            projection["resolver_distribution"],
            *projection["distributions"],
        ]:
            assert set(item) == {
                "name",
                "version",
                "requirements",
                "file_count",
                "file_tree_sha256",
            }
            assert item["version"]
            assert item["file_count"] > 0
            assert len(item["file_tree_sha256"]) == 64


def test_snapshot_accepts_exact_materialization(authority_template: Path) -> None:
    manifest = validate_authority_snapshot(
        _manifest_path(authority_template), require_live_match=True
    )

    assert manifest["schema_version"] == AUTHORITY_MANIFEST_SCHEMA_VERSION
    assert manifest["policy_id"] == AUTHORITY_SEAL_POLICY_ID


def test_blueprint_requires_exact_ten_inputs_and_twenty_six_raw_artifacts() -> None:
    profile = load_foundation_profile(canonical_blueprint_path())
    metadata = profile["_closure_meta"]

    assert set(metadata["required_input_hash_keys"]) == verifier_common.INPUT_KEYS
    assert len(verifier_common.INPUT_KEYS - {"compiler_code_sha256"}) == 9
    expected_f3_hashes = {
        "f3_prior_draft_sha256": "9177e2788286aa7aeef82d315ad4788088b27612653b8a57aa846b0ac7d1b819",
        "f3_service_graph_sha256": (
            "b288837827b6b1b616494510a5f86c912a3540ae845a21d460d9762b48fa2555"
        ),
        "f3_external_synthesis_sha256": (
            "35a47ab7cfbc7f78e3e87f38e8777dfbc88308985f5f17c1a5515a03e2505996"
        ),
    }
    assert {
        key: metadata["known_input_hashes"].get(key) for key in expected_f3_hashes
    } == expected_f3_hashes
    assert sum(len(block["required_artifact_types"]) for block in profile["blocks"].values()) == 26


def test_snapshot_verifier_source_is_pack_local_and_live_identical(
    authority_template: Path,
) -> None:
    manifest_path = _manifest_path(authority_template)
    manifest = validate_authority_snapshot(manifest_path, require_live_match=True)
    verifier = canonical_verifier("F4_research_factory")

    snapshot_path, relative_path = closure_pack_module._snapshot_verifier_source(
        manifest_path=manifest_path,
        authority_manifest=manifest,
        block_id="F4_research_factory",
    )

    assert snapshot_path.is_relative_to(authority_template / "sources")
    assert relative_path == f"xinao_discovery/src/{verifier.relative_source}"
    assert snapshot_path.read_bytes() == verifier.source_path.read_bytes()


def test_source_material_refs_must_be_exactly_pack_local(
    authority_template: Path, tmp_path: Path
) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    manifest_ref = evidence_ref(_manifest_path(root))
    input_path = tmp_path / "source_materials" / "inputs" / "dataset.json"
    input_path.parent.mkdir(parents=True)
    input_path.write_text("{}", encoding="utf-8")
    input_refs = {
        "dataset_sha256": evidence_ref(input_path, input_hash_key="dataset_sha256"),
        "compiler_code_sha256": {
            **manifest_ref,
            "input_hash_key": "compiler_code_sha256",
        },
    }
    raw_blocks: dict[str, dict[str, Any]] = {}
    for block_id in registry_module.FOUNDATION_BLOCK_IDS:
        source = tmp_path / "source_materials" / "artifacts" / block_id / "raw.json"
        source.parent.mkdir(parents=True)
        source.write_text("{}", encoding="utf-8")
        envelope = tmp_path / "artifacts" / block_id / "envelope.json"
        envelope.parent.mkdir(parents=True)
        envelope.write_bytes(
            canonical_dumps(
                {
                    "artifact_type": "fixture",
                    "version": "v1",
                    "payload": {"fixture": True},
                    "source_ref": evidence_ref(source),
                }
            )
        )
        raw_blocks[block_id] = {"evidence_refs": [evidence_ref(envelope)]}

    assert (
        closure_module._source_materials_are_pack_local(
            authority_manifest_ref=manifest_ref,
            input_refs=input_refs,
            raw_blocks=raw_blocks,
        )
        is True
    )

    (tmp_path / "source_materials" / "unexpected.bin").write_bytes(b"extra")
    assert (
        closure_module._source_materials_are_pack_local(
            authority_manifest_ref=manifest_ref,
            input_refs=input_refs,
            raw_blocks=raw_blocks,
        )
        is False
    )


def test_snapshot_rejects_missing_file(authority_template: Path, tmp_path: Path) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    _first_snapshot_source(root).unlink()

    with pytest.raises(CanonicalVerifierError, match="file inventory"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_extra_file(authority_template: Path, tmp_path: Path) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    (root / "sources" / "extra.py").write_text("pass\n", encoding="utf-8")

    with pytest.raises(CanonicalVerifierError, match="file inventory"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_hash_drift(authority_template: Path, tmp_path: Path) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    source = _first_snapshot_source(root)
    source.write_bytes(source.read_bytes() + b"\n")

    with pytest.raises(CanonicalVerifierError, match="source hash drifted"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_manifest_path_traversal(authority_template: Path, tmp_path: Path) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    manifest = _load_manifest(root)
    manifest["entries"][0]["relative_path"] = "../escape.py"
    _write_rehashed_manifest(root, manifest)

    with pytest.raises(CanonicalVerifierError, match="escapes its root"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_casefold_collision(authority_template: Path, tmp_path: Path) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    manifest = _load_manifest(root)
    manifest["entries"][1]["relative_path"] = manifest["entries"][0]["relative_path"].upper()
    _write_rehashed_manifest(root, manifest)

    with pytest.raises(CanonicalVerifierError, match="source identity"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_reparse_content(
    authority_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    original = registry_module._is_reparse
    monkeypatch.setattr(
        registry_module,
        "_is_reparse",
        lambda path: Path(path).name == "sources" or original(path),
    )

    with pytest.raises(CanonicalVerifierError, match="reparse point"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_snapshot_rejects_unknown_policy_even_when_rehashed(
    authority_template: Path, tmp_path: Path
) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    manifest = _load_manifest(root)
    manifest["policy_id"] = "attacker.self-authorized.v1"
    _write_rehashed_manifest(root, manifest)

    with pytest.raises(CanonicalVerifierError, match="policy is unknown"):
        validate_authority_snapshot(_manifest_path(root), require_live_match=False)


def test_sealed_fresh_runner_rejects_pre_execution_snapshot_drift(
    authority_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    source = _first_snapshot_source(root)
    source.write_bytes(source.read_bytes() + b"\n")
    called = False

    def fake_runner(**_kwargs: object) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(closure_pack_module, "run_canonical_bundle_fresh", fake_runner)
    with pytest.raises(ClosurePackError, match="source hash drifted"):
        closure_pack_module._run_sealed_bundle_fresh(
            manifest_path=_manifest_path(root),
            request_path=tmp_path / "request.json",
            block_id="F1_settlement_world",
            output_path=tmp_path / "output.json",
            timeout=1,
        )
    assert called is False


def test_sealed_fresh_runner_rejects_post_execution_toctou(
    authority_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _clone_snapshot(authority_template, tmp_path)
    source = _first_snapshot_source(root)

    def fake_runner(**_kwargs: object) -> dict[str, Any]:
        source.write_bytes(source.read_bytes() + b"\n")
        return {}

    monkeypatch.setattr(closure_pack_module, "run_canonical_bundle_fresh", fake_runner)
    with pytest.raises(ClosurePackError, match="source hash drifted"):
        closure_pack_module._run_sealed_bundle_fresh(
            manifest_path=_manifest_path(root),
            request_path=tmp_path / "request.json",
            block_id="F1_settlement_world",
            output_path=tmp_path / "output.json",
            timeout=1,
        )


def test_p5_validation_bytes_are_outside_foundation_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = canonical_dumps(build_canonical_code_manifest())
    repo_root = Path(__file__).resolve().parents[4]
    p5_path = (
        repo_root / "xinao_discovery" / "src" / "xinao" / "validation" / "court.py"
    ).resolve()
    original = Path.read_bytes

    def changed_p5(path: Path) -> bytes:
        if path.resolve() == p5_path:
            return original(path) + b"\n# simulated P5-only change\n"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", changed_p5)
    assert canonical_dumps(build_canonical_code_manifest()) == baseline


def test_f1_phase_children_use_isolation_without_allocator_or_gc_workarounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "catalog.json"
    dataset = tmp_path / "dataset.txt"
    catalog.write_text("{}", encoding="utf-8")
    dataset.write_text("fixture", encoding="utf-8")
    prepared = verifier_common.PreparedRequest(
        block_id="F1_settlement_world",
        input_paths={
            "play_catalog_sha256": catalog,
            "dataset_sha256": dataset,
        },
        input_hashes={},
        artifact_paths={},
        artifact_hashes={},
        artifact_versions={},
        required_assertion_ids=(),
    )
    environments: list[dict[str, str]] = []

    def fake_run(arguments: list[str], **kwargs: Any) -> SimpleNamespace:
        environment = kwargs["env"]
        environments.append(dict(environment))
        payload = {"event_keys": {}} if arguments[6] == "final" else {}
        Path(arguments[-1]).write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(
        verifier_common, "canonical_python_executable", lambda: Path(sys.executable)
    )
    monkeypatch.setattr(verifier_common.subprocess, "run", fake_run)

    verifier_common.run_f1_isolated_recomputation(prepared)

    assert len(environments) == 3
    assert all(
        not any(key.upper().startswith("PYTHON") for key in environment)
        for environment in environments
    )
    phase_source = Path(verifier_common.__file__).with_name("_f1_phase_worker.py")
    assert "gc.disable(" not in phase_source.read_text(encoding="utf-8")
