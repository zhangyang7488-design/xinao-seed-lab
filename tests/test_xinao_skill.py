from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
FAKE_DONOR_BINARY_PAYLOAD = b"fake-grok-donor-binary-for-sp-b-001-tests\n"
FAKE_DONOR_BINARY_SHA256 = hashlib.sha256(FAKE_DONOR_BINARY_PAYLOAD).hexdigest()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao_runtime.py", "xinao_runtime_under_test")


def _bootstrap_module():
    return _load_module(SKILL_ROOT / "scripts" / "xinao.py", "xinao_bootstrap_under_test")


def _auth(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_AUTH_PATH", auth)
    return auth


def _state(module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state))
    monkeypatch.setenv("XINAO_RESEARCHER_RUN_ROOT", str(tmp_path / "runs"))
    lock = state / "researcher_container" / ".activation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"\0")
    return state


def _sealed_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str = "a",
    dirty: bool = False,
    variant: bytes | None = None,
) -> tuple[dict[str, object], Path]:
    state = _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    if variant is not None:
        source_rows.append(
            (
                "references/test-release-variant.txt",
                tmp_path / "unused-source-path",
                variant,
            )
        )
        source_rows.sort(key=lambda item: item[0])
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version="1.2.0")
    hashes = module._reference_hashes(SKILL_ROOT)
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": dirty,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
    }
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    image_id = "sha256:" + image_character * 64
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity[
            "grok_donor_binary_sha256"
        ],
        "io.xinao.researcher.charter.sha256": hashes["charter_sha256"],
        "io.xinao.researcher.output-schema.sha256": hashes["output_schema_sha256"],
        "io.xinao.researcher.material-bundle-schema.sha256": hashes[
            "material_bundle_schema_sha256"
        ],
        "io.xinao.researcher.runtime-lock.sha256": hashes["runtime_lock_sha256"],
        "io.xinao.researcher.skill-invoker.sha256": hashes["skill_invoker_sha256"],
        "io.xinao.researcher.dockerfile.sha256": "1" * 64,
        "io.xinao.researcher.entrypoint.sha256": "2" * 64,
        "io.xinao.researcher.source-identity.sha256": source_identity_sha256,
        "io.xinao.researcher.requested-model": "grok-4.5",
    }
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": "1.2.0",
        "capability_id": "researcher-container",
        "capability_version": "1.1.0",
        "charter_version": "1.1.0",
        "runtime_version": "1.1.0",
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:test",
        "image_id": image_id,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_labels": labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    identity_sha256 = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(manifest))
    )
    release_id = f"researcher-1.1.0-{identity_sha256[:16]}"
    release_root = state / "researcher_container" / "releases" / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity_sha256,
            "skill_bundle_path": str(release_root / "skill-bundle"),
            "skill_bundle_manifest_path": str(release_root / "skill-bundle.manifest.json"),
            "skill_bundle_manifest_sha256": module._sha256_bytes(
                module._canonical_bytes(bundle_manifest)
            ),
        }
    )
    module._materialize_skill_bundle(release_root / "skill-bundle", source_rows, bundle_manifest)
    module._write_json_atomic(
        release_root / "skill-bundle.manifest.json", bundle_manifest, create_new=True
    )
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    module._validate_release_manifest(manifest, manifest_path)
    return manifest, manifest_path


def _terminal_pointer(
    module,
    manifest: dict[str, object],
    manifest_path: Path,
    *,
    generation: int = 1,
    txn_suffix: str = "1" * 16,
    previous_verified: dict[str, object] | None = None,
    state: str = "VERIFIED",
) -> tuple[dict[str, object], dict[str, object], Path]:
    txn_id = f"xra_20260730T120000_{txn_suffix}"
    active = module._release_ref_from_manifest(manifest, manifest_path, activation_txn_id=txn_id)
    pointer = {
        "schema_version": module.CURRENT_POINTER_SCHEMA,
        "generation": generation,
        "active": active,
        "previous_verified": previous_verified,
        "switched_at": "2026-07-30T12:00:00Z",
    }
    journal_path = module._journal_path(txn_id)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    canary_path = journal_path.parent / "canary.receipt.json"
    module._write_json_atomic(canary_path, {"status": "PASS"}, create_new=True)
    journal = {
        "schema_version": module.ACTIVATION_JOURNAL_SCHEMA,
        "revision": 4,
        "txn_id": txn_id,
        "operation": "ACTIVATE",
        "state": state,
        "from": None,
        "requested_to": active,
        "to": active,
        "expected_generation": generation,
        "prepared_at": "2026-07-30T12:00:00Z",
        "updated_at": "2026-07-30T12:00:01Z",
        "switched_pointer_sha256": None,
        "canary": {
            "status": "PASS",
            "receipt_path": str(canary_path),
            "receipt_sha256": module._sha256(canary_path),
        },
        "failure_reason": None,
        "terminal_pointer_sha256": None,
    }
    module._write_json_atomic(journal_path, journal, create_new=True)
    pointer_path = module._state_paths()["pointer"]
    module._write_json_atomic(pointer_path, pointer)
    pointer_sha256 = module._sha256(pointer_path)
    journal["switched_pointer_sha256"] = pointer_sha256
    if state in module.TERMINAL_ACTIVATION_STATES:
        journal["terminal_pointer_sha256"] = pointer_sha256
    module._write_json_atomic(journal_path, journal)
    return pointer, journal, journal_path


def _install_bootstrap_fence(
    module,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> dict[str, object]:
    state_root = module._state_paths()["state_root"]
    bootstrap = _bootstrap_module()
    _runtime_path, _runtime_payload, fence = bootstrap._runtime_entry_locked(command, state_root)
    monkeypatch.setattr(module, "_BOOTSTRAP_FENCE_CACHE", None)
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
    )
    return fence


def _set_syntactic_bootstrap_fence(
    module, monkeypatch: pytest.MonkeyPatch, state_root: Path
) -> dict[str, object]:
    fence: dict[str, object] = {
        "schema_version": module.BOOTSTRAP_FENCE_SCHEMA,
        "state_root": str(state_root),
        "pointer_sha256": "1" * 64,
        "pointer_generation": 1,
        "active_txn_id": "xra_20260730T120000_" + "1" * 16,
        "pending_txn_id": None,
        "selected_release_id": "researcher-1.1.0-" + "1" * 16,
        "selected_release_manifest_sha256": "2" * 64,
        "selected_skill_bundle_tree_sha256": "3" * 64,
        "selected_runtime_sha256": "4" * 64,
    }
    monkeypatch.setattr(module, "_BOOTSTRAP_FENCE_CACHE", None)
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, sort_keys=True, separators=(",", ":")),
    )
    return fence


def _canary_value(module, journal: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "xinao.researcher_activation_canary.v1",
        "status": "CANARY_READY",
        "txn_id": journal["txn_id"],
        "pointer_generation": journal["expected_generation"],
        "pointer_sha256": journal["switched_pointer_sha256"],
        "release_id": journal["to"]["release_id"],
        "release_manifest_sha256": journal["to"]["release_manifest_sha256"],
        "skill_bundle_tree_sha256": journal["to"]["skill_bundle_tree_sha256"],
        "provider_effect_verified": False,
        "completion_claim_allowed": False,
    }


def _parse_build_args(command: list[str]) -> dict[str, str]:
    args: dict[str, str] = {}
    for index, value in enumerate(command):
        if value == "--build-arg":
            key, argument = command[index + 1].split("=", 1)
            args[key] = argument
    return args


