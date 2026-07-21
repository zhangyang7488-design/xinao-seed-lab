from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from services.agent_runtime import platform_capacity_maintenance as subject

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "infra" / "capacity" / "maintenance-policy.v1.json"


class FakeContainer:
    def __init__(self, name: str, image_id: str, labels: dict[str, str]) -> None:
        self.id = f"{name}-id"
        self.attrs = {
            "Id": self.id,
            "Image": image_id,
            "Name": f"/{name}",
            "Config": {"Labels": labels},
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
        }
        self.exec_calls: list[list[str]] = []
        self.exec_users: list[str | None] = []

    def reload(self) -> None:
        return None

    def exec_run(self, argv: list[str], **kwargs: object) -> SimpleNamespace:
        self.exec_calls.append(list(argv))
        self.exec_users.append(kwargs.get("user") if isinstance(kwargs.get("user"), str) else None)
        if argv == subject._PGBACKREST_CONFIG_HASH_COMMAND:
            expected = json.loads(POLICY.read_text(encoding="utf-8"))["postgres"][
                "expected_pgbackrest_config_sha256"
            ]
            output = f"{expected}  /etc/pgbackrest/pgbackrest.conf\n".encode()
        elif argv[-1] == "--output=json":
            output = json.dumps(
                [
                    {
                        "status": {"code": 0, "message": "ok"},
                        "backup": [{"label": "20260717-TESTF", "error": False}],
                    }
                ]
            ).encode()
        else:
            output = b"ok"
        return SimpleNamespace(exit_code=0, output=output)


class FakeContainers:
    def __init__(self, values: dict[str, FakeContainer]) -> None:
        self.values = values

    def get(self, name: str) -> FakeContainer:
        return self.values[name]


class FakeClient:
    def __init__(self, values: dict[str, FakeContainer]) -> None:
        self.containers = FakeContainers(values)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _fake_client(*, postgres_image: str | None = None) -> tuple[FakeClient, FakeContainer]:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    broker_cfg = policy["docker_control_broker"]
    postgres_cfg = policy["postgres"]
    broker = FakeContainer(
        "mowei-zhixing",
        broker_cfg["expected_image_id"],
        {
            "com.docker.compose.project": broker_cfg["compose_project"],
            "com.docker.compose.service": broker_cfg["compose_service"],
            "xinao.endpoint_owner": broker_cfg["endpoint_owner"],
        },
    )
    postgres = FakeContainer(
        "shiwu-ku",
        postgres_image or postgres_cfg["expected_image_id"],
        {
            "com.docker.compose.project": postgres_cfg["compose_project"],
            "com.docker.compose.service": postgres_cfg["compose_service"],
            "com.docker.compose.config-hash": postgres_cfg["expected_compose_config_hash"],
            "org.opencontainers.image.version": postgres_cfg["expected_image_version"],
        },
    )
    return FakeClient({"mowei-zhixing": broker, "shiwu-ku": postgres}), postgres


def _request() -> dict[str, str]:
    return {
        "schema_version": subject.REQUEST_SCHEMA,
        "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "workflow_id": "capacity-test",
        "workflow_run_id": "run-1",
    }


def test_request_rejects_model_controlled_command() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        subject.validate_request(
            {
                "schema_version": subject.REQUEST_SCHEMA,
                "policy_sha256": "0" * 64,
                "command": "docker system prune -a",
            }
        )


def test_policy_commands_are_an_exact_compiled_allowlist(tmp_path: Path) -> None:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    value["postgres"]["commands"]["backup"].append("--repo=unknown")
    path = tmp_path / "bad-policy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="argv drifted"):
        subject.load_policy(path)


def test_activity_executes_only_fixed_pgbackrest_commands_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, postgres = _fake_client()
    monkeypatch.setenv("XINAO_CAPACITY_POLICY", str(POLICY))
    monkeypatch.setenv("XINAO_RESEARCH_RUNTIME", str(tmp_path))
    monkeypatch.setattr(subject, "_docker_client", lambda: client)

    first = subject.pgbackrest_full_backup_activity(_request())
    assert first["status"] == "verified"
    assert first["explicit_delete_command_count"] == 0
    assert (
        first["postgres"]["pgbackrest_config_sha256"]
        == json.loads(POLICY.read_text(encoding="utf-8"))["postgres"][
            "expected_pgbackrest_config_sha256"
        ]
    )
    assert postgres.exec_calls == [
        subject._PGBACKREST_CONFIG_HASH_COMMAND,
        subject._EXPECTED_COMMANDS["preflight"],
        subject._EXPECTED_COMMANDS["info"],
        subject._EXPECTED_COMMANDS["backup"],
        subject._EXPECTED_COMMANDS["verify"],
        subject._EXPECTED_COMMANDS["info"],
    ]
    assert postgres.exec_users == ["postgres"] * 6
    evidence = tmp_path / subject.STATE_RELATIVE / "capacity-test" / "run-1.json"
    assert json.loads(evidence.read_text(encoding="utf-8"))["status"] == "verified"

    second = subject.pgbackrest_full_backup_activity(_request())
    assert second == first
    assert len(postgres.exec_calls) == 6


def test_pgbackrest_config_hash_drift_fails_before_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, postgres = _fake_client()
    original_exec = postgres.exec_run

    def drifted_exec(argv: list[str], **kwargs: object) -> SimpleNamespace:
        if argv == subject._PGBACKREST_CONFIG_HASH_COMMAND:
            postgres.exec_calls.append(list(argv))
            postgres.exec_users.append(
                kwargs.get("user") if isinstance(kwargs.get("user"), str) else None
            )
            return SimpleNamespace(exit_code=0, output=("0" * 64 + "  config\n").encode())
        return original_exec(argv, **kwargs)

    postgres.exec_run = drifted_exec  # type: ignore[method-assign]
    monkeypatch.setenv("XINAO_CAPACITY_POLICY", str(POLICY))
    monkeypatch.setenv("XINAO_RESEARCH_RUNTIME", str(tmp_path))
    monkeypatch.setattr(subject, "_docker_client", lambda: client)

    with pytest.raises(ValueError, match="config hash admission failed"):
        subject.pgbackrest_full_backup_activity(_request())
    assert postgres.exec_calls == [subject._PGBACKREST_CONFIG_HASH_COMMAND]


def test_identity_mismatch_fails_before_docker_exec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, postgres = _fake_client(postgres_image="sha256:" + "0" * 64)
    monkeypatch.setenv("XINAO_CAPACITY_POLICY", str(POLICY))
    monkeypatch.setenv("XINAO_RESEARCH_RUNTIME", str(tmp_path))
    monkeypatch.setattr(subject, "_docker_client", lambda: client)

    with pytest.raises(ValueError, match="identity admission failed"):
        subject.pgbackrest_full_backup_activity(_request())
    assert postgres.exec_calls == []


def test_operation_identity_cannot_rebind_to_another_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    operation = tmp_path / subject.STATE_RELATIVE / "capacity-test" / "run-1.json"
    operation.parent.mkdir(parents=True)
    operation.write_text(
        json.dumps({"status": "failed", "policy_sha256": "0" * 64}), encoding="utf-8"
    )
    client, _ = _fake_client()
    monkeypatch.setenv("XINAO_CAPACITY_POLICY", str(POLICY))
    monkeypatch.setenv("XINAO_RESEARCH_RUNTIME", str(tmp_path))
    monkeypatch.setattr(subject, "_docker_client", lambda: client)

    with pytest.raises(ValueError, match="another policy"):
        subject.pgbackrest_full_backup_activity(_request())
