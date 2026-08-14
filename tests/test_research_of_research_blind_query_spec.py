from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from services.research_of_research.blind_query_spec import (
    ARCHIVE_MCP_INVOCATION_PREFIX,
    ARCHIVE_QUERY_SCRIPT,
    BlindQuerySpecError,
    build_blind_query_spec,
    build_blind_query_spec_file,
)


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _config(tmp_path: Path) -> dict[str, object]:
    records = []
    created_values = (
        "2026-08-01T00:00:00Z",
        "2026-08-03T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-06T00:00:00Z",
        "2026-08-04T00:00:00Z",
        "2026-08-05T00:00:00Z",
    )
    for index, created_at in enumerate(created_values, 1):
        records.append(
            {
                "record_id": f"opaque-{index}",
                "source_id": f"archive-source-{index}",
                "kind": "conversation" if index < 3 else "experiment",
                "path": _write(tmp_path / f"record-{index}.txt", f"record {index}\n"),
                "created_at": created_at,
            }
        )
    return {
        "cell_id": "blind-query-test",
        "account_slot": "C",
        "cap_policy": str(tmp_path / "cap-policy.json"),
        "production_guards": [str(tmp_path / "production.json")],
        "launcher": str(tmp_path / "launcher.ps1"),
        "quota": str(tmp_path / "quota"),
        "workspace": str(tmp_path / "workspaces"),
        "stimulus_source_mappings": {
            "STIMULUS.md": {
                "source_id": "stimulus",
                "path": _write(tmp_path / "stimulus.md", "an unresolved surprise\n"),
            },
            "OBSERVATION.md": {
                "source_id": "observation",
                "path": _write(tmp_path / "observation.md", "current observation\n"),
            },
        },
        "archive_records": records,
        "curated_record_ids": ["opaque-1", "opaque-3", "opaque-5"],
        "curated_selection_provenance": {"receipt_id": "external-selection-001"},
        "random_seed": "frozen-seed-20260814",
        "withheld_sources": [
            {
                "record_id": "heldout-opaque",
                "source_id": "heldout-source",
                "kind": "future-settlement",
                "path": _write(tmp_path / "heldout.txt", "FUTURE_ONLY\n"),
                "created_at": "2026-08-04T00:00:00Z",
            }
        ],
        "forbidden_sentinels": ["FUTURE_ONLY"],
        "stimulus_implied_ids": ["opaque-1"],
        "withheld_interesting_ids": ["heldout-opaque"],
    }