def _fake_build_environment(
    module,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dirty: bool,
    image_character: str = "e",
    donor_binary_payload: bytes = FAKE_DONOR_BINARY_PAYLOAD,
    on_before_build=None,
    fail_on: str | None = None,
) -> dict[str, object]:
    build_commands: list[list[str]] = []
    docker_commands: list[list[str]] = []
    fence_checks: list[tuple[str, object]] = []
    created_containers: list[str] = []
    removed_containers: list[str] = []
    fence = {"test_fence": "build"}
    donor_binary_sha256 = hashlib.sha256(donor_binary_payload).hexdigest()
    lock = json.loads(module.RUNTIME_LOCK_PATH.read_text(encoding="utf-8"))
    donor_id = str(lock["grok_donor_image_id"])
    donor_tag = str(lock["grok_donor_image"])
    live_containers: dict[str, dict[str, object]] = {}

    def fake_fence(command: str, *, expected=None):
        fence_checks.append((command, expected))
        assert command == "build"
        if expected is not None:
            assert expected == fence
        return dict(fence)

    def fake_run(arguments, **_kwargs):
        values = list(arguments)
        if values and values[0] == "docker":
            docker_commands.append(list(values))
        if values[:3] == ["git", "status", "--porcelain"]:
            return SimpleNamespace(stdout=" M source\n" if dirty else "", stderr="", returncode=0)
        if values[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="c" * 40, stderr="", returncode=0)
        if values[:3] == ["git", "rev-parse", "HEAD^{tree}"]:
            return SimpleNamespace(stdout="d" * 40, stderr="", returncode=0)
        if values[:2] == ["docker", "create"]:
            assert "--name" in values
            assert values[values.index("--name") + 1]
            assert "--entrypoint" in values
            assert values[values.index("--entrypoint") + 1] == "/bin/true"
            assert values[-1] == donor_id
            assert donor_tag not in values
            assert "start" not in values
            assert "-v" not in values
            assert "--volume" not in values
            assert "--mount" not in values
            name = values[values.index("--name") + 1]
            assert name.startswith(module.DONOR_EXTRACT_NAME_PREFIX)
            assert name not in live_containers
            if fail_on == "create":
                raise module.XinaoError("PROCESS_FAILED", "injected create failure")
            live_containers[name] = {
                "Image": donor_id,
                "State": {"Running": False, "Status": "created"},
                "HostConfig": {"Binds": None, "Mounts": None},
                "Mounts": [],
            }
            created_containers.append(name)
            return SimpleNamespace(stdout=name + "\n", stderr="", returncode=0)
        if values[:2] == ["docker", "inspect"]:
            name = values[2]
            if fail_on == "inspect":
                raise module.XinaoError("PROCESS_FAILED", "injected inspect failure")
            assert name in live_containers
            payload = json.dumps([live_containers[name]])
            return SimpleNamespace(stdout=payload, stderr="", returncode=0)
        if values[:2] == ["docker", "cp"]:
            assert len(values) == 4
            source = values[2]
            dest = Path(values[3])
            assert source.endswith(":/usr/local/bin/grok")
            container = source.split(":", 1)[0]
            assert container in live_containers
            assert "start" not in values
            if fail_on == "cp":
                raise module.XinaoError("PROCESS_FAILED", "injected cp failure")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(donor_binary_payload)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:3] == ["docker", "rm", "-f"] or values[:2] == ["docker", "rm"]:
            name = values[-1]
            live_containers.pop(name, None)
            removed_containers.append(name)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:2] == ["docker", "build"]:
            if on_before_build is not None:
                on_before_build(values)
            if fail_on == "build":
                build_commands.append(values)
                raise module.XinaoError("PROCESS_FAILED", "injected build failure")
            build_commands.append(values)
            args = _parse_build_args(values)
            assert "GROK_DONOR_IMAGE" not in args
            assert args.get("GROK_DONOR_IMAGE_ID") == donor_id
            assert args.get("GROK_DONOR_BINARY_SHA256") == donor_binary_sha256
            context = Path(values[-1])
            binary = context / module.DONOR_BINARY_CONTEXT_RELATIVE
            assert binary.is_file()
            assert binary.read_bytes() == donor_binary_payload
            assert not any(part == "start" for part in values)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        if values[:2] == ["docker", "start"]:
            raise AssertionError(f"donor container must never start: {values}")
        raise AssertionError(values)

    def fake_image(_docker: str, image: str) -> dict[str, object]:
        if image in {donor_tag, donor_id}:
            return {"Id": donor_id}
        assert build_commands
        command = build_commands[-1]
        args = _parse_build_args(command)
        labels = {
            "io.xinao.researcher.chain": "dedicated-xinao-science",
            "io.xinao.researcher.generic-worker-route": "forbidden",
            "io.xinao.researcher.grok-donor-image-id": args["GROK_DONOR_IMAGE_ID"],
            "io.xinao.researcher.grok-donor-binary.sha256": args["GROK_DONOR_BINARY_SHA256"],
            "io.xinao.researcher.charter.sha256": args["CHARTER_SHA256"],
            "io.xinao.researcher.output-schema.sha256": args["OUTPUT_SCHEMA_SHA256"],
            "io.xinao.researcher.material-bundle-schema.sha256": args[
                "MATERIAL_BUNDLE_SCHEMA_SHA256"
            ],
            "io.xinao.researcher.runtime-lock.sha256": args["RUNTIME_LOCK_SHA256"],
            "io.xinao.researcher.skill-invoker.sha256": args["SKILL_INVOKER_SHA256"],
            "io.xinao.researcher.dockerfile.sha256": args["DOCKERFILE_SHA256"],
            "io.xinao.researcher.entrypoint.sha256": args["ENTRYPOINT_SHA256"],
            "io.xinao.researcher.source-identity.sha256": args["SOURCE_IDENTITY_SHA256"],
            "io.xinao.researcher.requested-model": args["REQUESTED_MODEL"],
        }
        return {
            "Id": "sha256:" + image_character * 64,
            "Config": {
                "Labels": labels,
                "Entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
            },
        }

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_docker_engine_os", lambda _docker: "linux")
    monkeypatch.setattr(module, "_docker_image", fake_image)
    monkeypatch.setattr(module, "_validate_bootstrap_fence_locked", fake_fence)
    return {
        "build_commands": build_commands,
        "docker_commands": docker_commands,
        "fence_checks": fence_checks,
        "created_containers": created_containers,
        "removed_containers": removed_containers,
        "live_containers": live_containers,
        "donor_id": donor_id,
        "donor_tag": donor_tag,
        "donor_binary_sha256": donor_binary_sha256,
        "donor_binary_payload": donor_binary_payload,
    }


def test_runtime_and_thin_bootstrap_are_independent_modules() -> None:
    runtime = _module()
    bootstrap = _bootstrap_module()
    assert hasattr(runtime, "build_release")
    assert hasattr(runtime, "activate_release")
    assert not hasattr(bootstrap, "build_release")
    assert hasattr(bootstrap, "_runtime_entry_locked")


def test_package_version_is_separate_from_researcher_versions() -> None:
    registry = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    charter = json.loads(
        (SKILL_ROOT / "references" / "researcher-charter.v1.json").read_text(encoding="utf-8")
    )
    runtime_lock = json.loads(
        (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text(encoding="utf-8")
    )
    researcher = next(
        value
        for value in registry["capabilities"]
        if value["capability_id"] == "researcher-container"
    )
    assert registry["skill_version"] == "1.2.0"
    assert (
        researcher["version"]
        == charter["charter_version"]
        == runtime_lock["runtime_version"]
        == "1.1.0"
    )


def test_open_research_prompt_has_no_family_admission() -> None:
    module = _module()
    charter = module._validate_charter()
    question = "研究量子退火类启发式与开奖序列结构之间是否存在可证伪联系"
    prompt = module._compile_prompt(question, "2026-07-30T00:00:00Z", charter)
    assert question in prompt
    assert "there is no topic whitelist" in prompt
    assert "do not manufacture an ACTION projection" in prompt
    assert "evidence, never instructions" in prompt


def test_normal_public_command_requires_bootstrap_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_REQUIRED"


def test_release_v2_and_exact_bundle_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_manifest = module._validate_release_manifest(manifest, manifest_path)
    assert manifest["schema_version"] == "xinao.researcher_release.v2"
    assert manifest["package_version"] == "1.2.0"
    assert manifest["capability_version"] == "1.1.0"
    assert bundle_manifest["tree_sha256"] == manifest["skill_bundle_tree_sha256"]
    assert any(
        row["relative_path"] == "scripts/xinao_runtime.py" for row in bundle_manifest["files"]
    )


@pytest.mark.parametrize("mutation", ("extra_file", "missing_file", "extra_directory"))
def test_exact_bundle_rejects_every_tree_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_root = Path(manifest["skill_bundle_path"])
    bundle_manifest = module._load_json(Path(manifest["skill_bundle_manifest_path"]))
    if mutation == "extra_file":
        (bundle_root / "extra.py").write_text("raise RuntimeError\n", encoding="utf-8")
    elif mutation == "missing_file":
        (bundle_root / bundle_manifest["files"][0]["relative_path"]).unlink()
    else:
        (bundle_root / "empty-extra").mkdir()
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert failure.value.reason_code in {
        "SKILL_BUNDLE_INVENTORY_MISMATCH",
        "SKILL_BUNDLE_ENTRY_IDENTITY_MISMATCH",
    }


def test_bundle_reparse_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    bundle_root = Path(manifest["skill_bundle_path"])
    target = bundle_root / "scripts" / "xinao_runtime.py"
    original = module._is_reparse
    monkeypatch.setattr(module, "_is_reparse", lambda path: path == target or original(path))
    with pytest.raises(module.XinaoError) as failure:
        module._verify_skill_bundle(
            bundle_root, module._load_json(Path(manifest["skill_bundle_manifest_path"]))
        )
    assert failure.value.reason_code == "SKILL_BUNDLE_REPARSE_FORBIDDEN"


def test_runtime_activation_lock_is_safely_created_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    lock_path.unlink()
    with module._activation_lock():
        observed = os.lstat(lock_path)
        assert observed.st_nlink == 1
        assert observed.st_size >= 1
    assert lock_path.is_file()


def test_runtime_activation_lock_rejects_hardlink_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    alias = tmp_path / "activation-lock-alias"
    try:
        os.link(lock_path, alias)
    except OSError:
        pytest.skip("hardlinks unavailable")
    with pytest.raises(module.XinaoError) as failure:
        with module._activation_lock():
            pytest.fail("hardlinked lock must not be acquired")
    assert failure.value.reason_code == "ACTIVATION_LOCK_INVALID"


def test_runtime_activation_lock_detects_path_identity_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock_path = module._state_paths()["lock"]
    replacement = tmp_path / "replacement-lock"
    replacement.write_bytes(b"\0")
    original_lstat = os.lstat
    lock_lstat_calls = 0

    def replaced_lstat(path):
        nonlocal lock_lstat_calls
        if module._paths_equal(Path(path), lock_path):
            lock_lstat_calls += 1
            if lock_lstat_calls >= 3:
                return original_lstat(replacement)
        return original_lstat(path)

    monkeypatch.setattr(module.os, "lstat", replaced_lstat)
    with pytest.raises(module.XinaoError) as failure:
        with module._activation_lock():
            pytest.fail("replaced lock must not be acquired")
    assert failure.value.reason_code == "ACTIVATION_LOCK_CHANGED"
    assert lock_lstat_calls >= 3


def test_dockerfile_has_no_donor_from_or_raw_image_id_stage() -> None:
    """Real-failure regression: raw local image Id in FROM is unbuildable under BuildKit."""
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ARG GROK_DONOR_IMAGE=" not in dockerfile
    assert "ARG GROK_DONOR_IMAGE\n" not in dockerfile
    assert "AS grok_donor" not in dockerfile
    assert "COPY --from=grok_donor" not in dockerfile
    assert re.search(r"^FROM\s+\$\{?GROK_DONOR", dockerfile, flags=re.MULTILINE) is None
    assert re.search(r"^FROM\s+sha256:", dockerfile, flags=re.MULTILINE) is None
    assert "COPY donor-artifacts/grok" in dockerfile
    assert "GROK_DONOR_BINARY_SHA256" in dockerfile
    assert "ARG GROK_DONOR_IMAGE_ID" in dockerfile
    assert "io.xinao.researcher.grok-donor-binary.sha256" in dockerfile


def test_build_is_candidate_only_and_passes_complete_image_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=True)
    build_commands = env["build_commands"]
    fence_checks = env["fence_checks"]
    donor_id = env["donor_id"]
    donor_tag = env["donor_tag"]
    donor_binary_sha256 = env["donor_binary_sha256"]
    receipt = module.build_release(ROOT, allow_dirty=True)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert receipt["package_version"] == "1.2.0"
    assert receipt["capability_version"] == "1.1.0"
    assert receipt["source_dirty"] is True
    assert receipt["activated"] is False
    assert not module._state_paths()["pointer"].exists()
    build = build_commands[0]
    joined = "\n".join(build)
    for key in (
        "DOCKERFILE_SHA256",
        "ENTRYPOINT_SHA256",
        "SOURCE_IDENTITY_SHA256",
        "REQUESTED_MODEL=grok-4.5",
        f"GROK_DONOR_IMAGE_ID={donor_id}",
        f"GROK_DONOR_BINARY_SHA256={donor_binary_sha256}",
    ):
        assert key in joined
    assert "GROK_DONOR_IMAGE=" not in joined
    assert donor_tag not in joined
    assert str(ROOT) not in build[-1]
    assert (Path(build[-1]) / module.DONOR_BINARY_CONTEXT_RELATIVE).name == "grok"
    manifest = module._load_json(Path(receipt["release_manifest_path"]))
    module._validate_release_manifest(manifest, Path(receipt["release_manifest_path"]))
    assert manifest["source_identity"]["grok_donor_image_id"] == donor_id
    assert manifest["source_identity"]["grok_donor_binary_sha256"] == donor_binary_sha256
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-image-id"] == donor_id
    )
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-binary.sha256"]
        == donor_binary_sha256
    )
    assert fence_checks == [
        ("build", None),
        ("build", {"test_fence": "build"}),
        ("build", {"test_fence": "build"}),
    ]
    # Exact create/inspect/cp shape; never start; cleanup removed the extract container.
    docker_commands = env["docker_commands"]
    assert any(cmd[:2] == ["docker", "create"] for cmd in docker_commands)
    assert any(cmd[:2] == ["docker", "inspect"] for cmd in docker_commands)
    assert any(cmd[:2] == ["docker", "cp"] for cmd in docker_commands)
    assert any(cmd[:3] == ["docker", "rm", "-f"] for cmd in docker_commands)
    assert not any(cmd[:2] == ["docker", "start"] for cmd in docker_commands)
    assert env["created_containers"]
    assert set(env["created_containers"]).issubset(set(env["removed_containers"]))
    assert env["live_containers"] == {}
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
        for path in module._state_paths()["capability_root"].iterdir()
    )


