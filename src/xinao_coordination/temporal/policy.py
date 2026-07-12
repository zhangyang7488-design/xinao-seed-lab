"""T9 Temporal policy — thin mount for promoted tasks only."""

from __future__ import annotations

import os

from xinao_coordination.module_config import load_module_config

POLICY_ID = "xinao.temporal.v1"
DEFAULT_QUEUE = "xinao-dualbrain-promoted-v1"
DEFAULT_NAMESPACE = "default"
DEFAULT_WORKFLOW_TYPE = "XinaoPromotedTaskWorkflowV1"


def _env_truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_falsy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in {"0", "false", "no", "off"}


def temporal_policy() -> dict[str, object]:
    config, provenance = load_module_config("temporal")
    defaults = config.get("temporal", {}) if isinstance(config.get("temporal"), dict) else {}
    enabled = _env_truthy(
        "XINAO_TEMPORAL_ENABLED", "1" if defaults.get("enabled") is True else "0"
    )
    mock_default = "1" if defaults.get("mock_mode", True) is True else "0"
    mock_mode = not _env_falsy("XINAO_TEMPORAL_MOCK", mock_default)
    live_requested = _env_truthy("XINAO_TEMPORAL_LIVE", "0")
    # Real Temporal client only when live is explicitly on and mock is explicitly off.
    live_connect = live_requested and not mock_mode
    if live_connect:
        mock_mode = False
    address = os.environ.get(
        "XINAO_TEMPORAL_ADDRESS", str(defaults.get("address") or "127.0.0.1:7233")
    ).strip()
    namespace = os.environ.get(
        "XINAO_TEMPORAL_NAMESPACE", str(defaults.get("namespace") or DEFAULT_NAMESPACE)
    ).strip()
    queue = os.environ.get(
        "XINAO_TEMPORAL_TASK_QUEUE", str(defaults.get("task_queue") or DEFAULT_QUEUE)
    ).strip()
    return {
        "policy_id": POLICY_ID,
        "enabled": enabled,
        "mock_mode": mock_mode,
        "live_connect": live_connect,
        "auto_start_on_promote": False,
        "promoted_task_only": True,
        "chat_to_temporal": False,
        "discuss_to_temporal": False,
        "temporal_owner_of_dual_brain_governance": False,
        "task_queue": queue,
        "namespace": namespace,
        "workflow_type": str(defaults.get("workflow_type") or DEFAULT_WORKFLOW_TYPE),
        "address": address,
        "config_provenance": provenance,
        "note_cn": (
            "仅显式 temporal-start-promoted；禁止 chat/discuss 自动进 Temporal；"
            "默认 XINAO_TEMPORAL_ENABLED=0；mock=1 供 canary/CI；"
            "live 需 XINAO_TEMPORAL_LIVE=1 且 XINAO_TEMPORAL_MOCK=0"
        ),
    }
