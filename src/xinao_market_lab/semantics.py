from __future__ import annotations

import csv
import hashlib
import io
import json
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .inputs import InputLayout, canonical_json_bytes, sha256_file
from .models import (
    P5AcceptancePin,
    P5CsvValueSelector,
    P5EvidenceRecord,
    P5JsonlValueSelector,
    P5JsonValueSelector,
    P5JudgeGateResult,
    P5Protocol,
    P5ProtocolSpec,
    P5SourceInventoryEntry,
    P5TextPositionSelector,
    P5TextQuoteSelector,
    P5TextSelectorSet,
    P5TombstoneRecord,
    PlayStructureClassification,
    RuleClaim,
)

P5_RESOLUTION_KEY = "p5-unresolved-semantics-evidence-catalog-v1"
RULE_CLAIM_SUBJECTS = ("payout_basis", "special_two_sided_49_policy")
ZERO_HASH = "0" * 64
UNICODE_POLICY = "utf8_sig_decode_crlf_cr_to_lf_then_nfc_codepoint_offsets_v1"

QUERY_TERMS = (
    "含本",
    "不含本",
    "本金",
    "返还",
    "净赢",
    "退码",
    "和局",
    "走盘",
    "派彩",
    "赔付",
    "输赢",
    "结算",
    "49算和",
    "49为和",
    "49和局",
    "49退码",
    "49走盘",
    "49赔付",
    "49不计",
    "49不算",
    "特码两面",
    "49号",
)
PAYOUT_DIRECT_TERMS = frozenset(QUERY_TERMS[:9])
PAYOUT_GENERIC_TERMS = frozenset(QUERY_TERMS[9:12])
SPECIAL_49_DIRECT_TERMS = frozenset(QUERY_TERMS[12:20])
SPECIAL_49_GENERIC_TERMS = frozenset(QUERY_TERMS[20:])
EXPECTED_CANONICAL_TERM_COUNTS = {
    term: (1 if term in {"赔付", "输赢"} else 18 if term == "结算" else 0) for term in QUERY_TERMS
}

EXPECTED_SOURCE_PATHS = tuple(
    sorted(
        {
            "弱智策略版本.txt",
            "新澳_数据源清洗重建包_v1.zip",
            "新澳盘口_完整映射数据包_v1.zip",
            "新澳盘口_完整映射数据包_v1/analysis_ready/coverage_summary_v1.json",
            "新澳盘口_完整映射数据包_v1/analysis_ready/link_audit_summary.json",
            "新澳盘口_完整映射数据包_v1/analysis_ready/link_audit_urls.csv",
            "新澳盘口_完整映射数据包_v1/analysis_ready/odds_snapshot_items_v1.csv",
            "新澳盘口_完整映射数据包_v1/analysis_ready/odds_snapshot_items_v1.jsonl",
            "新澳盘口_完整映射数据包_v1/analysis_ready/odds_snapshot_pages_v1.jsonl",
            "新澳盘口_完整映射数据包_v1/analysis_ready/page_catalog_all_sources.csv",
            "新澳盘口_完整映射数据包_v1/analysis_ready/pages_all_full_bodytext.jsonl",
            "新澳盘口_完整映射数据包_v1/analysis_ready/pages_dedup_full_bodytext.jsonl",
            "新澳盘口_完整映射数据包_v1/analysis_ready/play_structure_v1.csv",
            "新澳盘口_完整映射数据包_v1/analysis_ready/play_structure_v1.json",
            "新澳盘口_完整映射数据包_v1/context_reference/商店修复策略.txt",
            "新澳盘口_完整映射数据包_v1/context_reference/新澳机会分析.txt",
            "新澳盘口_完整映射数据包_v1/context_reference/Agent启动与接口问题.txt",
            "新澳盘口_完整映射数据包_v1/context_reference/macaujc2_corrected_2023_2026_v2.jsonl",
            "新澳盘口_完整映射数据包_v1/context_reference/macaujc2_corrected_2023_2026_v2.txt",
            "新澳盘口_完整映射数据包_v1/docs/数据字典.md",
            "新澳盘口_完整映射数据包_v1/manifest.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_菜单映射.txt",
            "新澳盘口_完整映射数据包_v1/raw/盘口_连类nav补抓_v5_2026-05-12T11-24-03-201Z.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率_full_v3_2026-05-12T11-12-34-765Z.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率_live.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_玩法补缺_v4_2026-05-12T11-18-32-515Z.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口_玩法链接审计_v6_2026-05-12T11-35-57-826Z.json",
            "新澳盘口_完整映射数据包_v1/raw/盘口-单页特码-a盘.txt",
            "新澳盘口_完整映射数据包_v1/raw/新澳盘口代理链_水位内幕机制标定.txt",
            "新澳盘口_完整映射数据包_v1/README.md",
            "新澳盘口_完整映射数据包_v1/scripts/load_bundle.py",
            "macaujc2_corrected_2023_2026_v2.txt",
        }
    )
)

