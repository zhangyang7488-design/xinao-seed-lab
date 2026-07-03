from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xinao_seedlab.application.seed_cortex import build_default_service


DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(__file__).resolve().parents[3]


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _json_array_arg(value: str, *, name: str) -> list[dict[str, Any]]:
    if not value.strip():
        return []
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise argparse.ArgumentTypeError(f"{name} must be a JSON array")
    if not all(isinstance(item, dict) for item in payload):
        raise argparse.ArgumentTypeError(f"{name} entries must be JSON objects")
    return payload


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--repo-root", default=None)


def _run_root_intent_loop_driver(
    args: argparse.Namespace,
    *,
    runtime_root: Path,
    repo_root: Path,
) -> int:
    from services.agent_runtime import root_intent_loop_driver

    argv = [
        "--runtime-root",
        str(runtime_root),
        "--repo-root",
        str(repo_root),
        "--wave-id",
        args.wave_id,
    ]
    for subagent in args.codex_subagent:
        argv.extend(["--codex-subagent", subagent])
    if args.no_write:
        argv.append("--no-write")
    return int(root_intent_loop_driver.main(argv))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xinao-seedlab")
    parser.add_argument("--runtime-root", dest="global_runtime_root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", dest="global_repo_root", default=str(DEFAULT_REPO))
    subparsers = parser.add_subparsers(dest="command", required=True)

    productivity_parsers = [
        subparsers.add_parser("productivity-mode-v2-wave"),
        subparsers.add_parser("productivity-mode-v2"),
    ]
    for productivity in productivity_parsers:
        _add_common_paths(productivity)
        productivity.add_argument("--task-id", required=True)
        productivity.add_argument("--wave-id", default="")
        productivity.add_argument("--objective", default="")
        productivity.add_argument("--mode-reason", default="")
        productivity.add_argument("--zh-readback", default="")
        productivity.add_argument("--lanes-json", default="")
        productivity.add_argument("--results-json", default="")
        productivity.add_argument("--no-write", action="store_true")

    durable = subparsers.add_parser("durable-continuation-reconnect")
    _add_common_paths(durable)
    durable.add_argument("--task-id", required=True)
    durable.add_argument("--workflow-id", default="")
    durable.add_argument("--wave-id", default="")
    durable.add_argument("--intent", default="")
    durable.add_argument("--worker-result-ref", default="")
    durable.add_argument("--resume-from-latest", action="store_true")
    durable.add_argument("--no-write", action="store_true")

    main_tick = subparsers.add_parser("main-execution-loop-tick")
    _add_common_paths(main_tick)
    main_tick.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    main_tick.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    main_tick.add_argument("--codex-subagent", action="append", default=[])
    main_tick.add_argument("--no-write", action="store_true")

    durable_packet = subparsers.add_parser("durable-parallel-wave-packet")
    _add_common_paths(durable_packet)
    durable_packet.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    durable_packet.add_argument("--codex-subagent", action="append", default=[])
    durable_packet.add_argument("--no-write", action="store_true")

    trigger = subparsers.add_parser("default-main-loop-trigger-candidate")
    _add_common_paths(trigger)
    trigger.add_argument("--task-id", default="xinao_seed_cortex_phase0_20260701")
    trigger.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    trigger.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    trigger.add_argument("--codex-subagent", action="append", default=[])
    trigger.add_argument("--no-productivity-v2", action="store_true")
    trigger.add_argument("--no-write", action="store_true")

    artifact = subparsers.add_parser("artifact-acceptance-queue")
    _add_common_paths(artifact)
    artifact.add_argument("--episode-id", required=True)
    artifact.add_argument("--candidate", action="append", default=[])
    artifact.add_argument("--no-write", action="store_true")

    root_driver = subparsers.add_parser("root-intent-loop-driver")
    _add_common_paths(root_driver)
    root_driver.add_argument("--wave-id", default="codex-s-root-intent-loop-driver-wave-20260703")
    root_driver.add_argument("--codex-subagent", action="append", default=[])
    root_driver.add_argument("--no-write", action="store_true")

    args = parser.parse_args(argv)
    runtime_root = Path(args.runtime_root or args.global_runtime_root)
    repo_root = Path(args.repo_root or args.global_repo_root)
    service = build_default_service(runtime_root, repo_root=repo_root)

    if args.command in {"productivity-mode-v2-wave", "productivity-mode-v2"}:
        lanes = _json_array_arg(args.lanes_json, name="lanes-json") if args.lanes_json else None
        results = (
            _json_array_arg(args.results_json, name="results-json")
            if args.results_json
            else None
        )
        payload = service.productivity_mode_v2_wave(
            task_id=args.task_id,
            wave_id=args.wave_id,
            objective=args.objective,
            mode_reason=args.mode_reason,
            zh_readback=args.zh_readback,
            lanes=lanes,
            results=results,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "durable-continuation-reconnect":
        payload = service.durable_continuation_reconnect(
            task_id=args.task_id,
            workflow_id=args.workflow_id,
            wave_id=args.wave_id,
            intent=args.intent,
            worker_result_ref=args.worker_result_ref,
            resume_from_latest=args.resume_from_latest,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "main-execution-loop-tick":
        payload = service.main_execution_loop_tick(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            codex_subagents=args.codex_subagent,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "durable-parallel-wave-packet":
        payload = service.durable_parallel_wave_packet(
            wave_id=args.wave_id,
            codex_subagents=args.codex_subagent,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "default-main-loop-trigger-candidate":
        payload = service.default_main_loop_trigger_candidate(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            task_id=args.task_id,
            codex_subagents=args.codex_subagent,
            bind_productivity_v2=not args.no_productivity_v2,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "artifact-acceptance-queue":
        candidates = [
            {
                "candidate_id": f"candidate-{index:02d}",
                "artifact_ref": value,
                "accepted_for": "next_frontier_evidence",
            }
            for index, value in enumerate(args.candidate, start=1)
        ]
        payload = service.artifact_acceptance_queue(
            args.episode_id,
            candidates,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "root-intent-loop-driver":
        return _run_root_intent_loop_driver(args, runtime_root=runtime_root, repo_root=repo_root)

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
