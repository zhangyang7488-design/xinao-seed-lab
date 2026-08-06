from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from services.agent_runtime.outcome_boundary_preflight import inspect_outcome_boundary

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "preflight_outcome_boundary.py"


def test_inspection_denies_post_cutoff_reference_without_returning_source_content(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unknown-worker-return.md"
    source.write_text(
        "ordinary pre-cutoff context\noutcome_interval=3000090..3000109\nprivate-result-sentinel\n",
        encoding="utf-8",
    )

    report = inspect_outcome_boundary(source, cutoff_period=3_000_100)

    assert report["disposition"] == "DENY_SEMANTIC_READ"
    assert report["semantic_read_allowed"] is False
    assert report["reason_codes"] == ["POST_CUTOFF_PERIOD_REFERENCE"]
    assert report["potential_match_count"] == 1
    serialized = json.dumps(report, ensure_ascii=False)
    assert "3000109" not in serialized
    assert "private-result-sentinel" not in serialized


def test_inspection_denies_explicit_consumption_marker_without_period_tokens(
    tmp_path: Path,
) -> None:
    source = tmp_path / "marker-only.txt"
    source.write_text(
        "post_cutoff_outcomes_consumed=true\nprivate-result-sentinel\n",
        encoding="utf-8",
    )

    report = inspect_outcome_boundary(source, cutoff_period=3_000_100)

    assert report["disposition"] == "DENY_SEMANTIC_READ"
    assert report["reason_codes"] == ["DECLARED_POST_CUTOFF_CONSUMPTION"]
    assert report["potential_match_count"] == 1
    assert "private-result-sentinel" not in json.dumps(report)


def test_inspection_allows_only_pre_cutoff_periods_and_ignores_embedded_digits(
    tmp_path: Path,
) -> None:
    source = tmp_path / "safe.txt"
    source.write_text(
        "period=3000099\npost_cutoff_outcomes_consumed=false\ndigest-fragment=abc3000109def\n",
        encoding="utf-8",
    )

    report = inspect_outcome_boundary(source, cutoff_period=3_000_100)

    assert report["disposition"] == "ALLOW_SEMANTIC_READ"
    assert report["semantic_read_allowed"] is True
    assert report["reason_codes"] == []
    assert report["potential_match_count"] == 0
    assert len(report["source_sha256"]) == 64


def test_inspection_fails_closed_for_non_utf8_or_oversized_artifacts(tmp_path: Path) -> None:
    binary = tmp_path / "binary.dat"
    binary.write_bytes(b"safe-prefix\x00\xff")
    oversized = tmp_path / "oversized.txt"
    oversized.write_text("x" * 33, encoding="utf-8")

    binary_report = inspect_outcome_boundary(binary, cutoff_period=3_000_100)
    oversized_report = inspect_outcome_boundary(
        oversized,
        cutoff_period=3_000_100,
        max_bytes=32,
    )

    assert binary_report["reason_codes"] == ["SOURCE_NOT_UTF8_TEXT"]
    assert oversized_report["reason_codes"] == ["SOURCE_EXCEEDS_MAX_BYTES"]
    assert binary_report["semantic_read_allowed"] is False
    assert oversized_report["semantic_read_allowed"] is False


def test_emit_command_never_prints_denied_content(tmp_path: Path) -> None:
    source = tmp_path / "dangerous.txt"
    source.write_text(
        "outcome_period=3000109\nprivate-result-sentinel\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "emit",
            "--path",
            str(source),
            "--cutoff-period",
            "3000100",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 3
    assert result.stdout == b""
    stderr = result.stderr.decode("utf-8")
    assert "3000109" not in stderr
    assert "private-result-sentinel" not in stderr
    report = json.loads(stderr)
    assert report["disposition"] == "DENY_SEMANTIC_READ"


def test_emit_command_outputs_the_exact_allowed_byte_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "safe.txt"
    raw = b"period=3000099\r\nordinary context\r\n"
    source.write_bytes(raw)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "emit",
            "--path",
            str(source),
            "--cutoff-period",
            "3000100",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == raw
    assert result.stderr == b""
