"""Wave97: multipolicy settle-all-from-reveal public consumer + fail-closed negatives."""

from __future__ import annotations

import ast
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xinao.canonical import canonical_sha256
from xinao.cli import build_parser, main
from xinao.science.portfolio import FrozenDecisionSet
from xinao.science.settle_all_from_reveal_adapter import (
    ADAPTER_MARKER,
    FIXTURE_REVEAL_SCHEMA,
    OBJECT_MODEL,
    SettleAllFromRevealError,
    apply_settle_all_from_reveal,
    assert_no_control_plane_imports,
    build_isolated_reveal_fixture,
    enumerate_expected_tickets,
    load_sealed_freeze_set,
    reject_settle_all_forbidden_kwargs,
)

# Reuse synthetic freeze builders from portfolio unit tests (same package).
from tests.unit.science.test_portfolio import OPEN, frozen_set  # type: ignore

FORMAL_2026209_COPY = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\audit_scratch\wave84\g\formal_2026209_copy"
    r"\frozen_decision_set.v1.json"
)
FORMAL_2026209_HASH = "d57bbaee297da674e01f9f78a54f08b67ecc32f926c0de1d2569380f77279334"
FORMAL_TARGET = "macaujc2/expect/2026209"
FORMAL_OPEN = datetime(2026, 7, 28, 13, 32, 32, tzinfo=UTC)  # 21:32:32+08:00


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _freeze_path(tmp_path: Path, freeze: FrozenDecisionSet | None = None) -> tuple[Path, str]:
    fs = freeze or frozen_set()
    path = tmp_path / "frozen_decision_set.v1.json"
    _write_json(path, fs.model_dump(mode="json"))
    assert fs.content_hash is not None
    return path, fs.content_hash


def _reveal_path(tmp_path: Path, reveal: dict[str, Any], name: str = "reveal.json") -> Path:
    path = tmp_path / name
    _write_json(path, reveal)
    return path


def test_adapter_has_no_control_plane_imports() -> None:
    assert_no_control_plane_imports()


def test_reject_caller_outcome_and_subset_kwargs() -> None:
    with pytest.raises(SettleAllFromRevealError, match="CALLER_OUTCOME_OVERRIDE_FORBIDDEN"):
        reject_settle_all_forbidden_kwargs({"actual_special_number": 7})
    with pytest.raises(
        SettleAllFromRevealError,
        match="CALLER_SETTLE_ALL_OVERRIDE_FORBIDDEN|CALLER_OUTCOME_OVERRIDE_FORBIDDEN",
    ):
        reject_settle_all_forbidden_kwargs({"verified": True})
    with pytest.raises(SettleAllFromRevealError, match="CALLER_SETTLE_ALL_OVERRIDE_FORBIDDEN"):
        reject_settle_all_forbidden_kwargs({"ticket_refs": ["a"]})
    with pytest.raises(SettleAllFromRevealError, match="CALLER_SETTLE_ALL_OVERRIDE_FORBIDDEN"):
        reject_settle_all_forbidden_kwargs({"subset": ["only-one"]})


def test_positive_settle_all_exact_once_and_idempotent_replay(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    freeze = FrozenDecisionSet.model_validate_json(freeze_path.read_text(encoding="utf-8"))
    reveal = build_isolated_reveal_fixture(
        target_ref=freeze.target_ref,
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    rpath = _reveal_path(tmp_path, reveal)
    root = tmp_path / "settlement_root"

    first = apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_path,
        expected_freeze_set_hash=freeze_hash,
        reveal_artifact=rpath,
    )
    assert first["ok"] is True
    assert first["adapter_marker"] == ADAPTER_MARKER
    assert first["object_model"] == OBJECT_MODEL
    assert first["not_single_seat_shadow_portfolio"] is True
    assert first["eligible_frozen_count"] == 4
    assert first["settled_exactly_once_count"] == 4
    assert first["missing_or_duplicate_count"] == 0
    assert first["conservation_ok"] is True
    assert first["action_settled_count"] == 3
    assert first["no_action_settled_count"] == 1
    assert first["scientific_promotion"] is False
    assert first["completion_claim_allowed"] is False
    assert first["fixture_isolated_mechanics"] is True
    assert first["formal_object_settled"] is False
    assert first["settlement_written"] is True
    assert first["idempotent_replay"] is False
    assert (root / "settlement_set.v1.json").is_file()
    assert (root / "action_settlement_bundles.v1.json").is_file()

    second = apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_path,
        expected_freeze_set_hash=freeze_hash,
        reveal_artifact=rpath,
    )
    assert second["ok"] is True
    assert second["idempotent_replay"] is True
    assert second["settlement_written"] is False
    assert second["settlement_set_hash"] == first["settlement_set_hash"]
    # Bundles file must not be rewritten with different bytes (no double-post).
    bundles_bytes = (root / "action_settlement_bundles.v1.json").read_bytes()
    third = apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_path,
        expected_freeze_set_hash=freeze_hash,
        reveal_artifact=rpath,
    )
    assert (root / "action_settlement_bundles.v1.json").read_bytes() == bundles_bytes
    assert third["settlement_set_hash"] == first["settlement_set_hash"]


