"""Pinned Promptfoo 0.121.18 offline runner via Docker create/inspect/start/cleanup.

Host process never executes Promptfoo. Container is pre-start inspected for
NetworkMode=none, ReadonlyRootfs, CapDrop=ALL, no-new-privileges, PidsLimit,
non-root user, exact image digest, and allowlisted mounts only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from . import SYNTHETIC_LABEL
from .canonical import raw_bytes_sha256_file, write_json
from .objects import expected_case_set_identity_sha256, expected_public_case_ids
from .security_model import scan_forbidden_public_payload

EXPECTED_VERSION = "0.121.18"
PINNED_IMAGE = (
    "ghcr.io/promptfoo/promptfoo@sha256:"
    "6b9076def7ebe27c64d72432bd27e5019a348c92ccb47a71b774caa5b61c04ca"
)
PINNED_DIGEST = "sha256:6b9076def7ebe27c64d72432bd27e5019a348c92ccb47a71b774caa5b61c04ca"
PLATFORM_MANIFEST_SHA256 = "26abf6d74b7f469c4874a0363ab5ed65ef9d871ae6971876af4e8ee30eb26da8"
EXPECTED_NODE = "v24.17.0"
OWNER_LABEL = "io.xinao.g4.hidden_capability_seam"
PIDS_LIMIT = 128
CONTAINER_PYTHON = "/usr/bin/python3"
TRUSTED_PROVIDER_ID = "python:/adapter/promptfoo_subject_adapter.py"
# Complete supported top-level Promptfoo config schema for this seam.
SUPPORTED_PROMPTFOO_TOP_LEVEL_KEYS = frozenset(
    {
        "description",
        "providers",
        "prompts",
        "tests",
        "evaluateOptions",
        "commandLineOptions",
    }
)
# Fields that can introduce executable providers / overrides; always reject.
FORBIDDEN_PROVIDER_BEARING_KEYS = frozenset(
    {
        "defaultTest",
        "scenarios",
        "extensions",
        "provider",
        "env",
        "sharing",
        "tags",
        "outputPath",
        "writeLatestResults",
    }
)

# Explicit non-secret env we set (never API keys, never host inheritance)
ALLOWED_ENV = {
    "PROMPTFOO_DISABLE_TELEMETRY": "1",
    "PROMPTFOO_DISABLE_UPDATE": "1",
    "PROMPTFOO_CACHE_PATH": "/state/cache",
    "PROMPTFOO_CONFIG_DIR": "/state/config_dir",
    "HOME": "/state/home",
    "NODE_ENV": "production",
}

# Exact non-secret Config.Env values from the digest-pinned image, plus the
# explicit overrides above. Docker inspect exposes this pre-start configuration;
# no wildcard or key-only admission is needed.
PINNED_IMAGE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "NODE_VERSION": "24.17.0",
    "YARN_VERSION": "1.22.22",
    "API_PORT": "3000",
    "HOST": "0.0.0.0",
    "PROMPTFOO_SELF_HOSTED": "1",
    "PROMPTFOO_RUNNING_IN_DOCKER": "1",
    "PROMPTFOO_OFFICIAL_DOCKER_IMAGE": "1",
}
ADMITTED_ENV_VALUES = {**PINNED_IMAGE_ENV, **ALLOWED_ENV}
ADMITTED_ENV_KEYS = frozenset(ADMITTED_ENV_VALUES)

# Offline subject execution mounts only bounded output/state. Config, cases, and
# adapter are copied into the stopped container's private layer (no host bind
# mounts and no writable aliases under /state).
EXPECTED_MOUNT_PLAN = (
    {"dest": "/output", "mode": "rw"},
    {"dest": "/state", "mode": "rw"},
)
# Destinations that would re-introduce host-bound executable inputs.
FORBIDDEN_EXECUTABLE_INPUT_MOUNTS = frozenset({"/work", "/adapter", "/snapshot"})
PRIVATE_CONTAINER_CONFIG_PATH = "/work/promptfooconfig.yaml"
PRIVATE_CONTAINER_CASES_PATH = "/work/public_cases.json"
PRIVATE_CONTAINER_ADAPTER_PATH = "/adapter/promptfoo_subject_adapter.py"
PROMPTFOO_OUTPUT_BASENAME = "promptfoo_results.json"

TRANSIENT_FILE_NAMES = frozenset(
    {
        "promptfoo.db",
        "promptfoo.db-shm",
        "promptfoo.db-wal",
        "promptfoo.yaml",
        "evalLastWritten",
    }
)
CACHE_DIR_NAMES = frozenset({".ruff_cache", ".pytest_cache", "__pycache__", "cache"})


def _run(
    argv: list[str],
    *,
    timeout: int = 120,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
        shell=False,
    )


def _lexical_absolute_path(path: Path | str) -> Path:
    """Absolute lexical path without following symlinks or junctions."""
    return Path(os.path.abspath(os.path.normpath(os.fspath(path))))


def _norm_win_path(path: Path | str) -> str:
    """Windows-safe lexical path for equality/prefix checks (never resolves links)."""
    s = os.path.normcase(str(_lexical_absolute_path(path))).replace("/", "\\")
    while s.endswith("\\") and len(s) > 3:
        s = s[:-1]
    return s


def _paths_equal(a: Path | str, b: Path | str) -> bool:
    return _norm_win_path(a) == _norm_win_path(b)


def _is_under_or_equal(child: Path | str, root: Path | str) -> bool:
    c = _norm_win_path(child)
    r = _norm_win_path(root)
    if c == r:
        return True
    sep = "\\"
    return c.startswith(r + sep)


def _paths_intersect(a: Path | str, b: Path | str) -> bool:
    """True when either lexical path contains the other (including equality)."""
    return _is_under_or_equal(a, b) or _is_under_or_equal(b, a)


def _is_reparse_point(path: Path) -> bool:
    """Reject symlink/junction/reparse-point host mount sources."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    # Windows: reparse points / junctions via stat file attribute
    try:
        import ctypes
        from ctypes import wintypes

        GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW  # type: ignore[attr-defined]
        GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
        GetFileAttributesW.restype = wintypes.DWORD
        INVALID = 0xFFFFFFFF
        FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
        attrs = GetFileAttributesW(str(path))
        if attrs == INVALID:
            return False
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:  # noqa: BLE001
        return False


def _has_reparse_ancestor(path: Path) -> bool:
    """True if path or any existing ancestor is a reparse/symlink/junction."""
    cur = _lexical_absolute_path(path)
    seen: set[str] = set()
    while True:
        key = _norm_win_path(cur)
        if key in seen:
            break
        seen.add(key)
        if cur.exists() and _is_reparse_point(cur):
            return True
        parent = cur.parent
        if _paths_equal(parent, cur):
            break
        cur = parent
    return False


def normalize_host_mount_source(path: Path) -> dict[str, Any]:
    lexical = _lexical_absolute_path(path)
    if _has_reparse_ancestor(lexical):
        return {
            "ok": False,
            "reason": "mount_source_reparse_or_symlink_ancestor",
            "path": str(lexical),
        }
    try:
        p = lexical.resolve(strict=True)
    except OSError as exc:
        return {
            "ok": False,
            "reason": "mount_source_resolve_failed",
            "path": str(path),
            "error_class": type(exc).__name__,
        }
    if not p.exists():
        return {"ok": False, "reason": "mount_source_missing", "path": str(p)}
    return {"ok": True, "path": str(p), "normalized": _norm_win_path(p)}


def _normalize_planned_host_path(path: Path) -> dict[str, Any]:
    """Resolve a possibly not-yet-created path after rejecting reparse ancestry."""
    lexical = _lexical_absolute_path(path)
    if _has_reparse_ancestor(lexical):
        return {
            "ok": False,
            "reason": "mount_source_reparse_or_symlink_ancestor",
            "path": str(lexical),
        }
    try:
        resolved = lexical.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return {
            "ok": False,
            "reason": "mount_source_resolve_failed",
            "path": str(path),
            "error_class": type(exc).__name__,
        }
    return {"ok": True, "path": str(resolved), "normalized": _norm_win_path(resolved)}


def _normalize_denied_host_path(path: Path) -> dict[str, Any]:
    """Normalize a denied root while retaining Windows device-namespace paths."""
    raw = str(path).replace("/", "\\").lower()
    if raw.startswith("\\\\.\\pipe\\"):
        lexical = _lexical_absolute_path(path)
        return {"ok": True, "path": str(lexical), "normalized": _norm_win_path(lexical)}
    return _normalize_planned_host_path(path)


def default_denied_roots(
    *,
    vault_root: Path | None = None,
    evaluator_root: Path | None = None,
    op_root: Path | None = None,
) -> list[Path]:
    """Sensitive trees that must not be mounted and must not be contained by a mount.

    vault.parent is not listed as a denied *tree* (that would false-deny siblings);
    ancestor-of-vault denial is handled by intersection against the vault path itself.
    """
    denied: list[Path] = []
    if vault_root is not None:
        denied.append(_lexical_absolute_path(vault_root))
    if evaluator_root is not None:
        denied.append(_lexical_absolute_path(evaluator_root))
    home = Path.home()
    denied.extend(
        [
            home / ".ssh",
            home / ".aws",
            home / ".docker",
            home / "AppData" / "Roaming",
            home / "AppData" / "Local",
        ]
    )
    denied.extend(
        [
            Path(r"\\.\pipe\docker_engine"),
            Path("/var/run/docker.sock"),
            Path("/run/docker.sock"),
        ]
    )
    if op_root is not None:
        denied.append(_lexical_absolute_path(Path(op_root) / "ledgers"))
        denied.append(_lexical_absolute_path(Path(op_root) / "objects"))
        denied.append(_lexical_absolute_path(Path(op_root) / "vault"))
        denied.append(_lexical_absolute_path(Path(op_root) / "evaluator"))
    out: list[Path] = []
    seen: set[str] = set()
    for d in denied:
        try:
            key = _norm_win_path(d)
        except Exception:  # noqa: BLE001
            continue
        if key not in seen:
            seen.add(key)
            out.append(Path(d))
    return out


def validate_mount_boundary(
    *,
    source: Path,
    dest: str,
    mode: str,
    allowed_roots: list[Path],
    denied_roots: list[Path],
) -> dict[str, Any]:
    """Every mount source must be under an allowed root and disjoint from denied roots.

    Disjoint means: source is not the denied tree, not under it, and not an ancestor
    that would contain it (parent-of-vault mounts fail). Sibling paths under a shared
    parent remain allowed when they themselves are allowlisted.
    """
    chk = normalize_host_mount_source(source)
    if not chk.get("ok"):
        return chk
    src = Path(chk["path"])
    src_n = _norm_win_path(src)

    normalized_allowed: list[Path] = []
    for root in allowed_roots:
        root_check = normalize_host_mount_source(Path(root))
        if not root_check.get("ok"):
            return {
                "ok": False,
                "reason": "allowed_mount_root_invalid",
                "detail": root_check,
            }
        normalized_allowed.append(Path(root_check["path"]))
    under_allowed = any(_is_under_or_equal(src, root) for root in normalized_allowed)
    if not under_allowed:
        return {
            "ok": False,
            "reason": "mount_source_outside_allowed_roots",
            "source": src_n,
            "dest": dest,
        }

    for denied in denied_roots:
        denied_check = _normalize_denied_host_path(Path(denied))
        if not denied_check.get("ok"):
            return {
                "ok": False,
                "reason": "denied_mount_root_invalid",
                "detail": denied_check,
            }
        d = Path(denied_check["path"])
        # source is denied root or nested inside denied tree
        if _is_under_or_equal(src, d):
            return {
                "ok": False,
                "reason": "mount_source_intersects_denied_root",
                "source": src_n,
                "denied": _norm_win_path(d),
                "dest": dest,
            }
        # source is a parent/ancestor that would contain the denied tree
        if not _paths_equal(src, d) and _is_under_or_equal(d, src):
            return {
                "ok": False,
                "reason": "mount_source_is_ancestor_of_denied_root",
                "source": src_n,
                "denied": _norm_win_path(d),
                "dest": dest,
            }

    expected = {m["dest"]: m["mode"] for m in EXPECTED_MOUNT_PLAN}
    if dest not in expected:
        return {"ok": False, "reason": "unexpected_mount_destination", "dest": dest}
    if mode != expected[dest]:
        return {
            "ok": False,
            "reason": "unexpected_mount_mode",
            "dest": dest,
            "mode": mode,
            "expected_mode": expected[dest],
        }
    if dest in {"/var/run/docker.sock", "/run/docker.sock"} or "docker.sock" in dest:
        return {"ok": False, "reason": "docker_socket_mount_forbidden", "dest": dest}
    return {
        "ok": True,
        "source": src_n,
        "dest": dest,
        "mode": mode,
    }


