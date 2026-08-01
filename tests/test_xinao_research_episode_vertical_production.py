"""WAVE124A: long ResearchEpisode vertical production package attacks.

Prior break closed by public `ensure-pair` Owner consumer. Fresh-process CLI
coverage + negatives for: hidden outcome, self-scheduling/leg-B, unauthorized
write roots, stale checkpoint/CAS, cancel/resume. No live provider call.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
RUNTIME_PATH = SKILL_ROOT / "scripts" / "xinao_runtime.py"
BOOTSTRAP_PATH = SKILL_ROOT / "scripts" / "xinao.py"


class _FakeRecordPath:
    def __init__(self, relative: str, *, size: int, sha256: str) -> None:
        self.relative = relative
        self.size = size
        self.hash = SimpleNamespace(
            mode="sha256",
            value=base64.urlsafe_b64encode(bytes.fromhex(sha256)).rstrip(b"=").decode("ascii"),
        )

    def __str__(self) -> str:
        return self.relative


def _fake_distribution(module: Any, package_root: Path, *, version: str = "0.1.3") -> Any:
    files = [
        _FakeRecordPath(
            f"xinao/{row['relative_path']}",
            size=int(row["size"]),
            sha256=str(row["sha256"]),
        )
        for row in module._discovery_package_inventory(package_root)
    ]
    record = (
        "\n".join(f"{item.relative},sha256={item.hash.value},{item.size}" for item in files) + "\n"
    )
    return SimpleNamespace(
        metadata={"Name": "xinao-discovery"},
        version=version,
        files=files,
        locate_file=lambda relative: package_root.parent / relative,
        read_text=lambda name: record if name == "RECORD" else None,
    )


def _fake_module(path: Path) -> Any:
    return SimpleNamespace(__file__=str(path), __spec__=SimpleNamespace(origin=str(path)))


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
    return _load("xinao_runtime_wave124a_vertical", RUNTIME_PATH)


def _seed_receipt(
    module: Any,
    *,
    release: dict[str, Any],
    transport_image_id: str,
    tool_image_id: str,
) -> None:
    from tests.test_xinao_dual_image_namespace import _seed_canonical_receipt

    _seed_canonical_receipt(
        module,
        release=release,
        transport_image_id=transport_image_id,
        tool_image_id=tool_image_id,
    )


def _prepare_episode(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_receipt: bool = True,
    dual_synthetic: bool = True,
) -> tuple[Any, Path, dict[str, Any], dict[str, Any]]:
    from tests import test_xinao_skill as skill_tests

    manifest, path = skill_tests._sealed_release(
        module,
        tmp_path,
        monkeypatch,
        package_version="1.3.6",
        capability_version="1.2.2",
    )
    skill_tests._terminal_pointer(module, manifest, path)
    if with_receipt:
        _seed_receipt(
            module,
            release=manifest,
            transport_image_id=manifest["image_id"],
            tool_image_id=manifest["tool_image_id"],
        )
    if dual_synthetic:
        monkeypatch.setenv("XINAO_DUAL_CONTAINER_SYNTHETIC", "1")
        monkeypatch.setenv("XINAO_AUTH_HOST_PATH", str(tmp_path / "auth.json"))
        (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    # Prefer D-like root (not C:).
    episode = tmp_path / "D_episode" / "ep1"
    started = module.research_episode_start(
        root=episode, question="bounded multi-round open research"
    )
    return module, episode, started, manifest


def _episode_tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    snapshot: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[relative] = ("dir", None)
        else:
            snapshot[relative] = ("other", None)
    return snapshot


def test_public_cli_exposes_ensure_and_retire_pair() -> None:
    # Candidate source runtime is the public Skill entry after Owner build/activate.
    # Ordinary `xinao.py` help binds the *live sealed release* runtime until adoption.
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(RUNTIME_PATH), "research-episode", "--help"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0
    assert "ensure-pair" in text
    assert "retire-pair" in text
    # Companion seal must track candidate runtime bytes (bootstrap-migrate/forward path).
    expected = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()
    bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert expected in bootstrap
    runtime_src = RUNTIME_PATH.read_text(encoding="utf-8")
    assert '"ensure-pair"' in runtime_src
    assert '"retire-pair"' in runtime_src
    assert "research_episode_ensure_pair" in runtime_src
    assert "research_episode_retire_pair" in runtime_src


def test_capabilities_registry_lists_ensure_pair(module: Any) -> None:
    caps = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    episode = next(c for c in caps["capabilities"] if c["capability_id"] == "research-episode")
    assert episode["version"] == "0.1.6"
    assert episode["packaged_dependency"] == "xinao-discovery"
    assert episode["packaged_dependency_version"] == "0.1.3"
    assert episode["packaged_dependency_tree_schema"] == "xinao.package_tree.v1"
    assert episode["packaged_dependency_tree_sha256"] == module._discovery_package_tree_sha256(
        ROOT / "xinao_discovery" / "src" / "xinao"
    )
    assert "ensure-pair" in episode["skill_verbs"]
    assert "retire-pair" in episode["skill_verbs"]
    assert "prepare-actor-materials" in episode["skill_verbs"]
    assert episode["auto_next_task"] is False
    assert episode["candidate_only"] is True
    assert episode["completion_claim_allowed"] is False


def test_discovery_consumer_import_rejects_stale_installed_package(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = ROOT / "xinao_discovery" / "src" / "xinao"
    distribution = _fake_distribution(module, package_root, version="0.1.0")
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_PACKAGE_VERSION_MISMATCH"


def test_discovery_consumer_import_accepts_exact_installed_package(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = ROOT / "xinao_discovery" / "src" / "xinao"
    candidate = _fake_module(package_root / "science" / "research_feedback_material.py")
    distribution = _fake_distribution(module, package_root)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: candidate)
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    assert module._import_discovery_science("research_feedback_material") is candidate


def test_discovery_consumer_rejects_same_version_ambient_shadow_module(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = ROOT / "xinao_discovery" / "src" / "xinao"
    ambient = tmp_path / "ambient" / "xinao" / "science" / "research_feedback_material.py"
    ambient.parent.mkdir(parents=True)
    ambient.write_text("AMBIENT = True\n", encoding="utf-8")
    candidate = _fake_module(ambient)
    distribution = _fake_distribution(module, package_root)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: candidate)
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_PACKAGE_ORIGIN_MISMATCH"


def test_discovery_consumer_rejects_same_version_changed_package_tree(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = ROOT / "xinao_discovery" / "src" / "xinao"
    package_root = tmp_path / "site-packages" / "xinao"
    shutil.copytree(
        source_root, package_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    module_path = package_root / "science" / "research_feedback_material.py"
    module_path.write_bytes(module_path.read_bytes() + b"\nTAMPERED = True\n")
    candidate = _fake_module(module_path)
    distribution = _fake_distribution(module, package_root)
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: candidate)
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_PACKAGE_TREE_MISMATCH"


def test_discovery_consumer_rejects_ambiguous_same_name_distributions(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = ROOT / "xinao_discovery" / "src" / "xinao"
    distribution = _fake_distribution(module, package_root)
    monkeypatch.setattr(
        module.importlib_metadata,
        "distributions",
        lambda **_kwargs: [distribution, distribution],
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_PACKAGE_DISTRIBUTION_AMBIGUOUS"


def test_discovery_consumer_rejects_recorded_file_removed_from_disk(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = ROOT / "xinao_discovery" / "src" / "xinao"
    package_root = tmp_path / "site-packages" / "xinao"
    shutil.copytree(
        source_root, package_root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    distribution = _fake_distribution(module, package_root)
    (package_root / "science" / "research_feedback_material.py").unlink()
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_PACKAGE_RECORD_MISMATCH"


def test_formal_runtime_rejects_editable_install_and_source_override(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = ROOT / "xinao_discovery" / "src" / "xinao"
    distribution = SimpleNamespace(
        metadata={"Name": "xinao-discovery"},
        version="0.1.3",
        files=[],
        locate_file=lambda relative: package_root.parent / relative,
        read_text=lambda name: (
            json.dumps({"dir_info": {"editable": True}}) if name == "direct_url.json" else None
        ),
    )
    monkeypatch.setattr(module, "_discovery_runtime_is_formal", lambda: True)
    monkeypatch.setattr(
        module.importlib_metadata, "distributions", lambda **_kwargs: [distribution]
    )
    with pytest.raises(module.XinaoError) as failure:
        module._import_discovery_science("research_feedback_material")
    assert failure.value.reason_code == "DISCOVERY_EDITABLE_INSTALL_FORBIDDEN"

    monkeypatch.setenv("XINAO_DISCOVERY_SRC", str(tmp_path / "unsealed-source"))
    with pytest.raises(module.XinaoError) as override_failure:
        module._import_discovery_science("research_feedback_material")
    assert override_failure.value.reason_code == "DISCOVERY_SOURCE_OVERRIDE_FORBIDDEN"


def test_ensure_pair_requires_namespace_receipt(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(
        module, tmp_path, monkeypatch, with_receipt=False
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256=started["head_checkpoint_sha256"],
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_NAMESPACE_UNVERIFIED"


def test_ensure_pair_stale_cas_rejected(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256="0" * 64,
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    # Honest checkpoint then ensure under new head.
    failed_experiment = episode / "lab" / "experiments" / "fail1.txt"
    failed_experiment.parent.mkdir(parents=True, exist_ok=True)
    failed_experiment.write_bytes(b"experiment failed: exit 1\n")
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
        progress_note="failed shell experiment retained",
        lab_relative="experiments/fail1.txt",
        lab_bytes=b"experiment failed: exit 1\n",
    )
    assert (
        (episode / "lab" / "experiments" / "fail1.txt")
        .read_bytes()
        .startswith(b"experiment failed")
    )
    assert ckpt["completion_claim_allowed"] is False
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=ckpt["head_checkpoint_sha256"],
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    assert ready["next_task_created"] is False
    assert ready["leg_b_scheduled"] is False
    assert ready["successor_episode_created"] is False
    assert ready["outcome_written"] is False
    assert ready["freeze_written"] is False
    assert ready["settlement_written"] is False
    assert ready["completion_claim_allowed"] is False
    assert ready["owner_adopted"] is False
    assert ready["parent_complete"] is False
    # Intermediate failure retained after pair ensure.
    assert (episode / "lab" / "experiments" / "fail1.txt").is_file()


def test_checkpoint_cli_binds_existing_lab_bytes_without_rewrite(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    lab_file = episode / "lab" / "lab_notes" / "wild_search_result.md"
    lab_file.parent.mkdir(parents=True, exist_ok=True)
    exact = b"# exact experiment bytes\r\n\x00negative retained\n"
    lab_file.write_bytes(exact)
    before = os.lstat(lab_file)

    exit_code = module.main(
        [
            "research-episode",
            "checkpoint",
            "--root",
            str(episode),
            "--expected-head",
            started["head_checkpoint_sha256"],
            "--progress-note",
            "bind existing result",
            "--lab-relative",
            "lab_notes/wild_search_result.md",
        ]
    )
    output = capsys.readouterr().out.strip().splitlines()
    assert exit_code == 0
    payload = json.loads(output[-1])
    after = os.lstat(lab_file)
    assert lab_file.read_bytes() == exact
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    assert payload["checkpoint"]["lab_bytes_sha256"] == hashlib.sha256(exact).hexdigest()
    assert payload["checkpoint"]["lab_relative"] == "lab_notes/wild_search_result.md"


def test_checkpoint_python_api_cannot_materialize_or_overwrite_lab(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    lab_file = episode / "lab" / "lab_notes" / "result.md"
    lab_file.parent.mkdir(parents=True, exist_ok=True)
    exact = b"provider-authored experiment result\n"
    lab_file.write_bytes(exact)
    before = _episode_tree_snapshot(episode)

    def forbidden_container_action(**_kwargs: Any) -> dict[str, Any]:
        pytest.fail("mismatched caller bytes must fail before the container checkpoint driver")

    monkeypatch.setattr(module, "_research_episode_container_identity", forbidden_container_action)
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_checkpoint(
            root=episode,
            expected_head_sha256=started["head_checkpoint_sha256"],
            lab_relative="lab_notes/result.md",
            lab_bytes=b"caller replacement bytes\n",
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_LAB_FILE_CHANGED"
    assert _episode_tree_snapshot(episode) == before

    with pytest.raises(module.XinaoError) as missing_failure:
        module.research_episode_checkpoint(
            root=episode,
            expected_head_sha256=started["head_checkpoint_sha256"],
            lab_relative="lab_notes/new.md",
            lab_bytes=b"must not create\n",
        )
    assert missing_failure.value.reason_code == "RESEARCH_EPISODE_LAB_FILE_INVALID"
    assert _episode_tree_snapshot(episode) == before


@pytest.mark.parametrize("case", ["missing", "escape", "ads", "directory", "too_large"])
def test_checkpoint_cli_invalid_existing_lab_has_no_episode_side_effect(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    if case == "missing":
        relative = "lab_notes/missing.md"
    elif case == "escape":
        relative = "../outside.md"
    elif case == "ads":
        relative = "lab_notes/result.md:alternate"
    elif case == "directory":
        relative = "lab_notes/not_a_file"
        (episode / "lab" / relative).mkdir(parents=True)
    else:
        relative = "lab_notes/oversized.bin"
        target = episode / "lab" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * (module.MAX_RESEARCH_EPISODE_LAB_FILE_BYTES + 1))
    before = _episode_tree_snapshot(episode)

    def forbidden_container_action(**_kwargs: Any) -> dict[str, Any]:
        pytest.fail("invalid lab input must fail before the container checkpoint driver")

    monkeypatch.setattr(module, "_research_episode_container_identity", forbidden_container_action)
    exit_code = module.main(
        [
            "research-episode",
            "checkpoint",
            "--root",
            str(episode),
            "--expected-head",
            started["head_checkpoint_sha256"],
            "--lab-relative",
            relative,
        ]
    )
    output = capsys.readouterr().out.strip().splitlines()
    assert exit_code == 2
    error = json.loads(output[-1])
    assert error["reason_codes"][0] in {
        "RESEARCH_EPISODE_LAB_PATH_INVALID",
        "RESEARCH_EPISODE_LAB_FILE_INVALID",
    }
    assert _episode_tree_snapshot(episode) == before


@pytest.mark.parametrize("reparse_kind", ["leaf", "ancestor"])
def test_checkpoint_cli_reparse_lab_file_has_no_episode_side_effect(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reparse_kind: str,
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    if reparse_kind == "leaf":
        target = episode / "outside_target.md"
        target.write_bytes(b"must not be consumed through an alias")
        link = episode / "lab" / "lab_notes" / "alias.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        relative = "lab_notes/alias.md"
        is_directory = False
    else:
        target = episode / "outside_lab_notes"
        target.mkdir()
        (target / "result.md").write_bytes(b"must not cross an ancestor alias")
        link = episode / "lab" / "lab_notes"
        relative = "lab_notes/result.md"
        is_directory = True
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    before = _episode_tree_snapshot(episode)

    def forbidden_container_action(**_kwargs: Any) -> dict[str, Any]:
        pytest.fail("reparse lab input must fail before the container checkpoint driver")

    monkeypatch.setattr(module, "_research_episode_container_identity", forbidden_container_action)
    exit_code = module.main(
        [
            "research-episode",
            "checkpoint",
            "--root",
            str(episode),
            "--expected-head",
            started["head_checkpoint_sha256"],
            "--lab-relative",
            relative,
        ]
    )
    output = capsys.readouterr().out.strip().splitlines()
    assert exit_code == 2
    assert json.loads(output[-1])["reason_codes"] == ["RESEARCH_EPISODE_LAB_FILE_INVALID"]
    assert _episode_tree_snapshot(episode) == before


def test_unauthorized_lab_roots_and_hidden_outcome_isolation(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    for bad in (
        "shadow/ledger.json",
        "freeze/ticket.json",
        "outcome/reveal.json",
        "settlement/row.json",
        "../outside.txt",
        "auth/secret.json",
    ):
        with pytest.raises(module.XinaoError) as failure:
            module.research_episode_checkpoint(
                root=episode,
                expected_head_sha256=started["head_checkpoint_sha256"],
                progress_note="attack",
                lab_relative=bad,
                lab_bytes=b"x",
            )
        assert failure.value.reason_code in {
            "RESEARCH_EPISODE_UNAUTHORIZED_LEDGER_PATH",
            "RESEARCH_EPISODE_LAB_PATH_INVALID",
        }
    # ensure-pair must not create hidden outcome/settlement files under episode.
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    assert ready["outcome_written"] is False
    for forbidden in ("outcome", "settlement", "freeze", "shadow"):
        assert not (episode / forbidden).exists()
    # Container contract advertises forbidden mounts when dual host identity used.
    contract = module._research_episode_container_identity(
        verb="ensure-pair",
        episode_id=started["episode_id"],
        session_id=started["session_id"],
        generation=1,
        lab_root=episode / "lab",
        root=episode,
    )
    forbidden = set(contract.get("forbidden_mounts") or [])
    assert (
        "outcome_store" in forbidden
        or contract.get("driver") == "mock_host_side_until_sibling_container"
    )
    if contract.get("driver") == "dual_container_host":
        assert "outcome_store" in forbidden
        assert "shadow_ledger" in forbidden
        assert contract.get("temporal_leg_b") is False
        assert contract.get("daemon") is False


def test_self_scheduling_and_leg_b_flags_false_on_public_verbs(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    for payload in (started, ready):
        assert payload.get("next_task_created", False) is False
        assert payload.get("leg_b_scheduled", False) is False
        assert payload.get("successor_episode_created", False) is False
        assert payload.get("completion_claim_allowed") is False
    # Cancel must not schedule successor; must best-effort retire pair.
    cancelled = module.research_episode_cancel(root=episode)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["next_task_created"] is False
    assert cancelled["leg_b_scheduled"] is False
    assert cancelled["successor_episode_created"] is False
    assert cancelled["completion_claim_allowed"] is False
    assert "pair_retire" in cancelled
    # Resume after cancel is blocked.
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_resume(
            root=episode,
            expected_head_sha256=cancelled["head_checkpoint_sha256"],
        )
    assert failure.value.reason_code == "RESEARCH_EPISODE_CANCELLED"
    # ensure-pair after cancel is terminal.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_ensure_pair(
            root=episode,
            expected_head_sha256=cancelled["head_checkpoint_sha256"],
        )
    assert failure2.value.reason_code == "RESEARCH_EPISODE_TERMINAL"
    # Idempotent cancel.
    again = module.research_episode_cancel(root=episode)
    assert again["status"] == "CANCEL_IDEMPOTENT"


def test_cancel_resume_checkpoint_cas_chain(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    head1 = started["head_checkpoint_sha256"]
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=head1,
        progress_note="round-1 notes",
        mark_interrupted=True,
    )
    assert ckpt["status"] == "INTERRUPTED_CHECKPOINT"
    # Stale resume against old head.
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_resume(root=episode, expected_head_sha256=head1)
    assert failure.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    resumed = module.research_episode_resume(
        root=episode,
        expected_head_sha256=ckpt["head_checkpoint_sha256"],
        expected_session_id=started["session_id"],
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["exact_session_bound"] is True
    # Foreign session rejected.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_resume(
            root=episode,
            expected_head_sha256=resumed["head_checkpoint_sha256"],
            expected_session_id="xrsess_foreign",
        )
    assert failure2.value.reason_code == "RESEARCH_EPISODE_FOREIGN_SESSION"
    # C: root forbidden.
    with pytest.raises(module.XinaoError) as failure3:
        module.research_episode_start(root=Path(r"C:\xinao_episode_forbidden"), question="q")
    assert failure3.value.reason_code == "RESEARCH_EPISODE_ROOT_C_DRIVE_FORBIDDEN"


def test_fresh_process_ensure_pair_cli(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "XINAO_SKILL_STATE_ROOT": str(tmp_path / "state"),
        "XINAO_RESEARCHER_RUN_ROOT": str(tmp_path / "runs"),
        "XINAO_DUAL_CONTAINER_SYNTHETIC": "1",
        "XINAO_AUTH_HOST_PATH": str(tmp_path / "auth.json"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # State was prepared inside the loaded module fixture; re-point env to same tmp state.
    # The module fixture already wrote under monkeypatched XINAO_SKILL_STATE_ROOT.
    # Capture actual state root used by module.
    state_root = module._state_paths()["capability_root"].parent
    env["XINAO_SKILL_STATE_ROOT"] = str(state_root)
    auth = tmp_path / "auth.json"
    if not auth.is_file():
        auth.write_text("{}", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(RUNTIME_PATH),
            "research-episode",
            "ensure-pair",
            "--root",
            str(episode),
            "--expected-head",
            started["head_checkpoint_sha256"],
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    assert payload["completion_claim_allowed"] is False
    assert payload["next_task_created"] is False
    assert payload["leg_b_scheduled"] is False
    assert payload["successor_episode_created"] is False
    assert payload["outcome_written"] is False
    # Retire via fresh process.
    retired = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(RUNTIME_PATH),
            "research-episode",
            "retire-pair",
            "--root",
            str(episode),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )
    assert retired.returncode == 0, retired.stdout + retired.stderr
    retire_payload = json.loads(retired.stdout.strip().splitlines()[-1])
    assert retire_payload["next_task_created"] is False
    assert retire_payload["leg_b_scheduled"] is False
    assert retire_payload["successor_episode_created"] is False


def test_attach_run_without_pair_fails_closed(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    # attach-run without ensure-pair → lease missing (or synthetic live refused).
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_attach_run(
            root=episode,
            prompt="attempt without pair",
            expected_head_sha256=started["head_checkpoint_sha256"],
            plan_only=False,
        )
    assert failure.value.reason_code in {
        "DUAL_HOST_LEASE_MISSING",
        "DUAL_HOST_SYNTHETIC_LIVE_REFUSED",
        "RESEARCH_EPISODE_ATTACH_FAILED",
        "DUAL_CONTAINER_HOST_CONFIG_REQUIRED",
        "DUAL_CONTAINER_SEALED_IMAGES_REQUIRED",
    }
    ready = module.research_episode_ensure_pair(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_ALREADY_READY", "PAIR_STARTED"}
    # Synthetic dual host is for pair/CAS plumbing only; live attach still refuse synthetic
    # (no provider theater). Production live attach requires real dual containers.
    with pytest.raises(module.XinaoError) as failure2:
        module.research_episode_attach_run(
            root=episode,
            prompt="plan only multi-turn",
            expected_head_sha256=started["head_checkpoint_sha256"],
            max_turns=16,
            plan_only=True,
        )
    assert failure2.value.reason_code in {
        "DUAL_HOST_SYNTHETIC_LIVE_REFUSED",
        "RESEARCH_EPISODE_ATTACH_FAILED",
    }
    # Stale CAS on attach after checkpoint drift.
    ckpt = module.research_episode_checkpoint(
        root=episode,
        expected_head_sha256=started["head_checkpoint_sha256"],
        progress_note="post-pair note",
    )
    with pytest.raises(module.XinaoError) as failure3:
        module.research_episode_attach_run(
            root=episode,
            prompt="stale head",
            expected_head_sha256=started["head_checkpoint_sha256"],
            plan_only=True,
        )
    assert failure3.value.reason_code == "RESEARCH_EPISODE_STALE_HEAD"
    assert ckpt["completion_claim_allowed"] is False


def _load_dual_host_mod() -> Any:
    path = SKILL_ROOT / "scripts" / "dual_container_host.py"
    return _load("xinao_dual_host_wave124x_recovery", path)


def test_ensure_pair_tool_started_not_already_ready(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tool_started is intermediate: ensure must advance via start, not PAIR_ALREADY_READY."""
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    ready = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_STARTED"}
    host_mod = _load_dual_host_mod()
    host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:t",
            tool_image="tool:t",
            auth_host_path=tmp_path / "auth.json",
            episode_root=episode,
            synthetic=True,
        )
    )
    lease = host.load_lease()
    assert lease is not None
    lease["phase"] = "tool_started"
    host._save_lease(lease)
    again = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert again["status"] == "PAIR_STARTED"
    assert again["status"] != "PAIR_ALREADY_READY"
    final_lease = host.load_lease()
    assert final_lease is not None
    assert final_lease["phase"] == "running"


