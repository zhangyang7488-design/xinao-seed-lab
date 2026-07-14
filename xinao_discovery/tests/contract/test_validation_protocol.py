from __future__ import annotations

from xinao.validation import PROTOCOL, build_split_version
from xinao.world.builder import load_draws


def test_fixed_split_contract_covers_all_913_rows_without_overlap() -> None:
    split = build_split_version(load_draws())
    assert split.row_counts == {
        "EXPLORATION": 547,
        "VALIDATION": 184,
        "CONFIRMATION_VAULT": 151,
        "FINAL_HOLDOUT": 31,
    }
    assert sum(split.row_counts.values()) == 913
    assert split.research_visible_partitions == ("EXPLORATION", "VALIDATION")
    assert split.research_forbidden_partitions == ("CONFIRMATION_VAULT", "FINAL_HOLDOUT")
    assert len(split.content_hash) == len(PROTOCOL.content_hash) == 64


def test_protocol_is_machine_fixed_and_purge_matches_lookback() -> None:
    assert PROTOCOL.purge_embargo_draws == max(
        PROTOCOL.feature_lookback_draws, PROTOCOL.decision_horizon_draws
    )
    assert PROTOCOL.exploration_multiple_testing == "BH_FDR_0.05"
    assert PROTOCOL.confirmation_multiple_testing == "HOLM_FWER_0.05"