def _preflight_promptfoo_host_paths(
    *,
    config_path: Path,
    state_root: Path,
    output_root: Path,
    adapter_src: Path,
    op_root: Path,
    allowed_roots: list[Path],
    denied_roots: list[Path],
) -> dict[str, Any]:
    """Admit every caller-controlled host path before any mkdir/rmtree/write.

    Planned mount roots may not exist yet, so this pass is lexical plus existing-
    ancestor reparse checking. A second strict pass runs after the two admitted
    directories are created and before any executable staging or Docker boundary.
    """
    config_path = _lexical_absolute_path(config_path)
    config_dir = config_path.parent
    cases_path = config_dir / "public_cases.json"
    state_root = _lexical_absolute_path(state_root)
    output_root = _lexical_absolute_path(output_root)
    adapter_src = _lexical_absolute_path(adapter_src)
    op_root = _lexical_absolute_path(op_root)

    op_check = normalize_host_mount_source(op_root)
    if not op_check.get("ok"):
        return {
            "ok": False,
            "reason": "operation_root_invalid",
            "detail": op_check,
        }
    op_root = Path(op_check["path"])
    trusted_mount_root = op_root / "promptfoo"
    package_root = op_root.parent.parent
    trusted_adapter_root = package_root / "adapters"

    resolved_inputs: dict[str, Path] = {}
    for label, path in (
        ("config", config_path),
        ("cases", cases_path),
        ("adapter", adapter_src),
    ):
        check = normalize_host_mount_source(path)
        if not check.get("ok"):
            return {
                "ok": False,
                "reason": f"{label}_source_invalid",
                "detail": check,
            }
        resolved_inputs[label] = Path(check["path"])
    config_path = resolved_inputs["config"]
    config_dir = config_path.parent
    cases_path = resolved_inputs["cases"]
    adapter_src = resolved_inputs["adapter"]

    resolved_mounts: dict[str, Path] = {}
    for label, path in (("state", state_root), ("output", output_root)):
        check = _normalize_planned_host_path(path)
        if not check.get("ok"):
            return {
                "ok": False,
                "reason": f"{label}_source_invalid",
                "detail": check,
            }
        resolved_mounts[label] = Path(check["path"])
    state_root = resolved_mounts["state"]
    output_root = resolved_mounts["output"]
    if not _is_under_or_equal(config_dir, trusted_mount_root):
        return {"ok": False, "reason": "config_source_outside_operation_promptfoo_root"}
    if not _is_under_or_equal(adapter_src, trusted_adapter_root):
        return {
            "ok": False,
            "reason": "adapter_source_outside_trusted_package_adapter_root",
        }

    normalized_allowed: list[Path] = []
    for root in allowed_roots:
        check = _normalize_planned_host_path(Path(root))
        if not check.get("ok"):
            return {
                "ok": False,
                "reason": "allowed_mount_root_invalid",
                "detail": check,
            }
        normalized_allowed.append(Path(check["path"]))
    expected_allowed = {
        _norm_win_path(config_dir),
        _norm_win_path(state_root),
        _norm_win_path(output_root),
    }
    observed_allowed = {_norm_win_path(root) for root in normalized_allowed}
    if len(normalized_allowed) != 3 or observed_allowed != expected_allowed:
        return {
            "ok": False,
            "reason": "allowed_roots_not_exact_planned_sources",
        }
    for root in normalized_allowed:
        if _has_reparse_ancestor(root):
            return {
                "ok": False,
                "reason": "allowed_mount_root_reparse_or_symlink_ancestor",
                "path": _norm_win_path(root),
            }
        if not _is_under_or_equal(root, trusted_mount_root):
            return {
                "ok": False,
                "reason": "allowed_root_outside_operation_promptfoo_root",
                "path": _norm_win_path(root),
            }

    normalized_denied: list[Path] = []
    for root in denied_roots:
        check = _normalize_denied_host_path(Path(root))
        if not check.get("ok"):
            return {
                "ok": False,
                "reason": "denied_mount_root_invalid",
                "detail": check,
            }
        normalized_denied.append(Path(check["path"]))

    executable_sources = (config_dir, adapter_src)
    mount_sources = (output_root, state_root)
    if _paths_intersect(output_root, state_root):
        return {"ok": False, "reason": "mount_sources_overlap"}
    for mount_source in mount_sources:
        if _has_reparse_ancestor(mount_source):
            return {
                "ok": False,
                "reason": "mount_source_reparse_or_symlink_ancestor",
                "path": _norm_win_path(mount_source),
            }
        if not any(_is_under_or_equal(mount_source, allowed) for allowed in normalized_allowed):
            return {
                "ok": False,
                "reason": "mount_source_outside_allowed_roots",
                "path": _norm_win_path(mount_source),
            }
        for executable_source in executable_sources:
            if _paths_intersect(mount_source, executable_source):
                return {
                    "ok": False,
                    "reason": "mount_source_overlaps_executable_source",
                }
        for denied in normalized_denied:
            if _paths_intersect(mount_source, denied):
                return {
                    "ok": False,
                    "reason": "mount_source_intersects_denied_root",
                    "path": _norm_win_path(mount_source),
                }

    snapshot_stage = trusted_mount_root / ".private_exec_snapshot"
    legacy_adapter_alias = state_root / "adapter_mount"
    for label, path in (
        ("private_snapshot", snapshot_stage),
        ("legacy_adapter_alias", legacy_adapter_alias),
    ):
        if _has_reparse_ancestor(path):
            return {
                "ok": False,
                "reason": f"{label}_reparse_or_symlink_ancestor",
            }

    return {
        "ok": True,
        "op_root": str(op_root),
        "trusted_mount_root": str(trusted_mount_root),
        "normalized_allowed": [str(root) for root in normalized_allowed],
        "config_path": str(config_path),
        "cases_path": str(cases_path),
        "adapter_src": str(adapter_src),
        "state_root": str(state_root),
        "output_root": str(output_root),
    }


def attest_promptfoo_version_in_container() -> dict[str, Any]:
    """Parse Promptfoo version from actual execution in the pinned image."""
    name = f"xinao-g4hcs-ver-{uuid.uuid4().hex[:12]}"
    container_id: str | None = None
    try:
        create_argv = [
            "docker",
            "create",
            "--name",
            name,
            "--label",
            f"{OWNER_LABEL}.role=version_attest",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "32",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=33554432",
            # Bounded non-secret env so CLI can start; never host inheritance
            "--env",
            "HOME=/tmp",
            "--env",
            "PROMPTFOO_CONFIG_DIR=/tmp",
            "--env",
            "PROMPTFOO_CACHE_PATH=/tmp",
            "--env",
            "PROMPTFOO_DISABLE_TELEMETRY=1",
            "--env",
            "PROMPTFOO_DISABLE_UPDATE=1",
            "--env",
            "NODE_ENV=production",
            PINNED_IMAGE,
            "sh",
            "-c",
            # Prefer CLI --version; also read package.json as runtime-produced corroboration
            "promptfoo --version; "
            "node -e \"const p=require('/app/package.json');"
            "process.stdout.write('pkg='+p.version+'\\n')\"",
        ]
        create = _run(create_argv, timeout=60)
        if create.returncode != 0:
            return {
                "ok": False,
                "reason": "version_container_create_failed",
                "stderr_tail": (create.stderr or "")[-400:],
            }
        raw_create_stdout = create.stdout or ""
        container_id = raw_create_stdout or "<missing-container-id>"
        parsed_container_id = _container_id_from_create_stdout(raw_create_stdout)
        if parsed_container_id is None:
            raise RuntimeError("version_create_stdout_not_exact_canonical")
        container_id = parsed_container_id
        run = _run(["docker", "start", "-a", container_id], timeout=60)
        text = ((run.stdout or "") + "\n" + (run.stderr or "")).strip()
        # Never inherit host env; only parse version token / package fact
        observed = None
        for line in text.splitlines():
            line = line.strip()
            if line == EXPECTED_VERSION or line.startswith(EXPECTED_VERSION):
                observed = EXPECTED_VERSION
                break
            if line.startswith("pkg=") and line.split("=", 1)[-1].strip() == EXPECTED_VERSION:
                observed = EXPECTED_VERSION
                break
        if observed is None:
            for token in text.replace(",", " ").split():
                if token == EXPECTED_VERSION or "0.121.18" in token:
                    observed = EXPECTED_VERSION
                    break
        if observed != EXPECTED_VERSION:
            return {
                "ok": False,
                "reason": "promptfoo_version_not_observed",
                "stdout_tail": (run.stdout or "")[-300:],
                "stderr_tail": (run.stderr or "")[-300:],
                "returncode": run.returncode,
            }
        return {
            "ok": True,
            "version": observed,
            "expected_version": EXPECTED_VERSION,
            "attestation": "in_container_promptfoo_version",
            "returncode": run.returncode,
        }
    finally:
        require_terminal_container_cleanup(_docker_rm_exact(name, container_id))