def test_ensure_pair_failed_retire_pending_recovers_then_recreates(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """failed_retire_pending must recover/retire (not blind start) then recreate."""
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    first = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert first["status"] in {"PAIR_READY", "PAIR_STARTED"}
    host_mod = _load_dual_host_mod()
    host = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:t",
            tool_image="tool:t",
            auth_host_path=tmp_path / "auth.json",
            episode_root=episode,
            synthetic=True,
        )
    )
    lease = host.load_lease()
    assert lease is not None
    old_tool = lease.get("tool_container_id")
    lease["phase"] = "failed_retire_pending"
    lease["failure_reason"] = "DUAL_HOST_TRANSPORT_START_FAILED"
    host._save_lease(lease)
    # Spy: start_pair must not be called while still failed_retire_pending.
    calls: list[str] = []
    original_start = host_mod.DualContainerHost.start_pair
    original_recover = host_mod.DualContainerHost.recover_or_retire_after_crash

    def wrapped_start(self: Any) -> Any:
        phase = (self.load_lease() or {}).get("phase")
        calls.append(f"start:{phase}")
        assert phase != "failed_retire_pending"
        return original_start(self)

    def wrapped_recover(self: Any) -> Any:
        calls.append(f"recover:{(self.load_lease() or {}).get('phase')}")
        return original_recover(self)

    monkeypatch.setattr(host_mod.DualContainerHost, "start_pair", wrapped_start)
    monkeypatch.setattr(
        host_mod.DualContainerHost, "recover_or_retire_after_crash", wrapped_recover
    )
    # research_episode_ensure_pair re-imports dual host via load; patch the module it loads.
    import sys

    sys.modules["xinao_dual_host_wave124x_recovery"] = host_mod

    # Ensure runtime uses our host_mod instance path: patch _research_episode_load_dual_host.
    def fake_load(root: Path) -> tuple[Any, Any]:
        cfg = host_mod.DualHostConfig(
            transport_image="transport:t",
            tool_image="tool:t",
            auth_host_path=tmp_path / "auth.json",
            episode_root=Path(root),
            synthetic=True,
        )
        return host_mod, host_mod.DualContainerHost(cfg)

    monkeypatch.setattr(module, "_research_episode_load_dual_host", fake_load)
    recovered = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert recovered["status"] == "PAIR_READY"
    assert any(c.startswith("recover:") for c in calls)
    assert not any(c == "start:failed_retire_pending" for c in calls)
    new_lease = host_mod.DualContainerHost(
        host_mod.DualHostConfig(
            transport_image="transport:t",
            tool_image="tool:t",
            auth_host_path=tmp_path / "auth.json",
            episode_root=episode,
            synthetic=True,
        )
    ).load_lease()
    assert new_lease is not None
    assert new_lease["phase"] == "running"
    assert new_lease["phase"] != "failed_retire_pending"
    assert old_tool is not None


