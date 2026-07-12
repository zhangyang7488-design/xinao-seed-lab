from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from services.agent_runtime import openhands_execution_activity as endpoint
from services.agent_runtime.integrated_bus_workflow_registry import (
    collect_openhands_worker_binding,
    collect_worker_bindings,
)
from services.agent_runtime.openhands_execution_contract import (
    BROKER_ENDPOINT_ID,
    CONTROL_NETWORK,
    IMAGE,
    NETWORK_ENDPOINT_ID,
    PER_REQUEST_NETWORK_PREFIX,
    TASK_QUEUE,
    XinaoOpenHandsExecuteWorkflowV1,
    execute_request_hash,
    validate_execute_request,
)
from temporalio.exceptions import CancelledError as TemporalCancelledError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


def request() -> dict[str, object]:
    return {
        "operation_key": "negative-boundary",
        "command": "printf XINAO_OPENHANDS_OK",
        "timeout_seconds": 30,
        "parent_operation_id": "op-test",
        "parent_workflow_id": "wf-test",
        "lane_id": "lane-test",
    }


def test_contract_rejects_model_controlled_infrastructure() -> None:
    for field, value in {
        "image": "ubuntu:latest",
        "network": "host",
        "volumes": ["/:/host"],
        "privileged": True,
    }.items():
        payload = {**request(), field: value}
        with pytest.raises(ValueError, match="unsupported execute request fields"):
            validate_execute_request(payload)


def test_request_hash_binds_identity_and_command() -> None:
    first = execute_request_hash(request())
    second = execute_request_hash({**request(), "command": "printf CHANGED"})
    assert first != second


def test_registry_separates_endpoint_from_langgraph_orchestrator() -> None:
    bindings = collect_worker_bindings()
    assert all(item.task_queue != TASK_QUEUE for item in bindings)
    endpoint_binding = collect_openhands_worker_binding()
    assert endpoint_binding.task_queue == TASK_QUEUE
    assert [item.__name__ for item in endpoint_binding.workflows] == [
        "XinaoOpenHandsExecuteWorkflowV1"
    ]
    assert [item.__name__ for item in endpoint_binding.activities] == [
        "execute_openhands_command_activity"
    ]
    assert any(item.langgraph_plugin for item in bindings)


def test_compose_gives_docker_control_only_to_execution_broker() -> None:
    import yaml

    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose["services"]
    orchestrator = services["houtai-gongren"]
    broker = services["mowei-zhixing"]
    orchestrator_volumes = [str(item) for item in orchestrator.get("volumes") or []]
    broker_volumes = [str(item) for item in broker.get("volumes") or []]
    assert all("docker.sock" not in item for item in orchestrator_volumes)
    assert "xinao_sandbox_control" not in orchestrator["networks"]
    assert any("docker.sock" in item for item in broker_volumes)
    assert broker["networks"] == ["xinao_internal", "xinao_sandbox_control"]
    assert broker["labels"]["xinao.endpoint_owner"] == BROKER_ENDPOINT_ID
    assert broker["environment"]["XINAO_OPENHANDS_BROKER_CONTAINER"] == "mowei-zhixing"
    assert "openhands_execution_worker" in " ".join(broker["command"])


