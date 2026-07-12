from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from xinao_market_lab.public_sources import (
    P6JudgeGate,
    P6SourceSpec,
    _selector,
    _sha256_bytes,
    _static_markup_text,
    _verify_selector,
    p6_source_specs,
)


def test_p6_source_role_allowlist_and_claim_eligibility_are_frozen() -> None:
    sources = p6_source_specs()

    assert [source.source_id for source in sources] == [
        "gov_pj_787749",
        "dicj_legislation_index",
        "dicj_pacapio",
        "hkjc_marksix_rules_hub",
    ]
    assert all(source.requested_url.startswith("https://") for source in sources)
    assert all(source.allowed_redirect_urls == () for source in sources)
    assert [source.source_id for source in sources if source.macau_product_claim_eligible] == [
        "gov_pj_787749"
    ]
    assert sources[-1].non_operator_reference is True
    assert all(source.target_ruleclaim_vote_weight == 0 for source in sources)

    promoted = sources[-1].model_dump(mode="python")
    promoted["non_operator_reference"] = False
    with pytest.raises(ValidationError, match="non-operator"):
        P6SourceSpec.model_validate(promoted, strict=True)


def test_static_markup_text_excludes_nonstatic_and_hidden_claims() -> None:
    body = b"""
    <html><body>
      <p>PUBLIC CLAIM</p>
      <script>FORBIDDEN SCRIPT CLAIM</script>
      <style>.x { content: "FORBIDDEN STYLE CLAIM"; }</style>
      <div hidden>FORBIDDEN HIDDEN CLAIM</div>
      <div aria-hidden="true">FORBIDDEN ARIA CLAIM</div>
      <div style="display: none">FORBIDDEN CSS CLAIM</div>
      <p>SECOND PUBLIC CLAIM</p>
    </body></html>
    """

    text = _static_markup_text(body, "utf-8")

    assert text == "PUBLIC CLAIM SECOND PUBLIC CLAIM"
    assert "FORBIDDEN" not in text


def test_p6_text_quote_and_position_replay_with_repeated_context() -> None:
    text = "prefix repeated phrase middle repeated phrase suffix"
    selector = _selector(text, "repeated phrase")
    partial = {
        "schema_version": 1,
        "sequence": 0,
        "evidence_bundle_id": "bundle-p6-" + "a" * 24,
        "protocol_hash": "b" * 64,
        "evidence_id": "evidence-p6-test",
        "source_id": "test",
        "source_role": "macao_government_law_enforcement_notice",
        "body_sha256": "c" * 64,
        "claim_scope": "macau_official_product_status",
        "selected_text": "repeated phrase",
        "selected_text_sha256": _sha256_bytes(b"repeated phrase"),
        "selector": selector.model_dump(mode="json"),
        "interpretation_code": "direct_regulator_denial_primary_evidence",
        "previous_hash": "0" * 64,
    }
    record_hash = hashlib.sha256(
        (
            __import__("json").dumps(
                partial,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    ).hexdigest()
    from xinao_market_lab.public_sources import P6EvidenceRecord

    record = P6EvidenceRecord.model_validate(
        {**partial, "record_hash": record_hash},
        strict=True,
    )
    _verify_selector(text, record)


def test_p6_judge_rejects_capability_escalation() -> None:
    judge = P6JudgeGate(
        evidence_bundle_id="bundle-p6-" + "a" * 24,
        protocol_hash="b" * 64,
        rule_claim_statuses={
            "payout_basis": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
            "special_two_sided_49_policy": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
        },
        checks={"all": True},
    )
    value = judge.model_dump(mode="json")
    value["operator_rule_truth_verified"] = True

    with pytest.raises(ValidationError):
        P6JudgeGate.model_validate(value, strict=True)
