"""Fresh subprocess twins followed by independent offline Taste scoring.

The run phase launches the same exact command/request/body/config/environment
in new work directories; only ``condition.bin`` differs.  It seals both raw
outputs without a scorer or oracle in either accessible tree.  A later score
phase recomputes the fixed rubric.  Synthetic tests prove the adapter contract,
not production-model qualification, and nothing here enables live retrieval.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_qualification import (
    TasteQualificationError,
    build_sealed_taste_outcome,
    qualify_taste_candidate,
)

SHADOW_REQUEST_SCHEMA = "s.taste_shadow_request.v2"
SCORER_SCHEMA = "s.taste_shadow_scorer.v1"
CONSUMER_OUTPUT_SCHEMA = "s.taste_shadow_consumer_output.v2"
EXECUTION_BUNDLE_SCHEMA = "s.taste_shadow_execution_bundle.v2"
PAIR_BUNDLE_SCHEMA = "s.taste_shadow_pair_bundle.v2"
SCORE_BUNDLE_SCHEMA = "s.taste_shadow_score_bundle.v1"

_CAPABILITIES = (
    "required_tool_use",
    "bounded_action",
    "open_representation_revision",
    "world_revision",
)
_MAX_FILE_BYTES = 16 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class TasteShadowRunnerError(ValueError):
    """A fresh-run, byte-binding, or reproducible-scoring contract failed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _fail(code: str, message: str) -> None:
    raise TasteShadowRunnerError(code, message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _seal(value: Mapping[str, object], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = _sha(canonical_json_bytes(sealed))
    return sealed


def _verify_seal(value: Mapping[str, object], field: str) -> str:
    observed = value.get(field)
    if not isinstance(observed, str) or _SHA_RE.fullmatch(observed) is None:
        _fail("HASH_MISMATCH", f"{field} is invalid")
    unsigned = dict(value)
    unsigned.pop(field, None)
    if _sha(canonical_json_bytes(unsigned)) != observed:
        _fail("HASH_MISMATCH", f"{field} does not seal the record")
    return observed


def _read_file(path: Path, field: str, *, allow_empty: bool = False) -> bytes:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        _fail("FILE_INVALID", f"{field} is not a regular non-link file")
    size = path.stat().st_size
    minimum = 0 if allow_empty else 1
    if size < minimum or size > _MAX_FILE_BYTES:
        _fail("FILE_INVALID", f"{field} must contain {minimum}..{_MAX_FILE_BYTES} bytes")
    with path.open("rb") as handle:
        raw = handle.read(_MAX_FILE_BYTES + 1)
    if len(raw) != size:
        _fail("FILE_CHANGED", f"{field} changed while it was read")
    return raw


def _json_object(raw: bytes, field: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasteShadowRunnerError("JSON_INVALID", f"{field} is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        _fail("JSON_INVALID", f"{field} must be a JSON object")
    return dict(value)


def _canonical_json_file(path: Path, field: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_file(path, field)
    value = _json_object(raw, field)
    if raw != canonical_json_bytes(value):
        _fail("JSON_NOT_CANONICAL", f"{field} must use canonical JSON bytes")
    return value, raw


def _binding(relative_path: str, raw: bytes) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "byte_sha256": _sha(raw),
        "byte_length": len(raw),
    }


def _bound_file(root: Path, binding: Mapping[str, object], field: str) -> bytes:
    relative = binding.get("relative_path")
    if not isinstance(relative, str) or not relative:
        _fail("BINDING_INVALID", f"{field} has no path")
    try:
        path = (root / relative).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise TasteShadowRunnerError("BINDING_INVALID", f"{field} escaped its bundle") from exc
    raw = _read_file(path, field, allow_empty=True)
    if len(raw) != binding.get("byte_length") or _sha(raw) != binding.get("byte_sha256"):
        _fail("BINDING_MISMATCH", f"{field} bytes differ from the manifest")
    return raw


def _write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        _fail("SCORER_INVALID", f"{field} must be a list of non-empty literal strings")
    return list(value)


def validate_scorer_spec(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) != {"schema_version", "target_failure", "capabilities"}:
        _fail("SCORER_INVALID", "scorer has missing or unsupported fields")
    if value.get("schema_version") != SCORER_SCHEMA:
        _fail("SCORER_INVALID", "unsupported scorer schema")
    target = value.get("target_failure")
    capabilities = value.get("capabilities")
    if not isinstance(target, Mapping) or set(target) != {
        "required_substrings",
        "forbidden_substrings",
    }:
        _fail("SCORER_INVALID", "target_failure rules are invalid")
    if not isinstance(capabilities, Mapping) or set(capabilities) != set(_CAPABILITIES):
        _fail("SCORER_INVALID", "capability rules are incomplete")
    normalized_capabilities: dict[str, object] = {}
    for name in _CAPABILITIES:
        rule = capabilities[name]
        if not isinstance(rule, Mapping) or set(rule) != {"required_substrings"}:
            _fail("SCORER_INVALID", f"{name} rule is invalid")
        normalized_capabilities[name] = {
            "required_substrings": _string_list(
                rule["required_substrings"], f"capabilities.{name}.required_substrings"
            )
        }
    return {
        "schema_version": SCORER_SCHEMA,
        "target_failure": {
            "required_substrings": _string_list(
                target["required_substrings"], "target_failure.required_substrings"
            ),
            "forbidden_substrings": _string_list(
                target["forbidden_substrings"], "target_failure.forbidden_substrings"
            ),
        },
        "capabilities": normalized_capabilities,
    }


def _consumer_output(raw: bytes) -> dict[str, object]:
    value = _json_object(raw.rstrip(b"\r\n"), "consumer stdout")
    expected = {
        "schema_version",
        "response_text",
        "session_identity",
        "observed_model_identity",
        "observed_request_sha256",
        "observed_body_sha256",
        "observed_config_sha256",
        "observed_condition_sha256",
    }
    if set(value) != expected or value.get("schema_version") != CONSUMER_OUTPUT_SCHEMA:
        _fail("CONSUMER_OUTPUT_INVALID", "consumer stdout does not satisfy the adapter schema")
    if not isinstance(value.get("response_text"), str) or not value["response_text"]:
        _fail("CONSUMER_OUTPUT_INVALID", "consumer response_text is empty")
    if not isinstance(value.get("session_identity"), str) or not value["session_identity"]:
        _fail("CONSUMER_OUTPUT_INVALID", "consumer session identity is empty")
    if (
        not isinstance(value.get("observed_model_identity"), str)
        or not value["observed_model_identity"]
    ):
        _fail("CONSUMER_OUTPUT_INVALID", "consumer model identity is empty")
    for field in (
        "observed_request_sha256",
        "observed_body_sha256",
        "observed_config_sha256",
        "observed_condition_sha256",
    ):
        if not isinstance(value.get(field), str) or _SHA_RE.fullmatch(str(value[field])) is None:
            _fail("CONSUMER_OUTPUT_INVALID", f"consumer {field} is invalid")
    return value


def _verify_consumer_observation(
    output: Mapping[str, object],
    *,
    candidate: Mapping[str, object],
    request: bytes,
    body: bytes,
    config: bytes,
    condition: bytes,
) -> None:
    expected = {
        "observed_model_identity": candidate["identities"]["model"],
        "observed_request_sha256": _sha(request),
        "observed_body_sha256": _sha(body),
        "observed_config_sha256": _sha(config),
        "observed_condition_sha256": _sha(condition),
    }
    if any(output.get(field) != value for field, value in expected.items()):
        _fail("CONSUMER_OBSERVATION_MISMATCH", "consumer did not observe the sealed arm inputs")


def score_consumer_output(
    *,
    stdout_bytes: bytes,
    scorer_spec: Mapping[str, object],
    evidence_ref: Mapping[str, object],
) -> dict[str, object]:
    """Recompute the fixed literal rubric from exact consumer stdout bytes."""

    spec = validate_scorer_spec(scorer_spec)
    output = _consumer_output(stdout_bytes)
    text = str(output["response_text"])
    target = spec["target_failure"]
    assert isinstance(target, Mapping)
    missing = sum(1 for needle in target["required_substrings"] if needle not in text)
    forbidden = sum(1 for needle in target["forbidden_substrings"] if needle in text)
    scores: dict[str, int] = {"target_failure": missing + forbidden}
    capabilities = spec["capabilities"]
    assert isinstance(capabilities, Mapping)
    for name in _CAPABILITIES:
        rule = capabilities[name]
        assert isinstance(rule, Mapping)
        scores[name] = sum(1 for needle in rule["required_substrings"] if needle in text)
    return {
        name: {"score": score, "evidence_refs": [dict(evidence_ref)]}
        for name, score in scores.items()
    }


def _identity_digest(value: object, raw: bytes, field: str) -> None:
    expected = f"sha256:{_sha(raw)}"
    if value != expected:
        _fail("IDENTITY_MISMATCH", f"candidate {field} identity is not bound to supplied bytes")


def _launch(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
) -> subprocess.Popen[bytes]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def _communicate(
    process: subprocess.Popen[bytes], *, request: bytes, timeout_seconds: float
) -> tuple[bytes, bytes]:
    try:
        stdout, stderr = process.communicate(input=request, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise TasteShadowRunnerError("RUN_TIMEOUT", "shadow subprocess timed out") from exc
    if len(stdout) > _MAX_FILE_BYTES or len(stderr) > _MAX_FILE_BYTES:
        _fail("RUN_OUTPUT_TOO_LARGE", "shadow subprocess output exceeded the bounded limit")
    if process.returncode != 0:
        _fail("RUN_FAILED", f"shadow subprocess exited {process.returncode}")
    return stdout, stderr


def _outcome_ref(*, run_id: str, arm: str, stdout: bytes) -> dict[str, object]:
    return {
        "source_ref": f"shadow-output://{run_id}/{arm}/{_sha(stdout)}",
        "byte_sha256": _sha(stdout),
        "byte_length": len(stdout),
        "rollout_locator": f"shadow-run://{run_id}/{arm}/stdout.json",
        "ordinal": 1,
    }


def _safe_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    safe_keys = {
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "PYTHONIOENCODING",
        "LANG",
        "LC_ALL",
    }
    if environment is None:
        result = {key: os.environ[key] for key in safe_keys if key in os.environ}
    else:
        result = dict(environment)
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        or "\x00" in key
        or "\x00" in value
        for key, value in result.items()
    ):
        _fail("ENVIRONMENT_INVALID", "shadow environment must contain exact strings")
    forbidden_keys = {
        "CODEX_HOME",
        "CODEX_CONTEXT_FABRIC_ROOT",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "HOME",
        "USERPROFILE",
    }
    if forbidden_keys & set(result):
        _fail("ENVIRONMENT_LEAK", "shadow environment exposes an ambient profile or Context root")
    if set(result) - safe_keys:
        _fail("ENVIRONMENT_INVALID", "shadow environment contains a non-allowlisted input")
    return result


def _command_file_receipts(command: Sequence[str]) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for index, argument in enumerate(command):
        path = Path(argument)
        if not path.is_absolute() or not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            _fail("COMMAND_INVALID", "absolute command file arguments must be regular non-links")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            _fail("COMMAND_CHANGED", "a command file changed while it was hashed")
        receipts.append(
            {
                "argv_index": index,
                "resolved_path": str(path.resolve(strict=True)),
                "byte_sha256": digest.hexdigest(),
                "byte_length": before.st_size,
            }
        )
    return receipts


def _tree_digest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in Path(root).rglob("*"):
        if path.is_symlink():
            _fail("ACCESSIBLE_TREE_INVALID", "shadow accessible tree contains a link")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("ACCESSIBLE_TREE_INVALID", "shadow accessible tree contains a non-file")
        result[path.relative_to(root).as_posix()] = _sha(
            _read_file(path, "shadow accessible tree file", allow_empty=True)
        )
    return result


def _assert_declared_tree(root: Path, expected_files: set[str], field: str) -> None:
    allowed_directories: set[str] = set()
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    observed_files: set[str] = set()
    for path in Path(root).rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            _fail("ACCESSIBLE_TREE_INVALID", f"{field} contains a link")
        if path.is_dir():
            if relative not in allowed_directories:
                _fail("ACCESSIBLE_TREE_INVALID", f"{field} contains an undeclared directory")
            continue
        if not path.is_file():
            _fail("ACCESSIBLE_TREE_INVALID", f"{field} contains a non-regular object")
        observed_files.add(relative)
    if observed_files != expected_files:
        _fail("ACCESSIBLE_TREE_INVALID", f"{field} contains undeclared or missing files")


def _oracle_bytes(evaluation: Mapping[str, object]) -> list[bytes]:
    oracle = evaluation["oracle"]
    assert isinstance(oracle, Mapping)
    rows = [
        oracle["bad_continuation"],
        *oracle["human_corrections"],
        oracle["desired_continuation"],
    ]
    result: list[bytes] = []
    for row in rows:
        assert isinstance(row, Mapping)
        result.append(str(row["text"]).encode("utf-8"))
    return result


def _assert_model_visible_nonleak(
    *,
    plan: Mapping[str, object],
    request: bytes,
    body: bytes,
    config: bytes,
    conditions: Mapping[str, bytes],
    command: Sequence[str],
    environment: Mapping[str, str],
    source_dir: Path,
    evaluation_dir: Path,
    plan_dir: Path,
) -> None:
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, Mapping)
    visible = {
        "request": request,
        "body": body,
        "config": config,
        "baseline condition": conditions["baseline"],
        "treatment condition": conditions["treatment"],
        "command": canonical_json_bytes(list(command)),
        "environment": canonical_json_bytes(dict(sorted(environment.items()))),
    }
    for oracle_raw in _oracle_bytes(evaluation):
        for field, raw in visible.items():
            if oracle_raw in raw:
                _fail(
                    "EVALUATION_ORACLE_LEAK",
                    f"held-out oracle bytes appear in model-visible {field}",
                )
    for root in (source_dir, evaluation_dir, plan_dir):
        resolved = str(Path(root).resolve()).replace("\\", "/").casefold()
        locator_inputs = {
            "request": request.decode("utf-8", errors="ignore"),
            "body": body.decode("utf-8", errors="ignore"),
            "config": config.decode("utf-8", errors="ignore"),
            "baseline condition": conditions["baseline"].decode("utf-8", errors="ignore"),
            "treatment condition": conditions["treatment"].decode("utf-8", errors="ignore"),
            **{f"command[{index}]": item for index, item in enumerate(command)},
            **{f"environment[{key}]": value for key, value in environment.items()},
        }
        for field, surface in locator_inputs.items():
            if resolved and resolved in surface.replace("\\", "/").casefold():
                _fail(
                    "EVALUATION_PATH_LEAK",
                    f"model-visible {field} exposes a corpus/plan path",
                )
    locator_surface = "\n".join([*command, *environment.values()]).replace("\\", "/").casefold()
    if "offline/scorer.json" in locator_surface or "offline/oracle.json" in locator_surface:
        _fail("EVALUATION_PATH_LEAK", "shadow launch exposes an offline judge path")
    scorer_raw = evaluation["scorer_raw"]
    assert isinstance(scorer_raw, bytes)
    if any(_sha(raw) == _sha(scorer_raw) for raw in visible.values()):
        _fail("SCORER_LEAK", "offline scorer was supplied as a model-visible input")


def _prepare_execution_dir(
    *, pair_root: Path, arm: str, request: bytes, body: bytes, config: bytes, condition: bytes
) -> Path:
    run_dir = pair_root / arm
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_bytes(run_dir / "request.json", request)
    _write_bytes(run_dir / "body.bin", body)
    _write_bytes(run_dir / "config.bin", config)
    _write_bytes(run_dir / "condition.bin", condition)
    return run_dir


def _nested_paths(left: Path, right: Path) -> bool:
    left = Path(left).resolve()
    right = Path(right).resolve()
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _verify_adapter_observation(
    output: Mapping[str, object],
    *,
    candidate: Mapping[str, object],
    request: bytes,
    body: bytes,
    config: bytes,
    condition: bytes,
) -> None:
    _verify_consumer_observation(
        output,
        candidate=candidate,
        request=request,
        body=body,
        config=config,
        condition=condition,
    )


def _finish_execution(
    *,
    run_dir: Path,
    arm: str,
    pair_id: str,
    process_id: int,
    command: Sequence[str],
    environment_sha256: str,
    candidate: Mapping[str, object],
    request: bytes,
    body: bytes,
    config: bytes,
    condition: bytes,
    stdout: bytes,
    stderr: bytes,
) -> dict[str, object]:
    output = _consumer_output(stdout)
    _verify_adapter_observation(
        output,
        candidate=candidate,
        request=request,
        body=body,
        config=config,
        condition=condition,
    )
    _write_bytes(run_dir / "stdout.json", stdout)
    _write_bytes(run_dir / "stderr.bin", stderr)
    files = {
        "request": _binding("request.json", request),
        "body": _binding("body.bin", body),
        "config": _binding("config.bin", config),
        "condition": _binding("condition.bin", condition),
        "stdout": _binding("stdout.json", stdout),
        "stderr": _binding("stderr.bin", stderr),
    }
    manifest = _seal(
        {
            "schema_version": EXECUTION_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "arm": arm,
            "pair_id": pair_id,
            "process_id": process_id,
            "consumer_session_identity": output["session_identity"],
            "command_sha256": _sha(canonical_json_bytes(list(command))),
            "environment_sha256": environment_sha256,
            "freshness": {
                "new_process": True,
                "new_run_directory": True,
                "resume_allowed": False,
                "cache_reuse_allowed": False,
            },
            "files": files,
        },
        "execution_bundle_sha256",
    )
    _write_bytes(run_dir / "execution_manifest.json", canonical_json_bytes(manifest))
    return {
        "directory": str(run_dir.resolve()),
        "manifest": manifest,
        "output": output,
    }


def verify_shadow_execution_bundle(
    execution_dir: Path,
    *,
    expected_arm: str,
    plan: Mapping[str, object],
) -> dict[str, object]:
    root = Path(execution_dir)
    manifest, manifest_raw = _canonical_json_file(
        root / "execution_manifest.json", "execution manifest"
    )
    execution_sha = _verify_seal(manifest, "execution_bundle_sha256")
    if (
        manifest.get("schema_version") != EXECUTION_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("arm") != expected_arm
        or root.name != expected_arm
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("EXECUTION_POLICY_INVALID", "shadow execution policy or identity drifted")
    expected_files = {
        "request.json",
        "body.bin",
        "config.bin",
        "condition.bin",
        "stdout.json",
        "stderr.bin",
        "execution_manifest.json",
    }
    _assert_declared_tree(root, expected_files, "shadow execution")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        "request",
        "body",
        "config",
        "condition",
        "stdout",
        "stderr",
    }:
        _fail("BINDING_INVALID", "execution file bindings are incomplete")
    raw: dict[str, bytes] = {}
    for name in files:
        binding = files[name]
        if not isinstance(binding, Mapping):
            _fail("BINDING_INVALID", f"execution {name} binding is invalid")
        raw[name] = _bound_file(root, binding, f"execution {name}")
    output = _consumer_output(raw["stdout"])
    candidate = plan["candidate"]
    conditions = plan["conditions"]
    assert isinstance(candidate, Mapping) and isinstance(conditions, Mapping)
    _verify_adapter_observation(
        output,
        candidate=candidate,
        request=raw["request"],
        body=raw["body"],
        config=raw["config"],
        condition=raw["condition"],
    )
    if raw["request"] != plan["request"] or raw["condition"] != conditions[expected_arm]:
        _fail("INPUT_BINDING_MISMATCH", "execution request or condition differs from its plan")
    _identity_digest(candidate["identities"]["body"], raw["body"], "body")
    _identity_digest(candidate["identities"]["config"], raw["config"], "config")
    freshness = manifest.get("freshness")
    if freshness != {
        "new_process": True,
        "new_run_directory": True,
        "resume_allowed": False,
        "cache_reuse_allowed": False,
    }:
        _fail("RUN_NOT_FRESH", "execution freshness contract drifted")
    process_id = manifest.get("process_id")
    if type(process_id) is not int or process_id <= 0:
        _fail("RUN_NOT_FRESH", "execution lacks a real process identity")
    return {
        "execution_bundle_sha256": execution_sha,
        "process_id": process_id,
        "consumer_session_identity": output["session_identity"],
        "output": output,
        "stdout": raw["stdout"],
        "stderr": raw["stderr"],
        "condition_sha256": _sha(raw["condition"]),
        "same_inputs": {
            "request_sha256": _sha(raw["request"]),
            "body_sha256": _sha(raw["body"]),
            "config_sha256": _sha(raw["config"]),
            "command_sha256": manifest["command_sha256"],
            "environment_sha256": manifest["environment_sha256"],
        },
    }


def run_fresh_shadow_pair(
    *,
    source_dir: Path,
    evaluation_dir: Path,
    plan_dir: Path,
    output_root: Path,
    command: Sequence[str],
    body_path: Path,
    config_path: Path,
    timeout_seconds: float = 120.0,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run fresh isolated twins and seal raw executions without reading the scorer."""

    from services.agent_runtime.taste_corpus import verify_qualification_plan

    if (
        isinstance(command, (str, bytes))
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        _fail("COMMAND_INVALID", "command must be a non-empty exact argv sequence")
    executable = Path(command[0])
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        _fail("COMMAND_INVALID", "command executable must be an absolute regular non-link file")
    if any(item in {"resume", "--resume", "--continue"} for item in command[1:]):
        _fail("RUN_NOT_FRESH", "shadow command may not resume or continue a prior session")
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        _fail("TIMEOUT_INVALID", "timeout must be within 0..3600 seconds")
    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    body = _read_file(body_path, "body")
    config = _read_file(config_path, "config")
    candidate = plan["candidate"]
    assert isinstance(candidate, Mapping)
    _identity_digest(candidate["identities"]["body"], body, "body")
    _identity_digest(candidate["identities"]["config"], config, "config")
    request = plan["request"]
    conditions = plan["conditions"]
    assert isinstance(request, bytes) and isinstance(conditions, Mapping)
    stable_environment = _safe_environment(environment)
    command_files = _command_file_receipts(command)
    _assert_model_visible_nonleak(
        plan=plan,
        request=request,
        body=body,
        config=config,
        conditions=conditions,
        command=command,
        environment=stable_environment,
        source_dir=Path(source_dir),
        evaluation_dir=Path(evaluation_dir),
        plan_dir=Path(plan_dir),
    )
    output_root = Path(output_root)
    if any(
        _nested_paths(output_root, protected)
        for protected in (Path(source_dir), Path(evaluation_dir), Path(plan_dir))
    ):
        _fail("ACCESSIBLE_TREE_INVALID", "shadow output tree overlaps an offline corpus/plan root")
    pair_id = f"pair-{uuid.uuid4().hex}"
    pair_root = output_root / "pairs" / pair_id
    pair_root.mkdir(parents=True, exist_ok=False)
    run_dirs = {
        arm: _prepare_execution_dir(
            pair_root=pair_root,
            arm=arm,
            request=request,
            body=body,
            config=config,
            condition=conditions[arm],
        )
        for arm in ("baseline", "treatment")
    }
    if _sha(conditions["baseline"]) == _sha(conditions["treatment"]):
        _fail("CONDITION_MISMATCH", "shadow conditions are not distinct")
    before_tree = _tree_digest(pair_root)
    environment_sha = _sha(canonical_json_bytes(dict(sorted(stable_environment.items()))))
    started = time.monotonic()
    processes = {
        arm: _launch(command, cwd=run_dirs[arm], environment=stable_environment)
        for arm in ("baseline", "treatment")
    }
    if processes["baseline"].pid == processes["treatment"].pid:
        _fail("RUN_NOT_FRESH", "shadow arms did not receive distinct subprocesses")
    outputs: dict[str, tuple[bytes, bytes]] = {}
    try:
        for arm in ("baseline", "treatment"):
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                _fail("RUN_TIMEOUT", "shadow pair exceeded its shared timeout")
            outputs[arm] = _communicate(processes[arm], request=request, timeout_seconds=remaining)
        if _tree_digest(pair_root) != before_tree:
            _fail("HOT_MUTATION_DETECTED", "consumer changed its accessible input tree")
        if _command_file_receipts(command) != command_files:
            _fail("COMMAND_CHANGED", "a command file changed during the shadow pair")
    except Exception:
        for process in processes.values():
            if process.poll() is None:
                process.kill()
                process.communicate()
        raise
    finished: dict[str, dict[str, object]] = {}
    for arm in ("baseline", "treatment"):
        stdout, stderr = outputs[arm]
        finished[arm] = _finish_execution(
            run_dir=run_dirs[arm],
            arm=arm,
            pair_id=pair_id,
            process_id=processes[arm].pid,
            command=command,
            environment_sha256=environment_sha,
            candidate=candidate,
            request=request,
            body=body,
            config=config,
            condition=conditions[arm],
            stdout=stdout,
            stderr=stderr,
        )
    verified_arms = {
        arm: verify_shadow_execution_bundle(run_dirs[arm], expected_arm=arm, plan=plan)
        for arm in ("baseline", "treatment")
    }
    if (
        verified_arms["baseline"]["process_id"] == verified_arms["treatment"]["process_id"]
        or verified_arms["baseline"]["consumer_session_identity"]
        == verified_arms["treatment"]["consumer_session_identity"]
    ):
        _fail("RUN_NOT_INDEPENDENT", "shadow arms reused one process or consumer session")
    pair_manifest = _seal(
        {
            "schema_version": PAIR_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "scoring_complete": False,
            "pair_id": pair_id,
            "plan_bundle_sha256": plan["plan_bundle_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "command": list(command),
            "command_files": command_files,
            "environment": dict(sorted(stable_environment.items())),
            "model_visible_same_inputs": verified_arms["baseline"]["same_inputs"],
            "distinct_conditions": {
                arm: verified_arms[arm]["condition_sha256"] for arm in ("baseline", "treatment")
            },
            "executions": {
                arm: {
                    "relative_path": arm,
                    "execution_bundle_sha256": verified_arms[arm]["execution_bundle_sha256"],
                }
                for arm in ("baseline", "treatment")
            },
            "offline_inputs_exposed": {"oracle": False, "scorer": False},
        },
        "pair_bundle_sha256",
    )
    _write_bytes(pair_root / "pair_manifest.json", canonical_json_bytes(pair_manifest))
    verified_pair = verify_shadow_pair(
        pair_root,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    return {
        "pair_directory": str(pair_root.resolve()),
        "pair_bundle_sha256": verified_pair["pair_bundle_sha256"],
        "baseline_directory": str(run_dirs["baseline"].resolve()),
        "treatment_directory": str(run_dirs["treatment"].resolve()),
        "scoring_complete": False,
        "live_activation_allowed": False,
    }


def verify_shadow_pair(
    pair_dir: Path,
    *,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_qualification_plan

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    root = Path(pair_dir)
    manifest, manifest_raw = _canonical_json_file(root / "pair_manifest.json", "pair manifest")
    pair_sha = _verify_seal(manifest, "pair_bundle_sha256")
    if (
        manifest.get("schema_version") != PAIR_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("scoring_complete") is not False
        or manifest.get("pair_id") != root.name
        or manifest.get("plan_bundle_sha256") != plan["plan_bundle_sha256"]
        or manifest.get("candidate_sha256") != plan["candidate"]["candidate_sha256"]
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("PAIR_POLICY_INVALID", "shadow pair policy or chain drifted")
    if manifest.get("offline_inputs_exposed") != {"oracle": False, "scorer": False}:
        _fail("OFFLINE_INPUT_EXPOSED", "shadow pair exposes an offline judge input")
    command = manifest.get("command")
    command_files = manifest.get("command_files")
    environment = manifest.get("environment")
    common = manifest.get("model_visible_same_inputs")
    normalized_environment = (
        _safe_environment(environment) if isinstance(environment, Mapping) else None
    )
    if (
        not isinstance(command, list)
        or any(not isinstance(item, str) or not item for item in command)
        or not isinstance(command_files, list)
        or not isinstance(environment, Mapping)
        or normalized_environment != dict(environment)
        or not isinstance(common, Mapping)
        or common.get("command_sha256") != _sha(canonical_json_bytes(command))
        or common.get("environment_sha256")
        != _sha(canonical_json_bytes(dict(sorted(environment.items()))))
    ):
        _fail("INPUT_BINDING_MISMATCH", "pair launch input receipt is incomplete")
    seen_command_indices: set[int] = set()
    for receipt in command_files:
        if not isinstance(receipt, Mapping) or set(receipt) != {
            "argv_index",
            "resolved_path",
            "byte_sha256",
            "byte_length",
        }:
            _fail("INPUT_BINDING_MISMATCH", "command file receipt is invalid")
        index = receipt.get("argv_index")
        if (
            type(index) is not int
            or index < 0
            or index >= len(command)
            or index in seen_command_indices
            or not Path(command[index]).is_absolute()
            or str(Path(command[index]).resolve()) != receipt.get("resolved_path")
            or not isinstance(receipt.get("byte_sha256"), str)
            or _SHA_RE.fullmatch(str(receipt["byte_sha256"])) is None
            or type(receipt.get("byte_length")) is not int
            or int(receipt["byte_length"]) < 1
        ):
            _fail("INPUT_BINDING_MISMATCH", "command file receipt does not bind argv")
        seen_command_indices.add(index)
    if 0 not in seen_command_indices:
        _fail("INPUT_BINDING_MISMATCH", "command executable receipt is missing")
    executions = manifest.get("executions")
    if not isinstance(executions, Mapping) or set(executions) != {"baseline", "treatment"}:
        _fail("BINDING_INVALID", "pair execution bindings are missing")
    arms: dict[str, dict[str, object]] = {}
    for arm in ("baseline", "treatment"):
        binding = executions[arm]
        if not isinstance(binding, Mapping) or binding.get("relative_path") != arm:
            _fail("BINDING_INVALID", f"{arm} execution binding is invalid")
        arms[arm] = verify_shadow_execution_bundle(root / arm, expected_arm=arm, plan=plan)
        if arms[arm]["execution_bundle_sha256"] != binding.get("execution_bundle_sha256"):
            _fail("BINDING_MISMATCH", f"{arm} execution identity drifted")
    if arms["baseline"]["same_inputs"] != arms["treatment"]["same_inputs"]:
        _fail("INPUT_BINDING_MISMATCH", "shadow arms differ beyond their condition")
    if manifest.get("model_visible_same_inputs") != arms["baseline"]["same_inputs"]:
        _fail("INPUT_BINDING_MISMATCH", "pair common-input receipt drifted")
    expected_conditions = {arm: arms[arm]["condition_sha256"] for arm in ("baseline", "treatment")}
    if (
        manifest.get("distinct_conditions") != expected_conditions
        or expected_conditions["baseline"] == expected_conditions["treatment"]
    ):
        _fail("CONDITION_MISMATCH", "pair conditions are missing or not distinct")
    if (
        arms["baseline"]["process_id"] == arms["treatment"]["process_id"]
        or arms["baseline"]["consumer_session_identity"]
        == arms["treatment"]["consumer_session_identity"]
    ):
        _fail("RUN_NOT_INDEPENDENT", "shadow pair reused one process or consumer session")
    execution_files = {
        "request.json",
        "body.bin",
        "config.bin",
        "condition.bin",
        "stdout.json",
        "stderr.bin",
        "execution_manifest.json",
    }
    _assert_declared_tree(
        root,
        {
            "pair_manifest.json",
            *{f"baseline/{name}" for name in execution_files},
            *{f"treatment/{name}" for name in execution_files},
        },
        "shadow pair",
    )
    return {
        "pair_bundle_sha256": pair_sha,
        "pair_id": manifest["pair_id"],
        "candidate_sha256": plan["candidate"]["candidate_sha256"],
        "baseline": arms["baseline"],
        "treatment": arms["treatment"],
        "live_activation_allowed": False,
    }


def _score_records(
    *, pair: Mapping[str, object], plan: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    candidate = plan["candidate"]
    evaluation = plan["evaluation"]
    assert isinstance(candidate, Mapping) and isinstance(evaluation, Mapping)
    scorer = evaluation["scorer"]
    assert isinstance(scorer, Mapping)
    outcomes: dict[str, dict[str, object]] = {}
    for arm in ("baseline", "treatment"):
        execution = pair[arm]
        assert isinstance(execution, Mapping)
        stdout = execution["stdout"]
        assert isinstance(stdout, bytes)
        output_ref = _outcome_ref(run_id=f"{pair['pair_id']}-{arm}", arm=arm, stdout=stdout)
        metrics = score_consumer_output(
            stdout_bytes=stdout, scorer_spec=scorer, evidence_ref=output_ref
        )
        outcomes[arm] = build_sealed_taste_outcome(
            candidate=candidate,
            arm=arm,
            condition_sha256=execution["condition_sha256"],
            run_id=f"{pair['pair_id']}-{arm}",
            fresh_run=True,
            cache_used=False,
            observed_prefix=candidate["baseline_prefix"]["sources"],
            model_identity=str(candidate["identities"]["model"]),
            body_identity=str(candidate["identities"]["body"]),
            config_identity=str(candidate["identities"]["config"]),
            hooks_enabled=False,
            oracle_exposed=False,
            live_retrieval_used=False,
            hot_mutations={"prompt": False, "skill": False, "agents": False},
            trajectory={"sealed": True, "ref": output_ref},
            metrics=metrics,
        )
    try:
        receipt = qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=outcomes["baseline"],
            treatment_outcome=outcomes["treatment"],
        )
    except TasteQualificationError as exc:
        raise TasteShadowRunnerError(exc.reason_code, str(exc)) from exc
    return outcomes["baseline"], outcomes["treatment"], receipt


def score_shadow_pair(
    *,
    pair_dir: Path,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
    score_root: Path,
) -> dict[str, object]:
    """Score only after both exact executions are sealed; never expose scorer to arms."""

    from services.agent_runtime.taste_corpus import verify_qualification_plan

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    pair = verify_shadow_pair(
        pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    baseline, treatment, receipt = _score_records(pair=pair, plan=plan)
    score_id = f"score-{uuid.uuid4().hex}"
    target = Path(score_root) / score_id
    baseline_raw = canonical_json_bytes(baseline)
    treatment_raw = canonical_json_bytes(treatment)
    receipt_raw = canonical_json_bytes(receipt)
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, Mapping)
    manifest = _seal(
        {
            "schema_version": SCORE_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "score_id": score_id,
            "plan_bundle_sha256": plan["plan_bundle_sha256"],
            "pair_bundle_sha256": pair["pair_bundle_sha256"],
            "candidate_sha256": plan["candidate"]["candidate_sha256"],
            "offline_scorer_sha256": _sha(evaluation["scorer_raw"]),
            "files": {
                "baseline": _binding("outcomes/baseline.json", baseline_raw),
                "treatment": _binding("outcomes/treatment.json", treatment_raw),
                "receipt": _binding("qualification.receipt.json", receipt_raw),
            },
            "qualification_receipt_sha256": receipt["receipt_sha256"],
        },
        "score_bundle_sha256",
    )
    files = {
        "score_manifest.json": canonical_json_bytes(manifest),
        "outcomes/baseline.json": baseline_raw,
        "outcomes/treatment.json": treatment_raw,
        "qualification.receipt.json": receipt_raw,
    }
    target.mkdir(parents=True, exist_ok=False)
    for relative, raw in files.items():
        _write_bytes(target / relative, raw)
    verified = verify_shadow_score_bundle(
        target,
        pair_dir=pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    return {
        "score_directory": str(target.resolve()),
        "score_bundle_sha256": verified["score_bundle_sha256"],
        "qualification_receipt_sha256": verified["qualification_receipt_sha256"],
        "live_activation_allowed": False,
    }


def verify_shadow_score_bundle(
    score_dir: Path,
    *,
    pair_dir: Path,
    plan_dir: Path,
    source_dir: Path,
    evaluation_dir: Path,
) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_qualification_plan

    plan = verify_qualification_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
    pair = verify_shadow_pair(
        pair_dir,
        plan_dir=plan_dir,
        source_dir=source_dir,
        evaluation_dir=evaluation_dir,
    )
    root = Path(score_dir)
    manifest, manifest_raw = _canonical_json_file(root / "score_manifest.json", "score manifest")
    score_sha = _verify_seal(manifest, "score_bundle_sha256")
    evaluation = plan["evaluation"]
    assert isinstance(evaluation, Mapping)
    if (
        manifest.get("schema_version") != SCORE_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("score_id") != root.name
        or manifest.get("plan_bundle_sha256") != plan["plan_bundle_sha256"]
        or manifest.get("pair_bundle_sha256") != pair["pair_bundle_sha256"]
        or manifest.get("candidate_sha256") != plan["candidate"]["candidate_sha256"]
        or manifest.get("offline_scorer_sha256") != _sha(evaluation["scorer_raw"])
        or manifest_raw != canonical_json_bytes(manifest)
    ):
        _fail("SCORE_POLICY_INVALID", "score bundle policy or evidence chain drifted")
    bindings = manifest.get("files")
    if not isinstance(bindings, Mapping) or set(bindings) != {
        "baseline",
        "treatment",
        "receipt",
    }:
        _fail("BINDING_INVALID", "score file bindings are incomplete")
    observed: dict[str, bytes] = {}
    for name in bindings:
        binding = bindings[name]
        if not isinstance(binding, Mapping):
            _fail("BINDING_INVALID", f"score {name} binding is invalid")
        observed[name] = _bound_file(root, binding, f"score {name}")
    baseline, treatment, receipt = _score_records(pair=pair, plan=plan)
    expected = {
        "baseline": canonical_json_bytes(baseline),
        "treatment": canonical_json_bytes(treatment),
        "receipt": canonical_json_bytes(receipt),
    }
    if (
        observed != expected
        or manifest.get("qualification_receipt_sha256") != receipt["receipt_sha256"]
    ):
        _fail("SCORE_RECOMPUTE_MISMATCH", "offline score or qualification does not recompute")
    _assert_declared_tree(
        root,
        {
            "score_manifest.json",
            "outcomes/baseline.json",
            "outcomes/treatment.json",
            "qualification.receipt.json",
        },
        "offline score bundle",
    )
    return {
        "score_bundle_sha256": score_sha,
        "score_id": manifest["score_id"],
        "qualification_receipt_sha256": receipt["receipt_sha256"],
        "baseline_outcome": baseline,
        "treatment_outcome": treatment,
        "candidate_sha256": plan["candidate"]["candidate_sha256"],
        "live_activation_allowed": False,
    }


__all__ = [
    "CONSUMER_OUTPUT_SCHEMA",
    "SCORER_SCHEMA",
    "TasteShadowRunnerError",
    "run_fresh_shadow_pair",
    "score_consumer_output",
    "score_shadow_pair",
    "validate_scorer_spec",
    "verify_shadow_execution_bundle",
    "verify_shadow_pair",
    "verify_shadow_score_bundle",
]
