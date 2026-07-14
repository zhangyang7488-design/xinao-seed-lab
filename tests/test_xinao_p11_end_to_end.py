from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_xinao_p11_end_to_end.py"
SPEC = importlib.util.spec_from_file_location("xinao_p11", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_canonical_pack_hash_is_order_stable() -> None:
    assert MODULE.canonical_hash({"a": 1, "b": 2}) == MODULE.canonical_hash({"b": 2, "a": 1})


def test_pack_writer_roundtrips(tmp_path: Path) -> None:
    path = tmp_path / "pack.json"
    value = {"schema_version": "test", "pack_hash": ""}
    value["pack_hash"] = MODULE.canonical_hash(value)
    MODULE.write_json_atomic(path, value)
    assert MODULE.load_object(path) == value
