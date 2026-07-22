from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation import assertion_bundle_runner as bundle_runner
from xinao.foundation import closure as closure_module
from xinao.foundation.assertion_bundle_runner import (
    PROTOCOL_VERSION,
    REQUEST_SCHEMA_VERSION,
    AssertionBundleRunnerError,
    build_assertion_request_v2,
)
from xinao.foundation.assertion_verifier_registry import (
    CanonicalVerifierError,
    canonical_blueprint_path,
    canonical_verifier,
    load_canonical_actuals_callable,
    materialize_authority_snapshot,
    validate_authority_snapshot,
)
from xinao.foundation.closure import evidence_ref
from xinao.foundation.closure_pack import build_foundation_closure_pack
from xinao.foundation.f4_current_evidence_verifier import ASSERTION_IDS

F4_CURRENT_PACK = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f4-current-source-oci-portable-20260715T084000"
)
F4_CLOSURE_PACK = F4_CURRENT_PACK.parent / (F4_CURRENT_PACK.name + "-independent-closure")


def _file_ref(path: Path) -> dict[str, object]:
    path = path.resolve()
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _write_canonical(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(value))
    return path


def _invalid_f1_request() -> dict[str, object]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "block_id": "F1_settlement_world",
        "assertion_ids": ["semantic_rule_mapped_eq"],
        "input_evidence": {},
        "input_hashes": {},
        "artifacts": {},
        "compiler_code_sha256": "a" * 64,
        "compiler_config_sha256": "b" * 64,
    }


def _f4_materials() -> dict[str, dict[str, object]]:
    compiler_path = F4_CURRENT_PACK / "compiler_report.json"
    canaries = sorted(F4_CLOSURE_PACK.glob("ResearchFactoryCanaryReport.*.json"))
    if not compiler_path.is_file() or not canaries:
        pytest.skip("retained canonical F4 source/map/canary evidence is unavailable")
    compiler = json.loads(compiler_path.read_text(encoding="utf-8"))
    paths = {
        item["object_type"]: Path(item["file"]["path"]) for item in compiler["required_artifacts"]
    }
    paths["ResearchFactoryCanaryReport"] = canaries[0]
    materials: dict[str, dict[str, object]] = {}
    for artifact_type, path in sorted(paths.items()):
        payload = json.loads(path.read_text(encoding="utf-8"))
        materials[artifact_type] = {
            "version": str(payload.get("version_id") or payload.get("schema_version")),
            "payload": payload,
            "source_ref": _file_ref(path),
        }
    return materials


def test_caller_verifier_injection_does_not_cross_fresh_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = _write_canonical(tmp_path / "request.json", _invalid_f1_request())
    output_path = tmp_path / "bundle.json"

    fake_entry = SimpleNamespace(
        checker_id="caller.fake",
        checker_version="caller.fake.v1",
        module_name="caller.fake",
        source_path=tmp_path / "fake.py",
        source_sha256="f" * 64,
    )
    monkeypatch.setattr(
        bundle_runner,
        "load_canonical_actuals_callable",
        lambda _block_id: (fake_entry, lambda _request: {"semantic_rule_mapped_eq": True}),
    )

    with pytest.raises(AssertionBundleRunnerError, match="fresh canonical assertion runner failed"):
        bundle_runner.run_canonical_bundle_fresh(
            request_path=request_path,
            block_id="F1_settlement_world",
            output_path=output_path,
        )
    assert not output_path.exists()


def test_fake_blueprint_with_identical_bytes_has_no_production_identity(
    tmp_path: Path,
) -> None:
    canonical = canonical_blueprint_path()
    forged = tmp_path / canonical.name
    forged.write_bytes(canonical.read_bytes())

    with pytest.raises(
        CanonicalVerifierError,
        match="current non-authoritative machine projection",
    ):
        canonical_blueprint_path(forged)


def test_handcrafted_identical_bundles_fail_fresh_canonical_replay(
    tmp_path: Path,
) -> None:
    authority = materialize_authority_snapshot(tmp_path / "authority_snapshot")
    materials = _f4_materials()
    input_hashes = {
        "dataset_sha256": hashlib.sha256(b"adversarial-f4-dataset").hexdigest(),
        "compiler_config_sha256": hashlib.sha256(b"adversarial-f4-config").hexdigest(),
    }
    code_hash = hashlib.sha256(b"adversarial-f4-code").hexdigest()
    config_hash = input_hashes["compiler_config_sha256"]
    artifact_refs: list[dict[str, object]] = []
    for artifact_type, material in sorted(materials.items()):
        payload = material["payload"]
        envelope = {
            "artifact_type": artifact_type,
            "version": material["version"],
            "input_hashes": input_hashes,
            "code_hash": code_hash,
            "config_hash": config_hash,
            "source_ref": material["source_ref"],
            "payload": payload,
            "payload_sha256": canonical_sha256(payload),
        }
        path = _write_canonical(tmp_path / "artifacts" / f"{artifact_type}.json", envelope)
        artifact_refs.append({**evidence_ref(path), "artifact_type": artifact_type})

    request = build_assertion_request_v2(
        block_id="F4_research_factory",
        assertion_ids=ASSERTION_IDS,
        input_refs={},
        input_hashes=input_hashes,
        materials=materials,
        compiler_code_sha256=code_hash,
        compiler_config_sha256=config_hash,
    )
    request_ref = evidence_ref(_write_canonical(tmp_path / "request.json", request))
    first_ref = evidence_ref(
        _write_canonical(tmp_path / "handcrafted-first.json", {"caller_claim": True})
    )
    second_ref = evidence_ref(
        _write_canonical(tmp_path / "handcrafted-second.json", {"caller_claim": True})
    )
    assert Path(first_ref["path"]).read_bytes() == Path(second_ref["path"]).read_bytes()
    receipt_ref = evidence_ref(
        _write_canonical(tmp_path / "receipt.json", {"request_ref": request_ref})
    )
    assertion_results: dict[str, dict[str, object]] = {}
    for assertion_id in sorted(ASSERTION_IDS):
        payload_path = _write_canonical(
            tmp_path / "assertions" / f"{assertion_id}.json",
            {
                "assertion_bundle_ref": first_ref,
                "fresh_assertion_bundle_ref": second_ref,
                "fresh_receipt_ref": receipt_ref,
            },
        )
        assertion_results[assertion_id] = {
            "evidence_refs": [{**evidence_ref(payload_path), "assertion_id": assertion_id}]
        }

    replayed, reason = closure_module._canonical_replay_block(
        "F4_research_factory",
        {
            "evidence_refs": artifact_refs,
            "assertion_results": assertion_results,
        },
        profile_block={
            "required_artifact_types": sorted(materials),
            "required_assertion_ids": sorted(ASSERTION_IDS),
        },
        input_refs={},
        input_hashes=input_hashes,
        code_hash=code_hash,
        config_hash=config_hash,
        authority_manifest_ref=evidence_ref(authority["manifest_path"]),
    )

    assert replayed is False
    assert reason in {
        "canonical_replay_fresh_bundle_mismatch",
        "canonical_replay_execution_failed:AssertionBundleRunnerError",
    }


