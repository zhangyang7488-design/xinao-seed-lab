"""Thin adapter: provider-native accepted direct-grok-worker-pool lane → common receipt.

Non-authoritative candidate. Does not schedule, ledger, route, retry, or claim
completion. Reuses closed v1 builders/validators only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.agent_runtime.execution_contract import (
    artifact_json_bytes,
    build_common_dispatch_disposition,
    classify_identical_work_disposition,
    identical_work_pin_sha256,
    logical_contract_sha256,
    validate_attempt_receipt,
    validate_logical_contract,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    GROK_DIRECT_WORKER_POOL_TRANSPORT_ID,
    build_direct_worker_pool_attempt_receipt,
    direct_worker_pool_context_binding_sha256,
)

ADAPTER_RECEIPT_VERSION = "xinao.direct_worker_pool.common_adapter_receipt.v1"
PROVIDER_CONTRACT_VERSION = "xinao.grok.shared_execution_contract.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

FALSE_GREEN_DENY = (
    "REUSE requires current-contract-validated prior attempt_receipt via "
    "classify_identical_work_disposition; pool all_ok/PASS/directory presence/"
    "token use alone never grants REUSE or completion; Spark/manual TUI rejected"
)

_FORBIDDEN_TRANSPORT_SNIPPETS = (
    "spark",
    "manual-tui",
    "visible-tui",
    "tui-inject",
    "typeahead",
)


class DirectWorkerPoolCommonAdapterError(ValueError):
    """Provider evidence or identity failed closed before common mapping."""


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectWorkerPoolCommonAdapterError(f"{field} must be an object")
    return dict(value)


def _require_sha256(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _SHA256_RE.fullmatch(text):
        raise DirectWorkerPoolCommonAdapterError(f"{field} must be a lowercase sha256")
    return text


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, field: str) -> dict[str, Any]:
    if not path.is_file():
        raise DirectWorkerPoolCommonAdapterError(f"{field} not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DirectWorkerPoolCommonAdapterError(f"{field} is not valid JSON: {path}") from exc
    return _require_mapping(raw, field)


def _write_artifact(path: Path, value: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = artifact_json_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _sha256_obj(value: Mapping[str, object]) -> str:
    return hashlib.sha256(artifact_json_bytes(value)).hexdigest()


def _reject_tui_or_spark_evidence(
    summary: Mapping[str, object], lane: Mapping[str, object]
) -> None:
    transport = (
        str(summary.get("selected_transport_id") or lane.get("transport_id") or "")
        .strip()
        .casefold()
    )
    if transport != GROK_DIRECT_WORKER_POOL_TRANSPORT_ID:
        raise DirectWorkerPoolCommonAdapterError(
            f"unsupported pool transport for common adapter: {transport or 'missing'}"
        )
    # Affirmative transport/drain fields only — denial lists in free-text notes are allowed.
    affirmative = " ".join(
        [
            transport,
            str(lane.get("transport_id") or "").casefold(),
            str(lane.get("argv_transport") or "").casefold(),
            str(lane.get("drain") or "").casefold(),
        ]
    )
    for forbidden in _FORBIDDEN_TRANSPORT_SNIPPETS:
        if forbidden in affirmative:
            raise DirectWorkerPoolCommonAdapterError(
                f"Spark/manual Grok TUI evidence is rejected: matched={forbidden}"
            )


def validate_pool_identity_against_contract(
    summary: Mapping[str, object],
    contract: Mapping[str, object],
) -> None:
    """Require pool selection identity to match the selected logical contract."""

    logical = validate_logical_contract(contract)
    selection = logical["selection"]
    if selection["transport_id"] != GROK_DIRECT_WORKER_POOL_TRANSPORT_ID:
        raise DirectWorkerPoolCommonAdapterError(
            "logical contract transport_id is not direct-grok-worker-pool"
        )
    checks = (
        ("selected_provider_id", selection["provider_id"]),
        ("selected_profile_ref", selection["profile_ref"]),
        ("model", selection["model_id"]),
        ("selected_transport_id", selection["transport_id"]),
    )
    for field, expected in checks:
        observed = str(summary.get(field) or "")
        if observed != expected:
            raise DirectWorkerPoolCommonAdapterError(
                f"pool summary identity mismatch: field={field}, "
                f"expected={expected}, observed={observed or 'missing'}"
            )


def _lane_result(summary: Mapping[str, object], lane_index: int) -> dict[str, Any]:
    results = summary.get("results")
    if not isinstance(results, list) or not results:
        raise DirectWorkerPoolCommonAdapterError("pool summary has no results")
    for item in results:
        row = _require_mapping(item, "results[]")
        if int(row.get("lane", -1)) == int(lane_index):
            return row
    raise DirectWorkerPoolCommonAdapterError(f"pool summary has no lane index {lane_index}")


def _validate_lane_result_identity(
    result: Mapping[str, object],
    contract: Mapping[str, object],
) -> None:
    selection = contract["selection"]
    checks = (
        ("provider_id", selection["provider_id"]),
        ("profile_ref", selection["profile_ref"]),
        ("model", selection["model_id"]),
        ("transport_id", selection["transport_id"]),
    )
    for field, expected in checks:
        observed = str(result.get(field) or "")
        if observed != expected:
            raise DirectWorkerPoolCommonAdapterError(
                f"lane result identity mismatch: field={field}, "
                f"expected={expected}, observed={observed or 'missing'}"
            )


def _lane_id_for(
    result: Mapping[str, object], lane_meta: Mapping[str, object], lane_index: int
) -> str:
    for source in (lane_meta.get("lane_id"), result.get("lane_id")):
        text = str(source or "").strip()
        if text:
            return text
    evidence_dir = str(result.get("evidence_dir") or lane_meta.get("evidence_dir") or "")
    if evidence_dir:
        name = Path(evidence_dir).name
        if name.startswith("lane_"):
            return name
    return f"lane_{int(lane_index):02d}"


def _session_id_for(lane_meta: Mapping[str, object]) -> str:
    explicit = str(lane_meta.get("session_id") or "").strip()
    if explicit:
        return explicit
    evidence_dir = str(lane_meta.get("session_evidence_dir") or "").strip()
    if evidence_dir:
        return Path(evidence_dir).name
    return ""


def _observed_rules_sha256(lane_meta: Mapping[str, object], contract: Mapping[str, object]) -> str:
    for key in ("observed_rules_sha256", "short_execution_contract_sha256"):
        value = str(lane_meta.get(key) or "").strip()
        if value:
            if value != contract["rules_sha256"]:
                raise DirectWorkerPoolCommonAdapterError(
                    "provider observed rules do not match logical contract rules_sha256"
                )
            return value
    raise DirectWorkerPoolCommonAdapterError(
        "provider evidence lacks observed_rules_sha256 / short_execution_contract_sha256"
    )


def _validate_common_contract_preflight(
    lane_meta: Mapping[str, object],
    contract: Mapping[str, object],
    subject_manifest_sha256: str,
    frozen_context_sha256: str | None = None,
) -> dict[str, Any]:
    raw = lane_meta.get("common_contract_preflight")
    preflight = _require_mapping(raw, "common_contract_preflight")
    if preflight.get("validated") is not True:
        raise DirectWorkerPoolCommonAdapterError(
            "common_contract_preflight was not validated before dispatch"
        )
    subject = _require_sha256(
        subject_manifest_sha256,
        "subject_manifest_sha256",
    )
    frozen_context = _require_sha256(
        preflight.get("frozen_context_sha256"),
        "common_contract_preflight.frozen_context_sha256",
    )
    if frozen_context_sha256 is not None:
        requested_frozen_context = _require_sha256(
            frozen_context_sha256,
            "frozen_context_sha256",
        )
        if requested_frozen_context != frozen_context:
            raise DirectWorkerPoolCommonAdapterError(
                "common_contract_preflight mismatch: frozen_context_sha256"
            )
    expected = {
        "logical_contract_sha256": logical_contract_sha256(contract),
        "subject_manifest_sha256": subject,
        "input_sha256": contract["input_sha256"],
        "context_sha256": contract["context_sha256"],
        "rules_sha256": contract["rules_sha256"],
        "output_contract_sha256": contract["output_contract_sha256"],
        "capability_binding_sha256": contract["selection"]["capability_binding_sha256"],
    }
    for field, value in expected.items():
        if str(preflight.get(field) or "") != str(value):
            raise DirectWorkerPoolCommonAdapterError(f"common_contract_preflight mismatch: {field}")
    observed_context = direct_worker_pool_context_binding_sha256(
        frozen_context_sha256=frozen_context,
        subject_manifest_sha256=subject,
    )
    if observed_context != contract["context_sha256"]:
        raise DirectWorkerPoolCommonAdapterError(
            "common_contract_preflight context preimage does not match contract"
        )
    return preflight


def normalize_lane_evidence(
    *,
    lane_meta: Mapping[str, object],
    result: Mapping[str, object],
    contract: Mapping[str, object],
    lane_index: int,
) -> dict[str, Any]:
    """Map host pool latest.json (+ summary row) into the closed pool receipt builder shape."""

    meta = dict(lane_meta)
    rules = _observed_rules_sha256(meta, contract)
    usage_raw = meta.get("usage")
    usage = dict(usage_raw) if isinstance(usage_raw, Mapping) else {}
    if "total_tokens" not in usage and isinstance(result.get("usage"), Mapping):
        usage = dict(result["usage"])  # type: ignore[index]

    lane_id = _lane_id_for(result, meta, lane_index)
    run_id = str(meta.get("run_id") or result.get("run_id") or "").strip()
    if not run_id:
        raise DirectWorkerPoolCommonAdapterError("lane meta missing run_id")

    # Prefer lane meta; only fall back to nested validation / summary row when absent.
    validation = meta.get("validation") if isinstance(meta.get("validation"), Mapping) else {}

    def flag(name: str) -> object:
        if name in meta:
            return meta.get(name)
        if name in validation:
            return validation.get(name)
        return result.get(name)

    def bool_flag(name: str, *, default: bool = False) -> bool:
        value = flag(name)
        if value is None:
            return default
        return value is True

    observed_capability = str(meta.get("observed_capability_binding_sha256") or "").strip()
    selected_capability = str(contract["selection"]["capability_binding_sha256"])
    if not observed_capability:
        raise DirectWorkerPoolCommonAdapterError(
            "provider evidence lacks observed_capability_binding_sha256"
        )
    if observed_capability != selected_capability:
        raise DirectWorkerPoolCommonAdapterError(
            "provider observed_capability_binding_sha256 does not match logical contract"
        )

    session_id = _session_id_for(meta)
    if not session_id:
        raise DirectWorkerPoolCommonAdapterError("lane meta missing session_id lineage")

    evidence = {
        "run_id": run_id,
        "lane_id": lane_id,
        "status": str(meta.get("status") or result.get("status") or ""),
        "outcome": str(meta.get("outcome") or result.get("outcome") or ""),
        "effective_output_accepted": bool_flag("effective_output_accepted"),
        "requested_model": str(meta.get("requested_model") or result.get("requested_model") or ""),
        "session_model": str(meta.get("session_model") or result.get("session_model") or ""),
        "model_identity_ok": bool_flag("model_identity_ok"),
        "backend_model_identity_ok": bool_flag("backend_model_identity_ok"),
        "session_model_identity_ok": bool_flag("session_model_identity_ok"),
        "session_turn_model_identity_ok": bool_flag("session_turn_model_identity_ok"),
        "session_evidence_ok": bool_flag("session_evidence_ok"),
        "usage_accounting_complete": bool_flag("usage_accounting_complete"),
        "usage_is_incomplete": bool_flag("usage_is_incomplete"),
        "stop_reason": str(meta.get("stop_reason") or result.get("stop_reason") or ""),
        "result_text_sha256": str(meta.get("result_text_sha256") or ""),
        "result_text_chars": int(meta.get("result_text_chars") or 0),
        "structured_output_present": meta.get("structured_output_present") is True,
        "json_schema_requested": meta.get("json_schema_requested") is True,
        "schema_instance_valid": meta.get("schema_instance_valid"),
        "observed_rules_sha256": rules,
        "observed_capability_binding_sha256": observed_capability,
        "session_id": session_id,
        "usage": usage,
        "transport_id": str(meta.get("transport_id") or result.get("transport_id") or ""),
        "hot_path_cn": str(meta.get("hot_path_cn") or ""),
        "argv_transport": str(meta.get("argv_transport") or ""),
        "drain": str(meta.get("drain") or ""),
    }
    return evidence


def derive_prospective_identical_reuse(
    *,
    contract: Mapping[str, object],
    subject_manifest_sha256: str,
    attempt_receipt: Mapping[str, object],
    phase: str,
    write_domains: Sequence[str],
    depends_on: Sequence[str],
) -> dict[str, Any]:
    """Prospective next-identical REUSE only from a validated accepted receipt.

    Never derives REUSE from pool all_ok, PASS, directory presence, or tokens alone.
    """

    subject = _require_sha256(subject_manifest_sha256, "subject_manifest_sha256")
    logical = validate_logical_contract(contract)
    verdict = validate_attempt_receipt(
        logical,
        attempt_receipt,
        expected_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    )
    if not verdict.accepted:
        raise DirectWorkerPoolCommonAdapterError(
            "cannot derive prospective REUSE from non-accepted receipt: "
            + ",".join(verdict.reason_codes)
        )
    classification = classify_identical_work_disposition(
        logical,
        subject_manifest_sha256=subject,
        prior_accepted=[
            {
                "logical_contract": logical,
                "subject_manifest_sha256": subject,
                "attempt_receipt": dict(attempt_receipt),
            }
        ],
    )
    if classification is None or classification.get("disposition") != "ACCEPTED_IDENTICAL_REUSE":
        raise DirectWorkerPoolCommonAdapterError(
            "prospective identical REUSE disposition was not produced from accepted receipt"
        )
    disposition = build_common_dispatch_disposition(
        logical,
        subject_manifest_sha256=subject,
        phase=phase,
        write_domains=list(write_domains),
        depends_on=list(depends_on),
        classification=classification,
    )
    if (
        disposition.get("authority") is not False
        or disposition.get("completion_claim_allowed") is not False
    ):
        raise DirectWorkerPoolCommonAdapterError("common disposition must remain non-authoritative")
    if disposition.get("disposition") != "ACCEPTED_IDENTICAL_REUSE":
        raise DirectWorkerPoolCommonAdapterError("expected ACCEPTED_IDENTICAL_REUSE disposition")
    return disposition


def classify_prior_attempt_for_dispatch(
    *,
    contract: Mapping[str, object],
    subject_manifest_sha256: str,
    frozen_context_sha256: str,
    prior_attempt_receipt: Mapping[str, object],
    phase: str,
    write_domains: Sequence[str],
    depends_on: Sequence[str],
) -> dict[str, Any]:
    """Run the zero-model identical-work precheck against one explicit receipt."""

    logical = validate_logical_contract(contract)
    subject = _require_sha256(
        subject_manifest_sha256,
        "subject_manifest_sha256",
    )
    frozen_context = _require_sha256(
        frozen_context_sha256,
        "frozen_context_sha256",
    )
    expected_context = direct_worker_pool_context_binding_sha256(
        frozen_context_sha256=frozen_context,
        subject_manifest_sha256=subject,
    )
    if expected_context != logical["context_sha256"]:
        raise DirectWorkerPoolCommonAdapterError(
            "frozen context and subject do not match logical contract context_sha256"
        )
    receipt = _require_mapping(
        prior_attempt_receipt,
        "prior_attempt_receipt",
    )
    return derive_prospective_identical_reuse(
        contract=logical,
        subject_manifest_sha256=subject,
        attempt_receipt=receipt,
        phase=phase,
        write_domains=write_domains,
        depends_on=depends_on,
    )


def adapt_accepted_lane_to_common(
    *,
    logical_contract: Mapping[str, object],
    subject_manifest_sha256: str,
    frozen_context_sha256: str | None = None,
    phase: str,
    write_domains: Sequence[str],
    depends_on: Sequence[str],
    pool_summary: Mapping[str, object],
    lane_index: int,
    lane_meta: Mapping[str, object] | None = None,
    provider_evidence_ref: str | None = None,
    provider_evidence_sha256: str | None = None,
    attempt: int = 1,
    output_root: Path | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """Validate one accepted pool lane and emit common hash-bound artifacts."""

    contract = validate_logical_contract(logical_contract)
    subject = _require_sha256(subject_manifest_sha256, "subject_manifest_sha256")
    summary = _require_mapping(pool_summary, "pool_summary")

    # Explicit denial: pool-level all_ok is never enough for common acceptance.
    validate_pool_identity_against_contract(summary, contract)
    result = _lane_result(summary, lane_index)
    _validate_lane_result_identity(result, contract)

    meta_path_text = str(result.get("meta_path") or "").strip()
    if not meta_path_text and lane_meta is None:
        raise DirectWorkerPoolCommonAdapterError("lane result missing meta_path")

    if lane_meta is None:
        meta_path = Path(meta_path_text)
        meta = _load_json(meta_path, "lane_meta")
        evidence_ref = str(meta_path)
        evidence_sha = _file_sha256(meta_path)
    else:
        meta = _require_mapping(lane_meta, "lane_meta")
        evidence_ref = (
            provider_evidence_ref or meta_path_text or f"lane_{int(lane_index):02d}/latest.json"
        )
        if provider_evidence_sha256:
            evidence_sha = _require_sha256(provider_evidence_sha256, "provider_evidence_sha256")
        elif meta_path_text and Path(meta_path_text).is_file():
            evidence_sha = _file_sha256(Path(meta_path_text))
        else:
            evidence_sha = _sha256_obj(meta)

    _validate_common_contract_preflight(
        meta,
        contract,
        subject,
        frozen_context_sha256,
    )
    evidence = normalize_lane_evidence(
        lane_meta=meta,
        result=result,
        contract=contract,
        lane_index=lane_index,
    )
    _reject_tui_or_spark_evidence(summary, evidence)

    runtime_version = str(meta.get("cli_version") or summary.get("cli_version") or "unknown")
    pool_id = str(summary.get("pool_id") or "")
    if not pool_id:
        raise DirectWorkerPoolCommonAdapterError("pool summary missing pool_id")

    receipt = build_direct_worker_pool_attempt_receipt(
        logical_contract=contract,
        attempt=int(attempt),
        lane_evidence=evidence,
        runtime_version=runtime_version,
        pool_id=pool_id,
        provider_contract_version=str(
            meta.get("execution_contract_version")
            or summary.get("execution_contract_version")
            or PROVIDER_CONTRACT_VERSION
        ),
        provider_evidence_ref=evidence_ref,
        provider_evidence_sha256=evidence_sha,
    )
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    )
    if not verdict.accepted:
        raise DirectWorkerPoolCommonAdapterError(
            "common attempt receipt rejected: " + ",".join(verdict.reason_codes)
        )

    disposition = derive_prospective_identical_reuse(
        contract=contract,
        subject_manifest_sha256=subject,
        attempt_receipt=receipt,
        phase=phase,
        write_domains=write_domains,
        depends_on=depends_on,
    )
    pin = identical_work_pin_sha256(contract, subject_manifest_sha256=subject)
    contract_digest = logical_contract_sha256(contract)
    receipt_digest = _sha256_obj(receipt)
    disposition_digest = _sha256_obj(disposition)

    if output_root is None:
        evidence_dir = str(result.get("evidence_dir") or "").strip()
        if not evidence_dir:
            raise DirectWorkerPoolCommonAdapterError(
                "output_root required when lane evidence_dir is absent"
            )
        output_root = Path(evidence_dir)
    out = Path(output_root)

    paths: dict[str, str] = {}
    path_digests: dict[str, str] = {}
    if write_artifacts:
        mapping = {
            "logical_contract": ("common_logical_contract.json", contract),
            "attempt_receipt": ("common_attempt_receipt.json", receipt),
            "prospective_disposition": (
                "common_prospective_identical_disposition.json",
                disposition,
            ),
        }
        for key, (name, payload) in mapping.items():
            target = out / name
            digest = _write_artifact(target, payload)
            paths[key] = str(target)
            path_digests[key] = digest

    adapter_receipt: dict[str, Any] = {
        "schema_version": ADAPTER_RECEIPT_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "consumer_id": GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
        "pool_id": pool_id,
        "lane_index": int(lane_index),
        "lane_id": evidence["lane_id"],
        "work_key": contract["work_key"],
        "logical_operation_id": contract["logical_operation_id"],
        "contract_sha256": contract_digest,
        "attempt_receipt_sha256": receipt_digest,
        "identical_work_pin_sha256": pin,
        "prospective_disposition": disposition["disposition"],
        "prospective_disposition_sha256": disposition_digest,
        "provider_evidence_ref": evidence_ref,
        "provider_evidence_sha256": evidence_sha,
        "provider_native_accepted": True,
        "common_receipt_accepted": True,
        "artifact_paths": paths,
        "artifact_sha256": path_digests,
        "reason_codes": list(disposition.get("reason_codes") or []),
        "false_green_deny": FALSE_GREEN_DENY,
        "note": (
            "Prospective ACCEPTED_IDENTICAL_REUSE is a pin-bound prediction for the "
            "next identical dispatch only; it is not completion authority."
        ),
    }
    if write_artifacts:
        adapter_path = out / "common_adapter_receipt.json"
        adapter_receipt["adapter_receipt_ref"] = str(adapter_path)
        _write_artifact(adapter_path, adapter_receipt)

    return {
        "logical_contract": contract,
        "attempt_receipt": receipt,
        "prospective_disposition": disposition,
        "adapter_receipt": adapter_receipt,
        "output_root": str(out),
    }


def adapt_from_paths(
    *,
    logical_contract_path: Path,
    subject_manifest_sha256: str,
    frozen_context_sha256: str | None = None,
    phase: str,
    write_domains: Sequence[str],
    depends_on: Sequence[str],
    pool_summary_path: Path,
    lane_index: int,
    attempt: int = 1,
    output_root: Path | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    contract = _load_json(Path(logical_contract_path), "logical_contract")
    summary = _load_json(Path(pool_summary_path), "pool_summary")
    result = _lane_result(summary, lane_index)
    meta_path = Path(str(result.get("meta_path") or ""))
    if not meta_path.is_file():
        raise DirectWorkerPoolCommonAdapterError(
            f"lane meta_path missing or not a file: {meta_path}"
        )
    evidence_sha = _file_sha256(meta_path)
    lane_meta = _load_json(meta_path, "lane_meta")
    return adapt_accepted_lane_to_common(
        logical_contract=contract,
        subject_manifest_sha256=subject_manifest_sha256,
        frozen_context_sha256=frozen_context_sha256,
        phase=phase,
        write_domains=write_domains,
        depends_on=depends_on,
        pool_summary=summary,
        lane_index=lane_index,
        lane_meta=lane_meta,
        provider_evidence_ref=str(meta_path),
        provider_evidence_sha256=evidence_sha,
        attempt=attempt,
        output_root=output_root,
        write_artifacts=write_artifacts,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Adapt one provider-native accepted direct-grok-worker-pool lane into "
            "common logical-contract / attempt-receipt artifacts (authority=false)."
        )
    )
    parser.add_argument("--logical-contract", required=True, type=Path)
    parser.add_argument("--subject-manifest-sha256", required=True)
    parser.add_argument("--frozen-context-sha256", required=True)
    parser.add_argument(
        "--phase", required=True, choices=["EXPLORE", "CONSTRUCT", "VERIFY", "LAND"]
    )
    parser.add_argument(
        "--write-domain",
        action="append",
        default=[],
        dest="write_domains",
        help="Repeatable write domain; may be empty for pure read units.",
    )
    parser.add_argument(
        "--depends-on",
        action="append",
        default=[],
        dest="depends_on",
        help="Repeatable unit dependency id.",
    )
    parser.add_argument("--pool-summary", type=Path, default=None)
    parser.add_argument("--lane-index", type=int, default=0)
    parser.add_argument("--prior-attempt-receipt", type=Path, default=None)
    parser.add_argument(
        "--classify-prior-only",
        action="store_true",
        help="Run the zero-model identical-work precheck and do not read pool evidence.",
    )
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Defaults to the lane evidence_dir from pool_summary.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate without writing artifacts.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.classify_prior_only:
        if args.prior_attempt_receipt is None:
            raise DirectWorkerPoolCommonAdapterError(
                "--prior-attempt-receipt is required with --classify-prior-only"
            )
        contract = _load_json(args.logical_contract, "logical_contract")
        prior = _load_json(args.prior_attempt_receipt, "prior_attempt_receipt")
        disposition = classify_prior_attempt_for_dispatch(
            contract=contract,
            subject_manifest_sha256=args.subject_manifest_sha256,
            frozen_context_sha256=args.frozen_context_sha256,
            prior_attempt_receipt=prior,
            phase=args.phase,
            write_domains=list(args.write_domains),
            depends_on=list(args.depends_on),
        )
        disposition_path = ""
        disposition_sha256 = _sha256_obj(disposition)
        if args.output_root is not None and not args.dry_run:
            target = args.output_root / "common_preflight_disposition.json"
            disposition_sha256 = _write_artifact(target, disposition)
            disposition_path = str(target)
        print(
            json.dumps(
                {
                    "ok": True,
                    "authority": False,
                    "completion_claim_allowed": False,
                    "disposition": disposition["disposition"],
                    "skip_execution": disposition["skip_execution"],
                    "disposition_path": disposition_path,
                    "disposition_sha256": disposition_sha256,
                    "false_green_deny": FALSE_GREEN_DENY,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.pool_summary is None:
        raise DirectWorkerPoolCommonAdapterError(
            "--pool-summary is required unless --classify-prior-only is used"
        )
    result = adapt_from_paths(
        logical_contract_path=args.logical_contract,
        subject_manifest_sha256=args.subject_manifest_sha256,
        frozen_context_sha256=args.frozen_context_sha256,
        phase=args.phase,
        write_domains=list(args.write_domains),
        depends_on=list(args.depends_on),
        pool_summary_path=args.pool_summary,
        lane_index=int(args.lane_index),
        attempt=int(args.attempt),
        output_root=args.output_root,
        write_artifacts=not args.dry_run,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "authority": False,
                "completion_claim_allowed": False,
                "consumer_id": GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
                "contract_sha256": result["adapter_receipt"]["contract_sha256"],
                "attempt_receipt_sha256": result["adapter_receipt"]["attempt_receipt_sha256"],
                "prospective_disposition": result["adapter_receipt"]["prospective_disposition"],
                "output_root": result["output_root"],
                "false_green_deny": FALSE_GREEN_DENY,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
