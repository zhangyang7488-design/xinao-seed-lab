from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from xinao.canonical import (
    ACCOUNTING_DECIMAL,
    PROBABILITY_DECIMAL,
    canonical_dumps,
    canonical_loads,
    canonical_sha256,
    format_decimal,
    format_decimal_exact,
    format_utc,
    generate_uuid7,
    is_uuid7,
    parse_utc,
)
from xinao.contracts import CommonEnvelope

UUID7_A = "0190f9c0-6f4c-7a11-8b22-334455667788"
UUID7_B = "0190f9c0-6f4c-7a12-8b22-334455667788"


def envelope(**overrides: object) -> CommonEnvelope:
    values: dict[str, object] = {
        "entity_id": UUID7_A,
        "entity_type": "EvidenceBundle",
        "parent_ids": (),
        "correlation_id": UUID7_B,
        "causation_id": None,
        "created_at": datetime(2026, 7, 14, 0, 0, 0, 123000, tzinfo=UTC),
        "effective_at": None,
        "knowledge_cutoff_at": datetime(2026, 7, 13, 23, 59, 59, tzinfo=UTC),
        "source_refs": ("authority:macaujc2",),
        "artifact_refs": (),
        "git_sha": "f" * 40,
        "config_hash": "a" * 64,
        "rule_version": None,
        "idempotency_key": "evidence-fixture-1",
        "producer": "unit-test",
        "status": "VERIFIED",
    }
    values.update(overrides)
    return CommonEnvelope(**values)


def test_decimal_profiles_are_fixed_and_explicit() -> None:
    assert format_decimal("0.1234567890126", PROBABILITY_DECIMAL) == "0.123456789013"
    assert format_decimal("12.34565", ACCOUNTING_DECIMAL) == "12.3457"
    assert format_decimal("-0", ACCOUNTING_DECIMAL) == "0.0000"
    assert format_decimal_exact(Decimal("100.2500")) == "100.25"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN")])
def test_decimal_profile_rejects_float_and_non_finite(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        format_decimal(value, ACCOUNTING_DECIMAL)  # type: ignore[arg-type]


def test_timestamp_profile_normalizes_aware_values_and_rejects_naive() -> None:
    local = datetime(2026, 7, 14, 8, 0, 0, 123000, tzinfo=timezone(timedelta(hours=8)))
    assert format_utc(local) == "2026-07-14T00:00:00.123Z"
    assert parse_utc("2026-07-14T00:00:00.123Z") == datetime(
        2026, 7, 14, 0, 0, 0, 123000, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="naive"):
        format_utc(datetime(2026, 7, 14))
    with pytest.raises(ValueError, match="millisecond"):
        format_utc(datetime(2026, 7, 14, microsecond=1, tzinfo=UTC))


def test_jcs_orders_keys_and_hashes_utf8_bytes() -> None:
    left = {"z": 1, "a": Decimal("1.20"), "time": datetime(2026, 7, 14, tzinfo=UTC)}
    right = {"time": datetime(2026, 7, 14, tzinfo=UTC), "a": Decimal("1.2"), "z": 1}
    expected = b'{"a":"1.2","time":"2026-07-14T00:00:00.000Z","z":1}'
    assert canonical_dumps(left) == canonical_dumps(right) == expected
    assert canonical_sha256(left) == canonical_sha256(right)


def test_jcs_rejects_duplicate_keys_non_finite_and_non_string_keys() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        canonical_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="non-finite"):
        canonical_loads('{"a":NaN}')
    with pytest.raises(ValueError, match="NaN"):
        canonical_dumps({"a": float("nan")})
    with pytest.raises(TypeError, match="keys"):
        canonical_dumps({1: "not allowed"})
    with pytest.raises(ValueError):
        canonical_dumps({"unsafe_integer": 2**53})


def test_uuid7_generator_and_validator_do_not_claim_global_order() -> None:
    generated = generate_uuid7()
    assert is_uuid7(generated)
    assert UUID(generated).version == 7
    assert not is_uuid7("e9ab9d1c-6c31-4e11-a142-928c625d1b18")


def test_common_envelope_hash_excludes_only_its_self_hash() -> None:
    raw = envelope()
    sealed = raw.with_content_hash()
    assert sealed.content_hash == raw.compute_content_hash()
    assert CommonEnvelope.model_validate(sealed.model_dump(mode="json")) == sealed
    changed = envelope(status="REJECTED")
    assert changed.compute_content_hash() != sealed.content_hash


def test_common_envelope_rejects_wrong_hash_uuid_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        envelope(content_hash="0" * 64)
    with pytest.raises(ValidationError, match="pattern"):
        envelope(entity_id="e9ab9d1c-6c31-4e11-a142-928c625d1b18")
    with pytest.raises(ValidationError, match="Extra inputs"):
        envelope(unknown="not allowed")


def test_common_envelope_json_schema_exposes_uuid_and_hash_patterns() -> None:
    schema = CommonEnvelope.model_json_schema()
    properties = schema["properties"]
    assert "-7" in properties["entity_id"]["pattern"]
    assert properties["git_sha"]["pattern"] == "^[0-9a-f]{40}$"
    assert properties["config_hash"]["pattern"] == "^[0-9a-f]{64}$"
