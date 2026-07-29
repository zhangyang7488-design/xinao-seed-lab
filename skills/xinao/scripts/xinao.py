from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence

SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = SKILL_ROOT / "references"
DEFAULT_STATE_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill")
DEFAULT_RUN_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\runs\xinao_researcher")
DEFAULT_AUTH_PATH = Path(r"C:\Users\xx363\.grok-bg-workers\auth.json")

REGISTRY_PATH = REFERENCE_ROOT / "capabilities.v1.json"
CHARTER_PATH = REFERENCE_ROOT / "researcher-charter.v1.json"
OUTPUT_SCHEMA_PATH = REFERENCE_ROOT / "researcher-output.v1.schema.json"
RUNTIME_LOCK_PATH = REFERENCE_ROOT / "researcher-runtime-lock.v1.json"

FORBIDDEN_RUNTIME_TOKENS = (
    "grok_worker_pool",
    "codex_task_runs",
    "selection_receipt",
    "common_contract",
    "integrated_bus",
)


class XinaoError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


class XinaoArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise XinaoError("INVOCATION_ARGUMENTS_INVALID", message)


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XinaoError("JSON_READ_FAILED", f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise XinaoError("JSON_OBJECT_REQUIRED", str(path))
    return value


def _write_json_atomic(path: Path, value: dict[str, Any], *, create_new: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if create_new and path.exists():
        temporary.unlink(missing_ok=True)
        raise XinaoError("IMMUTABLE_PATH_EXISTS", str(path))
    os.replace(temporary, path)


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(arguments),
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise XinaoError(
            "PROCESS_FAILED",
            f"exit={completed.returncode} command={arguments[0]} stderr={completed.stderr[:2000]}",
        )
    return completed


def _docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise XinaoError("DOCKER_CLI_MISSING", "docker was not found")
    return docker


def _docker_image(docker: str, image: str) -> dict[str, Any]:
    completed = _run([docker, "image", "inspect", image], timeout=60)
    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise XinaoError("DOCKER_IMAGE_INSPECT_INVALID", image) from exc
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise XinaoError("DOCKER_IMAGE_INSPECT_INVALID", image)
    return values[0]


def _reference_hashes(root: Path = SKILL_ROOT) -> dict[str, str]:
    return {
        "skill_md_sha256": _sha256(root / "SKILL.md"),
        "skill_invoker_sha256": _sha256(root / "scripts" / "xinao.py"),
        "capability_registry_sha256": _sha256(root / "references" / "capabilities.v1.json"),
        "charter_sha256": _sha256(root / "references" / "researcher-charter.v1.json"),
        "output_schema_sha256": _sha256(root / "references" / "researcher-output.v1.schema.json"),
        "runtime_lock_sha256": _sha256(root / "references" / "researcher-runtime-lock.v1.json"),
        "meta_sha256": _sha256(root / "references" / "meta.md"),
    }


def _validate_registry() -> dict[str, Any]:
    registry = _load_json(REGISTRY_PATH)
    if registry.get("schema_version") != "xinao.skill_capability_registry.v1":
        raise XinaoError("REGISTRY_SCHEMA_INVALID", str(REGISTRY_PATH))
    if registry.get("ordinary_worker_chain_allowed") is not False:
        raise XinaoError("GENERIC_WORKER_ROUTE_NOT_FORBIDDEN", str(REGISTRY_PATH))
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list):
        raise XinaoError("CAPABILITY_LIST_INVALID", str(REGISTRY_PATH))
    researcher = [
        item
        for item in capabilities
        if isinstance(item, dict) and item.get("capability_id") == "researcher-container"
    ]
    if len(researcher) != 1 or researcher[0].get("source_status") != "available":
        raise XinaoError("RESEARCHER_CAPABILITY_NOT_AVAILABLE", str(REGISTRY_PATH))
    return registry


def _validate_charter() -> dict[str, Any]:
    charter = _load_json(CHARTER_PATH)
    if charter.get("research_space") != "open":
        raise XinaoError("RESEARCH_SPACE_NOT_OPEN", str(CHARTER_PATH))
    forbidden_admission_fields = {
        "ResearchTopicWhitelist",
        "research_topic_whitelist",
        "allowed_topics",
        "required_family",
    }
    if forbidden_admission_fields.intersection(charter):
        raise XinaoError("RESEARCH_TOPIC_WHITELIST_FORBIDDEN", str(CHARTER_PATH))
    prior = charter.get("seven_family_attention_prior")
    action_ref = charter.get("action_support_reference")
    if not isinstance(prior, dict) or prior.get("binding") is not False:
        raise XinaoError("ATTENTION_PRIOR_BECAME_BINDING", str(CHARTER_PATH))
    if not isinstance(prior.get("families"), list) or len(prior["families"]) != 7:
        raise XinaoError("ATTENTION_PRIOR_IDENTITY_INVALID", str(CHARTER_PATH))
    if not isinstance(action_ref, dict) or action_ref.get("binding_on_research") is not False:
        raise XinaoError("ACTION_REFERENCE_BECAME_RESEARCH_GATE", str(CHARTER_PATH))
    return charter


def _state_roots() -> tuple[Path, Path]:
    state_root = Path(os.environ.get("XINAO_SKILL_STATE_ROOT", str(DEFAULT_STATE_ROOT)))
    run_root = Path(os.environ.get("XINAO_RESEARCHER_RUN_ROOT", str(DEFAULT_RUN_ROOT)))
    return state_root, run_root


def _current_release() -> tuple[dict[str, Any], Path, str]:
    state_root, _ = _state_roots()
    pointer_path = state_root / "researcher_container" / "current.json"
    pointer = _load_json(pointer_path)
    if pointer.get("schema_version") != "xinao.researcher_current_pointer.v1":
        raise XinaoError("CURRENT_POINTER_SCHEMA_INVALID", str(pointer_path))
    manifest_path = Path(str(pointer.get("release_manifest_path", "")))
    expected = str(pointer.get("release_manifest_sha256", ""))
    if not manifest_path.is_file() or _sha256(manifest_path) != expected:
        raise XinaoError("RELEASE_MANIFEST_IDENTITY_MISMATCH", str(manifest_path))
    return _load_json(manifest_path), manifest_path, _sha256(pointer_path)


def inspect_capability() -> dict[str, Any]:
    registry = _validate_registry()
    charter = _validate_charter()
    result: dict[str, Any] = {
        "schema_version": "xinao.skill_inspection.v1",
        "skill_id": "xinao",
        "skill_version": registry["skill_version"],
        "research_space": charter["research_space"],
        "ordinary_worker_chain_allowed": False,
        "user_operations_required": [],
        "source_capabilities": registry["capabilities"],
        "runtime_status": "ABSENT",
    }
    try:
        release, manifest_path, pointer_sha = _current_release()
    except XinaoError as exc:
        result["runtime_reason_code"] = exc.reason_code
        result["runtime_detail"] = exc.detail
        return result
    result.update(
        {
            "runtime_status": "AVAILABLE",
            "release_id": release.get("release_id"),
            "release_manifest_path": str(manifest_path),
            "release_manifest_sha256": _sha256(manifest_path),
            "current_pointer_sha256": pointer_sha,
            "image_id": release.get("image_id"),
        }
    )
    return result


def build_release(source_root: Path, *, promote: bool, allow_dirty: bool) -> dict[str, Any]:
    source_root = source_root.resolve()
    source_skill = source_root / "skills" / "xinao"
    dockerfile = source_root / "docker" / "xinao-researcher" / "Dockerfile"
    entrypoint = source_root / "docker" / "xinao-researcher" / "entrypoint.py"
    if not source_skill.is_dir() or not dockerfile.is_file() or not entrypoint.is_file():
        raise XinaoError("SOURCE_CONE_MISSING", str(source_root))
    status = _run(["git", "status", "--porcelain"], cwd=source_root).stdout.strip()
    if status and not allow_dirty:
        raise XinaoError("SOURCE_TREE_DIRTY", status)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=source_root).stdout.strip()
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=source_root).stdout.strip()
    lock = _load_json(source_skill / "references" / "researcher-runtime-lock.v1.json")
    if lock.get("generic_worker_route_allowed") is not False:
        raise XinaoError("GENERIC_WORKER_ROUTE_NOT_FORBIDDEN", str(RUNTIME_LOCK_PATH))
    docker = _docker()
    donor = str(lock.get("grok_donor_image", ""))
    expected_donor_id = str(lock.get("grok_donor_image_id", ""))
    observed_donor_id = str(_docker_image(docker, donor).get("Id", ""))
    if observed_donor_id != expected_donor_id:
        raise XinaoError(
            "GROK_DONOR_IMAGE_DRIFT",
            f"expected={expected_donor_id} observed={observed_donor_id}",
        )
    hashes = _reference_hashes(source_skill)
    hashes.update(
        {
            "dockerfile_sha256": _sha256(dockerfile),
            "entrypoint_sha256": _sha256(entrypoint),
        }
    )
    identity = {
        "source_commit": commit,
        "source_tree": tree,
        "source_dirty": bool(status),
        "grok_donor_image_id": observed_donor_id,
        **hashes,
    }
    identity_sha = _sha256_bytes(_canonical_bytes(identity))
    release_id = f"researcher-1.0.0-{identity_sha[:16]}"
    image_tag = f"xinao-researcher:{release_id}"
    build_args = [
        docker,
        "build",
        "--file",
        str(dockerfile),
        "--tag",
        image_tag,
        "--build-arg",
        f"GROK_DONOR_IMAGE={donor}",
        "--build-arg",
        f"GROK_DONOR_IMAGE_ID={observed_donor_id}",
        "--build-arg",
        f"CHARTER_SHA256={hashes['charter_sha256']}",
        "--build-arg",
        f"OUTPUT_SCHEMA_SHA256={hashes['output_schema_sha256']}",
        "--build-arg",
        f"RUNTIME_LOCK_SHA256={hashes['runtime_lock_sha256']}",
        "--build-arg",
        f"SKILL_INVOKER_SHA256={hashes['skill_invoker_sha256']}",
        str(source_root),
    ]
    _run(build_args, cwd=source_root, timeout=1800)
    image = _docker_image(docker, image_tag)
    image_id = str(image.get("Id", ""))
    labels = (image.get("Config") or {}).get("Labels") or {}
    expected_labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": observed_donor_id,
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
    }
    if any(labels.get(key) != value for key, value in expected_labels.items()):
        raise XinaoError("IMAGE_LABEL_IDENTITY_MISMATCH", image_id)
    state_root, _ = _state_roots()
    release_dir = state_root / "researcher_container" / "releases" / release_id
    manifest_path = release_dir / "release.json"
    candidate_manifest = {
        "schema_version": "xinao.researcher_release.v1",
        "release_id": release_id,
        "created_at": _utc_now(),
        "source_identity": identity,
        "image_tag_observational": image_tag,
        "image_id": image_id,
        "image_entrypoint": (image.get("Config") or {}).get("Entrypoint"),
        "image_labels": expected_labels,
        "skill_hashes": hashes,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        stable_fields = (
            "schema_version",
            "release_id",
            "source_identity",
            "image_id",
            "image_labels",
            "skill_hashes",
            "generic_worker_route_allowed",
            "state_namespace",
            "run_namespace",
        )
        if any(manifest.get(key) != candidate_manifest.get(key) for key in stable_fields):
            raise XinaoError("RELEASE_ID_COLLISION", str(manifest_path))
    else:
        manifest = candidate_manifest
        _write_json_atomic(manifest_path, manifest, create_new=True)
    manifest_sha = _sha256(manifest_path)
    if promote:
        pointer_path = state_root / "researcher_container" / "current.json"
        previous_pointer_sha256 = _sha256(pointer_path) if pointer_path.is_file() else None
        previous_pointer = _load_json(pointer_path) if pointer_path.is_file() else {}
        pointer = {
            "schema_version": "xinao.researcher_current_pointer.v1",
            "release_id": release_id,
            "release_manifest_path": str(manifest_path),
            "release_manifest_sha256": manifest_sha,
            "promoted_at": _utc_now(),
            "previous_pointer_sha256": previous_pointer_sha256,
            "previous_release_id": previous_pointer.get("release_id"),
            "previous_release_manifest_path": previous_pointer.get("release_manifest_path"),
            "previous_release_manifest_sha256": previous_pointer.get("release_manifest_sha256"),
        }
        observed_pointer_sha256 = _sha256(pointer_path) if pointer_path.is_file() else None
        if observed_pointer_sha256 != previous_pointer_sha256:
            raise XinaoError("CURRENT_POINTER_CAS_CONFLICT", str(pointer_path))
        _write_json_atomic(pointer_path, pointer)
    return {
        "schema_version": "xinao.researcher_build_receipt.v1",
        "release_id": release_id,
        "image_id": image_id,
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": manifest_sha,
        "promoted": promote,
        "source_dirty": bool(status),
        "completion_claim_allowed": False,
    }


def rollback_release() -> dict[str, Any]:
    state_root, _ = _state_roots()
    pointer_path = state_root / "researcher_container" / "current.json"
    current = _load_json(pointer_path)
    current_sha256 = _sha256(pointer_path)
    previous_path = Path(str(current.get("previous_release_manifest_path", "")))
    previous_sha256 = str(current.get("previous_release_manifest_sha256", ""))
    previous_release_id = str(current.get("previous_release_id", ""))
    if not previous_release_id or not previous_path.is_file():
        raise XinaoError("ROLLBACK_TARGET_ABSENT", str(pointer_path))
    if _sha256(previous_path) != previous_sha256:
        raise XinaoError("ROLLBACK_TARGET_IDENTITY_MISMATCH", str(previous_path))
    previous_manifest = _load_json(previous_path)
    if previous_manifest.get("release_id") != previous_release_id:
        raise XinaoError("ROLLBACK_TARGET_RELEASE_MISMATCH", previous_release_id)
    if _sha256(pointer_path) != current_sha256:
        raise XinaoError("CURRENT_POINTER_CAS_CONFLICT", str(pointer_path))
    pointer = {
        "schema_version": "xinao.researcher_current_pointer.v1",
        "release_id": previous_release_id,
        "release_manifest_path": str(previous_path),
        "release_manifest_sha256": previous_sha256,
        "promoted_at": _utc_now(),
        "previous_pointer_sha256": current_sha256,
        "previous_release_id": current.get("release_id"),
        "previous_release_manifest_path": current.get("release_manifest_path"),
        "previous_release_manifest_sha256": current.get("release_manifest_sha256"),
    }
    _write_json_atomic(pointer_path, pointer)
    return {
        "schema_version": "xinao.researcher_rollback_receipt.v1",
        "status": "ROLLED_BACK",
        "release_id": previous_release_id,
        "release_manifest_sha256": previous_sha256,
        "current_pointer_sha256": _sha256(pointer_path),
        "completion_claim_allowed": False,
    }


def _compile_prompt(question: str, as_of: str, charter: dict[str, Any]) -> str:
    return (
        "You are one XINAO scientific researcher in a bounded candidate-only episode.\n"
        "Research freely: there is no topic whitelist and no required family binding. The seven-family "
        "weights below are advisory attention only. The ACTION support reference is downstream and must "
        "not filter, coerce, or discard research. Do not create accounts, tickets, freezes, settlements, "
        "replays, real-money actions, SCIENCE_RESTORED, or parent-completion claims. Use no tools.\n\n"
        f"As-of: {as_of}\n"
        f"Research question: {question}\n\n"
        "Charter:\n"
        f"{json.dumps(charter, ensure_ascii=False, sort_keys=True)}\n\n"
        "Return only the JSON object required by the supplied schema. Preserve an out-of-domain finding "
        "as research and mark current_action_projection UNSUPPORTED or NOT_ASSESSED instead of mapping it "
        "to the nearest family."
    )


def _validate_release_for_invoke(release: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _validate_registry()
    charter = _validate_charter()
    if release.get("generic_worker_route_allowed") is not False:
        raise XinaoError("RELEASE_CHAIN_CLASS_INVALID", "generic worker route is not forbidden")
    for value in (
        str(release.get("state_namespace", "")),
        str(release.get("run_namespace", "")),
    ):
        normalized = value.lower().replace("-", "_")
        if any(token in normalized for token in FORBIDDEN_RUNTIME_TOKENS):
            raise XinaoError("CROSS_CHAIN_NAMESPACE_FORBIDDEN", value)
    observed_hashes = _reference_hashes()
    expected_hashes = release.get("skill_hashes")
    if not isinstance(expected_hashes, dict):
        raise XinaoError("RELEASE_SKILL_HASHES_MISSING", "skill_hashes")
    for key, value in observed_hashes.items():
        if expected_hashes.get(key) != value:
            raise XinaoError("INSTALLED_SKILL_DRIFT", key)
    docker = _docker()
    image_id = str(release.get("image_id", ""))
    image = _docker_image(docker, image_id)
    if image.get("Id") != image_id:
        raise XinaoError("IMAGE_IDENTITY_MISMATCH", image_id)
    labels = (image.get("Config") or {}).get("Labels") or {}
    if labels.get("io.xinao.researcher.chain") != "dedicated-xinao-science":
        raise XinaoError("IMAGE_CHAIN_LABEL_INVALID", image_id)
    if labels.get("io.xinao.researcher.generic-worker-route") != "forbidden":
        raise XinaoError("IMAGE_GENERIC_ROUTE_NOT_FORBIDDEN", image_id)
    return docker, charter


def _mount_source(mount: dict[str, Any]) -> str:
    return str(mount.get("Source", "")).lower().replace("\\", "/")


def _validate_container_inspect(
    inspect: dict[str, Any],
    *,
    image_id: str,
    input_root: Path,
    output_root: Path,
    auth_path: Path,
) -> None:
    host = inspect.get("HostConfig") or {}
    config = inspect.get("Config") or {}
    if inspect.get("Image") != image_id:
        raise XinaoError("CONTAINER_IMAGE_IDENTITY_MISMATCH", str(inspect.get("Image")))
    if host.get("ReadonlyRootfs") is not True:
        raise XinaoError("CONTAINER_ROOTFS_NOT_READ_ONLY", "ReadonlyRootfs")
    if "ALL" not in (host.get("CapDrop") or []):
        raise XinaoError("CONTAINER_CAP_DROP_INVALID", str(host.get("CapDrop")))
    if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
        raise XinaoError("CONTAINER_NO_NEW_PRIVILEGES_MISSING", str(host.get("SecurityOpt")))
    if host.get("NetworkMode") != "bridge":
        raise XinaoError("CONTAINER_NETWORK_PROFILE_INVALID", str(host.get("NetworkMode")))
    if config.get("Env") is None or "XINAO_CHAIN_CLASS=scientific_researcher" not in config["Env"]:
        raise XinaoError("CONTAINER_CHAIN_IDENTITY_MISSING", "XINAO_CHAIN_CLASS")
    mounts = inspect.get("Mounts") or []
    observed = {_mount_source(item): (item.get("Destination"), item.get("RW")) for item in mounts}
    expected = {
        str(input_root).lower().replace("\\", "/"): ("/input", False),
        str(output_root).lower().replace("\\", "/"): ("/output", True),
        str(auth_path).lower().replace("\\", "/"): ("/grok-home/auth.json", False),
    }
    if observed != expected:
        raise XinaoError("CONTAINER_MOUNT_SET_INVALID", json.dumps(observed, sort_keys=True))
    forbidden_fragments = ("/desktop/", "/主线/", "/codex_task_runs/", "/grok_worker_pool/")
    if any(fragment in source for source in observed for fragment in forbidden_fragments):
        raise XinaoError("CONTAINER_FORBIDDEN_MOUNT", json.dumps(observed, sort_keys=True))


def _provider_effect_valid(result: dict[str, Any]) -> bool:
    usage = result.get("usage")
    model_usage = result.get("provider_model_usage")
    return (
        result.get("provider_stop_reason") == "EndTurn"
        and isinstance(result.get("provider_num_turns"), int)
        and result["provider_num_turns"] >= 1
        and result.get("provider_session_id_present") is True
        and result.get("provider_request_id_present") is True
        and isinstance(usage, dict)
        and isinstance(usage.get("total_tokens"), int)
        and usage["total_tokens"] > 0
        and isinstance(model_usage, dict)
        and bool(model_usage)
    )


def research(question: str, as_of: str | None) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise XinaoError("RESEARCH_QUESTION_INVALID", "question is empty")
    if len(question.encode("utf-8")) > 128 * 1024:
        raise XinaoError("RESEARCH_QUESTION_TOO_LARGE", "question exceeds 128 KiB")
    release, manifest_path, pointer_sha = _current_release()
    docker, charter = _validate_release_for_invoke(release)
    if not DEFAULT_AUTH_PATH.is_file():
        raise XinaoError("GROK_AUTH_HANDLE_MISSING", str(DEFAULT_AUTH_PATH))
    auth_sha_before = _sha256(DEFAULT_AUTH_PATH)
    observed_os = _run([docker, "info", "--format", "{{json .OSType}}"], timeout=60).stdout.strip()
    if observed_os != '"linux"':
        raise XinaoError("LINUX_CONTAINER_ENGINE_REQUIRED", observed_os)

    _, run_root = _state_roots()
    run_id = (
        "xrr_" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:10]
    )
    root = run_root / run_id
    input_root = root / "input"
    output_root = root / "output"
    input_root.mkdir(parents=True, exist_ok=False)
    output_root.mkdir(parents=True, exist_ok=False)
    effective_as_of = as_of or _utc_now()
    request = {
        "schema_version": "xinao.research_request.v1",
        "research_question": question,
        "as_of": effective_as_of,
    }
    _write_json_atomic(input_root / "request.json", request, create_new=True)
    (input_root / "prompt.md").write_text(
        _compile_prompt(question, effective_as_of, charter), encoding="utf-8"
    )
    shutil.copyfile(OUTPUT_SCHEMA_PATH, input_root / "output.schema.json")

    image_id = str(release["image_id"])
    name = "xinao-researcher-" + run_id.lower().replace("_", "-")
    create = _run(
        [
            docker,
            "create",
            "--name",
            name,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "128",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--network",
            "bridge",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
            "--tmpfs",
            "/grok-home:rw,nosuid,nodev,size=256m,mode=0700",
            "--env",
            "XINAO_CHAIN_CLASS=scientific_researcher",
            "--mount",
            f"type=bind,source={input_root},target=/input,readonly",
            "--mount",
            f"type=bind,source={output_root},target=/output",
            "--mount",
            f"type=bind,source={DEFAULT_AUTH_PATH},target=/grok-home/auth.json,readonly",
            image_id,
        ],
        timeout=120,
    )
    container_id = create.stdout.strip()
    if not container_id:
        raise XinaoError("CONTAINER_CREATE_OUTPUT_INVALID", create.stdout)
    terminal: dict[str, Any] = {}
    try:
        inspected_values = json.loads(_run([docker, "inspect", container_id]).stdout)
        if not isinstance(inspected_values, list) or len(inspected_values) != 1:
            raise XinaoError("CONTAINER_INSPECT_INVALID", container_id)
        inspected = inspected_values[0]
        _validate_container_inspect(
            inspected,
            image_id=image_id,
            input_root=input_root,
            output_root=output_root,
            auth_path=DEFAULT_AUTH_PATH,
        )
        started = _run([docker, "start", "--attach", container_id], timeout=1000, check=False)
        terminal_values = json.loads(_run([docker, "inspect", container_id]).stdout)
        terminal = terminal_values[0].get("State") or {}
        if started.returncode != 0:
            raise XinaoError(
                "CONTAINER_RUNTIME_FAILED",
                f"exit={started.returncode} stderr={started.stderr[:2000]}",
            )
    finally:
        _run([docker, "rm", "--force", container_id], timeout=60, check=False)
    if _sha256(DEFAULT_AUTH_PATH) != auth_sha_before:
        raise XinaoError("GROK_AUTH_HANDLE_MUTATED", str(DEFAULT_AUTH_PATH))
    result_path = output_root / "result.json"
    result = _load_json(result_path)
    if result.get("status") not in {"CANDIDATE_READY", "EXPLICIT_NO_ACTION"}:
        raise XinaoError(
            "RESEARCH_RESULT_NOT_ACCEPTED", json.dumps(result, ensure_ascii=False)[:2000]
        )
    if not _provider_effect_valid(result):
        raise XinaoError("PROVIDER_EFFECT_EVIDENCE_INVALID", str(result_path))
    host_config = inspected.get("HostConfig") or {}
    mounts = inspected.get("Mounts") or []
    receipt = {
        "schema_version": "xinao.skill_research_receipt.v1",
        "run_id": run_id,
        "status": result["status"],
        "candidate": result.get("candidate"),
        "reason_codes": result.get("reason_codes", []),
        "release_id": release["release_id"],
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": _sha256(manifest_path),
        "current_pointer_sha256": pointer_sha,
        "image_id": image_id,
        "container_id": container_id,
        "container_exit_code": terminal.get("ExitCode"),
        "container_security": {
            "readonly_rootfs": host_config.get("ReadonlyRootfs"),
            "cap_drop": host_config.get("CapDrop"),
            "security_opt": host_config.get("SecurityOpt"),
            "network_mode": host_config.get("NetworkMode"),
            "pids_limit": host_config.get("PidsLimit"),
            "memory": host_config.get("Memory"),
            "nano_cpus": host_config.get("NanoCpus"),
            "mounts": [
                {
                    "source": item.get("Source"),
                    "destination": item.get("Destination"),
                    "rw": item.get("RW"),
                }
                for item in mounts
            ],
        },
        "container_removed": _run(
            [docker, "container", "inspect", container_id], timeout=30, check=False
        ).returncode
        != 0,
        "request_sha256": _sha256(input_root / "request.json"),
        "prompt_sha256": _sha256(input_root / "prompt.md"),
        "result_sha256": _sha256(result_path),
        "result_path": str(result_path),
        "created_at": _utc_now(),
        "route_class": "scientific_researcher",
        "ordinary_worker_chain_used": False,
        "provider_evidence": {
            "stop_reason": result.get("provider_stop_reason"),
            "num_turns": result.get("provider_num_turns"),
            "session_id_present": result.get("provider_session_id_present"),
            "request_id_present": result.get("provider_request_id_present"),
            "model_usage": result.get("provider_model_usage"),
            "usage": result.get("usage"),
        },
        "auth_handle_unchanged": True,
        "user_operations_required": [],
        "owner_adopted": False,
        "research_progress_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "completion_claim_allowed": False,
    }
    receipt_path = root / "receipt.json"
    _write_json_atomic(receipt_path, receipt, create_new=True)
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = _sha256(receipt_path)
    return receipt


def _error_envelope(error: XinaoError) -> dict[str, Any]:
    return {
        "schema_version": "xinao.skill_error.v1",
        "status": "PREFLIGHT_FAILED",
        "reason_codes": [error.reason_code],
        "detail": error.detail,
        "user_operations_required": [],
        "science_restored": False,
        "parent_complete": False,
        "completion_claim_allowed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = XinaoArgumentParser(prog="xinao-skill")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect")
    build = sub.add_parser("build")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--promote", action="store_true")
    build.add_argument("--allow-dirty", action="store_true")
    sub.add_parser("rollback")
    invoke = sub.add_parser("research")
    invoke.add_argument("--question", required=True)
    invoke.add_argument("--as-of", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "inspect":
            value = inspect_capability()
        elif args.command == "build":
            value = build_release(
                args.source_root, promote=args.promote, allow_dirty=args.allow_dirty
            )
        elif args.command == "rollback":
            value = rollback_release()
        else:
            value = research(args.question, args.as_of)
    except XinaoError as error:
        print(json.dumps(_error_envelope(error), ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
