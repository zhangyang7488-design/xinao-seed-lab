#!/usr/bin/env python3
"""Fresh-process readback for the live tool-glue constitution."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_AUTHORITY_PATH = Path(
    r"C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt"
)
EXPECTED_CURRENT_VERSION = "v3.4"
INVARIANT_SENTINEL = "XINAO_NECESSARY_CHAIN_MATURATION_INVARIANT"
INVARIANT_HEADING = "## 4. 父级持续成熟化不变量的工程兑现与成熟实现准入"
INVARIANT_SEMANTIC_ANCHORS = (
    INVARIANT_SENTINEL,
    "bounded_probe_not_yet_maturable",
    "MATURATION_REQUIRED",
    "真实消费者调用",
    "fresh-process 发现",
    "晋升后的默认路径不得静默退化",
    "第二控制面",
)
_VERSION_PREFIX = "\u7248\u672c\uff1a"


def _normalized_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("expected SHA256 must be a 64-character hex digest")
    return normalized


def _version(text: str) -> str:
    version_lines = [line.strip() for line in text.splitlines() if line.startswith(_VERSION_PREFIX)]
    if len(version_lines) != 1:
        raise RuntimeError("fresh consumer requires exactly one constitution version line")
    return version_lines[0].removeprefix(_VERSION_PREFIX).strip()


def _verify_invariant_section(text: str) -> list[str]:
    start = text.find(INVARIANT_HEADING)
    if start < 0:
        raise RuntimeError("fresh consumer cannot find the maturation invariant section")
    next_section = text.find("\n## ", start + len(INVARIANT_HEADING))
    section = text[start:] if next_section < 0 else text[start:next_section]
    missing = [anchor for anchor in INVARIANT_SEMANTIC_ANCHORS if anchor not in section]
    if missing:
        raise RuntimeError(
            "fresh consumer maturation invariant semantics are incomplete: " + ", ".join(missing)
        )
    return list(INVARIANT_SEMANTIC_ANCHORS)


def verify_consumer(
    authority_path: Path,
    expected_sha256: str,
    *,
    expected_version: str = EXPECTED_CURRENT_VERSION,
    require_maturation_invariant: bool = True,
) -> dict[str, object]:
    authority_path = authority_path.resolve()
    expected_sha256 = _normalized_sha256(expected_sha256)
    if not authority_path.is_file():
        raise FileNotFoundError(f"authority document is missing: {authority_path}")
    raw = authority_path.read_bytes()
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise RuntimeError(
            f"fresh consumer hash mismatch: expected={expected_sha256} observed={observed_sha256}"
        )
    if not raw:
        raise RuntimeError("fresh consumer refused an empty authority document")
    text = raw.decode("utf-8-sig")
    observed_version = _version(text)
    if observed_version != expected_version:
        raise RuntimeError(
            "fresh consumer version mismatch: "
            f"expected={expected_version} observed={observed_version}"
        )
    if expected_version == EXPECTED_CURRENT_VERSION and not require_maturation_invariant:
        raise RuntimeError("v3.4 readback cannot skip the maturation invariant semantics")
    semantic_anchors = _verify_invariant_section(text) if require_maturation_invariant else []
    return {
        "schema_version": "xinao.tool_glue_constitution_consumer_readback.v1",
        "status": "VERIFIED",
        "authority_path": str(authority_path),
        "authority_sha256": observed_sha256,
        "authority_size_bytes": len(raw),
        "constitution_version": observed_version,
        "maturation_invariant_verified": require_maturation_invariant,
        "semantic_anchors": semantic_anchors,
        "completion_claim_allowed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-path", type=Path, default=DEFAULT_AUTHORITY_PATH)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-version", default=EXPECTED_CURRENT_VERSION)
    parser.add_argument(
        "--legacy-preimage-readback",
        action="store_true",
        help="verify a pre-v3.4 rollback preimage without the v3.4 invariant section",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_consumer(
            args.authority_path,
            args.expected_sha256,
            expected_version=args.expected_version,
            require_maturation_invariant=not args.legacy_preimage_readback,
        )
    except Exception as exc:
        result = {
            "schema_version": "xinao.tool_glue_constitution_consumer_readback.v1",
            "status": "FAILED",
            "error": str(exc),
            "completion_claim_allowed": False,
        }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
