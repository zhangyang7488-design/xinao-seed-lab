from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import xinao_market_lab.public_sources as p6
from xinao_market_lab.public_sources import (
    P6_FORMAL_ARTIFACT_NAMES,
    P6_WARC_FILENAME,
    build_p6_p5_acceptance_pin,
    build_p6_trusted_anchor,
    run_p6_public_source_role_ruleclaim,
    verify_p6_run,
)

RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs")
CAPTURE = RUN_ROOT / "p6-public-primary-source-capture-20260711"
CAPTURE_ANCHOR = RUN_ROOT / "p6-public-primary-source-capture-anchor-20260711.json"
P5_RUN = RUN_ROOT / "p5-unresolved-semantics-evidence-catalog-acceptance-a-20260711"
P5_ANCHOR = RUN_ROOT / "p5-unresolved-semantics-evidence-catalog-trusted-anchor-20260711.json"
P5_ADMIN = RUN_ROOT / "p5-admin-acceptance-20260711" / "admin_acceptance.json"
P5_INDEPENDENT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\temp\p5-independent-verifier-20260711"
    r"\independent_verification_report.json"
)
P6_A = RUN_ROOT / "p6-public-source-role-ruleclaim-acceptance-a-20260711"
P6_B = RUN_ROOT / "p6-public-source-role-ruleclaim-acceptance-b-20260711"
P6_ANCHOR = RUN_ROOT / "p6-public-source-role-ruleclaim-trusted-anchor-20260711.json"
CANONICAL_PATHS = (
    CAPTURE,
    CAPTURE_ANCHOR,
    P5_RUN,
    P5_ANCHOR,
    P5_ADMIN,
    P5_INDEPENDENT,
    P6_A,
    P6_B,
    P6_ANCHOR,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    not all(path.exists() for path in CANONICAL_PATHS),
    reason="canonical P5/P6 evidence is unavailable",
)
def test_p6_actual_dual_offline_run_anchor_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_before = {
        path.name: _sha(path) for path in (*sorted(CAPTURE.iterdir()), CAPTURE_ANCHOR) if path.is_file()
    }
    for name in (*P6_FORMAL_ARTIFACT_NAMES, "run_manifest.json"):
        assert (P6_A / name).read_bytes() == (P6_B / name).read_bytes()

    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("P6 formal verification attempted network access")

    monkeypatch.setattr(p6.socket, "getaddrinfo", network_forbidden)
    monkeypatch.setattr(p6, "_p6_source_fingerprint", lambda: "f" * 64)
    verified_a = verify_p6_run(
        run_dir=P6_A,
        capture_dir=CAPTURE,
        capture_anchor_path=CAPTURE_ANCHOR,
        p5_run_dir=P5_RUN,
        p5_trusted_anchor=P5_ANCHOR,
        p5_admin_acceptance=P5_ADMIN,
        p5_independent_report=P5_INDEPENDENT,
        trusted_anchor=P6_ANCHOR,
    )
    verified_b = verify_p6_run(
        run_dir=P6_B,
        capture_dir=CAPTURE,
        capture_anchor_path=CAPTURE_ANCHOR,
        p5_run_dir=P5_RUN,
        p5_trusted_anchor=P5_ANCHOR,
        p5_admin_acceptance=P5_ADMIN,
        p5_independent_report=P5_INDEPENDENT,
        trusted_anchor=P6_ANCHOR,
    )
    with pytest.raises(FileExistsError, match="immutable"):
        build_p6_trusted_anchor(
            run_dir=P6_A,
            capture_dir=CAPTURE,
            capture_anchor_path=CAPTURE_ANCHOR,
            p5_run_dir=P5_RUN,
            p5_trusted_anchor=P5_ANCHOR,
            p5_admin_acceptance=P5_ADMIN,
            p5_independent_report=P5_INDEPENDENT,
            anchor_path=P6_ANCHOR,
        )
    capture_after = {
        path.name: _sha(path) for path in (*sorted(CAPTURE.iterdir()), CAPTURE_ANCHOR) if path.is_file()
    }
    quarantine = json.loads((P6_A / "quarantine_register.json").read_text(encoding="utf-8"))
    judge = json.loads((P6_A / "judge_gate_p6.json").read_text(encoding="utf-8"))

    assert capture_before == capture_after
    assert b"w1.kka8f.com" not in (CAPTURE / P6_WARC_FILENAME).read_bytes()
    assert {key: value for key, value in verified_a.items() if key != "run_dir"} == {
        key: value for key, value in verified_b.items() if key != "run_dir"
    }
    assert verified_a["trusted_anchor_verified"] is True
    assert verified_a["public_source_status"] == "PUBLIC_PRIMARY_SOURCE_BUNDLE_VERIFIED"
    assert verified_a["macau_official_product_claim_status"] == "MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED"
    assert verified_a["semantics_status"] == "SEMANTICS_STILL_UNRESOLVED"
    assert verified_a["economic_claim_status"] == "ECONOMIC_CLAIM_BLOCKED"
    assert quarantine["entries"][0]["exact_domain_legal_status"] == "NOT_DETERMINED"
    assert quarantine["entries"][0]["fetched_in_p6"] is False
    assert all(judge["checks"].values())


