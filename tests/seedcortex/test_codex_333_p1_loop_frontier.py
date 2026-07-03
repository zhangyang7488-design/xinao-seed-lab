import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_333_p1_loop_frontier.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_333_p1_loop_frontier.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_333_p1_loop_frontier", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeChild:
    calls: list[str] = []

    @classmethod
    def build(
        cls,
        *,
        runtime_root: str | Path,
        repo_root: str | Path,
        task_id: str,
        intent_package: str | Path,
        wave_id: str,
        codex_subagents: list[str],
        write: bool,
    ) -> dict[str, Any]:
        cls.calls.append(wave_id)
        runtime = Path(runtime_root)
        draft_path = runtime / "drafts" / "deepseek" / f"{wave_id}-draft" / "draft.md"
        if write:
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(f"# draft for {wave_id}\n\nfrontier delta\n", encoding="utf-8")
        return {
            "schema_version": "xinao.codex_s.max_capability_think_execute.v1",
            "task_id": task_id,
            "wave_id": wave_id,
            "WORKER_ASSIGNMENT": {
                "execute_lanes": [
                    {
                        "lane_id": "codex-max-execute-dp-draft-01",
                        "phase": "execute",
                        "status": "succeeded",
                        "artifact_refs": [str(draft_path)],
                        "evidence_refs": {
                            "requested_mode": "draft",
                            "executed_mode": "draft",
                        },
                    },
                    {
                        "lane_id": "codex-max-execute-dp-eval-01",
                        "phase": "execute",
                        "status": "succeeded",
                        "artifact_refs": [str(runtime / "state" / f"{wave_id}-eval.json")],
                        "evidence_refs": {
                            "requested_mode": "eval",
                            "executed_mode": "eval",
                        },
                    },
                ]
            },
            "width_decision": {"observed_provider_width": 1},
            "summary": {
                "dp_execute_draft_succeeded_count": 1,
                "dp_execute_eval_succeeded_count": 1,
                "execute_search_invocation_count": 0,
                "provider_probe_invocation_count": 0,
                "execute_modes_observed": ["draft", "eval"],
            },
            "fan_in": {
                "lane_results": {
                    "source_kind": "worker_dispatch_ledger_poll",
                    "accepted_edge_count": 2,
                }
            },
            "artifact_acceptance": {"accepted_artifact_count": 1},
            "continuity_envelope": {"should_continue_loop": True},
            "output_paths": {
                "fan_in_acceptance_latest": str(runtime / "state" / f"{wave_id}-fan-in.json"),
                "lane_results_latest": str(runtime / "state" / f"{wave_id}-lane-results.json"),
            },
            "validation": {"passed": True},
        }


def test_333_p1_driver_runs_two_waves_hooks_fanin_and_pushes_frontier(tmp_path: Path) -> None:
    module = _load_module()
    _FakeChild.calls = []
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    intent_package = tmp_path / "grok_333_continue_root_intent_loop_20260703.json"
    intent_package.write_text("{}", encoding="utf-8")

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id="xinao_seed_cortex_phase0_20260701",
        intent_package=intent_package,
        base_wave_id="p1-test",
        wave_count=2,
        codex_subagents=["agent-1:p1:succeeded"],
        child_module=_FakeChild,
        write=True,
    )

    assert _FakeChild.calls == ["p1-test-wave-01", "p1-test-wave-02"]
    assert payload["schema_version"] == "xinao.codex_s.333_p1_loop_frontier.v1"
    assert payload["validation"]["passed"] is True
    assert payload["adoption_state"] == "runtime_enforced"
    assert payload["runtime_enforced"] is True
    assert payload["trigger_installed"] is True
    assert payload["runtime_enforced_scope"] == "codex_333_p1_loop_frontier_task_scoped_two_wave_driver"
    assert payload["p0_reopened"] is False
    assert payload["summary"]["while_wave_count"] == 2
    assert payload["summary"]["draft_eval_group_count_total"] == 2
    assert payload["summary"]["draft_succeeded_count_total"] == 2
    assert payload["summary"]["eval_succeeded_count_total"] == 2
    assert payload["summary"]["execute_search_invocation_count_total"] == 0
    assert payload["summary"]["provider_probe_invocation_count_total"] == 0
    assert payload["p2_episode_fan_in_hook"]["runtime_enforced"] is True
    assert payload["p2_episode_fan_in_hook"]["validation"]["passed"] is True
    assert payload["p3_frontier"]["validation"]["passed"] is True
    assert payload["p3_frontier"]["merged_draft_count"] == 2
    assert payload["p3_frontier"]["codex_merge_review"]["accepted_for_next_frontier_only"] is True
    assert payload["p3_frontier"]["codex_merge_review"]["fact_promotion_allowed"] is False
    assert payload["p3_frontier"]["strategy_update"]["promoted"] is False
    assert payload["p3_frontier"]["strategy_update"]["fact_promotion_allowed"] is False
    assert len(payload["p3_frontier"]["next_frontier"]["frontier_nodes"]) >= 2

    latest = Path(payload["output_paths"]["runtime_latest"])
    readback = Path(payload["output_paths"]["runtime_readback_zh"])
    repo_frontier = Path(payload["output_paths"]["repo_frontier_readback"])
    assert latest.is_file()
    assert readback.is_file()
    assert repo_frontier.is_file()
    written = _read_json(latest)
    assert written["validation"]["checks"]["execute_search_zero"] is True
    assert "现在能 invoke 什么" in readback.read_text(encoding="utf-8")
    assert "P3 frontier diff" in repo_frontier.read_text(encoding="utf-8")
    assert "StrategyUpdate: promoted=False" in repo_frontier.read_text(encoding="utf-8")


