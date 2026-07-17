from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from xinao.foundation import f4_evidence_snapshot as snapshot
from xinao.foundation import f4_snapshot_runtime as runtime


def _capsule(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    child = source / "child.json"
    child.write_text('{"value":1}\n', encoding="utf-8")
    (source / "index.json").write_text(
        json.dumps({"path": str(child.resolve())}) + "\n",
        encoding="utf-8",
    )
    builder = snapshot.EvidenceSnapshotBuilder(
        tmp_path / "capsule",
        allowed_source_roots=[tmp_path],
    )
    builder.add_root("primary", source)
    return builder.build(), source, child


def _enable(monkeypatch: pytest.MonkeyPatch, manifest: Path) -> None:
    monkeypatch.setenv(runtime.SNAPSHOT_MANIFEST_ENV, str(manifest))
    monkeypatch.setattr(runtime, "_RUNTIME", False)


def test_snapshot_runtime_resolves_retained_identity_after_original_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, source, child = _capsule(tmp_path)
    retained_child = str(child.resolve())
    moved_source = tmp_path / "source-moved"
    source.rename(moved_source)
    _enable(monkeypatch, manifest)

    resolved = runtime.input_path(retained_child, expect="file")
    assert resolved.read_bytes() == (moved_source / "child.json").read_bytes()
    assert runtime.retained_path(resolved) == retained_child
    assert runtime.retained_path(resolved.as_posix()) == retained_child
    assert runtime.same_path(resolved, retained_child)
    assert runtime.inside(resolved, str(source.resolve()))


def test_snapshot_runtime_rejects_unknown_live_path_and_allows_declared_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, _ = _capsule(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    generated = output / "generated.json"
    generated.write_text("{}\n", encoding="utf-8")
    _enable(monkeypatch, manifest)
    monkeypatch.setenv(runtime.SNAPSHOT_OUTPUT_ROOT_ENV, str(output))

    with pytest.raises(runtime.SnapshotRuntimeError, match="no declared input identity"):
        runtime.input_path(tmp_path / "unknown.json", expect="file")
    assert runtime.readable_path(generated) == generated.resolve()
    assert runtime.file_sha256(generated) == snapshot.file_sha256(generated)


def test_snapshot_runtime_remains_valid_after_capsule_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, child = _capsule(tmp_path)
    moved = tmp_path / "moved-capsule"
    shutil.copytree(manifest.parent, moved)
    _enable(monkeypatch, moved / snapshot.MANIFEST_NAME)

    resolved = runtime.input_path(str(child.resolve()), expect="file")
    assert str(moved) in str(resolved)
    report = runtime.snapshot_runtime().resolver.trace_report()  # type: ignore[union-attr]
    assert report["fallback_count"] == 0
    assert report["event_count"] >= 1
