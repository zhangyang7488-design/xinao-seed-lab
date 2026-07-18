from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from scripts import run_foundation_v2_f4_negative_companion as generator
from scripts import verify_f4_negative_companion_pack as verifier
from xinao.foundation.f4_snapshot_runtime import SnapshotRuntimeError


def _sealed(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, Path]]:
    bindings, index_binding = generator.seal_source_cas(tmp_path)
    report: dict[str, object] = {
        "source_index": index_binding,
        "source_bindings": bindings,
    }
    artifacts = {
        path.relative_to(tmp_path).as_posix(): path
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    return report, artifacts


def test_source_bindings_resolve_only_pack_local_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, artifacts = _sealed(tmp_path)
    unrelated_repo = tmp_path / "mutated-live-repo"
    unrelated_repo.mkdir()
    monkeypatch.setattr(verifier, "REPO_ROOT", unrelated_repo)

    paths, observed = verifier._verify_source_bindings(
        report,
        tmp_path,
        artifacts,
    )

    assert set(paths) == set(generator.SOURCE_ROLE_PATHS)
    assert all(path.is_relative_to(tmp_path) for path in paths.values())
    assert all("path" not in value for value in observed.values())


@pytest.mark.parametrize("mutation", ["missing", "hash", "extra", "map"])
def test_source_cas_rejects_inventory_and_binding_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    report, artifacts = _sealed(tmp_path)
    candidate = next(
        path for relative, path in artifacts.items() if relative.startswith("source_cas/sha256/")
    )
    if mutation == "missing":
        candidate.unlink()
    elif mutation == "hash":
        candidate.write_bytes(candidate.read_bytes() + b"\n# drift\n")
    elif mutation == "extra":
        raw = b"# unreferenced source CAS object\n"
        digest = hashlib.sha256(raw).hexdigest()
        extra = tmp_path / f"source_cas/sha256/{digest[:2]}/{digest}.py"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_bytes(raw)
        artifacts[extra.relative_to(tmp_path).as_posix()] = extra
    else:
        report = copy.deepcopy(report)
        bindings = report["source_bindings"]
        assert isinstance(bindings, dict)
        runner = bindings["runner"]
        assert isinstance(runner, dict)
        runner["logical_path"] = "scripts/not-the-bound-runner.py"

    with pytest.raises(verifier.VerificationError) as exc_info:
        verifier._verify_source_bindings(report, tmp_path, artifacts)
    if mutation == "missing":
        assert "source CAS object" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, SnapshotRuntimeError)


def test_negative_verifier_has_no_live_runner_source_binding() -> None:
    raw = Path(verifier.__file__).read_text(encoding="utf-8")
    assert 'REPO_ROOT / "scripts" / "run_foundation_v2_f4_negative_companion.py"' not in raw
    assert "source_cas/sha256/" in raw
