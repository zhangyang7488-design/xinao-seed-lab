from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from .models import DisplayedOddsQuote, Draw, LineageRecord, OddsQuote, SeriesSpec

SHANGHAI = ZoneInfo("Asia/Shanghai")


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha256_file(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"input changed while hashing: {path}")
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(canonical_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class InputLayout:
    root: Path
    mapping_bundle: Path
    history_tsv: Path
    history_context_tsv: Path
    history_jsonl: Path
    play_structure_csv: Path
    odds_items_csv: Path
    odds_pages_jsonl: Path
    bundle_manifest: Path

    @classmethod
    def from_root(cls, root: Path) -> InputLayout:
        root = root.resolve()
        bundle = root / "新澳盘口_完整映射数据包_v1"
        layout = cls(
            root=root,
            mapping_bundle=bundle,
            history_tsv=root / "macaujc2_corrected_2023_2026_v2.txt",
            history_context_tsv=bundle / "context_reference" / "macaujc2_corrected_2023_2026_v2.txt",
            history_jsonl=bundle / "context_reference" / "macaujc2_corrected_2023_2026_v2.jsonl",
            play_structure_csv=bundle / "analysis_ready" / "play_structure_v1.csv",
            odds_items_csv=bundle / "analysis_ready" / "odds_snapshot_items_v1.csv",
            odds_pages_jsonl=bundle / "analysis_ready" / "odds_snapshot_pages_v1.jsonl",
            bundle_manifest=bundle / "manifest.json",
        )
        missing = [str(path) for path in layout.semantic_paths().values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"required input files missing: {missing}")
        return layout

    def semantic_paths(self) -> dict[str, Path]:
        return {
            "history_tsv": self.history_tsv,
            "history_context_tsv": self.history_context_tsv,
            "history_jsonl": self.history_jsonl,
            "play_structure_csv": self.play_structure_csv,
            "odds_items_csv": self.odds_items_csv,
            "odds_pages_jsonl": self.odds_pages_jsonl,
            "bundle_manifest": self.bundle_manifest,
        }


def build_snapshot_manifest(layout: InputLayout) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted((item for item in layout.root.rglob("*") if item.is_file()), key=str):
        relative = path.relative_to(layout.root).as_posix()
        stat = path.stat()
        files.append(
            {
                "relative_path": relative,
                "size_bytes": stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    semantic_inputs = {
        role: path.relative_to(layout.root).as_posix() for role, path in layout.semantic_paths().items()
    }
    identity = {"schema_version": 1, "files": files, "semantic_inputs": semantic_inputs}
    snapshot_id = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    return {
        **identity,
        "snapshot_id": snapshot_id,
        "input_root": str(layout.root),
        "file_count": len(files),
        "total_bytes": sum(item["size_bytes"] for item in files),
        "read_policy": "source_read_only_hash_before_and_after",
    }


def assert_snapshot_unchanged(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before["snapshot_id"] != after["snapshot_id"] or before["files"] != after["files"]:
        raise RuntimeError("input snapshot changed during the run")


def _split_exact(value: str, expected: int, field: str, expect: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in value.split(","))
    if len(parts) != expected:
        raise ValueError(f"{expect}: {field} expected {expected} parts, got {len(parts)}")
    return parts


def _parse_draw(raw: dict[str, Any], series: SeriesSpec) -> Draw:
    expect = raw.get("expect")
    if not isinstance(expect, str):
        raise ValueError("expect must be a string")
    open_time_raw = raw.get("openTime")
    if not isinstance(open_time_raw, str):
        raise ValueError(f"{expect}: openTime must be a string")
    open_time = datetime.strptime(open_time_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    code_raw = raw.get("openCode")
    wave_raw = raw.get("wave")
    zodiac_raw = raw.get("zodiac")
    if not all(isinstance(item, str) for item in (code_raw, wave_raw, zodiac_raw)):
        raise ValueError(f"{expect}: openCode/wave/zodiac must be strings")
    code = tuple(int(part) for part in _split_exact(code_raw, 7, "openCode", expect))
    wave = _split_exact(wave_raw, 7, "wave", expect)
    zodiac = _split_exact(zodiac_raw, 7, "zodiac", expect)
    flags: list[str] = []
    if expect[:4] != f"{open_time.year:04d}":
        flags.append("expect_year_mismatch")
    if raw.get("type") != series.upstream_type:
        flags.append("upstream_type_mismatch")
    verify = raw.get("verify")
    if not isinstance(verify, bool):
        raise ValueError(f"{expect}: verify must be bool")
    return Draw(
        series_id=series.series_id,
        source_expect=expect,
        open_time=open_time,
        regular_numbers=code[:6],
        special=code[6],
        wave=wave,
        zodiac=zodiac,
        source_verified=verify,
        flags=tuple(flags),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def _read_history_tsv(path: Path) -> pl.DataFrame:
    return pl.read_csv(
        path,
        separator="\t",
        schema_overrides={
            "expect": pl.String,
            "openTime": pl.String,
            "openCode": pl.String,
            "wave": pl.String,
            "zodiac": pl.String,
        },
    )


def _bundle_manifest_mismatches(layout: InputLayout) -> list[dict[str, str]]:
    manifest = json.loads(layout.bundle_manifest.read_text(encoding="utf-8"))
    mismatches: list[dict[str, str]] = []
    for record in manifest["files"]:
        path = layout.mapping_bundle / record["relative_path"]
        actual = sha256_file(path) if path.is_file() else "missing"
        if actual.lower() != record["sha256"].lower():
            mismatches.append(
                {
                    "relative_path": record["relative_path"],
                    "expected": record["sha256"],
                    "actual": actual,
                }
            )
    return mismatches


def _select_special_quote(layout: InputLayout) -> tuple[OddsQuote, dict[str, Any]]:
    odds = pl.read_csv(
        layout.odds_items_csv,
        schema_overrides={
            "pid": pl.String,
            "tid": pl.String,
            "pan": pl.String,
            "nav": pl.String,
            "item": pl.String,
            "odds": pl.Decimal(scale=3),
            "char_start": pl.Int64,
        },
    ).with_columns(pl.col("item").cast(pl.Int64, strict=False).alias("item_number"))
    selected = odds.filter(
        (pl.col("group") == "特码")
        & (pl.col("pid") == "1")
        & (pl.col("tid") == "14")
        & (pl.col("pan") == "A")
        & (pl.col("title") == "特码A盘")
        & pl.col("source_file").str.contains("full_v3")
        & pl.col("final_url").str.contains("/pan/A/tid/14")
        & pl.col("item_number").is_between(1, 49)
    )
    raw_selected_height = selected.height
    price_counts = selected.group_by("odds").len().sort("len", descending=True)
    if price_counts.height < 1 or price_counts["len"][0] != 49:
        raise ValueError(f"special A quote has no 49-number modal price: {price_counts.to_dicts()}")
    modal_price = price_counts["odds"][0]
    selected = selected.filter(pl.col("odds") == modal_price)
    if selected.height != 49 or selected["item_number"].n_unique() != 49:
        raise ValueError(f"special A quote requires exactly 49 distinct numbers, got {selected.height}")
    prices = selected["odds"].unique().to_list()
    if len(prices) != 1:
        raise ValueError(f"special A quote expected one displayed price, got {prices}")
    page_keys = selected["page_key"].unique().to_list()
    if len(page_keys) != 1:
        raise ValueError(f"special A quote expected one page key, got {page_keys}")
    page_key = str(page_keys[0])
    bundle = json.loads(layout.bundle_manifest.read_text(encoding="utf-8"))
    observed_at = datetime.fromisoformat(bundle["created_at"])
    quote_material = {
        "page_key": page_key,
        "observed_at": observed_at.isoformat(),
        "inclusive_return": str(prices[0]),
        "source_file": str(selected["source_file"][0]),
        "items_sha256": sha256_file(layout.odds_items_csv),
        "pages_sha256": sha256_file(layout.odds_pages_jsonl),
    }
    quote_id = "quote-" + hashlib.sha256(canonical_json_bytes(quote_material)).hexdigest()[:24]
    quote = OddsQuote(
        quote_id=quote_id,
        observed_at=observed_at,
        page_key=page_key,
        source_file=str(selected["source_file"][0]),
        inclusive_return=Decimal(str(prices[0])),
    )
    matching_pages = [
        row for row in _read_jsonl(layout.odds_pages_jsonl) if row.get("canonical_key") == page_key
    ]
    if len(matching_pages) != 1:
        raise ValueError(f"special A page evidence expected one row, got {len(matching_pages)}")
    evidence = {
        **quote_material,
        "number_count": selected.height,
        "raw_candidate_count": raw_selected_height,
        "discarded_parser_candidates": raw_selected_height - selected.height,
        "page_evidence_count": len(matching_pages),
        "page_body_text_length": matching_pages[0].get("captured_text_length"),
        "price_limit": "single snapshot; not contemporaneous with historical draws",
    }
    return quote, evidence


def _source_catalog_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"catalog source has no header: {path}")
        fields = list(reader.fieldnames)
        rows = [
            {
                "row_number": row_number,
                "candidate_status": "CANDIDATE",
                "fields": {field: row.get(field, "") for field in fields},
            }
            for row_number, row in enumerate(reader, 2)
        ]
    return fields, rows


def build_source_catalog(layout: InputLayout) -> dict[str, Any]:
    play_fields, play_rows = _source_catalog_rows(layout.play_structure_csv)
    odds_fields, odds_rows = _source_catalog_rows(layout.odds_items_csv)
    if len(play_rows) != 136 or len(odds_rows) != 4_043:
        raise ValueError(f"unexpected source catalog counts: play={len(play_rows)} odds={len(odds_rows)}")
    return {
        "schema_version": 1,
        "catalog_status": "CANDIDATE",
        "interpretation": "lossless parsed source rows; not verified operator rules",
        "sources": {
            "play_structure": {
                "relative_path": layout.play_structure_csv.relative_to(layout.root).as_posix(),
                "sha256": sha256_file(layout.play_structure_csv),
                "field_names": play_fields,
                "row_count": len(play_rows),
                "rows": play_rows,
            },
            "odds_candidates": {
                "relative_path": layout.odds_items_csv.relative_to(layout.root).as_posix(),
                "sha256": sha256_file(layout.odds_items_csv),
                "field_names": odds_fields,
                "row_count": len(odds_rows),
                "rows": odds_rows,
            },
        },
    }


def build_lineage_v2(draws: tuple[Draw, ...]) -> tuple[tuple[Draw, ...], tuple[LineageRecord, ...]]:
    if not draws:
        raise ValueError("lineage requires at least one source draw")

    outcome_hashes = [
        hashlib.sha256(
            canonical_json_bytes(
                {
                    "regular_numbers": draw.regular_numbers,
                    "special": draw.special,
                }
            )
        ).hexdigest()
        for draw in draws
    ]
    exact_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, draw in enumerate(draws):
        exact_groups[(draw.open_time.isoformat(), outcome_hashes[index])].append(index)

    status: dict[int, tuple[str, int, str]] = {}
    canonical_indices: list[int] = []
    for indices in exact_groups.values():
        ranked = sorted(
            indices,
            key=lambda index: (
                "expect_year_mismatch" in draws[index].flags,
                not draws[index].source_verified,
                index,
            ),
        )
        winner = ranked[0]
        canonical_indices.append(winner)
        winner_reason = (
            "canonical_validation_ranked_exact_time_alias" if len(indices) > 1 else "canonical_unique"
        )
        status[winner] = ("canonical", winner, winner_reason)
        for loser in ranked[1:]:
            reason = (
                "expect_year_mismatch_exact_time_alias"
                if "expect_year_mismatch" in draws[loser].flags
                else "later_full_outcome_repetition"
            )
            status[loser] = ("quarantined", winner, reason)

    for index in tuple(canonical_indices):
        unexpected = set(draws[index].flags) - {"expect_year_mismatch"}
        if unexpected:
            raise ValueError(
                f"unresolved lineage flags for {draws[index].source_expect}: {sorted(unexpected)}"
            )
        if "expect_year_mismatch" in draws[index].flags:
            status[index] = ("quarantined", index, "expect_year_mismatch")
            canonical_indices.remove(index)

    by_open_time: dict[str, set[str]] = defaultdict(set)
    for index in canonical_indices:
        by_open_time[draws[index].open_time.isoformat()].add(outcome_hashes[index])
    conflicts = {key: values for key, values in by_open_time.items() if len(values) > 1}
    if conflicts:
        raise ValueError(f"conflicting outcomes share an open_time: {conflicts}")

    by_outcome: dict[str, list[int]] = defaultdict(list)
    for index in canonical_indices:
        by_outcome[outcome_hashes[index]].append(index)
    for indices in by_outcome.values():
        if len(indices) < 2:
            continue
        ranked = sorted(indices, key=lambda index: (draws[index].open_time, index))
        winner = ranked[0]
        for loser in ranked[1:]:
            status[loser] = ("quarantined", winner, "later_full_outcome_repetition")
            canonical_indices.remove(loser)

    usable_indices = sorted(canonical_indices, key=lambda index: (draws[index].open_time, index))
    usable = tuple(draws[index] for index in usable_indices)
    if any(left.open_time >= right.open_time for left, right in pairwise(usable)):
        raise ValueError("lineage-v2 usable draw times must be strictly increasing")

    records = tuple(
        LineageRecord(
            source_index=index,
            source_expect=draw.source_expect,
            open_time=draw.open_time,
            outcome_sha256=outcome_hashes[index],
            source_verified=draw.source_verified,
            source_flags=draw.flags,
            status=status[index][0],
            canonical_expect=draws[status[index][1]].source_expect,
            reason_code=status[index][2],
        )
        for index, draw in enumerate(draws)
    )
    return usable, records


def load_raw_draws(layout: InputLayout) -> tuple[Draw, ...]:
    """Load every source draw without applying a replay or lineage filter."""
    series = SeriesSpec()
    raw_rows = _read_jsonl(layout.history_jsonl)
    return tuple(_parse_draw(raw, series) for raw in raw_rows)


def _select_regular_a_quote(layout: InputLayout) -> tuple[DisplayedOddsQuote, dict[str, Any]]:
    source_file = "盘口_全玩法赔率_full_v3_2026-05-12T11-12-34-765Z.json"
    canonical_url = "https://w1.kka8f.com/index.php/index/dropma/pan/A/tid/16/pid/2.html"
    alias_url = "https://w1.kka8f.com/index.php/Index/dropMa/pid/2/tid/16"
    odds = pl.read_csv(
        layout.odds_items_csv,
        schema_overrides={
            "pid": pl.String,
            "tid": pl.String,
            "pan": pl.String,
            "nav": pl.String,
            "item": pl.String,
            "odds": pl.Decimal(scale=3),
            "char_start": pl.Int64,
        },
    ).with_columns(pl.col("item").cast(pl.Int64, strict=False).alias("item_number"))
    selected = odds.filter(
        (pl.col("group") == "正码")
        & (pl.col("pid") == "2")
        & (pl.col("tid") == "16")
        & (pl.col("pan") == "A")
        & (pl.col("title") == "正码A盘")
        & (pl.col("source_file") == source_file)
        & pl.col("final_url").is_in([canonical_url, alias_url])
    )
    page_evidence: list[dict[str, Any]] = []
    accepted_maps: list[dict[int, str]] = []
    page_keys: list[str] = []
    displayed_odds: Decimal | None = None
    for url in (canonical_url, alias_url):
        page_rows = selected.filter(pl.col("final_url") == url)
        numeric = page_rows.filter(pl.col("item_number").is_between(1, 49))
        price_counts = numeric.group_by("odds").len().sort(["len", "odds"], descending=[True, False])
        if price_counts.height < 1 or int(price_counts["len"][0]) != 49:
            raise ValueError(f"regular A page has no 49-number modal price: {url}")
        modal = Decimal(str(price_counts["odds"][0]))
        accepted = numeric.filter(pl.col("odds") == price_counts["odds"][0]).sort("item_number")
        if accepted.height != 49 or accepted["item_number"].n_unique() != 49:
            raise ValueError(f"regular A page must contain exactly 49 modal number rows: {url}")
        mapping = {
            int(row["item_number"]): str(row["odds"])
            for row in accepted.select("item_number", "odds").to_dicts()
        }
        if tuple(mapping) != tuple(range(1, 50)):
            raise ValueError(f"regular A page number space mismatch: {url}")
        if displayed_odds is None:
            displayed_odds = modal
        elif displayed_odds != modal:
            raise ValueError("regular A alias pages disagree on displayed odds")
        accepted_maps.append(mapping)
        key_values = page_rows["page_key"].unique().to_list()
        if len(key_values) != 1:
            raise ValueError(f"regular A URL must map to one page key: {url}")
        page_key = str(key_values[0])
        page_keys.append(page_key)
        rejected = page_rows.filter(
            ~(pl.col("item_number").is_between(1, 49) & (pl.col("odds") == price_counts["odds"][0]))
        ).select("item", "odds", "char_start")
        page_evidence.append(
            {
                "page_key": page_key,
                "final_url": url,
                "raw_candidate_count": page_rows.height,
                "numeric_candidate_count": numeric.height,
                "accepted_number_count": accepted.height,
                "accepted_numbers": list(mapping),
                "displayed_odds": str(modal),
                "rejected_candidates": [
                    {
                        "item": str(row["item"]),
                        "odds": str(row["odds"]),
                        "char_start": int(row["char_start"]),
                    }
                    for row in rejected.to_dicts()
                ],
            }
        )
    if accepted_maps[0] != accepted_maps[1] or displayed_odds is None:
        raise ValueError("regular A alias pages do not have identical accepted number/price maps")

    pages = {
        str(row["canonical_key"]): row
        for row in _read_jsonl(layout.odds_pages_jsonl)
        if row.get("canonical_key") in set(page_keys)
    }
    if set(pages) != set(page_keys):
        raise ValueError("regular A page evidence rows are missing")
    for evidence in page_evidence:
        page = pages[evidence["page_key"]]
        evidence["captured_text_length"] = page.get("captured_text_length")
        evidence["page_odds_candidate_count"] = page.get("odds_candidate_count")

    raw_source = layout.mapping_bundle / "raw" / source_file
    if not raw_source.is_file():
        raise FileNotFoundError(f"regular A raw source missing: {raw_source}")
    raw_payload = json.loads(raw_source.read_text(encoding="utf-8"))
    captured_at = datetime.fromisoformat(str(raw_payload["capturedAt"]).replace("Z", "+00:00"))
    bundle_payload = json.loads(layout.bundle_manifest.read_text(encoding="utf-8"))
    bundle_created_at = datetime.fromisoformat(str(bundle_payload["created_at"]))
    material = {
        "captured_at": captured_at.isoformat(),
        "canonical_page_key": page_keys[0],
        "alias_page_keys": page_keys[1:],
        "displayed_odds": str(displayed_odds),
        "accepted_numbers": list(range(1, 50)),
        "raw_source_sha256": sha256_file(raw_source),
        "items_sha256": sha256_file(layout.odds_items_csv),
        "pages_sha256": sha256_file(layout.odds_pages_jsonl),
    }
    quote_id = "displayed-quote-" + hashlib.sha256(canonical_json_bytes(material)).hexdigest()[:24]
    quote = DisplayedOddsQuote(
        quote_id=quote_id,
        captured_at=captured_at,
        bundle_created_at=bundle_created_at,
        page_key=page_keys[0],
        alias_page_keys=tuple(page_keys[1:]),
        source_file=source_file,
        raw_source_file=raw_source.relative_to(layout.root).as_posix(),
        raw_source_sha256=material["raw_source_sha256"],
        accepted_numbers=tuple(range(1, 50)),
        displayed_odds=displayed_odds,
    )
    return quote, {
        **material,
        "quote_id": quote_id,
        "page_aliases_identical": True,
        "pages": page_evidence,
        "payout_basis_status": "UNRESOLVED",
        "price_limit": "single snapshot; not contemporaneous with historical draws",
    }


def audit_inputs_p2(
    layout: InputLayout,
) -> tuple[
    tuple[Draw, ...],
    DisplayedOddsQuote,
    dict[str, Any],
    tuple[LineageRecord, ...],
    dict[str, Any],
]:
    legacy_draws, _legacy_quote, legacy_audit = audit_inputs(layout)
    raw_draws = load_raw_draws(layout)
    usable_draws, lineage = build_lineage_v2(raw_draws)
    regular_quote, quote_evidence = _select_regular_a_quote(layout)
    catalog = build_source_catalog(layout)
    quarantines = [record for record in lineage if record.status == "quarantined"]
    audit = {
        "schema_version": 2,
        "status": "usable_for_spec_pinned_mechanics_only",
        "legacy_p1": {
            "usable_draws": len(legacy_draws),
            "policy": "order_dependent_keep_first_preserved_for_p1_regression_only",
        },
        "lineage_v2": {
            "source_draws": len(raw_draws),
            "usable_draws": len(usable_draws),
            "source_verify_true": sum(draw.source_verified for draw in raw_draws),
            "source_verify_false": sum(not draw.source_verified for draw in raw_draws),
            "strictly_increasing_open_time": all(
                left.open_time < right.open_time for left, right in pairwise(usable_draws)
            ),
            "quarantines": [record.model_dump(mode="json") for record in quarantines],
        },
        "catalog": {
            "status": catalog["catalog_status"],
            "play_structure_rows": catalog["sources"]["play_structure"]["row_count"],
            "odds_candidate_rows": catalog["sources"]["odds_candidates"]["row_count"],
        },
        "regular_a_quote": quote_evidence,
        "legacy_bundle_manifest_mismatches": legacy_audit["bundle_manifest_mismatches"],
        "hard_boundaries": [
            "all source rows remain upstream verify=false",
            "regular-set membership is a spec-pinned mechanics candidate, not verified operator truth",
            "payout basis is unresolved; inclusive-return arithmetic is an explicit mechanics assumption",
            "special two-sided 49 policy is unresolved and cannot compile",
            "no output supports historical returns, predictive ranking, advice, or real-money action",
        ],
    }
    if len(raw_draws) != 1_209 or len(usable_draws) != 1_204:
        raise ValueError(f"unexpected lineage-v2 counts: source={len(raw_draws)} usable={len(usable_draws)}")
    return usable_draws, regular_quote, audit, lineage, catalog


def audit_inputs(layout: InputLayout) -> tuple[list[Draw], OddsQuote, dict[str, Any]]:
    series = SeriesSpec()
    raw_rows = _read_jsonl(layout.history_jsonl)
    draws: list[Draw] = []
    invalid_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        try:
            draws.append(_parse_draw(raw, series))
        except (TypeError, ValueError) as error:
            invalid_rows.append({"index": index, "expect": raw.get("expect"), "error": str(error)})
    if invalid_rows:
        raise ValueError(f"invalid draw rows: {invalid_rows[:10]}")

    tsv = _read_history_tsv(layout.history_tsv)
    tsv_by_expect = {str(row["expect"]): row for row in tsv.to_dicts()}
    tsv_json_mismatches: list[dict[str, Any]] = []
    compare_fields = ("openTime", "openCode", "wave", "zodiac")
    for raw in raw_rows:
        peer = tsv_by_expect.get(str(raw["expect"]))
        differing = [field for field in compare_fields if peer is None or peer.get(field) != raw.get(field)]
        if differing:
            tsv_json_mismatches.append({"expect": raw["expect"], "fields": differing})

    outcomes: dict[tuple[int, ...], list[str]] = defaultdict(list)
    for draw in draws:
        outcomes[(*draw.regular_numbers, draw.special)].append(draw.source_expect)
    duplicate_outcomes = [expects for expects in outcomes.values() if len(expects) > 1]
    duplicate_repetitions = {expect for expects in duplicate_outcomes for expect in expects[1:]}
    draws = [
        draw.model_copy(update={"flags": (*draw.flags, "duplicate_outcome_repetition")})
        if draw.source_expect in duplicate_repetitions
        else draw
        for draw in draws
    ]
    expect_counts = Counter(draw.source_expect for draw in draws)
    year_mismatches = [draw.source_expect for draw in draws if "expect_year_mismatch" in draw.flags]

    play_structure = pl.read_csv(
        layout.play_structure_csv,
        schema_overrides={"pid": pl.String, "tid": pl.String, "pan": pl.String, "nav": pl.String},
    )
    quote, quote_evidence = _select_special_quote(layout)
    manifest_mismatches = _bundle_manifest_mismatches(layout)
    history_copy_equal = sha256_file(layout.history_tsv) == sha256_file(layout.history_context_tsv)
    usable_draws = [draw for draw in draws if draw.usable_for_replay]
    audit = {
        "schema_version": 1,
        "status": "usable_for_mechanics_only" if not manifest_mismatches else "invalid_bundle_hashes",
        "series": series.model_dump(mode="json"),
        "history": {
            "jsonl_rows": len(raw_rows),
            "tsv_rows": tsv.height,
            "valid_draws": len(draws),
            "usable_mechanics_draws": len(usable_draws),
            "verify_true_count": sum(draw.source_verified for draw in draws),
            "verify_false_count": sum(not draw.source_verified for draw in draws),
            "expect_duplicates": sorted(expect for expect, count in expect_counts.items() if count > 1),
            "duplicate_outcome_groups": duplicate_outcomes,
            "quarantined_duplicate_outcome_repetitions": sorted(duplicate_repetitions),
            "expect_year_mismatches": year_mismatches,
            "tsv_json_mismatch_count": len(tsv_json_mismatches),
            "tsv_json_mismatches": tsv_json_mismatches[:20],
            "top_level_and_bundle_history_tsv_hash_equal": history_copy_equal,
        },
        "market_mapping": {
            "play_structure_rows": play_structure.height,
            "play_structure_columns": play_structure.columns,
            "odds_candidate_rows": pl.scan_csv(layout.odds_items_csv).select(pl.len()).collect().item(),
            "quote": quote_evidence,
        },
        "bundle_manifest_mismatches": manifest_mismatches,
        "hard_boundaries": [
            "all history rows are upstream verify=false",
            "2026-05-12 odds are a single candidate snapshot, not historical quotes or fills",
            "mechanics replay cannot support an edge, betting, or real-money claim",
            "expect-year mismatch rows are quarantined from sequential replay",
        ],
    }
    if not history_copy_equal or tsv_json_mismatches:
        raise ValueError("history representations disagree")
    if manifest_mismatches:
        raise ValueError(f"bundle manifest hash mismatches: {manifest_mismatches}")
    return usable_draws, quote, audit
