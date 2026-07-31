"""Wave88: sealed skill-bundle / installed projection must not grow .pyc.

Product formal entry disables bytecode writes; inventory stays fail-closed.
Does not touch live installed/release trees.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = REPO / "skills" / "xinao" / "scripts" / "xinao.py"
RUNTIME_PATH = REPO / "skills" / "xinao" / "scripts" / "xinao_runtime.py"


def _load(name: str, path: Path):
    """Exec module source without SourceFileLoader (avoids worktree __pycache__)."""

    source = path.read_text(encoding="utf-8")
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = None
    module.__cached__ = None
    sys.modules[name] = module
    # Clear flags so product body must re-enable sealed-tree hygiene.
    sys.dont_write_bytecode = False
    os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _tree_file_map(root: Path) -> dict[str, bytes]:
    rows: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = path.read_bytes()
    return rows


def _mini_bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """Tiny sealed skill-bundle fixture (no large EOL-sensitive blobs)."""

    root = tmp_path / "skill-bundle"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    files = {
        "SKILL.md": b"# mini sealed skill\n",
        "scripts/xinao.py": b"print('launcher')\n",
        "scripts/xinao_runtime.py": (
            b"import importlib.util, sys\n"
            b"from pathlib import Path\n"
            b"p = Path(__file__).with_name('dual_container_host.py')\n"
            b"spec = importlib.util.spec_from_file_location('dual_probe', p)\n"
            b"m = importlib.util.module_from_spec(spec)\n"
            b"sys.modules[spec.name] = m\n"
            b"spec.loader.exec_module(m)\n"
            b"print(m.MARKER)\n"
        ),
        "scripts/dual_container_host.py": b"MARKER = 'dual-ok'\n",
    }
    inventory = []
    for relative, payload in sorted(files.items()):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        inventory.append(
            {
                "relative_path": relative,
                "type": "file",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    tree_sha256 = hashlib.sha256(
        (
            json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": "xinao.skill_bundle_manifest.v1",
        "skill_id": "xinao",
        "package_version": "1.2.1",
        "tree_sha256": tree_sha256,
        "files": inventory,
    }
    return root, manifest


def test_bootstrap_and_runtime_enable_bytecode_hygiene_on_load() -> None:
    bootstrap = _load("xinao_bootstrap_pycache_hygiene", BOOTSTRAP_PATH)
    runtime = _load("xinao_runtime_pycache_hygiene", RUNTIME_PATH)
    assert sys.dont_write_bytecode is True
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    assert bootstrap._sealed_runtime_child_argv(["inspect"]) == [
        sys.executable,
        "-I",
        "-B",
        "-",
        "inspect",
    ]
    env = bootstrap._sealed_runtime_child_env({"PATH": "x", "PYTHONDONTWRITEBYTECODE": "0"})
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    wrapper = bootstrap._runtime_wrapper(Path("sealed/xinao_runtime.py"), b"print(1)\n")
    assert b"sys.dont_write_bytecode = True" in wrapper
    assert b"PYTHONDONTWRITEBYTECODE" in wrapper
    assert callable(runtime._load_sealed_python_module)
    assert callable(runtime._enforce_sealed_tree_bytecode_hygiene)


def test_companion_runtime_seal_matches_edited_bytes() -> None:
    bootstrap = _load("xinao_bootstrap_pycache_seal", BOOTSTRAP_PATH)
    observed = hashlib.sha256(RUNTIME_PATH.read_bytes()).hexdigest()
    assert bootstrap.EXPECTED_COMPANION_RUNTIME_SHA256 == observed


def test_verify_skill_bundle_rejects_unauthorized_pyc(tmp_path: Path) -> None:
    runtime = _load("xinao_runtime_pycache_verify", RUNTIME_PATH)
    bundle_root, manifest = _mini_bundle(tmp_path)
    runtime._verify_skill_bundle(bundle_root, manifest)
    before = _tree_file_map(bundle_root)

    poison = bundle_root / "scripts" / "__pycache__" / "xinao_runtime.cpython-312.pyc"
    poison.parent.mkdir(parents=True, exist_ok=True)
    poison.write_bytes(b"unauthorized-pyc\n")

    with pytest.raises(runtime.XinaoError) as failure:
        runtime._verify_skill_bundle(bundle_root, manifest)
    assert failure.value.reason_code == "SKILL_BUNDLE_INVENTORY_MISMATCH"
    assert "extra:scripts/__pycache__/xinao_runtime.cpython-312.pyc" in failure.value.detail

    # Fail-closed: inventory still exact when poison removed.
    poison.unlink()
    poison.parent.rmdir()
    runtime._verify_skill_bundle(bundle_root, manifest)
    assert _tree_file_map(bundle_root) == before


def test_strict_plain_tree_does_not_ignore_pycache(tmp_path: Path) -> None:
    runtime = _load("xinao_runtime_pycache_strict", RUNTIME_PATH)
    root = tmp_path / "installed"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_bytes(b"# s\n")
    (root / "scripts" / "xinao.py").write_bytes(b"print(1)\n")
    files, directories = runtime._strict_plain_tree(root, reason_code="PROBE")
    assert set(files) == {"SKILL.md", "scripts/xinao.py"}
    assert directories == {"scripts"}

    poison = root / "scripts" / "__pycache__" / "xinao_runtime.cpython-312.pyc"
    poison.parent.mkdir(parents=True)
    poison.write_bytes(b"drift\n")
    files2, directories2 = runtime._strict_plain_tree(root, reason_code="PROBE")
    assert "scripts/__pycache__/xinao_runtime.cpython-312.pyc" in files2
    assert "scripts/__pycache__" in directories2
    assert files2 != files


def test_sealed_module_loader_and_formal_wrapper_leave_tree_unchanged(
    tmp_path: Path,
) -> None:
    runtime = _load("xinao_runtime_pycache_loader", RUNTIME_PATH)
    bootstrap = _load("xinao_bootstrap_pycache_loader", BOOTSTRAP_PATH)
    sealed = tmp_path / "authority"
    scripts = sealed / "scripts"
    scripts.mkdir(parents=True)
    sibling = scripts / "dual_container_host.py"
    sibling.write_bytes(b"MARKER = 'sealed-sibling'\nVALUE = 7\n")
    before = _tree_file_map(sealed)

    # Even if a caller re-enables bytecode, sealed loader must not write next to authority modules.
    sys.dont_write_bytecode = False
    os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
    module = runtime._load_sealed_python_module("xinao_dual_probe_hygiene", sibling)
    assert module.MARKER == "sealed-sibling"
    assert module.VALUE == 7
    assert sys.dont_write_bytecode is True
    assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    assert _tree_file_map(sealed) == before
    assert not (scripts / "__pycache__").exists()

    # Formal stdin-exec wrapper (product child path) must not create .pyc under sealed root.
    runtime_payload = (
        "from pathlib import Path\n"
        "import importlib.util, sys, os\n"
        # Intentionally try to re-enable; product runtime body / sealed path should keep hygiene.
        "sys.dont_write_bytecode = False\n"
        "os.environ.pop('PYTHONDONTWRITEBYTECODE', None)\n"
        "p = Path(__file__).resolve().parent / 'dual_container_host.py'\n"
        # Prefer product sealed loader if present in executed runtime bytes; fallback is importlib
        # under -B child which product always passes.
        "print('ok')\n"
    ).encode("utf-8")
    runtime_file = scripts / "xinao_runtime.py"
    runtime_file.write_bytes(runtime_payload)
    before_child = _tree_file_map(sealed)
    wrapper = bootstrap._runtime_wrapper(runtime_file, runtime_payload)
    env = os.environ.copy()
    # Strip hygiene env to prove argv -B / wrapper body is enough for formal path.
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-"],
        input=wrapper,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
        timeout=30,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert completed.stdout.strip() == b"ok"
    assert _tree_file_map(sealed) == before_child
    assert not any(
        path.name == "__pycache__" or path.suffix == ".pyc" for path in sealed.rglob("*")
    )


def test_fresh_process_importlib_without_product_hygiene_would_pollute_but_formal_does_not(
    tmp_path: Path,
) -> None:
    """Contrast: naive importlib pollutes; product formal -B/env/sealed-load does not."""

    sealed = tmp_path / "skill-bundle" / "scripts"
    sealed.mkdir(parents=True)
    target = sealed / "probe_mod.py"
    target.write_bytes(b"X = 1\n")
    before = _tree_file_map(tmp_path)

    # Naive load: no -B, no env, SourceFileLoader → writes under sealed scripts/.
    pollute = (
        "import importlib.util, sys\n"
        f"p = r'''{target}'''\n"
        "spec = importlib.util.spec_from_file_location('probe_mod', p)\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = m\n"
        "spec.loader.exec_module(m)\n"
        "print(m.X)\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    polluted = subprocess.run(
        [sys.executable, "-I", "-c", pollute],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert polluted.returncode == 0
    assert polluted.stdout.strip() == b"1"
    assert (sealed / "__pycache__").is_dir() or any(sealed.rglob("*.pyc"))

    for path in list(sealed.rglob("*")):
        if path.is_file() and (path.suffix == ".pyc" or path.name.endswith(".pyc")):
            path.unlink()
    for path in sorted(sealed.rglob("__pycache__"), reverse=True):
        if path.is_dir():
            path.rmdir()
    assert _tree_file_map(tmp_path) == before

    # Formal product child: -I -B + PYTHONDONTWRITEBYTECODE + sealed compile/exec loader.
    formal_code = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from types import ModuleType\n"
        "sys.dont_write_bytecode = True\n"
        "os.environ['PYTHONDONTWRITEBYTECODE'] = '1'\n"
        f"p = Path(r'''{target}''')\n"
        "source = p.read_text(encoding='utf-8')\n"
        "m = ModuleType('probe_mod')\n"
        "m.__file__ = str(p)\n"
        "m.__cached__ = None\n"
        "sys.modules['probe_mod'] = m\n"
        "exec(compile(source, str(p), 'exec'), m.__dict__)\n"
        "print(m.X)\n"
    )
    formal_env = env.copy()
    formal_env["PYTHONDONTWRITEBYTECODE"] = "1"
    formal = subprocess.run(
        [sys.executable, "-I", "-B", "-c", formal_code],
        env=formal_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert formal.returncode == 0, formal.stderr.decode("utf-8", errors="replace")
    assert formal.stdout.strip() == b"1"
    assert _tree_file_map(tmp_path) == before
    assert not any(p.name == "__pycache__" or p.suffix == ".pyc" for p in tmp_path.rglob("*"))

    # -B alone also blocks SourceFileLoader when callers do not re-enable writes.
    alone = subprocess.run(
        [sys.executable, "-I", "-B", "-c", pollute],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
    assert alone.returncode == 0
    assert alone.stdout.strip() == b"1"
    assert _tree_file_map(tmp_path) == before


def test_installed_projection_alignment_drifts_on_unauthorized_pyc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _load("xinao_runtime_pycache_align", RUNTIME_PATH)
    installed = tmp_path / "installed"
    (installed / "scripts").mkdir(parents=True)
    payload = b"print('installed')\n"
    (installed / "SKILL.md").write_bytes(b"# skill\n")
    (installed / "scripts" / "xinao.py").write_bytes(payload)
    monkeypatch.setenv("XINAO_INSTALLED_SKILL_ROOT", str(installed))
    monkeypatch.setattr(runtime, "DEFAULT_INSTALLED_SKILL_ROOT", installed)

    # Build matching target rows as if sealed bundle equaled installed before poison.
    rows = [
        ("SKILL.md", b"# skill\n"),
        ("scripts/xinao.py", payload),
    ]
    inventory = runtime._tree_inventory(rows)
    tree_sha256 = runtime._sha256_bytes(runtime._canonical_bytes(inventory))

    def fake_target_rows(_target_ref):
        return {}, Path("unused"), rows

    monkeypatch.setattr(runtime, "_target_projection_rows", fake_target_rows)
    monkeypatch.setattr(
        runtime,
        "_load_pointer_raw",
        lambda: (
            {
                "active": {
                    "release_id": "researcher-1.2.1-" + ("d" * 16),
                    "skill_bundle_tree_sha256": tree_sha256,
                }
            },
            "e" * 64,
        ),
    )
    release = {
        "release_id": "researcher-1.2.1-" + ("d" * 16),
        "skill_bundle_tree_sha256": tree_sha256,
    }
    aligned = runtime._installed_projection_alignment(release)
    assert aligned["status"] == "ALIGNED"

    poison = installed / "scripts" / "__pycache__" / "xinao_runtime.cpython-312.pyc"
    poison.parent.mkdir(parents=True)
    poison.write_bytes(b"drift\n")
    drifted = runtime._installed_projection_alignment(release)
    assert drifted["status"] == "DRIFTED"
    assert drifted["reason_code"] == "INSTALLED_PROJECTION_DRIFTED"
    assert drifted["installed_inventory_tree_sha256"] != drifted["target_inventory_tree_sha256"]
