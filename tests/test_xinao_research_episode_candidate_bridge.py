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


REAL_PRIMARY_AFFINE_MANIFEST = (
    ROOT
    / "tests"
    / "fixtures"
    / "real_research_episode"
    / "xre_20260731T214242_15d5292ebc9a"
    / "candidate_manifest.primary_affine.official.v1.json"
)
REAL_PRIMARY_AFFINE_MANIFEST_SHA256 = (
    "f4c19e21fad994948824f8c4f8ff7c77969366d1e478da5aac23b2bfe29cb5f0"
)


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


def test_real_primary_affine_legacy_shape_is_not_actor_behavior(native: Any) -> None:
    """A hash-pinned signal-policy fixture cannot impersonate actor behavior."""

    raw = REAL_PRIMARY_AFFINE_MANIFEST.read_bytes()
    assert _sha(raw) == REAL_PRIMARY_AFFINE_MANIFEST_SHA256
    with pytest.raises(native.NativeSessionError) as exc:
        native.validate_candidate_manifest(
            raw,
            expected_episode_id="xre_20260731T214242_15d5292ebc9a",
        )
    assert exc.value.reason_code == "CANDIDATE_MANIFEST_ACTOR_INTENT_INVALID"


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


def test_arbitrary_hex_sidecar_without_tool_chain_rejected(native: Any) -> None:
    """Planted /output MCP event with random hex sidecar must not pass trusted chain."""
    body = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_tools_call",
        "op": "write_file",
        "status": "ok",
        "productive": True,
        "episode_id": "ep1",
        "server": "episode_lab",
        "path_relative": "candidate/candidate_manifest.v1.json",
        "sidecar_event_hash": "ff" * 32,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    event_hash = _sha(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    delta = {
        "status": "DELTA_OK",
        "productive_ops": ["write_file"],
        "events": [{**body, "event_hash": event_hash}],
    }
    # Format-only path still requires hex sidecar (present) → OK without trusted set
    native.require_productive_lab_delta(delta)
    # Live attach path requires membership in tool-executor sealed set
    with pytest.raises(native.NativeSessionError) as exc:
        native.require_productive_lab_delta(
            delta,
            trusted_event_hashes=[],
            require_trusted_tool_chain=True,
        )
    assert exc.value.reason_code == "TOOL_EVENT_UNTRUSTED"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.require_productive_lab_delta(
            delta,
            trusted_event_hashes=["aa" * 32],
            require_trusted_tool_chain=True,
        )
    assert exc2.value.reason_code == "TOOL_EVENT_UNTRUSTED"
    # Happy path: independently sealed tool-side record matches sidecar
    native.require_productive_lab_delta(
        delta,
        trusted_event_hashes=["ff" * 32],
        require_trusted_tool_chain=True,
    )


def test_lab_effect_binding_requires_changed_artifact(native: Any) -> None:
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
    # Mere presence of a pre-existing identical hash must fail
    planted = {
        "artifacts": [
            {
                "path": "candidate/candidate_manifest.v1.json",
                "sha256": "cc" * 32,
            }
        ]
    }
    with pytest.raises(native.NativeSessionError) as exc_same:
        native.require_lab_effect_binding(
            delta=delta,
            lab_artifact_manifest=planted,
            prior_lab_artifact_manifest=planted,
        )
    assert exc_same.value.reason_code == "LAB_EFFECT_WRITE_UNBOUND"
    # Changed content vs prior → bound
    ok = native.require_lab_effect_binding(
        delta=delta,
        lab_artifact_manifest={
            "artifacts": [
                {
                    "path": "candidate/candidate_manifest.v1.json",
                    "sha256": "dd" * 32,
                }
            ]
        },
        prior_lab_artifact_manifest={
            "artifacts": [
                {
                    "path": "candidate/candidate_manifest.v1.json",
                    "sha256": "cc" * 32,
                }
            ]
        },
    )
    assert ok["bound"] is True
    # First create (prior empty) still binds
    ok2 = native.require_lab_effect_binding(
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
    assert ok2["bound"] is True


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
    assert "--no-subagents" in argv
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
    assert bundle["host_session_id"] == "hs_loop"
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
    """Behavior-level honesty: no subagent fitness claim while spawn is denied."""
    assert native.OPEN_RESEARCH_ALLOW_EPISODE_SUBAGENTS is False
    assert "spawn_subagent" in native.OPEN_RESEARCH_SUBAGENT_POLICY_REASON.lower()
    sid = native.new_session_uuid()
    open_argv = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, research_profile="OPEN_RESEARCH"
    )
    closed_argv = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, research_profile="CLOSED_LAB"
    )
    # Both profiles keep --no-subagents (honest minimal behavior)
    assert "--no-subagents" in open_argv
    assert "--no-subagents" in closed_argv
    denied = open_argv[open_argv.index("--disallowed-tools") + 1]
    assert "spawn_subagent" in denied
    # CLI capability surface: supported version pin is real, not comment-only
    assert native.SUPPORTED_GROK_CLI_VERSION == "0.2.117"
    with pytest.raises(native.NativeSessionError) as exc:
        native.require_supported_grok_cli_version("grok 0.2.112 (deadbeef)")
    assert exc.value.reason_code == "GROK_CLI_VERSION_UNSUPPORTED"
    assert native.require_supported_grok_cli_version("grok 0.2.117 (f1c0609308)") == "0.2.117"
    # Role fitness: multi-turn + tools still present (not one-turn canary regression)
    assert "--max-turns" in open_argv
    assert int(open_argv[open_argv.index("--max-turns") + 1]) >= 2
    tools = open_argv[open_argv.index("--tools") + 1]
    assert "web_search" in tools
    assert "use_tool" in tools
    assert tools != ""