def test_build_extract_pins_binary_against_tag_retarget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SP-B-001: tag retarget after first inspect cannot change staged donor bytes."""
    module = _module()
    _state(module, tmp_path, monkeypatch)
    lock = json.loads(module.RUNTIME_LOCK_PATH.read_text(encoding="utf-8"))
    donor_tag = str(lock["grok_donor_image"])
    pinned_id = str(lock["grok_donor_image_id"])
    retargeted_id = "sha256:" + "9" * 64
    assert retargeted_id != pinned_id

    donor_tag_inspects = 0
    tag_retargeted = False

    def on_before_build(values: list[str]) -> None:
        nonlocal tag_retargeted
        tag_retargeted = True
        args = _parse_build_args(values)
        assert "GROK_DONOR_IMAGE" not in args
        assert args["GROK_DONOR_IMAGE_ID"] == pinned_id
        assert args["GROK_DONOR_BINARY_SHA256"] == FAKE_DONOR_BINARY_SHA256
        context = Path(values[-1])
        assert (context / module.DONOR_BINARY_CONTEXT_RELATIVE).read_bytes() == (
            FAKE_DONOR_BINARY_PAYLOAD
        )

    env = _fake_build_environment(
        module, monkeypatch, dirty=False, on_before_build=on_before_build
    )
    original_image = module._docker_image

    def retarget_aware_image(_docker: str, image: str) -> dict[str, object]:
        nonlocal donor_tag_inspects
        if image == donor_tag:
            donor_tag_inspects += 1
            if tag_retargeted or donor_tag_inspects > 1:
                return {"Id": retargeted_id}
            return {"Id": pinned_id}
        if image == pinned_id:
            return {"Id": pinned_id}
        if image == retargeted_id:
            return {"Id": retargeted_id}
        return original_image(_docker, image)

    monkeypatch.setattr(module, "_docker_image", retarget_aware_image)

    receipt = module.build_release(ROOT, allow_dirty=False)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert tag_retargeted is True
    assert donor_tag_inspects == 1
    assert len(env["build_commands"]) == 1
    assert module._docker_image("docker", donor_tag)["Id"] == retargeted_id
    assert module._docker_image("docker", pinned_id)["Id"] == pinned_id
    manifest = module._load_json(Path(receipt["release_manifest_path"]))
    module._validate_release_manifest(manifest, Path(receipt["release_manifest_path"]))
    assert manifest["source_identity"]["grok_donor_image_id"] == pinned_id
    assert manifest["source_identity"]["grok_donor_binary_sha256"] == FAKE_DONOR_BINARY_SHA256
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-image-id"] == pinned_id
    )
    assert (
        manifest["image_labels"]["io.xinao.researcher.grok-donor-binary.sha256"]
        == FAKE_DONOR_BINARY_SHA256
    )
    assert manifest["source_identity"]["grok_donor_image_id"] != retargeted_id


def test_build_detects_staged_binary_tamper_before_docker_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_prepare = module._prepare_donor_binary_staging

    def prepare_then_tamper(docker: str, *, donor_image_id: str, entrypoint_path: Path):
        result = original_prepare(
            docker, donor_image_id=donor_image_id, entrypoint_path=entrypoint_path
        )
        _binary_sha256, _staging_root, build_context, _container_name = result
        binary = build_context / module.DONOR_BINARY_CONTEXT_RELATIVE
        binary.write_bytes(b"tampered-donor-binary\n")
        return result

    monkeypatch.setattr(module, "_prepare_donor_binary_staging", prepare_then_tamper)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "DONOR_BINARY_TAMPERED"
    assert env["live_containers"] == {}
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
        for path in module._state_paths()["capability_root"].iterdir()
        if path.is_dir()
    )


def test_build_rejects_non_regular_staged_donor_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_run = module._run

    def symlink_cp(arguments, **kwargs):
        values = list(arguments)
        if values[:2] == ["docker", "cp"]:
            dest = Path(values[3])
            dest.parent.mkdir(parents=True, exist_ok=True)
            target = dest.parent / "link-target"
            target.write_bytes(FAKE_DONOR_BINARY_PAYLOAD)
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            dest.symlink_to(target)
            return SimpleNamespace(stdout="", stderr="", returncode=0)
        return original_run(arguments, **kwargs)

    monkeypatch.setattr(module, "_run", symlink_cp)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "DONOR_BINARY_INVALID"
    assert env["live_containers"] == {}


@pytest.mark.parametrize("fail_on", ("create", "inspect", "cp", "build"))
def test_build_donor_extract_cleanup_on_every_failure_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_on: str
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False, fail_on=fail_on)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "PROCESS_FAILED"
    assert env["live_containers"] == {}
    capability_root = module._state_paths()["capability_root"]
    leftovers = [
        path
        for path in capability_root.iterdir()
        if path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
    ]
    assert leftovers == []
    if fail_on != "create":
        assert env["created_containers"]
        assert set(env["created_containers"]).issubset(set(env["removed_containers"]))


def test_build_concurrent_extract_identities_are_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    names: list[str] = []
    staging_roots: list[Path] = []

    def capture_prepare(docker: str, *, donor_image_id: str, entrypoint_path: Path):
        result = original_prepare(
            docker, donor_image_id=donor_image_id, entrypoint_path=entrypoint_path
        )
        binary_sha256, staging_root, build_context, container_name = result
        names.append(container_name)
        staging_roots.append(staging_root)
        return result

    env = _fake_build_environment(module, monkeypatch, dirty=False)
    original_prepare = module._prepare_donor_binary_staging
    monkeypatch.setattr(module, "_prepare_donor_binary_staging", capture_prepare)
    first = module.build_release(ROOT, allow_dirty=False)
    second = module.build_release(ROOT, allow_dirty=False)
    assert first["status"] == second["status"] == "CANDIDATE_BUILT"
    assert len(names) == 2
    assert names[0] != names[1]
    assert staging_roots[0] != staging_roots[1]
    assert all(name.startswith(module.DONOR_EXTRACT_NAME_PREFIX) for name in names)
    assert all(
        root.name.startswith(module.DONOR_STAGING_DIR_PREFIX) for root in staging_roots
    )
    assert env["live_containers"] == {}


def test_build_parser_has_no_promote_flag(capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    code = module.main(["build", "--source-root", str(ROOT), "--promote"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["reason_codes"] == ["INVOCATION_ARGUMENTS_INVALID"]


def test_same_semver_different_content_is_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _fake_build_environment(module, monkeypatch, dirty=False, image_character="f")
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "SEMVER_CONTENT_COLLISION"


@pytest.mark.parametrize(
    ("failure_call", "expected_build_count"),
    ((2, 0), (3, 1)),
)
def test_build_fence_blocks_effect_or_release_seal_at_the_matching_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
    expected_build_count: int,
) -> None:
    module = _module()
    _state(module, tmp_path, monkeypatch)
    env = _fake_build_environment(module, monkeypatch, dirty=False)
    build_commands = env["build_commands"]
    fence = {"test_fence": "build"}
    calls = 0

    def fail_at_boundary(command: str, *, expected=None):
        nonlocal calls
        calls += 1
        assert command == "build"
        if calls == failure_call:
            raise module.XinaoError("BOOTSTRAP_FENCE_STATE_DRIFT", "injected")
        if expected is not None:
            assert expected == fence
        return dict(fence)

    monkeypatch.setattr(module, "_validate_bootstrap_fence_locked", fail_at_boundary)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=False)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"
    assert len(build_commands) == expected_build_count
    assert not module._state_paths()["release_root"].exists()
    # Fence failure after extract still cleans temporary donor staging/container.
    assert env["live_containers"] == {}
    capability_root = module._state_paths()["capability_root"]
    assert not any(
        path.name.startswith(module.DONOR_STAGING_DIR_PREFIX)
        for path in capability_root.iterdir()
    )


def test_legacy_pointer_fails_before_any_activation_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    pointer_path = module._state_paths()["pointer"]
    legacy = {
        "schema_version": "xinao.researcher_current_pointer.v1",
        "release_id": manifest["release_id"],
    }
    module._write_json_atomic(pointer_path, legacy)
    before = pointer_path.read_bytes()
    _set_syntactic_bootstrap_fence(module, monkeypatch, tmp_path / "state")
    with pytest.raises(module.XinaoError) as failure:
        module.activate_release(str(manifest["release_id"]))
    assert failure.value.reason_code == "BOOTSTRAP_MIGRATION_REQUIRED"
    assert pointer_path.read_bytes() == before
    assert not module._state_paths()["transaction_root"].exists()


def test_dirty_candidate_never_activates_or_changes_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    clean, clean_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, clean, clean_path)
    dirty, _dirty_path = _sealed_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        dirty=True,
    )
    pointer_path = module._state_paths()["pointer"]
    before = pointer_path.read_bytes()
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(dirty["release_id"])]
    )
    with pytest.raises(module.XinaoError) as failure:
        module.activate_release(str(dirty["release_id"]))
    assert failure.value.reason_code == "DIRTY_RELEASE_ACTIVATION_FORBIDDEN"
    assert pointer_path.read_bytes() == before
    assert module._pending_journals() == []


def test_activate_verifies_canary_and_keeps_full_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    first_pointer, _journal, _path = _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda journal: _canary_value(module, journal)
    )
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    receipt = module.activate_release(str(second["release_id"]))
    pointer = module._load_json(module._state_paths()["pointer"])
    journal = module._load_json(Path(receipt["activation_journal_path"]))
    assert receipt["status"] == "VERIFIED"
    assert pointer["generation"] == 2
    assert pointer["active"]["release_id"] == second["release_id"]
    assert pointer["previous_verified"] == first_pointer["active"]
    assert journal["state"] == "VERIFIED"
    assert journal["txn_id"] == pointer["active"]["activation_txn_id"]
    assert journal["terminal_pointer_sha256"] == module._sha256(module._state_paths()["pointer"])
    assert module._load_current_context()["release"]["release_id"] == second["release_id"]


def test_failed_activation_rolls_back_with_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    calls: list[str] = []

    def canary(journal):
        release_id = journal["to"]["release_id"]
        calls.append(release_id)
        if release_id == second["release_id"]:
            raise module.XinaoError("ACTIVATION_CANARY_FAILED", "injected")
        return _canary_value(module, journal)

    monkeypatch.setattr(module, "_run_activation_canary", canary)
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    receipt = module.activate_release(str(second["release_id"]))
    pointer = module._load_json(module._state_paths()["pointer"])
    journal = module._load_json(Path(receipt["activation_journal_path"]))
    assert receipt["status"] == "ROLLED_BACK"
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == first["release_id"]
    assert journal["state"] == "ROLLED_BACK"
    assert calls == [second["release_id"], first["release_id"]]
    assert module._load_current_context()["release"]["release_id"] == first["release_id"]


@pytest.mark.parametrize("crash_state", ("PREPARED", "POINTER_SWITCHED", "CANARY_STARTED"))
def test_recover_converges_each_activation_crash_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_state: str,
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"recover"
    )
    with module._activation_lock():
        current = module._load_current_context()
        journal, journal_path = module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
        if crash_state != "PREPARED":
            journal, _pointer, _sha = module._switch_prepared_pointer(journal, journal_path)
        if crash_state == "CANARY_STARTED":
            journal = module._journal_transition(journal_path, journal, "CANARY_STARTED")
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    _install_bootstrap_fence(module, monkeypatch, ["recover", "--txn-id", str(journal["txn_id"])])
    receipt = module.recover_release(str(journal["txn_id"]))
    assert receipt["status"] == "VERIFIED"
    assert module._load_current_context()["release"]["release_id"] == second["release_id"]
    assert module._load_json(journal_path)["state"] == "VERIFIED"


def test_recover_explicit_transaction_must_match_fenced_pending_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"recover-fence"
    )
    with module._activation_lock():
        current = module._load_current_context()
        journal, journal_path = module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    _install_bootstrap_fence(module, monkeypatch, ["recover", "--txn-id", str(journal["txn_id"])])
    pointer_path = module._state_paths()["pointer"]
    pointer_before = pointer_path.read_bytes()
    journal_before = journal_path.read_bytes()
    mismatched_txn_id = "xra_20260730T120001_" + "f" * 16
    with pytest.raises(module.XinaoError) as failure:
        module.recover_release(mismatched_txn_id)
    assert failure.value.reason_code == "RECOVERY_TRANSACTION_FENCE_MISMATCH"
    assert pointer_path.read_bytes() == pointer_before
    assert journal_path.read_bytes() == journal_before


def test_rollback_requires_complete_previous_verified_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, first, first_path)
    pointer_path = module._state_paths()["pointer"]
    before = pointer_path.read_bytes()
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    with pytest.raises(module.XinaoError) as failure:
        module.rollback_release()
    assert failure.value.reason_code == "ROLLBACK_MATERIAL_ABSENT"
    assert pointer_path.read_bytes() == before


def test_rollback_switches_to_full_previous_and_increments_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, _second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"second"
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    _install_bootstrap_fence(
        module, monkeypatch, ["activate", "--release-id", str(second["release_id"])]
    )
    module.activate_release(str(second["release_id"]))
    _install_bootstrap_fence(module, monkeypatch, ["rollback"])
    receipt = module.rollback_release()
    pointer = module._load_json(module._state_paths()["pointer"])
    assert receipt["status"] == "ROLLED_BACK"
    assert pointer["generation"] == 3
    assert pointer["active"]["release_id"] == first["release_id"]
    assert pointer["previous_verified"]["release_id"] == second["release_id"]
    assert module._load_current_context()["journal"]["state"] == "ROLLED_BACK"


def test_pending_runtime_inspection_reports_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"pending-inspection"
    )
    with module._activation_lock():
        current = module._load_current_context()
        module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    _install_bootstrap_fence(module, monkeypatch, ["recover"])
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("command", (["inspect"], ["research", "--question", "q"]))
def test_thin_bootstrap_blocks_pending_inspect_and_research(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path, state="POINTER_SWITCHED")
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._runtime_entry_locked(command, tmp_path / "state")
    assert failure.value.reason_code == "RECOVERY_REQUIRED"


def test_thin_bootstrap_requires_verified_txn_and_pointer_hash_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _pointer, journal, journal_path = _terminal_pointer(runtime, manifest, manifest_path)
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    expected_runtime, expected_payload, fence = bootstrap._runtime_entry_locked(
        ["inspect"], tmp_path / "state"
    )
    assert expected_runtime == Path(manifest["skill_bundle_path"]) / "scripts" / "xinao_runtime.py"
    assert expected_payload == expected_runtime.read_bytes()
    assert fence["selected_runtime_sha256"] == runtime._sha256_bytes(expected_payload)
    assert set(fence) == runtime.BOOTSTRAP_FENCE_KEYS

    journal["terminal_pointer_sha256"] = "0" * 64
    runtime._write_json_atomic(journal_path, journal)
    with pytest.raises(bootstrap.BootstrapError) as hash_failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert hash_failure.value.reason_code == "ACTIVATION_POINTER_BINDING_MISMATCH"

    journal["terminal_pointer_sha256"] = runtime._sha256(runtime._state_paths()["pointer"])
    journal["txn_id"] = "xra_20260730T120000_" + "f" * 16
    runtime._write_json_atomic(journal_path, journal)
    with pytest.raises(bootstrap.BootstrapError) as txn_failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert txn_failure.value.reason_code == "ACTIVATION_TRANSACTION_BINDING_MISMATCH"


def test_thin_bootstrap_loads_runtime_only_from_exact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path)
    bootstrap = _bootstrap_module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    runtime_path, runtime_payload, fence = bootstrap._runtime_entry_locked(
        ["inspect"], tmp_path / "state"
    )
    bundle_manifest = json.loads(
        Path(manifest["skill_bundle_manifest_path"]).read_text(encoding="utf-8")
    )
    row = next(
        item
        for item in bundle_manifest["files"]
        if item["relative_path"] == "scripts/xinao_runtime.py"
    )
    assert runtime_path == Path(manifest["skill_bundle_path"]) / row["relative_path"]
    assert runtime._sha256(runtime_path) == row["sha256"]
    assert runtime._sha256_bytes(runtime_payload) == row["sha256"]
    assert fence["selected_runtime_sha256"] == row["sha256"]


def test_runtime_consumes_exact_bootstrap_fence_under_activation_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    with module._activation_lock():
        observed = module._validate_bootstrap_fence_locked("inspect")
    assert observed == fence
    assert module.BOOTSTRAP_FENCE_ENVIRONMENT not in os.environ
    observed["pointer_sha256"] = "0" * 64
    with module._activation_lock():
        reread = module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert reread == fence
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(fence, sort_keys=True, separators=(",", ":")),
    )
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as pollution:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert pollution.value.reason_code == "BOOTSTRAP_FENCE_ENVIRONMENT_REAPPEARED"
    assert module.BOOTSTRAP_FENCE_ENVIRONMENT not in os.environ


@pytest.mark.parametrize("mutation", ("missing_key", "extra_key"))
def test_bootstrap_fence_rejects_missing_or_extra_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    candidate = dict(fence)
    if mutation == "missing_key":
        candidate.pop("selected_runtime_sha256")
    else:
        candidate["unexpected"] = True
    monkeypatch.setenv(
        module.BOOTSTRAP_FENCE_ENVIRONMENT,
        json.dumps(candidate, sort_keys=True, separators=(",", ":")),
    )
    with pytest.raises(module.XinaoError) as failure:
        module._load_bootstrap_fence()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_INVALID"


def test_bootstrap_fence_rejects_pointer_drift_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    pointer_path = module._state_paths()["pointer"]
    pointer = module._load_json(pointer_path)
    pointer["switched_at"] = "2026-07-30T12:00:02Z"
    module._write_json_atomic(pointer_path, pointer)
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_bootstrap_fence_rejects_pending_transaction_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    first, first_path = _sealed_release(module, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(module, first, first_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    second, second_path = _sealed_release(
        module, tmp_path, monkeypatch, image_character="b", variant=b"pending-drift"
    )
    with module._activation_lock():
        current = module._load_current_context()
        module._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("recover", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_bootstrap_fence_rejects_executed_runtime_digest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["inspect"])
    drifted_runtime = tmp_path / "drifted-runtime.py"
    drifted_runtime.write_text("raise RuntimeError('drift')\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(drifted_runtime))
    with module._activation_lock():
        with pytest.raises(module.XinaoError) as failure:
            module._validate_bootstrap_fence_locked("inspect", expected=fence)
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_RUNTIME_DRIFT"


def test_inspect_revalidates_fence_before_reporting_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])

    def drift_pointer(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:03Z"
        module._write_json_atomic(pointer_path, pointer)
        return "docker", module._validate_charter()

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_pointer)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_inspect_revalidates_fence_before_returning_error_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["inspect"])

    def drift_then_fail(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:05Z"
        module._write_json_atomic(pointer_path, pointer)
        raise module.XinaoError("ENGINE_UNAVAILABLE", "injected")

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_then_fail)
    with pytest.raises(module.XinaoError) as failure:
        module.inspect_capability()
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_research_revalidates_fence_before_container_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    _auth(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (
            module._validate_charter(),
            {
                "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
                "provider_egress_runtime_verified": True,
            },
        ),
    )

    def drift_pointer(_release):
        pointer_path = module._state_paths()["pointer"]
        pointer = module._load_json(pointer_path)
        pointer["switched_at"] = "2026-07-30T12:00:04Z"
        module._write_json_atomic(pointer_path, pointer)
        return "docker", module._validate_charter()

    monkeypatch.setattr(module, "_validate_release_for_invoke", drift_pointer)
    monkeypatch.setattr(
        module, "_run", lambda *_args, **_kwargs: pytest.fail("Docker must not run")
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research("q", None, [])
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"


def test_egress_boundary_fails_before_docker_or_auth_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, _manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    runtime_lock["provider_egress_runtime_verified"] = False
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (module._validate_charter(), runtime_lock),
    )
    monkeypatch.setattr(module, "_docker", lambda: pytest.fail("Docker must not be touched"))
    monkeypatch.setattr(module, "DEFAULT_AUTH_PATH", tmp_path / "missing-auth.json")
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_for_invoke(manifest)
    assert failure.value.reason_code == "EGRESS_BOUNDARY_UNAVAILABLE"


def test_research_egress_failure_precedes_auth_snapshot_and_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    monkeypatch.setattr(
        module,
        "_validate_release_source_identity",
        lambda _release: (
            module._validate_charter(),
            {
                "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
                "provider_egress_runtime_verified": False,
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "_snapshot_material_sources",
        lambda _paths: pytest.fail("auth/material snapshot must not run"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research("q", None, [])
    assert failure.value.reason_code == "EGRESS_BOUNDARY_UNAVAILABLE"
    assert not (tmp_path / "runs").exists()


def test_material_snapshot_holds_one_auth_identity_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    auth = _auth(module, tmp_path, monkeypatch)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first evidence", encoding="utf-8")
    second.write_text("second evidence", encoding="utf-8")
    original_auth_payload = auth.read_bytes()
    snapshots, witness = module._snapshot_material_sources([first, second])
    assert len(snapshots) == 2
    assert witness["path"] == str(auth.resolve())
    assert witness["content_sha256"] == module._sha256_bytes(original_auth_payload)
    assert "payload" not in witness
    module._validate_auth_identity_witness(witness)
    changed_auth_payload = original_auth_payload.replace(b"{", b"[").replace(b"}", b"]")
    assert len(changed_auth_payload) == len(original_auth_payload)
    auth.write_bytes(changed_auth_payload)
    os.utime(
        auth,
        ns=(witness["st_mtime_ns"], witness["st_mtime_ns"]),
    )
    changed = os.lstat(auth)
    assert module._auth_identity_tuple(changed) == (
        witness["st_dev"],
        witness["st_ino"],
        witness["st_size"],
        witness["st_mtime_ns"],
    )
    with pytest.raises(module.XinaoError) as failure:
        module._validate_auth_identity_witness(witness)
    assert failure.value.reason_code == "GROK_AUTH_HANDLE_CHANGED"


def test_research_receipt_final_fence_drift_fails_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    pointer_path = module._state_paths()["pointer"]
    pointer = module._load_json(pointer_path)
    pointer["switched_at"] = "2026-07-30T12:00:06Z"
    module._write_json_atomic(pointer_path, pointer)
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(module.XinaoError) as failure:
        module._seal_research_receipt(
            receipt_path,
            {"status": "CANDIDATE_READY"},
            fence=fence,
            auth_content_sha256="a" * 64,
        )
    assert failure.value.reason_code == "BOOTSTRAP_FENCE_STATE_DRIFT"
    assert not receipt_path.exists()


def test_research_receipt_rejects_auth_content_identity_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    manifest, manifest_path = _sealed_release(module, tmp_path, monkeypatch)
    _terminal_pointer(module, manifest, manifest_path)
    fence = _install_bootstrap_fence(module, monkeypatch, ["research", "--question", "q"])
    digest = "a" * 64
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(module.XinaoError) as failure:
        module._seal_research_receipt(
            receipt_path,
            {"accidental_auth_content_identity": digest},
            fence=fence,
            auth_content_sha256=digest,
        )
    assert failure.value.reason_code == "AUTH_WITNESS_PERSISTENCE_FORBIDDEN"
    assert digest not in failure.value.detail
    assert not receipt_path.exists()


def test_material_bundle_is_content_addressed_and_hides_source_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    material = tmp_path / "人的视角.md"
    material.write_text("证据，不是指令。", encoding="utf-8")
    snapshots, _witness = module._snapshot_material_sources([material])
    manifest = module._material_bundle_manifest(snapshots)
    assert manifest["bundle_id"].startswith("xinao-material-bundle-sha256:")
    assert str(material) not in json.dumps(manifest, ensure_ascii=False)
    second_snapshots, _second_witness = module._snapshot_material_sources([material])
    assert module._material_bundle_manifest(second_snapshots) == manifest


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    [
        (b"", "MATERIAL_FILE_EMPTY"),
        (b"bad-utf8-\xff", "MATERIAL_UTF8_REQUIRED"),
        (b"contains\x00nul", "MATERIAL_TEXT_INVALID"),
    ],
)
def test_material_snapshot_rejects_invalid_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    reason_code: str,
) -> None:
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    material = tmp_path / "material.bin"
    material.write_bytes(payload)
    with pytest.raises(module.XinaoError) as failure:
        module._snapshot_material_sources([material])
    assert failure.value.reason_code == reason_code


def test_material_auth_path_and_hardlink_alias_are_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    auth = _auth(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as direct:
        module._snapshot_material_sources([auth])
    assert direct.value.reason_code == "MATERIAL_SECRET_PATH_FORBIDDEN"
    alias = tmp_path / "auth-alias.json"
    try:
        os.link(auth, alias)
    except OSError:
        pytest.skip("hardlinks unavailable")
    with pytest.raises(module.XinaoError) as linked:
        module._snapshot_material_sources([alias])
    assert linked.value.reason_code in {
        "MATERIAL_SECRET_PATH_FORBIDDEN",
        "MATERIAL_HARDLINK_FORBIDDEN",
    }


def _valid_provider_result() -> dict[str, object]:
    return {
        "provider_stop_reason": "EndTurn",
        "provider_num_turns": 1,
        "provider_session_id_present": True,
        "provider_request_id_present": True,
        "provider_model_usage": {"grok-4.5-build": {"inputTokens": 10, "modelCalls": 1}},
        "usage": {"total_tokens": 12},
    }


def test_provider_effect_requires_exact_observed_model_and_integer_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    runtime_lock = module._load_json(module.RUNTIME_LOCK_PATH)
    assert module._validate_provider_effect(_valid_provider_result(), runtime_lock) == (
        "grok-4.5-build",
        1,
    )
    invalid_values = (
        {"grok-4.5": {"modelCalls": 1}},
        {
            "grok-4.5-build": {"modelCalls": 1},
            "fake": {"modelCalls": 1},
        },
        {"grok-4.5-build": {"modelCalls": True}},
        {"grok-4.5-build": {"modelCalls": 0}},
    )
    for model_usage in invalid_values:
        result = _valid_provider_result()
        result["provider_model_usage"] = model_usage
        with pytest.raises(module.XinaoError) as failure:
            module._validate_provider_effect(result, runtime_lock)
        assert failure.value.reason_code == "PROVIDER_EFFECT_EVIDENCE_INVALID"


def _valid_container_inspect(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    input_root = tmp_path / "input"
    materials_root = tmp_path / "materials"
    output_root = tmp_path / "output"
    auth_path = tmp_path / "auth.json"
    image_id = "sha256:" + "a" * 64
    inspect: dict[str, object] = {
        "Image": image_id,
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": "bridge",
            "PidsLimit": 128,
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "Privileged": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
            },
        },
        "Config": {"Env": ["XINAO_CHAIN_CLASS=scientific_researcher"]},
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(input_root),
                "Destination": "/input",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(materials_root),
                "Destination": "/materials",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": str(output_root),
                "Destination": "/output",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(auth_path),
                "Destination": "/grok-home/auth.json",
                "RW": False,
            },
        ],
    }
    arguments: dict[str, object] = {
        "image_id": image_id,
        "input_root": input_root,
        "materials_root": materials_root,
        "output_root": output_root,
        "auth_path": auth_path,
    }
    return inspect, arguments


@pytest.mark.parametrize(
    ("field", "invalid_value", "reason_code"),
    (
        ("PidsLimit", 129, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("PidsLimit", True, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("CapDrop", ["ALL", "SYS_ADMIN"], "CONTAINER_CAP_DROP_INVALID"),
        ("CapAdd", ["SYS_ADMIN"], "CONTAINER_CAP_ADD_INVALID"),
        (
            "SecurityOpt",
            ["no-new-privileges:true", "seccomp=unconfined"],
            "CONTAINER_NO_NEW_PRIVILEGES_MISSING",
        ),
        ("Memory", 2147483647, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("Memory", 2147483648.0, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("NanoCpus", 1999999999, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("NanoCpus", 2000000000.0, "CONTAINER_RESOURCE_BOUNDARY_INVALID"),
        ("Privileged", True, "CONTAINER_PRIVILEGE_BOUNDARY_INVALID"),
        (
            "RestartPolicy",
            {"Name": "no", "MaximumRetryCount": False},
            "CONTAINER_RESTART_POLICY_INVALID",
        ),
        (
            "RestartPolicy",
            {"Name": "always", "MaximumRetryCount": 0},
            "CONTAINER_RESTART_POLICY_INVALID",
        ),
        (
            "Tmpfs",
            {"/tmp": "rw,nosuid,nodev,size=256m,mode=1777"},
            "CONTAINER_TMPFS_INVALID",
        ),
        (
            "Tmpfs",
            {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
                "/extra": "rw",
            },
            "CONTAINER_TMPFS_INVALID",
        ),
    ),
)
def test_container_inspect_requires_exact_runtime_security_values(
    tmp_path: Path,
    field: str,
    invalid_value: object,
    reason_code: str,
) -> None:
    module = _module()
    inspect, arguments = _valid_container_inspect(tmp_path)
    module._validate_container_inspect(inspect, **arguments)
    host = inspect["HostConfig"]
    assert isinstance(host, dict)
    host["CapAdd"] = []
    module._validate_container_inspect(inspect, **arguments)
    host[field] = invalid_value
    with pytest.raises(module.XinaoError) as failure:
        module._validate_container_inspect(inspect, **arguments)
    assert failure.value.reason_code == reason_code


@pytest.mark.parametrize(
    "delta",
    (
        {"Status": "running"},
        {"Running": True},
        {"ExitCode": True},
        {"ExitCode": 1},
        {"OOMKilled": True},
        {"Error": "boom"},
    ),
)
def test_container_terminal_state_is_strict(delta: dict[str, object]) -> None:
    module = _module()
    terminal = {
        "Status": "exited",
        "Running": False,
        "ExitCode": 0,
        "OOMKilled": False,
        "Error": "",
        "Paused": False,
        "Restarting": False,
        "Dead": False,
    }
    assert module._validate_container_terminal_state(terminal) == terminal
    terminal.update(delta)
    with pytest.raises(module.XinaoError) as failure:
        module._validate_container_terminal_state(terminal)
    assert failure.value.reason_code == "CONTAINER_TERMINAL_STATE_INVALID"


def test_terminal_attestation_is_bounded_canonical_and_hash_bound() -> None:
    module = _module()
    value = {
        "schema_version": "xinao.researcher_terminal_attestation.v1",
        "status": "CANDIDATE_READY",
        "result_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "observed_model_id": "grok-4.5-build",
        "observed_model_calls": 1,
    }
    payload = module._canonical_bytes(value)
    assert (
        module._validate_terminal_attestation(
            payload,
            request_sha256="b" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
        == value
    )
    with pytest.raises(module.XinaoError) as tampered:
        module._validate_terminal_attestation(
            payload,
            request_sha256="0" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
    assert tampered.value.reason_code == "CONTAINER_TERMINAL_ATTESTATION_BINDING_INVALID"
    with pytest.raises(module.XinaoError) as oversized:
        module._validate_terminal_attestation(
            b"x" * (module.MAX_TERMINAL_ATTESTATION_BYTES + 1),
            request_sha256="b" * 64,
            result_sha256="a" * 64,
            result_status="CANDIDATE_READY",
            observed_model_id="grok-4.5-build",
            observed_model_calls=1,
        )
    assert oversized.value.reason_code == "CONTAINER_TERMINAL_ATTESTATION_INVALID"


def test_material_result_binding_requires_real_supplied_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _auth(module, tmp_path, monkeypatch)
    source = tmp_path / "material.txt"
    source.write_text("evidence", encoding="utf-8")
    snapshots, _witness = module._snapshot_material_sources([source])
    manifest = module._material_bundle_manifest(snapshots)
    manifest_sha = module._sha256_bytes(module._canonical_bytes(manifest))
    packet = module._material_packet_bytes(manifest, snapshots)
    packet_sha = module._sha256_bytes(packet)
    effective_sha = module._sha256_bytes(module._effective_prompt_bytes("base", packet))
    entry = manifest["materials"][0]
    candidate = {
        "schema_version": "xinao.research_candidate.v2",
        "status": "CANDIDATE_READY",
        "research_question": "q",
        "as_of": "2026-07-30T00:00:00Z",
        "material_bundle_id": manifest["bundle_id"],
        "material_refs_used": [{"material_id": entry["material_id"], "sha256": entry["sha256"]}],
        "summary": "candidate only",
        "hypotheses": ["one hypothesis"],
        "competing_explanations": ["one competing explanation"],
        "methods": ["bounded material analysis"],
        "evidence_used": [
            {
                "material_id": entry["material_id"],
                "finding": "bounded finding",
                "locator": "whole file",
            }
        ],
        "counterevidence": [],
        "limitations": ["candidate evidence only"],
        "next_evidence": ["independent observation"],
    }
    request_sha = "1" * 64
    prompt_sha = "2" * 64
    output_schema_sha = module._sha256(module.OUTPUT_SCHEMA_PATH)
    result = {
        "schema_version": "xinao.researcher_container_result.v2",
        "status": "CANDIDATE_READY",
        "reason_codes": [],
        "candidate": candidate,
        "request_sha256": request_sha,
        "prompt_sha256": prompt_sha,
        "output_schema_sha256": output_schema_sha,
        "material_bundle_id": manifest["bundle_id"],
        "material_manifest_sha256": manifest_sha,
        "material_packet_sha256": packet_sha,
        "effective_prompt_sha256": effective_sha,
        "material_refs_available": [entry["material_id"]],
        "provider": "grok",
        "requested_model": "grok-4.5",
        **_valid_provider_result(),
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
    }
    module._validate_material_result_binding(
        result,
        manifest=manifest,
        request_sha256=request_sha,
        prompt_sha256=prompt_sha,
        output_schema_sha256=output_schema_sha,
        manifest_sha256=manifest_sha,
        material_packet_sha256=packet_sha,
        effective_prompt_sha256=effective_sha,
        question="q",
        as_of="2026-07-30T00:00:00Z",
    )
    candidate["material_refs_used"] = []
    candidate["evidence_used"] = []
    with pytest.raises(module.XinaoError) as unbound:
        module._validate_material_result_binding(
            result,
            manifest=manifest,
            request_sha256=request_sha,
            prompt_sha256=prompt_sha,
            output_schema_sha256=output_schema_sha,
            manifest_sha256=manifest_sha,
            material_packet_sha256=packet_sha,
            effective_prompt_sha256=effective_sha,
            question="q",
            as_of="2026-07-30T00:00:00Z",
        )
    assert unbound.value.reason_code == "RESEARCH_CANDIDATE_MATERIAL_USE_UNBOUND"


def test_bounded_result_reader_rejects_oversized_json(
    tmp_path: Path,
) -> None:
    module = _module()
    result = tmp_path / "result.json"
    result.write_bytes(b'{"x":"' + b"a" * 128 + b'"}\n')
    with pytest.raises(module.XinaoError) as failure:
        module._load_json(result, maximum_bytes=32)
    assert failure.value.reason_code == "JSON_READ_FAILED"


def _copy_skill_tree(source: Path, destination: Path, *, newline: bytes | None = None) -> None:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        if newline is not None and path.suffix.lower() in {
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".txt",
        }:
            text = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            if newline == b"\r\n":
                payload = text.replace(b"\n", b"\r\n")
            else:
                payload = text
        target.write_bytes(payload)


def _stage_source_rendering(
    module,
    release_id: str,
    *,
    newline: bytes,
    marker: bytes | None = None,
) -> Path:
    root = module._source_rendering_root(release_id)
    if root.exists():
        import shutil

        shutil.rmtree(root)
    _copy_skill_tree(SKILL_ROOT, root, newline=newline)
    if marker is not None:
        marker_path = root / "references" / "migration-marker.txt"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_bytes(marker if newline == b"\n" else marker.replace(b"\n", newline))
    return root


def _legacy_skill_hashes_for_tree(module, root: Path) -> dict[str, str]:
    skill_side = module._legacy_skill_side_hashes(root)
    skill_side["dockerfile_sha256"] = "1" * 64
    skill_side["entrypoint_sha256"] = "2" * 64
    return skill_side


def _write_pure_v1_release(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_character: str,
    newline: bytes,
    marker: bytes,
    release_suffix: str,
) -> tuple[dict[str, object], Path, Path]:
    state = _state(module, tmp_path, monkeypatch)
    release_id = f"researcher-1.0.0-{release_suffix}"
    rendering = _stage_source_rendering(
        module, release_id, newline=newline, marker=marker
    )
    skill_hashes = _legacy_skill_hashes_for_tree(module, rendering)
    source_identity = {
        "source_commit": "b916f8bd22dd38b4807298a4c935f6bf2969eb13",
        "source_tree": "71f8994c8e8e8f10c09cf8aef3e21ba3635d627e",
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "capability_registry_sha256": skill_hashes["capability_registry_sha256"],
        "charter_sha256": skill_hashes["charter_sha256"],
        "dockerfile_sha256": skill_hashes["dockerfile_sha256"],
        "entrypoint_sha256": skill_hashes["entrypoint_sha256"],
        "meta_sha256": skill_hashes["meta_sha256"],
        "output_schema_sha256": skill_hashes["output_schema_sha256"],
        "runtime_lock_sha256": skill_hashes["runtime_lock_sha256"],
        "skill_invoker_sha256": skill_hashes["skill_invoker_sha256"],
        "skill_md_sha256": skill_hashes["skill_md_sha256"],
    }
    manifest = {
        "schema_version": module.LEGACY_RELEASE_SCHEMA,
        "release_id": release_id,
        "created_at": "2026-07-29T07:40:23.273627Z",
        "generic_worker_route_allowed": False,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_id": "sha256:" + image_character * 64,
        "image_labels": {
            "io.xinao.researcher.chain": "dedicated-xinao-science",
            "io.xinao.researcher.generic-worker-route": "forbidden",
            "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        },
        "image_tag_observational": f"xinao-researcher:{release_id}",
        "run_namespace": "xinao_researcher",
        "skill_hashes": skill_hashes,
        "source_identity": source_identity,
        "state_namespace": "xinao_skill/researcher_container",
    }
    release_dir = state / "researcher_container" / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / "release.json"
    module._write_json_atomic(manifest_path, manifest, create_new=True)
    # Pure v1 directory: only release.json.
    assert sorted(path.name for path in release_dir.iterdir()) == ["release.json"]
    return manifest, manifest_path, rendering


def _install_drifted_skill(
    module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, active_rendering: Path
) -> Path:
    installed = tmp_path / "installed_skill"
    _copy_skill_tree(active_rendering, installed, newline=None)
    # Drift three sealed Skill files relative to active CRLF bundle.
    (installed / "SKILL.md").write_bytes(
        (installed / "SKILL.md").read_bytes() + b"\n# installed-drift\n"
    )
    capabilities = installed / "references" / "capabilities.v1.json"
    capabilities.write_bytes(capabilities.read_bytes().rstrip() + b"\n")
    meta = installed / "references" / "meta.md"
    meta.write_bytes(meta.read_bytes() + b"\ninstalled-meta-drift\n")
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(module, "DEFAULT_INSTALLED_SKILL_ROOT", installed)
    return installed


def _legacy_pointer_for_v1(
    module,
    active: dict[str, object],
    active_path: Path,
    previous: dict[str, object],
    previous_path: Path,
) -> dict[str, object]:
    return {
        "schema_version": module.LEGACY_POINTER_SCHEMA,
        "release_id": active["release_id"],
        "release_manifest_path": str(active_path),
        "release_manifest_sha256": module._sha256(active_path),
        "promoted_at": "2026-07-29T07:40:23.281374Z",
        "previous_pointer_sha256": "d" * 64,
        "previous_release_id": previous["release_id"],
        "previous_release_manifest_path": str(previous_path),
        "previous_release_manifest_sha256": module._sha256(previous_path),
    }


def _prepare_v1_migration_world(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    active_newline: bytes = b"\r\n",
    previous_newline: bytes = b"\n",
) -> dict[str, object]:
    previous, previous_path, previous_rendering = _write_pure_v1_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="a",
        newline=previous_newline,
        marker=b"previous-rendering\n",
        release_suffix="4d3458d9901c09b1",
    )
    active, active_path, active_rendering = _write_pure_v1_release(
        module,
        tmp_path,
        monkeypatch,
        image_character="b",
        newline=active_newline,
        marker=b"active-rendering\n",
        release_suffix="0a7aea3f2ed52581",
    )
    installed = _install_drifted_skill(
        module, tmp_path, monkeypatch, active_rendering=active_rendering
    )
    pointer_path = module._state_paths()["pointer"]
    legacy = _legacy_pointer_for_v1(module, active, active_path, previous, previous_path)
    module._write_json_atomic(pointer_path, legacy)
    return {
        "active": active,
        "active_path": active_path,
        "active_rendering": active_rendering,
        "previous": previous,
        "previous_path": previous_path,
        "previous_rendering": previous_rendering,
        "installed": installed,
        "pointer_path": pointer_path,
        "legacy": legacy,
        "legacy_bytes": pointer_path.read_bytes(),
        "installed_snapshot": {
            relative.as_posix(): (installed / relative).read_bytes()
            for relative in [
                path.relative_to(installed)
                for path in installed.rglob("*")
                if path.is_file()
            ]
        },
    }


def test_bootstrap_migrate_success_from_pure_v1_and_crlf_lf_renderings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    # Active rendering is CRLF; previous is LF — commit identity alone is insufficient.
    active_skill_md = (world["active_rendering"] / "SKILL.md").read_bytes()
    previous_skill_md = (world["previous_rendering"] / "SKILL.md").read_bytes()
    assert b"\r\n" in active_skill_md
    assert b"\r\n" not in previous_skill_md
    assert world["active"]["source_identity"]["source_commit"] == (
        world["previous"]["source_identity"]["source_commit"]
    )
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    assert receipt["completion_claim_allowed"] is False
    assert receipt["pointer_generation"] == 1
    assert "legacy_restore_tree_sha256" in receipt
    pointer = module._load_json(world["pointer_path"])
    assert pointer["schema_version"] == module.CURRENT_POINTER_SCHEMA
    assert pointer["generation"] == 1
    # Constructed protocol-2 targets, not the raw v1 release ids alone as complete releases.
    assert pointer["active"]["release_id"] != world["active"]["release_id"] or (
        module._state_paths()["release_root"]
        / pointer["active"]["release_id"]
        / "skill-bundle"
    ).is_dir()
    assert (module._state_paths()["release_root"] / pointer["active"]["release_id"] / "skill-bundle").is_dir()
    assert (
        module._state_paths()["release_root"]
        / pointer["previous_verified"]["release_id"]
        / "skill-bundle"
    ).is_dir()
    # Original pure v1 directories remain reconstructible (only release.json).
    assert sorted(
        path.name
        for path in (module._state_paths()["release_root"] / world["active"]["release_id"]).iterdir()
    ) == ["release.json"]
    journal = module._load_json(module._journal_path(pointer["active"]["activation_txn_id"]))
    assert journal["operation"] == "MIGRATE"
    assert journal["state"] == "VERIFIED"
    assert journal["from"]["legacy_restore_tree_sha256"] == receipt["legacy_restore_tree_sha256"]
    context = module._load_current_context(require_terminal=True)
    assert context["release"]["required_bootstrap_protocol"] == 2


def test_bootstrap_migrate_wrong_line_ending_material_fails_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    # Replace active rendering with LF bytes while v1 skill_hashes still seal CRLF.
    wrong = module._source_rendering_root(str(world["active"]["release_id"]))
    import shutil

    shutil.rmtree(wrong)
    _copy_skill_tree(SKILL_ROOT, wrong, newline=b"\n")
    marker = wrong / "references" / "migration-marker.txt"
    marker.write_bytes(b"active-rendering\n")
    before = world["pointer_path"].read_bytes()
    installed_before = {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    }
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "MIGRATION_SOURCE_RENDERING_HASH_MISMATCH"
    assert world["pointer_path"].read_bytes() == before
    assert {
        path.relative_to(world["installed"]).as_posix(): path.read_bytes()
        for path in world["installed"].rglob("*")
        if path.is_file()
    } == installed_before


def test_bootstrap_migrate_captures_exact_drifted_live_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    receipt = module.bootstrap_migrate()
    journal = module._load_json(module._journal_path(receipt["txn_id"]))
    restore_root = Path(journal["from"]["legacy_restore_path"])
    restored_skill = restore_root / "installed_skill"
    for relative, payload in world["installed_snapshot"].items():
        assert (restored_skill / relative).read_bytes() == payload
    # Drifted files must not equal the active historical rendering.
    assert (restored_skill / "SKILL.md").read_bytes() != (
        world["active_rendering"] / "SKILL.md"
    ).read_bytes()


def test_bootstrap_migrate_missing_previous_rendering_zero_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    import shutil

    shutil.rmtree(module._source_rendering_root(str(world["previous"]["release_id"])))
    before = world["pointer_path"].read_bytes()
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "ROLLBACK_MATERIAL_ABSENT"
    assert world["pointer_path"].read_bytes() == before
    assert not any(
        (module._state_paths()["transaction_root"]).glob("*/activation.v1.json")
    ) if module._state_paths()["transaction_root"].exists() else True


def test_bootstrap_migrate_corrupt_v1_manifest_zero_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    world["active_path"].write_text("{not-json", encoding="utf-8")
    before = world["pointer_path"].read_bytes()
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code in {
        "JSON_READ_FAILED",
        "RELEASE_MANIFEST_IDENTITY_MISMATCH",
        "MIGRATION_RELEASE_INCOMPLETE",
    }
    assert world["pointer_path"].read_bytes() == before


def test_bootstrap_migrate_pointer_cas_conflict_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    pointer_path = world["pointer_path"]
    original_switch = module._switch_migrate_pointer

    def drift_then_switch(journal, journal_path):
        drifted = module._load_json(pointer_path)
        drifted["promoted_at"] = "2026-07-30T00:00:00Z"
        module._write_json_atomic(pointer_path, drifted)
        return original_switch(journal, journal_path)

    monkeypatch.setattr(module, "_switch_migrate_pointer", drift_then_switch)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "CURRENT_POINTER_CAS_CONFLICT"
    assert module._load_json(pointer_path)["schema_version"] == module.LEGACY_POINTER_SCHEMA
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "MIGRATE"
    assert pending[0][0]["state"] == "PREPARED"


def test_bootstrap_migrate_repeated_invocation_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    first = module.bootstrap_migrate()
    pointer_after = world["pointer_path"].read_bytes()
    journal_path = module._journal_path(first["txn_id"])
    journal_after = journal_path.read_bytes()
    second = module.bootstrap_migrate()
    assert first["status"] == "MIGRATED"
    assert second["status"] == "ALREADY_MIGRATED"
    assert world["pointer_path"].read_bytes() == pointer_after
    assert journal_path.read_bytes() == journal_after


def test_bootstrap_migrate_interrupted_prepared_boundary_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    pointer_path = world["pointer_path"]
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    original_continue = module._continue_migrate_journal
    calls = {"count": 0}

    def stop_after_prepare(journal, journal_path):
        calls["count"] += 1
        if calls["count"] == 1:
            assert journal["state"] == "PREPARED"
            assert module._load_json(pointer_path)["schema_version"] == module.LEGACY_POINTER_SCHEMA
            raise module.XinaoError("INJECTED_CRASH", "prepared boundary")
        return original_continue(journal, journal_path)

    monkeypatch.setattr(module, "_continue_migrate_journal", stop_after_prepare)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["state"] == "PREPARED"
    monkeypatch.setattr(module, "_continue_migrate_journal", original_continue)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    pointer = module._load_json(pointer_path)
    assert pointer["schema_version"] == module.CURRENT_POINTER_SCHEMA
    journal = module._load_json(module._journal_path(pointer["active"]["activation_txn_id"]))
    assert journal["state"] == "VERIFIED"
    assert not module._pending_journals()


def test_bootstrap_migrate_crash_after_pointer_switch_recovers_or_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    installed = world["installed"]
    installed_before = {
        path.relative_to(installed).as_posix(): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    }
    legacy_bytes = world["legacy_bytes"]

    def fail_canary(journal):
        raise module.XinaoError("INJECTED_CANARY_FAILURE", "post-switch")

    monkeypatch.setattr(module, "_run_activation_canary", fail_canary)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "ROLLED_BACK"
    assert world["pointer_path"].read_bytes() == legacy_bytes
    assert module._load_json(world["pointer_path"])["schema_version"] == module.LEGACY_POINTER_SCHEMA
    assert {
        path.relative_to(installed).as_posix(): path.read_bytes()
        for path in installed.rglob("*")
        if path.is_file()
    } == installed_before
    # Pure v1 release directories restored.
    assert sorted(
        path.name
        for path in (module._state_paths()["release_root"] / world["active"]["release_id"]).iterdir()
    ) == ["release.json"]


def test_bootstrap_migrate_crash_after_pointer_switch_then_recover_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POINTER_SWITCHED crash must leave recoverable journal that can finish v2 activation."""

    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    original_switch = module._switch_migrate_pointer
    calls = {"count": 0}

    def switch_then_crash(journal, journal_path):
        calls["count"] += 1
        switched = original_switch(journal, journal_path)
        if calls["count"] == 1:
            raise module.XinaoError("INJECTED_CRASH", "after pointer switch")
        return switched

    monkeypatch.setattr(module, "_switch_migrate_pointer", switch_then_crash)
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "INJECTED_CRASH"
    pending = module._pending_journals()
    assert len(pending) == 1
    assert pending[0][0]["operation"] == "MIGRATE"
    assert pending[0][0]["state"] == "POINTER_SWITCHED"
    assert module._load_json(world["pointer_path"])["schema_version"] == module.CURRENT_POINTER_SCHEMA
    monkeypatch.setattr(module, "_switch_migrate_pointer", original_switch)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"
    journal = module._load_json(module._journal_path(receipt["txn_id"]))
    assert journal["state"] == "VERIFIED"
    assert not module._pending_journals()


