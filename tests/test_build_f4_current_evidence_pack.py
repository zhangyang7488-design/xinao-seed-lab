from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from xinao.foundation import f4_current_evidence_builder as subject


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return path


def _source_pack(root: Path, name: str, manifest_name: str) -> tuple[Path, Path]:
    pack = root / name
    _write(pack / "payload.json", {"pack": name})
    manifest = _write(pack / manifest_name, {"schema_version": f"{name}.manifest.v1"})
    return pack, manifest


def _verified_file(
    directory: Path,
    *,
    pack: Path,
    manifest: Path,
    marker: str,
) -> Path:
    core = {
        "schema_version": f"test.{marker}.verification.v1",
        "status": "VERIFIED",
        "source_pack": str(pack.resolve()),
        "source_manifest_sha256": subject.file_sha256(manifest),
        "assertion_count": 1,
    }
    content_hash = subject.canonical_sha256(core)
    return _write(
        directory / f"{content_hash}.json",
        {**core, "content_sha256": content_hash},
    )


def _behavior_summary(path: Path) -> Path:
    return _write(
        path,
        {
            "schema_version": "test.behavior_summary.v1",
            "run_id": path.parent.name,
            "case_pattern": "continuous interjection",
            "suites": {"case_ids": ["REG_PERPETUAL_INTERJECTION_RESUMES_ACTIVE_RUN"]},
            "totals": {"successes": 1, "failures": 0, "errors": 0},
            "exit_code": 0,
            "infrastructure_error": None,
        },
    )


def test_discover_latest_verified_uses_content_address_and_status(tmp_path: Path) -> None:
    pack, manifest = _source_pack(tmp_path, "pack", "artifact_manifest.json")
    directory = tmp_path / "verifications"
    verified = _verified_file(
        directory,
        pack=pack,
        manifest=manifest,
        marker="verified",
    )
    invalid = _write(
        directory / ("f" * 64 + ".json"),
        {"status": "VERIFIED", "content_sha256": "f" * 64},
    )
    os.utime(invalid, (verified.stat().st_mtime + 10, verified.stat().st_mtime + 10))

    assert subject.discover_latest_verified(directory) == verified.resolve()


def test_cli_requires_every_source_identity_instead_of_dated_defaults() -> None:
    with pytest.raises(SystemExit) as missing:
        subject.parse_args([])

    assert missing.value.code == 2
    args = subject.parse_args(
        [
            "--live-pack",
            "live",
            "--live-verification",
            "live-verification",
            "--portfolio-pack",
            "portfolio",
            "--portfolio-verification",
            "portfolio-verification",
            "--negative-pack",
            "negative",
            "--negative-verification",
            "negative-verification",
            "--behavior-summary",
            "behavior-summary.json",
        ]
    )

    assert args.live_pack == Path("live")
    assert args.live_verification == Path("live-verification")
    assert args.portfolio_pack == Path("portfolio")
    assert args.portfolio_verification == Path("portfolio-verification")
    assert args.negative_pack == Path("negative")
    assert args.negative_verification == Path("negative-verification")
    assert args.behavior_summary == Path("behavior-summary.json")


def test_build_pack_materializes_current_contracts_without_verdict(
    tmp_path: Path,
) -> None:
    live, live_manifest = _source_pack(
        tmp_path,
        "live",
        "artifact_manifest.json",
    )
    portfolio, portfolio_manifest = _source_pack(
        tmp_path,
        "portfolio",
        "evidence_manifest.json",
    )
    negative, negative_manifest = _source_pack(
        tmp_path,
        "negative",
        "artifact_manifest.json",
    )
    live_verification = _verified_file(
        tmp_path / "live-verification",
        pack=live,
        manifest=live_manifest,
        marker="live",
    )
    portfolio_verification = _verified_file(
        tmp_path / "portfolio-verification",
        pack=portfolio,
        manifest=portfolio_manifest,
        marker="portfolio",
    )
    negative_verification = _verified_file(
        tmp_path / "negative-verification",
        pack=negative,
        manifest=negative_manifest,
        marker="negative",
    )
    behavior = _behavior_summary(tmp_path / "behavior" / "summary.json")
    output = tmp_path / "current-pack"

    result = subject.build_current_evidence_pack(
        output=output,
        live_pack=live,
        live_verification=live_verification,
        portfolio_pack=portfolio,
        portfolio_verification=portfolio_verification,
        negative_pack=negative,
        negative_verification=negative_verification,
        behavior_summary=behavior,
    )

    assert result["required_artifact_count"] == 7
    assert result["supporting_payload_count"] == 2
    assert result["manifest_artifact_count"] == 11
    assert result["model_invocations"] == 0
    assert result["verdict_emitted"] is False

    report = json.loads((output / "compiler_report.json").read_text(encoding="utf-8"))
    assert report["compilation_state"] == "MATERIALIZED_UNADJUDICATED"
    assert report["verdict_emitted"] is False
    assert report["canary_report_emitted"] is False
    assert "status" not in report
    builder_source = Path(report["compiler_sources"]["builder"]["path"])
    assert builder_source.name == "f4_current_evidence_builder.py"
    assert builder_source == Path(subject.__file__).resolve()
    assert builder_source != (
        Path(__file__).resolve().parents[1] / "scripts" / "build_f4_current_evidence_pack.py"
    )
    assert "ResearchFactoryCanaryReport" not in {
        item["object_type"] for item in report["required_artifacts"]
    }

    manifest = json.loads((output / "artifact_manifest.json").read_text(encoding="utf-8"))
    listed = {item["relative_path"] for item in manifest["artifacts"]}
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "artifact_manifest.json"
    }
    assert listed == actual
    assert manifest["artifact_count"] == len(actual) == 11
    assert manifest["artifact_set_sha256"] == subject.canonical_sha256(manifest["artifacts"])
    assert all(b"\r\n" not in path.read_bytes() for path in output.rglob("*.json"))