def _seed_repo_refs(repo: Path) -> None:
    for relative in (
        "services/agent_runtime/root_intent_loop_driver.py",
        "services/agent_runtime/codex_333_p1_loop_frontier.py",
        "services/agent_runtime/codex_max_capability_think_execute.py",
        "tests/seedcortex/test_root_intent_loop_driver.py",
        "tests/seedcortex/test_codex_333_p1_loop_frontier.py",
        "tests/seedcortex/test_codex_max_capability_think_execute.py",
        "contracts/schemas/codex_s_root_intent_loop_driver.v1.json",
        "contracts/schemas/codex_333_p1_loop_frontier.v1.json",
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test ref\n", encoding="utf-8")


def test_333_p1_driver_default_main_chain_appends_wave04_and_distinct_frontier(tmp_path: Path) -> None:
    module = _load_module()
    _FakeChild.calls = []
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_repo_refs(repo)
    intent_package = tmp_path / "grok_333_continue_root_intent_loop_20260703.json"
    intent_package.write_text("{}", encoding="utf-8")
    trigger_latest = runtime / "state" / "root_intent_loop_driver" / "default_trigger_enforcement_latest.json"
    trigger_latest.parent.mkdir(parents=True, exist_ok=True)
    trigger_latest.write_text(
        json.dumps({"validation": {"passed": True}}, ensure_ascii=False),
        encoding="utf-8",
    )
    durable_latest = runtime / "state" / "durable_parallel_wave_packet" / "latest.json"
    durable_latest.parent.mkdir(parents=True, exist_ok=True)
    durable_latest.write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.durable_parallel_wave_packet.v1",
                "validation": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    (runtime / "capabilities" / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port").mkdir(
        parents=True,
        exist_ok=True,
    )
    (
        runtime
        / "capabilities"
        / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
        / "manifest.json"
    ).write_text("{}", encoding="utf-8")
    waves_dir = runtime / "state" / "codex_333_p1_loop_frontier" / "waves"
    waves_dir.mkdir(parents=True, exist_ok=True)
    old_wave_refs: list[dict[str, Any]] = []
    for index in range(1, 4):
        wave_id = f"p1-default-main-chain-test-wave-{index:02d}"
        wave_payload = _FakeChild.build(
            runtime_root=runtime,
            repo_root=repo,
            task_id="xinao_seed_cortex_phase0_20260701",
            intent_package=intent_package,
            wave_id=wave_id,
            codex_subagents=["agent-1:p1:succeeded"],
            write=True,
        )
        wave_path = waves_dir / f"{wave_id}.json"
        wave_path.write_text(json.dumps(wave_payload, ensure_ascii=False), encoding="utf-8")
        old_wave_refs.append(
            {
                "wave_id": wave_id,
                "payload_ref": str(wave_path),
                "validation_passed": True,
                "should_continue_loop": True,
                "execute_search_invocation_count": 0,
                "execute_modes_observed": ["draft", "eval"],
            }
        )
    (runtime / "state" / "codex_333_p1_loop_frontier" / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": "xinao.codex_s.333_p1_loop_frontier.v1",
                "default_main_chain": True,
                "base_wave_id": "p1-default-main-chain-test",
                "while_wave_ids": [ref["wave_id"] for ref in old_wave_refs],
                "while_waves": old_wave_refs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _FakeChild.calls = []

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        task_id="xinao_seed_cortex_phase0_20260701",
        intent_package=intent_package,
        base_wave_id="p1-default-main-chain-test",
        wave_count=2,
        codex_subagents=["agent-1:p1:succeeded"],
        child_module=_FakeChild,
        default_main_chain=True,
        root_driver_wave_id="root-driver-test-wave",
        append_to_existing=True,
        write=True,
    )

    assert _FakeChild.calls == ["p1-default-main-chain-test-wave-04"]
    assert payload["validation"]["passed"] is True
    assert payload["runtime_enforced_scope"] == "root_intent_loop_driver_p1_default_main_chain_auto_while"
    assert payload["default_main_chain"] is True
    assert payload["summary"]["while_wave_count"] == 4
    assert payload["summary"]["wave04_plus_present"] is True
    assert payload["summary"]["latest_auto_wave_index"] == 4
    assert payload["summary"]["new_wave_ids_this_tick"] == ["p1-default-main-chain-test-wave-04"]
    assert payload["default_main_chain_invocation"]["wave04_plus_present"] is True
    assert payload["default_main_chain_invocation"]["trigger_durable_same_binding_enforced"] is True
    assert payload["p1_loop_frontier_refs"]["validation"]["checks"]["wave04_plus_present"] is True
    assert payload["p1_loop_frontier_refs"]["validation"]["checks"]["new_wave_this_tick_present"] is True
    assert payload["p1_loop_frontier_refs"]["validation"]["checks"]["root_trigger_enforcement_ref_bound"] is True
    assert payload["p1_loop_frontier_refs"]["validation"]["checks"]["durable_runtime_enforced"] is True
    assert payload["p1_loop_frontier_refs"]["validation"]["checks"]["episode_default_hook_invoked"] is True
    assert payload["p3_frontier"]["frontier_id"] != "p3-333-total-draft-frontier-20260703"
    assert "p1-default-main-chain-test" in payload["p3_frontier"]["frontier_id"]
    assert Path(payload["output_paths"]["root_driver_p1_default_main_chain_latest"]).is_file()
    assert Path(payload["output_paths"]["root_driver_p1_continuation_latest"]).is_file()
    root_readback = Path(payload["output_paths"]["root_driver_p1_default_main_chain_readback_zh"])
    assert root_readback.is_file()
    assert "现在能 invoke" in root_readback.read_text(encoding="utf-8")


def test_333_p1_schema_locks_no_completion_and_execute_search_zero() -> None:
    schema = _read_json(SCHEMA_PATH)

    assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.333_p1_loop_frontier.v1"
    assert schema["properties"]["sentinel"]["const"] == (
        "SENTINEL:XINAO_CODEX_S_333_P1_LOOP_FRONTIER_RUNTIME_INVOKED"
    )
    assert schema["properties"]["completion_claim_allowed"]["const"] is False
    assert set(schema["properties"]["adoption_state"]["enum"]) == {
        "runtime_enforced",
        "candidate_registered",
    }
    assert set(schema["properties"]["runtime_enforced_scope"]["enum"]) == {
        "codex_333_p1_loop_frontier_task_scoped_two_wave_driver",
        "root_intent_loop_driver_p1_default_main_chain_wave03",
        "root_intent_loop_driver_p1_default_main_chain_auto_while",
    }
    assert schema["properties"]["phase1_data_chain_allowed"]["const"] is False
    assert schema["properties"]["positive_ev_claim_allowed"]["const"] is False
    assert schema["properties"]["p0_reopened"]["const"] is False
    checks = schema["properties"]["validation"]["properties"]["checks"]["required"]
    assert "two_or_more_while_waves" in checks
    assert "p1_width_multi_group_draft_eval" in checks
    assert "execute_search_zero" in checks
    assert "p2_fan_in_hook_runtime_enforced" in checks
    assert "p3_frontier_pushed" in checks
    assert "p3_distinct_frontier" in checks
    assert "default_main_chain_p1_logic_invoked" in checks
    assert "wave03_floor_present_deprecated_compat" in checks
    assert "four_or_more_default_main_chain_waves" in checks
    assert "wave04_plus_present" in checks
    assert "new_wave_this_tick_present" in checks
    assert "fixed_three_wave_stop_absent" in checks
    assert "episode_default_hook_invoked" in checks
    assert "trigger_durable_same_binding_enforced" in checks
    p3 = schema["properties"]["p3_frontier"]["properties"]
    assert "codex_merge_review" in p3
    assert "strategy_update" in p3
    assert "next_frontier" in p3
    summary = schema["properties"]["summary"]["properties"]
    assert summary["execute_search_invocation_count_total"]["const"] == 0
    assert summary["provider_probe_invocation_count_total"]["const"] == 0