EXCLUSION_REASONS = {
    "新澳_数据源清洗重建包_v1.zip": "binary_archive_not_expanded_in_p5",
    "新澳盘口_完整映射数据包_v1.zip": "binary_archive_hash_pinned_extracted_tree_also_present",
    "新澳盘口_完整映射数据包_v1/context_reference/macaujc2_corrected_2023_2026_v2.jsonl": (
        "draw_history_cannot_define_rule_semantics"
    ),
    "新澳盘口_完整映射数据包_v1/context_reference/macaujc2_corrected_2023_2026_v2.txt": (
        "draw_history_cannot_define_rule_semantics"
    ),
    "macaujc2_corrected_2023_2026_v2.txt": "draw_history_cannot_define_rule_semantics",
    "新澳盘口_完整映射数据包_v1/scripts/load_bundle.py": "executable_helper_not_evidence_source",
}

HUMAN_CONTEXT_PATHS = {
    "弱智策略版本.txt",
    "新澳盘口_完整映射数据包_v1/context_reference/商店修复策略.txt",
    "新澳盘口_完整映射数据包_v1/context_reference/新澳机会分析.txt",
    "新澳盘口_完整映射数据包_v1/context_reference/Agent启动与接口问题.txt",
    "新澳盘口_完整映射数据包_v1/raw/新澳盘口代理链_水位内幕机制标定.txt",
}
PACKAGE_MANIFEST_PATHS = {
    "新澳盘口_完整映射数据包_v1/README.md",
    "新澳盘口_完整映射数据包_v1/manifest.json",
    "新澳盘口_完整映射数据包_v1/docs/数据字典.md",
}
CAPTURED_PAGE_PATHS = {
    "新澳盘口_完整映射数据包_v1/analysis_ready/odds_snapshot_pages_v1.jsonl",
    "新澳盘口_完整映射数据包_v1/analysis_ready/pages_all_full_bodytext.jsonl",
    "新澳盘口_完整映射数据包_v1/analysis_ready/pages_dedup_full_bodytext.jsonl",
    "新澳盘口_完整映射数据包_v1/raw/盘口_菜单映射.txt",
    "新澳盘口_完整映射数据包_v1/raw/盘口_连类nav补抓_v5_2026-05-12T11-24-03-201Z.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率_full_v3_2026-05-12T11-12-34-765Z.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率_live.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口_全玩法赔率.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口_玩法补缺_v4_2026-05-12T11-18-32-515Z.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口_玩法链接审计_v6_2026-05-12T11-35-57-826Z.json",
    "新澳盘口_完整映射数据包_v1/raw/盘口-单页特码-a盘.txt",
}
DERIVED_CATALOG_PATHS = set(EXPECTED_SOURCE_PATHS) - (
    set(EXCLUSION_REASONS) | HUMAN_CONTEXT_PATHS | PACKAGE_MANIFEST_PATHS | CAPTURED_PAGE_PATHS
)


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    value = _parse_json_text(_decode_text(path, normalize_values=False))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _decode_text(path: Path, *, normalize_values: bool = True) -> str:
    text = path.read_bytes().decode("utf-8-sig", errors="strict")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text) if normalize_values else text


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member is not selector-safe: {key}")
        result[key] = value
    return result


def _parse_json_text(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)


def _document_kind(relative_path: str) -> str:
    if relative_path == "新澳盘口_完整映射数据包_v1/raw/盘口_菜单映射.txt":
        return "json"
    suffix = Path(relative_path).suffix.lower()
    kinds = {
        ".txt": "text",
        ".md": "text",
        ".json": "json",
        ".jsonl": "jsonl",
        ".csv": "csv",
        ".zip": "binary_archive",
        ".py": "executable_helper",
    }
    if suffix not in kinds:
        raise ValueError(f"P5 has no frozen document contract for {relative_path}")
    return kinds[suffix]


def _source_role(relative_path: str) -> str:
    if relative_path in HUMAN_CONTEXT_PATHS:
        return "human_context_hypothesis"
    if relative_path in PACKAGE_MANIFEST_PATHS:
        return "package_manifest"
    if relative_path in CAPTURED_PAGE_PATHS:
        return "captured_page_snapshot"
    if relative_path in DERIVED_CATALOG_PATHS:
        return "derived_catalog"
    raise ValueError(f"P5 scanned source has no frozen role: {relative_path}")


