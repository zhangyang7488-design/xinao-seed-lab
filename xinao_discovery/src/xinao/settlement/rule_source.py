"""Versioned provenance for user-authorized target-market rule conventions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xinao.canonical import canonical_sha256

SOURCE_TYPE = "TARGET_MARKET_PAGE_SNAPSHOT"
SOURCE_BUNDLE_REF = "xinao-target-market-page-snapshot.2026-05-12.v1"
SOURCE_BUNDLE_HASH = "637c42b85a74a16d17d3ebcc0ea3e124c098b7626af9f0a275be424fe99ddd11"
AUTHORITY_BASIS = "USER_CONFIRMED_LOCAL_SNAPSHOT"
DEFAULT_SOURCE_BUNDLE_PATH = Path(
    r"C:\Users\xx363\Desktop\历史备用 不动\旧主线\新澳数据包"
    r"\新澳盘口_完整映射数据包_v1"
)

SemanticStatus = Literal["EXPLICIT_PAGE", "RESEARCH_CONVENTION"]


class SemanticClaim(BaseModel):
    """One claim with its evidence class kept explicit and non-interchangeable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_ref: str = Field(min_length=1)
    semantic_status: SemanticStatus
    statement: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)


class TargetMarketSnapshotRuleVersion(BaseModel):
    """Common flattened source identity required on every admitted RuleVersion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["TARGET_MARKET_PAGE_SNAPSHOT"] = SOURCE_TYPE
    source_bundle_ref: Literal["xinao-target-market-page-snapshot.2026-05-12.v1"] = (
        SOURCE_BUNDLE_REF
    )
    source_bundle_hash: Literal[
        "637c42b85a74a16d17d3ebcc0ea3e124c098b7626af9f0a275be424fe99ddd11"
    ] = SOURCE_BUNDLE_HASH
    source_bundle_hash_basis: Literal["SHA256_OF_MANIFEST_FILE"] = "SHA256_OF_MANIFEST_FILE"
    authority_basis: Literal["USER_CONFIRMED_LOCAL_SNAPSHOT"] = AUTHORITY_BASIS
    authority_confirmation_ref: Literal["user-confirmation.2026-07-14"] = (
        "user-confirmation.2026-07-14"
    )
    semantic_status: tuple[SemanticStatus, ...] = (
        "EXPLICIT_PAGE",
        "RESEARCH_CONVENTION",
    )
    claims: tuple[SemanticClaim, ...] = Field(min_length=1)

    @field_validator("semantic_status")
    @classmethod
    def require_both_semantic_classes(
        cls, value: tuple[SemanticStatus, ...]
    ) -> tuple[SemanticStatus, ...]:
        if value != ("EXPLICIT_PAGE", "RESEARCH_CONVENTION"):
            raise ValueError("semantic_status must preserve both ordered evidence classes")
        return value

    @model_validator(mode="after")
    def require_claims_in_both_classes(self) -> TargetMarketSnapshotRuleVersion:
        observed = {claim.semantic_status for claim in self.claims}
        if observed != set(self.semantic_status):
            raise ValueError("claims must include EXPLICIT_PAGE and RESEARCH_CONVENTION")
        claim_refs = [claim.claim_ref for claim in self.claims]
        if len(claim_refs) != len(set(claim_refs)):
            raise ValueError("claim_ref values must be unique")
        return self


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_source_bundle(
    *,
    source_root: Path = DEFAULT_SOURCE_BUNDLE_PATH,
    expected_manifest_sha256: str = SOURCE_BUNDLE_HASH,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Recompute the manifest binding and every manifest-listed file."""

    manifest_path = source_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"source bundle manifest is missing: {manifest_path}")
    manifest_sha256 = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    listed = manifest.get("files")
    if not isinstance(listed, list):
        raise ValueError("manifest files must be a list")

    checks: list[dict[str, Any]] = []
    listed_paths: set[str] = set()
    for raw in listed:
        if not isinstance(raw, dict):
            raise ValueError("manifest file entry must be an object")
        relative_path = str(raw.get("relative_path", ""))
        if not relative_path or relative_path in listed_paths:
            raise ValueError("manifest relative paths must be non-empty and unique")
        listed_paths.add(relative_path)
        candidate = source_root / Path(relative_path)
        exists = candidate.is_file()
        actual_sha256 = sha256_file(candidate) if exists else None
        actual_size = candidate.stat().st_size if exists else None
        expected_sha256 = str(raw.get("sha256", ""))
        expected_size = raw.get("size_bytes")
        checks.append(
            {
                "relative_path": relative_path,
                "exists": exists,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "hash_ok": exists and actual_sha256 == expected_sha256,
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
                "size_ok": exists and actual_size == expected_size,
            }
        )

    actual_paths = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    expected_paths = listed_paths | {"manifest.json"}
    failures = [check for check in checks if not check["hash_ok"] or not check["size_ok"]]
    body: dict[str, Any] = {
        "schema_version": "xinao.target_market_source_bundle_verification.v1",
        "source_type": SOURCE_TYPE,
        "source_bundle_ref": SOURCE_BUNDLE_REF,
        "source_bundle_path": str(source_root),
        "source_bundle_hash": manifest_sha256,
        "source_bundle_hash_basis": "SHA256_OF_MANIFEST_FILE",
        "expected_source_bundle_hash": expected_manifest_sha256,
        "authority_basis": AUTHORITY_BASIS,
        "manifest_entry_count": len(checks),
        "manifest_listed_file_count": len(checks),
        "manifest_file_count": 1,
        "expected_actual_file_count": len(checks) + 1,
        "actual_file_count": len(actual_paths),
        "actual_count_includes_manifest_file": True,
        "manifest_hash_ok": manifest_sha256 == expected_manifest_sha256,
        "listed_files_ok": not failures,
        "file_set_ok": actual_paths == expected_paths,
        "unexpected_files": sorted(actual_paths - expected_paths),
        "missing_files": sorted(expected_paths - actual_paths),
        "failures": failures,
    }
    body["ok"] = bool(body["manifest_hash_ok"] and body["listed_files_ok"] and body["file_set_ok"])
    body["content_hash"] = canonical_sha256(body)
    if output_path is not None:
        _write_atomic(output_path, body)
    return body
