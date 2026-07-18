from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from xinao.canonical import canonical_dumps
from xinao.foundation import f4_current_evidence_verifier as f4_verifier
from xinao.foundation.assertion_bundle_runner import run_canonical_bundle_fresh
from xinao.foundation.assertion_verifiers.f4_assertion_actuals import (
    _F4PathBoundary,
    build_assertion_actuals_v1,
)
from xinao.foundation.f4_current_evidence_verifier import ASSERTION_IDS, canonical_sha256

CURRENT_PACK = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f4-current-source-oci-portable-20260715T084000"
)
OUTPUT_PACK = CURRENT_PACK.parent / f"{CURRENT_PACK.name}-independent-closure"
_CANARY_PATHS = sorted(OUTPUT_PACK.glob("ResearchFactoryCanaryReport.*.json"))
CANARY_PATH = _CANARY_PATHS[0] if _CANARY_PATHS else OUTPUT_PACK / "missing-canary.json"

retained_f4_evidence = pytest.mark.skipif(
    os.environ.get("XINAO_RUN_RETAINED_F4_ASSERTION_TESTS") != "1"
    or not CURRENT_PACK.is_dir()
    or not CANARY_PATH.is_file(),
    reason="explicit retained F4 assertion replay is not enabled or unavailable",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_ref(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _request() -> dict[str, object]:
    compiler = json.loads((CURRENT_PACK / "compiler_report.json").read_text(encoding="utf-8"))
    paths = {
        item["object_type"]: Path(item["file"]["path"]) for item in compiler["required_artifacts"]
    }
    paths["ResearchFactoryCanaryReport"] = CANARY_PATH
    input_hashes = {
        "dataset_sha256": hashlib.sha256(b"f4-test-dataset").hexdigest(),
        "compiler_config_sha256": hashlib.sha256(b"f4-test-config").hexdigest(),
    }
    code_hash = hashlib.sha256(b"f4-test-code").hexdigest()
    config_hash = input_hashes["compiler_config_sha256"]
    artifacts: dict[str, object] = {}
    for artifact_type, path in paths.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        envelope = {
            "artifact_type": artifact_type,
            "version": str(payload.get("version_id") or payload.get("schema_version")),
            "input_hashes": input_hashes,
            "code_hash": code_hash,
            "config_hash": config_hash,
            "source_ref": _file_ref(path),
            "payload": payload,
            "payload_sha256": canonical_sha256(payload),
        }
        artifacts[artifact_type] = {
            "staged_envelope": envelope,
            "staged_envelope_content_sha256": canonical_sha256(envelope),
        }
    return {
        "schema_version": "xinao.assertion_request.v2",
        "protocol_version": "xinao.assertion_bundle_protocol.v2",
        "block_id": "F4_research_factory",
        "assertion_ids": sorted(ASSERTION_IDS),
        "input_evidence": {},
        "input_hashes": input_hashes,
        "artifacts": artifacts,
        "compiler_code_sha256": code_hash,
        "compiler_config_sha256": config_hash,
    }


def _finalize_canary(value: dict[str, object]) -> dict[str, object]:
    core = dict(value)
    core.pop("content_sha256", None)
    core.pop("version_id", None)
    content_hash = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchFactoryCanaryReport@{content_hash[:16]}",
        "content_sha256": content_hash,
    }


def test_pretty_json_byte_check_is_portable_only_across_crlf_and_lf() -> None:
    lf = b'{\n  "value": true\n}\n'
    crlf = lf.replace(b"\n", b"\r\n")
    mixed = crlf.replace(b"\r\n", b"\n", 1)

    assert f4_verifier._pretty_json_bytes({"value": True}) == lf
    assert _F4PathBoundary.normalize_pretty_json_bytes(lf, "lf") == lf
    assert _F4PathBoundary.normalize_pretty_json_bytes(crlf, "crlf") == lf
    with pytest.raises(ValueError, match="mixed newline conventions"):
        _F4PathBoundary.normalize_pretty_json_bytes(mixed, "mixed")
    with pytest.raises(ValueError, match="unsupported carriage return"):
        _F4PathBoundary.normalize_pretty_json_bytes(
            b'{\r  "value": true\r}\r',
            "bare-cr",
        )


def _replace_canary(
    request: dict[str, object],
    canary: dict[str, object],
    path: Path,
) -> None:
    _write_json(path, canary)
    artifacts = request["artifacts"]
    assert isinstance(artifacts, dict)
    artifact = artifacts["ResearchFactoryCanaryReport"]
    assert isinstance(artifact, dict)
    envelope = artifact["staged_envelope"]
    assert isinstance(envelope, dict)
    envelope["version"] = canary["version_id"]
    envelope["source_ref"] = _file_ref(path)
    envelope["payload"] = canary
    envelope["payload_sha256"] = canonical_sha256(canary)
    artifact["staged_envelope_content_sha256"] = canonical_sha256(envelope)


@retained_f4_evidence
def test_f4_fixed_runner_freshly_returns_exact_boolean_actuals(tmp_path: Path) -> None:
    request = _request()
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "bundle.json"
    request_path.write_bytes(canonical_dumps(request))

    result = run_canonical_bundle_fresh(
        request_path=request_path,
        block_id="F4_research_factory",
        output_path=output_path,
    )
    bundle = json.loads(output_path.read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert list(bundle["assertion_actuals"]) == sorted(ASSERTION_IDS)
    assert bundle["assertion_actuals"] == {key: True for key in sorted(ASSERTION_IDS)}


@retained_f4_evidence
def test_self_consistent_canary_tamper_is_rejected_after_fresh_rebuild(
    tmp_path: Path,
) -> None:
    request = _request()
    canary = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    canary["report_is_evidence_authority"] = True
    tampered = _finalize_canary(canary)
    _replace_canary(request, tampered, tmp_path / "tampered-canary.json")

    with pytest.raises(ValueError, match="canary differs from rebuild"):
        build_assertion_actuals_v1(request)


@retained_f4_evidence
def test_self_consistent_map_and_canary_tamper_is_rejected_after_fresh_rebuild(
    tmp_path: Path,
) -> None:
    request = _request()
    canary = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    map_ref = canary["f4_assertion_evidence_map"]
    assert isinstance(map_ref, dict)
    evidence_map = json.loads(Path(map_ref["path"]).read_text(encoding="utf-8"))
    assertion_id = sorted(ASSERTION_IDS)[0]
    item = copy.deepcopy(evidence_map["assertions"][assertion_id])
    item["verification_state"] = "UNVERIFIED"
    item_core = dict(item)
    item_core.pop("content_sha256", None)
    item["content_sha256"] = canonical_sha256(item_core)
    evidence_map["assertions"][assertion_id] = item
    map_core = dict(evidence_map)
    map_core.pop("content_sha256", None)
    evidence_map["content_sha256"] = canonical_sha256(map_core)
    tampered_map_path = _write_json(tmp_path / "tampered-map.json", evidence_map)

    canary["f4_assertion_evidence_map"] = _file_ref(tampered_map_path)
    canary["f4_assertion_evidence_map_content_sha256"] = evidence_map["content_sha256"]
    tampered_canary = _finalize_canary(canary)
    _replace_canary(request, tampered_canary, tmp_path / "tampered-map-canary.json")

    with pytest.raises(ValueError, match="assertion map differs from rebuild"):
        build_assertion_actuals_v1(request)
