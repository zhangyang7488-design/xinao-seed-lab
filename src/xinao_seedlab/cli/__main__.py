from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(
    os.environ.get("XINAO_REPO")
    or os.environ.get("XINAO_CODEX_WORKSPACE")
    or os.environ.get("XINAO_CODEX_WORKDIR")
    or Path(__file__).absolute().parents[3]
)
DEFAULT_SRC = DEFAULT_REPO / "src"
for path in (DEFAULT_REPO, DEFAULT_SRC):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from xinao_seedlab.application.seed_cortex import build_default_service


def _print_json(payload: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
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


def _json_object_or_file_arg(value: str, *, name: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {}
    if not text.startswith("{"):
        path = Path(text)
        if path.is_file():
            text = path.read_text(encoding="utf-8-sig")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(f"{name} must be a JSON object")
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
    anchor_package_root = getattr(args, "anchor_package_root", "")
    if anchor_package_root:
        argv.extend(["--anchor-package-root", anchor_package_root])
    for subagent in args.codex_subagent:
        argv.extend(["--codex-subagent", subagent])
    if getattr(args, "bind_provider_worker_pool", False):
        argv.append("--bind-provider-worker-pool")
        argv.extend(["--phase1-target-width", str(args.phase1_target_width)])
        argv.extend(["--phase1-max-parallel-workers", str(args.phase1_max_parallel_workers)])
        if getattr(args, "allow_local_stub_acceptance", False):
            argv.append("--allow-local-stub-acceptance")
        workflow_id = getattr(args, "workflow_id", "")
        workflow_run_id = getattr(args, "workflow_run_id", "")
        if workflow_id:
            argv.extend(["--workflow-id", workflow_id])
        if workflow_run_id:
            argv.extend(["--workflow-run-id", workflow_run_id])
    if args.no_write:
        argv.append("--no-write")
    if getattr(args, "full_output", False):
        argv.append("--full-output")
    return int(root_intent_loop_driver.main(argv))


def _run_sunset_333_command(command: str, *, runtime_root: Path) -> int:
    from services.agent_runtime.sunset_deprecation import build_sunset_payload, write_sunset_log

    payload = build_sunset_payload(
        module_name=command,
        replacement_cn="薄胶闭环一体已替代 333 手搓门；请用 thin-glue",
        replacement_command="xinao-seedlab thin-glue",
        overnight_evidence=str(runtime_root / "overnight" / "overnight-glue-20260708"),
    )
    write_sunset_log(runtime_root, command.replace("-", "_"), payload)
    _print_json(payload)
    return 2


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

    pre_pass = subparsers.add_parser("pre-pass-audit-loop")
    _add_common_paths(pre_pass)
    pre_pass.add_argument("--task-id", default="pre_pass_audit_loop_20260704")
    pre_pass.add_argument("--wave-id", default="pre-pass-audit-loop-wave-001")
    pre_pass.add_argument("--candidate-json", default="")
    pre_pass.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    pre_pass.add_argument("--invoked-by-temporal-activity", action="store_true")
    pre_pass.add_argument("--no-write", action="store_true")

    allocation_plan = subparsers.add_parser("allocation-plan")
    _add_common_paths(allocation_plan)
    allocation_plan.add_argument("--task-id", default="allocation_plan_20260704")
    allocation_plan.add_argument("--wave-id", default="allocation-plan-wave-001")
    allocation_plan.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    allocation_plan.add_argument("--invoked-by-temporal-activity", action="store_true")
    allocation_plan.add_argument("--no-write", action="store_true")

    external_research_strategy = subparsers.add_parser("external-research-strategy-mutation-bridge")
    _add_common_paths(external_research_strategy)
    external_research_strategy.add_argument(
        "--source-package",
        default=r"C:\Users\xx363\Desktop\外部成熟自反思进化循环_防空转查缺补漏_20260705.txt",
    )
    external_research_strategy.add_argument(
        "--wave-id",
        default="external-research-strategy-mutation-bridge-20260705",
    )
    external_research_strategy.add_argument("--no-write", action="store_true")

    light_research = subparsers.add_parser("light-research-loop")
    _add_common_paths(light_research)
    light_research.add_argument(
        "--mode",
        choices=["local_only", "external_light", "architecture_audit"],
        default="local_only",
    )
    light_research.add_argument("--wave-id", default="")
    light_research.add_argument("--objective", default="")
    light_research.add_argument("--local-query", default="")
    light_research.add_argument("--local-root", action="append", default=[])
    light_research.add_argument("--source-url", action="append", default=[])
    light_research.add_argument("--source-package", action="append", default=[])
    light_research.add_argument("--external-note", default="")
    light_research.add_argument("--max-results", type=int, default=12)
    light_research.add_argument(
        "--worker-policy",
        choices=["auto", "local_only", "cloud_allowed", "skip"],
        default="auto",
    )
    light_research.add_argument("--no-write", action="store_true")

    run_reconciler = subparsers.add_parser("333-run-reconciler")
    _add_common_paths(run_reconciler)
    run_reconciler.add_argument("--temporal-address", default="127.0.0.1:7233")
    run_reconciler.add_argument("--task-queue", default="xinao-codex-task-default")
    run_reconciler.add_argument("--workflow-type", default="TemporalCodexTaskWorkflow")
    run_reconciler.add_argument("--no-write", action="store_true")
    run_reconciler.add_argument("--no-current-index-write", action="store_true")

    durable_packet = subparsers.add_parser("durable-parallel-wave-packet")
    _add_common_paths(durable_packet)
    durable_packet.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    durable_packet.add_argument("--codex-subagent", action="append", default=[])
    durable_packet.add_argument("--no-write", action="store_true")

    source_frontier_fanin = subparsers.add_parser("source-frontier-fanin-acceptance")
    _add_common_paths(source_frontier_fanin)
    source_frontier_fanin.add_argument(
        "--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统"
    )
    source_frontier_fanin.add_argument(
        "--wave-id", default="source-frontier-fanin-acceptance-wave-block3"
    )
    source_frontier_fanin.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    source_frontier_fanin.add_argument("--no-write", action="store_true")

    total_source_episode = subparsers.add_parser("total-source-episode-entry")
    _add_common_paths(total_source_episode)
    total_source_episode.add_argument(
        "--source-package",
        default=r"C:\Users\xx363\Desktop\新系统\新系统独立并行_自由发散外部研究总稿_20260701.txt",
    )
    total_source_episode.add_argument("--wave-id", default="total-source-episode-entry-20260705")
    total_source_episode.add_argument("--submit-aaq", action="store_true")
    total_source_episode.add_argument("--no-write", action="store_true")

    source_family = subparsers.add_parser("source-family-wave-scheduler")
    _add_common_paths(source_family)
    source_family.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    source_family.add_argument("--wave-id", default="wave-block4-20260701-source-family")
    source_family.add_argument("--invoked-by-main-execution-loop-tick", action="store_true")
    source_family.add_argument("--no-write", action="store_true")

    source_family_phase5 = subparsers.add_parser("source-family-mature-thin-bind-sunset")
    _add_common_paths(source_family_phase5)
    source_family_phase5.add_argument(
        "--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统"
    )
    source_family_phase5.add_argument(
        "--wave-id", default="wave-block5-source-family-mature-thin-bind-sunset"
    )
    source_family_phase5.add_argument("--invoked-by-temporal-activity", action="store_true")
    source_family_phase5.add_argument("--no-write", action="store_true")

    source_family_adapter_smoke = subparsers.add_parser("source-family-adapter-smoke")
    _add_common_paths(source_family_adapter_smoke)
    source_family_adapter_smoke.add_argument(
        "--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统"
    )
    source_family_adapter_smoke.add_argument(
        "--wave-id", default="wave-block6-source-family-adapter-smoke"
    )
    source_family_adapter_smoke.add_argument(
        "--probe-mode", choices=["live", "synthetic"], default="live"
    )
    source_family_adapter_smoke.add_argument("--timeout-sec", type=int, default=20)
    source_family_adapter_smoke.add_argument("--no-write", action="store_true")

    source_family_thin_bind = subparsers.add_parser("source-family-smoked-candidate-thin-bind")
    _add_common_paths(source_family_thin_bind)
    source_family_thin_bind.add_argument(
        "--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统"
    )
    source_family_thin_bind.add_argument(
        "--wave-id", default="wave-block7-source-family-smoked-candidate-thin-bind"
    )
    source_family_thin_bind.add_argument("--no-write", action="store_true")

    source_family_value_eval = subparsers.add_parser("source-family-adapter-value-eval")
    _add_common_paths(source_family_value_eval)
    source_family_value_eval.add_argument(
        "--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统"
    )
    source_family_value_eval.add_argument(
        "--wave-id", default="wave-block8-source-family-adapter-value-eval"
    )
    source_family_value_eval.add_argument("--no-write", action="store_true")

    source_family_value_eval_monitor = subparsers.add_parser(
        "source-family-adapter-value-eval-temporal-monitor"
    )
    _add_common_paths(source_family_value_eval_monitor)
    source_family_value_eval_monitor.add_argument(
        "--wave-id",
        default="wave-block8-source-family-adapter-value-eval-temporal-monitor",
    )
    source_family_value_eval_monitor.add_argument("--no-write", action="store_true")

    phase0_kernel = subparsers.add_parser("phase0-reusable-kernel")
    _add_common_paths(phase0_kernel)
    phase0_kernel.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    phase0_kernel.add_argument(
        "--spec-path",
        default=r"D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md",
    )
    phase0_kernel.add_argument("--wave-id", default="wave-block5-phase0-reusable-kernel")
    phase0_kernel.add_argument("--no-write", action="store_true")

    thin_glue = subparsers.add_parser(
        "thin-glue",
        help="胶水替换+闭环一体（默认入口）",
    )
    _add_common_paths(thin_glue)
    thin_glue.add_argument("--input", default="")
    thin_glue.add_argument("--materials-dir", default="")
    thin_glue.add_argument("--no-docker", action="store_true")
    thin_glue.add_argument("--gateway-chat", action="store_true")
    thin_glue.add_argument("--no-write", action="store_true")
    thin_glue.add_argument("--temporal", action="store_true")

    thin_glue_spawn = subparsers.add_parser(
        "thin-glue-spawn",
        help="主链薄接缝：spawn thin_glue_loop 子 workflow（not_333_mainline）",
    )
    _add_common_paths(thin_glue_spawn)
    thin_glue_spawn.add_argument("--input", default="")
    thin_glue_spawn.add_argument("--no-docker", action="store_true")
    thin_glue_spawn.add_argument("--address", default="127.0.0.1:7233")

    thin_glue_mainline_orch = subparsers.add_parser(
        "thin-glue-mainline-orch",
        help="主队列 orchestrator 调 thin_glue_mainline_spawn_activity",
    )
    _add_common_paths(thin_glue_mainline_orch)
    thin_glue_mainline_orch.add_argument("--input", default="")
    thin_glue_mainline_orch.add_argument("--no-docker", action="store_true")
    thin_glue_mainline_orch.add_argument("--force", action="store_true")
    thin_glue_mainline_orch.add_argument("--address", default="127.0.0.1:7233")

    thin_bootstrap = subparsers.add_parser(
        "thin-bootstrap",
        help="已并入 thin-glue；保留兼容",
    )
    _add_common_paths(thin_bootstrap)
    thin_bootstrap.add_argument(
        "--input",
        default=str(DEFAULT_REPO / "materials" / "thin_bootstrap_input.md"),
    )
    thin_bootstrap.add_argument("--prefer-e2b", action="store_true")
    thin_bootstrap.add_argument("--no-docker", action="store_true")

    thin_provider = subparsers.add_parser("thin-provider-probe")
    _add_common_paths(thin_provider)
    thin_provider.add_argument("--base-url", default="")

    thin_glue_closure = subparsers.add_parser("thin-glue-closure")
    _add_common_paths(thin_glue_closure)
    thin_glue_closure.add_argument(
        "--input",
        default=str(DEFAULT_REPO / "materials" / "thin_bootstrap_input.md"),
    )
    thin_glue_closure.add_argument("--no-docker", action="store_true")
    thin_glue_closure.add_argument("--skip-gateway-probe", action="store_true")

    thin_glue_intake = subparsers.add_parser("thin-glue-intake")
    _add_common_paths(thin_glue_intake)
    thin_glue_intake.add_argument("--materials-dir", default="")
    thin_glue_intake.add_argument("--no-write", action="store_true")

    thin_glue_provider = subparsers.add_parser("thin-glue-provider")
    _add_common_paths(thin_glue_provider)
    thin_glue_provider.add_argument("--wave-id", default="thin-glue-provider-wave-001")
    thin_glue_provider.add_argument("--base-url", default="")
    thin_glue_provider.add_argument("--chat-smoke", action="store_true")
    thin_glue_provider.add_argument("--no-write", action="store_true")

    thin_glue_worker_pool = subparsers.add_parser(
        "thin-glue-worker-pool",
        help="L9 worker pool — Temporal child workflows 替 modular_dynamic_worker_pool",
    )
    _add_common_paths(thin_glue_worker_pool)
    thin_glue_worker_pool.add_argument("--wave-id", default="thin-glue-worker-pool-wave-001")
    thin_glue_worker_pool.add_argument("--width", type=int, default=0)
    thin_glue_worker_pool.add_argument("--temporal", action="store_true")
    thin_glue_worker_pool.add_argument("--address", default="127.0.0.1:7233")
    thin_glue_worker_pool.add_argument("--no-write", action="store_true")

    phase0_weld = subparsers.add_parser(
        "phase0-minimal-weld",
        help="Phase0 smoke: markitdown → e2b/docker → commit（not_333_mainline）",
    )
    _add_common_paths(phase0_weld)
    phase0_weld.add_argument("--input", default="")
    phase0_weld.add_argument("--no-e2b", action="store_true")
    phase0_weld.add_argument("--no-docker", action="store_true")
    phase0_weld.add_argument("--no-write", action="store_true")

    thin_glue_root_intent = subparsers.add_parser(
        "thin-glue-root-intent",
        help="L2 薄入口 tick — 读薄胶证据链（替 root_intent_loop_driver 手搓）",
    )
    _add_common_paths(thin_glue_root_intent)
    thin_glue_root_intent.add_argument("--wave-id", default="thin-glue-root-intent-tick")
    thin_glue_root_intent.add_argument("--temporal", action="store_true")
    thin_glue_root_intent.add_argument("--address", default="127.0.0.1:7233")
    thin_glue_root_intent.add_argument("--no-write", action="store_true")

    thin_glue_task_package = subparsers.add_parser(
        "thin-glue-task-package",
        help="L1 结构化任务包 — Pydantic 替 task_package_resolver 手搓",
    )
    _add_common_paths(thin_glue_task_package)
    thin_glue_task_package.add_argument("--root", default="")
    thin_glue_task_package.add_argument("--entry", default="")
    thin_glue_task_package.add_argument("--no-write", action="store_true")

    thin_glue_token_stack = subparsers.add_parser(
        "thin-glue-token-stack",
        help="L8 readback 压缩 — RTK/Caveman/fallback",
    )
    _add_common_paths(thin_glue_token_stack)
    thin_glue_token_stack.add_argument("--max-files", type=int, default=12)
    thin_glue_token_stack.add_argument("--no-write", action="store_true")

    thin_glue_status = subparsers.add_parser(
        "thin-glue-status",
        help="薄胶总清单收口 — 各层 latest 聚成一张验收证据",
    )
    _add_common_paths(thin_glue_status)
    thin_glue_status.add_argument("--no-write", action="store_true")

    closure_test = subparsers.add_parser(
        "closure-test-v1",
        help="一次性全链测试闭环（§7 架构）",
    )
    _add_common_paths(closure_test)
    closure_test.add_argument(
        "--input",
        default=str(DEFAULT_REPO / "materials" / "closure_test_input.md"),
    )
    closure_test.add_argument("--no-docker", action="store_true")
    closure_test.add_argument("--temporal", action="store_true")

    wave2_hygiene = subparsers.add_parser("wave2-mainchain-hygiene")
    _add_common_paths(wave2_hygiene)
    wave2_hygiene.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    wave2_hygiene.add_argument(
        "--planning-text",
        default=r"C:\Users\xx363\Desktop\新系统_源文本对照_整块进度规划_20260704.txt",
    )
    wave2_hygiene.add_argument("--wave-id", default="wave-block2-mainchain-hygiene")
    wave2_hygiene.add_argument("--no-write", action="store_true")

    trigger = subparsers.add_parser("default-main-loop-trigger-candidate")
    _add_common_paths(trigger)
    trigger.add_argument("--task-id", default="xinao_seed_cortex_phase0_20260701")
    trigger.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    trigger.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    trigger.add_argument("--codex-subagent", action="append", default=[])
    trigger.add_argument("--no-productivity-v2", action="store_true")
    trigger.add_argument("--bind-provider-worker-pool", action="store_true")
    trigger.add_argument("--phase1-target-width", type=int, default=0)
    trigger.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    trigger.add_argument("--allow-local-stub-acceptance", action="store_true")
    trigger.add_argument("--workflow-id", default="")
    trigger.add_argument("--workflow-run-id", default="")
    trigger.add_argument("--no-write", action="store_true")

    artifact = subparsers.add_parser("artifact-acceptance-queue")
    _add_common_paths(artifact)
    artifact.add_argument("--episode-id", required=True)
    artifact.add_argument("--candidate", action="append", default=[])
    artifact.add_argument("--candidate-json", action="append", default=[])
    artifact.add_argument("--no-write", action="store_true")

    root_driver = subparsers.add_parser("root-intent-loop-driver")
    _add_common_paths(root_driver)
    root_driver.add_argument("--anchor-package-root", default="")
    root_driver.add_argument("--wave-id", default="codex-s-root-intent-loop-driver-wave-20260703")
    root_driver.add_argument("--codex-subagent", action="append", default=[])
    root_driver.add_argument("--bind-provider-worker-pool", action="store_true")
    root_driver.add_argument("--phase1-target-width", type=int, default=0)
    root_driver.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    root_driver.add_argument("--allow-local-stub-acceptance", action="store_true")
    root_driver.add_argument("--workflow-id", default="")
    root_driver.add_argument("--workflow-run-id", default="")
    root_driver.add_argument("--no-write", action="store_true")
    root_driver.add_argument("--full-output", action="store_true")

    task_control = subparsers.add_parser("333-task-transaction-control")
    _add_common_paths(task_control)
    task_control.add_argument("--routing-verb", default="return_to_mainline")
    task_control.add_argument("--assignment-dag-node-id", default="")
    task_control.add_argument("--wave-id", default="")
    task_control.add_argument("--reason", default="")
    task_control.add_argument("--priority", type=int, default=0)
    task_control.add_argument("--control-id", default="")
    task_control.add_argument("--live-temporal-signal", action="store_true")
    task_control.add_argument("--no-write", action="store_true")

    continuity = subparsers.add_parser("333-stateful-continuity-router")
    _add_common_paths(continuity)
    continuity.add_argument("--source-file", action="append", default=[])
    continuity.add_argument("--no-write", action="store_true")

    host_gate = subparsers.add_parser("333-host-dialogue-gate-trace")
    _add_common_paths(host_gate)
    host_gate.add_argument(
        "--hooks-json", default=str(Path(r"C:\Users\xx363\.codex-seed-cortex\hooks.json"))
    )
    host_gate.add_argument("--no-write", action="store_true")

    legacy_freeze = subparsers.add_parser("333-legacy-freeze-manifest")
    _add_common_paths(legacy_freeze)
    legacy_freeze.add_argument("--source-file", action="append", default=[])
    legacy_freeze.add_argument("--no-write", action="store_true")

    control_boundary = subparsers.add_parser("333-control-vs-evidence-boundary-contract")
    _add_common_paths(control_boundary)
    control_boundary.add_argument("--source-file", action="append", default=[])
    control_boundary.add_argument("--no-write", action="store_true")

    modular_pool = subparsers.add_parser("modular-dynamic-worker-pool-phase1")
    _add_common_paths(modular_pool)
    modular_pool.add_argument("--wave-id", default="modular-dynamic-worker-pool-phase1-wave-001")
    modular_pool.add_argument("--target-width", type=int, default=0)
    modular_pool.add_argument("--no-write", action="store_true")
    modular_pool.add_argument("--record-meta-rsi", action="store_true")
    modular_pool.add_argument("--force-local-dp-draft", action="store_true")
    modular_pool.add_argument("--allow-local-stub-acceptance", action="store_true")
    modular_pool.add_argument("--max-parallel-workers", type=int, default=0)
    modular_pool.add_argument("--enforced", action="store_true")
    modular_pool.add_argument("--while-waves", type=int, default=1)
    modular_pool.add_argument("--assignment-dag-node-id", default="parallel_draft_batch_bind")
    modular_pool.add_argument("--workflow-id", default="")
    modular_pool.add_argument("--workflow-run-id", default="")
    modular_pool.add_argument("--work-package-json", default="")
    modular_pool.add_argument(
        "--chain-id",
        default="modular-dynamic-worker-pool-phase1-global-default",
    )

    direct_worker_lane = subparsers.add_parser("direct-worker-lane")
    _add_common_paths(direct_worker_lane)
    direct_worker_lane.add_argument("--wave-id", default="")
    direct_worker_lane.add_argument("--lane-id", default="")
    direct_worker_lane.add_argument(
        "--mode",
        choices=[
            "draft",
            "eval",
            "contradiction",
            "audit",
            "extraction",
            "citation_verify",
            "search",
            "provider_probe",
        ],
        default="draft",
    )
    direct_worker_lane.add_argument("--provider", choices=["auto", "qwen", "dp"], default="auto")
    direct_worker_lane.add_argument("--objective", default="")
    direct_worker_lane.add_argument("--input-text", default="")
    direct_worker_lane.add_argument("--input-file", default="")
    direct_worker_lane.add_argument("--no-write", action="store_true")

    loop_state_phase2 = subparsers.add_parser("loop-runtime-state-phase2")
    _add_common_paths(loop_state_phase2)
    loop_state_phase2.add_argument("--wave-id", default="")
    loop_state_phase2.add_argument("--target-width", type=int, default=0)
    loop_state_phase2.add_argument("--max-parallel-workers", type=int, default=12)
    loop_state_phase2.add_argument("--successor-delay-seconds", type=int, default=120)
    loop_state_phase2.add_argument("--poll-seconds", type=int, default=60)
    loop_state_phase2.add_argument("--max-waves", type=int, default=0)
    loop_state_phase2.add_argument("--loop", action="store_true")
    loop_state_phase2.add_argument("--start-background", action="store_true")
    loop_state_phase2.add_argument("--no-write", action="store_true")

    phase3_activity = subparsers.add_parser("temporal-activity-no-window-dp-worker-pool-phase3")
    _add_common_paths(phase3_activity)
    phase3_activity.add_argument("--wave-id", default="")
    phase3_activity.add_argument("--target-width", type=int, default=0)
    phase3_activity.add_argument("--max-parallel-workers", type=int, default=12)
    phase3_activity.add_argument("--workflow-id", default="")
    phase3_activity.add_argument("--workflow-run-id", default="")
    phase3_activity.add_argument("--task-queue", default="xinao-codex-task-default")
    phase3_activity.add_argument("--worker-identity", default="")
    phase3_activity.add_argument("--event-queue-self-chain", action="store_true")
    phase3_activity.add_argument("--max-event-waves-per-run", type=int, default=0)
    phase3_activity.add_argument("--event-wave-index-in-run", type=int, default=0)
    phase3_activity.add_argument("--continue-generation", type=int, default=0)
    phase3_activity.add_argument("--previous-run-id", default="")
    phase3_activity.add_argument("--no-write", action="store_true")

    phase4_scheduler = subparsers.add_parser("codex-native-provider-scheduler-phase4")
    _add_common_paths(phase4_scheduler)
    phase4_scheduler.add_argument(
        "--wave-id", default="codex-native-provider-scheduler-phase4-wave-001"
    )
    phase4_scheduler.add_argument("--skip-codex-exec-canary", action="store_true")
    phase4_scheduler.add_argument("--codex-exec-timeout-seconds", type=int, default=180)
    phase4_scheduler.add_argument("--skip-qwen-canary", action="store_true")
    phase4_scheduler.add_argument("--qwen-timeout-seconds", type=int, default=60)
    phase4_scheduler.add_argument("--no-write", action="store_true")

    args = parser.parse_args(argv)
    runtime_root = Path(args.runtime_root or args.global_runtime_root)
    repo_root = Path(args.repo_root or args.global_repo_root)
    service = build_default_service(runtime_root, repo_root=repo_root)

    if args.command in {"productivity-mode-v2-wave", "productivity-mode-v2"}:
        lanes = _json_array_arg(args.lanes_json, name="lanes-json") if args.lanes_json else None
        results = (
            _json_array_arg(args.results_json, name="results-json") if args.results_json else None
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

    if args.command == "pre-pass-audit-loop":
        payload = service.pre_pass_audit_loop(
            task_id=args.task_id,
            wave_id=args.wave_id,
            candidate_json=args.candidate_json,
            invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
            invoked_by_temporal_activity=args.invoked_by_temporal_activity,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "allocation-plan":
        payload = service.allocation_plan(
            task_id=args.task_id,
            wave_id=args.wave_id,
            invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
            invoked_by_temporal_activity=args.invoked_by_temporal_activity,
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

    if args.command == "source-frontier-fanin-acceptance":
        payload = service.source_frontier_fanin_acceptance(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "total-source-episode-entry":
        payload = service.total_source_episode_entry(
            source_package_path=args.source_package,
            wave_id=args.wave_id,
            submit_aaq=args.submit_aaq,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-wave-scheduler":
        payload = service.source_family_wave_scheduler(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            invoked_by_main_execution_loop_tick=args.invoked_by_main_execution_loop_tick,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-mature-thin-bind-sunset":
        payload = service.source_family_mature_thin_bind_sunset(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            invoked_by_temporal_activity=args.invoked_by_temporal_activity,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-adapter-smoke":
        payload = service.source_family_adapter_smoke(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            probe_mode=args.probe_mode,
            timeout_sec=args.timeout_sec,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-smoked-candidate-thin-bind":
        payload = service.source_family_smoked_candidate_thin_bind(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-adapter-value-eval":
        payload = service.source_family_adapter_value_eval(
            anchor_package_root=args.anchor_package_root,
            wave_id=args.wave_id,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "source-family-adapter-value-eval-temporal-monitor":
        payload = service.source_family_adapter_value_eval_temporal_monitor(
            wave_id=args.wave_id,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "thin-glue":
        input_path = Path(args.input) if args.input else None
        materials = Path(args.materials_dir) if args.materials_dir else None
        if args.temporal:
            from services.agent_runtime.thin_glue_worker import start_thin_glue_workflow

            payload = asyncio.run(
                start_thin_glue_workflow(
                    input_path,
                    runtime_root=runtime_root,
                    repo_root=repo_root,
                    materials_dir=materials,
                    prefer_docker=not args.no_docker,
                    invoke_gateway_chat=args.gateway_chat,
                )
            )
        else:
            from services.agent_runtime.thin_glue_loop import run_thin_glue_loop

            payload = run_thin_glue_loop(
                input_path,
                runtime_root=runtime_root,
                repo_root=repo_root,
                materials_dir=materials,
                prefer_docker=not args.no_docker,
                invoke_gateway_chat=args.gateway_chat,
                write=not args.no_write,
            )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-bootstrap":
        from services.agent_runtime.thin_glue_loop import run_thin_glue_loop

        payload = run_thin_glue_loop(
            Path(args.input),
            runtime_root=runtime_root,
            repo_root=repo_root,
            prefer_docker=not args.no_docker,
            write=True,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-provider-probe":
        from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, probe_gateway

        base_url = args.base_url or DEFAULT_BASE_URL
        payload = probe_gateway(base_url=base_url)
        _print_json(payload)
        return 0 if payload.get("ok") else 1

    if args.command == "thin-glue-closure":
        from services.agent_runtime.thin_glue_closure_runner import run_thin_glue_closure

        payload = run_thin_glue_closure(
            Path(args.input),
            runtime_root=runtime_root,
            repo_root=repo_root,
            prefer_docker=not args.no_docker,
            probe_gateway=not args.skip_gateway_probe,
        )
        _print_json(payload)
        return 0

    if args.command == "thin-glue-intake":
        from services.agent_runtime.thin_glue_intake import build_thin_glue_intake

        materials = Path(args.materials_dir) if args.materials_dir else None
        payload = build_thin_glue_intake(
            runtime_root=runtime_root,
            repo_root=repo_root,
            materials_dir=materials,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-spawn":
        from services.agent_runtime.thin_glue_mainline_spawn import spawn_thin_glue_child_workflow

        input_path = Path(args.input) if args.input else None
        payload = asyncio.run(
            spawn_thin_glue_child_workflow(
                input_path=input_path,
                runtime_root=runtime_root,
                repo_root=repo_root,
                prefer_docker=not args.no_docker,
                address=args.address,
            )
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-mainline-orch":
        from services.agent_runtime.thin_glue_mainline_orchestrator import run_mainline_orchestrator

        payload = asyncio.run(
            run_mainline_orchestrator(
                {
                    "input_path": args.input,
                    "runtime_root": str(runtime_root),
                    "repo_root": str(repo_root),
                    "prefer_docker": not args.no_docker,
                    "force": args.force,
                    "address": args.address,
                },
                address=args.address,
            )
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-provider":
        from services.agent_runtime.thin_glue_provider_scheduler import (
            run_thin_glue_provider_scheduler,
        )

        base_url = args.base_url or None
        payload = run_thin_glue_provider_scheduler(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=args.wave_id,
            invoke_chat_smoke=args.chat_smoke,
            base_url=base_url,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-status":
        from services.agent_runtime.thin_glue_status import build_thin_glue_status

        payload = build_thin_glue_status(
            runtime_root=runtime_root,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-token-stack":
        from services.agent_runtime.thin_glue_l8_token_stack import run_thin_glue_token_stack

        payload = run_thin_glue_token_stack(
            runtime_root=runtime_root,
            max_files=args.max_files,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-task-package":
        from services.agent_runtime.thin_glue_l1_task_package import resolve_thin_glue_task_package

        root = Path(args.root) if args.root else repo_root / "materials"
        payload = resolve_thin_glue_task_package(
            root,
            entry_path=args.entry or None,
            runtime_root=runtime_root,
            repo_root=repo_root,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-root-intent":
        import asyncio

        from services.agent_runtime.thin_glue_l2_root_intent import (
            run_thin_glue_root_intent_temporal,
            run_thin_glue_root_intent_tick,
        )

        if args.temporal:
            payload = asyncio.run(
                run_thin_glue_root_intent_temporal(
                    runtime_root=runtime_root,
                    repo_root=repo_root,
                    wave_id=args.wave_id,
                    address=args.address,
                    write=not args.no_write,
                )
            )
        else:
            payload = run_thin_glue_root_intent_tick(
                runtime_root=runtime_root,
                repo_root=repo_root,
                wave_id=args.wave_id,
                write=not args.no_write,
            )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "phase0-minimal-weld":
        from services.agent_runtime.phase0_minimal_weld_activity import run_phase0_minimal_weld

        input_path = Path(args.input) if args.input else None
        payload = run_phase0_minimal_weld(
            input_path,
            runtime_root=runtime_root,
            repo_root=repo_root,
            prefer_e2b=not args.no_e2b,
            prefer_docker=not args.no_docker,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "thin-glue-worker-pool":
        from services.agent_runtime.thin_glue_l9_worker_pool import run_thin_glue_worker_pool_wave

        payload = run_thin_glue_worker_pool_wave(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=args.wave_id,
            target_width=args.width,
            use_temporal=args.temporal,
            temporal_address=args.address,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "closure-test-v1":
        from services.agent_runtime.closure_test_workflow import run_closure_test

        payload = run_closure_test(
            Path(args.input),
            runtime_root=runtime_root,
            repo_root=repo_root,
            prefer_docker=not args.no_docker,
            use_temporal=args.temporal,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") else 1

    if args.command == "phase0-reusable-kernel":
        payload = service.phase0_reusable_kernel(
            anchor_package_root=args.anchor_package_root,
            spec_path=args.spec_path,
            wave_id=args.wave_id,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "wave2-mainchain-hygiene":
        payload = service.wave2_mainchain_hygiene(
            anchor_package_root=args.anchor_package_root,
            planning_text=args.planning_text,
            wave_id=args.wave_id,
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
            bind_provider_worker_pool=args.bind_provider_worker_pool,
            phase1_target_width=args.phase1_target_width,
            phase1_max_parallel_workers=args.phase1_max_parallel_workers,
            phase1_require_external_draft=not args.allow_local_stub_acceptance,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
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
        for value in args.candidate_json:
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"--candidate-json must be a JSON object: {exc}") from exc
            if not isinstance(parsed, dict):
                raise SystemExit("--candidate-json must be a JSON object")
            candidates.append(parsed)
        payload = service.artifact_acceptance_queue(
            args.episode_id,
            candidates,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "root-intent-loop-driver":
        return _run_root_intent_loop_driver(args, runtime_root=runtime_root, repo_root=repo_root)

    if args.command in {
        "333-task-transaction-control",
        "333-stateful-continuity-router",
        "333-host-dialogue-gate-trace",
        "333-legacy-freeze-manifest",
        "333-control-vs-evidence-boundary-contract",
    }:
        return _run_sunset_333_command(args.command, runtime_root=runtime_root)

    if args.command == "modular-dynamic-worker-pool-phase1":
        payload = service.modular_dynamic_worker_pool_phase1(
            wave_id=args.wave_id,
            target_width=args.target_width,
            write=not args.no_write,
            record_meta_rsi=args.record_meta_rsi,
            force_local_dp_draft=args.force_local_dp_draft,
            require_external_draft=not args.allow_local_stub_acceptance,
            max_parallel_workers=args.max_parallel_workers or None,
            runtime_enforced=args.enforced,
            while_waves=args.while_waves,
            chain_id=args.chain_id,
            assignment_dag_node_id=args.assignment_dag_node_id,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            work_package=_json_object_or_file_arg(
                args.work_package_json,
                name="work_package_json",
            ),
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "direct-worker-lane":
        from services.agent_runtime import codex_s_direct_worker_lane

        payload = codex_s_direct_worker_lane.invoke_direct_worker_lane(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=args.wave_id,
            lane_id=args.lane_id,
            mode=args.mode,
            provider=args.provider,
            objective=args.objective,
            input_text=args.input_text,
            input_file=args.input_file,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "light-research-loop":
        payload = service.light_research_loop(
            mode=args.mode,
            wave_id=args.wave_id,
            objective=args.objective,
            local_query=args.local_query,
            local_roots=args.local_root,
            source_urls=args.source_url,
            source_packages=args.source_package,
            external_note=args.external_note,
            max_results=args.max_results,
            worker_policy=args.worker_policy,
            write_runtime=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "333-run-reconciler":
        payload = service.codex_333_run_reconciler(
            temporal_address=args.temporal_address,
            task_queue=args.task_queue,
            workflow_type=args.workflow_type,
            write_runtime=not args.no_write,
            write_current_index=not args.no_current_index_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "loop-runtime-state-phase2":
        from services.agent_runtime import loop_runtime_state_supervisor_worker_pool_phase2

        if args.start_background:
            payload = loop_runtime_state_supervisor_worker_pool_phase2.start_background_consumer(
                runtime_root=runtime_root,
                repo_root=repo_root,
                poll_seconds=args.poll_seconds,
                target_width=args.target_width,
                max_parallel_workers=args.max_parallel_workers,
                successor_delay_seconds=args.successor_delay_seconds,
            )
        elif args.loop:
            payload = loop_runtime_state_supervisor_worker_pool_phase2.run_consumer_loop(
                runtime_root=runtime_root,
                repo_root=repo_root,
                poll_seconds=args.poll_seconds,
                max_waves=args.max_waves,
                target_width=args.target_width,
                max_parallel_workers=args.max_parallel_workers,
                successor_delay_seconds=args.successor_delay_seconds,
            )
        else:
            payload = loop_runtime_state_supervisor_worker_pool_phase2.run_queue_consumer_tick(
                runtime_root=runtime_root,
                repo_root=repo_root,
                wave_id=args.wave_id,
                target_width=args.target_width,
                max_parallel_workers=args.max_parallel_workers,
                successor_delay_seconds=args.successor_delay_seconds,
                write=not args.no_write,
            )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "temporal-activity-no-window-dp-worker-pool-phase3":
        from services.agent_runtime import temporal_activity_no_window_dp_worker_pool_phase3

        payload = temporal_activity_no_window_dp_worker_pool_phase3.run_activity_sequence(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=args.wave_id
            or f"{temporal_activity_no_window_dp_worker_pool_phase3.TASK_ID}-event-wave-001",
            target_width=args.target_width,
            max_parallel_workers=args.max_parallel_workers,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            task_queue=args.task_queue,
            worker_identity=args.worker_identity,
            event_queue_self_chain_enabled=args.event_queue_self_chain,
            max_event_waves_per_run=args.max_event_waves_per_run,
            event_wave_index_in_run=args.event_wave_index_in_run,
            continue_generation=args.continue_generation,
            previous_run_id=args.previous_run_id,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "codex-native-provider-scheduler-phase4":
        from services.agent_runtime import codex_native_provider_scheduler_phase4

        payload = codex_native_provider_scheduler_phase4.run_provider_scheduler(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=args.wave_id,
            invoke_codex_exec=not args.skip_codex_exec_canary,
            codex_exec_timeout_seconds=args.codex_exec_timeout_seconds,
            invoke_qwen=not args.skip_qwen_canary,
            qwen_timeout_seconds=args.qwen_timeout_seconds,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    if args.command == "external-research-strategy-mutation-bridge":
        from services.agent_runtime import external_research_strategy_mutation_bridge

        payload = external_research_strategy_mutation_bridge.run_bridge(
            runtime_root=runtime_root,
            repo_root=repo_root,
            source_package=args.source_package,
            wave_id=args.wave_id,
            write=not args.no_write,
        )
        _print_json(payload)
        return 0 if payload.get("validation", {}).get("passed") is True else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