def verify_promptfoo_identity() -> dict[str, Any]:
    """Fail closed if local image digest/version differs. Never pull.

    Version is attested from actual in-container execution, not merely the
    configured constant.
    """
    try:
        insp = _run(
            ["docker", "image", "inspect", PINNED_IMAGE],
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": f"docker_unavailable:{type(exc).__name__}"}
    if insp.returncode != 0:
        return {
            "ok": False,
            "reason": "pinned_image_missing_or_inspect_failed",
            "stderr_tail": (insp.stderr or "")[-500:],
        }
    data = json.loads(insp.stdout)[0]
    repo_digests = data.get("RepoDigests") or []
    image_id = str(data.get("Id") or "")
    digest_ok = any(str(d).rsplit("@", 1)[-1] == PINNED_DIGEST for d in repo_digests)
    labels = (data.get("Config") or {}).get("Labels") or {}
    if not digest_ok:
        return {
            "ok": False,
            "reason": "image_digest_drift",
            "image_id": image_id,
            "repo_digests": repo_digests,
            "expected": PINNED_DIGEST,
        }
    user = (data.get("Config") or {}).get("User") or ""
    if not user or user in {"0", "root"}:
        return {"ok": False, "reason": "image_user_is_root_or_empty", "user": user}
    env = (data.get("Config") or {}).get("Env") or []
    node_ok = any(str(e).startswith("NODE_VERSION=24.17.0") for e in env)
    version_attest = attest_promptfoo_version_in_container()
    if not version_attest.get("ok"):
        return {
            "ok": False,
            "reason": "promptfoo_version_attestation_failed",
            "version_attest": version_attest,
            "image_id": image_id,
        }
    return {
        "ok": True,
        "version": version_attest["version"],
        "expected_version": EXPECTED_VERSION,
        "version_attestation": version_attest,
        "image_ref": PINNED_IMAGE,
        "image_id": image_id,
        "image_platform_manifest_sha256": PLATFORM_MANIFEST_SHA256,
        "repo_digests": repo_digests,
        "node_version": EXPECTED_NODE if node_ok else "unknown",
        "image_user": user,
        "digest_ok": True,
        "labels_sample": {k: labels.get(k) for k in list(labels)[:5]},
        "reason": None,
    }


def _yaml_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_canonical_promptfoo_config_yaml(
    *,
    provider_id: str = TRUSTED_PROVIDER_ID,
    python_executable: str = CONTAINER_PYTHON,
) -> str:
    """Exact trusted YAML bytes shape used by the builder and digest binding."""
    py_exec = CONTAINER_PYTHON  # always in-container python; ignore caller override
    if provider_id != TRUSTED_PROVIDER_ID:
        raise ValueError("canonical_config_requires_trusted_provider_id")
    yaml_lines = [
        "description: 'g4_hidden_capability_seam synthetic offline subject enumeration (NOT capability evidence)'",
        "providers:",
        "  - id: " + _yaml_single_quote(TRUSTED_PROVIDER_ID),
        "    config:",
        "      pythonExecutable: " + _yaml_single_quote(py_exec),
        "prompts:",
        "  - '{{public_prompt}}'",
        "tests: file://public_cases.json",
        "evaluateOptions:",
        "  cache: false",
        "  maxConcurrency: 1",
        "commandLineOptions:",
        "  cache: false",
        "",
    ]
    return "\n".join(yaml_lines)


def _provider_id_from_entry(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        raw = entry.get("id")
        if raw is None:
            raw = entry.get("provider")
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            nested = raw.get("id")
            if isinstance(nested, str):
                return nested.strip()
    return None


def _is_forbidden_executable_provider(provider_id: str) -> bool:
    pid = provider_id.strip()
    if not pid:
        return True
    if pid == TRUSTED_PROVIDER_ID:
        return False
    lower = pid.lower().replace("\\", "/")
    # Any executable alternative under /work or non-adapter python path is forbidden.
    if lower.startswith("python:/work/") or "/work/" in lower:
        return True
    if lower.startswith("python:") and lower != TRUSTED_PROVIDER_ID.lower():
        return True
    if lower.startswith("file://") or lower.startswith("exec:"):
        return True
    return True


def validate_promptfoo_config_providers(
    config_path: Path,
    *,
    expected_config_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail-closed complete-schema validation of executable provider surfaces.

    Substring presence of the trusted descriptor is never sufficient. Exactly one
    executable provider is admitted, and it must be the digest-bound adapter path.
    """
    config_path = _lexical_absolute_path(config_path)
    config_dir = config_path.parent
    local_adapter = config_dir / "promptfoo_subject_adapter.py"
    if local_adapter.exists():
        return {
            "ok": False,
            "reason": "config_local_adapter_shadow_forbidden",
            "path": str(local_adapter),
        }
    # Any other executable .py under /work is an unbound alternative surface.
    work_py: list[str] = []
    try:
        for child in config_dir.iterdir():
            if child.is_file() and child.suffix.lower() == ".py":
                work_py.append(child.name)
    except OSError as exc:
        return {
            "ok": False,
            "reason": "config_dir_unreadable",
            "error_class": type(exc).__name__,
        }
    if work_py:
        return {
            "ok": False,
            "reason": "untrusted_work_python_provider_surface_present",
            "files": sorted(work_py),
        }

    try:
        raw = config_path.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "reason": "promptfoo_config_unreadable",
            "error_class": type(exc).__name__,
        }
    from .canonical import sha256_hex

    config_sha256 = sha256_hex(raw)
    if expected_config_sha256 is not None and config_sha256 != expected_config_sha256:
        return {
            "ok": False,
            "reason": "promptfoo_config_digest_mismatch",
            "expected": expected_config_sha256,
            "observed": config_sha256,
        }

    try:
        import yaml  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "yaml_parser_unavailable",
            "error_class": type(exc).__name__,
        }
    try:
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "promptfoo_config_yaml_parse_failed",
            "error_class": type(exc).__name__,
        }
    if not isinstance(parsed, dict):
        return {"ok": False, "reason": "promptfoo_config_root_not_mapping"}

    unknown = sorted(set(parsed) - SUPPORTED_PROMPTFOO_TOP_LEVEL_KEYS)
    if unknown:
        return {
            "ok": False,
            "reason": "promptfoo_config_unsupported_top_level_keys",
            "keys": unknown,
        }
    forbidden_present = sorted(set(parsed) & FORBIDDEN_PROVIDER_BEARING_KEYS)
    if forbidden_present:
        return {
            "ok": False,
            "reason": "promptfoo_config_provider_bearing_keys_forbidden",
            "keys": forbidden_present,
        }

    providers = parsed.get("providers")
    if not isinstance(providers, list) or len(providers) != 1:
        return {
            "ok": False,
            "reason": "promptfoo_config_requires_exactly_one_provider",
            "count": 0 if not isinstance(providers, list) else len(providers),
        }
    provider_entry = providers[0]
    provider_id = _provider_id_from_entry(provider_entry)
    if provider_id is None:
        return {"ok": False, "reason": "promptfoo_provider_id_missing_or_malformed"}
    if provider_id != TRUSTED_PROVIDER_ID:
        return {
            "ok": False,
            "reason": "promptfoo_provider_not_trusted_adapter_descriptor",
            "observed": provider_id,
            "expected": TRUSTED_PROVIDER_ID,
        }
    if not isinstance(provider_entry, dict):
        return {"ok": False, "reason": "promptfoo_provider_entry_must_be_mapping"}
    allowed_provider_keys = {"id", "config"}
    extra_provider_keys = sorted(set(provider_entry) - allowed_provider_keys)
    if extra_provider_keys:
        return {
            "ok": False,
            "reason": "promptfoo_provider_entry_unsupported_keys",
            "keys": extra_provider_keys,
        }
    cfg = provider_entry.get("config")
    if not isinstance(cfg, dict):
        return {"ok": False, "reason": "promptfoo_provider_config_missing"}
    if set(cfg) != {"pythonExecutable"}:
        return {
            "ok": False,
            "reason": "promptfoo_provider_config_unsupported_keys",
            "keys": sorted(set(cfg)),
        }
    if cfg.get("pythonExecutable") != CONTAINER_PYTHON:
        return {
            "ok": False,
            "reason": "promptfoo_provider_python_executable_not_container_pin",
            "observed": cfg.get("pythonExecutable"),
        }

    # Reject per-test / nested provider overrides inside tests file reference only.
    tests = parsed.get("tests")
    if not isinstance(tests, str) or not tests.startswith("file://"):
        return {
            "ok": False,
            "reason": "promptfoo_tests_must_be_file_uri",
            "observed_type": type(tests).__name__,
        }
    # Inert trusted-string fields elsewhere must not admit any other executable path.
    # (They are already ignored for execution; still require exact provider binding.)
    if _is_forbidden_executable_provider(provider_id):
        return {"ok": False, "reason": "promptfoo_provider_forbidden"}

    prompts = parsed.get("prompts")
    if prompts != ["{{public_prompt}}"]:
        return {"ok": False, "reason": "promptfoo_prompts_schema_mismatch"}
    eval_opts = parsed.get("evaluateOptions")
    if not isinstance(eval_opts, dict) or eval_opts.get("cache") is not False:
        return {"ok": False, "reason": "promptfoo_cache_must_be_false"}
    if eval_opts.get("maxConcurrency") != 1:
        return {"ok": False, "reason": "promptfoo_max_concurrency_must_be_1"}
    cli_opts = parsed.get("commandLineOptions")
    if not isinstance(cli_opts, dict) or cli_opts.get("cache") is not False:
        return {"ok": False, "reason": "promptfoo_cli_cache_must_be_false"}

    # The reusable runner admits one exact owner-generated configuration.  A
    # semantic subset check alone leaves future/nested Promptfoo surfaces open
    # to interpretation drift, so comments, aliases, extra options, and
    # alternate encodings are all rejected even when the parsed provider looks
    # trusted.
    canonical_raw = render_canonical_promptfoo_config_yaml().encode("utf-8")
    canonical_sha256 = sha256_hex(canonical_raw)
    if raw != canonical_raw:
        return {
            "ok": False,
            "reason": "promptfoo_config_not_exact_canonical_bytes",
            "expected_sha256": canonical_sha256,
            "observed_sha256": config_sha256,
        }

    return {
        "ok": True,
        "provider_id": TRUSTED_PROVIDER_ID,
        "config_sha256": config_sha256,
        "config_size": len(raw),
        "providers_count": 1,
        "work_python_surface_absent": True,
        "config_local_shadow_absent": True,
        "schema": "exact_supported_promptfoo_config_v1",
    }


def validate_promptfoo_public_cases(
    cases_path: Path,
    *,
    expected_case_ids: list[str] | None = None,
    expected_cases_sha256: str | None = None,
) -> dict[str, Any]:
    """Reject every provider-bearing or ambiguous Promptfoo test body.

    Promptfoo can consume executable/provider-bearing fields from test data as
    well as the top-level YAML.  The seam therefore supports one deliberately
    tiny public-case schema only: each row is exactly ``{"vars": ...}``, and
    its vars mapping contains only the three public synthetic fields emitted by
    the owner builder.
    """
    cases_path = _lexical_absolute_path(cases_path)
    try:
        raw = cases_path.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "reason": "promptfoo_public_cases_unreadable",
            "error_class": type(exc).__name__,
        }
    from .canonical import sha256_hex

    cases_sha256 = sha256_hex(raw)
    if expected_cases_sha256 is not None and cases_sha256 != expected_cases_sha256:
        return {
            "ok": False,
            "reason": "promptfoo_public_cases_digest_mismatch",
            "expected": expected_cases_sha256,
            "observed": cases_sha256,
        }
    try:
        rows = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "reason": "promptfoo_public_cases_parse_failed",
            "error_class": type(exc).__name__,
        }
    if not isinstance(rows, list) or not rows:
        return {
            "ok": False,
            "reason": "promptfoo_public_cases_must_be_nonempty_list",
        }

    observed_ids: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"vars"}:
            return {
                "ok": False,
                "reason": "promptfoo_public_case_row_schema_mismatch",
                "index": index,
                "keys": sorted(row) if isinstance(row, dict) else [],
            }
        vars_obj = row.get("vars")
        expected_vars = {"public_case_id", "public_prompt", "commitment_sha256"}
        if not isinstance(vars_obj, dict) or set(vars_obj) != expected_vars:
            return {
                "ok": False,
                "reason": "promptfoo_public_case_vars_schema_mismatch",
                "index": index,
                "keys": sorted(vars_obj) if isinstance(vars_obj, dict) else [],
            }
        case_id = vars_obj.get("public_case_id")
        public_prompt = vars_obj.get("public_prompt")
        commitment = vars_obj.get("commitment_sha256")
        if not isinstance(case_id, str) or not case_id:
            return {
                "ok": False,
                "reason": "promptfoo_public_case_id_invalid",
                "index": index,
            }
        if not isinstance(public_prompt, str) or not public_prompt:
            return {
                "ok": False,
                "reason": "promptfoo_public_prompt_invalid",
                "index": index,
            }
        if (
            not isinstance(commitment, str)
            or len(commitment) != 64
            or any(char not in "0123456789abcdef" for char in commitment)
        ):
            return {
                "ok": False,
                "reason": "promptfoo_public_commitment_invalid",
                "index": index,
            }
        observed_ids.append(case_id)

    if len(set(observed_ids)) != len(observed_ids):
        return {
            "ok": False,
            "reason": "promptfoo_public_case_ids_not_unique",
        }
    if expected_case_ids is not None and observed_ids != list(expected_case_ids):
        return {
            "ok": False,
            "reason": "promptfoo_public_case_ids_mismatch",
            "expected": list(expected_case_ids),
            "observed": observed_ids,
        }
    return {
        "ok": True,
        "schema": "exact_supported_promptfoo_public_cases_v1",
        "cases_sha256": cases_sha256,
        "case_count": len(rows),
        "case_ids": observed_ids,
        "provider_bearing_fields_absent": True,
    }


def build_promptfoo_config(
    *,
    config_dir: Path,
    adapter_path: Path,
    cases_path: Path,
    python_executable: str = CONTAINER_PYTHON,
) -> dict[str, Any]:
    config_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            {
                "vars": {
                    "public_case_id": row["public_case_id"],
                    "public_prompt": row["public_prompt"],
                    "commitment_sha256": row["commitment_sha256"],
                }
            }
        )
    cases_json_path = config_dir / "public_cases.json"
    write_json(cases_json_path, cases)
    cases_sha256, _ = raw_bytes_sha256_file(cases_json_path)
    cases_validation = validate_promptfoo_public_cases(
        cases_json_path,
        expected_case_ids=[str(row["vars"]["public_case_id"]) for row in cases],
        expected_cases_sha256=cases_sha256,
    )
    if not cases_validation.get("ok"):
        raise ValueError(
            f"promptfoo_canonical_public_cases_self_validation_failed:{cases_validation}"
        )

    # The executable provider lives only on the dedicated read-only /adapter
    # mount. Remove any stale config-local copy so /work cannot shadow it.
    local_adapter = config_dir / "promptfoo_subject_adapter.py"
    local_adapter.unlink(missing_ok=True)
    for stale in config_dir.glob("*.py"):
        stale.unlink(missing_ok=True)

    py_exec = CONTAINER_PYTHON  # always in-container python
    yaml_text = render_canonical_promptfoo_config_yaml(
        provider_id=TRUSTED_PROVIDER_ID,
        python_executable=py_exec,
    )
    config_path = config_dir / "promptfooconfig.yaml"
    config_path.write_text(yaml_text, encoding="utf-8", newline="\n")
    from .canonical import sha256_hex

    config_sha256 = sha256_hex(yaml_text.encode("utf-8"))

    config_public = {
        "description": "g4_hidden_capability_seam synthetic offline subject enumeration (NOT capability evidence)",
        "providers": [{"id": TRUSTED_PROVIDER_ID, "config": {"pythonExecutable": py_exec}}],
        "prompts": ["{{public_prompt}}"],
        "tests": "file://public_cases.json",
        "evaluateOptions": {"cache": False, "maxConcurrency": 1},
        "commandLineOptions": {"cache": False},
    }
    leaks = scan_forbidden_public_payload(config_public)
    critical = [
        p
        for p in leaks
        if any(
            x in p.lower()
            for x in (
                "vault",
                "seed",
                "truth",
                "answer",
                "family_identity",
                "rejection_label",
                "scorer_feature",
                "scorer_credential",
            )
        )
    ]
    if critical:
        raise ValueError(f"promptfoo_config_forbidden:{critical}")

    validated = validate_promptfoo_config_providers(
        config_path, expected_config_sha256=config_sha256
    )
    if not validated.get("ok"):
        raise ValueError(f"promptfoo_canonical_config_self_validation_failed:{validated}")

    return {
        "ok": True,
        "config_path": str(config_path),
        "cases_json": str(cases_json_path),
        "local_adapter": str(local_adapter),
        "cache_enabled": False,
        "scoring_enabled": False,
        "label": SYNTHETIC_LABEL,
        "config_public": config_public,
        "config_sha256": config_sha256,
        "cases_sha256": cases_sha256,
        "provider_id": TRUSTED_PROVIDER_ID,
        "provider_validation": validated,
        "cases_validation": cases_validation,
    }


def _inspect_container(container: str) -> dict[str, Any]:
    proc = _run(["docker", "inspect", container], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"docker_inspect_failed:{proc.stderr[-300:]}")
    return json.loads(proc.stdout)[0]


def _inspect_image(image: str) -> dict[str, Any]:
    proc = _run(["docker", "image", "inspect", image], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"docker_image_inspect_failed:{proc.stderr[-300:]}")
    rows = json.loads(proc.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError("docker_image_inspect_shape_invalid")
    return rows[0]


def _verify_pre_start(
    insp: dict[str, Any],
    *,
    expected_mounts: list[dict[str, str]] | None = None,
    allowed_mount_targets: set[str] | None = None,
    expected_image_ref: str = PINNED_IMAGE,
    expected_image_id: str | None = PINNED_DIGEST,
) -> dict[str, Any]:
    """Exact mount dest/mode and admitted env-key set inspection (no secret values)."""
    host = insp.get("HostConfig") or {}
    config = insp.get("Config") or {}
    problems: list[str] = []

    if host.get("NetworkMode") != "none":
        problems.append(f"network_mode:{host.get('NetworkMode')}")
    if host.get("ReadonlyRootfs") is not True:
        problems.append("readonly_rootfs_false")
    if host.get("Privileged") is not False:
        problems.append("privileged_not_false")
    cap_drop = host.get("CapDrop") or []
    if "ALL" not in [str(x).upper() for x in cap_drop]:
        problems.append(f"cap_drop:{cap_drop}")
    security = host.get("SecurityOpt") or []
    if not any(str(s).startswith("no-new-privileges") for s in security):
        problems.append(f"security_opt:{security}")
    pids = host.get("PidsLimit")
    if pids is None or int(pids) <= 0 or int(pids) > 256:
        problems.append(f"pids_limit:{pids}")
    user = config.get("User") or ""
    if not user or user in {"0", "root"}:
        problems.append(f"user:{user}")
    image = str(config.get("Image") or "")
    image_id = str(insp.get("Image") or "")
    if image != expected_image_ref:
        problems.append("image_ref_not_expected")
    if expected_image_id is not None and image_id != expected_image_id:
        problems.append("image_id_not_expected")
    tmpfs = host.get("Tmpfs") or {}
    tmp_spec = str(tmpfs.get("/tmp") or "")
    tmp_tokens = {token.strip().lower() for token in tmp_spec.split(",") if token.strip()}
    required_tmp_tokens = {"rw", "noexec", "nosuid", "nodev", "size=268435456"}
    if not required_tmp_tokens.issubset(tmp_tokens):
        problems.append("tmpfs_policy_mismatch")

    mounts = insp.get("Mounts") or []
    mount_targets: set[str] = set()
    observed_mounts: list[dict[str, str]] = []
    expected = expected_mounts or [
        {"dest": m["dest"], "mode": m["mode"], "source_norm": ""} for m in EXPECTED_MOUNT_PLAN
    ]
    expected_by_dest = {m["dest"]: m for m in expected}
    allowed_targets = allowed_mount_targets or set(expected_by_dest.keys())

    for m in mounts:
        dest = str(m.get("Destination") or m.get("Target") or "")
        src = str(m.get("Source") or "")
        # Docker reports RW as boolean
        rw = m.get("RW")
        mode = (
            "rw"
            if rw is True
            else "ro"
            if rw is False
            else ("rw" if m.get("Mode") in (None, "", "rw", "z") else "ro")
        )
        if rw is False or str(m.get("Mode") or "").startswith("ro"):
            mode = "ro"
        if rw is True:
            mode = "rw"
        mount_targets.add(dest)
        src_norm = _norm_win_path(src) if src else ""
        observed_mounts.append({"dest": dest, "mode": mode, "source_norm": src_norm})

        # Defense in depth substring checks (not the security boundary)
        src_l = src.lower().replace("\\", "/")
        dest_l = dest.lower()
        for bad in (
            "vault",
            "docker.sock",
            "/var/run/docker",
            "evaluator",
            ".git",
            "credentials",
            "appdata",
        ):
            if bad in src_l or bad in dest_l:
                problems.append(f"forbidden_mount_substr:{dest}")

        if dest.startswith("/tmp"):
            continue
        if dest not in allowed_targets:
            problems.append(f"non_allowlisted_mount:{dest}")
            continue
        exp = expected_by_dest.get(dest)
        if exp is None:
            problems.append(f"unexpected_mount_destination:{dest}")
            continue
        if exp.get("mode") and mode != exp["mode"]:
            problems.append(f"mount_mode_mismatch:{dest}:{mode}!={exp['mode']}")
        if exp.get("source_norm") and src_norm != exp["source_norm"]:
            problems.append(f"mount_source_mismatch:{dest}")

    required = set(expected_by_dest.keys())
    missing = required - mount_targets
    if missing:
        problems.append(f"missing_mounts:{sorted(missing)}")
    if len(observed_mounts) != len(expected_by_dest):
        problems.append("mount_count_mismatch")

    # Exact admitted environment-key and value set. Evidence exposes key names
    # and drift names only; values are compared in memory and never recorded.
    env_list = config.get("Env") or []
    env_keys: list[str] = []
    unexpected_env: list[str] = []
    secretish: list[str] = []
    env_value_drift: list[str] = []
    observed_env: dict[str, str] = {}
    for item in env_list:
        if "=" not in str(item):
            continue
        k, _, value = str(item).partition("=")
        env_keys.append(k)
        observed_env[k] = value
        up = k.upper()
        if (
            up.endswith("_API_KEY")
            or "SECRET" in up
            or "PASSWORD" in up
            or ("TOKEN" in up and "PROMPTFOO" not in up)
        ):
            secretish.append(k)
        if k not in ADMITTED_ENV_KEYS:
            unexpected_env.append(k)
    missing_required_env = sorted(set(ADMITTED_ENV_VALUES) - set(env_keys))
    for key, expected_value in ADMITTED_ENV_VALUES.items():
        if key in observed_env and observed_env[key] != expected_value:
            env_value_drift.append(key)

    return {
        "ok": (
            len(problems) == 0
            and not secretish
            and not unexpected_env
            and not missing_required_env
            and not env_value_drift
        ),
        "problems": problems,
        "secretish_env_keys": secretish,
        "unexpected_env_keys": unexpected_env,
        "missing_required_env_keys": missing_required_env,
        "env_value_drift_keys": env_value_drift,
        "network_mode": host.get("NetworkMode"),
        "readonly_rootfs": host.get("ReadonlyRootfs"),
        "cap_drop": cap_drop,
        "security_opt": security,
        "pids_limit": pids,
        "user": user,
        "image": image,
        "tmpfs_targets": sorted(tmpfs),
        "mount_targets": sorted(mount_targets),
        "observed_mounts": observed_mounts,
        "env_keys_only": sorted(env_keys),
        "admitted_env_keys": sorted(ADMITTED_ENV_KEYS),
    }


def parse_promptfoo_results(
    output_path: Path,
    *,
    expected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Require exactly the expected unique public case IDs; reject incomplete/cached/error rows."""
    expected = list(expected_ids or expected_public_case_ids())
    expected_set = set(expected)
    case_set_id = expected_case_set_identity_sha256()
    if not output_path.exists():
        return {
            "ok": False,
            "reason": "promptfoo_output_missing",
            "expected_count": len(expected),
            "case_set_identity_sha256": case_set_id,
        }
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "promptfoo_output_parse_drift",
            "error_class": type(exc).__name__,
            "case_set_identity_sha256": case_set_id,
        }

    results = data.get("results") if isinstance(data, dict) else data
    rows: list[Any]
    if isinstance(results, dict):
        rows = results.get("results") or results.get("table") or []
        if not rows and "results" in results and isinstance(results["results"], list):
            rows = results["results"]
    elif isinstance(results, list):
        rows = results
    else:
        return {
            "ok": False,
            "reason": "promptfoo_output_parse_drift",
            "case_set_identity_sha256": case_set_id,
        }

    if not rows:
        return {
            "ok": False,
            "reason": "zero_case_rows",
            "observed_count": 0,
            "expected_count": len(expected),
            "case_set_identity_sha256": case_set_id,
        }

    observed_ids: list[str] = []
    problems: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"malformed_row:{idx}")
            continue
        # public case id locations in Promptfoo JSON vary by version
        vars_obj = row.get("vars") if isinstance(row.get("vars"), dict) else {}
        cid = vars_obj.get("public_case_id") or row.get("public_case_id")
        if not cid and isinstance(row.get("testCase"), dict):
            tc_vars = row["testCase"].get("vars") or {}
            if isinstance(tc_vars, dict):
                cid = tc_vars.get("public_case_id")
        if not cid and isinstance(row.get("metadata"), dict):
            cid = row["metadata"].get("public_case_id")
        if not cid:
            for key in ("testIdx", "testIndex"):
                if key in row and isinstance(row[key], int) and 0 <= row[key] < len(expected):
                    cid = expected[row[key]]
                    break
        if not cid:
            problems.append(f"missing_case_id_row:{idx}")
            continue
        cid = str(cid)
        observed_ids.append(cid)
        if cid not in expected_set:
            problems.append(f"unexpected_row:{cid}")
        # cached rows fail closed (top-level or response.cached)
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        if row.get("cached") is True or row.get("fromCache") is True or resp.get("cached") is True:
            problems.append(f"cached_row:{cid}")
        err = row.get("error")
        fr = row.get("failureReason")
        # failureReason 0 / missing is success in Promptfoo v3
        fr_bad = False
        if isinstance(fr, int) and fr != 0:
            fr_bad = True
        elif isinstance(fr, str) and fr not in {"", "0"}:
            fr_bad = True
        elif fr not in (None, 0, "0", False, "") and not isinstance(fr, (int, str)):
            fr_bad = True
        if err or fr_bad:
            problems.append(f"row_error:{cid}")
        if row.get("success") is False:
            problems.append(f"row_success_false:{cid}")

    if len(observed_ids) != len(set(observed_ids)):
        problems.append("duplicate_rows")
    missing = sorted(expected_set - set(observed_ids))
    if missing:
        problems.append(f"missing_rows:{missing}")
    if len(observed_ids) != len(expected):
        problems.append(f"count_mismatch:observed={len(observed_ids)}:expected={len(expected)}")

    return {
        "ok": len(problems) == 0 and set(observed_ids) == expected_set,
        "problems": problems,
        "observed_count": len(observed_ids),
        "expected_count": len(expected),
        "observed_ids": sorted(set(observed_ids)),
        "expected_ids": expected,
        "case_set_identity_sha256": case_set_id,
        "unique_count": len(set(observed_ids)),
    }


def _safe_cleanup_run(argv: list[str], *, timeout: int) -> dict[str, Any]:
    """Run one cleanup probe without preventing later independent cleanup legs."""
    try:
        proc = _run(argv, timeout=timeout)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr_tail": (proc.stderr or "")[-400:],
            "error_class": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "returncode": None,
            "stdout": "",
            "stderr_tail": "",
            "error_class": type(exc).__name__,
        }


