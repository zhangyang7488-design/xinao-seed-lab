"""CLI shim — delegates to services.agent_runtime.integrated_bus_runner."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.agent_runtime.integrated_bus_runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())