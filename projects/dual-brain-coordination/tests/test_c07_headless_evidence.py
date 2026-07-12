from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_c07_headless_evidence.py"
    spec = importlib.util.spec_from_file_location("verify_c07_headless_evidence_tests", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_probe_computes_real_hash_and_size(tmp_path: Path) -> None:
    module = _module()
    manifest = tmp_path / "manifest.json"
    raw = json.dumps({"workflow_id": "wf", "lanes": []}).encode()
    manifest.write_bytes(raw)

    probe = module._verify_manifest(manifest)

    assert probe["exists"] is True
    assert probe["hash_computed"] is True
    assert probe["size_computed"] is True
    assert probe["actual_sha256"] == hashlib.sha256(raw).hexdigest()
    assert probe["actual_size_bytes"] == len(raw)


def test_history_is_opened_by_exact_workflow_and_run(monkeypatch) -> None:
    module = _module()
    opened: list[tuple[str, str | None]] = []

    class FakeHandle:
        async def describe(self):
            return SimpleNamespace(
                id="wf-exact",
                run_id="run-exact",
                status=SimpleNamespace(name="COMPLETED"),
            )

        async def fetch_history(self):
            return SimpleNamespace(events=[])

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None):
            opened.append((workflow_id, run_id))
            return FakeHandle()

    class FakeClientType:
        @staticmethod
        async def connect(_address: str, **_kwargs):
            return FakeClient()

    monkeypatch.setattr(module, "Client", FakeClientType)

    snapshot = asyncio.run(module._history("temporal:7233", "wf-exact", "run-exact"))

    assert opened == [("wf-exact", "run-exact")]
    assert snapshot["workflow_id"] == "wf-exact"
    assert snapshot["run_id"] == "run-exact"


def test_immutable_only_pytest_evidence_does_not_require_mutable_drift() -> None:
    module = _module()

    assert module._mutable_pytest_reference_safe([], current_semantic=False) is True
    assert (
        module._mutable_pytest_reference_safe(
            [{"rebound_to_current_after_disclosed_drift": True, "historical_hash_matches": True}],
            current_semantic=True,
        )
        is False
    )
