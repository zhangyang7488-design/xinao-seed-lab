"""Native Grok session/MCP transport seam + self-attacks (portable).

No live Docker/model required. Fail closed when unavailable. Does not claim
role fitness, Owner adoption, or parent completion.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "docker" / "xinao-researcher"
SCRIPTS = ROOT / "skills" / "xinao" / "scripts"
SEALED_CANARY_SHA256 = "c9c1a132ac00ebde9b198db6eb12a1be456cbcfb8c66d892856997595e40c47e"


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
    return _load("xinao_native_grok_session", PKG / "native_grok_session.py")


@pytest.fixture(scope="module")
def host_mod() -> Any:
    return _load("xinao_dual_container_host_native", SCRIPTS / "dual_container_host.py")


@pytest.fixture(scope="module")
def bind_mod() -> Any:
    _load("ipc_contract", PKG / "ipc_contract.py")
    return _load("xinao_episode_mcp_binding_native", PKG / "episode_mcp_binding.py")


def test_canary_entrypoint_byte_exact() -> None:
    digest = hashlib.sha256((PKG / "entrypoint.py").read_bytes()).hexdigest()
    assert digest == SEALED_CANARY_SHA256
    text = (PKG / "entrypoint.py").read_text(encoding="utf-8")
    assert "GENUINE_SCIENTIST_EPISODE" not in text
    assert ' "--tools",' in text or "\"--tools\"" in text


def test_cli_probe_and_fail_closed_contract(native: Any) -> None:
    probe = native.probe_grok_cli(probe_auth=True)
    doc = probe.as_dict()
    assert doc["schema_version"] == native.PROBE_SCHEMA
    assert doc["completion_claim_allowed"] is False
    # Worker seat has grok binary.
    assert probe.grok_bin
    for flag in (
        "--tools",
        "--session-id",
        "--resume",
        "--continue",
        "--max-turns",
        "--output-format",
    ):
        assert probe.flags_present.get(flag) is True, flag
    assert probe.mcp_available is True
    contract = native.fail_closed_live_invoke(probe=probe)
    assert contract["live_model_invoked"] is False
    assert contract["role_fitness_claimed"] is False
    assert contract["completion_claim_allowed"] is False
    if not probe.live_model_callable or not probe.docker_available:
        assert contract["status"] == "FAIL_CLOSED_LIVE_UNAVAILABLE"
        assert contract["reasons"]
    native.assert_argv_is_genuine_not_canary(contract["genuine_new_session_argv"])
    native.assert_argv_is_canary(contract["canary_argv"])
    # Resume uses --resume not --session-id
    resume = contract["genuine_resume_argv"]
    assert "--resume" in resume
    assert resume[resume.index("--tools") + 1] == "search_tool,use_tool"
    assert int(resume[resume.index("--max-turns") + 1]) >= 2


def test_canary_and_genuine_argv_divergence(native: Any) -> None:
    canary = native.build_canary_argv()
    sid = native.new_session_uuid()
    genuine = native.build_genuine_session_argv(session_id=sid, max_turns=16)
    native.assert_argv_is_canary(canary)
    native.assert_argv_is_genuine_not_canary(genuine)
    assert canary[canary.index("--tools") + 1] == ""
    assert genuine[genuine.index("--tools") + 1] == "search_tool,use_tool"
    with pytest.raises(native.NativeSessionError) as exc:
        native.build_genuine_session_argv(session_id=sid, max_turns=1)
    assert exc.value.reason_code == "MAX_TURNS_TOO_LOW"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.build_genuine_session_argv(session_id="not-a-uuid", resume=False)
    assert exc2.value.reason_code == "SESSION_ID_NOT_UUID"


def test_session_substitution_rejected(native: Any) -> None:
    expected = "xrsess_owner_exact"
    with pytest.raises(native.NativeSessionError) as exc:
        native.validate_resume_identity(
            expected_session_id=expected,
            inventory_session_id="xrsess_FOREIGN",
            lease_session_id=expected,
        )
    assert exc.value.reason_code == "FOREIGN_SESSION"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.validate_resume_identity(
            expected_session_id=expected,
            inventory_session_id=expected,
            lease_session_id="xrsess_LEASE_DRIFT",
        )
    assert exc2.value.reason_code == "RESUME_IDENTITY_DRIFT"
    # Happy path
    native.validate_resume_identity(
        expected_session_id=expected,
        inventory_session_id=expected,
        lease_session_id=expected,
        receipt_session_id=expected,
    )


def test_same_process_fake_resume_rejected(native: Any) -> None:
    ck = "a" * 64
    with pytest.raises(native.NativeSessionError) as exc:
        native.reject_same_process_fake_resume(
            checkpoint_bind_sha256=ck,
            prior_host_pid=os.getpid(),
            current_host_pid=os.getpid(),
            prior_transport_container_id="t1",
            current_transport_container_id="t1",
            containers_were_removed=False,
        )
    assert exc.value.reason_code == "SAME_PROCESS_FAKE_RESUME"
    # After removal, new container id required
    with pytest.raises(native.NativeSessionError) as exc2:
        native.reject_same_process_fake_resume(
            checkpoint_bind_sha256=ck,
            prior_host_pid=1,
            current_host_pid=2,
            prior_transport_container_id="t1",
            current_transport_container_id="t1",
            containers_were_removed=True,
        )
    assert exc2.value.reason_code == "CONTAINER_ID_REUSE_AFTER_REMOVAL"
    ok = native.reject_same_process_fake_resume(
        checkpoint_bind_sha256=ck,
        prior_host_pid=1,
        current_host_pid=2,
        prior_transport_container_id="t1",
        current_transport_container_id="t2",
        containers_were_removed=True,
    )
    assert ok["status"] == "FRESH_RESUME_GATES_OK"
    assert ok["completion_claim_allowed"] is False


def test_tool_event_fabrication_rejected(native: Any) -> None:
    body = {
        "schema_version": "xinao.dual_container_mcp_event.v1",
        "kind": "experiment",
        "turn": 1,
        "completion_claim_allowed": False,
    }
    good_hash = hashlib.sha256(
        (
            json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    ).hexdigest()
    trusted = [good_hash]
    good_event = {**body, "event_hash": good_hash}
    native.reject_fabricated_tool_event(event=good_event, trusted_event_hashes=trusted)
    # Wrong hash
    with pytest.raises(native.NativeSessionError) as exc:
        native.reject_fabricated_tool_event(
            event={**body, "event_hash": "b" * 64},
            trusted_event_hashes=trusted,
        )
    assert exc.value.reason_code == "TOOL_EVENT_FABRICATED"
    # Self-consistent but never emitted by sidecar
    with pytest.raises(native.NativeSessionError) as exc2:
        native.reject_fabricated_tool_event(
            event=good_event,
            trusted_event_hashes=["c" * 64],
        )
    assert exc2.value.reason_code == "TOOL_EVENT_UNTRUSTED"


def test_synthetic_receipt_promotion_rejected(native: Any) -> None:
    with pytest.raises(native.NativeSessionError) as exc:
        native.reject_synthetic_receipt_promotion(
            receipt={
                "synthetic": True,
                "tool_container_id": "synthetic-tool-abc",
                "completion_claim_allowed": False,
            },
            live_required=True,
        )
    assert exc.value.reason_code == "SYNTHETIC_RECEIPT_PROMOTION"
    with pytest.raises(native.NativeSessionError) as exc2:
        native.reject_synthetic_receipt_promotion(
            receipt={"completion_claim_allowed": True, "synthetic": False},
            live_required=False,
        )
    assert exc2.value.reason_code == "SYNTHETIC_RECEIPT_AUTHORITY"


def test_credential_reachability_negatives(native: Any) -> None:
    clean = native.credential_reachability_scan(
        env={"PATH": "/usr/bin", "HOME": "/tmp", "LANG": "C"},
        tool_mounts=["/episode-lab", "/ipc"],
    )
    assert clean["ok"] is True
    dirty = native.credential_reachability_scan(
        env={"XAI_API_KEY": "secret", "DOCKER_HOST": "unix:///var/run/docker.sock"},
        tool_mounts=["/episode-lab", "/grok-home/.grok/auth.json", "/var/run/docker.sock"],
    )
    assert dirty["ok"] is False
    assert any("XAI_API_KEY" in h for h in dirty["hits"])
    assert any("docker.sock" in h for h in dirty["hits"])


def test_mcp_binding_only_search_tool_use_tool(bind_mod: Any, tmp_path: Path) -> None:
    receipt = bind_mod.materialize_attempt_local_binding(
        root=tmp_path / "bind",
        episode_id="ep-native",
        socket_path="/ipc/tool.sock",
        server_path=str(PKG / "mcp_episode_lab_server.py"),
        pythonpath=str(PKG),
    )
    assert receipt["tools_allowlist"] == ["search_tool", "use_tool"]
    assert receipt["completion_claim_allowed"] is False
    assert receipt["global_config_modified"] is False
    cfg = Path(receipt["config_toml"]).read_text(encoding="utf-8")
    assert "mcp_servers.episode_lab" in cfg
    assert "mcp_episode_lab_server.py" in cfg
    profile = Path(receipt["agent_profile"]).read_text(encoding="utf-8")
    assert "search_tool" in profile
    assert "run_terminal_cmd" in profile  # denied list


def test_dual_host_resume_argv_uses_native_mcp_tools(
    host_mod: Any, tmp_path: Path
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
    host_session = f"xrsess_native_{uuid.uuid4().hex[:8]}"
    created = host.create_pair(episode_id="ep_native_1", session_id=host_session)
    assert created["mcp_server"] == "episode_lab"
    host.start_pair()
    inv = host.load_session_inventory()
    assert inv is not None
    # Grok session must be UUID even when host session is not.
    uuid.UUID(str(inv["grok_session_id"]))
    host.checkpoint_bind(progress_note="before interrupt")
    host.interrupt_pair()
    resumed = host.resume_pair(expected_session_id=host_session)
    argv = resumed["planned_grok_argv"]
    assert "--resume" in argv
    assert argv[argv.index("--tools") + 1] == "search_tool,use_tool"
    assert int(argv[argv.index("--max-turns") + 1]) >= 2
    # Foreign session rejected
    with pytest.raises(host_mod.DualHostError) as exc:
        host.resume_pair(expected_session_id="xrsess_FOREIGN")
    assert exc.value.reason_code in {
        "DUAL_HOST_FOREIGN_SESSION",
        "DUAL_HOST_RESUME_IDENTITY_DRIFT",
    }
    cancelled = host.cancel_pair()
    assert cancelled["status"] in {"CANCELLED", "CANCELLED_WITH_ERRORS", "CANCEL_IDEMPOTENT"}


def test_driver_plan_new_and_resume(native: Any, tmp_path: Path) -> None:
    sid = native.new_session_uuid()
    driver = native.NativeEpisodeSessionDriver(
        episode_id="ep_drv",
        session_id=sid,
        grok_home=tmp_path / "grok-home",
        work_root=tmp_path,
        grok_bin="/usr/local/bin/grok",
    )
    plan = driver.plan_new(prompt="fail then revise lab")
    assert plan["verb"] == "new_session"
    assert "--session-id" in plan["argv"]
    assert plan["argv"][plan["argv"].index("--session-id") + 1] == sid
    assert plan["completion_claim_allowed"] is False
    rplan = driver.plan_resume()
    assert "--resume" in rplan["argv"]


def test_cli_probe_subcommand_exit_zero() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(PKG / "native_grok_session.py"),
            "probe",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["completion_claim_allowed"] is False
    assert payload["live_model_invoked"] is False
    assert "genuine_new_session_argv" in payload
