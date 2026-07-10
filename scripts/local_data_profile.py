"""Profile common local datasets without sending rows to an LLM or remote service."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

SUPPORTED_SUFFIXES = frozenset(
    {".csv", ".feather", ".ipc", ".json", ".jsonl", ".ndjson", ".parquet", ".tsv"}
)


def _source_file(raw_path: str | Path) -> Path:
    raw = str(raw_path)
    if "://" in raw:
        raise ValueError("Only local files are accepted; URLs are not allowed")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"Expected a file: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported data format: {path.suffix or '<none>'}")
    return path


def _lazy_frame(path: Path):
    import polars as pl

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pl.scan_csv(path)
    if suffix == ".tsv":
        return pl.scan_csv(path, separator="\t")
    if suffix == ".parquet":
        return pl.scan_parquet(path)
    if suffix in {".jsonl", ".ndjson"}:
        return pl.scan_ndjson(path)
    if suffix in {".ipc", ".feather"}:
        return pl.scan_ipc(path)
    if suffix == ".json":
        return pl.read_json(path).lazy()
    raise AssertionError(f"unhandled suffix: {suffix}")


def _json_value(value: Any, *, max_chars: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (date, datetime, time, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        value = value.hex()
    elif isinstance(value, (list, tuple)):
        return [_json_value(item, max_chars=max_chars) for item in value]
    elif isinstance(value, dict):
        return {str(key): _json_value(item, max_chars=max_chars) for key, item in value.items()}
    else:
        value = str(value)
    return value if len(value) <= max_chars else value[:max_chars] + "…"


def profile_data(
    source: str | Path,
    *,
    sample_rows: int = 0,
    max_columns: int = 100,
    max_value_chars: int = 200,
) -> dict[str, Any]:
    import polars as pl

    path = _source_file(source)
    lazy = _lazy_frame(path)
    schema = lazy.collect_schema()
    all_columns = list(schema.names())
    columns = all_columns[:max_columns]
    selected = lazy.select(columns)

    row_count = int(lazy.select(pl.len()).collect(engine="streaming").item())
    null_row = selected.select(pl.all().null_count()).collect(engine="streaming").row(0, named=True)
    numeric_columns = [name for name in columns if schema[name].is_numeric()]
    numeric: dict[str, dict[str, Any]] = {}
    if numeric_columns:
        expressions = []
        for name in numeric_columns:
            expressions.extend(
                (
                    pl.col(name).min().alias(f"{name}__min"),
                    pl.col(name).max().alias(f"{name}__max"),
                    pl.col(name).mean().alias(f"{name}__mean"),
                )
            )
        values = lazy.select(expressions).collect(engine="streaming").row(0, named=True)
        for name in numeric_columns:
            numeric[name] = {
                "min": _json_value(values[f"{name}__min"], max_chars=max_value_chars),
                "max": _json_value(values[f"{name}__max"], max_chars=max_value_chars),
                "mean": _json_value(values[f"{name}__mean"], max_chars=max_value_chars),
            }

    samples: list[dict[str, Any]] = []
    if sample_rows > 0:
        rows = selected.head(sample_rows).collect(engine="streaming").to_dicts()
        samples = [
            {key: _json_value(value, max_chars=max_value_chars) for key, value in row.items()}
            for row in rows
        ]

    return {
        "schema_version": "xinao.local-data-profile.v1",
        "local_only": True,
        "content_network_egress": False,
        "source": str(path),
        "engine": f"polars {pl.__version__}",
        "rows": row_count,
        "columns": len(all_columns),
        "profiled_columns": len(columns),
        "omitted_columns": all_columns[max_columns:],
        "schema": {name: str(schema[name]) for name in columns},
        "null_counts": {name: int(null_row[name]) for name in columns},
        "numeric_summary": numeric,
        "sample_rows": samples,
    }


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Local data profile",
        "",
        f"- Rows: {result['rows']}",
        f"- Columns: {result['columns']}",
        f"- Engine: {result['engine']}",
        "- Content network egress: false",
        "",
        "| Column | Type | Nulls | Min | Max | Mean |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    numeric = result["numeric_summary"]
    for name, dtype in result["schema"].items():
        stats = numeric.get(name, {})
        cells = [
            name,
            dtype,
            result["null_counts"][name],
            stats.get("min", ""),
            stats.get("max", ""),
            stats.get("mean", ""),
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
    if result["sample_rows"]:
        lines.extend(("", "## Opt-in sample", "", "```json"))
        lines.append(json.dumps(result["sample_rows"], ensure_ascii=False, indent=2))
        lines.append("```")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="CSV, TSV, Parquet, JSON(L), IPC, or Feather file")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=0,
        help="Include this many leading rows; default 0 avoids exposing row values",
    )
    parser.add_argument("--max-columns", type=int, default=100)
    parser.add_argument("--max-value-chars", type=int, default=200)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.sample_rows < 0 or args.max_columns < 1 or args.max_value_chars < 1:
        print("local-data-profile: numeric limits must be positive", file=sys.stderr)
        return 2
    try:
        result = profile_data(
            args.source,
            sample_rows=args.sample_rows,
            max_columns=args.max_columns,
            max_value_chars=args.max_value_chars,
        )
    except Exception as exc:
        print(f"local-data-profile: {exc}", file=sys.stderr)
        return 2
    rendered = (
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.format == "json"
        else _markdown(result)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered.rstrip() + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
