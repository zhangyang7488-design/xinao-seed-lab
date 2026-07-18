from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from xinao.canonical import canonical_dumps, canonical_sha256

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def export_cli():
    return _load_script(
        "export_current_foundation_materials.py",
        "_test_export_current_foundation_materials",
    )


@pytest.fixture(scope="module")
def build_pack_cli():
    return _load_script(
        "build_current_foundation_closure_pack.py",
        "_test_build_current_foundation_closure_pack",
    )


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _valid_materials() -> dict[str, dict[str, object]]:
    return {
        "AlphaArtifact": {"schema_version": "xinao.alpha.v1", "value": 1},
        "BetaArtifact": {"version_id": "xinao.beta.v1", "value": [2, 3]},
    }


def test_export_is_atomic_content_addressed_and_pack_compatible(
    export_cli, monkeypatch, tmp_path
) -> None:
    source = _write_json(tmp_path / "source.json", {"request": "current"})
    output_root = tmp_path / "materials"
    output_root.mkdir()
    materials = _valid_materials()
    observed: dict[str, Path] = {}

    def load(snapshot: Path):
        observed["snapshot"] = snapshot
        assert snapshot != source.resolve()
        assert snapshot.read_bytes() == source.read_bytes()
        return materials

    monkeypatch.setattr(export_cli, "load_f1_snapshot_materials", load)

    result = export_cli.export_materials("f1", source, output_root)

    assert result["schema_version"] == "xinao.current_foundation_material_export.v1"
    assert result["block"] == "f1"
    assert result["source"]["path"] == str(source.resolve())
    assert result["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert not observed["snapshot"].exists()
    assert not list(tmp_path.glob(f".{output_root.name}.*.tmp"))
    for artifact_type, payload in materials.items():
        ref = result["materials"][artifact_type]
        assert set(ref) == {"version", "path", "sha256"}
        assert "artifact_type" not in ref
        assert "size_bytes" not in ref
        material_path = Path(ref["path"])
        assert material_path.parent == output_root.resolve()
        assert material_path.read_bytes() == canonical_dumps(payload)
        assert ref["sha256"] == canonical_sha256(payload)
        assert material_path.name == f"{artifact_type}.{ref['sha256']}.json"


def test_export_rejects_occupied_root_before_loading(export_cli, monkeypatch, tmp_path) -> None:
    source = _write_json(tmp_path / "source.json", {})
    output_root = tmp_path / "materials"
    output_root.mkdir()
    marker = output_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    loader = Mock(side_effect=AssertionError("loader must not run"))
    monkeypatch.setattr(export_cli, "load_f1_snapshot_materials", loader)

    with pytest.raises(ValueError, match="output root must be empty"):
        export_cli.export_materials("f1", source, output_root)

    loader.assert_not_called()
    assert marker.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "materials, error",
    [
        ({"AlphaArtifact": {"value": 1}}, "has no version identity"),
        (
            {"AlphaArtifact": {"schema_version": "xinao.alpha.v1", "value": float("nan")}},
            "NaN and Infinity",
        ),
    ],
)
def test_export_preflight_failure_leaves_no_partial_output(
    export_cli, monkeypatch, tmp_path, materials, error
) -> None:
    source = _write_json(tmp_path / "source.json", {})
    output_root = tmp_path / "materials"
    monkeypatch.setattr(export_cli, "load_f1_snapshot_materials", lambda _path: materials)

    with pytest.raises((TypeError, ValueError), match=error):
        export_cli.export_materials("f1", source, output_root)

    assert not output_root.exists()
    assert not list(tmp_path.glob(f".{output_root.name}.*.tmp"))


def test_export_detects_source_drift_and_restores_empty_root(
    export_cli, monkeypatch, tmp_path
) -> None:
    source = _write_json(tmp_path / "source.json", {"request": "before"})
    output_root = tmp_path / "materials"
    output_root.mkdir()

    def mutate_source(_snapshot: Path):
        _write_json(source, {"request": "after"})
        return _valid_materials()

    monkeypatch.setattr(export_cli, "load_f1_snapshot_materials", mutate_source)

    with pytest.raises(ValueError, match="source changed during material export"):
        export_cli.export_materials("f1", source, output_root)

    assert output_root.is_dir()
    assert not any(output_root.iterdir())
    assert not list(tmp_path.glob(f".{output_root.name}.*.tmp"))


