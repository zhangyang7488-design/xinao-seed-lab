"""Fixed fresh-process runner for canonical F1-F4 assertion actuals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_verifier_registry import (
    CanonicalVerifierError,
    canonical_python_executable,
    load_canonical_actuals_callable,
)

PROTOCOL_VERSION = "xinao.assertion_bundle_protocol.v2"
BUNDLE_SCHEMA_VERSION = "xinao.assertion_actual_bundle.v2"
REQUEST_SCHEMA_VERSION = "xinao.assertion_request.v2"
_REQUEST_KEYS = {
    "schema_version",
    "protocol_version",
    "block_id",
    "assertion_ids",
    "input_evidence",
    "input_hashes",
    "artifacts",
    "compiler_code_sha256",
    "compiler_config_sha256",
}


class AssertionBundleRunnerError(ValueError):
    """Raised when a request or canonical verifier violates the protocol."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_request(request: Mapping[str, Any], *, block_id: str) -> dict[str, Any]:
    value = dict(request)
    if set(value) != _REQUEST_KEYS:
        raise AssertionBundleRunnerError(
            "assertion request keys are not exact: "
            f"missing={sorted(_REQUEST_KEYS - set(value))}, "
            f"extra={sorted(set(value) - _REQUEST_KEYS)}"
        )
    if value.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise AssertionBundleRunnerError("assertion request schema is invalid")
    if value.get("protocol_version") != PROTOCOL_VERSION:
        raise AssertionBundleRunnerError("assertion request protocol is invalid")
    if value.get("block_id") != block_id:
        raise AssertionBundleRunnerError("assertion request block identity is invalid")
    assertion_ids = value.get("assertion_ids")
    if (
        not isinstance(assertion_ids, Sequence)
        or isinstance(assertion_ids, (str, bytes, bytearray))
        or not assertion_ids
        or not all(isinstance(item, str) and item for item in assertion_ids)
        or list(assertion_ids) != sorted(set(assertion_ids))
    ):
        raise AssertionBundleRunnerError("assertion request IDs are invalid")
    try:
        return json.loads(canonical_dumps(value))
    except (TypeError, ValueError) as exc:
        raise AssertionBundleRunnerError("assertion request is not canonical JSON") from exc


def build_assertion_request_v2(
    *,
    block_id: str,
    assertion_ids: Sequence[str],
    input_refs: Mapping[str, Mapping[str, Any]],
    input_hashes: Mapping[str, str],
    materials: Mapping[str, Mapping[str, Any]],
    compiler_code_sha256: str,
    compiler_config_sha256: str,
) -> dict[str, Any]:
    """Create the only expectation-free request accepted by canonical verifiers."""

    staged_envelopes = {
        artifact_type: {
            "artifact_type": artifact_type,
            "version": material["version"],
            "input_hashes": dict(input_hashes),
            "code_hash": compiler_code_sha256,
            "config_hash": compiler_config_sha256,
            "source_ref": material["source_ref"],
            "payload": material["payload"],
            "payload_sha256": canonical_sha256(material["payload"]),
        }
        for artifact_type, material in sorted(materials.items())
    }
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "block_id": block_id,
        "assertion_ids": sorted(assertion_ids),
        "input_evidence": {key: dict(input_refs[key]) for key in sorted(input_refs)},
        "input_hashes": {key: input_hashes[key] for key in sorted(input_hashes)},
        "artifacts": {
            artifact_type: {
                "staged_envelope": staged_envelopes[artifact_type],
                "staged_envelope_content_sha256": canonical_sha256(
                    staged_envelopes[artifact_type]
                ),
            }
            for artifact_type in sorted(staged_envelopes)
        },
        "compiler_code_sha256": compiler_code_sha256,
        "compiler_config_sha256": compiler_config_sha256,
    }
    return _canonical_request(request, block_id=block_id)


def build_bundle_bytes_v2(*, request: Mapping[str, Any], block_id: str) -> bytes:
    """Run the registry-selected verifier and return canonical actuals bytes."""

    request_object = _canonical_request(request, block_id=block_id)
    try:
        entry, verifier = load_canonical_actuals_callable(block_id)
    except CanonicalVerifierError as exc:
        raise AssertionBundleRunnerError(str(exc)) from exc
    actuals = verifier(json.loads(canonical_dumps(request_object)))
    if not isinstance(actuals, Mapping):
        raise AssertionBundleRunnerError("canonical verifier must return an assertion mapping")
    assertion_ids = request_object["assertion_ids"]
    if set(actuals) != set(assertion_ids):
        raise AssertionBundleRunnerError(
            "canonical verifier assertion IDs do not match request: "
            f"missing={sorted(set(assertion_ids) - set(actuals))}, "
            f"extra={sorted(set(actuals) - set(assertion_ids))}"
        )
    normalized_actuals = {key: actuals[key] for key in sorted(actuals)}
    try:
        canonical_dumps(normalized_actuals)
    except (TypeError, ValueError) as exc:
        raise AssertionBundleRunnerError(
            "canonical verifier actuals are not canonical JSON values"
        ) from exc
    actual_content_hashes = {
        assertion_id: canonical_sha256(
            {"assertion_id": assertion_id, "actual": normalized_actuals[assertion_id]}
        )
        for assertion_id in sorted(normalized_actuals)
    }
    core = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "block_id": block_id,
        "checker_id": entry.checker_id,
        "checker_version": entry.checker_version,
        "request_sha256": canonical_sha256(request_object),
        "entrypoint": {
            "module_name": entry.module_name,
            "source_path": str(entry.source_path),
            "source_sha256": entry.source_sha256,
            "checker_id": entry.checker_id,
            "checker_version": entry.checker_version,
        },
        "assertion_actuals": normalized_actuals,
        "assertion_actual_content_sha256": actual_content_hashes,
    }
    return canonical_dumps({**core, "content_sha256": canonical_sha256(core)})


def _fresh_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON")
    }


def run_canonical_bundle_fresh(
    *, request_path: Path, block_id: str, output_path: Path, timeout: int = 180
) -> dict[str, Any]:
    """Execute one block in the fixed isolated project interpreter."""

    python = canonical_python_executable()
    project_root = python.parents[2]
    completed = subprocess.run(
        [
            str(python),
            "-I",
            "-m",
            "xinao.foundation.assertion_bundle_runner",
            "--request",
            str(request_path.resolve()),
            "--block-id",
            block_id,
            "--output",
            str(output_path.resolve()),
        ],
        capture_output=True,
        check=False,
        cwd=project_root,
        encoding="utf-8",
        env=_fresh_environment(),
        timeout=timeout,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise AssertionBundleRunnerError(
            "fresh canonical assertion runner failed: "
            f"exit={completed.returncode}, stderr={completed.stderr.strip()!r}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionBundleRunnerError("fresh canonical runner result is invalid") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise AssertionBundleRunnerError("fresh canonical runner did not attest success")
    return result


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--block-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise AssertionBundleRunnerError("assertion request must be an object")
        bundle_bytes = build_bundle_bytes_v2(request=request, block_id=args.block_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(bundle_bytes)
    except (
        AssertionBundleRunnerError,
        CanonicalVerifierError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "sha256": _sha256_bytes(bundle_bytes)}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through fresh process
    raise SystemExit(main())


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "PROTOCOL_VERSION",
    "REQUEST_SCHEMA_VERSION",
    "AssertionBundleRunnerError",
    "build_assertion_request_v2",
    "build_bundle_bytes_v2",
    "run_canonical_bundle_fresh",
]
