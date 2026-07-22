"""Public payload safety scans for the hidden-benchmark generator."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from .constants import (
    FORBIDDEN_PUBLIC_KEYS,
    H03_PROHIBITED_HINTS,
    H04_PROHIBITED_HINTS,
)


def _walk_keys(payload: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            p = f"{path}.{k}"
            if k in FORBIDDEN_PUBLIC_KEYS:
                found.append(p)
            # also catch near-synonyms by lowercased key fragments
            kl = str(k).lower()
            for banned in FORBIDDEN_PUBLIC_KEYS:
                if banned in kl and k not in FORBIDDEN_PUBLIC_KEYS:
                    found.append(p)
                    break
            found.extend(_walk_keys(v, p))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            found.extend(_walk_keys(v, f"{path}[{i}]"))
    return found


def scan_forbidden_public_keys(payload: Any) -> list[str]:
    """Return dotted paths of forbidden keys in a public payload tree."""
    return _walk_keys(payload)


def _string_leaves(payload: Any) -> list[str]:
    out: list[str] = []
    if isinstance(payload, str):
        out.append(payload)
    elif isinstance(payload, dict):
        for v in payload.values():
            out.extend(_string_leaves(v))
    elif isinstance(payload, list):
        for v in payload:
            out.extend(_string_leaves(v))
    return out


def scan_prohibited_hints(payload: Any, hints: Iterable[str]) -> list[str]:
    """Return matched prohibited hint strings found in public text leaves."""
    blob = "\n".join(_string_leaves(payload)).lower()
    hits: list[str] = []
    for hint in hints:
        if hint.lower() in blob:
            hits.append(hint)
    return hits


def scan_h03_public_hints(payload: Any) -> list[str]:
    return scan_prohibited_hints(payload, H03_PROHIBITED_HINTS)


def scan_h04_public_hints(payload: Any) -> list[str]:
    return scan_prohibited_hints(payload, H04_PROHIBITED_HINTS)


def contains_secret_material(public_payload: Any, secret: bytes) -> list[str]:
    """Detect raw/hex/base64 encodings of secret bytes in public payload text."""
    import base64

    hits: list[str] = []
    text = json.dumps(public_payload, ensure_ascii=False, sort_keys=True)
    if secret.hex() in text or secret.hex().upper() in text:
        hits.append("secret_hex")
    b64 = base64.b64encode(secret).decode("ascii")
    if b64 in text:
        hits.append("secret_b64")
    b64url = base64.urlsafe_b64encode(secret).decode("ascii").rstrip("=")
    if b64url and b64url in text:
        hits.append("secret_b64url")
    # raw bytes cannot appear in JSON text as such; also scan latin-1 escape
    try:
        raw_as_latin1 = secret.decode("latin-1")
        if len(raw_as_latin1) >= 8 and raw_as_latin1 in text:
            hits.append("secret_raw_latin1")
    except Exception:  # pragma: no cover
        pass
    return hits


_FAMILY_TOKEN_RE = re.compile(r"\bH(?:0[1-9]|1[0-4])\b", re.IGNORECASE)
_FAMILY_NAME_HINTS = (
    "weak_single_variable",
    "lag_window",
    "pure_interaction",
    "multiscale_convergence",
    "regime_switching",
    "graph_cross_object",
    "emergence_decay",
    "confounding_spurious",
    "leakage_revision",
    "pure_random_null",
    "evaluator_exploit",
    "unobserved_key",
    "non_predeclared",
    "knowledge_cutoff",
)


def scan_family_identity_leak(public_payload: Any) -> list[str]:
    blob = "\n".join(_string_leaves(public_payload)).lower()
    hits: list[str] = []
    if _FAMILY_TOKEN_RE.search(blob):
        hits.append("family_token_Hxx")
    for name in _FAMILY_NAME_HINTS:
        if name in blob:
            hits.append(name)
    return hits
