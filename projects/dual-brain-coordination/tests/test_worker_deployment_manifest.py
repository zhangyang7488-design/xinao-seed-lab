from __future__ import annotations

import json
from pathlib import Path

from adapters.temporal.deployment_management import load_verified_deployment
from adapters.temporal.refresh_worker_deployment_manifest import (
    DEFAULT_MANIFEST,
    PROJECT_ROOT,
    refreshed_manifest,
)

CANONICAL_GROK_MANIFEST = DEFAULT_MANIFEST.with_name("canonical_grok_host_deployment.v1.json")


def test_worker_deployment_manifest_matches_current_worker_sources() -> None:
    current = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert current == refreshed_manifest(current, PROJECT_ROOT)
    assert current["build_id"] == current["source_digest_sha256"][:32]
    assert len(current["source_digest_sha256"]) == 64


def test_worker_deployment_manifest_refresh_is_path_stable(tmp_path: Path) -> None:
    template = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    copied = tmp_path / "project"
    for relative in template["source_hashes"]:
        destination = copied / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((PROJECT_ROOT / relative).read_bytes())
    refreshed = refreshed_manifest(template, copied)
    assert refreshed["source_hashes"] == refreshed_manifest(template, PROJECT_ROOT)["source_hashes"]


def test_canonical_grok_host_manifest_is_current_and_isolated() -> None:
    current = json.loads(CANONICAL_GROK_MANIFEST.read_text(encoding="utf-8"))
    assert current == refreshed_manifest(current, PROJECT_ROOT)
    assert current["deployment_name"] == "xinao-canonical-grok-host"
    assert current["task_queue"] == "xinao-canonical-grok-host-v1"
    assert load_verified_deployment(PROJECT_ROOT, CANONICAL_GROK_MANIFEST) == current


def test_canonical_grok_runner_uses_the_versioned_host_deployment() -> None:
    text = (PROJECT_ROOT / "scripts/run_canonical_grok_transaction.py").read_text(encoding="utf-8")
    assert "build_promoted_worker" in text
    assert "ensure_deployment_current" in text
    assert "canonical_grok_host_deployment.v1.json" in text


def test_kernel_canary_is_orthogonal_to_the_full_grok_route() -> None:
    text = (PROJECT_ROOT / "scripts/run_temporal_kernel_convergence_canary.py").read_text(encoding="utf-8")
    assert 'WORKFLOW_TYPE = "XinaoIntegratedBusWorkflow"' in text
    assert 'TASK_QUEUE = "xinao-integrated-langgraph-plugin-queue"' in text
    assert '"full_provider_route_not_claimed": True' in text
    assert '"grok_invocations": 0' in text
