"""Attack tests: OPEN_RESEARCH productive lab path (candidate-only).

Covers profile split, argv/web, MCP lab ops, path alignment, attempt-delta
evidence, productive ops, and authority clamps. No live Docker/provider.
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
    return _load("xinao_native_open_research", PKG / "native_grok_session.py")


@pytest.fixture(scope="module")
def host_mod() -> Any:
    return _load("xinao_dual_host_open_research", SCRIPTS / "dual_container_host.py")


@pytest.fixture(scope="module")
def bind_mod() -> Any:
    _load("ipc_contract_or", PKG / "ipc_contract.py")
    return _load("xinao_episode_mcp_binding_or", PKG / "episode_mcp_binding.py")


@pytest.fixture(scope="module")
def mcp_mod() -> Any:
    _load("ipc_contract_or2", PKG / "ipc_contract.py")
    # transport_broker may be needed; load server with path
    return _load("xinao_mcp_lab_or", PKG / "mcp_episode_lab_server.py")


@pytest.fixture(scope="module")
def ipc_mod() -> Any:
    return _load("ipc_contract_or3", PKG / "ipc_contract.py")


def _provider_stdout(*, session_id: str, turns: int = 4) -> bytes:
    payload = {
        "session_id": session_id,
        "stop_reason": "end_turn",
        "model": "grok-4.5",
        "turn_count": turns,
        "type": "result",
    }
    return (json.dumps(payload) + "\n").encode("utf-8")


def _hash_event(body: dict[str, Any]) -> str:
    raw = (
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _append_tool_sidecar_event(
    episode_root: Path,
    *,
    event_hash: str,
    episode_id: str,
    op: str = "write_file",
    path_relative: str = "candidate/candidate_manifest.v1.json",
) -> None:
    """Independently sealed tool-executor evidence (not under transport /output)."""
    tool_path = episode_root / "sidecar_evidence" / "tool_events.jsonl"
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.tool_executor_sidecar_event.v1",
        "event_hash": event_hash,
        "op": op,
        "episode_id": episode_id,
        "status": "ok",
        "path_relative": path_relative,
        "productive": True,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    with tool_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _append_productive_event(
    path: Path,
    *,
    episode_id: str,
    op: str = "write_file",
    status: str = "ok",
    path_relative: str = "candidate/candidate_manifest.v1.json",
    sidecar_event_hash: str | None = None,
    episode_root: Path | None = None,
) -> str:
    sidecar = sidecar_event_hash or ("ab" * 32)
    body = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_tools_call",
        "episode_id": episode_id,
        "op": op,
        "status": status,
        "productive": op in {"write_file", "shell_exec"},
        "server": "episode_lab",
        "sidecar_event_hash": sidecar,
        "path_relative": path_relative,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    event_hash = _hash_event(body)
    line = {**body, "event_hash": event_hash}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n")
    # Prefer explicit episode_root; else infer from .../output/mcp_events.jsonl
    root = episode_root
    if root is None and path.name == "mcp_events.jsonl" and path.parent.name == "output":
        root = path.parent.parent
    if root is not None:
        _append_tool_sidecar_event(
            root,
            event_hash=sidecar,
            episode_id=episode_id,
            op=op,
            path_relative=path_relative,
        )
    return event_hash


def _write_lab_candidate_manifest(
    lab_root: Path, *, episode_id: str, attempt_cas: str | None = None
) -> bytes:
    payload = {
        "schema_version": "xinao.research_episode_candidate_manifest.v1",
        "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        "candidate_id": "cand_open_research_1",
        "candidate_version": "v1",
        "episode_id": episode_id,
        "attempt_cas_digest": attempt_cas,
        "research_question": "what survives a failed experiment then revise?",
        "research_object": "bounded OPEN_RESEARCH episode candidate",
        "data_cutoff": {
            "as_of": "2026-07-31T00:00:00Z",
            "material_refs": [{"id": "mat1", "sha256": "11" * 32}],
        },
        "method_refs": ["shell_experiment", "black_box_ok"],
        "falsifiers": ["failed first shell"],
        "account_recommendation": "NO_RECOMMENDATION",
        "proposed": None,
        "candidate_only": True,
        "owner_adopted": False,
        "completion": False,
    }
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    dest = lab_root / "candidate" / "candidate_manifest.v1.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return raw


def test_open_research_argv_has_meta_web_no_disable(native: Any) -> None:
    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, prompt="lab", research_profile="OPEN_RESEARCH"
    )
    native.assert_live_research_argv(argv, research_profile="OPEN_RESEARCH")
    tools = argv[argv.index("--tools") + 1]
    assert tools == "search_tool,use_tool,web_search,web_fetch"
    assert "--disable-web-search" not in argv
    denied = argv[argv.index("--disallowed-tools") + 1]
    assert "run_terminal_cmd" in denied and "read_file" in denied
    assert "web_search" not in denied and "web_fetch" not in denied
    assert argv[argv.index("--cwd") + 1] == "/episode-lab"
    assert argv[argv.index("--agent") + 1] == "/grok-home/agents/genuine_scientist_mcp.md"


def test_closed_lab_and_canary_restrictions(native: Any) -> None:
    sid = native.new_session_uuid()
    closed = native.build_genuine_session_argv(
        session_id=sid, max_turns=16, research_profile="CLOSED_LAB"
    )
    native.assert_live_research_argv(closed, research_profile="CLOSED_LAB")
    assert closed[closed.index("--tools") + 1] == "search_tool,use_tool"
    assert "--disable-web-search" in closed
    denied = closed[closed.index("--disallowed-tools") + 1]
    assert "web_search" in denied and "web_fetch" in denied

    canary = native.build_canary_argv()
    native.assert_argv_is_canary(canary)
    assert canary[canary.index("--tools") + 1] == ""
    assert "--disable-web-search" in canary
    assert canary[canary.index("--max-turns") + 1] == "1"

    with pytest.raises(native.NativeSessionError) as exc:
        native.assert_live_research_argv(canary, research_profile="OPEN_RESEARCH")
    assert exc.value.reason_code in {
        "GENUINE_TOOLS_MISMATCH",
        "CANARY_ARGV_ON_GENUINE_PATH",
        "LIVE_MAX_TURNS_TOO_LOW",
        "GENUINE_MAX_TURNS_CANARY_SHAPED",
    }


def test_open_research_rejects_disable_web_on_assert(native: Any) -> None:
    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(session_id=sid, max_turns=16)
    poisoned = list(argv) + ["--disable-web-search"]
    with pytest.raises(native.NativeSessionError) as exc:
        native.assert_live_research_argv(poisoned, research_profile="OPEN_RESEARCH")
    assert exc.value.reason_code == "OPEN_RESEARCH_WEB_DISABLED"


def test_path_alignment_fail_closed(bind_mod: Any) -> None:
    bind_mod.assert_path_alignment(
        grok_home="/grok-home",
        agent_profile="/grok-home/agents/genuine_scientist_mcp.md",
        config_toml="/grok-home/config.toml",
        evidence_path="/output/mcp_events.jsonl",
        cwd="/episode-lab",
    )
    with pytest.raises(ValueError):
        bind_mod.assert_path_alignment(grok_home="/attempt/grok-home")
    with pytest.raises(ValueError):
        bind_mod.assert_path_alignment(
            grok_home="/grok-home", evidence_path="/output/mcp-evidence.jsonl"
        )


def test_mcp_server_exposes_lab_ops_not_meta(mcp_mod: Any) -> None:
    tools = mcp_mod._list_tools()
    names = {t["name"] for t in tools}
    assert names == {"ping", "list_dir", "read_file", "write_file", "shell_exec"}
    assert "search_tool" not in names and "use_tool" not in names
    assert mcp_mod._normalize_op_name("episode_lab__write_file") == "write_file"
    assert mcp_mod._normalize_op_name("episode_lab.shell_exec") == "shell_exec"


def test_ipc_timeout_allows_long_experiments(ipc_mod: Any) -> None:
    assert ipc_mod.DEFAULT_TIMEOUT_MS == 600_000
    assert ipc_mod.MAX_TIMEOUT_MS == 3_600_000
    req = ipc_mod.build_request(
        op="shell_exec",
        episode_id="ep",
        args={"argv": ["/usr/bin/python3", "-c", "print(1)"]},
        timeout_ms=600_000,
    )
    assert req["timeout_ms"] == 600_000
    with pytest.raises(ipc_mod.IpcContractError) as exc:
        ipc_mod.build_request(op="ping", episode_id="ep", timeout_ms=3_600_001)
    assert exc.value.reason_code == "TIMEOUT_OUT_OF_RANGE"
    with pytest.raises(ipc_mod.IpcContractError):
        ipc_mod.build_request(op="freeze", episode_id="ep")


def test_binding_canonical_evidence_and_open_profile(bind_mod: Any, tmp_path: Path) -> None:
    receipt = bind_mod.materialize_attempt_local_binding(
        root=tmp_path / "bind",
        episode_id="ep-open",
        server_path=str(PKG / "mcp_episode_lab_server.py"),
        pythonpath=str(PKG),
        research_profile="OPEN_RESEARCH",
    )
    assert receipt["research_profile"] == "OPEN_RESEARCH"
    assert receipt["evidence_path"] == "/output/mcp_events.jsonl"
    assert "web_search" in receipt["tools_allowlist"]
    cfg = Path(receipt["config_toml"]).read_text(encoding="utf-8")
    assert "/output/mcp_events.jsonl" in cfg
    assert "mcp-evidence" not in cfg
    assert "tool_timeout_sec = 600" in cfg or "tool_timeout_sec = 600" in cfg.replace(" ", "")
    profile = Path(receipt["agent_profile"]).read_text(encoding="utf-8")
    assert "web_search" in profile
    assert "run_terminal_cmd" in profile  # denied


def test_stale_truncation_discovery_foreign_episode(native: Any, tmp_path: Path) -> None:
    path = tmp_path / "mcp_events.jsonl"
    # Prior discovery-only
    body0 = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_server_start",
        "episode_id": "epA",
        "productive": False,
        "server": "episode_lab",
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    h0 = _hash_event(body0)
    path.write_text(
        json.dumps({**body0, "event_hash": h0}, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    cursor = native.capture_mcp_event_cursor(path)
    # No append → stale-only
    delta = native.collect_attempt_mcp_delta(path, cursor, expected_episode_id="epA")
    assert delta["status"] == "STALE_ONLY"
    with pytest.raises(native.NativeSessionError) as exc:
        native.require_productive_lab_delta(delta)
    assert exc.value.reason_code == "MCP_DELTA_STALE_OR_EMPTY"

    # Discovery-only append still not productive
    body1 = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_tools_list",
        "episode_id": "epA",
        "productive": False,
        "server": "episode_lab",
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    h1 = _hash_event(body1)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({**body1, "event_hash": h1}, sort_keys=True, separators=(",", ":")) + "\n"
        )
    delta2 = native.collect_attempt_mcp_delta(path, cursor, expected_episode_id="epA")
    assert delta2["status"] == "DELTA_OK"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.require_productive_lab_delta(delta2)
    assert exc2.value.reason_code == "PRODUCTIVE_LAB_OP_MISSING"

    # Foreign episode
    body_f = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_tools_call",
        "episode_id": "epFOREIGN",
        "op": "write_file",
        "status": "ok",
        "productive": True,
        "server": "episode_lab",
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    hf = _hash_event(body_f)
    cursor2 = native.capture_mcp_event_cursor(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({**body_f, "event_hash": hf}, sort_keys=True, separators=(",", ":")) + "\n"
        )
    with pytest.raises(native.NativeSessionError) as exc3:
        native.collect_attempt_mcp_delta(path, cursor2, expected_episode_id="epA")
    assert exc3.value.reason_code == "MCP_EVENT_FOREIGN_EPISODE"

    # Truncation
    cursor3 = native.capture_mcp_event_cursor(path)
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(native.NativeSessionError) as exc4:
        native.collect_attempt_mcp_delta(path, cursor3)
    assert exc4.value.reason_code in {"MCP_EVENT_TRUNCATED", "MCP_EVENT_REWRITTEN"}


def test_successful_attempt_requires_productive_delta(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(session_id=sid, max_turns=16, prompt="x")
    out = _provider_stdout(session_id=sid, turns=5)
    # Missing productive → fail
    bad = native.build_live_attempt_record(
        episode_id="ep1",
        host_session_id="hs1",
        provider_session_uuid=sid,
        attempt_id="att1",
        argv=argv,
        stdout=out,
        stderr=b"",
        exit_code=0,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=120,
        started_at="2026-07-31T00:00:00Z",
        finished_at="2026-07-31T00:01:00Z",
        transport_container_id="t1",
        tool_container_id="t2",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="r",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": []},
        prior_attempt_hash=None,
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        productive_lab_ops=[],
        mcp_delta_status="DELTA_OK",
        require_productive_lab_op=True,
    )
    assert bad["status"] == native.STATUS_ATTEMPT_FAILED
    assert "PRODUCTIVE_LAB_OP_MISSING" in bad["failure_reasons"]

    good = native.build_live_attempt_record(
        episode_id="ep1",
        host_session_id="hs1",
        provider_session_uuid=sid,
        attempt_id="att2",
        argv=argv,
        stdout=out,
        stderr=b"",
        exit_code=0,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=120,
        started_at="2026-07-31T00:00:00Z",
        finished_at="2026-07-31T00:01:00Z",
        transport_container_id="t1",
        tool_container_id="t2",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="r",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": [{"path": "notes.md", "sha256": "f" * 64}]},
        prior_attempt_hash=None,
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        productive_lab_ops=["write_file"],
        mcp_delta_status="DELTA_OK",
        require_productive_lab_op=True,
    )
    assert good["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    assert good["research_profile"] == "OPEN_RESEARCH"
    assert good["web_enabled"] is True
    assert good["completion_claim_allowed"] is False


def test_mocked_nonzero_timeout_malformed(native: Any) -> None:
    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(session_id=sid, max_turns=16, prompt="x")
    common = dict(
        episode_id="ep",
        host_session_id="hs",
        provider_session_uuid=sid,
        attempt_id="att",
        argv=argv,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=60,
        started_at="t0",
        finished_at="t1",
        transport_container_id="t1",
        tool_container_id="t2",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="r",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": []},
        prior_attempt_hash=None,
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        productive_lab_ops=["shell_exec"],
        mcp_delta_status="DELTA_OK",
    )
    nz = native.build_live_attempt_record(
        **common, stdout=_provider_stdout(session_id=sid), stderr=b"", exit_code=1
    )
    assert nz["status"] == native.STATUS_ATTEMPT_FAILED
    assert any("NONZERO_EXIT" in r for r in nz["failure_reasons"])

    to = native.build_live_attempt_record(
        **common,
        stdout=_provider_stdout(session_id=sid),
        stderr=b"",
        exit_code=124,
        timed_out=True,
    )
    assert to["status"] == native.STATUS_ATTEMPT_FAILED
    assert "OUTER_TIMEOUT" in to["failure_reasons"]

    mal = native.build_live_attempt_record(**common, stdout=b"not-json", stderr=b"", exit_code=0)
    assert mal["status"] == native.STATUS_ATTEMPT_FAILED
    assert any("PROVIDER" in r or "MALFORMED" in r or "EMPTY" in r for r in mal["failure_reasons"])

    with pytest.raises(native.NativeSessionError):
        native.reject_non_live_driver(synthetic=False, driver="mock_fixture", planned_only=False)


def test_dual_host_open_research_argv_and_profile(
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
    created = host.create_pair(
        episode_id="ep_open", session_id=host_session, research_profile="OPEN_RESEARCH"
    )
    assert created["lease"]["research_profile"] == "OPEN_RESEARCH"
    inv = host.load_session_inventory()
    assert inv is not None and inv["research_profile"] == "OPEN_RESEARCH"
    # Binding evidence path
    cfg_path = tmp_path / "ep" / "attempt" / "grok-home" / "config.toml"
    text = cfg_path.read_text(encoding="utf-8")
    assert "/output/mcp_events.jsonl" in text
    assert "mcp-evidence" not in text

    argv = host.build_grok_session_argv(
        resume=False, session_id=str(inv["grok_session_id"]), max_turns=16, prompt="lab"
    )
    native.assert_live_research_argv(argv, research_profile="OPEN_RESEARCH")
    assert "--disable-web-search" not in argv
    assert "web_search" in argv[argv.index("--tools") + 1]
    assert argv[argv.index("--cwd") + 1] == "/episode-lab"

    closed_host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="t",
            tool_image="u",
            auth_host_path=tmp_path / "auth2",
            episode_root=tmp_path / "ep2",
            synthetic=True,
        )
    )
    (tmp_path / "auth2").mkdir()
    closed_host.create_pair(
        episode_id="ep_closed",
        session_id=f"xrsess_{uuid.uuid4().hex[:8]}",
        research_profile="CLOSED_LAB",
    )
    cargv = closed_host.build_grok_session_argv(
        resume=False,
        session_id=str(closed_host.load_session_inventory()["grok_session_id"]),
        max_turns=16,
    )
    assert "--disable-web-search" in cargv


def test_attach_run_delta_productive_mocked(
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
    syn.create_pair(episode_id="ep_delta", session_id=host_session)
    syn.start_pair()
    lease = syn.load_lease()
    assert lease is not None
    lease["tool_container_id"] = "toolcid123"
    lease["transport_container_id"] = "transportcid123"
    lease["phase"] = "running"
    # seed stale discovery event
    mcp_path = tmp_path / "ep" / "output" / "mcp_events.jsonl"
    stale_body = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "event": "mcp_server_start",
        "episode_id": "ep_delta",
        "productive": False,
        "server": "episode_lab",
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    sh = _hash_event(stale_body)
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(
        json.dumps({**stale_body, "event_hash": sh}, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
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
        assert env is not None
        assert env["GROK_HOME"] == "/grok-home"
        assert env["XINAO_MCP_EVENT_LOG"] == "/output/mcp_events.jsonl"
        assert "/attempt/" not in env["GROK_HOME"]
        native.assert_live_research_argv(list(argv), research_profile="OPEN_RESEARCH")
        assert "--disable-web-search" not in list(argv)
        assert "--always-approve" in list(argv)
        assert "--no-subagents" in list(argv)
        # Productive op with sidecar hash + real lab FS effect (manifest path).
        _write_lab_candidate_manifest(tmp_path / "ep" / "lab", episode_id="ep_delta")
        _append_productive_event(
            mcp_path,
            episode_id="ep_delta",
            op="write_file",
            path_relative="candidate/candidate_manifest.v1.json",
            episode_root=tmp_path / "ep",
        )
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=0,
            stdout=_provider_stdout(session_id=sid, turns=6),
            stderr=b"",
        )

    monkeypatch.setattr(live_host, "require_live_pair_ready", fake_ready)
    monkeypatch.setattr(live_host, "exec_transport_grok", fake_exec)

    result = live_host.attach_run_live(
        prompt="productive lab write",
        max_turns=16,
        timeout_seconds=120,
        expected_episode_id="ep_delta",
        expected_host_session_id=host_session,
        cas_head_sha256="a" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="researcher-test",
        release_identity_sha256="d" * 64,
    )
    assert result["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    assert "write_file" in (result.get("productive_lab_ops") or [])
    assert result["research_profile"] == "OPEN_RESEARCH"
    assert result["completion_claim_allowed"] is False
    assert result["mcp_delta_status"] == "DELTA_OK"

    # Export
    bundle = live_host.export_candidate_evidence(
        attempt_cas_digest=result["attempt_cas_digest"],
        episode_id="ep_delta",
        cas_head_sha256="a" * 64,
        expected_provider_session_uuid=sid,
        namespace_receipt_sha256="c" * 64,
    )
    assert bundle["status"] == native.STATUS_CANDIDATE_EVIDENCE_EXPORTED
    assert "write_file" in bundle["productive_lab_ops"]
    assert bundle.get("shadow_write") is False
    assert bundle.get("next_task_created") is False
    assert bundle.get("freeze_written") is False
    assert bundle.get("settlement_written") is False


def test_no_authority_writes_in_export_bundle(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    argv = native.build_genuine_session_argv(session_id=sid, max_turns=16, prompt="x")
    attempt = native.build_live_attempt_record(
        episode_id="ep_auth",
        host_session_id="hs",
        provider_session_uuid=sid,
        attempt_id="att",
        argv=argv,
        stdout=_provider_stdout(session_id=sid),
        stderr=b"",
        exit_code=0,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=60,
        started_at="t0",
        finished_at="t1",
        transport_container_id="t1",
        tool_container_id="t2",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="r",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": []},
        prior_attempt_hash=None,
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        productive_lab_ops=["shell_exec"],
        mcp_delta_status="DELTA_OK",
    )
    assert attempt["status"] == native.STATUS_LIVE_ATTEMPT_RECORDED
    persisted = native.persist_live_attempt(tmp_path, attempt)
    # failed does not replace last successful (already success)
    failed = dict(attempt)
    failed["status"] = native.STATUS_ATTEMPT_FAILED
    failed["exit_code"] = 1
    failed["failure_reasons"] = ["NONZERO_EXIT:1"]
    body = {k: v for k, v in failed.items() if k != "attempt_hash"}
    failed["attempt_hash"] = hashlib.sha256(
        (
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    ).hexdigest()
    # build a failed via API
    bad = native.build_live_attempt_record(
        episode_id="ep_auth",
        host_session_id="hs",
        provider_session_uuid=sid,
        attempt_id="att_fail",
        argv=argv,
        stdout=_provider_stdout(session_id=sid),
        stderr=b"",
        exit_code=2,
        model=native.DEFAULT_LIVE_MODEL,
        max_turns=16,
        timeout_seconds=60,
        started_at="t0",
        finished_at="t1",
        transport_container_id="t1",
        tool_container_id="t2",
        transport_image_id="sha256:" + "1" * 64,
        tool_image_id="sha256:" + "2" * 64,
        pair_receipt_sha256="b" * 64,
        namespace_receipt_sha256="c" * 64,
        release_id="r",
        release_identity_sha256="d" * 64,
        cas_head_sha256="a" * 64,
        mcp_event_hashes=["e" * 64],
        lab_artifact_manifest={"artifacts": []},
        prior_attempt_hash=persisted.get("attempt_hash"),
        resume=False,
        live_executed=True,
        driver="dual_container_host_docker_exec",
        synthetic=False,
        productive_lab_ops=["write_file"],
        mcp_delta_status="DELTA_OK",
    )
    native.persist_live_attempt(tmp_path, bad)
    success_ptr = json.loads(
        (tmp_path / "attempts" / "last_successful.json").read_text(encoding="utf-8")
    )
    assert success_ptr["attempt_hash"] == persisted["attempt_hash"]
