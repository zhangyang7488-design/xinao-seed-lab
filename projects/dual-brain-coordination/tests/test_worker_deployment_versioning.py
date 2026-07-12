from __future__ import annotations

import pytest
from temporalio.common import VersioningBehavior
from temporalio.workflow import _Definition as WorkflowDefinition

from adapters.temporal.worker_runtime import (
    DEFAULT_DEPLOYMENT_NAME,
    WorkerRuntimeConfig,
    build_worker_deployment_config,
)
from xinao_coordination.temporal.workflow import XinaoPromotedTaskWorkflowV1


@pytest.fixture(autouse=True)
def _clean_versioning_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "XINAO_TEMPORAL_WORKER_VERSIONING",
        "XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME",
        "XINAO_TEMPORAL_WORKER_BUILD_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_unversioned_config_remains_available_for_replay_and_isolated_tests() -> None:
    cfg = WorkerRuntimeConfig.from_env()
    assert cfg.use_worker_versioning is False
    assert cfg.worker_build_id == ""
    assert build_worker_deployment_config(cfg) is None


def test_versioned_config_uses_official_worker_deployment_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_WORKER_VERSIONING", "1")
    monkeypatch.setenv("XINAO_TEMPORAL_WORKER_BUILD_ID", "build-0123456789abcdef")
    cfg = WorkerRuntimeConfig.from_env()
    deployment = build_worker_deployment_config(cfg)
    assert deployment is not None
    assert deployment.use_worker_versioning is True
    assert deployment.version.deployment_name == DEFAULT_DEPLOYMENT_NAME
    assert deployment.version.build_id == "build-0123456789abcdef"
    assert deployment.default_versioning_behavior is VersioningBehavior.PINNED


@pytest.mark.parametrize(
    ("flag", "build_id", "error"),
    [
        ("1", "", "XINAO_TEMPORAL_WORKER_VERSIONING_IDENTITY_REQUIRED"),
        ("0", "unexpected-build", "XINAO_TEMPORAL_WORKER_VERSIONING_FLAG_REQUIRED"),
        ("sometimes", "", "XINAO_TEMPORAL_WORKER_VERSIONING_INVALID"),
    ],
)
def test_versioning_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
    build_id: str,
    error: str,
) -> None:
    monkeypatch.setenv("XINAO_TEMPORAL_WORKER_VERSIONING", flag)
    if build_id:
        monkeypatch.setenv("XINAO_TEMPORAL_WORKER_BUILD_ID", build_id)
    with pytest.raises(RuntimeError, match=error):
        WorkerRuntimeConfig.from_env()


def test_promoted_workflow_is_pinned() -> None:
    definition = WorkflowDefinition.from_class(XinaoPromotedTaskWorkflowV1)
    assert definition.versioning_behavior is VersioningBehavior.PINNED
