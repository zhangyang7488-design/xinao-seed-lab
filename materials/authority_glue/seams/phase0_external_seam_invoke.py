"""SUNSET — hand-roll driver removed; delegates to integrated_bus_runner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.agent_runtime.integrated_bus_runner import run_integrated_bus  # noqa: E402

PARAMS_PATH = Path(__file__).with_name("integrated_bus_params.v1.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SUNSET delegate → integrated_bus_runner")
    parser.add_argument("--input", default="")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--temporal", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    temporal = args.temporal or not args.local
    try:
        payload = run_integrated_bus(input_path, temporal=temporal, mainline_default=True)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())