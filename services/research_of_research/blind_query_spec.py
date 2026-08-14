"""Build a blind archive-query canary as a research cell v2 specification.

The builder deliberately does not import the cell runner.  It compiles a small,
generic configuration into the runner's public JSON dialect while keeping the
consumer-facing archive opaque: source ids and host paths stay in the
preregistration, never in ``archive/catalog.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from .archive_query import LEDGER_SCHEMA, catalog_archive

CELL_SPEC_SCHEMA = "xinao.research-of-research.cell-spec.v2"
CANARY_SCHEMA = "xinao.research-of-research.archive-query-canary.v1"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
_OPAQUE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_DISALLOWED_CATALOG_LABELS = (
    "important",
    "must-read",
    "must_read",
    "required",
    "priority",
    "critical",
    "最重要",
    "重要",
    "必读",
    "必须",
)
_WORKSPACE_NAMES = {
    "stimulus": "STIMULUS.md",
    "stimulus.md": "STIMULUS.md",
    "observation": "OBSERVATION.md",
    "observation.md": "OBSERVATION.md",
}


class BlindQuerySpecError(ValueError):
    """A blind-query configuration cannot produce a valid isolated cell spec."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> None:
    raise BlindQuerySpecError(reason_code, message)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve_source_path(value: object, *, base_dir: Path) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        _fail("SOURCE_PATH_INVALID", "source paths must be non-empty strings")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _stable_read_file(path: Path) -> tuple[bytes, dict[str, object]]:
    """Read one regular file while detecting replacement or in-place mutation."""

    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        _fail("SOURCE_INVALID", f"source is not a regular non-link file: {path}")
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise BlindQuerySpecError("SOURCE_READ_FAILED", f"could not read source: {path}") from exc
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field, None) != getattr(after, field, None) for field in stable_fields):
        _fail("SOURCE_CHANGED", f"source changed while being read: {path}")
    if len(raw) != before.st_size:
        _fail("SOURCE_CHANGED", f"source size changed while being read: {path}")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "mtime_ns": before.st_mtime_ns,
    }


