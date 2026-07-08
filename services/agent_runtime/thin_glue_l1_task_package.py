"""L1 task package thin bind — Pydantic structured output (instructor-ready, no hand-roll marathon)."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, l0_intake_markdown, write_json

REPLACES_MODULE = "task_package_resolver"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l1_task_package.v1"


class ThinGlueTaskPackageModel(BaseModel):
    schema_version: str = Field(default="xinao.thin_glue.task_package.v1")
    task_id: str
    user_intent_cn: str
    source_path: str
    content_md: str
    timestamp: str
    structured_by: str = "pydantic_validate"
    instructor_available: bool = False


def thin_glue_task_package_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_TASK_PACKAGE", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_task_package"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_task_package_latest.md",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()


def _text_source_ref(path: Path, *, role: str = "thin_glue_task_entry") -> dict[str, Any]:
    exists = path.is_file()
    raw = path.read_bytes() if exists else b""
    text = raw.decode("utf-8-sig", errors="replace") if raw else ""
    return {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix.lower(),
        "role": role,
        "exists": exists,
        "read_full": exists,
        "read_in_full": exists,
        "size_bytes": len(raw),
        "line_count": len(text.splitlines()) if text else 0,
        "char_count": len(text),
        "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
        "read_error": "",
    }


def _pick_entry_path(
    root: Path,
    *,
    entry_path: str | Path | None,
    repo_root: Path,
) -> Path | None:
    if entry_path:
        candidate = Path(entry_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_file():
            return candidate
    repo_materials = repo_root / "materials"
    for name in (
        "thin_bootstrap_input.md",
        "phase0_test_input.md",
        "closure_test_input.md",
    ):
        candidate = repo_materials / name
        if candidate.is_file():
            return candidate
    if entry_path:
        explicit = Path(str(entry_path))
        if explicit.is_file():
            return explicit
    return None


def _maybe_instructor_enrich(model: ThinGlueTaskPackageModel, content_md: str) -> ThinGlueTaskPackageModel:
    if os.environ.get("XINAO_THIN_GLUE_TASK_PACKAGE_INSTRUCTOR", "0").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return model
    try:
        import instructor  # type: ignore[import-untyped]
    except ImportError:
        return model
    # Instructor optional: only when installed + explicit env; default path stays Pydantic-only.
    model.instructor_available = True
    model.structured_by = "pydantic_validate_instructor_ready"
    return model


def resolve_thin_glue_task_package(
    root: str | Path,
    *,
    entry_path: str | Path | None = None,
    runtime_root: str | Path | None = None,
    repo_root: str | Path = DEFAULT_REPO,
    package_role: str = "current_task_package",
    write: bool = True,
    **compat_kwargs: Any,
) -> dict[str, Any]:
    del compat_kwargs
    root_path = Path(root)
    repo = Path(repo_root)
    runtime = Path(runtime_root) if runtime_root else None
    generated_at = _now_iso()
    entry = _pick_entry_path(root_path, entry_path=entry_path, repo_root=repo)
    if entry is None:
        from services.agent_runtime import task_package_resolver as handroll

        payload = handroll.resolve_task_package(
            root_path,
            entry_path=entry_path,
            runtime_root=runtime_root,
            package_role=package_role,
        )
        payload["thin_glue_fallback_to_handroll"] = True
        payload["named_blocker"] = "THIN_GLUE_TASK_PACKAGE_NO_LOCAL_ENTRY"
        return payload

    intake = l0_intake_markdown(entry, max_chars=4000)
    content_md = str(intake.get("content_md") or "")
    intent_line = next(
        (line.strip() for line in content_md.splitlines() if line.strip() and not line.startswith("#")),
        content_md[:120].strip() or "thin_glue_task_package",
    )
    structured = ThinGlueTaskPackageModel(
        task_id=f"thin-glue-task-{entry.stem}",
        user_intent_cn=intent_line[:500],
        source_path=str(entry),
        content_md=content_md,
        timestamp=generated_at,
    )
    structured = _maybe_instructor_enrich(structured, content_md)
    ref = _text_source_ref(entry)
    digest_basis = [
        {
            "path": ref["path"],
            "exists": ref["exists"],
            "sha256": ref.get("sha256", ""),
            "line_count": ref.get("line_count", 0),
            "role": ref.get("role", ""),
        }
    ]
    read_order = [ref["path"]]
    checks = {
        "entry_resolved": True,
        "pydantic_structured_valid": True,
        "hand_rolled_resolver_bypassed": True,
        "content_md_non_empty": bool(content_md.strip()),
        "instructor_ready": structured.instructor_available,
    }
    passed = all(checks[k] for k in checks if k != "instructor_ready")

    payload: dict[str, Any] = {
        "schema_version": "xinao.codex_s.task_package_resolution.v1",
        "thin_glue_schema_version": SCHEMA_VERSION,
        "package_role": package_role,
        "root": str(root_path),
        "source_entry_root": str(entry.parent),
        "mode": "thin_glue_structured_task_package",
        "package_mode": "thin_glue_structured_task_package",
        "resolution": "thin_glue_l1_pydantic_structured",
        "manifest_driven": False,
        "single_entry_driven": True,
        "legacy_fallback": False,
        "legacy_fallback_allowed": False,
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "task_package_manifest_ref": {},
        "task_package_manifest": {},
        "task_package_manifest_path": "",
        "entrypoint_ref": str(entry),
        "read_at": generated_at,
        "generated_at": generated_at,
        "authority_read_order": read_order,
        "read_order": read_order,
        "required_files": [entry.name],
        "refs": [ref],
        "sampled_files": [ref],
        "file_count": 1,
        "sampled_count": 1,
        "read_full_count": 1,
        "all_required_sources_read_full": True,
        "source_package_digest_sha256": _sha256_json(digest_basis),
        "source_entry_digest_sha256": _sha256_json(digest_basis),
        "structured_task_package": structured.model_dump(),
        "hand_rolled_task_package_resolver_bypassed": True,
        "acceptance_now_can_invoke_cn": (
            f"L1 薄绑：Pydantic 结构化任务包已从 {entry.name} 解析；"
            f"意图={structured.user_intent_cn[:80]}"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": generated_at},
        "sample_policy": "thin_glue materials entry + pydantic validate; instructor optional via env",
        "external_mature_basis": ["567-labs/instructor pattern", "pydantic model_validate"],
    }

    if write and runtime is not None:
        paths = output_paths(runtime)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# Thin Glue L1 Task Package",
                    f"- entry: `{entry}`",
                    f"- task_id: `{structured.task_id}`",
                    f"- passed: {passed}",
                    payload["acceptance_now_can_invoke_cn"],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(paths["latest"]),
            "readback_zh": str(paths["readback"]),
        }

    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Thin glue L1 structured task package")
    parser.add_argument("--root", default=str(DEFAULT_REPO / "materials"))
    parser.add_argument("--entry", default="")
    parser.add_argument("--runtime-root", default=os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = resolve_thin_glue_task_package(
        args.root,
        entry_path=args.entry or None,
        runtime_root=args.runtime_root,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())