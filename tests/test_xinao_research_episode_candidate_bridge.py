"""Bridge + role-fitness negative tests for ResearchEpisode → candidate pool.

Unit-level: mock transport state transitions. Live dual-container proof remains
Owner acceptance. Codex remains sole Owner.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "docker" / "xinao-researcher"
SCIENCE_SRC = ROOT / "xinao_discovery" / "src"
# Science package must precede docker path so `xinao` resolves to the package.
if str(DOCKER) in sys.path:
    sys.path.remove(str(DOCKER))
if str(SCIENCE_SRC) not in sys.path:
    sys.path.insert(0, str(SCIENCE_SRC))
if str(DOCKER) not in sys.path:
    sys.path.append(str(DOCKER))


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def native() -> Any:
    return _load("xinao_native_bridge", DOCKER / "native_grok_session.py")


@pytest.fixture(scope="module")
def mcp_server() -> Any:
    return _load("xinao_mcp_bridge", DOCKER / "mcp_episode_lab_server.py")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest(
    *,
    episode_id: str = "ep_bridge",
    attempt: str | None = None,
    recommendation: str = "NO_RECOMMENDATION",
    owner_adopted: bool = False,
    completion: bool = False,
    candidate_only: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "xinao.research_episode_candidate_manifest.v1",
        "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        "candidate_id": "cand_bridge_1",
        "candidate_version": "v1",
        "episode_id": episode_id,
        "attempt_cas_digest": attempt,
        "research_question": "does fail→revise→succeed yield a sealed candidate?",
        "research_object": "experiment loop + export",
        "data_cutoff": {
            "as_of": "2026-07-31T12:00:00Z",
            "material_refs": [{"id": "seed", "sha256": "aa" * 32}],
        },
        "method_refs": ["failed_shell", "revised_python", "wild_black_box_ok"],
        "falsifiers": ["first shell returned nonzero"],
        "account_recommendation": recommendation,
        "proposed": {"numbers": [7], "stake": "1.00"},
        "candidate_only": candidate_only,
        "owner_adopted": owner_adopted,
        "completion": completion,
    }
    if extra:
        body.update(extra)
    return body


def test_mcp_arg_remap_path_content_cwd(mcp_server: Any) -> None:
    mapped = mcp_server.remap_mcp_args_to_ipc(
        "write_file", {"path": "work/a.py", "content": "print(1)\n"}
    )
    assert mapped["path_relative"] == "work/a.py"
    assert mapped["content_utf8"] == "print(1)\n"
    assert "path" not in mapped
    shell = mcp_server.remap_mcp_args_to_ipc("shell_exec", {"argv": ["python", "work/a.py"]})
    assert shell["cwd_relative"] == "work"
    assert shell["cwd_relative"] != "."


def test_event_forgery_without_sidecar_rejected(native: Any) -> None:
    body = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_tools_call",
        "op": "write_file",
        "status": "ok",
        "productive": True,
        "episode_id": "ep1",
        "server": "episode_lab",
    }
    event_hash = _sha(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    delta = {
        "status": "DELTA_OK",
        "productive_ops": ["write_file"],
        "events": [{**body, "event_hash": event_hash}],
    }
    with pytest.raises(native.NativeSessionError) as exc:
        native.require_productive_lab_delta(delta)
    assert exc.value.reason_code == "PRODUCTIVE_SIDECAR_HASH_MISSING"


def test_lab_effect_binding_requires_fs_delta(native: Any) -> None:
    body = {
        "op": "write_file",
        "status": "ok",
        "path_relative": "candidate/candidate_manifest.v1.json",
        "sidecar_event_hash": "ab" * 32,
    }
    delta = {"status": "DELTA_OK", "productive_ops": ["write_file"], "events": [body]}
    with pytest.raises(native.NativeSessionError) as exc:
        native.require_lab_effect_binding(
            delta=delta,
            lab_artifact_manifest={"artifacts": []},
            prior_lab_artifact_manifest={"artifacts": []},
        )
    assert exc.value.reason_code in {
        "LAB_EFFECT_WRITE_UNBOUND",
        "LAB_EFFECT_MISSING",
    }
    # With matching lab path present → bound
    ok = native.require_lab_effect_binding(
        delta=delta,
        lab_artifact_manifest={
            "artifacts": [
                {
                    "path": "candidate/candidate_manifest.v1.json",
                    "sha256": "cc" * 32,
                }
            ]
        },
        prior_lab_artifact_manifest={"artifacts": []},
    )
    assert ok["bound"] is True


def test_candidate_manifest_closed_schema_and_authority(native: Any, tmp_path: Path) -> None:
    good = _manifest()
    native.validate_candidate_manifest(good)
    bad = _manifest(owner_adopted=True)
    with pytest.raises(native.NativeSessionError) as exc:
        native.validate_candidate_manifest(bad)
    assert "OWNER_ADOPTED" in exc.value.reason_code
    bad2 = _manifest(recommendation="ACTION")  # not candidate form
    with pytest.raises(native.NativeSessionError) as exc2:
        native.validate_candidate_manifest(bad2)
    assert "RECOMMENDATION" in exc2.value.reason_code
    # Symlink / alternate path refused
    lab = tmp_path / "lab"
    lab.mkdir()
    real = lab / "candidate"
    real.mkdir()
    raw = (json.dumps(good, sort_keys=True) + "\n").encode("utf-8")
    (real / "candidate_manifest.v1.json").write_bytes(raw)
    with pytest.raises(native.NativeSessionError) as exc3:
        native.load_lab_candidate_manifest_bytes(
            lab_root=lab, relative_path="other/candidate_manifest.v1.json"
        )
    assert exc3.value.reason_code == "CANDIDATE_MANIFEST_PATH_FORBIDDEN"


def test_experiment_loop_state_transitions_and_export(native: Any, tmp_path: Path) -> None:
    """Fail shell → revise → succeed → write manifest → export binds hashes."""
    lab = tmp_path / "lab"
    out = tmp_path / "output"
    lab.mkdir()
    # Failed experiment artifact
    fail_log = lab / "work" / "fail.log"
    fail_log.parent.mkdir(parents=True)
    fail_log.write_text("exit=1\n", encoding="utf-8")
    # Revised success code
    (lab / "work" / "solve.py").write_text("print('ok')\n", encoding="utf-8")
    (lab / "work" / "ok.log").write_text("exit=0\n", encoding="utf-8")
    manifest = _manifest(episode_id="ep_loop")
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    man_path = lab / "candidate" / "candidate_manifest.v1.json"
    man_path.parent.mkdir(parents=True)
    man_path.write_bytes(raw)
    # Scan artifacts as dual-host would
    artifacts = []
    for p in sorted(lab.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(lab)).replace("\\", "/")
            b = p.read_bytes()
            artifacts.append({"path": rel, "sha256": _sha(b), "size": str(len(b))})
    assert any(a["path"] == "candidate/candidate_manifest.v1.json" for a in artifacts)
    assert any(a["path"] == "work/fail.log" for a in artifacts)
    assert any(a["path"] == "work/ok.log" for a in artifacts)

    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(session_id=sid, max_turns=16, prompt="revise")
    native.assert_live_research_argv(argv, research_profile="OPEN_RESEARCH")
    assert "--no-subagents" not in argv
    assert "--always-approve" in argv
    stdout = (
        json.dumps(
            {
                "type": "result",
                "sessionId": sid,
                "stopReason": "end_turn",
                "num_turns": 9,
            }
        )
        + "\n"
    ).encode("utf-8")
    attempt = native.build_live_attempt_record(
        episode_id="ep_loop",
        host_session_id="hs_loop",
        provider_session_uuid=sid,
        attempt_id="att_loop",
        argv=argv,
        stdout=stdout,
        stderr=b"",
        exit_code=0,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=120,
        started_at="2026-07-31T00:00:00Z",
        finished_at="2026-07-31T00:10:00Z",
        transport_container_id="t1",
        tool_container_id="k1",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="rel",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": artifacts},
        prior_attempt_hash=None,
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        research_profile="OPEN_RESEARCH",
        productive_lab_ops=["write_file", "shell_exec"],
        mcp_delta_status="DELTA_OK",
        require_productive_lab_op=True,
    )
    assert attempt["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    # First persist without attempt pin in manifest; then rewrite manifest without
    # attempt binding (optional field) so export matches current lab bytes.
    persisted = native.persist_live_attempt(out, attempt)
    raw2 = raw  # already sealed; no attempt pin required
    bundle = native.export_candidate_evidence_bundle(
        episode_output_root=out,
        attempt_cas_digest=persisted["attempt_cas_digest"],
        episode_id="ep_loop",
        cas_head_sha256="a" * 64,
        lab_root=lab,
    )
    assert bundle["candidate_manifest_sha256"] == _sha(raw2)
    assert bundle["owner_adopted"] is False
    assert bundle["freeze_written"] is False
    # Drift: mutate lab after artifact seal on attempt should fail export
    man_path.write_bytes(raw2 + b" ")
    with pytest.raises(native.NativeSessionError) as exc:
        native.export_candidate_evidence_bundle(
            episode_output_root=out,
            attempt_cas_digest=persisted["attempt_cas_digest"],
            episode_id="ep_loop",
            cas_head_sha256="a" * 64,
            lab_root=lab,
        )
    assert exc.value.reason_code == "CANDIDATE_MANIFEST_HASH_MISMATCH"


def test_episode_export_pool_adapter_and_one_shot_untouched(tmp_path: Path) -> None:
    from xinao.science.episode_export_pool_adapter import (
        INGEST_KIND,
        EpisodeExportAdapterError,
        ingest_verified_episode_export,
        load_episode_pool_entry,
        verify_episode_export_bundle,
    )
    from xinao.science.researcher_result_adapter import (
        ResearcherResultAdapterError,
        verify_researcher_result_against_receipt,
    )

    # Multi-turn export accepted
    body = {
        "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
        "status": "CANDIDATE_EVIDENCE_EXPORTED",
        "episode_id": "ep_pool",
        "attempt_id": "att1",
        "attempt_hash": "a" * 64,
        "attempt_cas_digest": "b" * 64,
        "raw_session_hash": "c" * 64,
        "tool_trace_hash": "d" * 64,
        "artifact_manifest_hash": "e" * 64,
        "candidate_manifest_sha256": "f" * 64,  # filled below
        "pair_receipt_sha256": "11" * 32,
        "namespace_receipt_sha256": "22" * 32,
        "release_identity_sha256": "33" * 32,
        "provider_session_uuid": "00000000-0000-4000-8000-000000000001",
        "research_profile": "OPEN_RESEARCH",
        "actual_turns": 9,
        "max_turns": 16,
        "candidate_only": True,
        "owner_adopted": False,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "shadow_write": False,
        "next_task_created": False,
        "disposition_written": False,
        "freeze_written": False,
        "settlement_written": False,
        "portfolio_updated": False,
    }
    manifest = _manifest(episode_id="ep_pool", attempt="b" * 64)
    man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    body["candidate_manifest_sha256"] = _sha(man_bytes)
    # Seal like native (newline-canonical body hash)
    bundle_hash = _sha(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    export = {**body, "bundle_sha256": bundle_hash}
    export_bytes = (json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    verified = verify_episode_export_bundle(export)
    assert verified["actual_turns"] == 9
    entry = ingest_verified_episode_export(
        pool_root=tmp_path / "pool",
        export=export_bytes,
        manifest_bytes=man_bytes,
    )
    assert entry["owner_adopted"] is False
    assert entry["ingest_kind"] == INGEST_KIND
    assert entry["decision_map_projected"] is False
    loaded = load_episode_pool_entry(tmp_path / "pool", entry["result_sha256"])
    assert loaded["result_sha256"] == entry["result_sha256"]

    # Recommendation does not freeze
    assert entry.get("freeze_written") is not True

    # Drift rejects
    with pytest.raises(EpisodeExportAdapterError) as exc:
        ingest_verified_episode_export(
            pool_root=tmp_path / "pool2",
            export=export_bytes,
            manifest_bytes=man_bytes + b"x",
        )
    assert exc.value.reason_code == "CANDIDATE_MANIFEST_HASH_MISMATCH"

    # Old one-shot path still enforces num_turns==1 (do not weaken)
    with pytest.raises(ResearcherResultAdapterError):
        verify_researcher_result_against_receipt(
            b'{"schema_version":"xinao.researcher_container_result.v2","status":"SUCCESS"}',
            {"schema_version": "xinao.skill_research_receipt.v2"},
        )


def test_feedback_material_no_rewrite_no_autostart(tmp_path: Path) -> None:
    from xinao.canonical import canonical_sha256
    from xinao.science.research_feedback_material import (
        ResearchFeedbackMaterialError,
        assert_feedback_cannot_rewrite_priors,
        bind_feedback_pack_as_episode_material,
    )

    # Minimal sealed pack bytes under CAS path layout
    pack_body = {
        "schema_version": "xinao.research_feedback_pack.v1",
        "pack_marker": "XINAO_RESEARCH_FEEDBACK_PACK_V1",
        "prior_result_sha256": "aa" * 32,
        "prior_research_binding_sha256": "bb" * 32,
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "scientific_promotion": False,
        "future_outcome_access": False,
    }
    content_hash = canonical_sha256(pack_body)
    sealed = {**pack_body, "content_hash": content_hash}
    cas = (
        tmp_path
        / "objects"
        / "research_feedback_pack"
        / "sha256"
        / content_hash[:2]
        / f"{content_hash}.json"
    )
    cas.parent.mkdir(parents=True)
    cas.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # research_feedback_pack_cas_path resolves via resolve_root — use same root
    binding = bind_feedback_pack_as_episode_material(
        portfolio_root=tmp_path,
        feedback_content_hash=content_hash,
        prior_candidate_result_sha256="aa" * 32,
        settled_portfolio_hash="cc" * 32,
        target_episode_version="ep_v2",
    )
    assert binding["auto_start_next_research"] is False
    assert binding["rewrites_prior_candidate"] is False
    assert_feedback_cannot_rewrite_priors(binding=binding)
    leak = dict(binding)
    leak["rewrites_prior_freeze"] = True
    with pytest.raises(ResearchFeedbackMaterialError):
        assert_feedback_cannot_rewrite_priors(binding=leak)


def test_open_research_subagent_policy_documented(native: Any) -> None:
    assert native.OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS is True
    assert "host builtins" in native.OPEN_RESEARCH_SUBAGENT_POLICY_REASON.lower() or (
        "stripped" in native.OPEN_RESEARCH_SUBAGENT_POLICY_REASON.lower()
    )
    sid = native.new_session_uuid()
    open_argv = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, research_profile="OPEN_RESEARCH"
    )
    closed_argv = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, research_profile="CLOSED_LAB"
    )
    assert "--no-subagents" not in open_argv
    assert "--no-subagents" in closed_argv
    denied = open_argv[open_argv.index("--disallowed-tools") + 1]
    assert "spawn_subagent" in denied
