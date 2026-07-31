"""ASCII-safe machine-readable JSON emission for packaged CLI stdout.

Windows redirected consumers often inherit the active ANSI codepage (cp936/GBK).
``json.dumps(..., ensure_ascii=False)`` embeds raw non-ASCII code points that
cannot be encoded by those codecs and raise ``UnicodeEncodeError`` on print.

Escaping with ``ensure_ascii=True`` keeps the wire form pure ASCII while
``json.loads`` recovers the exact original Unicode strings. Callers that decode
stdout as UTF-8 or GBK both round-trip correctly for machine-readable JSON.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def dumps_cli_json(
    payload: Any,
    *,
    sort_keys: bool = True,
    default: Any | None = None,
) -> str:
    """Serialize payload for CLI stdout as ASCII-safe JSON text."""

    kwargs: dict[str, Any] = {
        "ensure_ascii": True,
        "sort_keys": sort_keys,
        "allow_nan": False,
    }
    if default is not None:
        kwargs["default"] = default
    return json.dumps(payload, **kwargs)


def print_cli_json(
    payload: Any,
    *,
    sort_keys: bool = True,
    default: Any | None = None,
    file: TextIO | None = None,
) -> None:
    """Print machine-readable JSON to a text stream without codepage crashes."""

    print(
        dumps_cli_json(payload, sort_keys=sort_keys, default=default),
        file=file if file is not None else sys.stdout,
    )
