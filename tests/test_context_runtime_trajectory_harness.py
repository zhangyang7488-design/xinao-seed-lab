from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = (
    REPO_ROOT / "evals" / "context_runtime_trajectory" / "run_context_runtime_trajectory.py"
)
SCHEMA_PATH = REPO_ROOT / "evals" / "context_runtime_trajectory" / "receipt.schema.json"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_behavior_regression.ps1"


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "context_runtime_trajectory_harness", HARNESS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_receipt_is_isolated_machine_readable_and_claim_bounded(tmp_path: Path) -> None:
    harness = _load_harness()
    operation_root = tmp_path / "operation"
    receipt = harness.run_contract(operation_root)

    assert receipt["schema_version"] == "s.context_runtime_trajectory_receipt.v1"
    assert receipt["mode"] == "contract"
    assert receipt["evidence_level"] == "deterministic_contract"
    assert receipt["claim_class"] == "context_contract_only"
    assert receipt["status"] == "passed"
    assert receipt["runtime_claim_allowed"] is False
    assert receipt["summary"]["selected"] == 4
    assert receipt["summary"]["passed"] == 4
    assert receipt["summary"]["failed"] == 0
    assert receipt["summary"]["ineligible"] == 0
    assert receipt["isolation"] == {
        "operation_scoped": True,
        "production_store_used": False,
        "production_codex_home_used": False,
        "separate_case_roots": True,
        "separate_enabled_and_empty_stores": True,
        "network_or_model_called": False,
    }
    assert {
        "model_used_rehydrated_context_correctly",
        "zero_tool_or_external_effect_in_a_model_turn",
        "fresh_compact_or_resume_app_server_protocol",
        "longitudinal_reduction_of_user_correction_burden",
    }.issubset(receipt["claim_boundary"]["does_not_prove"])
    for case in receipt["cases"]:
        assert case["status"] == "passed"
        assert case["runtime_claim_allowed"] is False
        assert case["failed_assertions"] == []
        assert case["assertions"]
        assert all(case["assertions"].values())
        assert not Path(case["case_root"]).is_absolute()


def test_fresh_ablation_recovers_nonce_only_from_enabled_store(tmp_path: Path) -> None:
    harness = _load_harness()
    receipt = harness.run_contract(
        tmp_path / "operation",
        r"^CTX_FRESH_ENABLED_VS_EMPTY_STORE$",
    )

    assert receipt["summary"]["selected"] == 1
    case = receipt["cases"][0]
    assert case["case_id"] == "CTX_FRESH_ENABLED_VS_EMPTY_STORE"
    assert case["evidence"]["nonce_recovery"] == {"enabled": 3, "empty": 0}
    assert (
        case["evidence"]["matched_source_ref_count"]
        == case["evidence"]["expected_source_ref_count"]
    )
    assert case["evidence"]["claim_scope"] == "mechanical_rehydration_delta_only"


def test_contract_case_pattern_fails_closed_when_it_selects_nothing(tmp_path: Path) -> None:
    harness = _load_harness()
    with pytest.raises(ValueError, match="selected no contract cases"):
        harness.run_contract(tmp_path / "operation", r"^DOES_NOT_EXIST$")


def test_operation_root_cannot_enter_production_context_or_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _load_harness()
    production_context = tmp_path / "production-context"
    production_home = tmp_path / "production-home"
    production_context.mkdir()
    production_home.mkdir()
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_CONTEXT_FABRIC_ROOT",
        production_context,
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(production_home): "s-primary"},
    )

    context_target = production_context / "must-not-create"
    home_target = production_home / "must-not-create"
    with pytest.raises(ValueError, match="production context or Codex homes"):
        harness.run_contract(context_target)
    with pytest.raises(ValueError, match="production context or Codex homes"):
        harness.run_contract(home_target)
    assert not context_target.exists()
    assert not home_target.exists()


def test_live_mode_is_typed_ineligible_and_never_inherits_contract_pass(tmp_path: Path) -> None:
    harness = _load_harness()
    receipt = harness.run_live(
        tmp_path / "live-operation",
        codex_path=None,
        s_codex_home=None,
        b_codex_home=None,
        working_dir=None,
        hook_sink=None,
    )

    assert receipt["mode"] == "live"
    assert receipt["evidence_level"] == "live_app_server_and_hook_sink"
    assert receipt["claim_class"] == "context_live_ineligible"
    assert receipt["status"] == "ineligible"
    assert receipt["runtime_claim_allowed"] is False
    assert receipt["cases"] == []
    assert "native_codex_0_147" in receipt["eligibility"]["missing_or_unverified"]
    assert "hook_sink_contract" in receipt["eligibility"]["missing_or_unverified"]
    assert receipt["claim_boundary"]["proves"] == [
        "live_mode_failed_closed_before_model_or_protocol_claim"
    ]


def test_live_case_pattern_fails_before_eligibility_checks(tmp_path: Path) -> None:
    harness = _load_harness()
    with pytest.raises(ValueError, match="selected no live cases"):
        harness.run_live(
            tmp_path / "live-operation",
            codex_path=None,
            s_codex_home=None,
            b_codex_home=None,
            working_dir=None,
            hook_sink=None,
            case_pattern=r"^DOES_NOT_EXIST$",
        )