def _is_canonical_container_id(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[0-9a-f]{64}", value))


def _container_id_from_create_stdout(stdout: str | None) -> str | None:
    """Accept exactly one lowercase full ID followed by one line terminator."""
    if stdout is None:
        return None
    match = re.fullmatch(r"([0-9a-f]{64})(?:\r\n|\n)", stdout)
    return match.group(1) if match else None


def _docker_rm_exact(name: str, container_id: str | None) -> dict[str, Any]:
    """Remove the exact owned container and prove absence from a full inventory."""
    evidence: dict[str, Any] = {"name": name, "container_id": container_id}
    container_id_canonical_full = container_id is None or _is_canonical_container_id(container_id)
    evidence["container_id_canonical_full"] = container_id_canonical_full
    removal_returncodes: list[dict[str, Any]] = []
    for identity in [container_id, name] if container_id else [name]:
        if not identity:
            continue
        removed = _safe_cleanup_run(["docker", "rm", "-f", identity], timeout=60)
        removal_returncodes.append(
            {
                "identity": identity,
                "returncode": removed["returncode"],
                "error_class": removed["error_class"],
            }
        )
    # Inspect failures are diagnostic only: daemon/auth/transport failures are
    # not equivalent to Docker's object-not-found state.
    insp = _safe_cleanup_run(["docker", "inspect", name], timeout=30)
    evidence["inspect_after_rm_returncode"] = insp["returncode"]
    evidence["inspect_after_rm_error_class"] = insp["error_class"]
    if container_id:
        insp2 = _safe_cleanup_run(["docker", "inspect", container_id], timeout=30)
        evidence["id_inspect_after_rm_returncode"] = insp2["returncode"]
        evidence["id_inspect_after_rm_error_class"] = insp2["error_class"]

    # Successful, unfiltered, non-truncated enumeration is the terminal proof.
    # Checking both the captured ID and original name also catches rename races.
    ps = _safe_cleanup_run(
        [
            "docker",
            "container",
            "ls",
            "-a",
            "--no-trunc",
            "--format",
            "{{.ID}}|{{.Names}}",
        ],
        timeout=30,
    )
    records: list[tuple[str, str]] = []
    inventory_parse_ok = True
    if ps["returncode"] == 0 and ps["error_class"] is None:
        for line in str(ps["stdout"]).splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r"([0-9a-f]{64})\|([^|\r\n]+)", line)
            if match is None:
                inventory_parse_ok = False
                break
            records.append((match.group(1), match.group(2)))
    else:
        inventory_parse_ok = False
    inventory_complete = bool(
        ps["returncode"] == 0 and ps["error_class"] is None and inventory_parse_ok
    )
    exact_name_absent = inventory_complete and all(
        observed_name != name for _, observed_name in records
    )
    exact_id_absent = bool(
        inventory_complete
        and container_id_canonical_full
        and (container_id is None or all(observed_id != container_id for observed_id, _ in records))
    )
    evidence["inventory_returncode"] = ps["returncode"]
    evidence["inventory_error_class"] = ps["error_class"]
    evidence["inventory_complete"] = inventory_complete
    evidence["inventory_record_count"] = len(records) if inventory_complete else None
    evidence["exact_name_absent"] = exact_name_absent
    evidence["exact_id_absent"] = exact_id_absent
    # Backward-compatible field names now derive only from complete inventory.
    evidence["absent"] = exact_name_absent
    evidence["id_absent"] = exact_id_absent
    evidence["removal_returncodes"] = removal_returncodes
    evidence["ok"] = bool(
        container_id_canonical_full and inventory_complete and exact_name_absent and exact_id_absent
    )
    return evidence


