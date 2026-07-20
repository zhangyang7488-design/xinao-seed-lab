from __future__ import annotations

import json
from pathlib import Path

import pytest
from services.agent_runtime.context_slice_manifest import (
    CONTEXT_SLICE_SPEC_VERSION,
    ContextSliceManifestError,
    build_context_slice_manifest,
    load_context_slice_manifest,
    validate_context_slice_manifest,
    write_context_slice_manifest,
)


def _write_spec(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"schema_version": CONTEXT_SLICE_SPEC_VERSION, "entries": entries}),
        encoding="utf-8",
    )


def test_build_extracts_python_symbols_and_line_ranges_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "HEADER = 1\n\ndef alpha(value: int) -> int:\n    return value + 1\n\ndef beta() -> str:\n    return 'b'\n",
        encoding="utf-8",
        newline="\n",
    )
    spec = tmp_path / "spec.json"
    _write_spec(
        spec,
        [
            {
                "path": "sample.py",
                "selectors": [
                    {"kind": "python_symbol", "name": "alpha"},
                    {"kind": "line_range", "start": 6, "end": 7},
                ],
            }
        ],
    )

    first = build_context_slice_manifest(root=tmp_path, spec_path=spec)
    second = build_context_slice_manifest(root=tmp_path, spec_path=spec)

    assert first == second
    assert first["authority"] is False
    assert first["completion_claim_allowed"] is False
    assert first["sources"][0]["path"] == "sample.py"
    assert [row["line_start"] for row in first["sources"][0]["slices"]] == [3, 6]
    assert "def alpha" in first["sources"][0]["slices"][0]["content"]


def test_source_drift_outside_slice_changes_context_identity(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("FLAG = 1\n\ndef alpha():\n    return 1\n", encoding="utf-8", newline="\n")
    spec = tmp_path / "spec.json"
    _write_spec(
        spec,
        [{"path": "sample.py", "selectors": [{"kind": "python_symbol", "name": "alpha"}]}],
    )
    before = build_context_slice_manifest(root=tmp_path, spec_path=spec)
    source.write_text("FLAG = 2\n\ndef alpha():\n    return 1\n", encoding="utf-8", newline="\n")
    after = build_context_slice_manifest(root=tmp_path, spec_path=spec)

    assert (
        before["sources"][0]["slices"][0]["content_sha256"]
        == after["sources"][0]["slices"][0]["content_sha256"]
    )
    assert before["source_manifest_sha256"] != after["source_manifest_sha256"]
    assert before["context_sha256"] != after["context_sha256"]


def test_raw_line_ending_drift_changes_identity(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    spec = tmp_path / "spec.json"
    _write_spec(
        spec,
        [{"path": "sample.py", "selectors": [{"kind": "python_symbol", "name": "alpha"}]}],
    )
    source.write_bytes(b"def alpha():\n    return 1\n")
    lf = build_context_slice_manifest(root=tmp_path, spec_path=spec)
    source.write_bytes(b"def alpha():\r\n    return 1\r\n")
    crlf = build_context_slice_manifest(root=tmp_path, spec_path=spec)

    assert lf["context_sha256"] != crlf["context_sha256"]


def test_rejects_escape_overlap_and_content_budget(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    _write_spec(
        spec,
        [{"path": "../sample.py", "selectors": [{"kind": "line_range", "start": 1, "end": 1}]}],
    )
    with pytest.raises(ContextSliceManifestError, match="bounded relative path"):
        build_context_slice_manifest(root=tmp_path, spec_path=spec)

    _write_spec(
        spec,
        [
            {
                "path": "sample.py",
                "selectors": [
                    {"kind": "python_symbol", "name": "alpha"},
                    {"kind": "line_range", "start": 1, "end": 1},
                ],
            }
        ],
    )
    with pytest.raises(ContextSliceManifestError, match="overlapping selectors"):
        build_context_slice_manifest(root=tmp_path, spec_path=spec)
    _write_spec(
        spec,
        [{"path": "sample.py", "selectors": [{"kind": "python_symbol", "name": "alpha"}]}],
    )
    with pytest.raises(ContextSliceManifestError, match="max_content_bytes"):
        build_context_slice_manifest(root=tmp_path, spec_path=spec, max_content_bytes=4)


def test_manifest_round_trip_detects_tamper(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    output = tmp_path / "manifest.json"
    _write_spec(
        spec,
        [{"path": "sample.py", "selectors": [{"kind": "python_symbol", "name": "alpha"}]}],
    )
    manifest = build_context_slice_manifest(root=tmp_path, spec_path=spec)
    write_context_slice_manifest(output, manifest)
    assert load_context_slice_manifest(output) == manifest

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["sources"][0]["slices"][0]["content"] += "# tamper\n"
    with pytest.raises(ContextSliceManifestError, match="content_sha256"):
        validate_context_slice_manifest(tampered)
