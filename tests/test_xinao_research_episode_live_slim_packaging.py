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
    # Bytes match monorepo source (build copy, not a second logic truth).
    src_specs = (ROOT / "docker" / "xinao-researcher" / "docker_create_specs.py").read_bytes()
    staged = next(
        payload
        for relative, _path, payload in rows
        if relative.endswith("host_modules/docker_create_specs.py")
    )
    assert module._lf_materialize_bytes(src_specs) == staged


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