def test_self_consistent_code_manifest_hash_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    authority = materialize_authority_snapshot(tmp_path / "authority_snapshot")
    manifest_path = authority["manifest_path"]
    manifest = json.loads(manifest_path.read_bytes())
    source_entry = next(
        item
        for item in manifest["entries"]
        if item["relative_path"].endswith("assertion_verifier_registry.py")
    )
    attacker_source = (
        manifest_path.parent / "sources" / Path(*source_entry["relative_path"].split("/"))
    )
    attacker_source.write_text(
        "def build_assertion_actuals_v1(request): return {}\n", encoding="utf-8"
    )
    attacker_raw = attacker_source.read_bytes()
    source_entry["sha256"] = hashlib.sha256(attacker_raw).hexdigest()
    source_entry["size"] = len(attacker_raw)
    manifest["source_tree_sha256"] = canonical_sha256(manifest["entries"])
    manifest["authority_tree_sha256"] = canonical_sha256(
        {
            "policy_id": manifest["policy_id"],
            "source_tree_sha256": manifest["source_tree_sha256"],
            "runtime_buildinfo_ref": manifest["runtime_buildinfo_ref"],
        }
    )
    core = dict(manifest)
    core.pop("content_sha256")
    manifest["content_sha256"] = canonical_sha256(core)
    manifest_path.write_bytes(canonical_dumps(manifest))

    historical = validate_authority_snapshot(manifest_path, require_live_match=False)
    assert historical["content_sha256"] == manifest["content_sha256"]
    with pytest.raises(CanonicalVerifierError, match="current production authority"):
        validate_authority_snapshot(manifest_path, require_live_match=True)


def test_source_path_replacement_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = canonical_verifier("F3_research_weight")
    replacement_path = tmp_path / "f3_assertion_actuals.py"
    replacement_path.write_text(
        "def build_assertion_actuals_v1(request): return {}\n", encoding="utf-8"
    )
    replacement = ModuleType(entry.module_name)
    replacement.__file__ = str(replacement_path)
    replacement.build_assertion_actuals_v1 = lambda _request: {}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, entry.module_name, replacement)

    with pytest.raises(CanonicalVerifierError, match="module path replacement"):
        load_canonical_actuals_callable("F3_research_weight")


def test_pythonpath_injection_is_ignored_by_fixed_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "pythonpath-owned.txt"
    malicious_root = tmp_path / "malicious"
    package = malicious_root / "xinao" / "foundation"
    package.mkdir(parents=True)
    (malicious_root / "xinao" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "assertion_bundle_runner.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('owned', encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(malicious_root))
    request_path = _write_canonical(tmp_path / "request.json", _invalid_f1_request())

    with pytest.raises(AssertionBundleRunnerError, match="fresh canonical assertion runner failed"):
        bundle_runner.run_canonical_bundle_fresh(
            request_path=request_path,
            block_id="F1_settlement_world",
            output_path=tmp_path / "bundle.json",
        )
    assert not marker.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("assertion_bundle_verifiers", {"F1_settlement_world": "caller"}),
        ("block_producer_ids", {"F1_settlement_world": ["caller"]}),
        ("block_verifier_ids", {"F1_settlement_world": "caller"}),
        ("report_producer_ids", ["caller"]),
        ("independent_verifier_id", "caller"),
    ],
)
def test_arbitrary_producer_and_verifier_identities_are_not_public_inputs(
    tmp_path: Path, field: str, value: object
) -> None:
    arguments = {
        "output_root": tmp_path / "pack",
        "input_evidence": {},
        "artifact_materials": {},
        "report_id": "adversarial",
        "version": "v0",
        "created_at": "2026-07-15T00:00:00+08:00",
        field: value,
    }

    with pytest.raises(TypeError, match=field):
        build_foundation_closure_pack(**arguments)  # type: ignore[arg-type]
