"""Wave104: public CLI JSON must round-trip on Windows default codepages.

The packaged CLI previously dumped machine-readable JSON with
``ensure_ascii=False``. On a host whose redirected stdout uses cp936/GBK,
characters outside that codec (for example U+2286 in the real one-shot
fixture) raised ``UnicodeEncodeError`` after a successful pool ingest.

These regressions force a subprocess without ``PYTHONUTF8`` /
``PYTHONIOENCODING``, exercise the real public verbs, and assert:
returncode 0, JSON parse, pure-ASCII wire form, and exact Unicode recovery.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from xinao.cli_json import dumps_cli_json, print_cli_json

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "oneshot_xrr_20260730T201916_20001f0913"
REAL_RESULT_PATH = FIXTURE_DIR / "result.json"
REAL_RECEIPT_PATH = FIXTURE_DIR / "receipt.json"

EXPECTED_RESULT_SHA256 = "12a53a6ff51a52fa6e2635df4508185a967210966fc44fcda101e24fbd876ec9"
# Subset-of (U+2286) appears in the historical one-shot candidate hypothesis text.
NON_CODEPAGE_CHAR = "\u2286"


def _env_default_codepage() -> dict[str, str]:
    """Inherit host env but strip UTF-8 overrides that hide the real Windows failure."""

    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_cli_bytes(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "xinao.cli", *argv],
        cwd=str(ROOT),
        env=_env_default_codepage(),
        capture_output=True,
        text=False,
        check=False,
    )


def _decode_cli_stdout(raw: bytes) -> str:
    """CLI JSON is ASCII-safe; decode as UTF-8 or GBK without loss for the wire form."""

    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        # Should not happen after the repair; surface for diagnosis.
        return raw.decode("utf-8")


def _payload_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_payload_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_payload_contains(item, needle) for item in value)
    return False


def test_fixture_carries_non_codepage_unicode() -> None:
    raw = REAL_RESULT_PATH.read_text(encoding="utf-8")
    assert NON_CODEPAGE_CHAR in raw
    # Host GBK cannot encode this character; that is the public consumer hazard.
    with pytest.raises(UnicodeEncodeError):
        NON_CODEPAGE_CHAR.encode("gbk")


def test_dumps_cli_json_is_ascii_and_roundtrips() -> None:
    payload = {
        "marker": NON_CODEPAGE_CHAR,
        "nested": {"text": f"prefix {NON_CODEPAGE_CHAR} suffix"},
        "list": [NON_CODEPAGE_CHAR, "plain"],
    }
    wire = dumps_cli_json(payload)
    assert wire.isascii()
    assert "\\u2286" in wire
    assert NON_CODEPAGE_CHAR not in wire
    recovered = json.loads(wire)
    assert recovered == payload
    assert recovered["marker"] == NON_CODEPAGE_CHAR


def test_print_cli_json_survives_gbk_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct emitter smoke: print must not raise when stdout codec is gbk."""

    import io

    buffer = io.TextIOWrapper(io.BytesIO(), encoding="gbk", write_through=True)
    print_cli_json({"probe": f"has {NON_CODEPAGE_CHAR}"}, file=buffer)
    buffer.flush()
    raw = buffer.buffer.getvalue()  # type: ignore[attr-defined]
    assert raw.decode("ascii")
    assert json.loads(raw.decode("ascii"))["probe"] == f"has {NON_CODEPAGE_CHAR}"


@pytest.mark.parametrize(
    "verb",
    [
        "pool-ingest-result",
        "pool-ingest-oneshot",
    ],
)
def test_public_oneshot_verbs_roundtrip_non_codepage_unicode(tmp_path: Path, verb: str) -> None:
    pool = tmp_path / f"pool_{verb}"
    proc = _run_cli_bytes(
        [
            "research-episode",
            verb,
            "--pool-root",
            str(pool),
            "--result",
            str(REAL_RESULT_PATH),
            "--receipt",
            str(REAL_RECEIPT_PATH),
        ]
    )
    stderr_text = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, stderr_text
    assert b"UnicodeEncodeError" not in proc.stderr
    stdout_text = _decode_cli_stdout(proc.stdout)
    assert stdout_text.isascii(), "machine-readable JSON wire form must be ASCII-safe"
    out = json.loads(stdout_text)
    assert out["ok"] is True
    assert out["result_sha256"] == EXPECTED_RESULT_SHA256
    assert _payload_contains(out, NON_CODEPAGE_CHAR), (
        "parsed JSON must recover the exact original non-codepage character"
    )
    # Nested path known from the historical fixture.
    hypotheses = out.get("candidate", {}).get("hypotheses")
    assert isinstance(hypotheses, list) and hypotheses
    assert NON_CODEPAGE_CHAR in hypotheses[0]


def test_shared_emitter_error_surface_roundtrips_non_codepage(tmp_path: Path) -> None:
    """Another public JSON surface (research-episode fail envelope) shares the emitter."""

    missing = tmp_path / "no-such-result.json"
    receipt = REAL_RECEIPT_PATH
    proc = _run_cli_bytes(
        [
            "research-episode",
            "pool-ingest-result",
            "--pool-root",
            str(tmp_path / "pool"),
            "--result",
            str(missing),
            "--receipt",
            str(receipt),
        ]
    )
    # Missing file yields a fail JSON envelope (not a crash).
    assert proc.returncode == 1
    stdout_text = _decode_cli_stdout(proc.stdout)
    assert stdout_text.isascii()
    out = json.loads(stdout_text)
    assert out["ok"] is False
    assert out["completion_claim_allowed"] is False
    assert "reason_code" in out


def test_prospective_fail_surface_escapes_non_codepage_detail(tmp_path: Path) -> None:
    """Prospective CLI shares print_cli_json; non-codepage detail must not crash."""

    # Missing payload path is embedded in the fail envelope error string.
    # Craft a path containing a non-codepage character so the shared emitter is exercised.
    missing = tmp_path / f"disp_{NON_CODEPAGE_CHAR}.json"
    proc = _run_cli_bytes(
        [
            "prospective",
            "write-owner-disposition",
            "--owner-state-root",
            str(tmp_path / "owner"),
            "--pool-root",
            str(tmp_path / "pool"),
            "--payload",
            str(missing),
        ]
    )
    assert proc.returncode == 1
    assert b"UnicodeEncodeError" not in proc.stderr
    stdout_text = _decode_cli_stdout(proc.stdout)
    assert stdout_text.isascii()
    out = json.loads(stdout_text)
    assert out["ok"] is False
    assert out["reason_code"] == "DISPOSITION_PAYLOAD_MISSING"
    assert NON_CODEPAGE_CHAR in out["error"]
