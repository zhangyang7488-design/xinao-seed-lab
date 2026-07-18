from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts import verify_f4_live_canary_pack as subject


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _manifest_entry(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": subject.file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _minimal_pack(tmp_path: Path) -> tuple[Path, Path]:
    pack = tmp_path / "pack"
    report = _write(pack / "f4_live_canary_report.json", {"status": "VERIFIED"})
    payload = _write(pack / "payload.bin", b"bound payload")
    _write(
        pack / "artifact_manifest.json",
        {
            "schema_version": "xinao.f4_live_canary_artifact_manifest.v1",
            "report_ref": str(report.resolve()),
            "report_sha256": subject.file_sha256(report),
            "artifacts": [_manifest_entry(report), _manifest_entry(payload)],
        },
    )
    return pack, payload


def test_content_addressed_assertion_recomputes(tmp_path: Path) -> None:
    evidence = _write(tmp_path / "evidence.json", {"ok": True})
    assertion = subject._assertion("example", [evidence], {"count": 1})
    body = dict(assertion)
    recorded = body.pop("assertion_sha256")

    assert recorded == subject.canonical_sha256(body)
    assert assertion["evidence_set_sha256"] == subject.canonical_sha256(assertion["evidence_refs"])


def test_artifact_manifest_is_exact_and_hash_bound(tmp_path: Path) -> None:
    pack, payload = _minimal_pack(tmp_path)
    manifest, _, paths, artifact_set_hash = subject._verify_artifact_manifest(pack)

    assert manifest["schema_version"] == "xinao.f4_live_canary_artifact_manifest.v1"
    assert len(paths) == 2
    assert len(artifact_set_hash) == 64

    payload.write_bytes(b"tampered")
    with pytest.raises(subject.VerificationError, match="hash drifted"):
        subject._verify_artifact_manifest(pack)


def test_artifact_manifest_rejects_unlisted_extra_file(tmp_path: Path) -> None:
    pack, _ = _minimal_pack(tmp_path)
    _write(pack / "unlisted.txt", b"extra")

    with pytest.raises(subject.VerificationError, match="exact file set"):
        subject._verify_artifact_manifest(pack)


def test_result_parser_accepts_json_fence_and_rejects_prose() -> None:
    assert subject._parse_result_object('```json\n{"ok": true}\n```') == {"ok": True}
    with pytest.raises(subject.VerificationError, match="strict JSON"):
        subject._parse_result_object("not json")


def test_attempt_manifest_names_are_portable_from_windows_paths() -> None:
    files = [
        {"path": rf"D:\\evidence\\attempt-001\\{name}"}
        for name in sorted(subject.EXPECTED_MANIFEST_FILES)
    ]

    assert subject._attempt_file_names(files) == subject.EXPECTED_MANIFEST_FILES


@pytest.mark.parametrize(
    "path",
    [
        r"D:\\evidence\\fanin\\digest.json",
        "/evidence/fanin/digest.json",
    ],
)
def test_portable_stem_accepts_windows_and_posix_paths(path: str) -> None:
    assert subject._portable_stem(path) == "digest"


def test_container_evidence_ref_maps_to_bound_host_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    evidence = _write(runtime / "state" / "proof.json", {"ok": True})
    monkeypatch.setattr(subject, "HOST_EVIDENCE_ROOT", runtime.resolve())

    assert subject._resolve_ref("/evidence/state/proof.json") == evidence.resolve()
    assert subject._same_path("/evidence/state/proof.json", evidence)


def test_container_evidence_ref_rejects_runtime_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    _write(tmp_path / "outside.json", {"outside": True})
    monkeypatch.setattr(subject, "HOST_EVIDENCE_ROOT", runtime.resolve())

    with pytest.raises(subject.VerificationError, match="escaped the host runtime root"):
        subject._resolve_ref("/evidence/../outside.json")


def test_legacy_acpx_model_identity_fails_closed_on_observed_model_drift() -> None:
    evidence = {
        "source": "acpx_runtime_status_after_turn",
        "requestedModel": "grok-4.5",
        "currentModelId": "grok-4.5",
        "availableModelIds": ["grok-4.5"],
        "acpxRecordId": "record",
        "backendSessionId": "session",
    }
    lane = {
        "session_model_evidence": dict(evidence),
        "session_model_evidence_valid": True,
    }
    manifest = {
        "session_model_evidence": dict(evidence),
        "session_model_evidence_valid": True,
    }
    subject._verify_model_identity(lane, manifest)
    manifest["session_model_evidence"]["currentModelId"] = "unexpected"

    with pytest.raises(subject.VerificationError, match="grok-4.5"):
        subject._verify_model_identity(lane, manifest)


def test_operation_route_selects_exact_legacy_and_docker_models() -> None:
    assert subject._operation_route({}) == ("legacy:acpx", "grok-4.5")
    assert subject._operation_observed_model("legacy:acpx", "grok-4.5") == "grok-4.5"
    assert subject._operation_route({"execution_location": "docker:houtai-gongren"}) == (
        "docker:houtai-gongren",
        "grok-composer-2.5-fast",
    )
    assert (
        subject._operation_observed_model("docker:houtai-gongren", "grok-composer-2.5-fast")
        == "grok-4.5-build"
    )

    with pytest.raises(subject.VerificationError, match="unsupported operation"):
        subject._operation_route({"execution_location": "unknown"})


def test_docker_composer_identity_accepts_only_exact_backend() -> None:
    model = "grok-composer-2.5-fast"
    backend = "grok-4.5-build"
    lane = {
        "agent_session_id": "session",
        "observed_backend_models": [backend],
        "model_identity_ok": True,
        "session_model_evidence_valid": True,
        "session_model_evidence": {
            "source": "grok_session_summary_and_turn_events",
            "requestedModel": model,
            "selectedSessionModel": model,
            "currentModelId": model,
            "observedModelId": backend,
            "turnModelIds": [model],
            "modelUsageIds": [backend],
            "availableModelIds": ["grok-4.5", model],
            "backendModelIds": [backend],
            "expectedBackendModelIds": [backend],
            "backendSessionId": "session",
            "sessionSummaryRef": "summary.json",
            "sessionSummarySha256": "a" * 64,
            "sessionEventsRef": "events.jsonl",
            "sessionEventsSha256": "b" * 64,
            "sessionCwd": "D:/repo",
            "sessionGrokHome": "D:/profile",
        },
    }

    subject._verify_docker_model_identity(lane)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "grok_cli_json_modelUsage"),
        ("requestedModel", "grok-4.5"),
        ("selectedSessionModel", "grok-4.5"),
        ("currentModelId", "grok-4.5"),
        ("observedModelId", "grok-composer-2.5-fast"),
        ("turnModelIds", ["grok-4.5-build"]),
        ("modelUsageIds", ["grok-composer-2.5-fast"]),
        ("availableModelIds", ["grok-4.5"]),
        ("backendModelIds", []),
        ("backendModelIds", ["grok-4.5"]),
        ("backendModelIds", ["grok-4.5-build", "unexpected"]),
        ("expectedBackendModelIds", ["grok-composer-2.5-fast"]),
    ],
)
def test_docker_composer_identity_rejects_route_or_backend_drift(
    field: str,
    value: object,
) -> None:
    model = "grok-composer-2.5-fast"
    backend = "grok-4.5-build"
    evidence = {
        "source": "grok_session_summary_and_turn_events",
        "requestedModel": model,
        "selectedSessionModel": model,
        "currentModelId": model,
        "observedModelId": backend,
        "turnModelIds": [model],
        "modelUsageIds": [backend],
        "availableModelIds": ["grok-4.5", model],
        "backendModelIds": [backend],
        "expectedBackendModelIds": [backend],
        "backendSessionId": "session",
        "sessionSummaryRef": "summary.json",
        "sessionSummarySha256": "a" * 64,
        "sessionEventsRef": "events.jsonl",
        "sessionEventsSha256": "b" * 64,
        "sessionCwd": "D:/repo",
        "sessionGrokHome": "D:/profile",
    }
    evidence[field] = value
    lane = {
        "agent_session_id": "session",
        "observed_backend_models": [backend],
        "model_identity_ok": True,
        "session_model_evidence_valid": True,
        "session_model_evidence": evidence,
    }

    with pytest.raises(subject.VerificationError, match="grok-composer-2.5-fast"):
        subject._verify_docker_model_identity(lane)


