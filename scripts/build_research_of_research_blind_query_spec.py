"""Build a research-of-research blind archive-query cell specification."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

main = import_module("services.research_of_research.blind_query_spec").main


if __name__ == "__main__":
    raise SystemExit(main())