def test_load_material_manifest_accepts_only_exact_v1(build_pack_cli, tmp_path) -> None:
    inputs = {"dataset_sha256": {"path": "D:/dataset", "sha256": "a" * 64}}
    artifacts = {
        "F1_settlement_world": {
            "Artifact": {"version": "v1", "path": "D:/artifact", "sha256": "b" * 64}
        }
    }
    manifest = _write_json(
        tmp_path / "manifest.json",
        {
            "schema_version": build_pack_cli.MANIFEST_SCHEMA_VERSION,
            "input_evidence": inputs,
            "artifact_materials": artifacts,
        },
    )

    loaded_inputs, loaded_artifacts = build_pack_cli.load_material_manifest(manifest)

    assert loaded_inputs == inputs
    assert loaded_artifacts == artifacts


@pytest.mark.parametrize(
    "payload, error",
    [
        ([], "exact v1 fields"),
        (
            {"schema_version": "old", "input_evidence": {}, "artifact_materials": {}},
            "schema version is not current",
        ),
        (
            {"schema_version": "xinao.current_foundation_closure_materials.v1"},
            "exact v1 fields",
        ),
        (
            {
                "schema_version": "xinao.current_foundation_closure_materials.v1",
                "input_evidence": {},
                "artifact_materials": {},
                "extra": True,
            },
            "exact v1 fields",
        ),
        (
            {
                "schema_version": "xinao.current_foundation_closure_materials.v1",
                "input_evidence": [],
                "artifact_materials": {},
            },
            "material manifest maps are invalid",
        ),
    ],
)
def test_load_material_manifest_rejects_invalid_envelopes(
    build_pack_cli, tmp_path, payload, error
) -> None:
    manifest = _write_json(tmp_path / "manifest.json", payload)
    with pytest.raises(ValueError, match=error):
        build_pack_cli.load_material_manifest(manifest)


def _builder_result(tmp_path: Path) -> dict[str, object]:
    return {
        "report_input_path": tmp_path / "input.json",
        "report_path": tmp_path / "report.json",
        "verification_path": tmp_path / "verification.json",
        "manifest_path": tmp_path / "pack.json",
        "authority_snapshot_manifest_path": tmp_path / "authority.json",
        "report": {"status": "VERIFIED"},
        "verification": {"ok": True},
        "manifest": {"foundation_execution_ready": True},
    }


def test_build_cli_forwards_exact_arguments_and_emits_strict_json(
    build_pack_cli, monkeypatch, capsys, tmp_path
) -> None:
    args = SimpleNamespace(
        manifest=tmp_path / "manifest.json",
        output_root=tmp_path / "output",
        report_id="report-id",
        version="foundation-closure-current.v2",
        created_at="2026-07-18T14:00:00+08:00",
    )
    inputs = {"input": {"path": "D:/input", "sha256": "a" * 64}}
    artifacts = {"F1": {"Artifact": {"version": "v1", "path": "D:/a", "sha256": "b" * 64}}}
    observed: dict[str, object] = {}

    monkeypatch.setattr(build_pack_cli, "parse_args", lambda: args)
    monkeypatch.setattr(
        build_pack_cli,
        "load_material_manifest",
        lambda path: (inputs, artifacts) if path == args.manifest else pytest.fail("wrong manifest"),
    )

    def build(**kwargs):
        observed.update(kwargs)
        return _builder_result(tmp_path)

    monkeypatch.setattr(build_pack_cli, "build_foundation_closure_pack", build)

    assert build_pack_cli.main() == 0

    assert observed == {
        "output_root": args.output_root,
        "input_evidence": inputs,
        "artifact_materials": artifacts,
        "report_id": args.report_id,
        "version": args.version,
        "created_at": args.created_at,
    }
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["report_path"] == str(tmp_path / "report.json")
    assert emitted["verification"]["ok"] is True


@pytest.mark.parametrize(
    "bad_value, error_type, error",
    [
        (object(), TypeError, "unsupported CLI JSON value: object"),
        (float("nan"), ValueError, "Out of range float values"),
    ],
)
def test_build_cli_rejects_non_json_output_values(
    build_pack_cli, monkeypatch, tmp_path, bad_value, error_type, error
) -> None:
    args = SimpleNamespace(
        manifest=tmp_path / "manifest.json",
        output_root=tmp_path / "output",
        report_id="report-id",
        version="foundation-closure-current.v2",
        created_at="2026-07-18T14:00:00+08:00",
    )
    monkeypatch.setattr(build_pack_cli, "parse_args", lambda: args)
    monkeypatch.setattr(build_pack_cli, "load_material_manifest", lambda _path: ({}, {}))
    result = _builder_result(tmp_path)
    result["bad"] = bad_value
    monkeypatch.setattr(build_pack_cli, "build_foundation_closure_pack", lambda **_kwargs: result)

    with pytest.raises(error_type, match=error):
        build_pack_cli.main()
