from __future__ import annotations

from pathlib import Path

import pytest
from scripts import build_f4_snapshot_oci as subject


def test_build_argv_uses_fixed_dockerfile_bases_without_override(tmp_path: Path) -> None:
    config = {
        "image_ref": "xinao/f4-verifier:test",
        "authority_manifest_sha256": "1" * 64,
        "authority_content_sha256": "2" * 64,
        "data_manifest_sha256": "3" * 64,
        "data_content_sha256": "4" * 64,
        "dockerfile_sha256": "5" * 64,
        "contract_writer_sha256": "6" * 64,
        "verifier_lock_sha256": "7" * 64,
    }

    argv = subject._build_argv(config, tmp_path / "authority")

    assert not any("PYTHON_BASE_IMAGE=" in item for item in argv)
    assert not any("UV_BASE_IMAGE=" in item for item in argv)
    assert f"authority={tmp_path / 'authority'}" in argv


def test_fresh_failure_cannot_write_postbuild_verified_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[Path] = []

    def fail() -> dict[str, object]:
        raise subject.OciBuildError("fresh verification failed")

    monkeypatch.setattr(subject, "_fresh_runner_verify", fail)
    monkeypatch.setattr(
        subject,
        "_write_immutable",
        lambda path, value: writes.append(path),
    )

    with pytest.raises(subject.OciBuildError, match="fresh verification failed"):
        subject._write_postbuild_verification(
            config={"image_ref": "xinao/f4-verifier:test"},
            final={"content_sha256": "1" * 64},
            receipt={"content_sha256": "2" * 64},
            receipt_path=tmp_path / "image_build_receipt.json",
            image_id="sha256:" + "3" * 64,
            repo_digests=[],
        )

    assert writes == []


@pytest.mark.parametrize(
    ("argv", "exit_code"),
    [(["--help"], 0), (["--unsupported"], 2)],
)
def test_cli_meta_arguments_never_start_a_build(
    argv: list[str],
    exit_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_verify_build_inputs",
        lambda: pytest.fail("CLI metadata argument started a build"),
    )

    with pytest.raises(SystemExit) as raised:
        subject.main(argv)

    assert raised.value.code == exit_code
