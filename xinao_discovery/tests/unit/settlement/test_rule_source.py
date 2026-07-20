from __future__ import annotations

import pytest
from pydantic import ValidationError

from xinao.settlement import (
    SOURCE_BUNDLE_HASH,
    SPECIAL_NUMBER_FUNCTION,
    SPECIAL_NUMBER_RULE,
    SemanticClaim,
    TargetMarketSnapshotRuleVersion,
    evaluate_special_number_page_evidence,
    verify_source_bundle,
    verify_special_number_rule_evidence,
)


def test_rule_version_keeps_page_facts_and_research_conventions_distinct() -> None:
    assert SPECIAL_NUMBER_RULE.rule_ref == "special-number-rule.v1"
    assert SPECIAL_NUMBER_FUNCTION.function_ref == "special-number-settlement.v1"
    assert SPECIAL_NUMBER_FUNCTION.rule_ref == SPECIAL_NUMBER_RULE.rule_ref
    assert SPECIAL_NUMBER_RULE.source_type == "TARGET_MARKET_PAGE_SNAPSHOT"
    assert SPECIAL_NUMBER_RULE.source_bundle_hash == SOURCE_BUNDLE_HASH
    assert SPECIAL_NUMBER_RULE.authority_basis == "USER_CONFIRMED_LOCAL_SNAPSHOT"
    assert SPECIAL_NUMBER_RULE.semantic_status == (
        "EXPLICIT_PAGE",
        "RESEARCH_CONVENTION",
    )
    claims = {claim.semantic_status for claim in SPECIAL_NUMBER_RULE.claims}
    assert claims == {"EXPLICIT_PAGE", "RESEARCH_CONVENTION"}


def test_rule_version_rejects_a_collapsed_semantic_identity() -> None:
    claims = (
        SemanticClaim(
            claim_ref="page",
            semantic_status="EXPLICIT_PAGE",
            statement="page fact",
            source_refs=("page",),
        ),
    )
    with pytest.raises(ValidationError):
        TargetMarketSnapshotRuleVersion(
            semantic_status=("EXPLICIT_PAGE",),
            claims=claims,
        )


def test_current_source_bundle_recomputes_every_manifest_entry() -> None:
    report = verify_source_bundle()
    assert report["ok"] is True
    assert report["source_bundle_hash"] == SOURCE_BUNDLE_HASH
    assert report["manifest_entry_count"] == 28
    assert report["actual_file_count"] == 29
    assert report["failures"] == []


def test_special_number_slice_has_cross_page_and_historical_replay_evidence() -> None:
    report = verify_special_number_rule_evidence()
    assert report["ok"] is True
    assert report["family_compilation_status"] == "PARTIALLY_COMPILED"
    assert report["compiled_baseline_ids"] == ["BO0001", "BO0013"]
    assert report["cross_page_evidence"]["admitted_snapshot_count_by_panel"] == {
        "A": 4,
        "B": 2,
    }
    assert report["cross_page_evidence"]["settlement_rule_term_hit_count"] == 0
    assert report["historical_replay"]["draw_count"] == 913
    assert report["historical_replay"]["positive_case_count"] == 1826
    assert report["historical_replay"]["negative_case_count"] == 1826
    assert report["historical_replay"]["event_row_count"] == 89474
    assert report["verification_scope"] == "SPECIAL_NUMBER_EXACT_NUMBER_SLICE_ONLY"
    assert report["family_compilation_complete"] is False
    assert report["foundation_closure_claim_allowed"] is False


def test_candidate_132_pollution_is_ignored_and_cross_panel_url_mismatch_is_rejected() -> None:
    items: list[dict[str, object]] = []
    pages: list[dict[str, object]] = []
    page_specs = (
        ("a-main", "A", "14", "https://example.test/Index/dropMa/pid/1", "47.285"),
        ("a-panel", "A", "14", "https://example.test/dropma/pan/A/tid/14", "47.285"),
        ("b-one", "B", "15", "https://example.test/dropma/pan/B/tid/15", "42.385"),
        ("b-two", "B", "15", "https://example.test/dropma/pan/B/tid/15", "42.385"),
        ("a-wrong-url", "A", "14", "https://example.test/dropma/pan/B/tid/15", "47.285"),
    )
    for key, panel, tid, url, odds in page_specs:
        pages.append(
            {
                "canonical_key": key,
                "bodyText": " ".join(f"{number:02d} {odds}" for number in range(1, 50)),
            }
        )
        for number in range(1, 50):
            items.append(
                {
                    "page_key": key,
                    "source_file": f"{key}.json",
                    "group": "特码",
                    "pan": panel,
                    "tid": tid,
                    "final_url": url,
                    "item": f"{number:02d}",
                    "odds": odds,
                }
            )
    items.append(
        {
            "page_key": "a-main",
            "source_file": "a-main.json",
            "group": "特码",
            "pan": "A",
            "tid": "14",
            "final_url": "https://example.test/Index/dropMa/pid/1",
            "item": "49",
            "odds": "132",
        }
    )

    report = evaluate_special_number_page_evidence(items, pages)  # type: ignore[arg-type]
    assert report["ok"] is True
    assert report["admitted_snapshot_count_by_panel"] == {"A": 2, "B": 2}
    assert all(item["page_key"] != "a-wrong-url" for item in report["admitted_snapshots"])
    a_main = next(item for item in report["admitted_snapshots"] if item["page_key"] == "a-main")
    assert a_main["displayed_odds"] == "47.285"
    assert a_main["ignored_candidate_odds"] == ["132"]
