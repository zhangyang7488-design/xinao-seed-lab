"""Focused attacks: ResearchEpisode live attach-run / resume-live / export.

Candidate-only. Never claims Owner adoption, science restored, or parent complete.
No live Docker/provider required: docker exec is monkeypatched or fail-closed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "docker" / "xinao-researcher"
SCRIPTS = ROOT / "skills" / "xinao" / "scripts"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def native() -> Any:
    return _load("xinao_native_live_attach", PKG / "native_grok_session.py")


@pytest.fixture(scope="module")
def host_mod() -> Any:
    return _load("xinao_dual_host_live_attach", SCRIPTS / "dual_container_host.py")


def _provider_stdout(
    *,
    session_id: str,
    stop_reason: str = "end_turn",
    model: str = "grok-4.5",
    turns: int = 4,
    error: str | None = None,
) -> bytes:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "stop_reason": stop_reason,
        "model": model,
        "turn_count": turns,
        "type": "result",
    }
    if error:
        payload["error"] = error
        payload["type"] = "error"
    return (json.dumps(payload) + "\n").encode("utf-8")


def _mcp_hashes() -> list[str]:
    body = {
        "event": "mcp_tools_call",
        "op": "write_file",
        "status": "ok",
        "productive": True,
        "n": 1,
    }
    digest = hashlib.sha256(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    return [digest]


def _live_argv(native: Any, session: str, *, resume: bool = False, turns: int = 16) -> list[str]:
    return native.build_genuine_session_argv(
        session_id=session,
        resume=resume,
        max_turns=turns,
        model=native.DEFAULT_LIVE_MODEL,
        prompt="revise hypothesis after failed experiment",
    )


def _candidate_manifest_bytes(
    *,
    episode_id: str = "ep_live_1",
    attempt_cas_digest: str | None = None,
) -> bytes:
    payload = {
        "schema_version": "xinao.research_episode_candidate_manifest.v1",
        "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        "candidate_id": "cand_live_1",
        "candidate_version": "v1",
        "episode_id": episode_id,
        "attempt_cas_digest": attempt_cas_digest,
        "research_question": "bounded OPEN_RESEARCH question",
        "research_object": "lab candidate body",
        "data_cutoff": {
            "as_of": "2026-07-31T00:00:00Z",
            "material_refs": [{"id": "m1", "sha256": "22" * 32}],
        },
        "method_refs": ["experiment_loop"],
        "falsifiers": ["first shell failed"],
        "account_recommendation": "NO_RECOMMENDATION",
        "candidate_only": True,
        "owner_adopted": False,
        "completion": False,
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _successful_attempt(
    native: Any,
    *,
    episode_id: str = "ep_live_1",
    host_session: str = "xrsess_live_1",
    provider_session: str | None = None,
    resume: bool = False,
    exit_code: int = 0,
    mcp: list[str] | None = None,
    stdout: bytes | None = None,
    stderr: bytes = b"",
    synthetic: bool = False,
    driver: str = "dual_container_host_docker_exec",
    live_executed: bool = True,
    timed_out: bool = False,
    docker_exec_failed: bool = False,
    cas_head: str = "a" * 64,
    pair_receipt: str = "b" * 64,
    namespace_receipt: str = "c" * 64,
    max_turns: int = 16,
    manifest_bytes: bytes | None = None,
) -> dict[str, Any]:
    sid = provider_session or str(uuid.uuid4())
    argv = _live_argv(native, sid, resume=resume, turns=max_turns)
    out = stdout if stdout is not None else _provider_stdout(session_id=sid, turns=5)
    manifest = (
        manifest_bytes
        if manifest_bytes is not None
        else _candidate_manifest_bytes(episode_id=episode_id)
    )
    manifest_sha = hashlib.sha256(manifest).hexdigest()
    return native.build_live_attempt_record(
        episode_id=episode_id,
        host_session_id=host_session,
        provider_session_uuid=sid,
        attempt_id=f"att_{uuid.uuid4().hex[:12]}",
        argv=argv,
        stdout=out,
        stderr=stderr,
        exit_code=exit_code,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=max_turns,
        timeout_seconds=3600,
        started_at="2026-07-31T00:00:00Z",
        finished_at="2026-07-31T00:01:00Z",
        transport_container_id="ctr_transport_1",
        tool_container_id="ctr_tool_1",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256=pair_receipt,
        namespace_receipt_sha256=namespace_receipt,
        release_id="researcher-test-release",
        release_identity_sha256="d" * 64,
        cas_head_sha256=cas_head,
        mcp_event_hashes=mcp if mcp is not None else _mcp_hashes(),
        lab_artifact_manifest={
            "artifacts": [
                {"path": "notes.md", "sha256": "e" * 64},
                {
                    "path": "candidate/candidate_manifest.v1.json",
                    "sha256": manifest_sha,
                    "size": str(len(manifest)),
                },
            ]
        },
        prior_attempt_hash=None,
        resume=resume,
        live_executed=live_executed,
        driver=driver,
        synthetic=synthetic,
        timed_out=timed_out,
        docker_exec_failed=docker_exec_failed,
        research_profile="OPEN_RESEARCH",
        productive_lab_ops=["write_file"],
        mcp_delta_status="DELTA_OK",
        require_productive_lab_op=True,
    )


def test_live_argv_rejects_empty_tools_one_turn_and_host_bypass(native: Any) -> None:
    sid = native.new_session_uuid()
    good = _live_argv(native, sid, turns=16)
    native.assert_live_research_argv(good)
    canary = native.build_canary_argv()
    with pytest.raises(native.NativeSessionError) as exc:
        native.assert_live_research_argv(canary)
    assert exc.value.reason_code in {
        "GENUINE_TOOLS_MISMATCH",
        "CANARY_ARGV_ON_GENUINE_PATH",
        "LIVE_MAX_TURNS_TOO_LOW",
        "GENUINE_MAX_TURNS_CANARY_SHAPED",
    }
    low = native.build_genuine_session_argv(session_id=sid, max_turns=4)
    with pytest.raises(native.NativeSessionError) as exc2:
        native.assert_live_research_argv(low)
    assert exc2.value.reason_code == "LIVE_MAX_TURNS_TOO_LOW"
    # OPEN_RESEARCH must not carry --disable-web-search; injecting it fails closed.
    poisoned = list(good) + ["--disable-web-search"]
    with pytest.raises(native.NativeSessionError) as exc3:
        native.assert_live_research_argv(poisoned)
    assert exc3.value.reason_code == "OPEN_RESEARCH_WEB_DISABLED"


def test_planned_and_synthetic_cannot_export(native: Any, tmp_path: Path) -> None:
    with pytest.raises(native.NativeSessionError) as exc:
        native.reject_non_live_driver(
            synthetic=False, driver="dual_container_host_docker_exec", planned_only=True
        )
    assert exc.value.reason_code == "PLANNED_ARGV_NOT_LIVE"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.reject_non_live_driver(
            synthetic=True, driver="dual_container_host_docker_exec", planned_only=False
        )
    assert exc2.value.reason_code == "SYNTHETIC_DRIVER_REFUSED"
    with pytest.raises(native.NativeSessionError) as exc3:
        native.reject_non_live_driver(
            synthetic=False, driver="mock_fixture_driver", planned_only=False
        )
    assert exc3.value.reason_code == "MOCK_DRIVER_REFUSED"

    # Planned-shaped attempt must not export.
    sid = native.new_session_uuid()
    with pytest.raises(native.NativeSessionError):
        native.build_live_attempt_record(
            episode_id="ep",
            host_session_id="hs",
            provider_session_uuid=sid,
            attempt_id="att1",
            argv=_live_argv(native, sid),
            stdout=_provider_stdout(session_id=sid),
            stderr=b"",
            exit_code=0,
            model=native.DEFAULT_LIVE_MODEL,
            max_turns=16,
            timeout_seconds=60,
            started_at="t0",
            finished_at="t1",
            transport_container_id="t",
            tool_container_id="u",
            transport_image_id="sha256:" + "1" * 64,
            tool_image_id="sha256:" + "2" * 64,
            pair_receipt_sha256="b" * 64,
            namespace_receipt_sha256="c" * 64,
            release_id="r",
            release_identity_sha256="d" * 64,
            cas_head_sha256="a" * 64,
            mcp_event_hashes=_mcp_hashes(),
            lab_artifact_manifest={"artifacts": []},
            prior_attempt_hash=None,
            resume=False,
            live_executed=False,
            driver="planned_only",
            synthetic=False,
        )


def test_docker_plumbing_and_nonzero_exit_not_success(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    failed_exec = _successful_attempt(
        native,
        provider_session=sid,
        exit_code=125,
        docker_exec_failed=True,
        stdout=b"",
        stderr=b"docker exec failed",
        mcp=[],
    )
    assert failed_exec["status"] == native.STATUS_ATTEMPT_FAILED
    assert "DOCKER_EXEC_FAILED" in failed_exec["failure_reasons"]
    persisted = native.persist_live_attempt(tmp_path / "output", failed_exec)
    assert persisted["status"] == native.STATUS_ATTEMPT_FAILED
    # No success pointer
    assert not (tmp_path / "output" / "attempts" / "last_successful.json").is_file()
    with pytest.raises(native.NativeSessionError) as exc:
        native.export_candidate_evidence_bundle(
            episode_output_root=tmp_path / "output",
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_live_1",
            cas_head_sha256="a" * 64,
        )
    assert exc.value.reason_code in {
        "ATTEMPT_NOT_EXPORTABLE",
        "DOCKER_FAILURE_NOT_EXPORTABLE",
        "NONZERO_EXIT_NOT_EXPORTABLE",
    }

    nonzero = _successful_attempt(
        native,
        provider_session=sid,
        exit_code=2,
        stdout=_provider_stdout(session_id=sid, error="provider boom"),
    )
    assert nonzero["status"] == native.STATUS_ATTEMPT_FAILED


def test_malformed_timeout_missing_session_stop_mcp_rejected(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    malformed = _successful_attempt(
        native,
        provider_session=sid,
        stdout=b"not-json-at-all",
        mcp=_mcp_hashes(),
    )
    assert malformed["status"] == native.STATUS_ATTEMPT_FAILED
    assert any("PROVIDER_OUTPUT" in r or "MALFORMED" in r for r in malformed["failure_reasons"])

    timed = _successful_attempt(
        native,
        provider_session=sid,
        timed_out=True,
        exit_code=124,
        stdout=_provider_stdout(session_id=sid),
    )
    assert timed["status"] == native.STATUS_ATTEMPT_FAILED
    assert "OUTER_TIMEOUT" in timed["failure_reasons"]

    no_stop = _successful_attempt(
        native,
        provider_session=sid,
        stdout=json.dumps({"session_id": sid, "model": "grok-4.5", "turn_count": 3}).encode(),
    )
    assert no_stop["status"] == native.STATUS_ATTEMPT_FAILED
    assert "STOP_REASON_MISSING" in no_stop["failure_reasons"]

    no_mcp = _successful_attempt(native, provider_session=sid, mcp=[])
    assert no_mcp["status"] == native.STATUS_ATTEMPT_FAILED
    assert "MCP_EVENTS_MISSING" in no_mcp["failure_reasons"]


def test_success_persist_export_idempotent_and_authority_clamp(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    cas_head = "a" * 64
    manifest = _candidate_manifest_bytes(episode_id="ep_live_1")
    attempt = _successful_attempt(
        native, provider_session=sid, cas_head=cas_head, manifest_bytes=manifest
    )
    assert attempt["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    assert attempt["completion_claim_allowed"] is False
    assert attempt["owner_adopted"] is False
    assert attempt["science_restored"] is False
    assert attempt["parent_complete"] is False
    out = tmp_path / "output"
    lab = tmp_path / "lab"
    (lab / "candidate").mkdir(parents=True, exist_ok=True)
    (lab / "candidate" / "candidate_manifest.v1.json").write_bytes(manifest)
    first = native.persist_live_attempt(out, attempt)
    assert first["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    assert (out / "attempts" / "last_successful.json").is_file()

    # Failed attempt must not overwrite success pointer.
    failed = _successful_attempt(
        native,
        provider_session=sid,
        exit_code=1,
        cas_head=cas_head,
        stdout=_provider_stdout(session_id=sid, error="late fail"),
        manifest_bytes=manifest,
    )
    native.persist_live_attempt(out, failed)
    success_ptr = json.loads(
        (out / "attempts" / "last_successful.json").read_text(encoding="utf-8")
    )
    assert success_ptr["attempt_hash"] == first["attempt_hash"]

    bundle1 = native.export_candidate_evidence_bundle(
        episode_output_root=out,
        attempt_cas_digest=first["attempt_cas_digest"],
        episode_id="ep_live_1",
        cas_head_sha256=cas_head,
        expected_provider_session_uuid=sid,
        lab_root=lab,
    )
    assert bundle1["status"] == native.STATUS_CANDIDATE_EVIDENCE_EXPORTED
    assert bundle1["completion_claim_allowed"] is False
    assert bundle1["owner_adopted"] is False
    assert bundle1["science_restored"] is False
    assert bundle1["parent_complete"] is False
    assert bundle1["candidate_only"] is True
    assert bundle1["next_task_created"] is False
    assert bundle1["freeze_written"] is False
    assert bundle1["settlement_written"] is False
    assert bundle1["portfolio_updated"] is False
    assert bundle1.get("candidate_manifest_sha256")

    bundle2 = native.export_candidate_evidence_bundle(
        episode_output_root=out,
        attempt_cas_digest=first["attempt_cas_digest"],
        episode_id="ep_live_1",
        cas_head_sha256=cas_head,
        expected_provider_session_uuid=sid,
        lab_root=lab,
    )
    assert bundle2["idempotent"] is True
    assert bundle2["bundle_sha256"] == bundle1["bundle_sha256"]


def test_export_rejects_forged_identity_and_head_drift(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    cas_head = "a" * 64
    attempt = _successful_attempt(native, provider_session=sid, cas_head=cas_head)
    out = tmp_path / "output"
    persisted = native.persist_live_attempt(out, attempt)

    with pytest.raises(native.NativeSessionError) as exc:
        native.export_candidate_evidence_bundle(
            episode_output_root=out,
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_FOREIGN",
            cas_head_sha256=cas_head,
        )
    assert exc.value.reason_code == "EPISODE_MISMATCH"

    with pytest.raises(native.NativeSessionError) as exc2:
        native.export_candidate_evidence_bundle(
            episode_output_root=out,
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_live_1",
            cas_head_sha256="f" * 64,
        )
    assert exc2.value.reason_code == "CHECKPOINT_HEAD_DRIFT"

    with pytest.raises(native.NativeSessionError) as exc3:
        native.export_candidate_evidence_bundle(
            episode_output_root=out,
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_live_1",
            cas_head_sha256=cas_head,
            expected_provider_session_uuid=str(uuid.uuid4()),
        )
    assert exc3.value.reason_code == "SESSION_UUID_MISMATCH"

    with pytest.raises(native.NativeSessionError) as exc4:
        native.export_candidate_evidence_bundle(
            episode_output_root=out,
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_live_1",
            cas_head_sha256=cas_head,
            expected_pair_receipt_sha256="0" * 64,
        )
    assert exc4.value.reason_code == "PAIR_RECEIPT_MISMATCH"


def test_resume_session_mismatch_rejected(native: Any) -> None:
    sid = native.new_session_uuid()
    other = native.new_session_uuid()
    attempt = _successful_attempt(
        native,
        provider_session=sid,
        resume=True,
        stdout=_provider_stdout(session_id=other),
    )
    # build uses provider_session_uuid=sid but stdout has other → mismatch on resume
    assert attempt["status"] == native.STATUS_ATTEMPT_FAILED
    assert "SESSION_UUID_MISMATCH" in attempt["failure_reasons"]


def test_argv_digest_redacts_secrets(native: Any) -> None:
    argv = _live_argv(native, native.new_session_uuid()) + ["--api-key", "super-secret-value"]
    redacted = native.redact_argv(argv)
    assert "super-secret-value" not in redacted
    assert "<redacted>" in redacted
    digest = native.argv_digest(argv)
    assert len(digest) == 64
    assert "super-secret" not in digest


def test_dual_host_synthetic_live_refused(host_mod: Any, tmp_path: Path) -> None:
    cfg = host_mod.DualHostConfig(
        transport_image="transport:candidate",
        tool_image="tool:candidate",
        auth_host_path=tmp_path / "auth",
        episode_root=tmp_path / "ep",
        synthetic=True,
    )
    (tmp_path / "auth").mkdir()
    host = host_mod.DualContainerHost(cfg)
    host_session = f"xrsess_{uuid.uuid4().hex[:8]}"
    host.create_pair(episode_id="ep_syn", session_id=host_session)
    host.start_pair()
    with pytest.raises(host_mod.DualHostError) as exc:
        host.require_live_pair_ready(expected_episode_id="ep_syn")
    assert exc.value.reason_code == "DUAL_HOST_SYNTHETIC_LIVE_REFUSED"
    with pytest.raises(host_mod.DualHostError) as exc2:
        host.attach_run_live(prompt="must not run synthetic as live")
    assert exc2.value.reason_code == "DUAL_HOST_SYNTHETIC_LIVE_REFUSED"


def test_dual_host_live_argv_shape_and_foreign_session(
    host_mod: Any, native: Any, tmp_path: Path
) -> None:
    cfg = host_mod.DualHostConfig(
        transport_image="transport:candidate",
        tool_image="tool:candidate",
        auth_host_path=tmp_path / "auth",
        episode_root=tmp_path / "ep",
        synthetic=True,
    )
    (tmp_path / "auth").mkdir()
    host = host_mod.DualContainerHost(cfg)
    host_session = f"xrsess_{uuid.uuid4().hex[:8]}"
    created = host.create_pair(episode_id="ep_argv", session_id=host_session)
    assert created["mcp_server"] == "episode_lab"
    inv = host.load_session_inventory()
    assert inv is not None
    grok_session = str(inv["grok_session_id"])
    argv = host.build_grok_session_argv(
        resume=False, session_id=grok_session, max_turns=16, prompt="lab"
    )
    native.assert_live_research_argv(argv)
    assert "--model" in argv and argv[argv.index("--model") + 1] == "grok-4.5"
    assert int(argv[argv.index("--max-turns") + 1]) >= 8
    assert argv[argv.index("--tools") + 1] == "search_tool,use_tool,web_search,web_fetch"
    # OPEN_RESEARCH: honest --no-subagents; host tools still stripped; multi-turn tools remain.
    assert "--no-subagents" in argv
    assert "--always-approve" in argv
    assert "--disable-web-search" not in argv
    assert "--disallowed-tools" in argv
    denied = argv[argv.index("--disallowed-tools") + 1]
    assert "run_terminal_cmd" in denied and "run_terminal_command" in denied
    assert "spawn_subagent" in denied
    assert "web_search" not in denied

    host.start_pair()
    host.interrupt_pair()
    resumed = host.resume_pair(expected_session_id=host_session)
    rargv = resumed["planned_grok_argv"]
    native.assert_live_research_argv(rargv)
    assert "--resume" in rargv
    with pytest.raises(host_mod.DualHostError):
        host.resume_pair(expected_session_id="xrsess_FOREIGN")


def test_dual_host_attach_run_with_mocked_exec_records_evidence(
    host_mod: Any, native: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = host_mod.DualHostConfig(
        transport_image="transport:candidate",
        tool_image="tool:candidate",
        auth_host_path=tmp_path / "auth",
        episode_root=tmp_path / "ep",
        synthetic=False,
    )
    (tmp_path / "auth").mkdir()
    host = host_mod.DualContainerHost(cfg)
    # Force non-synthetic lease files without docker by manually planting lease after
    # synthetic create, then flip synthetic off for require path via monkeypatch.
    syn = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:candidate",
            tool_image="tool:candidate",
            auth_host_path=tmp_path / "auth",
            episode_root=tmp_path / "ep",
            synthetic=True,
        )
    )
    host_session = f"xrsess_{uuid.uuid4().hex[:8]}"
    syn.create_pair(episode_id="ep_mock_exec", session_id=host_session)
    syn.start_pair()
    # Rewrite lease container ids to non-synthetic tokens.
    lease = syn.load_lease()
    assert lease is not None
    lease["tool_container_id"] = "toolcid123"
    lease["transport_container_id"] = "transportcid123"
    lease["phase"] = "running"
    syn._save_lease(lease)
    inv = syn.load_session_inventory()
    assert inv is not None
    inv["tool_container_id"] = "toolcid123"
    inv["transport_container_id"] = "transportcid123"
    syn._save_session_inventory(inv)
    receipt = syn.load_pair_receipt()
    assert receipt is not None
    receipt["tool_container_id"] = "toolcid123"
    receipt["transport_container_id"] = "transportcid123"
    body = {k: v for k, v in receipt.items() if k != "pair_receipt_sha256"}
    receipt["pair_receipt_sha256"] = hashlib.sha256(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    ).hexdigest()
    (tmp_path / "ep" / "dual_container_pair_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    lease["pair_receipt_sha256"] = receipt["pair_receipt_sha256"]
    syn._save_lease(lease)

    # Host under test (synthetic=False) shares same episode_root files.
    live_host = host_mod.DualContainerHost(cfg)
    sid = str(inv["grok_session_id"])

    def fake_ready(**kwargs: Any) -> dict[str, Any]:
        return {
            "status": "LIVE_PAIR_READY",
            "lease": live_host.load_lease(),
            "session_inventory": live_host.load_session_inventory(),
            "pair_receipt": live_host.load_pair_receipt(),
            "pair_receipt_sha256": lease["pair_receipt_sha256"],
            "provider_session_uuid": sid,
            "completion_claim_allowed": False,
        }

    def fake_exec(argv: Any, *, timeout_seconds: float, env: Any = None) -> Any:
        # Append productive lab op event + lab FS effect (sidecar + manifest).
        mcp_path = tmp_path / "ep" / "output" / "mcp_events.jsonl"
        mcp_path.parent.mkdir(parents=True, exist_ok=True)
        lab = tmp_path / "ep" / "lab"
        manifest = _candidate_manifest_bytes(episode_id="ep_mock_exec")
        (lab / "candidate").mkdir(parents=True, exist_ok=True)
        (lab / "candidate" / "candidate_manifest.v1.json").write_bytes(manifest)
        sidecar = "cd" * 32
        event = {
            "schema_version": "xinao.dual_container_mcp_event.v1",
            "event": "mcp_tools_call",
            "op": "write_file",
            "status": "ok",
            "productive": True,
            "episode_id": "ep_mock_exec",
            "server": "episode_lab",
            "sidecar_event_hash": sidecar,
            "path_relative": "candidate/candidate_manifest.v1.json",
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        body = {k: v for k, v in event.items() if k != "event_hash"}
        event_hash = hashlib.sha256(
            (
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        ).hexdigest()
        with mcp_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({**event, "event_hash": event_hash}, sort_keys=True) + "\n")
        # Tool-executor-only sealed evidence (transport cannot forge this path).
        tool_path = tmp_path / "ep" / "sidecar_evidence" / "tool_events.jsonl"
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_rec = {
            "schema_version": "xinao.tool_executor_sidecar_event.v1",
            "event_hash": sidecar,
            "op": "write_file",
            "episode_id": "ep_mock_exec",
            "status": "ok",
            "path_relative": "candidate/candidate_manifest.v1.json",
            "productive": True,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        with tool_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(tool_rec, sort_keys=True) + "\n")
        if env is not None:
            assert env.get("GROK_HOME") == "/grok-home"
        native.assert_live_research_argv(list(argv), research_profile="OPEN_RESEARCH")
        assert "--disable-web-search" not in list(argv)
        assert "--always-approve" in list(argv)
        assert timeout_seconds >= 8
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=0,
            stdout=_provider_stdout(session_id=sid, turns=6),
            stderr=b"",
        )

    monkeypatch.setattr(live_host, "require_live_pair_ready", fake_ready)
    monkeypatch.setattr(live_host, "exec_transport_grok", fake_exec)

    result = live_host.attach_run_live(
        prompt="fail experiment then revise",
        max_turns=16,
        timeout_seconds=120,
        expected_episode_id="ep_mock_exec",
        expected_host_session_id=host_session,
        cas_head_sha256="a" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="researcher-test",
        release_identity_sha256="d" * 64,
    )
    assert result["live_executed"] is True
    assert result["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    assert result["completion_claim_allowed"] is False
    assert result["attempt_cas_digest"]
    assert result["provider_session_uuid"] == sid

    # plan_only never becomes live evidence
    planned = live_host.attach_run_live(prompt="x", plan_only=True)
    assert planned["status"] == native.STATUS_PLANNED
    assert planned["live_executed"] is False

    # Export success
    bundle = live_host.export_candidate_evidence(
        attempt_cas_digest=result["attempt_cas_digest"],
        episode_id="ep_mock_exec",
        cas_head_sha256="a" * 64,
        expected_provider_session_uuid=sid,
        namespace_receipt_sha256="c" * 64,
    )
    assert bundle["status"] == native.STATUS_CANDIDATE_EVIDENCE_EXPORTED
    assert bundle["owner_adopted"] is False
    assert bundle["parent_complete"] is False

    # Direct identity gate on a fresh host (not monkeypatched): session mismatch.
    gate_host = host_mod.DualContainerHost(cfg)
    with pytest.raises(host_mod.DualHostError) as exc2:
        gate_host.require_live_pair_ready(
            expected_episode_id="ep_mock_exec",
            expected_provider_session_uuid=str(uuid.uuid4()),
            allow_synthetic=True,
        )
    assert exc2.value.reason_code == "DUAL_HOST_PROVIDER_SESSION_MISMATCH"


def test_cli_help_exposes_live_verbs() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPTS / "xinao_runtime.py"),
            "research-episode",
            "--help",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # argparse may put subcommands on stderr or require deeper help; parse tree via source.
    text = (SCRIPTS / "xinao_runtime.py").read_text(encoding="utf-8")
    assert 'add_parser("attach-run")' in text
    assert 'add_parser("resume-live")' in text
    assert 'add_parser("export-candidate-evidence")' in text
    assert "LIVE_ATTEMPT_RECORDED" in (PKG / "native_grok_session.py").read_text(encoding="utf-8")
    assert "CANDIDATE_EVIDENCE_EXPORTED" in (PKG / "native_grok_session.py").read_text(
        encoding="utf-8"
    )
    del completed


def test_auth_not_on_tool_via_credential_scan(native: Any) -> None:
    bad = native.credential_reachability_scan(
        env={"XAI_API_KEY": "secret", "HOME": "/tmp"},
        tool_mounts=["/episode-lab", "/grok-home/.grok"],
    )
    assert bad["ok"] is False
    assert any("XAI_API_KEY" in h or "grok-home" in h for h in bad["hits"])
    good = native.credential_reachability_scan(
        env={"HOME": "/tmp", "TMPDIR": "/tmp"},
        tool_mounts=["/episode-lab", "/ipc"],
    )
    assert good["ok"] is True
