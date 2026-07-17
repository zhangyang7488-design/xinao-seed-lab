from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation.f1_replay import (
    CASE_KIND_ORDER,
    COMPOSITE_FAMILIES,
    FAMILY_ORDER,
    F1RepresentativeReplayEvidence,
    compile_f1_replay_evidence,
)
from xinao.foundation.selection_manifest import load_play_catalog
from xinao.foundation.semantics_registry import (
    compile_default_semantics_registry,
    compile_semantics_registry,
)
from xinao.foundation.world_compile import (
    DEFAULT_AUTHORITY_DATASET_PATH,
    compile_functional_world,
)


@pytest.fixture(scope="module")
def registry():
    return compile_default_semantics_registry()


@pytest.fixture(scope="module")
def formal_world(registry):
    if not DEFAULT_AUTHORITY_DATASET_PATH.is_file():
        pytest.skip("formal 913-draw authority text is not mounted")
    return compile_functional_world(registry).world_snapshot


@pytest.fixture(scope="module")
def evidence(registry, formal_world):
    return compile_f1_replay_evidence(registry, formal_world)


def test_all_13_families_have_asserted_positive_negative_and_boundary_evidence(
    evidence,
) -> None:
    assert evidence.result_status == "VERIFIED"
    assert evidence.family_count == 13
    assert evidence.case_count == 39
    assert evidence.family_case_counts == {family: 3 for family in FAMILY_ORDER}
    assert evidence.representative_replay_summary.result_status == "VERIFIED"
    assert evidence.representative_replay_summary.executed_case_count == 39
    assert evidence.representative_replay_summary.asserted_pass_count == 39
    assert evidence.representative_replay_summary.asserted_fail_count == 0
    assert all(
        family.status == "VERIFIED"
        for family in evidence.representative_replay_summary.family_coverage
    )

    kinds: dict[str, list[str]] = defaultdict(list)
    for item in evidence.cases:
        kinds[item.result.family_id].append(item.case.case_kind)
        assert item.result.assertion_status == "PASS"
        assert item.result.outcome == item.case.expected_outcome
        assert item.derivation_basis
    assert kinds == {family: list(CASE_KIND_ORDER) for family in FAMILY_ORDER}
    assert all(
        item.result.outcome == "HIT" for item in evidence.cases if item.case.case_kind == "POSITIVE"
    )
    assert all(
        item.result.outcome == "MISS"
        for item in evidence.cases
        if item.case.case_kind == "NEGATIVE"
    )


def test_evidence_binds_active_world_and_lazy_atomic_ticket_structure(
    evidence, registry, formal_world
) -> None:
    assert evidence.active_semantics_hash == registry.active_physical_semantics_hash
    assert evidence.source_world_snapshot_hash == formal_world.content_hash
    assert evidence.source_event_matrix_snapshot_hash == formal_world.event_matrix_snapshot_hash
    assert (
        evidence.active_selection_domain_structural_hash
        == formal_world.active_selection_domain_structural_hash
    )
    assert (
        evidence.active_atomic_ticket_binding_structural_hash
        == formal_world.active_atomic_ticket_binding_structural_hash
    )
    composite = [item for item in evidence.cases if item.result.family_id in COMPOSITE_FAMILIES]
    non_composite = [
        item for item in evidence.cases if item.result.family_id not in COMPOSITE_FAMILIES
    ]
    assert len(composite) == 7 * 3
    assert all(item.lazy_ticket_selection is not None for item in composite)
    assert all(item.atomic_ticket_binding_hash for item in composite)
    assert all(item.result.atomic_ticket_binding_hash for item in composite)
    assert all(item.lazy_ticket_selection is None for item in non_composite)
    assert all(item.atomic_ticket_binding_hash is None for item in non_composite)
    assert all(item.expanded_atomic_tickets_materialized is False for item in evidence.cases)
    assert evidence.expanded_atomic_tickets_materialized is False
    assert evidence.conceptual_atomic_ticket_count == 21_652_542_248
    assert evidence.foundation_complete is False
    assert "outside this object" in evidence.scope_limitation