def _docker_rmi_exact(image_id: str) -> dict[str, Any]:
    """Remove one owned image ID and prove absence from a full image inventory."""
    rmi = _safe_cleanup_run(["docker", "rmi", "-f", image_id], timeout=60)
    inspect_img = _safe_cleanup_run(["docker", "image", "inspect", image_id], timeout=30)
    inventory = _safe_cleanup_run(
        ["docker", "image", "ls", "-a", "--no-trunc", "--quiet"],
        timeout=30,
    )
    observed_ids: list[str] = []
    inventory_parse_ok = True
    if inventory["returncode"] == 0 and inventory["error_class"] is None:
        for line in str(inventory["stdout"]).splitlines():
            observed = line.strip().casefold()
            if not observed:
                continue
            if re.fullmatch(r"sha256:[0-9a-f]{64}", observed) is None:
                inventory_parse_ok = False
                break
            observed_ids.append(observed)
    else:
        inventory_parse_ok = False
    inventory_complete = bool(
        inventory["returncode"] == 0 and inventory["error_class"] is None and inventory_parse_ok
    )
    absent = inventory_complete and image_id.casefold() not in set(observed_ids)
    return {
        "image": image_id,
        "rmi_returncode": rmi["returncode"],
        "rmi_error_class": rmi["error_class"],
        "inspect_returncode": inspect_img["returncode"],
        "inspect_error_class": inspect_img["error_class"],
        "inventory_returncode": inventory["returncode"],
        "inventory_error_class": inventory["error_class"],
        "inventory_complete": inventory_complete,
        "inventory_record_count": len(observed_ids) if inventory_complete else None,
        "absent": absent,
        "ok": absent,
    }


def require_terminal_container_cleanup(cleanup: dict[str, Any]) -> None:
    """Raise so an otherwise successful return cannot hide cleanup failure."""
    if cleanup.get("ok") is not True:
        raise RuntimeError("owned_container_cleanup_not_proven")


def _require_expected_bindings(
    *,
    expected_config_sha256: str | None,
    expected_cases_sha256: str | None,
    expected_case_ids: list[str] | None,
    expected_adapter_sha256: str | None,
) -> dict[str, Any]:
    """Mandatory builder-to-run digest and case-id bindings at the reusable boundary."""
    missing: list[str] = []
    if not isinstance(expected_config_sha256, str) or not expected_config_sha256.strip():
        missing.append("expected_config_sha256")
    elif len(expected_config_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in expected_config_sha256
    ):
        return {
            "ok": False,
            "reason": "expected_config_sha256_invalid",
            "missing": missing,
        }
    if not isinstance(expected_cases_sha256, str) or not expected_cases_sha256.strip():
        missing.append("expected_cases_sha256")
    elif len(expected_cases_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in expected_cases_sha256
    ):
        return {
            "ok": False,
            "reason": "expected_cases_sha256_invalid",
            "missing": missing,
        }
    if not isinstance(expected_adapter_sha256, str) or not expected_adapter_sha256.strip():
        missing.append("expected_adapter_sha256")
    elif len(expected_adapter_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in expected_adapter_sha256
    ):
        return {
            "ok": False,
            "reason": "expected_adapter_sha256_invalid",
            "missing": missing,
        }
    if expected_case_ids is None:
        missing.append("expected_case_ids")
    elif not isinstance(expected_case_ids, list) or not expected_case_ids:
        return {
            "ok": False,
            "reason": "expected_case_ids_missing_or_empty",
            "missing": missing,
        }
    elif any(not isinstance(x, str) or not x.strip() for x in expected_case_ids):
        return {
            "ok": False,
            "reason": "expected_case_ids_blank_entry",
            "missing": missing,
        }
    if missing:
        return {
            "ok": False,
            "reason": "expected_bindings_mandatory_missing",
            "missing": missing,
        }
    return {
        "ok": True,
        "expected_config_sha256": expected_config_sha256,
        "expected_cases_sha256": expected_cases_sha256,
        "expected_adapter_sha256": expected_adapter_sha256,
        "expected_case_ids": list(expected_case_ids or []),
    }


def _remove_private_snapshot_stage(path: Path) -> dict[str, Any]:
    """Remove the exact package-owned host staging directory and prove absence."""
    error_class: str | None = None
    try:
        if path.exists():
            shutil.rmtree(path)
    except Exception as exc:  # noqa: BLE001
        error_class = type(exc).__name__
    try:
        absent = not path.exists()
    except OSError as exc:
        absent = False
        error_class = error_class or type(exc).__name__
    return {
        "path_name": path.name,
        "absent": absent,
        "ok": absent,
        "error_class": error_class,
    }