def _variants(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    intervention = spec["intervention"]
    assert isinstance(intervention, dict)
    return {row["id"]: row for row in intervention["variants"]}


def test_builder_emits_four_prompt_identical_empty_view_variants_and_opaque_catalogs(
    tmp_path: Path,
) -> None:
    spec = build_blind_query_spec(_config(tmp_path))
    variants = _variants(spec)

    assert spec["schema"] == "xinao.research-of-research.cell-spec.v2"
    assert set(variants) == {"baseline", "autonomous", "curated", "random"}
    assert all(row["view"] == [] for row in variants.values())
    assert spec["intervention"]["common_view"] == []
    assert spec["harness"]["workspace_files"]["archive_query.py"] == ARCHIVE_QUERY_SCRIPT
    assert spec["harness"]["workspace_source_files"] == {
        "STIMULUS.md": "stimulus",
        "OBSERVATION.md": "observation",
    }

    catalogs = {
        variant_id: json.loads(row["workspace_files"]["archive/catalog.json"])
        for variant_id, row in variants.items()
    }
    assert {key: len(value["records"]) for key, value in catalogs.items()} == {
        "baseline": 0,
        "autonomous": 6,
        "curated": 3,
        "random": 3,
    }
    canary = spec["observables"]["archive_query_canary"]
    generated = canary["configured_to_generated_record_ids"]
    full_catalog = catalogs["autonomous"]["records"]
    assert {row["record_id"] for row in catalogs["curated"]["records"]} == {
        generated["opaque-1"],
        generated["opaque-3"],
        generated["opaque-5"],
    }
    assert all(
        set(row) == {"record_id", "kind", "created_at", "bytes", "sha256"} for row in full_catalog
    )
    rendered = variants["autonomous"]["workspace_files"]["archive/catalog.json"]
    assert "source_id" not in rendered
    assert str(tmp_path) not in rendered
    assert "heldout" not in rendered
    private_configs = {
        variant_id: json.loads(row["workspace_files"]["archive/private/config.json"])
        for variant_id, row in variants.items()
    }
    assert all(
        config["binding_mode"] == "portable_relative_paths_v1"
        for config in private_configs.values()
    )
    assert all(str(tmp_path) not in json.dumps(config) for config in private_configs.values())
    assert all(
        row["workspace_files"]["archive/query-ledger.jsonl"] == "" for row in variants.values()
    )
    assert not variants["baseline"]["workspace_source_files"]
    assert set(variants["autonomous"]["workspace_source_files"]) == {
        f"archive/store/opaque-{index}.bin" for index in range(1, 7)
    }
    assert all(
        path.startswith("archive/store/")
        for variant in variants.values()
        for path in variant["workspace_source_files"]
    )


def test_random_arm_is_frozen_by_seed_and_not_by_input_order(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = build_blind_query_spec(config)
    config["archive_records"] = list(reversed(config["archive_records"]))
    second = build_blind_query_spec(config)

    first_canary = first["observables"]["archive_query_canary"]
    second_canary = second["observables"]["archive_query_canary"]
    assert first_canary["arm_provenance"]["random"] == second_canary["arm_provenance"]["random"]
    assert first_canary["arm_provenance"]["random"]["selection_method"] == ("sha256_seed_rank_v1")
    assert len(first_canary["arm_provenance"]["random"]["record_ids"]) == 3
    seed_bytes = (
        json.dumps(
            {"seed": config["random_seed"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    pool_ids = [
        row["record_id"] for row in first_canary["full_pool_record_identities"]
    ]
    expected = sorted(
        pool_ids,
        key=lambda record_id: hashlib.sha256(
            seed_bytes + b"\0" + record_id.encode("utf-8")
        ).hexdigest(),
    )[:3]
    assert first_canary["arm_provenance"]["random"]["expected_selected_ids"] == expected


def test_builder_defaults_to_shallow_three_arm_design_without_curated_set(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.pop("curated_record_ids")
    config.pop("curated_selection_provenance")

    spec = build_blind_query_spec(config)
    variants = _variants(spec)
    canary = spec["observables"]["archive_query_canary"]

    assert list(variants) == ["baseline", "autonomous", "random"]
    assert canary["variant_ids"] == ["baseline", "autonomous", "random"]
    assert set(canary["arm_provenance"]) == {"baseline", "autonomous", "random"}
    assert canary["query_ledger_contract"]["required_unique_open_count_by_variant"] == {
        "baseline": 0,
        "autonomous": 3,
        "random": 3,
    }


def test_builder_freezes_cap_guards_and_canary_evaluation_contract(tmp_path: Path) -> None:
    spec = build_blind_query_spec(_config(tmp_path))
    harness = spec["harness"]
    canary = spec["observables"]["archive_query_canary"]

    assert harness["account_slot"] == "C"
    assert harness["max_account_research_turns"] == 2
    assert harness["physical_world_turn_slots"] == 4
    assert harness["root_main_compute_allowed"] is False
    assert harness["web_search"] == "disabled"
    assert harness["forbidden_item_types"] == ["web_search_call"]
    assert canary["prompt_identity_required"] is True
    assert canary["variant_views_required_empty"] is True
    assert canary["automatic_adoption_allowed"] is False
    assert canary["project_completion_gate"] is False
    assert canary["backing_store_relative_path"] == "archive/store"
    assert canary["allowed_query_tool_invocation_prefix"] == ARCHIVE_MCP_INVOCATION_PREFIX
    assert canary["query_ledger_path"] == "archive/query-ledger.jsonl"
    assert canary["private_config_path"] == "archive/private/config.json"
    assert canary["stage"] == "matched"
    assert canary["query_ledger_contract"]["required_unique_open_count_by_variant"] == {
        "baseline": 0,
        "autonomous": 3,
        "curated": 3,
        "random": 3,
    }
    assert canary["full_pool_id"].startswith("sha256:")
    assert len(canary["full_pool_record_identities"]) == 6
    assert {row["full_pool_id"] for row in canary["arm_provenance"].values()} == {
        canary["full_pool_id"]
    }
    assert canary["retrieval_policy"] == {
        "lexical_exact_substring_search_only": True,
        "semantic_retrieval_allowed": False,
        "vector_retrieval_allowed": False,
        "llm_retrieval_allowed": False,
    }
    assert canary["query_ledger_contract"]["operations"] == [
        "list",
        "metadata",
        "find",
        "open",
    ]
    assert canary["stimulus_implied_ids"] == [
        canary["configured_to_generated_record_ids"]["opaque-1"]
    ]
    assert canary["withheld_interesting_ids"] == ["heldout-opaque"]
    sources = spec["episode"]["sources"]
    heldout = next(row for row in sources if row["id"] == "heldout-source")
    assert heldout["visibility"] == "withheld"
    assert all(
        "heldout-source" not in row.get("workspace_source_files", {}).values()
        for row in _variants(spec).values()
    )


def test_builder_supports_source_registry_and_config_relative_paths(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["stimulus_source_mappings"] = {
        "STIMULUS.md": "stimulus",
        "OBSERVATION.md": "observation",
    }
    config["source_files"] = {
        "stimulus": "stimulus.md",
        "observation": "observation.md",
    }
    for row in config["archive_records"]:
        row["path"] = Path(row["path"]).name
    for row in config["withheld_sources"]:
        row["path"] = Path(row["path"]).name
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "out" / "cell-spec.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = build_blind_query_spec_file(config_path, output_path)
    written = json.loads(output_path.read_text(encoding="utf-8"))

    assert written == result
    assert output_path.read_bytes().endswith(b"\n")
    assert written["harness"]["workspace_source_files"] == {
        "STIMULUS.md": "stimulus",
        "OBSERVATION.md": "observation",
    }


def test_builder_embedded_query_tool_survives_relocation_and_enforces_open_cap(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path / "inputs")
    spec = build_blind_query_spec(config)
    variant = _variants(spec)["autonomous"]
    source_paths = {row["id"]: Path(row["material"]["path"]) for row in spec["episode"]["sources"]}
    original = tmp_path / "original"
    for relative, content in spec["harness"]["workspace_files"].items():
        target = original / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for relative, source_id in spec["harness"]["workspace_source_files"].items():
        target = original / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_paths[source_id].read_bytes())
    for relative, content in variant["workspace_files"].items():
        target = original / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for relative, source_id in variant["workspace_source_files"].items():
        target = original / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_paths[source_id].read_bytes())

    relocated = tmp_path / "relocated" / "workspace"
    relocated.parent.mkdir()
    shutil.copytree(original, relocated)
    common = [
        "--catalog",
        "archive/catalog.json",
        "--config",
        "archive/private/config.json",
        "--ledger",
        "archive/query-ledger.jsonl",
    ]

    searched = subprocess.run(
        [sys.executable, "archive_query.py", "find", *common, "record"],
        cwd=relocated,
        check=True,
        capture_output=True,
        text=True,
    )
    result_ids = json.loads(searched.stdout)["result"]["record_ids"]
    opened = subprocess.run(
        [sys.executable, "archive_query.py", "open", *common, *result_ids[:3]],
        cwd=relocated,
        check=True,
        capture_output=True,
        text=True,
    )
    fourth = subprocess.run(
        [sys.executable, "archive_query.py", "open", *common, result_ids[3]],
        cwd=relocated,
        capture_output=True,
        text=True,
    )

    opened_result = json.loads(opened.stdout)["result"]
    assert opened_result["record_ids"] == result_ids[:3]
    assert all("record" in row["content"] for row in opened_result["records"])
    assert fourth.returncode != 0
    ledger = [
        json.loads(line)
        for line in (relocated / "archive" / "query-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["sequence"] for row in ledger] == list(range(1, 7))
    assert [row["phase"] for row in ledger] == [
        "request",
        "result",
        "request",
        "result",
        "request",
        "result",
    ]
    assert [row["operation"] for row in ledger] == [
        "find",
        "find",
        "open",
        "open",
        "open",
        "open",
    ]
    assert ledger[-1]["status"] == "REJECTED"


def test_instrument_pilot_is_one_autonomous_arm_and_zero_opens_is_legal(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config["stage"] = "instrument-pilot"
    config.pop("curated_record_ids")
    config.pop("curated_selection_provenance")
    config.pop("random_seed")

    spec = build_blind_query_spec(config)
    variants = _variants(spec)
    canary = spec["observables"]["archive_query_canary"]

    assert list(variants) == ["autonomous"]
    assert variants["autonomous"]["factor_assignments"] == {}
    assert spec["intervention"]["intervention_variables"] == []
    assert canary["stage"] == "instrument-pilot"
    assert canary["query_ledger_contract"]["required_unique_open_count_by_variant"] == {
        "autonomous": 0
    }
    assert canary["query_ledger_contract"]["maximum_unique_open_count"] == 3
    assert canary["project_completion_gate"] is False


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda config: config.update(curated_record_ids=["opaque-1"]), "CURATED_SET_INVALID"),
        (lambda config: config.update(random_seed=""), "RANDOM_SEED_INVALID"),
        (
            lambda config: config.update(stimulus_implied_ids=["not-present"]),
            "OBSERVABLE_ID_INVALID",
        ),
        (lambda config: config.update(max_open_count=4), "MAX_OPEN_COUNT_INVALID"),
        (
            lambda config: config["archive_records"][0].update(record_id="../escape"),
            "OPAQUE_ID_INVALID",
        ),
    ],
)
def test_builder_rejects_invalid_blind_query_contract(
    tmp_path: Path, mutation: object, reason_code: str
) -> None:
    config = _config(tmp_path)
    mutation(config)

    with pytest.raises(BlindQuerySpecError) as raised:
        build_blind_query_spec(config)

    assert raised.value.reason_code == reason_code


def test_builder_rejects_a_future_sentinel_in_any_visible_record(tmp_path: Path) -> None:
    config = _config(tmp_path)
    Path(config["archive_records"][0]["path"]).write_text("FUTURE_ONLY", encoding="utf-8")

    with pytest.raises(BlindQuerySpecError) as raised:
        build_blind_query_spec(config)

    assert raised.value.reason_code == "FORBIDDEN_SENTINEL_VISIBLE"


def test_builder_rejects_importance_labels_from_subject_visible_catalog(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config["archive_records"][0]["kind"] = "must-read"

    with pytest.raises(BlindQuerySpecError) as raised:
        build_blind_query_spec(config)

    assert raised.value.reason_code == "CATALOG_LABEL_INVALID"
