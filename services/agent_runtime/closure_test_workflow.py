"""closure_test_v1 Temporal workflow + local fallback."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from services.agent_runtime.closure_test_activities import run_closure_test_pipeline
from services.agent_runtime.thin_evidence_writer import DEFAULT_RUNTIME

DEFAULT_REPO = Path(__file__).resolve().parents[2]
TASK_QUEUE = "xinao-closure-test-v1"
WORKFLOW_NAME = "XinaoClosureTestWorkflow"


async def _run_temporal(input_path: str, *, runtime: Path, repo: Path) -> dict[str, Any]:
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import Worker

    with workflow.unsafe.imports_passed_through():
        from services.agent_runtime.closure_test_activities import run_closure_test_pipeline

    @workflow.defn(name=WORKFLOW_NAME)
    class XinaoClosureTestWorkflow:
        @workflow.run
        async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
            return await workflow.execute_activity(
                run_closure_test_activity,
                payload,
                start_to_close_timeout=timedelta(minutes=10),
            )

    async def run_closure_test_activity(payload: dict[str, Any]) -> dict[str, Any]:
        return run_closure_test_pipeline(
            Path(payload["input_path"]),
            runtime_root=Path(payload.get("runtime_root") or DEFAULT_RUNTIME),
            repo_root=Path(payload.get("repo_root") or DEFAULT_REPO),
            prefer_docker=payload.get("prefer_docker", True),
            workflow_id=payload.get("workflow_id", WORKFLOW_NAME),
        )

    client = await Client.connect("127.0.0.1:7233")
    run_id = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"closure-test-{run_id}"
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[XinaoClosureTestWorkflow],
        activities=[run_closure_test_activity],
    ):
        handle = await client.start_workflow(
            XinaoClosureTestWorkflow.run,
            {
                "input_path": input_path,
                "runtime_root": str(runtime),
                "repo_root": str(repo),
                "workflow_id": wf_id,
            },
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        return await handle.result()


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
            return asyncio.run(
                _run_temporal(str(input_path), runtime=runtime_root, repo=repo_root)
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