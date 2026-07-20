#!/usr/bin/env python3
"""Write the canonical image-owned F4 execution contract during image build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authority-manifest-sha256", required=True)
    parser.add_argument("--authority-content-sha256", required=True)
    parser.add_argument("--data-manifest-sha256", required=True)
    parser.add_argument("--data-content-sha256", required=True)
    parser.add_argument("--dockerfile-sha256", required=True)
    parser.add_argument("--contract-writer-sha256", required=True)
    parser.add_argument("--verifier-lock-sha256", required=True)
    parser.add_argument("--python-base-image", required=True)
    parser.add_argument("--uv-base-image", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hashes = (
        args.authority_manifest_sha256,
        args.authority_content_sha256,
        args.data_manifest_sha256,
        args.data_content_sha256,
        args.dockerfile_sha256,
        args.contract_writer_sha256,
        args.verifier_lock_sha256,
    )
    if any(
        len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        for value in hashes
    ):
        raise SystemExit("all execution-contract hashes must be SHA-256 hex identities")
    core = {
        "schema_version": "xinao.f4_oci_image_execution_contract.v1",
        "authority_manifest_sha256": args.authority_manifest_sha256,
        "authority_content_sha256": args.authority_content_sha256,
        "data_manifest_sha256": args.data_manifest_sha256,
        "data_content_sha256": args.data_content_sha256,
        "dockerfile_sha256": args.dockerfile_sha256,
        "contract_writer_sha256": args.contract_writer_sha256,
        "verifier_lock_sha256": args.verifier_lock_sha256,
        "python_base_image": args.python_base_image,
        "uv_base_image": args.uv_base_image,
        "authority_retained_identity": (
            r"E:\XINAO_RESEARCH_WORKSPACES\nianhua-new-route-active"
        ),
    }
    value = {
        **core,
        "content_sha256": hashlib.sha256(_canonical_bytes(core)).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_bytes(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
