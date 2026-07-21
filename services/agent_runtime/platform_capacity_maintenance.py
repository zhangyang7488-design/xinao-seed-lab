"""Deterministic Temporal maintenance for the local PostgreSQL capacity path.

Temporal owns time and retry semantics.  This module exposes one fixed
pgBackRest operation through the already-authorized Docker control broker; it
does not accept a command, path, container name, image or deletion request from
workflow input.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

POLICY_SCHEMA = "xinao.platform_capacity_policy.v1"
REQUEST_SCHEMA = "xinao.platform_capacity_maintenance_request.v1"
RESULT_SCHEMA = "xinao.platform_capacity_maintenance_result.v1"
WORKFLOW_NAME = "XinaoPlatformCapacityMaintenanceWorkflowV1"
ACTIVITY_NAME = "xinao.platform_capacity.pgbackrest_full_backup"
TASK_QUEUE = "xinao-platform-maintenance-v1"
DEFAULT_POLICY_PATH = "/app/infra/capacity/maintenance-policy.v1.json"
STATE_RELATIVE = Path("state") / "platform_capacity_maintenance"
MAX_OUTPUT_BYTES = 131_072

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_EXPECTED_COMMANDS = {
    "preflight": ["pgbackrest", "--stanza=xinao-core", "check"],
    "backup": ["pgbackrest", "--stanza=xinao-core", "backup", "--type=full"],
    "verify": ["pgbackrest", "--stanza=xinao-core", "verify"],
    "info": ["pgbackrest", "--stanza=xinao-core", "info", "--output=json"],
}
_PGBACKREST_CONFIG_HASH_COMMAND = [
    "sha256sum",
    "/etc/pgbackrest/pgbackrest.conf",
]


def validate_request(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise TypeError("capacity maintenance request must be an object")
    unknown = sorted(set(payload) - {"schema_version", "policy_sha256"})
    if unknown:
        raise ValueError(f"unsupported capacity maintenance request fields: {unknown}")
    if str(payload.get("schema_version") or "") != REQUEST_SCHEMA:
        raise ValueError("unsupported capacity maintenance request schema")
    policy_sha256 = str(payload.get("policy_sha256") or "").lower()
    if not _SHA256.fullmatch(policy_sha256):
        raise ValueError("policy_sha256 must be a lowercase SHA-256")
    return {"schema_version": REQUEST_SCHEMA, "policy_sha256": policy_sha256}


def _validate_policy(policy: object) -> dict[str, Any]:
    if not isinstance(policy, dict) or policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("capacity policy schema is invalid")
    postgres = policy.get("postgres")
    broker = policy.get("docker_control_broker")
    temporal = policy.get("temporal")
    if not all(isinstance(item, dict) for item in (postgres, broker, temporal)):
        raise ValueError("capacity policy is missing required sections")
    if postgres.get("commands") != _EXPECTED_COMMANDS:
        raise ValueError("capacity policy pgBackRest argv drifted")
    if postgres.get("container_name") != "shiwu-ku":
        raise ValueError("capacity policy PostgreSQL target drifted")
    if postgres.get("exec_os_user") != "postgres":
        raise ValueError("capacity policy pgBackRest OS user drifted")
    if not _SHA256.fullmatch(str(postgres.get("expected_pgbackrest_config_sha256") or "")):
        raise ValueError("capacity policy pgBackRest config hash is invalid")
    if broker.get("container_name") != "mowei-zhixing":
        raise ValueError("capacity policy Docker control owner drifted")
    if temporal.get("task_queue") != TASK_QUEUE or temporal.get("workflow_type") != WORKFLOW_NAME:
        raise ValueError("capacity policy Temporal binding drifted")
    if temporal.get("overlap_policy") != "SKIP" or temporal.get("pause_on_failure") is not True:
        raise ValueError("capacity policy retry/overlap safety drifted")
    if policy.get("policy_is_not_authorization") is not True:
        raise ValueError("capacity policy must not create task authorization")
    automatic = set(policy.get("enforced_automatic_actions") or [])
    required = {
        "pgbackrest_check",
        "pgbackrest_info_observation",
        "pgbackrest_full_backup",
        "pgbackrest_verify",
        "pgbackrest_catalog_expire_after_successful_backup",
    }
    if automatic != required:
        raise ValueError("capacity automatic action allowlist drifted")
    return policy


def load_policy(path: Path | None = None) -> tuple[dict[str, Any], str]:
    policy_path = path or Path(os.environ.get("XINAO_CAPACITY_POLICY", DEFAULT_POLICY_PATH))
    raw = policy_path.read_bytes()
    policy_hash = hashlib.sha256(raw).hexdigest()
    policy = _validate_policy(json.loads(raw.decode("utf-8")))
    return policy, policy_hash


def _docker_client() -> Any:
    import docker

    return docker.from_env()


def _safe(value: str, *, limit: int = 96) -> str:
    return (_SAFE.sub("-", value).strip("-.") or "unknown")[:limit]


def _bounded(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    return raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")


def _container_identity(
    container: Any, expected: Mapping[str, Any], *, role: str
) -> dict[str, Any]:
    container.reload()
    attrs = container.attrs
    labels = {str(k): str(v) for k, v in ((attrs.get("Config") or {}).get("Labels") or {}).items()}
    state = attrs.get("State") or {}
    health = (state.get("Health") or {}).get("Status")
    image_id = str(attrs.get("Image") or getattr(getattr(container, "image", None), "id", ""))
    failures: list[str] = []
    if labels.get("com.docker.compose.project") != expected.get("compose_project"):
        failures.append("compose_project")
    if labels.get("com.docker.compose.service") != expected.get("compose_service"):
        failures.append("compose_service")
    config_hash = expected.get("expected_compose_config_hash")
    if config_hash and labels.get("com.docker.compose.config-hash") != config_hash:
        failures.append("compose_config_hash")
    if image_id != expected.get("expected_image_id"):
        failures.append("image_id")
    if state.get("Status") != "running":
        failures.append("running")
    if health not in (None, "healthy"):
        failures.append("health")
    owner = expected.get("endpoint_owner")
    if owner and labels.get("xinao.endpoint_owner") != owner:
        failures.append("endpoint_owner")
    version = expected.get("expected_image_version")
    if version and labels.get("org.opencontainers.image.version") != version:
        failures.append("image_version")
    if failures:
        raise ValueError(f"{role} identity admission failed: {failures}")
    return {
        "container_id": str(attrs.get("Id") or getattr(container, "id", "")),
        "container_name": str(attrs.get("Name") or "").lstrip("/"),
        "image_id": image_id,
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "health": health,
    }


def _exec_exact(container: Any, *, step: str, argv: list[str]) -> dict[str, Any]:
    if argv != _EXPECTED_COMMANDS[step]:
        raise ValueError(f"{step} argv is not the compiled allowlist")
    result = container.exec_run(argv, stdout=True, stderr=True, user="postgres")
    if hasattr(result, "exit_code"):
        exit_code = int(result.exit_code)
        output = result.output
    else:
        exit_code = int(result[0])
        output = result[1]
    text = _bounded(output)
    if exit_code != 0:
        raise RuntimeError(f"pgBackRest {step} failed with exit {exit_code}: {text}")
    try:
        activity.heartbeat({"step": step, "exit_code": exit_code})
    except RuntimeError:
        pass
    return {
        "step": step,
        "argv": argv,
        "exec_os_user": "postgres",
        "exit_code": exit_code,
        "output": text,
    }


def _verify_pgbackrest_config(container: Any, expected_sha256: str) -> str:
    result = container.exec_run(
        list(_PGBACKREST_CONFIG_HASH_COMMAND),
        stdout=True,
        stderr=True,
        user="postgres",
    )
    if hasattr(result, "exit_code"):
        exit_code = int(result.exit_code)
        output = result.output
    else:
        exit_code = int(result[0])
        output = result[1]
    text = _bounded(output)
    observed = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    if exit_code != 0 or observed != expected_sha256:
        raise ValueError("PostgreSQL pgBackRest config hash admission failed")
    return observed


def _parse_pgbackrest_info(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    value = json.loads(text)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise RuntimeError("pgBackRest info did not report exactly one stanza")
    stanza = value[0]
    if stanza.get("status", {}).get("code") != 0:
        raise RuntimeError("pgBackRest stanza status is not healthy")
    backups = stanza.get("backup") or []
    if not isinstance(backups, list):
        raise RuntimeError("pgBackRest backup catalog is invalid")
    return stanza, backups


def _activity_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        info = activity.info()
        return {
            "workflow_id": info.workflow_id,
            "workflow_run_id": info.workflow_run_id,
            "activity_id": info.activity_id,
            "attempt": info.attempt,
        }
    except RuntimeError:
        return {
            "workflow_id": str(payload.get("workflow_id") or "direct"),
            "workflow_run_id": str(payload.get("workflow_run_id") or "direct"),
            "activity_id": ACTIVITY_NAME,
            "attempt": 1,
        }


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


@activity.defn(name=ACTIVITY_NAME)
def pgbackrest_full_backup_activity(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"schema_version", "policy_sha256", "workflow_id", "workflow_run_id"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise TypeError("capacity Activity payload is invalid")
    request = validate_request(
        {
            "schema_version": payload.get("schema_version"),
            "policy_sha256": payload.get("policy_sha256"),
        }
    )
    policy, actual_hash = load_policy()
    if actual_hash != request["policy_sha256"]:
        raise ValueError("capacity policy hash drifted after Schedule admission")

    identity = _activity_identity(payload)
    runtime_root = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", "/evidence"))
    operation_dir = runtime_root / STATE_RELATIVE / _safe(identity["workflow_id"])
    operation_path = operation_dir / f"{_safe(identity['workflow_run_id'])}.json"
    prior: dict[str, Any] = {}
    if operation_path.is_file():
        prior = json.loads(operation_path.read_text(encoding="utf-8"))
        if prior.get("policy_sha256") != actual_hash:
            raise ValueError("operation identity is already bound to another policy")
        if prior.get("status") == "verified" and prior.get("policy_sha256") == actual_hash:
            return prior

    client = _docker_client()
    started_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "status": "running",
        "policy_sha256": actual_hash,
        "identity": identity,
        "started_at_utc": started_at.isoformat(),
        "explicit_delete_command_count": 0,
    }
    try:
        broker_cfg = policy["docker_control_broker"]
        postgres_cfg = policy["postgres"]
        broker = client.containers.get(broker_cfg["container_name"])
        postgres = client.containers.get(postgres_cfg["container_name"])
        result["docker_control_broker"] = _container_identity(
            broker, broker_cfg, role="Docker control broker"
        )
        result["postgres"] = _container_identity(postgres, postgres_cfg, role="PostgreSQL")
        result["postgres"]["pgbackrest_config_sha256"] = _verify_pgbackrest_config(
            postgres,
            str(postgres_cfg["expected_pgbackrest_config_sha256"]),
        )
        steps = [
            _exec_exact(
                postgres, step="preflight", argv=list(postgres_cfg["commands"]["preflight"])
            ),
            _exec_exact(postgres, step="info", argv=list(postgres_cfg["commands"]["info"])),
        ]
        _, observed_before = _parse_pgbackrest_info(steps[-1]["output"])
        current_labels = [str(item.get("label") or "") for item in observed_before]
        baseline_labels = prior.get("backup_labels_before")
        if not isinstance(baseline_labels, list):
            baseline_labels = current_labels
            result["backup_labels_before"] = baseline_labels
            result["identity_admitted_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_json_atomic(operation_path, result)
        else:
            baseline_labels = [str(item) for item in baseline_labels]
            result["backup_labels_before"] = baseline_labels
        new_labels = sorted(set(current_labels) - set(baseline_labels))
        if new_labels:
            steps.append(
                {
                    "step": "backup",
                    "argv": list(postgres_cfg["commands"]["backup"]),
                    "exec_os_user": "postgres",
                    "exit_code": 0,
                    "skipped": True,
                    "reason": "a healthy new full already appeared after this operation was admitted",
                    "detected_labels": new_labels,
                }
            )
        else:
            steps.append(
                _exec_exact(postgres, step="backup", argv=list(postgres_cfg["commands"]["backup"]))
            )
        steps.append(
            _exec_exact(postgres, step="verify", argv=list(postgres_cfg["commands"]["verify"]))
        )
        steps.append(
            _exec_exact(postgres, step="info", argv=list(postgres_cfg["commands"]["info"]))
        )
        stanza, backups = _parse_pgbackrest_info(steps[-1]["output"])
        if not backups or backups[-1].get("error") is not False:
            raise RuntimeError("pgBackRest did not report a healthy newest backup")
        result.update(
            {
                "status": "verified",
                "steps": steps,
                "newest_backup_label": backups[-1].get("label"),
                "backup_count_after": len(backups),
                "backup_labels_after": [str(item.get("label") or "") for item in backups],
                "catalog_labels_expired": sorted(
                    set(baseline_labels) - {str(item.get("label") or "") for item in backups}
                ),
                "repo_status_code": stanza.get("status", {}).get("code"),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "duration_ms": int(
                    (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
                ),
            }
        )
        _write_json_atomic(operation_path, result)
        _write_json_atomic(runtime_root / STATE_RELATIVE / "latest.json", result)
        return result
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc)[:4096],
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_json_atomic(operation_path, result)
        _write_json_atomic(runtime_root / STATE_RELATIVE / "latest.json", result)
        raise
    finally:
        try:
            client.close()
        except Exception:
            pass


@workflow.defn(name=WORKFLOW_NAME)
class XinaoPlatformCapacityMaintenanceWorkflowV1:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = validate_request(payload)
        info = workflow.info()
        return await workflow.execute_activity(
            ACTIVITY_NAME,
            {
                **request,
                "workflow_id": info.workflow_id,
                "workflow_run_id": info.run_id,
            },
            result_type=dict,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                non_retryable_error_types=["ValueError", "TypeError"],
            ),
        )


def temporal_exports() -> tuple[list[type], list[Any]]:
    return [XinaoPlatformCapacityMaintenanceWorkflowV1], [pgbackrest_full_backup_activity]


__all__ = [
    "ACTIVITY_NAME",
    "POLICY_SCHEMA",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "TASK_QUEUE",
    "WORKFLOW_NAME",
    "XinaoPlatformCapacityMaintenanceWorkflowV1",
    "load_policy",
    "pgbackrest_full_backup_activity",
    "temporal_exports",
    "validate_request",
]
