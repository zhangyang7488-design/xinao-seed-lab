from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "_l0_m1_frequency_null_canary.py"
    spec = importlib.util.spec_from_file_location("l0_m1_frequency_null", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_special_numbers_reads_last_open_code_from_tsv(tmp_path: Path) -> None:
    snapshot = tmp_path / "draws.tsv"
    snapshot.write_text(
        "\nexpect\topenTime\topenCode\twave\tzodiac\n"
        "1\t2026-01-01\t01,02,03,04,05,06,07\tx\tx\n"
        "2\t2026-01-02\t08,09,10,11,12,13,14\tx\tx\n"
        "3\t2026-01-03\tbad\tx\tx\n"
        "4\t2026-01-04\t15,16,17,18,19,20,21\tx\tx\n",
        encoding="utf-8",
    )

    assert _module().load_special_numbers(snapshot, 2) == [14, 21]


def test_load_special_numbers_rejects_wrong_schema(tmp_path: Path) -> None:
    snapshot = tmp_path / "wrong.tsv"
    snapshot.write_text("expect\tvalue\n1\t7\n", encoding="utf-8")

    with pytest.raises(ValueError, match="openCode"):
        _module().load_special_numbers(snapshot, 10)
