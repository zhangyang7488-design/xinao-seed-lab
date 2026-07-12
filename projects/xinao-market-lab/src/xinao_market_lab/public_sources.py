from __future__ import annotations

import hashlib
import importlib.metadata
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from warcio.archiveiterator import ArchiveIterator
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

P6_RESOLUTION_KEY = "p6-public-source-role-and-ruleclaim-acquisition-contract-v1"
P6_WARC_FILENAME = "official_sources.warc"
P6_CAPTURE_ARTIFACT_NAMES = (
    "capture_contract.json",
    P6_WARC_FILENAME,
    "capture_events.jsonl",
    "capture_manifest.json",
)
P6_FORMAL_ARTIFACT_NAMES = (
    "p5_acceptance_pin.json",
    "capture_bundle_pin.json",
    "p6_protocol.json",
    "official_primary_pin.json",
    "public_source_role_register.jsonl",
    "official_evidence_ledger.jsonl",
    "ruleclaim_acquisition_criteria.json",
    "unresolved_claim_register_p6.json",
    "quarantine_register.json",
    "provenance_graph.json",
    "judge_gate_p6.json",
    "checks.json",
)
CANONICAL_RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\runs")
P6_UUID_NAMESPACE = uuid.UUID("0e52c794-2ae2-5b3f-9669-a2a84daac2e8")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
WARC_ID_PATTERN = r"^<urn:uuid:[0-9a-f-]{36}>$"
_FORBIDDEN_REQUEST_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "referer",
}
_IGNORED_MARKUP_TAGS = {"script", "style", "template", "noscript", "iframe", "svg", "canvas"}
_BLOCK_MARKUP_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_SUPPORTED_CHARSETS = {
    "big5": "big5",
    "big-5": "big5",
    "gb18030": "gb18030",
    "iso-8859-1": "iso-8859-1",
    "latin1": "iso-8859-1",
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "windows-1252": "windows-1252",
}


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class P6P5AcceptancePin(FrozenModel):
    schema_version: Literal[1] = 1
    p5_run_directory: str
    p5_run_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    p5_protocol_hash: str = Field(pattern=SHA256_PATTERN)
    p5_protocol_artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    catalog_id: str = Field(pattern=r"^catalog-p5-[0-9a-f]{24}$")
    evidence_ledger_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_chain_tip: str = Field(pattern=SHA256_PATTERN)
    p5_page_catalog_sha256: str = Field(pattern=SHA256_PATTERN)
    trusted_anchor_path: str
    trusted_anchor_sha256: str = Field(pattern=SHA256_PATTERN)
    admin_acceptance_path: str
    admin_acceptance_sha256: str = Field(pattern=SHA256_PATTERN)
    admin_task_id: str
    independent_report_path: str
    independent_report_sha256: str = Field(pattern=SHA256_PATTERN)
    catalog_status: Literal["EVIDENCE_CATALOG_VERIFIED"] = "EVIDENCE_CATALOG_VERIFIED"
    semantics_status: Literal["SEMANTICS_STILL_UNRESOLVED"] = "SEMANTICS_STILL_UNRESOLVED"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    admin_non_authoritative_hash_field_ignored: Literal[True] = True


class P6SourceSpec(FrozenModel):
    schema_version: Literal[1] = 1
    source_id: str
    requested_url: str
    allowed_redirect_urls: tuple[str, ...] = ()
    source_role: Literal[
        "macao_government_law_enforcement_notice",
        "macao_regulator_scope_index",
        "macao_regulator_chinese_lottery_reference",
        "hong_kong_nonoperator_rules_comparator",
    ]
    credential_class: Literal["government_primary", "regulator_primary", "licensed_foreign_operator"]
    jurisdiction: Literal["Macao SAR", "Hong Kong SAR"]
    non_operator_reference: bool
    dicj_reference_only: bool
    macau_product_claim_eligible: bool
    target_ruleclaim_vote_weight: Literal[0] = 0
    required_fragments: tuple[str, ...]

    @model_validator(mode="after")
    def validate_role_boundary(self) -> P6SourceSpec:
        if not self.required_fragments or any(not item.strip() for item in self.required_fragments):
            raise ValueError("P6 source specs require non-empty pre-fetch fragments")
        if self.source_role == "hong_kong_nonoperator_rules_comparator":
            if not self.non_operator_reference or self.macau_product_claim_eligible:
                raise ValueError("HKJC must remain a non-operator comparator")
        elif self.non_operator_reference:
            raise ValueError("only the foreign comparator may be non_operator_reference")
        if self.source_role == "macao_government_law_enforcement_notice":
            if not self.macau_product_claim_eligible:
                raise ValueError("only the PJ notice carries the direct denial claim")
        elif self.macau_product_claim_eligible:
            raise ValueError("DICJ/HKJC context cannot replace the direct PJ denial")
        if self.dicj_reference_only != self.source_role.startswith("macao_regulator_"):
            raise ValueError("DICJ reference-only disclaimer must stay on DICJ rows")
        return self


