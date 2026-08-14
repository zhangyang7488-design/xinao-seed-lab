from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from services.research_of_research.archive_query import (
    CATALOG_SCHEMA,
    CONFIG_SCHEMA,
    LEDGER_SCHEMA,
    ArchiveQueryError,
    catalog_archive,
    find_fixed_string,
    list_records,
    open_records,
    record_metadata,
)

PUBLIC_FIELDS = {"record_id", "kind", "created_at", "bytes", "sha256"}


def _paths(tmp_path: Path) -> dict[str, Path]:
    control = tmp_path / "control"
    control.mkdir()
    return {
        "store": tmp_path / "store",
        "catalog": control / "catalog.json",
        "config": control / "archive_query_config.json",
        "ledger": control / "query_log.jsonl",
    }


def _make_store(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "first.txt").write_text("alpha alpha\nfirst\n", encoding="utf-8")
    (root / "nested" / "second.json").write_text('{"word":"alpha"}\n', encoding="utf-8")
    (root / "third.bin").write_bytes(b"\x00opaque\xff")
    (root / "fourth.md").write_text("fourth\n", encoding="utf-8")
    base = 1_700_000_000_000_000_000
    for index, path in enumerate(sorted(item for item in root.rglob("*") if item.is_file())):
        stamp = base + index * 1_000_000_000
        os.utime(path, ns=(stamp, stamp))


