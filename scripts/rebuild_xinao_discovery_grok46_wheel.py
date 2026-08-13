"""Rebuild the installed xinao-discovery wheel with exact Grok 4.6 bindings.

The original source checkout is no longer present on this machine, while the
installed tool remains an active PATH consumer.  This script performs a small,
auditable wheel-to-wheel migration, updates RECORD, and emits a provenance
receipt beside the rebuilt wheel.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path


TARGET_VERSION = "0.1.3+grok46.20260813"
OUTPUT_NAME = f"xinao_discovery-{TARGET_VERSION}-py3-none-any.whl"
PATCHES = {
    "xinao/policy/agent_admission.py": (
        (b'"grok-4.5"', b'"grok-4.6"'),
    ),
    "xinao/science/researcher_result_adapter.py": (
        (b"grok-4.5-build", b"grok-4.6-build"),
        (b"grok-4.5", b"grok-4.6"),
    ),
    "xinao/foundation/assessment.py": (
        (b'"grok-4.5"', b'"grok-4.6"'),
    ),
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_digest(raw: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode("ascii")


def _record_bytes(entries: dict[str, bytes], record_path: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(entries):
        writer.writerow((name, _record_digest(entries[name]), len(entries[name])))
    writer.writerow((record_path, "", ""))
    return output.getvalue().encode("utf-8")


def rebuild(source: Path, output_dir: Path) -> tuple[Path, Path]:
    source = source.resolve()
    if not source.is_file() or source.suffix.casefold() != ".whl":
        raise ValueError(f"source wheel is unavailable: {source}")

    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        dist_roots = {
            name.split("/", 1)[0]
            for name in names
            if re.fullmatch(r"xinao_discovery-[^/]+\.dist-info/.+", name)
        }
        if len(dist_roots) != 1:
            raise ValueError("source wheel must contain one xinao_discovery dist-info root")
        old_dist = next(iter(dist_roots))
        new_dist = f"xinao_discovery-{TARGET_VERSION}.dist-info"
        entries: dict[str, bytes] = {}
        for name in names:
            if name.endswith("/") or name == f"{old_dist}/RECORD":
                continue
            new_name = new_dist + name[len(old_dist) :] if name.startswith(old_dist + "/") else name
            entries[new_name] = archive.read(name)

    applied: dict[str, list[dict[str, object]]] = {}
    for name, replacements in PATCHES.items():
        raw = entries.get(name)
        if raw is None:
            raise ValueError(f"required wheel member is missing: {name}")
        applied[name] = []
        for before, after in replacements:
            count = raw.count(before)
            if count < 1:
                raise ValueError(f"expected binding is absent from {name}: {before!r}")
            raw = raw.replace(before, after)
            applied[name].append(
                {
                    "before": before.decode("ascii"),
                    "after": after.decode("ascii"),
                    "count": count,
                }
            )
        entries[name] = raw

    metadata_path = f"{new_dist}/METADATA"
    metadata = entries.get(metadata_path)
    if metadata is None:
        raise ValueError("wheel METADATA is missing")
    updated_metadata, count = re.subn(
        rb"(?m)^Version: 0\.1\.3$",
        f"Version: {TARGET_VERSION}".encode("ascii"),
        metadata,
    )
    if count != 1:
        raise ValueError("wheel METADATA version is not the expected 0.1.3")
    entries[metadata_path] = updated_metadata

    forbidden = (b"grok-4.5", b"grok-composer-2.5-fast")
    leaks = [
        name
        for name, raw in entries.items()
        if name.startswith("xinao/") and name.endswith(".py") and any(value in raw for value in forbidden)
    ]
    if leaks:
        raise ValueError(f"retired Grok bindings remain in rebuilt wheel: {leaks}")

    record_path = f"{new_dist}/RECORD"
    record = _record_bytes(entries, record_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / OUTPUT_NAME
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 13, 13, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entries[name])
        info = zipfile.ZipInfo(record_path, date_time=(2026, 8, 13, 13, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, record)

    receipt = output.with_suffix(".receipt.json")
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "xinao.discovery.local_grok46_wheel_rebuild.v1",
                "source_path": str(source),
                "source_sha256": _sha256(source.read_bytes()),
                "output_path": str(output),
                "output_sha256": _sha256(output.read_bytes()),
                "package_version": TARGET_VERSION,
                "patches": applied,
                "retired_active_bindings_remaining": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output, receipt = rebuild(args.source, args.output_dir)
    print(json.dumps({"wheel": str(output), "receipt": str(receipt)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
