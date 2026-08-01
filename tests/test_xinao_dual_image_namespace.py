"""Focused tests: dual-image release identity + host tool-namespace hardening.

No live Docker builds. No host-state mutation of real D-state.
completion_claim_allowed remains false. Profile status is TOOL_NAMESPACE_VERIFIED
only (never scientist role fitness).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
RUNTIME_PATH = SKILL_ROOT / "scripts" / "xinao_runtime.py"
BOOTSTRAP_PATH = SKILL_ROOT / "scripts" / "xinao.py"
SPECS_PATH = ROOT / "docker" / "xinao-researcher" / "docker_create_specs.py"


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def module() -> Any:
    return _load("xinao_runtime_dual_ns", RUNTIME_PATH)


@pytest.fixture
def specs() -> Any:
    return _load("xinao_docker_create_specs_dual_ns", SPECS_PATH)


def _state(module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state))
    monkeypatch.setenv("XINAO_RESEARCHER_RUN_ROOT", str(tmp_path / "runs"))
    lock = state / "researcher_container" / ".activation.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"\0")
    return state


def _tool_digests(module: Any) -> tuple[str, str]:
    tool_df = ROOT / module.TOOL_EXECUTOR_DOCKERFILE_RELATIVE
    df_sha = module._sha256_bytes(tool_df.read_bytes())
    rows = module._collect_tool_executor_module_rows(ROOT)
    mod_sha = module._tool_executor_modules_tree_sha256(rows)
    return df_sha, mod_sha


def _make_dual_manifest(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, Path]:
    from tests import test_xinao_skill as skill_tests

    return skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )


def _fake_tool_inspect(
    *,
    image_id: str,
    cid: str,
    lab: str,
    ipc: str,
    entrypoint: list[str] | None = None,
    cmd: list[str] | None = None,
    extra_mounts: list[dict[str, str]] | None = None,
    env: list[str] | None = None,
    sidecar: str | None = None,
) -> dict[str, Any]:
    mounts = [
        {"Destination": "/episode-lab", "Source": lab, "Type": "bind", "Mode": "rw"},
        {"Destination": "/ipc", "Source": ipc, "Type": "bind", "Mode": "rw"},
    ]
    if sidecar:
        mounts.append(
            {
                "Destination": "/sidecar-evidence",
                "Source": sidecar,
                "Type": "bind",
                "Mode": "rw",
            }
        )
    if extra_mounts:
        mounts.extend(extra_mounts)
    if entrypoint is None:
        entrypoint = [
            "python",
            "-I",
            "/opt/xinao-tool-executor/tool_executor.py",
            "--lab-root",
            "/episode-lab",
            "--socket",
            "/ipc/tool.sock",
            "--replay-state-dir",
            "/ipc/.xinao-replay",
        ]
    if env is None:
        env = [
            "HOME=/tmp",
            "TMPDIR=/tmp",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8",
            "XINAO_TOOL_EXEC_BWRAP=require",
            "XINAO_IPC_PEER_REQUIRE=1",
            "XINAO_IPC_PEER_UIDS=0",
            "XINAO_REPLAY_STATE_DIR=/ipc/.xinao-replay",
            "XINAO_TOOL_SIDECAR_EVIDENCE_DIR=/sidecar-evidence",
            "XINAO_TOOL_SIDECAR_EVENTS_PATH=/sidecar-evidence/tool_events.jsonl",
        ]
    return {
        "Id": cid,
        "Image": image_id,
        "Config": {
            "User": "65532:65532",
            "Image": image_id,
            "Entrypoint": list(entrypoint),
            "Cmd": list(cmd) if cmd is not None else None,
            "Env": list(env),
            "Labels": {
                "io.xinao.researcher.role": "tool_executor",
                "io.xinao.researcher.auth-mount": "forbidden",
            },
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": mounts,
    }


def _fake_transport_inspect(
    *,
    image_id: str,
    cid: str,
    auth: str,
    lab_input: str,
    lab_output: str,
    ipc: str,
    entrypoint: list[str] | None = None,
    cmd: list[str] | None = None,
) -> dict[str, Any]:
    mounts = [
        {
            "Destination": "/grok-home/auth.json",
            "Source": auth,
            "Type": "bind",
            "Mode": "ro",
            "RW": False,
        },
        {
            "Destination": "/input",
            "Source": lab_input,
            "Type": "bind",
            "Mode": "ro",
            "RW": False,
        },
        {
            "Destination": "/output",
            "Source": lab_output,
            "Type": "bind",
            "Mode": "rw",
            "RW": True,
        },
        {"Destination": "/ipc", "Source": ipc, "Type": "bind", "Mode": "rw", "RW": True},
    ]
    if entrypoint is None:
        entrypoint = ["python", "-I", "-c"]
    if cmd is None:
        cmd = ["import time; time.sleep(3600)"]
    return {
        "Id": cid,
        "Image": image_id,
        "Config": {
            "User": "0:0",
            "Image": image_id,
            "Entrypoint": list(entrypoint),
            "Cmd": list(cmd),
            "Env": [
                "HOME=/grok-home",
                "GROK_HOME=/grok-home",
                "XINAO_DUAL_CONTAINER=1",
                "XINAO_GENERIC_FILE_SHELL_TOOLS=0",
            ],
            "Labels": {
                "io.xinao.researcher.role": "transport_model",
                "io.xinao.researcher.auth-mount": "required",
            },
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": mounts,
    }


def _install_docker_io_mock(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    transport_image_id: str,
    tool_image_id: str,
    fail_create: bool = False,
    fail_proof: str | None = None,
    fail_start: bool = False,
    fail_exec_plumbing: bool = False,
    wrong_executable: bool = False,
    unrelated_nonzero: bool = False,
) -> dict[str, Any]:
    """Monkeypatch narrow Docker I/O only — no production probe injector."""

    deny_exit = int(getattr(module, "TOOL_NAMESPACE_DENY_PROOF_EXIT", 17))
    state: dict[str, Any] = {
        "containers": {},
        "creates": 0,
        "execs": [],
        "starts": 0,
        "receipt_attempts": 0,
    }

    def fake_docker() -> str:
        return "docker"

    def fake_engine_os(_docker: str) -> str:
        return "linux"

    def fake_image(_docker: str, image: str) -> dict[str, Any]:
        if image == transport_image_id:
            return {
                "Id": transport_image_id,
                "Config": {
                    "Labels": {
                        "io.xinao.researcher.role": "transport_model",
                        "io.xinao.researcher.auth-mount": "required",
                    },
                    "Entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
                },
            }
        if image == tool_image_id:
            return {
                "Id": tool_image_id,
                "Config": {
                    "Labels": {
                        "io.xinao.researcher.role": "tool_executor",
                        "io.xinao.researcher.auth-mount": "forbidden",
                    },
                    "Entrypoint": [
                        "python",
                        "-I",
                        "/opt/xinao-tool-executor/tool_executor.py",
                        "--lab-root",
                        "/episode-lab",
                        "--socket",
                        "/ipc/tool.sock",
                    ],
                },
            }
        return {"Id": image if str(image).startswith("sha256:") else "sha256:" + "0" * 64}

    def fake_run(arguments: list[str], **kwargs: Any) -> Any:
        argv = [str(a) for a in arguments]
        check = kwargs.get("check", True)

        class Result:
            def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = rc
                self.stdout = stdout
                self.stderr = stderr

        if len(argv) >= 2 and argv[1] == "create":
            state["creates"] += 1
            if fail_create:
                if check:
                    raise module.XinaoError("DOCKER_CREATE_FAILED", "mock")
                return Result(1, "", "create failed")
            cid = f"cid{state['creates']:04d}{hashlib.sha256(str(state['creates']).encode()).hexdigest()[:8]}"
            # Recover bind sources from --mount flags for inspect.
            lab = "/host/lab"
            ipc = "/host/ipc"
            sidecar = ""
            auth = ""
            tin = "/host/tin"
            tout = "/host/tout"
            for i, token in enumerate(argv):
                if token == "--mount" and i + 1 < len(argv):
                    mount = argv[i + 1]
                    src = ""
                    dst = ""
                    for part in mount.split(","):
                        if part.startswith("src="):
                            src = part[4:]
                        if part.startswith("dst="):
                            dst = part[4:]
                    if dst in {"/episode-lab", "/episode-lab/"}:
                        lab = src or lab
                    if dst in {"/ipc", "/ipc/"}:
                        ipc = src or ipc
                    if dst in {"/sidecar-evidence", "/sidecar-evidence/"}:
                        sidecar = src
                    if dst in {"/grok-home/auth.json"} or dst.endswith("auth.json"):
                        auth = src
                    if dst in {"/input", "/input/"}:
                        tin = src or tin
                    if dst in {"/output", "/output/"}:
                        tout = src or tout
            # Real Docker CLI: --entrypoint is a single executable token; rest is Cmd.
            entrypoint: list[str] | None = None
            cmd: list[str] | None = None
            image_for_create = tool_image_id
            if "--entrypoint" in argv:
                ep_idx = argv.index("--entrypoint")
                ep = argv[ep_idx + 1]
                assert not ep.lstrip().startswith("["), f"JSON-text entrypoint forbidden: {ep!r}"
                assert " " not in ep, f"entrypoint must be single token: {ep!r}"
                image_idx = None
                for j in range(ep_idx + 2, len(argv)):
                    tok = argv[j]
                    if tok.startswith("-"):
                        continue
                    # first non-flag after entrypoint is IMAGE
                    image_idx = j
                    break
                assert image_idx is not None
                entrypoint = [ep]
                cmd = argv[image_idx + 1 :]
                image_tok = argv[image_idx]
                if image_tok == transport_image_id:
                    image_for_create = transport_image_id
                elif image_tok == tool_image_id:
                    image_for_create = tool_image_id
            role = "transport" if auth or image_for_create == transport_image_id else "tool"
            state["containers"][cid] = {
                "role": role,
                "image": image_for_create,
                "lab": lab,
                "ipc": ipc,
                "sidecar": sidecar,
                "auth": auth,
                "tin": tin,
                "tout": tout,
                "started": False,
                "running": False,
                "entrypoint": entrypoint,
                "cmd": cmd,
            }
            return Result(0, cid + "\n", "")

        if len(argv) >= 3 and argv[1] == "inspect":
            # docker inspect -f {{.State.Running}} cid
            if len(argv) >= 5 and argv[2] == "-f":
                cid = argv[4] if len(argv) > 4 else argv[-1]
                meta = state["containers"].get(cid)
                if meta is None:
                    return Result(1, "", "missing")
                return Result(0, "true\n" if meta.get("running") else "false\n", "")
            cid = argv[2]
            meta = state["containers"].get(cid)
            if meta is None:
                if check:
                    raise module.XinaoError("DOCKER_INSPECT_FAILED", cid)
                return Result(1, "", "missing")
            if meta.get("role") == "transport":
                doc = _fake_transport_inspect(
                    image_id=meta["image"],
                    cid=cid,
                    auth=meta.get("auth") or "/host/auth.json",
                    lab_input=meta.get("tin") or "/host/tin",
                    lab_output=meta.get("tout") or "/host/tout",
                    ipc=meta["ipc"],
                    entrypoint=meta.get("entrypoint"),
                    cmd=meta.get("cmd"),
                )
            else:
                doc = _fake_tool_inspect(
                    image_id=meta["image"],
                    cid=cid,
                    lab=meta["lab"],
                    ipc=meta["ipc"],
                    sidecar=meta.get("sidecar") or None,
                    entrypoint=meta.get("entrypoint"),
                    cmd=meta.get("cmd"),
                )
            return Result(0, json.dumps([doc]), "")

        if len(argv) >= 3 and argv[1] == "start":
            state["starts"] += 1
            cid = argv[2]
            if fail_start:
                return Result(1, "", "Error: OCI runtime create failed: executable file not found")
            if cid in state["containers"]:
                state["containers"][cid]["started"] = True
                state["containers"][cid]["running"] = True
            return Result(0, cid, "")

        if len(argv) >= 3 and argv[1] == "exec":
            cid = argv[2]
            exec_cmd = argv[3:]
            state["execs"].append({"cid": cid, "cmd": exec_cmd})
            if fail_exec_plumbing:
                return Result(
                    127, "", "OCI runtime exec failed: exec failed: executable file not found"
                )
            if wrong_executable:
                return Result(127, "", "executable file not found in $PATH: not-a-real-bin")
            joined = " ".join(exec_cmd)
            meta = state["containers"].get(cid) or {}
            # Transport positive path-identity probe (placeholder auth, no byte dump).
            if (
                meta.get("role") == "transport"
                and "os.path.isfile" in joined
                and "/grok-home/auth.json" in joined
            ):
                return Result(0, "", "transport_auth_path_ok")
            # Default: isolation probes return dedicated denial marker exit.
            rc = deny_exit
            if unrelated_nonzero:
                rc = 1
            if fail_proof == "credential_read_denied" and "auth.json" in joined:
                rc = 0
            if fail_proof == "path_traversal_denied" and (
                "auth.json" in joined or "realpath" in joined or "../" in joined
            ):
                rc = 0
            if fail_proof == "symlink_escape_denied" and (
                "escape" in joined or "auth_escape" in joined
            ):
                rc = 0
            if fail_proof == "worktree_escape_denied" and "/workspace" in joined:
                rc = 0
            if fail_proof == "ledger_outcome_mutation_denied" and "/ledger" in joined:
                rc = 0
            return Result(rc, "", "denied" if rc == deny_exit else "ok")

        if len(argv) >= 2 and argv[1] in {"rm", "stop"}:
            if len(argv) >= 3:
                cid = argv[-1]
                if cid in state["containers"]:
                    state["containers"][cid]["running"] = False
            return Result(0, "", "")

        if check:
            raise module.XinaoError("DOCKER_UNEXPECTED", " ".join(argv[:6]))
        return Result(1, "", "unexpected")

    monkeypatch.setattr(module, "_docker", fake_docker)
    monkeypatch.setattr(module, "_docker_engine_os", fake_engine_os)
    monkeypatch.setattr(module, "_docker_image", fake_image)
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_validate_release_image_identity", lambda _r: "docker")
    return state


def _seed_canonical_receipt(
    module: Any,
    *,
    release: dict[str, Any],
    transport_image_id: str,
    tool_image_id: str,
    mutate: Any | None = None,
    write_pointer: bool = True,
) -> tuple[Path, dict[str, Any], Path]:
    security_root = module._tool_namespace_security_root()
    security_root.mkdir(parents=True, exist_ok=True)
    import datetime as dt

    now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    receipt_id = f"tnsr_test_seed_{uuid.uuid4().hex[:12]}"
    receipt: dict[str, Any] = {
        "schema_version": module.TOOL_NAMESPACE_RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "issuer": "host_security_evidence",
        "profile_id": module.GENUINE_SCIENTIST_PROFILE_ID,
        "tool_namespace_isolated": True,
        "auth_reachable_from_model_tools": False,
        "ledger_writable_from_model_tools": False,
        "freeze_writable_from_model_tools": False,
        "outcome_writable_from_model_tools": False,
        "same_container_file_tools_allowed": False,
        "negative_proof_ids": list(module.TOOL_NAMESPACE_RECEIPT_REQUIRED_NEGATIVE_PROOF_IDS),
        "transport_image_id": transport_image_id,
        "tool_image_id": tool_image_id,
        "release_id": release["release_id"],
        "release_identity_sha256": release["release_identity_sha256"],
        "sealed_at": now,
        "physical_proof": True,
        "evidence_class": "live_physical_host",
        "synthetic": False,
        "authority": False,
        "completion_claim_allowed": False,
        "science_restored": False,
        "parent_complete": False,
        "owner_adopted": False,
    }
    if mutate is not None:
        mutate(receipt)
    receipt_path = security_root / f"{receipt_id}.json"
    module._write_json_atomic(receipt_path, receipt, create_new=True)
    pointer_path = security_root / "current.json"
    if write_pointer:
        pointer = {
            "schema_version": module.TOOL_NAMESPACE_CURRENT_POINTER_SCHEMA,
            "receipt_id": receipt_id,
            "receipt_path": str(receipt_path),
            "receipt_sha256": module._sha256(receipt_path),
            "transport_image_id": transport_image_id,
            "tool_image_id": tool_image_id,
            "release_id": release["release_id"],
            "release_identity_sha256": release["release_identity_sha256"],
            "sealed_at": now,
            "authority": False,
            "completion_claim_allowed": False,
        }
        # Pointer is mutable current; overwrite is expected.
        module._write_json_atomic(pointer_path, pointer, create_new=False)
    return receipt_path, receipt, pointer_path


def test_semver_source_is_1_3_14_and_1_2_10(module: Any) -> None:
    """Current dual-image identity: Skill 1.3.14 / researcher capability 1.2.10."""
    registry = json.loads((SKILL_ROOT / "references" / "capabilities.v1.json").read_text())
    charter = json.loads((SKILL_ROOT / "references" / "researcher-charter.v1.json").read_text())
    runtime_lock = json.loads(
        (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text()
    )
    researcher = next(
        c for c in registry["capabilities"] if c["capability_id"] == "researcher-container"
    )
    assert registry["skill_version"] == "1.3.14"
    assert (
        researcher["version"]
        == charter["charter_version"]
        == runtime_lock["runtime_version"]
        == "1.2.10"
    )
    shadow = next(
        c for c in registry["capabilities"] if c["capability_id"] == "shadow-lifecycle-leg-a"
    )
    assert shadow["version"] == "0.3.0"


def test_dual_image_identity_bound_in_current_release(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, path = _make_dual_manifest(module, tmp_path, monkeypatch)
    assert "tool_image_id" in manifest
    assert manifest["tool_image_id"].startswith("sha256:")
    assert manifest["tool_image_id"] != manifest["image_id"]
    assert manifest["tool_image_entrypoint"] == list(module.TOOL_EXECUTOR_ENTRYPOINT)
    assert manifest["tool_image_labels"]["io.xinao.researcher.role"] == "tool_executor"
    df_sha, mod_sha = _tool_digests(module)
    assert manifest["source_identity"]["tool_executor_dockerfile_sha256"] == df_sha
    assert manifest["source_identity"]["tool_executor_modules_tree_sha256"] == mod_sha
    module._validate_release_manifest(manifest, path)


def test_historical_pre_tool_image_still_readable(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-tool-image generation remains valid through generation-aware path."""
    _state(module, tmp_path, monkeypatch)
    source_rows = module._source_bundle_files(SKILL_ROOT)
    bundle_manifest = module._skill_bundle_manifest(source_rows, package_version="1.3.4")
    hashes = module._reference_hashes(SKILL_ROOT)
    shadow_lock = module._load_shadow_runtime_lock(SKILL_ROOT)
    shadow_rows = module._collect_shadow_runtime_rows(ROOT, shadow_lock)
    shadow_tree = module._shadow_runtime_tree_sha256(shadow_rows)
    modules_tree = module._researcher_image_modules_tree_sha256(
        module._collect_researcher_image_module_rows(ROOT)
    )
    source_identity = {
        "source_commit": "c" * 40,
        "source_tree": "d" * 40,
        "source_dirty": False,
        "grok_donor_image_id": "sha256:" + "b" * 64,
        "grok_donor_binary_sha256": "a" * 64,
        "shadow_runtime_tree_sha256": shadow_tree,
        "shadow_runtime_lock_sha256": hashes["shadow_runtime_lock_sha256"],
        "researcher_image_modules_tree_sha256": modules_tree,
    }
    source_identity_sha256 = module._sha256_bytes(module._canonical_bytes(source_identity))
    labels = {
        "io.xinao.researcher.chain": "dedicated-xinao-science",
        "io.xinao.researcher.generic-worker-route": "forbidden",
        "io.xinao.researcher.grok-donor-image-id": source_identity["grok_donor_image_id"],
        "io.xinao.researcher.grok-donor-binary.sha256": source_identity["grok_donor_binary_sha256"],
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
        "io.xinao.researcher.shadow-runtime.sha256": shadow_tree,
        "io.xinao.researcher.shadow-runtime-lock.sha256": hashes["shadow_runtime_lock_sha256"],
        "io.xinao.researcher.requested-model": "grok-4.5",
        **module._dual_profile_image_labels(researcher_image_modules_tree_sha256=modules_tree),
    }
    manifest: dict[str, object] = {
        "schema_version": module.RELEASE_SCHEMA,
        "release_id": "pending",
        "package_version": "1.3.4",
        "capability_id": "researcher-container",
        "capability_version": "1.2.1",
        "charter_version": "1.2.1",
        "runtime_version": "1.2.1",
        "release_identity_sha256": "pending",
        "source_identity": source_identity,
        "skill_bundle_path": "pending",
        "skill_bundle_manifest_path": "pending",
        "skill_bundle_manifest_sha256": "pending",
        "skill_bundle_tree_sha256": bundle_manifest["tree_sha256"],
        "image_tag_observational": "xinao-researcher:historical",
        "image_id": "sha256:" + "a" * 64,
        "image_entrypoint": ["python", "-I", "/opt/xinao-researcher/entrypoint.py"],
        "image_labels": labels,
        "skill_hashes": hashes,
        "required_bootstrap_protocol": 2,
        "generic_worker_route_allowed": False,
        "state_namespace": "xinao_skill/researcher_container",
        "run_namespace": "xinao_researcher",
    }
    identity = module._sha256_bytes(
        module._canonical_bytes(module._release_identity_payload(manifest))
    )
    release_id = f"researcher-1.2.1-{identity[:16]}"
    release_root = module._state_paths()["release_root"] / release_id
    manifest_path = release_root / "release.json"
    manifest.update(
        {
            "release_id": release_id,
            "release_identity_sha256": identity,
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
    with pytest.raises(module.XinaoError) as failure:
        module._validate_release_manifest(manifest, manifest_path)
    assert failure.value.reason_code == "RELEASE_SCHEMA_INVALID"
    module._validate_sealed_protocol_v2_release(manifest, manifest_path)
    assert module._source_identity_generation(source_identity) == "pre_tool_image"
    assert module._active_release_requires_forward_upgrade(manifest) is True


def test_sealed_id_override_rejected(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    monkeypatch.delenv("XINAO_DUAL_CONTAINER_SYNTHETIC", raising=False)
    monkeypatch.setenv("XINAO_TRANSPORT_IMAGE", "sha256:" + "f" * 64)
    monkeypatch.setenv("XINAO_TOOL_EXECUTOR_IMAGE", manifest["tool_image_id"])

    def fake_image(_docker: str, image: str) -> dict[str, object]:
        return {"Id": image if image.startswith("sha256:") else "sha256:" + "f" * 64}

    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_docker_engine_os", lambda _d: "linux")
    monkeypatch.setattr(module, "_docker_image", fake_image)
    with pytest.raises(module.XinaoError) as failure:
        module._resolve_research_episode_dual_images()
    assert failure.value.reason_code == "DUAL_CONTAINER_TRANSPORT_IMAGE_OVERRIDE_REJECTED"


def test_docker_create_argv_uses_real_cli_entrypoint_shape(specs: Any) -> None:
    tool = specs.tool_executor_container_spec(
        image="sha256:" + "a" * 64,
        name="tool-shape",
        episode_lab_host_path="/host/lab",
        ipc_host_dir="/host/ipc",
    )
    argv = specs.docker_create_argv(tool)
    assert argv[0] == "docker"
    assert argv[1] == "create"
    assert "--entrypoint" in argv
    ep_idx = argv.index("--entrypoint")
    ep = argv[ep_idx + 1]
    # Real Docker CLI does not parse JSON-array --entrypoint.
    assert not ep.lstrip().startswith("["), ep
    assert ep == "python"
    image_idx = argv.index(tool["image"])
    assert image_idx == ep_idx + 2
    cmd_rest = argv[image_idx + 1 :]
    assert cmd_rest[0] == "-I"
    assert "tool_executor.py" in " ".join(cmd_rest)
    process = [ep, *cmd_rest]
    # Split inspect shape (Entrypoint=first, Cmd=rest) is valid, not drift.
    split = _fake_tool_inspect(
        image_id=tool["image"],
        cid="c1",
        lab="/host/lab",
        ipc="/host/ipc",
        entrypoint=[ep],
        cmd=cmd_rest,
    )
    assert specs.validate_tool_container_inspect(split) == []
    assert specs.process_argv_from_inspect(split) == process
    # Full image ENTRYPOINT list with empty Cmd is also valid.
    sealed = _fake_tool_inspect(
        image_id=tool["image"],
        cid="c2",
        lab="/host/lab",
        ipc="/host/ipc",
        entrypoint=process,
        cmd=None,
    )
    assert specs.validate_tool_container_inspect(sealed) == []
    # JSON-text entrypoint (the physical Docker failure mode) is rejected.
    bad = _fake_tool_inspect(
        image_id=tool["image"],
        cid="c3",
        lab="/host/lab",
        ipc="/host/ipc",
        entrypoint=[json.dumps(process)],
        cmd=None,
    )
    live_v = specs.validate_tool_container_inspect(bad)
    assert any("entrypoint_json_text_not_executable" in v for v in live_v)


def _mount_values(argv: list[str]) -> list[str]:
    out: list[str] = []
    for i, token in enumerate(argv):
        if token == "--mount" and i + 1 < len(argv):
            out.append(argv[i + 1])
    return out


def test_bind_mount_cli_value_uses_docker_mount_semantics(specs: Any) -> None:
    """Writable omits mode; readonly uses ``readonly``; bare ``rw`` never emitted."""
    assert (
        specs.bind_mount_cli_value(
            {
                "host": r"D:\XINAO_RESEARCH_RUNTIME\state\lab",
                "container": "/episode-lab",
                "mode": "rw",
            }
        )
        == r"type=bind,src=D:\XINAO_RESEARCH_RUNTIME\state\lab,dst=/episode-lab"
    )
    assert (
        specs.bind_mount_cli_value(
            {
                "host": r"D:\path with spaces\auth.json",
                "container": "/grok-home/auth.json",
                "mode": "ro",
            }
        )
        == r"type=bind,src=D:\path with spaces\auth.json,dst=/grok-home/auth.json,readonly"
    )
    # Default is writable (omit mode).
    assert (
        specs.bind_mount_cli_value({"host": "/h/lab", "container": "/episode-lab"})
        == "type=bind,src=/h/lab,dst=/episode-lab"
    )
    with pytest.raises(ValueError, match="unsupported bind mode"):
        specs.bind_mount_cli_value({"host": "/h", "container": "/c", "mode": "private"})


def test_docker_create_argv_mounts_omit_bare_rw_and_keep_readonly(specs: Any) -> None:
    """Shared create-argv generator must not invent bare ``rw`` for --mount.

    Live failure (Docker 29.x): ``invalid field 'rw' must be a key=value pair``.
    Spec data may still record mode=rw/ro (inspect-style); CLI materializes only.
    """
    win_lab = r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\security\tool_namespace_separation\.probe_work\lab"
    win_ipc = r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\security\tool_namespace_separation\.probe_work\ipc"
    win_auth = r"D:\path with spaces\credentials\auth.json"
    tool = specs.tool_executor_container_spec(
        image="sha256:" + "b" * 64,
        name="tool-mount-shape",
        episode_lab_host_path=win_lab,
        ipc_host_dir=win_ipc,
        sidecar_evidence_host_path=r"D:\XINAO_RESEARCH_RUNTIME\state\sidecar",
    )
    transport = specs.transport_container_spec(
        image="sha256:" + "c" * 64,
        name="transport-mount-shape",
        auth_host_path=win_auth,
        input_host_path=r"D:\input dir",
        output_host_path=r"D:\output dir",
        ipc_host_dir=win_ipc,
        episode_lab_host_path=win_lab,
    )
    tool_argv = specs.docker_create_argv(tool)
    transport_argv = specs.docker_create_argv(transport)
    mounts = _mount_values(tool_argv) + _mount_values(transport_argv)
    assert mounts, "expected bind --mount flags"
    for mount in mounts:
        # Bare volume-mode tokens are invalid for --mount.
        parts = mount.split(",")
        for part in parts:
            assert part not in {"rw", "ro"}, f"bare mode token in mount: {mount}"
            if "=" not in part:
                assert part in {"readonly"}, f"unexpected bare field: {part} in {mount}"
        assert not mount.endswith(",rw"), mount
        assert ",rw," not in mount
        assert mount.startswith("type=bind,src=")
        assert ",dst=" in mount
    # Writable lab/ipc must not carry readonly.
    tool_mounts = _mount_values(tool_argv)
    lab_mount = next(
        m for m in tool_mounts if "dst=/episode-lab" in m or m.endswith("dst=/episode-lab")
    )
    ipc_mount = next(m for m in tool_mounts if "dst=/ipc" in m or m.endswith("dst=/ipc"))
    assert lab_mount == f"type=bind,src={win_lab},dst=/episode-lab"
    assert ipc_mount == f"type=bind,src={win_ipc},dst=/ipc"
    assert "readonly" not in lab_mount
    assert "readonly" not in ipc_mount
    # Transport auth/input stay readonly via mature --mount flag.
    t_mounts = _mount_values(transport_argv)
    auth_mount = next(m for m in t_mounts if "dst=/grok-home/auth.json" in m)
    input_mount = next(m for m in t_mounts if "dst=/input" in m)
    assert auth_mount.endswith(",readonly")
    assert input_mount.endswith(",readonly")
    assert "auth.json" in auth_mount
    # Forbidden surfaces stay out of tool argv.
    joined = " ".join(tool_argv)
    assert "docker.sock" not in joined
    assert "/ledger" not in joined
    assert "/outcomes" not in joined
    assert "auth.json" not in joined
    # Spec still records inspect-style modes for consumers of create-spec JSON.
    assert all(b.get("mode") in {"rw", "ro"} for b in tool["binds"])
    assert any(b.get("mode") == "ro" for b in transport["binds"])
    assert any(b.get("mode") == "rw" for b in transport["binds"])


def test_docker_create_argv_mounts_accepted_by_real_docker_parser(
    specs: Any, tmp_path: Path
) -> None:
    """Optional isolated real-CLI parse: create+rm only; no formal state / receipt."""
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker binary not on PATH")
    try:
        info = subprocess.run(
            ["docker", "info", "--format", "{{.OSType}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"docker info unavailable: {exc}")
    if info.returncode != 0:
        pytest.skip(f"docker info rc={info.returncode}")

    # Prefer a local tag already present; fall back to hello-world only if needed.
    image = "hello-world:latest"
    lab = tmp_path / "lab with spaces"
    ipc = tmp_path / "ipc"
    auth = tmp_path / "auth dir"
    auth.mkdir()
    (auth / "auth.json").write_text("{}", encoding="utf-8")
    lab.mkdir()
    ipc.mkdir()
    # Windows drive-letter paths as probe issuer uses (str(Path)).
    tool = specs.tool_executor_container_spec(
        image=image,
        name=f"xinao-mnt-probe-tool-{uuid.uuid4().hex[:10]}",
        episode_lab_host_path=str(lab),
        ipc_host_dir=str(ipc),
    )
    transport = specs.transport_container_spec(
        image=image,
        name=f"xinao-mnt-probe-tr-{uuid.uuid4().hex[:10]}",
        auth_host_path=str(auth / "auth.json"),
        input_host_path=str(tmp_path / "input"),
        output_host_path=str(tmp_path / "output"),
        ipc_host_dir=str(ipc),
        episode_lab_host_path=str(lab),
    )
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()

    created: list[str] = []
    try:
        for argv in (specs.docker_create_argv(tool), specs.docker_create_argv(transport)):
            # Parser acceptance only: --mount must not fail before image resolve.
            # Drop heavy security opts that are unrelated to mount parsing so a
            # missing image still surfaces as image-not-found rather than mount.
            assert all(
                not (argv[i] == "--mount" and ",rw" in argv[i + 1]) for i in range(len(argv) - 1)
            )
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            stderr = (completed.stderr or "") + (completed.stdout or "")
            # Exact live failure from gen9 probe (Docker 29.x --mount parser).
            assert "invalid field 'rw'" not in stderr, stderr
            assert not ("invalid field" in stderr.lower() and "key=value pair" in stderr.lower()), (
                stderr
            )
            if completed.returncode == 0:
                cid = (completed.stdout or "").strip()
                if cid:
                    created.append(cid)
            else:
                # Image may be absent or platform mismatch; still prove mount parse OK.
                lower = stderr.lower()
                mount_parse_fail = (
                    "invalid field" in lower
                    or "invalid mount" in lower
                    or ("invalid argument" in lower and "--mount" in lower)
                )
                assert not mount_parse_fail, stderr
    finally:
        for cid in created:
            subprocess.run(
                ["docker", "rm", "--force", cid],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )


def test_issuer_fail_closed_without_active_dual_release(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code in {
        "TOOL_NAMESPACE_SEALED_IMAGES_REQUIRED",
        "CURRENT_POINTER_ABSENT",
        "TOOL_NAMESPACE_SYNTHETIC_EVIDENCE_REFUSED",
    }


def test_issuer_refuses_synthetic_and_episode_local(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _state(module, tmp_path, monkeypatch)
    monkeypatch.setenv("XINAO_TOOL_NAMESPACE_SYNTHETIC", "1")
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code == "TOOL_NAMESPACE_SYNTHETIC_EVIDENCE_REFUSED"
    monkeypatch.delenv("XINAO_TOOL_NAMESPACE_SYNTHETIC", raising=False)
    with pytest.raises(module.XinaoError) as failure2:
        module.issue_tool_namespace_separation_receipt(episode_root=tmp_path / "ep")
    assert failure2.value.reason_code == "TOOL_NAMESPACE_EPISODE_LOCAL_ISSUE_FORBIDDEN"


def test_production_issuer_ignores_global_probe_injector(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_TOOL_NAMESPACE_PHYSICAL_PROBE_IMPL must not forge live proof on production path."""
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)

    forged_calls = {"n": 0}

    def forged_probe(**_kwargs: object) -> dict[str, object]:
        forged_calls["n"] += 1
        return {
            "physical_proof": True,
            "synthetic": False,
            "negative_proof_ids": list(module.TOOL_NAMESPACE_RECEIPT_REQUIRED_NEGATIVE_PROOF_IDS),
            "details": {"clean_tool_container_id": "FORGED"},
            "evidence_class": "live_physical_host",
        }

    module._TOOL_NAMESPACE_PHYSICAL_PROBE_IMPL = forged_probe  # type: ignore[attr-defined]
    io_state = _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    issued = module.issue_tool_namespace_separation_receipt()
    assert forged_calls["n"] == 0
    assert issued["status"] == "ISSUED"
    assert io_state["creates"] >= 1
    receipt = json.loads(Path(issued["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["probe_details"]["clean_tool_container_id"] != "FORGED"
    del module._TOOL_NAMESPACE_PHYSICAL_PROBE_IMPL  # type: ignore[attr-defined]


def test_issuer_requires_complete_physical_proofs_fail_closed(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        fail_proof="credential_read_denied",
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code in {
        "TOOL_NAMESPACE_PROBE_AUTH_NOT_DENIED",
        "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN",
        "TOOL_NAMESPACE_PROOF_INCOMPLETE",
    }


def test_issuer_writes_canonical_receipt_via_real_docker_io_mock(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    io_state = _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    issued = module.issue_tool_namespace_separation_receipt()
    assert issued["status"] == "ISSUED"
    assert issued["completion_claim_allowed"] is False
    assert issued["owner_adopted"] is False
    assert issued["science_restored"] is False
    assert issued["parent_complete"] is False
    assert issued["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    assert io_state["creates"] >= 1
    assert io_state["execs"]
    receipt_path = Path(issued["receipt_path"])
    assert receipt_path.is_file()
    assert "tool_namespace_separation" in str(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["issuer"] == "host_security_evidence"
    assert receipt["authority"] is False
    assert receipt["completion_claim_allowed"] is False
    assert receipt["physical_proof"] is True
    assert receipt["release_id"] == manifest["release_id"]
    assert receipt["release_identity_sha256"] == manifest["release_identity_sha256"]
    assert receipt["transport_image_id"] == manifest["image_id"]
    assert receipt["tool_image_id"] == manifest["tool_image_id"]
    assert set(module.TOOL_NAMESPACE_RECEIPT_REQUIRED_NEGATIVE_PROOF_IDS).issubset(
        set(receipt["negative_proof_ids"])
    )
    pointer = json.loads(
        (module._tool_namespace_security_root() / "current.json").read_text(encoding="utf-8")
    )
    assert set(pointer.keys()) == module.TOOL_NAMESPACE_CURRENT_POINTER_KEYS
    assert pointer["receipt_sha256"] == module._sha256(receipt_path)
    # Consumer elevates only via canonical pointer.
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    )


def test_consumer_rejects_off_root_forged_json(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    episode = tmp_path / "episode"
    episode.mkdir()
    forged = tmp_path / "off_root" / "forged.json"
    forged.parent.mkdir()
    forged.write_text(
        json.dumps(
            {
                "schema_version": module.TOOL_NAMESPACE_RECEIPT_SCHEMA,
                "issuer": "host_security_evidence",
                "profile_id": module.GENUINE_SCIENTIST_PROFILE_ID,
                "tool_namespace_isolated": True,
                "auth_reachable_from_model_tools": False,
                "ledger_writable_from_model_tools": False,
                "freeze_writable_from_model_tools": False,
                "outcome_writable_from_model_tools": False,
                "same_container_file_tools_allowed": False,
                "completion_claim_allowed": False,
                "authority": False,
                "physical_proof": True,
                "synthetic": False,
                "evidence_class": "live_physical_host",
                "sealed_at": "2026-07-31T00:00:00Z",
                "negative_proof_ids": list(
                    module.TOOL_NAMESPACE_RECEIPT_REQUIRED_NEGATIVE_PROOF_IDS
                ),
                "release_id": manifest["release_id"],
                "release_identity_sha256": manifest["release_identity_sha256"],
                "transport_image_id": manifest["image_id"],
                "tool_image_id": manifest["tool_image_id"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XINAO_TOOL_NAMESPACE_SEPARATION_RECEIPT", str(forged))
    assert (
        module._research_episode_resolve_profile_status(episode)
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )


def test_consumer_rejects_hash_drift_and_tamper(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    receipt_path, _receipt, pointer_path = _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    )
    # Tamper receipt bytes → hash drift.
    raw = receipt_path.read_text(encoding="utf-8")
    receipt_path.write_text(
        raw.replace("live_physical_host", "live_physical_HOST"), encoding="utf-8"
    )
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )
    # Restore and corrupt pointer hash.
    module._write_json_atomic(
        receipt_path,
        json.loads(raw),
    )
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["receipt_sha256"] = "0" * 64
    module._write_json_atomic(pointer_path, pointer)
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )


def test_consumer_rejects_stale_wrong_release_wrong_image(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)

    def stale(receipt: dict[str, Any]) -> None:
        receipt["sealed_at"] = "2000-01-01T00:00:00Z"

    _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        mutate=stale,
    )
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )

    def wrong_release(receipt: dict[str, Any]) -> None:
        receipt["release_id"] = "researcher-0.0.0-" + "a" * 16
        receipt["release_identity_sha256"] = "b" * 64

    _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        mutate=wrong_release,
    )
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )

    def wrong_image(receipt: dict[str, Any]) -> None:
        receipt["tool_image_id"] = "sha256:" + "c" * 64

    _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        mutate=wrong_image,
    )
    assert (
        module._research_episode_resolve_profile_status(tmp_path / "ep")
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )


def test_consumer_rejects_episode_local_and_env_only_path(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    episode = tmp_path / "episode"
    episode.mkdir()
    local = episode / "local_receipt.json"
    local.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XINAO_TOOL_NAMESPACE_SEPARATION_RECEIPT", str(local))
    assert (
        module._research_episode_resolve_profile_status(episode)
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )
    # Canonical receipt + env must match; env pointing elsewhere rejects.
    receipt_path, _r, _p = _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    monkeypatch.setenv("XINAO_TOOL_NAMESPACE_SEPARATION_RECEIPT", str(local))
    assert (
        module._research_episode_resolve_profile_status(episode)
        == module.RESEARCH_EPISODE_PROFILE_STATUS
    )
    monkeypatch.setenv("XINAO_TOOL_NAMESPACE_SEPARATION_RECEIPT", str(receipt_path))
    assert (
        module._research_episode_resolve_profile_status(episode)
        == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    )


def test_profile_status_consistent_across_identity_start_status_resume(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    episode = tmp_path / "episode_root"
    # Without receipt: all surfaces UNAVAILABLE.
    started = module.research_episode_start(root=episode, question="q1")
    assert started["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS
    assert started["completion_claim_allowed"] is False
    assert started["container_identity"]["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS
    status = module.research_episode_status(root=episode)
    assert status["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS
    resumed = module.research_episode_resume(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    assert resumed["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS
    assert resumed["container_identity"]["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS

    # With canonical receipt: all surfaces TOOL_NAMESPACE_VERIFIED (not AVAILABLE / role fitness).
    _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    status2 = module.research_episode_status(root=episode)
    assert status2["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    assert status2["completion_claim_allowed"] is False
    identity = module._research_episode_container_identity(
        verb="status",
        episode_id=started["episode_id"],
        session_id=started["session_id"],
        generation=2,
        lab_root=episode / "lab",
        root=episode,
    )
    assert identity["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    assert identity["completion_claim_allowed"] is False
    assert identity["owner_adopted"] is False
    assert identity["science_restored"] is False
    assert identity["parent_complete"] is False
    resumed2 = module.research_episode_resume(
        root=episode,
        expected_head_sha256=resumed["head_checkpoint_sha256"],
    )
    assert resumed2["profile_status"] == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    assert (
        resumed2["container_identity"]["profile_status"]
        == module.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED
    )
    assert resumed2["completion_claim_allowed"] is False


def test_issuer_start_failure_is_not_denial_proof(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        fail_start=True,
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN"
    # No receipt may be issued after start failure.
    security_root = module._tool_namespace_security_root()
    assert not (security_root / "current.json").is_file()


def test_issuer_exec_plumbing_failure_is_not_denial_proof(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        fail_exec_plumbing=True,
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code in {
        "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN",
        "TOOL_NAMESPACE_PROBE_AUTH_NOT_DENIED",
        "TOOL_NAMESPACE_PROOF_INCOMPLETE",
    }
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN"
    assert not (module._tool_namespace_security_root() / "current.json").is_file()


def test_issuer_wrong_executable_is_not_denial_proof(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        wrong_executable=True,
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN"
    assert not (module._tool_namespace_security_root() / "current.json").is_file()


def test_issuer_unrelated_nonzero_is_not_denial_proof(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        unrelated_nonzero=True,
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    # Unrelated nonzero under expect_fail is not exit-0 auth success.
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_RUNTIME_UNPROVEN"
    assert not (module._tool_namespace_security_root() / "current.json").is_file()


def test_issuer_true_auth_read_is_not_denied_code(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When tool open() returns 0, reason must remain AUTH_NOT_DENIED (not unproven)."""
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        fail_proof="credential_read_denied",
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_NOT_DENIED"
    assert "runtime auth read succeeded" in str(failure.value.detail)
    assert not (module._tool_namespace_security_root() / "current.json").is_file()


def test_physical_probe_requires_tool_sidecar_and_transport_auth_asymmetry(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, specs: Any
) -> None:
    """Clean tool probe must mount sidecar; transport placeholder auth is readable only there."""
    from tests import test_xinao_skill as skill_tests

    _state(module, tmp_path, monkeypatch)
    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    io_state = _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    probe = module._run_tool_namespace_physical_probes(
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    assert probe["physical_proof"] is True
    assert "credential_read_denied" in probe["negative_proof_ids"]
    methods = probe["details"]["proof_methods"]
    assert methods["credential_read_denied"]
    assert methods["transport_auth_handle_readable"]
    assert probe["details"]["role_boundary"]["tool_auth_mount"] == "forbidden"
    assert probe["details"]["role_boundary"]["auth_bytes_observed"] is False
    # At least one tool create + one transport create.
    assert io_state["creates"] >= 2
    roles = [meta.get("role") for meta in io_state["containers"].values()]
    assert "tool" in roles
    assert "transport" in roles
    # Tool create argv must include sidecar bind; transport must include auth.json RO.
    # Reconstruct from mock container metadata.
    tool_metas = [m for m in io_state["containers"].values() if m.get("role") == "tool"]
    transport_metas = [m for m in io_state["containers"].values() if m.get("role") == "transport"]
    assert tool_metas and tool_metas[0].get("sidecar")
    assert transport_metas and transport_metas[0].get("auth")
    # Spec-level inversion guard: tool must never admit auth bind targets.
    tool_spec = specs.tool_executor_container_spec(
        image=manifest["tool_image_id"],
        name="xinao-ns-tool-inv",
        episode_lab_host_path=str(tmp_path / "lab"),
        ipc_host_dir=str(tmp_path / "ipc"),
        sidecar_evidence_host_path=str(tmp_path / "side"),
    )
    for bind in tool_spec["binds"]:
        dest = str(bind.get("container") or "")
        assert "auth" not in dest
        assert "/grok-home" not in dest
    transport_spec = specs.transport_container_spec(
        image=manifest["image_id"],
        name="xinao-ns-transport-inv",
        auth_host_path=str(tmp_path / "auth.json"),
        input_host_path=str(tmp_path / "in"),
        output_host_path=str(tmp_path / "out"),
        ipc_host_dir=str(tmp_path / "ipc2"),
    )
    (tmp_path / "auth.json").write_bytes(b'{"probe":"placeholder"}\n')
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "ipc2").mkdir()
    dests = {str(b.get("container")) for b in transport_spec["binds"]}
    assert specs.TRANSPORT_AUTH_MOUNT in dests
    assert specs.TOOL_SIDECAR_EVIDENCE_MOUNT not in dests


def test_probe_invocation_roots_unique_and_cleaned_on_success(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two successive successful issues use distinct inv_* roots; each cleans its own."""
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    first = module.issue_tool_namespace_separation_receipt()
    second = module.issue_tool_namespace_separation_receipt()
    assert first["status"] == "ISSUED"
    assert second["status"] == "ISSUED"
    r1 = json.loads(Path(first["receipt_path"]).read_text(encoding="utf-8"))
    r2 = json.loads(Path(second["receipt_path"]).read_text(encoding="utf-8"))
    inv1 = r1["probe_details"]["probe_invocation_id"]
    inv2 = r2["probe_details"]["probe_invocation_id"]
    assert inv1 and inv2
    assert inv1 != inv2
    assert inv1.startswith(module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX)
    assert inv2.startswith(module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX)
    cleanup1 = r1["probe_details"]["probe_cleanup"]
    cleanup2 = r2["probe_details"]["probe_cleanup"]
    assert cleanup1["owned"] is True and cleanup1["cleaned"] is True
    assert cleanup2["owned"] is True and cleanup2["cleaned"] is True
    work = module._tool_namespace_probe_work_parent()
    assert not (work / inv1).exists()
    assert not (work / inv2).exists()
    # Must never bind to the legacy fixed `.probe_work/lab` path.
    for receipt in (r1, r2):
        root = str(receipt["probe_details"]["probe_root"])
        assert (
            f"{module.TOOL_NAMESPACE_PROBE_WORK_DIRNAME}{os.sep}{module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX}"
            in root.replace("/", os.sep)
            or f"/{module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX}" in root.replace("\\", "/")
        )


def test_probe_failure_residue_does_not_block_next_issue(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First mid-run failure retains inv_* evidence; second issue still starts cleanly.

    Also plants legacy fixed-path auth_escape residue (the production pollution mode)
    to prove the new exclusive root is immune.
    """
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
        fail_proof="credential_read_denied",
    )
    with pytest.raises(module.XinaoError) as failure:
        module.issue_tool_namespace_separation_receipt()
    assert failure.value.reason_code == "TOOL_NAMESPACE_PROBE_AUTH_NOT_DENIED"
    work = module._tool_namespace_probe_work_parent()
    retained = sorted(
        p
        for p in work.iterdir()
        if p.is_dir() and p.name.startswith(module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX)
    )
    assert retained, "failed probe must retain its exact inv_* root for evidence"
    # Simulate Windows reparse/symlink residue under the retained lab + legacy fixed path.
    for lab in (retained[0] / "lab", work / "lab"):
        lab.mkdir(parents=True, exist_ok=True)
        escape = lab / ".auth_escape"
        if escape.exists() or escape.is_symlink():
            continue
        try:
            escape.symlink_to(tmp_path / "outside_target", target_is_directory=True)
        except OSError:
            escape.write_text("auth_escape_residue", encoding="utf-8")
    (tmp_path / "outside_target").mkdir(exist_ok=True)
    # Fresh mock for the second successful attempt (same sealed images).
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    issued = module.issue_tool_namespace_separation_receipt()
    assert issued["status"] == "ISSUED"
    receipt = json.loads(Path(issued["receipt_path"]).read_text(encoding="utf-8"))
    second_inv = receipt["probe_details"]["probe_invocation_id"]
    assert second_inv != retained[0].name
    assert receipt["probe_details"]["probe_cleanup"]["cleaned"] is True
    assert not (work / second_inv).exists()
    # Prior failure evidence still present (not swept by success cleanup).
    assert retained[0].is_dir()


def test_probe_roots_concurrent_allocate_isolated(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent allocate calls never share or stomp inv_* roots."""

    _state(module, tmp_path, monkeypatch)
    barrier = threading.Barrier(6)
    results: list[tuple[str, str]] = []
    lock = threading.Lock()
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            barrier.wait(timeout=10)
            inv, root = module._allocate_tool_namespace_probe_root()
            (root / "lab").mkdir()
            (root / "lab" / "marker").write_text(inv, encoding="utf-8")
            with lock:
                results.append((inv, str(root)))
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(results) == 6
    invs = [r[0] for r in results]
    paths = [r[1] for r in results]
    assert len(set(invs)) == 6
    assert len(set(paths)) == 6
    for inv, path_s in results:
        root = Path(path_s)
        assert root.name == inv
        assert (root / "lab" / "marker").read_text(encoding="utf-8") == inv
        assert module._tool_namespace_probe_root_is_owned(root, invocation_id=inv)


def test_probe_cleanup_refuses_foreign_and_does_not_follow_reparse(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Success cleanup deletes only the owned inv_* root; never foreign or reparse targets."""

    _state(module, tmp_path, monkeypatch)
    inv, root = module._allocate_tool_namespace_probe_root()
    lab = root / "lab"
    lab.mkdir()
    outside = tmp_path / "must_survive_outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("do-not-delete", encoding="utf-8")
    escape = lab / ".auth_escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
        reparse_planted = True
    except OSError:
        escape.write_text("reparse_sim", encoding="utf-8")
        reparse_planted = False

    foreign = module._tool_namespace_probe_work_parent() / "foreign_not_inv"
    foreign.mkdir()
    foreign_marker = foreign / "keep.txt"
    foreign_marker.write_text("foreign", encoding="utf-8")

    # Wrong invocation id → refuse.
    refused = module._cleanup_tool_namespace_probe_root(
        root, invocation_id=f"{module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX}notmine", success=True
    )
    assert refused["owned"] is False
    assert root.is_dir()

    # Foreign directory name that is not inv_* → refuse even if under .probe_work.
    foreign_clean = module._cleanup_tool_namespace_probe_root(
        foreign, invocation_id=foreign.name, success=True
    )
    assert foreign_clean["owned"] is False
    assert foreign_marker.is_file()

    # Exact owned success cleanup.
    cleaned = module._cleanup_tool_namespace_probe_root(root, invocation_id=inv, success=True)
    assert cleaned["owned"] is True
    assert cleaned["cleaned"] is True
    assert not root.exists()
    assert secret.is_file(), "cleanup must not follow reparse/symlink into outside target"
    assert foreign_marker.is_file()
    if reparse_planted:
        assert not escape.exists() and not escape.is_symlink()

    # Failure path retains owned root.
    inv2, root2 = module._allocate_tool_namespace_probe_root()
    (root2 / "lab").mkdir()
    retained = module._cleanup_tool_namespace_probe_root(root2, invocation_id=inv2, success=False)
    assert retained["retained"] is True
    assert retained["cleaned"] is False
    assert root2.is_dir()


def test_repeated_physical_probes_isolated_under_docker_io_mock(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct physical probe runs also isolate roots (issuer is not the only caller)."""
    from tests import test_xinao_skill as skill_tests

    _state(module, tmp_path, monkeypatch)
    manifest, path = skill_tests._sealed_release(
        module, tmp_path, monkeypatch, package_version="1.3.6", capability_version="1.2.2"
    )
    skill_tests._terminal_pointer(module, manifest, path)
    _install_docker_io_mock(
        module,
        monkeypatch,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    p1 = module._run_tool_namespace_physical_probes(
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    p2 = module._run_tool_namespace_physical_probes(
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    assert p1["probe_invocation_id"] != p2["probe_invocation_id"]
    assert p1["details"]["probe_cleanup"]["cleaned"] is True
    assert p2["details"]["probe_cleanup"]["cleaned"] is True
    assert p1["details"]["probe_root"] != p2["details"]["probe_root"]
    assert module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX in p1["details"]["probe_root"]
    assert module.TOOL_NAMESPACE_PROBE_INVOCATION_PREFIX in p2["details"]["probe_root"]


def test_tool_executor_build_staging_normalizes_crlf_and_binds_digest(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CRLF source modules must stage as LF bytes matching sealed digests."""

    _state(module, tmp_path, monkeypatch)
    source_root = tmp_path / "src"
    pkg = source_root / "docker" / "xinao-researcher"
    pkg.mkdir(parents=True)
    df_lf = b"FROM python:3.12-slim\nCOPY docker/xinao-researcher/tool_executor.py /x\n"
    (pkg / "Dockerfile.tool-executor").write_bytes(df_lf)
    # CRLF module bodies (Windows worktree shape).
    (pkg / "ipc_contract.py").write_bytes(b"CONTRACT = 1\r\n")
    (pkg / "tool_executor.py").write_bytes(b"def main():\r\n    return 0\r\n")
    rows = module._collect_tool_executor_module_rows(source_root)
    for _rel, _path, payload in rows:
        assert b"\r" not in payload
    tree = module._tool_executor_modules_tree_sha256(rows)
    df_sha = module._sha256_bytes(module._lf_materialize_bytes(df_lf))
    staging = module._prepare_tool_executor_build_staging(
        tool_dockerfile_bytes=df_lf,
        tool_module_rows=rows,
    )
    try:
        module._verify_staged_tool_executor_build(
            staging,
            expected_dockerfile_sha256=df_sha,
            expected_modules_tree_sha256=tree,
            tool_module_rows=rows,
        )
        staged_mod = (
            staging / module.RESEARCHER_IMAGE_CONTEXT_RELATIVE / "tool_executor.py"
        ).read_bytes()
        assert staged_mod == b"def main():\n    return 0\n"
        assert b"\r" not in staged_mod
        # Tamper staged bytes → fail closed.
        tamper = staging / module.RESEARCHER_IMAGE_CONTEXT_RELATIVE / "ipc_contract.py"
        tamper.write_bytes(b"CONTRACT = 2\n")
        with pytest.raises(module.XinaoError) as failure:
            module._verify_staged_tool_executor_build(
                staging,
                expected_dockerfile_sha256=df_sha,
                expected_modules_tree_sha256=tree,
                tool_module_rows=rows,
            )
        assert failure.value.reason_code in {
            "TOOL_BUILD_STAGING_MODULE_DRIFT",
            "TOOL_BUILD_STAGING_MODULES_HASH_MISMATCH",
        }
    finally:
        module._remove_tool_build_staging_root(staging)
    assert not staging.exists()


def test_companion_runtime_hash_matches_bytes() -> None:
    bootstrap = _load("xinao_bootstrap_dual_ns", BOOTSTRAP_PATH)
    observed = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()
    assert bootstrap.EXPECTED_COMPANION_RUNTIME_SHA256 == observed


def test_require_live_research_still_fail_closed(tmp_path: Path) -> None:
    # Keep role-fitness require_live_research fail-closed when discovery deps exist.
    try:
        from tests import test_owner_live_commissioning as live
    except ModuleNotFoundError as exc:
        pytest.skip(f"owner live commissioning deps unavailable: {exc}")
    live.test_require_live_research_pre_outcome_fails_without_evidence(tmp_path)


def test_transport_spec_injects_proxy_env_on_egress_network_only(
    specs: Any, tmp_path: Path
) -> None:
    """Live internal-net transport must carry sealed HTTP(S)_PROXY; offline none must not.

    Negative: stripping proxy env on egress network fails transport invariants
    (real failure mode: reqwest cannot resolve/CONNECT cli-chat-proxy.grok.com).
    """
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    common = dict(
        image="sha256:" + "a" * 64,
        name="xinao-transport-proxy-probe",
        auth_host_path=str(auth),
        input_host_path=str(tmp_path / "in"),
        output_host_path=str(tmp_path / "out"),
        ipc_host_dir=str(tmp_path / "ipc"),
    )
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "ipc").mkdir()

    offline = specs.transport_container_spec(**common, network="none")
    assert offline["network"] == "none"
    for key in specs.PROVIDER_EGRESS_CONTROLLED_ENV_KEYS:
        assert key not in offline["env"]
    assert specs.validate_transport_spec_invariants(offline) == []

    live = specs.transport_container_spec(
        **common, network=specs.DEFAULT_PROVIDER_EGRESS_NETWORK
    )
    assert live["network"] == specs.DEFAULT_PROVIDER_EGRESS_NETWORK
    for key in specs.PROVIDER_EGRESS_PROXY_URL_ENV_KEYS:
        assert live["env"][key] == specs.DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT
    for key in specs.PROVIDER_EGRESS_CLEAR_ENV_KEYS:
        assert live["env"][key] == ""
    assert specs.validate_transport_spec_invariants(live) == []

    # Create argv must materialize proxy env for docker create.
    argv = specs.docker_create_argv(live)
    joined = " ".join(argv)
    assert f"HTTP_PROXY={specs.DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT}" in joined
    assert f"HTTPS_PROXY={specs.DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT}" in joined

    stripped = dict(live)
    stripped_env = dict(live["env"])
    for key in specs.PROVIDER_EGRESS_CONTROLLED_ENV_KEYS:
        stripped_env.pop(key, None)
    stripped["env"] = stripped_env
    violations = specs.validate_transport_spec_invariants(stripped)
    assert any(v.startswith("proxy_env_missing_or_wrong:") for v in violations), violations

    wrong = dict(live)
    wrong_env = dict(live["env"])
    wrong_env["HTTPS_PROXY"] = "http://evil-proxy.example:9999"
    wrong["env"] = wrong_env
    bad = specs.validate_transport_spec_invariants(wrong)
    assert "proxy_env_missing_or_wrong:HTTPS_PROXY" in bad

    # Offline must not silently carry proxy (escape/confusion).
    poisoned = dict(offline)
    poisoned_env = dict(offline["env"])
    poisoned_env["HTTP_PROXY"] = specs.DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT
    poisoned["env"] = poisoned_env
    offline_bad = specs.validate_transport_spec_invariants(poisoned)
    assert any(v.startswith("proxy_env_unexpected_on_offline_network:") for v in offline_bad)


def test_dual_bundle_live_network_propagates_proxy_env(specs: Any, tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    (tmp_path / "lab").mkdir()
    (tmp_path / "ipc").mkdir()
    (tmp_path / "in").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "side").mkdir()
    bundle = specs.dual_container_bundle(
        transport_image="sha256:" + "b" * 64,
        tool_image="sha256:" + "c" * 64,
        auth_host_path=str(auth),
        input_host_path=str(tmp_path / "in"),
        output_host_path=str(tmp_path / "out"),
        episode_lab_host_path=str(tmp_path / "lab"),
        ipc_host_dir=str(tmp_path / "ipc"),
        sidecar_evidence_host_path=str(tmp_path / "side"),
        network=specs.DEFAULT_PROVIDER_EGRESS_NETWORK,
        use_episode_entrypoint=True,
        episode_id="xre_proxy_env_probe",
    )
    assert bundle["transport_spec_violations"] == []
    transport = bundle["transport"]
    for key in specs.PROVIDER_EGRESS_PROXY_URL_ENV_KEYS:
        assert transport["env"][key] == specs.DEFAULT_PROVIDER_EGRESS_PROXY_ENDPOINT
    for key in specs.PROVIDER_EGRESS_CLEAR_ENV_KEYS:
        assert transport["env"][key] == ""
    # Tool remains network=none and must never receive proxy routing env.
    tool_env = bundle["tool_executor"]["env"]
    for key in specs.PROVIDER_EGRESS_CONTROLLED_ENV_KEYS:
        assert key not in tool_env


def test_transport_spec_rejects_noncanonical_live_network(specs: Any, tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    for name in ("in", "out", "ipc"):
        (tmp_path / name).mkdir()
    spec = specs.transport_container_spec(
        image="sha256:" + "d" * 64,
        name="xinao-transport-network-probe",
        auth_host_path=str(auth),
        input_host_path=str(tmp_path / "in"),
        output_host_path=str(tmp_path / "out"),
        ipc_host_dir=str(tmp_path / "ipc"),
        network="caller-controlled-network",
    )
    violations = specs.validate_transport_spec_invariants(spec)
    assert "provider_egress_network_unsupported:caller-controlled-network" in violations
    assert not any(key in spec["env"] for key in specs.PROVIDER_EGRESS_CONTROLLED_ENV_KEYS)
