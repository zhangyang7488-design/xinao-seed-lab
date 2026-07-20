"""Evidence compiler for the authorized special-number exact-number slice."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256

from .rule_source import DEFAULT_SOURCE_BUNDLE_PATH, verify_source_bundle
from .special_number import SPECIAL_NUMBER_FUNCTION, SPECIAL_NUMBER_RULE, settle_special_number

_SETTLEMENT_RULE_TERMS = re.compile(r"中奖|和局|作废|退回|派彩|结算|规则")
_EXACT_NUMBER = re.compile(r"^\d{2}$")


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"JSON object required in {path}")
            records.append(value)
    return records


def _page_matches_panel(raw: dict[str, Any], panel: str) -> bool:
    url = str(raw.get("final_url", "")).lower()
    tid = str(raw.get("tid", ""))
    if panel == "A":
        return tid == "14" and ("/pid/1" in url or "/pan/a/tid/14" in url)
    return tid == "15" and "/pan/b/tid/15" in url


def evaluate_special_number_page_evidence(
    items: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Admit page facts only after candidate, URL, and body-text agreement."""

    page_bodies = {
        str(page.get("canonical_key", "")): str(page.get("bodyText", "")) for page in pages
    }
    page_items: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = str(raw.get("item", ""))
        panel = str(raw.get("pan", ""))
        if (
            raw.get("group") != "特码"
            or panel not in {"A", "B"}
            or not _EXACT_NUMBER.fullmatch(item)
            or not 1 <= int(item) <= 49
            or not _page_matches_panel(raw, panel)
        ):
            continue
        key = str(raw.get("page_key", ""))
        page = page_items.setdefault(
            key,
            {
                "page_key": key,
                "panel": panel,
                "tid": str(raw.get("tid", "")),
                "final_url": str(raw.get("final_url", "")),
                "source_file": str(raw.get("source_file", "")),
                "odds_by_item": {},
            },
        )
        odds_by_item = page["odds_by_item"]
        odds_by_item.setdefault(item, set()).add(str(raw.get("odds", "")))

    expected_items = {f"{value:02d}" for value in range(1, 50)}
    expected_odds = {
        "A": SPECIAL_NUMBER_FUNCTION.a_odds,
        "B": SPECIAL_NUMBER_FUNCTION.b_odds,
    }
    admitted: list[dict[str, Any]] = []
    for page in page_items.values():
        panel = page["panel"]
        odds_by_item = page.pop("odds_by_item")
        items_ok = set(odds_by_item) == expected_items
        odds_ok = items_ok and all(
            expected_odds[panel] in values for values in odds_by_item.values()
        )
        pair_pattern = re.compile(
            rf"(?<!\d)(0[1-9]|[1-4]\d)\s+{re.escape(expected_odds[panel])}(?!\d)"
        )
        body_items = set(pair_pattern.findall(page_bodies.get(page["page_key"], "")))
        body_text_ok = body_items == expected_items
        if items_ok and odds_ok and body_text_ok:
            ignored_candidate_odds = sorted(
                {
                    odds
                    for values in odds_by_item.values()
                    for odds in values
                    if odds != expected_odds[panel]
                }
            )
            admitted.append(
                {
                    **page,
                    "exact_option_count": len(odds_by_item),
                    "displayed_odds": expected_odds[panel],
                    "body_text_confirmation": True,
                    "ignored_candidate_odds": ignored_candidate_odds,
                }
            )
    admitted.sort(key=lambda item: (item["panel"], item["page_key"]))
    panel_counts = {panel: sum(item["panel"] == panel for item in admitted) for panel in ("A", "B")}

    rule_term_hits: list[dict[str, str]] = []
    for page in pages:
        text = str(page.get("bodyText", ""))
        match = _SETTLEMENT_RULE_TERMS.search(text)
        if match:
            rule_term_hits.append(
                {
                    "canonical_key": str(page.get("canonical_key", "")),
                    "term": match.group(0),
                }
            )
    return {
        "schema_version": "xinao.special_number_cross_page_evidence.v1",
        "semantic_status": "EXPLICIT_PAGE",
        "expected_exact_options": 49,
        "expected_panel_odds": expected_odds,
        "admitted_snapshot_count": len(admitted),
        "admitted_snapshot_count_by_panel": panel_counts,
        "admitted_snapshots": admitted,
        "settlement_rule_term_hit_count": len(rule_term_hits),
        "settlement_rule_term_hits": rule_term_hits,
        "ok": (panel_counts["A"] >= 2 and panel_counts["B"] >= 2 and not rule_term_hits),
    }


def _cross_page_evidence(source_root: Path) -> dict[str, Any]:
    items = _jsonl(source_root / "analysis_ready" / "odds_snapshot_items_v1.jsonl")
    pages = _jsonl(source_root / "analysis_ready" / "odds_snapshot_pages_v1.jsonl")
    return evaluate_special_number_page_evidence(items, pages)


