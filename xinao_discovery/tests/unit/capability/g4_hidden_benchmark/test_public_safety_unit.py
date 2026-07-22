"""Unit tests for public-safety scanners."""

from __future__ import annotations

from xinao.capability.g4_hidden_benchmark.public_safety import (
    contains_secret_material,
    scan_family_identity_leak,
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)


def test_forbidden_keys_detected() -> None:
    payload = {"ok": True, "nested": {"truth": 1, "vault_path": "/x"}}
    hits = scan_forbidden_public_keys(payload)
    assert any(h.endswith(".truth") for h in hits)
    assert any("vault_path" in h for h in hits)


def test_h03_h04_hint_scanners() -> None:
    assert scan_h03_public_hints({"ask": "find the XOR rule"}) == ["xor"]
    assert scan_h03_public_hints({"ask": "find a compact rule"}) == []
    assert scan_h04_public_hints({"ask": "measure phase overlap"}) == ["phase", "overlap"]
    assert scan_h04_public_hints({"ask": "two periodic components"}) == [
        "periodic",
        "component",
    ]


def test_secret_material_scan() -> None:
    secret = b"S" * 32 + b"unique-secret-blob"
    payload = {"note": secret.hex()}
    assert "secret_hex" in contains_secret_material(payload, secret)


def test_family_identity_leak_scan() -> None:
    assert "family_token_Hxx" in scan_family_identity_leak({"x": "case H03 ready"})
    assert scan_family_identity_leak({"x": "opaque pc_ab12"}) == []
