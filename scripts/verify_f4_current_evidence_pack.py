#!/usr/bin/env python3
"""Compatibility CLI for the canonical package-owned F4 evidence verifier."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
_XINAO_SRC = _REPO_ROOT / "xinao_discovery" / "src"
if str(_XINAO_SRC) not in _sys.path:
    _sys.path.insert(0, str(_XINAO_SRC))

from xinao.foundation import f4_current_evidence_verifier as _implementation

globals().update(
    {_name: _value for _name, _value in vars(_implementation).items() if not _name.startswith("__")}
)

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
