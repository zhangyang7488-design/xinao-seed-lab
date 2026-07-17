from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from xinao.canonical import canonical_sha256
from xinao.foundation import world_compile as world_subject
from xinao.foundation.assertion_verifier_registry import canonical_python_executable
from xinao.foundation.selection_manifest import (
    assert_registry_manifest_matches,
    compile_atomic_ticket_bindings,
    compile_independent_selection_manifest,
    load_play_catalog,
)
from xinao.foundation.semantics_registry import (
    compile_default_semantics_registry,
    compile_semantics_registry,
)
from xinao.foundation.world_compile import (
    DEFAULT_AUTHORITY_DATASET_PATH,
    DatasetExpectation,
    FamilyReplayCase,
    compile_functional_world,
    iter_atomic_ticket_replay_selections,
    iter_functional_event_cells,
    load_authority_draws,
    replay_family_case,
    replay_functional_cell,
    resolve_atomic_ticket_binding,
    summarize_replay_results,
)

SMALL_EXPECTATION = DatasetExpectation(
    draw_count=2,
    first_draw_id="2024001",
    last_draw_id="2024002",
    first_draw_date="2024-01-01",
    last_draw_date="2024-01-02",
)


def _raw_draw(
    draw_id: str,
    open_time: str,
    open_code: str,
    *,
    zodiac: str = "鼠,牛,虎,兔,龙,蛇,马",
    annual_endpoint: int = 2024,
) -> dict[str, object]:
    return {
        "suit": None,
        "expect": draw_id,
        "openTime": open_time,
        "type": "8",
        "openCode": open_code,
        "wave": "red,blue,green,red,blue,green,red",
        "zodiac": zodiac,
        "verify": False,
        "info": "macaujc.com source fixture",
        "_annual_endpoint": annual_endpoint,
    }