def build_source_inventory(snapshot: dict[str, Any]) -> tuple[P5SourceInventoryEntry, ...]:
    snapshot_paths = tuple(sorted(str(item["relative_path"]) for item in snapshot["files"]))
    if snapshot_paths != EXPECTED_SOURCE_PATHS:
        missing = sorted(set(EXPECTED_SOURCE_PATHS) - set(snapshot_paths))
        added = sorted(set(snapshot_paths) - set(EXPECTED_SOURCE_PATHS))
        raise ValueError(f"P5 exact 33-file surface drift; missing={missing}; added={added}")
    entries: list[P5SourceInventoryEntry] = []
    for source in sorted(snapshot["files"], key=lambda item: item["relative_path"]):
        relative_path = str(source["relative_path"])
        excluded = relative_path in EXCLUSION_REASONS
        entries.append(
            P5SourceInventoryEntry(
                relative_path=relative_path,
                source_sha256=str(source["sha256"]),
                size_bytes=int(source["size_bytes"]),
                source_role=None if excluded else _source_role(relative_path),  # type: ignore[arg-type]
                document_kind=_document_kind(relative_path),  # type: ignore[arg-type]
                disposition="EXCLUDED" if excluded else "SCANNED",
                exclusion_reason=EXCLUSION_REASONS.get(relative_path),
            )
        )
    return tuple(entries)


def query_vocabulary_artifact() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, term in enumerate(QUERY_TERMS):
        if term in PAYOUT_DIRECT_TERMS:
            subject, marker_class = "payout_basis", "candidate_semantics_marker"
        elif term in PAYOUT_GENERIC_TERMS:
            subject, marker_class = "payout_basis", "generic_context_marker"
        elif term in SPECIAL_49_DIRECT_TERMS:
            subject, marker_class = "special_two_sided_49_policy", "candidate_semantics_marker"
        else:
            subject, marker_class = "special_two_sided_49_policy", "generic_context_marker"
        rows.append(
            {
                "query_index": index,
                "query_id": f"q{index + 1:02d}",
                "term": term,
                "claim_subject": subject,
                "marker_class": marker_class,
                "resolution_effect": "catalog_only_never_auto_resolve",
            }
        )
    artifact = {"schema_version": 1, "normalization_policy": UNICODE_POLICY, "terms": rows}
    return {**artifact, "vocabulary_sha256": _sha256_value(artifact)}


def source_scan_contract_artifact(
    inventory: tuple[P5SourceInventoryEntry, ...],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_count": len(inventory),
        "scanned_count": sum(item.disposition == "SCANNED" for item in inventory),
        "excluded_count": sum(item.disposition == "EXCLUDED" for item in inventory),
        "entries": [item.model_dump(mode="json") for item in inventory],
    }


def build_p5_acceptance_pin(
    *, p4_run_dir: Path, trusted_anchor_path: Path, admin_acceptance_path: Path
) -> P5AcceptancePin:
    p4_run_dir = p4_run_dir.resolve()
    trusted_anchor_path = trusted_anchor_path.resolve()
    admin_acceptance_path = admin_acceptance_path.resolve()
    manifest_path = p4_run_dir / "run_manifest.json"
    judge_path = p4_run_dir / "judge_gate_p4.json"
    protocol_path = p4_run_dir / "p4_protocol.json"
    manifest = _read_json_object(manifest_path)
    judge = _read_json_object(judge_path)
    protocol = _read_json_object(protocol_path)
    anchor = _read_json_object(trusted_anchor_path)
    admin = _read_json_object(admin_acceptance_path)
    protocol_hash = str(protocol["protocol_hash"])
    judge_sha256 = sha256_file(judge_path)
    manifest_sha256 = sha256_file(manifest_path)
    if manifest.get("status") != "verified_exact_null_contamination_structure_economic_claims_blocked":
        raise ValueError("P5 requires the accepted P4 formal run status")
    if judge.get("structure_status") != "STRUCTURE_NULL_RETAINED":
        raise ValueError("P5 is frozen after the retained exact P4 family")
    if judge.get("economic_claim_status") != "ECONOMIC_CLAIM_BLOCKED":
        raise ValueError("P4 economic claim gate must remain blocked")
    anchor_pins = {
        "protocol_hash": protocol_hash,
        "protocol_artifact_sha256": sha256_file(protocol_path),
        "judge_gate_sha256": judge_sha256,
        "run_manifest_sha256": manifest_sha256,
        "null_statistics_sha256": sha256_file(p4_run_dir / "null_statistics.jsonl"),
        "input_snapshot_id": str(manifest["input_snapshot_id"]),
    }
    if any(anchor.get(key) != value for key, value in anchor_pins.items()):
        raise ValueError("P4 trusted anchor does not bind the selected formal run")
    if admin.get("verdict") != "accepted" or admin.get("resolution_key") != (
        "p4-exact-null-contamination-structure-v1"
    ):
        raise ValueError("P5 requires independent P4 Admin acceptance")
    admin_hashes = admin.get("hashes", {})
    if (
        admin_hashes.get("protocol_hash") != protocol_hash
        or admin_hashes.get("trusted_anchor_sha256") != sha256_file(trusted_anchor_path)
        or admin_hashes.get("run_manifest_a_sha256") != manifest_sha256
    ):
        raise ValueError("P4 Admin acceptance pins disagree with the selected run")
    p3_pin = _read_json_object(p4_run_dir / "p3_acceptance_pin.json")
    p3_run_dir = Path(str(p3_pin["run_directory"])).resolve()
    p2_pin = _read_json_object(p3_run_dir / "p2_acceptance_pin.json")
    p2_run_dir = Path(str(p2_pin["run_directory"])).resolve()
    p2_rule_catalog_sha256 = sha256_file(p2_run_dir / "rule_catalog.json")
    if p2_rule_catalog_sha256 != p2_pin.get("rule_catalog_sha256"):
        raise ValueError("P2 rule catalog no longer matches the accepted P3 pin")
    if p2_pin.get("input_snapshot_id") != manifest.get("input_snapshot_id"):
        raise ValueError("P2/P4 input snapshot chain disagrees")
    return P5AcceptancePin(
        p4_run_directory=str(p4_run_dir),
        p4_run_manifest_sha256=manifest_sha256,
        p4_protocol_hash=protocol_hash,
        p4_judge_gate_sha256=judge_sha256,
        trusted_anchor_path=str(trusted_anchor_path),
        trusted_anchor_sha256=sha256_file(trusted_anchor_path),
        admin_acceptance_path=str(admin_acceptance_path),
        admin_acceptance_sha256=sha256_file(admin_acceptance_path),
        admin_task_id=str(admin["task_id"]),
        admin_verdict="accepted",
        p3_run_directory=str(p3_run_dir),
        p2_run_directory=str(p2_run_dir),
        p2_rule_catalog_sha256=p2_rule_catalog_sha256,
    )


