from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation import authority_promotion as promotion
from xinao.foundation.authority_generation import prepare_authority_generation


def _prepare(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    projection = tmp_path / "blueprint.current_domain_research.json"
    projection.write_bytes(registry.canonical_projection_path().read_bytes())
    generation = prepare_authority_generation(
        projection_path=projection,
        owner_id="codex-owner-test",
        rationale="reviewed publication is compatible with the sealed F1-F4 inventory",
        generation_root=tmp_path / "generations",
    )
    return projection, generation


def test_promotion_cas_rejects_projection_drift_without_overwrite(tmp_path: Path) -> None:
    projection, generation = _prepare(tmp_path)
    drifted = json.loads(projection.read_text(encoding="utf-8-sig"))
    drifted["_isolated_cas_drift"] = True
    projection.write_text(json.dumps(drifted), encoding="utf-8")
    drifted_bytes = projection.read_bytes()

    with pytest.raises(RuntimeError, match="FOUNDATION_PROMOTION_CAS_MISMATCH"):
        promotion.promote_authority_generation(
            projection_path=projection,
            generation_manifest_path=generation["manifest_path"],  # type: ignore[arg-type]
            receipt_root=tmp_path / "receipts",
            run_pytest=False,
        )

    assert projection.read_bytes() == drifted_bytes


def test_consumer_failure_rolls_back_exact_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, generation = _prepare(tmp_path)
    prior_bytes = projection.read_bytes()

    monkeypatch.setattr(
        promotion.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="forced consumer failure"
        ),
    )

    with pytest.raises(RuntimeError, match="FOUNDATION_PROMOTION_CONSUMER_TEST_FAILED"):
        promotion.promote_authority_generation(
            projection_path=projection,
            generation_manifest_path=generation["manifest_path"],  # type: ignore[arg-type]
            receipt_root=tmp_path / "receipts",
            run_pytest=True,
        )

    assert projection.read_bytes() == prior_bytes
    assert not list((tmp_path / "receipts").glob("*.json"))
    assert not list(tmp_path.glob("*.candidate"))
