from pathlib import Path


def test_p12_probe_has_no_mutating_temporal_command() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "verify_xinao_p12_bypass.py"
    ).read_text(encoding="utf-8")
    assert '"workflow",\n            "list"' in source
    assert '"workflow",\n            "start"' not in source
    assert "P12 remains sidelined" in source
