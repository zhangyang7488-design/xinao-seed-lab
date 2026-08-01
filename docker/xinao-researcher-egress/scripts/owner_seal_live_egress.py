#!/usr/bin/env python3
"""Owner thin sealer/validator for D-state provider egress live seal.

Platform-neutral. No daemon/scheduler. Does not mutate immutable source lock.
Does not claim science/parent completion. Evidence receipts must be redacted metadata only.

Trust boundary: host filesystem + Docker CLI observation only (no signing PKI).

Semantic evidence contract (Wave 9b Owner rejection):
  - Negative suite must prove suite_passed/all_cases_passed with exact required case IDs
    all ok=true, posture-bound identities, unauthorized domain false, direct escape false.
  - Engineering canary must prove real_provider_call + provider_effect_verified with
    grok-4.5 / grok-4.5-build / EndTurn / output_tokens>0 / complete usage /
    cli-chat-proxy.grok.com / posture-bound identities / immutable canary image /
    internal-network-only + auth RO + no secret/raw persistence.
  - CONNECT-only, HTTP-only, planned/partial, null/zero token, wrong model, incomplete
    usage, replayed identities, or stale observation times are rejected before any seal write.
  - Direct Docker observation remains required after semantic evidence validation.

Sibling PowerShell carrier handshake (documented; not executed here):
  Owner-LiveNegativeSuite.ps1 / Owner-EngineeringCanary.ps1 must emit seal-eligible
  receipts matching the exact/allowed key sets and semantic constants below. CONNECT-only
  engineering receipts (real_provider_call=false, positive_token_value=null) are transport
  evidence only and MUST NOT be accepted as positive canary for sealing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

SCHEMA = "xinao.provider_egress_live_seal.v1"
POSTURE_SCHEMA = "xinao.provider_egress_posture.v1"
NEGATIVE_SCHEMA = "xinao.provider_egress_negative_suite_receipt.v1"
CANARY_SCHEMA = "xinao.provider_egress_engineering_canary_receipt.v1"
TRUST_BOUNDARY = "host_filesystem_and_docker_cli_observation_only_no_signing_pki"
MAX_TTL_SECONDS = 24 * 60 * 60
CLOCK_SKEW_SECONDS = 5 * 60
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_TOKENS = (
    "authorization",
    "api_key",
    "auth.json",
    "password",
    "begin private",
    "bearer ",
    "client_secret",
    "private_key",
)

# Exact required negative case IDs (Windows Owner carrier + bash suite spirit).
REQUIRED_NEGATIVE_CASE_IDS: tuple[str, ...] = (
    "N1",
    "N3",
    "N4",
    "N5",
    "N6",
    "N7",
    "N8",
    "N9",
    "N15",
    "N17",
    "N17b",
    "N17c",
    "N17d",
)

REQUESTED_MODEL = "grok-4.5"
OBSERVED_BACKEND_MODEL = "grok-4.5-build"
STOP_REASON = "EndTurn"
ENDPOINT_HOST = "cli-chat-proxy.grok.com"

# Exact required keys for seal-eligible negative suite receipt.
NEGATIVE_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "path_class",
        "status",
        "suite_passed",
        "all_cases_passed",
        "cases",
        "pass_count",
        "fail_count",
        "internal_network_id",
        "proxy_container_id",
        "proxy_image_id",
        "allowlist_sha256",
        "proxy_config_sha256",
        "unauthorized_domain_reachable",
        "direct_no_proxy_escape",
        "provider_egress_runtime_verified",
        "provider_egress_live_verified",
        "secrets_present",
        "completion_claim_allowed",
        "authority",
        "science_restored",
        "parent_complete",
        "scientific_research",
        "observed_at",
    }
)
# Allowed optional keys for sibling PowerShell / bash carrier handshake.
NEGATIVE_ALLOWED_KEYS: frozenset[str] = NEGATIVE_REQUIRED_KEYS | frozenset(
    {
        "executed_at",
        "object_identities",
        "mode",
        "note",
        "docker_mutated",
        "carrier",
        "wsl_used",
        "git_bash_used",
        "research_invoked",
        "path_class",
    }
)

CANARY_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "path_class",
        "status",
        "real_provider_call",
        "provider_effect_verified",
        "requested_model",
        "observed_backend_model",
        "stop_reason",
        "output_tokens",
        "usage_accounting_complete",
        "usage",
        "endpoint_host",
        "internal_network_id",
        "proxy_container_id",
        "proxy_image_id",
        "allowlist_sha256",
        "proxy_config_sha256",
        "canary_image_id",
        "internal_network_only",
        "auth_mounted_read_only",
        "auth_content_persisted",
        "raw_output_persisted",
        "research_invoked",
        "is_research_call",
        "scientific_research",
        "masquerades_as_research",
        "scientific_adoption",
        "science_restored",
        "parent_complete",
        "authority",
        "completion_claim_allowed",
        "secrets_present",
        "provider_egress_runtime_verified",
        "provider_egress_live_verified",
        "observed_at",
    }
)
CANARY_ALLOWED_KEYS: frozenset[str] = CANARY_REQUIRED_KEYS | frozenset(
    {
        "executed_at",
        "object_identities",
        "mode",
        "note",
        "docker_mutated",
        "carrier",
        "wsl_used",
        "git_bash_used",
        "probe_ok",
        "probe_exit_code",
        "connect_probe_ok",
        "canary_container_id",
        "canary_container_removed",
        "endpoint_hint",
        "model_hint",
        "positive_token_present_observed",
        "positive_token_value",
        "engineering_evidence",
        "redaction",
        "allow_real_provider_call_requested",
        "raw_output_sha256",
        "reason_code",
        "connect_only",
        "http_only",
    }
)

USAGE_REQUIRED_KEYS: frozenset[str] = frozenset({"input_tokens", "output_tokens", "total_tokens"})


class SealError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def _reject_secrets(blob: str) -> None:
    lowered = blob.lower()
    for token in FORBIDDEN_TOKENS:
        if token in lowered:
            raise SealError("EGRESS_SEAL_SECRET_LEAK", token)


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise SealError("SEAL_INPUT_INVALID", f"not object: {path}")
    _reject_secrets(raw.decode("utf-8"))
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(value)
    _reject_secrets(payload.decode("utf-8"))
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise SealError("DOCKER_CLI_MISSING", "docker")
    return docker


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise SealError(
            "DOCKER_COMMAND_FAILED",
            f"{command!r} exit={completed.returncode} stderr={completed.stderr[:2000]}",
        )
    return completed.stdout


def _engine_identity(docker: str) -> dict[str, str]:
    text = _run(
        [docker, "info", "--format", "{{.ID}}|{{.Name}}|{{.ServerVersion}}|{{.OSType}}"]
    ).strip()
    parts = text.split("|")
    if len(parts) != 4 or any(not part for part in parts):
        raise SealError("DOCKER_ENGINE_UNOBSERVED", text[:500])
    engine_id, name, server_version, ostype = parts
    if ostype != "linux":
        raise SealError("LINUX_CONTAINER_ENGINE_REQUIRED", ostype)
    return {
        "docker_engine_observational_id": f"{engine_id}|{name}",
        "docker_server_version": server_version,
        "docker_ostype": ostype,
    }


def _parse_utc_z(value: object, *, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SealError("EVIDENCE_TIMESTAMP_INVALID", field)
    text = value[:-1]
    try:
        if "." in text:
            parsed = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            parsed = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise SealError("EVIDENCE_TIMESTAMP_INVALID", field) from exc
    return parsed.replace(tzinfo=dt.UTC)


def _require_false(receipt: dict[str, Any], *fields: str, reason: str) -> None:
    for field in fields:
        if receipt.get(field) is not False:
            raise SealError(reason, field)


def _require_true(receipt: dict[str, Any], *fields: str, reason: str) -> None:
    for field in fields:
        if receipt.get(field) is not True:
            raise SealError(reason, field)


def _require_keys(
    receipt: dict[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    reason_missing: str,
    reason_unknown: str,
) -> None:
    keys = set(receipt)
    missing = sorted(required - keys)
    unknown = sorted(keys - allowed)
    if missing:
        raise SealError(reason_missing, ",".join(missing))
    if unknown:
        raise SealError(reason_unknown, ",".join(unknown))


def _bind_posture_identities(
    receipt: dict[str, Any],
    posture: dict[str, Any],
    *,
    reason: str,
) -> None:
    bindings = (
        ("internal_network_id", "internal_network_id"),
        ("proxy_container_id", "proxy_container_id"),
        ("proxy_image_id", "proxy_image_id"),
        ("allowlist_sha256", "allowlist_sha256"),
        ("proxy_config_sha256", "proxy_config_sha256"),
    )
    for receipt_key, posture_key in bindings:
        if receipt.get(receipt_key) != posture.get(posture_key):
            raise SealError(
                reason,
                f"{receipt_key}:{receipt.get(receipt_key)}!={posture.get(posture_key)}",
            )
    for field in ("allowlist_sha256", "proxy_config_sha256"):
        value = receipt.get(field)
        if not isinstance(value, str) or not HEX_SHA256.fullmatch(value):
            raise SealError(reason, field)
    image = receipt.get("proxy_image_id")
    if not isinstance(image, str) or not IMAGE_ID.fullmatch(image):
        raise SealError(reason, "proxy_image_id")


def _validate_observation_freshness(
    observed_at: object,
    *,
    now: dt.datetime,
    max_age_seconds: int,
    field: str = "observed_at",
) -> dt.datetime:
    parsed = _parse_utc_z(observed_at, field=field)
    if parsed > now + dt.timedelta(seconds=CLOCK_SKEW_SECONDS):
        raise SealError("EVIDENCE_OBSERVATION_FUTURE", field)
    age = (now - parsed).total_seconds()
    if age > max_age_seconds:
        raise SealError("EVIDENCE_OBSERVATION_STALE", f"{field} age={age}")
    return parsed


def _validate_common_nonclaims(receipt: dict[str, Any], *, schema: str) -> None:
    if receipt.get("schema_version") != schema:
        raise SealError("EVIDENCE_SCHEMA_INVALID", str(receipt.get("schema_version")))
    _require_false(
        receipt,
        "completion_claim_allowed",
        "authority",
        "science_restored",
        "parent_complete",
        "scientific_research",
        reason="EVIDENCE_CLAIM_FORBIDDEN",
    )
    if receipt.get("secrets_present") is not False:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "secrets_present")
    if receipt.get("provider_egress_runtime_verified") is not False:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "provider_egress_runtime_verified")
    if receipt.get("provider_egress_live_verified") is not False:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "provider_egress_live_verified")
    if str(receipt.get("schema_version", "")).startswith("xinao.skill_research_receipt"):
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "scientific_research_receipt")


def _case_id(case: object) -> str | None:
    if not isinstance(case, dict):
        return None
    for key in ("id", "case_id"):
        value = case.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def validate_negative_suite_receipt(
    receipt: dict[str, Any],
    *,
    posture: dict[str, Any],
    now: dt.datetime | None = None,
    max_age_seconds: int = MAX_TTL_SECONDS,
) -> dict[str, Any]:
    """Strict negative-suite contract for seal eligibility."""
    _validate_common_nonclaims(receipt, schema=NEGATIVE_SCHEMA)
    _require_keys(
        receipt,
        required=NEGATIVE_REQUIRED_KEYS,
        allowed=NEGATIVE_ALLOWED_KEYS,
        reason_missing="NEGATIVE_RECEIPT_MISSING_KEY",
        reason_unknown="NEGATIVE_RECEIPT_UNKNOWN_KEY",
    )
    if receipt.get("path_class") != "negative_suite":
        raise SealError("EVIDENCE_PATH_CLASS_INVALID", str(receipt.get("path_class")))
    if receipt.get("status") != "observed":
        raise SealError("NEGATIVE_SUITE_STATUS_INVALID", str(receipt.get("status")))
    _require_true(
        receipt,
        "suite_passed",
        "all_cases_passed",
        reason="NEGATIVE_SUITE_NOT_PASSED",
    )
    if receipt.get("unauthorized_domain_reachable") is not False:
        raise SealError("NEGATIVE_SUITE_UNAUTHORIZED_DOMAIN", "unauthorized_domain_reachable")
    if receipt.get("direct_no_proxy_escape") is not False:
        raise SealError("NEGATIVE_SUITE_DIRECT_ESCAPE", "direct_no_proxy_escape")
    if type(receipt.get("pass_count")) is not int or receipt["pass_count"] < 0:
        raise SealError("NEGATIVE_SUITE_COUNT_INVALID", "pass_count")
    if type(receipt.get("fail_count")) is not int or receipt["fail_count"] != 0:
        raise SealError("NEGATIVE_SUITE_COUNT_INVALID", "fail_count")
    cases = receipt.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SealError("NEGATIVE_SUITE_CASES_INVALID", "cases")
    seen: list[str] = []
    for case in cases:
        case_id = _case_id(case)
        if case_id is None:
            raise SealError("NEGATIVE_SUITE_CASES_INVALID", "case missing id")
        if case_id in seen:
            raise SealError("NEGATIVE_SUITE_DUPLICATE_CASE", case_id)
        seen.append(case_id)
        if not isinstance(case, dict) or case.get("ok") is not True:
            raise SealError("NEGATIVE_SUITE_CASE_NOT_OK", case_id)
    required = list(REQUIRED_NEGATIVE_CASE_IDS)
    missing = [case_id for case_id in required if case_id not in seen]
    if missing:
        raise SealError("NEGATIVE_SUITE_MISSING_CASE", ",".join(missing))
    unknown = [case_id for case_id in seen if case_id not in required]
    if unknown:
        raise SealError("NEGATIVE_SUITE_UNKNOWN_CASE", ",".join(unknown))
    if receipt["pass_count"] != len(required):
        raise SealError(
            "NEGATIVE_SUITE_COUNT_INVALID",
            f"pass_count={receipt['pass_count']} expected={len(required)}",
        )
    _bind_posture_identities(receipt, posture, reason="NEGATIVE_RECEIPT_POSTURE_MISMATCH")
    clock = now or dt.datetime.now(dt.UTC)
    _validate_observation_freshness(
        receipt.get("observed_at"),
        now=clock,
        max_age_seconds=max_age_seconds,
    )
    # Nested object_identities, when present, must not contradict top-level bindings.
    identities = receipt.get("object_identities")
    if identities is not None:
        if not isinstance(identities, dict):
            raise SealError("NEGATIVE_RECEIPT_POSTURE_MISMATCH", "object_identities")
        for key in (
            "internal_network_id",
            "proxy_container_id",
            "proxy_image_id",
            "allowlist_sha256",
            "proxy_config_sha256",
        ):
            if key in identities and identities.get(key) != receipt.get(key):
                raise SealError("NEGATIVE_RECEIPT_POSTURE_MISMATCH", f"object_identities.{key}")
    return receipt


def _validate_usage(usage: object, *, output_tokens: int) -> None:
    if not isinstance(usage, dict):
        raise SealError("CANARY_USAGE_INVALID", "usage not object")
    keys = set(usage)
    missing = sorted(USAGE_REQUIRED_KEYS - keys)
    unknown = sorted(keys - USAGE_REQUIRED_KEYS)
    if missing:
        raise SealError("CANARY_USAGE_INVALID", f"missing:{','.join(missing)}")
    if unknown:
        raise SealError("CANARY_USAGE_INVALID", f"unknown:{','.join(unknown)}")
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(field)
        if type(value) is not int or isinstance(value, bool) or value < 0:
            raise SealError("CANARY_USAGE_INVALID", field)
    if usage["output_tokens"] <= 0:
        raise SealError("CANARY_USAGE_INVALID", "output_tokens<=0")
    if usage["output_tokens"] != output_tokens:
        raise SealError(
            "CANARY_USAGE_INVALID",
            f"usage.output_tokens={usage['output_tokens']} != output_tokens={output_tokens}",
        )
    if usage["total_tokens"] < usage["input_tokens"] + usage["output_tokens"]:
        raise SealError("CANARY_USAGE_INVALID", "total_tokens incomplete")
    if usage["total_tokens"] <= 0:
        raise SealError("CANARY_USAGE_INVALID", "total_tokens<=0")


def validate_engineering_canary_receipt(
    receipt: dict[str, Any],
    *,
    posture: dict[str, Any],
    now: dt.datetime | None = None,
    max_age_seconds: int = MAX_TTL_SECONDS,
) -> dict[str, Any]:
    """Strict engineering-canary contract for seal eligibility (real provider effect)."""
    _validate_common_nonclaims(receipt, schema=CANARY_SCHEMA)
    _require_keys(
        receipt,
        required=CANARY_REQUIRED_KEYS,
        allowed=CANARY_ALLOWED_KEYS,
        reason_missing="CANARY_RECEIPT_MISSING_KEY",
        reason_unknown="CANARY_RECEIPT_UNKNOWN_KEY",
    )
    if receipt.get("path_class") != "engineering_canary":
        raise SealError("EVIDENCE_PATH_CLASS_INVALID", str(receipt.get("path_class")))
    if receipt.get("status") != "observed":
        raise SealError("CANARY_STATUS_INVALID", str(receipt.get("status")))
    # Reject CONNECT-only / HTTP-only / planned / partial semantics.
    if receipt.get("real_provider_call") is not True:
        raise SealError("CANARY_REAL_PROVIDER_CALL_REQUIRED", "real_provider_call")
    if receipt.get("provider_effect_verified") is not True:
        raise SealError("CANARY_PROVIDER_EFFECT_REQUIRED", "provider_effect_verified")
    if receipt.get("connect_only") is True:
        raise SealError("CANARY_CONNECT_ONLY_REJECTED", "connect_only")
    if receipt.get("http_only") is True:
        raise SealError("CANARY_HTTP_ONLY_REJECTED", "http_only")
    if receipt.get("requested_model") != REQUESTED_MODEL:
        raise SealError("CANARY_MODEL_INVALID", str(receipt.get("requested_model")))
    if receipt.get("observed_backend_model") != OBSERVED_BACKEND_MODEL:
        raise SealError("CANARY_BACKEND_MODEL_INVALID", str(receipt.get("observed_backend_model")))
    if receipt.get("stop_reason") != STOP_REASON:
        raise SealError("CANARY_STOP_REASON_INVALID", str(receipt.get("stop_reason")))
    output_tokens = receipt.get("output_tokens")
    if type(output_tokens) is not int or isinstance(output_tokens, bool) or output_tokens <= 0:
        raise SealError("CANARY_OUTPUT_TOKENS_INVALID", str(output_tokens))
    if receipt.get("usage_accounting_complete") is not True:
        raise SealError("CANARY_USAGE_INCOMPLETE", "usage_accounting_complete")
    _validate_usage(receipt.get("usage"), output_tokens=output_tokens)
    if receipt.get("endpoint_host") != ENDPOINT_HOST:
        raise SealError("CANARY_ENDPOINT_HOST_INVALID", str(receipt.get("endpoint_host")))
    _bind_posture_identities(receipt, posture, reason="CANARY_RECEIPT_POSTURE_MISMATCH")
    canary_image = receipt.get("canary_image_id")
    if not isinstance(canary_image, str) or not IMAGE_ID.fullmatch(canary_image):
        raise SealError("CANARY_IMAGE_ID_INVALID", str(canary_image))
    _require_true(
        receipt,
        "internal_network_only",
        "auth_mounted_read_only",
        reason="CANARY_ISOLATION_INVALID",
    )
    _require_false(
        receipt,
        "auth_content_persisted",
        "raw_output_persisted",
        reason="CANARY_PERSISTENCE_FORBIDDEN",
    )
    _require_false(
        receipt,
        "research_invoked",
        "is_research_call",
        "scientific_research",
        "masquerades_as_research",
        "scientific_adoption",
        reason="EVIDENCE_CLAIM_FORBIDDEN",
    )
    # positive_token_value must never carry secret material; only null allowed if present.
    if "positive_token_value" in receipt and receipt.get("positive_token_value") is not None:
        raise SealError("CANARY_TOKEN_VALUE_FORBIDDEN", "positive_token_value")
    clock = now or dt.datetime.now(dt.UTC)
    _validate_observation_freshness(
        receipt.get("observed_at"),
        now=clock,
        max_age_seconds=max_age_seconds,
    )
    identities = receipt.get("object_identities")
    if identities is not None:
        if not isinstance(identities, dict):
            raise SealError("CANARY_RECEIPT_POSTURE_MISMATCH", "object_identities")
        for key in (
            "internal_network_id",
            "proxy_container_id",
            "proxy_image_id",
            "allowlist_sha256",
            "proxy_config_sha256",
        ):
            if key in identities and identities.get(key) != receipt.get(key):
                raise SealError("CANARY_RECEIPT_POSTURE_MISMATCH", f"object_identities.{key}")
    return receipt


def _validate_evidence_legacy_shape(
    receipt: dict[str, Any], *, schema: str, path_class: str | None
) -> None:
    """Minimal non-claim / schema shape retained for unit helpers and reject paths."""
    if receipt.get("schema_version") != schema:
        raise SealError("EVIDENCE_SCHEMA_INVALID", str(receipt.get("schema_version")))
    if receipt.get("completion_claim_allowed") is not False:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "completion_claim_allowed")
    if receipt.get("authority") is not False:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "authority")
    if receipt.get("science_restored") is True or receipt.get("parent_complete") is True:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "science_or_parent")
    if receipt.get("scientific_research") is True:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "scientific_research")
    if path_class is not None and receipt.get("path_class") != path_class:
        raise SealError("EVIDENCE_PATH_CLASS_INVALID", str(receipt.get("path_class")))
    if schema == CANARY_SCHEMA and receipt.get("masquerades_as_research") is True:
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "masquerades_as_research")
    if str(receipt.get("schema_version", "")).startswith("xinao.skill_research_receipt"):
        raise SealError("EVIDENCE_CLAIM_FORBIDDEN", "scientific_research_receipt")


def _validate_evidence(
    receipt: dict[str, Any],
    *,
    schema: str,
    path_class: str | None,
    posture: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    max_age_seconds: int = MAX_TTL_SECONDS,
) -> None:
    """Validate evidence. When posture is provided, enforce full semantic seal contract."""
    _validate_evidence_legacy_shape(receipt, schema=schema, path_class=path_class)
    if posture is None:
        return
    if schema == NEGATIVE_SCHEMA:
        validate_negative_suite_receipt(
            receipt, posture=posture, now=now, max_age_seconds=max_age_seconds
        )
        return
    if schema == CANARY_SCHEMA:
        validate_engineering_canary_receipt(
            receipt, posture=posture, now=now, max_age_seconds=max_age_seconds
        )
        return


def _relative_under(root: Path, path: Path) -> str:
    root_abs = Path(os.path.abspath(root))
    path_abs = Path(os.path.abspath(path))
    try:
        rel = path_abs.relative_to(root_abs)
    except ValueError as exc:
        raise SealError("EVIDENCE_PATH_ESCAPE", str(path)) from exc
    text = rel.as_posix()
    if any(part in {"", ".", ".."} for part in rel.parts):
        raise SealError("EVIDENCE_PATH_ESCAPE", text)
    return text


def build_seal(
    *,
    posture_path: Path,
    negative_receipt_path: Path,
    canary_receipt_path: Path,
    ttl_seconds: int,
    sealed_at: dt.datetime | None = None,
) -> dict[str, Any]:
    if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        raise SealError("SEAL_TTL_INVALID", str(ttl_seconds))
    posture_raw = posture_path.read_bytes()
    posture = json.loads(posture_raw.decode("utf-8"))
    if not isinstance(posture, dict) or posture.get("schema_version") != POSTURE_SCHEMA:
        raise SealError("POSTURE_INVALID", str(posture_path))
    _reject_secrets(posture_raw.decode("utf-8"))

    negative_raw = negative_receipt_path.read_bytes()
    canary_raw = canary_receipt_path.read_bytes()
    negative = json.loads(negative_raw.decode("utf-8"))
    canary = json.loads(canary_raw.decode("utf-8"))
    if not isinstance(negative, dict) or not isinstance(canary, dict):
        raise SealError("EVIDENCE_INVALID", "receipts must be objects")
    _reject_secrets(negative_raw.decode("utf-8"))
    _reject_secrets(canary_raw.decode("utf-8"))

    sealed = sealed_at or dt.datetime.now(dt.UTC)
    # Semantic validation BEFORE Docker observation / seal write.
    _validate_evidence(
        negative,
        schema=NEGATIVE_SCHEMA,
        path_class="negative_suite",
        posture=posture,
        now=sealed,
        max_age_seconds=ttl_seconds,
    )
    _validate_evidence(
        canary,
        schema=CANARY_SCHEMA,
        path_class="engineering_canary",
        posture=posture,
        now=sealed,
        max_age_seconds=ttl_seconds,
    )

    docker = _docker()
    engine = _engine_identity(docker)
    # Direct observation of sealed objects (replacement resistance at seal time).
    network_id = str(posture["internal_network_id"])
    proxy_id = str(posture["proxy_container_id"])
    network = json.loads(_run([docker, "network", "inspect", network_id]))[0]
    proxy = json.loads(_run([docker, "container", "inspect", proxy_id]))[0]
    if network.get("Internal") is not True:
        raise SealError("NETWORK_NOT_INTERNAL", str(network.get("Internal")))
    if not (proxy.get("State") or {}).get("Running"):
        raise SealError("PROXY_NOT_RUNNING", str((proxy.get("State") or {}).get("Status")))
    live_image = str(proxy.get("Image", ""))
    if live_image != posture.get("proxy_image_id") and not (
        live_image.startswith(str(posture.get("proxy_image_id")))
        or str(posture.get("proxy_image_id")).startswith(live_image)
    ):
        raise SealError("PROXY_IMAGE_MISMATCH", live_image)
    conf = subprocess.run(
        [docker, "exec", proxy_id, "/bin/cat", "/var/spool/squid/squid.conf"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if conf.returncode != 0 or not conf.stdout:
        raise SealError("LIVE_CONFIG_UNOBSERVED", conf.stderr[:500].decode("utf-8", "replace"))
    live_conf_sha = _sha256_bytes(conf.stdout)
    if live_conf_sha != posture.get("proxy_config_sha256"):
        raise SealError(
            "LIVE_CONFIG_HASH_MISMATCH",
            f"live={live_conf_sha} posture={posture.get('proxy_config_sha256')}",
        )

    egress_root = posture_path.parent
    expires = sealed + dt.timedelta(seconds=ttl_seconds)
    seal = {
        "schema_version": SCHEMA,
        "provider_egress_live_verified": True,
        "posture_sha256": _sha256_bytes(posture_raw),
        "posture_relative_path": "current_posture.v1.json",
        "negative_suite_receipt_sha256": _sha256_bytes(negative_raw),
        "negative_suite_receipt_relative_path": _relative_under(egress_root, negative_receipt_path),
        "positive_canary_receipt_sha256": _sha256_bytes(canary_raw),
        "positive_canary_receipt_relative_path": _relative_under(egress_root, canary_receipt_path),
        "allowlist_sha256": posture["allowlist_sha256"],
        "proxy_config_sha256": posture["proxy_config_sha256"],
        "proxy_container_id": str(proxy.get("Id") or posture["proxy_container_id"]),
        "proxy_image_id": posture["proxy_image_id"],
        "internal_network_id": str(network.get("Id") or posture["internal_network_id"]),
        "internal_network_name": posture["internal_network_name"],
        "external_network_name": posture.get("external_network_name")
        or "xinao_provider_egress_ext",
        "proxy_endpoint": posture["proxy_endpoint"],
        "docker_engine_observational_id": engine["docker_engine_observational_id"],
        "docker_server_version": engine["docker_server_version"],
        "docker_ostype": engine["docker_ostype"],
        "sealed_at": sealed.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "completion_claim_allowed": False,
        "authority": False,
        "science_restored": False,
        "parent_complete": False,
        "secrets_present": False,
        "trust_boundary": TRUST_BOUNDARY,
    }
    for field in ("allowlist_sha256", "proxy_config_sha256"):
        if not isinstance(seal[field], str) or not HEX_SHA256.fullmatch(seal[field]):
            raise SealError("SEAL_HASH_INVALID", field)
    return seal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seal XINAO researcher egress live boundary")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path(
            os.environ.get(
                "XINAO_EGRESS_STATE_ROOT",
                r"D:/XINAO_RESEARCH_RUNTIME/state/xinao_skill/researcher_container/egress",
            )
        ),
    )
    parser.add_argument("--posture", type=Path, default=None)
    parser.add_argument("--negative-receipt", type=Path, required=True)
    parser.add_argument("--canary-receipt", type=Path, required=True)
    parser.add_argument("--ttl-seconds", type=int, default=3600)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    posture_path = args.posture or (args.state_root / "current_posture.v1.json")
    seal_path = args.state_root / "current_live_seal.v1.json"
    try:
        if args.validate_only:
            if not seal_path.is_file():
                raise SealError("EGRESS_LIVE_SEAL_MISSING", str(seal_path))
            seal = _load_json(seal_path)
            if seal.get("schema_version") != SCHEMA:
                raise SealError("EGRESS_LIVE_SEAL_INVALID", str(seal.get("schema_version")))
            if seal.get("provider_egress_live_verified") is not True:
                raise SealError("EGRESS_LIVE_SEAL_INVALID", "provider_egress_live_verified")
            print(
                json.dumps(
                    {
                        "status": "VALID_OBSERVED",
                        "seal_path": str(seal_path),
                        "seal_sha256": _sha256_bytes(seal_path.read_bytes()),
                        "completion_claim_allowed": False,
                        "authority": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        seal = build_seal(
            posture_path=posture_path,
            negative_receipt_path=args.negative_receipt,
            canary_receipt_path=args.canary_receipt,
            ttl_seconds=args.ttl_seconds,
        )
        _write_json_atomic(seal_path, seal)
        print(
            json.dumps(
                {
                    "status": "SEALED",
                    "seal_path": str(seal_path),
                    "seal_sha256": _sha256_bytes(seal_path.read_bytes()),
                    "expires_at": seal["expires_at"],
                    "provider_egress_live_verified": True,
                    "completion_claim_allowed": False,
                    "authority": False,
                    "science_restored": False,
                    "parent_complete": False,
                    "source_lock_mutated": False,
                    "trust_boundary": TRUST_BOUNDARY,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except SealError as error:
        print(
            json.dumps(
                {
                    "status": "SEAL_FAILED",
                    "reason_code": error.reason_code,
                    "detail": error.detail,
                    "completion_claim_allowed": False,
                    "authority": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