def test_b_quote_source_change_cannot_propagate_into_replay_evidence_hash(
    evidence, formal_world
) -> None:
    changed = deepcopy(load_play_catalog())
    b_row = next(row for row in changed["entries"] if row["baseline_id"] == "BO0013")
    b_row["baseline_odds_components"] = ["41.999"]
    changed["entries"] = sorted(changed["entries"], key=lambda row: row["baseline_id"])
    body = {key: value for key, value in changed.items() if key != "content_hash"}
    changed["content_hash"] = canonical_sha256(body)
    changed_registry = compile_semantics_registry(changed)

    second = compile_f1_replay_evidence(changed_registry, formal_world)
    assert second.content_hash == evidence.content_hash
    assert second.ordered_case_digest == evidence.ordered_case_digest


def test_boundary_matrix_covers_voids_endpoints_and_lazy_domain_edges(evidence) -> None:
    boundaries = {
        item.result.family_id: item for item in evidence.cases if item.case.case_kind == "BOUNDARY"
    }
    assert set(boundaries) == set(FAMILY_ORDER)
    assert Counter(item.result.outcome for item in boundaries.values()) == {
        "HIT": 5,
        "MISS": 4,
        "VOID": 4,
    }
    assert boundaries["special-number"].case.selection == ("合单",)
    assert boundaries["regular-number"].case.selection == (49,)
    assert boundaries["regular-position-special"].result.outcome == "VOID"
    assert boundaries["linked-number"].case.selection == (48, 49)
    assert boundaries["six-zodiac"].result.outcome == "VOID"
    assert boundaries["parlay"].lazy_ticket_selection is not None
    assert boundaries["parlay"].lazy_ticket_selection.selection_id == "P01=ODD+P02=ODD"
    assert boundaries["special-regular-hit"].lazy_ticket_selection is not None
    assert boundaries["special-regular-hit"].lazy_ticket_selection.selection_id == "49"


def test_recomputation_is_content_address_stable_in_same_and_fresh_process(
    evidence, registry, formal_world
) -> None:
    second = compile_f1_replay_evidence(registry, formal_world)
    assert second.content_hash == evidence.content_hash
    assert second.ordered_case_digest == evidence.ordered_case_digest
    assert (
        second.representative_replay_summary.content_hash
        == evidence.representative_replay_summary.content_hash
    )

    script = (
        "import json; "
        "from xinao.foundation.semantics_registry import compile_default_semantics_registry; "
        "from xinao.foundation.world_compile import compile_functional_world; "
        "from xinao.foundation.f1_replay import compile_f1_replay_evidence; "
        "r=compile_default_semantics_registry(); "
        "w=compile_functional_world(r).world_snapshot; "
        "e=compile_f1_replay_evidence(r,w); "
        "print(json.dumps([e.content_hash,e.ordered_case_digest,"
        "e.representative_replay_summary.content_hash]))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert json.loads(completed.stdout.strip()) == [
        evidence.content_hash,
        evidence.ordered_case_digest,
        evidence.representative_replay_summary.content_hash,
    ]


def test_world_identity_drift_and_content_hash_tampering_fail_closed(
    evidence, registry, formal_world
) -> None:
    drifted_world = formal_world.model_copy(
        update={"active_atomic_ticket_binding_structural_hash": "0" * 64}
    )
    with pytest.raises(ValueError, match="active atomic ticket binding"):
        compile_f1_replay_evidence(registry, drifted_world)

    payload = evidence.model_dump(mode="json")
    payload["ordered_case_digest"] = "0" * 64
    with pytest.raises(ValueError, match=r"ordered replay case digest|content_hash"):
        F1RepresentativeReplayEvidence.model_validate(payload)
