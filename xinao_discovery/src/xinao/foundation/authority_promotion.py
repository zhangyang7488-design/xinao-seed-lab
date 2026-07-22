"""Atomic promotion for reviewed Foundation authority generations."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import portalocker

from xinao.foundation import assertion_verifier_registry as registry
from xinao.foundation.authority_generation import (
    generation_reference,
    validate_authority_generation,
)
from xinao.foundation.closure import resolve_foundation_profile
from xinao.foundation.foundation_implementation_model import implementation_model_projection

DEFAULT_RECEIPT_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\evidence\foundation_authority_promotions")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _projection_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _validate_as_canonical(path: Path) -> dict[str, Any]:
    previous = registry.CANONICAL_PROJECTION_PATH
    registry.CANONICAL_PROJECTION_PATH = path
    try:
        return resolve_foundation_profile(path)
    finally:
        registry.CANONICAL_PROJECTION_PATH = previous


def promote_authority_generation(
    *,
    projection_path: Path,
    generation_manifest_path: Path,
    receipt_root: Path = DEFAULT_RECEIPT_ROOT,
    run_pytest: bool = True,
) -> dict[str, Any]:
    """CAS-promote one generation and roll back on any consumer failure."""

    projection_path = projection_path.resolve()
    generation = validate_authority_generation(generation_manifest_path)
    manifest = generation["manifest"]
    binding = generation["binding"]
    reference = generation_reference(generation_manifest_path)
    lock_path = projection_path.with_name(f".{projection_path.name}.foundation-promotion.lock")
    prior_bytes = projection_path.read_bytes()
    expected_prior = manifest["expected_previous_projection_sha256"]
    if _sha256_bytes(prior_bytes) != expected_prior:
        raise RuntimeError("FOUNDATION_PROMOTION_CAS_MISMATCH")

    with portalocker.Lock(
        str(lock_path),
        mode="a+b",
        timeout=30,
        check_interval=0.05,
        flags=portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
    ):
        current_bytes = projection_path.read_bytes()
        if _sha256_bytes(current_bytes) != expected_prior:
            raise RuntimeError("FOUNDATION_PROMOTION_CAS_MISMATCH_AFTER_LOCK")
        current = json.loads(current_bytes.decode("utf-8-sig"))
        if not isinstance(current, dict) or not isinstance(current.get("authority"), dict):
            raise RuntimeError("FOUNDATION_PROMOTION_PROJECTION_INVALID")

        candidate = deepcopy(current)
        candidate["authority"]["foundation_generation"] = reference
        candidate["runtime_cutover"] = implementation_model_projection(binding)
        candidate_bytes = _projection_bytes(candidate)
        candidate_path = projection_path.with_name(
            f".{projection_path.name}.{manifest['content_sha256']}.candidate"
        )
        _atomic_write(candidate_path, candidate_bytes)
        try:
            preflight = _validate_as_canonical(candidate_path)
            if preflight.get("status") != "READY" or preflight.get("blockers"):
                raise RuntimeError(
                    "FOUNDATION_PROMOTION_PREFLIGHT_FAILED:"
                    + ",".join(preflight.get("blockers") or [])
                )

            _atomic_write(projection_path, candidate_bytes)
            try:
                postflight = _validate_as_canonical(projection_path)
                if postflight.get("status") != "READY" or postflight.get("blockers"):
                    raise RuntimeError(
                        "FOUNDATION_PROMOTION_POSTFLIGHT_FAILED:"
                        + ",".join(postflight.get("blockers") or [])
                    )
                test_result: dict[str, Any] = {"performed": False}
                if run_pytest:
                    repo_root = Path(__file__).resolve().parents[4]
                    target = (
                        repo_root
                        / "xinao_discovery"
                        / "tests"
                        / "unit"
                        / "foundation"
                        / "test_authority_profile_cutover.py"
                    )
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "pytest",
                            f"{target}::test_current_projection_binds_reviewed_generation_and_exact_model",
                            "-q",
                        ],
                        cwd=repo_root,
                        capture_output=True,
                        check=False,
                        encoding="utf-8",
                        timeout=180,
                    )
                    test_result = {
                        "performed": True,
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout[-4000:],
                        "stderr": completed.stderr[-4000:],
                    }
                    if completed.returncode != 0:
                        raise RuntimeError("FOUNDATION_PROMOTION_CONSUMER_TEST_FAILED")
            except BaseException as exc:
                _atomic_write(projection_path, current_bytes)
                rollback = _validate_as_canonical(projection_path)
                if _sha256_bytes(projection_path.read_bytes()) != expected_prior:
                    raise RuntimeError("FOUNDATION_PROMOTION_ROLLBACK_WRITE_FAILED") from exc
                if current.get("authority", {}).get("foundation_generation") and (
                    rollback.get("status") != "READY"
                ):
                    raise RuntimeError("FOUNDATION_PROMOTION_ROLLBACK_CONSUMER_FAILED") from exc
                raise
        finally:
            candidate_path.unlink(missing_ok=True)

    receipt_core = {
        "schema_version": "xinao.foundation_authority_promotion_receipt.v1",
        "status": "EFFECT_VERIFIED",
        "generation_manifest_path": str(generation_manifest_path.resolve()),
        "generation_manifest_sha256": reference["manifest_sha256"],
        "generation_content_sha256": reference["generation_content_sha256"],
        "previous_projection_sha256": expected_prior,
        "applied_projection_sha256": _sha256_bytes(projection_path.read_bytes()),
        "runtime_cutover": candidate["runtime_cutover"],
        "preflight_status": preflight["status"],
        "postflight_status": postflight["status"],
        "consumer_test": test_result,
        "formal_research_remains_closed": True,
    }
    receipt = {
        **receipt_core,
        "content_sha256": hashlib.sha256(
            json.dumps(
                receipt_core, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        ).hexdigest(),
    }
    receipt_path = receipt_root.resolve() / f"{reference['generation_content_sha256']}.json"
    _atomic_write(receipt_path, _projection_bytes(receipt))
    return {**receipt, "receipt_path": str(receipt_path)}


__all__ = ["DEFAULT_RECEIPT_ROOT", "promote_authority_generation"]
