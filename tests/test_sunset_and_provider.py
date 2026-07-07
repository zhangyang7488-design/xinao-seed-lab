from __future__ import annotations

from services.agent_runtime.sunset_deprecation import build_sunset_payload
from services.agent_runtime.thin_provider_client import probe_gateway


def test_build_sunset_payload_shape() -> None:
    payload = build_sunset_payload(
        module_name="333-host-dialogue-gate-trace",
        replacement_cn="thin-bootstrap",
        replacement_command="xinao-seedlab thin-bootstrap",
    )
    assert payload["status"] == "sunset_deprecated"
    assert payload["named_blocker"] == "MODULE_SUNSET_USE_THIN_GLUE_PATH"


def test_probe_gateway_unreachable() -> None:
    payload = probe_gateway(base_url="http://127.0.0.1:59999/v1", timeout_s=0.5)
    assert payload["ok"] is False