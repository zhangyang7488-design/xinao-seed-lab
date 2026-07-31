"""Owner live path: fail-closed live research gate on existing owner-vertical.

No second commissioning platform. Product entry remains:

  xinao_role_fitness_acceptance.py owner-vertical --require-live-research
  + xinao.py research-episode (host)
  + xinao.shadow_lifecycle (freeze/settle/feedback)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_DISCOVERY = _REPO / "xinao_discovery" / "src"
if _DISCOVERY.is_dir() and str(_DISCOVERY) not in sys.path:
    sys.path.insert(0, str(_DISCOVERY))

_RF_PATH = _REPO / "skills" / "xinao" / "scripts" / "xinao_role_fitness_acceptance.py"
_COMMISSION_PATH = _REPO / "skills" / "xinao" / "scripts" / "owner_live_commissioning.py"


def _load_rf():
    spec = importlib.util.spec_from_file_location(
        "xinao_role_fitness_acceptance_under_test_live", _RF_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rf = _load_rf()


def test_owner_live_commissioning_second_platform_absent() -> None:
    """Wave platform script must not ship; use existing two-phase owner-vertical."""

    assert not _COMMISSION_PATH.is_file()
    cmds = rf.two_owner_commands()
    assert "owner-vertical" in cmds["pre_outcome"]
    assert "--require-live-research" in cmds["pre_outcome"]
    assert "owner_live_commissioning" not in cmds["pre_outcome"]
    assert "owner_live_commissioning" not in cmds["post_outcome"]
    assert "live_runner" not in cmds["pre_outcome"]


def test_require_live_research_pre_outcome_fails_without_evidence(tmp_path: Path) -> None:
    pre = rf.run_owner_invoked_vertical_pre_outcome(
        work_root=tmp_path / "live-pre",
        require_live_research=True,
    )
    assert pre["status"] == "FAIL"
    assert pre["completion_claim_allowed"] is False
    assert pre["parent_completion"] is False
    assert pre["pre_outcome_freeze_ok"] is False
    assert pre.get("awaiting_external_outcome") is False
    assert any("live research" in f.lower() for f in pre["failures"])
    # Must not create portfolio freeze without live research.
    assert not (tmp_path / "live-pre" / "portfolio").exists()


def test_require_live_research_rejects_fixture_scientist(tmp_path: Path) -> None:
    fixture = rf._minimal_scientist_evidence()
    pre = rf.run_owner_invoked_vertical_pre_outcome(
        work_root=tmp_path / "fixture-live",
        scientist_evidence=fixture,
        require_live_research=True,
    )
    assert pre["status"] == "FAIL"
    assert pre["completion_claim_allowed"] is False
    assert pre["pre_outcome_freeze_ok"] is False
    assert any("fixture" in f.lower() or "live research" in f.lower() for f in pre["failures"])


def test_full_synthetic_forbidden_with_live_research_flag(tmp_path: Path) -> None:
    with pytest.raises(rf.RoleFitnessAcceptanceError, match="full_synthetic"):
        rf.run_owner_invoked_vertical(
            work_root=tmp_path / "fs",
            mode="full_synthetic",
            require_live_research=True,
        )


def test_is_fixture_scientist_evidence_detects_demo() -> None:
    assert rf.is_fixture_scientist_evidence(None) is True
    assert rf.is_fixture_scientist_evidence(rf._minimal_scientist_evidence()) is True


def test_cli_require_live_research_flag(tmp_path: Path) -> None:
    code = rf.main(
        [
            "owner-vertical",
            "--work-root",
            str(tmp_path / "cli-live"),
            "--mode",
            "pre_outcome",
            "--require-live-research",
        ]
    )
    assert code == 1  # fail-closed without live evidence
    receipt_path = tmp_path / "cli-live" / "pre_outcome_receipt.json"
    assert receipt_path.is_file()
    body = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert body["status"] == "FAIL"
    assert body["completion_claim_allowed"] is False
    assert body["pre_outcome_freeze_ok"] is False


def test_harness_without_live_flag_still_runs_fixture_path(tmp_path: Path) -> None:
    """Default harness path may use fixtures; must not claim live role fitness."""

    pre = rf.run_owner_invoked_vertical_pre_outcome(
        work_root=tmp_path / "harness",
        require_live_research=False,
    )
    # May PASS structure with fixture scientist, but never live fitness greens.
    assert pre["completion_claim_allowed"] is False
    assert pre["genuine_role_fitness"] is False
    assert pre["parent_completion"] is False