def _read_ledger(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_chain(rows: list[dict[str, object]]) -> None:
    previous = None
    for sequence, row in enumerate(rows, start=1):
        assert row["schema"] == LEDGER_SCHEMA
        assert row["sequence"] == sequence
        assert row["previous_entry_sha256"] == previous
        unsigned = dict(row)
        observed = unsigned.pop("entry_sha256")
        expected = hashlib.sha256(
            (
                json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
        ).hexdigest()
        assert observed == expected
        assert row["authority"] is False
        assert row["completion_claim_allowed"] is False
        previous = observed


def test_neutral_queries_hide_paths_and_only_open_returns_content(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _make_store(paths["store"])

    frozen = catalog_archive(
        store_root=paths["store"],
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
        max_open_count=3,
    )
    catalog = json.loads(paths["catalog"].read_text(encoding="utf-8"))
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    assert catalog["schema"] == CATALOG_SCHEMA
    assert config["schema"] == CONFIG_SCHEMA
    assert all(set(record) == PUBLIC_FIELDS for record in catalog["records"])
    assert str(paths["store"]) not in paths["catalog"].read_text(encoding="utf-8")
    assert all("first.txt" not in json.dumps(record) for record in catalog["records"])
    assert frozen["result"]["max_open_count"] == 3
    assert [record["record_id"] for record in catalog["records"]] == sorted(
        record["record_id"] for record in catalog["records"]
    )
    provenance = config["provenance"]
    assert provenance["store_root"] == str(paths["store"].resolve())
    assert {row["store_relative_path"] for row in provenance["records"]} == {
        "first.txt",
        "nested/second.json",
        "third.bin",
        "fourth.md",
    }
    assert {row["operation"] for row in config["allowed_invocation_shapes"]} == {
        "list",
        "metadata",
        "find",
        "open",
    }

    listed = list_records(
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
    )
    assert listed["result"] == {
        "record_ids": frozen["result"]["record_ids"],
        "count": 4,
    }
    assert "content" not in json.dumps(listed)
    assert str(paths["store"]) not in json.dumps(listed)

    metadata = record_metadata(
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
    )
    assert all(set(record) == PUBLIC_FIELDS for record in metadata["result"]["records"])
    assert "content" not in json.dumps(metadata)

    found = find_fixed_string(
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
        fixed_string="alpha",
    )
    assert found["result"]["count"] == 2
    assert sorted(row["count"] for row in found["result"]["match_counts"]) == [1, 2]
    assert "first.txt" not in json.dumps(found)
    assert "content" not in json.dumps(found)

    first_three = frozen["result"]["record_ids"][:3]
    opened = open_records(
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
        record_ids=first_three,
    )
    assert opened["result"]["record_ids"] == first_three
    assert opened["result"]["opened_unique_count_after"] == 3
    assert all("content" in record for record in opened["result"]["records"])
    for record in opened["result"]["records"]:
        if record["content_encoding"] == "utf-8":
            raw = record["content"].encode("utf-8")
        else:
            import base64

            raw = base64.b64decode(record["content"])
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert len(raw) == record["bytes"]

    rows = _read_ledger(paths["ledger"])
    assert len(rows) == 10
    assert all(
        rows[index]["phase"] == ("request" if index % 2 == 0 else "result")
        for index in range(len(rows))
    )
    for index in range(0, len(rows), 2):
        assert rows[index]["operation_id"] == rows[index + 1]["operation_id"]
        assert rows[index + 1]["request_entry_sha256"] == rows[index]["entry_sha256"]
    open_result = rows[-1]
    assert open_result["status"] == "SUCCESS"
    assert open_result["actual_open"]["record_ids"] == first_three
    assert open_result["actual_open"]["records"] == [
        {"record_id": record["record_id"], "bytes": record["bytes"], "sha256": record["sha256"]}
        for record in opened["result"]["records"]
    ]
    _assert_chain(rows)


def test_unique_open_cap_rejects_fourth_but_allows_repeat(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _make_store(paths["store"])
    frozen = catalog_archive(
        store_root=paths["store"],
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
        max_open_count=3,
    )
    record_ids = frozen["result"]["record_ids"]
    common = {
        "catalog_path": paths["catalog"],
        "config_path": paths["config"],
        "ledger_path": paths["ledger"],
    }
    open_records(record_ids=record_ids[:3], **common)
    repeated = open_records(record_ids=[record_ids[0]], **common)
    assert repeated["result"]["opened_unique_count_after"] == 3
    with pytest.raises(ArchiveQueryError, match="unique-id limit") as caught:
        open_records(record_ids=[record_ids[3]], **common)
    assert caught.value.reason_code == "MAX_OPEN_COUNT_EXCEEDED"
    rows = _read_ledger(paths["ledger"])
    assert rows[-1]["phase"] == "result"
    assert rows[-1]["status"] == "REJECTED"
    assert rows[-1]["actual_open"] == {"record_ids": [], "records": [], "count": 0}
    assert rows[-1]["error"]["code"] == "MAX_OPEN_COUNT_EXCEEDED"
    _assert_chain(rows)


def test_archive_drift_and_bad_output_placement_are_rejected_and_logged(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _make_store(paths["store"])
    catalog_archive(
        store_root=paths["store"],
        catalog_path=paths["catalog"],
        config_path=paths["config"],
        ledger_path=paths["ledger"],
    )
    (paths["store"] / "first.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ArchiveQueryError) as caught:
        list_records(
            catalog_path=paths["catalog"],
            config_path=paths["config"],
            ledger_path=paths["ledger"],
        )
    assert caught.value.reason_code == "ARCHIVE_DRIFT"
    rows = _read_ledger(paths["ledger"])
    assert rows[-2]["status"] == "STARTED"
    assert rows[-1]["status"] == "REJECTED"
    assert rows[-1]["error"]["code"] == "ARCHIVE_DRIFT"
    _assert_chain(rows)

    second = tmp_path / "second"
    second.mkdir()
    inner_store = second / "store"
    _make_store(inner_store)
    with pytest.raises(ArchiveQueryError) as placement:
        catalog_archive(
            store_root=inner_store,
            catalog_path=inner_store / "catalog.json",
            config_path=second / "config.json",
            ledger_path=second / "ledger.jsonl",
        )
    assert placement.value.reason_code == "STORE_NOT_SEPARATED"
    placement_rows = _read_ledger(second / "ledger.jsonl")
    assert [row["status"] for row in placement_rows] == ["STARTED", "REJECTED"]


def test_backing_store_symlink_is_rejected_when_platform_allows_it(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _make_store(paths["store"])
    target = paths["store"] / "first.txt"
    link = paths["store"] / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("platform does not permit test symlink creation")
    with pytest.raises(ArchiveQueryError) as caught:
        catalog_archive(
            store_root=paths["store"],
            catalog_path=paths["catalog"],
            config_path=paths["config"],
            ledger_path=paths["ledger"],
        )
    assert caught.value.reason_code == "BACKING_STORE_LINK"
    rows = _read_ledger(paths["ledger"])
    assert [row["status"] for row in rows] == ["STARTED", "REJECTED"]
    _assert_chain(rows)


def test_portable_tree_survives_relocation_and_mtime_changes_but_not_drift(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "portable-source"
    source_root.mkdir()
    source = _paths(source_root)
    _make_store(source["store"])
    frozen = catalog_archive(
        store_root=source["store"],
        catalog_path=source["catalog"],
        config_path=source["config"],
        ledger_path=source["ledger"],
        portable_root=source_root,
        max_open_count=3,
    )
    config_text = source["config"].read_text(encoding="utf-8")
    config = json.loads(config_text)
    assert config["binding_mode"] == "portable_relative_paths_v1"
    assert str(source_root.resolve()) not in config_text
    assert config["provenance"]["store_relative_path"] == "store"
    assert config["provenance"]["catalog_relative_path"] == "control/catalog.json"

    relocated_root = tmp_path / "portable-relocated"
    shutil.copytree(source_root, relocated_root, copy_function=shutil.copy)
    relocated = {
        "store": relocated_root / "store",
        "catalog": relocated_root / "control" / "catalog.json",
        "config": relocated_root / "control" / "archive_query_config.json",
        "ledger": relocated_root / "control" / "query_log.jsonl",
    }
    changed_time = 1_800_000_000_123_456_789
    for path in relocated["store"].rglob("*"):
        if path.is_file():
            os.utime(path, ns=(changed_time, changed_time))

    listed = list_records(
        catalog_path=relocated["catalog"],
        config_path=relocated["config"],
        ledger_path=relocated["ledger"],
    )
    assert listed["result"]["record_ids"] == frozen["result"]["record_ids"]
    opened = open_records(
        catalog_path=relocated["catalog"],
        config_path=relocated["config"],
        ledger_path=relocated["ledger"],
        record_ids=[frozen["result"]["record_ids"][0]],
    )
    assert opened["result"]["opened_unique_count_after"] == 1

    wrong_ledger = tmp_path / "wrong-ledger.jsonl"
    with pytest.raises(ArchiveQueryError) as moved_path:
        list_records(
            catalog_path=relocated["catalog"],
            config_path=relocated["config"],
            ledger_path=wrong_ledger,
        )
    assert moved_path.value.reason_code == "CONFIG_PATH_MISMATCH"
    assert _read_ledger(wrong_ledger)[-1]["status"] == "REJECTED"

    (relocated["store"] / "first.txt").write_text("changed bytes\n", encoding="utf-8")
    with pytest.raises(ArchiveQueryError) as drift:
        list_records(
            catalog_path=relocated["catalog"],
            config_path=relocated["config"],
            ledger_path=relocated["ledger"],
        )
    assert drift.value.reason_code == "ARCHIVE_DRIFT"
    relocated_rows = _read_ledger(relocated["ledger"])
    assert relocated_rows[-1]["status"] == "REJECTED"
    assert relocated_rows[-1]["error"]["code"] == "ARCHIVE_DRIFT"
    _assert_chain(relocated_rows)


def test_portable_catalog_rejects_member_outside_portable_root(tmp_path: Path) -> None:
    portable_root = tmp_path / "portable"
    portable_root.mkdir()
    control = portable_root / "control"
    control.mkdir()
    store_outside = tmp_path / "outside-store"
    _make_store(store_outside)
    with pytest.raises(ArchiveQueryError) as caught:
        catalog_archive(
            store_root=store_outside,
            catalog_path=control / "catalog.json",
            config_path=control / "config.json",
            ledger_path=control / "ledger.jsonl",
            portable_root=portable_root,
        )
    assert caught.value.reason_code == "PORTABLE_PATH_OUTSIDE_ROOT"
    rows = _read_ledger(control / "ledger.jsonl")
    assert [row["status"] for row in rows] == ["STARTED", "REJECTED"]
    _assert_chain(rows)