def test_altered_freeze_hash_fail_closed(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    reveal = build_isolated_reveal_fixture(
        target_ref="draw.synthetic.1",
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    with pytest.raises(SettleAllFromRevealError, match="FREEZE_SET_HASH_MISMATCH"):
        apply_settle_all_from_reveal(
            settlement_root=tmp_path / "s",
            freeze_set_path=freeze_path,
            expected_freeze_set_hash="0" * 64,
            reveal_artifact=_reveal_path(tmp_path, reveal),
        )
    # Tamper file body while keeping expected hash of original.
    raw = json.loads(freeze_path.read_text(encoding="utf-8"))
    raw["tickets"] = raw["tickets"][:3]  # partial set
    raw["eligible_frozen_count"] = 3
    raw["content_hash"] = freeze_hash  # lie
    freeze_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(
        SettleAllFromRevealError,
        match="FREEZE_SET_HASH_ALTERED|FREEZE_SET_INVALID|role coverage|min_length",
    ):
        apply_settle_all_from_reveal(
            settlement_root=tmp_path / "s2",
            freeze_set_path=freeze_path,
            expected_freeze_set_hash=freeze_hash,
            reveal_artifact=_reveal_path(tmp_path, reveal, "r2.json"),
        )


def test_wrong_target_reveal_fail_closed(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    reveal = build_isolated_reveal_fixture(
        target_ref="draw.synthetic.OTHER",
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    with pytest.raises(SettleAllFromRevealError, match="REVEAL_TARGET_MISMATCH"):
        apply_settle_all_from_reveal(
            settlement_root=tmp_path / "s",
            freeze_set_path=freeze_path,
            expected_freeze_set_hash=freeze_hash,
            reveal_artifact=_reveal_path(tmp_path, reveal),
        )


def test_free_form_verified_outcome_not_authority(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    free_form = {
        "outcome_ref": "x",
        "source_ref": "caller",
        "target_ref": "draw.synthetic.1",
        "actual_special_number": 3,
        "observed_at": (OPEN + timedelta(minutes=1)).isoformat(),
        "verified": True,
    }
    with pytest.raises(SettleAllFromRevealError, match="REVEAL_ENVELOPE_REQUIRED"):
        apply_settle_all_from_reveal(
            settlement_root=tmp_path / "s",
            freeze_set_path=freeze_path,
            expected_freeze_set_hash=freeze_hash,
            reveal_artifact=_reveal_path(tmp_path, free_form),
        )


def test_changed_reveal_after_partial_fail_closed(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    freeze = FrozenDecisionSet.model_validate_json(freeze_path.read_text(encoding="utf-8"))
    r1 = build_isolated_reveal_fixture(
        target_ref=freeze.target_ref,
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
        outcome_ref="outcome.fixture/a",
    )
    r2 = build_isolated_reveal_fixture(
        target_ref=freeze.target_ref,
        actual_special_number=9,
        observed_at=OPEN + timedelta(minutes=1),
        outcome_ref="outcome.fixture/b",
    )
    root = tmp_path / "s"
    apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_path,
        expected_freeze_set_hash=freeze_hash,
        reveal_artifact=_reveal_path(tmp_path, r1, "r1.json"),
    )
    with pytest.raises(SettleAllFromRevealError, match="REVEAL_CHANGED_AFTER_PARTIAL"):
        apply_settle_all_from_reveal(
            settlement_root=root,
            freeze_set_path=freeze_path,
            expected_freeze_set_hash=freeze_hash,
            reveal_artifact=_reveal_path(tmp_path, r2, "r2.json"),
        )


def test_changed_freeze_set_after_partial_fail_closed(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    freeze = FrozenDecisionSet.model_validate_json(freeze_path.read_text(encoding="utf-8"))
    reveal = build_isolated_reveal_fixture(
        target_ref=freeze.target_ref,
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    root = tmp_path / "s"
    apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_path,
        expected_freeze_set_hash=freeze_hash,
        reveal_artifact=_reveal_path(tmp_path, reveal),
    )
    # Different freeze identity (new freeze_set_ref → new hash) against same root.
    other = frozen_set().model_copy(
        update={"freeze_set_ref": "freeze-set.synthetic.OTHER.v1", "content_hash": None}
    ).with_content_hash()
    other_path = tmp_path / "other_freeze.json"
    _write_json(other_path, other.model_dump(mode="json"))
    with pytest.raises(
        SettleAllFromRevealError,
        match="FREEZE_CHANGED_AFTER_PARTIAL|TICKET_SET_CHANGED_AFTER_PARTIAL",
    ):
        apply_settle_all_from_reveal(
            settlement_root=root,
            freeze_set_path=other_path,
            expected_freeze_set_hash=str(other.content_hash),
            reveal_artifact=_reveal_path(tmp_path, reveal, "r2.json"),
        )


def test_kwargs_override_fail_closed(tmp_path: Path) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    reveal = build_isolated_reveal_fixture(
        target_ref="draw.synthetic.1",
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    with pytest.raises(SettleAllFromRevealError, match="CALLER_OUTCOME_OVERRIDE_FORBIDDEN"):
        apply_settle_all_from_reveal(
            settlement_root=tmp_path / "s",
            freeze_set_path=freeze_path,
            expected_freeze_set_hash=freeze_hash,
            reveal_artifact=_reveal_path(tmp_path, reveal),
            actual_special_number=12,  # type: ignore[call-arg]
        )


def test_cli_settle_all_parser_and_dry_run(tmp_path: Path) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "prospective",
                "settle-all-from-reveal",
                "--settlement-root",
                "s",
                "--freeze-set",
                "f.json",
                "--expected-freeze-set-hash",
                "0" * 64,
                "--actual-special-number",
                "12",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "prospective",
                "settle-all-from-reveal",
                "--settlement-root",
                "s",
                "--freeze-set",
                "f.json",
                "--expected-freeze-set-hash",
                "0" * 64,
                "--outcome",
                "o.json",
            ]
        )
    # dry-run does not write
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    root = tmp_path / "dry_root"
    code = main(
        [
            "prospective",
            "settle-all-from-reveal",
            "--settlement-root",
            str(root),
            "--freeze-set",
            str(freeze_path),
            "--expected-freeze-set-hash",
            freeze_hash,
            "--reveal-artifact",
            str(_reveal_path(tmp_path, build_isolated_reveal_fixture(
                target_ref="draw.synthetic.1",
                actual_special_number=3,
                observed_at=OPEN + timedelta(minutes=1),
            ))),
            "--dry-run",
        ]
    )
    assert code == 0
    assert not (root / "settlement_set.v1.json").exists()


def test_cli_end_to_end_settle_all(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    freeze_path, freeze_hash = _freeze_path(tmp_path)
    reveal = build_isolated_reveal_fixture(
        target_ref="draw.synthetic.1",
        actual_special_number=3,
        observed_at=OPEN + timedelta(minutes=1),
    )
    rpath = _reveal_path(tmp_path, reveal)
    root = tmp_path / "cli_settle"
    code = main(
        [
            "prospective",
            "settle-all-from-reveal",
            "--settlement-root",
            str(root),
            "--freeze-set",
            str(freeze_path),
            "--expected-freeze-set-hash",
            freeze_hash,
            "--reveal-artifact",
            str(rpath),
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["settled_exactly_once_count"] == 4
    assert out["missing_or_duplicate_count"] == 0
    assert out["not_single_seat_shadow_portfolio"] is True


def test_formal_2026209_copy_consumer_shape_with_isolated_fixture(tmp_path: Path) -> None:
    """REAL freeze bytes + isolated reveal fixture for mechanics only.

    Does **not** claim formal 2026209 settlement or mutate formal state.
    """

    if not FORMAL_2026209_COPY.is_file():
        pytest.skip("formal 2026209 copy not present on this machine")

    # Work on an isolated copy — never the formal commission path.
    freeze_copy = tmp_path / "formal_2026209_frozen_decision_set.v1.json"
    shutil.copyfile(FORMAL_2026209_COPY, freeze_copy)
    freeze = load_sealed_freeze_set(
        freeze_set_path=freeze_copy,
        expected_freeze_set_hash=FORMAL_2026209_HASH,
    )
    assert freeze.target_ref == FORMAL_TARGET
    assert freeze.eligible_frozen_count == 4
    ticket_enum = enumerate_expected_tickets(freeze)
    assert set(ticket_enum["roles"]) == {
        "NO_ACTION",
        "NEG_CONTROL",
        "BASELINE",
        "SUBSTANTIVE",
    }

    reveal = build_isolated_reveal_fixture(
        target_ref=FORMAL_TARGET,
        actual_special_number=17,
        observed_at=FORMAL_OPEN + timedelta(hours=1),
        source_ref="isolated-reveal-fixture.wave97.formal-2026209-mechanics.v1",
    )
    assert reveal["schema_version"] == FIXTURE_REVEAL_SCHEMA
    assert reveal["fixture_isolated_mechanics"] is True
    assert reveal["formal_object_settled"] is False

    root = tmp_path / "isolated_2026209_settlement"
    receipt = apply_settle_all_from_reveal(
        settlement_root=root,
        freeze_set_path=freeze_copy,
        expected_freeze_set_hash=FORMAL_2026209_HASH,
        reveal_artifact=_reveal_path(tmp_path, reveal),
    )
    assert receipt["ok"] is True
    assert receipt["eligible_frozen_count"] == 4
    assert receipt["settled_exactly_once_count"] == 4
    assert receipt["missing_or_duplicate_count"] == 0
    assert receipt["conservation_ok"] is True
    assert receipt["fixture_isolated_mechanics"] is True
    assert receipt["formal_object_settled"] is False
    assert receipt["evidence_class"] == "ISOLATED_REVEAL_FIXTURE_MECHANICS"
    assert "formal" in receipt["next_true_consumer"].lower() or "FIXTURE" in receipt[
        "next_true_consumer"
    ]
    assert receipt["scientific_promotion"] is False
    # Isolated audit_scratch copy only — never write formal commission episode root.
    assert receipt["settlement_root"] == str(root)
    commission_episode = Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\codex_task_runs"
        r"\ai-research-runtime-commissioning-20260728-g5\evidence"
        r"\formal_prospective_2026209_v1\episode_2026209"
    )
    if commission_episode.is_dir():
        assert not (commission_episode / "settlement_set.v1.json").exists()


def test_single_seat_settle_from_reveal_verb_still_present() -> None:
    parser = build_parser()
    # Both verbs exist and remain distinct.
    help_settle = parser.parse_args(
        [
            "prospective",
            "settle-from-reveal",
            "--authority-root",
            "a",
            "--portfolio-root",
            "p",
            "--packet-content-hash",
            "a" * 64,
            "--dry-run",
        ]
    )
    assert help_settle.command == "settle-from-reveal"
    help_all = parser.parse_args(
        [
            "prospective",
            "settle-all-from-reveal",
            "--settlement-root",
            "s",
            "--freeze-set",
            "f",
            "--expected-freeze-set-hash",
            "b" * 64,
            "--dry-run",
        ]
    )
    assert help_all.command == "settle-all-from-reveal"


def test_module_self_attack_no_subset_api_surface() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "src/xinao/science/settle_all_from_reveal_adapter.py"
    )
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "apply_settle_all_from_reveal":
            arg_names = {a.arg for a in node.args.args}
            assert "ticket_refs" not in arg_names
            assert "subset" not in arg_names
            assert "actual_special_number" not in arg_names
            assert "verified" not in arg_names
    assert "settle_portfolio_period" not in src
    assert "OBJECT_MODEL" in src
