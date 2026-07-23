"""Prepare one immutable preregistration for the provider-neutral G4 batch seam."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
if str(XINAO_SRC) not in sys.path:
    sys.path.insert(0, str(XINAO_SRC))

from xinao.canonical import format_utc  # noqa: E402
from xinao.capability.g4_preregistration import (  # noqa: E402
    TERMINAL_READY,
    prepare_g4_preregistration,
)


def _write_json_exclusive(path: Path, payload: Any) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _package_root(path: Path) -> Path:
    target = path.resolve()
    runtime = Path(
        os.environ.get("XINAO_RESEARCH_RUNTIME_ROOT", r"D:\XINAO_RESEARCH_RUNTIME")
    ).resolve()
    try:
        target.relative_to(runtime)
    except ValueError as exc:
        raise SystemExit("package root must remain under D:\\XINAO_RESEARCH_RUNTIME") from exc
    return target


def publish_preparation_package(
    *,
    package_root: Path,
    result: dict[str, Any],
    extra_files: Mapping[str, bytes] | None = None,
) -> list[str]:
    target = package_root.resolve()
    if target.exists():
        raise FileExistsError(f"package root already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.",
            dir=target.parent,
        )
    )
    published: list[str] = []
    try:
        receipt_path = temp_root / "preparation_receipt.v1.json"
        _write_json_exclusive(receipt_path, result["receipt"])
        published.append(receipt_path.name)
        if result["terminal"] == TERMINAL_READY:
            request_path = temp_root / "request.v1.json"
            preregistration_path = temp_root / "preregistration.v1.json"
            ledger_path = temp_root / "obligation_ledger.v1.json"
            batch_path = temp_root / "batch_manifest.v1.json"
            _write_json_exclusive(request_path, result["request"])
            _write_json_exclusive(preregistration_path, result["preregistration"])
            _write_json_exclusive(ledger_path, result["obligation_ledger"])
            _write_json_exclusive(batch_path, result["batch_manifest"])
            published.extend(
                (
                    request_path.name,
                    preregistration_path.name,
                    ledger_path.name,
                    batch_path.name,
                )
            )
        for relative_name, payload in sorted((extra_files or {}).items()):
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"extra file must remain package-relative: {relative_name}")
            extra_path = temp_root / relative_path
            _write_bytes_exclusive(extra_path, payload)
            if hashlib.sha256(extra_path.read_bytes()).digest() != hashlib.sha256(payload).digest():
                raise OSError(f"staged extra file hash drifted: {relative_name}")
            published.append(relative_path.as_posix())
        os.rename(temp_root, target)
    except BaseException:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    return published


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument(
        "--known-prior-outcome-receipt",
        action="append",
        default=[],
        help="Known outcome receipt for this batch; any value forces HOLD.",
    )
    parser.add_argument(
        "--forbidden-suite-commitment",
        action="append",
        default=[],
        help="Previously outcome-exposed suite commitment that this batch must not reuse.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    package_root = _package_root(args.package_root)
    now = datetime.now(UTC)
    prepared_at_utc = format_utc(now.replace(microsecond=(now.microsecond // 1000) * 1000))
    result = prepare_g4_preregistration(
        request,
        prepared_at_utc=prepared_at_utc,
        known_prior_outcome_receipts=args.known_prior_outcome_receipt,
        forbidden_suite_commitments=args.forbidden_suite_commitment,
    )
    published = publish_preparation_package(
        package_root=package_root,
        result=result,
    )
    summary = {
        "terminal": result["terminal"],
        "batch_id": result["receipt"]["batch_id"],
        "package_root": str(package_root),
        "published": published,
        "outcome_accessed": False,
        "authority": False,
        "g4_closed": False,
        "g4_full": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if result["terminal"] == TERMINAL_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
