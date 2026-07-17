"""Fail-closed identity check for the Docker worker's read-only repo mounts."""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "xinao.worker_repo_mount_identity.v1"
NAMED_BLOCKER = "WORKER_REPO_MOUNT_MISMATCH"
DEFAULT_CONTAINER = "houtai-gongren"
DEFAULT_SERVICE = "houtai-gongren"

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
    completed = subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .Mounts}}"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list):
        raise ValueError("docker inspect mounts must be an array")
    return [dict(item) for item in payload if isinstance(item, Mapping)]


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


def _inspection_failure_report(exc: BaseException) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "named_blocker": NAMED_BLOCKER,
        "provider_invocation_allowed": False,
        "issues": [{"code": "MOUNT_INSPECTION_FAILED", "message": str(exc)[:400]}],
    }


def actual_mount_report(
    repo_root: str | Path,
    *,
    container: str = DEFAULT_CONTAINER,
) -> dict[str, Any]:
    try:
        return validate_worker_repo_mounts(
            repo_root,
            inspect_container_mounts(container),
        )
    except (
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
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
        report = actual_mount_report(args.repo_root, container=args.container)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("ok") is True else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_REPO_MOUNTS",
    "NAMED_BLOCKER",
    "actual_mount_report",
    "compose_mount_report",
    "expected_repo_mounts",
    "inspect_compose_mounts",
    "inspect_container_mounts",
    "normalize_windows_host_path",
    "validate_worker_repo_mounts",
]
