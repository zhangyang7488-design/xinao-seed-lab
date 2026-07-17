"""Deterministic atomic semantics for the 22 number-combination catalog rows.

The module deliberately separates an accepted *atomic ticket* from the UI
generators that may create many tickets (复式、拖头、对碰、多组).  Every row
below has a complete unordered-number selection domain and a pure settlement
candidate.  Generator-specific limits and drag/pair construction remain an
upstream concern and cannot silently alter the atomic settlement predicate.

The seventh draw position is the special number; the first six positions are
the regular numbers.  A normal hit pays the displayed quote component, a miss
pays zero, and no additional principal is added.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
from math import comb
from typing import Literal

TARGET_FAMILY_IDS = frozenset(
    {
        "linked-number",
        "multi-select-no-hit",
        "multi-select-one-hit",
        "special-regular-hit",
    }
)

EXPECTED_BASELINE_IDS = (
    "BO0212",
    "BO0213",
    "BO0214",
    "BO0215",
    "BO0216",
    "BO0261",
    "BO0262",
    "BO0263",
    "BO0264",
    "BO0265",
    "BO0266",
    "BO0423",
    "BO0424",
    "BO0425",
    "BO0426",
    "BO0427",
    "BO0428",
    "BO0429",
    "BO0430",
    "BO0431",
    "BO0432",
    "BO0433",
)

TargetSet = Literal["REGULAR_SIX", "FULL_SEVEN"]
SemanticKind = Literal[
    "ALL_SELECTED_REGULAR",
    "TWO_REGULAR_OR_REGULAR_SPECIAL",
    "REGULAR_SPECIAL",
    "THREE_OR_TWO_REGULAR",
    "NO_SELECTED_IN_SEVEN",
    "EXACTLY_ONE_SELECTED_IN_SEVEN",
    "ANY_SELECTED_IN_SEVEN",
]


@dataclass(frozen=True, slots=True)
class SelectionDomainDescriptor:
    """Compact, independently hashable representation of all atomic tickets."""

    kind: str
    universe_min: int
    universe_max: int
    arity: int
    distinct: bool
    order_sensitive: bool
    atomic_selection_count: int
    canonical_encoding: str


@dataclass(frozen=True, slots=True)
class SettlementTierDefinition:
    tier_id: str
    predicate: str
    payout_component_index: int


@dataclass(frozen=True, slots=True)
class CombinationSemanticRecord:
    """One catalog row bound to an atomic selection and settlement candidate."""

    baseline_id: str
    option_id: str
    play_id: str
    play_group: str
    family_id: str
    play_name: str
    pid: int
    tid: int
    source_row_hash: str
    quote_components: tuple[str, ...]
    selection_domain: SelectionDomainDescriptor
    target_set: TargetSet
    semantic_kind: SemanticKind
    probability_formula_ref: str
    paying_tiers: tuple[SettlementTierDefinition, ...]
    tier_order_basis: str
    declared_input_modes: tuple[str, ...]
    upstream_generator_modes: tuple[str, ...]
    atomic_expansion_rule: str
    semantic_basis: tuple[str, ...]
    principal_refund_on_normal_settlement: bool

    def canonical_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CombinationSettlementResult:
    baseline_id: str
    outcome: Literal["HIT", "MISS"]
    tier_id: str
    payout_component_index: int | None
    unit_payout: str
    principal_refund_added: bool = False


@dataclass(frozen=True, slots=True)
class _RuleSpec:
    baseline_id: str
    play_group: str
    family_id: str
    play_id: str
    play_name: str
    pid: int
    tid: int
    arity: int
    target_set: TargetSet
    semantic_kind: SemanticKind
    tiers: tuple[tuple[str, str, int], ...]


def _build_specs() -> dict[str, _RuleSpec]:
    specs = (
        _RuleSpec(
            "BO0212",
            "连码",
            "linked-number",
            "play:6:34:none",
            "二全中",
            6,
            34,
            2,
            "REGULAR_SIX",
            "ALL_SELECTED_REGULAR",
            (("ALL_TWO_REGULAR", "regular_hits == 2", 0),),
        ),
        _RuleSpec(
            "BO0213",
            "连码",
            "linked-number",
            "play:6:35:none",
            "二中特",
            6,
            35,
            2,
            "REGULAR_SIX",
            "TWO_REGULAR_OR_REGULAR_SPECIAL",
            (
                ("TWO_REGULAR", "regular_hits == 2", 0),
                (
                    "REGULAR_AND_SPECIAL",
                    "regular_hits == 1 and special_hit",
                    1,
                ),
            ),
        ),
        _RuleSpec(
            "BO0214",
            "连码",
            "linked-number",
            "play:6:36:none",
            "特串",
            6,
            36,
            2,
            "FULL_SEVEN",
            "REGULAR_SPECIAL",
            (("REGULAR_AND_SPECIAL", "regular_hits == 1 and special_hit", 0),),
        ),
        _RuleSpec(
            "BO0215",
            "连码",
            "linked-number",
            "play:6:37:none",
            "三全中",
            6,
            37,
            3,
            "REGULAR_SIX",
            "ALL_SELECTED_REGULAR",
            (("ALL_THREE_REGULAR", "regular_hits == 3", 0),),
        ),
        _RuleSpec(
            "BO0216",
            "连码",
            "linked-number",
            "play:6:38:none",
            "三中二",
            6,
            38,
            3,
            "REGULAR_SIX",
            "THREE_OR_TWO_REGULAR",
            (
                ("THREE_REGULAR", "regular_hits == 3", 0),
                ("TWO_REGULAR", "regular_hits == 2", 1),
            ),
        ),
    )
    result = {spec.baseline_id: spec for spec in specs}

    chinese_counts = ("五", "六", "七", "八", "九", "十")
    for offset, (count_name, arity) in enumerate(zip(chinese_counts, range(5, 11), strict=True)):
        baseline_number = 261 + offset
        spec = _RuleSpec(
            f"BO{baseline_number:04d}",
            "多选不中",
            "multi-select-no-hit",
            f"play:9:{41 + offset}:none",
            f"{count_name}不中",
            9,
            41 + offset,
            arity,
            "FULL_SEVEN",
            "NO_SELECTED_IN_SEVEN",
            (("NO_HIT", "seven_hits == 0", 0),),
        )
        result[spec.baseline_id] = spec

    for offset, (count_name, arity) in enumerate(zip(chinese_counts, range(5, 11), strict=True)):
        baseline_number = 423 + offset
        spec = _RuleSpec(
            f"BO{baseline_number:04d}",
            "多选中一",
            "multi-select-one-hit",
            f"play:12:{61 + offset}:none",
            f"{count_name}中一",
            12,
            61 + offset,
            arity,
            "FULL_SEVEN",
            "EXACTLY_ONE_SELECTED_IN_SEVEN",
            (("EXACTLY_ONE", "seven_hits == 1", 0),),
        )
        result[spec.baseline_id] = spec

    grain_names = ("一", "二", "三", "四", "五")
    for offset, (count_name, arity) in enumerate(zip(grain_names, range(1, 6), strict=True)):
        baseline_number = 429 + offset
        spec = _RuleSpec(
            f"BO{baseline_number:04d}",
            "特平中",
            "special-regular-hit",
            f"play:13:{67 + offset}:none",
            f"{count_name}粒任中",
            13,
            67 + offset,
            arity,
            "FULL_SEVEN",
            "ANY_SELECTED_IN_SEVEN",
            (("ANY_HIT", "seven_hits >= 1", 0),),
        )
        result[spec.baseline_id] = spec

    if tuple(sorted(result)) != EXPECTED_BASELINE_IDS:
        raise RuntimeError("combination rule specification identity is inconsistent")
    return result


_RULE_SPECS = _build_specs()
_PROBABILITY_FORMULA_BY_KIND: dict[SemanticKind, str] = {
    "ALL_SELECTED_REGULAR": "hypergeometric-selected-in-six-regular.v1",
    "TWO_REGULAR_OR_REGULAR_SPECIAL": "ordered-six-plus-special-dual-tier.v1",
    "REGULAR_SPECIAL": "ordered-six-plus-special-tier.v1",
    "THREE_OR_TWO_REGULAR": "hypergeometric-three-or-two-in-six-regular.v1",
    "NO_SELECTED_IN_SEVEN": "hypergeometric-zero-in-seven.v1",
    "EXACTLY_ONE_SELECTED_IN_SEVEN": "hypergeometric-one-in-seven.v1",
    "ANY_SELECTED_IN_SEVEN": "complement-hypergeometric-zero-in-seven.v1",
}
_ROW_IDENTITY_FIELDS = (
    "baseline_id",
    "option_id",
    "play_id",
    "play_group",
    "family_id",
    "play_name",
    "pid",
    "tid",
    "panel",
    "bet_shape",
    "option_name",
    "option_range",
    "baseline_odds_components",
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_row_hash(entry: Mapping[str, object]) -> str:
    payload = {field: entry.get(field) for field in _ROW_IDENTITY_FIELDS}
    return sha256(_canonical_json(payload)).hexdigest()


def _quote_components(entry: Mapping[str, object], *, expected_count: int) -> tuple[str, ...]:
    raw = entry.get("baseline_odds_components")
    if not isinstance(raw, (list, tuple)) or len(raw) != expected_count:
        raise ValueError("baseline quote tier count does not match settlement tiers")
    components: list[str] = []
    for component in raw:
        if not isinstance(component, str) or not component.strip():
            raise TypeError("baseline quote components must be non-empty decimal strings")
        text = component.strip()
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError("invalid baseline quote component") from exc
        if not number.is_finite() or number <= 0:
            raise ValueError("baseline quote components must be finite and positive")
        components.append(text)
    return tuple(components)


def _input_modes(entry: Mapping[str, object]) -> tuple[str, ...]:
    raw = entry.get("bet_shape")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("catalog row must declare its input modes")
    modes = tuple(part.strip() for part in raw.split("/") if part.strip())
    if not modes or len(set(modes)) != len(modes):
        raise ValueError("catalog input modes must be non-empty and unique")
    return modes


def _validate_identity(entry: Mapping[str, object], spec: _RuleSpec) -> None:
    expected = {
        "baseline_id": spec.baseline_id,
        "option_id": f"baseline-option:{spec.baseline_id}",
        "play_id": spec.play_id,
        "play_group": spec.play_group,
        "family_id": spec.family_id,
        "play_name": spec.play_name,
        "pid": spec.pid,
        "tid": spec.tid,
        "panel": None,
        "option_name": "号码",
        "option_range": "01-49",
    }
    mismatches = [key for key, value in expected.items() if entry.get(key) != value]
    if mismatches:
        raise ValueError(f"catalog row identity mismatch: {', '.join(sorted(mismatches))}")


def compile_combination_semantic(entry: Mapping[str, object]) -> CombinationSemanticRecord:
    """Compile one known catalog row; unknown or drifted identities fail closed."""

    if not isinstance(entry, Mapping):
        raise TypeError("catalog entry must be a mapping")
    baseline_id = entry.get("baseline_id")
    if not isinstance(baseline_id, str) or baseline_id not in _RULE_SPECS:
        raise ValueError("unsupported combination baseline_id")
    spec = _RULE_SPECS[baseline_id]
    _validate_identity(entry, spec)
    quote_components = _quote_components(entry, expected_count=len(spec.tiers))
    modes = _input_modes(entry)
    upstream_modes = tuple(mode for mode in modes if mode not in {"复式", "多组"})
    tiers = tuple(SettlementTierDefinition(*tier) for tier in spec.tiers)
    if spec.baseline_id == "BO0213":
        tier_order_basis = "EXTERNAL_CONSENSUS_CANDIDATE:中二/中特"
    elif spec.baseline_id == "BO0216":
        tier_order_basis = "EXTERNAL_CONSENSUS_CANDIDATE:中三/中二"
    else:
        tier_order_basis = "SINGLE_COMPONENT"
    selection_domain = SelectionDomainDescriptor(
        kind="UNORDERED_NUMBER_COMBINATION",
        universe_min=1,
        universe_max=49,
        arity=spec.arity,
        distinct=True,
        order_sensitive=False,
        atomic_selection_count=comb(49, spec.arity),
        canonical_encoding="ascending-zero-padded-2-digit-csv",
    )
    return CombinationSemanticRecord(
        baseline_id=spec.baseline_id,
        option_id=f"baseline-option:{spec.baseline_id}",
        play_id=spec.play_id,
        play_group=spec.play_group,
        family_id=spec.family_id,
        play_name=spec.play_name,
        pid=spec.pid,
        tid=spec.tid,
        source_row_hash=_source_row_hash(entry),
        quote_components=quote_components,
        selection_domain=selection_domain,
        target_set=spec.target_set,
        semantic_kind=spec.semantic_kind,
        probability_formula_ref=_PROBABILITY_FORMULA_BY_KIND[spec.semantic_kind],
        paying_tiers=tiers,
        tier_order_basis=tier_order_basis,
        declared_input_modes=modes,
        upstream_generator_modes=upstream_modes,
        atomic_expansion_rule=f"each accepted pool expands to C(m,{spec.arity}) atomic tickets",
        semantic_basis=(
            "PLAY_CATALOG_ROW_IDENTITY",
            "MULTI_SOURCE_RULE_CONSENSUS_CANDIDATE",
            "PARAMETERIZED_ATOMIC_SETTLEMENT",
        ),
        principal_refund_on_normal_settlement=False,
    )


def compile_combination_semantics(
    entries: Iterable[Mapping[str, object]],
    *,
    require_complete: bool = True,
) -> tuple[CombinationSemanticRecord, ...]:
    """Compile a deterministic row set and optionally require exact 22-row coverage."""

    records: list[CombinationSemanticRecord] = []
    seen: set[str] = set()
    for entry in entries:
        record = compile_combination_semantic(entry)
        if record.baseline_id in seen:
            raise ValueError(f"duplicate baseline_id: {record.baseline_id}")
        seen.add(record.baseline_id)
        records.append(record)
    records.sort(key=lambda record: record.baseline_id)
    actual_ids = tuple(record.baseline_id for record in records)
    if require_complete and actual_ids != EXPECTED_BASELINE_IDS:
        missing = sorted(set(EXPECTED_BASELINE_IDS) - seen)
        extra = sorted(seen - set(EXPECTED_BASELINE_IDS))
        raise ValueError(
            f"combination catalog coverage is incomplete: missing={missing}, extra={extra}"
        )
    return tuple(records)


def compile_combination_catalog(
    catalog: Mapping[str, object],
) -> tuple[CombinationSemanticRecord, ...]:
    """Select and compile the four target families from a PlayCatalogVersion payload."""

    if catalog.get("schema_version") != "xinao.play_catalog.v1":
        raise ValueError("unsupported play catalog schema_version")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise TypeError("play catalog entries must be a list")
    if catalog.get("entry_count") != len(entries):
        raise ValueError("play catalog entry_count does not match entries")
    selected = [entry for entry in entries if entry.get("family_id") in TARGET_FAMILY_IDS]
    return compile_combination_semantics(selected)


def combination_records_hash(records: Iterable[CombinationSemanticRecord]) -> str:
    """Hash a complete or partial record set independent of input ordering."""

    ordered = sorted(records, key=lambda record: record.baseline_id)
    ids = [record.baseline_id for record in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate baseline_id in semantic record hash input")
    return sha256(_canonical_json([record.canonical_dict() for record in ordered])).hexdigest()


def selection_domain_hash(record: CombinationSemanticRecord) -> str:
    """Hash only the catalog row identity and independently derived atomic domain."""

    payload = {
        "baseline_id": record.baseline_id,
        "source_row_hash": record.source_row_hash,
        "selection_domain": asdict(record.selection_domain),
    }
    return sha256(_canonical_json(payload)).hexdigest()


def _normalize_numbers(
    values: Sequence[int | str],
    *,
    expected_count: int,
    label: str,
) -> tuple[int, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be a sequence")
    if len(values) != expected_count:
        raise ValueError(f"{label} must contain exactly {expected_count} numbers")
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool):
            raise TypeError(f"{label} cannot contain bool")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.isdigit():
            number = int(value)
        else:
            raise TypeError(f"{label} numbers must be integers or digit strings")
        if not 1 <= number <= 49:
            raise ValueError(f"{label} numbers must be between 1 and 49")
        normalized.append(number)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} numbers must be distinct")
    return tuple(normalized)


def expand_number_pool(
    values: Sequence[int | str],
    *,
    arity: int,
) -> tuple[tuple[int, ...], ...]:
    """Expand one 复式 number pool into canonical atomic unordered tickets."""

    if isinstance(arity, bool) or not isinstance(arity, int):
        raise TypeError("arity must be an integer")
    if not 1 <= arity <= 10:
        raise ValueError("arity must be between 1 and 10")
    pool = _normalize_numbers(values, expected_count=len(values), label="number pool")
    if len(pool) < arity:
        raise ValueError("number pool is smaller than atomic arity")
    return tuple(combinations(sorted(pool), arity))


def settle_combination(
    *,
    entry: Mapping[str, object] | CombinationSemanticRecord,
    draw: Sequence[int | str],
    selection: Sequence[int | str],
) -> CombinationSettlementResult:
    """Settle one atomic ticket against six regular numbers plus one special."""

    record = (
        entry
        if isinstance(entry, CombinationSemanticRecord)
        else compile_combination_semantic(entry)
    )
    draw_numbers = _normalize_numbers(draw, expected_count=7, label="draw")
    selected = set(
        _normalize_numbers(
            selection,
            expected_count=record.selection_domain.arity,
            label="selection",
        )
    )
    regular = set(draw_numbers[:6])
    special = draw_numbers[6]
    regular_hits = len(selected & regular)
    special_hit = special in selected
    seven_hits = regular_hits + int(special_hit)

    tier_index: int | None = None
    kind = record.semantic_kind
    if kind == "ALL_SELECTED_REGULAR" and regular_hits == record.selection_domain.arity:
        tier_index = 0
    elif kind == "TWO_REGULAR_OR_REGULAR_SPECIAL":
        if regular_hits == 2:
            tier_index = 0
        elif regular_hits == 1 and special_hit:
            tier_index = 1
    elif kind == "REGULAR_SPECIAL" and regular_hits == 1 and special_hit:
        tier_index = 0
    elif kind == "THREE_OR_TWO_REGULAR":
        if regular_hits == 3:
            tier_index = 0
        elif regular_hits == 2:
            tier_index = 1
    elif (
        (kind == "NO_SELECTED_IN_SEVEN" and seven_hits == 0)
        or (kind == "EXACTLY_ONE_SELECTED_IN_SEVEN" and seven_hits == 1)
        or (kind == "ANY_SELECTED_IN_SEVEN" and seven_hits >= 1)
    ):
        tier_index = 0

    if tier_index is None:
        return CombinationSettlementResult(
            baseline_id=record.baseline_id,
            outcome="MISS",
            tier_id="MISS",
            payout_component_index=None,
            unit_payout="0",
        )
    tier = record.paying_tiers[tier_index]
    if tier.payout_component_index != tier_index:
        raise RuntimeError("settlement tier and quote component order diverged")
    return CombinationSettlementResult(
        baseline_id=record.baseline_id,
        outcome="HIT",
        tier_id=tier.tier_id,
        payout_component_index=tier_index,
        unit_payout=record.quote_components[tier_index],
    )


def _hypergeometric_probability(*, marked: int, sample: int, hits: int) -> Fraction:
    if hits < 0 or hits > marked or sample - hits < 0 or sample - hits > 49 - marked:
        return Fraction(0)
    return Fraction(comb(marked, hits) * comb(49 - marked, sample - hits), comb(49, sample))


def tier_probabilities(
    entry: Mapping[str, object] | CombinationSemanticRecord,
) -> dict[str, Fraction]:
    """Return exact mutually exclusive payout-tier probabilities plus MISS."""

    record = (
        entry
        if isinstance(entry, CombinationSemanticRecord)
        else compile_combination_semantic(entry)
    )
    arity = record.selection_domain.arity
    kind = record.semantic_kind
    probabilities: dict[str, Fraction]
    if kind == "ALL_SELECTED_REGULAR":
        probabilities = {
            record.paying_tiers[0].tier_id: _hypergeometric_probability(
                marked=arity,
                sample=6,
                hits=arity,
            )
        }
    elif kind in {"TWO_REGULAR_OR_REGULAR_SPECIAL", "REGULAR_SPECIAL"}:
        regular_and_special = Fraction(2 * comb(47, 5), comb(49, 6) * 43)
        if kind == "TWO_REGULAR_OR_REGULAR_SPECIAL":
            probabilities = {
                record.paying_tiers[0].tier_id: _hypergeometric_probability(
                    marked=2,
                    sample=6,
                    hits=2,
                ),
                record.paying_tiers[1].tier_id: regular_and_special,
            }
        else:
            probabilities = {record.paying_tiers[0].tier_id: regular_and_special}
    elif kind == "THREE_OR_TWO_REGULAR":
        probabilities = {
            record.paying_tiers[0].tier_id: _hypergeometric_probability(
                marked=3,
                sample=6,
                hits=3,
            ),
            record.paying_tiers[1].tier_id: _hypergeometric_probability(
                marked=3,
                sample=6,
                hits=2,
            ),
        }
    elif kind == "NO_SELECTED_IN_SEVEN":
        probabilities = {
            record.paying_tiers[0].tier_id: _hypergeometric_probability(
                marked=arity,
                sample=7,
                hits=0,
            )
        }
    elif kind == "EXACTLY_ONE_SELECTED_IN_SEVEN":
        probabilities = {
            record.paying_tiers[0].tier_id: _hypergeometric_probability(
                marked=arity,
                sample=7,
                hits=1,
            )
        }
    elif kind == "ANY_SELECTED_IN_SEVEN":
        zero = _hypergeometric_probability(marked=arity, sample=7, hits=0)
        probabilities = {record.paying_tiers[0].tier_id: 1 - zero}
    else:  # pragma: no cover - the closed Literal set is exhaustively handled above
        raise ValueError(f"unsupported combination semantic kind: {kind}")
    probabilities["MISS"] = 1 - sum(probabilities.values(), Fraction(0))
    if probabilities["MISS"] < 0 or sum(probabilities.values(), Fraction(0)) != 1:
        raise RuntimeError("combination probability tiers are not a normalized partition")
    return probabilities
