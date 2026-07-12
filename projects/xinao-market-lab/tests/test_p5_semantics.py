from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xinao_market_lab.inputs import InputLayout, build_snapshot_manifest
from xinao_market_lab.models import P5EvidenceRecord, P5JudgeGateResult, P5ProtocolSpec
from xinao_market_lab.semantics import (
    EXPECTED_CANONICAL_TERM_COUNTS,
    EXPECTED_SOURCE_PATHS,
    QUERY_TERMS,
    _pointer_tokens,
    _resolve_pointer,
    build_p5_acceptance_pin,
    build_p5_protocol,
    build_semantics_artifacts,
    build_source_inventory,
    evidence_ledger_bytes,
    scan_packet,
    verify_selector,
)

INPUT_ROOT = Path(r"C:\Users\xx363\Desktop\主线\新澳数据包")
P4_RUN = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-acceptance-a-20260711"
)
P4_ANCHOR = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-exact-null-contamination-structure-trusted-anchor-20260711.json"
)
ADMIN_ACCEPTANCE = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs\p4-admin-acceptance-20260711\admin_acceptance.json"
)


def _actual_protocol():
    layout = InputLayout.from_root(INPUT_ROOT)
    snapshot = build_snapshot_manifest(layout)
    inventory = build_source_inventory(snapshot)
    acceptance = build_p5_acceptance_pin(
        p4_run_dir=P4_RUN,
        trusted_anchor_path=P4_ANCHOR,
        admin_acceptance_path=ADMIN_ACCEPTANCE,
    )
    protocol = build_p5_protocol(
        snapshot_id=snapshot["snapshot_id"],
        p4_acceptance=acceptance,
        source_inventory=inventory,
    )
    return layout, snapshot, inventory, protocol


@pytest.mark.skipif(not INPUT_ROOT.is_dir(), reason="canonical input is unavailable")
def test_exact_inventory_roles_exclusions_and_query_surface_are_frozen() -> None:
    _layout, _snapshot, inventory, protocol = _actual_protocol()
    assert tuple(item.relative_path for item in inventory) == EXPECTED_SOURCE_PATHS
    assert len(inventory) == 33
    assert sum(item.disposition == "SCANNED" for item in inventory) == 27
    assert sum(item.disposition == "EXCLUDED" for item in inventory) == 6
    assert sum(item.source_role == "human_context_hypothesis" for item in inventory) == 5
    assert sum(item.source_role == "package_manifest" for item in inventory) == 3
    assert sum(item.source_role == "captured_page_snapshot" for item in inventory) == 11
    assert sum(item.source_role == "derived_catalog" for item in inventory) == 8
    assert (
        next(item for item in inventory if item.relative_path.endswith("raw/盘口_菜单映射.txt")).document_kind
        == "json"
    )
    assert (
        next(item for item in inventory if item.relative_path.endswith("scripts/load_bundle.py")).disposition
        == "EXCLUDED"
    )
    assert protocol.spec.query_terms == QUERY_TERMS

    tampered = protocol.spec.model_dump(mode="python")
    tampered["query_terms"] = tuple(reversed(QUERY_TERMS))
    with pytest.raises(ValidationError, match="frozen 22-term"):
        P5ProtocolSpec.model_validate(tampered, strict=True)

    role_escalation = protocol.spec.model_dump(mode="python")
    role_escalation["source_inventory"][1]["source_role"] = "operator_truth"
    with pytest.raises(ValidationError):
        P5ProtocolSpec.model_validate(role_escalation, strict=True)


def test_rfc6901_pointer_is_strict_and_round_trips_escaped_members() -> None:
    value = {"a/b": {"m~n": ["zero", "one"]}}
    pointer = "/a~1b/m~0n/1"
    assert _pointer_tokens(pointer) == ("a/b", "m~n", "1")
    assert _resolve_pointer(value, pointer) == "one"
    for invalid in ("a/b", "/bad~2escape", "/a~", "/a~1b/m~0n/01", "/a~1b/m~0n/-"):
        with pytest.raises(ValueError):
            _resolve_pointer(value, invalid)
    with pytest.raises(ValueError, match="out of range"):
        _resolve_pointer(value, "/a~1b/m~0n/9")


