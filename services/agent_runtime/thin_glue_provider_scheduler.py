"""Thin replacement for codex_native_provider_scheduler_phase4 — LiteLLM/OmniRoute gateway."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import (
    DEFAULT_RUNTIME,
    SCHEMA_VERSION,
    SENTINEL,
    l9_chat_smoke,
    l9_probe_provider,
    now_iso,
    write_json,
)
from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL

TASK_ID = "thin_glue_provider_scheduler"
REPLACES_MODULE = "codex_native_provider_scheduler_phase4"


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_provider"
    return {
        "latest": state / "latest.json",
        "provider_evidence_dir": runtime / "provider",
        "readback": runtime / "readback" / "zh" / "thin_glue_provider_latest.md",
    }


def run_thin_glue_provider_scheduler(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path | None = None,
    wave_id: str = "thin-glue-provider-wave-001",
    invoke_chat_smoke: bool = False,
    base_url: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    del repo_root  # thin gateway does not touch repo
    runtime = Path(runtime_root)
    paths = output_paths(runtime)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    gateway_url = base_url or os.environ.get("XINAO_PROVIDER_BASE_URL", DEFAULT_BASE_URL)

    probe = l9_probe_provider(base_url=gateway_url)
    chat: dict[str, Any] = {"skipped": True}
    if invoke_chat_smoke and probe.get("ok"):
        chat = l9_chat_smoke(base_url=gateway_url)

    gateway_ok = probe.get("ok") is True
    checks = {
        "gateway_reachable": gateway_ok,
        "hand_rolled_scheduler_bypassed": True,
        "single_base_url": bool(gateway_url),
        "evidence_written": not write,
    }

    blockers: list[str] = []
    if not gateway_ok:
        blockers.append(str(probe.get("named_blocker") or "PROVIDER_GATEWAY_UNREACHABLE"))

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "wave_id": wave_id,
        "run_id": run_id,
        "status": "thin_glue_provider_ready" if gateway_ok else "thin_glue_provider_blocked",
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "gateway": {
            "base_url": gateway_url,
            "probe": probe,
            "chat_smoke": chat,
        },
        "provider_registry": {
            "status": "external_gateway",
            "providers": [
                {
                    "provider_id": "thin_glue_gateway",
                    "status": "ready" if gateway_ok else "blocked",
                    "base_url": gateway_url,
                    "adapter": "LiteLLM_or_OmniRoute",
                    "hand_rolled": False,
                }
            ],
        },
        "scheduler_decision": {
            "routed_by": "thin_glue_gateway",
            "hand_rolled_gateway_default": False,
            "model_gateway_binding": {"status": "bound" if gateway_ok else "blocked"},
        },
        "model_gateway": {
            "status": "model_gateway_ready" if gateway_ok else "model_gateway_blocked",
            "binding_id": "thin_glue_litellm_omniroute",
            "routed_by": "thin_glue_gateway",
            "default_hot_path": True,
            "hand_rolled_gateway_default": False,
        },
        "named_blockers": blockers,
        "acceptance_now_can_invoke_cn": (
            f"模型调用已改走外部网关 {gateway_url}；手搓 provider_scheduler 已旁路。"
            if gateway_ok
            else "网关未起：先 docker compose -f docker-compose.thin-glue.yml up -d"
        ),
        "validation": {
            "passed": gateway_ok,
            "checks": checks,
            "validated_at": now_iso(),
        },
        "generated_at": now_iso(),
    }

    if write:
        evidence_path = paths["provider_evidence_dir"] / f"{run_id}.json"
        write_json(evidence_path, payload)
        write_json(paths["latest"], payload)
        zh = paths["readback"]
        zh.parent.mkdir(parents=True, exist_ok=True)
        zh.write_text(
            "\n".join(
                [
                    "# Thin Glue Provider",
                    "",
                    f"- status: {payload['status']}",
                    f"- base_url: {gateway_url}",
                    f"- gateway_ok: {gateway_ok}",
                    f"- 现在能干什么：{payload['acceptance_now_can_invoke_cn']}",
                ]
            ),
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(paths["latest"]),
            "provider_evidence": str(evidence_path),
            "readback_zh": str(zh),
        }
        checks["evidence_written"] = evidence_path.is_file()
        payload["validation"]["checks"] = checks
        payload["validation"]["passed"] = gateway_ok and checks["evidence_written"]
        write_json(evidence_path, payload)
        write_json(paths["latest"], payload)

    return payload
