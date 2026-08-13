"""Fresh subprocess twins and reproducible scoring for cold Taste candidates.

The runner is deliberately adapter-shaped: it launches the same executable and
the same exact request/body/config twice in new process/work directories.  The
only logical input difference is ``condition.bin``.  A real model adapter can
consume this contract later; this module never treats a synthetic subprocess
test as production model qualification or enables live retrieval.
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
    validate_sealed_taste_outcome,
    validate_taste_qualification_receipt,
)

SHADOW_REQUEST_SCHEMA = "s.taste_shadow_request.v1"
SCORER_SCHEMA = "s.taste_shadow_scorer.v1"
CONSUMER_OUTPUT_SCHEMA = "s.taste_shadow_consumer_output.v1"
OUTCOME_BUNDLE_SCHEMA = "s.taste_shadow_outcome_bundle.v1"
PAIR_BUNDLE_SCHEMA = "s.taste_shadow_pair_bundle.v1"

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
        "fresh_session",
        "cache_used",
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
    if value.get("fresh_session") is not True or value.get("cache_used") is not False:
        _fail("RUN_NOT_FRESH", "consumer did not attest a fresh uncached session")
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


def _request_bytes(
    candidate_dir: Path, bundle: Mapping[str, object], body: bytes, config: bytes
) -> bytes:
    candidate = bundle["candidate"]
    manifest = bundle["manifest"]
    assert isinstance(candidate, Mapping) and isinstance(manifest, Mapping)
    prefix_count = int(manifest["prefix_count"])
    prefix: list[dict[str, object]] = []
    for binding in manifest["source_bindings"][:prefix_count]:
        source = _bound_file(candidate_dir, binding, "candidate prefix source")
        prefix.append(
            {
                "event_id": binding["event_id"],
                "speaker": binding["speaker"],
                "byte_sha256": _sha(source),
                "text": source.decode("utf-8"),
            }
        )
    envelope = {
        "schema_version": SHADOW_REQUEST_SCHEMA,
        "candidate_sha256": candidate["candidate_sha256"],
        "prefix_sha256": candidate["baseline_prefix"]["prefix_sha256"],
        "model_identity": candidate["identities"]["model"],
        "body_sha256": _sha(body),
        "config_sha256": _sha(config),
        "prefix": prefix,
    }
    return canonical_json_bytes(envelope)


def _identity_digest(value: object, raw: bytes, field: str) -> None:
    expected = f"sha256:{_sha(raw)}"
    if value != expected:
        _fail("IDENTITY_MISMATCH", f"candidate {field} identity is not bound to supplied bytes")


def _prepare_run(
    *,
    pair_root: Path,
    arm: str,
    request: bytes,
    body: bytes,
    config: bytes,
    condition: bytes,
    scorer_raw: bytes,
) -> Path:
    run_dir = pair_root / arm
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_bytes(run_dir / "request.json", request)
    _write_bytes(run_dir / "body.bin", body)
    _write_bytes(run_dir / "config.bin", config)
    _write_bytes(run_dir / "condition.bin", condition)
    _write_bytes(run_dir / "scorer.json", scorer_raw)
    return run_dir


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


def _finish_outcome(
    *,
    run_dir: Path,
    arm: str,
    run_id: str,
    process_id: int,
    command: Sequence[str],
    environment_sha256: str,
    candidate: Mapping[str, object],
    stdout: bytes,
    stderr: bytes,
    request: bytes,
    body: bytes,
    config: bytes,
    condition: bytes,
    scorer: Mapping[str, object],
    scorer_raw: bytes,
) -> dict[str, object]:
    output = _consumer_output(stdout)
    _verify_consumer_observation(
        output,
        candidate=candidate,
        request=request,
        body=body,
        config=config,
        condition=condition,
    )
    output_ref = _outcome_ref(run_id=run_id, arm=arm, stdout=stdout)
    metrics = score_consumer_output(
        stdout_bytes=stdout,
        scorer_spec=scorer,
        evidence_ref=output_ref,
    )
    outcome = build_sealed_taste_outcome(
        candidate=candidate,
        arm=arm,
        condition_sha256=_sha(condition),
        run_id=run_id,
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
    outcome_raw = canonical_json_bytes(outcome)
    _write_bytes(run_dir / "stdout.json", stdout)
    _write_bytes(run_dir / "stderr.bin", stderr)
    _write_bytes(run_dir / "outcome.json", outcome_raw)
    files = {
        "request": _binding("request.json", request),
        "body": _binding("body.bin", body),
        "config": _binding("config.bin", config),
        "condition": _binding("condition.bin", condition),
        "scorer": _binding("scorer.json", scorer_raw),
        "stdout": _binding("stdout.json", stdout),
        "stderr": _binding("stderr.bin", stderr),
        "outcome": _binding("outcome.json", outcome_raw),
    }
    manifest = _seal(
        {
            "schema_version": OUTCOME_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "freshness_scope": "fresh_isolated_subprocess_and_consumer_session",
            "candidate_sha256": candidate["candidate_sha256"],
            "arm": arm,
            "run_id": run_id,
            "process_id": process_id,
            "consumer_session_identity": output["session_identity"],
            "command": list(command),
            "environment_sha256": environment_sha256,
            "files": files,
            "outcome_sha256": outcome["outcome_sha256"],
        },
        "bundle_sha256",
    )
    _write_bytes(run_dir / "manifest.json", canonical_json_bytes(manifest))
    return {"directory": str(run_dir), "manifest": manifest, "outcome": outcome}


def verify_shadow_outcome_bundle(outcome_dir: Path, *, candidate_dir: Path) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_candidate_bundle

    candidate_bundle = verify_candidate_bundle(candidate_dir)
    candidate = candidate_bundle["candidate"]
    root = Path(outcome_dir)
    manifest, _ = _canonical_json_file(root / "manifest.json", "shadow outcome manifest")
    bundle_sha = _verify_seal(manifest, "bundle_sha256")
    if (
        manifest.get("schema_version") != OUTCOME_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("candidate_sha256") != candidate["candidate_sha256"]
    ):
        _fail("BUNDLE_POLICY_INVALID", "shadow outcome bundle policy or candidate differs")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        "request",
        "body",
        "config",
        "condition",
        "scorer",
        "stdout",
        "stderr",
        "outcome",
    }:
        _fail("BINDING_INVALID", "shadow outcome file bindings are incomplete")
    values = {name: _bound_file(root, files[name], name) for name in files}
    scorer = validate_scorer_spec(_json_object(values["scorer"], "scorer"))
    if values["scorer"] != canonical_json_bytes(scorer):
        _fail("SCORER_INVALID", "scorer bytes are not canonical")
    expected_request = _request_bytes(
        candidate_dir=Path(candidate_dir),
        bundle=candidate_bundle,
        body=values["body"],
        config=values["config"],
    )
    if values["request"] != expected_request:
        _fail("REQUEST_MISMATCH", "shadow request differs from exact candidate/body/config")
    arm = str(manifest.get("arm") or "")
    if arm not in {"baseline", "treatment"}:
        _fail("ARM_MISMATCH", "shadow outcome arm is invalid")
    condition_binding = candidate_bundle["manifest"]["conditions"][arm]
    expected_condition = _bound_file(Path(candidate_dir), condition_binding, f"{arm} condition")
    if values["condition"] != expected_condition:
        _fail("CONDITION_MISMATCH", "shadow outcome used another condition")
    _identity_digest(candidate["identities"]["body"], values["body"], "body")
    _identity_digest(candidate["identities"]["config"], values["config"], "config")
    outcome_value = _json_object(values["outcome"], "outcome")
    try:
        outcome = validate_sealed_taste_outcome(
            outcome_value, candidate=candidate, expected_arm=arm
        )
    except TasteQualificationError as exc:
        raise TasteShadowRunnerError(exc.reason_code, str(exc)) from exc
    output_ref = _outcome_ref(run_id=str(manifest["run_id"]), arm=arm, stdout=values["stdout"])
    expected_metrics = score_consumer_output(
        stdout_bytes=values["stdout"], scorer_spec=scorer, evidence_ref=output_ref
    )
    if (
        outcome["metrics"] != expected_metrics
        or outcome["trajectory"] != {"sealed": True, "ref": output_ref}
        or outcome["run"]["run_id"] != manifest.get("run_id")
        or outcome["outcome_sha256"] != manifest.get("outcome_sha256")
    ):
        _fail("OUTCOME_MISMATCH", "sealed outcome does not match exact output and scorer")
    output = _consumer_output(values["stdout"])
    _verify_consumer_observation(
        output,
        candidate=candidate,
        request=values["request"],
        body=values["body"],
        config=values["config"],
        condition=values["condition"],
    )
    if output["session_identity"] != manifest.get("consumer_session_identity"):
        _fail("RUN_NOT_FRESH", "consumer session identity drifted")
    command = manifest.get("command")
    environment_sha = manifest.get("environment_sha256")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item for item in command)
        or not isinstance(environment_sha, str)
        or _SHA_RE.fullmatch(environment_sha) is None
    ):
        _fail("BINDING_INVALID", "shadow command or environment identity is invalid")
    same_inputs = {
        "request_sha256": _sha(values["request"]),
        "body_sha256": _sha(values["body"]),
        "config_sha256": _sha(values["config"]),
        "scorer_sha256": _sha(values["scorer"]),
        "command_sha256": _sha(canonical_json_bytes(command)),
        "environment_sha256": environment_sha,
    }
    return {
        "bundle_sha256": bundle_sha,
        "candidate_sha256": candidate["candidate_sha256"],
        "arm": arm,
        "run_id": manifest["run_id"],
        "process_id": manifest["process_id"],
        "consumer_session_identity": output["session_identity"],
        "same_inputs": same_inputs,
        "condition_sha256": _sha(values["condition"]),
        "outcome": outcome,
        "live_activation_allowed": False,
    }


def run_fresh_shadow_pair(
    *,
    candidate_dir: Path,
    output_root: Path,
    command: Sequence[str],
    body_path: Path,
    config_path: Path,
    scorer_spec_path: Path,
    timeout_seconds: float = 120.0,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Run and qualify two real subprocess consumers; never activate the result."""

    from services.agent_runtime.taste_corpus import verify_candidate_bundle

    if (
        isinstance(command, (str, bytes))
        or not command
        or any(not isinstance(item, str) or not item for item in command)
    ):
        _fail("COMMAND_INVALID", "command must be a non-empty exact argv sequence")
    executable = Path(command[0])
    if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
        _fail("COMMAND_INVALID", "command executable must be an absolute regular non-link file")
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        _fail("TIMEOUT_INVALID", "timeout must be within 0..3600 seconds")

    candidate_bundle = verify_candidate_bundle(candidate_dir)
    candidate = candidate_bundle["candidate"]
    body = _read_file(body_path, "body")
    config = _read_file(config_path, "config")
    _identity_digest(candidate["identities"]["body"], body, "body")
    _identity_digest(candidate["identities"]["config"], config, "config")
    scorer_value, scorer_raw = _canonical_json_file(scorer_spec_path, "scorer")
    scorer = validate_scorer_spec(scorer_value)
    if scorer_raw != canonical_json_bytes(scorer):
        _fail("SCORER_INVALID", "scorer normalization changed its bytes")
    request = _request_bytes(Path(candidate_dir), candidate_bundle, body, config)

    pair_id = f"pair-{uuid.uuid4().hex}"
    pair_root = Path(output_root) / str(candidate["candidate_sha256"]) / pair_id
    pair_root.mkdir(parents=True, exist_ok=False)
    condition_values: dict[str, bytes] = {}
    run_dirs: dict[str, Path] = {}
    for arm in ("baseline", "treatment"):
        condition = _bound_file(
            Path(candidate_dir),
            candidate_bundle["manifest"]["conditions"][arm],
            f"{arm} condition",
        )
        condition_values[arm] = condition
        run_dirs[arm] = _prepare_run(
            pair_root=pair_root,
            arm=arm,
            request=request,
            body=body,
            config=config,
            condition=condition,
            scorer_raw=scorer_raw,
        )
    if _sha(condition_values["baseline"]) == _sha(condition_values["treatment"]):
        _fail("CONDITION_MISMATCH", "shadow conditions are not distinct")

    stable_environment = dict(os.environ if environment is None else environment)
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
    except Exception:
        for process in processes.values():
            if process.poll() is None:
                process.kill()
                process.communicate()
        raise

    finished: dict[str, dict[str, object]] = {}
    for arm in ("baseline", "treatment"):
        stdout, stderr = outputs[arm]
        finished[arm] = _finish_outcome(
            run_dir=run_dirs[arm],
            arm=arm,
            run_id=f"{pair_id}-{arm}",
            process_id=processes[arm].pid,
            command=command,
            environment_sha256=environment_sha,
            candidate=candidate,
            stdout=stdout,
            stderr=stderr,
            request=request,
            body=body,
            config=config,
            condition=condition_values[arm],
            scorer=scorer,
            scorer_raw=scorer_raw,
        )
    baseline_verified = verify_shadow_outcome_bundle(
        Path(str(finished["baseline"]["directory"])), candidate_dir=Path(candidate_dir)
    )
    treatment_verified = verify_shadow_outcome_bundle(
        Path(str(finished["treatment"]["directory"])), candidate_dir=Path(candidate_dir)
    )
    if (
        baseline_verified["consumer_session_identity"]
        == treatment_verified["consumer_session_identity"]
    ):
        _fail("RUN_NOT_INDEPENDENT", "shadow arms reused one consumer session")
    try:
        receipt = qualify_taste_candidate(
            candidate=candidate,
            baseline_outcome=baseline_verified["outcome"],
            treatment_outcome=treatment_verified["outcome"],
        )
    except TasteQualificationError as exc:
        raise TasteShadowRunnerError(exc.reason_code, str(exc)) from exc
    receipt_raw = canonical_json_bytes(receipt)
    _write_bytes(pair_root / "qualification.receipt.json", receipt_raw)
    pair_manifest = _seal(
        {
            "schema_version": PAIR_BUNDLE_SCHEMA,
            "authority": False,
            "cold_only": True,
            "live_activation_allowed": False,
            "candidate_sha256": candidate["candidate_sha256"],
            "pair_id": pair_id,
            "same_inputs": {
                "request_sha256": _sha(request),
                "body_sha256": _sha(body),
                "config_sha256": _sha(config),
                "scorer_sha256": _sha(scorer_raw),
                "command_sha256": _sha(canonical_json_bytes(list(command))),
                "environment_sha256": environment_sha,
            },
            "distinct_conditions": {
                arm: _sha(condition_values[arm]) for arm in ("baseline", "treatment")
            },
            "outcome_bundles": {
                "baseline": baseline_verified["bundle_sha256"],
                "treatment": treatment_verified["bundle_sha256"],
            },
            "qualification_receipt": _binding("qualification.receipt.json", receipt_raw),
        },
        "pair_bundle_sha256",
    )
    _write_bytes(pair_root / "pair_manifest.json", canonical_json_bytes(pair_manifest))
    return {
        "pair_directory": str(pair_root.resolve()),
        "baseline_directory": str(run_dirs["baseline"].resolve()),
        "treatment_directory": str(run_dirs["treatment"].resolve()),
        "baseline_outcome_path": str((run_dirs["baseline"] / "outcome.json").resolve()),
        "treatment_outcome_path": str((run_dirs["treatment"] / "outcome.json").resolve()),
        "qualification_receipt_path": str((pair_root / "qualification.receipt.json").resolve()),
        "pair_bundle_sha256": pair_manifest["pair_bundle_sha256"],
        "qualified": True,
        "live_activation_allowed": False,
    }