@pytest.mark.skipif(
    not all(path.exists() for path in CANONICAL_PATHS),
    reason="canonical P5/P6 evidence is unavailable",
)
def test_p6_resigned_role_escalation_is_rejected(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(P6_A, fixture)
    quarantine_path = fixture / "quarantine_register.json"
    quarantine = json.loads(quarantine_path.read_text(encoding="utf-8"))
    quarantine["entries"][0]["exact_domain_legal_status"] = "ILLEGAL"
    quarantine_path.write_text(
        json.dumps(
            quarantine,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = fixture / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(
        row for row in manifest["artifacts"] if row["relative_path"] == "quarantine_register.json"
    )
    artifact["size_bytes"] = quarantine_path.stat().st_size
    artifact["sha256"] = _sha(quarantine_path)
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="semantic artifact mismatch"):
        verify_p6_run(
            run_dir=fixture,
            capture_dir=CAPTURE,
            capture_anchor_path=CAPTURE_ANCHOR,
            p5_run_dir=P5_RUN,
            p5_trusted_anchor=P5_ANCHOR,
            p5_admin_acceptance=P5_ADMIN,
            p5_independent_report=P5_INDEPENDENT,
        )


@pytest.mark.skipif(
    not all(path.exists() for path in CANONICAL_PATHS),
    reason="canonical P5/P6 evidence is unavailable",
)
def test_p6_rejects_p5_source_contract_not_bound_by_anchor(tmp_path: Path) -> None:
    fixture = tmp_path / "p5-fixture"
    shutil.copytree(P5_RUN, fixture)
    source_contract_path = fixture / "source_scan_contract.json"
    source_contract = json.loads(source_contract_path.read_text(encoding="utf-8"))
    page_catalog = next(
        row
        for row in source_contract["entries"]
        if row["relative_path"].endswith("/analysis_ready/page_catalog_all_sources.csv")
    )
    page_catalog["source_sha256"] = "f" * 64
    source_contract_path.write_text(
        json.dumps(
            source_contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trusted anchor"):
        build_p6_p5_acceptance_pin(
            p5_run_dir=fixture,
            p5_trusted_anchor=P5_ANCHOR,
            p5_admin_acceptance=P5_ADMIN,
            p5_independent_report=P5_INDEPENDENT,
        )


@pytest.mark.skipif(
    not all(path.exists() for path in CANONICAL_PATHS),
    reason="canonical P5/P6 evidence is unavailable",
)
def test_p6_canonical_evidence_rejects_non_d_runtime_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="canonical P6 formal evidence"):
        run_p6_public_source_role_ruleclaim(
            evidence_root=tmp_path,
            run_name="forbidden",
            capture_dir=CAPTURE,
            capture_anchor_path=CAPTURE_ANCHOR,
            p5_run_dir=P5_RUN,
            p5_trusted_anchor=P5_ANCHOR,
            p5_admin_acceptance=P5_ADMIN,
            p5_independent_report=P5_INDEPENDENT,
        )
