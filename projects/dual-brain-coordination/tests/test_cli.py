from __future__ import annotations

import json
from pathlib import Path

from xinao_coordination.cli import main


def test_cli_status_json(db_path: Path, capsys: object) -> None:
    code = main(["--db", str(db_path), "status"])
    assert code == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    parsed = json.loads(output)
    assert parsed["health"]["quick_check"] == "ok"
    assert parsed["background_daemon"] is False


def test_cli_route_assessment_is_advisory(db_path: Path, capsys: object) -> None:
    code = main(
        [
            "--db",
            str(db_path),
            "route-assess",
            "--uncertainty",
            "1",
            "--complementarity",
            "1",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    parsed = json.loads(output)
    assert parsed["advisory_only"] is True


def test_cli_validation_error_is_json_without_traceback(db_path: Path, capsys: object) -> None:
    code = main(["--db", str(db_path), "route-assess", "--uncertainty", "NaN"])
    assert code == 2
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    parsed = json.loads(output)
    assert parsed["error"] == "validation_error"
    assert "Traceback" not in output


def test_cli_invalid_custom_weight_is_safe_json(db_path: Path, capsys: object) -> None:
    code = main(
        [
            "--db",
            str(db_path),
            "route-assess",
            "--benefit-weights",
            '{"bad":1}',
        ]
    )
    assert code == 2
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    parsed = json.loads(output)
    assert parsed["error"] == "validation_error"
    assert "Traceback" not in output
