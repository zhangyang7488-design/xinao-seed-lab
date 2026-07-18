from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from scripts import verify_f4_portfolio_source_canary_pack as subject


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _minimal_manifest(pack: Path) -> tuple[Path, Path]:
    report = _write_json(pack / "portfolio_source_canary_report.json", {"ok": True})
    payload = _write_json(pack / "inputs" / "payload.json", {"bound": True})
    entries = []
    for path in (payload, report):
        entries.append(
            {
                "path": path.relative_to(pack).as_posix(),
                "sha256": subject.file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    entries.sort(key=lambda item: item["path"])
    body = {
        "schema_version": "xinao.f4_portfolio_source_canary_manifest.v1",
        "report_ref": str(report.resolve()),
        "report_file_sha256": subject.file_sha256(report),
        "entry_count": len(entries),
        "entries": entries,
    }
    _write_json(
        pack / "evidence_manifest.json",
        {**body, "content_sha256": subject.canonical_sha256(body)},
    )
    return payload, report


def test_manifest_recomputes_exact_file_bytes(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    payload, _ = _minimal_manifest(pack)

    manifest, _, entries = subject._verify_manifest(pack, subject.Audit())

    assert manifest["entry_count"] == 2
    assert set(entries) == {
        "inputs/payload.json",
        "portfolio_source_canary_report.json",
    }

    payload.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(subject.VerificationError, match="byte hash drifted"):
        subject._verify_manifest(pack, subject.Audit())


def test_manifest_rejects_unlisted_file(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _minimal_manifest(pack)
    (pack / "unlisted.txt").write_text("not bound\n", encoding="utf-8")

    with pytest.raises(subject.VerificationError, match="exact source-pack file set"):
        subject._verify_manifest(pack, subject.Audit())


def test_versioned_identity_fails_closed_after_rehashless_mutation() -> None:
    core = {
        "object_type": "Example",
        "schema_version": "example.v1",
        "value": 1,
    }
    digest = subject.canonical_sha256(core)
    value = {
        **core,
        "version_id": f"Example@{digest[:16]}",
        "content_sha256": digest,
    }
    assert subject._verify_versioned(value, subject.Audit()) == digest

    value["value"] = 2
    with pytest.raises(subject.VerificationError, match="content identity drifted"):
        subject._verify_versioned(value, subject.Audit())


def test_weighted_order_uses_share_then_canonical_tie_break() -> None:
    rows = [
        {
            "candidate_id": "candidate:b",
            "work_key": "b" * 64,
            "family_id": "b",
            "portfolio_lane": "EXPLOITATION",
        },
        {
            "candidate_id": "candidate:a",
            "work_key": "a" * 64,
            "family_id": "a",
            "portfolio_lane": "EXPLOITATION",
        },
        {
            "candidate_id": "candidate:c",
            "work_key": "c" * 64,
            "family_id": "c",
            "portfolio_lane": "EXPLOITATION",
        },
    ]
    scheduled = subject._expected_allocation_order(
        rows,
        {"a": Decimal("0.4"), "b": Decimal("0.4"), "c": Decimal("0.1")},
    )

    assert [item[2]["candidate_id"] for item in scheduled] == [
        "candidate:a",
        "candidate:b",
        "candidate:c",
    ]


def test_rehash_versioned_rebinds_mutated_negative() -> None:
    value = {
        "object_type": "Example",
        "schema_version": "example.v1",
        "value": "changed",
        "version_id": "stale",
        "content_sha256": "0" * 64,
    }
    subject._rehash_versioned(value)

    assert subject._verify_versioned(value, subject.Audit()) == value["content_sha256"]


@pytest.mark.skipif(
    os.environ.get("XINAO_RUN_F4_PORTFOLIO_PACK_INTEGRATION") != "1"
    or not subject.DEFAULT_PACK.is_dir(),
    reason="requires the retained current-source F4 portfolio pack",
)
def test_retained_current_source_pack_verifies_independently() -> None:
    report = subject.verify_portfolio_pack(subject.DEFAULT_PACK)

    assert report["status"] == "VERIFIED"
    assert report["assertion_count"] == 8
    assert report["primitive_check_count"] > 2_000
    assert report["unclosed_items"] == []
    assert report["content_sha256"] == subject.canonical_sha256(
        {key: value for key, value in report.items() if key != "content_sha256"}
    )
