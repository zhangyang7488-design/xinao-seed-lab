from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backup" / "create_backup.py"
SPEC = spec_from_file_location("xinao_create_backup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_json_lines = MODULE._json_lines
_sha256_bytes = MODULE._sha256_bytes
_version_id = MODULE._version_id


def test_version_id_accepts_minio_json_shapes() -> None:
    assert _version_id({"versionID": "v1"}) == "v1"
    assert _version_id({"object": {"versionId": "v2"}}) == "v2"
    assert _version_id({"version_id": "v3"}) == "v3"


def test_json_lines_and_hash_are_deterministic() -> None:
    value = _json_lines("\n".join((json.dumps({"a": 1}), json.dumps({"b": 2}))))
    assert value == [{"a": 1}, {"b": 2}]
    assert _sha256_bytes(b"x") == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