def test_bootstrap_migrate_cli_absorbs_technical_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    exit_code = module.main(["bootstrap-migrate"])
    assert exit_code == 0
    assert (
        module._load_json(world["pointer_path"])["schema_version"]
        == module.CURRENT_POINTER_SCHEMA
    )
    exit_code = module.main(
        ["bootstrap-migrate", "--compat-release", str(world["active"]["release_id"])]
    )
    assert exit_code == 2


def test_bootstrap_migrate_companion_runtime_tamper_fails_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap = _bootstrap_module()
    runtime_path = bootstrap._companion_runtime_path()
    original = runtime_path.read_bytes()
    try:
        runtime_path.write_bytes(original + b"\n# tampered\n")
        with pytest.raises(bootstrap.BootstrapError) as failure:
            bootstrap._run_companion_runtime(["bootstrap-migrate"])
        assert failure.value.reason_code == "COMPANION_RUNTIME_IDENTITY_MISMATCH"
    finally:
        runtime_path.write_bytes(original)


def test_bootstrap_migrate_concurrent_second_lock_holder_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    world = _prepare_v1_migration_world(module, tmp_path, monkeypatch)
    monkeypatch.setattr(
        module, "_run_activation_canary", lambda value: _canary_value(module, value)
    )
    # Simulate OS lock contention with a non-reentrant hold (portable across FS).
    from contextlib import contextmanager

    gate = threading.Lock()
    ready = threading.Event()
    release = threading.Event()

    @contextmanager
    def contended_lock():
        if not gate.acquire(blocking=False):
            raise module.XinaoError("ACTIVATION_LOCK_TIMEOUT", "contended")
        try:
            yield
        finally:
            gate.release()

    monkeypatch.setattr(module, "_activation_lock", contended_lock)

    def holder() -> None:
        with module._activation_lock():
            ready.set()
            release.wait(timeout=10)

    worker = threading.Thread(target=holder)
    worker.start()
    assert ready.wait(timeout=5)
    before = world["pointer_path"].read_bytes()
    with pytest.raises(module.XinaoError) as failure:
        module.bootstrap_migrate()
    assert failure.value.reason_code == "ACTIVATION_LOCK_TIMEOUT"
    assert world["pointer_path"].read_bytes() == before
    release.set()
    worker.join(timeout=5)
    receipt = module.bootstrap_migrate()
    assert receipt["status"] == "MIGRATED"