def test_app_server_json_stdio_client_parses_interleaved_protocol(tmp_path: Path) -> None:
    harness = _load_harness()
    fake_server = tmp_path / "fake_app_server.py"
    fake_server.write_text(
        """\
import json
import sys

turn_counter = 0
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        print(json.dumps({"method": "config/warning", "params": {"message": "fixture"}}), flush=True)
        print(json.dumps({"id": request_id, "result": {"userAgent": "fixture"}}), flush=True)
    elif method == "hooks/list":
        print(json.dumps({"id": request_id, "result": {"data": []}}), flush=True)
    elif method in {"thread/start", "thread/resume"}:
        print(json.dumps({"id": request_id, "result": {"thread": {"id": "thread-fixture"}}}), flush=True)
    elif method == "turn/start":
        turn_counter += 1
        turn_id = f"turn-fixture-{turn_counter}"
        turn = {"id": turn_id, "items": [], "status": "inProgress"}
        print(json.dumps({"id": request_id, "result": {"turn": turn}}), flush=True)
        print(json.dumps({"method": "turn/started", "params": {"threadId": "thread-fixture", "turn": turn}}), flush=True)
        print(json.dumps({"method": "hook/completed", "params": {"run": {"eventName": "sessionStart", "status": "completed"}}}), flush=True)
        print(json.dumps({"method": "item/completed", "params": {"threadId": "thread-fixture", "turnId": turn_id, "item": {"id": f"item-fixture-{turn_counter}", "type": "agentMessage", "text": "FIXTURE-NONCE"}}}), flush=True)
        turn["status"] = "completed"
        print(json.dumps({"method": "turn/completed", "params": {"threadId": "thread-fixture", "turn": turn}}), flush=True)
""",
        encoding="utf-8",
    )

    with harness._AppServerClient(
        [sys.executable, str(fake_server)],
        cwd=tmp_path,
        environ=harness._minimal_windows_environment(os.environ),
    ) as client:
        client.initialize(timeout=5)
        assert client.request("hooks/list", {"cwds": [str(tmp_path)]}, timeout=5) == {"data": []}
        start = client.request("thread/start", {}, timeout=5)
        observed_steps: list[str] = []
        start_text, start_messages = harness._run_live_turn_then_observe_session_start(
            client,
            thread_id="thread-fixture",
            prompt="startup fixture prompt",
            working_dir=tmp_path,
            timeout=5,
            before_hook_wait=lambda: observed_steps.append("startup_hook"),
        )
        resume = client.request("thread/resume", {"threadId": "thread-fixture"}, timeout=5)
        resume_text, resume_messages = harness._run_live_turn_then_observe_session_start(
            client,
            thread_id="thread-fixture",
            prompt="resume fixture prompt",
            working_dir=tmp_path,
            timeout=5,
            before_hook_wait=lambda: observed_steps.append("resume_hook"),
        )

    assert start == resume == {"thread": {"id": "thread-fixture"}}
    assert start_text == resume_text == "FIXTURE-NONCE"
    assert "turn/started" in [message.get("method") for message in start_messages]
    assert "turn/started" in [message.get("method") for message in resume_messages]
    assert observed_steps == ["startup_hook", "resume_hook"]
    assert [
        method
        for method in client.sent_methods
        if method in {"thread/start", "thread/resume", "turn/start"}
    ] == ["thread/start", "turn/start", "thread/resume", "turn/start"]
    assert [message.get("method") for message in client.messages].count("hook/completed") == 2
    assert client.stderr_receipt["line_count"] == 0


def test_live_protocol_extractors_require_real_compaction_and_hook_shapes() -> None:
    harness = _load_harness()
    messages = [
        {
            "method": "item/completed",
            "params": {"item": {"id": "compact-1", "type": "contextCompaction"}},
        },
        {
            "method": "hook/completed",
            "params": {"run": {"eventName": "preCompact", "status": "completed"}},
        },
        {
            "method": "hook/completed",
            "params": {"run": {"eventName": "postCompact", "status": "completed"}},
        },
    ]

    assert harness._item_types(messages) == ["contextCompaction"]
    assert harness._hook_event_names(messages) == ["preCompact", "postCompact"]
    assert 'wait_notification("thread/compacted"' not in HARNESS_PATH.read_text(encoding="utf-8")