@pytest.mark.skipif(
    not all(path.exists() for path in (INPUT_ROOT, P4_RUN, P4_ANCHOR, ADMIN_ACCEPTANCE)),
    reason="canonical P4/P5 inputs are unavailable",
)
def test_actual_scan_is_complete_hash_chained_and_every_selector_replays() -> None:
    layout, _snapshot, _inventory, protocol = _actual_protocol()
    summary, records = scan_packet(root=layout.root, protocol=protocol)
    assert summary["source_file_count"] == 33
    assert summary["scanned_file_count"] == 27
    assert summary["excluded_file_count"] == 6
    assert summary["term_counts"] == EXPECTED_CANONICAL_TERM_COUNTS
    assert len(records) == 20
    assert len(evidence_ledger_bytes(records).splitlines()) == 20
    for record in records:
        verify_selector(root=layout.root, record=record)

    p2_surface, claim_register, classification_register = build_semantics_artifacts(
        layout=layout,
        snapshot_id=protocol.spec.input_snapshot_id,
        p4_acceptance=protocol.spec.p4_acceptance,
        records=records,
        scan_summary=summary,
    )
    pinned_catalog = json.loads(
        (Path(protocol.spec.p4_acceptance.p2_run_directory) / "rule_catalog.json").read_text(encoding="utf-8")
    )
    assert [row["claim_id"] for row in p2_surface["unresolved_rule_claims"]] == [
        "claim-payout-basis-unresolved-v1",
        "claim-special-two-sided-49-unresolved-v1",
    ]
    assert [row["claim_id"] for row in claim_register["rule_claims"]] == [
        "claim-payout-basis-unresolved-v1",
        "claim-special-two-sided-49-unresolved-v1",
    ]
    assert len(classification_register["rows"]) == 136
    assert p2_surface["unresolved_rule_claims"] == [
        row for row in pinned_catalog["claims"] if row["status"] == "unresolved"
    ]
    assert classification_register["rows"] == [
        {
            **row,
            "p5_accounting_status": (
                "IMPLEMENTED_REFERENCE_ACCOUNTED"
                if row["status"] == "IMPLEMENTED"
                else "UNRESOLVED_ACCOUNTED_NO_COMPILATION"
            ),
        }
        for row in pinned_catalog["typed_rule_bundle"]["classification"]["rows"]
    ]

    payload = records[0].model_dump(mode="python")
    payload["selector"] = {**records[0].selector.model_dump(mode="python"), "undeclared": True}
    with pytest.raises(ValidationError):
        P5EvidenceRecord.model_validate(payload, strict=True)


def test_judge_schema_rejects_semantic_or_economic_escalation() -> None:
    valid = P5JudgeGateResult(
        catalog_id="catalog-p5-" + "a" * 24,
        protocol_hash="b" * 64,
        semantics_status="SEMANTICS_STILL_UNRESOLVED",
        rule_claim_statuses={
            "payout_basis": "INSUFFICIENT_LOCAL_EVIDENCE",
            "special_two_sided_49_policy": "INSUFFICIENT_LOCAL_EVIDENCE",
        },
        checks={"catalog": True},
    )
    invalid = valid.model_dump(mode="python")
    invalid["ranking_permitted"] = True
    with pytest.raises(ValidationError):
        P5JudgeGateResult.model_validate(invalid, strict=True)

    undeclared = valid.model_dump(mode="python")
    undeclared["rule_claim_statuses"]["label_and_two_sided_paths"] = "CONFLICT"
    with pytest.raises(ValidationError):
        P5JudgeGateResult.model_validate(undeclared, strict=True)
