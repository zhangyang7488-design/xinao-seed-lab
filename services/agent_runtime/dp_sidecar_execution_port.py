from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


SENTINEL = "SENTINEL:XINAO_DP_SIDECAR_EXECUTION_PORT_RUNNER_READY"
SCHEMA_VERSION = "xinao.codex_s.dp_sidecar_execution_port_runner.v1"
DEFAULT_RUNTIME_ROOT = Path("D:/XINAO_RESEARCH_RUNTIME")
VALID_MODES = (
    "draft",
    "eval",
    "contradiction",
    "extraction",
    "audit",
    "search",
    "citation_verify",
    "provider_probe",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_import_path() -> None:
    repo = _repo_root()
    src = repo / "src"
    for path in (str(src), str(repo)):
        if path not in sys.path:
            sys.path.insert(0, path)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    last_error: PermissionError | None = None
    for attempt in range(8):
        temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.{attempt}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def invoke_dp_sidecar_execution_port(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    task_id: str = "codex-s-dp-sidecar-execution-port-runner-001",
    request_id: str = "codex-s-dp-sidecar-execution-port-route-001",
    invocation_id: str = "codex-s-dp-sidecar-execution-port-invoke-001",
    episode_id: str = "seedcortex-smoke-001",
    mode: str = "provider_probe",
    objective: str = "",
    input_text: str,
    max_results: int = 5,
    write: bool = True,
) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise ValueError(f"Unsupported dp sidecar execution mode: {mode}")
    _ensure_import_path()
    from xinao_seedlab.application.seed_cortex import build_default_service
    from xinao_seedlab.adapters.local_fs import to_plain

    runtime = Path(runtime_root)
    service = build_default_service(runtime)
    provider_payload = service.invoke_dp_sidecar_execution_provider(
        task_id=task_id,
        request_id=request_id,
        invocation_id=invocation_id,
        episode_id=episode_id,
        mode=mode,
        objective=objective,
        input_text=input_text,
        max_results=max_results,
        write_runtime=write,
    )
    provider_payload = to_plain(provider_payload)
    state_root = runtime / "state" / "dp_sidecar_execution_port"
    record_path = state_root / "records" / f"{invocation_id}.json"
    latest_path = state_root / "latest.json"
    provider_ref = str(provider_payload.get("provider_invocation_ref") or "")
    provider_latest_ref = str(
        provider_payload.get("evidence_refs", {}).get("latest")
        if isinstance(provider_payload.get("evidence_refs"), dict)
        else ""
    )
    runner_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "dp_sidecar_execution_port_runner_ready",
        "adoption_state": "api_cli_verifier_ready_not_hook_enforced",
        "runtime_enforced": False,
        "trigger_installed": False,
        "default_hot_path_ready": False,
        "task_id": task_id,
        "request_id": request_id,
        "invocation_id": invocation_id,
        "episode_id": episode_id,
        "port_id": "dp_sidecar_execution_port",
        "provider_id": "legacy.deepseek_dp_sidecar",
        "mode": mode,
        "available_modes": list(VALID_MODES),
        "dp_search_is_mode_not_port_definition": True,
        "service_entrypoint": {
            "caller": "services.agent_runtime.dp_sidecar_execution_port.invoke_dp_sidecar_execution_port",
            "delegates_to": "SeedCortexService.invoke_dp_sidecar_execution_provider",
            "provider_invocation_ref": provider_ref,
            "provider_latest_ref": provider_latest_ref,
            "not_execution_controller": True,
        },
        "provider_payload_digest": _sha256_json(provider_payload),
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "dp_sidecar_execution_port": "dp_sidecar_execution_port",
            "provider_invocation_ref": provider_ref,
            "provider_latest_ref": provider_latest_ref,
            "mode": mode,
            "selected_carrier_provider_id": str(
                provider_payload.get("selected_carrier_provider_id") or ""
            ),
            "mode_dispatch_attempted": provider_payload.get("mode_dispatch_attempted") is True,
            "provider_invocation_performed": provider_payload.get("provider_invocation_performed")
            is True,
            "model_invocation_performed": provider_payload.get("model_invocation_performed")
            is True,
            "tool_invocation_performed": provider_payload.get("tool_invocation_performed")
            is True,
            "result_path": str(provider_payload.get("result_path") or ""),
            "raw_response_ref": str(provider_payload.get("raw_response_ref") or ""),
            "refs_are_not_execution_controllers": True,
        },
        "poll_refs": {
            "poll_policy": "poll_live_backend_watch_first",
            "provider_latest_ref": provider_latest_ref,
        },
        "fan_in_refs": {
            "artifact_acceptance_queue_required": True,
            "provider_fan_in_refs": provider_payload.get("fan_in_refs", {}),
        },
        "evidence_refs": {
            "record_path": str(record_path),
            "latest": str(latest_path),
            "provider_invocation_ref": provider_ref,
            "provider_latest_ref": provider_latest_ref,
        },
        "readback_refs": provider_payload.get("readback_refs", {}),
        "direct_fact_promotion_allowed": False,
        "sidecar_repo_mutation_performed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "created_at": now_iso(),
    }
    if write:
        write_json(record_path, runner_payload)
        runner_payload["artifact_sha256"] = hashlib.sha256(record_path.read_bytes()).hexdigest()
        write_json(record_path, runner_payload)
        write_json(latest_path, runner_payload)
    return runner_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--task-id", default="codex-s-dp-sidecar-execution-port-runner-001")
    parser.add_argument("--request-id", default="codex-s-dp-sidecar-execution-port-route-001")
    parser.add_argument("--invocation-id", default="codex-s-dp-sidecar-execution-port-invoke-001")
    parser.add_argument("--episode-id", default="seedcortex-smoke-001")
    parser.add_argument("--mode", choices=list(VALID_MODES), default="provider_probe")
    parser.add_argument("--objective", default="")
    parser.add_argument("--input-text", required=True)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = invoke_dp_sidecar_execution_port(
        runtime_root=args.runtime_root,
        task_id=args.task_id,
        request_id=args.request_id,
        invocation_id=args.invocation_id,
        episode_id=args.episode_id,
        mode=args.mode,
        objective=args.objective,
        input_text=args.input_text,
        max_results=args.max_results,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