def test_generic_worker_arguments_get_typed_rejection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    exit_code = module.main(["research", "--question", "q", "--CommonWorkKey", "wrong"])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["reason_codes"] == ["INVOCATION_ARGUMENTS_INVALID"]
    assert result["user_operations_required"] == []


@pytest.mark.parametrize(
    "txn_id",
    (
        "..",
        "C:/absolute/activation",
        "xra_20260730T120000_../../escape",
    ),
)
def test_thin_rejects_malicious_transaction_ids_before_path_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, txn_id: str
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    pointer, _journal, _journal_path = _terminal_pointer(runtime, manifest, manifest_path)
    pointer["active"]["activation_txn_id"] = txn_id
    runtime._write_json_atomic(runtime._state_paths()["pointer"], pointer)
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._runtime_entry_locked(["inspect"], tmp_path / "state")
    assert failure.value.reason_code == "ACTIVATION_TRANSACTION_ID_INVALID"


@pytest.mark.parametrize("mutation", ("extra_key", "unknown_state", "redirect_from"))
def test_thin_pending_journal_shape_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    first, first_path = _sealed_release(runtime, tmp_path, monkeypatch, image_character="a")
    _terminal_pointer(runtime, first, first_path)
    second, second_path = _sealed_release(
        runtime, tmp_path, monkeypatch, image_character="b", variant=b"pending"
    )
    with runtime._activation_lock():
        current = runtime._load_current_context()
        journal, journal_path = runtime._prepare_activation(
            current,
            target_manifest=second,
            target_manifest_path=second_path,
            operation="ACTIVATE",
        )
    if mutation == "extra_key":
        journal["unexpected"] = True
    elif mutation == "unknown_state":
        journal["state"] = "UNKNOWN"
    else:
        journal["from"]["active"]["release_manifest_path"] = str(
            tmp_path / "redirected-release.json"
        )
    runtime._write_json_atomic(journal_path, journal)
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._pending_activation_journals(tmp_path / "state")
    expected = {
        "extra_key": "ACTIVATION_JOURNAL_SCHEMA_INVALID",
        "unknown_state": "ACTIVATION_STATE_INVALID",
        "redirect_from": "RELEASE_MANIFEST_PATH_INVALID",
    }
    assert failure.value.reason_code == expected[mutation]


