from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from xinao.contracts import AuthorityContract, DatasetSnapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "domain"


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_authority_and_dataset_fixed_identity_contract() -> None:
    authority = AuthorityContract.model_validate(load("authority_contract.json"))
    dataset = DatasetSnapshot.model_validate(load("dataset_snapshot.json"))
    assert authority.contract_ref == dataset.authority_contract_ref
    assert authority.source_id == dataset.source_id == "macaujc2"
    assert dataset.record_count == dataset.human_record_lines == dataset.json_record_lines == 913
    assert dataset.dataset_sha256 == (
        "57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"
    )
    assert dataset.duplicate_policy == "KEEP_ALL"
    assert authority.with_content_hash().content_hash
    assert dataset.with_content_hash().content_hash


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("record_count", 912),
        ("human_record_lines", 914),
        ("dataset_sha256", "0" * 64),
        ("duplicate_policy", "DEDUPLICATE"),
        ("period_end", "2026-07-02"),
    ],
)
def test_dataset_fixed_values_fail_closed(field: str, invalid: object) -> None:
    payload = copy.deepcopy(load("dataset_snapshot.json"))
    payload[field] = invalid
    with pytest.raises(ValidationError):
        DatasetSnapshot.model_validate(payload)


def test_generated_json_schemas_validate_fixtures() -> None:
    pairs = [
        (AuthorityContract, load("authority_contract.json")),
        (DatasetSnapshot, load("dataset_snapshot.json")),
    ]
    for model, fixture in pairs:
        errors = list(Draft202012Validator(model.model_json_schema()).iter_errors(fixture))
        assert errors == []
