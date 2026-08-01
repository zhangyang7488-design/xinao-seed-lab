"""Focused regressions for live ResearchEpisode material binding.

These tests exercise candidate code only.  They do not invoke a provider,
install a release, switch current, freeze a decision, or settle an account.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "xinao" / "scripts"
RUNTIME_PATH = SCRIPTS / "xinao_runtime.py"
HOST_PATH = SCRIPTS / "dual_container_host.py"
SPECS_PATH = ROOT / "docker" / "xinao-researcher" / "docker_create_specs.py"


def _load(name: str, path: Path) -> Any:
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime() -> Any:
    return _load("xinao_runtime_material_binding", RUNTIME_PATH)


@pytest.fixture
def host_mod() -> Any:
    return _load("xinao_dual_host_material_binding", HOST_PATH)


@pytest.fixture
def specs() -> Any:
    return _load("xinao_specs_material_binding", SPECS_PATH)


def _auth(tmp_path: Path) -> Path:
    path = tmp_path / "provider_handle.json"
    path.write_text('{"handle":"test-only"}\n', encoding="utf-8")
    return path


def _materials(tmp_path: Path) -> tuple[Path, Path]:
    account = tmp_path / "account_snapshot.v1.json"
    target = tmp_path / "prospective_target_packet.v1.txt"
    account.write_text(
        '{"available_balance":"19.25","open_commitments":[]}\n',
        encoding="utf-8",
    )
    target.write_text(
        "prospective event: participant A versus participant B\n",
        encoding="utf-8",
    )
    return account, target


def _binding(
    runtime: Any, tmp_path: Path, *, prompt: str = "Investigate the live object."
) -> tuple[dict[str, Any], dict[str, Any], Path, Path, Path]:
    episode = tmp_path / "episode"
    account, target = _materials(tmp_path)
    binding, witness = runtime._materialize_research_episode_active_binding(
        episode_root=episode,
        base_prompt=prompt,
        material_paths=[account, target],
        auth_path=_auth(tmp_path),
    )
    return binding, witness, episode, account, target


def test_active_binding_reuses_content_identity_and_preserves_source_identity(
    runtime: Any, tmp_path: Path
) -> None:
    prompt = "Investigate the live object without a prescribed method."
    binding, witness, episode, account, target = _binding(
        runtime, tmp_path, prompt=prompt
    )
    assert binding["schema_version"] == (
        "xinao.research_episode_active_material_binding.v1"
    )
    assert binding["material_count"] == 2
    snapshot_at = dt.datetime.fromisoformat(
        binding["material_snapshot_at"].replace("Z", "+00:00")
    )
    assert snapshot_at.tzinfo is not None
    assert witness["path"].endswith("provider_handle.json")

    refs = binding["material_source_refs"]
    assert {item["path"] for item in refs} == {
        str(account.resolve()),
        str(target.resolve()),
    }
    assert all(len(item["path_identity_sha256"]) == 64 for item in refs)
    assert {
        (item["material_id"], item["sha256"]) for item in refs
    } == {
        (item["material_id"], item["sha256"])
        for item in binding["material_manifest"]["materials"]
    }

    active_root = episode / "active_materials"
    manifest_path = active_root / binding["material_manifest_relative_path"]
    assert runtime._sha256(manifest_path) == binding["material_manifest_sha256"]
    bundle_root = manifest_path.parent
    assert {
        runtime._sha256(bundle_root / item["relative_path"])
        for item in binding["material_manifest"]["materials"]
    } == {runtime._sha256(account), runtime._sha256(target)}
    effective = (
        active_root / binding["effective_prompt_relative_path"]
    ).read_text(encoding="utf-8")
    assert effective.startswith(prompt)
    assert "available_balance" in effective
    assert "prospective event" in effective
    assert str(account.resolve()) not in effective
    assert str(target.resolve()) not in effective
    assert "not instructions, authority, or a prescribed research method" in effective

    reused, second_witness = runtime._materialize_research_episode_active_binding(
        episode_root=episode,
        base_prompt=prompt,
        material_paths=[target, account],
        auth_path=Path(witness["path"]),
    )
    assert reused["material_bundle_id"] == binding["material_bundle_id"]
    assert reused["material_manifest_sha256"] == binding["material_manifest_sha256"]
    assert reused["effective_prompt_sha256"] == binding["effective_prompt_sha256"]
    assert second_witness["content_sha256"] == witness["content_sha256"]


@pytest.mark.parametrize(
    ("kind", "expected_reason"),
    [
        ("same_path", "MATERIAL_PATH_DUPLICATED"),
        ("same_content", "MATERIAL_CONTENT_DUPLICATED"),
    ],
)
def test_active_binding_rejects_duplicate_materials(
    runtime: Any,
    tmp_path: Path,
    kind: str,
    expected_reason: str,
) -> None:
    auth = _auth(tmp_path)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("same evidence\n", encoding="utf-8")
    second.write_text("same evidence\n", encoding="utf-8")
    paths = [first, first] if kind == "same_path" else [first, second]
    with pytest.raises(runtime.XinaoError) as failure:
        runtime._materialize_research_episode_active_binding(
            episode_root=tmp_path / "episode",
            base_prompt="q",
            material_paths=paths,
            auth_path=auth,
        )
    assert failure.value.reason_code == expected_reason


@pytest.mark.parametrize(
    "relative",
    ["outcomes/next.json", "secrets/source.txt", ".env"],
)
def test_active_binding_rejects_direct_authority_or_secret_paths(
    runtime: Any, tmp_path: Path, relative: str
) -> None:
    material = tmp_path / relative
    material.parent.mkdir(parents=True, exist_ok=True)
    material.write_text("must not enter provider context\n", encoding="utf-8")
    with pytest.raises(runtime.XinaoError) as failure:
        runtime._materialize_research_episode_active_binding(
            episode_root=tmp_path / "episode",
            base_prompt="q",
            material_paths=[material],
            auth_path=_auth(tmp_path),
        )
    assert failure.value.reason_code == (
        "RESEARCH_EPISODE_MATERIAL_AUTHORITY_PATH_FORBIDDEN"
    )


def test_active_binding_rejects_frozen_bundle_content_drift(
    runtime: Any, tmp_path: Path
) -> None:
    binding, _witness, episode, account, target = _binding(runtime, tmp_path)
    bundle_digest = binding["material_bundle_id"].split(":", 1)[1]
    entry = binding["material_manifest"]["materials"][0]
    frozen_file = (
        episode
        / "active_materials"
        / "bundles"
        / bundle_digest
        / entry["relative_path"]
    )
    frozen_file.write_text("tampered after snapshot\n", encoding="utf-8")
    with pytest.raises(runtime.XinaoError) as export_failure:
        runtime._validate_research_episode_active_binding_files(episode, binding)
    assert export_failure.value.reason_code in {
        "RESEARCH_EPISODE_MATERIAL_BINDING_DRIFT",
        "RESEARCH_EPISODE_MATERIAL_BUNDLE_DRIFT",
    }
    with pytest.raises(runtime.XinaoError) as failure:
        runtime._materialize_research_episode_active_binding(
            episode_root=episode,
            base_prompt="Investigate the live object.",
            material_paths=[account, target],
            auth_path=Path(tmp_path / "provider_handle.json"),
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_MATERIAL_BUNDLE_DRIFT"


def test_writable_lab_copy_cannot_impersonate_active_material(
    runtime: Any, tmp_path: Path
) -> None:
    binding, _witness, episode, _account, _target = _binding(runtime, tmp_path)
    lab_copy = episode / "lab" / "materials" / "manifest.json"
    lab_copy.parent.mkdir(parents=True, exist_ok=True)
    lab_copy.write_text(
        json.dumps(binding["material_manifest"], sort_keys=True) + "\n",
        encoding="utf-8",
    )
    forged = copy.deepcopy(binding)
    forged["material_manifest_relative_path"] = "../lab/materials/manifest.json"
    with pytest.raises(runtime.XinaoError) as failure:
        runtime._validate_research_episode_active_binding_files(episode, forged)
    assert failure.value.reason_code == "RESEARCH_EPISODE_MATERIAL_BINDING_INVALID"


def test_host_rejects_active_bundle_drift_before_provider_use(
    runtime: Any, host_mod: Any, tmp_path: Path
) -> None:
    binding, _witness, episode, _account, _target = _binding(runtime, tmp_path)
    host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:candidate",
            tool_image="tool:candidate",
            auth_host_path=tmp_path / "provider_handle.json",
            episode_root=episode,
            synthetic=True,
        )
    )
    assert host._validate_active_material_binding(binding) == binding
    bundle_digest = binding["material_bundle_id"].split(":", 1)[1]
    entry = binding["material_manifest"]["materials"][0]
    source = (
        episode
        / "active_materials"
        / "bundles"
        / bundle_digest
        / entry["relative_path"]
    )
    source.write_text("host-visible drift\n", encoding="utf-8")
    with pytest.raises(host_mod.DualHostError) as failure:
        host._validate_active_material_binding(binding)
    assert failure.value.reason_code == "DUAL_HOST_ACTIVE_MATERIAL_DRIFT"


def test_active_material_mount_is_transport_only_and_readonly(
    specs: Any, host_mod: Any, tmp_path: Path
) -> None:
    active = tmp_path / "episode" / "active_materials"
    active.mkdir(parents=True)
    legacy = tmp_path / "legacy-material"
    bundle = specs.dual_container_bundle(
        transport_image="transport:candidate",
        tool_image="tool:candidate",
        auth_host_path=str(tmp_path / "auth.json"),
        input_host_path=str(tmp_path / "input"),
        output_host_path=str(tmp_path / "output"),
        episode_lab_host_path=str(tmp_path / "lab"),
        ipc_host_dir=str(tmp_path / "ipc"),
        material_host_path=str(legacy),
        active_material_host_path=str(active),
    )
    transport_binds = bundle["transport"]["binds"]
    active_bind = next(
        item for item in transport_binds if item["container"] == "/active-materials"
    )
    assert active_bind == {
        "host": str(active),
        "container": "/active-materials",
        "mode": "ro",
    }
    assert any(
        item["container"] == "/material" and item["mode"] == "ro"
        for item in transport_binds
    )
    assert all(
        item["container"] not in {"/active-materials", "/material"}
        for item in bundle["tool_executor"]["binds"]
    )
    assert bundle["transport_spec_violations"] == []

    writable = copy.deepcopy(bundle["transport"])
    next(
        item for item in writable["binds"] if item["container"] == "/active-materials"
    )["mode"] = "rw"
    assert "active_material_mount_must_be_readonly" in (
        specs.validate_transport_spec_invariants(writable)
    )

    inspect_doc = {
        "Config": {"User": "0:0", "Env": []},
        "HostConfig": {
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
        },
        "Mounts": [
            {"Destination": "/grok-home/auth.json", "Source": str(tmp_path / "auth.json")},
            {"Destination": "/ipc", "Source": str(tmp_path / "ipc"), "RW": True},
            {
                "Destination": "/active-materials",
                "Source": str(active),
                "Type": "bind",
                "RW": False,
            },
        ],
    }
    assert not any(
        value.startswith("active_material_mount")
        for value in specs.validate_transport_container_inspect(
            inspect_doc, expected_active_materials=str(active)
        )
    )
    desktop_projection = (
        "/run/desktop/mnt/host/"
        + active.drive.rstrip(":").lower()
        + active.as_posix()[2:]
        if active.drive
        else str(active)
    )
    assert specs.host_bind_sources_equal(str(active), desktop_projection)
    host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:candidate",
            tool_image="tool:candidate",
            auth_host_path=tmp_path / "auth.json",
            episode_root=tmp_path / "episode",
            synthetic=True,
        )
    )
    mount_readback = host._require_active_material_mount(
        inspect_doc, expected_source=str(active)
    )
    assert mount_readback == {
        "container_path": "/active-materials",
        "host_path": str(active),
        "mount_type": "bind",
        "readonly": True,
        "rw": False,
    }
    foreign = tmp_path / "foreign-active-materials"
    foreign.mkdir()
    foreign_inspect = copy.deepcopy(inspect_doc)
    foreign_inspect["Mounts"][-1]["Source"] = str(foreign)
    with pytest.raises(host_mod.DualHostError) as foreign_failure:
        host._require_active_material_mount(
            foreign_inspect, expected_source=str(foreign)
        )
    assert foreign_failure.value.reason_code == (
        "DUAL_HOST_ACTIVE_MATERIAL_MOUNT_SOURCE_DRIFT"
    )
    inspect_doc["Mounts"][-1]["RW"] = True
    assert "active_material_mount_not_readonly" in (
        specs.validate_transport_container_inspect(
            inspect_doc, expected_active_materials=str(active)
        )
    )


def test_attach_and_resume_use_exact_prompt_file_while_no_material_keeps_p(
    runtime: Any,
    host_mod: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_prompt = "Explore the target."
    binding, _witness, episode, _account, _target = _binding(
        runtime, tmp_path, prompt=base_prompt
    )
    assert host_mod.ACTIVE_MATERIAL_PACKET_NOTICE == (
        runtime.RESEARCH_EPISODE_MATERIAL_PACKET_NOTICE
    )
    provider_session = str(uuid.uuid4())
    host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:candidate",
            tool_image="tool:candidate",
            auth_host_path=tmp_path / "provider_handle.json",
            episode_root=episode,
            synthetic=True,
        )
    )
    ready = {
        "lease": {"episode_id": "ep", "session_id": "host-session"},
        "session_inventory": {"grok_session_id": provider_session},
        "pair_receipt_sha256": "a" * 64,
        "active_material_mount": {
            "container_path": "/active-materials",
            "host_path": str(episode / "active_materials"),
            "mount_type": "bind",
            "readonly": True,
            "rw": False,
        },
    }
    monkeypatch.setattr(host, "require_live_pair_ready", lambda **_kwargs: ready)
    monkeypatch.setattr(host, "sealed_research_profile", lambda: "OPEN_RESEARCH")
    monkeypatch.setattr(
        host, "resume_pair", lambda **_kwargs: {"status": "PAIR_RESUMED"}
    )

    attached = host.attach_run_live(
        prompt=base_prompt,
        active_material_binding=binding,
        plan_only=True,
    )
    attach_argv = attached["planned_grok_argv"]
    assert "--prompt-file" in attach_argv
    assert attach_argv[attach_argv.index("--prompt-file") + 1] == (
        binding["container_effective_prompt_path"]
    )
    assert "-p" not in attach_argv
    assert base_prompt not in attach_argv
    assert attached["material_packet_sha256"] == binding["material_packet_sha256"]
    assert attached["effective_prompt_sha256"] == binding["effective_prompt_sha256"]
    assert attached["material_snapshot_at"] == binding["material_snapshot_at"]
    assert attached["active_material_mount"]["readonly"] is True

    resumed = host.resume_live(
        expected_provider_session_uuid=provider_session,
        expected_host_session_id="host-session",
        prompt="continue",
        active_material_binding=binding,
        plan_only=True,
    )
    resume_argv = resumed["planned_grok_argv"]
    assert resume_argv[resume_argv.index("--resume") + 1] == provider_session
    assert resume_argv[resume_argv.index("--prompt-file") + 1] == (
        binding["container_effective_prompt_path"]
    )
    assert resumed["active_material_binding"]["material_bundle_id"] == (
        binding["material_bundle_id"]
    )

    old_shape = host.attach_run_live(prompt=base_prompt, plan_only=True)
    old_argv = old_shape["planned_grok_argv"]
    assert old_argv[old_argv.index("-p") + 1] == base_prompt
    assert "--prompt-file" not in old_argv
    assert old_shape["active_material_binding"] is None


def test_cli_accepts_generic_or_actor_material_mode_for_attach_and_resume(
    runtime: Any, tmp_path: Path
) -> None:
    first, second = _materials(tmp_path)
    attach = runtime._parser().parse_args(
        [
            "research-episode",
            "attach-run",
            "--root",
            str(tmp_path / "episode"),
            "--prompt",
            "q",
            "--material",
            str(first),
            "--material",
            str(second),
            "--plan-only",
        ]
    )
    assert attach.material == [first, second]
    assert attach.actor_material_root is None
    resume = runtime._parser().parse_args(
        [
            "research-episode",
            "resume-live",
            "--root",
            str(tmp_path / "episode"),
            "--expected-provider-session",
            str(uuid.uuid4()),
            "--expected-head",
            "a" * 64,
            "--material",
            str(first),
        ]
    )
    assert resume.material == [first]
    assert resume.actor_material_root is None

    prepared = tmp_path / "prepared-actor-materials"
    actor_attach = runtime._parser().parse_args(
        [
            "research-episode",
            "attach-run",
            "--root",
            str(tmp_path / "episode"),
            "--prompt",
            "q",
            "--actor-material-root",
            str(prepared),
        ]
    )
    assert actor_attach.material == []
    assert actor_attach.actor_material_root == prepared
    actor_resume = runtime._parser().parse_args(
        [
            "research-episode",
            "resume-live",
            "--root",
            str(tmp_path / "episode"),
            "--expected-provider-session",
            str(uuid.uuid4()),
            "--expected-head",
            "a" * 64,
            "--actor-material-root",
            str(prepared),
        ]
    )
    assert actor_resume.material == []
    assert actor_resume.actor_material_root == prepared


def test_export_seals_active_binding_into_prompt_material_cutoff(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, _witness, episode, _account, _target = _binding(runtime, tmp_path)
    output = episode / "output"
    output.mkdir(parents=True, exist_ok=True)
    attempt_binding = {
        "active_material_binding": binding,
        "material_bundle_id": binding["material_bundle_id"],
        "material_manifest_sha256": binding["material_manifest_sha256"],
        "material_packet_sha256": binding["material_packet_sha256"],
        "material_snapshot_at": binding["material_snapshot_at"],
        "effective_prompt_sha256": binding["effective_prompt_sha256"],
    }
    (output / "fake_attempt.json").write_text(
        json.dumps(attempt_binding, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fake_modules = tmp_path / "fake-host-modules"
    fake_modules.mkdir()
    (fake_modules / "native_grok_session.py").write_text(
        """from __future__ import annotations