def _write_dataset(path: Path, rows: list[dict[str, object]]) -> Path:
    human = [
        "新澳门六合彩 macaujc2 测试数据",
        "【人读开奖记录】",
        "本段不能被 JSONL 解析器读取。",
        "【API完整字段 JSONL(test)】",
    ]
    lines = [*human, *(json.dumps(row, ensure_ascii=False) for row in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def registry():
    return compile_default_semantics_registry()


@pytest.fixture()
def small_rows() -> list[dict[str, object]]:
    return [
        _raw_draw("2024001", "2024-01-01 21:32:32", "01,02,03,04,05,06,07"),
        _raw_draw("2024002", "2024-01-02 21:32:32", "08,09,10,11,12,13,49"),
    ]


@pytest.fixture()
def small_world(tmp_path, small_rows, registry):
    path = _write_dataset(tmp_path / "draws.txt", small_rows)
    return compile_functional_world(registry, path, expectation=SMALL_EXPECTATION)


@pytest.fixture(scope="module")
def formal_world(registry):
    if not DEFAULT_AUTHORITY_DATASET_PATH.is_file():
        pytest.skip("formal 913-draw authority text is not mounted")
    return compile_functional_world(registry, DEFAULT_AUTHORITY_DATASET_PATH)


def test_loader_uses_raw_jsonl_deduplicates_identity_and_preserves_zodiac(
    tmp_path, small_rows
) -> None:
    duplicate = dict(small_rows[0])
    duplicate["_annual_endpoint"] = 2025
    path = _write_dataset(tmp_path / "duplicates.txt", [small_rows[0], duplicate, small_rows[1]])
    loaded = load_authority_draws(path, expectation=SMALL_EXPECTATION)

    plain_path = _write_dataset(tmp_path / "plain.txt", small_rows)
    plain = load_authority_draws(plain_path, expectation=SMALL_EXPECTATION)
    assert len(loaded.draws) == 2
    assert loaded.raw_json_line_count == 3
    assert loaded.duplicate_json_line_count == 1
    assert loaded.source_annual_endpoints == (2024, 2025)
    assert loaded.dataset_semantic_hash == plain.dataset_semantic_hash
    assert loaded.draws[0].source_zodiac_raw == small_rows[0]["zodiac"]
    assert loaded.draws[0].source_zodiac_values == tuple(str(small_rows[0]["zodiac"]).split(","))
    assert loaded.draws[0].zodiac_basis_ref == "SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"


def test_conflicting_duplicate_period_date_and_numbers_fails_closed(tmp_path, small_rows) -> None:
    conflict = dict(small_rows[0])
    conflict["zodiac"] = "马,蛇,龙,兔,虎,牛,鼠"
    path = _write_dataset(tmp_path / "conflict.txt", [small_rows[0], conflict, small_rows[1]])
    with pytest.raises(ValueError, match="conflicting source fields"):
        load_authority_draws(path, expectation=SMALL_EXPECTATION)


def test_functional_surface_has_exact_draw_x_component_keys_without_ticket_expansion(
    small_world, registry
) -> None:
    snapshot = small_world.event_matrix_snapshot
    world = small_world.world_snapshot
    assert snapshot.surface_kind == "FUNCTIONAL_EVENT_SURFACE"
    assert snapshot.coverage.active_settlement_component_count == 416
    assert snapshot.coverage.expected_functional_cell_count == 2 * 416
    assert snapshot.coverage.actual_functional_cell_count == 2 * 416
    assert snapshot.coverage.missing_functional_key_count == 0
    assert snapshot.coverage.unexpected_functional_key_count == 0
    assert snapshot.coverage.duplicate_functional_key_count == 0
    assert snapshot.cells_materialized is False
    assert snapshot.f1_status == "PARTIAL"
    assert world.expanded_atomic_ticket_keys_materialized is False
    assert world.lazy_domain_proof.component_binding_count == 416
    assert world.lazy_domain_proof.descriptor_count == 233
    assert world.lazy_domain_proof.registry_manifest_exact_match is True
    assert world.lazy_domain_proof.atomic_ticket_binding_count == 37
    assert world.lazy_domain_proof.composite_exact_atomic_ticket_count == 21_652_539_822
    assert (
        world.lazy_domain_proof.exact_conceptual_atomic_selection_count
        == registry.expected_selection_domain.exact_atomic_selection_count
    )
    assert world.lazy_domain_proof.exact_conceptual_atomic_selection_count == 21_652_542_248
    assert world.lazy_domain_proof.materialized_atomic_ticket_key_count == 0
    assert world.representative_replay_evidence.result_status == "PARTIAL"
    assert len(world.representative_replay_evidence.family_coverage) == 13
    assert (
        snapshot.active_selection_domain_structural_hash
        == world.active_selection_domain_structural_hash
        == world.lazy_domain_proof.active_selection_domain_structural_hash
    )
    assert (
        snapshot.active_atomic_ticket_binding_structural_hash
        == world.active_atomic_ticket_binding_structural_hash
        == world.lazy_domain_proof.active_atomic_ticket_binding_structural_hash
    )
    assert snapshot.active_semantics_hash == registry.active_physical_semantics_hash
    assert world.active_semantics_hash == registry.active_physical_semantics_hash

    cells = tuple(iter_functional_event_cells(registry, world.draw_inputs))
    assert len(cells) == 832
    assert len({(cell.draw_id, cell.baseline_id) for cell in cells}) == 832
    assert not {f"BO{number:04d}" for number in (*range(13, 25), *range(30, 35))} & {
        cell.baseline_id for cell in cells
    }
    assert cells[0].draw_id == "2024001"
    assert cells[0].baseline_id == "BO0001"
    assert cells[-1].draw_id == "2024002"
    assert cells[-1].baseline_id == "BO0433"
    assert cells[0].registry_selection_domain_hash
    assert cells[0].atomic_ticket_binding_hash is None
    composite = next(cell for cell in cells if cell.baseline_id == "BO0213")
    assert composite.atomic_ticket_binding_id is not None
    assert composite.atomic_ticket_binding_hash is not None
    replayed = replay_functional_cell(registry, world, draw_id="2024001", baseline_id="BO0001")
    assert replayed == cells[0]
    with pytest.raises(ValueError, match="frozen agent-route quote"):
        replay_functional_cell(registry, world, draw_id="2024001", baseline_id="BO0013")


def test_independent_manifest_and_lazy_ticket_iterator_are_bound_into_world(
    small_world, registry
) -> None:
    catalog = load_play_catalog()
    independent = compile_independent_selection_manifest(catalog)
    comparison = assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    atomic_version = compile_atomic_ticket_bindings(catalog, independent)
    world = small_world.world_snapshot

    assert comparison.exact_match is True
    assert atomic_version.binding_count == 37
    assert world.lazy_domain_proof.registry_manifest_exact_match is True

    linked_number = resolve_atomic_ticket_binding(registry, "BO0213")
    first_number_ticket = next(iter_atomic_ticket_replay_selections(registry, "BO0213"))
    assert first_number_ticket.binding_id == linked_number.binding_id
    assert first_number_ticket.selection_id == "01,02"
    assert first_number_ticket.canonical_ticket_id.endswith("::01,02")
    assert first_number_ticket.participating_baseline_ids == ("BO0213",)

    parlay = resolve_atomic_ticket_binding(registry, "BO0219")
    first_parlay_ticket = next(iter_atomic_ticket_replay_selections(registry, "BO0219"))
    assert first_parlay_ticket.binding_id == parlay.binding_id
    assert first_parlay_ticket.selection_id == "P01=ODD+P02=ODD"
    assert first_parlay_ticket.participating_baseline_ids == ("BO0219", "BO0226")
    with pytest.raises(ValueError, match="no composite atomic-ticket binding"):
        resolve_atomic_ticket_binding(registry, "BO0001")


def test_input_reordering_and_redundant_duplicate_do_not_change_world_hashes(
    tmp_path, small_rows, registry
) -> None:
    first_path = _write_dataset(tmp_path / "ordered.txt", small_rows)
    duplicate = dict(small_rows[0])
    duplicate["_annual_endpoint"] = 2025
    second_path = _write_dataset(
        tmp_path / "reordered.txt", [small_rows[1], duplicate, small_rows[0]]
    )
    first = compile_functional_world(registry, first_path, expectation=SMALL_EXPECTATION)
    second = compile_functional_world(registry, second_path, expectation=SMALL_EXPECTATION)
    assert first.loaded_dataset.dataset_semantic_hash == second.loaded_dataset.dataset_semantic_hash
    assert (
        first.event_matrix_snapshot.ordered_cell_stream_sha256
        == second.event_matrix_snapshot.ordered_cell_stream_sha256
    )
    assert (
        first.event_matrix_snapshot.ordered_merkle_root
        == second.event_matrix_snapshot.ordered_merkle_root
    )
    assert first.event_matrix_snapshot.content_hash == second.event_matrix_snapshot.content_hash
    assert first.world_snapshot.content_hash == second.world_snapshot.content_hash


def test_parent_rejects_tampered_pure_worker_result(
    tmp_path, small_rows, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_dataset(tmp_path / "result-tamper.txt", small_rows)
    real_run = subprocess.run

    def tampering_run(*args, **kwargs):
        completed = real_run(*args, **kwargs)
        payload = json.loads(completed.stdout)
        payload["cell_count"] += 1
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii"),
            completed.stderr,
        )

    monkeypatch.setattr(world_subject.subprocess, "run", tampering_run)
    with pytest.raises(ValueError, match="result content hash drifted"):
        compile_functional_world(registry, path, expectation=SMALL_EXPECTATION)


def test_parent_rejects_pure_worker_source_toctou(
    tmp_path, small_rows, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_dataset(tmp_path / "worker-toctou.txt", small_rows)
    worker_copy = tmp_path / "f1_pure_ascii_stream_worker.py"
    shutil.copy2(world_subject.PURE_ASCII_STREAM_WORKER, worker_copy)
    monkeypatch.setattr(world_subject, "PURE_ASCII_STREAM_WORKER", worker_copy)
    monkeypatch.setattr(world_subject, "__file__", str(tmp_path / "world_compile.py"))
    real_run = subprocess.run

    def mutating_run(*args, **kwargs):
        completed = real_run(*args, **kwargs)
        worker_copy.write_bytes(worker_copy.read_bytes() + b"\n")
        return completed

    monkeypatch.setattr(world_subject.subprocess, "run", mutating_run)
    with pytest.raises(ValueError, match="worker changed during execution"):
        compile_functional_world(registry, path, expectation=SMALL_EXPECTATION)


def test_b_quote_change_does_not_change_active_world(
    tmp_path, small_rows, registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_dataset(tmp_path / "b-price-independent.txt", small_rows)
    first = compile_functional_world(registry, path, expectation=SMALL_EXPECTATION)

    changed_catalog = deepcopy(load_play_catalog())
    b_row = next(row for row in changed_catalog["entries"] if row["baseline_id"] == "BO0013")
    b_row["baseline_odds_components"] = ["41.999"]
    changed_catalog["entries"] = sorted(
        changed_catalog["entries"], key=lambda row: row["baseline_id"]
    )
    catalog_body = {key: value for key, value in changed_catalog.items() if key != "content_hash"}
    changed_catalog["content_hash"] = canonical_sha256(catalog_body)
    changed_registry = compile_semantics_registry(changed_catalog)
    monkeypatch.setattr(world_subject, "load_play_catalog", lambda: changed_catalog)
    second = compile_functional_world(changed_registry, path, expectation=SMALL_EXPECTATION)

    assert changed_registry.content_hash == registry.content_hash
    assert (
        changed_registry.active_physical_semantics_hash == registry.active_physical_semantics_hash
    )
    assert second.event_matrix_snapshot.content_hash == first.event_matrix_snapshot.content_hash
    assert second.world_snapshot.content_hash == first.world_snapshot.content_hash
    assert (
        second.event_matrix_snapshot.ordered_cell_stream_sha256
        == first.event_matrix_snapshot.ordered_cell_stream_sha256
    )


def test_replay_interface_executes_asserted_cases_and_keeps_global_summary_partial(
    small_world, registry
) -> None:
    world = small_world.world_snapshot
    cases = (
        FamilyReplayCase(
            case_id="special-positive",
            case_kind="POSITIVE",
            draw_id="2024001",
            component_baseline_ids=("BO0001",),
            selection=(7,),
            expected_outcome="HIT",
        ),
        FamilyReplayCase(
            case_id="special-negative",
            case_kind="NEGATIVE",
            draw_id="2024001",
            component_baseline_ids=("BO0001",),
            selection=(8,),
            expected_outcome="MISS",
        ),
        FamilyReplayCase(
            case_id="special-boundary-49",
            case_kind="BOUNDARY",
            draw_id="2024002",
            component_baseline_ids=("BO0002",),
            selection=("合单",),
            expected_outcome="VOID",
        ),
        FamilyReplayCase(
            case_id="linked-number-positive",
            case_kind="POSITIVE",
            draw_id="2024001",
            component_baseline_ids=("BO0212",),
            selection=(1, 2),
            expected_outcome="HIT",
        ),
    )
    results = tuple(replay_family_case(registry, world, case) for case in cases)
    assert all(result.assertion_status == "PASS" for result in results)
    assert (
        results[-1].atomic_ticket_binding_hash
        == resolve_atomic_ticket_binding(registry, "BO0212").content_hash
    )
    summary = summarize_replay_results(results)
    special = next(item for item in summary.family_coverage if item.family_id == "special-number")
    linked_number = next(
        item for item in summary.family_coverage if item.family_id == "linked-number"
    )
    assert special.status == "VERIFIED"
    assert special.passed_case_kinds == ("POSITIVE", "NEGATIVE", "BOUNDARY")
    assert linked_number.status == "PARTIAL"
    assert summary.result_status == "PARTIAL"
    with pytest.raises(ValueError, match="cannot use catalog-only frozen route quotes"):
        replay_family_case(
            registry,
            world,
            FamilyReplayCase(
                case_id="b-is-not-physical",
                case_kind="POSITIVE",
                draw_id="2024001",
                component_baseline_ids=("BO0013",),
                selection=(7,),
                expected_outcome="HIT",
            ),
        )


def test_formal_913_functional_surface_is_exact(formal_world, registry) -> None:
    loaded = formal_world.loaded_dataset
    snapshot = formal_world.event_matrix_snapshot
    world = formal_world.world_snapshot
    assert len(loaded.draws) == 913
    assert loaded.raw_json_line_count == 913
    assert loaded.duplicate_json_line_count == 0
    assert loaded.draws[0].draw_id == "2024001"
    assert loaded.draws[-1].draw_id == "2026182"
    assert snapshot.coverage.expected_functional_cell_count == 379_808
    assert snapshot.coverage.actual_functional_cell_count == 379_808
    assert snapshot.family_cell_counts == {
        family: row_count * 913
        for family, row_count in registry.rule_semantic_map.family_counts.items()
    }
    assert snapshot.cells_materialized is False
    assert world.lazy_domain_proof.expanded_atomic_ticket_keys_materialized is False
    assert snapshot.representative_replay_status == "PARTIAL"
    assert snapshot.f1_status == world.f1_status == "PARTIAL"


def test_formal_hashes_are_stable_in_a_fresh_process(formal_world) -> None:
    script = (
        "import json; "
        "from xinao.foundation.semantics_registry import compile_default_semantics_registry; "
        "from xinao.foundation.world_compile import compile_functional_world; "
        "r=compile_functional_world(compile_default_semantics_registry()); "
        "print(json.dumps([r.event_matrix_snapshot.content_hash, "
        "r.world_snapshot.content_hash, "
        "r.event_matrix_snapshot.ordered_cell_stream_sha256, "
        "r.event_matrix_snapshot.ordered_merkle_root]))"
    )
    completed = subprocess.run(
        [str(canonical_python_executable()), "-X", "faulthandler", "-I", "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = json.loads(completed.stdout.strip())
    expected = [
        formal_world.event_matrix_snapshot.content_hash,
        formal_world.world_snapshot.content_hash,
        formal_world.event_matrix_snapshot.ordered_cell_stream_sha256,
        formal_world.event_matrix_snapshot.ordered_merkle_root,
    ]
    assert observed == expected


def test_formal_jsonl_reordering_keeps_semantic_and_surface_hashes(
    formal_world, registry, tmp_path
) -> None:
    if not DEFAULT_AUTHORITY_DATASET_PATH.is_file():
        pytest.skip("formal 913-draw authority text is not mounted")
    lines = DEFAULT_AUTHORITY_DATASET_PATH.read_text(encoding="utf-8").splitlines()
    marker = next(
        index for index, line in enumerate(lines) if line.startswith("【API完整字段 JSONL")
    )
    reordered = [*lines[: marker + 1], *reversed(lines[marker + 1 :])]
    path = tmp_path / "formal-reordered.txt"
    path.write_text("\n".join(reordered) + "\n", encoding="utf-8")
    second = compile_functional_world(registry, path)
    assert (
        second.loaded_dataset.dataset_semantic_hash
        == formal_world.loaded_dataset.dataset_semantic_hash
    )
    assert (
        second.event_matrix_snapshot.content_hash == formal_world.event_matrix_snapshot.content_hash
    )
    assert second.world_snapshot.content_hash == formal_world.world_snapshot.content_hash
