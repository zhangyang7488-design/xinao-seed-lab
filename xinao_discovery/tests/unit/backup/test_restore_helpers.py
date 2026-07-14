from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backup" / "restore_drill.py"
SPEC = spec_from_file_location("xinao_restore_drill", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_row_hash_is_order_and_byte_sensitive() -> None:
    assert MODULE._hash_rows("a\nb") == MODULE._hash_rows("a\nb")
    assert MODULE._hash_rows("a\nb") != MODULE._hash_rows("b\na")