def _docker_cp_file(
    *,
    container_id: str,
    host_path: Path,
    container_path: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Copy already-validated host snapshot bytes into a stopped owned container.

    Re-hashes the host path immediately before docker cp. A host swap before copy
    causes digest mismatch; a host swap after copy cannot affect private bytes.
    Uses a tar stream so intermediate container directories are created without a
    host bind mount for executable inputs.
    """
    import io
    import tarfile

    from .canonical import sha256_hex

    try:
        raw = host_path.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "reason": "snapshot_host_unreadable_before_copy",
            "error_class": type(exc).__name__,
            "container_path": container_path,
        }
    observed = sha256_hex(raw)
    if observed != expected_sha256:
        return {
            "ok": False,
            "reason": "snapshot_host_digest_mismatch_before_copy",
            "expected": expected_sha256,
            "observed": observed,
            "container_path": container_path,
        }
    rel = container_path.lstrip("/")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        # Create parent directory members so /work and /adapter exist privately.
        parts = rel.split("/")
        accum = []
        for part in parts[:-1]:
            accum.append(part)
            info = tarfile.TarInfo(name="/".join(accum))
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(info)
        info = tarfile.TarInfo(name=rel)
        info.size = len(raw)
        info.mode = 0o444
        tar.addfile(info, io.BytesIO(raw))
    proc = subprocess.run(
        ["docker", "cp", "-", f"{container_id}:/"],
        input=buf.getvalue(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "reason": "docker_cp_failed",
            "returncode": proc.returncode,
            "container_path": container_path,
            "stderr_tail": ((proc.stderr or b"")[-400:]).decode("utf-8", errors="replace"),
        }
    return {
        "ok": True,
        "container_path": container_path,
        "sha256": observed,
        "size": len(raw),
    }


def run_promptfoo_offline(
    *,
    config_path: Path,
    state_root: Path,
    output_path: Path,
    adapter_host_path: Path | None = None,
    expected_adapter_sha256: str | None = None,
    timeout_s: int = 180,
    run_id: str = "run",
    package_owner: str = "g4_hidden_capability_seam_v1",
    op_root: Path | None = None,
    vault_root: Path | None = None,
    evaluator_root: Path | None = None,
    allowed_roots: list[Path] | None = None,
    denied_roots: list[Path] | None = None,
    expected_case_ids: list[str] | None = None,
    expected_config_sha256: str | None = None,
    expected_cases_sha256: str | None = None,
) -> dict[str, Any]:
    """Offline Promptfoo via create → private docker-cp snapshot → inspect → start.

    expected_config_sha256, expected_cases_sha256, expected_case_ids, and
    expected_adapter_sha256 are mandatory. Config/cases/adapter are never bind
    mounted and never staged under the read-write /state mount.
    """
    from .canonical import sha256_hex

    binding = _require_expected_bindings(
        expected_config_sha256=expected_config_sha256,
        expected_cases_sha256=expected_cases_sha256,
        expected_case_ids=expected_case_ids,
        expected_adapter_sha256=expected_adapter_sha256,
    )
    if not binding.get("ok"):
        return {
            "ok": False,
            "phase": "expected_bindings",
            "terminal_status": "failed",
            "reason": binding.get("reason"),
            "missing": binding.get("missing"),
        }
    expected_config_sha256 = str(binding["expected_config_sha256"])
    expected_cases_sha256 = str(binding["expected_cases_sha256"])
    expected_adapter_sha256 = str(binding["expected_adapter_sha256"])
    expected_case_ids = list(binding["expected_case_ids"])
    case_set_id = expected_case_set_identity_sha256()

    config_path = _lexical_absolute_path(config_path)
    config_dir = config_path.parent
    state_root = _lexical_absolute_path(state_root)
    output_path = _lexical_absolute_path(output_path)
    if output_path.name != PROMPTFOO_OUTPUT_BASENAME:
        return {
            "ok": False,
            "phase": "output_binding",
            "terminal_status": "failed",
            "reason": "promptfoo_output_basename_not_exact",
            "expected_basename": PROMPTFOO_OUTPUT_BASENAME,
        }
    adapter_src = (
        Path(adapter_host_path)
        if adapter_host_path
        else (config_dir / "promptfoo_subject_adapter.py")
    )
    adapter_src = _lexical_absolute_path(adapter_src)

    if op_root is None or allowed_roots is None or denied_roots is None:
        return {
            "ok": False,
            "phase": "mount_boundary",
            "terminal_status": "failed",
            "check": {"ok": False, "reason": "explicit_trusted_mount_policy_required"},
        }
    op_root = _lexical_absolute_path(op_root)
    mandatory_denied = default_denied_roots(
        vault_root=_lexical_absolute_path(vault_root) if vault_root else None,
        evaluator_root=_lexical_absolute_path(evaluator_root) if evaluator_root else None,
        op_root=op_root,
    )
    denied_roots = [*denied_roots, *mandatory_denied]
    preflight = _preflight_promptfoo_host_paths(
        config_path=config_path,
        state_root=state_root,
        output_root=output_path.parent,
        adapter_src=adapter_src,
        op_root=op_root,
        allowed_roots=list(allowed_roots),
        denied_roots=list(denied_roots),
    )
    if not preflight.get("ok"):
        return {
            "ok": False,
            "phase": "mount_boundary",
            "terminal_status": "failed",
            "check": preflight,
        }
    op_root = Path(preflight["op_root"])
    trusted_mount_root = Path(preflight["trusted_mount_root"])
    normalized_allowed = [Path(root) for root in preflight["normalized_allowed"]]
    config_path = Path(preflight["config_path"])
    config_dir = config_path.parent
    cases_path = Path(preflight["cases_path"])
    adapter_src = Path(preflight["adapter_src"])
    state_root = Path(preflight["state_root"])
    output_root = Path(preflight["output_root"])

    # This is the first host mutation. Every caller-controlled path, trust root,
    # denied-root intersection, reparse ancestor, and source-alias relationship
    # has already failed closed above.
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "phase": "mount_boundary",
            "terminal_status": "failed",
            "reason": "admitted_mount_source_create_failed",
            "error_class": type(exc).__name__,
        }

    mount_plan = [
        {"source": output_root, "dest": "/output", "mode": "rw"},
        {"source": state_root, "dest": "/state", "mode": "rw"},
    ]
    expected_mounts: list[dict[str, str]] = []
    for mount in mount_plan:
        try:
            check = validate_mount_boundary(
                source=Path(mount["source"]),
                dest=str(mount["dest"]),
                mode=str(mount["mode"]),
                allowed_roots=normalized_allowed,
                denied_roots=list(denied_roots),
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "phase": "mount_boundary",
                "terminal_status": "failed",
                "reason": "mount_boundary_validation_exception",
                "error_class": type(exc).__name__,
            }
        if not check.get("ok"):
            return {
                "ok": False,
                "phase": "mount_boundary",
                "terminal_status": "failed",
                "check": check,
            }
        expected_mounts.append(
            {
                "dest": str(mount["dest"]),
                "mode": str(mount["mode"]),
                "source_norm": str(check["source"]),
            }
        )

    try:
        (state_root / "cache").mkdir(parents=True, exist_ok=True)
        (state_root / "config_dir").mkdir(parents=True, exist_ok=True)
        (state_root / "home").mkdir(parents=True, exist_ok=True)
        (state_root / "logs").mkdir(parents=True, exist_ok=True)
        legacy_adapter_alias = state_root / "adapter_mount"
        if legacy_adapter_alias.exists():
            if _is_reparse_point(legacy_adapter_alias):
                return {
                    "ok": False,
                    "phase": "mount_boundary",
                    "terminal_status": "failed",
                    "reason": "legacy_adapter_alias_reparse_point",
                }
            shutil.rmtree(legacy_adapter_alias)
    except OSError as exc:
        return {
            "ok": False,
            "phase": "mount_boundary",
            "terminal_status": "failed",
            "reason": "admitted_state_prepare_failed",
            "error_class": type(exc).__name__,
        }

    # Capture validated executable bytes once, then stage outside every mount.
    # Host mutation of the original paths after this capture cannot change the
    # private container snapshot if docker cp uses the staged copies.
    try:
        config_bytes = config_path.read_bytes()
        cases_bytes = cases_path.read_bytes()
        adapter_bytes = adapter_src.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "executable_input_unreadable",
            "error_class": type(exc).__name__,
        }
    source_adapter_sha256 = sha256_hex(adapter_bytes)
    source_adapter_size = len(adapter_bytes)
    if source_adapter_sha256 != expected_adapter_sha256:
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "trusted_adapter_digest_not_bound_to_suite_descriptor",
        }
    observed_config_sha = sha256_hex(config_bytes)
    observed_cases_sha = sha256_hex(cases_bytes)
    if observed_config_sha != expected_config_sha256:
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "promptfoo_config_digest_mismatch_at_capture",
            "expected": expected_config_sha256,
            "observed": observed_config_sha,
        }
    if observed_cases_sha != expected_cases_sha256:
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "promptfoo_cases_digest_mismatch_at_capture",
            "expected": expected_cases_sha256,
            "observed": observed_cases_sha,
        }

    # Private staging root is never mounted at /state, /output, or executable dests.
    # Keep adapter in a sibling directory so config validation does not see a
    # config-local adapter shadow (which would be an unbound /work surface).
    snapshot_stage = trusted_mount_root / ".private_exec_snapshot"
    # Check the lexical placement before creating or deleting anything.
    if _is_under_or_equal(snapshot_stage, state_root):
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "private_snapshot_must_not_live_under_state_root",
        }
    if _is_under_or_equal(snapshot_stage, output_path.parent):
        return {
            "ok": False,
            "phase": "adapter_binding",
            "terminal_status": "failed",
            "reason": "private_snapshot_must_not_live_under_output_root",
        }
    prior_stage_cleanup = _remove_private_snapshot_stage(snapshot_stage)
    if not prior_stage_cleanup.get("ok"):
        return {
            "ok": False,
            "phase": "private_snapshot_cleanup",
            "terminal_status": "failed",
            "reason": "prior_private_snapshot_stage_not_absent",
            "cleanup": prior_stage_cleanup,
        }

    def _fail_before_container(result: dict[str, Any]) -> dict[str, Any]:
        cleanup = _remove_private_snapshot_stage(snapshot_stage)
        if not cleanup.get("ok"):
            raise RuntimeError("private_snapshot_stage_cleanup_not_proven")
        return {**result, "private_snapshot_cleanup": cleanup}

    stage_work = snapshot_stage / "work"
    stage_adapter_dir = snapshot_stage / "adapter"
    stage_config = stage_work / "promptfooconfig.yaml"
    stage_cases = stage_work / "public_cases.json"
    stage_adapter = stage_adapter_dir / "promptfoo_subject_adapter.py"
    try:
        stage_work.mkdir(parents=True)
        stage_adapter_dir.mkdir(parents=True)
        stage_config.write_bytes(config_bytes)
        stage_cases.write_bytes(cases_bytes)
        stage_adapter.write_bytes(adapter_bytes)
    except OSError as exc:
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "private_snapshot_stage_write_failed",
                "error_class": type(exc).__name__,
            }
        )

    # Validate schemas against the staged snapshot files (same bytes as capture).
    try:
        provider_validation = validate_promptfoo_config_providers(
            stage_config, expected_config_sha256=expected_config_sha256
        )
    except Exception as exc:  # noqa: BLE001
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "promptfoo_provider_validation_exception",
                "error_class": type(exc).__name__,
            }
        )
    if not provider_validation.get("ok"):
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "promptfoo_provider_not_exclusively_bound_to_adapter_mount",
                "provider_validation": provider_validation,
            }
        )
    try:
        cases_validation = validate_promptfoo_public_cases(
            stage_cases,
            expected_case_ids=expected_case_ids,
            expected_cases_sha256=expected_cases_sha256,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "promptfoo_public_cases_validation_exception",
                "error_class": type(exc).__name__,
            }
        )
    if not cases_validation.get("ok"):
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "promptfoo_public_cases_not_exclusively_bound",
                "cases_validation": cases_validation,
            }
        )
    try:
        staged_adapter_sha256 = sha256_hex(stage_adapter.read_bytes())
    except OSError as exc:
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "trusted_adapter_stage_unreadable",
                "error_class": type(exc).__name__,
            }
        )
    if staged_adapter_sha256 != source_adapter_sha256:
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "trusted_adapter_stage_digest_mismatch",
            }
        )

    adapter_attestation = {
        "provider_id": TRUSTED_PROVIDER_ID,
        "source_sha256": source_adapter_sha256,
        "suite_descriptor_expected_sha256": expected_adapter_sha256,
        "private_snapshot_sha256": staged_adapter_sha256,
        "size": source_adapter_size,
        "dedicated_read_only_mount": False,
        "private_container_layer_snapshot": True,
        "state_root_adapter_alias_absent": not legacy_adapter_alias.exists(),
        "config_local_shadow_absent": True,
        "config_sha256": provider_validation.get("config_sha256"),
        "config_size": provider_validation.get("config_size"),
        "providers_count": provider_validation.get("providers_count"),
        "provider_validation_schema": provider_validation.get("schema"),
        "public_cases_sha256": cases_validation.get("cases_sha256"),
        "public_cases_validation_schema": cases_validation.get("schema"),
        "execution_input_paths": {
            "config": PRIVATE_CONTAINER_CONFIG_PATH,
            "cases": PRIVATE_CONTAINER_CASES_PATH,
            "adapter": PRIVATE_CONTAINER_ADAPTER_PATH,
        },
        "authority": False,
    }
    try:
        write_json(state_root / "adapter_mount_attestation.v1.json", adapter_attestation)
    except OSError as exc:
        return _fail_before_container(
            {
                "ok": False,
                "phase": "adapter_binding",
                "terminal_status": "failed",
                "reason": "adapter_attestation_write_failed",
                "error_class": type(exc).__name__,
            }
        )

    # Only output + state remain host bind mounts (bounded rw, disjoint from snapshot).
    mount_plan = [
        {"source": output_path.parent, "dest": "/output", "mode": "rw"},
        {"source": state_root, "dest": "/state", "mode": "rw"},
    ]
    expected_mounts: list[dict[str, str]] = []
    for m in mount_plan:
        try:
            v = validate_mount_boundary(
                source=Path(m["source"]),
                dest=str(m["dest"]),
                mode=str(m["mode"]),
                allowed_roots=normalized_allowed,
                denied_roots=list(denied_roots),
            )
        except Exception as exc:  # noqa: BLE001
            return _fail_before_container(
                {
                    "ok": False,
                    "phase": "mount_boundary",
                    "terminal_status": "failed",
                    "reason": "mount_boundary_validation_exception",
                    "error_class": type(exc).__name__,
                }
            )
        if not v.get("ok"):
            return _fail_before_container(
                {
                    "ok": False,
                    "phase": "mount_boundary",
                    "terminal_status": "failed",
                    "check": v,
                }
            )
        expected_mounts.append(
            {
                "dest": str(m["dest"]),
                "mode": str(m["mode"]),
                "source_norm": str(v["source"]),
            }
        )

    # This is the first Docker boundary. Every caller-controlled binding,
    # executable byte snapshot, schema, output basename, and mount policy has
    # already failed closed before version attestation creates a container.
    try:
        ident = verify_promptfoo_identity()
    except Exception as exc:  # noqa: BLE001
        cleanup = _remove_private_snapshot_stage(snapshot_stage)
        if not cleanup.get("ok"):
            raise RuntimeError(
                "identity_exception_and_private_snapshot_cleanup_not_proven"
            ) from exc
        raise
    if not ident.get("ok"):
        return _fail_before_container(
            {
                "ok": False,
                "phase": "identity",
                "terminal_status": "failed",
                "promptfoo_identity": ident,
            }
        )

    stage_name = f"xinao-g4hcs-stage-{uuid.uuid4().hex[:12]}"
    name = f"xinao-g4hcs-{uuid.uuid4().hex[:16]}"
    stage_container_id: str | None = None
    container_id: str | None = None
    snapshot_image: str | None = None
    stage_provenance: dict[str, Any] | None = None
    snapshot_image_provenance: dict[str, Any] | None = None
    stage_cleanup_after_commit: dict[str, Any] | None = None
    pre_start: dict[str, Any] | None = None
    post_state: dict[str, Any] | None = None
    offline_probe: dict[str, Any] | None = None
    terminal = "failed"
    returncode = -1
    stdout = ""
    stderr = ""
    promoted_to_pass = False
    result_parse: dict[str, Any] | None = None
    copy_evidence: list[dict[str, Any]] = []

    # In-container digest of the private copied snapshot immediately before use.
    inner = (
        "set -e; "
        "python3 - <<'PY'\n"
        "import hashlib\n"
        "checks=[\n"
        f" ('{PRIVATE_CONTAINER_CONFIG_PATH}','{expected_config_sha256}'),\n"
        f" ('{PRIVATE_CONTAINER_CASES_PATH}','{expected_cases_sha256}'),\n"
        f" ('{PRIVATE_CONTAINER_ADAPTER_PATH}','{source_adapter_sha256}'),\n"
        "]\n"
        "for path, expected in checks:\n"
        "    observed=hashlib.sha256(open(path,'rb').read()).hexdigest()\n"
        "    if observed != expected:\n"
        "        raise SystemExit(96)\n"
        "PY\n"
        "python3 - <<'PY'\n"
        "import socket\n"
        "ok=False\n"
        "err='unknown'\n"
        "try:\n"
        "    s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    s.settimeout(2)\n"
        "    s.connect(('1.1.1.1', 443))\n"
        "    s.close()\n"
        "    ok=True\n"
        "    err='connected'\n"
        "except Exception as e:\n"
        "    ok=False\n"
        "    err=type(e).__name__\n"
        "open('/output/offline_probe.json','w').write("
        "'{\\\"reachable\\\":'+('true' if ok else 'false')+',\\\"error_class\\\":\\\"'+err+'\\\"}\\n')\n"
        "if ok:\n"
        "    raise SystemExit(97)\n"
        "PY\n"
        "promptfoo eval -c /work/promptfooconfig.yaml --no-cache "
        f"-o /output/{PROMPTFOO_OUTPUT_BASENAME} --max-concurrency 1"
    )

    try:
        # Stage container is intentionally not --read-only so docker cp can write
        # the private executable snapshot into the container layer. It is never
        # started. The execution container is then created --read-only from a
        # commit of that layer (no host bind mounts for config/cases/adapter).
        stage_create = _run(
            [
                "docker",
                "create",
                "--name",
                stage_name,
                "--label",
                f"{OWNER_LABEL}.owner={package_owner}",
                "--label",
                f"{OWNER_LABEL}.role=private_snapshot_stage",
                "--label",
                f"{OWNER_LABEL}=1",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "32",
                PINNED_IMAGE,
                "true",
            ],
            timeout=60,
        )
        if stage_create.returncode != 0:
            return {
                "ok": False,
                "phase": "docker_stage_create",
                "terminal_status": "failed",
                "stderr_tail": (stage_create.stderr or "")[-2000:],
                "stdout_tail": (stage_create.stdout or "")[-500:],
                "promptfoo_identity": ident,
            }
        raw_stage_create_stdout = stage_create.stdout or ""
        stage_container_id = raw_stage_create_stdout or "<missing-container-id>"
        parsed_stage_container_id = _container_id_from_create_stdout(raw_stage_create_stdout)
        if parsed_stage_container_id is None:
            return {
                "ok": False,
                "phase": "docker_stage_create",
                "terminal_status": "failed",
                "reason": "stage_create_stdout_not_exact_canonical",
                "promptfoo_identity": ident,
            }
        stage_container_id = parsed_stage_container_id

        # Prove that the never-started staging container resolves to the exact
        # digest-pinned base image before any bytes are copied into its layer.
        pinned_image_inspect = _inspect_image(PINNED_IMAGE)
        stage_inspect = _inspect_container(stage_container_id)
        pinned_layers = list(((pinned_image_inspect.get("RootFS") or {}).get("Layers") or []))
        stage_state = stage_inspect.get("State") or {}
        stage_problems: list[str] = []
        if pinned_image_inspect.get("Id") != PINNED_DIGEST:
            stage_problems.append("pinned_image_id_drift")
        if PINNED_IMAGE not in (pinned_image_inspect.get("RepoDigests") or []):
            stage_problems.append("pinned_repo_digest_absent")
        if not pinned_layers:
            stage_problems.append("pinned_rootfs_layers_absent")
        if stage_inspect.get("Image") != PINNED_DIGEST:
            stage_problems.append("stage_base_image_id_drift")
        if (stage_inspect.get("Config") or {}).get("Image") != PINNED_IMAGE:
            stage_problems.append("stage_base_image_ref_drift")
        if stage_state.get("Running") is not False or stage_state.get("Status") != "created":
            stage_problems.append("stage_container_not_never_started_created_state")
        started_at = str(stage_state.get("StartedAt") or "")
        if started_at and not started_at.startswith("0001-"):
            stage_problems.append("stage_container_started_at_nonzero")
        if stage_inspect.get("Mounts"):
            stage_problems.append("stage_container_unexpected_mount")
        stage_provenance = {
            "ok": not stage_problems,
            "problems": stage_problems,
            "pinned_image_id": pinned_image_inspect.get("Id"),
            "pinned_repo_digest_present": PINNED_IMAGE
            in (pinned_image_inspect.get("RepoDigests") or []),
            "pinned_rootfs_layer_count": len(pinned_layers),
            "stage_image_id": stage_inspect.get("Image"),
            "stage_image_ref": (stage_inspect.get("Config") or {}).get("Image"),
            "stage_status": stage_state.get("Status"),
            "stage_running": stage_state.get("Running"),
            "stage_started_at_zero": not started_at or started_at.startswith("0001-"),
            "stage_mount_count": len(stage_inspect.get("Mounts") or []),
        }
        if not stage_provenance["ok"]:
            return {
                "ok": False,
                "phase": "private_snapshot_stage_provenance",
                "terminal_status": "failed",
                "stage_provenance": stage_provenance,
                "promptfoo_identity": ident,
            }

        # Copy validated snapshot into the stopped stage container private layer.
        for host_file, dest, digest in (
            (stage_config, PRIVATE_CONTAINER_CONFIG_PATH, expected_config_sha256),
            (stage_cases, PRIVATE_CONTAINER_CASES_PATH, expected_cases_sha256),
            (stage_adapter, PRIVATE_CONTAINER_ADAPTER_PATH, source_adapter_sha256),
        ):
            cp = _docker_cp_file(
                container_id=stage_container_id,
                host_path=host_file,
                container_path=dest,
                expected_sha256=digest,
            )
            copy_evidence.append(cp)
            if not cp.get("ok"):
                return {
                    "ok": False,
                    "phase": "private_snapshot_copy",
                    "terminal_status": "failed",
                    "reason": cp.get("reason"),
                    "copy_evidence": copy_evidence,
                    "promptfoo_identity": ident,
                    "container_name": stage_name,
                    "container_id": stage_container_id,
                }

        # docker cp must not have started or rebased the staging container.
        stage_after_copy = _inspect_container(stage_container_id)
        stage_after_state = stage_after_copy.get("State") or {}
        if (
            stage_after_copy.get("Image") != PINNED_DIGEST
            or (stage_after_copy.get("Config") or {}).get("Image") != PINNED_IMAGE
            or stage_after_state.get("Running") is not False
            or stage_after_state.get("Status") != "created"
            or (
                str(stage_after_state.get("StartedAt") or "")
                and not str(stage_after_state.get("StartedAt") or "").startswith("0001-")
            )
        ):
            return {
                "ok": False,
                "phase": "private_snapshot_stage_post_copy_provenance",
                "terminal_status": "failed",
                "reason": "stage_container_state_or_base_drift_after_copy",
                "stage_provenance": stage_provenance,
                "promptfoo_identity": ident,
            }

        commit = _run(
            [
                "docker",
                "commit",
                "--change",
                "USER promptfoo",
                stage_container_id,
            ],
            timeout=120,
        )
        if commit.returncode != 0 or not (commit.stdout or "").strip():
            return {
                "ok": False,
                "phase": "private_snapshot_commit",
                "terminal_status": "failed",
                "stderr_tail": (commit.stderr or "")[-2000:],
                "promptfoo_identity": ident,
                "copy_evidence": copy_evidence,
            }
        snapshot_image = (commit.stdout or "").strip()
        snapshot_image_inspect = _inspect_image(snapshot_image)
        snapshot_layers = list(((snapshot_image_inspect.get("RootFS") or {}).get("Layers") or []))
        snapshot_problems: list[str] = []
        if snapshot_image_inspect.get("Id") != snapshot_image:
            snapshot_problems.append("snapshot_image_id_not_commit_result")
        if len(snapshot_layers) != len(pinned_layers) + 1:
            snapshot_problems.append("snapshot_rootfs_layer_count_not_base_plus_one")
        elif snapshot_layers[: len(pinned_layers)] != pinned_layers:
            snapshot_problems.append("snapshot_rootfs_not_derived_from_pinned_base")
        if (snapshot_image_inspect.get("Config") or {}).get("User") != "promptfoo":
            snapshot_problems.append("snapshot_image_user_not_promptfoo")
        snapshot_image_provenance = {
            "ok": not snapshot_problems,
            "problems": snapshot_problems,
            "snapshot_image_id": snapshot_image_inspect.get("Id"),
            "base_image_id": pinned_image_inspect.get("Id"),
            "base_rootfs_layer_count": len(pinned_layers),
            "snapshot_rootfs_layer_count": len(snapshot_layers),
            "base_layers_are_exact_prefix": snapshot_layers[: len(pinned_layers)] == pinned_layers,
            "snapshot_user": (snapshot_image_inspect.get("Config") or {}).get("User"),
        }
        if not snapshot_image_provenance["ok"]:
            return {
                "ok": False,
                "phase": "private_snapshot_image_provenance",
                "terminal_status": "failed",
                "snapshot_image_provenance": snapshot_image_provenance,
                "promptfoo_identity": ident,
            }
        # Stage container is no longer needed once the snapshot image exists.
        stage_cleanup_after_commit = _docker_rm_exact(stage_name, stage_container_id)
        if not stage_cleanup_after_commit.get("ok"):
            return {
                "ok": False,
                "phase": "private_snapshot_stage_cleanup",
                "terminal_status": "failed",
                "cleanup": stage_cleanup_after_commit,
                "promptfoo_identity": ident,
            }
        stage_container_id = None

        create_argv = [
            "docker",
            "create",
            "--name",
            name,
            "--label",
            f"{OWNER_LABEL}.owner={package_owner}",
            "--label",
            f"{OWNER_LABEL}.run_id={run_id}",
            "--label",
            f"{OWNER_LABEL}=1",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(PIDS_LIMIT),
            "--mount",
            f"type=bind,src={output_path.parent},dst=/output",
            "--mount",
            f"type=bind,src={state_root},dst=/state",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        ]
        for k, v in ALLOWED_ENV.items():
            create_argv.extend(["--env", f"{k}={v}"])
        create_argv.extend(
            [
                "--workdir",
                "/work",
                snapshot_image,
                "sh",
                "-c",
                inner,
            ]
        )
        created = _run(create_argv, timeout=60)
        if created.returncode != 0:
            return {
                "ok": False,
                "phase": "docker_create",
                "terminal_status": "failed",
                "stderr_tail": (created.stderr or "")[-2000:],
                "stdout_tail": (created.stdout or "")[-500:],
                "promptfoo_identity": ident,
                "copy_evidence": copy_evidence,
            }
        raw_create_stdout = created.stdout or ""
        container_id = raw_create_stdout or "<missing-container-id>"
        parsed_container_id = _container_id_from_create_stdout(raw_create_stdout)
        if parsed_container_id is None:
            return {
                "ok": False,
                "phase": "docker_create",
                "terminal_status": "failed",
                "reason": "execution_create_stdout_not_exact_canonical",
                "promptfoo_identity": ident,
                "copy_evidence": copy_evidence,
            }
        container_id = parsed_container_id

        insp = _inspect_container(container_id)
        # Image ref will be the local commit id, not the pinned digest string.
        # Re-check security posture with a relaxed image identity that still
        # requires non-root user and the exact mount plan.
        pre_start = _verify_pre_start(
            insp,
            expected_mounts=expected_mounts,
            allowed_mount_targets={"/output", "/state"},
            expected_image_ref=snapshot_image,
            expected_image_id=snapshot_image,
        )
        pre_start = {
            **pre_start,
            "snapshot_image_from_pinned_stage": bool(
                stage_provenance
                and stage_provenance.get("ok")
                and snapshot_image_provenance
                and snapshot_image_provenance.get("ok")
            ),
            "pinned_source_image": PINNED_IMAGE,
            "stage_provenance": stage_provenance,
            "snapshot_image_provenance": snapshot_image_provenance,
        }
        if not pre_start["snapshot_image_from_pinned_stage"]:
            pre_start = {
                **pre_start,
                "ok": False,
                "problems": list(pre_start.get("problems") or [])
                + ["snapshot_image_provenance_not_proven"],
            }
        # Forbid any unexpected executable-input mounts.
        for mount in pre_start.get("observed_mounts") or []:
            dest = str(mount.get("dest") or "")
            if dest in FORBIDDEN_EXECUTABLE_INPUT_MOUNTS:
                pre_start = {
                    **pre_start,
                    "ok": False,
                    "problems": list(pre_start.get("problems") or [])
                    + [f"executable_input_mount_forbidden:{dest}"],
                }
        # Strip any env values from evidence — keys only
        pre_start_public = {k: v for k, v in pre_start.items() if k not in {"env_values", "env"}}
        pre_start_public["private_snapshot_copy"] = {
            "ok": all(c.get("ok") for c in copy_evidence),
            "paths": [c.get("container_path") for c in copy_evidence],
            "digests_checked_before_copy": True,
        }
        write_json(state_root / "pre_start_inspect.v1.json", pre_start_public)
        if not pre_start.get("ok"):
            terminal = "failed"
            return {
                "ok": False,
                "phase": "pre_start_inspect",
                "terminal_status": terminal,
                "pre_start": pre_start_public,
                "promptfoo_identity": ident,
                "container_name": name,
                "container_id": container_id,
                "case_set_identity_sha256": case_set_id,
            }

        # Bounded host attach
        try:
            started = _run(["docker", "start", "-a", container_id], timeout=timeout_s)
            stdout = started.stdout or ""
            stderr = started.stderr or ""
            returncode = started.returncode
            terminal = "completed" if returncode == 0 else "failed"
            if returncode == 96:
                terminal = "failed"
        except subprocess.TimeoutExpired as exc:
            terminal = "timeout"
            returncode = -9
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            # Zero-grace kill of exact owned container
            _run(["docker", "kill", container_id], timeout=30)
            _run(["docker", "stop", "-t", "0", container_id], timeout=30)
            try:
                after = _inspect_container(container_id)
                running = bool((after.get("State") or {}).get("Running"))
            except Exception:  # noqa: BLE001
                running = False
                after = {}
            post_state = {
                "running_after_timeout_kill": running,
                "state_status": (after.get("State") or {}).get("Status"),
            }
            promoted_to_pass = False
            result = {
                "ok": False,
                "terminal_status": "timeout",
                "promoted_to_pass": False,
                "reason": "promptfoo_timeout",
                "container_name": name,
                "container_id": container_id,
                "post_timeout": post_state,
                "promptfoo_identity": ident,
                "cache_enabled": False,
                "scoring_enabled": False,
                "network_mode": "none",
                "offline_enforced": True,
                "synthetic_only": True,
                "label": SYNTHETIC_LABEL,
                "pre_start": pre_start_public,
                "execution_boundary": "docker_create_private_cp_inspect_start",
            }
            write_json(state_root / "promptfoo_run_receipt.v1.json", result)
            return result

        # Offline probe receipt
        probe_path = output_path.parent / "offline_probe.json"
        if probe_path.exists():
            try:
                offline_probe = json.loads(probe_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                offline_probe = {"reachable": None, "error_class": type(exc).__name__}
        else:
            offline_probe = {"reachable": None, "error_class": "probe_missing"}

        try:
            after = _inspect_container(container_id)
            post_state = {
                "running": bool((after.get("State") or {}).get("Running")),
                "status": (after.get("State") or {}).get("Status"),
                "exit_code": (after.get("State") or {}).get("ExitCode"),
            }
        except Exception as exc:  # noqa: BLE001
            post_state = {"error_class": type(exc).__name__}

        # Fail closed if network was reachable
        if offline_probe and offline_probe.get("reachable") is True:
            terminal = "failed"
            returncode = 97

        result_parse = parse_promptfoo_results(
            output_path,
            expected_ids=expected_case_ids,
        )
        ok = (
            returncode == 0
            and terminal == "completed"
            and offline_probe is not None
            and offline_probe.get("reachable") is False
            and output_path.exists()
            and result_parse.get("ok") is True
        )
        if not ok and terminal == "completed":
            terminal = "failed"

        result = {
            "ok": ok,
            "terminal_status": terminal,
            "promoted_to_pass": promoted_to_pass,
            "returncode": returncode,
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
            "output_path": str(output_path),
            "cache_enabled": False,
            "scoring_enabled": False,
            "network_mode": "none",
            "offline_enforced": True,
            "offline_probe": {
                "reachable": offline_probe.get("reachable") if offline_probe else None,
                "error_class": offline_probe.get("error_class") if offline_probe else None,
            },
            "promptfoo_identity": ident,
            "result_parse": result_parse,
            "case_set_identity_sha256": case_set_id,
            "container_name": name,
            "container_id": container_id,
            "pre_start": pre_start_public,
            "post_state": post_state,
            "state_root": str(state_root),
            "synthetic_only": True,
            "label": SYNTHETIC_LABEL,
            "not_admission": True,
            "not_capability_result": True,
            "inspect_ai_used": False,
            "authority": False,
            "host_promptfoo_executed": False,
            "execution_boundary": "docker_create_private_cp_inspect_start",
            "mount_boundary_enforced": True,
            "env_allowlist_enforced": True,
            "private_snapshot_copy": copy_evidence,
            "adapter_mount_attestation": adapter_attestation,
            "promptfoo_config_sha256": provider_validation.get("config_sha256"),
            "promptfoo_config_size": provider_validation.get("config_size"),
            "promptfoo_public_cases_sha256": cases_validation.get("cases_sha256"),
            "promptfoo_provider_id": TRUSTED_PROVIDER_ID,
            "promptfoo_provider_validation": {
                "ok": True,
                "schema": provider_validation.get("schema"),
                "providers_count": 1,
                "config_sha256": provider_validation.get("config_sha256"),
            },
            "promptfoo_public_cases_validation": {
                "ok": True,
                "schema": cases_validation.get("schema"),
                "case_count": cases_validation.get("case_count"),
                "cases_sha256": cases_validation.get("cases_sha256"),
                "provider_bearing_fields_absent": True,
            },
        }
        write_json(state_root / "promptfoo_run_receipt.v1.json", result)
        return result
    finally:
        # Always reconcile exact owned containers and ephemeral snapshot image.
        cleanup = _docker_rm_exact(name, container_id)
        if stage_cleanup_after_commit is not None:
            cleanup = {
                **cleanup,
                "stage_cleanup_after_commit": stage_cleanup_after_commit,
                "ok": cleanup.get("ok") is True and stage_cleanup_after_commit.get("ok") is True,
            }
        if stage_container_id is not None:
            stage_cleanup = _docker_rm_exact(stage_name, stage_container_id)
            cleanup = {
                **cleanup,
                "stage_cleanup": stage_cleanup,
                "ok": cleanup.get("ok") is True and stage_cleanup.get("ok") is True,
            }
        image_cleanup: dict[str, Any] = {"image": snapshot_image, "ok": True}
        if snapshot_image:
            image_cleanup = _docker_rmi_exact(snapshot_image)
            cleanup = {
                **cleanup,
                "snapshot_image_cleanup": image_cleanup,
                "ok": cleanup.get("ok") is True and image_cleanup.get("ok") is True,
            }
        host_stage_cleanup = _remove_private_snapshot_stage(snapshot_stage)
        cleanup = {
            **cleanup,
            "host_private_snapshot_cleanup": host_stage_cleanup,
            "ok": cleanup.get("ok") is True and host_stage_cleanup.get("ok") is True,
        }
        try:
            write_json(state_root / "container_cleanup.v1.json", cleanup)
        except Exception as exc:  # noqa: BLE001
            cleanup = {
                **cleanup,
                "cleanup_receipt_write_error_class": type(exc).__name__,
                "ok": False,
            }
        require_terminal_container_cleanup(cleanup)


def run_adversarial_isolation(
    *,
    state_root: Path,
    package_owner: str = "g4_hidden_capability_seam_v1",
) -> dict[str, Any]:
    """Subject tries vault path classes; vault must be absent; all reads fail."""
    ident = verify_promptfoo_identity()
    if not ident.get("ok"):
        return {"ok": False, "phase": "identity", **ident}

    state_root = Path(state_root).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    out_dir = state_root / "adversarial_out"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    work = state_root / "adversarial_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    adapter_dir = state_root / "adversarial_adapter"
    if adapter_dir.exists():
        shutil.rmtree(adapter_dir)
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "noop.py").write_text("# adversarial noop\n", encoding="utf-8")

    name = f"xinao-g4hcs-adv-{uuid.uuid4().hex[:12]}"
    container_id = None
    (state_root / "adv_state").mkdir(parents=True, exist_ok=True)
    # Probe script: attempt known path classes; record only booleans/error classes
    script = r"""
import json, os
from pathlib import Path
attempts = []
paths = [
    ("relative_traversal", "../../vault/sealed_truth.v1.json"),
    ("relative_traversal_deep", "../../../vault/sealed_truth.v1.json"),
    ("absolute_windows", r"D:\XINAO_RESEARCH_RUNTIME\worktrees\mainline-parallel-wave146-20260722\g4_hidden_capability_seam_v1\ops\op_main\vault\sealed_truth.v1.json"),
    ("vault_root", "/vault/sealed_truth.v1.json"),
    ("vault_alt", "/work/../../vault/sealed_truth.v1.json"),
    ("symlink_escape", "/work/escape_link"),
    ("env_vault", os.environ.get("VAULT_LOCATOR") or os.environ.get("SEALED_TRUTH_PATH") or ""),
]
for cls, p in paths:
    if not p:
        attempts.append({"path_class": cls, "readable": False, "error_class": "empty_or_unset", "content_recorded": False})
        continue
    try:
        data = Path(p).read_bytes()[:1]
        attempts.append({"path_class": cls, "readable": True, "error_class": None, "content_recorded": False, "bytes_seen": 1 if data else 0})
    except Exception as e:
        attempts.append({"path_class": cls, "readable": False, "error_class": type(e).__name__, "content_recorded": False})
# env discovery
env_hits = [k for k in os.environ if any(x in k.upper() for x in ("VAULT", "TRUTH", "SEALED", "API_KEY"))]
open("/output/adversarial_isolation.json","w").write(json.dumps({
    "attempts": attempts,
    "env_secret_key_names_present": env_hits,
    "any_readable": any(a.get("readable") for a in attempts),
}, sort_keys=True))
"""
    (work / "probe.py").write_text(script, encoding="utf-8")
    try:
        adv_state = state_root / "adv_state"
        create_argv = [
            "docker",
            "create",
            "--name",
            name,
            "--label",
            f"{OWNER_LABEL}.owner={package_owner}",
            "--label",
            f"{OWNER_LABEL}.role=adversarial_isolation",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(PIDS_LIMIT),
            "--mount",
            f"type=bind,src={work},dst=/work,readonly",
            "--mount",
            f"type=bind,src={adapter_dir},dst=/adapter,readonly",
            "--mount",
            f"type=bind,src={out_dir},dst=/output",
            "--mount",
            f"type=bind,src={adv_state},dst=/state",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        ]
        for key, value in ALLOWED_ENV.items():
            create_argv.extend(["--env", f"{key}={value}"])
        create_argv.extend(["--workdir", "/work", PINNED_IMAGE, "python3", "/work/probe.py"])
        create = _run(create_argv, timeout=60)
        if create.returncode != 0:
            return {
                "ok": False,
                "reason": "adv_create_failed",
                "stderr": (create.stderr or "")[-500:],
            }
        raw_create_stdout = create.stdout or ""
        container_id = raw_create_stdout or "<missing-container-id>"
        parsed_container_id = _container_id_from_create_stdout(raw_create_stdout)
        if parsed_container_id is None:
            return {"ok": False, "reason": "adv_create_stdout_not_exact_canonical"}
        container_id = parsed_container_id
        insp = _inspect_container(container_id)
        mounts = insp.get("Mounts") or []
        vault_mount_present = any(
            "vault" in str(m.get("Source", "")).lower()
            or "vault" in str(m.get("Destination", "")).lower()
            for m in mounts
        )
        pre = _verify_pre_start(
            insp,
            expected_mounts=[
                {"dest": "/work", "mode": "ro", "source_norm": _norm_win_path(work)},
                {
                    "dest": "/adapter",
                    "mode": "ro",
                    "source_norm": _norm_win_path(adapter_dir),
                },
                {"dest": "/output", "mode": "rw", "source_norm": _norm_win_path(out_dir)},
                {"dest": "/state", "mode": "rw", "source_norm": _norm_win_path(adv_state)},
            ],
            allowed_mount_targets={"/work", "/adapter", "/output", "/state"},
        )
        _run(["docker", "start", "-a", container_id], timeout=60)
        report_path = out_dir / "adversarial_isolation.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        any_readable = bool(report.get("any_readable"))
        ok = (
            pre.get("ok")
            and not vault_mount_present
            and not any_readable
            and not report.get("env_secret_key_names_present")
        )
        return {
            "ok": ok,
            "vault_mount_present": vault_mount_present,
            "any_readable": any_readable,
            "attempts": report.get("attempts") or [],
            "env_secret_key_names_present": report.get("env_secret_key_names_present") or [],
            "pre_start_ok": pre.get("ok"),
            "pre_start": pre,
            "network_mode": pre.get("network_mode"),
            "content_recorded": False,
            "authority": False,
        }
    finally:
        require_terminal_container_cleanup(_docker_rm_exact(name, container_id))


def run_timeout_child_probe(
    *,
    state_root: Path,
    package_owner: str = "g4_hidden_capability_seam_v1",
    host_timeout_s: int = 3,
) -> dict[str, Any]:
    """Exercise timeout/kill: container process tree must not survive; cannot become pass."""
    ident = verify_promptfoo_identity()
    if not ident.get("ok"):
        return {"ok": False, "phase": "identity", **ident}
    state_root = Path(state_root).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    out_dir = state_root / "timeout_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = state_root / "timeout_work"
    work.mkdir(parents=True, exist_ok=True)
    adapter_dir = state_root / "timeout_adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "noop.py").write_text("#\n", encoding="utf-8")
    st = state_root / "timeout_state"
    st.mkdir(parents=True, exist_ok=True)
    name = f"xinao-g4hcs-to-{uuid.uuid4().hex[:12]}"
    container_id = None
    # Sleep longer than host timeout; spawn a child sleep as well
    inner = "sleep 120 & sleep 120; wait"
    try:
        create = _run(
            [
                "docker",
                "create",
                "--name",
                name,
                "--label",
                f"{OWNER_LABEL}.owner={package_owner}",
                "--label",
                f"{OWNER_LABEL}.role=timeout_probe",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                str(PIDS_LIMIT),
                "--mount",
                f"type=bind,src={work},dst=/work,readonly",
                "--mount",
                f"type=bind,src={adapter_dir},dst=/adapter,readonly",
                "--mount",
                f"type=bind,src={out_dir},dst=/output",
                "--mount",
                f"type=bind,src={st},dst=/state",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=33554432",
                PINNED_IMAGE,
                "sh",
                "-c",
                inner,
            ],
            timeout=60,
        )
        if create.returncode != 0:
            return {
                "ok": False,
                "reason": "timeout_probe_create_failed",
                "stderr": (create.stderr or "")[-400:],
            }
        raw_create_stdout = create.stdout or ""
        container_id = raw_create_stdout or "<missing-container-id>"
        parsed_container_id = _container_id_from_create_stdout(raw_create_stdout)
        if parsed_container_id is None:
            return {
                "ok": False,
                "reason": "timeout_probe_create_stdout_not_exact_canonical",
            }
        container_id = parsed_container_id
        timed_out = False
        try:
            _run(["docker", "start", "-a", container_id], timeout=host_timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _run(["docker", "kill", container_id], timeout=30)
            _run(["docker", "stop", "-t", "0", container_id], timeout=30)
        try:
            after = _inspect_container(container_id)
            running = bool((after.get("State") or {}).get("Running"))
            status = (after.get("State") or {}).get("Status")
        except Exception:  # noqa: BLE001
            running = False
            status = "inspect_failed"
        terminal_status = "timeout" if timed_out else "completed"
        promoted_to_pass = False
        # Must not become pass
        ok = timed_out and not running and terminal_status == "timeout" and not promoted_to_pass
        cleanup = _docker_rm_exact(name, container_id)
        cleanup_ok = cleanup.get("ok") is True
        ok = bool(ok and cleanup_ok)
        if cleanup_ok:
            container_id = None  # already cleaned
        return {
            "ok": ok,
            "timed_out": timed_out,
            "running_after_kill": running,
            "state_status": status,
            "terminal_status": terminal_status,
            "promoted_to_pass": promoted_to_pass,
            "cleanup": cleanup,
            "container_absent": cleanup_ok,
            "authority": False,
        }
    finally:
        if container_id:
            require_terminal_container_cleanup(_docker_rm_exact(name, container_id))


def assert_no_inspect_ai() -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.find_spec("inspect_ai")
    return {
        "ok": spec is None,
        "inspect_ai_present": spec is not None,
        "reason": None if spec is None else "inspect_ai_installation_detected",
    }


def python_executable() -> str:
    return CONTAINER_PYTHON


def clean_promptfoo_transients(state_root: Path) -> dict[str, Any]:
    """Remove transient Promptfoo DB/WAL/SHM/log/cache; structured success/failure.

    Silent deletion failures are not treated as success.
    """
    removed: list[str] = []
    failures: list[dict[str, str]] = []
    state_root = Path(state_root)
    if not state_root.exists():
        return {
            "ok": True,
            "removed": removed,
            "failures": failures,
            "count": 0,
        }
    for p in list(state_root.rglob("*")):
        if not p.is_file():
            continue
        name = p.name
        if (
            name in TRANSIENT_FILE_NAMES
            or name.endswith(".log")
            or name.endswith(".pyc")
            or "promptfoo-debug" in name
            or "promptfoo-error" in name
        ):
            try:
                rel = str(p)
                p.unlink()
                removed.append(rel)
            except OSError as exc:
                failures.append(
                    {
                        "path": str(p),
                        "error_class": type(exc).__name__,
                        "action": "unlink",
                    }
                )
    # Remove cache dirs under state root
    for dirpath, dirnames, _filenames in os.walk(state_root, topdown=False):
        base = Path(dirpath)
        for d in dirnames:
            if d in CACHE_DIR_NAMES or d == "cache":
                target = base / d
                try:
                    shutil.rmtree(target)
                    removed.append(str(target))
                except OSError as exc:
                    failures.append(
                        {
                            "path": str(target),
                            "error_class": type(exc).__name__,
                            "action": "rmtree",
                        }
                    )
    return {
        "ok": len(failures) == 0,
        "removed": removed,
        "failures": failures,
        "count": len(removed),
    }


def inventory_forbidden_transients(root: Path) -> dict[str, Any]:
    """Exhaustive post-cleanup inventory for forbidden caches/transients.

    Any retained or inaccessible forbidden transient is failure.
    """
    root = Path(root)
    retained: list[str] = []
    inaccessible: list[str] = []
    if not root.exists():
        return {
            "ok": True,
            "retained": retained,
            "inaccessible": inaccessible,
            "scanned": False,
        }
    try:

        def record_walk_error(exc: OSError) -> None:
            inaccessible.append(str(exc.filename or root))

        for dirpath, dirnames, filenames in os.walk(
            root,
            topdown=True,
            onerror=record_walk_error,
            followlinks=False,
        ):
            for d in list(dirnames):
                if d in CACHE_DIR_NAMES:
                    retained.append(str(Path(dirpath) / d))
            for fn in filenames:
                p = Path(dirpath) / fn
                rel = str(p)
                try:
                    if fn in TRANSIENT_FILE_NAMES or fn.endswith(".pyc"):
                        retained.append(rel)
                    elif fn.endswith(".log") and (
                        "promptfoo" in rel.lower() or "ops" in rel.lower()
                    ):
                        # runtime logs are transients under ops/promptfoo
                        if "promptfoo" in rel.replace("\\", "/").lower():
                            retained.append(rel)
                except OSError:
                    inaccessible.append(rel)
    except OSError as exc:
        return {
            "ok": False,
            "retained": retained,
            "inaccessible": [str(root)],
            "error_class": type(exc).__name__,
            "scanned": False,
        }
    return {
        "ok": len(retained) == 0 and len(inaccessible) == 0,
        "retained": retained,
        "inaccessible": inaccessible,
        "scanned": True,
    }