def test_docker_operation_spec_uses_artifact_schema_digest_and_history_binding() -> None:
    result_schema = {"type": "object", "required": ["work_key"]}
    artifact_digest = hashlib.sha256(subject.artifact_json_bytes(result_schema)).hexdigest()
    assert artifact_digest != subject.canonical_sha256(result_schema)
    spec = {
        "schema_version": "xinao.grok.docker_native_cli.v1",
        "operation_id": "operation-1",
        "lane_id": "lane-1",
        "contract_id": "xinao.foundation.f4.readonly_lane.v1",
        "write": False,
        "model": "grok-composer-2.5-fast",
        "allowed_tools": ["read_file"],
        "max_turns": None,
        "result_format": "json_object",
        "result_json_schema": result_schema,
        "result_json_schema_sha256": artifact_digest,
        "prompt_sha256": "5" * 64,
    }
    binding = {
        "result_format": "json_object",
        "result_json_schema_sha256": artifact_digest,
        "prompt_sha256": "5" * 64,
    }

    subject._verify_docker_operation_spec(
        spec,
        binding,
        operation_id="operation-1",
        lane_id="lane-1",
    )

    binding["result_json_schema_sha256"] = subject.canonical_sha256(result_schema)
    with pytest.raises(subject.VerificationError, match="operation-spec"):
        subject._verify_docker_operation_spec(
            spec,
            binding,
            operation_id="operation-1",
            lane_id="lane-1",
        )


@pytest.mark.skipif(
    os.environ.get("XINAO_RUN_F4_LIVE_PACK_INTEGRATION") != "1"
    or not subject.DEFAULT_PACK.is_dir(),
    reason="requires the retained local F4 live pack and canonical Temporal replay venv",
)
def test_retained_false_green_pack_is_rejected_before_history_replay() -> None:
    with pytest.raises(
        subject.VerificationError,
        match="external result runtime identity drifted",
    ):
        asyncio.run(subject.verify_live_pack(subject.DEFAULT_PACK))
