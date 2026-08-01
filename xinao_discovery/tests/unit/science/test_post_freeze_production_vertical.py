"""Owner integration: one frozen production object reaches next-episode input.

The source transport is a deterministic fixture, so this proves the production
consumer chain and its bindings, not a live prospective campaign or model
learning.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from xinao.science.portfolio import compile_settled_portfolio_feedback_state
from xinao.science.portfolio_settle_all_from_reveal import (
    apply_portfolio_settle_all_from_reveal,
)
from xinao.science.research_feedback_material import load_episode_feedback_inventory
from xinao.science.research_feedback_pack import emit_research_feedback_pack
from xinao.shadow_lifecycle.store import period_directory


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_source_bound_freeze_reaches_explicit_next_episode_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling = Path(__file__).resolve().parent / "test_settle_from_reveal.py"
    settle_fixture = _load_module("post_freeze_settle_fixture", sibling)
    capture = settle_fixture._capture_auth(tmp_path)
    portfolio, authority, frozen = settle_fixture._action_freeze(
        tmp_path,
        capture,
        selected_number=12,
    )
    frozen_path = period_directory(portfolio, 1) / "frozen_episode.v1.json"
    frozen_before = frozen_path.read_bytes()
    reveal = settle_fixture._reveal(
        tmp_path,
        capture,
        open_code="01,02,03,04,05,06,12",
    )

    settled = apply_portfolio_settle_all_from_reveal(
        authority_root=authority,
        portfolio_root=portfolio,
        packet_content_hash=capture["packet_content_hash"],
        reveal_content_hash=reveal["reveal_content_hash"],
    )
    assert settled["status"] == "SETTLE_ALL_COMMITTED"
    assert settled["enumerated_due_count"] == 1
    assert settled["settled_count"] == 1
    assert settled["unsettled_due_count"] == 0
    assert settled["source_raw_reparsed"] is True
    assert settled["caller_verified_flag_trusted"] is False
    assert frozen_path.read_bytes() == frozen_before

    state = compile_settled_portfolio_feedback_state(
        portfolio_root=portfolio,
        through_period_index=1,
    )
    assert state["through_period_index"] == 1
    assert state["account_axis"]["cost_accounting_status"] == "UNPROVEN_NOT_RECORDED"
    assert state["account_axis"]["after_cost_profit_claim_allowed"] is False
    assert state["science_axis"]["account_performance_is_scientific_proof"] is False

    emitted = emit_research_feedback_pack(portfolio_root=portfolio, period_index=1)
    assert emitted["portfolio_feedback_state_hash"] == state["content_hash"]
    assert emitted["auto_start_next_research"] is False
    assert not period_directory(portfolio, 2).exists()

    repo_root = Path(__file__).resolve().parents[4]
    runtime = _load_module(
        "post_freeze_feedback_runtime",
        repo_root / "skills" / "xinao" / "scripts" / "xinao_runtime.py",
    )
    monkeypatch.setattr(runtime, "_research_episode_assert_root_allowed", lambda _root: None)
    monkeypatch.setattr(
        runtime,
        "_research_episode_resolve_profile_status",
        lambda _root: runtime.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED,
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_container_identity",
        lambda **_kwargs: {"integration_test_identity": True},
    )

    next_episode = tmp_path / "next-research-episode"
    started = runtime.research_episode_start(
        root=next_episode,
        question="Revise or retain the candidate using the settled evidence.",
        feedback_portfolio_root=portfolio,
        feedback_content_hash=emitted["content_hash"],
    )
    inventory_hash = started["feedback_inventory_hash"]
    inventory = load_episode_feedback_inventory(
        episode_root=next_episode,
        inventory_hash=inventory_hash,
    )
    assert inventory["feedback_content_hash"] == emitted["content_hash"]
    assert inventory["portfolio_feedback_state_hash"] == state["content_hash"]
    assert started["auto_start_next_research"] is False

    observed: dict[str, Any] = {}

    class _PlanHost:
        def attach_run_live(self, **kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            return {"status": "PLANNED", "plan_only": True}

    monkeypatch.setattr(
        runtime,
        "_research_episode_load_dual_host",
        lambda _root: (None, _PlanHost()),
    )
    monkeypatch.setattr(runtime, "_research_episode_namespace_and_release_facts", lambda: {})
    attached = runtime.research_episode_attach_run(
        root=next_episode,
        prompt="Continue the bounded research.",
        expected_head_sha256=started["head_checkpoint_sha256"],
        plan_only=True,
    )
    provider_prompt = observed["prompt"]
    assert inventory_hash in provider_prompt
    assert emitted["pack"]["prior_result_sha256"] in provider_prompt
    assert reveal["outcome"]["result_hash"] in provider_prompt
    assert attached["feedback_inventory_read"] is True
    assert attached["feedback_prompt_bound"] is True
    assert attached["model_learned_claim_allowed"] is False
    assert attached["auto_start_next_research"] is False
    assert attached["next_task_created"] is False
    assert frozen["frozen_episode_hash"] == settled["periods"][0]["frozen_episode_hash"]
