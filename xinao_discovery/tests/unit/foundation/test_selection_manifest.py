from __future__ import annotations

import ast
from copy import deepcopy
from itertools import islice
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation import selection_manifest as subject


def _catalog() -> dict[str, object]:
    return subject.load_play_catalog()


def test_module_has_no_semantic_compiler_or_registry_imports() -> None:
    tree = ast.parse(Path(subject.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    prohibited = {
        "xinao.foundation.semantics_basic",
        "xinao.foundation.semantics_sets",
        "xinao.foundation.semantics_combinations",
        "xinao.foundation.semantics_linked",
        "xinao.foundation.semantics_registry",
    }
    assert imported.isdisjoint(prohibited)


def test_independent_manifest_exactly_partitions_416_active_rows_and_13_families() -> None:
    catalog = _catalog()
    manifest = subject.compile_independent_selection_manifest(catalog)
    classification = subject.classify_catalog_physical_roles(catalog)

    component_ids = [
        baseline_id
        for spec in manifest.specifications
        for baseline_id in spec.component_baseline_ids
    ]
    assert manifest.selection_domain_spec_count == 233
    assert len(manifest.specifications) == 233
    assert set(component_ids) == subject.ACTIVE_SETTLEMENT_BASELINE_IDS
    assert len(component_ids) == len(set(component_ids)) == 416
    assert manifest.family_counts == subject.EXPECTED_ACTIVE_FAMILY_COUNTS
    assert len(manifest.family_counts) == 13
    assert manifest.exact_atomic_selection_count == 21_652_542_248
    assert tuple(sorted(subject.FROZEN_ROUTE_QUOTE_BASELINE_IDS)) == tuple(
        f"BO{number:04d}" for number in (*range(13, 25), *range(30, 35))
    )
    assert len(classification) == 433
    assert sum(role == "ACTIVE_SETTLEMENT" for role in classification.values()) == 416
    assert sum(role == "FROZEN_AGENT_ROUTE_QUOTE" for role in classification.values()) == 17
    assert set(component_ids).isdisjoint(subject.FROZEN_ROUTE_QUOTE_BASELINE_IDS)
    assert manifest.materialized_atomic_selection_count == 0
    assert manifest.foundation_complete is False


def test_manifest_family_counts_are_derived_from_bound_specifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = subject.compile_independent_selection_manifest(_catalog())
    payload = manifest.model_dump(mode="json", exclude={"content_hash"})
    payload["family_counts"] = {"tampered-family": 416}
    payload["content_hash"] = subject.canonical_sha256(payload)
    monkeypatch.setattr(
        subject,
        "EXPECTED_ACTIVE_FAMILY_COUNTS",
        {"tampered-family": 416},
    )

    with pytest.raises(ValueError, match="do not match its specifications"):
        subject.IndependentExpectedSelectionDomainManifestVersion.model_validate(payload)


def test_independent_counts_are_exact_without_materialising_the_large_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "iter_atomic_ticket_selections",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must stay lazy")),
    )
    manifest = subject.compile_independent_selection_manifest(_catalog())
    counts = {spec.spec_id: spec.exact_atomic_selection_count for spec in manifest.specifications}

    assert counts["selection-domain:sets:BO0217"] == 924
    assert counts["selection-domain:combinations:BO0266"] == 8_217_822_536
    assert counts["selection-domain:linked-zodiac:play:10:50:none"] == 792
    assert counts["selection-domain:linked-tail:play:11:57:none"] == 210
    assert counts["selection-domain:parlay:play:8:40:none"] == 262_101
    assert sum(counts.values()) == 21_652_542_248
    assert all(
        not set(spec.component_baseline_ids) & subject.FROZEN_ROUTE_QUOTE_BASELINE_IDS
        for spec in manifest.specifications
    )


def test_atomic_ticket_version_has_canonical_non_component_identity_and_lazy_routes() -> None:
    catalog = _catalog()
    manifest = subject.compile_independent_selection_manifest(catalog)
    version = subject.compile_atomic_ticket_bindings(catalog, manifest)

    assert version.binding_count == 37
    assert version.exact_atomic_ticket_count == 21_652_539_822
    assert version.materialized_atomic_ticket_count == 0

    by_spec = {binding.domain_spec_id: binding for binding in version.bindings}
    combination = by_spec["selection-domain:combinations:BO0213"]
    first_numbers = next(subject.iter_atomic_ticket_selections(combination))
    assert first_numbers.selection_id == "01,02"
    assert first_numbers.canonical_ticket_id == "play:6:35:none::01,02"
    assert first_numbers.participating_baseline_ids == ("BO0213",)

    zodiac = by_spec["selection-domain:linked-zodiac:play:10:47:none"]
    first_zodiac = next(subject.iter_atomic_ticket_selections(zodiac))
    assert first_zodiac.selection_id == "鼠+牛"
    assert len(first_zodiac.participating_baseline_ids) == 2
    assert first_zodiac.canonical_ticket_id.startswith("play:10:47:none::")
    assert first_zodiac.quote_aggregation_ref == "MIN_SELECTED_COMPONENT"

    parlay = by_spec["selection-domain:parlay:play:8:40:none"]
    first_three = list(islice(subject.iter_atomic_ticket_selections(parlay), 3))
    assert [ticket.selection_id for ticket in first_three] == [
        "P01=ODD+P02=ODD",
        "P01=ODD+P02=EVEN",
        "P01=ODD+P02=BIG",
    ]
    assert first_three[0].participating_baseline_ids == ("BO0219", "BO0226")
    assert first_three[0].quote_aggregation_ref == "PRODUCT_NON_VOID_LEGS"
    assert all("BO" not in ticket.canonical_ticket_id for ticket in first_three)


def test_input_reordering_keeps_manifest_and_atomic_binding_hashes_stable() -> None:
    catalog = _catalog()
    reversed_catalog = deepcopy(catalog)
    reversed_catalog["entries"] = list(reversed(reversed_catalog["entries"]))

    left_manifest = subject.compile_independent_selection_manifest(catalog)
    right_manifest = subject.compile_independent_selection_manifest(reversed_catalog)
    left_bindings = subject.compile_atomic_ticket_bindings(catalog, left_manifest)
    right_bindings = subject.compile_atomic_ticket_bindings(reversed_catalog, right_manifest)

    assert left_manifest.content_hash == right_manifest.content_hash
    assert left_bindings.content_hash == right_bindings.content_hash


def test_b_quote_source_change_cannot_propagate_into_active_selection_hashes() -> None:
    catalog = _catalog()
    changed = deepcopy(catalog)
    b_row = next(row for row in changed["entries"] if row["baseline_id"] == "BO0013")
    b_row["baseline_odds_components"] = ["41.999"]
    changed["entries"] = sorted(changed["entries"], key=lambda row: row["baseline_id"])
    changed_body = {key: value for key, value in changed.items() if key != "content_hash"}
    changed["content_hash"] = canonical_sha256(changed_body)
    assert changed["content_hash"] != catalog["content_hash"]
    assert subject.classify_catalog_physical_roles(changed) == (
        subject.classify_catalog_physical_roles(catalog)
    )

    left_manifest = subject.compile_independent_selection_manifest(catalog)
    right_manifest = subject.compile_independent_selection_manifest(changed)
    left_atomic = subject.compile_atomic_ticket_bindings(catalog, left_manifest)
    right_atomic = subject.compile_atomic_ticket_bindings(changed, right_manifest)

    assert (
        left_manifest.active_catalog_projection_hash
        == right_manifest.active_catalog_projection_hash
    )
    assert left_manifest.content_hash == right_manifest.content_hash
    assert left_atomic.content_hash == right_atomic.content_hash


def test_semantic_compiler_monkeypatches_cannot_change_independent_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xinao.foundation import (
        semantics_basic,
        semantics_combinations,
        semantics_linked,
        semantics_sets,
    )

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("independent compiler consulted a semantic compiler")

    monkeypatch.setattr(semantics_basic, "compile_basic_semantics", explode)
    monkeypatch.setattr(semantics_sets, "compile_set_family_semantics", explode)
    monkeypatch.setattr(semantics_combinations, "compile_combination_catalog", explode)
    monkeypatch.setattr(semantics_linked, "compile_linked_semantics", explode)

    manifest = subject.compile_independent_selection_manifest(_catalog())
    assert manifest.selection_domain_spec_count == 233
    assert manifest.content_hash


def test_current_registry_manifest_matches_independent_oracle() -> None:
    from xinao.foundation.semantics_registry import compile_default_semantics_registry

    independent = subject.compile_default_independent_selection_manifest()
    registry = compile_default_semantics_registry()
    comparison = subject.assert_registry_manifest_matches(
        independent,
        registry.expected_selection_domain,
    )

    assert comparison.exact_match is True
    assert comparison.compared_spec_count == 233
    assert comparison.compared_component_count == 416


@pytest.mark.parametrize("drift", ["missing", "duplicate", "arity", "count"])
def test_registry_comparison_fails_closed_on_identity_or_scope_drift(drift: str) -> None:
    from xinao.foundation.semantics_registry import compile_default_semantics_registry

    independent = subject.compile_default_independent_selection_manifest()
    observed = compile_default_semantics_registry().expected_selection_domain.model_dump(
        mode="json"
    )
    if drift == "missing":
        observed["specifications"].pop()
        observed["selection_domain_spec_count"] -= 1
    elif drift == "duplicate":
        observed["specifications"][1]["component_baseline_ids"] = observed["specifications"][0][
            "component_baseline_ids"
        ]
    elif drift == "arity":
        observed["specifications"][0]["arity_max"] += 1
    else:
        observed["specifications"][0]["exact_atomic_selection_count"] += 1

    with pytest.raises(ValueError):
        subject.assert_registry_manifest_matches(independent, observed)


def test_catalog_missing_duplicate_and_content_drift_fail_closed() -> None:
    catalog = _catalog()

    missing = deepcopy(catalog)
    missing["entries"].pop()
    missing["entry_count"] = 432
    with pytest.raises(ValueError, match="433"):
        subject.compile_independent_selection_manifest(missing)

    duplicate = deepcopy(catalog)
    duplicate["entries"][-1] = deepcopy(duplicate["entries"][0])
    with pytest.raises(ValueError, match=r"BO0001\.\.BO0433"):
        subject.compile_independent_selection_manifest(duplicate)

    drifted = deepcopy(catalog)
    drifted["entries"][0]["option_range"] = "01-48"
    with pytest.raises(ValueError, match="content_hash"):
        subject.compile_independent_selection_manifest(drifted)
