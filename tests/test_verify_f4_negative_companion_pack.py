from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import pytest
from scripts import verify_f4_negative_companion_pack as subject


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return path


def _minimal_manifest_pack(tmp_path: Path) -> tuple[Path, Path]:
    pack = tmp_path / "pack"
    report = _write(pack / "negative_companion_report.json", {"report": True})
    payload = _write(pack / "payload.bin", b"bound negative evidence")
    entries = []
    for path in (report, payload):
        entries.append(
            {
                "relative_path": path.relative_to(pack).as_posix(),
                "sha256": subject.file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    _write(
        pack / "artifact_manifest.json",
        {
            "schema_version": ("xinao.f4_negative_companion_artifact_manifest.v1"),
            "pack_ref": str(pack.resolve()),
            "report_ref": str(report.resolve()),
            "report_sha256": subject.file_sha256(report),
            "artifact_count": len(entries),
            "artifacts": entries,
        },
    )
    return pack, payload


def _isolated_runner_source(*, extra: str = "") -> str:
    return f"""
from temporalio.testing import WorkflowEnvironment
from scripts.run_foundation_v2_f4_live_canary import (
    RUNTIME, file_sha256, prepare_inputs, write_json
)

async def run_backpressure_case(*, client):
    await client.start_workflow(FoundationContinuousWorkflowV2.run)

async def run_partial_case(*, client):
    await client.start_workflow(FoundationContinuousWorkflowV2.run)

async def run_cancel_case(*, client):
    await client.start_workflow(FoundationWaveChildWorkflowV1.run)
    await client.start_workflow(FoundationContinuousWorkflowV2.run)
    await client.start_workflow(FoundationContinuousWorkflowV2.run)

async def run(pack):
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        await run_backpressure_case(client=environment.client)
        await run_partial_case(client=environment.client)
        await run_cancel_case(client=environment.client)

{extra}
"""


def _input_helper_source() -> str:
    return """
def file_sha256(path):
    return str(path)

def write_json(path, value):
    return path, value

def versioned_source_graph():
    return {}

def build_method():
    return {}

def prepare_inputs():
    graph = versioned_source_graph()
    method = build_method()
    write_json('input.json', {'graph': graph, 'method': method})
    return file_sha256('input.json')
"""


def test_content_addressed_assertion_recomputes() -> None:
    assertion = subject._assertion("example", [], {"count": 1})
    body = dict(assertion)
    recorded = body.pop("assertion_sha256")

    assert recorded == subject.canonical_sha256(body)
    assert assertion["evidence_set_sha256"] == subject.canonical_sha256([])


def test_manifest_verifies_exact_file_bytes(tmp_path: Path) -> None:
    pack, _ = _minimal_manifest_pack(tmp_path)
    manifest, manifest_path, paths, artifact_set_hash = subject._verify_manifest(pack)

    assert manifest["artifact_count"] == 2
    assert manifest_path == pack / "artifact_manifest.json"
    assert set(paths) == {"negative_companion_report.json", "payload.bin"}
    assert len(artifact_set_hash) == 64


def test_manifest_rejects_tampered_or_unlisted_bytes(tmp_path: Path) -> None:
    pack, payload = _minimal_manifest_pack(tmp_path)
    payload.write_bytes(b"tampered")
    with pytest.raises(subject.VerificationError, match="hash drifted"):
        subject._verify_manifest(pack)

    pack, _ = _minimal_manifest_pack(tmp_path / "second")
    _write(pack / "unlisted.txt", b"extra")
    with pytest.raises(subject.VerificationError, match="exact source file set"):
        subject._verify_manifest(pack)


def test_json_plain_payload_decodes_without_report_booleans() -> None:
    value = {"status": "STOPPED", "available_slots": 0}
    container = {
        "payloads": [
            {
                "metadata": {"encoding": base64.b64encode(b"json/plain").decode()},
                "data": base64.b64encode(
                    json.dumps(value, separators=(",", ":")).encode()
                ).decode(),
            }
        ]
    }

    assert subject._decode_payload_object(container, label="test") == value


def test_runner_isolation_requires_ephemeral_client_and_known_workflows(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(_isolated_runner_source(), encoding="utf-8")
    helper = tmp_path / "input_helper.py"
    helper.write_text(_input_helper_source(), encoding="utf-8")

    observed = subject._verify_runner_isolation(runner, helper)

    assert observed["ephemeral_environment_calls"] == 1
    assert observed["live_client_connect_calls"] == 0
    assert len(observed["started_workflow_classes"]) == 5


def test_runner_isolation_rejects_live_client_connect(tmp_path: Path) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(
        _isolated_runner_source(extra="Client.connect('localhost:7233')"),
        encoding="utf-8",
    )
    helper = tmp_path / "input_helper.py"
    helper.write_text(_input_helper_source(), encoding="utf-8")

    with pytest.raises(subject.VerificationError, match="live/process transport"):
        subject._verify_runner_isolation(runner, helper)


@pytest.mark.skipif(
    os.environ.get("XINAO_RUN_F4_NEGATIVE_PACK_INTEGRATION") != "1"
    or not subject.DEFAULT_PACK.is_dir(),
    reason="requires retained negative pack and Temporal replay environment",
)
def test_retained_negative_pack_replays_and_derives_all_cases() -> None:
    report = asyncio.run(subject.verify_negative_pack(subject.DEFAULT_PACK))
    repeated = asyncio.run(subject.verify_negative_pack(subject.DEFAULT_PACK))

    assert report["status"] == "VERIFIED"
    assert report == repeated
    assert "verified_at" not in report
    assert report["assertion_count"] == 6
    assert report["unclosed_items"] == []
    assert report["content_sha256"] == subject.canonical_sha256(
        {key: value for key, value in report.items() if key != "content_sha256"}
    )
    replay = report["assertions"]["three_cases_nine_histories_sdk_replay"]
    assert replay["observed"]["history_count"] == 9
    assert replay["observed"]["event_count"] == 385
    assert (
        report["assertions"]["available_slots_zero_backpressure"]["observed"]["dispatch_width"] == 0
    )
    assert (
        report["assertions"]["external_failure_partial_downshift_recovery"]["observed"][
            "recovery_dispatch_width"
        ]
        == 1
    )
