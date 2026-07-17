"""Stdlib-only constrained RFC 8785 stream compiler for F1 event cells.

This file is executed by absolute path with ``python -I -S``.  It deliberately
does not import the xinao package, Pydantic, or a general JSON canonicalizer.
The accepted cell domain is narrower: sixteen fixed 7-bit ASCII keys and
dynamic values that are either safe 7-bit ASCII strings or null.  Within that
domain, the fixed byte order is exactly RFC 8785's UTF-16 key order.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

PROJECTION_SCHEMA = "xinao.f1_pure_ascii_stream_projection.v1"
RESULT_SCHEMA = "xinao.f1_pure_ascii_stream_result.v1"
HEX_DIGITS = frozenset("0123456789abcdef")
BASELINE_PAYLOAD_KEYS = {
    "atomic_ticket_binding_hash",
    "atomic_ticket_binding_id",
    "baseline_id",
    "registry_selection_domain_hash",
    "selection_domain_hash",
    "selection_domain_spec_id",
    "semantic_record_hash",
    "settlement_function_ref",
}
DRAW_KEYS = {
    "draw_date",
    "draw_fingerprint",
    "draw_id",
    "draw_replay_input_hash",
}
CELL_KEYS = (
    "atomic_ticket_binding_hash",
    "atomic_ticket_binding_id",
    "baseline_id",
    "draw_date",
    "draw_fingerprint",
    "draw_id",
    "draw_replay_input_hash",
    "physical_role",
    "registry_selection_domain_hash",
    "schema_version",
    "selection_domain_hash",
    "selection_domain_spec_id",
    "semantic_record_hash",
    "settlement_function_ref",
    "surface_kind",
    "zodiac_basis_ref",
)


class OrderedMerkleFrontier:
    def __init__(self) -> None:
        self._peaks: list[bytes | None] = []
        self.count = 0

    def add(self, payload: bytes) -> None:
        node = hashlib.sha256(b"\x00" + payload).digest()
        level = 0
        while level < len(self._peaks) and self._peaks[level] is not None:
            left = self._peaks[level]
            if left is None:  # pragma: no cover - narrowed by the loop condition
                raise AssertionError("merkle frontier lost its left node")
            node = hashlib.sha256(b"\x01" + left + node).digest()
            self._peaks[level] = None
            level += 1
        if level == len(self._peaks):
            self._peaks.append(node)
        else:
            self._peaks[level] = node
        self.count += 1

    def root(self) -> str:
        payload = bytearray(b"\x02")
        payload.extend(self.count.to_bytes(8, "big"))
        for level, peak in enumerate(self._peaks):
            if peak is not None:
                payload.extend(level.to_bytes(2, "big"))
                payload.extend(peak)
        return hashlib.sha256(payload).hexdigest()


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} keys are not exact")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _safe_ascii(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} is outside 7-bit ASCII") from exc
    if b'"' in raw or b"\\" in raw or any(item < 0x20 for item in raw):
        raise ValueError(f"{label} requires JSON escaping")
    return value


def _sha256_text(value: object, label: str) -> str:
    text = _safe_ascii(value, label)
    if len(text) != 64 or any(item not in HEX_DIGITS for item in text):
        raise ValueError(f"{label} is not lowercase SHA-256")
    return text


def _ascii_json_string(value: object, label: str) -> bytes:
    return b'"' + _safe_ascii(value, label).encode("ascii") + b'"'


def _nullable_ascii_json_string(value: object, label: str) -> bytes:
    return b"null" if value is None else _ascii_json_string(value, label)


def _prepare_draw(draw: dict[str, object], index: int) -> dict[str, bytes | str]:
    label = f"draws[{index}]"
    _exact_object(draw, DRAW_KEYS, label)
    draw_id = _safe_ascii(draw["draw_id"], f"{label}.draw_id")
    if len(draw_id) != 7 or not draw_id.isdigit():
        raise ValueError(f"{label}.draw_id is invalid")
    draw_date = _safe_ascii(draw["draw_date"], f"{label}.draw_date")
    if (
        len(draw_date) != 10
        or draw_date[4] != "-"
        or draw_date[7] != "-"
        or not (draw_date[:4] + draw_date[5:7] + draw_date[8:]).isdigit()
    ):
        raise ValueError(f"{label}.draw_date is invalid")
    _sha256_text(draw["draw_fingerprint"], f"{label}.draw_fingerprint")
    _sha256_text(draw["draw_replay_input_hash"], f"{label}.draw_replay_input_hash")
    return {
        "draw_id_text": draw_id,
        "draw_date_text": draw_date,
        "draw_date": _ascii_json_string(draw_date, f"{label}.draw_date"),
        "draw_fingerprint": _ascii_json_string(
            draw["draw_fingerprint"], f"{label}.draw_fingerprint"
        ),
        "draw_id": _ascii_json_string(draw_id, f"{label}.draw_id"),
        "draw_replay_input_hash": _ascii_json_string(
            draw["draw_replay_input_hash"], f"{label}.draw_replay_input_hash"
        ),
    }


def _prepare_baseline(row: dict[str, object], index: int) -> dict[str, bytes | str]:
    label = f"baselines[{index}]"
    _exact_object(row, {"family_id", "payload"}, label)
    family_id = _safe_ascii(row["family_id"], f"{label}.family_id")
    payload = _exact_object(row["payload"], BASELINE_PAYLOAD_KEYS, f"{label}.payload")
    baseline_id = _safe_ascii(payload["baseline_id"], f"{label}.baseline_id")
    if len(baseline_id) != 6 or not (baseline_id.startswith("BO") and baseline_id[2:].isdigit()):
        raise ValueError(f"{label}.baseline_id is invalid")
    for field in (
        "registry_selection_domain_hash",
        "selection_domain_hash",
        "semantic_record_hash",
    ):
        _sha256_text(payload[field], f"{label}.{field}")
    atomic_id = payload["atomic_ticket_binding_id"]
    atomic_hash = payload["atomic_ticket_binding_hash"]
    if (atomic_id is None) != (atomic_hash is None):
        raise ValueError(f"{label} atomic binding identity is incomplete")
    if atomic_id is not None:
        _safe_ascii(atomic_id, f"{label}.atomic_ticket_binding_id")
        _sha256_text(atomic_hash, f"{label}.atomic_ticket_binding_hash")
    _safe_ascii(payload["selection_domain_spec_id"], f"{label}.selection_domain_spec_id")
    _safe_ascii(payload["settlement_function_ref"], f"{label}.settlement_function_ref")
    return {
        "family_id": family_id,
        "baseline_id_text": baseline_id,
        "atomic_ticket_binding_hash": _nullable_ascii_json_string(
            atomic_hash, f"{label}.atomic_ticket_binding_hash"
        ),
        "atomic_ticket_binding_id": _nullable_ascii_json_string(
            atomic_id, f"{label}.atomic_ticket_binding_id"
        ),
        "baseline_id": _ascii_json_string(baseline_id, f"{label}.baseline_id"),
        "registry_selection_domain_hash": _ascii_json_string(
            payload["registry_selection_domain_hash"],
            f"{label}.registry_selection_domain_hash",
        ),
        "selection_domain_hash": _ascii_json_string(
            payload["selection_domain_hash"], f"{label}.selection_domain_hash"
        ),
        "selection_domain_spec_id": _ascii_json_string(
            payload["selection_domain_spec_id"], f"{label}.selection_domain_spec_id"
        ),
        "semantic_record_hash": _ascii_json_string(
            payload["semantic_record_hash"], f"{label}.semantic_record_hash"
        ),
        "settlement_function_ref": _ascii_json_string(
            payload["settlement_function_ref"], f"{label}.settlement_function_ref"
        ),
    }


def _canonical_cell(draw: dict[str, bytes | str], baseline: dict[str, bytes | str]) -> bytes:
    """Encode the constrained cell domain; this is not a general JCS encoder."""

    return b"".join(
        (
            b'{"atomic_ticket_binding_hash":',
            baseline["atomic_ticket_binding_hash"],
            b',"atomic_ticket_binding_id":',
            baseline["atomic_ticket_binding_id"],
            b',"baseline_id":',
            baseline["baseline_id"],
            b',"draw_date":',
            draw["draw_date"],
            b',"draw_fingerprint":',
            draw["draw_fingerprint"],
            b',"draw_id":',
            draw["draw_id"],
            b',"draw_replay_input_hash":',
            draw["draw_replay_input_hash"],
            b',"physical_role":"ACTIVE_SETTLEMENT"',
            b',"registry_selection_domain_hash":',
            baseline["registry_selection_domain_hash"],
            b',"schema_version":"xinao.functional_event_cell.v1"',
            b',"selection_domain_hash":',
            baseline["selection_domain_hash"],
            b',"selection_domain_spec_id":',
            baseline["selection_domain_spec_id"],
            b',"semantic_record_hash":',
            baseline["semantic_record_hash"],
            b',"settlement_function_ref":',
            baseline["settlement_function_ref"],
            b',"surface_kind":"FUNCTIONAL_EVENT_SURFACE"',
            b',"zodiac_basis_ref":"SOURCE_API_ZODIAC_FIELDS_UNMODIFIED.v1"}',
        )
    )


def _compile(projection_bytes: bytes) -> dict[str, object]:
    try:
        projection = json.loads(projection_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("projection is not UTF-8 JSON") from exc
    projection = _exact_object(
        projection,
        {
            "schema_version",
            "expected_baseline_count",
            "expected_draw_count",
            "expected_cell_count",
            "baselines",
            "draws",
        },
        "projection",
    )
    if projection["schema_version"] != PROJECTION_SCHEMA:
        raise ValueError("projection schema is invalid")
    expected_baselines = _positive_int(
        projection["expected_baseline_count"], "expected_baseline_count"
    )
    expected_draws = _positive_int(projection["expected_draw_count"], "expected_draw_count")
    expected_cells = _positive_int(projection["expected_cell_count"], "expected_cell_count")
    if expected_cells != expected_baselines * expected_draws:
        raise ValueError("expected cell count is not baseline x draw")
    raw_baselines = projection["baselines"]
    raw_draws = projection["draws"]
    if not isinstance(raw_baselines, list) or len(raw_baselines) != expected_baselines:
        raise ValueError("baseline projection count drifted")
    if not isinstance(raw_draws, list) or len(raw_draws) != expected_draws:
        raise ValueError("draw projection count drifted")
    if not all(isinstance(item, dict) for item in (*raw_baselines, *raw_draws)):
        raise ValueError("projection rows must be objects")

    baselines = [_prepare_baseline(item, index) for index, item in enumerate(raw_baselines)]
    draws = [_prepare_draw(item, index) for index, item in enumerate(raw_draws)]
    baseline_ids = [str(item["baseline_id_text"]) for item in baselines]
    draw_ids = [str(item["draw_id_text"]) for item in draws]
    if len(set(baseline_ids)) != expected_baselines:
        raise ValueError("baseline projection contains duplicate identities")
    if len(set(draw_ids)) != expected_draws:
        raise ValueError("draw projection contains duplicate identities")
    baselines.sort(key=lambda item: str(item["baseline_id_text"]))
    draws.sort(key=lambda item: (str(item["draw_date_text"]), str(item["draw_id_text"])))

    stream = hashlib.sha256()
    merkle = OrderedMerkleFrontier()
    family_counts: Counter[str] = Counter()
    previous_key: tuple[str, str] | None = None
    first_key: tuple[str, str] | None = None
    for draw in draws:
        draw_id = str(draw["draw_id_text"])
        for baseline in baselines:
            baseline_id = str(baseline["baseline_id_text"])
            key = (draw_id, baseline_id)
            if previous_key is not None and key <= previous_key:
                raise ValueError("functional event keys are duplicated or out of order")
            if first_key is None:
                first_key = key
            previous_key = key
            canonical_payload = _canonical_cell(draw, baseline)
            stream.update(len(canonical_payload).to_bytes(8, "big"))
            stream.update(canonical_payload)
            merkle.add(canonical_payload)
            family_counts[str(baseline["family_id"])] += 1
    if merkle.count != expected_cells or first_key is None or previous_key is None:
        raise ValueError("functional Cartesian stream is incomplete")

    forbidden = sorted(
        name
        for name in sys.modules
        if name == "xinao"
        or name.startswith("xinao.")
        or name == "pydantic"
        or name.startswith("pydantic.")
        or name == "pydantic_core"
        or name.startswith("pydantic_core.")
        or name == "rfc8785"
        or name.startswith("rfc8785.")
    )
    if forbidden:
        raise RuntimeError(f"pure worker imported forbidden modules: {forbidden}")
    worker_bytes = Path(__file__).resolve().read_bytes()
    core = {
        "schema_version": RESULT_SCHEMA,
        "projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
        "projection_size_bytes": len(projection_bytes),
        "worker_sha256": hashlib.sha256(worker_bytes).hexdigest(),
        "worker_size_bytes": len(worker_bytes),
        "baseline_count": expected_baselines,
        "draw_count": expected_draws,
        "cell_count": merkle.count,
        "ordered_cell_stream_sha256": stream.hexdigest(),
        "ordered_merkle_root": merkle.root(),
        "family_cell_counts": dict(sorted(family_counts.items())),
        "key_proof": {
            "expected_cartesian_key_count": expected_cells,
            "actual_stream_key_count": merkle.count,
            "missing_cartesian_keys": 0,
            "unexpected_cartesian_keys": 0,
            "duplicate_cartesian_keys": 0,
            "strictly_ordered": True,
            "first_canonical_key": list(first_key),
            "last_canonical_key": list(previous_key),
        },
        "isolated_mode": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "forbidden_module_count": 0,
    }
    core_bytes = json.dumps(
        core,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return {**core, "content_sha256": hashlib.sha256(core_bytes).hexdigest()}


def main() -> int:
    if len(sys.argv) != 1 or not sys.flags.isolated or not sys.flags.no_site:
        raise RuntimeError("pure worker requires argument-free python -I -S execution")
    projection_bytes = sys.stdin.buffer.read()
    if not projection_bytes:
        raise ValueError("projection stdin is empty")
    result = _compile(projection_bytes)
    sys.stdout.buffer.write(
        json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