def test_core_uses_hardened_pinned_container_and_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container_id = "a" * 64
    broker_id = "b" * 64
    network_id = "c" * 64
    run_kwargs: dict[str, object] = {}

    class FakeContainer:
        id = container_id

    class FakeBroker:
        id = broker_id

    class FakeNetwork:
        id = network_id

        def connect(self, broker: object, *, aliases: list[str]) -> None:
            assert broker is fake_broker
            assert aliases == ["mowei-zhixing"]

    class FakeImages:
        def get(self, image: str) -> object:
            assert image == IMAGE
            return object()

    class FakeContainers:
        def list(self, **kwargs: object) -> list[object]:
            return []

        def run(self, image: str, **kwargs: object) -> FakeContainer:
            assert image == IMAGE
            run_kwargs.update(kwargs)
            return FakeContainer()

    class FakeClient:
        images = FakeImages()
        containers = FakeContainers()

        def close(self) -> None:
            pass

    client = FakeClient()
    fake_broker = FakeBroker()
    fake_network = FakeNetwork()
    network_name = endpoint._network_name(
        execute_request_hash(request()),
        endpoint._normalize_execution_identity(request(), execute_request_hash(request()), None),
    )

    monkeypatch.setattr(endpoint, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(endpoint, "_docker_client", lambda: client)
    monkeypatch.setattr(endpoint, "_broker_container", lambda exact: fake_broker)
    monkeypatch.setattr(
        endpoint,
        "_reconcile_prior_attempts",
        lambda exact, request_hash, identity, broker: {
            "containers_scanned": 0,
            "containers_removed": 0,
            "removed_container_ids": [],
            "networks_scanned": 0,
            "networks_removed": 0,
            "removed_network_ids": [],
            "current_attempt": identity["attempt"],
        },
    )
    monkeypatch.setattr(
        endpoint,
        "_create_request_network",
        lambda exact, request_hash, identity: fake_network,
    )
    monkeypatch.setattr(
        endpoint,
        "_validate_request_network",
        lambda exact, request_hash, identity, expected_member_ids: {
            "network_id": exact.id,
            "network_name": network_name,
            "member_container_ids": sorted(expected_member_ids),
        },
    )
    monkeypatch.setattr(
        endpoint,
        "_validate_container",
        lambda exact, request_hash, identity, exact_network_name: {
            "container_id": exact.id,
            "request_hash": request_hash,
            "attempt": identity["attempt"],
            "network": exact_network_name,
        },
    )
    monkeypatch.setattr(endpoint, "_wait_for_health", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        endpoint,
        "_execute_remote",
        lambda *args, **kwargs: {
            "exit_code": 0,
            "stdout": "XINAO_OPENHANDS_OK",
            "stderr": "",
            "timeout_occurred": False,
        },
    )
    monkeypatch.setattr(
        endpoint,
        "_cleanup_exact",
        lambda exact_client, exact_id, request_hash, identity: {
            "attempted": True,
            "removed": (
                exact_client is client and exact_id == container_id and identity["attempt"] == 1
            ),
        },
    )
    monkeypatch.setattr(
        endpoint,
        "_cleanup_request_network_exact",
        lambda exact_client, exact_id, request_hash, identity, broker: {
            "attempted": True,
            "removed": (
                exact_client is client and exact_id == network_id and broker is fake_broker
            ),
        },
    )
    result = endpoint.execute_openhands_command_core(request())
    assert result["ok"] is True
    assert run_kwargs["network"] == network_name
    assert run_kwargs["network"] != CONTROL_NETWORK
    assert run_kwargs["cap_drop"] == ["ALL"]
    assert run_kwargs["security_opt"] == ["no-new-privileges:true"]
    assert run_kwargs["read_only"] is True
    assert run_kwargs["detach"] is True
    assert run_kwargs["remove"] is False
    assert "volumes" not in run_kwargs and "ports" not in run_kwargs
    evidence = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert "command" not in evidence
    assert evidence["command_sha256"]


def test_cancel_writes_evidence_and_cleans_exact_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    container_id = "b" * 64
    network_id = "c" * 64

    class FakeContainer:
        id = container_id

    class FakeBroker:
        id = "d" * 64

    class FakeNetwork:
        id = network_id

        def connect(self, broker: object, *, aliases: list[str]) -> None:
            assert isinstance(broker, FakeBroker)
            assert aliases == ["mowei-zhixing"]

    class FakeClient:
        class FakeContainers:
            def list(self, **kwargs: object) -> list[object]:
                return []

        containers = FakeContainers()

        def close(self) -> None:
            pass

    client = FakeClient()
    broker = FakeBroker()
    network = FakeNetwork()
    monkeypatch.setattr(endpoint, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(endpoint, "_docker_client", lambda: client)
    monkeypatch.setattr(endpoint, "_broker_container", lambda exact: broker)
    monkeypatch.setattr(
        endpoint,
        "_reconcile_prior_attempts",
        lambda *args, **kwargs: {
            "containers_scanned": 0,
            "containers_removed": 0,
            "removed_container_ids": [],
            "networks_scanned": 0,
            "networks_removed": 0,
            "removed_network_ids": [],
            "current_attempt": 1,
        },
    )
    monkeypatch.setattr(endpoint, "_create_request_network", lambda *args: network)
    monkeypatch.setattr(
        endpoint,
        "_validate_request_network",
        lambda exact, request_hash, identity, expected_member_ids: {
            "network_id": exact.id,
            "member_container_ids": sorted(expected_member_ids),
        },
    )
    monkeypatch.setattr(
        endpoint,
        "_start_container",
        lambda *args, **kwargs: FakeContainer(),
    )
    monkeypatch.setattr(
        endpoint,
        "_validate_container",
        lambda exact, request_hash, identity, network_name: {
            "container_id": exact.id,
            "attempt": identity["attempt"],
            "network": network_name,
        },
    )
    monkeypatch.setattr(endpoint, "_wait_for_health", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        endpoint,
        "_execute_remote",
        lambda *args, **kwargs: (_ for _ in ()).throw(TemporalCancelledError("Cancelled")),
    )
    monkeypatch.setattr(
        endpoint,
        "_cleanup_exact",
        lambda *args, **kwargs: {"attempted": True, "removed": True},
    )
    monkeypatch.setattr(
        endpoint,
        "_cleanup_request_network_exact",
        lambda *args, **kwargs: {"attempted": True, "removed": True},
    )
    with pytest.raises(TemporalCancelledError):
        endpoint.execute_openhands_command_core(request())
    path = (
        tmp_path
        / "state"
        / "openhands_execution_endpoint"
        / execute_request_hash(request())
        / "result.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["cancelled"] is True
    assert evidence["cleanup"]["removed"] is True
    assert evidence["cleanup"]["network"]["removed"] is True


def test_retry_reconciles_only_exact_prior_attempt() -> None:
    request_hash = "c" * 64
    removed: list[str] = []
    identity = {
        "workflow_id": "wf-retry",
        "workflow_run_id": "run-retry",
        "activity_id": "activity-retry",
        "activity_run_id": "activity-run-retry",
        "attempt": 2,
    }

    class PriorContainer:
        id = "d" * 64
        attrs = {
            "Config": {
                "Labels": {
                    "xinao.endpoint": "openhands-execution-v1",
                    "xinao.request_hash": request_hash,
                    "xinao.temporal.workflow_id": "wf-retry",
                    "xinao.temporal.workflow_run_id": "run-retry",
                    "xinao.temporal.activity_id": "activity-retry",
                    "xinao.temporal.activity_run_id": "activity-run-retry",
                    "xinao.temporal.attempt": "1",
                }
            }
        }

        def reload(self) -> None:
            pass

        def remove(self, *, force: bool) -> None:
            assert force is True
            removed.append(self.id)

    prior = PriorContainer()

    class FakeContainers:
        def list(self, **kwargs: object) -> list[PriorContainer]:
            assert kwargs["all"] is True
            return [prior]

        def get(self, container_id: str) -> object:
            assert container_id == prior.id
            if removed:
                raise endpoint.NotFound("gone")
            return prior

    class FakeNetworks:
        def list(self, **kwargs: object) -> list[object]:
            return []

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    broker = type("Broker", (), {"id": "b" * 64})()
    result = endpoint._reconcile_prior_attempts(FakeClient(), request_hash, identity, broker)
    assert result["containers_removed"] == 1
    assert result["removed_container_ids"] == [prior.id]


def test_retry_reconciliation_rejects_identity_mismatch_without_removal() -> None:
    request_hash = "e" * 64
    removed = False
    identity = {
        "workflow_id": "wf-current",
        "workflow_run_id": "run-current",
        "activity_id": "activity-current",
        "activity_run_id": "activity-run-current",
        "attempt": 2,
    }

    class ForeignContainer:
        id = "f" * 64
        attrs = {
            "Config": {
                "Labels": {
                    "xinao.endpoint": "openhands-execution-v1",
                    "xinao.request_hash": request_hash,
                    "xinao.temporal.workflow_id": "wf-foreign",
                    "xinao.temporal.workflow_run_id": "run-foreign",
                    "xinao.temporal.activity_id": "activity-foreign",
                    "xinao.temporal.activity_run_id": "activity-run-foreign",
                    "xinao.temporal.attempt": "1",
                }
            }
        }

        def reload(self) -> None:
            pass

        def remove(self, *, force: bool) -> None:
            nonlocal removed
            removed = True

    class FakeContainers:
        def list(self, **kwargs: object) -> list[ForeignContainer]:
            return [ForeignContainer()]

    class FakeNetworks:
        def list(self, **kwargs: object) -> list[object]:
            return []

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    with pytest.raises(RuntimeError, match="identity mismatch"):
        endpoint._reconcile_prior_attempts(
            FakeClient(), request_hash, identity, type("Broker", (), {"id": "b" * 64})()
        )
    assert removed is False


def test_request_network_is_internal_labeled_and_attempt_scoped() -> None:
    request_hash = "1" * 64
    identity = {
        "workflow_id": "wf-network",
        "workflow_run_id": "run-network",
        "activity_id": "activity-network",
        "activity_run_id": "activity-run-network",
        "attempt": 2,
    }
    create_args: dict[str, object] = {}

    class FakeNetwork:
        id = "2" * 64

    class FakeNetworks:
        def create(self, name: str, **kwargs: object) -> FakeNetwork:
            create_args["name"] = name
            create_args.update(kwargs)
            return FakeNetwork()

    class FakeClient:
        networks = FakeNetworks()

    network = endpoint._create_request_network(FakeClient(), request_hash, identity)
    assert network.id == "2" * 64
    assert str(create_args["name"]).startswith(f"{PER_REQUEST_NETWORK_PREFIX}_")
    assert create_args["driver"] == "bridge"
    assert create_args["internal"] is True
    assert create_args["attachable"] is False
    labels = create_args["labels"]
    assert isinstance(labels, dict)
    assert labels["xinao.endpoint"] == NETWORK_ENDPOINT_ID
    assert labels["xinao.request_hash"] == request_hash
    assert labels["xinao.temporal.attempt"] == "2"


def test_request_network_admission_requires_exact_members() -> None:
    request_hash = "3" * 64
    identity = {
        "workflow_id": "wf-network",
        "workflow_run_id": "run-network",
        "activity_id": "activity-network",
        "activity_run_id": "activity-run-network",
        "attempt": 1,
    }
    network_name = endpoint._network_name(request_hash, identity)

    class FakeNetwork:
        id = "4" * 64
        attrs = {
            "Name": network_name,
            "Driver": "bridge",
            "Internal": True,
            "Labels": endpoint._network_labels(request_hash, identity),
            "Containers": {"5" * 64: {}, "6" * 64: {}},
        }

        def reload(self) -> None:
            pass

    result = endpoint._validate_request_network(
        FakeNetwork(),
        request_hash,
        identity,
        expected_member_ids={"5" * 64, "6" * 64},
    )
    assert result["internal"] is True
    assert result["member_container_ids"] == ["5" * 64, "6" * 64]
    with pytest.raises(RuntimeError, match="network_members"):
        endpoint._validate_request_network(
            FakeNetwork(),
            request_hash,
            identity,
            expected_member_ids={"5" * 64},
        )


def test_retry_reconciles_exact_prior_network_after_container() -> None:
    request_hash = "7" * 64
    broker = type("Broker", (), {"id": "8" * 64})()
    identity = {
        "workflow_id": "wf-network",
        "workflow_run_id": "run-network",
        "activity_id": "activity-network",
        "activity_run_id": "activity-run-network",
        "attempt": 2,
    }
    removed = False
    disconnected = False

    class PriorNetwork:
        id = "9" * 64
        attrs = {
            "Labels": {
                **endpoint._network_labels(request_hash, identity),
                "xinao.temporal.attempt": "1",
            },
            "Containers": {broker.id: {}},
        }

        def reload(self) -> None:
            pass

        def disconnect(self, exact: object, *, force: bool) -> None:
            nonlocal disconnected
            assert exact is broker and force is True
            disconnected = True

        def remove(self) -> None:
            nonlocal removed
            assert disconnected is True
            removed = True

    prior = PriorNetwork()

    class FakeContainers:
        def list(self, **kwargs: object) -> list[object]:
            return []

    class FakeNetworks:
        def list(self, **kwargs: object) -> list[PriorNetwork]:
            return [prior]

        def get(self, network_id: str) -> PriorNetwork:
            assert network_id == prior.id
            if removed:
                raise endpoint.NotFound("gone")
            return prior

    class FakeClient:
        containers = FakeContainers()
        networks = FakeNetworks()

    result = endpoint._reconcile_prior_attempts(FakeClient(), request_hash, identity, broker)
    assert result["networks_removed"] == 1
    assert result["removed_network_ids"] == [prior.id]
    assert disconnected is True and removed is True


def test_network_cleanup_refuses_unexpected_member_without_disconnect() -> None:
    request_hash = "a" * 64
    identity = {
        "workflow_id": "wf-cleanup",
        "workflow_run_id": "run-cleanup",
        "activity_id": "activity-cleanup",
        "activity_run_id": "activity-run-cleanup",
        "attempt": 1,
    }
    broker = type("Broker", (), {"id": "b" * 64})()
    disconnected = False
    removed = False

    class FakeNetwork:
        id = "c" * 64
        attrs = {
            "Labels": endpoint._network_labels(request_hash, identity),
            "Containers": {broker.id: {}, "d" * 64: {}},
        }

        def reload(self) -> None:
            pass

        def disconnect(self, exact: object, *, force: bool) -> None:
            nonlocal disconnected
            disconnected = True

        def remove(self) -> None:
            nonlocal removed
            removed = True

    class FakeNetworks:
        def get(self, network_id: str) -> FakeNetwork:
            assert network_id == FakeNetwork.id
            return FakeNetwork()

    class FakeClient:
        networks = FakeNetworks()

    result = endpoint._cleanup_request_network_exact(
        FakeClient(), FakeNetwork.id, request_hash, identity, broker
    )
    assert result["removed"] is False
    assert result["unexpected_member_ids"] == ["d" * 64]
    assert disconnected is False and removed is False


def test_temporal_retries_caught_infrastructure_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []

    def fake_core(
        payload: dict[str, object],
        *,
        execution_identity: dict[str, object],
    ) -> dict[str, object]:
        attempt = int(execution_identity["attempt"])
        attempts.append(attempt)
        if attempt == 1:
            return {
                "request_hash": execute_request_hash(payload),
                "ok": False,
                "error_type": "DockerException",
                "error_message": "transient Docker transport failure",
                "cleanup": {"removed": True},
            }
        return {
            "request_hash": execute_request_hash(payload),
            "ok": True,
            "exit_code": 0,
            "stdout": "XINAO_RETRY_OK",
            "stderr": "",
            "timeout_occurred": False,
            "error_type": "",
            "error_message": "",
            "cleanup": {"removed": True},
            "evidence_path": "/evidence/fake/result.json",
            "attempt_evidence_path": "/evidence/fake/attempt-002.json",
            "elapsed_ms": 1,
        }

    monkeypatch.setattr(endpoint, "execute_openhands_command_core", fake_core)

    async def run() -> dict[str, object]:
        task_queue = f"openhands-retry-test-{uuid.uuid4().hex}"
        workflow_id = f"openhands-retry-wf-{uuid.uuid4().hex}"
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[XinaoOpenHandsExecuteWorkflowV1],
                    activities=[endpoint.execute_openhands_command_activity],
                    activity_executor=executor,
                ):
                    return await env.client.execute_workflow(
                        XinaoOpenHandsExecuteWorkflowV1.run,
                        {**request(), "operation_key": "retry-infra"},
                        id=workflow_id,
                        task_queue=task_queue,
                    )

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["stdout"] == "XINAO_RETRY_OK"
    assert attempts == [1, 2]
