#!/usr/bin/env python3
"""Build, verify, and run the self-carried F4 portable closure pack.

The copied script in a built pack is the only moved-pack entry point.  Verify
and run derive their pack root from ``__file__`` and never dereference retained
absolute paths from the frozen provenance JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import secrets
import shutil
import stat
import subprocess
import tarfile
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

MANIFEST_NAME = "portable_closure_manifest.json"
BASELINE_RELATIVE = "baseline/portable_baseline.json"
RUNNER_NAME = "f4_portable_closure.py"
IMAGE_TAR_RELATIVE = "runtime/f4-verifier-image.tar"
SNAPSHOT_RELATIVE = "snapshot"
FOUNDATION_RELATIVE = "foundation"
BLUEPRINT_RELATIVE = "external_inputs/blueprint.json"
FROZEN_RELATIVE = "provenance/frozen_inputs.v1.json"
EXECUTION_RELATIVE = "provenance/canonical_execution_receipt.json"
AUTHORITY_RELATIVE = "provenance/authority_source_manifest.json"

PACK_SCHEMA = "xinao.f4_portable_closure_pack.v1"
BASELINE_SCHEMA = "xinao.f4_portable_closure_baseline.v2"
BUILD_RECEIPT_SCHEMA = "xinao.f4_portable_closure_build_receipt.v1"
RUN_RECEIPT_SCHEMA = "xinao.f4_portable_closure_execution_receipt.v2"
OCI_EXECUTION_RECEIPT_SCHEMA = "xinao.f4_oci_execution_receipt.v2"
ASSERTION_BUNDLE_RELATIVE = "f4_assertion_actual_bundle.v2.json"
OWNER_LABEL = "io.xinao.f4.portable.owner"
RUN_LABEL = "io.xinao.f4.portable.run"
OCI_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
OCI_MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
OCI_CONFIG_MEDIA_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}

EXPECTED_ENTRYPOINT = [
    "/opt/f4-runtime/.venv/bin/python",
    "-I",
    "/opt/xinao-authority/scripts/run_f4_snapshot_stage0.py",
]
EXPECTED_CMD = ["run"]
EXPECTED_SEMANTIC_PATHS = {
    ASSERTION_BUNDLE_RELATIVE,
    "snapshot_trace_summary.json",
    "stage0_result.json",
}
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
SOURCE_ANCHOR_KEYS = (
    "frozen_file_sha256",
    "frozen_content_sha256",
    "canonical_execution_file_sha256",
    "canonical_execution_content_sha256",
    "data_manifest_file_sha256",
    "data_manifest_content_sha256",
    "foundation_manifest_file_sha256",
    "foundation_pack_sha256",
    "foundation_physical_inventory_sha256",
    "blueprint_file_sha256",
)


class PortableClosureError(RuntimeError):
    """Raised when the portable closure identity or runtime contract drifts."""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise PortableClosureError(message)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    path = _assert_no_lexical_reparse(path, label="hashed file")
    _require(path.is_file(), f"hashed file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_canonical(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(dict(value)))


def _publish_file_no_clobber(source: Path, destination: Path) -> None:
    linked = False
    try:
        os.link(source, destination)
        linked = True
        source.unlink()
    except FileExistsError as exc:
        raise PortableClosureError(
            f"publish destination appeared concurrently: {destination}"
        ) from exc
    except Exception:
        if linked:
            destination.unlink(missing_ok=True)
        raise


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    path = _assert_no_lexical_reparse(path, label=label)
    _require(path.is_file(), f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortableClosureError(f"{label} is invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"{label} is not a JSON object")
    return value


def _content_addressed(
    value: Mapping[str, Any], *, label: str, field: str = "content_sha256"
) -> str:
    core = dict(value)
    recorded = str(core.pop(field, ""))
    _require(
        len(recorded) == 64 and recorded == _canonical_sha256(core),
        f"{label} content identity drifted",
    )
    return recorded


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = int(getattr(info, "st_file_attributes", 0))
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _assert_no_lexical_reparse(path: Path, *, label: str) -> Path:
    """Reject existing lexical reparse ancestors before resolving can hide them."""

    lexical = Path(os.path.abspath(str(path)))
    current = lexical
    while True:
        try:
            os.lstat(current)
        except FileNotFoundError:
            pass
        else:
            _require(not _is_reparse(current), f"{label} contains a reparse point: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent
    return lexical


def _relative(value: object, *, label: str) -> str:
    raw = str(value or "")
    _require(raw == raw.strip() and raw, f"{label} is empty or padded")
    _require(raw == unicodedata.normalize("NFC", raw), f"{label} is not NFC: {raw!r}")
    _require("\\" not in raw, f"{label} uses a backslash: {raw}")
    _require(":" not in raw, f"{label} contains a colon: {raw}")
    path = PurePosixPath(raw)
    _require(not path.is_absolute(), f"{label} is absolute: {raw}")
    _require(
        path.as_posix() == raw and all(part not in {"", ".", ".."} for part in path.parts),
        f"{label} is not canonical: {raw}",
    )
    for part in path.parts:
        _require(not part.endswith((".", " ")), f"{label} has an ambiguous suffix: {raw}")
        _require(
            part.split(".", 1)[0].upper() not in WINDOWS_RESERVED,
            f"{label} uses a Windows reserved name: {raw}",
        )
    return raw


def _path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _walk_regular_files(root: Path) -> Iterable[Path]:
    lexical = _assert_no_lexical_reparse(root, label="tree root")
    _require(lexical.is_dir(), f"tree root is missing: {lexical}")
    seen: dict[str, str] = {}
    for directory, names, files in os.walk(lexical, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(names):
            candidate = directory_path / name
            _require(not _is_reparse(candidate), f"tree directory is a reparse point: {candidate}")
            relative = _relative(candidate.relative_to(lexical).as_posix(), label="tree directory")
            prior = seen.get(_path_key(relative))
            _require(prior is None, f"tree path collision: {prior} / {relative}")
            seen[_path_key(relative)] = relative
        for name in sorted(files):
            candidate = directory_path / name
            _require(not _is_reparse(candidate), f"tree file is a reparse point: {candidate}")
            _require(candidate.is_file(), f"tree object is not a regular file: {candidate}")
            relative = _relative(candidate.relative_to(lexical).as_posix(), label="tree file")
            prior = seen.get(_path_key(relative))
            _require(prior is None, f"tree path collision: {prior} / {relative}")
            seen[_path_key(relative)] = relative
            yield candidate


def _inventory(root: Path, *, excluded: Iterable[str] = ()) -> list[dict[str, Any]]:
    excluded_set = set(excluded)
    rows = []
    for path in _walk_regular_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in excluded_set:
            continue
        rows.append(
            {
                "relative_path": relative,
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    rows.sort(key=lambda item: str(item["relative_path"]))
    return rows


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _overlaps(left: Path, right: Path) -> bool:
    return _inside(left, right) or _inside(right, left)


def _validate_new_root(path: Path, *, label: str, protected: Iterable[Path]) -> Path:
    lexical = _assert_no_lexical_reparse(path, label=label)
    _require(not lexical.exists(), f"{label} already exists: {lexical}")
    _require(
        not any(_overlaps(lexical, item) for item in protected),
        f"{label} overlaps a protected input",
    )
    _require("," not in str(lexical), f"{label} contains an unsupported comma")
    return lexical


def _copy_tree(source: Path, destination: Path) -> None:
    source = _assert_no_lexical_reparse(source, label="copy source")
    _require(source.is_dir(), f"copy source is missing: {source}")
    _require(not destination.exists(), f"copy destination already exists: {destination}")
    destination.mkdir(parents=True)
    for path in _walk_regular_files(source):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    _require(_inventory(source) == _inventory(destination), "copied tree bytes drifted")


def _file_ref(path: Path, *, relative_path: str) -> dict[str, Any]:
    return {
        "relative_path": _relative(relative_path, label="file ref"),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _require_file_ref(root: Path, raw: Mapping[str, Any], *, label: str) -> Path:
    relative = _relative(raw.get("relative_path"), label=f"{label} relative path")
    path = _assert_no_lexical_reparse(root / PurePosixPath(relative), label=f"{label} active path")
    _require(path.is_file(), f"{label} is missing: {relative}")
    _require(
        raw.get("sha256") == _file_sha256(path) and raw.get("size_bytes") == path.stat().st_size,
        f"{label} bytes drifted: {relative}",
    )
    return path


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 1800,
    require_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        shell=False,
        timeout=timeout,
        check=False,
    )
    if require_success:
        _require(
            completed.returncode == 0,
            f"command failed ({completed.returncode}): {argv!r}\n"
            f"{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}",
        )
    return completed


def _docker_inspect(kind: str, identity: str, *, cwd: Path) -> dict[str, Any]:
    raw = _run(["docker", kind, "inspect", identity], cwd=cwd).stdout
    value = json.loads(raw)
    _require(isinstance(value, list) and len(value) == 1, f"docker {kind} inspect drifted")
    _require(isinstance(value[0], dict), f"docker {kind} inspect returned no object")
    return value[0]


def _docker_scalar(argv: list[str], *, cwd: Path, label: str) -> str:
    completed = _run(argv, cwd=cwd, timeout=120, require_success=False)
    _require(
        completed.returncode == 0,
        f"docker fingerprint query failed ({label}): {completed.stderr[-1000:]}",
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    _require(len(lines) == 1 and "\t" not in lines[0], f"docker {label} query drifted")
    return lines[0]


def _daemon_fingerprint(*, cwd: Path) -> dict[str, str]:
    context = _docker_scalar(["docker", "context", "show"], cwd=cwd, label="fingerprint context")
    endpoint = _docker_scalar(
        [
            "docker",
            "context",
            "inspect",
            context,
            "--format",
            "{{.Endpoints.docker.Host}}",
        ],
        cwd=cwd,
        label="fingerprint endpoint",
    )
    daemon_id = _docker_scalar(
        ["docker", "info", "--format", "{{.ID}}"],
        cwd=cwd,
        label="fingerprint daemon",
    )
    core = {
        "context": context,
        "docker_endpoint": endpoint,
        "daemon_id": daemon_id,
    }
    return {**core, "content_sha256": _canonical_sha256(core)}


def _require_same_daemon(*, expected: Mapping[str, Any], cwd: Path, operation: str) -> None:
    observed = _daemon_fingerprint(cwd=cwd)
    _require(
        observed == expected,
        f"docker daemon identity drifted before {operation}",
    )


def _normalize_image_id(value: object, *, label: str) -> str:
    normalized = str(value or "").lower()
    _require(
        normalized.startswith("sha256:")
        and len(normalized) == 71
        and all(character in "0123456789abcdef" for character in normalized[7:]),
        f"{label} is not a full sha256 image ID",
    )
    return normalized


def _daemon_image_inventory(*, cwd: Path) -> list[dict[str, str | None]]:
    argv = [
        "docker",
        "image",
        "ls",
        "--all",
        "--no-trunc",
        "--format",
        "{{.ID}}\t{{.Repository}}\t{{.Tag}}",
    ]
    completed = _run(argv, cwd=cwd, timeout=120, require_success=False)
    _require(
        completed.returncode == 0,
        "docker image inventory query failed; pre-load state is not proven: "
        f"{completed.stderr[-1000:]}",
    )
    rows: list[dict[str, str | None]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        _require(len(fields) == 3, "docker image inventory row drifted")
        image_id = _normalize_image_id(fields[0], label="docker image inventory identity")
        repository, tag = fields[1:]
        _require(repository and tag, "docker image inventory tag fields are empty")
        _require(
            tag == "<none>" or repository != "<none>",
            "docker image inventory contains a named tag without a repository",
        )
        repo_tag = None if tag == "<none>" else f"{repository}:{tag}"
        rows.append(
            {
                "image_id": image_id,
                "repository": repository,
                "tag": tag,
                "repo_tag": repo_tag,
            }
        )
    rows.sort(
        key=lambda item: (
            str(item["image_id"]),
            str(item["repository"]),
            str(item["tag"]),
        )
    )
    _require(
        len({_canonical_sha256(item) for item in rows}) == len(rows),
        "docker image inventory contains duplicate rows",
    )
    return rows


def _prove_preload_image_state(
    *,
    image_id: str,
    sealed_repo_tags: Iterable[str],
    require_image_absent: bool,
    cwd: Path,
) -> dict[str, Any]:
    expected = _normalize_image_id(image_id, label="expected image identity")
    raw_tags = [str(item) for item in sealed_repo_tags]
    _require(
        len(raw_tags) == len(set(raw_tags))
        and all(tag and "\t" not in tag and "\n" not in tag for tag in raw_tags),
        "sealed RepoTags are invalid or duplicated",
    )
    tags = sorted(raw_tags)
    rows = _daemon_image_inventory(cwd=cwd)
    image_ids = {str(item["image_id"]) for item in rows}
    by_tag: dict[str, set[str]] = {}
    for row in rows:
        repo_tag = row["repo_tag"]
        if repo_tag is not None:
            by_tag.setdefault(str(repo_tag), set()).add(str(row["image_id"]))
    bindings: list[dict[str, Any]] = []
    for repo_tag in tags:
        bound_ids = sorted(by_tag.get(repo_tag, set()))
        _require(
            not (set(bound_ids) - {expected}),
            f"sealed RepoTag is bound to a foreign image: {repo_tag}",
        )
        bindings.append(
            {
                "repo_tag": repo_tag,
                "image_ids": bound_ids,
                "status": "expected-image" if bound_ids else "absent",
            }
        )
    expected_present = expected in image_ids
    _require(
        not require_image_absent
        or (not expected_present and all(not item["image_ids"] for item in bindings)),
        "portable run required an image-absent daemon but the image ID or a sealed RepoTag "
        "already exists",
    )
    return {
        "query_status": "VERIFIED",
        "row_count": len(rows),
        "unique_image_id_count": len(image_ids),
        "inventory_sha256": _canonical_sha256(rows),
        "expected_image_present": expected_present,
        "sealed_repo_tag_bindings": bindings,
    }


def _image_identity(image: Mapping[str, Any]) -> dict[str, Any]:
    config = image.get("Config")
    _require(isinstance(config, dict), "image Config is absent")
    identity = {
        "id": str(image.get("Id") or ""),
        "os": str(image.get("Os") or ""),
        "architecture": str(image.get("Architecture") or ""),
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "working_dir": config.get("WorkingDir"),
        "user": config.get("User"),
        "environment": config.get("Env"),
        "labels": config.get("Labels"),
    }
    _require(
        identity["id"].startswith("sha256:")
        and len(identity["id"]) == 71
        and identity["entrypoint"] == EXPECTED_ENTRYPOINT
        and identity["cmd"] == EXPECTED_CMD
        and identity["working_dir"] == "/work"
        and identity["user"] == "65532:65532"
        and isinstance(identity["environment"], list)
        and isinstance(identity["labels"], dict),
        "image fixed identity drifted",
    )
    _require(
        not any(str(item).upper().startswith("XINAO_F4_") for item in identity["environment"]),
        "image contains an overridable XINAO_F4 environment",
    )
    return identity


def _tar_member_relative(name: str, *, label: str) -> str:
    raw = name[:-1] if name.endswith("/") else name
    _require(raw and not raw.startswith(("/", "//")), f"{label} is absolute: {name}")
    _require(not ntpath.isabs(raw), f"{label} is Windows absolute: {name}")
    return _relative(raw, label=label)


def _tar_member_bytes(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    label: str,
    maximum_size: int = 16 * 1024 * 1024,
) -> bytes:
    _require(member.isfile(), f"{label} is not a regular file")
    _require(member.size <= maximum_size, f"{label} is too large to parse")
    stream = archive.extractfile(member)
    _require(stream is not None, f"{label} is unreadable")
    body = stream.read(maximum_size + 1)
    _require(len(body) == member.size, f"{label} size changed while reading")
    return body


def _tar_member_sha256(archive: tarfile.TarFile, member: tarfile.TarInfo, *, label: str) -> str:
    _require(member.isfile(), f"{label} is not a regular file")
    stream = archive.extractfile(member)
    _require(stream is not None, f"{label} is unreadable")
    digest = hashlib.sha256()
    size = 0
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
        size += len(block)
    _require(size == member.size, f"{label} size changed while hashing")
    return digest.hexdigest()


def _oci_descriptor(raw: object, *, label: str) -> dict[str, Any]:
    _require(isinstance(raw, dict), f"{label} is not an object")
    media_type = raw.get("mediaType")
    size = raw.get("size")
    _require(
        isinstance(media_type, str)
        and bool(media_type)
        and "\t" not in media_type
        and "\n" not in media_type,
        f"{label} mediaType is invalid",
    )
    raw_digest = raw.get("digest")
    _require(isinstance(raw_digest, str), f"{label} digest is not a string")
    digest = _normalize_image_id(raw_digest, label=f"{label} digest")
    _require(
        raw_digest == digest,
        f"{label} digest is not canonical lowercase sha256",
    )
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size >= 0,
        f"{label} size is invalid",
    )
    value: dict[str, Any] = {
        "media_type": media_type,
        "digest": digest,
        "size": size,
        "member": f"blobs/sha256/{digest.removeprefix('sha256:')}",
    }
    platform = raw.get("platform")
    if platform is not None:
        _require(isinstance(platform, dict), f"{label} platform is invalid")
        _require(
            all(isinstance(key, str) for key in platform)
            and isinstance(platform.get("architecture"), str)
            and isinstance(platform.get("os"), str),
            f"{label} platform identity is invalid",
        )
        value["platform"] = json.loads(_canonical_bytes(platform))
    annotations = raw.get("annotations")
    if annotations is not None:
        _require(
            isinstance(annotations, dict)
            and all(
                isinstance(key, str) and isinstance(item, str) for key, item in annotations.items()
            ),
            f"{label} annotations are invalid",
        )
        value["annotations"] = dict(sorted(annotations.items()))
    return value


def _audit_oci_descriptor_graph(
    *,
    archive: tarfile.TarFile,
    members_by_name: Mapping[str, tarfile.TarInfo],
    subject_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    payloads: dict[str, dict[str, Any]] = {}
    visiting: set[str] = set()
    completed: set[str] = set()
    manifest_references: list[dict[str, Any]] = []

    def visit(descriptor: Mapping[str, Any], *, label: str, depth: int = 0) -> None:
        _require(depth <= 64, "OCI descriptor graph exceeds the maximum depth")
        digest = str(descriptor["digest"])
        core = {key: descriptor[key] for key in ("media_type", "digest", "size", "member")}
        prior = nodes.get(digest)
        if prior is not None:
            _require(
                all(prior[key] == core[key] for key in core),
                f"OCI descriptor identity conflicts for {digest}",
            )
        _require(digest not in visiting, f"OCI descriptor graph contains a cycle at {digest}")
        if digest in completed:
            return
        _require(
            digest in nodes or len(nodes) < 4096,
            "OCI descriptor graph exceeds the maximum node count",
        )
        member = members_by_name.get(str(descriptor["member"]))
        _require(
            member is not None and member.isfile(), f"OCI descriptor member is absent: {digest}"
        )
        _require(
            member.size == descriptor["size"],
            f"OCI descriptor size drifted: {digest}",
        )
        _require(
            _tar_member_sha256(archive, member, label=f"OCI descriptor {digest}")
            == digest.removeprefix("sha256:"),
            f"OCI descriptor digest drifted: {digest}",
        )
        node = {
            **core,
            "kind": "blob",
            "children": [],
        }
        nodes[digest] = node
        visiting.add(digest)
        media_type = str(descriptor["media_type"])
        if media_type in OCI_INDEX_MEDIA_TYPES | OCI_MANIFEST_MEDIA_TYPES:
            body = _tar_member_bytes(
                archive,
                member,
                label=f"OCI JSON descriptor {digest}",
            )
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PortableClosureError(f"OCI JSON descriptor is invalid: {digest}") from exc
            _require(isinstance(payload, dict), f"OCI JSON descriptor is not an object: {digest}")
            _require(
                payload.get("schemaVersion") == 2 and payload.get("mediaType") == media_type,
                f"OCI JSON descriptor schema or mediaType drifted: {digest}",
            )
            payloads[digest] = payload
            if media_type in OCI_INDEX_MEDIA_TYPES:
                node["kind"] = "index"
                children = payload.get("manifests")
                _require(isinstance(children, list) and children, f"OCI index is empty: {digest}")
                normalized_children = [
                    _oci_descriptor(item, label=f"OCI index {digest} child {index}")
                    for index, item in enumerate(children)
                ]
                _require(
                    len({item["digest"] for item in normalized_children})
                    == len(normalized_children),
                    f"OCI index contains duplicate descriptors: {digest}",
                )
                for child in normalized_children:
                    node["children"].append({"role": "manifest", "digest": child["digest"]})
                    if child["media_type"] in OCI_MANIFEST_MEDIA_TYPES:
                        manifest_references.append(child)
                    visit(
                        child,
                        label=f"OCI index child of {digest}",
                        depth=depth + 1,
                    )
            else:
                node["kind"] = "manifest"
                config = _oci_descriptor(
                    payload.get("config"), label=f"OCI manifest {digest} config"
                )
                layers_raw = payload.get("layers")
                _require(isinstance(layers_raw, list), f"OCI manifest layers are absent: {digest}")
                layers = [
                    _oci_descriptor(item, label=f"OCI manifest {digest} layer {index}")
                    for index, item in enumerate(layers_raw)
                ]
                child_rows = [("config", config), *(("layer", item) for item in layers)]
                subject = payload.get("subject")
                if subject is not None:
                    child_rows.append(
                        (
                            "subject",
                            _oci_descriptor(subject, label=f"OCI manifest {digest} subject"),
                        )
                    )
                for role, child in child_rows:
                    node["children"].append({"role": role, "digest": child["digest"]})
                    visit(
                        child,
                        label=f"OCI manifest {role} of {digest}",
                        depth=depth + 1,
                    )
        visiting.remove(digest)
        completed.add(digest)

    normalized_subject = dict(subject_descriptor)
    if normalized_subject["media_type"] in OCI_MANIFEST_MEDIA_TYPES:
        manifest_references.append(normalized_subject)
    visit(normalized_subject, label="OCI subject descriptor")
    blob_members = {
        name
        for name, member in members_by_name.items()
        if member.isfile() and name.startswith("blobs/sha256/")
    }
    reachable_members = {str(item["member"]) for item in nodes.values()}
    _require(
        blob_members == reachable_members,
        "OCI archive contains unreferenced or unreachable blob members",
    )
    candidates: dict[str, dict[str, Any]] = {}
    for reference in manifest_references:
        platform = reference.get("platform")
        annotations = reference.get("annotations") or {}
        if not isinstance(platform, dict):
            continue
        if platform.get("os") != "linux" or platform.get("architecture") != "amd64":
            continue
        if annotations.get("vnd.docker.reference.type") == "attestation-manifest":
            continue
        manifest_payload = payloads.get(str(reference["digest"]))
        _require(manifest_payload is not None, "runnable manifest payload is absent")
        config = _oci_descriptor(manifest_payload.get("config"), label="runnable manifest config")
        if config["media_type"] not in OCI_CONFIG_MEDIA_TYPES:
            continue
        config_member = members_by_name[str(config["member"])]
        config_bytes = _tar_member_bytes(archive, config_member, label="runnable image config")
        try:
            config_payload = json.loads(config_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortableClosureError("runnable image config is invalid JSON") from exc
        _require(isinstance(config_payload, dict), "runnable image config is not an object")
        if config_payload.get("os") != "linux" or config_payload.get("architecture") != "amd64":
            continue
        candidates[str(reference["digest"])] = {
            "descriptor": reference,
            "payload": manifest_payload,
            "config": config,
            "config_payload": config_payload,
        }
    _require(
        len(candidates) == 1,
        "OCI runnable linux/amd64 manifest selection is not unique",
    )
    selected = next(iter(candidates.values()))
    layers_raw = selected["payload"].get("layers")
    _require(isinstance(layers_raw, list) and layers_raw, "runnable manifest has no layers")
    layers = [
        _oci_descriptor(item, label=f"runnable manifest layer {index}")
        for index, item in enumerate(layers_raw)
    ]
    graph_rows = sorted(nodes.values(), key=lambda item: str(item["digest"]))
    return {
        "subject_descriptor": normalized_subject,
        "runnable_manifest": selected["descriptor"],
        "config": selected["config"],
        "config_payload": selected["config_payload"],
        "layers": layers,
        "descriptor_count": len(graph_rows),
        "reachable_blob_count": len(reachable_members),
        "unreferenced_blob_count": len(blob_members - reachable_members),
        "descriptor_graph_sha256": _canonical_sha256(graph_rows),
    }


def _audit_image_tar(path: Path, *, image_id: str, image_ref: str) -> dict[str, Any]:
    path = _assert_no_lexical_reparse(path, label="image archive")
    _require(path.is_file(), f"image archive is missing: {path}")
    expected_image_id = _normalize_image_id(image_id, label="frozen image ID")
    _require(
        bool(image_ref) and "\t" not in image_ref and "\n" not in image_ref,
        "frozen image ref is invalid",
    )
    seen: dict[str, str] = {}
    members_by_name: dict[str, tarfile.TarInfo] = {}
    with tarfile.open(path, mode="r:*") as archive:
        members = archive.getmembers()
        _require(members, "image archive is empty")
        for member in members:
            relative = _tar_member_relative(member.name, label="image archive member")
            key = _path_key(relative)
            prior = seen.get(key)
            _require(prior is None, f"image archive member collision: {prior} / {relative}")
            seen[key] = relative
            _require(
                member.isfile() or member.isdir(),
                f"image archive contains a link or special object: {relative}",
            )
            members_by_name[relative] = member
        required_roots = {
            name: members_by_name.get(name)
            for name in ("oci-layout", "index.json", "manifest.json")
        }
        _require(
            all(member is not None and member.isfile() for member in required_roots.values()),
            "OCI archive root metadata is incomplete",
        )
        try:
            layout = json.loads(
                _tar_member_bytes(archive, required_roots["oci-layout"], label="OCI layout").decode(
                    "utf-8"
                )
            )
            index = json.loads(
                _tar_member_bytes(
                    archive, required_roots["index.json"], label="OCI root index"
                ).decode("utf-8")
            )
            manifest = json.loads(
                _tar_member_bytes(
                    archive, required_roots["manifest.json"], label="docker compatibility manifest"
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortableClosureError("OCI archive root metadata is invalid JSON") from exc
        _require(
            layout == {"imageLayoutVersion": "1.0.0"},
            "OCI layout version or shape drifted",
        )
        _require(
            isinstance(index, dict)
            and index.get("schemaVersion") == 2
            and index.get("mediaType") in OCI_INDEX_MEDIA_TYPES
            and isinstance(index.get("manifests"), list)
            and len(index["manifests"]) == 1,
            "OCI root index does not contain exactly one subject descriptor",
        )
        subject = _oci_descriptor(index["manifests"][0], label="OCI root subject descriptor")
        _require(
            subject["digest"] == expected_image_id,
            "OCI subject descriptor does not equal the frozen image ID",
        )
        graph = _audit_oci_descriptor_graph(
            archive=archive,
            members_by_name=members_by_name,
            subject_descriptor=subject,
        )
        _require(
            isinstance(manifest, list) and len(manifest) == 1,
            "docker compatibility image count is not one",
        )
        record = manifest[0]
        _require(isinstance(record, dict), "docker manifest record is invalid")
        config_name = _tar_member_relative(
            record.get("Config"), label="docker compatibility config member"
        )
        layers_raw = record.get("Layers")
        _require(
            isinstance(layers_raw, list) and layers_raw,
            "docker compatibility layer list is absent",
        )
        legacy_layers = [
            _tar_member_relative(item, label="docker compatibility layer member")
            for item in layers_raw
        ]
        _require(
            len(set(legacy_layers)) == len(legacy_layers),
            "docker compatibility layer list contains duplicates",
        )
        repo_tags = record.get("RepoTags")
        _require(
            isinstance(repo_tags, list)
            and repo_tags == [image_ref]
            and all(isinstance(item, str) and item for item in repo_tags),
            "docker compatibility RepoTags are empty or differ from the frozen image ref",
        )
        expected_config_member = str(graph["config"]["member"])
        expected_layer_members = [str(item["member"]) for item in graph["layers"]]
        _require(
            config_name == expected_config_member,
            "docker compatibility config differs from the runnable OCI manifest",
        )
        _require(
            legacy_layers == expected_layer_members,
            "docker compatibility layers differ from the runnable OCI manifest",
        )
        archive_layout = {
            "kind": "oci-image-layout-v1",
            "image_layout_version": "1.0.0",
            "oci_layout_member": "oci-layout",
            "oci_layout_sha256": _tar_member_sha256(
                archive, required_roots["oci-layout"], label="OCI layout"
            ),
            "index_member": "index.json",
            "index_sha256": _tar_member_sha256(
                archive, required_roots["index.json"], label="OCI root index"
            ),
            "docker_compatibility_manifest_member": "manifest.json",
            "docker_compatibility_manifest_sha256": _tar_member_sha256(
                archive,
                required_roots["manifest.json"],
                label="docker compatibility manifest",
            ),
        }
    return {
        "member_count": len(members_by_name),
        "member_name_set_sha256": _canonical_sha256(sorted(members_by_name)),
        "archive_layout": archive_layout,
        "subject_descriptor": graph["subject_descriptor"],
        "runnable_manifest": graph["runnable_manifest"],
        "config": {
            **graph["config"],
            "architecture": graph["config_payload"]["architecture"],
            "os": graph["config_payload"]["os"],
        },
        "layers": graph["layers"],
        "descriptor_count": graph["descriptor_count"],
        "reachable_blob_count": graph["reachable_blob_count"],
        "unreferenced_blob_count": graph["unreferenced_blob_count"],
        "descriptor_graph_sha256": graph["descriptor_graph_sha256"],
        "config_member": config_name,
        "config_sha256": str(graph["config"]["digest"]).removeprefix("sha256:"),
        "layer_count": len(graph["layers"]),
        "layer_name_set_sha256": _canonical_sha256(expected_layer_members),
        "repo_tags": list(repo_tags),
    }


def _verify_snapshot(pack_root: Path, baseline: Mapping[str, Any]) -> dict[str, Any]:
    raw = baseline.get("snapshot")
    _require(isinstance(raw, dict), "snapshot baseline is absent")
    manifest_path = _require_file_ref(pack_root, raw["manifest"], label="snapshot manifest")
    manifest = _load_object(manifest_path, label="snapshot manifest")
    content_hash = _content_addressed(manifest, label="snapshot manifest")
    _require(
        manifest.get("schema_version") == "xinao.evidence_snapshot.v1"
        and content_hash == raw.get("content_sha256")
        and manifest.get("inventory_count") == raw.get("inventory_count")
        and manifest.get("logical_ref_count") == raw.get("logical_ref_count")
        and manifest.get("reference_edge_count") == raw.get("reference_edge_count"),
        "snapshot frozen identity drifted",
    )
    recorded_inventory = manifest.get("inventory")
    _require(isinstance(recorded_inventory, list), "snapshot inventory is absent")
    _require(
        manifest.get("inventory_count") == len(recorded_inventory)
        and manifest.get("inventory_sha256") == _canonical_sha256(recorded_inventory),
        "snapshot inventory identity drifted",
    )
    snapshot_root = pack_root / SNAPSHOT_RELATIVE
    actual = _inventory(snapshot_root, excluded={"snapshot_manifest.json"})
    _require(actual == recorded_inventory, "snapshot exact physical inventory drifted")
    return {
        "manifest_file_sha256": _file_sha256(manifest_path),
        "content_sha256": content_hash,
        "physical_file_count": len(actual) + 1,
        "inventory_sha256": manifest["inventory_sha256"],
    }


def _match_recorded_ref(
    pack_root: Path,
    raw: Mapping[str, Any],
    relative: str,
    *,
    label: str,
) -> Path:
    relative = _relative(relative, label=f"{label} relative")
    path = pack_root / PurePosixPath(relative)
    _require(path.is_file(), f"{label} pack-local file is missing: {relative}")
    recorded_name = ntpath.basename(str(raw.get("path") or ""))
    _require(recorded_name == path.name, f"{label} retained name drifted")
    _require(
        raw.get("sha256") == _file_sha256(path) and raw.get("size_bytes") == path.stat().st_size,
        f"{label} retained identity differs from pack-local bytes",
    )
    return path


def _verify_foundation(pack_root: Path, baseline: Mapping[str, Any]) -> dict[str, Any]:
    raw = baseline.get("foundation")
    _require(isinstance(raw, dict), "foundation baseline is absent")
    foundation_root = pack_root / FOUNDATION_RELATIVE
    actual_inventory = _inventory(foundation_root)
    _require(
        actual_inventory == raw.get("physical_inventory")
        and _canonical_sha256(actual_inventory) == raw.get("physical_inventory_sha256"),
        "foundation exact physical inventory drifted",
    )
    manifest_path = _require_file_ref(pack_root, raw["manifest"], label="foundation manifest")
    manifest = _load_object(manifest_path, label="foundation manifest")
    pack_sha = _content_addressed(manifest, label="foundation manifest", field="pack_sha256")
    _require(
        manifest.get("schema_version") == "xinao.foundation_closure_pack.v4"
        and pack_sha == raw.get("pack_sha256")
        and manifest.get("foundation_execution_ready") is True
        and manifest.get("foundation_closed") is False
        and manifest.get("fresh_process_verified") is True
        and manifest.get("fresh_assertion_bundle_verified") is True
        and manifest.get("artifact_count") == 26
        and manifest.get("assertion_count") == 63
        and manifest.get("retained_input_material_count") == 9
        and manifest.get("retained_artifact_material_count") == 26,
        "foundation v4 closure identity drifted",
    )
    report_path = _match_recorded_ref(
        pack_root,
        manifest["report_ref"],
        f"{FOUNDATION_RELATIVE}/foundation_closure_report.json",
        label="foundation report",
    )
    verification_path = _match_recorded_ref(
        pack_root,
        manifest["verification_ref"],
        f"{FOUNDATION_RELATIVE}/foundation_closure_verification.json",
        label="foundation verification",
    )
    _match_recorded_ref(
        pack_root,
        manifest["report_input_ref"],
        f"{FOUNDATION_RELATIVE}/foundation_closure_report_input.json",
        label="foundation report input",
    )
    authority_relative = f"{FOUNDATION_RELATIVE}/authority_snapshot/authority_manifest.json"
    _match_recorded_ref(
        pack_root,
        manifest["authority_snapshot_manifest_ref"],
        authority_relative,
        label="foundation authority snapshot",
    )
    _match_recorded_ref(
        pack_root,
        manifest["compiler_code_manifest_ref"],
        authority_relative,
        label="foundation compiler manifest",
    )
    receipts = manifest.get("fresh_assertion_bundle_receipt_refs")
    _require(isinstance(receipts, dict) and len(receipts) == 4, "foundation receipts drifted")
    for block_id, ref in receipts.items():
        _require(isinstance(ref, dict), f"foundation receipt is invalid: {block_id}")
        _match_recorded_ref(
            pack_root,
            ref,
            f"{FOUNDATION_RELATIVE}/fresh_assertion_bundle_receipts/{block_id}.json",
            label=f"foundation receipt {block_id}",
        )
    blueprint_ref = manifest.get("blueprint_ref")
    _require(isinstance(blueprint_ref, dict), "foundation blueprint identity is absent")
    blueprint_path = _require_file_ref(pack_root, baseline["blueprint"], label="blueprint")
    _require(
        blueprint_ref.get("sha256") == _file_sha256(blueprint_path)
        and blueprint_ref.get("size_bytes") == blueprint_path.stat().st_size,
        "pack-local blueprint differs from retained foundation identity",
    )
    report = _load_object(report_path, label="foundation report")
    verification = _load_object(verification_path, label="foundation verification")
    checks = verification.get("checks")
    _require(
        report.get("status") == "VERIFIED"
        and report.get("foundation_execution_ready") is True
        and report.get("foundation_closed") is False
        and report.get("formal_research_allowed") is False
        and report.get("formal_research_gate") == "CLOSED"
        and verification.get("schema_version") == "xinao.foundation_closure_verification.v1"
        and verification.get("ok") is True
        and verification.get("foundation_execution_ready") is True
        and verification.get("foundation_closed") is False
        and isinstance(checks, dict)
        and checks
        and all(value is True for value in checks.values()),
        "foundation report or fresh verification drifted",
    )
    return {
        "pack_sha256": pack_sha,
        "physical_file_count": len(actual_inventory),
        "physical_inventory_sha256": _canonical_sha256(actual_inventory),
        "report_status": "VERIFIED",
        "foundation_execution_ready": True,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "formal_research_gate": "CLOSED",
    }


def _verify_provenance(pack_root: Path, baseline: Mapping[str, Any]) -> dict[str, Any]:
    provenance = baseline.get("provenance")
    _require(isinstance(provenance, dict), "provenance baseline is absent")
    frozen_path = _require_file_ref(pack_root, provenance["frozen"], label="frozen inputs")
    execution_path = _require_file_ref(
        pack_root, provenance["canonical_execution"], label="canonical execution"
    )
    authority_path = _require_file_ref(
        pack_root, provenance["authority_manifest"], label="authority manifest"
    )
    frozen = _load_object(frozen_path, label="frozen inputs")
    execution = _load_object(execution_path, label="canonical execution")
    authority = _load_object(authority_path, label="authority manifest")
    frozen_content = _content_addressed(frozen, label="frozen inputs")
    execution_content = _content_addressed(execution, label="canonical execution")
    authority_content = _content_addressed(authority, label="authority manifest")
    runtime = baseline["runtime"]
    canonical_runtime = baseline.get("canonical_runtime")
    runs = execution.get("runs")
    canonical_inventory = (
        canonical_runtime.get("semantic_output_inventory")
        if isinstance(canonical_runtime, dict)
        else None
    )
    _require(
        isinstance(canonical_runtime, dict)
        and isinstance(canonical_runtime.get("raw_assertion_bundle"), dict)
        and isinstance(canonical_inventory, list)
        and len(canonical_inventory) == 3
        and all(isinstance(item, dict) for item in canonical_inventory)
        and isinstance(runs, list)
        and len(runs) == 2
        and all(isinstance(run, dict) for run in runs),
        "portable canonical runtime provenance is incomplete",
    )
    canonical_bundle = canonical_runtime["raw_assertion_bundle"]
    bundle_rows = [
        item
        for item in canonical_inventory
        if item.get("relative_path") == ASSERTION_BUNDLE_RELATIVE
    ]
    _require(len(bundle_rows) == 1, "portable raw assertion inventory row is absent")
    bundle_inventory = bundle_rows[0]
    _require(
        frozen.get("schema_version") == "xinao.f4_oci_frozen_inputs.v1"
        and frozen_content == provenance.get("frozen_content_sha256")
        and execution.get("schema_version") == OCI_EXECUTION_RECEIPT_SCHEMA
        and execution.get("status") == "VERIFIED"
        and execution.get("run_count") == 2
        and execution.get("semantic_output_byte_identical") is True
        and execution_content == provenance.get("canonical_execution_content_sha256")
        and authority.get("schema_version") == "xinao.f4_authority_source_pack.v2"
        and authority_content == runtime.get("authority_content_sha256")
        and _file_sha256(authority_path) == runtime.get("authority_manifest_sha256")
        and frozen.get("image_id") == runtime.get("image_id")
        and frozen.get("data_content_sha256") == baseline["snapshot"]["content_sha256"]
        and execution.get("semantic_output_set_sha256")
        == canonical_runtime["semantic_output_set_sha256"]
        and canonical_runtime.get("semantic_output_file_count") == 3
        and {str(item.get("relative_path")) for item in canonical_inventory}
        == EXPECTED_SEMANTIC_PATHS
        and canonical_bundle.get("relative_path") == ASSERTION_BUNDLE_RELATIVE
        and canonical_bundle.get("sha256") == bundle_inventory.get("sha256")
        and canonical_bundle.get("size_bytes") == bundle_inventory.get("size_bytes")
        and all(run.get("semantic_output_file_count") == 3 for run in runs)
        and all(run.get("semantic_output_inventory") == canonical_inventory for run in runs)
        and all(
            run.get("semantic_output_set_sha256") == canonical_runtime["semantic_output_set_sha256"]
            for run in runs
        )
        and execution.get("assertion_count")
        == canonical_runtime.get("assertion_count")
        == canonical_bundle.get("assertion_count")
        and execution.get("fallback_count") == canonical_runtime.get("fallback_count") == 0,
        "portable provenance identity drifted",
    )
    return {
        "frozen_content_sha256": frozen_content,
        "canonical_execution_content_sha256": execution_content,
        "authority_content_sha256": authority_content,
    }


def verify_portable_pack(
    *,
    pack_root: Path,
    expected_manifest_sha256: str,
    expected_runner_sha256: str,
    expected_bundle_sha256: str,
) -> dict[str, Any]:
    pack_root = _assert_no_lexical_reparse(pack_root, label="portable pack")
    _require(pack_root.is_dir(), f"portable pack is missing: {pack_root}")
    manifest_path = _assert_no_lexical_reparse(pack_root / MANIFEST_NAME, label="portable manifest")
    runner_path = _assert_no_lexical_reparse(pack_root / RUNNER_NAME, label="portable runner")
    _require(manifest_path.is_file(), "portable manifest is missing")
    _require(runner_path.is_file(), "portable runner is missing")
    _require(
        _file_sha256(manifest_path) == expected_manifest_sha256,
        "portable manifest differs from the external anchor",
    )
    _require(
        _file_sha256(runner_path) == expected_runner_sha256,
        "portable runner differs from the external anchor",
    )
    manifest = _load_object(manifest_path, label="portable manifest")
    manifest_content = _content_addressed(manifest, label="portable manifest")
    _require(manifest.get("schema_version") == PACK_SCHEMA, "portable manifest schema drifted")
    recorded_inventory = manifest.get("artifacts")
    _require(isinstance(recorded_inventory, list), "portable artifact inventory is absent")
    actual_inventory = _inventory(pack_root, excluded={MANIFEST_NAME})
    _require(
        actual_inventory == recorded_inventory
        and manifest.get("artifact_count") == len(actual_inventory)
        and manifest.get("artifact_set_sha256") == _canonical_sha256(actual_inventory),
        "portable exact artifact inventory drifted",
    )
    baseline_path = _require_file_ref(pack_root, manifest["baseline"], label="baseline")
    baseline = _load_object(baseline_path, label="portable baseline")
    baseline_content = _content_addressed(baseline, label="portable baseline")
    _require(
        baseline.get("schema_version") == BASELINE_SCHEMA
        and baseline_content == manifest.get("baseline_content_sha256"),
        "portable baseline identity drifted",
    )
    bundle_path = _require_file_ref(pack_root, manifest["image_bundle"], label="image bundle")
    _require(
        _file_sha256(bundle_path) == expected_bundle_sha256,
        "image bundle differs from the external anchor",
    )
    runtime = baseline.get("runtime")
    _require(isinstance(runtime, dict), "runtime baseline is absent")
    tar_audit = _audit_image_tar(
        bundle_path,
        image_id=str(runtime.get("image_id") or ""),
        image_ref=str(runtime.get("image_ref") or ""),
    )
    _require(tar_audit == runtime.get("image_tar_audit"), "image archive audit drifted")
    provenance = _verify_provenance(pack_root, baseline)
    snapshot = _verify_snapshot(pack_root, baseline)
    foundation = _verify_foundation(pack_root, baseline)
    claims = baseline.get("claim_scope")
    _require(
        claims
        == {
            "f4_runtime_replay": "exact semantic replay of the sealed F4 OCI snapshot",
            "foundation_v4": "byte-sealed co-packaged execution-ready foundation evidence tree",
            "relationship": "co-packaged identities; no runtime-to-foundation derivation claim",
        },
        "portable claim scope drifted",
    )
    _require(
        baseline.get("foundation_v4_relocatable_execution") is False
        and manifest.get("foundation_v4_relocatable_execution") is False
        and manifest.get("f4_oci_relocatable_execution") is True,
        "portable relocatable-execution scope drifted",
    )
    _require(
        manifest.get("pre_execution_runner_anchor_required") is True,
        "portable pre-execution runner anchor requirement drifted",
    )
    source_anchors = manifest.get("source_admission_anchors")
    _require(
        isinstance(source_anchors, dict)
        and set(source_anchors) == set(SOURCE_ANCHOR_KEYS)
        and all(
            source_anchors[key] == _hash(source_anchors[key], label=f"source anchor {key}")
            for key in SOURCE_ANCHOR_KEYS
        )
        and int(manifest.get("foundation_physical_file_count_anchor") or 0) > 0,
        "portable source-admission anchor set drifted",
    )
    return {
        "status": "VERIFIED",
        "manifest_file_sha256": expected_manifest_sha256,
        "manifest_content_sha256": manifest_content,
        "runner_sha256": expected_runner_sha256,
        "bundle_sha256": expected_bundle_sha256,
        "baseline_content_sha256": baseline_content,
        "runtime": runtime,
        "canonical_runtime": baseline["canonical_runtime"],
        "snapshot": snapshot,
        "foundation": foundation,
        "provenance": provenance,
        "claim_scope": claims,
        "artifact_count": len(actual_inventory),
        "active_retained_absolute_ref_dereference_count": 0,
        "fallback_count": 0,
    }


def _source_identity_for_build(
    *,
    frozen_path: Path,
    execution_path: Path,
    data_root: Path,
    foundation_root: Path,
    blueprint_path: Path,
    repo_cwd: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    frozen = _load_object(frozen_path, label="frozen inputs")
    execution = _load_object(execution_path, label="canonical execution")
    data_manifest_path = data_root / "snapshot_manifest.json"
    foundation_manifest_path = foundation_root / "foundation_closure_pack.json"
    data = _load_object(data_manifest_path, label="source data manifest")
    foundation = _load_object(foundation_manifest_path, label="source foundation manifest")
    _content_addressed(frozen, label="frozen inputs")
    _content_addressed(execution, label="canonical execution")
    data_content = _content_addressed(data, label="source data manifest")
    foundation_pack = _content_addressed(
        foundation, label="source foundation manifest", field="pack_sha256"
    )
    execution_runs = execution.get("runs")
    _require(
        frozen.get("schema_version") == "xinao.f4_oci_frozen_inputs.v1"
        and execution.get("schema_version") == OCI_EXECUTION_RECEIPT_SCHEMA
        and execution.get("status") == "VERIFIED"
        and execution.get("run_count") == 2
        and isinstance(execution_runs, list)
        and len(execution_runs) == 2
        and all(isinstance(run, dict) for run in execution_runs)
        and data.get("schema_version") == "xinao.evidence_snapshot.v1"
        and foundation.get("schema_version") == "xinao.foundation_closure_pack.v4"
        and foundation.get("foundation_execution_ready") is True
        and foundation.get("foundation_closed") is False,
        "build source schemas or states drifted",
    )
    _require(
        frozen.get("data_manifest_sha256") == _file_sha256(data_manifest_path)
        and frozen.get("data_content_sha256") == data_content,
        "explicit data root differs from frozen OCI inputs",
    )
    blueprint_ref = foundation.get("blueprint_ref")
    _require(isinstance(blueprint_ref, dict), "foundation blueprint ref is absent")
    _require(
        blueprint_ref.get("sha256") == _file_sha256(blueprint_path)
        and blueprint_ref.get("size_bytes") == blueprint_path.stat().st_size,
        "explicit blueprint differs from final foundation identity",
    )
    image = _docker_inspect("image", str(frozen["image_id"]), cwd=repo_cwd)
    image_identity = _image_identity(image)
    _require(
        image_identity["id"] == frozen.get("image_id")
        and sorted(str(item) for item in image.get("RepoDigests") or [])
        == sorted(str(item) for item in frozen.get("repo_digests") or []),
        "daemon image differs from frozen OCI inputs",
    )
    _require(
        execution.get("image", {}).get("id") == image_identity["id"]
        and execution.get("data_content_sha256") == data_content
        and execution.get("authority_content_sha256") == frozen.get("authority_content_sha256")
        and execution.get("semantic_output_byte_identical") is True
        and execution.get("fallback_count") == 0,
        "canonical execution does not bind the requested runtime",
    )
    return (
        frozen,
        execution,
        data,
        foundation,
        {
            "foundation_pack_sha256": foundation_pack,
            "image_identity": image_identity,
        },
    )


def build_portable_pack(
    *,
    output_root: Path,
    frozen_inputs: Path,
    canonical_execution: Path,
    data_root: Path,
    foundation_root: Path,
    blueprint: Path,
    expected_source_anchors: Mapping[str, str],
    expected_foundation_physical_file_count: int,
) -> dict[str, Any]:
    source_script = _assert_no_lexical_reparse(Path(__file__), label="portable source runner")
    frozen_inputs = _assert_no_lexical_reparse(frozen_inputs, label="frozen inputs")
    canonical_execution = _assert_no_lexical_reparse(
        canonical_execution, label="canonical execution"
    )
    data_root = _assert_no_lexical_reparse(data_root, label="data root")
    foundation_root = _assert_no_lexical_reparse(foundation_root, label="foundation root")
    blueprint = _assert_no_lexical_reparse(blueprint, label="blueprint")
    for label, path, directory in (
        ("portable source runner", source_script, False),
        ("frozen inputs", frozen_inputs, False),
        ("canonical execution", canonical_execution, False),
        ("data root", data_root, True),
        ("foundation root", foundation_root, True),
        ("blueprint", blueprint, False),
    ):
        _require(path.is_dir() if directory else path.is_file(), f"{label} is missing: {path}")
    output_root = _validate_new_root(
        output_root,
        label="portable output root",
        protected=(source_script.parent, data_root, foundation_root),
    )
    frozen, execution, data, foundation, derived = _source_identity_for_build(
        frozen_path=frozen_inputs,
        execution_path=canonical_execution,
        data_root=data_root,
        foundation_root=foundation_root,
        blueprint_path=blueprint,
        repo_cwd=source_script.parent,
    )
    source_foundation_inventory = _inventory(foundation_root)
    observed_source_anchors = {
        "frozen_file_sha256": _file_sha256(frozen_inputs),
        "frozen_content_sha256": frozen["content_sha256"],
        "canonical_execution_file_sha256": _file_sha256(canonical_execution),
        "canonical_execution_content_sha256": execution["content_sha256"],
        "data_manifest_file_sha256": _file_sha256(data_root / "snapshot_manifest.json"),
        "data_manifest_content_sha256": data["content_sha256"],
        "foundation_manifest_file_sha256": _file_sha256(
            foundation_root / "foundation_closure_pack.json"
        ),
        "foundation_pack_sha256": derived["foundation_pack_sha256"],
        "foundation_physical_inventory_sha256": _canonical_sha256(source_foundation_inventory),
        "blueprint_file_sha256": _file_sha256(blueprint),
    }
    _verify_source_admission_anchors(
        observed=observed_source_anchors,
        expected=expected_source_anchors,
    )
    _require(
        len(source_foundation_inventory) == expected_foundation_physical_file_count,
        "portable build foundation physical file count drifted",
    )
    export_daemon_fingerprint = _daemon_fingerprint(cwd=source_script.parent)
    image_export_preflight = _prove_preload_image_state(
        image_id=str(frozen["image_id"]),
        sealed_repo_tags=[str(frozen["image_ref"])],
        require_image_absent=False,
        cwd=source_script.parent,
    )
    _require(
        image_export_preflight["expected_image_present"] is True
        and image_export_preflight["sealed_repo_tag_bindings"]
        == [
            {
                "repo_tag": str(frozen["image_ref"]),
                "image_ids": [str(frozen["image_id"])],
                "status": "expected-image",
            }
        ],
        "frozen image ref is not bound to the exact frozen image ID",
    )
    _require_same_daemon(
        expected=export_daemon_fingerprint,
        cwd=source_script.parent,
        operation="portable image export",
    )
    authority_source = _assert_no_lexical_reparse(
        Path(str(frozen["authority_manifest_path"])), label="authority manifest"
    )
    authority = _load_object(authority_source, label="authority manifest")
    authority_content = _content_addressed(authority, label="authority manifest")
    _require(
        _file_sha256(authority_source) == frozen.get("authority_manifest_sha256")
        and authority_content == frozen.get("authority_content_sha256"),
        "authority source differs from frozen inputs",
    )
    staging = output_root.parent / f".{output_root.name}.{os.getpid()}.tmp"
    receipt_path = output_root.parent / f"{output_root.name}.build_receipt.json"
    receipt_staging = output_root.parent / f".{receipt_path.name}.{os.getpid()}.tmp"
    _require(not staging.exists(), f"portable staging root exists: {staging}")
    _require(not receipt_path.exists(), f"build receipt already exists: {receipt_path}")
    _require(not receipt_staging.exists(), f"build receipt staging exists: {receipt_staging}")
    staging.mkdir(parents=True)
    moved = False
    try:
        _copy_tree(data_root, staging / SNAPSHOT_RELATIVE)
        _copy_tree(foundation_root, staging / FOUNDATION_RELATIVE)
        for source, relative in (
            (source_script, RUNNER_NAME),
            (blueprint, BLUEPRINT_RELATIVE),
            (frozen_inputs, FROZEN_RELATIVE),
            (canonical_execution, EXECUTION_RELATIVE),
            (authority_source, AUTHORITY_RELATIVE),
        ):
            destination = staging / PurePosixPath(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            _require(_file_sha256(source) == _file_sha256(destination), f"copy drifted: {relative}")
        image_tar = staging / IMAGE_TAR_RELATIVE
        image_tar.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "docker",
                "image",
                "save",
                "--output",
                str(image_tar),
                str(frozen["image_ref"]),
            ],
            cwd=source_script.parent,
            timeout=1800,
        )
        _require_same_daemon(
            expected=export_daemon_fingerprint,
            cwd=source_script.parent,
            operation="portable image export proof",
        )
        tar_audit = _audit_image_tar(
            image_tar,
            image_id=str(frozen["image_id"]),
            image_ref=str(frozen["image_ref"]),
        )
        snapshot_manifest = staging / SNAPSHOT_RELATIVE / "snapshot_manifest.json"
        foundation_manifest = staging / FOUNDATION_RELATIVE / "foundation_closure_pack.json"
        blueprint_copy = staging / BLUEPRINT_RELATIVE
        foundation_inventory = _inventory(staging / FOUNDATION_RELATIVE)
        _require(
            foundation_inventory == source_foundation_inventory,
            "foundation source changed during portable build",
        )
        canonical_run = execution["runs"][0]
        second_canonical_run = execution["runs"][1]
        canonical_output = _semantic_contract(Path(str(canonical_run.get("output_ref") or "")))
        second_canonical_output = _semantic_contract(
            Path(str(second_canonical_run.get("output_ref") or ""))
        )
        canonical_inventory = canonical_output["semantic_output_inventory"]
        _require(
            execution.get("run_count") == 2
            and canonical_run.get("semantic_output_file_count") == 3
            and second_canonical_run.get("semantic_output_file_count") == 3
            and canonical_run.get("semantic_output_inventory") == canonical_inventory
            and second_canonical_run.get("semantic_output_inventory") == canonical_inventory
            and second_canonical_output == canonical_output
            and execution.get("semantic_output_set_sha256")
            == canonical_output["semantic_output_set_sha256"]
            and canonical_run.get("semantic_output_set_sha256")
            == canonical_output["semantic_output_set_sha256"]
            and second_canonical_run.get("semantic_output_set_sha256")
            == canonical_output["semantic_output_set_sha256"]
            and execution.get("assertion_count") == canonical_output["assertion_count"]
            and execution.get("fallback_count") == 0,
            "canonical execution semantic outputs drifted",
        )
        baseline_core = {
            "schema_version": BASELINE_SCHEMA,
            "foundation_v4_relocatable_execution": False,
            "claim_scope": {
                "f4_runtime_replay": "exact semantic replay of the sealed F4 OCI snapshot",
                "foundation_v4": "byte-sealed co-packaged execution-ready foundation evidence tree",
                "relationship": "co-packaged identities; no runtime-to-foundation derivation claim",
            },
            "runtime": {
                "image_id": frozen["image_id"],
                "image_ref": frozen["image_ref"],
                "repo_digests": sorted(str(item) for item in frozen.get("repo_digests") or []),
                "image_identity": derived["image_identity"],
                "image_bundle": _file_ref(image_tar, relative_path=IMAGE_TAR_RELATIVE),
                "image_tar_audit": tar_audit,
                "authority_manifest_sha256": frozen["authority_manifest_sha256"],
                "authority_content_sha256": frozen["authority_content_sha256"],
                "data_manifest_sha256": frozen["data_manifest_sha256"],
                "data_content_sha256": frozen["data_content_sha256"],
            },
            "canonical_runtime": {
                **canonical_output,
            },
            "snapshot": {
                "manifest": _file_ref(
                    snapshot_manifest,
                    relative_path=f"{SNAPSHOT_RELATIVE}/snapshot_manifest.json",
                ),
                "content_sha256": data["content_sha256"],
                "inventory_count": data["inventory_count"],
                "logical_ref_count": data["logical_ref_count"],
                "reference_edge_count": data["reference_edge_count"],
            },
            "foundation": {
                "manifest": _file_ref(
                    foundation_manifest,
                    relative_path=f"{FOUNDATION_RELATIVE}/foundation_closure_pack.json",
                ),
                "pack_sha256": derived["foundation_pack_sha256"],
                "physical_inventory": foundation_inventory,
                "physical_inventory_sha256": _canonical_sha256(foundation_inventory),
                "physical_file_count": len(foundation_inventory),
            },
            "blueprint": _file_ref(blueprint_copy, relative_path=BLUEPRINT_RELATIVE),
            "provenance": {
                "frozen": _file_ref(staging / FROZEN_RELATIVE, relative_path=FROZEN_RELATIVE),
                "frozen_content_sha256": frozen["content_sha256"],
                "canonical_execution": _file_ref(
                    staging / EXECUTION_RELATIVE, relative_path=EXECUTION_RELATIVE
                ),
                "canonical_execution_content_sha256": execution["content_sha256"],
                "authority_manifest": _file_ref(
                    staging / AUTHORITY_RELATIVE, relative_path=AUTHORITY_RELATIVE
                ),
            },
        }
        baseline = {**baseline_core, "content_sha256": _canonical_sha256(baseline_core)}
        baseline_path = staging / BASELINE_RELATIVE
        _write_canonical(baseline_path, baseline)
        artifacts = _inventory(staging, excluded={MANIFEST_NAME})
        manifest_core = {
            "schema_version": PACK_SCHEMA,
            "layout_version": "xinao.f4_portable_closure_layout.v1",
            "runner": _file_ref(staging / RUNNER_NAME, relative_path=RUNNER_NAME),
            "baseline": _file_ref(baseline_path, relative_path=BASELINE_RELATIVE),
            "baseline_content_sha256": baseline["content_sha256"],
            "image_bundle": _file_ref(image_tar, relative_path=IMAGE_TAR_RELATIVE),
            "snapshot_root": SNAPSHOT_RELATIVE,
            "foundation_root": FOUNDATION_RELATIVE,
            "blueprint": _file_ref(blueprint_copy, relative_path=BLUEPRINT_RELATIVE),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "artifact_set_sha256": _canonical_sha256(artifacts),
            "active_path_model": "pack-relative-only",
            "f4_oci_relocatable_execution": True,
            "foundation_v4_relocatable_execution": False,
            "claim_scope": baseline["claim_scope"],
            "source_admission_anchors": dict(expected_source_anchors),
            "foundation_physical_file_count_anchor": expected_foundation_physical_file_count,
            "pre_execution_runner_anchor_required": True,
            "image_export_daemon_fingerprint": export_daemon_fingerprint,
            "image_export_preflight": image_export_preflight,
        }
        manifest = {**manifest_core, "content_sha256": _canonical_sha256(manifest_core)}
        manifest_path = staging / MANIFEST_NAME
        _write_canonical(manifest_path, manifest)
        anchors = {
            "manifest_sha256": _file_sha256(manifest_path),
            "runner_sha256": _file_sha256(staging / RUNNER_NAME),
            "bundle_sha256": _file_sha256(image_tar),
        }
        verify_portable_pack(
            pack_root=staging,
            expected_manifest_sha256=anchors["manifest_sha256"],
            expected_runner_sha256=anchors["runner_sha256"],
            expected_bundle_sha256=anchors["bundle_sha256"],
        )
        blueprint_sha256 = _file_sha256(blueprint_copy)
        receipt_core = {
            "schema_version": BUILD_RECEIPT_SCHEMA,
            "status": "VERIFIED",
            "pack_ref": str(output_root),
            **anchors,
            "manifest_content_sha256": manifest["content_sha256"],
            "baseline_content_sha256": baseline["content_sha256"],
            "image_id": frozen["image_id"],
            "snapshot_content_sha256": data["content_sha256"],
            "foundation_pack_sha256": derived["foundation_pack_sha256"],
            "blueprint_sha256": blueprint_sha256,
            "artifact_count": len(artifacts),
            "f4_oci_relocatable_execution": True,
            "foundation_v4_relocatable_execution": False,
            "claim_scope": baseline["claim_scope"],
            "source_admission_anchors": dict(expected_source_anchors),
            "foundation_physical_file_count_anchor": expected_foundation_physical_file_count,
            "pre_execution_runner_anchor_required": True,
            "image_export_daemon_fingerprint": export_daemon_fingerprint,
            "image_export_preflight": image_export_preflight,
        }
        receipt = {**receipt_core, "content_sha256": _canonical_sha256(receipt_core)}
        _write_canonical(receipt_staging, receipt)
        staging.rename(output_root)
        moved = True
        _publish_file_no_clobber(receipt_staging, receipt_path)
        return {**receipt, "build_receipt_ref": str(receipt_path)}
    except Exception:
        if moved and output_root.exists() and not staging.exists():
            output_root.rename(staging)
        shutil.rmtree(staging, ignore_errors=True)
        receipt_staging.unlink(missing_ok=True)
        raise


def _mount_rows(container: Mapping[str, Any]) -> list[dict[str, Any]]:
    mounts = container.get("Mounts")
    _require(isinstance(mounts, list), "container mounts are absent")
    rows = [
        {
            "type": str(item.get("Type") or ""),
            "source": str(item.get("Source") or ""),
            "destination": str(item.get("Destination") or ""),
            "rw": bool(item.get("RW")),
        }
        for item in mounts
        if isinstance(item, dict)
    ]
    rows.sort(key=lambda item: item["destination"])
    return rows


def _host_path_identity(value: object) -> str:
    raw = str(value or "").replace("/", "\\")
    if raw.casefold().startswith("\\\\?\\unc\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return ntpath.normcase(ntpath.abspath(raw))


def _normalize_container_id(value: object, *, label: str) -> str:
    normalized = str(value or "").lower()
    _require(
        len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized),
        f"{label} is not a valid full ID",
    )
    return normalized


def _query_container_rows(*, filter_value: str, cwd: Path) -> list[dict[str, str]]:
    argv = [
        "docker",
        "container",
        "ls",
        "-a",
        "--no-trunc",
        "--filter",
        filter_value,
        "--format",
        "{{.ID}}\t{{.Names}}",
    ]
    completed = _run(argv, cwd=cwd, timeout=120, require_success=False)
    _require(
        completed.returncode == 0,
        "docker container inventory query failed; ownership state is not proven: "
        f"{completed.stderr[-1000:]}",
    )
    rows: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        _require(len(fields) == 2 and bool(fields[1]), "docker container inventory row drifted")
        try:
            container_id = _normalize_container_id(
                fields[0], label="docker container inventory identity"
            )
        except PortableClosureError as exc:
            raise PortableClosureError(
                "docker container inventory returned an invalid full ID"
            ) from exc
        rows.append({"container_id": container_id, "name": fields[1]})
    rows.sort(key=lambda item: (item["container_id"], item["name"]))
    _require(
        len({(item["container_id"], item["name"]) for item in rows}) == len(rows),
        "docker container inventory contains duplicate rows",
    )
    return rows


def _query_exact_name_rows(*, name: str, cwd: Path) -> list[dict[str, str]]:
    rows = _query_container_rows(filter_value=f"name={name}", cwd=cwd)
    return [item for item in rows if item["name"] == name]


def _query_owner_rows(*, owner_nonce: str, cwd: Path) -> list[dict[str, str]]:
    return _query_container_rows(filter_value=f"label={OWNER_LABEL}={owner_nonce}", cwd=cwd)


def _require_container_preflight_clear(*, name: str, owner_nonce: str, cwd: Path) -> None:
    _require(
        not _query_exact_name_rows(name=name, cwd=cwd),
        f"portable container preflight collision on exact name: {name}",
    )
    _require(
        not _query_owner_rows(owner_nonce=owner_nonce, cwd=cwd),
        "portable container preflight collision on owner nonce",
    )


def _new_container_identity(ordinal: int) -> tuple[str, str, str]:
    name = f"xinao-f4-portable-{uuid.uuid4().hex[:16]}"
    owner_nonce = secrets.token_hex(16)
    run_id = f"run-{ordinal}-{uuid.uuid4().hex}"
    _require(len(owner_nonce) == 32, "portable owner nonce is not 128-bit")
    return name, owner_nonce, run_id


def _verify_container(
    container: Mapping[str, Any],
    *,
    container_id: str,
    name: str,
    owner_nonce: str,
    run_id: str,
    runtime: Mapping[str, Any],
    snapshot_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    host = container.get("HostConfig")
    config = container.get("Config")
    _require(isinstance(host, dict) and isinstance(config, dict), "container config is absent")
    expected_container_id = _normalize_container_id(container_id, label="expected container ID")
    image_identity = runtime["image_identity"]
    labels = config.get("Labels")
    _require(
        container.get("Id") == expected_container_id,
        "container full ID drifted",
    )
    _require(container.get("Name") == f"/{name}", "container exact name drifted")
    _require(isinstance(labels, dict), "container labels are absent")
    _require(labels.get(OWNER_LABEL) == owner_nonce, "container owner label drifted")
    _require(labels.get(RUN_LABEL) == run_id, "container run label drifted")
    _require(container.get("Image") == runtime["image_id"], "container image ID drifted")
    _require(config.get("Image") == runtime["image_id"], "container configured image drifted")
    _require(config.get("Entrypoint") == EXPECTED_ENTRYPOINT, "container entrypoint drifted")
    _require(config.get("Cmd") == EXPECTED_CMD, "container command drifted")
    _require(config.get("Env") == image_identity["environment"], "container environment drifted")
    _require(config.get("User") == "65532:65532", "container user drifted")
    _require(config.get("WorkingDir") == "/work", "container working directory drifted")
    _require(host.get("ReadonlyRootfs") is True, "container root filesystem is writable")
    _require(host.get("NetworkMode") == "none", "container network is not disabled")
    _require(host.get("CapDrop") == ["ALL"], "container capabilities were not dropped")
    _require(host.get("Privileged") is False, "container is privileged")
    _require(not host.get("Devices"), "container has device mappings")
    _require(not host.get("Binds"), "container has legacy bind mappings")
    for field in ("PidMode", "IpcMode", "UTSMode", "UsernsMode", "CgroupnsMode"):
        _require(str(host.get(field) or "") != "host", f"container shares host namespace: {field}")
    security = host.get("SecurityOpt")
    _require(
        isinstance(security, list)
        and any(str(item).startswith("no-new-privileges") for item in security),
        "container no-new-privileges is absent",
    )
    _require(host.get("PidsLimit") == 256, "container PID limit drifted")
    tmpfs = host.get("Tmpfs")
    _require(isinstance(tmpfs, dict) and set(tmpfs) == {"/tmp"}, "container tmpfs drifted")
    tmpfs_tokens = [item.strip() for item in str(tmpfs["/tmp"]).split(",")]
    _require(
        len(tmpfs_tokens) == 5
        and set(tmpfs_tokens) == {"rw", "noexec", "nosuid", "nodev", "size=268435456"},
        "container tmpfs options drifted",
    )
    mounts = _mount_rows(container)
    expected_mounts = [
        {
            "type": "bind",
            "source": str(snapshot_root.resolve()),
            "destination": "/capsule",
            "rw": False,
        },
        {
            "type": "bind",
            "source": str(output_dir.resolve()),
            "destination": "/output",
            "rw": True,
        },
    ]
    _require(len(mounts) == len(expected_mounts), "container mount count drifted")
    for observed, expected in zip(mounts, expected_mounts, strict=True):
        _require(
            observed["type"] == expected["type"]
            and observed["destination"] == expected["destination"]
            and observed["rw"] == expected["rw"]
            and _host_path_identity(observed["source"]) == _host_path_identity(expected["source"]),
            "container mount inventory drifted",
        )
    return {
        "readonly_rootfs": True,
        "network_mode": "none",
        "cap_drop": ["ALL"],
        "security_opt": sorted(str(item) for item in security),
        "privileged": False,
        "device_count": 0,
        "legacy_bind_count": 0,
        "tmpfs": {"/tmp": str(tmpfs["/tmp"])},
        "mounts": mounts,
        "entrypoint": list(EXPECTED_ENTRYPOINT),
        "cmd": list(EXPECTED_CMD),
        "environment_exact_image_match": True,
        "user": "65532:65532",
        "working_dir": "/work",
        "pids_limit": 256,
        "host_namespace_share_count": 0,
        "container_id": expected_container_id,
        "exact_name": name,
        "owner_label_bound": True,
        "run_label_bound": True,
    }


def _raw_assertion_bundle_identity(root: Path) -> dict[str, Any]:
    bundle_path = root / ASSERTION_BUNDLE_RELATIVE
    bundle = _load_object(bundle_path, label="F4 raw assertion bundle")
    bundle_content = _content_addressed(bundle, label="F4 raw assertion bundle")
    _require(
        bundle_path.read_bytes() == _canonical_bytes(bundle),
        "F4 raw assertion bundle bytes are not canonical",
    )
    actuals = bundle.get("assertion_actuals")
    actual_hashes = bundle.get("assertion_actual_content_sha256")
    assertion_ids = sorted(actuals) if isinstance(actuals, dict) else []
    expected_actual_hashes = {
        assertion_id: _canonical_sha256(
            {"assertion_id": assertion_id, "actual": actuals[assertion_id]}
        )
        for assertion_id in assertion_ids
    }
    request_sha256 = bundle.get("request_sha256")
    _require(
        bundle.get("schema_version") == "xinao.assertion_actual_bundle.v2"
        and bundle.get("protocol_version") == "xinao.assertion_bundle_protocol.v2"
        and bundle.get("block_id") == "F4_research_factory"
        and len(assertion_ids) == 14
        and all(actuals[assertion_id] is True for assertion_id in assertion_ids)
        and actual_hashes == expected_actual_hashes
        and isinstance(request_sha256, str)
        and len(request_sha256) == 64
        and all(character in "0123456789abcdef" for character in request_sha256),
        "F4 raw assertion bundle contract drifted",
    )
    return {
        "relative_path": ASSERTION_BUNDLE_RELATIVE,
        "sha256": _file_sha256(bundle_path),
        "size_bytes": bundle_path.stat().st_size,
        "content_sha256": bundle_content,
        "request_sha256": request_sha256,
        "assertion_ids": assertion_ids,
        "assertion_count": len(assertion_ids),
        "assertion_actuals_sha256": _canonical_sha256(actuals),
    }


def _semantic_contract(root: Path) -> dict[str, Any]:
    rows = _inventory(root)
    paths = {str(item["relative_path"]) for item in rows}
    _require(
        paths == EXPECTED_SEMANTIC_PATHS and len(rows) == 3,
        "semantic output inventory is not exactly the sealed three-file set",
    )
    bundle_identity = _raw_assertion_bundle_identity(root)
    stage0_path = root / "stage0_result.json"
    trace_path = root / "snapshot_trace_summary.json"
    stage0 = _load_object(stage0_path, label="stage0 result")
    trace = _load_object(trace_path, label="snapshot trace")
    _content_addressed(stage0, label="stage0 result")
    trace_content = _content_addressed(trace, label="snapshot trace")
    bundle_ref = stage0.get("common_assertion_bundle")
    authority_projection = stage0.get("common_authority_projection")
    _require(
        stage0.get("schema_version") == "xinao.f4_snapshot_stage0_run.v1"
        and stage0.get("status") == "VERIFIED"
        and stage0.get("assertion_count") == bundle_identity["assertion_count"]
        and stage0.get("fallback_count") == 0
        and isinstance(bundle_ref, dict)
        and bundle_ref.get("sha256") == bundle_identity["sha256"]
        and bundle_ref.get("size_bytes") == bundle_identity["size_bytes"]
        and bundle_ref.get("content_sha256") == bundle_identity["content_sha256"]
        and bundle_ref.get("request_sha256") == bundle_identity["request_sha256"]
        and bundle_ref.get("assertion_count") == bundle_identity["assertion_count"]
        and isinstance(authority_projection, dict)
        and authority_projection.get("schema_version") == "xinao.f4_common_authority_projection.v1"
        and authority_projection.get("status") == "VERIFIED"
        and stage0.get("snapshot_trace_summary_sha256") == _file_sha256(trace_path)
        and stage0.get("snapshot_trace_summary_content_sha256") == trace_content,
        "portable stage0 raw assertion binding drifted",
    )
    _require(
        trace.get("schema_version") == "xinao.f4_snapshot_trace_summary.v1"
        and trace.get("status") == "VERIFIED"
        and trace.get("fallback_count") == 0
        and int(trace.get("process_count", 0)) >= 5,
        "portable snapshot trace contract drifted",
    )
    return {
        "semantic_output_file_count": len(rows),
        "semantic_output_inventory": rows,
        "semantic_output_set_sha256": _canonical_sha256(rows),
        "raw_assertion_bundle": bundle_identity,
        "assertion_count": bundle_identity["assertion_count"],
        "fallback_count": 0,
    }


def _inspect_owned_container(
    *,
    container_id: str,
    name: str,
    owner_nonce: str,
    run_id: str,
    runtime: Mapping[str, Any],
    snapshot_root: Path,
    output_dir: Path,
    cwd: Path,
) -> dict[str, Any]:
    normalized_id = _normalize_container_id(container_id, label="owned container ID")
    container = _docker_inspect("container", normalized_id, cwd=cwd)
    isolation = _verify_container(
        container,
        container_id=normalized_id,
        name=name,
        owner_nonce=owner_nonce,
        run_id=run_id,
        runtime=runtime,
        snapshot_root=snapshot_root,
        output_dir=output_dir,
    )
    return {"container_id": normalized_id, "isolation": isolation}


def _reconcile_owned_container(
    *,
    name: str,
    owner_nonce: str,
    run_id: str,
    runtime: Mapping[str, Any],
    snapshot_root: Path,
    output_dir: Path,
    daemon_fingerprint: Mapping[str, Any],
    cwd: Path,
) -> dict[str, Any] | None:
    _require_same_daemon(expected=daemon_fingerprint, cwd=cwd, operation="container reconcile")
    rows = _query_owner_rows(owner_nonce=owner_nonce, cwd=cwd)
    if not rows:
        return None
    _require(len(rows) == 1, "portable owner nonce reconciliation is ambiguous")
    row = rows[0]
    _require(row["name"] == name, "portable owned container exact name drifted")
    return _inspect_owned_container(
        container_id=row["container_id"],
        name=name,
        owner_nonce=owner_nonce,
        run_id=run_id,
        runtime=runtime,
        snapshot_root=snapshot_root,
        output_dir=output_dir,
        cwd=cwd,
    )


def _remove_owned_container(
    *,
    container_id: str,
    name: str,
    owner_nonce: str,
    run_id: str,
    runtime: Mapping[str, Any],
    snapshot_root: Path,
    output_dir: Path,
    daemon_fingerprint: Mapping[str, Any],
    cwd: Path,
) -> dict[str, bool]:
    normalized_id = _normalize_container_id(container_id, label="cleanup container ID")
    _require_same_daemon(expected=daemon_fingerprint, cwd=cwd, operation="container remove")
    _inspect_owned_container(
        container_id=normalized_id,
        name=name,
        owner_nonce=owner_nonce,
        run_id=run_id,
        runtime=runtime,
        snapshot_root=snapshot_root,
        output_dir=output_dir,
        cwd=cwd,
    )
    removed = _run(
        ["docker", "rm", "-f", normalized_id],
        cwd=cwd,
        timeout=120,
        require_success=False,
    )
    _require(
        removed.returncode == 0,
        f"portable owned container removal failed: {removed.stderr[-1000:]}",
    )
    _require_same_daemon(expected=daemon_fingerprint, cwd=cwd, operation="container post-remove")
    id_rows = _query_container_rows(filter_value=f"id={normalized_id}", cwd=cwd)
    owner_rows = _query_owner_rows(owner_nonce=owner_nonce, cwd=cwd)
    name_rows = _query_exact_name_rows(name=name, cwd=cwd)
    _require_same_daemon(
        expected=daemon_fingerprint,
        cwd=cwd,
        operation="container cleanup proof",
    )
    _require(
        not any(item["container_id"] == normalized_id for item in id_rows),
        "portable container cleanup left the exact ID present",
    )
    _require(not owner_rows, "portable container cleanup left the owner nonce present")
    _require(not name_rows, "portable container cleanup left the exact name present")
    return {
        "verified": True,
        "container_id_absent": True,
        "owner_nonce_absent": True,
        "exact_name_absent": True,
    }


def _one_runtime(
    *,
    ordinal: int,
    pack_root: Path,
    output_root: Path,
    runtime: Mapping[str, Any],
    daemon_fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    output_dir = output_root / f"run-{ordinal}"
    _require(not output_dir.exists(), f"run output exists: {output_dir}")
    snapshot_root = pack_root / SNAPSHOT_RELATIVE
    name, owner_nonce, run_id = _new_container_identity(ordinal)
    _require_same_daemon(
        expected=daemon_fingerprint, cwd=pack_root, operation="container preflight"
    )
    _require_container_preflight_clear(name=name, owner_nonce=owner_nonce, cwd=pack_root)
    _require_same_daemon(
        expected=daemon_fingerprint,
        cwd=pack_root,
        operation="container post-preflight create",
    )
    output_dir.mkdir(parents=True)
    argv = [
        "docker",
        "create",
        "--name",
        name,
        "--label",
        f"{OWNER_LABEL}={owner_nonce}",
        "--label",
        f"{RUN_LABEL}={run_id}",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--mount",
        f"type=bind,src={snapshot_root.resolve()},dst=/capsule,readonly",
        "--mount",
        f"type=bind,src={output_dir.resolve()},dst=/output",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=268435456",
        str(runtime["image_id"]),
    ]
    owned: dict[str, Any] | None = None
    cleanup: dict[str, bool] | None = None
    stdout = ""
    stderr = ""
    try:
        create_error: PortableClosureError | None = None
        candidate_id: str | None = None
        try:
            created = _run(argv, cwd=pack_root, require_success=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            create_error = PortableClosureError(
                f"docker create invocation failed: {type(exc).__name__}: {exc}"
            )
        else:
            if created.returncode != 0:
                create_error = PortableClosureError(
                    f"docker create failed: {created.stdout[-1000:]}\n{created.stderr[-1000:]}"
                )
            else:
                try:
                    candidate_id = _normalize_container_id(
                        created.stdout.strip(), label="docker create returned identity"
                    )
                except PortableClosureError:
                    create_error = PortableClosureError(
                        "docker create returned no exact container ID"
                    )
        owned = _reconcile_owned_container(
            name=name,
            owner_nonce=owner_nonce,
            run_id=run_id,
            runtime=runtime,
            snapshot_root=snapshot_root,
            output_dir=output_dir,
            daemon_fingerprint=daemon_fingerprint,
            cwd=pack_root,
        )
        if owned is None:
            if create_error is not None:
                raise create_error
            raise PortableClosureError(
                "docker create returned an ID but owner reconciliation found no owned container"
            )
        container_id = str(owned["container_id"])
        if candidate_id is not None:
            _require(
                candidate_id == container_id,
                "docker create ID differs from the reconciled owner container ID",
            )
        if create_error is not None:
            raise create_error
        _require_same_daemon(
            expected=daemon_fingerprint, cwd=pack_root, operation="container start"
        )
        isolation = owned["isolation"]
        completed = _run(["docker", "start", "-a", container_id], cwd=pack_root)
        stdout = completed.stdout
        stderr = completed.stderr
        _require_same_daemon(
            expected=daemon_fingerprint,
            cwd=pack_root,
            operation="container post-start inspect",
        )
        after = _docker_inspect("container", container_id, cwd=pack_root)
        _verify_container(
            after,
            container_id=container_id,
            name=name,
            owner_nonce=owner_nonce,
            run_id=run_id,
            runtime=runtime,
            snapshot_root=snapshot_root,
            output_dir=output_dir,
        )
        _require_same_daemon(
            expected=daemon_fingerprint,
            cwd=pack_root,
            operation="container post-inspect",
        )
        state = after.get("State")
        _require(
            isinstance(state, dict)
            and state.get("Status") == "exited"
            and state.get("ExitCode") == 0
            and state.get("OOMKilled") is False,
            f"portable container did not exit cleanly: {state}",
        )
        semantic = _semantic_contract(output_dir)
        stage0 = _load_object(output_dir / "stage0_result.json", label="stage0 result")
        result = {
            "ordinal": ordinal,
            "container_id": container_id,
            "container_name": name,
            "container_owner_nonce": owner_nonce,
            "container_run_id": run_id,
            "exit_code": 0,
            "output_ref": str(output_dir),
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
            "isolation": isolation,
            **semantic,
            "runtime_negative_probes": stage0["preflight"]["isolation_negative_probes"],
        }
    finally:
        if owned is not None:
            cleanup = _remove_owned_container(
                container_id=str(owned["container_id"]),
                name=name,
                owner_nonce=owner_nonce,
                run_id=run_id,
                runtime=runtime,
                snapshot_root=snapshot_root,
                output_dir=output_dir,
                daemon_fingerprint=daemon_fingerprint,
                cwd=pack_root,
            )
    cleanup_keys = (
        "verified",
        "container_id_absent",
        "owner_nonce_absent",
        "exact_name_absent",
    )
    _require(
        isinstance(cleanup, dict) and all(cleanup.get(key) is True for key in cleanup_keys),
        "portable owned container cleanup proof is absent or incomplete",
    )
    return {
        **result,
        "container_cleanup_verified": True,
        "container_cleanup": cleanup,
    }


def run_portable_pack(
    *,
    pack_root: Path,
    output_root: Path,
    expected_manifest_sha256: str,
    expected_runner_sha256: str,
    expected_bundle_sha256: str,
    require_image_absent_before_load: bool = False,
) -> Path:
    verified = verify_portable_pack(
        pack_root=pack_root,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_runner_sha256=expected_runner_sha256,
        expected_bundle_sha256=expected_bundle_sha256,
    )
    output_root = _validate_new_root(
        output_root,
        label="portable run output",
        protected=(pack_root,),
    )
    runtime = verified["runtime"]
    daemon_fingerprint = _daemon_fingerprint(cwd=pack_root)
    _require_same_daemon(expected=daemon_fingerprint, cwd=pack_root, operation="image pre-load")
    repo_tags = runtime["image_tar_audit"]["repo_tags"]
    pre_load_image_inventory = _prove_preload_image_state(
        image_id=str(runtime["image_id"]),
        sealed_repo_tags=repo_tags,
        require_image_absent=require_image_absent_before_load,
        cwd=pack_root,
    )
    _require_same_daemon(
        expected=daemon_fingerprint,
        cwd=pack_root,
        operation="image load mutation",
    )
    image_present_before_load = bool(pre_load_image_inventory["expected_image_present"])
    bundle_path = pack_root / IMAGE_TAR_RELATIVE
    loaded = _run(
        ["docker", "image", "load", "--input", str(bundle_path)],
        cwd=pack_root,
        timeout=1800,
    )
    _require_same_daemon(expected=daemon_fingerprint, cwd=pack_root, operation="image post-load")
    post_load_image_inventory = _prove_preload_image_state(
        image_id=str(runtime["image_id"]),
        sealed_repo_tags=repo_tags,
        require_image_absent=False,
        cwd=pack_root,
    )
    _require(
        post_load_image_inventory["expected_image_present"] is True
        and all(
            item["image_ids"] == [str(runtime["image_id"])]
            for item in post_load_image_inventory["sealed_repo_tag_bindings"]
        ),
        "docker load did not bind every sealed RepoTag to the expected image ID",
    )
    image = _docker_inspect("image", str(runtime["image_id"]), cwd=pack_root)
    _require(_image_identity(image) == runtime["image_identity"], "loaded image identity drifted")
    _require_same_daemon(
        expected=daemon_fingerprint,
        cwd=pack_root,
        operation="image load proof",
    )
    output_root.mkdir(parents=True)
    first = _one_runtime(
        ordinal=1,
        pack_root=pack_root,
        output_root=output_root,
        runtime=runtime,
        daemon_fingerprint=daemon_fingerprint,
    )
    second = _one_runtime(
        ordinal=2,
        pack_root=pack_root,
        output_root=output_root,
        runtime=runtime,
        daemon_fingerprint=daemon_fingerprint,
    )
    expected_semantic = verified["canonical_runtime"]
    expected_inventory = expected_semantic["semantic_output_inventory"]
    expected_set = expected_semantic["semantic_output_set_sha256"]
    _require(
        first["semantic_output_inventory"]
        == second["semantic_output_inventory"]
        == expected_inventory
        and first["semantic_output_set_sha256"]
        == second["semantic_output_set_sha256"]
        == expected_set
        and first["semantic_output_file_count"]
        == second["semantic_output_file_count"]
        == expected_semantic["semantic_output_file_count"]
        == 3
        and first["raw_assertion_bundle"]
        == second["raw_assertion_bundle"]
        == expected_semantic["raw_assertion_bundle"]
        and first["assertion_count"]
        == second["assertion_count"]
        == expected_semantic["assertion_count"],
        "portable runtime does not exactly replay the sealed semantic output",
    )
    cleanup_verified = all(
        run.get("container_cleanup_verified") is True
        and isinstance(run.get("container_cleanup"), dict)
        and all(
            run["container_cleanup"].get(key) is True
            for key in (
                "verified",
                "container_id_absent",
                "owner_nonce_absent",
                "exact_name_absent",
            )
        )
        for run in (first, second)
    )
    _require(cleanup_verified, "portable aggregate container cleanup proof is incomplete")
    core = {
        "schema_version": RUN_RECEIPT_SCHEMA,
        "status": "VERIFIED",
        "captured_at": datetime.now(UTC).isoformat(),
        "pack_ref": str(pack_root),
        "pack_manifest_sha256": expected_manifest_sha256,
        "pack_manifest_content_sha256": verified["manifest_content_sha256"],
        "runner_sha256": expected_runner_sha256,
        "bundle_sha256": expected_bundle_sha256,
        "load_mode": (
            "warm_image_present_before_load"
            if image_present_before_load
            else "daemon_image_absent_before_load"
        ),
        "require_image_absent_before_load": require_image_absent_before_load,
        "daemon_fingerprint": daemon_fingerprint,
        "pre_load_image_inventory_proof": pre_load_image_inventory,
        "post_load_image_inventory_proof": post_load_image_inventory,
        "docker_load_stdout_sha256": hashlib.sha256(loaded.stdout.encode("utf-8")).hexdigest(),
        "docker_load_stderr_sha256": hashlib.sha256(loaded.stderr.encode("utf-8")).hexdigest(),
        "image_id": runtime["image_id"],
        "run_count": 2,
        "runs": [first, second],
        "semantic_output_byte_identical": True,
        "semantic_output_file_count": expected_semantic["semantic_output_file_count"],
        "semantic_output_set_sha256": expected_set,
        "raw_assertion_bundle": expected_semantic["raw_assertion_bundle"],
        "assertion_count": expected_semantic["assertion_count"],
        "fallback_count": 0,
        "active_retained_absolute_ref_dereference_count": 0,
        "snapshot_mount_readonly": True,
        "authority_mount_count": 0,
        "network_mode": "none",
        "readonly_rootfs": True,
        "container_cleanup_verified": cleanup_verified,
        "f4_oci_relocatable_execution": True,
        "foundation_v4_relocatable_execution": False,
        "claim_scope": verified["claim_scope"],
        "pre_execution_runner_anchor_required": True,
        "runner_anchor_check_scope": (
            "caller must verify the copied runner hash before execution; in-script checking "
            "detects corruption but does not authenticate the executing code"
        ),
    }
    receipt = {**core, "content_sha256": _canonical_sha256(core)}
    path = output_root / "portable_execution_receipt.json"
    _write_canonical(path, receipt)
    return path


def _pack_root_from_entrypoint() -> Path:
    entrypoint = _assert_no_lexical_reparse(Path(__file__), label="portable pack entrypoint")
    _require(entrypoint.is_file(), f"portable pack entrypoint is missing: {entrypoint}")
    return entrypoint.parent


def _hash(value: str, *, label: str) -> str:
    normalized = value.lower()
    _require(
        len(normalized) == 64 and all(character in "0123456789abcdef" for character in normalized),
        f"{label} is not a SHA-256 hex digest",
    )
    return normalized


def _verify_source_admission_anchors(
    *, observed: Mapping[str, str], expected: Mapping[str, str]
) -> None:
    _require(
        set(observed) == set(expected) == set(SOURCE_ANCHOR_KEYS),
        "portable build source-anchor inventory drifted",
    )
    for key in SOURCE_ANCHOR_KEYS:
        _require(
            observed[key] == _hash(expected[key], label=f"expected {key}"),
            f"portable build source anchor drifted: {key}",
        )


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--frozen-inputs", type=Path, required=True)
    build.add_argument("--canonical-execution", type=Path, required=True)
    build.add_argument("--data-root", type=Path, required=True)
    build.add_argument("--foundation-root", type=Path, required=True)
    build.add_argument("--blueprint", type=Path, required=True)
    build.add_argument("--expected-foundation-physical-file-count", type=int, required=True)
    for key in SOURCE_ANCHOR_KEYS:
        build.add_argument(f"--expected-{key.replace('_', '-')}", required=True)
    for command in ("verify", "run"):
        child = subparsers.add_parser(command)
        child.add_argument("--expected-manifest-sha256", required=True)
        child.add_argument("--expected-runner-sha256", required=True)
        child.add_argument("--expected-bundle-sha256", required=True)
        if command == "run":
            child.add_argument("--output-root", type=Path, required=True)
            child.add_argument("--require-image-absent-before-load", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        if args.command == "build":
            expected_source_anchors = {
                key: _hash(getattr(args, f"expected_{key}"), label=f"expected {key}")
                for key in SOURCE_ANCHOR_KEYS
            }
            result = build_portable_pack(
                output_root=args.output_root,
                frozen_inputs=args.frozen_inputs,
                canonical_execution=args.canonical_execution,
                data_root=args.data_root,
                foundation_root=args.foundation_root,
                blueprint=args.blueprint,
                expected_source_anchors=expected_source_anchors,
                expected_foundation_physical_file_count=(
                    args.expected_foundation_physical_file_count
                ),
            )
        else:
            anchors = {
                "expected_manifest_sha256": _hash(
                    args.expected_manifest_sha256, label="expected manifest SHA"
                ),
                "expected_runner_sha256": _hash(
                    args.expected_runner_sha256, label="expected runner SHA"
                ),
                "expected_bundle_sha256": _hash(
                    args.expected_bundle_sha256, label="expected bundle SHA"
                ),
            }
            pack_root = _pack_root_from_entrypoint()
            if args.command == "verify":
                result = verify_portable_pack(pack_root=pack_root, **anchors)
            else:
                receipt_path = run_portable_pack(
                    pack_root=pack_root,
                    output_root=args.output_root,
                    require_image_absent_before_load=args.require_image_absent_before_load,
                    **anchors,
                )
                receipt = _load_object(receipt_path, label="portable execution receipt")
                result = {
                    "status": receipt["status"],
                    "execution_receipt_ref": str(receipt_path),
                    "execution_receipt_sha256": _file_sha256(receipt_path),
                    "content_sha256": receipt["content_sha256"],
                    "image_id": receipt["image_id"],
                    "semantic_output_set_sha256": receipt["semantic_output_set_sha256"],
                    "load_mode": receipt["load_mode"],
                }
    except (PortableClosureError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