def build_p5_protocol(
    *,
    snapshot_id: str,
    p4_acceptance: P5AcceptancePin,
    source_inventory: tuple[P5SourceInventoryEntry, ...],
) -> P5Protocol:
    vocabulary = query_vocabulary_artifact()
    spec = P5ProtocolSpec(
        input_snapshot_id=snapshot_id,
        p4_acceptance=p4_acceptance,
        rule_claim_subjects=RULE_CLAIM_SUBJECTS,
        query_terms=QUERY_TERMS,
        query_vocabulary_sha256=str(vocabulary["vocabulary_sha256"]),
        source_inventory=source_inventory,
    )
    protocol_hash = _sha256_value(spec.model_dump(mode="json"))
    return P5Protocol(
        spec=spec,
        protocol_hash=protocol_hash,
        catalog_id=f"catalog-p5-{protocol_hash[:24]}",
    )


def validate_p5_protocol(
    protocol: P5Protocol,
    *,
    snapshot_id: str,
    p4_acceptance: P5AcceptancePin,
    source_inventory: tuple[P5SourceInventoryEntry, ...],
) -> None:
    expected = build_p5_protocol(
        snapshot_id=snapshot_id,
        p4_acceptance=p4_acceptance,
        source_inventory=source_inventory,
    )
    if protocol != expected:
        raise ValueError("P5 protocol identity, vocabulary, source role, or inventory drift")