import json

def load_attempt_cas(output_root, attempt_cas_digest):
    del attempt_cas_digest
    return json.loads((output_root / 'fake_attempt.json').read_text(encoding='utf-8'))

def export_candidate_evidence_bundle(**kwargs):
    output_root = kwargs['episode_output_root']
    cutoff = kwargs['prompt_material_cutoff']
    (output_root / 'captured_cutoff.json').write_text(
        json.dumps(cutoff, sort_keys=True) + '\\n', encoding='utf-8'
    )
    return {'status': 'EXPORTED', 'bundle_sha256': 'b' * 64}
""",
        encoding="utf-8",
    )
    head_sha = "a" * 64
    monkeypatch.setattr(runtime, "_research_episode_assert_root_allowed", lambda _root: None)
    monkeypatch.setattr(
        runtime, "_research_episode_lock", lambda _root: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_load_head",
        lambda _root: {"head_checkpoint_sha256": head_sha},
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_read_meta",
        lambda _root: {
            "episode_id": "ep_material",
            "session_id": "host_material",
            "question": "live question",
        },
    )
    monkeypatch.setattr(runtime, "_research_episode_namespace_and_release_facts", dict)
    monkeypatch.setattr(runtime, "_research_episode_append_journal", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime, "resolve_packaged_host_modules_dir", lambda: fake_modules
    )

    exported = runtime.research_episode_export_candidate_evidence(
        root=episode,
        attempt_cas_digest="fake-cas",
        expected_head_sha256=head_sha,
    )
    assert exported["status"] == "EXPORTED"
    captured = json.loads((output / "captured_cutoff.json").read_text(encoding="utf-8"))
    assert captured["question"] == "live question"
    sealed = captured["active_material_binding"]
    assert sealed["material_bundle_id"] == binding["material_bundle_id"]
    assert sealed["material_source_refs"] == binding["material_source_refs"]
    assert sealed["effective_prompt_sha256"] == binding["effective_prompt_sha256"]

    attempt_binding["material_bundle_id"] = "xinao-material-bundle-sha256:" + "0" * 64
    (output / "fake_attempt.json").write_text(
        json.dumps(attempt_binding, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(runtime.XinaoError) as mismatch:
        runtime.research_episode_export_candidate_evidence(
            root=episode,
            attempt_cas_digest="fake-cas",
            expected_head_sha256=head_sha,
        )
    assert mismatch.value.reason_code == "RESEARCH_EPISODE_MATERIAL_BINDING_INVALID"


def test_verified_material_reality_comes_only_from_current_attempt_cas(
    runtime: Any,
    specs: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = tmp_path / "episode"
    prospective = tmp_path / "prospective.json"
    prospective.write_text(
        json.dumps(
            {
                "schema_version": "xinao.prospective_target_authority_packet.v1",
                "packet_marker": "XINAO_PROSPECTIVE_TARGET_AUTHORITY_V1",
                "content_hash": "1" * 64,
                "target_expect": "2026214",
                "target_ref": "macaujc2/expect/2026214",
                "contract": {"contract_sha256": "a" * 64},
                "capture_sha256": "b" * 64,
                "latest_completed_expect": "2026213",
                "target_guard_open_time": "2026-08-02T01:00:00Z",
                "freeze_deadline": "2026-08-02T00:59:00Z",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    objective = tmp_path / "objective.json"
    objective.write_text(
        json.dumps(
            {
                "schema_version": "xinao.actor_objective_terms.v1",
                "source_kind": "PINNED_SETTLEMENT_RULE_SNAPSHOT",
                "source_ref": (
                    "xinao.settlement.special_number.SPECIAL_NUMBER_FUNCTION"
                ),
                "content_hash": "2" * 64,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_text(
        json.dumps(
            {
                "schema_version": "xinao.actor_portfolio_reality.v1",
                "packet_marker": "XINAO_ACTOR_PORTFOLIO_REALITY_V1",
                "content_hash": "a" * 64,
                "period_index": 1,
                "current_balance": "19.2500",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    binding, _witness = runtime._materialize_research_episode_active_binding(
        episode_root=episode,
        base_prompt="Investigate this exact prospective target.",
        material_paths=[prospective, objective, portfolio],
        auth_path=_auth(tmp_path),
    )
    episode_id = "ep_verified_material"
    host_session = "host_verified_material"
    provider_session = str(uuid.uuid4())
    head_sha = "3" * 64
    mount = {
        "container_path": "/active-materials",
        "host_path": str(episode / "active_materials"),
        "mount_type": "bind",
        "readonly": True,
        "rw": False,
    }
    stdout = json.dumps(
        {"session_id": provider_session, "stop_reason": "done"}, sort_keys=True
    ).encode("utf-8")
    stderr = b""
    attempt: dict[str, Any] = {
        "schema_version": "xinao.grok_live_attempt_evidence.v1",
        "attempt_id": "att_verified_material",
        "episode_id": episode_id,
        "host_session_id": host_session,
        "provider_session_uuid": provider_session,
        "status": "LIVE_ATTEMPT_RECORDED",
        "cas_head_sha256": head_sha,
        "finished_at": "2026-08-01T01:02:03Z",
        "prior_attempt_hash": None,
        "raw_stdout_cas": runtime._sha256_bytes(stdout),
        "raw_stderr_cas": runtime._sha256_bytes(stderr),
        "raw_stdout_sha256": runtime._sha256_bytes(stdout),
        "raw_stderr_sha256": runtime._sha256_bytes(stderr),
        "argv_redacted": [
            "grok",
            "--prompt-file",
            binding["container_effective_prompt_path"],
        ],
        "active_material_binding": binding,
        "active_material_mount": mount,
        "material_bundle_id": binding["material_bundle_id"],
        "material_manifest_sha256": binding["material_manifest_sha256"],
        "material_packet_sha256": binding["material_packet_sha256"],
        "material_snapshot_at": binding["material_snapshot_at"],
        "effective_prompt_sha256": binding["effective_prompt_sha256"],
        "pair_receipt_sha256": "4" * 64,
        "transport_container_id": "5" * 64,
        "tool_container_id": "6" * 64,
        "transport_image_id": "sha256:" + "7" * 64,
        "tool_image_id": "sha256:" + "8" * 64,
    }
    attempt["attempt_hash"] = runtime._sha256_bytes(runtime._canonical_bytes(attempt))
    pre_final = runtime._canonical_bytes(attempt)
    internal_cas = runtime._sha256_bytes(pre_final)
    attempt["attempt_cas_digest"] = internal_cas
    final_cas = runtime._sha256_bytes(runtime._canonical_bytes(attempt))

    output = episode / "output"
    (output / "attempts").mkdir(parents=True, exist_ok=True)
    pointer = {
        "attempt_cas_digest": final_cas,
        "attempt_hash": attempt["attempt_hash"],
        "status": attempt["status"],
        "episode_id": episode_id,
        "provider_session_uuid": provider_session,
    }
    (output / "attempts" / "last_successful.json").write_text(
        json.dumps(pointer, sort_keys=True) + "\n", encoding="utf-8"
    )
    index_row = {
        "attempt_id": attempt["attempt_id"],
        "attempt_cas_digest": final_cas,
        "attempt_hash": attempt["attempt_hash"],
        "status": attempt["status"],
        "episode_id": episode_id,
        "provider_session_uuid": provider_session,
        "recorded_at": attempt["finished_at"],
        "prior_attempt_hash": None,
    }
    (output / "attempts" / "index.jsonl").write_text(
        json.dumps(index_row, sort_keys=True) + "\n", encoding="utf-8"
    )

    class FakeNative:
        STATUS_LIVE_ATTEMPT_RECORDED = "LIVE_ATTEMPT_RECORDED"

        @staticmethod
        def load_attempt_cas(_root: Path, digest: str) -> dict[str, Any]:
            assert digest == final_cas
            return copy.deepcopy(attempt)

        @staticmethod
        def validate_attempt_exportable(value: dict[str, Any]) -> None:
            assert value["status"] == "LIVE_ATTEMPT_RECORDED"

        @staticmethod
        def load_cas_blob(_root: Path, kind: str, digest: str) -> bytes:
            blobs = {
                ("attempts", internal_cas): pre_final,
                ("raw", runtime._sha256_bytes(stdout)): stdout,
                ("raw", runtime._sha256_bytes(stderr)): stderr,
            }
            return blobs[(kind, digest)]

        @staticmethod
        def parse_provider_machine_output(_stdout: bytes, _stderr: bytes) -> dict[str, str]:
            return {"session_uuid": provider_session}

        @staticmethod
        def is_uuid(value: str) -> bool:
            return value == provider_session

    ready = {
        "lease": {
            "transport_container_id": attempt["transport_container_id"],
            "tool_container_id": attempt["tool_container_id"],
            "transport_image_id": attempt["transport_image_id"],
            "tool_image_id": attempt["tool_image_id"],
        },
        "pair_receipt_sha256": attempt["pair_receipt_sha256"],
        "active_material_mount": copy.deepcopy(mount),
    }
    source_equal = specs.host_bind_sources_equal

    class FakeHost:
        specs = SimpleNamespace(host_bind_sources_equal=source_equal)

        @staticmethod
        def require_live_pair_ready(**kwargs: Any) -> dict[str, Any]:
            assert kwargs == {
                "expected_episode_id": episode_id,
                "expected_host_session_id": host_session,
                "expected_provider_session_uuid": provider_session,
                "allow_synthetic": False,
                "require_active_material_mount": True,
            }
            return copy.deepcopy(ready)

    monkeypatch.setattr(runtime, "_research_episode_assert_root_allowed", lambda _root: None)
    monkeypatch.setattr(
        runtime, "_research_episode_lock", lambda _root: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_read_meta",
        lambda _root: {"episode_id": episode_id, "session_id": host_session},
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_load_head",
        lambda _root: {"head_checkpoint_sha256": head_sha},
    )
    monkeypatch.setattr(runtime, "_research_episode_load_native_session", FakeNative)
    monkeypatch.setattr(runtime, "_research_episode_load_dual_host", lambda _root: (None, FakeHost()))

    verified = runtime.research_episode_load_verified_material_reality(
        root=episode,
        attempt_cas_digest=final_cas,
        attempt_hash=str(attempt["attempt_hash"]),
        expected_head_sha256=head_sha,
        expected_provider_session_uuid=provider_session,
        expected_host_session_id=host_session,
    )
    assert verified["attempt_cas_digest"] == final_cas
    assert verified["attempt_hash"] == attempt["attempt_hash"]
    assert verified["active_material_binding"] == binding
    assert verified["active_material_mount"]["readonly"] is True
    assert set(verified["material_bytes_by_id"]) == set(verified["material_ids"])
    assert verified["prospective_packet_material_id"] in verified["material_ids"]
    assert verified["objective_terms_material_id"] in verified["material_ids"]
    assert verified["portfolio_reality_material_id"] in verified["material_ids"]

    with pytest.raises(runtime.XinaoError) as stale:
        runtime.research_episode_load_verified_material_reality(
            root=episode,
            attempt_cas_digest="9" * 64,
            attempt_hash=str(attempt["attempt_hash"]),
            expected_head_sha256=head_sha,
            expected_provider_session_uuid=provider_session,
            expected_host_session_id=host_session,
        )
    assert stale.value.reason_code == "RESEARCH_EPISODE_ATTEMPT_CAS_NOT_CURRENT_SUCCESS"


def test_actor_reality_production_wrapper_accepts_only_verified_episode_identities(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode_id = "episode-exact"
    host_session_id = "host-exact"
    provider_session_uuid = str(uuid.uuid4())
    head_sha = "d" * 64
    attempt_cas = "c" * 64
    internal_cas = "e" * 64
    attempt_hash = "f" * 64
    portfolio_id = "sha256:" + "5" * 64
    prospective_id = "sha256:" + "7" * 64
    objective_id = "sha256:" + "9" * 64
    material_manifest = {
        "schema_version": "xinao.material_bundle.v1",
        "provider_disclosure_scope": "caller_supplied_for_bounded_research_episode",
        "materials": [],
        "bundle_id": "xinao-material-bundle-sha256:" + "1" * 64,
    }
    binding = {
        "schema_version": "xinao.research_episode_active_material_binding.v1",
        "material_bundle_id": material_manifest["bundle_id"],
        "material_manifest": material_manifest,
        "material_manifest_sha256": "2" * 64,
        "material_packet_sha256": "3" * 64,
        "base_prompt_sha256": "4" * 64,
        "effective_prompt_sha256": "4" * 64,
        "material_manifest_relative_path": "bundles/one/manifest.json",
        "effective_prompt_relative_path": "prompts/four.utf8",
        "material_snapshot_at": "2026-08-01T00:00:00Z",
    }
    portfolio_payload = {
        "schema_version": "xinao.actor_portfolio_reality.v1",
        "content_hash": "6" * 64,
        "period_index": 1,
    }
    objective_payload = {
        "schema_version": "xinao.actor_objective_terms.v1",
        "content_hash": "a" * 64,
    }
    verified = {
        "schema_version": "xinao.research_episode_verified_material_reality.v1",
        "episode_id": episode_id,
        "host_session_id": host_session_id,
        "cas_head_sha256": head_sha,
        "attempt_cas_digest": attempt_cas,
        "attempt_internal_cas_digest": internal_cas,
        "attempt_hash": attempt_hash,
        "provider_session_uuid": provider_session_uuid,
        "active_material_binding": binding,
        "portfolio_reality_material_id": portfolio_id,
        "portfolio_reality_material_sha256": "5" * 64,
        "portfolio_reality_content_hash": "6" * 64,
        "portfolio_reality_period_index": 1,
        "prospective_packet_material_id": prospective_id,
        "prospective_packet_material_sha256": "7" * 64,
        "prospective_packet_content_hash": "8" * 64,
        "prospective_target_expect": "2026214",
        "prospective_target_ref": "macaujc2/expect/2026214",
        "prospective_source_id": "macaujc2",
        "prospective_source_contract_sha256": "b" * 64,
        "prospective_source_capture_sha256": "c" * 64,
        "prospective_source_authority_binding_hash": "d" * 64,
        "objective_terms_material_id": objective_id,
        "objective_terms_material_sha256": "9" * 64,
        "objective_terms_content_hash": "a" * 64,
        "prior_feedback_material_id": None,
        "prior_feedback_material_sha256": None,
        "prior_feedback_content_hash": None,
        "prior_candidate_export_material_id": None,
        "prior_candidate_export_sha256": None,
        "prior_candidate_manifest_material_id": None,
        "prior_candidate_manifest_sha256": None,
        "material_bytes_by_id": {
            portfolio_id: json.dumps(portfolio_payload, sort_keys=True).encode("utf-8"),
            objective_id: json.dumps(objective_payload, sort_keys=True).encode("utf-8"),
        },
    }
    monkeypatch.setattr(
        runtime,
        "research_episode_load_verified_material_reality",
        lambda **_kwargs: verified,
    )
    observed_factory: dict[str, Any] = {}
    class Packet:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload
            self.content_hash = payload["content_hash"]
            self.period_index = payload.get("period_index")

        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return copy.deepcopy(self.payload)

    class Manifest:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            assert mode == "json"
            return copy.deepcopy(material_manifest)

    materials = SimpleNamespace(
        schema_version="xinao.actor_material_reality.v1",
        episode_id=episode_id,
        host_session_id=host_session_id,
        cas_head_sha256=head_sha,
        attempt_cas_digest=attempt_cas,
        attempt_internal_cas_digest=internal_cas,
        attempt_hash=attempt_hash,
        provider_session_uuid=provider_session_uuid,
        active_material_binding_hash=runtime._sha256_bytes(
            runtime._canonical_bytes(binding)
        ),
        material_bundle_id=binding["material_bundle_id"],
        material_manifest=Manifest(),
        material_manifest_sha256=binding["material_manifest_sha256"],
        material_packet_sha256=binding["material_packet_sha256"],
        base_prompt_sha256=binding["base_prompt_sha256"],
        effective_prompt_sha256=binding["effective_prompt_sha256"],
        material_manifest_relative_path=binding["material_manifest_relative_path"],
        effective_prompt_relative_path=binding["effective_prompt_relative_path"],
        material_snapshot_at=dt.datetime.fromisoformat("2026-08-01T00:00:00+00:00"),
        portfolio_reality_material_id=verified["portfolio_reality_material_id"],
        portfolio_reality_material_sha256=verified[
            "portfolio_reality_material_sha256"
        ],
        portfolio_reality=Packet(portfolio_payload),
        prospective_packet_material_id=verified["prospective_packet_material_id"],
        prospective_packet_material_sha256=verified[
            "prospective_packet_material_sha256"
        ],
        prospective_packet_content_hash=verified["prospective_packet_content_hash"],
        source_id=verified["prospective_source_id"],
        source_contract_sha256=verified["prospective_source_contract_sha256"],
        source_capture_sha256=verified["prospective_source_capture_sha256"],
        source_authority_binding_hash=verified[
            "prospective_source_authority_binding_hash"
        ],
        target_expect=verified["prospective_target_expect"],
        target_ref=verified["prospective_target_ref"],
        objective_terms_material_id=verified["objective_terms_material_id"],
        objective_terms_material_sha256=verified[
            "objective_terms_material_sha256"
        ],
        objective_terms=Packet(objective_payload),
        prior_feedback_material_id=None,
        prior_feedback_material_sha256=None,
        prior_feedback_content_hash=None,
        prior_candidate_export_material_id=None,
        prior_candidate_export_sha256=None,
        prior_candidate_manifest_material_id=None,
        prior_candidate_manifest_sha256=None,
    )

    class Contract:
        def __init__(self) -> None:
            self.content_hash = "b" * 64
            self.material_reality = materials

        @classmethod
        def _from_verified_material_reality(cls, **kwargs: Any) -> Contract:
            observed_factory.update(kwargs)
            return cls()

        def compute_content_hash(self) -> str:
            return "b" * 64

    monkeypatch.setattr(
        runtime,
        "_import_actor_reality_contract_module",
        lambda: SimpleNamespace(ActorRealityContract=Contract),
    )
    episode = tmp_path / "episode"
    portfolio = tmp_path / "portfolio"
    authority = tmp_path / "authority"
    contract = runtime.research_episode_build_actor_reality(
        root=episode,
        portfolio_root=portfolio,
        authority_root=authority,
        attempt_cas_digest="c" * 64,
        expected_head_sha256=head_sha,
        expected_provider_session_uuid=provider_session_uuid,
        expected_host_session_id=host_session_id,
    )
    assert isinstance(contract, Contract)
    assert observed_factory == {
        "portfolio_root": portfolio,
        "episode_root": episode,
        "authority_root": authority,
        "verified_material_reality": verified,
    }

    materials.episode_id = "foreign-episode"
    with pytest.raises(runtime.XinaoError) as foreign:
        runtime.research_episode_build_actor_reality(
            root=episode,
            portfolio_root=portfolio,
            authority_root=authority,
            attempt_cas_digest=attempt_cas,
            expected_head_sha256=head_sha,
            expected_provider_session_uuid=provider_session_uuid,
            expected_host_session_id=host_session_id,
        )
    assert foreign.value.reason_code == "ACTOR_REALITY_VERIFIED_MATERIAL_MISMATCH"
    materials.episode_id = episode_id

    calls = {"count": 0}

    def drifting_loader(**_kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            return verified
        return {**verified, "attempt_hash": "0" * 64}

    monkeypatch.setattr(
        runtime, "research_episode_load_verified_material_reality", drifting_loader
    )
    with pytest.raises(runtime.XinaoError) as changed:
        runtime.research_episode_build_actor_reality(
            root=episode,
            portfolio_root=portfolio,
            authority_root=authority,
            attempt_cas_digest=attempt_cas,
            expected_head_sha256=head_sha,
            expected_provider_session_uuid=provider_session_uuid,
            expected_host_session_id=host_session_id,
        )
    assert changed.value.reason_code == (
        "ACTOR_REALITY_CURRENT_SUCCESS_CHANGED_DURING_BUILD"
    )


def test_material_role_loader_requires_declared_longitudinal_provenance_after_genesis(
    runtime: Any, tmp_path: Path
) -> None:
    documents = {
        "prospective.json": {
            "schema_version": "xinao.prospective_target_authority_packet.v1",
            "packet_marker": "XINAO_PROSPECTIVE_TARGET_AUTHORITY_V1",
            "content_hash": "1" * 64,
            "target_expect": "2026214",
            "target_ref": "macaujc2/expect/2026214",
            "contract": {"contract_sha256": "a" * 64},
            "capture_sha256": "b" * 64,
            "latest_completed_expect": "2026213",
            "target_guard_open_time": "2026-08-02T01:00:00Z",
            "freeze_deadline": "2026-08-02T00:59:00Z",
        },
        "objective.json": {
            "schema_version": "xinao.actor_objective_terms.v1",
            "source_kind": "PINNED_SETTLEMENT_RULE_SNAPSHOT",
            "source_ref": "xinao.settlement.special_number.SPECIAL_NUMBER_FUNCTION",
            "content_hash": "2" * 64,
        },
        "portfolio.json": {
            "schema_version": "xinao.actor_portfolio_reality.v1",
            "packet_marker": "XINAO_ACTOR_PORTFOLIO_REALITY_V1",
            "period_index": 2,
            "content_hash": "3" * 64,
        },
        "feedback.json": {
            "schema_version": "xinao.research_feedback_pack.v1",
            "pack_marker": "XINAO_RESEARCH_FEEDBACK_PACK_V1",
            "content_hash": "4" * 64,
        },
        "prior-export.json": {
            "schema_version": "xinao.research_episode_candidate_evidence_bundle.v1"
        },
        "prior-manifest.json": {
            "schema_version": "xinao.research_episode_candidate_manifest.v1",
            "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        },
    }
    paths: list[Path] = []
    for name, value in documents.items():
        path = tmp_path / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        paths.append(path)
    extra = tmp_path / "researcher-notes.txt"
    extra.write_text("additional declared feedback context\n", encoding="utf-8")
    paths.append(extra)
    binding, _witness = runtime._materialize_research_episode_active_binding(
        episode_root=tmp_path / "episode",
        base_prompt="continue the same research",
        material_paths=paths,
        auth_path=_auth(tmp_path),
    )
    roles = runtime._research_episode_material_role_identities(
        tmp_path / "episode", binding
    )
    assert roles["portfolio_reality_period_index"] == 2
    assert roles["prior_feedback_content_hash"] == "4" * 64
    assert roles["prior_candidate_export_material_id"].startswith("sha256:")
    assert roles["prior_candidate_manifest_material_id"].startswith("sha256:")
    assert len(roles["material_bytes_by_id"]) == len(paths)


def test_prepare_actor_materials_reads_live_objects_and_is_idempotent(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime._import_actor_reality_contract_module()
    prospective_module = runtime._import_prospective_source_module()

    core = tmp_path / "first-principles.txt"
    core.write_bytes("第一性原理：现实行动者先行。\n".encode("utf-8"))
    core_sha = runtime._sha256(core)
    authority_root = tmp_path / "authority"
    packet: dict[str, Any] = {
        "schema_version": "xinao.prospective_target_authority_packet.v1",
        "packet_marker": "XINAO_PROSPECTIVE_TARGET_AUTHORITY_V1",
        "contract": {"contract_sha256": "a" * 64},
        "latest_completed_expect": "2026213",
        "target_expect": "2026214",
        "target_ref": "macaujc2/expect/2026214",
        "target_guard_open_time": "2026-08-02T01:00:00Z",
        "freeze_deadline": "2026-08-02T00:59:00Z",
        "capture_sha256": "b" * 64,
        "host_time_utc": "2026-08-02T00:30:00Z",
        "unopened": {
            "history_max_expect": "2026213",
            "point_next_data_null": True,
            "absent_from_history": True,
        },
    }
    sealed = prospective_module.write_packet_exclusive(authority_root, packet)
    packet_hash = str(sealed["packet_content_hash"])
    authority_raw = Path(str(sealed["path"])).read_bytes()

    class GeneratedPacket:
        def __init__(self, *, content_hash: str, period_index: int = 1) -> None:
            self.content_hash = content_hash
            self.period_index = period_index

        def with_content_hash(self) -> GeneratedPacket:
            return self

    objective_packet = GeneratedPacket(content_hash="c" * 64)
    portfolio_packet = GeneratedPacket(content_hash="d" * 64)
    objective_raw = b'{"content_hash":"' + b"c" * 64 + b'"}\n'
    portfolio_raw = b'{"content_hash":"' + b"d" * 64 + b'","period_index":1}\n'

    class ObjectiveFactory:
        @staticmethod
        def from_settlement_rule() -> GeneratedPacket:
            return objective_packet

    fake_actor = SimpleNamespace(
        ActorObjectiveTermsPacket=ObjectiveFactory,
        actor_objective_terms_packet_bytes=lambda packet: (
            objective_raw if packet is objective_packet else b""
        ),
        build_actor_portfolio_reality_packet=lambda root: (
            portfolio_packet if Path(root) == tmp_path / "portfolio" else None
        ),
        actor_portfolio_reality_packet_bytes=lambda packet: (
            portfolio_raw if packet is portfolio_packet else b""
        ),
    )
    monkeypatch.setattr(
        runtime, "_import_actor_reality_contract_module", lambda: fake_actor
    )
    monkeypatch.setattr(
        runtime,
        "_assert_explicit_actor_material_output_root",
        lambda path: Path(path),
    )
    output_root = tmp_path / "prepared"

    with pytest.raises(runtime.XinaoError) as wrong_core:
        runtime.research_episode_prepare_actor_materials(
            core_path=core,
            core_sha256="0" * 64,
            authority_root=authority_root,
            packet_content_hash=packet_hash,
            portfolio_root=tmp_path / "portfolio",
            output_root=output_root,
        )
    assert wrong_core.value.reason_code == "ACTOR_MATERIAL_CORE_HASH_MISMATCH"

    prepared = runtime.research_episode_prepare_actor_materials(
        core_path=core,
        core_sha256=core_sha,
        authority_root=authority_root,
        packet_content_hash=packet_hash,
        portfolio_root=tmp_path / "portfolio",
        output_root=output_root,
    )
    assert prepared["status"] == "ACTOR_MATERIALS_PREPARED"
    assert prepared["material_count"] == 4
    assert prepared["files_created"] == 4
    assert prepared["longitudinal_materials_included"] is False
    by_role = {item["role"]: item for item in prepared["material_files"]}
    assert Path(by_role["first_principles_core"]["path"]).read_bytes() == core.read_bytes()
    assert (
        Path(by_role["prospective_authority_packet"]["path"]).read_bytes()
        == authority_raw
    )
    assert by_role["prospective_authority_packet"]["content_hash"] == packet_hash
    assert Path(by_role["objective_terms"]["path"]).read_bytes() == objective_raw
    assert Path(by_role["portfolio_reality"]["path"]).read_bytes() == portfolio_raw
    assert prepared["attach_performed"] is False
    assert prepared["freeze_performed"] is False

    reused = runtime.research_episode_prepare_actor_materials(
        core_path=core,
        core_sha256=core_sha,
        authority_root=authority_root,
        packet_content_hash=packet_hash,
        portfolio_root=tmp_path / "portfolio",
        output_root=output_root,
    )
    assert reused["files_created"] == 0
    assert reused["files_reused"] == 4

    objective_path = Path(by_role["objective_terms"]["path"])
    objective_path.write_bytes(b"conflict\n")
    with pytest.raises(runtime.XinaoError) as conflict:
        runtime.research_episode_prepare_actor_materials(
            core_path=core,
            core_sha256=core_sha,
            authority_root=authority_root,
            packet_content_hash=packet_hash,
            portfolio_root=tmp_path / "portfolio",
            output_root=output_root,
        )
    assert conflict.value.reason_code == "ACTOR_MATERIAL_OUTPUT_CONFLICT"

    portfolio_packet = GeneratedPacket(content_hash="e" * 64, period_index=2)
    portfolio_raw = b'{"content_hash":"' + b"e" * 64 + b'","period_index":2}\n'
    period2_root = tmp_path / "prepared-period2"
    with pytest.raises(runtime.XinaoError) as pool_required:
        runtime.research_episode_prepare_actor_materials(
            core_path=core,
            core_sha256=core_sha,
            authority_root=authority_root,
            packet_content_hash=packet_hash,
            portfolio_root=tmp_path / "portfolio",
            output_root=period2_root,
        )
    assert pool_required.value.reason_code == "ACTOR_MATERIAL_POOL_ROOT_REQUIRED"
    prior_payloads = {
        "prior_feedback_pack": (b"feedback-pack\n", "1" * 64),
        "prior_candidate_export": (b"prior-export\n", "2" * 64),
        "prior_candidate_manifest": (b"prior-manifest\n", "3" * 64),
    }
    monkeypatch.setattr(
        runtime,
        "_load_longitudinal_actor_material_payloads",
        lambda **_kwargs: prior_payloads,
    )
    period2 = runtime.research_episode_prepare_actor_materials(
        core_path=core,
        core_sha256=core_sha,
        authority_root=authority_root,
        packet_content_hash=packet_hash,
        portfolio_root=tmp_path / "portfolio",
        pool_root=tmp_path / "pool",
        output_root=period2_root,
    )
    assert period2["material_count"] == 7
    assert period2["longitudinal_materials_included"] is True
    assert {item["role"] for item in period2["material_files"]} == {
        "first_principles_core",
        "prospective_authority_packet",
        "objective_terms",
        "portfolio_reality",
        *prior_payloads,
    }


def test_prepare_actor_materials_cli_has_only_identity_and_root_inputs(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        runtime._parser().parse_args(
            ["research-episode", "prepare-actor-materials", "--help"]
        )
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    for required in (
        "--core",
        "--core-sha256",
        "--authority-root",
        "--packet-content-hash",
        "--portfolio-root",
        "--pool-root",
        "--output-root",
    ):
        assert required in help_text
    for forbidden in ("--odds", "--balance", "--target-ref", "--stake"):
        assert forbidden not in help_text

    observed: dict[str, Any] = {}

    def fake_prepare(**kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return {"status": "ACTOR_MATERIALS_PREPARED", "material_count": 4}

    monkeypatch.setattr(runtime, "research_episode_prepare_actor_materials", fake_prepare)
    args = [
        "research-episode",
        "prepare-actor-materials",
        "--core",
        str(tmp_path / "core.txt"),
        "--core-sha256",
        "1" * 64,
        "--authority-root",
        str(tmp_path / "authority"),
        "--packet-content-hash",
        "2" * 64,
        "--portfolio-root",
        str(tmp_path / "portfolio"),
        "--output-root",
        str(tmp_path / "output"),
    ]
    assert runtime.main(args) == 0
    assert json.loads(capsys.readouterr().out)["material_count"] == 4
    assert set(observed) == {
        "core_path",
        "core_sha256",
        "authority_root",
        "packet_content_hash",
        "portfolio_root",
        "pool_root",
        "output_root",
    }

    if sys.platform == "win32":
        with pytest.raises(runtime.XinaoError) as c_drive:
            runtime._assert_explicit_actor_material_output_root(Path("C:/xinao-materials"))
        assert c_drive.value.reason_code == "ACTOR_MATERIAL_OUTPUT_ROOT_NOT_DATA_DRIVE"


def _install_fake_actor_material_validators(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PortfolioContract:
        @staticmethod
        def model_validate(value: dict[str, Any]) -> SimpleNamespace:
            if (
                value.get("schema_version") != "xinao.actor_portfolio_reality.v1"
                or value.get("packet_marker") != "XINAO_ACTOR_PORTFOLIO_REALITY_V1"
                or not isinstance(value.get("period_index"), int)
                or value.get("period_index", 0) < 1
            ):
                raise ValueError("invalid portfolio packet")
            return SimpleNamespace(
                period_index=value["period_index"],
                content_hash=value.get("content_hash"),
                portfolio_ref=value.get("portfolio_ref", "portfolio-live"),
                prior_settled_episode_hash=value.get("prior_settled_episode_hash"),
                live_head_feedback_hash=value.get("live_head_feedback_hash"),
                current_balance=value.get("current_balance", "10000"),
            )

    class ObjectiveContract:
        @staticmethod
        def model_validate(value: dict[str, Any]) -> SimpleNamespace:
            if (
                value.get("schema_version") != "xinao.actor_objective_terms.v1"
                or value.get("source_kind") != "PINNED_SETTLEMENT_RULE_SNAPSHOT"
                or value.get("source_ref")
                != "xinao.settlement.special_number.SPECIAL_NUMBER_FUNCTION"
            ):
                raise ValueError("invalid objective packet")
            return SimpleNamespace(content_hash=value.get("content_hash"))

    fake_actor = SimpleNamespace(
        ActorPortfolioRealityPacket=PortfolioContract,
        ActorObjectiveTermsPacket=ObjectiveContract,
        canonical_sha256=lambda _value: "f" * 64,
    )

    class FakeProspective:
        @staticmethod
        def packet_content_hash(packet: dict[str, Any]) -> str:
            return str(packet.get("content_hash") or "")

        @staticmethod
        def reject_outcome_material(_packet: dict[str, Any]) -> None:
            return None

        @staticmethod
        def build_source_authority_binding(packet: dict[str, Any]) -> dict[str, Any]:
            return {"packet_content_hash": packet["content_hash"]}

        @staticmethod
        def validate_source_authority_binding(
            binding: dict[str, Any], *, packet: dict[str, Any]
        ) -> dict[str, Any]:
            assert binding["packet_content_hash"] == packet["content_hash"]
            return binding

    class FakeEpisodePool:
        @staticmethod
        def verify_episode_export_bundle(raw: bytes) -> dict[str, Any]:
            value = json.loads(raw.decode("utf-8"))
            assert value["schema_version"] == (
                "xinao.research_episode_candidate_evidence_bundle.v1"
            )
            return value

        @staticmethod
        def load_and_verify_candidate_manifest(
            *, export: dict[str, Any], manifest_bytes: bytes
        ) -> dict[str, Any]:
            del export
            value = json.loads(manifest_bytes.decode("utf-8"))
            assert value["manifest_marker"] == (
                "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1"
            )
            return value

    monkeypatch.setattr(
        runtime, "_import_actor_reality_contract_module", lambda: fake_actor
    )
    monkeypatch.setattr(
        runtime, "_import_prospective_source_module", lambda: FakeProspective
    )
    monkeypatch.setattr(
        runtime,
        "_import_xinao_science_module",
        lambda name: (
            FakeEpisodePool
            if name == "xinao.science.episode_export_pool_adapter"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )


def test_actor_material_root_requires_exact_period_appropriate_prepare_set(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_actor_material_validators(runtime, monkeypatch)
    monkeypatch.setattr(
        runtime,
        "_assert_explicit_actor_material_output_root",
        lambda path: Path(path),
    )
    root = tmp_path / "prepared"
    root.mkdir()
    (root / "first-principles-core.utf8").write_text(
        "行动者自主研究、行动并承担结果。\n", encoding="utf-8"
    )
    prospective = {
        "schema_version": "xinao.prospective_target_authority_packet.v1",
        "packet_marker": "XINAO_PROSPECTIVE_TARGET_AUTHORITY_V1",
        "content_hash": "1" * 64,
        "contract": {"contract_sha256": "a" * 64},
        "target_ref": "macaujc2/expect/2026214",
        "target_expect": "2026214",
        "target_guard_open_time": "2026-08-02T01:00:00Z",
        "freeze_deadline": "2026-08-02T00:59:00Z",
        "latest_completed_expect": "2026213",
        "capture_sha256": "b" * 64,
    }
    objective = {
        "schema_version": "xinao.actor_objective_terms.v1",
        "source_kind": "PINNED_SETTLEMENT_RULE_SNAPSHOT",
        "source_ref": "xinao.settlement.special_number.SPECIAL_NUMBER_FUNCTION",
        "content_hash": "2" * 64,
    }
    portfolio = {
        "schema_version": "xinao.actor_portfolio_reality.v1",
        "packet_marker": "XINAO_ACTOR_PORTFOLIO_REALITY_V1",
        "period_index": 1,
        "portfolio_ref": "portfolio-live",
        "current_balance": "10000",
        "content_hash": "3" * 64,
    }
    for name, value in (
        ("prospective-authority-packet.json", prospective),
        ("objective-terms.json", objective),
        ("portfolio-reality.json", portfolio),
    ):
        (root / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    genesis = runtime._resolve_research_episode_actor_material_selection(root)
    assert genesis["period_index"] == 1
    assert [path.name for path in genesis["paths"]] == [
        name for _role, name in runtime.RESEARCH_EPISODE_ACTOR_MATERIAL_BASE_OUTPUTS
    ]

    extra = root / "platform-supplement.json"
    extra.write_text('{"stake":"platform-picked"}\n', encoding="utf-8")
    with pytest.raises(runtime.XinaoError) as supplemented:
        runtime._resolve_research_episode_actor_material_selection(root)
    assert supplemented.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_FILE_SET_INVALID"
    )
    extra.unlink()

    for _role, name in runtime.RESEARCH_EPISODE_ACTOR_MATERIAL_LONGITUDINAL_OUTPUTS:
        (root / name).write_text("{}\n", encoding="utf-8")
    with pytest.raises(runtime.XinaoError) as genesis_with_priors:
        runtime._resolve_research_episode_actor_material_selection(root)
    assert genesis_with_priors.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_FILE_SET_INVALID"
    )
    for _role, name in runtime.RESEARCH_EPISODE_ACTOR_MATERIAL_LONGITUDINAL_OUTPUTS:
        (root / name).unlink()

    portfolio.update(
        {
            "period_index": 2,
            "prior_settled_episode_hash": "4" * 64,
            "live_head_feedback_hash": "5" * 64,
            "current_balance": "9600",
            "content_hash": "6" * 64,
        }
    )
    (root / "portfolio-reality.json").write_text(
        json.dumps(portfolio, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(runtime.XinaoError) as missing_priors:
        runtime._resolve_research_episode_actor_material_selection(root)
    assert missing_priors.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_FILE_SET_INVALID"
    )

    prior_export_raw = (
        json.dumps(
            {
                "schema_version": (
                    "xinao.research_episode_candidate_evidence_bundle.v1"
                )
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    prior_manifest_raw = (
        json.dumps(
            {
                "schema_version": "xinao.research_episode_candidate_manifest.v1",
                "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    feedback = {
        "schema_version": "xinao.research_feedback_pack.v1",
        "pack_marker": "XINAO_RESEARCH_FEEDBACK_PACK_V1",
        "content_hash": "f" * 64,
        "auto_start_next_research": False,
        "scientific_promotion": False,
        "portfolio_ref": "portfolio-live",
        "period_index": 1,
        "settled_episode_hash": "4" * 64,
        "account_feedback_hash": "5" * 64,
        "closing_balance": "9600",
        "prior_result_sha256": runtime._sha256_bytes(prior_export_raw),
        "prior_receipt_content_sha256": runtime._sha256_bytes(prior_manifest_raw),
    }
    (root / "prior-feedback-pack.json").write_text(
        json.dumps(feedback, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "prior-candidate-export.json").write_bytes(prior_export_raw)
    (root / "prior-candidate-manifest.json").write_bytes(prior_manifest_raw)
    longitudinal = runtime._resolve_research_episode_actor_material_selection(root)
    assert longitudinal["period_index"] == 2
    assert len(longitudinal["paths"]) == 7

    (root / "prior-candidate-manifest.json").unlink()
    with pytest.raises(runtime.XinaoError) as incomplete:
        runtime._resolve_research_episode_actor_material_selection(root)
    assert incomplete.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_FILE_SET_INVALID"
    )


def test_attach_and_resume_route_actor_root_to_original_material_producer(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    episode = tmp_path / "episode"
    head_sha = "a" * 64
    actor_paths = tuple(tmp_path / "prepared" / f"actor-{index}.utf8" for index in range(4))
    selection = {
        "root": tmp_path / "prepared",
        "paths": actor_paths,
        "period_index": 1,
        "source_sha256_by_path": {
            str(path): str(index) * 64 for index, path in enumerate(actor_paths, start=1)
        },
    }
    materialized: list[dict[str, Any]] = []
    actor_bound: list[dict[str, Any]] = []

    def fake_materialize(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        materialized.append(kwargs)
        return (
            {
                "material_bundle_id": "xinao-material-bundle-sha256:" + "b" * 64,
                "material_count": len(kwargs["material_paths"]),
                "material_source_refs": [],
            },
            {"path": str(tmp_path / "auth.json")},
        )

    class FakeHost:
        @staticmethod
        def attach_run_live(**_kwargs: Any) -> dict[str, Any]:
            return {"status": "PLANNED"}

        @staticmethod
        def resume_live(**_kwargs: Any) -> dict[str, Any]:
            return {"status": "PLANNED"}

    monkeypatch.setattr(
        runtime,
        "_resolve_research_episode_actor_material_selection",
        lambda root: selection if Path(root) == selection["root"] else None,
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_actor_candidate_authoring_prompt",
        lambda prompt: str(prompt or "") + "\nACTOR_AUTHORING_CONTRACT",
    )
    monkeypatch.setattr(runtime, "_research_episode_assert_root_allowed", lambda _root: None)
    monkeypatch.setattr(
        runtime, "_research_episode_lock", lambda _root: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_load_head",
        lambda _root: {"head_checkpoint_sha256": head_sha, "status": "RUNNING"},
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_read_meta",
        lambda _root: {"episode_id": "ep", "session_id": "host"},
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_resolve_profile_status",
        lambda _root: runtime.RESEARCH_EPISODE_PROFILE_STATUS_VERIFIED,
    )
    monkeypatch.setattr(runtime, "_research_episode_namespace_and_release_facts", dict)
    monkeypatch.setattr(
        runtime, "resolve_auth_host_path", lambda **_kwargs: tmp_path / "auth.json"
    )
    monkeypatch.setattr(
        runtime, "_materialize_research_episode_active_binding", fake_materialize
    )
    monkeypatch.setattr(
        runtime,
        "_assert_actor_material_selection_bound",
        lambda **kwargs: actor_bound.append(kwargs),
    )
    monkeypatch.setattr(runtime, "_validate_auth_identity_witness", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime, "_research_episode_load_dual_host", lambda _root: (None, FakeHost())
    )
    monkeypatch.setattr(
        runtime,
        "_research_episode_feedback_prompt",
        lambda **kwargs: {
            "prompt": str(kwargs["owner_prompt"] or "") + "\nSEALED_FEEDBACK_PROMPT",
            "feedback_inventory_read": True,
            "feedback_prompt_bound": True,
            "feedback_inventory_hash": "c" * 64,
            "feedback_packet_sha256": "d" * 64,
            "model_learned_claim_allowed": False,
        },
    )
    monkeypatch.setattr(runtime, "_research_episode_append_journal", lambda *_a, **_k: None)

    attached = runtime.research_episode_attach_run(
        root=episode,
        prompt="actor attach",
        expected_head_sha256=head_sha,
        actor_material_root=selection["root"],
        plan_only=True,
    )
    resumed = runtime.research_episode_resume_live(
        root=episode,
        expected_provider_session_uuid=str(uuid.uuid4()),
        expected_head_sha256=head_sha,
        prompt="actor resume",
        actor_material_root=selection["root"],
        plan_only=True,
    )
    generic = tmp_path / "generic.txt"
    generic_attach = runtime.research_episode_attach_run(
        root=episode,
        prompt="legacy generic",
        expected_head_sha256=head_sha,
        material_paths=[generic],
        plan_only=True,
    )
    assert attached["status"] == resumed["status"] == generic_attach["status"] == "PLANNED"
    assert [call["material_paths"] for call in materialized] == [
        actor_paths,
        actor_paths,
        (generic,),
    ]
    assert [call["base_prompt"] for call in materialized] == [
        "actor attach\nACTOR_AUTHORING_CONTRACT\nSEALED_FEEDBACK_PROMPT",
        "actor resume\nACTOR_AUTHORING_CONTRACT\nSEALED_FEEDBACK_PROMPT",
        "legacy generic\nSEALED_FEEDBACK_PROMPT",
    ]
    assert len(actor_bound) == 2
    assert all(call["selection"] == selection for call in actor_bound)


def test_actor_material_root_cannot_mix_with_generic_materials_before_host_use(
    runtime: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_called = False

    def forbidden_host(_root: Path) -> None:
        nonlocal host_called
        host_called = True
        raise AssertionError("host must not be loaded")

    monkeypatch.setattr(runtime, "_research_episode_load_dual_host", forbidden_host)
    with pytest.raises(runtime.XinaoError) as attach_conflict:
        runtime.research_episode_attach_run(
            root=tmp_path / "episode",
            prompt="q",
            material_paths=[tmp_path / "generic.txt"],
            actor_material_root=tmp_path / "prepared",
        )
    assert attach_conflict.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_MODE_CONFLICT"
    )
    with pytest.raises(runtime.XinaoError) as resume_conflict:
        runtime.research_episode_resume_live(
            root=tmp_path / "episode",
            expected_provider_session_uuid=str(uuid.uuid4()),
            expected_head_sha256="a" * 64,
            material_paths=[tmp_path / "generic.txt"],
            actor_material_root=tmp_path / "prepared",
        )
    assert resume_conflict.value.reason_code == (
        "RESEARCH_EPISODE_ACTOR_MATERIAL_MODE_CONFLICT"
    )
    assert host_called is False


def test_actor_authoring_contract_exposes_canonical_no_action_shape_not_a_choice(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_module = _load(
        "xinao_candidate_manifest_authoring_contract_test",
        ROOT
        / "xinao_discovery"
        / "src"
        / "xinao"
        / "science"
        / "research_episode_candidate_manifest.py",
    )
    monkeypatch.setattr(
        runtime,
        "_import_xinao_science_module",
        lambda name: (
            manifest_module
            if name == "xinao.science.research_episode_candidate_manifest"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )
    prompt = runtime._research_episode_actor_candidate_authoring_prompt(
        "Continue the investigation and preserve your own account choice."
    )
    assert prompt.startswith("Continue the investigation")
    contract = json.loads(
        prompt.split(runtime.RESEARCH_EPISODE_ACTOR_AUTHORING_CONTRACT_NOTICE, 1)[1]
    )
    assert contract["account_branch_mapping"]["NO_ACTION"] == "NO_ACTION_CANDIDATE"
    assert contract["actor_intent"]["schema_version"] == (
        "xinao.actor_authored_behavior_intent.v1"
    )
    assert contract["actor_intent"]["required_fields"] == [
        "authored_at",
        "decision_kind",
        "research_rationale",
        "schema_version",
        "stake",
    ]
    assert contract["legacy_aliases_forbidden"] == {
        "account_recommendation": ["ACTION", "RESEARCHER_ACCOUNT_NO_ACTION"],
        "actor_intent_fields": ["decision", "selection", "reasoning_one_line"],
    }
    assert contract["actor_choice_fields_supplied_by_contract"] == []

    base = {
        "schema_version": "xinao.research_episode_candidate_manifest.v1",
        "manifest_marker": "XINAO_RESEARCH_EPISODE_CANDIDATE_MANIFEST_V1",
        "candidate_id": "actor-no-action",
        "candidate_version": "v1",
        "research_question": "What should this actor do now?",
        "research_object": "live prospective period",
        "data_cutoff": {"as_of": "2026-08-01T00:00:00Z", "material_refs": []},
        "method_refs": ["actor-selected inquiry"],
        "falsifiers": ["future outcomes may falsify the rationale"],
        "candidate_only": True,
        "owner_adopted": False,
        "completion": False,
    }
    old_live_shape = {
        **base,
        "account_recommendation": "RESEARCHER_ACCOUNT_NO_ACTION",
        "proposed": {
            "decision": "NO_ACTION",
            "selection": None,
            "stake": "0.0000",
            "reasoning_one_line": "actor declined exposure",
        },
    }
    with pytest.raises(manifest_module.CandidateManifestError) as old_rejected:
        manifest_module.validate_candidate_manifest(old_live_shape)
    assert old_rejected.value.reason_code == "CANDIDATE_MANIFEST_RECOMMENDATION_INVALID"

    corrected_same_choice = {
        **base,
        "account_recommendation": "NO_ACTION_CANDIDATE",
        "proposed": {
            "schema_version": "xinao.actor_authored_behavior_intent.v1",
            "authored_at": "2026-08-01T00:00:00Z",
            "decision_kind": "NO_ACTION",
            "panel": None,
            "selected_number": None,
            "stake": "0.0000",
            "research_rationale": "actor declined exposure",
        },
    }
    validated = manifest_module.validate_candidate_manifest(corrected_same_choice)
    assert validated["account_recommendation"] == "NO_ACTION_CANDIDATE"
    assert validated["proposed"]["decision_kind"] == "NO_ACTION"
    assert validated["proposed"]["stake"] == "0.0000"
