"""closure_test_v1 Temporal workflow + local fallback."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.closure_test_activities import run_closure_test_pipeline
from services.agent_runtime.thin_evidence_writer import DEFAULT_RUNTIME

DEFAULT_REPO = Path(__file__).resolve().parents[2]


def run_closure_test(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    prefer_docker: bool = True,
    use_temporal: bool = False,
) -> dict[str, Any]:
    if use_temporal:
        try:
            from services.agent_runtime.closure_test_worker import start_closure_test_workflow

            return asyncio.run(
                start_closure_test_workflow(
                    input_path,
                    runtime_root=runtime_root,
                    repo_root=repo_root,
                    prefer_docker=prefer_docker,
                )
            )
        except Exception as exc:
            return {
                "validation": {"passed": False},
                "named_blocker": {"code": "TEMPORAL_UNAVAILABLE", "error": str(exc)},
                "fallback": "local",
            }
    return run_closure_test_pipeline(
        input_path,
        runtime_root=runtime_root,
        repo_root=repo_root,
        prefer_docker=prefer_docker,
        workflow_id="local",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="closure_test_v1 workflow")
    parser.add_argument("--input", default=str(DEFAULT_REPO / "materials" / "closure_test_input.md"))
    parser.add_argument("--no-docker", action="store_true")
    parser.add_argument("--temporal", action="store_true")
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"input missing: {input_path}", file=sys.stderr)
        return 2
    payload = run_closure_test(
        input_path,
        prefer_docker=not args.no_docker,
        use_temporal=args.temporal,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())