def _historical_replay() -> dict[str, Any]:
    from xinao.world.builder import iter_event_rows, load_draws

    draws = load_draws()
    positive_cases = 0
    negative_cases = 0
    for draw in draws:
        actual = draw.special_number
        miss = actual % 49 + 1
        for panel in ("A", "B"):
            positive = settle_special_number(
                selected_number=actual,
                actual_special_number=actual,
                panel=panel,
                stake="1",
            )
            negative = settle_special_number(
                selected_number=miss,
                actual_special_number=actual,
                panel=panel,
                stake="1",
            )
            if not positive.hit or positive.realized_loss != "0.0000":
                raise AssertionError("historical positive settlement case failed")
            if negative.hit or negative.realized_loss != "1.0000":
                raise AssertionError("historical negative settlement case failed")
            positive_cases += 1
            negative_cases += 1

    def digest_rows() -> tuple[str, int, int]:
        digest = hashlib.sha256()
        row_count = 0
        hit_count = 0
        for row in iter_event_rows(draws):
            digest.update(canonical_dumps(row.model_dump(mode="python")) + b"\n")
            row_count += 1
            hit_count += int(row.hit)
        return digest.hexdigest(), row_count, hit_count

    first_hash, row_count, hit_count = digest_rows()
    replay_hash, replay_row_count, replay_hit_count = digest_rows()
    return {
        "schema_version": "xinao.special_number_historical_replay.v1",
        "semantic_status": "RESEARCH_CONVENTION",
        "draw_count": len(draws),
        "positive_case_count": positive_cases,
        "negative_case_count": negative_cases,
        "event_row_count": row_count,
        "event_hit_count": hit_count,
        "first_replay_sha256": first_hash,
        "second_replay_sha256": replay_hash,
        "ok": bool(
            len(draws) == 913
            and positive_cases == negative_cases == 913 * 2
            and row_count == replay_row_count == 913 * 2 * 49
            and hit_count == replay_hit_count == 913 * 2
            and first_hash == replay_hash
        ),
    }


def verify_special_number_rule_evidence(
    *,
    source_root: Path = DEFAULT_SOURCE_BUNDLE_PATH,
    source_report_path: Path | None = None,
    fresh_process_replay_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Verify provenance, cross-page facts, and convention replay without widening scope."""

    source = verify_source_bundle(source_root=source_root, output_path=source_report_path)
    cross_page = _cross_page_evidence(source_root)
    historical = _historical_replay()
    fresh_process_replay = (
        json.loads(fresh_process_replay_path.read_text(encoding="utf-8"))
        if fresh_process_replay_path is not None
        else None
    )
    if fresh_process_replay is not None and not isinstance(fresh_process_replay, dict):
        raise TypeError("fresh-process replay report must be a JSON object")
    fresh_process_ok = bool(
        fresh_process_replay
        and fresh_process_replay.get("ok") is True
        and fresh_process_replay.get("row_count") == historical["event_row_count"]
        and fresh_process_replay.get("nnz") == historical["event_hit_count"]
        and fresh_process_replay.get("recorded_matrix_sha256") == historical["first_replay_sha256"]
        and fresh_process_replay.get("file_matrix_sha256") == historical["first_replay_sha256"]
        and fresh_process_replay.get("recomputed_matrix_sha256")
        == historical["first_replay_sha256"]
    )
    rule = SPECIAL_NUMBER_RULE.model_dump(mode="json")
    function = SPECIAL_NUMBER_FUNCTION.model_dump(mode="json")
    body: dict[str, Any] = {
        "schema_version": "xinao.special_number_rule_evidence.v1",
        "verification_scope": "SPECIAL_NUMBER_EXACT_NUMBER_SLICE_ONLY",
        "rule_ref": SPECIAL_NUMBER_RULE.rule_ref,
        "settlement_function_ref": SPECIAL_NUMBER_FUNCTION.function_ref,
        "source_type": SPECIAL_NUMBER_RULE.source_type,
        "source_bundle_hash": SPECIAL_NUMBER_RULE.source_bundle_hash,
        "authority_basis": SPECIAL_NUMBER_RULE.authority_basis,
        "semantic_status": list(SPECIAL_NUMBER_RULE.semantic_status),
        "rule_hash": canonical_sha256(rule),
        "settlement_function_hash": canonical_sha256(function),
        "compiled_baseline_ids": ["BO0001", "BO0013"],
        "family_baseline_entry_count": 24,
        "family_compilation_status": "PARTIALLY_COMPILED",
        "family_compilation_complete": False,
        "foundation_closure_claim_allowed": False,
        "source_bundle_verification": {
            "ok": source["ok"],
            "content_hash": source["content_hash"],
            "manifest_entry_count": source["manifest_entry_count"],
            "actual_file_count": source["actual_file_count"],
        },
        "cross_page_evidence": cross_page,
        "historical_replay": historical,
        "fresh_process_world_replay": fresh_process_replay,
        "fresh_process_world_replay_ok": fresh_process_ok,
    }
    slice_evidence_ok = bool(
        source["ok"]
        and cross_page["ok"]
        and historical["ok"]
        and (fresh_process_replay is None or fresh_process_ok)
    )
    body["slice_evidence_ok"] = slice_evidence_ok
    body["result_status"] = "verified_slice" if slice_evidence_ok else "partial"
    body["ok"] = slice_evidence_ok
    body["content_hash"] = canonical_sha256(body)
    if output_path is not None:
        _write_atomic(output_path, body)
    return body
