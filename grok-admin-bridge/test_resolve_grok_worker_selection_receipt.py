from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).with_name("resolve_grok_worker_selection_receipt.py")
SPEC = importlib.util.spec_from_file_location(
    "resolve_grok_worker_selection_receipt", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _selector(request: dict[str, object], *, runtime_root: Path) -> dict[str, object]:
    assert runtime_root.is_dir()
    candidate = dict(request["candidates"][0])
    receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": candidate,
    }
    receipt["decision_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return receipt


@pytest.mark.parametrize(
    ("extra_args", "expected_transport"),
    [
        ([], "direct-grok-worker-pool"),
        (
            ["--route-transport", "temporal-docker-langgraph"],
            "temporal-docker-langgraph",
        ),
    ],
)
def test_resolver_asks_stable_selector_for_exact_route_without_provider_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    expected_transport: str,
) -> None:
    supervisor_root = tmp_path / "selector"
    runtime_root = tmp_path / "runtime"
    output = tmp_path / "selection.json"
    supervisor_root.mkdir()
    runtime_root.mkdir()
    probe = {
        "capable": True,
        "resolved_root": str(supervisor_root),
        "selector_source": str(supervisor_root / "routing_policy_reader.py"),
        "selector_source_sha256": "a" * 64,
        "imported_module_source": str(supervisor_root / "routing_policy_reader.py"),
        "python_executable": sys.executable,
        "python_isolated": True,
        "dont_write_bytecode": True,
    }
    monkeypatch.setattr(
        subject, "probe_supervisor_root", lambda _root: (probe, _selector)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--supervisor-root",
            str(supervisor_root),
            "--runtime-root",
            str(runtime_root),
            "--model",
            "grok-4.5",
            "--output",
            str(output),
            *extra_args,
        ],
    )

    assert subject.main() == 0
    receipt = json.loads(output.read_text(encoding="utf-8"))
    selected = receipt["selected_candidate"]
    assert selected["transport_id"] == expected_transport
    assert "capability_binding_sha256" not in selected
    assert selected["provider_id"] == "grok_acpx_headless"
    assert selected["profile_ref"] == "grok.com.cached_profile"
    assert selected["model_id"] == "grok-4.5"
