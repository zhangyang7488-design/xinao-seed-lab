from __future__ import annotations

from pathlib import Path

import pytest
from scripts import local_data_profile


def test_profiles_csv_without_exposing_rows_by_default(tmp_path: Path) -> None:
    source = tmp_path / "people.csv"
    source.write_text("name,score\nAda,10\nLin,20\nNobody,\n", encoding="utf-8")

    result = local_data_profile.profile_data(source)

    assert result["rows"] == 3
    assert result["columns"] == 2
    assert result["null_counts"] == {"name": 0, "score": 1}
    assert result["numeric_summary"]["score"] == {"min": 10, "max": 20, "mean": 15.0}
    assert result["sample_rows"] == []
    assert result["content_network_egress"] is False


def test_opt_in_sample_is_limited_and_truncated(tmp_path: Path) -> None:
    source = tmp_path / "sample.jsonl"
    source.write_text('{"text":"abcdefgh"}\n{"text":"second"}\n', encoding="utf-8")

    result = local_data_profile.profile_data(source, sample_rows=1, max_value_chars=4)

    assert result["sample_rows"] == [{"text": "abcd…"}]


def test_rejects_remote_and_unknown_sources(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="URLs are not allowed"):
        local_data_profile.profile_data("https://example.com/data.csv")
    source = tmp_path / "data.exe"
    source.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="Unsupported data format"):
        local_data_profile.profile_data(source)