def test_fresh_live_probes_switch_only_fabric_root_and_hide_referents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    enabled_root = tmp_path / "enabled-fabric"
    empty_root = tmp_path / "empty-fabric"
    account_home = tmp_path / "account-home"
    source_env = {"PATH": "fixture-path", "FAKE_AMBIENT_SECRET": "must-not-cross"}
    enabled_env = harness._existing_account_environment(
        source_env, codex_home=account_home, fabric_root=enabled_root
    )
    empty_env = harness._existing_account_environment(
        source_env, codex_home=account_home, fabric_root=empty_root
    )
    anchor = "ANCHOR-FIXTURE"
    old_referent = "OLD-REFERENT-MUST-NOT-ENTER-PROMPT"
    current_referent = "CURRENT-REFERENT-MUST-NOT-ENTER-PROMPT"
    prompt = f"For hidden anchor {anchor}, reply with the current referent token only."
    protocol: list[tuple[str, str]] = []
    prompts: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, command, *, cwd, environ):
            self.root = Path(environ["CODEX_CONTEXT_FABRIC_ROOT"])
            self.label = "empty" if self.root == empty_root else "enabled"
            self.pid = 3101 if self.label == "empty" else 3102
            self.thread_id = f"thread-{self.label}"
            self.messages: list[dict[str, object]] = []
            self.sent_methods: list[str] = []
            self.stderr_receipt = {"line_count": 0, "sha256": ""}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def initialize(self, *, timeout):
            protocol.append((self.label, "initialize"))

        def request(self, method, params, *, timeout):
            protocol.append((self.label, method))
            self.sent_methods.append(method)
            if method == "thread/start":
                return {"thread": {"id": self.thread_id}}
            if method == "thread/name/set":
                self.messages.append(
                    {
                        "method": "thread/name/updated",
                        "params": {
                            "threadId": self.thread_id,
                            "threadName": params["name"],
                        },
                    }
                )
                return {}
            if method == "turn/start":
                turn_prompt = params["input"][0]["text"]
                prompts.append((self.label, turn_prompt))
                response = current_referent if self.label == "enabled" else "NO-MATCH"
                self.messages.extend(
                    [
                        {
                            "method": "item/completed",
                            "params": {"item": {"type": "agentMessage", "text": response}},
                        },
                        {
                            "method": "turn/completed",
                            "params": {
                                "threadId": self.thread_id,
                                "turn": {"id": f"turn-{self.label}", "status": "completed"},
                            },
                        },
                        {
                            "method": "hook/completed",
                            "params": {"run": {"eventName": "sessionStart"}},
                        },
                    ]
                )
                return {"turn": {"id": f"turn-{self.label}"}}
            raise AssertionError(f"unexpected request: {method}")

        def wait_notification(self, method, *, timeout, predicate=None):
            protocol.append((self.label, f"wait:{method}"))
            for message in self.messages:
                params = message.get("params", {})
                if message.get("method") == method and (predicate is None or predicate(params)):
                    return message
            raise AssertionError(f"missing notification: {method}")

    monkeypatch.setattr(harness, "_AppServerClient", FakeClient)
    steps: list[str] = []
    empty = harness._run_fresh_live_probe(
        ["fixture"],
        working_dir=tmp_path,
        environ=empty_env,
        model="fixture-model",
        prompt=prompt,
        thread_name="fresh-empty",
        timeout=30,
        step_prefix="fresh_empty",
        enter_step=steps.append,
    )
    enabled = harness._run_fresh_live_probe(
        ["fixture"],
        working_dir=tmp_path,
        environ=enabled_env,
        model="fixture-model",
        prompt=prompt,
        thread_name="fresh-enabled",
        timeout=30,
        step_prefix="fresh_enabled",
        enter_step=steps.append,
    )

    assert prompts == [("empty", prompt), ("enabled", prompt)]
    assert anchor in prompt and old_referent not in prompt and current_referent not in prompt
    assert old_referent not in empty["text"] and current_referent not in empty["text"]
    assert current_referent in enabled["text"] and old_referent not in enabled["text"]
    assert empty["process_id"] != enabled["process_id"]
    assert empty["thread_id"] != enabled["thread_id"]
    assert steps == [
        "fresh_empty_thread",
        "fresh_empty_turn",
        "fresh_empty_hook",
        "fresh_enabled_thread",
        "fresh_enabled_turn",
        "fresh_enabled_hook",
    ]
    for label in ("empty", "enabled"):
        sequence = [event for seen_label, event in protocol if seen_label == label]
        assert sequence.index("thread/start") < sequence.index("turn/start")
        assert sequence.index("turn/start") < sequence.index("wait:hook/completed")
    tool_types = {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall"}
    assert not tool_types.intersection(harness._item_types(empty["messages"]))
    assert not tool_types.intersection(harness._item_types(enabled["messages"]))
    assert "FAKE_AMBIENT_SECRET" not in empty_env
    assert "FAKE_AMBIENT_SECRET" not in enabled_env


def test_named_rollout_evidence_requires_three_exact_paths_without_opening_files() -> None:
    harness = _load_harness()
    thread_ids = {
        "main": "thread-main",
        "fresh_empty": "thread-empty",
        "fresh_enabled": "thread-enabled",
    }
    paths = [f"2026/08/13/rollout-{thread_id}.jsonl" for thread_id in thread_ids.values()]

    exact = harness._named_rollout_path_evidence(paths, thread_ids)
    with_extra = harness._named_rollout_path_evidence(
        [*paths, "2026/08/13/rollout-unrelated.jsonl"], thread_ids
    )

    assert exact["expected_named_test_rollouts"] == 3
    assert exact["exact_named_test_rollouts_written"] == 3
    assert exact["all_new_rollouts_match_named_threads"] is True
    assert with_extra["exact_named_test_rollouts_written"] == 3
    assert with_extra["all_new_rollouts_match_named_threads"] is False


def test_live_sink_contract_rejects_unadmitted_credential_channels(tmp_path: Path) -> None:
    harness = _load_harness()
    contract = tmp_path / "sink.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_env": "UNSAFE_SECRET_PATH",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not an admitted credential variable"):
        harness._load_live_sink_contract(contract)


def test_live_sink_contract_defaults_to_isolated_environment_and_opts_into_existing_b(
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    contract = tmp_path / "sink.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )

    isolated = harness._load_live_sink_contract(contract)
    assert isolated["auth_mode"] == "environment_isolated"
    assert isolated["auth_env"] == ""

    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_mode": "existing_b_home",
            }
        ),
        encoding="utf-8",
    )
    existing = harness._load_live_sink_contract(contract)
    assert existing["auth_mode"] == "existing_b_home"
    assert existing["auth_env"] == ""

    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_mode": "existing_b_home",
                "auth_env": "OPENAI_API_KEY",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot also select an auth_env"):
        harness._load_live_sink_contract(contract)


def test_existing_b_home_without_configured_auth_is_prelaunch_ineligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    codex_exe = tmp_path / "codex.exe"
    codex_exe.write_bytes(b"fixture")
    source_s = tmp_path / "source-s"
    source_b = tmp_path / "source-b"
    working_dir = tmp_path / "working"
    source_s.mkdir()
    source_b.mkdir()
    working_dir.mkdir()
    for name in ("AGENTS.md", "config.toml", "hooks.json"):
        (source_b / name).write_text("fixture\n", encoding="utf-8")
    contract = tmp_path / "sink.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_mode": "existing_b_home",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(source_s): "s-primary", str(source_b): "s-account-b"},
    )
    monkeypatch.setattr(harness, "_probe_codex_version", lambda *args, **kwargs: "0.147.0")

    class MustNotLaunch:
        def __init__(self, *args, **kwargs):
            raise AssertionError("native process must not launch before auth prerequisite")

    monkeypatch.setattr(harness, "_AppServerClient", MustNotLaunch)
    receipt = harness.run_live(
        tmp_path / "operation",
        codex_path=codex_exe,
        s_codex_home=source_s,
        b_codex_home=source_b,
        working_dir=working_dir,
        hook_sink=contract,
    )

    assert receipt["status"] == "ineligible"
    assert receipt["claim_class"] == "context_live_ineligible"
    assert receipt["summary"]["ineligible"] == 1
    assert "existing_b_home_auth_present" in receipt["eligibility"]["missing_or_unverified"]


