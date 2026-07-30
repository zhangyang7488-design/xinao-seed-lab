"""Formally selected replacement verifier for tool-glue projection bindings.

Closes the real consumer boundary that the live Situation Island selftest still
misses: ``software_foundation.version`` must be derived from the same authority
leaf as ``software_foundation.sha256``, and the SI operational updater must be a
same-byte projection of the package-canonical updater.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xinao.tool_glue.canonical_paths import (
    DEFAULT_MAINTENANCE_MAP_PATH,
    DEFAULT_SCIENCE_PROJECTION_PATH,
    CanonicalPathError,
    assert_same_bytes,
    discover_canonical_updater_path,
    operational_updater_path,
    sha256_file,
)
from xinao.tool_glue.publication import (
    DEFAULT_AUTHORITY_PATH,
    VERIFIED,
    PublicationError,
    _document_version,
    _normalized_sha256,
    _read_object,
)

RECEIPT_SCHEMA = "xinao.tool_glue_projection_binding_verification.v1"
READY_SENTINEL = "SENTINEL:XINAO_TOOL_GLUE_PROJECTION_BINDING_READY_V1"


def _fail(code: str, message: str, *, checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "FAILED",
        "ready": False,
        "sentinel": READY_SENTINEL,
        "error_code": code,
        "error": message,
        "failed": [code],
        "checks": checks,
        "completion_claim_allowed": False,
    }


def verify_projection_bindings(
    *,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    science_projection_path: Path = DEFAULT_SCIENCE_PROJECTION_PATH,
    maintenance_map_path: Path = DEFAULT_MAINTENANCE_MAP_PATH,
    island_root: Path | None = None,
    expected_sha256: str | None = None,
    expected_version: str | None = None,
    require_map_identity: bool = True,
) -> dict[str, Any]:
    """Verify version+sha authority binding and operational updater identity."""

    checks: list[dict[str, Any]] = []
    authority_path = authority_path.resolve()
    science_projection_path = science_projection_path.resolve()
    maintenance_map_path = maintenance_map_path.resolve()

    if not authority_path.is_file():
        return _fail(
            "AUTHORITY_MISSING",
            f"authority document is missing: {authority_path}",
            checks=checks,
        )
    authority_raw = authority_path.read_bytes()
    authority_digest = sha256_file(authority_path)
    try:
        authority_version = _document_version(authority_raw)
    except PublicationError as exc:
        return _fail(exc.code, str(exc), checks=checks)

    if expected_sha256 is not None:
        wanted = _normalized_sha256(expected_sha256, "expected_sha256")
        ok = authority_digest == wanted
        checks.append(
            {
                "name": "authority_sha256_pin",
                "ok": ok,
                "expected": wanted,
                "observed": authority_digest,
            }
        )
        if not ok:
            return _fail(
                "AUTHORITY_SHA256_PIN_MISMATCH",
                "authority sha256 does not match expected pin",
                checks=checks,
            )
    else:
        checks.append(
            {
                "name": "authority_sha256_pin",
                "ok": True,
                "expected": None,
                "observed": authority_digest,
            }
        )

    if expected_version is not None:
        ok = authority_version == expected_version
        checks.append(
            {
                "name": "authority_version_pin",
                "ok": ok,
                "expected": expected_version,
                "observed": authority_version,
            }
        )
        if not ok:
            return _fail(
                "AUTHORITY_VERSION_PIN_MISMATCH",
                "authority version does not match expected pin",
                checks=checks,
            )
    else:
        checks.append(
            {
                "name": "authority_version_pin",
                "ok": True,
                "expected": None,
                "observed": authority_version,
            }
        )

    if not science_projection_path.is_file():
        return _fail(
            "SCIENCE_PROJECTION_MISSING",
            f"science projection is missing: {science_projection_path}",
            checks=checks,
        )
    try:
        projection = _read_object(science_projection_path)
    except PublicationError as exc:
        return _fail(exc.code, str(exc), checks=checks)
    software = projection.get("software_foundation")
    if not isinstance(software, dict):
        return _fail(
            "SOFTWARE_FOUNDATION_MISSING",
            "science projection lacks software_foundation object",
            checks=checks,
        )

    observed_path = str(software.get("path") or "")
    observed_sha = str(software.get("sha256") or "").lower()
    observed_version = software.get("version")
    path_ok = bool(observed_path) and Path(observed_path).resolve() == authority_path.resolve()
    checks.append(
        {
            "name": "software_foundation_path",
            "ok": path_ok,
            "expected": str(authority_path),
            "observed": observed_path,
        }
    )
    if not path_ok:
        return _fail(
            "SOFTWARE_FOUNDATION_PATH_MISMATCH",
            "software_foundation.path does not bind the authority leaf",
            checks=checks,
        )

    sha_ok = observed_sha == authority_digest
    checks.append(
        {
            "name": "software_foundation_sha256",
            "ok": sha_ok,
            "expected": authority_digest,
            "observed": observed_sha,
        }
    )
    if not sha_ok:
        return _fail(
            "SOFTWARE_FOUNDATION_SHA256_MISMATCH",
            "software_foundation.sha256 does not match authority bytes",
            checks=checks,
        )

    version_ok = observed_version == authority_version
    checks.append(
        {
            "name": "software_foundation_version",
            "ok": version_ok,
            "expected": authority_version,
            "observed": observed_version,
        }
    )
    if not version_ok:
        return _fail(
            "SOFTWARE_FOUNDATION_VERSION_MISMATCH",
            "software_foundation.version missing or not bound to authority version line",
            checks=checks,
        )

    try:
        canonical = discover_canonical_updater_path()
    except CanonicalPathError as exc:
        return _fail(exc.code, str(exc), checks=checks)
    operational = operational_updater_path(island_root=island_root)
    try:
        updater_digest = assert_same_bytes(
            operational,
            canonical,
            code="OPERATIONAL_UPDATER_DRIFT",
            message="operational updater must match package-canonical bytes",
        )
        checks.append(
            {
                "name": "operational_updater_same_byte",
                "ok": True,
                "expected": updater_digest,
                "observed": updater_digest,
                "canonical_path": str(canonical),
                "operational_path": str(operational),
            }
        )
    except CanonicalPathError as exc:
        checks.append(
            {
                "name": "operational_updater_same_byte",
                "ok": False,
                "expected": sha256_file(canonical) if canonical.is_file() else None,
                "observed": sha256_file(operational) if operational.is_file() else None,
                "canonical_path": str(canonical),
                "operational_path": str(operational),
            }
        )
        return _fail(exc.code, str(exc), checks=checks)

    if require_map_identity:
        if not maintenance_map_path.is_file():
            return _fail(
                "MAINTENANCE_MAP_MISSING",
                f"maintenance map is missing: {maintenance_map_path}",
                checks=checks,
            )
        try:
            maintenance_map = _read_object(maintenance_map_path)
        except PublicationError as exc:
            return _fail(exc.code, str(exc), checks=checks)
        sources = maintenance_map.get("sources")
        if not isinstance(sources, list):
            return _fail(
                "MAINTENANCE_MAP_INVALID",
                "maintenance map sources must be a list",
                checks=checks,
            )
        catalog_updater = next(
            (
                item
                for item in sources
                if isinstance(item, dict) and item.get("id") == "catalog_updater"
            ),
            None,
        )
        if not isinstance(catalog_updater, dict):
            return _fail(
                "CATALOG_UPDATER_MAP_ENTRY_MISSING",
                "maintenance map lacks catalog_updater source",
                checks=checks,
            )
        map_path = Path(str(catalog_updater.get("path") or ""))
        map_path_ok = map_path.is_file() and map_path.resolve() == operational.resolve()
        checks.append(
            {
                "name": "map_catalog_updater_path",
                "ok": map_path_ok,
                "expected": str(operational),
                "observed": str(catalog_updater.get("path")),
            }
        )
        if not map_path_ok:
            return _fail(
                "MAP_CATALOG_UPDATER_PATH_MISMATCH",
                "maintenance map catalog_updater path is not the SI operational updater",
                checks=checks,
            )
        map_sha = str(catalog_updater.get("sha256") or "").lower()
        map_sha_ok = map_sha == updater_digest
        checks.append(
            {
                "name": "map_catalog_updater_sha256",
                "ok": map_sha_ok,
                "expected": updater_digest,
                "observed": map_sha,
            }
        )
        if not map_sha_ok:
            return _fail(
                "MAP_CATALOG_UPDATER_SHA_MISMATCH",
                "maintenance map catalog_updater sha diverges from operational bytes",
                checks=checks,
            )

    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": VERIFIED,
        "ready": True,
        "sentinel": READY_SENTINEL,
        "failed": [],
        "checks": checks,
        "authority_path": str(authority_path),
        "authority_sha256": authority_digest,
        "authority_version": authority_version,
        "software_foundation_version": authority_version,
        "software_foundation_sha256": authority_digest,
        "canonical_updater_path": str(canonical),
        "operational_updater_path": str(operational),
        "operational_updater_sha256": updater_digest,
        "completion_claim_allowed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-path", type=Path, default=DEFAULT_AUTHORITY_PATH)
    parser.add_argument(
        "--science-projection-path",
        type=Path,
        default=DEFAULT_SCIENCE_PROJECTION_PATH,
    )
    parser.add_argument(
        "--maintenance-map-path",
        type=Path,
        default=DEFAULT_MAINTENANCE_MAP_PATH,
    )
    parser.add_argument("--island-root", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-version")
    parser.add_argument(
        "--skip-map-identity",
        action="store_true",
        help="skip maintenance-map catalog_updater identity (fixture-only)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = verify_projection_bindings(
        authority_path=args.authority_path,
        science_projection_path=args.science_projection_path,
        maintenance_map_path=args.maintenance_map_path,
        island_root=args.island_root,
        expected_sha256=args.expected_sha256,
        expected_version=args.expected_version,
        require_map_identity=not args.skip_map_identity,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt.get("ready") is True and receipt.get("failed") == [] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "READY_SENTINEL",
    "RECEIPT_SCHEMA",
    "main",
    "verify_projection_bindings",
]