def _pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("RFC 6901 pointer must be empty or begin with slash")
    tokens: list[str] = []
    for token in pointer[1:].split("/"):
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in "01":
                    raise ValueError("invalid RFC 6901 escape")
                index += 2
            else:
                index += 1
        tokens.append(token.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _resolve_pointer(root: Any, pointer: str) -> Any:
    current = root
    for token in _pointer_tokens(pointer):
        if isinstance(current, list):
            if token == "-" or not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ValueError("invalid RFC 6901 array index")
            index = int(token)
            if index >= len(current):
                raise ValueError("RFC 6901 array index is out of range")
            current = current[index]
        elif isinstance(current, dict):
            if token not in current:
                raise ValueError("RFC 6901 member does not exist")
            current = current[token]
        else:
            raise ValueError("RFC 6901 pointer traverses a scalar")
    return current


def _walk_string_values(value: Any, pointer: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer, unicodedata.normalize("NFC", value)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_string_values(child, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _walk_string_values(value[key], f"{pointer}/{_pointer_escape(key)}")


def _parse_jsonl(path: Path) -> tuple[tuple[int, int, Any], ...]:
    text = _decode_text(path, normalize_values=False)
    records: list[tuple[int, int, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank JSONL record is not selector-safe: {path}:{line_number}")
        records.append((len(records), line_number, _parse_json_text(line)))
    if not records:
        raise ValueError(f"empty JSONL source: {path}")
    return tuple(records)


def _parse_csv(path: Path) -> tuple[tuple[str, ...], str, tuple[dict[str, str], ...]]:
    text = _decode_text(path, normalize_values=False)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = tuple(next(reader))
    except StopIteration as error:
        raise ValueError(f"empty CSV source: {path}") from error
    if not header or any(not name for name in header) or len(header) != len(set(header)):
        raise ValueError(f"CSV headers must be non-empty and unique: {path}")
    rows: list[dict[str, str]] = []
    for record_index, values in enumerate(reader):
        if len(values) != len(header):
            raise ValueError(f"CSV row width drift: {path}:record={record_index}")
        rows.append(dict(zip(header, values, strict=True)))
    header_sha256 = _sha256_value(list(header))
    return header, header_sha256, tuple(rows)


def _make_quote_position(
    value: str, start: int, end: int
) -> tuple[P5TextQuoteSelector, P5TextPositionSelector]:
    return (
        P5TextQuoteSelector(
            exact=value[start:end],
            prefix=value[max(0, start - 32) : start],
            suffix=value[end : end + 32],
        ),
        P5TextPositionSelector(start=start, end=end),
    )


def _match_offsets(text: str, term: str) -> Iterable[int]:
    start = 0
    while True:
        found = text.find(term, start)
        if found < 0:
            return
        yield found
        start = found + 1


def _query_meta(term: str) -> tuple[str, str, str]:
    vocabulary = query_vocabulary_artifact()["terms"]
    row = next(item for item in vocabulary if item["term"] == term)
    return str(row["query_id"]), str(row["claim_subject"]), str(row["marker_class"])


def _record_material(record: P5EvidenceRecord) -> dict[str, Any]:
    material = record.model_dump(mode="json")
    material.pop("record_hash", None)
    return material


def _pending_record(
    *,
    protocol: P5Protocol,
    entry: P5SourceInventoryEntry,
    term: str,
    selector: P5TextSelectorSet | P5JsonValueSelector | P5JsonlValueSelector | P5CsvValueSelector,
) -> dict[str, Any]:
    query_id, subject, _marker_class = _query_meta(term)
    locator = {
        "protocol_hash": protocol.protocol_hash,
        "source_path": entry.relative_path,
        "source_sha256": entry.source_sha256,
        "query_id": query_id,
        "query_term": term,
        "selector": selector.model_dump(mode="json"),
    }
    return {
        "evidence_id": f"evidence-{_sha256_value(locator)[:24]}",
        "query_term": term,
        "claim_relevance": (subject,),
        "source_path": entry.relative_path,
        "source_role": entry.source_role,
        "source_sha256": entry.source_sha256,
        "document_kind": entry.document_kind,
        "selector": selector,
        "selected_text": term,
        "selected_text_sha256": hashlib.sha256(term.encode("utf-8")).hexdigest(),
    }


def scan_packet(*, root: Path, protocol: P5Protocol) -> tuple[dict[str, Any], tuple[P5EvidenceRecord, ...]]:
    pending: list[dict[str, Any]] = []
    term_counts = dict.fromkeys(QUERY_TERMS, 0)
    per_source_counts: dict[str, int] = {}
    scanned_files: list[dict[str, Any]] = []
    excluded_files: list[dict[str, Any]] = []
    for entry in protocol.spec.source_inventory:
        if entry.disposition == "EXCLUDED":
            excluded_files.append(
                {
                    "relative_path": entry.relative_path,
                    "source_sha256": entry.source_sha256,
                    "document_kind": entry.document_kind,
                    "reason_code": entry.exclusion_reason,
                }
            )
            continue
        if entry.source_role is None:
            raise ValueError("scanned P5 source is missing its frozen source role")
        path = root / Path(entry.relative_path)
        if sha256_file(path) != entry.source_sha256:
            raise ValueError(f"P5 source hash drift during scan: {entry.relative_path}")
        before_count = len(pending)
        if entry.document_kind == "text":
            values: Iterable[tuple[dict[str, Any], str]] = (({"kind": "text"}, _decode_text(path)),)
        elif entry.document_kind == "json":
            parsed = _parse_json_text(_decode_text(path, normalize_values=False))
            values = (
                ({"kind": "json", "json_pointer": pointer}, value)
                for pointer, value in _walk_string_values(parsed)
            )
        elif entry.document_kind == "jsonl":
            values = (
                (
                    {
                        "kind": "jsonl",
                        "record_index": record_index,
                        "line_number": line_number,
                        "json_pointer": pointer,
                    },
                    value,
                )
                for record_index, line_number, parsed in _parse_jsonl(path)
                for pointer, value in _walk_string_values(parsed)
            )
        elif entry.document_kind == "csv":
            header, header_sha256, rows = _parse_csv(path)
            values = (
                (
                    {
                        "kind": "csv",
                        "record_index": record_index,
                        "header_sha256": header_sha256,
                        "column_name": column,
                        "json_pointer": f"/{_pointer_escape(column)}",
                    },
                    unicodedata.normalize("NFC", row[column]),
                )
                for record_index, row in enumerate(rows)
                for column in header
            )
        else:
            raise ValueError(f"excluded-only document entered scan: {entry.relative_path}")
        for locator, value in values:
            for term in QUERY_TERMS:
                for start in _match_offsets(value, term):
                    end = start + len(term)
                    quote, position = _make_quote_position(value, start, end)
                    if locator["kind"] == "text":
                        selector: Any = P5TextSelectorSet(text_quote=quote, text_position=position)
                    elif locator["kind"] == "json":
                        selector = P5JsonValueSelector(
                            json_pointer=locator["json_pointer"],
                            text_quote=quote,
                            text_position=position,
                        )
                    elif locator["kind"] == "jsonl":
                        selector = P5JsonlValueSelector(
                            json_pointer=locator["json_pointer"],
                            record_index=locator["record_index"],
                            line_number=locator["line_number"],
                            text_quote=quote,
                            text_position=position,
                        )
                    else:
                        selector = P5CsvValueSelector(
                            json_pointer=locator["json_pointer"],
                            record_index=locator["record_index"],
                            header_sha256=locator["header_sha256"],
                            column_name=locator["column_name"],
                            text_quote=quote,
                            text_position=position,
                        )
                    pending.append(
                        _pending_record(protocol=protocol, entry=entry, term=term, selector=selector)
                    )
                    term_counts[term] += 1
        per_source_counts[entry.relative_path] = len(pending) - before_count
        scanned_files.append(
            {
                "relative_path": entry.relative_path,
                "source_sha256": entry.source_sha256,
                "source_role": entry.source_role,
                "document_kind": entry.document_kind,
                "marker_count": per_source_counts[entry.relative_path],
            }
        )
    pending.sort(
        key=lambda item: (
            item["source_path"],
            json.dumps(item["selector"].model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
            QUERY_TERMS.index(item["query_term"]),
        )
    )
    records: list[P5EvidenceRecord] = []
    previous_hash = ZERO_HASH
    for sequence, item in enumerate(pending):
        partial = P5EvidenceRecord(
            sequence=sequence,
            catalog_id=protocol.catalog_id,
            protocol_hash=protocol.protocol_hash,
            previous_hash=previous_hash,
            record_hash=ZERO_HASH,
            **item,
        )
        record = partial.model_copy(update={"record_hash": _sha256_value(_record_material(partial))})
        records.append(record)
        previous_hash = record.record_hash
    summary = {
        "schema_version": 1,
        "catalog_id": protocol.catalog_id,
        "protocol_hash": protocol.protocol_hash,
        "query_vocabulary_sha256": protocol.spec.query_vocabulary_sha256,
        "unicode_policy": protocol.spec.unicode_policy,
        "source_file_count": len(protocol.spec.source_inventory),
        "scanned_file_count": len(scanned_files),
        "excluded_file_count": len(excluded_files),
        "scanned_files": scanned_files,
        "excluded_files": excluded_files,
        "term_counts": term_counts,
        "direct_payout_marker_count": sum(term_counts[term] for term in PAYOUT_DIRECT_TERMS),
        "generic_payout_context_count": sum(term_counts[term] for term in PAYOUT_GENERIC_TERMS),
        "direct_special_49_marker_count": sum(term_counts[term] for term in SPECIAL_49_DIRECT_TERMS),
        "generic_special_49_context_count": sum(term_counts[term] for term in SPECIAL_49_GENERIC_TERMS),
        "evidence_record_count": len(records),
        "hit_source_count": sum(count > 0 for count in per_source_counts.values()),
        "evidence_chain_tip": records[-1].record_hash if records else ZERO_HASH,
        "interpretation": "complete frozen marker scan; marker presence is not semantic resolution",
    }
    return summary, tuple(records)


def evidence_ledger_bytes(records: tuple[P5EvidenceRecord, ...]) -> bytes:
    previous_hash = ZERO_HASH
    for sequence, record in enumerate(records):
        if record.sequence != sequence or record.previous_hash != previous_hash:
            raise ValueError("P5 evidence sequence or previous hash drift")
        if record.query_term not in QUERY_TERMS:
            raise ValueError("P5 evidence contains an undeclared query term")
        if record.record_hash != _sha256_value(_record_material(record)):
            raise ValueError("P5 evidence record hash mismatch")
        previous_hash = record.record_hash
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def _verify_quote_position(
    value: str,
    *,
    quote: P5TextQuoteSelector,
    position: P5TextPositionSelector,
    expected_term: str,
) -> None:
    start, end = position.start, position.end
    if end > len(value) or value[start:end] != expected_term or quote.exact != expected_term:
        raise ValueError("P5 TextPosition/TextQuote exact selector drift")
    if quote.prefix != value[max(0, start - 32) : start]:
        raise ValueError("P5 TextQuoteSelector prefix drift")
    if quote.suffix != value[end : end + 32]:
        raise ValueError("P5 TextQuoteSelector suffix drift")


def verify_selector(*, root: Path, record: P5EvidenceRecord) -> None:
    path = root / Path(record.source_path)
    if sha256_file(path) != record.source_sha256:
        raise ValueError("P5 selector source hash mismatch")
    selector = record.selector
    if isinstance(selector, P5TextSelectorSet):
        if record.document_kind != "text":
            raise ValueError("text selector used for a structured source")
        value = _decode_text(path)
    elif isinstance(selector, P5JsonlValueSelector):
        if record.document_kind != "jsonl":
            raise ValueError("JSONL selector used for another source kind")
        rows = _parse_jsonl(path)
        if selector.record_index >= len(rows):
            raise ValueError("JSONL record index is out of range")
        record_index, line_number, parsed = rows[selector.record_index]
        if record_index != selector.record_index or line_number != selector.line_number:
            raise ValueError("JSONL record/line locator drift")
        value = _resolve_pointer(parsed, selector.json_pointer)
    elif isinstance(selector, P5CsvValueSelector):
        if record.document_kind != "csv":
            raise ValueError("CSV selector used for another source kind")
        _header, header_sha256, rows = _parse_csv(path)
        if header_sha256 != selector.header_sha256 or selector.record_index >= len(rows):
            raise ValueError("CSV header or record locator drift")
        expected_pointer = f"/{_pointer_escape(selector.column_name)}"
        if selector.json_pointer != expected_pointer:
            raise ValueError("CSV column and RFC 6901 pointer disagree")
        value = _resolve_pointer(rows[selector.record_index], selector.json_pointer)
    elif isinstance(selector, P5JsonValueSelector):
        if record.document_kind != "json":
            raise ValueError("JSON selector used for another source kind")
        parsed = _parse_json_text(_decode_text(path, normalize_values=False))
        value = _resolve_pointer(parsed, selector.json_pointer)
    else:  # pragma: no cover - strict Pydantic union prevents this branch
        raise ValueError("undeclared P5 selector type")
    if not isinstance(value, str):
        raise ValueError("P5 selector no longer resolves a string")
    normalized = unicodedata.normalize("NFC", value)
    _verify_quote_position(
        normalized,
        quote=selector.text_quote,
        position=selector.text_position,
        expected_term=record.selected_text,
    )
    if record.selected_text != record.query_term:
        raise ValueError("P5 selected text and frozen query term disagree")
    if hashlib.sha256(record.selected_text.encode("utf-8")).hexdigest() != record.selected_text_sha256:
        raise ValueError("P5 selected text hash mismatch")


def build_semantics_artifacts(
    *,
    layout: InputLayout,
    snapshot_id: str,
    p4_acceptance: P5AcceptancePin,
    records: tuple[P5EvidenceRecord, ...],
    scan_summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    del layout
    catalog_path = Path(p4_acceptance.p2_run_directory) / "rule_catalog.json"
    if sha256_file(catalog_path) != p4_acceptance.p2_rule_catalog_sha256:
        raise ValueError("P5 pinned P2 rule catalog hash drift")
    catalog = _read_json_object(catalog_path)
    if catalog.get("schema_version") != 1 or catalog.get("catalog_status") != "CANDIDATE":
        raise ValueError("P5 pinned P2 rule catalog status drift")
    raw_claims = catalog.get("claims")
    typed_bundle = catalog.get("typed_rule_bundle")
    if not isinstance(raw_claims, list) or not isinstance(typed_bundle, dict):
        raise ValueError("P5 pinned P2 rule catalog has no typed claim surface")
    claims = tuple(
        RuleClaim.model_validate(
            {**item, "evidence_refs": tuple(item.get("evidence_refs", ()))},
            strict=True,
        )
        for item in raw_claims
    )
    if len(claims) != 4 or len({claim.claim_id for claim in claims}) != 4:
        raise ValueError("P5 pinned P2 claim surface is not the accepted four-claim artifact")
    classification = typed_bundle.get("classification")
    if not isinstance(classification, dict) or not isinstance(classification.get("rows"), list):
        raise ValueError("P5 pinned P2 artifact has no classification rows")
    classifications = tuple(
        PlayStructureClassification.model_validate(item, strict=True) for item in classification["rows"]
    )
    if typed_bundle.get("source_snapshot_id") != snapshot_id:
        raise ValueError("P5 pinned P2 typed bundle snapshot drift")
    if (
        classification.get("source_row_count") != 136
        or classification.get("implemented_reference_rows") != 16
        or classification.get("unresolved_rows") != 120
        or tuple(item.row_number for item in classifications) != tuple(range(2, 138))
    ):
        raise ValueError("P5 pinned P2 classification surface drift")
    unresolved = tuple(
        sorted(
            (claim for claim in claims if claim.status == "unresolved"),
            key=lambda item: item.subject,
        )
    )
    if tuple(claim.subject for claim in unresolved) != RULE_CLAIM_SUBJECTS:
        raise ValueError("P5 RuleClaim surface drift")
    term_counts = scan_summary["term_counts"]
    direct_counts = {
        "payout_basis": sum(term_counts[term] for term in PAYOUT_DIRECT_TERMS),
        "special_two_sided_49_policy": sum(term_counts[term] for term in SPECIAL_49_DIRECT_TERMS),
    }
    evidence_by_subject = {
        subject: [record.evidence_id for record in records if subject in record.claim_relevance]
        for subject in RULE_CLAIM_SUBJECTS
    }
    p2_surface_pin = {
        "schema_version": 1,
        "p2_run_directory": p4_acceptance.p2_run_directory,
        "p2_rule_catalog_sha256": p4_acceptance.p2_rule_catalog_sha256,
        "input_snapshot_id": snapshot_id,
        "unresolved_rule_claims": [claim.model_dump(mode="json") for claim in unresolved],
        "rule_claim_subjects": list(RULE_CLAIM_SUBJECTS),
        "typed_rule_bundle_sha256": _sha256_value(typed_bundle),
        "play_structure_rows": len(classifications),
        "implemented_reference_rows": sum(item.status == "IMPLEMENTED" for item in classifications),
        "unresolved_rows": sum(item.status == "UNRESOLVED" for item in classifications),
    }
    claim_register = {
        "schema_version": 1,
        "rule_claims": [
            {
                "claim_id": claim.claim_id,
                "subject": claim.subject,
                "p2_status": claim.status,
                "p5_evidence_status": "INSUFFICIENT_LOCAL_EVIDENCE",
                "direct_marker_count": direct_counts[claim.subject],
                "marker_evidence_ids": evidence_by_subject[claim.subject],
                "semantics_hash": None,
                "source_truth_status": claim.source_truth_status,
                "compiler_execution_permitted": False,
                "reason_code": "frozen_local_scan_has_no_direct_semantic_resolution",
            }
            for claim in unresolved
        ],
        "compiler_gate": "P5 never adds semantics_hash or execution rights",
        "generic_marker_hits_do_not_resolve_semantics": True,
    }
    classification_rows = [
        {
            **classification.model_dump(mode="json"),
            "p5_accounting_status": (
                "IMPLEMENTED_REFERENCE_ACCOUNTED"
                if classification.status == "IMPLEMENTED"
                else "UNRESOLVED_ACCOUNTED_NO_COMPILATION"
            ),
        }
        for classification in classifications
    ]
    classification_register = {
        "schema_version": 1,
        "source_row_count": len(classifications),
        "implemented_reference_rows": sum(item.status == "IMPLEMENTED" for item in classifications),
        "unresolved_rows": sum(item.status == "UNRESOLVED" for item in classifications),
        "rows": classification_rows,
    }
    return p2_surface_pin, claim_register, classification_register


def build_p5_tombstones(protocol: P5Protocol) -> tuple[P5TombstoneRecord, ...]:
    definitions = (
        ("tombstone-p5-operator-truth-v1", "operator_rule_truth", ("all_sources_unverified",)),
        (
            "tombstone-p5-semantic-resolution-v1",
            "semantic_resolution",
            ("direct_payout_and_49_policy_evidence_absent",),
        ),
        (
            "tombstone-p5-edge-ranking-v1",
            "economic_edge_or_ranking",
            ("economics_still_blocked", "p4_null_retention_is_not_edge"),
        ),
        ("tombstone-p5-real-money-v1", "real_money_action", ("research_only",)),
        (
            "tombstone-p5-quote-fill-v1",
            "quote_fill_liability",
            ("contemporaneous_quote_fill_liability_absent",),
        ),
        (
            "tombstone-p5-completion-v1",
            "whole_project_completion",
            ("semantics_and_forward_evidence_unresolved",),
        ),
    )
    records: list[P5TombstoneRecord] = []
    previous_hash = ZERO_HASH
    for tombstone_id, subject, reasons in definitions:
        partial = P5TombstoneRecord(
            catalog_id=protocol.catalog_id,
            protocol_hash=protocol.protocol_hash,
            tombstone_id=tombstone_id,
            subject=subject,  # type: ignore[arg-type]
            reason_codes=reasons,
            evidence_refs=("unresolved_claim_register.json", "judge_gate_p5.json"),
            previous_hash=previous_hash,
            record_hash=ZERO_HASH,
        )
        material = partial.model_dump(mode="json")
        material.pop("record_hash")
        record = partial.model_copy(update={"record_hash": _sha256_value(material)})
        records.append(record)
        previous_hash = record.record_hash
    return tuple(records)


def p5_tombstone_ledger_bytes(records: tuple[P5TombstoneRecord, ...]) -> bytes:
    previous_hash = ZERO_HASH
    for record in records:
        if record.previous_hash != previous_hash:
            raise ValueError("P5 tombstone chain drift")
        material = record.model_dump(mode="json")
        actual = material.pop("record_hash")
        if _sha256_value(material) != actual:
            raise ValueError("P5 tombstone hash mismatch")
        previous_hash = actual
    return b"".join(canonical_json_bytes(record.model_dump(mode="json")) for record in records)


def build_p5_judge(*, protocol: P5Protocol, checks: dict[str, bool]) -> P5JudgeGateResult:
    return P5JudgeGateResult(
        catalog_id=protocol.catalog_id,
        protocol_hash=protocol.protocol_hash,
        semantics_status="SEMANTICS_STILL_UNRESOLVED",
        rule_claim_statuses={
            "payout_basis": "INSUFFICIENT_LOCAL_EVIDENCE",
            "special_two_sided_49_policy": "INSUFFICIENT_LOCAL_EVIDENCE",
        },
        checks=checks,
    )