def test_live_fabric_initialization_failure_is_observed_without_native_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    codex_exe = tmp_path / "codex.exe"
    codex_exe.write_bytes(b"fixture")
    source_s = tmp_path / "source-s"
    source_b = tmp_path / "source-b"
    working_dir = tmp_path / "working"
    source_s.mkdir()
    source_b.mkdir()
    working_dir.mkdir()
    for name in ("AGENTS.md", "config.toml", "hooks.json", "auth.json"):
        (source_b / name).write_text("fixture\n", encoding="utf-8")
    contract = tmp_path / "sink.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_mode": "existing_b_home",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(source_s): "s-primary", str(source_b): "s-account-b"},
    )
    monkeypatch.setattr(harness, "_probe_codex_version", lambda *args, **kwargs: "0.147.0")

    def fail_initialize(root: Path) -> dict[str, object]:
        raise harness.context_runtime.ContextFabricUnavailable("fixture unavailable")

    class MustNotLaunch:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "native process must not launch after Fabric initialization failure"
            )

    monkeypatch.setattr(harness.context_runtime, "initialize_context_fabric", fail_initialize)
    monkeypatch.setattr(harness, "_AppServerClient", MustNotLaunch)
    receipt = harness.run_live(
        tmp_path / "operation",
        codex_path=codex_exe,
        s_codex_home=source_s,
        b_codex_home=source_b,
        working_dir=working_dir,
        hook_sink=contract,
    )

    assert receipt["status"] == "failed"
    assert receipt["claim_class"] == "context_live_observed"
    assert receipt["summary"]["failed"] == 1
    evidence = receipt["cases"][0]["evidence"]
    assert evidence["failure_stage"] == "post_eligibility_fabric_initialization"
    assert evidence["protocol_step"] == "fabric_initialize"
    assert evidence["protocol_trace"] == ["fabric_initialize"]
    assert evidence["error_type"] == "ContextFabricUnavailable"
    assert "fixture unavailable" not in json.dumps(receipt)


def test_live_app_server_child_receives_only_selected_fake_auth(tmp_path: Path) -> None:
    harness = _load_harness()
    fake_server = tmp_path / "fake_env_server.py"
    fake_server.write_text(
        """\
import json
import os
import sys

for line in sys.stdin:
    message = json.loads(line)
    request_id = message.get("id")
    if message.get("method") == "initialize":
        result = {"userAgent": "fixture"}
    else:
        result = {"environment": dict(os.environ)}
    print(json.dumps({"id": request_id, "result": result}), flush=True)
""",
        encoding="utf-8",
    )
    live_home = tmp_path / "isolated-home"
    fabric_root = tmp_path / "isolated-fabric"
    source = harness._minimal_windows_environment(os.environ)
    source["OPENAI_API_KEY"] = "sk-fake-selected-auth-value"
    source["CODEX_ACCESS_TOKEN"] = "fake-nonselected-auth-value"
    source["FAKE_AMBIENT_SECRET"] = "fake-must-not-cross"
    child_env = harness._live_app_server_environment(
        source,
        codex_home=live_home,
        fabric_root=fabric_root,
        auth_env="OPENAI_API_KEY",
    )

    with harness._AppServerClient(
        [sys.executable, str(fake_server)],
        cwd=tmp_path,
        environ=child_env,
    ) as client:
        client.initialize(timeout=5)
        result = client.request("fixture/environment", {}, timeout=5)

    observed = result["environment"]
    assert observed["OPENAI_API_KEY"] == "sk-fake-selected-auth-value"
    assert "CODEX_ACCESS_TOKEN" not in observed
    assert "FAKE_AMBIENT_SECRET" not in observed
    assert observed["CODEX_HOME"] == str(live_home)
    assert observed["CODEX_CONTEXT_FABRIC_ROOT"] == str(fabric_root)
    assert not (live_home / "auth.json").exists()
    assert set(child_env).issubset(
        set(harness._WINDOWS_CHILD_ENV_NAMES)
        | {"CODEX_HOME", "CODEX_CONTEXT_FABRIC_ROOT", "OPENAI_API_KEY"}
    )


