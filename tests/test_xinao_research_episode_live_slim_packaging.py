"""WAVE124P: ResearchEpisode live-slim packaging + fail-closed seams.

Proves host modules are sealed into skill-bundle, installed-style staged Skill
resolves them without monorepo walk/PYTHONPATH, and network/auth/namespace
negatives fail closed. Does not start real Episode/containers or read secrets.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
RUNTIME_PATH = SKILL_ROOT / "scripts" / "xinao_runtime.py"
BOOTSTRAP_PATH = SKILL_ROOT / "scripts" / "xinao.py"


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
    return _load("xinao_runtime_wave124p_live_slim", RUNTIME_PATH)


def test_source_bundle_seals_host_modules(module: Any) -> None:
    rows = module._source_bundle_files(SKILL_ROOT)
    rels = {relative for relative, _path, _payload in rows}
    for name in module.HOST_MODULE_INVENTORY:
        relative = (module.HOST_MODULES_BUNDLE_RELATIVE / name).as_posix()
        assert relative in rels, relative
    # Explicit trusted monorepo root (formal build_release shape) must seal the same inventory.
    trusted = module._source_bundle_files(SKILL_ROOT, monorepo_source_root=ROOT)
    module._require_host_modules_sealed_in_bundle_rows(trusted)
    assert {relative for relative, _path, _payload in trusted} == rels
    # Bytes match monorepo source (build copy, not a second logic truth).
    src_specs = (ROOT / "docker" / "xinao-researcher" / "docker_create_specs.py").read_bytes()
    staged = next(
        payload
        for relative, _path, payload in rows
        if relative.endswith("host_modules/docker_create_specs.py")
    )
    assert module._lf_materialize_bytes(src_specs) == staged


def test_public_build_release_materializes_host_modules_in_release_dir(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real public consumer shape: build_release → release dir + skill-bundle.manifest.

    Exercises formal ``build_release`` (not helper-only ``_source_bundle_files``) under an
    isolated D:-style state root via the existing fake docker harness. Never activates.
    """
    from tests import test_xinao_skill as skill_tests

    skill_tests._state(module, tmp_path, monkeypatch)
    skill_tests._fake_build_environment(module, monkeypatch, dirty=True)
    receipt = module.build_release(ROOT, allow_dirty=True)
    assert receipt["status"] == "CANDIDATE_BUILT"
    assert receipt.get("activated") is False
    assert not module._state_paths()["pointer"].exists()

    release_dir = Path(str(receipt["release_manifest_path"])).parent
    bundle_root = release_dir / "skill-bundle"
    bundle_manifest_path = release_dir / "skill-bundle.manifest.json"
    assert bundle_root.is_dir()
    assert bundle_manifest_path.is_file()

    bundle_manifest = module._load_json(bundle_manifest_path)
    manifest_paths = {
        row["relative_path"]
        for row in bundle_manifest["files"]
        if isinstance(row, dict) and isinstance(row.get("relative_path"), str)
    }
    expected = {
        (module.HOST_MODULES_BUNDLE_RELATIVE / name).as_posix()
        for name in module.HOST_MODULE_INVENTORY
    }
    assert expected <= manifest_paths
    assert len(expected) == 6
    for relative in sorted(expected):
        path = bundle_root / Path(relative)
        assert path.is_file(), relative
        # Physical inventory matches manifest row identity.
        row = next(item for item in bundle_manifest["files"] if item["relative_path"] == relative)
        payload = path.read_bytes()
        assert row["size"] == len(payload)
        assert row["sha256"] == module._sha256_bytes(payload)

    # Formal monorepo builds must never emit the deficient 20-file skill-only inventory.
    assert len(bundle_manifest["files"]) >= 20 + 6


