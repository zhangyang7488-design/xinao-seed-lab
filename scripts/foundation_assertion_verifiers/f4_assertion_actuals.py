"""Compatibility wrapper for the package-owned canonical F4 verifier."""

from __future__ import annotations

import sys as _sys
from collections.abc import Mapping as _Mapping
from pathlib import Path as _Path
from typing import Any as _Any

_REPO_ROOT = _Path(__file__).resolve().parents[2]
_XINAO_SRC = _REPO_ROOT / "xinao_discovery" / "src"
if str(_XINAO_SRC) not in _sys.path:
    _sys.path.insert(0, str(_XINAO_SRC))

from xinao.foundation.assertion_verifiers import f4_assertion_actuals as _canonical


def build_assertion_actuals_v1(request: _Mapping[str, _Any]) -> dict[str, bool]:
    """Forward to the canonical package-owned F4 verifier."""

    return _canonical.build_assertion_actuals_v1(request)


__all__ = ["build_assertion_actuals_v1"]
