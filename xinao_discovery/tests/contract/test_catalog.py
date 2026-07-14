from __future__ import annotations

from pathlib import Path

import pytest

from xinao.catalog.compiler import DEFAULT_BASELINE_PATH, compile_catalog, coverage_report


@pytest.mark.skipif(not DEFAULT_BASELINE_PATH.is_file(), reason="formal baseline is not mounted")
def test_fixed_baseline_compiles_to_full_explicit_coverage(tmp_path: Path) -> None:
    catalog = compile_catalog(
        baseline_ref="baseline-odds-water.v1",
        output_path=tmp_path / "catalog.json",
    )
    report = coverage_report(catalog, output_path=tmp_path / "coverage.json")
    assert catalog["entry_count"] == 433
    assert catalog["play_group_count"] == 13
    assert report == {
        "schema_version": "xinao.play_catalog_coverage.v1",
        "catalog_ref": "play-catalog.v1",
        "catalog_content_hash": catalog["content_hash"],
        "total": 433,
        "compiled": 2,
        "not_compiled": 431,
        "unclassified_count": 0,
        "unclassified": [],
        "ok": True,
    }


@pytest.mark.skipif(not DEFAULT_BASELINE_PATH.is_file(), reason="formal baseline is not mounted")
def test_slash_odds_remain_two_explicit_tiers(tmp_path: Path) -> None:
    catalog = compile_catalog(
        baseline_ref="baseline-odds-water.v1",
        output_path=tmp_path / "catalog.json",
    )
    entry = next(item for item in catalog["entries"] if item["baseline_id"] == "BO0213")
    assert entry["baseline_odds_components"] == ["51.5", "35.5"]
    assert entry["compilation_status"] == "NOT_COMPILED"


def test_wrong_baseline_identity_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        compile_catalog(baseline_ref="wrong", output_path=tmp_path / "catalog.json")
