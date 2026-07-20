#!/usr/bin/env python3
"""Validate one neutral worker DAG and any A/B envelopes bound to its bytes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_worker_package_batch import (  # noqa: E402
    PathResolver,
    build_path_resolver,
)
from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    plan_package_frontier,
    validate_dispatch_envelope,
    validate_package_batch_manifest,
)


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _json_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def validate_manifest_and_envelopes(
    manifest: Mapping[str, object],
    envelopes: Sequence[Mapping[str, object]] = (),
    *,
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Validate the canonical graph before checking leg envelopes against its frontier."""

    validated = validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    frontier = plan_package_frontier(validated, path_resolver=path_resolver)
    admitted = list(frontier["admitted"])
    worker_ids = [
        str(row["package_id"])
        for row in admitted
        if row["candidate_only"] is True and row["execution_seal_ready"] is True
    ]
    owner_ids = [str(row["package_id"]) for row in admitted if row["candidate_only"] is False]
    unresolved_pin_ids = [
        str(row["package_id"])
        for row in validated["packages"]
        if any(dependency.get("pin") is None for dependency in row["depends_on"])
    ]

    reports: list[dict[str, object]] = []
    manifest_bindings: set[tuple[str, str]] = set()
    legs: set[str] = set()
    package_legs: dict[str, str] = {}
    allowed = set(worker_ids)
    for index, raw in enumerate(envelopes):
        envelope = validate_dispatch_envelope(raw, path_resolver=path_resolver)
        leg = str(envelope["leg"])
        if leg in legs:
            raise DispatchEconomicsError(f"duplicate dispatch envelope leg: {leg}")
        legs.add(leg)
        binding = (
            str(envelope["package_manifest_ref"]["path"]),
            str(envelope["package_manifest_ref"]["sha256"]),
        )
        manifest_bindings.add(binding)
        observed_manifest_sha = envelope["validated_package_manifest"]["validated_manifest_sha256"]
        if observed_manifest_sha != validated["validated_manifest_sha256"]:
            raise DispatchEconomicsError(
                f"dispatch envelope[{index}] does not consume the validated neutral manifest"
            )
        package_ids = [str(value) for value in envelope["package_ids"]]
        duplicated_across_legs = sorted(
            package_id
            for package_id in package_ids
            if package_id in package_legs and package_legs[package_id] != leg
        )
        if duplicated_across_legs:
            raise DispatchEconomicsError(
                "A/B are mutually exclusive route alternatives; packages cannot be dual-dispatched: "
                + ",".join(duplicated_across_legs)
            )
        for package_id in package_ids:
            package_legs[package_id] = leg
        disallowed = sorted(set(package_ids) - allowed)
        if disallowed:
            raise DispatchEconomicsError(
                "dispatch envelope contains packages outside the admitted worker frontier: "
                + ",".join(disallowed)
            )
        reports.append(
            {
                "leg": leg,
                "package_manifest_ref": dict(envelope["package_manifest_ref"]),
                "package_ids": package_ids,
                "validated_package_seals": dict(envelope["validated_package_seals"]),
            }
        )
    if len(manifest_bindings) > 1:
        raise DispatchEconomicsError(
            "A/B dispatch envelopes must bind the same neutral manifest bytes and ref"
        )

    return {
        "schema_version": "xinao.worker_package_preflight.v2",
        "validated_manifest": validated,
        "frontier": frontier,
        "worker_admitted_package_ids": worker_ids,
        "owner_admitted_package_ids": owner_ids,
        "unresolved_pin_package_ids": unresolved_pin_ids,
        "dispatch_envelopes": reports,
        "authority": False,
        "completion_claim_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-ref")
    parser.add_argument("--dispatch-envelope", type=Path, action="append", default=[])
    parser.add_argument("--path-map", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-initial-frontier", action="store_true")
    args = parser.parse_args()
    try:
        manifest_path = args.manifest.resolve(strict=True)
        raw = _json_object(manifest_path, "worker package manifest")
        envelope_values = [
            _json_object(path.resolve(strict=True), f"dispatch envelope[{index}]")
            for index, path in enumerate(args.dispatch_envelope)
        ]
        logical_manifest_refs = {
            str(value.get("package_manifest_ref", {}).get("path") or "")
            for value in envelope_values
            if isinstance(value.get("package_manifest_ref"), Mapping)
        }
        if args.manifest_ref:
            logical_manifest_refs.add(str(args.manifest_ref))
        logical_manifest_refs.discard("")
        resolver = build_path_resolver(
            args.path_map,
            exact_bindings={logical: manifest_path for logical in logical_manifest_refs},
        )
        report = validate_manifest_and_envelopes(
            raw,
            envelope_values,
            path_resolver=resolver,
        )
        result: object = (
            report
            if args.plan_initial_frontier or envelope_values
            else report["validated_manifest"]
        )
        if args.output:
            _write_json_atomic(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        DispatchEconomicsError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "xinao.worker_package_preflight_failure.v1",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
