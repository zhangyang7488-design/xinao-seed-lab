from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "docker" / "xinao-researcher" / "entrypoint.py"
    spec = importlib.util.spec_from_file_location("xinao_researcher_entrypoint", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind_runtime_entrypoint_identity(module: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    observed = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    monkeypatch.setenv(module.ENTRYPOINT_SHA256_ENV, observed)
    return observed


def _host_module():
    path = ROOT / "skills" / "xinao" / "scripts" / "xinao_runtime.py"
    spec = importlib.util.spec_from_file_location("xinao_skill_material_host", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle(
    module: Any,
    root: Path,
    payloads: tuple[tuple[str, bytes], ...] = (("evidence.txt", b"bounded evidence\n"),),
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    root.mkdir()
    manifest_entries = []
    packet_materials = []
    for logical_name, payload in payloads:
        digest = hashlib.sha256(payload).hexdigest()
        entry = {
            "material_id": f"sha256:{digest}",
            "logical_name": logical_name,
            "relative_path": f"files/{digest}.utf8",
            "sha256": digest,
            "size_bytes": len(payload),
            "media_type": "text/plain",
            "encoding": "utf-8",
        }
        manifest_entries.append(entry)
        packet_materials.append(
            {
                "material_id": entry["material_id"],
                "logical_name": logical_name,
                "sha256": digest,
                "size_bytes": len(payload),
                "content": payload.decode("utf-8", errors="replace"),
            }
        )
    ordering = sorted(
        range(len(manifest_entries)),
        key=lambda index: (
            manifest_entries[index]["material_id"],
            manifest_entries[index]["logical_name"],
        ),
    )
    manifest_entries = [manifest_entries[index] for index in ordering]
    packet_materials = [packet_materials[index] for index in ordering]
    core = {
        "schema_version": "xinao.material_bundle.v1",
        "provider_disclosure_scope": "caller_supplied_for_bounded_research_episode",
        "materials": manifest_entries,
    }
    bundle_digest = hashlib.sha256(module._canonical_bytes(core)).hexdigest()
    manifest = {
        **core,
        "bundle_id": f"xinao-material-bundle-sha256:{bundle_digest}",
    }
    payload_by_digest = {hashlib.sha256(payload).hexdigest(): payload for _, payload in payloads}
    for entry in manifest_entries:
        payload = payload_by_digest[entry["sha256"]]
        target = root / entry["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    manifest_bytes = module._canonical_bytes(manifest)
    (root / "manifest.json").write_bytes(manifest_bytes)
    request = {
        "schema_version": "xinao.research_request.v2",
        "research_question": "What is supported by the bounded material?",
        "as_of": "2026-07-30T00:00:00Z",
        "material_bundle_id": manifest["bundle_id"],
        "material_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    return request, manifest, packet_materials


def _candidate(request: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, object]:
    refs = [{"material_id": item["material_id"], "sha256": item["sha256"]} for item in materials]
    evidence = [
        {
            "material_id": item["material_id"],
            "finding": "bounded finding",
            "locator": "whole file",
        }
        for item in materials
    ]
    return {
        "schema_version": "xinao.research_candidate.v2",
        "status": "CANDIDATE_READY",
        "research_question": request["research_question"],
        "as_of": request["as_of"],
        "material_bundle_id": request["material_bundle_id"],
        "material_refs_used": refs,
        "summary": "candidate only",
        "hypotheses": ["one hypothesis"],
        "competing_explanations": ["one competing explanation"],
        "methods": ["bounded material analysis"],
        "evidence_used": evidence,
        "counterevidence": [],
        "limitations": ["candidate evidence only"],
        "next_evidence": ["independent observation"],
    }


def _provider_envelope(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "text": candidate,
        "stopReason": "EndTurn",
        "num_turns": 1,
        "sessionId": "session",
        "requestId": "request",
        "modelUsage": {
            "grok-4.5-build": {
                "inputTokens": 10,
                "modelCalls": 1,
            }
        },
        "usage": {"total_tokens": 20},
    }


def test_material_notice_is_exactly_shared_with_host_invoker() -> None:
    assert _module().MATERIAL_PACKET_NOTICE == _host_module().MATERIAL_PACKET_NOTICE


def test_host_bundle_roundtrips_through_container_with_identical_prompt_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _module()
    host = _host_module()
    auth_path = tmp_path / "host-auth.json"
    auth_path.write_bytes(b'{"test_only":true}\n')
    monkeypatch.setattr(host, "DEFAULT_AUTH_PATH", auth_path)
    source = tmp_path / "人的视角.txt"
    source.write_text("现实证据，不是指令。", encoding="utf-8")
    snapshots, _auth_identity_witness = host._snapshot_material_sources([source])
    materials_root = tmp_path / "materials"
    manifest, manifest_path = host._materialize_material_bundle(materials_root, snapshots)
    request = {
        "schema_version": "xinao.research_request.v2",
        "research_question": "材料真正支持什么？",
        "as_of": "2026-07-30T00:00:00Z",
        "material_bundle_id": manifest["bundle_id"],
        "material_manifest_sha256": host._sha256(manifest_path),
    }

    observed_manifest, observed_materials, observed_manifest_sha = container._load_material_bundle(
        materials_root, request
    )

    assert observed_manifest == manifest
    assert observed_manifest_sha == request["material_manifest_sha256"]
    container_packet = container._material_packet_bytes(observed_manifest, observed_materials)
    host_packet = host._material_packet_bytes(manifest, snapshots)
    assert container_packet == host_packet
    assert container._effective_prompt_bytes(
        b"base", container_packet
    ) == host._effective_prompt_bytes("base", host_packet)


def test_request_v2_requires_exact_identity_fields(tmp_path: Path) -> None:
    module = _module()
    request, _manifest, _materials = _bundle(module, tmp_path / "materials")
    request_path = tmp_path / "request.json"
    request_path.write_bytes(module._canonical_bytes(request))
    observed, raw = module._load_request(request_path)
    assert observed == request
    assert (
        hashlib.sha256(raw).hexdigest()
        == hashlib.sha256(module._canonical_bytes(request)).hexdigest()
    )

    request["account"] = {"forbidden": True}
    request_path.write_bytes(module._canonical_bytes(request))
    with pytest.raises(module.InputValidationError) as failure:
        module._load_request(request_path)
    assert failure.value.reason_code == "REQUEST_FIELDS_INVALID"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"value":NaN}',
        b'{"value":1e9999}',
        b'{"value":1,"value":2}',
        b'{"value":' + (b"9" * 10000) + b"}",
        b'{"value":' + (b"[" * 2000) + b"0" + (b"]" * 2000) + b"}",
    ],
)
def test_json_object_rejects_nonfinite_huge_or_deep_json(payload: bytes) -> None:
    module = _module()
    with pytest.raises(module.InputValidationError) as failure:
        module._json_object(payload, reason_code="REQUEST_INVALID", detail="request")
    assert failure.value.reason_code == "REQUEST_INVALID"


def test_failure_receipt_sanitizes_escaped_lone_surrogate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    output_root = tmp_path / "output"
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)

    assert module._failure("MATERIAL_LOGICAL_NAME_INVALID", "bad-\ud800-name", exit_code=10) == 10

    result = json.loads((output_root / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "RUNTIME_FAILED"
    assert result["reason_codes"] == ["MATERIAL_LOGICAL_NAME_INVALID"]
    assert "\\ud800" in result["detail"]


def test_provider_metadata_rejects_noncanonical_unicode() -> None:
    module = _module()
    with pytest.raises(module.InputValidationError) as failure:
        module._provider_metadata_object({"bad": "\ud800"}, field="usage")
    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


def test_runtime_entrypoint_identity_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    _bind_runtime_entrypoint_identity(module, monkeypatch)
    module._validate_runtime_entrypoint_identity()

    monkeypatch.delenv(module.ENTRYPOINT_SHA256_ENV)
    with pytest.raises(module.InputValidationError) as missing:
        module._validate_runtime_entrypoint_identity()
    assert missing.value.reason_code == "ENTRYPOINT_IDENTITY_INVALID"

    monkeypatch.setenv(module.ENTRYPOINT_SHA256_ENV, "0" * 64)
    with pytest.raises(module.InputValidationError) as failure:
        module._validate_runtime_entrypoint_identity()
    assert failure.value.reason_code == "ENTRYPOINT_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    ("expected", "reason_code"),
    ((None, "ENTRYPOINT_IDENTITY_INVALID"), ("0" * 64, "ENTRYPOINT_IDENTITY_MISMATCH")),
)
def test_main_rejects_missing_or_mismatched_entrypoint_identity_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    expected: str | None,
    reason_code: str,
) -> None:
    module = _module()
    output_root = tmp_path / "output"
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)
    if expected is None:
        monkeypatch.delenv(module.ENTRYPOINT_SHA256_ENV, raising=False)
    else:
        monkeypatch.setenv(module.ENTRYPOINT_SHA256_ENV, expected)
    monkeypatch.setattr(
        module.__dict__["sub" + "process"],
        "run",
        lambda *_args, **_kwargs: pytest.fail("model must not be invoked"),
    )

    assert module.main() == 10

    result = json.loads((output_root / "result.json").read_text(encoding="utf-8"))
    assert result["reason_codes"] == [reason_code]
    assert capsys.readouterr().out == ""


def test_provider_effect_accepts_only_bound_terminal_evidence() -> None:
    module = _module()
    effect = module._validate_provider_effect(_provider_envelope({"candidate": True}))

    assert effect["stop_reason"] == "EndTurn"
    assert effect["num_turns"] == 1
    assert effect["session_id"] == "session"
    assert effect["request_id"] == "request"
    assert effect["observed_model_id"] == "grok-4.5-build"
    assert effect["model_calls"] == 1
    assert effect["usage"] == {"total_tokens": 20}


@pytest.mark.parametrize("value", (None, "Cancelled", "", 1))
def test_provider_effect_requires_exact_end_turn(value: object) -> None:
    module = _module()
    provider = _provider_envelope({"candidate": True})
    provider["stopReason"] = value

    with pytest.raises(module.InputValidationError) as failure:
        module._validate_provider_effect(provider)

    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("value", (None, True, False, 0, 2, 1.0, "1"))
def test_provider_effect_requires_exact_one_integer_turn(value: object) -> None:
    module = _module()
    provider = _provider_envelope({"candidate": True})
    provider["num_turns"] = value

    with pytest.raises(module.InputValidationError) as failure:
        module._validate_provider_effect(provider)

    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("field", ("sessionId", "requestId"))
@pytest.mark.parametrize(
    "value",
    (None, "", "   ", "bad\x00id", "bad-\ud800-id", 1, "x" * 4097),
)
def test_provider_effect_requires_bounded_utf8_nonempty_ids(field: str, value: object) -> None:
    module = _module()
    provider = _provider_envelope({"candidate": True})
    provider[field] = value

    with pytest.raises(module.InputValidationError) as failure:
        module._validate_provider_effect(provider)

    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize(
    "model_usage",
    (
        {},
        {"grok-4.5": {"modelCalls": 1}},
        {"fake": {"modelCalls": 1}},
        {
            "grok-4.5-build": {"modelCalls": 1},
            "fake": {"modelCalls": 1},
        },
        {"grok-4.5-build": []},
        {"grok-4.5-build": {}},
        {"grok-4.5-build": {"modelCalls": True}},
        {"grok-4.5-build": {"modelCalls": 0}},
        {"grok-4.5-build": {"modelCalls": 1.0}},
        {"grok-4.5-build": {"modelCalls": "1"}},
    ),
)
def test_provider_effect_rejects_fake_multiple_or_invalid_model_usage(
    model_usage: object,
) -> None:
    module = _module()
    provider = _provider_envelope({"candidate": True})
    provider["modelUsage"] = model_usage

    with pytest.raises(module.InputValidationError) as failure:
        module._validate_provider_effect(provider)

    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("value", (None, True, False, 0, -1, 1.0, "1"))
def test_provider_effect_requires_positive_exact_integer_total_tokens(value: object) -> None:
    module = _module()
    provider = _provider_envelope({"candidate": True})
    provider["usage"] = {"total_tokens": value}

    with pytest.raises(module.InputValidationError) as failure:
        module._validate_provider_effect(provider)

    assert failure.value.reason_code == "MODEL_OUTPUT_INVALID"


def test_malformed_output_schema_fails_before_model_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    materials_root = tmp_path / "materials"
    input_root.mkdir()
    output_root.mkdir()
    request, _manifest, _materials = _bundle(module, materials_root, payloads=())
    (input_root / "request.json").write_bytes(module._canonical_bytes(request))
    (input_root / "prompt.md").write_text("base prompt", encoding="utf-8")
    (input_root / "output.schema.json").write_text(
        '{"type":"object","type":"array"}', encoding="utf-8"
    )

    monkeypatch.setattr(module, "INPUT_ROOT", input_root)
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(module, "MATERIALS_ROOT", materials_root)
    monkeypatch.setattr(module, "EFFECTIVE_PROMPT_PATH", tmp_path / "effective-prompt.md")
    _bind_runtime_entrypoint_identity(module, monkeypatch)
    monkeypatch.setattr(
        module.__dict__["sub" + "process"],
        "run",
        lambda *_args, **_kwargs: pytest.fail("model must not be invoked"),
    )

    assert module.main() == 10
    result = json.loads((output_root / "result.json").read_text(encoding="utf-8"))
    assert result["reason_codes"] == ["OUTPUT_SCHEMA_INVALID"]


def test_bundle_is_recomputed_and_normalized_into_model_packet(tmp_path: Path) -> None:
    module = _module()
    request, manifest, expected_materials = _bundle(
        module,
        tmp_path / "materials",
        (("b.txt", "beta".encode()), ("a.txt", "α".encode())),
    )

    observed_manifest, observed_materials, manifest_sha256 = module._load_material_bundle(
        tmp_path / "materials", request
    )
    packet = json.loads(module._material_packet_bytes(observed_manifest, observed_materials))

    assert observed_manifest == manifest
    assert observed_materials == expected_materials
    assert manifest_sha256 == request["material_manifest_sha256"]
    assert packet == {
        "schema_version": "xinao.model_material_packet.v1",
        "bundle_id": manifest["bundle_id"],
        "materials": expected_materials,
    }


def test_bundle_rejects_core_hash_drift(tmp_path: Path) -> None:
    module = _module()
    root = tmp_path / "materials"
    request, manifest, _materials = _bundle(module, root)
    replacement = "0" if manifest["bundle_id"][-1] != "0" else "1"
    manifest["bundle_id"] = manifest["bundle_id"][:-1] + replacement
    manifest_bytes = module._canonical_bytes(manifest)
    (root / "manifest.json").write_bytes(manifest_bytes)
    request["material_bundle_id"] = manifest["bundle_id"]
    request["material_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()

    with pytest.raises(module.InputValidationError) as failure:
        module._load_material_bundle(root, request)

    assert failure.value.reason_code == "MATERIAL_BUNDLE_CORE_HASH_INVALID"


def test_bundle_rejects_content_tampering_and_extra_files(tmp_path: Path) -> None:
    module = _module()
    tampered_root = tmp_path / "tampered"
    request, manifest, _materials = _bundle(module, tampered_root)
    (tampered_root / manifest["materials"][0]["relative_path"]).write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(module.InputValidationError) as tampered:
        module._load_material_bundle(tampered_root, request)
    assert tampered.value.reason_code in {"MATERIAL_SIZE_MISMATCH", "MATERIAL_SHA256_MISMATCH"}

    extra_root = tmp_path / "extra"
    request, _manifest, _materials = _bundle(module, extra_root)
    (extra_root / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(module.InputValidationError) as extra:
        module._load_material_bundle(extra_root, request)
    assert extra.value.reason_code == "MATERIAL_FILE_SET_INVALID"


@pytest.mark.parametrize("payload", (b"bad\x00text", b"\xff\xfe"))
def test_bundle_rejects_nul_and_non_utf8_material(tmp_path: Path, payload: bytes) -> None:
    module = _module()
    root = tmp_path / hashlib.sha256(payload).hexdigest()
    request, _manifest, _materials = _bundle(module, root, (("bad.txt", payload),))

    with pytest.raises(module.InputValidationError) as failure:
        module._load_material_bundle(root, request)

    assert failure.value.reason_code == "MATERIAL_TEXT_INVALID"


def test_candidate_accepts_exact_research_only_v2_output(tmp_path: Path) -> None:
    module = _module()
    request, _manifest, expected_materials = _bundle(module, tmp_path / "materials")
    candidate = _candidate(request, expected_materials)

    assert module._valid_candidate(candidate, request=request, materials=expected_materials) is True


@pytest.mark.parametrize(
    "forbidden_field",
    ("account", "settlement", "current_action_projection", "science_restored"),
)
def test_candidate_rejects_hidden_effect_or_action_fields(
    tmp_path: Path, forbidden_field: str
) -> None:
    module = _module()
    request, _manifest, expected_materials = _bundle(module, tmp_path / "materials")
    candidate = _candidate(request, expected_materials)
    candidate[forbidden_field] = {"forbidden": True}

    assert (
        module._valid_candidate(candidate, request=request, materials=expected_materials) is False
    )


def test_candidate_rejects_request_drift_and_unbound_material_use(tmp_path: Path) -> None:
    module = _module()
    request, _manifest, expected_materials = _bundle(module, tmp_path / "materials")
    drifted = _candidate(request, expected_materials)
    drifted["as_of"] = "different"
    assert module._valid_candidate(drifted, request=request, materials=expected_materials) is False

    unbound = _candidate(request, expected_materials)
    unbound["material_refs_used"] = []
    unbound["evidence_used"] = []
    assert module._valid_candidate(unbound, request=request, materials=expected_materials) is False

    no_evidence = _candidate(request, expected_materials)
    no_evidence["evidence_used"] = []
    assert (
        module._valid_candidate(no_evidence, request=request, materials=expected_materials) is False
    )


def test_candidate_rejects_unknown_or_unclaimed_evidence_reference(tmp_path: Path) -> None:
    module = _module()
    request, _manifest, expected_materials = _bundle(
        module,
        tmp_path / "materials",
        (("first.txt", b"first"), ("second.txt", b"second")),
    )
    candidate = _candidate(request, expected_materials)
    candidate["material_refs_used"] = candidate["material_refs_used"][:1]
    candidate["evidence_used"] = candidate["evidence_used"][1:]

    assert (
        module._valid_candidate(candidate, request=request, materials=expected_materials) is False
    )

    missing_claimed_evidence = _candidate(request, expected_materials)
    missing_claimed_evidence["evidence_used"] = missing_claimed_evidence["evidence_used"][:1]
    assert (
        module._valid_candidate(
            missing_claimed_evidence,
            request=request,
            materials=expected_materials,
        )
        is False
    )


def test_empty_bundle_requires_empty_material_and_evidence_refs(tmp_path: Path) -> None:
    module = _module()
    request, _manifest, expected_materials = _bundle(module, tmp_path / "materials", payloads=())
    candidate = _candidate(request, expected_materials)
    candidate["status"] = "INSUFFICIENT_EVIDENCE"

    assert module._valid_candidate(candidate, request=request, materials=expected_materials) is True


def test_main_writes_bound_v2_result_and_keeps_model_tool_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    materials_root = tmp_path / "materials"
    input_root.mkdir()
    output_root.mkdir()
    request, manifest, expected_materials = _bundle(module, materials_root)
    request_bytes = module._canonical_bytes(request)
    base_prompt = b"base prompt"
    schema = (
        ROOT / "skills" / "xinao" / "references" / "researcher-output.v2.schema.json"
    ).read_bytes()
    schema_value = json.loads(schema)
    Draft202012Validator.check_schema(schema_value)
    (input_root / "request.json").write_bytes(request_bytes)
    (input_root / "prompt.md").write_bytes(base_prompt)
    (input_root / "output.schema.json").write_bytes(schema)
    candidate = _candidate(request, expected_materials)
    Draft202012Validator(schema_value).validate(candidate)
    provider = _provider_envelope(candidate)
    observed_commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        observed_commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(provider),
            stderr="",
        )

    effective_prompt_path = tmp_path / "tmp" / "effective-prompt.md"
    monkeypatch.setattr(module, "INPUT_ROOT", input_root)
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(module, "MATERIALS_ROOT", materials_root)
    monkeypatch.setattr(module, "EFFECTIVE_PROMPT_PATH", effective_prompt_path)
    monkeypatch.setattr(module.__dict__["sub" + "process"], "run", fake_run)
    _bind_runtime_entrypoint_identity(module, monkeypatch)

    assert module.main() == 0

    packet = module._material_packet_bytes(manifest, expected_materials)
    effective_prompt = module._effective_prompt_bytes(base_prompt, packet)
    assert effective_prompt_path.read_bytes() == effective_prompt
    command = observed_commands[0]
    assert command[command.index("--prompt-file") + 1] == str(effective_prompt_path)
    assert command[command.index("--model") + 1] == "grok-4.5"
    assert command[command.index("--max-turns") + 1] == "1"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--json-schema") + 1] == schema.decode("utf-8")
    assert "--no-subagents" in command
    assert "--no-memory" in command
    assert "--disable-web-search" in command

    result_bytes = (output_root / "result.json").read_bytes()
    result = json.loads(result_bytes)
    assert result["schema_version"] == "xinao.researcher_container_result.v2"
    assert result["material_bundle_id"] == manifest["bundle_id"]
    assert result["material_manifest_sha256"] == request["material_manifest_sha256"]
    assert result["material_packet_sha256"] == hashlib.sha256(packet).hexdigest()
    assert result["effective_prompt_sha256"] == hashlib.sha256(effective_prompt).hexdigest()
    assert result["material_refs_available"] == sorted(
        item["material_id"] for item in expected_materials
    )
    assert result["completion_claim_allowed"] is False
    assert result["science_restored"] is False
    assert result["parent_complete"] is False
    assert result["provider_session_id"] == "session"
    assert result["provider_request_id"] == "request"
    Draft202012Validator(schema_value).validate(result["candidate"])

    terminal_bytes = capsys.readouterr().out.encode("utf-8")
    terminal = json.loads(terminal_bytes)
    assert terminal_bytes == module._canonical_bytes(terminal)
    assert len(terminal_bytes) <= module.MAX_TERMINAL_ATTESTATION_BYTES
    assert set(terminal) == {
        "schema_version",
        "status",
        "result_sha256",
        "request_sha256",
        "observed_model_id",
        "observed_model_calls",
    }
    assert "provider_session_id" not in terminal
    assert "provider_request_id" not in terminal
    assert terminal == {
        "schema_version": "xinao.researcher_terminal_attestation.v1",
        "status": "CANDIDATE_READY",
        "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "observed_model_id": "grok-4.5-build",
        "observed_model_calls": 1,
    }


def test_terminal_attestation_is_emitted_after_atomic_result_and_exposes_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    output_root = tmp_path / "output"
    output_root.mkdir()
    emitted: list[bytes] = []
    events: list[str] = []
    result_path = output_root / "result.json"
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)
    result = {
        "schema_version": "xinao.researcher_container_result.v2",
        "status": "CANDIDATE_READY",
    }
    expected_result_bytes = module._canonical_bytes(result)
    original_replace = os.replace

    def spy_replace(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path != destination_path
        assert source_path.parent == output_root
        original_replace(source, destination)
        if destination_path == result_path:
            events.append("atomic_replace")

    def capture_terminal(payload: bytes) -> None:
        assert result_path.read_bytes() == expected_result_bytes
        events.append("terminal_emit")
        emitted.append(payload)

    monkeypatch.setattr(module.os, "replace", spy_replace)
    monkeypatch.setattr(module, "_emit_terminal_bytes", capture_terminal)

    module._write_result_and_attestation(
        result,
        request_sha256="a" * 64,
        observed_model_id="grok-4.5-build",
        observed_model_calls=1,
    )

    result_bytes = result_path.read_bytes()
    assert result_bytes == expected_result_bytes
    assert events == ["atomic_replace", "terminal_emit"]
    assert len(emitted) == 1
    terminal = json.loads(emitted[0])
    assert emitted[0] == module._canonical_bytes(terminal)
    assert terminal["result_sha256"] == hashlib.sha256(result_bytes).hexdigest()
    result_path.write_bytes(b'{"status":"tampered"}\n')
    assert terminal["result_sha256"] != hashlib.sha256(result_path.read_bytes()).hexdigest()


def test_main_returns_structured_failure_for_provider_surrogate_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    materials_root = tmp_path / "materials"
    input_root.mkdir()
    output_root.mkdir()
    request, _manifest, expected_materials = _bundle(module, materials_root)
    (input_root / "request.json").write_bytes(module._canonical_bytes(request))
    (input_root / "prompt.md").write_text("base prompt", encoding="utf-8")
    (input_root / "output.schema.json").write_bytes(
        (ROOT / "skills" / "xinao" / "references" / "researcher-output.v2.schema.json").read_bytes()
    )
    provider = {
        "text": _candidate(request, expected_materials),
        "stopReason": "bad-\ud800-stop",
    }

    def fake_run(_command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=json.dumps(provider), stderr="")

    monkeypatch.setattr(module, "INPUT_ROOT", input_root)
    monkeypatch.setattr(module, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(module, "MATERIALS_ROOT", materials_root)
    monkeypatch.setattr(module, "EFFECTIVE_PROMPT_PATH", tmp_path / "effective-prompt.md")
    monkeypatch.setattr(module.__dict__["sub" + "process"], "run", fake_run)
    _bind_runtime_entrypoint_identity(module, monkeypatch)

    assert module.main() == 40
    result = json.loads((output_root / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "RUNTIME_FAILED"
    assert result["reason_codes"] == ["MODEL_OUTPUT_INVALID"]
    assert capsys.readouterr().out == ""


def test_dockerfile_binds_material_schema_identity() -> None:
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG MATERIAL_BUNDLE_SCHEMA_SHA256" in dockerfile
    assert (
        'io.xinao.researcher.material-bundle-schema.sha256="${MATERIAL_BUNDLE_SCHEMA_SHA256}"'
        in dockerfile
    )


def test_dockerfile_binds_source_and_entrypoint_identity() -> None:
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(encoding="utf-8")
    for argument in (
        "DOCKERFILE_SHA256",
        "ENTRYPOINT_SHA256",
        "SOURCE_IDENTITY_SHA256",
        "REQUESTED_MODEL",
    ):
        assert f"ARG {argument}" in dockerfile
    assert 'io.xinao.researcher.dockerfile.sha256="${DOCKERFILE_SHA256}"' in dockerfile
    assert 'io.xinao.researcher.entrypoint.sha256="${ENTRYPOINT_SHA256}"' in dockerfile
    assert 'io.xinao.researcher.source-identity.sha256="${SOURCE_IDENTITY_SHA256}"' in dockerfile
    assert 'io.xinao.researcher.requested-model="${REQUESTED_MODEL}"' in dockerfile
    assert "sha256sum" in dockerfile
    assert "/opt/xinao-researcher/entrypoint.py" in dockerfile
    assert "ENTRYPOINT_SHA256" in dockerfile
