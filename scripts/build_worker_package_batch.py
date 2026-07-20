#!/usr/bin/env python3
"""Seal one neutral package DAG and bind one or more worker-leg envelopes to it."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    build_route_choice_identity,
    build_worker_package_identity,
    plan_package_frontier,
    validate_dispatch_envelope,
    validate_package_batch_manifest,
)
from services.agent_runtime.grok_execution_contract_adapter import (  # noqa: E402
    GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
    GROK_DOCKER_ROUTE_TRANSPORT_ID,
    build_grok_docker_route_adapter_binding,
    validate_grok_route_selection_receipt,
)

PathResolver = Callable[[str], str | Path]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _logical_path(value: object, label: str) -> str:
    logical = str(value or "").strip()
    if not logical:
        raise ValueError(f"{label} must be a non-empty logical path")
    return logical


def _resolve_path(
    logical: str,
    *,
    path_resolver: PathResolver | None,
) -> Path:
    resolved = path_resolver(logical) if path_resolver is not None else Path(logical)
    return Path(resolved).resolve(strict=True)


def _path_ref(
    logical: str,
    *,
    path_resolver: PathResolver | None,
) -> dict[str, str]:
    return {"path": logical, "sha256": _sha(_resolve_path(logical, path_resolver=path_resolver))}


def _atomic_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def build_path_resolver(
    bindings: Sequence[str] = (),
    *,
    exact_bindings: Mapping[str, str | Path] | None = None,
) -> PathResolver:
    """Build a read-only logical-to-physical resolver without changing manifest bytes."""

    prefix_bindings: list[tuple[str, Path]] = []
    for index, raw in enumerate(bindings):
        if "=" not in raw:
            raise ValueError(f"path-map[{index}] must be LOGICAL=PHYSICAL")
        logical, physical = raw.split("=", 1)
        logical = logical.strip().replace("\\", "/").rstrip("/")
        physical_path = Path(physical.strip()).resolve(strict=True)
        if not logical:
            raise ValueError(f"path-map[{index}] logical prefix is empty")
        prefix_bindings.append((logical, physical_path))
    prefix_bindings.sort(key=lambda item: len(item[0]), reverse=True)
    exact = {
        str(logical): Path(physical).resolve(strict=False)
        for logical, physical in (exact_bindings or {}).items()
    }

    def resolve(logical: str) -> Path:
        if logical in exact:
            return exact[logical]
        normalized = logical.replace("\\", "/")
        for prefix, physical_root in prefix_bindings:
            if normalized == prefix:
                return physical_root
            if normalized.startswith(prefix + "/"):
                relative = normalized[len(prefix) + 1 :]
                return physical_root / Path(relative)
        return Path(logical)

    return resolve


def build_neutral_manifest(
    spec: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
) -> dict[str, object]:
    """Build one logical v3 manifest; physical resolver output never enters identity."""

    if spec.get("schema_version") != "xinao.worker_package_batch_spec.v1":
        raise ValueError("package spec schema mismatch")
    parent_work_key = str(spec.get("parent_work_key") or "").strip()
    if not parent_work_key:
        raise ValueError("package spec requires parent_work_key")
    graph_revision = spec.get("graph_revision", 1)
    if isinstance(graph_revision, bool) or not isinstance(graph_revision, int):
        raise ValueError("graph_revision must be an integer")

    packages: list[dict[str, Any]] = []
    raw_packages = spec.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise ValueError("package spec requires packages")
    for index, raw_value in enumerate(raw_packages):
        if not isinstance(raw_value, Mapping):
            raise TypeError(f"packages[{index}] must be an object")
        raw = dict(raw_value)
        if "consumer_id" in raw:
            raise ValueError(
                f"packages[{index}] cannot bind a physical consumer_id in the neutral manifest"
            )
        prompt_logical = _logical_path(raw.get("prompt_path"), f"packages[{index}].prompt_path")
        context_logical = _logical_path(
            raw.get("context_manifest_path"),
            f"packages[{index}].context_manifest_path",
        )
        input_values = raw.get("input_paths")
        if not isinstance(input_values, list) or not input_values:
            raise ValueError(f"packages[{index}] requires input_paths")
        input_refs = [
            _path_ref(
                _logical_path(value, f"packages[{index}].input_paths[]"),
                path_resolver=path_resolver,
            )
            for value in input_values
        ]
        input_sha = input_refs[0]["sha256"] if len(input_refs) == 1 else _canonical_sha(input_refs)
        context_ref = _path_ref(context_logical, path_resolver=path_resolver)
        prompt_ref = _path_ref(prompt_logical, path_resolver=path_resolver)

        acceptance = copy.deepcopy(dict(raw.get("acceptance") or {}))
        acceptance.setdefault("min_result_chars", 1)
        acceptance.setdefault("required_result_markers", [])
        acceptance.setdefault("require_json_object", False)
        schema_path_value = str(acceptance.pop("json_schema_path", "") or "").strip()
        if schema_path_value:
            acceptance["json_schema_ref"] = _path_ref(
                schema_path_value,
                path_resolver=path_resolver,
            )
        rules_path_value = str(raw.get("rules_path") or "").strip()
        rules_sha = (
            _sha(_resolve_path(rules_path_value, path_resolver=path_resolver))
            if rules_path_value
            else str(raw.get("rules_sha256") or "")
        )
        output_contract_sha = str(raw.get("output_contract_sha256") or "").strip()
        if not output_contract_sha:
            output_contract_sha = _canonical_sha(acceptance)
        candidate_only = raw.get("candidate_only", True)
        if not isinstance(candidate_only, bool):
            raise TypeError(f"packages[{index}].candidate_only must be boolean")
        identity = build_worker_package_identity(
            package_id=str(raw.get("package_id") or ""),
            work_key=str(raw.get("work_key") or ""),
            parent_work_key=parent_work_key,
            work_class=str(raw.get("work_class") or ""),
            role=str(raw.get("role") or ""),
            phase=str(raw.get("phase") or ""),
            input_sha256=input_sha,
            context_sha256=context_ref["sha256"],
            rules_sha256=rules_sha,
            output_contract_sha256=output_contract_sha,
            write_domains=list(raw.get("write_domains") or []),
            candidate_only=candidate_only,
        )
        package: dict[str, Any] = {
            **identity,
            "prompt_ref": prompt_ref,
            "context_manifest_ref": context_ref,
            "input_refs": input_refs,
            "allowed_output_root": _logical_path(
                raw.get("allowed_output_root"),
                f"packages[{index}].allowed_output_root",
            ),
            "cwd": _logical_path(raw.get("cwd"), f"packages[{index}].cwd"),
            "depends_on": copy.deepcopy(list(raw.get("depends_on") or [])),
            "acceptance": acceptance,
            "timeout_sec": int(raw.get("timeout_sec") or 600),
        }
        prior = raw.get("prior_attempt_receipt_ref")
        if isinstance(prior, Mapping):
            prior_logical = _logical_path(
                prior.get("path"), f"packages[{index}].prior_attempt_receipt_ref.path"
            )
            package["prior_attempt_receipt_ref"] = _path_ref(
                prior_logical,
                path_resolver=path_resolver,
            )
        packages.append(package)

    limits = copy.deepcopy(dict(spec.get("limits") or {}))
    limits.setdefault("max_parallel", 1)
    limits.setdefault("fan_in_capacity", 1)
    limits.setdefault("candidate_ingestion_capacity", limits["max_parallel"])
    manifest: dict[str, object] = {
        "schema_version": "xinao.worker_package_batch.v3",
        "authority": False,
        "completion_claim_allowed": False,
        "parent_work_key": parent_work_key,
        "candidate_output_base": _logical_path(
            spec.get("candidate_output_base"),
            "candidate_output_base",
        ),
        "graph_revision": graph_revision,
        "predecessor_manifest_ref": copy.deepcopy(spec.get("predecessor_manifest_ref")),
        "reseal_of": copy.deepcopy(spec.get("reseal_of")),
        "affected_cone": copy.deepcopy(list(spec.get("affected_cone") or [])),
        "limits": limits,
        "packages": packages,
    }
    validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    return manifest


def plan_worker_dispatch(
    manifest: Mapping[str, object],
    *,
    path_resolver: PathResolver | None = None,
    pending_candidate_ingestion_count: int = 0,
    pending_owner_authority_count: int = 0,
) -> dict[str, object]:
    """Canonicalize once, plan once, and separate worker from owner admissions."""

    validated = validate_package_batch_manifest(manifest, path_resolver=path_resolver)
    frontier = plan_package_frontier(
        validated,
        pending_candidate_ingestion_count=pending_candidate_ingestion_count,
        pending_owner_authority_count=pending_owner_authority_count,
        path_resolver=path_resolver,
    )
    admitted = list(frontier["admitted"])
    worker_rows = [
        row
        for row in admitted
        if row["candidate_only"] is True and row["execution_seal_ready"] is True
    ]
    owner_rows = [row for row in admitted if row["candidate_only"] is False]
    unresolved_pin_package_ids = [
        str(row["package_id"])
        for row in validated["packages"]
        if any(dependency.get("pin") is None for dependency in row["depends_on"])
    ]
    return {
        "validated_manifest": validated,
        "frontier": frontier,
        "worker_package_ids": [str(row["package_id"]) for row in worker_rows],
        "owner_package_ids": [str(row["package_id"]) for row in owner_rows],
        "unresolved_pin_package_ids": unresolved_pin_package_ids,
        "conditionally_ready_package_ids": list(frontier["conditionally_ready_package_ids"]),
    }


def build_dispatch_envelope(
    *,
    leg: str,
    manifest_ref: Mapping[str, object],
    package_ids: Sequence[str],
    epoch_id: str,
    snapshot: Mapping[str, object],
    snapshot_ref: Mapping[str, object],
    selection: Mapping[str, object],
    selection_ref: Mapping[str, object],
) -> dict[str, object]:
    """Compatibility name for the route-bound envelope constructor."""

    return build_route_bound_dispatch_envelope(
        leg=leg,
        manifest_ref=manifest_ref,
        package_ids=package_ids,
        epoch_id=epoch_id,
        snapshot=snapshot,
        snapshot_ref=snapshot_ref,
        selection=selection,
        selection_ref=selection_ref,
    )


def build_route_bound_dispatch_envelope(
    *,
    leg: str,
    manifest_ref: Mapping[str, object],
    package_ids: Sequence[str],
    epoch_id: str,
    snapshot: Mapping[str, object],
    snapshot_ref: Mapping[str, object],
    selection: Mapping[str, object],
    selection_ref: Mapping[str, object],
) -> dict[str, object]:
    """Bind one package batch to exactly one selector route and consumer leg."""

    normalized_leg = str(leg or "").strip().upper()
    route_transport_by_leg = {
        "A": GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
        "B": GROK_DOCKER_ROUTE_TRANSPORT_ID,
    }
    expected_route_transport = route_transport_by_leg.get(normalized_leg)
    if expected_route_transport is None:
        raise ValueError("dispatch envelope leg must be A or B")
    route = validate_grok_route_selection_receipt(
        selection,
        expected_route_transport_id=expected_route_transport,
    )
    if not package_ids:
        raise ValueError("worker dispatch envelope requires an admitted candidate package")
    route_identity = dict(route["route_identity"])
    envelope: dict[str, object] = {
        "schema_version": "xinao.worker_dispatch_envelope.v2",
        "authority": False,
        "completion_claim_allowed": False,
        "leg": normalized_leg,
        "package_manifest_ref": copy.deepcopy(dict(manifest_ref)),
        "package_ids": [str(value) for value in package_ids],
        "dispatch_epoch": {
            "epoch_id": str(epoch_id),
            "quota_snapshot_id": snapshot["snapshot_id"],
            "quota_snapshot_ref": snapshot_ref["path"],
            "quota_snapshot_sha256": snapshot_ref["sha256"],
        },
        "selection": {
            **route_identity,
            "receipt_ref": selection_ref["path"],
            "receipt_sha256": selection_ref["sha256"],
            "decision_sha256": route["decision_sha256"],
            "route_identity_sha256": route["route_identity_sha256"],
            "route_decision_binding_sha256": route["route_decision_binding_sha256"],
        },
    }
    if normalized_leg == "B":
        envelope["execution_adapter"] = build_grok_docker_route_adapter_binding(selection)
    envelope["route_choice"] = build_route_choice_identity(
        package_manifest_sha256=str(manifest_ref["sha256"]),
        package_ids=[str(value) for value in package_ids],
        epoch_id=str(epoch_id),
        leg=normalized_leg,
        selection_decision_sha256=str(route["decision_sha256"]),
        route_decision_binding_sha256=str(route["route_decision_binding_sha256"]),
    )
    return envelope


def _dispatch_targets(
    args: argparse.Namespace, spec: Mapping[str, object]
) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    if args.dispatch_output is not None:
        targets.append((str(spec.get("leg") or "A").upper(), args.dispatch_output))
    if args.dispatch_output_a is not None:
        targets.append(("A", args.dispatch_output_a))
    if args.dispatch_output_b is not None:
        targets.append(("B", args.dispatch_output_b))
    if not targets:
        raise ValueError(
            "one of --dispatch-output/--dispatch-output-a/--dispatch-output-b is required"
        )
    legs = [leg for leg, _ in targets]
    paths = [path.resolve(strict=False) for _, path in targets]
    if len(legs) != len(set(legs)):
        raise ValueError("dispatch envelope legs must be unique")
    if len(paths) != len(set(paths)):
        raise ValueError("dispatch envelope output paths must be unique")
    if any(leg not in {"A", "B"} for leg in legs):
        raise ValueError("dispatch envelope leg must be A or B")
    if len(targets) > 1:
        raise ValueError(
            "A/B are mutually exclusive route alternatives; "
            "one package batch cannot dispatch the same frontier to both legs"
        )
    return targets


def _selection_input_for_leg(
    args: argparse.Namespace,
    leg: str,
) -> tuple[Path, str]:
    specific_path = args.selection_receipt_a if leg == "A" else args.selection_receipt_b
    specific_ref = args.selection_receipt_ref_a if leg == "A" else args.selection_receipt_ref_b
    if specific_path is not None and args.selection_receipt is not None:
        raise ValueError(f"leg-{leg} selection receipt is ambiguous")
    selected_path = specific_path or args.selection_receipt
    if selected_path is None:
        raise ValueError(f"leg-{leg} requires its own stable-selector route receipt")
    selected_ref = str(specific_ref or args.selection_receipt_ref or selected_path)
    return selected_path.resolve(strict=True), selected_ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--quota-resolution", type=Path, required=True)
    parser.add_argument("--selection-receipt", type=Path)
    parser.add_argument("--selection-receipt-ref")
    parser.add_argument("--selection-receipt-a", type=Path)
    parser.add_argument("--selection-receipt-ref-a")
    parser.add_argument("--selection-receipt-b", type=Path)
    parser.add_argument("--selection-receipt-ref-b")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-ref")
    parser.add_argument("--dispatch-output", type=Path)
    parser.add_argument("--dispatch-output-a", type=Path)
    parser.add_argument("--dispatch-output-b", type=Path)
    parser.add_argument("--path-map", action="append", default=[])
    args = parser.parse_args()
    try:
        spec = _object(args.spec.resolve(strict=True), "package spec")
        parent_work_key = str(spec.get("parent_work_key") or "").strip()
        epoch_id = str(spec.get("epoch_id") or "").strip()
        if not parent_work_key or not epoch_id:
            raise ValueError("package spec requires parent_work_key and epoch_id")
        targets = _dispatch_targets(args, spec)
        target_leg = targets[0][0]
        selection_path, selection_logical = _selection_input_for_leg(args, target_leg)
        output_path = args.output.resolve(strict=False)
        for target in [output_path, *(path.resolve(strict=False) for _, path in targets)]:
            if target.exists():
                raise FileExistsError(f"output already exists: {target}")

        resolution = _object(args.quota_resolution.resolve(strict=True), "quota resolution")
        snapshot = resolution.get("snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("epoch_id") != epoch_id:
            raise ValueError("quota resolution epoch mismatch")
        selection = _object(selection_path, "selection receipt")
        snapshot_logical = _logical_path(snapshot.get("snapshot_ref"), "snapshot.snapshot_ref")
        manifest_logical = str(args.manifest_ref or args.output)
        base_resolver = build_path_resolver(
            args.path_map,
            exact_bindings={selection_logical: selection_path},
        )
        manifest = build_neutral_manifest(spec, path_resolver=base_resolver)
        plan = plan_worker_dispatch(manifest, path_resolver=base_resolver)
        manifest_sha = _atomic_json(output_path, manifest)
        manifest_ref = {"path": manifest_logical, "sha256": manifest_sha}
        runtime_resolver = build_path_resolver(
            args.path_map,
            exact_bindings={
                selection_logical: selection_path,
                manifest_logical: output_path,
            },
        )
        snapshot_path = _resolve_path(snapshot_logical, path_resolver=runtime_resolver)
        snapshot_ref = {"path": snapshot_logical, "sha256": _sha(snapshot_path)}
        selection_ref = {"path": selection_logical, "sha256": _sha(selection_path)}

        dispatch_results: dict[str, dict[str, str]] = {}
        package_ids = list(plan["worker_package_ids"])
        if package_ids:
            for leg, target in targets:
                envelope = build_dispatch_envelope(
                    leg=leg,
                    manifest_ref=manifest_ref,
                    package_ids=package_ids,
                    epoch_id=epoch_id,
                    snapshot=snapshot,
                    snapshot_ref=snapshot_ref,
                    selection=selection,
                    selection_ref=selection_ref,
                )
                validate_dispatch_envelope(envelope, path_resolver=runtime_resolver)
                envelope_path = target.resolve(strict=False)
                envelope_sha = _atomic_json(envelope_path, envelope)
                dispatch_results[leg] = {
                    "path": str(envelope_path),
                    "sha256": envelope_sha,
                }

        result: dict[str, object] = {
            "manifest_ref": manifest_logical,
            "manifest_sha256": manifest_sha,
            "package_count": len(manifest["packages"]),
            "worker_package_ids": package_ids,
            "owner_package_ids": list(plan["owner_package_ids"]),
            "conditionally_ready_package_ids": list(plan["conditionally_ready_package_ids"]),
            "unresolved_pin_package_ids": list(plan["unresolved_pin_package_ids"]),
            "dispatch_envelopes": dispatch_results,
            "dispatch_deferred": not bool(package_ids),
            "epoch_id": epoch_id,
            "selection_decision_sha256": selection["decision_sha256"],
            "selected_leg": target_leg,
        }
        if len(dispatch_results) == 1:
            only = next(iter(dispatch_results.values()))
            result["dispatch_envelope_ref"] = only["path"]
            result["dispatch_envelope_sha256"] = only["sha256"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        DispatchEconomicsError,
    ) as exc:
        print(f"WORKER_PACKAGE_BATCH_BUILD_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