@pytest.mark.parametrize("mutation", ("extra_key", "identity_drift", "skill_hash_drift"))
def test_thin_release_schema_and_identity_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    candidate = json.loads(json.dumps(manifest))
    if mutation == "extra_key":
        candidate["unexpected"] = True
    elif mutation == "identity_drift":
        candidate["release_identity_sha256"] = "0" * 64
    else:
        candidate["skill_hashes"]["skill_md_sha256"] = "0" * 64
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._validate_release_manifest_shape(
            candidate,
            manifest_path=manifest_path,
            state_root=tmp_path / "state",
        )
        bootstrap._validate_release_skill_hashes(candidate, Path(candidate["skill_bundle_path"]))
    assert failure.value.reason_code in {
        "RELEASE_SCHEMA_INVALID",
        "RELEASE_IDENTITY_MISMATCH",
        "RELEASE_IMAGE_IDENTITY_INVALID",
        "RELEASE_SKILL_HASHES_MISMATCH",
    }


@pytest.mark.parametrize("mutation", ("case_collision", "extra_empty_dir", "too_many"))
def test_thin_bundle_inventory_rejects_case_empty_dir_and_count_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime = _module()
    manifest, manifest_path = _sealed_release(runtime, tmp_path, monkeypatch)
    active = runtime._release_ref_from_manifest(
        manifest,
        manifest_path,
        activation_txn_id="xra_20260730T120000_" + "1" * 16,
    )
    bundle_manifest_path = Path(manifest["skill_bundle_manifest_path"])
    bundle_manifest = runtime._load_json(bundle_manifest_path)
    if mutation == "case_collision":
        row = dict(bundle_manifest["files"][0])
        row["relative_path"] = str(row["relative_path"]).swapcase()
        bundle_manifest["files"].append(row)
        bundle_manifest["files"].sort(key=lambda value: value["relative_path"])
    elif mutation == "too_many":
        template = dict(bundle_manifest["files"][0])
        bundle_manifest["files"] = [
            {
                **template,
                "relative_path": f"bulk/{index:04d}.txt",
            }
            for index in range(4097)
        ]
    else:
        (Path(manifest["skill_bundle_path"]) / "empty-extra").mkdir()
    if mutation != "extra_empty_dir":
        bundle_manifest["tree_sha256"] = runtime._sha256_bytes(
            runtime._canonical_bytes(bundle_manifest["files"])
        )
        runtime._write_json_atomic(bundle_manifest_path, bundle_manifest)
        manifest["skill_bundle_manifest_sha256"] = runtime._sha256(bundle_manifest_path)
        manifest["skill_bundle_tree_sha256"] = bundle_manifest["tree_sha256"]
        active["skill_bundle_manifest_sha256"] = manifest["skill_bundle_manifest_sha256"]
        active["skill_bundle_tree_sha256"] = manifest["skill_bundle_tree_sha256"]
    bootstrap = _bootstrap_module()
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap._validate_bundle(
            release_root=manifest_path.parent,
            manifest=manifest,
            active=active,
        )
    expected_codes = {
        "case_collision": {"SKILL_BUNDLE_PATH_COLLISION"},
        "extra_empty_dir": {"SKILL_BUNDLE_FILE_SET_MISMATCH"},
        "too_many": {"SKILL_BUNDLE_INVENTORY_INVALID"},
    }
    assert failure.value.reason_code in expected_codes[mutation]