def verify_shadow_pair(pair_dir: Path, *, candidate_dir: Path) -> dict[str, object]:
    from services.agent_runtime.taste_corpus import verify_candidate_bundle

    root = Path(pair_dir)
    candidate = verify_candidate_bundle(candidate_dir)["candidate"]
    manifest, _ = _canonical_json_file(root / "pair_manifest.json", "shadow pair manifest")
    pair_sha = _verify_seal(manifest, "pair_bundle_sha256")
    if (
        manifest.get("schema_version") != PAIR_BUNDLE_SCHEMA
        or manifest.get("authority") is not False
        or manifest.get("cold_only") is not True
        or manifest.get("live_activation_allowed") is not False
        or manifest.get("candidate_sha256") != candidate["candidate_sha256"]
    ):
        _fail("BUNDLE_POLICY_INVALID", "shadow pair policy or candidate differs")
    baseline = verify_shadow_outcome_bundle(root / "baseline", candidate_dir=candidate_dir)
    treatment = verify_shadow_outcome_bundle(root / "treatment", candidate_dir=candidate_dir)
    if (
        baseline["consumer_session_identity"] == treatment["consumer_session_identity"]
        or baseline["process_id"] == treatment["process_id"]
    ):
        _fail("RUN_NOT_INDEPENDENT", "shadow pair reused one consumer session")
    if baseline["same_inputs"] != treatment["same_inputs"]:
        _fail("TWIN_INPUT_MISMATCH", "shadow arms differ outside the condition")
    if baseline["condition_sha256"] == treatment["condition_sha256"]:
        _fail("CONDITION_MISMATCH", "shadow arm conditions are identical")
    if manifest.get("same_inputs") != baseline["same_inputs"] or manifest.get(
        "distinct_conditions"
    ) != {
        "baseline": baseline["condition_sha256"],
        "treatment": treatment["condition_sha256"],
    }:
        _fail("TWIN_INPUT_MISMATCH", "pair twin contract differs from outcome bytes")
    receipt_binding = manifest.get("qualification_receipt")
    if not isinstance(receipt_binding, Mapping):
        _fail("BINDING_INVALID", "qualification receipt binding is missing")
    receipt_value = _json_object(
        _bound_file(root, receipt_binding, "qualification receipt"), "qualification receipt"
    )
    try:
        receipt = validate_taste_qualification_receipt(
            receipt_value,
            candidate=candidate,
            baseline_outcome=baseline["outcome"],
            treatment_outcome=treatment["outcome"],
        )
    except TasteQualificationError as exc:
        raise TasteShadowRunnerError(exc.reason_code, str(exc)) from exc
    expected_bundles = manifest.get("outcome_bundles")
    if expected_bundles != {
        "baseline": baseline["bundle_sha256"],
        "treatment": treatment["bundle_sha256"],
    }:
        _fail("BINDING_MISMATCH", "pair outcome bundle identities drifted")
    return {
        "pair_bundle_sha256": pair_sha,
        "candidate_sha256": candidate["candidate_sha256"],
        "qualification_receipt_sha256": receipt["receipt_sha256"],
        "baseline": baseline,
        "treatment": treatment,
        "live_activation_allowed": False,
    }


__all__ = [
    "CONSUMER_OUTPUT_SCHEMA",
    "SCORER_SCHEMA",
    "TasteShadowRunnerError",
    "run_fresh_shadow_pair",
    "score_consumer_output",
    "validate_scorer_spec",
    "verify_shadow_outcome_bundle",
    "verify_shadow_pair",
]