def _as_object(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("CONFIG_INVALID", f"{field} must be an object")
    return value


def _required_string(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail("CONFIG_INVALID", f"{key} must be a non-empty string")
    return value


def _validate_slug(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SLUG.fullmatch(value) is None:
        _fail("ID_INVALID", f"{field} must be a stable lowercase slug")
    return value


def _validate_opaque_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        _fail("OPAQUE_ID_INVALID", f"{field} must be a path-safe opaque id")
    return value


def _created_at_key(value: object, *, field: str) -> tuple[datetime, str]:
    if not isinstance(value, str) or not value.strip():
        _fail("CREATED_AT_INVALID", f"{field} must be a non-empty ISO-8601 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise BlindQuerySpecError(
            "CREATED_AT_INVALID", f"{field} is not an ISO-8601 timestamp: {value}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("CREATED_AT_INVALID", f"{field} must include a UTC offset: {value}")
    return parsed, value


def _source_registry(config: Mapping[str, object]) -> dict[str, object]:
    raw = config.get("source_files", config.get("sources", {}))
    if raw is None:
        return {}
    registry = _as_object(raw, field="source_files")
    return {str(key): value for key, value in registry.items()}


def _workspace_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _WORKSPACE_NAMES.get(value.replace("\\", "/").casefold())


def _registry_path(value: object) -> object:
    if isinstance(value, Mapping):
        return value.get("path")
    return value


def _normalize_stimulus_sources(
    config: Mapping[str, object], *, base_dir: Path
) -> list[dict[str, object]]:
    mappings = _as_object(config.get("stimulus_source_mappings"), field="stimulus_source_mappings")
    registry = _source_registry(config)
    normalized: dict[str, dict[str, object]] = {}
    for key_value, raw_value in mappings.items():
        key = str(key_value)
        workspace_name = _workspace_name(key)
        source_id: object = None
        source_path: object = None
        if isinstance(raw_value, Mapping):
            workspace_name = _workspace_name(raw_value.get("workspace_path")) or workspace_name
            source_id = raw_value.get("source_id")
            source_path = raw_value.get("path")
        elif isinstance(raw_value, str):
            if raw_value in registry:
                source_id = raw_value
                source_path = _registry_path(registry[raw_value])
            else:
                source_path = raw_value
        else:
            _fail(
                "STIMULUS_MAPPING_INVALID",
                "stimulus mappings must contain a path, source id, or source descriptor",
            )

        if workspace_name is None:
            workspace_name = _workspace_name(
                raw_value.get("workspace_path") if isinstance(raw_value, Mapping) else None
            )
        if workspace_name is None:
            workspace_name = _workspace_name(source_id) or _workspace_name(key)
        if workspace_name is None:
            _fail(
                "STIMULUS_MAPPING_INVALID",
                f"mapping does not identify STIMULUS.md or OBSERVATION.md: {key}",
            )

        if source_id is None:
            source_id = "stimulus" if workspace_name == "STIMULUS.md" else "observation"
        source_id = _validate_slug(source_id, field=f"{workspace_name} source_id")
        if source_path is None and source_id in registry:
            source_path = _registry_path(registry[source_id])
        path = _resolve_source_path(source_path, base_dir=base_dir)
        raw, identity = _stable_read_file(path)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BlindQuerySpecError(
                "STIMULUS_NOT_UTF8", f"{workspace_name} source is not UTF-8: {path}"
            ) from exc
        if workspace_name in normalized:
            _fail("STIMULUS_MAPPING_INVALID", f"duplicate mapping for {workspace_name}")
        normalized[workspace_name] = {
            "workspace_path": workspace_name,
            "source_id": source_id,
            "path": path,
            "raw": raw,
            "identity": identity,
        }

    missing = sorted({"STIMULUS.md", "OBSERVATION.md"} - normalized.keys())
    if missing:
        _fail(
            "STIMULUS_MAPPING_INVALID",
            f"stimulus mappings must provide both workspace files; missing: {', '.join(missing)}",
        )
    return [normalized["STIMULUS.md"], normalized["OBSERVATION.md"]]


def _normalize_archive_records(
    config: Mapping[str, object], *, base_dir: Path
) -> list[dict[str, object]]:
    raw_records = config.get("archive_records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        _fail("ARCHIVE_RECORD_INVALID", "archive_records must be a non-empty list")
    if not raw_records:
        _fail("ARCHIVE_RECORD_INVALID", "archive_records must be a non-empty list")
    records: list[dict[str, object]] = []
    record_ids: set[str] = set()
    source_ids: set[str] = set()
    for index, raw_record in enumerate(raw_records):
        record = _as_object(raw_record, field=f"archive_records[{index}]")
        record_id = _validate_opaque_id(
            record.get("record_id"), field=f"archive_records[{index}].record_id"
        )
        source_id = _validate_slug(
            record.get("source_id"), field=f"archive_records[{index}].source_id"
        )
        kind = record.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            _fail("ARCHIVE_RECORD_INVALID", f"archive record {record_id} requires a kind")
        visible_label = f"{record_id}\n{kind}".casefold()
        if any(label.casefold() in visible_label for label in _DISALLOWED_CATALOG_LABELS):
            _fail(
                "CATALOG_LABEL_INVALID",
                f"opaque catalog metadata contains a steering label: {record_id}",
            )
        created_key, created_at = _created_at_key(
            record.get("created_at"), field=f"archive_records[{index}].created_at"
        )
        if record_id in record_ids:
            _fail("ARCHIVE_RECORD_INVALID", f"duplicate record_id: {record_id}")
        if source_id in source_ids:
            _fail("ARCHIVE_RECORD_INVALID", f"duplicate source_id: {source_id}")
        path = _resolve_source_path(record.get("path"), base_dir=base_dir)
        raw, identity = _stable_read_file(path)
        record_ids.add(record_id)
        source_ids.add(source_id)
        records.append(
            {
                "record_id": record_id,
                "source_id": source_id,
                "kind": kind,
                "created_at": created_at,
                "created_at_key": created_key,
                "path": path,
                "raw": raw,
                "identity": identity,
            }
        )
    return sorted(records, key=lambda row: (row["created_at_key"], row["record_id"]))


def _normalize_withheld_sources(
    config: Mapping[str, object], *, base_dir: Path
) -> list[dict[str, object]]:
    raw_sources = config.get("withheld_sources", [])
    registry = _source_registry(config)
    rows: list[tuple[object, object]]
    if isinstance(raw_sources, Mapping):
        rows = list(raw_sources.items())
    elif isinstance(raw_sources, Sequence) and not isinstance(raw_sources, (str, bytes)):
        rows = [(None, value) for value in raw_sources]
    else:
        _fail("WITHHELD_SOURCE_INVALID", "withheld_sources must be a list or object")

    normalized: list[dict[str, object]] = []
    source_ids: set[str] = set()
    record_ids: set[str] = set()
    for index, (mapping_key, raw_value) in enumerate(rows):
        if isinstance(raw_value, Mapping):
            source_id_value = raw_value.get("source_id", mapping_key)
            path_value = raw_value.get("path")
            record_id_value = raw_value.get("record_id", source_id_value)
            kind = raw_value.get("kind", "withheld")
            created_at = raw_value.get("created_at")
        elif isinstance(raw_value, str):
            if mapping_key is not None:
                source_id_value = mapping_key
                path_value = raw_value
            elif raw_value in registry:
                source_id_value = raw_value
                path_value = _registry_path(registry[raw_value])
            else:
                _fail(
                    "WITHHELD_SOURCE_INVALID",
                    "string withheld sources must reference source_files or appear in a mapping",
                )
            record_id_value = source_id_value
            kind = "withheld"
            created_at = None
        else:
            _fail("WITHHELD_SOURCE_INVALID", f"invalid withheld source at index {index}")

        source_id = _validate_slug(source_id_value, field=f"withheld_sources[{index}].source_id")
        record_id = _validate_opaque_id(
            record_id_value, field=f"withheld_sources[{index}].record_id"
        )
        if not isinstance(kind, str) or not kind.strip():
            _fail("WITHHELD_SOURCE_INVALID", f"withheld source {source_id} requires a kind")
        if created_at is not None:
            _created_at_key(created_at, field=f"withheld_sources[{index}].created_at")
        if source_id in source_ids or record_id in record_ids:
            _fail("WITHHELD_SOURCE_INVALID", f"duplicate withheld id: {source_id}/{record_id}")
        path = _resolve_source_path(path_value, base_dir=base_dir)
        raw, identity = _stable_read_file(path)
        source_ids.add(source_id)
        record_ids.add(record_id)
        normalized.append(
            {
                "record_id": record_id,
                "source_id": source_id,
                "kind": kind,
                "created_at": created_at,
                "path": path,
                "raw": raw,
                "identity": identity,
            }
        )
    return normalized


def _string_list(config: Mapping[str, object], key: str, *aliases: str) -> list[str]:
    value: object = config.get(key)
    if value is None:
        for alias in aliases:
            if alias in config:
                value = config[alias]
                break
    if value is None:
        return []
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or any(not isinstance(item, str) or not item for item in value)
    ):
        _fail("CONFIG_INVALID", f"{key} must be a list of non-empty strings")
    result = list(value)
    if len(set(result)) != len(result):
        _fail("CONFIG_INVALID", f"{key} must not contain duplicates")
    return result


# The isolated consumer receives the exact reviewed stdlib tool, not a second
# embedded implementation that can drift from its ledger or path contract.
ARCHIVE_QUERY_SCRIPT = Path(__file__).with_name("archive_query.py").read_text(encoding="utf-8")
RESEARCH_CELL_MCP_SCRIPT = Path(__file__).with_name("research_cell_mcp.py").read_text(
    encoding="utf-8"
)
ARCHIVE_MCP_ENABLED_TOOLS = [
    "archive_list",
    "archive_metadata",
    "archive_find",
    "archive_open",
]
ARCHIVE_MCP_CONFIG_TEXT = json.dumps(
    {
        "schema": "xinao.research-of-research.cell-mcp-config.v1",
        "mode": "archive-query",
        "archive": {
            "catalog_path": "archive/catalog.json",
            "config_path": "archive/private/config.json",
            "ledger_path": "archive/query-ledger.jsonl",
        },
    },
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
) + "\n"
ARCHIVE_MCP_INVOCATION_PREFIX = ["mcp__research_cell__archive"]


MATCHED_TERMINAL_CONTRACT = """Work only inside this isolated workspace.
Read STIMULUS.md and OBSERVATION.md. Form your own account of what matters and what, if anything,
should be queried next. A neutral local record interface is available through the archive_list,
archive_metadata, archive_find, and archive_open tools. If the catalog is non-empty, open exactly
three distinct records; if it is empty, open none. Do not read archive/store or archive/private
directly and do not use semantic, vector, or LLM retrieval. Report the queries and opaque record ids
you selected, the relationship you formed, what it predicts about held-out material, and what residual
would make you reopen it. Return a candidate only; do not modify production, claim adoption, or treat
this result as a project completion gate.
"""


PILOT_TERMINAL_CONTRACT = """Work only inside this isolated workspace.
Read STIMULUS.md and OBSERVATION.md. Form your own account of what matters and what, if anything,
should be queried next. A neutral local record interface is available through the archive_list,
archive_metadata, archive_find, and archive_open tools; use it only if it is useful. Zero record
opens is allowed. Do not read archive/store or archive/private directly and do not use semantic,
vector, or LLM retrieval. Report any queries and opaque record ids you selected, the relationship
you formed, one falsifiable prediction, and what residual would make you reopen it. Return a
candidate only; do not modify production, claim adoption, or treat this instrument pilot as a
formal canary or project completion gate.
"""


def _portable_archive_package(
    records: Sequence[Mapping[str, object]], *, max_open_count: int
) -> dict[str, object]:
    """Compile one relocatable archive tree for a variant workspace seed."""

    with tempfile.TemporaryDirectory(prefix="ror-neutral-archive-") as temporary:
        root = Path(temporary).resolve()
        store = root / "archive" / "store"
        store.mkdir(parents=True)
        assigned_by_relative: dict[str, str] = {}
        source_by_relative: dict[str, str] = {}
        for row in records:
            assigned_id = str(row["record_id"])
            relative = f"archive/store/{assigned_id}.bin"
            store_relative = f"{assigned_id}.bin"
            target = root / relative
            target.write_bytes(row["raw"])
            created_at = row["created_at_key"]
            if not isinstance(created_at, datetime):
                _fail("CREATED_AT_INVALID", f"record has no parsed timestamp: {assigned_id}")
            stamp_ns = int(created_at.timestamp() * 1_000_000_000)
            os.utime(target, ns=(stamp_ns, stamp_ns))
            assigned_by_relative[store_relative] = assigned_id
            source_by_relative[store_relative] = str(row["source_id"])

        catalog_path = root / "archive" / "catalog.json"
        config_path = root / "archive" / "private" / "config.json"
        ledger_path = root / "archive" / "query-ledger.jsonl"
        config_path.parent.mkdir(parents=True)
        catalog_archive(
            store_root=store,
            catalog_path=catalog_path,
            config_path=config_path,
            ledger_path=ledger_path,
            max_open_count=max_open_count,
            portable_root=root,
        )
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))
        generated_to_assigned: dict[str, str] = {}
        generated_to_source: dict[str, str] = {}
        for row in config["provenance"]["records"]:
            relative = str(row["store_relative_path"])
            generated = str(row["record_id"])
            generated_to_assigned[generated] = assigned_by_relative[relative]
            generated_to_source[generated] = source_by_relative[relative]
        return {
            "catalog": catalog,
            "catalog_text": catalog_path.read_text(encoding="utf-8"),
            "config_text": config_path.read_text(encoding="utf-8"),
            # Catalog construction is an S-side freeze step.  Subject-visible
            # query evidence starts from an empty, hash-chained ledger.
            "ledger_text": "",
            "generated_to_assigned": generated_to_assigned,
            "generated_to_source": generated_to_source,
        }


def build_blind_query_spec(
    config: Mapping[str, object], *, base_dir: str | Path | None = None
) -> dict[str, object]:
    """Compile ``config`` into one deterministic cell-spec.v2 JSON object."""

    if not isinstance(config, Mapping):
        _fail("CONFIG_INVALID", "configuration must be an object")
    source_base = Path.cwd() if base_dir is None else Path(base_dir).expanduser().resolve()
    cell_id = _validate_slug(config.get("cell_id"), field="cell_id")
    account_slot = _required_string(config, "account_slot")
    if account_slot not in {"A", "C"}:
        _fail("ACCOUNT_SLOT_INVALID", "account_slot must be A or C")
    stage = str(config.get("stage", "matched"))
    if stage not in {"instrument-pilot", "matched"}:
        _fail("CANARY_STAGE_INVALID", "stage must be instrument-pilot or matched")
    max_open_count = config.get("max_open_count", 3)
    if (
        not isinstance(max_open_count, int)
        or isinstance(max_open_count, bool)
        or max_open_count != 3
    ):
        _fail("MAX_OPEN_COUNT_INVALID", "this canary freezes max_open_count at exactly 3")

    path_fields = {
        "cap_policy": "account_research_cap_policy",
        "launcher": "launcher",
        "quota": "world_turn_quota_root",
        "workspace": "workspace_root",
    }
    harness_paths = {
        output_key: str(_resolve_source_path(config.get(input_key), base_dir=source_base))
        for input_key, output_key in path_fields.items()
    }
    guards_value = config.get("production_guards")
    if not isinstance(guards_value, Sequence) or isinstance(guards_value, (str, bytes)):
        _fail("PRODUCTION_GUARD_INVALID", "production_guards must be a non-empty list")
    production_guards = [
        str(_resolve_source_path(value, base_dir=source_base)) for value in guards_value
    ]
    if not production_guards:
        _fail("PRODUCTION_GUARD_INVALID", "production_guards must be a non-empty list")

    stimulus_sources = _normalize_stimulus_sources(config, base_dir=source_base)
    records = _normalize_archive_records(config, base_dir=source_base)
    withheld = _normalize_withheld_sources(config, base_dir=source_base)
    all_source_ids = [row["source_id"] for row in [*stimulus_sources, *records, *withheld]]
    if len(set(all_source_ids)) != len(all_source_ids):
        _fail("SOURCE_ID_CONFLICT", "stimulus, archive, and withheld source ids must be unique")

    if len(records) < 3:
        _fail("ARCHIVE_RECORD_INVALID", "the matched canary requires at least three records")
    archive_by_id = {str(row["record_id"]): row for row in records}
    curated_configured = "curated_record_ids" in config or "curated_ids" in config
    if stage == "instrument-pilot" and curated_configured:
        _fail("CURATED_SET_INVALID", "instrument-pilot does not include a curated arm")
    curated_ids = _string_list(config, "curated_record_ids", "curated_ids")
    if curated_configured and len(curated_ids) != max_open_count:
        _fail(
            "CURATED_SET_INVALID",
            "curated_record_ids must match the frozen maximum open count",
        )
    missing_curated = sorted(set(curated_ids) - archive_by_id.keys())
    if missing_curated:
        _fail("CURATED_SET_INVALID", f"curated ids are absent from the archive: {missing_curated}")
    curated_id_set = set(curated_ids)
    curated_records = [row for row in records if row["record_id"] in curated_id_set]
    # Freeze the full-pool opaque identity before selecting the random control.
    # The assessor sees and recomputes over these generated ids, so selection
    # must use the same domain rather than the operator's configured aliases.
    full_package = _portable_archive_package(records, max_open_count=max_open_count)
    assigned_to_generated = {
        assigned: generated
        for generated, assigned in full_package["generated_to_assigned"].items()
    }

    random_seed = config.get("random_seed")
    random_records: list[dict[str, object]] = []
    random_expected_generated_ids: list[str] = []
    if stage == "matched":
        if isinstance(random_seed, bool) or not isinstance(random_seed, (str, int)):
            _fail("RANDOM_SEED_INVALID", "random_seed must be a non-empty string or integer")
        if isinstance(random_seed, str) and not random_seed:
            _fail("RANDOM_SEED_INVALID", "random_seed must be a non-empty string or integer")
        seed_bytes = _canonical_bytes({"seed": random_seed})
        random_ranked = sorted(
            records,
            key=lambda row: _sha256(
                seed_bytes
                + b"\0"
                + assigned_to_generated[str(row["record_id"])].encode("utf-8")
            ),
        )
        random_id_set = {str(row["record_id"]) for row in random_ranked[:max_open_count]}
        random_records = [row for row in records if row["record_id"] in random_id_set]
        random_expected_generated_ids = [
            assigned_to_generated[str(row["record_id"])]
            for row in random_ranked[:max_open_count]
        ]

    curated_provenance_configured = (
        "curated_selection_provenance" in config or "curated_provenance" in config
    )
    if curated_provenance_configured and not curated_configured:
        _fail(
            "CURATED_SET_INVALID",
            "curated selection provenance requires curated_record_ids",
        )
    raw_curated_provenance = config.get(
        "curated_selection_provenance", config.get("curated_provenance", {})
    )
    if not isinstance(raw_curated_provenance, Mapping):
        _fail("CURATED_SET_INVALID", "curated_selection_provenance must be an object")
    try:
        curated_provenance = json.loads(json.dumps(raw_curated_provenance, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise BlindQuerySpecError(
            "CURATED_SET_INVALID", "curated_selection_provenance must be JSON-serializable"
        ) from exc

    raw_revision_lane = config.get("revision_path_lane")
    if raw_revision_lane is not None and not isinstance(raw_revision_lane, Mapping):
        _fail("REVISION_PATH_LANE_INVALID", "revision_path_lane must be an object when supplied")
    try:
        revision_lane = (
            json.loads(json.dumps(raw_revision_lane, ensure_ascii=False))
            if raw_revision_lane is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise BlindQuerySpecError(
            "REVISION_PATH_LANE_INVALID", "revision_path_lane must be JSON-serializable"
        ) from exc

    forbidden_sentinels = _string_list(config, "forbidden_sentinels", "forbidden_future_sentinels")
    stimulus_implied_ids = _string_list(config, "stimulus_implied_ids")
    withheld_interesting_ids = _string_list(config, "withheld_interesting_ids")
    archive_ids = set(archive_by_id)
    unknown_implied = sorted(set(stimulus_implied_ids) - archive_ids)
    if unknown_implied:
        _fail(
            "OBSERVABLE_ID_INVALID",
            f"stimulus_implied_ids are absent from the opaque archive: {unknown_implied}",
        )
    withheld_ids = {
        str(value) for row in withheld for value in (row["record_id"], row["source_id"])
    }
    unknown_withheld = sorted(set(withheld_interesting_ids) - withheld_ids)
    if unknown_withheld:
        _fail(
            "OBSERVABLE_ID_INVALID",
            f"withheld_interesting_ids are absent from withheld_sources: {unknown_withheld}",
        )

    terminal_contract = (
        PILOT_TERMINAL_CONTRACT if stage == "instrument-pilot" else MATCHED_TERMINAL_CONTRACT
    )
    visible_blobs = [
        *(row["raw"] for row in stimulus_sources),
        *(row["raw"] for row in records),
        ARCHIVE_QUERY_SCRIPT.encode("utf-8"),
        RESEARCH_CELL_MCP_SCRIPT.encode("utf-8"),
        ARCHIVE_MCP_CONFIG_TEXT.encode("utf-8"),
        terminal_contract.encode("utf-8"),
    ]
    for sentinel in forbidden_sentinels:
        needle = sentinel.encode("utf-8")
        if any(needle in blob for blob in visible_blobs):
            _fail(
                "FORBIDDEN_SENTINEL_VISIBLE",
                f"a forbidden future sentinel is model-visible: {sentinel!r}",
            )

    episode_sources: list[dict[str, object]] = []
    chronology = 0
    for row in stimulus_sources:
        chronology += 1
        episode_sources.append(
            {
                "id": row["source_id"],
                "role": row["workspace_path"].removesuffix(".md").casefold(),
                "visibility": "model_visible",
                "known_at": "canary-input",
                "chronology_index": chronology,
                "provenance_kind": "raw",
                "derived_from": [],
                "material": {"kind": "file", "path": str(row["path"])},
            }
        )
    for row in records:
        chronology += 1
        episode_sources.append(
            {
                "id": row["source_id"],
                "role": "opaque-archive-record",
                "visibility": "model_visible",
                "known_at": row["created_at"],
                "chronology_index": chronology,
                "provenance_kind": "raw",
                "derived_from": [],
                "material": {"kind": "file", "path": str(row["path"])},
            }
        )
    cutoff_index = chronology
    for row in withheld:
        chronology += 1
        episode_sources.append(
            {
                "id": row["source_id"],
                "role": "withheld-settlement",
                "visibility": "withheld",
                "known_at": row["created_at"],
                "chronology_index": chronology,
                "provenance_kind": "raw",
                "derived_from": [],
                "material": {"kind": "file", "path": str(row["path"])},
            }
        )

    selected_by_variant: dict[str, Sequence[Mapping[str, object]]]
    access_policies: dict[str, str]
    if stage == "instrument-pilot":
        selected_by_variant = {"autonomous": records}
        access_policies = {"autonomous": "full-opaque-catalog-free-k"}
    else:
        selected_by_variant = {"baseline": [], "autonomous": records}
        access_policies = {
            "baseline": "empty",
            "autonomous": "full-opaque-catalog",
        }
        if curated_configured:
            selected_by_variant["curated"] = curated_records
            access_policies["curated"] = "frozen-external-set"
        selected_by_variant["random"] = random_records
        access_policies["random"] = "frozen-seed-set"

    packages = {"autonomous": full_package}
    packages.update(
        {
            variant_id: _portable_archive_package(
                selected, max_open_count=(0 if variant_id == "baseline" else max_open_count)
            )
            for variant_id, selected in selected_by_variant.items()
            if variant_id != "autonomous"
        }
    )
    full_pool_catalog = full_package["catalog"]
    full_pool_id = f"sha256:{full_pool_catalog['catalog_id']}"
    stimulus_implied_generated_ids = [
        assigned_to_generated[record_id] for record_id in stimulus_implied_ids
    ]

    def variant(variant_id: str) -> dict[str, object]:
        package = packages[variant_id]
        selected = selected_by_variant[variant_id]
        return {
            "id": variant_id,
            "provenance_kind": "archive-access-policy",
            "factor_assignments": (
                {"archive_access_policy": access_policies[variant_id]} if stage == "matched" else {}
            ),
            "view": [],
            "workspace_files": {
                "archive/catalog.json": package["catalog_text"],
                "archive/private/config.json": package["config_text"],
                "archive/query-ledger.jsonl": package["ledger_text"],
            },
            "workspace_source_files": {
                f"archive/store/{row['record_id']}.bin": row["source_id"] for row in selected
            },
        }

    arm_provenance: dict[str, dict[str, object]] = {}
    for variant_id, selected in selected_by_variant.items():
        package = packages[variant_id]
        catalog = package["catalog"]
        catalog_raw = str(package["catalog_text"]).encode("utf-8")
        arm_provenance[variant_id] = {
            "full_pool_id": full_pool_id,
            "selected_from_full_pool": variant_id != "baseline",
            "record_ids": [row["record_id"] for row in catalog["records"]],
            "catalog_record_count": len(catalog["records"]),
            "catalog_bytes": len(catalog_raw),
            "catalog_sha256": _sha256(catalog_raw),
        }
    if "baseline" in arm_provenance:
        arm_provenance["baseline"].update({"selection_method": "empty"})
    arm_provenance["autonomous"].update({"selection_method": "full_opaque_catalog"})
    if curated_configured:
        arm_provenance["curated"].update(
            {
                "selection_method": "frozen_external_set",
                "external_selection_provenance": curated_provenance,
            }
        )
    if "random" in arm_provenance:
        arm_provenance["random"].update(
            {
                "selection_method": "sha256_seed_rank_v1",
                "seed": random_seed,
                "seed_rank_id_domain": "generated_opaque_record_id",
                "expected_selected_ids": random_expected_generated_ids,
            }
        )

    required_opens = {
        variant_id: (
            0 if variant_id == "baseline" or stage == "instrument-pilot" else max_open_count
        )
        for variant_id in selected_by_variant
    }

    observables = {
        "archive_query_canary": {
            "schema": CANARY_SCHEMA,
            "stage": stage,
            "diagnostic_only": True,
            "automatic_adoption_allowed": False,
            "project_completion_gate": False,
            "prompt_identity_required": True,
            "variant_views_required_empty": True,
            "fresh_session_per_variant_required": True,
            "variant_ids": list(selected_by_variant),
            "query_tool_path": "research_cell_mcp.py",
            "archive_query_implementation_path": "archive_query.py",
            "query_transport": "sealed-stdio-mcp",
            "mcp_server_id": "research_cell",
            "catalog_path": "archive/catalog.json",
            "private_config_path": "archive/private/config.json",
            "backing_store_relative_path": "archive/store",
            "backing_store_record_pattern": "archive/store/{opaque_id}.bin",
            "query_ledger_path": "archive/query-ledger.jsonl",
            "allowed_query_tool_invocation_prefix": list(ARCHIVE_MCP_INVOCATION_PREFIX),
            "stimulus_path": "STIMULUS.md",
            "observation_path": "OBSERVATION.md",
            "catalog_record_fields": [
                "record_id",
                "kind",
                "created_at",
                "bytes",
                "sha256",
            ],
            "catalog_schema_identical_across_variants": True,
            "full_pool_id": full_pool_id,
            "full_pool_record_identities": [
                {
                    "record_id": row["record_id"],
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                }
                for row in full_pool_catalog["records"]
            ],
            "query_surface_sha256": _sha256(
                ARCHIVE_QUERY_SCRIPT.encode("utf-8")
                + b"\x00"
                + RESEARCH_CELL_MCP_SCRIPT.encode("utf-8")
                + b"\x00"
                + ARCHIVE_MCP_CONFIG_TEXT.encode("utf-8")
            ),
            "retrieval_policy": {
                "lexical_exact_substring_search_only": True,
                "semantic_retrieval_allowed": False,
                "vector_retrieval_allowed": False,
                "llm_retrieval_allowed": False,
            },
            "stimulus_implied_ids": stimulus_implied_generated_ids,
            "configured_to_generated_record_ids": assigned_to_generated,
            "withheld_interesting_ids": withheld_interesting_ids,
            "arm_provenance": arm_provenance,
            "query_ledger_contract": {
                "schema": LEDGER_SCHEMA,
                "format": "append-only-jsonl",
                "two_phase_request_result": True,
                "operations": ["list", "metadata", "find", "open"],
                "required_unique_open_count_by_variant": required_opens,
                "maximum_unique_open_count": max_open_count,
                "open_events_bind_content_bytes_and_sha256": True,
            },
            "settlement_contract": {
                "evidence_sources": ["raw_trajectory", "workspace_after"],
                "required_unique_open_count_by_variant": required_opens,
                "direct_backing_store_access_forbidden": True,
                "direct_catalog_edit_forbidden": True,
                "query_ledger_edit_outside_query_tool_forbidden": True,
                "allowed_query_tool_invocation_prefix": list(
                    ARCHIVE_MCP_INVOCATION_PREFIX
                ),
                "backing_store_relative_path": "archive/store",
                "query_ledger_path": "archive/query-ledger.jsonl",
                "private_config_path": "archive/private/config.json",
                "scientific_conclusion": None,
                "project_completion_gate": False,
            },
            "evaluation_requires": [
                "self_selected_queries",
                "selected_opaque_record_ids",
                "unnamed_relationship_or_abstraction",
                "held_out_prediction",
                "search_or_representation_change",
                "reopen_condition",
            ],
            "evidence_source": "raw_trajectory_only",
        },
        "revision_path_lane": {
            "independent_lane": True,
            "configuration": revision_lane,
            "scientific_conclusion": None,
            "automatic_adoption_allowed": False,
        },
    }

    return {
        "schema": CELL_SPEC_SCHEMA,
        "cell_id": cell_id,
        "question": (
            "Does this neutral surface elicit any archive sampling beyond frozen-order following?"
            if stage == "instrument-pilot"
            else (
                "What causal difference, if any, follows from empty, self-selected full-archive, "
                + ("externally curated, and " if curated_configured else "")
                + "frozen random archive access under one matched surface?"
            )
        ),
        "episode": {
            "replay_fidelity": "OBSERVATIONAL_ONLY",
            "known_gaps": [
                "hidden model state is unavailable",
                "the canary observes behavior in an isolated reconstructed workspace only",
            ],
            "cutoff": "after stimulus and queryable archive; before withheld settlement",
            "cutoff_index": cutoff_index,
            "sources": episode_sources,
        },
        "intervention": {
            "common_view": [],
            "terminal_contract": {"kind": "literal", "text": terminal_contract},
            "held_constants": [
                "terminal contract bytes",
                "stimulus bytes",
                "observation bytes",
                "model and reasoning effort",
                "fresh Sol session policy",
                "tool surface and open ceiling",
                "turn timeout and terminal contract",
                "account cap and production guards",
            ],
            "intervention_variables": (
                [] if stage == "instrument-pilot" else ["archive_access_policy"]
            ),
            "known_confounders": [
                "the instrument pilot has no causal control arm"
                if stage == "instrument-pilot"
                else "catalog size and query-process exposure differ by access policy",
                "opaque record count and catalog bytes differ by access policy",
                *(["curated and random selections may overlap"] if curated_configured else []),
                "lexical search matches can differ because each arm has a different store",
            ],
            "variants": [variant(variant_id) for variant_id in selected_by_variant],
        },
        "observables": observables,
        "forbidden_future_sentinels": forbidden_sentinels,
        "production_guards": production_guards,
        "harness": {
            "account_slot": account_slot,
            "model": str(config.get("model", "gpt-5.6-sol")),
            "model_reasoning_effort": str(config.get("model_reasoning_effort", "max")),
            **harness_paths,
            "workspace_files": {
                "archive_query.py": ARCHIVE_QUERY_SCRIPT,
                "research_cell_mcp.py": RESEARCH_CELL_MCP_SCRIPT,
                "research-cell-tools.json": ARCHIVE_MCP_CONFIG_TEXT,
                "AGENTS.md": (
                    "This is an isolated candidate-only archive instrument. Work only inside this "
                    "workspace. Use the archive only through the archive_list, archive_metadata, "
                    "archive_find, and archive_open tools. Never read archive/store or "
                    "archive/private directly. Do not access production or the network.\n"
                ),
            },
            "workspace_source_files": {
                str(row["workspace_path"]): str(row["source_id"]) for row in stimulus_sources
            },
            "max_account_research_turns": 2,
            "physical_world_turn_slots": 4,
            "root_main_compute_allowed": False,
            "local_mcp": {
                "server_id": "research_cell",
                "script_path": "research_cell_mcp.py",
                "config_path": "research-cell-tools.json",
                "enabled_tools": list(ARCHIVE_MCP_ENABLED_TOOLS),
                "startup_timeout_sec": 20.0,
                "tool_timeout_sec": 120.0,
            },
            "web_search": "disabled",
            "forbidden_item_types": ["web_search_call"],
            "turn_timeout_seconds": int(config.get("turn_timeout_seconds", 1800)),
        },
    }


def _read_json_config(path: Path) -> Mapping[str, object]:
    raw, _identity = _stable_read_file(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlindQuerySpecError("CONFIG_JSON_INVALID", f"invalid JSON config: {path}") from exc
    return _as_object(value, field="configuration")


def _atomic_write(path: Path, raw: bytes) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_blind_query_spec_file(
    config_path: str | Path, output_path: str | Path
) -> dict[str, object]:
    """Stable-read a JSON config, compile it, and atomically write the cell spec."""

    config_file = Path(config_path).expanduser().resolve()
    spec = build_blind_query_spec(_read_json_config(config_file), base_dir=config_file.parent)
    _atomic_write(Path(output_path), _canonical_bytes(spec))
    return spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_path", nargs="?", help="JSON configuration path")
    parser.add_argument("output_path", nargs="?", help="output cell-spec JSON path")
    parser.add_argument("--config", dest="config_option", help="JSON configuration path")
    parser.add_argument("--output", dest="output_option", help="output cell-spec JSON path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = args.config_option or args.config_path
    output_path = args.output_option or args.output_path
    if not config_path or not output_path:
        _parser().error("both config and output paths are required")
    spec = build_blind_query_spec_file(config_path, output_path)
    receipt = {
        "schema": "xinao.research-of-research.blind-query-spec-build.v1",
        "output": str(Path(output_path).expanduser().resolve()),
        "cell_id": spec["cell_id"],
        "sha256": _sha256(_canonical_bytes(spec)),
    }
    sys.stdout.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