class P6CaptureContractSpec(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal[P6_RESOLUTION_KEY] = P6_RESOLUTION_KEY
    p5_acceptance: P6P5AcceptancePin
    method: Literal["GET"] = "GET"
    sources: tuple[P6SourceSpec, ...]
    network_scope: Literal["single_resource_exact_allowlist_capture_only"] = (
        "single_resource_exact_allowlist_capture_only"
    )
    network_permitted: Literal[True] = True
    warc_version: Literal["WARC/1.1"] = "WARC/1.1"
    warc_compression: Literal["none"] = "none"
    capture_representation: Literal["normalized_http_response_entity_body_v1"] = (
        "normalized_http_response_entity_body_v1"
    )
    redirect_policy: Literal["exact_prefrozen_urls_only"] = "exact_prefrozen_urls_only"
    max_redirects: Literal[0] = 0
    connect_and_read_timeout_seconds: Literal[20] = 20
    max_wall_seconds_per_source: Literal[30] = 30
    max_source_bytes: Literal[2_000_000] = 2_000_000
    max_total_bytes: Literal[8_000_000] = 8_000_000
    max_response_header_bytes: Literal[65_536] = 65_536
    user_agent: Literal["XinaoMarketLab-P6EvidenceCapture/1.0 (+local research; no crawl)"] = (
        "XinaoMarketLab-P6EvidenceCapture/1.0 (+local research; no crawl)"
    )
    accept: Literal["text/html,application/xhtml+xml"] = "text/html,application/xhtml+xml"
    accept_encoding: Literal["identity"] = "identity"
    proxy_permitted: Literal[False] = False
    cookies_permitted: Literal[False] = False
    authorization_permitted: Literal[False] = False
    request_body_permitted: Literal[False] = False
    embedded_asset_fetch_permitted: Literal[False] = False
    commercial_or_farm_fetch_permitted: Literal[False] = False
    supported_charsets: tuple[
        Literal["utf-8"],
        Literal["big5"],
        Literal["gb18030"],
        Literal["windows-1252"],
        Literal["iso-8859-1"],
    ] = ("utf-8", "big5", "gb18030", "windows-1252", "iso-8859-1")
    html_extraction_profile: Literal["strict_declared_charset_static_markup_text_nfc_whitespace_v1"] = (
        "strict_declared_charset_static_markup_text_nfc_whitespace_v1"
    )
    dependency: Literal["warcio==1.8.1"] = "warcio==1.8.1"

    @model_validator(mode="after")
    def validate_capture_surface(self) -> P6CaptureContractSpec:
        if tuple(item.source_id for item in self.sources) != tuple(
            item.source_id for item in p6_source_specs()
        ):
            raise ValueError("P6 exact four-source order drifted")
        if self.sources != p6_source_specs():
            raise ValueError("P6 source URL, role, or pre-fetch fragment drifted")
        return self


class P6CaptureContract(FrozenModel):
    spec: P6CaptureContractSpec
    contract_hash: str = Field(pattern=SHA256_PATTERN)
    capture_id: str = Field(pattern=r"^capture-p6-[0-9a-f]{24}$")


class P6CaptureRecord(FrozenModel):
    schema_version: Literal[1] = 1
    source_id: str
    requested_url: str
    final_url: str
    redirect_chain: tuple[str, ...] = ()
    resolved_ips: tuple[str, ...]
    peer_ip: str
    status: Literal[200] = 200
    reason: str
    content_type: str
    charset: str
    etag: str | None = None
    last_modified: str | None = None
    server_date: str | None = None
    capture_time_utc: str
    body_sha256: str = Field(pattern=SHA256_PATTERN)
    body_size_bytes: int = Field(gt=0, le=2_000_000)
    warc_response_record_id: str = Field(pattern=WARC_ID_PATTERN)
    warc_request_record_id: str = Field(pattern=WARC_ID_PATTERN)
    stripped_response_headers: tuple[str, ...]


class P6CaptureManifest(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal[P6_RESOLUTION_KEY] = P6_RESOLUTION_KEY
    capture_id: str
    contract_hash: str = Field(pattern=SHA256_PATTERN)
    contract_artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_events_sha256: str = Field(pattern=SHA256_PATTERN)
    warc_filename: Literal[P6_WARC_FILENAME] = P6_WARC_FILENAME
    warc_version: Literal["WARC/1.1"] = "WARC/1.1"
    warc_sha256: str = Field(pattern=SHA256_PATTERN)
    warc_size_bytes: int = Field(gt=0)
    warcio_version: Literal["1.8.1"] = "1.8.1"
    source_count: Literal[4] = 4
    total_body_bytes: int = Field(gt=0, le=8_000_000)
    records: tuple[P6CaptureRecord, P6CaptureRecord, P6CaptureRecord, P6CaptureRecord]


class P6CaptureBundlePin(FrozenModel):
    schema_version: Literal[1] = 1
    capture_id: str
    contract_hash: str = Field(pattern=SHA256_PATTERN)
    contract_artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_events_sha256: str = Field(pattern=SHA256_PATTERN)
    capture_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    warc_sha256: str = Field(pattern=SHA256_PATTERN)
    warc_size_bytes: int = Field(gt=0)
    source_body_sha256: dict[str, str]
    capture_anchor_sha256: str = Field(pattern=SHA256_PATTERN)


class P6ProtocolSpec(FrozenModel):
    schema_version: Literal[1] = 1
    resolution_key: Literal[P6_RESOLUTION_KEY] = P6_RESOLUTION_KEY
    p5_acceptance: P6P5AcceptancePin
    capture_bundle: P6CaptureBundlePin
    source_specs: tuple[P6SourceSpec, ...]
    rule_claim_subjects: tuple[
        Literal["payout_basis", "special_two_sided_49_policy"],
        Literal["payout_basis", "special_two_sided_49_policy"],
    ] = ("payout_basis", "special_two_sided_49_policy")
    network_permitted: Literal[False] = False
    operator_rule_truth_upgrade_permitted: Literal[False] = False
    semantics_compilation_permitted: Literal[False] = False
    economic_claim_permitted: Literal[False] = False
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False
    qft_annex_included: Literal[False] = False
    mirror_multiplicity_votes_permitted: Literal[False] = False
    provenance_concepts: tuple[
        Literal["prov_entity"],
        Literal["prov_activity"],
        Literal["prov_wasDerivedFrom"],
    ] = ("prov_entity", "prov_activity", "prov_wasDerivedFrom")

    @model_validator(mode="after")
    def validate_formal_boundary(self) -> P6ProtocolSpec:
        if self.source_specs != p6_source_specs():
            raise ValueError("P6 formal source-role surface drifted")
        return self


class P6Protocol(FrozenModel):
    spec: P6ProtocolSpec
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_bundle_id: str = Field(pattern=r"^bundle-p6-[0-9a-f]{24}$")


class P6TextQuoteSelector(FrozenModel):
    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"
    exact: str
    prefix: str
    suffix: str


class P6TextPositionSelector(FrozenModel):
    type: Literal["TextPositionSelector"] = "TextPositionSelector"
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> P6TextPositionSelector:
        if self.end <= self.start:
            raise ValueError("P6 TextPositionSelector must be non-empty")
        return self


class P6TextSelectorSet(FrozenModel):
    type: Literal["TextSelectorSet"] = "TextSelectorSet"
    extraction_profile: Literal["strict_declared_charset_static_markup_text_nfc_whitespace_v1"] = (
        "strict_declared_charset_static_markup_text_nfc_whitespace_v1"
    )
    text_quote: P6TextQuoteSelector
    text_position: P6TextPositionSelector


class P6EvidenceRecord(FrozenModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=0)
    evidence_bundle_id: str
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    evidence_id: str
    source_id: str
    source_role: str
    body_sha256: str = Field(pattern=SHA256_PATTERN)
    claim_scope: Literal[
        "macau_official_product_status",
        "regulated_product_taxonomy_context",
        "official_instrument_shape_nonoperator",
    ]
    selected_text: str
    selected_text_sha256: str = Field(pattern=SHA256_PATTERN)
    selector: P6TextSelectorSet
    interpretation_code: Literal[
        "direct_regulator_denial_primary_evidence",
        "regulator_scope_context_not_operator_semantics",
        "foreign_instrument_shape_only_not_target_semantics",
    ]
    previous_hash: str = Field(pattern=SHA256_PATTERN)
    record_hash: str = Field(pattern=SHA256_PATTERN)


class P6JudgeGate(FrozenModel):
    schema_version: Literal[1] = 1
    evidence_bundle_id: str
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    public_source_status: Literal["PUBLIC_PRIMARY_SOURCE_BUNDLE_VERIFIED"] = (
        "PUBLIC_PRIMARY_SOURCE_BUNDLE_VERIFIED"
    )
    macau_official_product_claim_status: Literal["MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED"] = (
        "MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED"
    )
    semantics_status: Literal["SEMANTICS_STILL_UNRESOLVED"] = "SEMANTICS_STILL_UNRESOLVED"
    economic_claim_status: Literal["ECONOMIC_CLAIM_BLOCKED"] = "ECONOMIC_CLAIM_BLOCKED"
    rule_claim_statuses: dict[
        Literal["payout_basis", "special_two_sided_49_policy"],
        Literal["INSUFFICIENT_TARGET_OPERATOR_EVIDENCE"],
    ]
    exact_w1_domain_legal_status: Literal["NOT_DETERMINED"] = "NOT_DETERMINED"
    checks: dict[str, bool]
    public_primary_source_bundle_verified: Literal[True] = True
    operator_rule_truth_verified: Literal[False] = False
    source_truth_verified_for_target_operator: Literal[False] = False
    semantics_compilation_permitted: Literal[False] = False
    historical_price_availability_verified: Literal[False] = False
    ranking_permitted: Literal[False] = False
    recommendation_permitted: Literal[False] = False
    real_money_use_permitted: Literal[False] = False
    whole_project_complete: Literal[False] = False

    @model_validator(mode="after")
    def validate_gate(self) -> P6JudgeGate:
        if set(self.rule_claim_statuses) != {"payout_basis", "special_two_sided_49_policy"}:
            raise ValueError("P6 Judge requires both unresolved target RuleClaims")
        if not self.checks or not all(self.checks.values()):
            raise ValueError("P6 Judge requires every acceptance check")
        return self


def p6_source_specs() -> tuple[P6SourceSpec, ...]:
    return (
        P6SourceSpec(
            source_id="gov_pj_787749",
            requested_url="https://www.gov.mo/zh-hans/news/787749/",
            source_role="macao_government_law_enforcement_notice",
            credential_class="government_primary",
            jurisdiction="Macao SAR",
            non_operator_reference=False,
            dicj_reference_only=False,
            macau_product_claim_eligible=True,
            required_fragments=(
                "澳门特区政府从没有批准任何公司经营",
                "名义的网站均属虚假及非法",
            ),
        ),
        P6SourceSpec(
            source_id="dicj_legislation_index",
            requested_url="https://www.dicj.gov.mo/web/en/legislation/index.html",
            source_role="macao_regulator_scope_index",
            credential_class="regulator_primary",
            jurisdiction="Macao SAR",
            non_operator_reference=False,
            dicj_reference_only=True,
            macau_product_claim_eligible=False,
            required_fragments=(
                "Instant Lottery",
                "Sports Lottery",
                "Chinese Lottery (Pacapio)",
            ),
        ),
        P6SourceSpec(
            source_id="dicj_pacapio",
            requested_url="https://www.dicj.gov.mo/web/cn/legislation/LotCh/index.html",
            source_role="macao_regulator_chinese_lottery_reference",
            credential_class="regulator_primary",
            jurisdiction="Macao SAR",
            non_operator_reference=False,
            dicj_reference_only=True,
            macau_product_claim_eligible=False,
            required_fragments=("中式彩票 (白鴿票)", "榮興彩票有限公司"),
        ),
        P6SourceSpec(
            source_id="hkjc_marksix_rules_hub",
            requested_url=("https://special.hkjc.com/e-win/en-US/betting-info/marksix/lotteries-rules/"),
            source_role="hong_kong_nonoperator_rules_comparator",
            credential_class="licensed_foreign_operator",
            jurisdiction="Hong Kong SAR",
            non_operator_reference=True,
            dicj_reference_only=False,
            macau_product_claim_eligible=False,
            required_fragments=(
                "HKJC Lotteries Limited",
                "These Rules have been made by the Board of Directors",
                "official website shall prevail",
            ),
        ),
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _duplicate_rejector(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_duplicate_rejector)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_exclusive(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return _sha256_bytes(payload)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _uuid_urn(material: str) -> str:
    return f"<urn:uuid:{uuid.uuid5(P6_UUID_NAMESPACE, material)}>"


def _hash_model(value: BaseModel) -> str:
    return _sha256_bytes(_canonical_json_bytes(value.model_dump(mode="json")))


def _chain_records(rows: list[dict[str, Any]]) -> bytes:
    previous = "0" * 64
    payloads: list[bytes] = []
    for sequence, row in enumerate(rows):
        material = {**row, "sequence": sequence, "previous_hash": previous}
        record_hash = _sha256_bytes(_canonical_json_bytes(material))
        complete = {**material, "record_hash": record_hash}
        payloads.append(_canonical_json_bytes(complete))
        previous = record_hash
    return b"".join(payloads)


def _verify_generic_chain(payload: bytes) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    previous = "0" * 64
    for expected_sequence, line in enumerate(payload.splitlines()):
        row = json.loads(line, object_pairs_hook=_duplicate_rejector)
        if not isinstance(row, dict):
            raise ValueError("hash-chain row must be a JSON object")
        if row.get("sequence") != expected_sequence or row.get("previous_hash") != previous:
            raise ValueError("hash-chain sequence or previous hash drift")
        material = {key: value for key, value in row.items() if key != "record_hash"}
        expected_hash = _sha256_bytes(_canonical_json_bytes(material))
        if row.get("record_hash") != expected_hash:
            raise ValueError("hash-chain record hash mismatch")
        previous = expected_hash
        rows.append(row)
    return tuple(rows)


def build_p6_p5_acceptance_pin(
    *,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
) -> P6P5AcceptancePin:
    p5_run_dir = p5_run_dir.resolve()
    p5_trusted_anchor = p5_trusted_anchor.resolve()
    p5_admin_acceptance = p5_admin_acceptance.resolve()
    p5_independent_report = p5_independent_report.resolve()
    manifest_path = p5_run_dir / "run_manifest.json"
    protocol_path = p5_run_dir / "p5_protocol.json"
    judge_path = p5_run_dir / "judge_gate_p5.json"
    scan_path = p5_run_dir / "local_packet_scan.json"
    source_contract_path = p5_run_dir / "source_scan_contract.json"
    evidence_path = p5_run_dir / "evidence_ledger.jsonl"
    manifest = _read_json_object(manifest_path)
    protocol = _read_json_object(protocol_path)
    judge = _read_json_object(judge_path)
    scan = _read_json_object(scan_path)
    source_contract = _read_json_object(source_contract_path)
    anchor = _read_json_object(p5_trusted_anchor)
    admin = _read_json_object(p5_admin_acceptance)
    independent = _read_json_object(p5_independent_report)
    if manifest.get("status") != (
        "verified_evidence_catalog_semantics_still_unresolved_economic_claims_blocked"
    ):
        raise ValueError("P6 requires the accepted P5 formal status")
    if (
        judge.get("catalog_status") != "EVIDENCE_CATALOG_VERIFIED"
        or judge.get("semantics_status") != "SEMANTICS_STILL_UNRESOLVED"
        or judge.get("economic_claim_status") != "ECONOMIC_CLAIM_BLOCKED"
    ):
        raise ValueError("P6 requires the accepted P5 Judge boundary")
    protocol_hash = str(protocol["protocol_hash"])
    protocol_artifact_sha256 = _sha256_file(protocol_path)
    manifest_sha256 = _sha256_file(manifest_path)
    evidence_sha256 = _sha256_file(evidence_path)
    anchor_pins = {
        "protocol_hash": protocol_hash,
        "protocol_artifact_sha256": protocol_artifact_sha256,
        "run_manifest_sha256": manifest_sha256,
        "source_scan_contract_sha256": _sha256_file(source_contract_path),
        "evidence_ledger_sha256": evidence_sha256,
        "evidence_chain_tip": scan["evidence_chain_tip"],
        "judge_gate_sha256": _sha256_file(judge_path),
    }
    if any(anchor.get(key) != value for key, value in anchor_pins.items()):
        raise ValueError("P5 trusted anchor does not bind the selected formal run")
    if (
        admin.get("verdict") != "accepted"
        or admin.get("resolution_key") != "p5-unresolved-semantics-evidence-catalog-v1"
        or admin.get("hashes", {}).get("protocol_hash") != protocol_hash
        or admin.get("hashes", {}).get("trusted_anchor_sha256") != _sha256_file(p5_trusted_anchor)
        or admin.get("hashes", {}).get("run_manifest_a_sha256") != manifest_sha256
    ):
        raise ValueError("P6 requires the P5 Admin task/verdict delivery witness")
    if (
        independent.get("status") != "verified"
        or independent.get("verifier_kind") != "independent_stdlib_rebuild_no_production_import"
        or independent.get("production_imports") != []
        or independent.get("protocol_hash") != protocol_hash
        or independent.get("anchor_sha256") != _sha256_file(p5_trusted_anchor)
        or independent.get("catalog_status") != "EVIDENCE_CATALOG_VERIFIED"
        or independent.get("semantics_status") != "SEMANTICS_STILL_UNRESOLVED"
        or independent.get("economic_claim_status") != "ECONOMIC_CLAIM_BLOCKED"
    ):
        raise ValueError("P6 requires the independent stdlib P5 acceptance report")
    entries = source_contract.get("entries")
    if not isinstance(entries, list):
        raise ValueError("P5 source scan contract entries are missing")
    page_catalog = [
        row
        for row in entries
        if isinstance(row, dict)
        and row.get("relative_path", "").endswith("/analysis_ready/page_catalog_all_sources.csv")
    ]
    if len(page_catalog) != 1 or not _is_sha256(page_catalog[0].get("source_sha256")):
        raise ValueError("P5 page-catalog origin evidence pin is missing")
    return P6P5AcceptancePin(
        p5_run_directory=str(p5_run_dir),
        p5_run_manifest_sha256=manifest_sha256,
        p5_protocol_hash=protocol_hash,
        p5_protocol_artifact_sha256=protocol_artifact_sha256,
        catalog_id=str(protocol["catalog_id"]),
        evidence_ledger_sha256=evidence_sha256,
        evidence_chain_tip=str(scan["evidence_chain_tip"]),
        p5_page_catalog_sha256=str(page_catalog[0]["source_sha256"]),
        trusted_anchor_path=str(p5_trusted_anchor),
        trusted_anchor_sha256=_sha256_file(p5_trusted_anchor),
        admin_acceptance_path=str(p5_admin_acceptance),
        admin_acceptance_sha256=_sha256_file(p5_admin_acceptance),
        admin_task_id=str(admin["task_id"]),
        independent_report_path=str(p5_independent_report),
        independent_report_sha256=_sha256_file(p5_independent_report),
    )


def build_p6_capture_contract(p5_acceptance: P6P5AcceptancePin) -> P6CaptureContract:
    spec = P6CaptureContractSpec(
        p5_acceptance=p5_acceptance,
        sources=p6_source_specs(),
    )
    contract_hash = _hash_model(spec)
    return P6CaptureContract(
        spec=spec,
        contract_hash=contract_hash,
        capture_id=f"capture-p6-{contract_hash[:24]}",
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _validate_exact_https_url(url: str, expected: str) -> urllib.parse.SplitResult:
    if url != expected or not url.isascii():
        raise ValueError("request URL differs from the exact pre-frozen ASCII allowlist")
    if any(ord(character) < 32 for character in url) or "\\" in url:
        raise ValueError("request URL contains a control character or backslash")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in (None, 443)
        or not parsed.hostname
        or parsed.hostname.endswith(".")
        or parsed.hostname.startswith("xn--")
    ):
        raise ValueError("P6 permits only exact HTTPS/443 URLs without userinfo or fragments")
    return parsed


def _global_dns_addresses(host: str) -> tuple[str, ...]:
    addresses = sorted(
        {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM) if item[4]}
    )
    if not addresses:
        raise ValueError(f"DNS returned no address for {host}")
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global:
            raise ValueError(f"non-global DNS address rejected for {host}: {address}")
    return tuple(addresses)


def _response_peer_ip(response: Any) -> str:
    current = getattr(response, "fp", None)
    for attribute in ("raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            break
    if current is None or not hasattr(current, "getpeername"):
        raise ValueError("could not prove the HTTPS peer IP")
    address = str(current.getpeername()[0])
    if not ipaddress.ip_address(address).is_global:
        raise ValueError(f"non-global HTTPS peer IP rejected: {address}")
    return address


def _header_values(headers: Any, name: str) -> list[str]:
    return [value for key, value in headers.raw_items() if key.casefold() == name.casefold()]


def _normalize_charset(value: str) -> str:
    normalized = value.strip().strip("\"'").casefold()
    if normalized not in _SUPPORTED_CHARSETS:
        raise ValueError(f"unsupported declared HTML charset: {value}")
    return _SUPPORTED_CHARSETS[normalized]


def _resolve_charset(headers: Any, body: bytes) -> str:
    content_type = headers.get("Content-Type", "")
    header_match = re.search(r"charset\s*=\s*[\"']?([^;\"'\s]+)", content_type, re.I)
    header_charset = _normalize_charset(header_match.group(1)) if header_match else None
    bom_charset = "utf-8" if body.startswith(b"\xef\xbb\xbf") else None
    prefix = body[:8192].decode("latin-1")
    meta_match = re.search(
        r"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
        prefix,
        re.I,
    )
    meta_charset = _normalize_charset(meta_match.group(1)) if meta_match else None
    declared = [item for item in (bom_charset, header_charset, meta_charset) if item is not None]
    if len(set(declared)) > 1:
        raise ValueError(f"conflicting BOM/header/meta charsets: {declared}")
    return declared[0] if declared else "utf-8"


class _StaticMarkupText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, bool]] = []
        self._parts: list[str] = []

    def _hidden(self) -> bool:
        return any(hidden for _, hidden in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attr_map = {key.casefold(): (value or "") for key, value in attrs}
        style = attr_map.get("style", "").replace(" ", "").casefold()
        hidden = (
            self._hidden()
            or tag in _IGNORED_MARKUP_TAGS
            or "hidden" in attr_map
            or attr_map.get("aria-hidden", "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        self._stack.append((tag, hidden))
        if not hidden and tag in _BLOCK_MARKUP_TAGS:
            self._parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        index = next(
            (position for position in range(len(self._stack) - 1, -1, -1) if self._stack[position][0] == tag),
            None,
        )
        if index is None:
            return
        hidden = self._stack[index][1]
        del self._stack[index:]
        if not hidden and tag in _BLOCK_MARKUP_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden():
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts).replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", joined)).strip()


def _static_markup_text(body: bytes, charset: str) -> str:
    decoded = body.decode(charset, errors="strict")
    if decoded.startswith("\ufeff"):
        decoded = decoded[1:]
    if "\x00" in decoded:
        raise ValueError("NUL is forbidden in P6 HTML evidence")
    parser = _StaticMarkupText()
    parser.feed(decoded)
    parser.close()
    text = parser.text()
    if not text:
        raise ValueError("P6 HTML extraction produced no static markup text")
    return text


def _request_headers(
    contract: P6CaptureContract, parsed: urllib.parse.SplitResult
) -> tuple[tuple[str, str], ...]:
    return (
        ("Host", str(parsed.hostname)),
        ("User-Agent", contract.spec.user_agent),
        ("Accept", contract.spec.accept),
        ("Accept-Encoding", contract.spec.accept_encoding),
        ("Connection", "close"),
    )


def _fetch_one(
    *,
    contract: P6CaptureContract,
    source: P6SourceSpec,
    opener: urllib.request.OpenerDirector,
) -> tuple[P6CaptureRecord, bytes, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    parsed = _validate_exact_https_url(source.requested_url, source.requested_url)
    resolved_ips = _global_dns_addresses(str(parsed.hostname))
    request_headers = _request_headers(contract, parsed)
    if _FORBIDDEN_REQUEST_HEADERS.intersection(name.casefold() for name, _ in request_headers):
        raise ValueError("forbidden credential or tracking request header")
    request = urllib.request.Request(
        source.requested_url,
        method="GET",
        headers=dict(request_headers),
        data=None,
    )
    started = time.monotonic()
    try:
        response = opener.open(
            request,
            timeout=contract.spec.connect_and_read_timeout_seconds,
        )
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            location = error.headers.get("Location")
            raise ValueError(f"P6 unexpected redirect rejected: {error.code} {location}") from error
        raise
    with response:
        peer_ip = _response_peer_ip(response)
        if response.geturl() != source.requested_url:
            raise ValueError("automatic redirect occurred despite the no-redirect opener")
        if response.status != 200:
            raise ValueError(f"P6 final HTTP status must be 200, got {response.status}")
        header_size = sum(
            len(name.encode("utf-8")) + len(value.encode("utf-8")) + 4
            for name, value in response.headers.raw_items()
        )
        if header_size > contract.spec.max_response_header_bytes:
            raise ValueError("P6 response headers exceed the frozen size limit")
        transfer_encoding = _header_values(response.headers, "Transfer-Encoding")
        content_lengths = _header_values(response.headers, "Content-Length")
        if transfer_encoding and content_lengths:
            raise ValueError("P6 rejects Transfer-Encoding plus Content-Length ambiguity")
        if transfer_encoding and [item.casefold() for item in transfer_encoding] != ["chunked"]:
            raise ValueError("P6 only tolerates urllib-dechunked transfer-encoding: chunked")
        if content_lengths:
            if len(set(content_lengths)) != 1 or not content_lengths[0].isdigit():
                raise ValueError("P6 rejects conflicting or invalid Content-Length")
            if int(content_lengths[0]) > contract.spec.max_source_bytes:
                raise ValueError("P6 declared Content-Length exceeds the frozen body limit")
        content_encoding = _header_values(response.headers, "Content-Encoding")
        if content_encoding and [item.casefold() for item in content_encoding] != ["identity"]:
            raise ValueError("P6 rejects non-identity Content-Encoding")
        content_type = response.headers.get("Content-Type", "")
        if not content_type.casefold().startswith(("text/html", "application/xhtml+xml")):
            raise ValueError(f"P6 source is not HTML: {content_type}")
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() - started > contract.spec.max_wall_seconds_per_source:
                raise TimeoutError("P6 source exceeded the frozen wall-clock limit")
            chunk = response.read(min(65_536, contract.spec.max_source_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > contract.spec.max_source_bytes:
                raise ValueError("P6 source exceeded the streaming body limit")
        body = b"".join(chunks)
        if not body:
            raise ValueError("P6 source returned an empty body")
        if content_lengths and len(body) != int(content_lengths[0]):
            raise ValueError("P6 body length differs from Content-Length")
        charset = _resolve_charset(response.headers, body)
        text = _static_markup_text(body, charset)
        missing_fragments = [fragment for fragment in source.required_fragments if fragment not in text]
        if missing_fragments:
            raise ValueError(
                f"P6 pre-frozen source fragments missing for {source.source_id}: {missing_fragments}"
            )
        captured_at = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        body_sha256 = _sha256_bytes(body)
        response_id = _uuid_urn(
            f"{contract.contract_hash}:{source.source_id}:response:{body_sha256}:{captured_at}"
        )
        request_id = _uuid_urn(
            f"{contract.contract_hash}:{source.source_id}:request:{body_sha256}:{captured_at}"
        )
        stripped = sorted(
            {
                name.casefold()
                for name, _value in response.headers.raw_items()
                if name.casefold()
                in {
                    "set-cookie",
                    "transfer-encoding",
                    "trailer",
                    "content-length",
                    "content-encoding",
                }
            }
        )
        normalized_headers: list[tuple[str, str]] = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
        ]
        for name in ("Date", "ETag", "Last-Modified", "Cache-Control"):
            value = response.headers.get(name)
            if value is not None:
                normalized_headers.append((name, value))
        record = P6CaptureRecord(
            source_id=source.source_id,
            requested_url=source.requested_url,
            final_url=source.requested_url,
            resolved_ips=resolved_ips,
            peer_ip=peer_ip,
            reason=str(response.reason),
            content_type=content_type,
            charset=charset,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            server_date=response.headers.get("Date"),
            capture_time_utc=captured_at,
            body_sha256=body_sha256,
            body_size_bytes=len(body),
            warc_response_record_id=response_id,
            warc_request_record_id=request_id,
            stripped_response_headers=tuple(stripped),
        )
        return record, body, request_headers, tuple(normalized_headers)


def _warcinfo_payload(contract: P6CaptureContract) -> bytes:
    rows = (
        ("software", f"xinao-market-lab warcio/{importlib.metadata.version('warcio')}"),
        ("format", "WARC File Format 1.1"),
        ("isPartOf", contract.capture_id),
        ("description", P6_RESOLUTION_KEY),
    )
    return "".join(f"{name}: {value}\r\n" for name, value in rows).encode("utf-8")


def capture_p6_official_sources(
    *,
    capture_root: Path,
    capture_name: str,
    capture_anchor_path: Path,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
) -> dict[str, Any]:
    p5_acceptance = build_p6_p5_acceptance_pin(
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    contract = build_p6_capture_contract(p5_acceptance)
    capture_root = capture_root.resolve()
    capture_dir = capture_root / capture_name
    capture_anchor_path = capture_anchor_path.resolve()
    if Path(p5_acceptance.p5_run_directory).drive.casefold() == "d:" and not _is_under(
        capture_dir, CANONICAL_RUN_ROOT
    ):
        raise ValueError(f"canonical P6 capture must stay under {CANONICAL_RUN_ROOT}")
    if _is_under(capture_anchor_path, capture_dir):
        raise ValueError("P6 capture anchor must be outside the capture directory")
    if capture_dir.exists():
        raise FileExistsError(f"immutable P6 capture already exists: {capture_dir}")
    if capture_anchor_path.exists():
        raise FileExistsError(f"immutable P6 capture anchor already exists: {capture_anchor_path}")
    capture_root.mkdir(parents=True, exist_ok=True)
    staging = capture_root / f".{capture_name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(exist_ok=False)
    contract_payload = _canonical_json_bytes(contract.model_dump(mode="json"))
    contract_sha256 = _write_exclusive(staging / "capture_contract.json", contract_payload)
    readback = P6CaptureContract.model_validate_json(
        (staging / "capture_contract.json").read_text(encoding="utf-8"),
        strict=True,
    )
    if readback != contract or _hash_model(readback.spec) != readback.contract_hash:
        raise ValueError("P6 capture contract failed frozen pre-fetch readback")
    events: list[dict[str, Any]] = [
        {
            "event": "capture_contract_frozen_before_network",
            "capture_id": contract.capture_id,
            "contract_hash": contract.contract_hash,
            "contract_artifact_sha256": contract_sha256,
        }
    ]
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    records: list[P6CaptureRecord] = []
    total_body_bytes = 0
    warc_path = staging / P6_WARC_FILENAME
    with warc_path.open("xb") as stream:
        writer = WARCWriter(stream, gzip=False, warc_version="1.1")
        capture_started = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        info_payload = _warcinfo_payload(contract)
        info = writer.create_warc_record(
            "",
            "warcinfo",
            payload=BytesIO(info_payload),
            length=len(info_payload),
            warc_headers_dict={
                "WARC-Record-ID": _uuid_urn(f"{contract.contract_hash}:warcinfo"),
                "WARC-Date": capture_started,
                "WARC-Filename": P6_WARC_FILENAME,
            },
        )
        writer.write_record(info)
        for source in contract.spec.sources:
            events.append(
                {
                    "event": "exact_get_started",
                    "source_id": source.source_id,
                    "requested_url": source.requested_url,
                }
            )
            record, body, request_headers, normalized_headers = _fetch_one(
                contract=contract,
                source=source,
                opener=opener,
            )
            total_body_bytes += len(body)
            if total_body_bytes > contract.spec.max_total_bytes:
                raise ValueError("P6 capture exceeded the frozen total body limit")
            parsed = urllib.parse.urlsplit(record.final_url)
            response_http = StatusAndHeaders(
                f"{record.status} {record.reason}",
                list(normalized_headers),
                protocol="HTTP/1.1",
            )
            request_target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            request_http = StatusAndHeaders(
                f"GET {request_target} HTTP/1.1",
                list(request_headers),
                is_http_request=True,
            )
            response_record = writer.create_warc_record(
                record.final_url,
                "response",
                payload=BytesIO(body),
                length=len(body),
                http_headers=response_http,
                warc_headers_dict={
                    "WARC-Record-ID": record.warc_response_record_id,
                    "WARC-Date": record.capture_time_utc,
                },
            )
            request_record = writer.create_warc_record(
                record.requested_url,
                "request",
                payload=BytesIO(),
                length=0,
                http_headers=request_http,
                warc_headers_dict={
                    "WARC-Record-ID": record.warc_request_record_id,
                    "WARC-Date": record.capture_time_utc,
                },
            )
            writer.write_request_response_pair(request_record, response_record)
            records.append(record)
            events.append(
                {
                    "event": "normalized_response_captured",
                    "source_id": source.source_id,
                    "body_sha256": record.body_sha256,
                    "body_size_bytes": record.body_size_bytes,
                    "warc_response_record_id": record.warc_response_record_id,
                    "warc_request_record_id": record.warc_request_record_id,
                }
            )
        stream.flush()
        os.fsync(stream.fileno())
    warc_sha256 = _sha256_file(warc_path)
    events.append(
        {
            "event": "capture_complete",
            "capture_id": contract.capture_id,
            "source_count": len(records),
            "total_body_bytes": total_body_bytes,
            "warc_sha256": warc_sha256,
        }
    )
    events_payload = _chain_records(events)
    events_sha256 = _write_exclusive(staging / "capture_events.jsonl", events_payload)
    manifest = P6CaptureManifest(
        capture_id=contract.capture_id,
        contract_hash=contract.contract_hash,
        contract_artifact_sha256=contract_sha256,
        capture_events_sha256=events_sha256,
        warc_sha256=warc_sha256,
        warc_size_bytes=warc_path.stat().st_size,
        total_body_bytes=total_body_bytes,
        records=tuple(records),  # type: ignore[arg-type]
    )
    manifest_payload = _canonical_json_bytes(manifest.model_dump(mode="json"))
    manifest_sha256 = _write_exclusive(staging / "capture_manifest.json", manifest_payload)
    expected_anchor = {
        "schema_version": 1,
        "resolution_key": P6_RESOLUTION_KEY,
        "capture_id": contract.capture_id,
        "contract_hash": contract.contract_hash,
        "contract_artifact_sha256": contract_sha256,
        "capture_events_sha256": events_sha256,
        "capture_manifest_sha256": manifest_sha256,
        "warc_sha256": warc_sha256,
        "warc_size_bytes": warc_path.stat().st_size,
        "source_body_sha256": {record.source_id: record.body_sha256 for record in records},
    }
    os.replace(staging, capture_dir)
    anchor_sha256 = _write_exclusive(
        capture_anchor_path,
        _canonical_json_bytes(expected_anchor),
    )
    verify_p6_capture_bundle(
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    return {
        "status": "capture_verified",
        "capture_dir": str(capture_dir),
        "capture_id": contract.capture_id,
        "contract_hash": contract.contract_hash,
        "warc_sha256": warc_sha256,
        "capture_manifest_sha256": manifest_sha256,
        "capture_anchor_path": str(capture_anchor_path),
        "capture_anchor_sha256": anchor_sha256,
        "source_count": len(records),
        "total_body_bytes": total_body_bytes,
    }


def _expected_capture_anchor(*, capture_dir: Path, manifest: P6CaptureManifest) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "resolution_key": P6_RESOLUTION_KEY,
        "capture_id": manifest.capture_id,
        "contract_hash": manifest.contract_hash,
        "contract_artifact_sha256": _sha256_file(capture_dir / "capture_contract.json"),
        "capture_events_sha256": _sha256_file(capture_dir / "capture_events.jsonl"),
        "capture_manifest_sha256": _sha256_file(capture_dir / "capture_manifest.json"),
        "warc_sha256": _sha256_file(capture_dir / P6_WARC_FILENAME),
        "warc_size_bytes": (capture_dir / P6_WARC_FILENAME).stat().st_size,
        "source_body_sha256": {record.source_id: record.body_sha256 for record in manifest.records},
    }


def _expected_http_request_line(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return f"GET {target} HTTP/1.1"


def _read_and_verify_warc(
    *,
    warc_path: Path,
    contract: P6CaptureContract,
    manifest: P6CaptureManifest,
) -> dict[str, bytes]:
    before_sha256 = _sha256_file(warc_path)
    if before_sha256 != manifest.warc_sha256 or warc_path.stat().st_size != manifest.warc_size_bytes:
        raise ValueError("P6 WARC file differs from the capture manifest")
    expected_sequence: list[tuple[str, P6CaptureRecord | None]] = [("warcinfo", None)]
    for record in manifest.records:
        expected_sequence.extend((("response", record), ("request", record)))
    bodies: dict[str, bytes] = {}
    seen_ids: set[str] = set()
    with warc_path.open("rb") as stream:
        iterator = ArchiveIterator(
            stream,
            verify_http=True,
            arc2warc=False,
            check_digests=True,
        )
        actual_count = 0
        for actual_count, warc_record in enumerate(iterator, start=1):
            if actual_count > len(expected_sequence):
                raise ValueError("P6 WARC contains an extra record")
            expected_type, expected_capture = expected_sequence[actual_count - 1]
            if warc_record.format != "warc" or warc_record.rec_headers.protocol != "WARC/1.1":
                raise ValueError("P6 requires strict WARC/1.1 records")
            if warc_record.rec_type != expected_type:
                raise ValueError("P6 WARC record type or order drifted")
            record_id = warc_record.rec_headers.get_header("WARC-Record-ID")
            if (
                not isinstance(record_id, str)
                or not re.fullmatch(WARC_ID_PATTERN, record_id)
                or record_id in seen_ids
            ):
                raise ValueError("P6 WARC record IDs must be unique canonical UUID URNs")
            seen_ids.add(record_id)
            if expected_type == "warcinfo":
                payload = warc_record.raw_stream.read()
                if contract.capture_id.encode("utf-8") not in payload:
                    raise ValueError("P6 WARC warcinfo does not bind the capture ID")
            elif expected_capture is not None and expected_type == "response":
                target = warc_record.rec_headers.get_header("WARC-Target-URI")
                if target != expected_capture.final_url:
                    raise ValueError("P6 response WARC target URI drifted")
                if record_id != expected_capture.warc_response_record_id:
                    raise ValueError("P6 response WARC record ID drifted")
                if warc_record.rec_headers.get_header("WARC-Date") != expected_capture.capture_time_utc:
                    raise ValueError("P6 response WARC capture time drifted")
                if warc_record.http_headers is None:
                    raise ValueError("P6 response WARC record lacks HTTP headers")
                if warc_record.http_headers.protocol != "HTTP/1.1":
                    raise ValueError("P6 normalized response must be HTTP/1.1")
                if warc_record.http_headers.get_statuscode() != "200":
                    raise ValueError("P6 normalized response status drifted")
                body = warc_record.content_stream().read()
                if (
                    _sha256_bytes(body) != expected_capture.body_sha256
                    or len(body) != expected_capture.body_size_bytes
                ):
                    raise ValueError("P6 response body differs from the capture manifest")
                if warc_record.http_headers.get_header("Content-Length") != str(len(body)):
                    raise ValueError("P6 normalized HTTP Content-Length drifted")
                if warc_record.http_headers.get_header("Content-Type") != expected_capture.content_type:
                    raise ValueError("P6 normalized HTTP Content-Type drifted")
                bodies[expected_capture.source_id] = body
            elif expected_capture is not None:
                target = warc_record.rec_headers.get_header("WARC-Target-URI")
                if target != expected_capture.requested_url:
                    raise ValueError("P6 request WARC target URI drifted")
                if record_id != expected_capture.warc_request_record_id:
                    raise ValueError("P6 request WARC record ID drifted")
                if (
                    warc_record.rec_headers.get_header("WARC-Date") != expected_capture.capture_time_utc
                    or warc_record.rec_headers.get_header("WARC-Concurrent-To")
                    != expected_capture.warc_response_record_id
                ):
                    raise ValueError("P6 request WARC time or response pairing drifted")
                if warc_record.http_headers is None:
                    raise ValueError("P6 request WARC record lacks HTTP headers")
                request_line = f"{warc_record.http_headers.protocol} {warc_record.http_headers.statusline}"
                if request_line != _expected_http_request_line(expected_capture.requested_url):
                    raise ValueError("P6 request method or request-target drifted")
                headers = tuple(warc_record.http_headers.headers)
                source = next(
                    item for item in contract.spec.sources if item.source_id == expected_capture.source_id
                )
                expected_headers = _request_headers(
                    contract,
                    urllib.parse.urlsplit(source.requested_url),
                )
                if headers != expected_headers:
                    raise ValueError("P6 request header surface drifted")
                if _FORBIDDEN_REQUEST_HEADERS.intersection(name.casefold() for name, _ in headers):
                    raise ValueError("P6 WARC contains a forbidden request credential header")
                if warc_record.content_stream().read() != b"":
                    raise ValueError("P6 GET request record must have an empty body")
            if warc_record.digest_checker.passed is not True:
                raise ValueError(f"P6 WARC digest verification failed: {warc_record.digest_checker.problems}")
        if actual_count != len(expected_sequence) or iterator.err_count != 0:
            raise ValueError("P6 WARC record count or parser integrity drifted")
    if set(bodies) != {source.source_id for source in contract.spec.sources}:
        raise ValueError("P6 WARC does not contain the exact four response bodies")
    if _sha256_file(warc_path) != before_sha256:
        raise ValueError("P6 WARC changed during offline verification")
    return bodies


def verify_p6_capture_bundle(
    *,
    capture_dir: Path,
    capture_anchor_path: Path,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
) -> dict[str, Any]:
    capture_dir = capture_dir.resolve()
    capture_anchor_path = capture_anchor_path.resolve()
    missing = [name for name in P6_CAPTURE_ARTIFACT_NAMES if not (capture_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P6 capture bundle is incomplete: {missing}")
    p5_acceptance = build_p6_p5_acceptance_pin(
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    expected_contract = build_p6_capture_contract(p5_acceptance)
    contract = P6CaptureContract.model_validate_json(
        (capture_dir / "capture_contract.json").read_text(encoding="utf-8"),
        strict=True,
    )
    if contract != expected_contract or _hash_model(contract.spec) != contract.contract_hash:
        raise ValueError("P6 capture contract differs from the independently rebuilt contract")
    manifest = P6CaptureManifest.model_validate_json(
        (capture_dir / "capture_manifest.json").read_text(encoding="utf-8"),
        strict=True,
    )
    if (
        manifest.capture_id != contract.capture_id
        or manifest.contract_hash != contract.contract_hash
        or manifest.contract_artifact_sha256 != _sha256_file(capture_dir / "capture_contract.json")
        or manifest.capture_events_sha256 != _sha256_file(capture_dir / "capture_events.jsonl")
        or manifest.warc_sha256 != _sha256_file(capture_dir / P6_WARC_FILENAME)
        or manifest.warc_size_bytes != (capture_dir / P6_WARC_FILENAME).stat().st_size
        or tuple(record.source_id for record in manifest.records)
        != tuple(source.source_id for source in contract.spec.sources)
        or manifest.total_body_bytes != sum(record.body_size_bytes for record in manifest.records)
    ):
        raise ValueError("P6 capture manifest no longer binds its exact bundle")
    event_rows = _verify_generic_chain((capture_dir / "capture_events.jsonl").read_bytes())
    if (
        len(event_rows) != 2 * len(contract.spec.sources) + 2
        or event_rows[0].get("event") != "capture_contract_frozen_before_network"
        or event_rows[-1].get("event") != "capture_complete"
        or event_rows[-1].get("warc_sha256") != manifest.warc_sha256
    ):
        raise ValueError("P6 capture event chain surface drifted")
    bodies = _read_and_verify_warc(
        warc_path=capture_dir / P6_WARC_FILENAME,
        contract=contract,
        manifest=manifest,
    )
    for source, record in zip(contract.spec.sources, manifest.records, strict=True):
        if (
            record.requested_url != source.requested_url
            or record.final_url != source.requested_url
            or record.redirect_chain
            or record.status != 200
            or _sha256_bytes(bodies[source.source_id]) != record.body_sha256
        ):
            raise ValueError("P6 capture source URL/status/body boundary drifted")
        text = _static_markup_text(bodies[source.source_id], record.charset)
        if any(fragment not in text for fragment in source.required_fragments):
            raise ValueError("P6 pre-frozen official source fragment no longer resolves")
    expected_anchor = _expected_capture_anchor(capture_dir=capture_dir, manifest=manifest)
    if _read_json_object(capture_anchor_path) != expected_anchor:
        raise ValueError("P6 external capture anchor mismatch")
    return {
        "status": "verified",
        "capture_id": contract.capture_id,
        "contract_hash": contract.contract_hash,
        "warc_sha256": manifest.warc_sha256,
        "capture_manifest_sha256": _sha256_file(capture_dir / "capture_manifest.json"),
        "capture_anchor_sha256": _sha256_file(capture_anchor_path),
        "source_count": len(manifest.records),
        "total_body_bytes": manifest.total_body_bytes,
    }


def _capture_bundle_pin(
    *,
    capture_dir: Path,
    capture_anchor_path: Path,
) -> P6CaptureBundlePin:
    manifest = P6CaptureManifest.model_validate_json(
        (capture_dir / "capture_manifest.json").read_text(encoding="utf-8"),
        strict=True,
    )
    return P6CaptureBundlePin(
        capture_id=manifest.capture_id,
        contract_hash=manifest.contract_hash,
        contract_artifact_sha256=manifest.contract_artifact_sha256,
        capture_events_sha256=manifest.capture_events_sha256,
        capture_manifest_sha256=_sha256_file(capture_dir / "capture_manifest.json"),
        warc_sha256=manifest.warc_sha256,
        warc_size_bytes=manifest.warc_size_bytes,
        source_body_sha256={record.source_id: record.body_sha256 for record in manifest.records},
        capture_anchor_sha256=_sha256_file(capture_anchor_path),
    )


def build_p6_protocol(
    *,
    p5_acceptance: P6P5AcceptancePin,
    capture_bundle: P6CaptureBundlePin,
) -> P6Protocol:
    spec = P6ProtocolSpec(
        p5_acceptance=p5_acceptance,
        capture_bundle=capture_bundle,
        source_specs=p6_source_specs(),
    )
    protocol_hash = _hash_model(spec)
    return P6Protocol(
        spec=spec,
        protocol_hash=protocol_hash,
        evidence_bundle_id=f"bundle-p6-{protocol_hash[:24]}",
    )


def _selector(text: str, fragment: str) -> P6TextSelectorSet:
    start = text.find(fragment)
    if start < 0:
        raise ValueError(f"P6 frozen fragment does not resolve: {fragment}")
    end = start + len(fragment)
    return P6TextSelectorSet(
        text_quote=P6TextQuoteSelector(
            exact=fragment,
            prefix=text[max(0, start - 48) : start],
            suffix=text[end : end + 48],
        ),
        text_position=P6TextPositionSelector(start=start, end=end),
    )


def _verify_selector(text: str, record: P6EvidenceRecord) -> None:
    selector = record.selector
    position = selector.text_position
    quote = selector.text_quote
    if text[position.start : position.end] != quote.exact:
        raise ValueError("P6 TextPosition/TextQuote exact selector drift")
    if text[max(0, position.start - len(quote.prefix)) : position.start] != quote.prefix:
        raise ValueError("P6 TextQuote prefix drift")
    if text[position.end : position.end + len(quote.suffix)] != quote.suffix:
        raise ValueError("P6 TextQuote suffix drift")
    if record.selected_text != quote.exact:
        raise ValueError("P6 selected text differs from its selector")
    if _sha256_bytes(record.selected_text.encode("utf-8")) != record.selected_text_sha256:
        raise ValueError("P6 selected text hash mismatch")


def _evidence_scope(source: P6SourceSpec) -> tuple[str, str]:
    if source.source_role == "macao_government_law_enforcement_notice":
        return "macau_official_product_status", "direct_regulator_denial_primary_evidence"
    if source.source_role.startswith("macao_regulator_"):
        return (
            "regulated_product_taxonomy_context",
            "regulator_scope_context_not_operator_semantics",
        )
    return (
        "official_instrument_shape_nonoperator",
        "foreign_instrument_shape_only_not_target_semantics",
    )


def _evidence_ledger(
    *,
    protocol: P6Protocol,
    contract: P6CaptureContract,
    manifest: P6CaptureManifest,
    bodies: dict[str, bytes],
) -> tuple[bytes, tuple[P6EvidenceRecord, ...], dict[str, str]]:
    capture_by_id = {record.source_id: record for record in manifest.records}
    records: list[P6EvidenceRecord] = []
    texts: dict[str, str] = {}
    previous = "0" * 64
    for source in contract.spec.sources:
        capture = capture_by_id[source.source_id]
        text = _static_markup_text(bodies[source.source_id], capture.charset)
        texts[source.source_id] = text
        claim_scope, interpretation = _evidence_scope(source)
        for fragment_index, fragment in enumerate(source.required_fragments):
            partial = {
                "schema_version": 1,
                "sequence": len(records),
                "evidence_bundle_id": protocol.evidence_bundle_id,
                "protocol_hash": protocol.protocol_hash,
                "evidence_id": (f"evidence-p6-{source.source_id}-{fragment_index + 1:02d}"),
                "source_id": source.source_id,
                "source_role": source.source_role,
                "body_sha256": capture.body_sha256,
                "claim_scope": claim_scope,
                "selected_text": fragment,
                "selected_text_sha256": _sha256_bytes(fragment.encode("utf-8")),
                "selector": _selector(text, fragment).model_dump(mode="json"),
                "interpretation_code": interpretation,
                "previous_hash": previous,
            }
            record_hash = _sha256_bytes(_canonical_json_bytes(partial))
            record = P6EvidenceRecord.model_validate(
                {**partial, "record_hash": record_hash},
                strict=True,
            )
            _verify_selector(text, record)
            records.append(record)
            previous = record_hash
    payload = b"".join(_canonical_json_bytes(record.model_dump(mode="json")) for record in records)
    return payload, tuple(records), texts


def _verify_evidence_ledger(
    *,
    payload: bytes,
    protocol: P6Protocol,
    texts: dict[str, str],
) -> tuple[P6EvidenceRecord, ...]:
    records: list[P6EvidenceRecord] = []
    previous = "0" * 64
    for sequence, line in enumerate(payload.splitlines()):
        record = P6EvidenceRecord.model_validate_json(line, strict=True)
        if (
            record.sequence != sequence
            or record.previous_hash != previous
            or record.protocol_hash != protocol.protocol_hash
            or record.evidence_bundle_id != protocol.evidence_bundle_id
        ):
            raise ValueError("P6 evidence sequence, chain, or protocol binding drift")
        material = record.model_dump(mode="json", exclude={"record_hash"})
        if _sha256_bytes(_canonical_json_bytes(material)) != record.record_hash:
            raise ValueError("P6 evidence record hash mismatch")
        _verify_selector(texts[record.source_id], record)
        records.append(record)
        previous = record.record_hash
    return tuple(records)


def _role_register(
    *,
    contract: P6CaptureContract,
    manifest: P6CaptureManifest,
) -> bytes:
    capture_by_id = {record.source_id: record for record in manifest.records}
    rows: list[dict[str, Any]] = []
    for source in contract.spec.sources:
        capture = capture_by_id[source.source_id]
        rows.append(
            {
                "schema_version": 1,
                "source_id": source.source_id,
                "requested_url": source.requested_url,
                "final_url": capture.final_url,
                "source_role": source.source_role,
                "credential_class": source.credential_class,
                "jurisdiction": source.jurisdiction,
                "body_sha256": capture.body_sha256,
                "body_size_bytes": capture.body_size_bytes,
                "capture_time_utc": capture.capture_time_utc,
                "warc_response_record_id": capture.warc_response_record_id,
                "non_operator_reference": source.non_operator_reference,
                "dicj_reference_only": source.dicj_reference_only,
                "macau_product_claim_eligible": source.macau_product_claim_eligible,
                "target_ruleclaim_vote_weight": source.target_ruleclaim_vote_weight,
                "operator_truth": False,
            }
        )
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _ruleclaim_criteria(protocol: P6Protocol) -> dict[str, Any]:
    required_classes = [
        "target_operator_legal_instrument_with_entity_identity",
        "target_regulator_instrument_explicitly_binding_the_target_operator",
        "target_signed_user_facing_rules_with_entity_identity_and_version",
    ]
    return {
        "schema_version": 1,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "generic_markers_never_auto_resolve": True,
        "farm_or_mirror_families_never_vote": True,
        "foreign_operator_rules_never_define_target_semantics": True,
        "claims": [
            {
                "subject": subject,
                "p5_status": "INSUFFICIENT_LOCAL_EVIDENCE",
                "p6_status": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
                "required_evidence_classes": required_classes,
                "satisfied_evidence_classes": [],
                "semantics_hash": None,
                "compiler_execution_permitted": False,
            }
            for subject in ("payout_basis", "special_two_sided_49_policy")
        ],
    }


def _unresolved_claim_register(
    *,
    protocol: P6Protocol,
    evidence_records: tuple[P6EvidenceRecord, ...],
) -> dict[str, Any]:
    denial_ids = [
        record.evidence_id
        for record in evidence_records
        if record.claim_scope == "macau_official_product_status"
    ]
    return {
        "schema_version": 1,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "claims": [
            {
                "subject": "macau_official_product_status",
                "status": "REGULATOR_DENIED",
                "judge_status": "MACAU_OFFICIAL_PRODUCT_CLAIM_REJECTED",
                "evidence_ids": denial_ids,
                "claim_boundary": (
                    "The captured official PJ notice rejects the named Macao Mark Six government-"
                    "approval claim. This is not an exact-domain legal determination and does not "
                    "compile target-operator payout semantics."
                ),
            },
            {
                "subject": "payout_basis",
                "status": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
                "p5_status": "INSUFFICIENT_LOCAL_EVIDENCE",
                "semantics_hash": None,
                "compiler_execution_permitted": False,
            },
            {
                "subject": "special_two_sided_49_policy",
                "status": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
                "p5_status": "INSUFFICIENT_LOCAL_EVIDENCE",
                "semantics_hash": None,
                "compiler_execution_permitted": False,
            },
        ],
    }


def _quarantine_register(protocol: P6Protocol) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "entries": [
            {
                "origin_host": "w1.kka8f.com",
                "source_role": (
                    "unverified_commercial_origin_whose_brand_conflicts_with_general_regulator_notice"
                ),
                "p5_origin_evidence_sha256": protocol.spec.p5_acceptance.p5_page_catalog_sha256,
                "fetched_in_p6": False,
                "target_semantics_vote_weight": 0,
                "exact_domain_legal_status": "NOT_DETERMINED",
                "operator_truth": False,
            }
        ],
        "farm_or_mirror_members_fetched": False,
        "mirror_multiplicity_votes_permitted": False,
        "minhash_or_template_engine_included": False,
    }


def _official_primary_pin(
    *,
    protocol: P6Protocol,
    contract: P6CaptureContract,
    manifest: P6CaptureManifest,
    texts: dict[str, str],
) -> dict[str, Any]:
    capture_by_id = {record.source_id: record for record in manifest.records}
    return {
        "schema_version": 1,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "capture_id": manifest.capture_id,
        "warc_sha256": manifest.warc_sha256,
        "sources": [
            {
                "source_id": source.source_id,
                "requested_url": source.requested_url,
                "source_role": source.source_role,
                "body_sha256": capture_by_id[source.source_id].body_sha256,
                "static_markup_text_sha256": _sha256_bytes(texts[source.source_id].encode("utf-8")),
                "required_fragments": list(source.required_fragments),
                "non_operator_reference": source.non_operator_reference,
                "dicj_reference_only": source.dicj_reference_only,
                "target_ruleclaim_vote_weight": 0,
            }
            for source in contract.spec.sources
        ],
    }


def _provenance_graph(
    *,
    protocol: P6Protocol,
    manifest: P6CaptureManifest,
    evidence_records: tuple[P6EvidenceRecord, ...],
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = [
        {
            "id": f"entity:capture:{manifest.capture_id}",
            "type": "prov_entity",
            "sha256": manifest.warc_sha256,
        }
    ]
    for capture in manifest.records:
        entities.append(
            {
                "id": f"entity:body:{capture.source_id}",
                "type": "prov_entity",
                "sha256": capture.body_sha256,
            }
        )
    for evidence in evidence_records:
        entities.append(
            {
                "id": f"entity:evidence:{evidence.evidence_id}",
                "type": "prov_entity",
                "sha256": evidence.record_hash,
            }
        )
    relations = [
        {
            "type": "prov_wasDerivedFrom",
            "generated_entity": f"entity:body:{capture.source_id}",
            "source_entity": f"entity:capture:{manifest.capture_id}",
        }
        for capture in manifest.records
    ]
    relations.extend(
        {
            "type": "prov_wasDerivedFrom",
            "generated_entity": f"entity:evidence:{evidence.evidence_id}",
            "source_entity": f"entity:body:{evidence.source_id}",
        }
        for evidence in evidence_records
    )
    return {
        "schema_version": 1,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "activities": [
            {
                "id": f"activity:capture:{manifest.capture_id}",
                "type": "prov_activity",
                "network_scope": "exact_allowlist_capture_only",
            },
            {
                "id": f"activity:formalize:{protocol.evidence_bundle_id}",
                "type": "prov_activity",
                "network_scope": "offline_only",
            },
        ],
        "entities": entities,
        "relations": relations,
    }


def _p6_source_fingerprint() -> str:
    project_root = Path(__file__).resolve().parents[2]
    paths = (
        Path(__file__).resolve(),
        project_root / "docs" / "P6_SPEC.md",
    )
    rows = [
        {
            "relative_path": path.relative_to(project_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in paths
    ]
    return _sha256_bytes(_canonical_json_bytes(rows))


def _p6_expected_artifacts(
    *,
    p5_acceptance: P6P5AcceptancePin,
    capture_dir: Path,
    capture_anchor_path: Path,
) -> tuple[dict[str, bytes], dict[str, Any], P6Protocol]:
    contract = P6CaptureContract.model_validate_json(
        (capture_dir / "capture_contract.json").read_text(encoding="utf-8"),
        strict=True,
    )
    manifest = P6CaptureManifest.model_validate_json(
        (capture_dir / "capture_manifest.json").read_text(encoding="utf-8"),
        strict=True,
    )
    capture_pin = _capture_bundle_pin(
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
    )
    protocol = build_p6_protocol(
        p5_acceptance=p5_acceptance,
        capture_bundle=capture_pin,
    )
    bodies = _read_and_verify_warc(
        warc_path=capture_dir / P6_WARC_FILENAME,
        contract=contract,
        manifest=manifest,
    )
    evidence_payload, evidence_records, texts = _evidence_ledger(
        protocol=protocol,
        contract=contract,
        manifest=manifest,
        bodies=bodies,
    )
    role_payload = _role_register(contract=contract, manifest=manifest)
    role_rows = [
        json.loads(line, object_pairs_hook=_duplicate_rejector) for line in role_payload.splitlines()
    ]
    criteria = _ruleclaim_criteria(protocol)
    claims = _unresolved_claim_register(
        protocol=protocol,
        evidence_records=evidence_records,
    )
    quarantine = _quarantine_register(protocol)
    official_pin = _official_primary_pin(
        protocol=protocol,
        contract=contract,
        manifest=manifest,
        texts=texts,
    )
    provenance = _provenance_graph(
        protocol=protocol,
        manifest=manifest,
        evidence_records=evidence_records,
    )
    judge_checks = {
        "p5_independent_acceptance_chain_verified": True,
        "capture_contract_frozen_before_network": True,
        "capture_bundle_external_anchor_verified": True,
        "exact_four_official_get_sources": len(manifest.records) == 4,
        "warc_1_1_internal_digests_and_external_sha256_verified": True,
        "all_prefrozen_fragments_reresolved": len(evidence_records)
        == sum(len(source.required_fragments) for source in contract.spec.sources),
        "official_source_roles_never_target_operator_truth": all(
            row["operator_truth"] is False for row in role_rows
        ),
        "pj_notice_is_only_direct_macau_product_claim_source": [
            row["source_id"] for row in role_rows if row["macau_product_claim_eligible"]
        ]
        == ["gov_pj_787749"],
        "dicj_reference_only_disclaimer_retained": all(
            row["dicj_reference_only"] is True
            for row in role_rows
            if str(row["source_id"]).startswith("dicj_")
        ),
        "hkjc_is_nonoperator_and_target_ruleclaim_weight_zero": all(
            row["non_operator_reference"] is True
            and row["target_ruleclaim_vote_weight"] == 0
            and row["operator_truth"] is False
            for row in role_rows
            if row["source_id"] == "hkjc_marksix_rules_hub"
        ),
        "w1_nonfetched_quarantined_and_exact_domain_legal_status_unknown": (
            quarantine["entries"][0]["fetched_in_p6"] is False
            and quarantine["entries"][0]["target_semantics_vote_weight"] == 0
            and quarantine["entries"][0]["exact_domain_legal_status"] == "NOT_DETERMINED"
        ),
        "two_target_ruleclaims_remain_uncompiled": all(
            row["p6_status"] == "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE"
            and row["semantics_hash"] is None
            and row["compiler_execution_permitted"] is False
            for row in criteria["claims"]
        ),
        "formal_network_and_economic_actions_disabled": (
            protocol.spec.network_permitted is False
            and protocol.spec.operator_rule_truth_upgrade_permitted is False
            and protocol.spec.semantics_compilation_permitted is False
            and protocol.spec.economic_claim_permitted is False
            and protocol.spec.ranking_permitted is False
            and protocol.spec.recommendation_permitted is False
            and protocol.spec.real_money_use_permitted is False
        ),
        "qft_minhash_pdf_and_asset_crawl_absent": (
            protocol.spec.qft_annex_included is False
            and quarantine["minhash_or_template_engine_included"] is False
            and contract.spec.embedded_asset_fetch_permitted is False
        ),
    }
    judge = P6JudgeGate(
        evidence_bundle_id=protocol.evidence_bundle_id,
        protocol_hash=protocol.protocol_hash,
        rule_claim_statuses={
            "payout_basis": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
            "special_two_sided_49_policy": "INSUFFICIENT_TARGET_OPERATOR_EVIDENCE",
        },
        checks=judge_checks,
    )
    checks = {
        "schema_version": 1,
        "resolution_key": P6_RESOLUTION_KEY,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "p5_protocol_hash": p5_acceptance.p5_protocol_hash,
        "p5_trusted_anchor_sha256": p5_acceptance.trusted_anchor_sha256,
        "p5_independent_report_sha256": p5_acceptance.independent_report_sha256,
        "capture_id": capture_pin.capture_id,
        "capture_contract_hash": capture_pin.contract_hash,
        "capture_manifest_sha256": capture_pin.capture_manifest_sha256,
        "capture_anchor_sha256": capture_pin.capture_anchor_sha256,
        "warc_sha256": capture_pin.warc_sha256,
        "source_count": len(manifest.records),
        "evidence_record_count": len(evidence_records),
        "evidence_ledger_sha256": _sha256_bytes(evidence_payload),
        "evidence_chain_tip": evidence_records[-1].record_hash,
        "role_register_sha256": _sha256_bytes(role_payload),
        "judge_checks": judge_checks,
        "all_judge_checks_pass": all(judge_checks.values()),
        "public_source_status": judge.public_source_status,
        "macau_official_product_claim_status": judge.macau_official_product_claim_status,
        "semantics_status": judge.semantics_status,
        "economic_claim_status": judge.economic_claim_status,
        "forbidden_claim_flags_all_false": all(
            value is False
            for value in (
                judge.operator_rule_truth_verified,
                judge.source_truth_verified_for_target_operator,
                judge.semantics_compilation_permitted,
                judge.historical_price_availability_verified,
                judge.ranking_permitted,
                judge.recommendation_permitted,
                judge.real_money_use_permitted,
                judge.whole_project_complete,
            )
        ),
    }
    if not checks["all_judge_checks_pass"] or not checks["forbidden_claim_flags_all_false"]:
        raise RuntimeError(f"P6 acceptance checks failed: {checks}")
    artifacts = {
        "p5_acceptance_pin.json": _canonical_json_bytes(p5_acceptance.model_dump(mode="json")),
        "capture_bundle_pin.json": _canonical_json_bytes(capture_pin.model_dump(mode="json")),
        "p6_protocol.json": _canonical_json_bytes(protocol.model_dump(mode="json")),
        "official_primary_pin.json": _canonical_json_bytes(official_pin),
        "public_source_role_register.jsonl": role_payload,
        "official_evidence_ledger.jsonl": evidence_payload,
        "ruleclaim_acquisition_criteria.json": _canonical_json_bytes(criteria),
        "unresolved_claim_register_p6.json": _canonical_json_bytes(claims),
        "quarantine_register.json": _canonical_json_bytes(quarantine),
        "provenance_graph.json": _canonical_json_bytes(provenance),
        "judge_gate_p6.json": _canonical_json_bytes(judge.model_dump(mode="json")),
        "checks.json": _canonical_json_bytes(checks),
    }
    if tuple(artifacts) != P6_FORMAL_ARTIFACT_NAMES:
        raise RuntimeError("P6 formal artifact order or surface drift")
    return artifacts, checks, protocol


def _p6_manifest(
    *,
    protocol: P6Protocol,
    artifacts: dict[str, bytes],
    producer_source_fingerprint: str | None = None,
) -> dict[str, Any]:
    fingerprint = producer_source_fingerprint or _p6_source_fingerprint()
    if not _is_sha256(fingerprint):
        raise ValueError("P6 producer source fingerprint is not a canonical SHA-256")
    return {
        "schema_version": 1,
        "status": (
            "verified_public_primary_source_bundle_macau_official_product_claim_rejected_"
            "semantics_unresolved_economic_claims_blocked"
        ),
        "resolution_key": P6_RESOLUTION_KEY,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "capture_id": protocol.spec.capture_bundle.capture_id,
        "capture_warc_sha256": protocol.spec.capture_bundle.warc_sha256,
        "producer_source_fingerprint": fingerprint,
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("xinao-market-lab", "pydantic", "warcio")
        },
        "artifacts": [
            {
                "relative_path": name,
                "size_bytes": len(artifacts[name]),
                "sha256": _sha256_bytes(artifacts[name]),
            }
            for name in P6_FORMAL_ARTIFACT_NAMES
        ],
        "claims": {
            "public_primary_source_bundle_verified": True,
            "macau_official_product_claim_rejected": True,
            "operator_rule_truth_verified": False,
            "payout_basis_verified": False,
            "special_two_sided_49_policy_verified": False,
            "semantics_resolved": False,
            "historical_price_availability_verified": False,
            "predictive_ranking_permitted": False,
            "recommendation_permitted": False,
            "real_money_use_permitted": False,
            "whole_project_complete": False,
        },
        "claim_boundary": (
            "This run verifies one exact official public-source capture bundle and rejects the "
            "named Macao Mark Six government-approval claim within the frozen official evidence. "
            "It does not determine the exact legal status of w1.kka8f.com, establish target-"
            "operator rule truth, resolve payout_basis or special_two_sided_49_policy, infer edge, "
            "rank candidates, recommend action, permit real-money use, or complete the project."
        ),
    }


def run_p6_public_source_role_ruleclaim(
    *,
    evidence_root: Path,
    run_name: str,
    capture_dir: Path,
    capture_anchor_path: Path,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
) -> dict[str, Any]:
    verify_p6_capture_bundle(
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    p5_acceptance = build_p6_p5_acceptance_pin(
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    evidence_root = evidence_root.resolve()
    run_dir = evidence_root / run_name
    if Path(p5_acceptance.p5_run_directory).drive.casefold() == "d:" and not _is_under(
        run_dir, CANONICAL_RUN_ROOT
    ):
        raise ValueError(f"canonical P6 formal evidence must stay under {CANONICAL_RUN_ROOT}")
    if _is_under(run_dir, capture_dir):
        raise ValueError("P6 formal evidence cannot be inside the capture bundle")
    evidence_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(exist_ok=False)
    artifacts, checks, protocol = _p6_expected_artifacts(
        p5_acceptance=p5_acceptance,
        capture_dir=capture_dir.resolve(),
        capture_anchor_path=capture_anchor_path.resolve(),
    )
    for name, payload in artifacts.items():
        _write_exclusive(run_dir / name, payload)
    manifest = _p6_manifest(protocol=protocol, artifacts=artifacts)
    _write_exclusive(run_dir / "run_manifest.json", _canonical_json_bytes(manifest))
    verification = verify_p6_run(
        run_dir=run_dir,
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    return {
        "status": manifest["status"],
        "run_dir": str(run_dir),
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "capture_id": protocol.spec.capture_bundle.capture_id,
        "warc_sha256": protocol.spec.capture_bundle.warc_sha256,
        "evidence_record_count": checks["evidence_record_count"],
        "evidence_ledger_sha256": checks["evidence_ledger_sha256"],
        "evidence_chain_tip": checks["evidence_chain_tip"],
        "public_source_status": checks["public_source_status"],
        "macau_official_product_claim_status": checks["macau_official_product_claim_status"],
        "semantics_status": checks["semantics_status"],
        "economic_claim_status": checks["economic_claim_status"],
        "self_verification": verification["status"],
    }


def _expected_p6_anchor(run_dir: Path) -> dict[str, Any]:
    protocol = P6Protocol.model_validate_json(
        (run_dir / "p6_protocol.json").read_text(encoding="utf-8"),
        strict=True,
    )
    checks = _read_json_object(run_dir / "checks.json")
    return {
        "schema_version": 1,
        "resolution_key": P6_RESOLUTION_KEY,
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "protocol_artifact_sha256": _sha256_file(run_dir / "p6_protocol.json"),
        "p5_acceptance_pin_sha256": _sha256_file(run_dir / "p5_acceptance_pin.json"),
        "capture_bundle_pin_sha256": _sha256_file(run_dir / "capture_bundle_pin.json"),
        "capture_warc_sha256": protocol.spec.capture_bundle.warc_sha256,
        "official_primary_pin_sha256": _sha256_file(run_dir / "official_primary_pin.json"),
        "source_role_register_sha256": _sha256_file(run_dir / "public_source_role_register.jsonl"),
        "evidence_ledger_sha256": _sha256_file(run_dir / "official_evidence_ledger.jsonl"),
        "evidence_chain_tip": checks["evidence_chain_tip"],
        "ruleclaim_acquisition_criteria_sha256": _sha256_file(
            run_dir / "ruleclaim_acquisition_criteria.json"
        ),
        "unresolved_claim_register_sha256": _sha256_file(run_dir / "unresolved_claim_register_p6.json"),
        "quarantine_register_sha256": _sha256_file(run_dir / "quarantine_register.json"),
        "provenance_graph_sha256": _sha256_file(run_dir / "provenance_graph.json"),
        "judge_gate_sha256": _sha256_file(run_dir / "judge_gate_p6.json"),
        "checks_sha256": _sha256_file(run_dir / "checks.json"),
        "run_manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
    }


def verify_p6_run(
    *,
    run_dir: Path,
    capture_dir: Path,
    capture_anchor_path: Path,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
    trusted_anchor: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    required = (*P6_FORMAL_ARTIFACT_NAMES, "run_manifest.json")
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P6 formal run is incomplete: {missing}")
    capture_before = {name: _sha256_file(capture_dir / name) for name in P6_CAPTURE_ARTIFACT_NAMES}
    p5_acceptance = build_p6_p5_acceptance_pin(
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    capture_verification = verify_p6_capture_bundle(
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    artifacts, checks, protocol = _p6_expected_artifacts(
        p5_acceptance=p5_acceptance,
        capture_dir=capture_dir.resolve(),
        capture_anchor_path=capture_anchor_path.resolve(),
    )
    actual_protocol = P6Protocol.model_validate_json(
        (run_dir / "p6_protocol.json").read_text(encoding="utf-8"),
        strict=True,
    )
    if actual_protocol != protocol or _hash_model(actual_protocol.spec) != actual_protocol.protocol_hash:
        raise ValueError("P6 protocol differs from the independently rebuilt protocol")
    for name, expected in artifacts.items():
        if (run_dir / name).read_bytes() != expected:
            raise ValueError(f"P6 semantic artifact mismatch: {name}")
    contract = P6CaptureContract.model_validate_json(
        (capture_dir / "capture_contract.json").read_text(encoding="utf-8"),
        strict=True,
    )
    manifest = P6CaptureManifest.model_validate_json(
        (capture_dir / "capture_manifest.json").read_text(encoding="utf-8"),
        strict=True,
    )
    bodies = _read_and_verify_warc(
        warc_path=capture_dir / P6_WARC_FILENAME,
        contract=contract,
        manifest=manifest,
    )
    texts = {
        record.source_id: _static_markup_text(bodies[record.source_id], record.charset)
        for record in manifest.records
    }
    evidence_records = _verify_evidence_ledger(
        payload=(run_dir / "official_evidence_ledger.jsonl").read_bytes(),
        protocol=protocol,
        texts=texts,
    )
    if (
        len(evidence_records) != checks["evidence_record_count"]
        or _sha256_file(run_dir / "official_evidence_ledger.jsonl") != checks["evidence_ledger_sha256"]
        or evidence_records[-1].record_hash != checks["evidence_chain_tip"]
    ):
        raise ValueError("P6 evidence ledger summary drifted")
    actual_manifest = _read_json_object(run_dir / "run_manifest.json")
    expected_manifest = _p6_manifest(
        protocol=protocol,
        artifacts=artifacts,
        producer_source_fingerprint=actual_manifest.get("producer_source_fingerprint"),
    )
    if (run_dir / "run_manifest.json").read_bytes() != _canonical_json_bytes(expected_manifest):
        raise ValueError("P6 run manifest or claim boundary mismatch")
    claims = actual_manifest.get("claims", {})
    required_false = (
        "operator_rule_truth_verified",
        "payout_basis_verified",
        "special_two_sided_49_policy_verified",
        "semantics_resolved",
        "historical_price_availability_verified",
        "predictive_ranking_permitted",
        "recommendation_permitted",
        "real_money_use_permitted",
        "whole_project_complete",
    )
    if any(claims.get(name) is not False for name in required_false):
        raise ValueError("P6 manifest enables a forbidden target semantic or economic claim")
    if (
        claims.get("public_primary_source_bundle_verified") is not True
        or claims.get("macau_official_product_claim_rejected") is not True
    ):
        raise ValueError("P6 manifest omits its narrow verified public-source claims")
    anchor_verified = False
    if trusted_anchor is not None:
        if _read_json_object(trusted_anchor.resolve()) != _expected_p6_anchor(run_dir):
            raise ValueError("P6 trusted out-of-run acceptance anchor mismatch")
        anchor_verified = True
    capture_after = {name: _sha256_file(capture_dir / name) for name in P6_CAPTURE_ARTIFACT_NAMES}
    if capture_before != capture_after:
        raise ValueError("P6 formal verification modified the immutable capture bundle")
    return {
        "status": "verified",
        "run_dir": str(run_dir),
        "evidence_bundle_id": protocol.evidence_bundle_id,
        "protocol_hash": protocol.protocol_hash,
        "capture_id": capture_verification["capture_id"],
        "warc_sha256": capture_verification["warc_sha256"],
        "evidence_record_count": len(evidence_records),
        "evidence_ledger_sha256": checks["evidence_ledger_sha256"],
        "evidence_chain_tip": checks["evidence_chain_tip"],
        "public_source_status": checks["public_source_status"],
        "macau_official_product_claim_status": checks["macau_official_product_claim_status"],
        "semantics_status": checks["semantics_status"],
        "economic_claim_status": checks["economic_claim_status"],
        "trusted_anchor_verified": anchor_verified,
    }


def build_p6_trusted_anchor(
    *,
    run_dir: Path,
    capture_dir: Path,
    capture_anchor_path: Path,
    p5_run_dir: Path,
    p5_trusted_anchor: Path,
    p5_admin_acceptance: Path,
    p5_independent_report: Path,
    anchor_path: Path,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    anchor_path = anchor_path.resolve()
    if _is_under(anchor_path, run_dir):
        raise ValueError("P6 trusted anchor must be outside the formal run directory")
    if anchor_path.exists():
        raise FileExistsError(f"P6 trusted anchor already exists and is immutable: {anchor_path}")
    verify_p6_run(
        run_dir=run_dir,
        capture_dir=capture_dir,
        capture_anchor_path=capture_anchor_path,
        p5_run_dir=p5_run_dir,
        p5_trusted_anchor=p5_trusted_anchor,
        p5_admin_acceptance=p5_admin_acceptance,
        p5_independent_report=p5_independent_report,
    )
    anchor = _expected_p6_anchor(run_dir)
    anchor_sha256 = _write_exclusive(anchor_path, _canonical_json_bytes(anchor))
    return {
        "status": "trusted_anchor_created",
        "anchor_path": str(anchor_path),
        "anchor_sha256": anchor_sha256,
        "evidence_bundle_id": anchor["evidence_bundle_id"],
        "protocol_hash": anchor["protocol_hash"],
        "warc_sha256": anchor["capture_warc_sha256"],
        "evidence_ledger_sha256": anchor["evidence_ledger_sha256"],
    }