def test_pool_adapter_rejects_missing_cutoff_method_falsifier(tmp_path: Path) -> None:
    from xinao.science.episode_export_pool_adapter import (
        EpisodeExportAdapterError,
        ingest_verified_episode_export,
    )

    def _export_for(manifest: dict[str, Any]) -> tuple[bytes, bytes]:
        man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        body = {
            "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
            "status": "CANDIDATE_EVIDENCE_EXPORTED",
            "episode_id": "ep_weak",
            "attempt_id": "att1",
            "attempt_hash": "a" * 64,
            "attempt_cas_digest": "b" * 64,
            "raw_session_hash": "c" * 64,
            "tool_trace_hash": "d" * 64,
            "artifact_manifest_hash": "e" * 64,
            "candidate_manifest_sha256": _sha(man_bytes),
            "pair_receipt_sha256": "11" * 32,
            "namespace_receipt_sha256": "22" * 32,
            "release_identity_sha256": "33" * 32,
            "provider_session_uuid": "00000000-0000-4000-8000-000000000099",
            "research_profile": "OPEN_RESEARCH",
            "actual_turns": 4,
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
        bundle_hash = _sha(
            (
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        )
        export = {**body, "bundle_sha256": bundle_hash}
        export_bytes = (
            json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return export_bytes, man_bytes

    cases = [
        ("CANDIDATE_MANIFEST_CUTOFF_INVALID", lambda m: m.pop("data_cutoff", None)),
        ("CANDIDATE_MANIFEST_METHODS_INVALID", lambda m: m.pop("method_refs", None)),
        ("CANDIDATE_MANIFEST_LIMITATIONS_INVALID", lambda m: m.pop("falsifiers", None)),
        (
            "CANDIDATE_MANIFEST_CUTOFF_INVALID",
            lambda m: m["data_cutoff"].update(
                {"material_refs": [{"id": "x", "sha256": "not-a-hash"}]}
            ),
        ),
    ]
    for expected_reason, mutator in cases:
        weak = _manifest(episode_id="ep_weak", attempt="b" * 64)
        mutator(weak)
        export_bytes, man_bytes = _export_for(weak)
        with pytest.raises(EpisodeExportAdapterError) as exc:
            ingest_verified_episode_export(
                pool_root=tmp_path / f"pool_{expected_reason}",
                export=export_bytes,
                manifest_bytes=man_bytes,
            )
        assert expected_reason in exc.value.reason_code


def test_owner_cli_ingest_export_and_bind_feedback_smoke(tmp_path: Path) -> None:
    """Stable Skill consumer surface: runtime verbs without freeze/disposition."""
    runtime = _load(
        "xinao_runtime_bridge_cli", ROOT / "skills" / "xinao" / "scripts" / "xinao_runtime.py"
    )
    from xinao.canonical import canonical_sha256
    from xinao.science.episode_export_pool_adapter import ingest_verified_episode_export

    manifest = _manifest(episode_id="ep_cli", attempt="b" * 64)
    man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    body = {
        "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
        "status": "CANDIDATE_EVIDENCE_EXPORTED",
        "episode_id": "ep_cli",
        "attempt_id": "att_cli",
        "attempt_hash": "a" * 64,
        "attempt_cas_digest": "b" * 64,
        "raw_session_hash": "c" * 64,
        "tool_trace_hash": "d" * 64,
        "artifact_manifest_hash": "e" * 64,
        "candidate_manifest_sha256": _sha(man_bytes),
        "pair_receipt_sha256": "11" * 32,
        "namespace_receipt_sha256": "22" * 32,
        "release_identity_sha256": "33" * 32,
        "provider_session_uuid": "00000000-0000-4000-8000-0000000000aa",
        "research_profile": "OPEN_RESEARCH",
        "actual_turns": 5,
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
    bundle_hash = _sha(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    export = {**body, "bundle_sha256": bundle_hash}
    export_path = tmp_path / "export.json"
    manifest_path = tmp_path / "candidate_manifest.v1.json"
    export_path.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.write_bytes(man_bytes)
    pool_root = tmp_path / "pool"
    result = runtime.research_episode_ingest_export(
        pool_root=pool_root,
        export_path=export_path,
        manifest_path=manifest_path,
    )
    assert result["owner_adopted"] is False
    assert result["freeze_written"] is False
    assert result["status"] == "POOL_ENTRY_READY"
    # CAS conflict on byte drift
    with pytest.raises(Exception):
        ingest_verified_episode_export(
            pool_root=pool_root,
            export=export_path.read_bytes(),
            manifest_bytes=man_bytes + b"x",
        )

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
    binding = runtime.research_episode_bind_feedback_material(
        portfolio_root=tmp_path,
        feedback_content_hash=content_hash,
        prior_candidate_result_sha256="aa" * 32,
    )
    assert binding["auto_start_next_research"] is False
    assert binding["next_task_created"] is False
    assert binding["freeze_written"] is False

    # CLI help lists new verbs (parser surface)
    parser = runtime._parser()
    help_text = parser.format_help()
    assert "research-episode" in help_text
    # Subparser help
    # ingest-export registered
    ns = parser.parse_args(
        [
            "research-episode",
            "ingest-export",
            "--pool-root",
            str(pool_root),
            "--export",
            str(export_path),
            "--manifest",
            str(manifest_path),
        ]
    )
    assert ns.research_episode_command == "ingest-export"


def test_denied_error_timeout_never_count_as_productive(native: Any, tmp_path: Path) -> None:
    """Success-only productive evidence: failed statuses never enter productive gates."""
    episode_id = "ep_denied_prod"
    events_path = tmp_path / "output" / "mcp_events.jsonl"
    sidecar_path = tmp_path / "sidecar_evidence" / "tool_events.jsonl"
    events_path.parent.mkdir(parents=True)
    sidecar_path.parent.mkdir(parents=True)
    lab = tmp_path / "lab"
    planted = lab / "candidate" / "candidate_manifest.v1.json"
    planted.parent.mkdir(parents=True)
    planted.write_text('{"planted":true}\n', encoding="utf-8")
    planted_digest = _sha(planted.read_bytes())

    def _mcp_line(
        *,
        status: str,
        sidecar: str,
        productive_flag: bool,
        path_relative: str = "candidate/candidate_manifest.v1.json",
    ) -> dict[str, Any]:
        body = {
            "schema_version": "xinao.dual_container_mcp_event.v1",
            "event": "mcp_tools_call",
            "episode_id": episode_id,
            "op": "write_file",
            "status": status,
            "productive": productive_flag,
            "server": "episode_lab",
            "sidecar_event_hash": sidecar,
            "path_relative": path_relative,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }
        eh = _sha((json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
        return {**body, "event_hash": eh}

    def _sidecar_line(*, event_hash: str, status: str, productive: bool) -> dict[str, Any]:
        return {
            "schema_version": "xinao.tool_executor_sidecar_event.v1",
            "event_hash": event_hash,
            "op": "write_file",
            "episode_id": episode_id,
            "status": status,
            "path_relative": "candidate/candidate_manifest.v1.json",
            "productive": productive,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "owner_adopted": False,
        }

    for bad_status in ("denied", "error", "timeout"):
        sidecar_hash = _sha(f"tool-{bad_status}".encode())
        # Real sidecar hash present but non-success status.
        with sidecar_path.open("w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    _sidecar_line(
                        event_hash=sidecar_hash,
                        status=bad_status,
                        productive=True,  # forged productive flag
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        with events_path.open("w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    _mcp_line(
                        status=bad_status,
                        sidecar=sidecar_hash,
                        productive_flag=True,
                    ),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        tool_delta = native.collect_tool_sidecar_evidence_delta(
            sidecar_path, None, expected_episode_id=episode_id
        )
        assert sidecar_hash not in (tool_delta.get("trusted_event_hashes") or [])
        assert sidecar_hash not in (tool_delta.get("successful_productive_event_hashes") or [])
        # Audit may retain the event body / all hashes, but not trusted productivity set.
        assert any(e.get("event_hash") == sidecar_hash for e in (tool_delta.get("events") or []))
        mcp_delta = native.collect_attempt_mcp_delta(
            events_path, None, expected_episode_id=episode_id
        )
        assert mcp_delta.get("productive_ops") == []
        with pytest.raises(native.NativeSessionError) as exc:
            native.require_productive_lab_delta(
                mcp_delta,
                trusted_event_hashes=list(tool_delta.get("trusted_event_hashes") or []),
                require_trusted_tool_chain=True,
            )
        assert exc.value.reason_code in {
            "PRODUCTIVE_LAB_OP_MISSING",
            "PRODUCTIVE_LAB_EVENT_MISSING",
            "TOOL_EVENT_UNTRUSTED",
        }
        # Planted lab file + denied hash must not bind as productive write.
        with pytest.raises(native.NativeSessionError):
            native.require_lab_effect_binding(
                delta={
                    "status": "DELTA_OK",
                    "productive_ops": ["write_file"],
                    "events": [
                        {
                            "op": "write_file",
                            "status": bad_status,
                            "productive": True,
                            "path_relative": "candidate/candidate_manifest.v1.json",
                            "sidecar_event_hash": sidecar_hash,
                        }
                    ],
                },
                lab_artifact_manifest={
                    "artifacts": [
                        {
                            "path": "candidate/candidate_manifest.v1.json",
                            "sha256": planted_digest,
                        }
                    ]
                },
                prior_lab_artifact_manifest={"artifacts": []},
            )

    # Wrong path / wrong hash on successful status still fails exact bind.
    ok_sidecar = "ab" * 32
    ok_event = {
        "op": "write_file",
        "status": "ok",
        "path_relative": "candidate/candidate_manifest.v1.json",
        "effect_identity": f"write:candidate/candidate_manifest.v1.json:{'ee' * 32}",
        "sidecar_event_hash": ok_sidecar,
    }
    with pytest.raises(native.NativeSessionError) as exc_hash:
        native.require_lab_effect_binding(
            delta={
                "status": "DELTA_OK",
                "productive_ops": ["write_file"],
                "events": [ok_event],
            },
            lab_artifact_manifest={
                "artifacts": [
                    {
                        "path": "candidate/candidate_manifest.v1.json",
                        "sha256": "ff" * 32,
                    }
                ]
            },
            prior_lab_artifact_manifest={"artifacts": []},
        )
    assert exc_hash.value.reason_code == "LAB_EFFECT_WRITE_HASH_MISMATCH"
    with pytest.raises(native.NativeSessionError) as exc_path:
        native.require_lab_effect_binding(
            delta={
                "status": "DELTA_OK",
                "productive_ops": ["write_file"],
                "events": [
                    {
                        "op": "write_file",
                        "status": "ok",
                        "path_relative": "other/wrong.json",
                        "sidecar_event_hash": ok_sidecar,
                    }
                ],
            },
            lab_artifact_manifest={
                "artifacts": [
                    {
                        "path": "candidate/candidate_manifest.v1.json",
                        "sha256": "dd" * 32,
                    }
                ]
            },
            prior_lab_artifact_manifest={"artifacts": []},
        )
    assert exc_path.value.reason_code == "LAB_EFFECT_WRITE_UNBOUND"

    # Positive: successful write with matching path + digest binds.
    good_digest = "11" * 32
    ok = native.require_lab_effect_binding(
        delta={
            "status": "DELTA_OK",
            "productive_ops": ["write_file"],
            "events": [
                {
                    "op": "write_file",
                    "status": "ok",
                    "path_relative": "candidate/candidate_manifest.v1.json",
                    "effect_identity": f"write:candidate/candidate_manifest.v1.json:{good_digest}",
                    "sidecar_event_hash": ok_sidecar,
                }
            ],
        },
        lab_artifact_manifest={
            "artifacts": [
                {
                    "path": "candidate/candidate_manifest.v1.json",
                    "sha256": good_digest,
                }
            ]
        },
        prior_lab_artifact_manifest={"artifacts": []},
    )
    assert ok["bound"] is True and ok["write_bound"] is True

    # Positive shell success with lab delta binds; timeout body does not enter productive_events.
    shell_ok = native.require_lab_effect_binding(
        delta={
            "status": "DELTA_OK",
            "productive_ops": ["shell_exec"],
            "events": [
                {
                    "op": "shell_exec",
                    "status": "ok",
                    "exit_code": 0,
                    "sidecar_event_hash": "cd" * 32,
                    "lab_effect": True,
                }
            ],
        },
        lab_artifact_manifest={"artifacts": [{"path": "work/out.txt", "sha256": "22" * 32}]},
        prior_lab_artifact_manifest={"artifacts": []},
    )
    assert shell_ok["shell_bound"] is True

    # A read/compute-only shell is still a real productive operation. It must
    # bind to the cursor-bounded tool-executor sidecar from this attempt rather
    # than being forced to create a dummy file merely to satisfy the classifier.
    read_only_sidecar = "ef" * 32
    read_only_ok = native.require_lab_effect_binding(
        delta={
            "status": "DELTA_OK",
            "productive_ops": ["shell_exec"],
            "events": [
                {
                    "op": "shell_exec",
                    "status": "ok",
                    "exit_code": 0,
                    "sidecar_event_hash": read_only_sidecar,
                }
            ],
        },
        lab_artifact_manifest={"artifacts": []},
        prior_lab_artifact_manifest={"artifacts": []},
        trusted_event_hashes=[read_only_sidecar],
    )
    assert read_only_ok["shell_bound"] is True
    assert read_only_ok["read_only_shell_bound"] is True

    with pytest.raises(native.NativeSessionError) as untrusted_read_only:
        native.require_lab_effect_binding(
            delta={
                "status": "DELTA_OK",
                "productive_ops": ["shell_exec"],
                "events": [
                    {
                        "op": "shell_exec",
                        "status": "ok",
                        "exit_code": 0,
                        "sidecar_event_hash": read_only_sidecar,
                    }
                ],
            },
            lab_artifact_manifest={"artifacts": []},
            prior_lab_artifact_manifest={"artifacts": []},
            trusted_event_hashes=["ab" * 32],
        )
    assert untrusted_read_only.value.reason_code == "LAB_EFFECT_SHELL_UNBOUND"


def test_package_validator_without_docker_tree(tmp_path: Path) -> None:
    """Isolated site-packages-style load: validator works with monorepo docker tree absent."""
    import subprocess
    import textwrap

    science_src = ROOT / "xinao_discovery" / "src"
    script = textwrap.dedent(
        f"""
        import json
        import sys
        from pathlib import Path

        # site-packages-only: only discovery src on path (no docker tree).
        sys.path[:] = [{str(science_src)!r}] + [
            p for p in sys.path if "docker" not in p.replace("\\\\", "/").lower()
        ]
        from xinao.science.research_episode_candidate_manifest import (
            validate_candidate_manifest,
            module_source_sha256,
            CandidateManifestError,
        )
        from xinao.science.episode_export_pool_adapter import (
            EpisodeExportAdapterError,
            ingest_verified_episode_export,
            load_and_verify_candidate_manifest,
        )

        # Prove no monorepo docker walk is required for adapter import/use.
        assert "native_grok_session" not in sys.modules
        good = {{
            "schema_version": "xinao.research_episode_candidate_manifest.v1",
            "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
            "candidate_id": "c1",
            "candidate_version": "v1",
            "research_question": "q",
            "research_object": "o",
            "data_cutoff": {{
                "as_of": "2026-07-31T00:00:00Z",
                "material_refs": [{{"id": "m", "sha256": "{"aa" * 32}"}}],
            }},
            "method_refs": ["m1"],
            "falsifiers": ["f1"],
            "account_recommendation": "NO_RECOMMENDATION",
            "candidate_only": True,
            "owner_adopted": False,
            "completion": False,
        }}
        validate_candidate_manifest(good)
        seal = module_source_sha256()
        assert len(seal) == 64
        bad = dict(good)
        del bad["method_refs"]
        try:
            validate_candidate_manifest(bad)
            raise SystemExit("expected methods rejection")
        except CandidateManifestError as exc:
            assert "METHODS" in exc.reason_code
        print(json.dumps({{"ok": True, "module_sha256": seal}}))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert len(payload["module_sha256"]) == 64


def test_packaged_cli_pool_ingest_and_feedback_bind_smoke(tmp_path: Path) -> None:
    """Fresh package CLI path: help + smoke ingest/bind with temp roots."""
    import subprocess

    science_src = ROOT / "xinao_discovery" / "src"
    env = {**dict(**__import__("os").environ), "PYTHONPATH": str(science_src)}
    help_proc = subprocess.run(
        [sys.executable, "-m", "xinao.cli", "research-episode", "-h"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT / "xinao_discovery"),
    )
    assert help_proc.returncode == 0, help_proc.stderr
    assert "pool-ingest" in help_proc.stdout or "pool-ingest" in help_proc.stderr
    assert "feedback-bind" in help_proc.stdout or "feedback-bind" in help_proc.stderr

    manifest = _manifest(episode_id="ep_pkg_cli", attempt="b" * 64)
    man_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    body = {
        "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1",
        "status": "CANDIDATE_EVIDENCE_EXPORTED",
        "episode_id": "ep_pkg_cli",
        "attempt_id": "att_pkg",
        "attempt_hash": "a" * 64,
        "attempt_cas_digest": "b" * 64,
        "raw_session_hash": "c" * 64,
        "tool_trace_hash": "d" * 64,
        "artifact_manifest_hash": "e" * 64,
        "candidate_manifest_sha256": _sha(man_bytes),
        "pair_receipt_sha256": "11" * 32,
        "namespace_receipt_sha256": "22" * 32,
        "release_identity_sha256": "33" * 32,
        "provider_session_uuid": "00000000-0000-4000-8000-0000000000bb",
        "research_profile": "OPEN_RESEARCH",
        "actual_turns": 6,
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
    bundle_hash = _sha(
        (json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    export = {**body, "bundle_sha256": bundle_hash}
    export_path = tmp_path / "export.json"
    manifest_path = tmp_path / "candidate_manifest.v1.json"
    export_path.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.write_bytes(man_bytes)
    pool_root = tmp_path / "pool"
    ingest = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao.cli",
            "research-episode",
            "pool-ingest",
            "--pool-root",
            str(pool_root),
            "--export",
            str(export_path),
            "--manifest",
            str(manifest_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT / "xinao_discovery"),
    )
    assert ingest.returncode == 0, ingest.stdout + ingest.stderr
    result = json.loads(ingest.stdout)
    assert result["owner_adopted"] is False
    assert result["freeze_written"] is False
    assert result["status"] == "POOL_ENTRY_READY"

    from xinao.canonical import canonical_sha256

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
    bind = subprocess.run(
        [
            sys.executable,
            "-m",
            "xinao.cli",
            "research-episode",
            "feedback-bind",
            "--portfolio-root",
            str(tmp_path),
            "--feedback-content-hash",
            content_hash,
            "--prior-candidate-result-sha256",
            "aa" * 32,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT / "xinao_discovery"),
    )
    assert bind.returncode == 0, bind.stdout + bind.stderr
    binding = json.loads(bind.stdout)
    assert binding["auto_start_next_research"] is False
    assert binding["owner_adopted"] is False


def test_mcp_binding_subagents_disabled_for_open_research(tmp_path: Path) -> None:
    bind_mod = _load("xinao_episode_mcp_binding_policy", DOCKER / "episode_mcp_binding.py")
    toml = bind_mod.render_config_toml(
        server_command="python",
        server_args=["-m", "mcp"],
        research_profile="OPEN_RESEARCH",
    )
    assert "[subagents]" in toml
    assert "enabled = false" in toml
    assert "enabled = true" not in toml.split("[subagents]")[1].split("[")[0]
