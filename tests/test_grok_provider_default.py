from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import set_grok_provider_default as cutover
from services.agent_runtime.routing_policy_reader import draft_model, pro_review_model


def _policy() -> dict[str, object]:
    return {
        "policy_version": "xinao.routing-policy.v3-grok-only",
        "routes": [
            {
                "route_role": "default_background_worker",
                "target": "grok",
                "provider_id": "grok_acpx_headless",
                "preferred_model": "grok-4.5",
            }
        ],
        "pro_review_after_draft": "grok-4.5",
    }


def test_cutover_promotes_composer_and_restores_exact_backup(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    policy_path = runtime / "agent_runtime" / "routing_policy.json"
    policy_path.parent.mkdir(parents=True)
    original_raw = (json.dumps(_policy(), indent=2) + "\n").encode()
    policy_path.write_bytes(original_raw)
    evidence = runtime / "state" / "promotions"

    promote = cutover.plan_set_model(
        policy_path,
        model=cutover.DEFAULT_MODEL,
        expected_current_model=cutover.ROLLBACK_MODEL,
    )
    promoted = cutover.apply_plan(promote, evidence_root=evidence)
    assert promoted["verified"] is True
    assert draft_model(runtime_root=runtime) == cutover.DEFAULT_MODEL
    assert pro_review_model(runtime_root=runtime) == cutover.PRO_REVIEW_MODEL
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["grok_provider_model_policy"] == {
        "schema_version": cutover.MODEL_POLICY_ID,
        "default_worker_model": cutover.DEFAULT_MODEL,
        "escalation_model": cutover.PRO_REVIEW_MODEL,
        "formal_writer": "codex",
        "deterministic_first": True,
        "worker_default_capability": "read_only",
        "write_requires_isolated_worktree": True,
        "account_quota_scope": "single_grok_account",
    }

    restore = cutover.plan_restore(
        policy_path,
        backup=Path(promoted["rollback_path"]),
        expected_current_model=cutover.DEFAULT_MODEL,
    )
    restored = cutover.apply_plan(restore, evidence_root=evidence)
    assert restored["verified"] is True
    assert policy_path.read_bytes() == original_raw
    assert draft_model(runtime_root=runtime) == cutover.ROLLBACK_MODEL


def test_cutover_fails_closed_on_drift_or_unknown_model(tmp_path: Path) -> None:
    policy_path = tmp_path / "routing_policy.json"
    policy_path.write_text(json.dumps(_policy()), encoding="utf-8")
    with pytest.raises(ValueError, match="expected grok-composer"):
        cutover.plan_set_model(
            policy_path,
            model=cutover.DEFAULT_MODEL,
            expected_current_model=cutover.DEFAULT_MODEL,
        )
    with pytest.raises(ValueError, match="unsupported Grok provider model"):
        cutover.build_policy(_policy(), model="grok-unknown")


def test_apply_refuses_policy_drift_after_planning(tmp_path: Path) -> None:
    policy_path = tmp_path / "routing_policy.json"
    policy_path.write_text(json.dumps(_policy()), encoding="utf-8")
    plan = cutover.plan_set_model(policy_path, model=cutover.DEFAULT_MODEL)

    drifted = _policy()
    drifted["unrelated_concurrent_edit"] = True
    drifted_raw = json.dumps(drifted).encode()
    policy_path.write_bytes(drifted_raw)

    with pytest.raises(RuntimeError, match="changed after planning"):
        cutover.apply_plan(plan, evidence_root=tmp_path / "evidence")
    assert policy_path.read_bytes() == drifted_raw
    assert not (tmp_path / "evidence").exists()
