"""Fail-closed identity check for the Docker worker's read-only repo mounts."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "xinao.worker_repo_mount_identity.v1"
NAMED_BLOCKER = "WORKER_REPO_MOUNT_MISMATCH"
DEFAULT_CONTAINER = "houtai-gongren"
DEFAULT_SERVICE = "houtai-gongren"
DEFAULT_RUNTIME_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME")
SOURCE_RELEASE_SCHEMA_VERSION = "xinao.s_runtime_source_release.v1"
SOURCE_RELEASE_COMMIT_ENV = "XINAO_S_RUNTIME_RELEASE_COMMIT"
SOURCE_RELEASE_MANIFEST_SHA256_ENV = "XINAO_S_RUNTIME_RELEASE_MANIFEST_SHA256"
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_HASH_RE = re.compile(r"[0-9a-f]{64}")

EXPECTED_REPO_MOUNTS: tuple[tuple[str, str], ...] = (
    ("AGENTS.md", "/app/AGENTS.md"),
    ("services", "/app/services"),
    ("projects", "/app/projects"),
    ("scripts", "/app/scripts"),
    ("docs", "/app/docs"),
    ("evals", "/app/evals"),
    ("pyproject.toml", "/app/pyproject.toml"),
    ("uv.lock", "/app/uv.lock"),
    ("xinao_discovery/src", "/app/xinao_discovery/src"),
    ("tests", "/app/tests"),
    ("materials", "/app/materials"),
    ("policies", "/app/policies"),
)


class SourceReleaseIdentityError(ValueError):
    """The live container declared a release identity that cannot be verified."""


def normalize_windows_host_path(value: str | Path, *, base: str | Path | None = None) -> str:
    """Compare Docker/Compose Windows paths without conflating drive roots."""

    raw = str(value or "").strip().replace("/", "\\")
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    if base is not None and raw and not ntpath.isabs(raw):
        raw = ntpath.join(str(base), raw)
    return ntpath.normcase(ntpath.normpath(raw)).rstrip("\\")


def expected_repo_mounts(repo_root: str | Path) -> dict[str, str]:
    root = normalize_windows_host_path(repo_root, base=os.getcwd())
    return {
        destination: normalize_windows_host_path(relative, base=root)
        for relative, destination in EXPECTED_REPO_MOUNTS
    }


def _destination(mount: Mapping[str, object]) -> str:
    raw = mount.get("Destination") or mount.get("destination") or mount.get("target")
    text = str(raw or "").strip().replace("\\", "/")
    return "/" + text.strip("/") if text else ""


def _source(mount: Mapping[str, object]) -> str:
    return normalize_windows_host_path(str(mount.get("Source") or mount.get("source") or ""))


def _type(mount: Mapping[str, object]) -> str:
    return str(mount.get("Type") or mount.get("type") or "").strip().lower()


def _read_only(mount: Mapping[str, object]) -> bool:
    if isinstance(mount.get("RW"), bool):
        return mount["RW"] is False
    if isinstance(mount.get("read_only"), bool):
        return mount["read_only"] is True
    mode = str(mount.get("Mode") or mount.get("mode") or "").lower().split(",")
    return "ro" in {part.strip() for part in mode}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _environment(values: object) -> dict[str, str]:
    if not isinstance(values, list):
        raise ValueError("docker inspect Config.Env must be an array")
    admitted = {
        SOURCE_RELEASE_COMMIT_ENV,
        SOURCE_RELEASE_MANIFEST_SHA256_ENV,
    }
    environment: dict[str, str] = {}
    for raw in values:
        name, separator, value = str(raw).partition("=")
        if separator and name in admitted:
            environment[name] = value
    return environment


def inspect_container_runtime(container: str = DEFAULT_CONTAINER) -> dict[str, object]:
    """Read mounts and release declaration from one Docker inspect snapshot."""

    completed = subprocess.run(
        ["docker", "inspect", container],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], Mapping):
        raise ValueError("docker inspect must return exactly one container object")
    selected = dict(payload[0])
    config = selected.get("Config")
    if not isinstance(config, Mapping):
        raise ValueError("docker inspect container has no Config object")
    mounts = selected.get("Mounts")
    if not isinstance(mounts, list):
        raise ValueError("docker inspect container has no Mounts array")
    return {
        "container_id": str(selected.get("Id") or ""),
        "environment": _environment(config.get("Env")),
        "mounts": [dict(item) for item in mounts if isinstance(item, Mapping)],
    }


def resolve_expected_repo_identity(
    repo_root: str | Path,
    *,
    runtime_root: str | Path,
    environment: Mapping[str, str],
) -> dict[str, object]:
    """Resolve the live worker source without conflating it with the operator repo."""

    commit = str(environment.get(SOURCE_RELEASE_COMMIT_ENV) or "").strip().lower()
    manifest_sha256 = str(environment.get(SOURCE_RELEASE_MANIFEST_SHA256_ENV) or "").strip().lower()
    if not commit and not manifest_sha256:
        return {
            "mode": "repo_root",
            "expected_repo_root": normalize_windows_host_path(repo_root, base=os.getcwd()),
        }
    if not _COMMIT_RE.fullmatch(commit) or not _HASH_RE.fullmatch(manifest_sha256):
        raise SourceReleaseIdentityError(
            "container source release declaration is incomplete or invalid"
        )

    release_parent = Path(runtime_root) / "state" / "s_runtime_releases"
    release_dir = release_parent / commit
    manifest_path = release_parent / f"{commit}.release-manifest.json"
    if not release_dir.is_dir() or not manifest_path.is_file():
        raise SourceReleaseIdentityError("container source release path or manifest is missing")
    if _sha256(manifest_path) != manifest_sha256:
        raise SourceReleaseIdentityError("container source release manifest hash drifted")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceReleaseIdentityError("container source release manifest is unreadable") from exc
    if not isinstance(manifest, Mapping) or (
        manifest.get("schema_version") != SOURCE_RELEASE_SCHEMA_VERSION
        or manifest.get("commit") != commit
    ):
        raise SourceReleaseIdentityError("container source release manifest identity is invalid")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise SourceReleaseIdentityError("container source release manifest has no file identities")
    for relative, _destination in EXPECTED_REPO_MOUNTS:
        target = release_dir.joinpath(*relative.split("/"))
        if not target.exists():
            raise SourceReleaseIdentityError(
                f"container source release mount target is missing: {relative}"
            )
        if target.is_file():
            covered = isinstance(files.get(relative), Mapping)
        else:
            prefix = relative.rstrip("/") + "/"
            covered = any(str(name).startswith(prefix) for name in files)
        if not covered:
            raise SourceReleaseIdentityError(
                f"container source release manifest omitted mount target: {relative}"
            )
    return {
        "mode": "content_addressed_release",
        "commit": commit,
        "manifest_ref": str(manifest_path.resolve(strict=True)),
        "manifest_sha256": manifest_sha256,
        "expected_repo_root": normalize_windows_host_path(release_dir, base=os.getcwd()),
    }


def validate_worker_repo_mounts(
    expected_repo_root: str | Path,
    mounts: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    expected = expected_repo_mounts(expected_repo_root)
    by_destination: dict[str, list[Mapping[str, object]]] = {}
    for mount in mounts:
        destination = _destination(mount)
        if destination:
            by_destination.setdefault(destination, []).append(mount)

    issues: list[dict[str, object]] = []
    verified: list[dict[str, object]] = []
    for destination, expected_source in expected.items():
        observed = by_destination.get(destination, [])
        if not observed:
            issues.append({"code": "MISSING_MOUNT", "destination": destination})
            continue
        if len(observed) != 1:
            issues.append(
                {
                    "code": "DUPLICATE_MOUNT",
                    "destination": destination,
                    "observed_count": len(observed),
                }
            )
            continue
        mount = observed[0]
        observed_source = _source(mount)
        if _type(mount) != "bind":
            issues.append(
                {
                    "code": "NON_BIND_MOUNT",
                    "destination": destination,
                    "observed_type": _type(mount),
                }
            )
        if observed_source != expected_source:
            issues.append(
                {
                    "code": "SOURCE_MISMATCH",
                    "destination": destination,
                    "expected_source": expected_source,
                    "observed_source": observed_source,
                }
            )
        if not _read_only(mount):
            issues.append({"code": "MOUNT_NOT_READ_ONLY", "destination": destination})
        if _type(mount) == "bind" and observed_source == expected_source and _read_only(mount):
            verified.append(
                {
                    "destination": destination,
                    "source": observed_source,
                    "read_only": True,
                }
            )

    for destination in sorted(by_destination):
        if destination == "/app" or (
            destination.startswith("/app/") and destination not in expected
        ):
            issues.append({"code": "UNEXPECTED_APP_MOUNT", "destination": destination})

    ok = not issues and len(verified) == len(expected)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "named_blocker": None if ok else NAMED_BLOCKER,
        "provider_invocation_allowed": ok,
        "expected_repo_root": normalize_windows_host_path(
            expected_repo_root,
            base=os.getcwd(),
        ),
        "expected_mount_count": len(expected),
        "verified_mount_count": len(verified),
        "observed_app_mount_count": sum(
            len(value) for key, value in by_destination.items() if key.startswith("/app")
        ),
        "issues": issues,
        "verified_mounts": verified,
    }


def inspect_container_mounts(container: str = DEFAULT_CONTAINER) -> list[dict[str, object]]:
    return list(inspect_container_runtime(container)["mounts"])


def inspect_compose_mounts(
    compose_file: str | Path,
    *,
    service: str = DEFAULT_SERVICE,
) -> list[dict[str, object]]:
    compose_path = Path(compose_file).resolve()
    env = dict(os.environ)
    env.setdefault("LITELLM_MASTER_KEY", "mount-preflight-not-used")
    completed = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config", "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        cwd=compose_path.parent,
        env=env,
    )
    payload = json.loads(completed.stdout)
    services = payload.get("services") if isinstance(payload, Mapping) else None
    selected = services.get(service) if isinstance(services, Mapping) else None
    mounts = selected.get("volumes") if isinstance(selected, Mapping) else None
    if not isinstance(mounts, list):
        raise ValueError(f"compose service {service!r} has no volume array")
    return [dict(item) for item in mounts if isinstance(item, Mapping)]


def _inspection_failure_report(
    exc: BaseException,
    *,
    code: str = "MOUNT_INSPECTION_FAILED",
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "named_blocker": NAMED_BLOCKER,
        "provider_invocation_allowed": False,
        "issues": [{"code": code, "message": str(exc)[:400]}],
    }


def actual_mount_report(
    repo_root: str | Path,
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    container: str = DEFAULT_CONTAINER,
) -> dict[str, Any]:
    try:
        runtime = inspect_container_runtime(container)
        environment = runtime.get("environment")
        mounts = runtime.get("mounts")
        if not isinstance(environment, Mapping) or not isinstance(mounts, list):
            raise ValueError("docker inspect runtime snapshot is incomplete")
        source_identity = resolve_expected_repo_identity(
            repo_root,
            runtime_root=runtime_root,
            environment={str(key): str(value) for key, value in environment.items()},
        )
        report = validate_worker_repo_mounts(
            str(source_identity["expected_repo_root"]),
            [dict(item) for item in mounts if isinstance(item, Mapping)],
        )
        report["source_identity"] = source_identity
        report["container_id"] = str(runtime.get("container_id") or "")
        return report
    except SourceReleaseIdentityError as exc:
        return _inspection_failure_report(exc, code="SOURCE_RELEASE_IDENTITY_INVALID")
    except (
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        return _inspection_failure_report(exc)


def compose_mount_report(
    repo_root: str | Path,
    compose_file: str | Path,
    *,
    service: str = DEFAULT_SERVICE,
) -> dict[str, Any]:
    try:
        return validate_worker_repo_mounts(
            repo_root,
            inspect_compose_mounts(compose_file, service=service),
        )
    except (
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return _inspection_failure_report(exc)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--mode", choices=("compose", "actual"), required=True)
    parser.add_argument("--compose-file")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    args = parser.parse_args(argv)
    if args.mode == "compose":
        if not args.compose_file:
            parser.error("--compose-file is required for compose mode")
        report = compose_mount_report(
            args.repo_root,
            args.compose_file,
            service=args.service,
        )
    else:
        report = actual_mount_report(
            args.repo_root,
            runtime_root=args.runtime_root,
            container=args.container,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("ok") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_REPO_MOUNTS",
    "NAMED_BLOCKER",
    "SOURCE_RELEASE_COMMIT_ENV",
    "SourceReleaseIdentityError",
    "SOURCE_RELEASE_MANIFEST_SHA256_ENV",
    "SOURCE_RELEASE_SCHEMA_VERSION",
    "actual_mount_report",
    "compose_mount_report",
    "expected_repo_mounts",
    "inspect_compose_mounts",
    "inspect_container_mounts",
    "inspect_container_runtime",
    "normalize_windows_host_path",
    "resolve_expected_repo_identity",
    "validate_worker_repo_mounts",
]
