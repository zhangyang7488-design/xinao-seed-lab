"""Content-addressed generator artifact binding source + family registry."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from xinao.canonical import canonical_sha256

from .constants import FAMILY_SPECS, GENERATOR_ID, SCHEMA_VERSION
from .types import GeneratorArtifact


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _iter_package_py_files(root: Path) -> list[Path]:
    files = sorted(p for p in root.rglob("*.py") if p.is_file())
    return files


def _normalized_python_source_bytes(path: Path) -> bytes:
    """Return UTF-8 source with platform checkout line endings normalized."""
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _ordered_source_digest(paths: Iterable[Path], root: Path) -> tuple[str, int]:
    """Hash relative path + file bytes for each package module in stable order."""
    h = hashlib.sha256()
    h.update(b"xinao.g4.hidden_benchmark.source_tree.v1\0")
    count = 0
    for path in paths:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = _normalized_python_source_bytes(path)
        h.update(len(rel).to_bytes(4, "big"))
        h.update(rel)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
        count += 1
    h.update(count.to_bytes(4, "big"))
    return h.hexdigest(), count


def family_registry_sha256() -> str:
    return canonical_sha256(
        {
            "schema_version": "xinao.g4.hidden_benchmark.family_registry.v1",
            "families": FAMILY_SPECS,
        }
    )


def specification_sha256() -> str:
    """Bind formal generator specification constants (not runtime secrets)."""
    return canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "generator_id": GENERATOR_ID,
            "family_ids": list(FAMILY_SPECS.keys()),
            "family_specs": FAMILY_SPECS,
            "roles": [
                "pure_producer_port",
                "no_scoring",
                "no_provider_calls",
                "no_vault_io",
            ],
        }
    )


def build_generator_artifact() -> GeneratorArtifact:
    root = _package_root()
    paths = _iter_package_py_files(root)
    source_digest, module_count = _ordered_source_digest(paths, root)
    reg = family_registry_sha256()
    spec = specification_sha256()
    artifact = canonical_sha256(
        {
            "generator_id": GENERATOR_ID,
            "source_files_sha256": source_digest,
            "family_registry_sha256": reg,
            "specification_sha256": spec,
            "module_count": module_count,
            "schema_version": "xinao.g4.hidden_benchmark.generator_artifact.v1",
        }
    )
    return GeneratorArtifact(
        generator_id=GENERATOR_ID,
        artifact_sha256=artifact,
        source_files_sha256=source_digest,
        family_registry_sha256=reg,
        specification_sha256=spec,
        module_count=module_count,
    )


def package_source_paths() -> list[str]:
    root = _package_root()
    return [p.relative_to(root).as_posix() for p in _iter_package_py_files(root)]