def test_public_build_fails_closed_when_host_module_source_missing(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing monorepo host module fails closed; no deficient release directory is sealed."""
    from tests import test_xinao_skill as skill_tests

    skill_tests._state(module, tmp_path, monkeypatch)
    skill_tests._fake_build_environment(module, monkeypatch, dirty=True)

    def missing_host_rows(source_root: Path):
        del source_root
        raise module.XinaoError(
            "HOST_MODULES_SOURCE_MISSING",
            "docker_create_specs.py:synthetic-missing",
        )

    monkeypatch.setattr(module, "_collect_packaged_host_module_rows", missing_host_rows)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=True)
    assert failure.value.reason_code == "HOST_MODULES_SOURCE_MISSING"
    release_root = module._state_paths()["release_root"]
    if release_root.is_dir():
        assert list(release_root.iterdir()) == []


def test_public_build_fails_closed_when_host_module_source_tampered(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Incomplete host-module inventory fails closed before a deficient release is sealed."""
    from tests import test_xinao_skill as skill_tests

    skill_tests._state(module, tmp_path, monkeypatch)
    skill_tests._fake_build_environment(module, monkeypatch, dirty=True)
    original = module._collect_packaged_host_module_rows

    def tamper_then_collect(source_root: Path):
        rows = original(source_root)
        # Drop one inventory row so post-seal require fails closed (simulates silent omit).
        return [row for row in rows if not row[0].endswith("native_grok_session.py")]

    monkeypatch.setattr(module, "_collect_packaged_host_module_rows", tamper_then_collect)
    with pytest.raises(module.XinaoError) as failure:
        module.build_release(ROOT, allow_dirty=True)
    assert failure.value.reason_code == "HOST_MODULES_BUNDLE_INCOMPLETE"
    assert "native_grok_session.py" in failure.value.detail
    release_root = module._state_paths()["release_root"]
    if release_root.is_dir():
        assert list(release_root.iterdir()) == []


def test_staged_installed_skill_resolves_host_modules_without_monorepo(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )
    skill_tests._terminal_pointer(module, manifest, path)
    bundle = Path(str(manifest["skill_bundle_path"]))
    host_dir = bundle / "scripts" / "host_modules"
    assert (host_dir / "docker_create_specs.py").is_file()
    assert (host_dir / "native_grok_session.py").is_file()

    # Fresh process: only staged skill tree on sys.path/cwd; no monorepo PYTHONPATH.
    staged_runtime = bundle / "scripts" / "xinao_runtime.py"
    env = {
        **os.environ,
        "XINAO_SKILL_STATE_ROOT": str(tmp_path / "state_probe"),
        "XINAO_RESEARCHER_RUN_ROOT": str(tmp_path / "runs_probe"),
        "XINAO_INSTALLED_SKILL_ROOT": str(bundle),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "",
    }
    probe = r"""
import importlib.util, json, sys
from pathlib import Path
runtime = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("staged_rt", runtime)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
host = mod.resolve_packaged_host_modules_dir()
print(json.dumps({
    "host_dir": str(host),
    "specs": (host / "docker_create_specs.py").is_file(),
    "native": (host / "native_grok_session.py").is_file(),
    "under_bundle": str(host).replace("\\\\", "/").endswith("scripts/host_modules")
      or str(host).replace("\\", "/").endswith("scripts/host_modules"),
}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(staged_runtime)],
        check=False,
        cwd=str(tmp_path),  # not monorepo root
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["specs"] is True
    assert payload["native"] is True
    assert payload["under_bundle"] is True


def test_fresh_staged_cli_help_and_inspect_surface(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )
    skill_tests._terminal_pointer(module, manifest, path)
    bundle = Path(str(manifest["skill_bundle_path"]))
    staged_runtime = bundle / "scripts" / "xinao_runtime.py"
    env = {
        **os.environ,
        "XINAO_SKILL_STATE_ROOT": str(module._state_paths()["capability_root"].parent),
        "XINAO_RESEARCHER_RUN_ROOT": str(tmp_path / "runs"),
        "XINAO_INSTALLED_SKILL_ROOT": str(bundle),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "",
    }
    help_run = subprocess.run(
        [sys.executable, "-I", "-B", str(staged_runtime), "research-episode", "--help"],
        check=False,
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (help_run.stdout or "") + (help_run.stderr or "")
    assert help_run.returncode == 0, text
    assert "ensure-pair" in text
    assert "retire-pair" in text

    # Companion seal tracks candidate runtime bytes.
    expected = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()
    bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert expected in bootstrap


def test_auth_resolve_order_and_fail_closed(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XINAO_AUTH_HOST_PATH", raising=False)
    monkeypatch.delenv("GROK_HOME", raising=False)
    monkeypatch.delenv("XINAO_DUAL_CONTAINER_SYNTHETIC", raising=False)
    missing = tmp_path / "no_such_auth.json"
    monkeypatch.setenv("XINAO_AUTH_HOST_PATH", str(missing))
    with pytest.raises(module.XinaoError) as failure:
        module.resolve_auth_host_path(allow_synthetic_missing=False)
    assert failure.value.reason_code == "GROK_AUTH_HANDLE_MISSING"

    present = tmp_path / "auth.json"
    present.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XINAO_AUTH_HOST_PATH", str(present))
    assert module.resolve_auth_host_path() == present

    monkeypatch.delenv("XINAO_AUTH_HOST_PATH", raising=False)
    grok_home = tmp_path / "gh"
    grok_home.mkdir()
    gh_auth = grok_home / "auth.json"
    gh_auth.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GROK_HOME", str(grok_home))
    assert module.resolve_auth_host_path() == gh_auth


def test_dual_bundle_passes_transport_network_tool_none(module: Any) -> None:
    specs = module._load_docker_create_specs_module()
    bundle = specs.dual_container_bundle(
        transport_image="sha256:" + "a" * 64,
        tool_image="sha256:" + "b" * 64,
        auth_host_path=str(Path.home() / ".grok" / "auth.json"),
        input_host_path=str(Path("D:/ep/in")),
        output_host_path=str(Path("D:/ep/out")),
        episode_lab_host_path=str(Path("D:/ep/lab")),
        ipc_host_dir=str(Path("D:/ep/ipc")),
        network="xinao_researcher_internal",
    )
    assert bundle["transport"]["network"] == "xinao_researcher_internal"
    assert bundle["tool_executor"]["network"] == "none"
    assert not bundle["tool_spec_violations"]


def test_ensure_pair_negatives_namespace_stale_terminal(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import test_xinao_skill as skill_tests
    from tests.test_xinao_dual_image_namespace import _seed_canonical_receipt

    manifest, path = skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )
    skill_tests._terminal_pointer(module, manifest, path)
    monkeypatch.setenv("XINAO_DUAL_CONTAINER_SYNTHETIC", "1")
    auth = tmp_path / "auth.json"
    auth.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XINAO_AUTH_HOST_PATH", str(auth))
    episode = tmp_path / "D_episode" / "ep1"
    started = module.research_episode_start(root=episode, question="bounded")
    with pytest.raises(module.XinaoError) as no_ns:
        module.research_episode_ensure_pair(
            root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
        )
    assert no_ns.value.reason_code == "RESEARCH_EPISODE_NAMESPACE_UNVERIFIED"

    _seed_canonical_receipt(
        module,
        release=manifest,
        transport_image_id=manifest["image_id"],
        tool_image_id=manifest["tool_image_id"],
    )
    with pytest.raises(module.XinaoError) as stale:
        module.research_episode_ensure_pair(root=episode, expected_head_sha256="0" * 64)
    assert stale.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"

    ready = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    assert ready["next_task_created"] is False
    assert ready["leg_b_scheduled"] is False
    assert ready["successor_episode_created"] is False
    assert ready["completion_claim_allowed"] is False
    assert ready["daemon"] is False

    cancelled = module.research_episode_cancel(root=episode)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["pair_retire"] is not None
    with pytest.raises(module.XinaoError) as terminal:
        module.research_episode_ensure_pair(
            root=episode, expected_head_sha256=cancelled["head_checkpoint_sha256"]
        )
    assert terminal.value.reason_code == "RESEARCH_EPISODE_TERMINAL"