def test_retire_recreate_preserves_provider_session_uuid(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disposable pair replacement must resume the same durable Grok session."""
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    first = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    first_inventory = json.loads((episode / "session_inventory.json").read_text("utf-8"))
    provider_session = first_inventory["grok_session_id"]

    retired = module.research_episode_retire_pair(root=episode)
    assert retired["status"] == "RETIRED"
    recreated = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    recreated_inventory = json.loads((episode / "session_inventory.json").read_text("utf-8"))

    assert recreated["status"] in {"PAIR_READY", "PAIR_STARTED"}
    assert recreated["episode_id"] == started["episode_id"]
    assert recreated["session_id"] == started["session_id"]
    assert recreated["cas_head_sha256"] == started["head_checkpoint_sha256"]
    assert recreated_inventory["episode_id"] == started["episode_id"]
    assert recreated_inventory["host_session_id"] == started["session_id"]
    assert recreated_inventory["grok_session_id"] == provider_session
    assert recreated_inventory["resume_mode"] == "resume"


@pytest.mark.parametrize(
    ("field", "invalid", "reason_code"),
    [
        ("episode_id", "xre_foreign", "RESEARCH_EPISODE_FOREIGN_EPISODE"),
        ("host_session_id", "xrsess_foreign", "RESEARCH_EPISODE_FOREIGN_SESSION"),
        (
            "grok_session_id",
            "not-a-provider-uuid",
            "RESEARCH_EPISODE_PROVIDER_SESSION_NOT_UUID",
        ),
    ],
)
def test_retire_recreate_rejects_invalid_prior_session_inventory(
    module: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: str,
    reason_code: str,
) -> None:
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    module.research_episode_retire_pair(root=episode)
    inventory_path = episode / "session_inventory.json"
    inventory = json.loads(inventory_path.read_text("utf-8"))
    inventory[field] = invalid
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
        )
    assert failure.value.reason_code == reason_code


def test_ensure_pair_already_ready_dual_host_error_maps_xinao(
    module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """running already-ready path must map DualHostError → XinaoError reason (no swallow)."""
    _mod, episode, started, _manifest = _prepare_episode(module, tmp_path, monkeypatch)
    ready = module.research_episode_ensure_pair(
        root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
    )
    assert ready["status"] in {"PAIR_READY", "PAIR_STARTED", "PAIR_ALREADY_READY"}
    host_mod = _load_dual_host_mod()

    def boom(self: Any, **kwargs: Any) -> dict[str, Any]:
        raise host_mod.DualHostError("DUAL_HOST_CONTAINER_STOPPED", "transport")

    monkeypatch.setattr(host_mod.DualContainerHost, "require_live_pair_ready", boom)

    def fake_load(root: Path) -> tuple[Any, Any]:
        cfg = host_mod.DualHostConfig(
            transport_image="transport:t",
            tool_image="tool:t",
            auth_host_path=tmp_path / "auth.json",
            episode_root=Path(root),
            synthetic=True,
        )
        return host_mod, host_mod.DualContainerHost(cfg)

    monkeypatch.setattr(module, "_research_episode_load_dual_host", fake_load)
    with pytest.raises(module.XinaoError) as failure:
        module.research_episode_ensure_pair(
            root=episode, expected_head_sha256=started["head_checkpoint_sha256"]
        )
    assert failure.value.reason_code == "DUAL_HOST_CONTAINER_STOPPED"
    assert "transport" in failure.value.detail
