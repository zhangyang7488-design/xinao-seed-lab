from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from xinao.canonical import canonical_dumps, canonical_sha256, format_decimal_exact, generate_uuid7


@given(
    st.dictionaries(
        st.text(min_size=1),
        st.integers(min_value=-(2**53) + 1, max_value=2**53 - 1),
        max_size=20,
    )
)
@settings(max_examples=100)
def test_mapping_insertion_order_never_changes_canonical_bytes(values: dict[str, int]) -> None:
    reversed_values = dict(reversed(list(values.items())))
    assert canonical_dumps(values) == canonical_dumps(reversed_values)
    assert canonical_sha256(values) == canonical_sha256(reversed_values)


@given(
    st.decimals(
        allow_nan=False,
        allow_infinity=False,
        min_value=Decimal("-999999999999999999"),
        max_value=Decimal("999999999999999999"),
        places=12,
    )
)
@settings(max_examples=100)
def test_exact_decimal_string_roundtrips_without_binary_float(value: Decimal) -> None:
    rendered = format_decimal_exact(value)
    assert "e" not in rendered.lower()
    assert Decimal(rendered) == value


@given(st.sampled_from([float("nan"), float("inf"), float("-inf")]))
def test_non_finite_float_always_fails_closed(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_dumps({"value": value})


def test_generated_uuid7_values_are_strictly_increasing_in_one_locked_process() -> None:
    values = [generate_uuid7() for _ in range(100)]
    assert values == sorted(values)
    assert len(values) == len(set(values))


def test_datetime_is_part_of_the_canonical_domain_conversion() -> None:
    value = {"at": datetime(2026, 7, 14, microsecond=123000, tzinfo=UTC)}
    assert canonical_dumps(value) == b'{"at":"2026-07-14T00:00:00.123Z"}'