def test_hook_wrapper_strips_all_auth_and_ambient_secrets_from_adapter(
    tmp_path: Path,
) -> None:
    harness = _load_harness()
    adapter_env_path = tmp_path / "adapter-environment.json"
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        f"""\
import json
import os
from pathlib import Path
import sys

Path({str(adapter_env_path)!r}).write_text(json.dumps(dict(os.environ)), encoding="utf-8")
sys.stdin.buffer.read()
sys.stdout.write('{{"continue":true}}\\n')
""",
        encoding="utf-8",
    )
    source_home = tmp_path / "source-s-home"
    source_home.mkdir()
    fabric_root = tmp_path / "fabric"
    empty_fabric_root = tmp_path / "empty-fabric"
    wrapper = tmp_path / "hook_sink_wrapper.py"
    harness._write_live_hook_wrapper(
        wrapper,
        log_path=tmp_path / "hook-sink.jsonl",
        adapter_path=fake_adapter,
        source_codex_home=source_home,
        fabric_root=fabric_root,
        working_dir=tmp_path,
        additional_fabric_roots=(empty_fabric_root,),
    )
    wrapper_env = harness._minimal_windows_environment(os.environ)
    wrapper_env["OPENAI_API_KEY"] = "sk-fake-wrapper-auth"
    wrapper_env["CODEX_ACCESS_TOKEN"] = "fake-wrapper-access-token"
    wrapper_env["FAKE_AMBIENT_SECRET"] = "fake-wrapper-ambient"
    wrapper_env["CODEX_CONTEXT_FABRIC_ROOT"] = str(empty_fabric_root.resolve())
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(wrapper)],
        input=json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "019ff75c-703c-7972-96cd-b0d257b13baa",
            }
        ),
        cwd=tmp_path,
        env=wrapper_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    adapter_env = json.loads(adapter_env_path.read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" not in adapter_env
    assert "CODEX_ACCESS_TOKEN" not in adapter_env
    assert "FAKE_AMBIENT_SECRET" not in adapter_env
    assert adapter_env["CODEX_HOME"] == str(source_home)
    assert adapter_env["CODEX_CONTEXT_FABRIC_ROOT"] == str(empty_fabric_root.resolve())

    wrapper_env["CODEX_CONTEXT_FABRIC_ROOT"] = str(tmp_path / "unadmitted-fabric")
    unadmitted = subprocess.run(
        [sys.executable, "-I", "-B", str(wrapper)],
        input="{}",
        cwd=tmp_path,
        env=wrapper_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert unadmitted.returncode == 0, unadmitted.stderr
    fallback_env = json.loads(adapter_env_path.read_text(encoding="utf-8"))
    assert fallback_env["CODEX_CONTEXT_FABRIC_ROOT"] == str(fabric_root.resolve())


def test_post_eligibility_protocol_error_is_observed_failure_and_cli_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    codex_exe = tmp_path / "codex.exe"
    codex_exe.write_bytes(b"fixture")
    source_s = tmp_path / "source-s"
    source_b = tmp_path / "source-b"
    source_s.mkdir()
    source_b.mkdir()
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    sink_contract = tmp_path / "hook-sink-contract.json"
    sink_contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_env": "OPENAI_API_KEY",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(source_s): "s-primary", str(source_b): "s-account-b"},
    )
    monkeypatch.setattr(harness, "_probe_codex_version", lambda *args, **kwargs: "0.147.0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-protocol-auth")
    monkeypatch.setenv("FAKE_AMBIENT_SECRET", "fake-protocol-ambient")
    observed_child_env: dict[str, str] = {}

    class BrokenProtocolClient:
        def __init__(self, command, *, cwd, environ):
            observed_child_env.update(environ)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def initialize(self, *, timeout):
            raise harness.LiveProtocolError("fixture protocol failure")

    monkeypatch.setattr(harness, "_AppServerClient", BrokenProtocolClient)
    operation_root = tmp_path / "operation"
    output = tmp_path / "receipt.json"
    exit_code = harness.main(
        [
            "--mode",
            "live",
            "--operation-root",
            str(operation_root),
            "--output",
            str(output),
            "--codex-path",
            str(codex_exe),
            "--s-codex-home",
            str(source_s),
            "--b-codex-home",
            str(source_b),
            "--working-dir",
            str(working_dir),
            "--hook-sink",
            str(sink_contract),
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(receipt)
    assert exit_code == 1
    assert receipt["claim_class"] == "context_live_observed"
    assert receipt["status"] == "failed"
    assert receipt["runtime_claim_allowed"] is False
    assert receipt["summary"] == {
        "selected": 1,
        "passed": 0,
        "failed": 1,
        "ineligible": 0,
    }
    assert receipt["cases"][0]["failed_assertions"] == ["native_live_protocol_completed"]
    assert "OPENAI_API_KEY" in observed_child_env
    assert "FAKE_AMBIENT_SECRET" not in observed_child_env
    assert "sk-fake-protocol-auth" not in serialized
    assert "fake-protocol-ambient" not in serialized
    assert not (operation_root / "isolated-codex-home" / "auth.json").exists()


def test_existing_b_home_uses_configured_account_without_forwarding_or_copying_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    codex_exe = tmp_path / "codex.exe"
    codex_exe.write_bytes(b"fixture")
    source_s = tmp_path / "source-s"
    source_b = tmp_path / "source-b"
    source_s.mkdir()
    source_b.mkdir()
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    protected_contents = {
        "AGENTS.md": b"fixture agents\n",
        "config.toml": b"model = 'fixture'\n",
        "hooks.json": b'{"hooks": []}\n',
        "auth.json": b'{"fixture": "opaque-test-account-state"}\n',
    }
    for name, contents in protected_contents.items():
        (source_b / name).write_bytes(contents)
    hashed_paths: list[Path] = []
    original_sha256_file = harness._sha256_file

    def tracked_sha256_file(path: Path) -> str:
        hashed_paths.append(path)
        return original_sha256_file(path)

    monkeypatch.setattr(harness, "_sha256_file", tracked_sha256_file)
    protected_before = harness._account_protection_receipt(source_b)
    sink_contract = tmp_path / "hook-sink-contract.json"
    sink_contract.write_text(
        json.dumps(
            {
                "schema_version": "s.context_runtime_live_hook_sink.v1",
                "model": "gpt-5.6-sol",
                "timeout_seconds": 30,
                "auth_mode": "existing_b_home",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        harness.context_runtime,
        "DEFAULT_ALLOWED_CODEX_HOMES",
        {str(source_s): "s-primary", str(source_b): "s-account-b"},
    )
    monkeypatch.setattr(harness, "_probe_codex_version", lambda *args, **kwargs: "0.147.0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-must-not-reach-existing-home-child")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "fake-access-token-must-not-reach-child")
    monkeypatch.setenv("FAKE_AMBIENT_SECRET", "fake-ambient-must-not-reach-child")
    observed_child_env: dict[str, str] = {}
    protocol_events: list[str] = []
    fixture_session = "019ff75c-703c-7972-96cd-b0d257b13baa"

    class BrokenProtocolClient:
        pid = 43210

        def __init__(self, command, *, cwd, environ):
            observed_child_env.update(environ)
            self.messages = []
            self.sent_methods = []
            fabric_root = Path(environ["CODEX_CONTEXT_FABRIC_ROOT"])
            assert (fabric_root / "context_fabric.sqlite3").is_file()
            assert harness.context_runtime.store_inventory(fabric_root)["events"] == 0
            captured = harness.context_runtime.capture_hook_event(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": fixture_session,
                    "source": "startup",
                    "cwd": str(working_dir),
                },
                root=fabric_root,
                environ=environ,
            )
            assert captured is not None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def initialize(self, *, timeout):
            protocol_events.append("initialize")
            (source_b / "auth.json").write_bytes(b"fixture refreshed opaque account state\n")

        def request(self, method, params, *, timeout):
            protocol_events.append(f"request:{method}")
            self.sent_methods.append(method)
            if method == "hooks/list":
                hooks = [
                    {
                        "source": "user",
                        "sourcePath": str(source_b / "hooks.json"),
                        "eventName": event_name,
                        "trustStatus": "trusted",
                    }
                    for event_name in (
                        "sessionStart",
                        "userPromptSubmit",
                        "stop",
                        "preCompact",
                        "postCompact",
                        "sessionEnd",
                    )
                ]
                return {"data": [{"hooks": hooks}]}
            if method == "thread/start":
                return {"thread": {"id": fixture_session}}
            if method == "thread/name/set":
                return {}
            if method == "turn/start":
                return {"turn": {"id": "turn-fixture", "status": "inProgress"}}
            raise AssertionError(f"unexpected request: {method}")

        def wait_notification(self, method, *, timeout, predicate=None):
            protocol_events.append(f"wait:{method}")
            if method == "thread/name/updated":
                return {
                    "method": method,
                    "params": {
                        "threadId": fixture_session,
                        "threadName": "fixture-name",
                    },
                }
            if method == "turn/completed":
                return {
                    "method": method,
                    "params": {
                        "threadId": fixture_session,
                        "turn": {"id": "turn-fixture", "status": "completed"},
                    },
                }
            if method == "hook/completed":
                raise harness.LiveProtocolError("fixture startup hook timeout")
            raise AssertionError(f"unexpected notification: {method}")

    monkeypatch.setattr(harness, "_AppServerClient", BrokenProtocolClient)
    operation_root = tmp_path / "operation"
    output = tmp_path / "receipt.json"
    exit_code = harness.main(
        [
            "--mode",
            "live",
            "--operation-root",
            str(operation_root),
            "--output",
            str(output),
            "--codex-path",
            str(codex_exe),
            "--s-codex-home",
            str(source_s),
            "--b-codex-home",
            str(source_b),
            "--working-dir",
            str(working_dir),
            "--hook-sink",
            str(sink_contract),
        ]
    )

    receipt = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(receipt)
    assert exit_code == 1
    assert receipt["claim_class"] == "context_live_observed"
    assert receipt["status"] == "failed"
    assert receipt["auth_content_read"] is False
    assert receipt["source_credentials_copied"] is False
    assert receipt["source_credentials_symlinked"] is False
    assert receipt["expected_named_test_rollouts"] == 3
    assert receipt["exact_named_test_rollouts_written"] == 0
    evidence = receipt["cases"][0]["evidence"]
    assert evidence["auth_mode"] == "existing_b_home"
    assert evidence["protocol_step"] == "startup_hook"
    assert evidence["protocol_trace"] == [
        "fabric_initialize",
        "hooks_trust",
        "thread_start",
        "startup_turn",
        "startup_hook",
    ]
    assert evidence["isolated_context_initial_inventory"]["events"] == 0
    assert evidence["b_account_configuration_unchanged"] is True
    assert evidence["b_account_protection_before"] == protected_before
    assert evidence["b_account_protection_after"] == protected_before
    assert observed_child_env["CODEX_HOME"] == str(source_b)
    assert observed_child_env["CODEX_CONTEXT_FABRIC_ROOT"] == str(
        operation_root / "isolated-context-fabric"
    )
    assert "OPENAI_API_KEY" not in observed_child_env
    assert "CODEX_ACCESS_TOKEN" not in observed_child_env
    assert "FAKE_AMBIENT_SECRET" not in observed_child_env
    assert set(observed_child_env).issubset(
        set(harness._WINDOWS_CHILD_ENV_NAMES) | {"CODEX_HOME", "CODEX_CONTEXT_FABRIC_ROOT"}
    )
    assert harness._account_protection_receipt(source_b) == protected_before
    assert protected_before["auth"] == {"present": True, "content_read": False}
    assert all(path.name.casefold() != "auth.json" for path in hashed_paths)
    assert not (operation_root / "isolated-codex-home").exists()
    assert not (operation_root / "hook_sink_wrapper.py").exists()
    assert not (operation_root / "hook-sink.jsonl").exists()
    assert not (operation_root / "auth.json").exists()
    fabric_root = operation_root / "isolated-context-fabric"
    empty_fabric_root = operation_root / "empty-control-context-fabric"
    assert (fabric_root / "context_fabric.sqlite3").is_file()
    assert (empty_fabric_root / "context_fabric.sqlite3").is_file()
    assert harness.context_runtime.store_inventory(fabric_root)["events"] == 1
    assert harness.context_runtime.store_inventory(empty_fabric_root)["events"] == 0
    assert harness._fabric_session_evidence(fabric_root, fixture_session)["event_count"] == 1
    assert "sk-fake-must-not-reach-existing-home-child" not in serialized
    assert "fake-access-token-must-not-reach-child" not in serialized
    assert "fake-ambient-must-not-reach-child" not in serialized
    assert protocol_events == [
        "initialize",
        "request:hooks/list",
        "request:thread/start",
        "request:thread/name/set",
        "wait:thread/name/updated",
        "request:turn/start",
        "wait:turn/completed",
        "wait:hook/completed",
    ]


def test_fabric_session_evidence_reads_only_bounded_metadata(tmp_path: Path) -> None:
    harness = _load_harness()
    fabric_root = tmp_path / "fabric"
    fabric_root.mkdir()
    session_id = "019ff75c-703c-7972-96cd-b0d257b13baa"
    connection = harness.sqlite3.connect(fabric_root / "context_fabric.sqlite3")
    connection.execute(
        "CREATE TABLE events("
        "seq INTEGER PRIMARY KEY,carrier_id TEXT,session_id TEXT,"
        "event_kind TEXT,metadata_json TEXT)"
    )
    connection.executemany(
        "INSERT INTO events(seq,carrier_id,session_id,event_kind,metadata_json) VALUES(?,?,?,?,?)",
        [
            (1, "s-account-b", session_id, "session_start", '{"source":"startup"}'),
            (2, "s-account-b", session_id, "user_message", "{}"),
            (3, "s-account-b", session_id, "session_start", '{"source":"compact"}'),
            (4, "s-account-b", session_id, "session_start", '{"source":"resume"}'),
        ],
    )
    connection.commit()
    connection.close()

    evidence = harness._fabric_session_evidence(fabric_root, session_id)

    assert evidence == {
        "event_count": 4,
        "event_kinds": ["session_start", "user_message", "session_start", "session_start"],
        "session_start_sources": ["startup", "compact", "resume"],
        "carrier_ids": ["s-account-b"],
        "all_rows_match_session": True,
        "store_distinct_session_count": 1,
        "store_contains_only_requested_session": True,
    }


def test_native_0147_discovers_and_trusts_operation_scoped_hooks(tmp_path: Path) -> None:
    harness = _load_harness()
    codex_exe = Path(
        r"D:\XINAO_RESEARCH_RUNTIME\tools\npm-global\node_modules\@openai\codex"
        r"\node_modules\@openai\codex-win32-x64\vendor"
        r"\x86_64-pc-windows-msvc\bin\codex.exe"
    )
    if not codex_exe.is_file():
        pytest.skip("installed native Codex binary is unavailable")
    source_home = Path(r"C:\Users\xx363\.codex")
    if not source_home.is_dir():
        pytest.skip("S Codex home is unavailable")
    live_home = tmp_path / "isolated-home"
    live_home.mkdir()
    wrapper = tmp_path / "hook_sink_wrapper.py"
    hooks_path = live_home / "hooks.json"
    config_path = live_home / "config.toml"
    harness._write_live_hook_wrapper(
        wrapper,
        log_path=tmp_path / "hook-sink.jsonl",
        adapter_path=REPO_ROOT / "scripts" / "codex_situation_context_hook.py",
        source_codex_home=source_home,
        fabric_root=tmp_path / "fabric",
        working_dir=REPO_ROOT,
    )
    harness._write_live_hooks(hooks_path, wrapper=wrapper)
    harness._write_live_config(config_path, [])
    env = harness._minimal_windows_environment(os.environ)
    env["CODEX_HOME"] = str(live_home)
    command = [str(codex_exe), "app-server", "--stdio"]

    with harness._AppServerClient(command, cwd=REPO_ROOT, environ=env) as discovery:
        discovery.initialize(timeout=10)
        result = discovery.request("hooks/list", {"cwds": [str(REPO_ROOT)]}, timeout=10)
        hooks = harness._owned_hooks(result, hooks_path)
    assert len(hooks) == 6
    assert {hook["trustStatus"] for hook in hooks} == {"untrusted"}

    harness._write_live_config(config_path, hooks)
    with harness._AppServerClient(command, cwd=REPO_ROOT, environ=env) as trusted_client:
        trusted_client.initialize(timeout=10)
        result = trusted_client.request("hooks/list", {"cwds": [str(REPO_ROOT)]}, timeout=10)
        trusted = harness._owned_hooks(result, hooks_path)
    assert len(trusted) == 6
    assert {hook["trustStatus"] for hook in trusted} == {"trusted"}


def test_cli_writes_receipt_and_uses_documented_exit_codes(tmp_path: Path) -> None:
    contract_root = tmp_path / "contract-operation"
    contract_output = tmp_path / "receipts" / "contract.json"
    contract = subprocess.run(
        [
            sys.executable,
            str(HARNESS_PATH),
            "--mode",
            "contract",
            "--operation-root",
            str(contract_root),
            "--output",
            str(contract_output),
            "--case-pattern",
            r"^CTX_AC_CLEANROOM_DENIED$",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert contract.returncode == 0, contract.stderr
    contract_receipt = json.loads(contract_output.read_text(encoding="utf-8"))
    assert contract_receipt["status"] == "passed"
    assert contract_receipt["summary"]["selected"] == 1
    assert json.loads(contract.stdout)["schema_version"] == contract_receipt["schema_version"]

    live_output = tmp_path / "receipts" / "live.json"
    live = subprocess.run(
        [
            sys.executable,
            str(HARNESS_PATH),
            "--mode",
            "live",
            "--operation-root",
            str(tmp_path / "live-operation"),
            "--output",
            str(live_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert live.returncode == 3, live.stderr
    live_receipt = json.loads(live_output.read_text(encoding="utf-8"))
    assert live_receipt["status"] == "ineligible"
    assert live_receipt["runtime_claim_allowed"] is False


def test_receipt_schema_accepts_contract_and_live_receipts(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    harness = _load_harness()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    contract = harness.run_contract(
        tmp_path / "contract-operation",
        r"^CTX_CORRUPT_CONTEXT_FAILS_OPEN_TO_L0$",
    )
    live = harness.run_live(
        tmp_path / "live-operation",
        codex_path=None,
        s_codex_home=None,
        b_codex_home=None,
        working_dir=None,
        hook_sink=None,
    )
    jsonschema.validate(contract, schema)
    jsonschema.validate(live, schema)
    observed_live = {
        "schema_version": "s.context_runtime_trajectory_receipt.v1",
        "mode": "live",
        "evidence_level": "live_app_server_and_hook_sink",
        "claim_class": "context_live_observed",
        "status": "passed",
        "runtime_claim_allowed": True,
        "operation_root": str(tmp_path / "observed-live"),
        "cases": [
            {
                "case_id": "CTX_LIVE_START_COMPACT_RESUME",
                "status": "passed",
                "evidence_level": "live_app_server_and_hook_sink",
                "runtime_claim_allowed": True,
                "assertions": {"native_trace": True},
                "failed_assertions": [],
                "evidence": {"claim_scope": "fixture"},
            }
        ],
        "summary": {"selected": 1, "passed": 1, "failed": 0, "ineligible": 0},
        "claim_boundary": {"proves": ["fixture"], "does_not_prove": []},
    }
    jsonschema.validate(observed_live, schema)


@pytest.mark.parametrize(
    ("exit_code", "status", "claim_class", "runtime_allowed", "summary"),
    [
        (0, "passed", "context_live_observed", True, (1, 1, 0, 0)),
        (1, "failed", "context_live_observed", False, (1, 0, 1, 0)),
        (3, "ineligible", "context_live_ineligible", False, (0, 0, 0, 1)),
    ],
)
def test_shared_runner_accepts_only_typed_live_receipt_outcomes(
    tmp_path: Path,
    exit_code: int,
    status: str,
    claim_class: str,
    runtime_allowed: bool,
    summary: tuple[int, int, int, int],
) -> None:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pinned = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")
        if not pinned.is_file():
            pytest.skip("PowerShell 7 is unavailable")
        powershell = str(pinned)
    source = RUNNER_PATH.read_text(encoding="utf-8-sig")
    match = re.search(
        r"(?ms)^function Get-ContextRuntimeTrajectorySummary \{.*?(?=^function Invoke-PromptfooSuite \{)",
        source,
    )
    assert match is not None
    selected, passed, failed, ineligible = summary
    cases = (
        [] if selected == 0 else [{"case_id": "CTX_LIVE_START_COMPACT_RESUME", "status": status}]
    )
    receipt = {
        "schema_version": "s.context_runtime_trajectory_receipt.v1",
        "mode": "live",
        "evidence_level": "live_app_server_and_hook_sink",
        "claim_class": claim_class,
        "status": status,
        "runtime_claim_allowed": runtime_allowed,
        "operation_root": str(tmp_path / "operation"),
        "cases": cases,
        "summary": {
            "selected": selected,
            "passed": passed,
            "failed": failed,
            "ineligible": ineligible,
        },
        "claim_boundary": {"proves": [], "does_not_prove": []},
    }
    receipt_path = tmp_path / f"receipt-{exit_code}.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    quoted_receipt = str(receipt_path).replace("'", "''")
    probe = tmp_path / f"runner-probe-{exit_code}.ps1"
    probe.write_text(
        match.group(0)
        + "\n$result = Get-ContextRuntimeTrajectorySummary "
        + f"-ReceiptPath '{quoted_receipt}' -ExpectedMode live -ExitCode {exit_code}\n"
        + "$result | ConvertTo-Json -Depth 8 -Compress\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(probe)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.lstrip("\ufeff").strip())
    assert result["claim_class"] == claim_class
    assert result["status"] == status
    assert result["runtime_pass_claim_eligible"] is (exit_code == 0)


def test_shared_runner_generates_explicit_nonsecret_live_auth_contract() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8-sig")
    assert re.search(
        r"\[ValidateSet\('environment_isolated',\s*'existing_b_home'\)\]\s*"
        r"\[string\]\$ContextLiveAuthMode\s*=\s*'environment_isolated'",
        source,
    )
    assert (
        "if ($Profile -ne 'context' -and "
        "$PSBoundParameters.ContainsKey('ContextLiveAuthMode'))" in source
    )
    assert (
        "if ($ContextEvidenceMode -ne 'live' -and "
        "$PSBoundParameters.ContainsKey('ContextLiveAuthMode'))" in source
    )
    block_match = re.search(
        r"(?ms)\$effectiveContextHookSink\s*=\s*\$ContextHookSink\s*"
        r"if \(\[string\]::IsNullOrWhiteSpace\(\$effectiveContextHookSink\)\) \{"
        r"(?P<body>.*?)^\s*\}\s*"
        r"\$contextArguments\s*\+=\s*@\((?P<arguments>.*?)^\s*\)",
        source,
    )
    assert block_match is not None
    body = block_match.group("body")
    arguments = block_match.group("arguments")
    assert "Join-Path $outputRoot" in body
    assert "context-live-hook-sink-contract.json" in body
    assert "schema_version = 's.context_runtime_live_hook_sink.v1'" in body
    assert "auth_mode = $ContextLiveAuthMode" in body
    assert "auth_env" not in body
    assert "Set-Content" in body
    assert "-LiteralPath $effectiveContextHookSink" in body
    assert "'--hook-sink', $effectiveContextHookSink" in arguments
