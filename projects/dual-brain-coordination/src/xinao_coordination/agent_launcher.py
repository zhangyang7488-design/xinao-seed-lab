"""Short-lived bootstrap that provisions transport and starts one operation worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_controller import AgentOperationController
from .errors import CoordinationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = AgentOperationController(args.db).start(args.operation_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CoordinationError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False))
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "agent_launcher_failed",
                    "exception_type": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