def test_thin_child_executes_the_exact_verified_runtime_bytes() -> None:
    bootstrap = _bootstrap_module()
    payload = b"import sys\nsys.stdout.write('verified-runtime-bytes')\n"
    wrapper = bootstrap._runtime_wrapper(Path("sealed/runtime.py"), payload)
    completed = subprocess.run(
        [sys.executable, "-I", "-"],
        input=wrapper,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == b"verified-runtime-bytes"
    assert completed.stderr == b""
    assert b"os.execv" not in wrapper


def test_thin_handoff_timeout_reaps_only_its_child_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    state_root = _state(runtime, tmp_path, monkeypatch)
    bootstrap = _bootstrap_module()
    monkeypatch.setattr(bootstrap, "RUNTIME_HANDOFF_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(bootstrap, "RUNTIME_REAP_TIMEOUT_SECONDS", 1.0)
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    started = time.monotonic()
    try:
        with pytest.raises(bootstrap.BootstrapError) as failure:
            with bootstrap._activation_lock(state_root):
                bootstrap._handoff_runtime_wrapper(process, b"x" * (8 * 1024 * 1024))
        assert failure.value.reason_code == "SKILL_RUNTIME_HANDOFF_FAILED"
        assert time.monotonic() - started < 5.0
        assert process.poll() is not None
        assert process.stdin is None
        assert not any(
            thread.name == "xinao-runtime-handoff" and thread.is_alive()
            for thread in threading.enumerate()
        )
        with bootstrap._activation_lock(state_root):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_thin_wrapper_preserves_non_ascii_runtime_and_state_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _module()
    unicode_root = tmp_path / "新澳状态根"
    manifest, manifest_path = _sealed_release(runtime, unicode_root, monkeypatch)
    _terminal_pointer(runtime, manifest, manifest_path)
    state_root = runtime._state_paths()["state_root"]
    bootstrap = _bootstrap_module()
    runtime_path, _runtime_payload, fence = bootstrap._runtime_entry_locked(["inspect"], state_root)
    assert "新澳状态根" in str(runtime_path)
    assert fence["state_root"] == str(state_root)
    encoded_fence = json.dumps(
        fence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    assert json.loads(encoded_fence.decode("ascii")) == fence
    probe = (
        "# -*- coding: utf-8 -*-\n"
        "import json, sys\n"
        "_value = json.dumps({'runtime_path': __file__, 'value': '新澳'}, ensure_ascii=False)\n"
        "sys.stdout.buffer.write((_value + '\\n').encode('utf-8'))\n"
    ).encode("utf-8")
    wrapper = bootstrap._runtime_wrapper(runtime_path, probe)
    wrapper.decode("ascii")
    completed = subprocess.run(
        [sys.executable, "-I", "-"],
        input=wrapper,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == b""
    observed = json.loads(completed.stdout.decode("utf-8"))
    assert observed == {"runtime_path": str(runtime_path), "value": "新澳"}
