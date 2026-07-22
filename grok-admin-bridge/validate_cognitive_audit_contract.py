#!/usr/bin/env python3
"""Validate the fixed candidate-only cognitive audit envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

EXPECTED_CONTEXT_SCHEMA = "xinao.context_slice_manifest.v1"
EXPECTED_OUTPUT_SCHEMA_ID = (
    "https://xinao.local/schemas/audit_candidate_findings.v1.schema.json"
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return raw, value


def _validate_context(path: Path, expected_sha256: str) -> tuple[dict[str, Any], set[tuple[Any, ...]]]:
    raw, manifest = _object(path, "context manifest")
    if _sha(raw) != expected_sha256:
        raise ValueError("context manifest sha256 mismatch")
    if manifest.get("schema_version") != EXPECTED_CONTEXT_SCHEMA:
        raise ValueError("context manifest schema mismatch")
    if manifest.get("authority") is not False or manifest.get("completion_claim_allowed") is not False:
        raise ValueError("context manifest authority boundary mismatch")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("context manifest sources must be non-empty")

    source_identity: list[dict[str, Any]] = []
    identity_sources: list[dict[str, Any]] = []
    citations: set[tuple[Any, ...]] = set()
    total_content_bytes = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("context source must be an object")
        path_value = str(source.get("path") or "")
        source_sha256 = str(source.get("source_sha256") or "")
        source_bytes = source.get("source_bytes")
        slices = source.get("slices")
        if not path_value or len(source_sha256) != 64 or not isinstance(source_bytes, int):
            raise ValueError("context source identity is incomplete")
        if not isinstance(slices, list) or not slices:
            raise ValueError("context source slices must be non-empty")
        identity_slices: list[dict[str, Any]] = []
        for row in slices:
            if not isinstance(row, dict):
                raise ValueError("context slice must be an object")
            content = str(row.get("content") or "")
            content_raw = content.encode("utf-8")
            line_start = row.get("line_start")
            line_end = row.get("line_end")
            content_sha256 = str(row.get("content_sha256") or "")
            content_bytes = row.get("content_bytes")
            if (
                not isinstance(line_start, int)
                or not isinstance(line_end, int)
                or line_start < 1
                or line_end < line_start
                or content_bytes != len(content_raw)
                or content_sha256 != _sha(content_raw)
            ):
                raise ValueError("context slice identity or content hash mismatch")
            total_content_bytes += len(content_raw)
            citations.add(
                (path_value, source_sha256, line_start, line_end, content_sha256)
            )
            identity_row = dict(row)
            identity_row.pop("content", None)
            identity_slices.append(identity_row)
        source_identity.append(
            {"path": path_value, "sha256": source_sha256, "bytes": source_bytes}
        )
        identity_sources.append(
            {
                "path": path_value,
                "source_sha256": source_sha256,
                "source_bytes": source_bytes,
                "slices": identity_slices,
            }
        )
    if manifest.get("source_manifest_sha256") != _sha(_canonical(source_identity)):
        raise ValueError("context source manifest sha256 mismatch")
    context_identity = {
        "schema_version": "xinao.context_slice_identity.v1",
        "sources": identity_sources,
    }
    if manifest.get("context_sha256") != _sha(_canonical(context_identity)):
        raise ValueError("context identity sha256 mismatch")
    if manifest.get("total_content_bytes") != total_content_bytes:
        raise ValueError("context total_content_bytes mismatch")
    return manifest, citations


def _validate_schema(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw, schema = _object(path, "output schema")
    if _sha(raw) != expected_sha256:
        raise ValueError("output schema sha256 mismatch")
    if schema.get("$id") != EXPECTED_OUTPUT_SCHEMA_ID:
        raise ValueError("cognitive audit requires the canonical candidate-only schema")
    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)
    return schema


def _validate_result(
    result_path: Path,
    schema: dict[str, Any],
    citations: set[tuple[Any, ...]],
) -> None:
    _, result = _object(result_path, "candidate result")
    jsonschema.validators.validator_for(schema)(schema).validate(result)
    expected_fields = {
        "schema_version",
        "verdict",
        "summary",
        "findings",
        "limitations",
        "authority",
        "completion_claim_allowed",
        "repair_authorized",
    }
    if set(result) != expected_fields:
        raise ValueError("candidate result fields do not match the fixed interface")
    if result.get("schema_version") != "xinao.audit_candidate_findings.v1":
        raise ValueError("candidate result schema_version mismatch")
    if result.get("verdict") not in {
        "ACCEPT_HOLD_CANDIDATE",
        "CANDIDATE_FINDINGS",
        "EVIDENCE_INCOMPLETE",
    }:
        raise ValueError("candidate verdict is not candidate-only")
    if (
        result.get("authority") is not False
        or result.get("completion_claim_allowed") is not False
        or result.get("repair_authorized") is not False
    ):
        raise ValueError("candidate result attempted to acquire authority")
    for finding in result.get("findings", []):
        if set(finding) != {
            "finding_id",
            "family",
            "title",
            "claim",
            "severity_claim",
            "evidence_citations",
            "reproduction_conditions",
            "finding_kind",
        }:
            raise ValueError("candidate finding fields do not match the fixed interface")
        if finding.get("finding_kind") != "CANDIDATE_FINDING":
            raise ValueError("finding attempted to escape candidate-only status")
        if not finding.get("evidence_citations") or not finding.get(
            "reproduction_conditions"
        ):
            raise ValueError("candidate finding lacks evidence or reproduction conditions")
        for citation in finding.get("evidence_citations", []):
            key = (
                citation.get("path"),
                citation.get("source_sha256"),
                citation.get("line_start"),
                citation.get("line_end"),
                citation.get("content_sha256"),
            )
            if key not in citations:
                raise ValueError("candidate citation is absent from the embedded evidence package")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--expected-context-sha256", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--expected-schema-sha256", required=True)
    parser.add_argument("--result")
    args = parser.parse_args()

    manifest, citations = _validate_context(
        Path(args.context), args.expected_context_sha256.lower()
    )
    schema = _validate_schema(Path(args.schema), args.expected_schema_sha256.lower())
    if args.result:
        _validate_result(Path(args.result), schema, citations)
    print(
        json.dumps(
            {
                "ok": True,
                "context_sha256": manifest["context_sha256"],
                "citation_count": len(citations),
                "schema_id": schema["$id"],
                "result_validated": bool(args.result),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
