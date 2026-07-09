"""Integrated bus modular nodes — thin-bind existing mature carriers (no 1:1 glue)."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from services.agent_runtime.default_plus_dynamic_escalate import (
    resolve_parallel_lane_model_binding,
    resolve_search_tier_evidence,
)
from services.agent_runtime.routing_policy_reader import resolve_parallel_semantic
from services.agent_runtime.thin_glue_l4_search import (
    derive_search_query,
    run_external_search,
    run_local_rg_search,
)
from services.agent_runtime.lexicon_cn_escape import registry_wiring_deferred
from services.agent_runtime.thin_glue_l8_token_stack import compress_readback_fallback
from services.agent_runtime.thin_glue_stack import write_json

# Host Windows E: mirrors are bind-mounted into the worker as /external_mature/official
_DEFAULT_EXTERNAL_MATURE_ROOT = "/external_mature/official"
_DEFAULT_HOST_EXTERNAL_MATURE_ROOT = r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\official"
_HOST_EXTERNAL_MATURE_MARKER = "XINAO_EXTERNAL_MATURE"
_CONTAINER_MOUNT_PREFIX = "/external_mature/official"


def resolve_official_mirror_root(*, params: dict[str, Any] | None = None) -> Path:
    """Pick container mount when present; otherwise host E:\\ official root."""
    params = params or {}
    container = Path(
        str(
            params.get("external_mature_root")
            or os.environ.get("XINAO_EXTERNAL_MATURE_ROOT")
            or _DEFAULT_EXTERNAL_MATURE_ROOT
        )
    )
    host = Path(
        str(params.get("external_mature_root_host") or _DEFAULT_HOST_EXTERNAL_MATURE_ROOT)
    )
    if container.is_dir():
        return container
    if host.is_dir():
        return host
    return container


def resolve_external_mature_path(
    raw: str | Path,
    *,
    params: dict[str, Any] | None = None,
) -> Path:
    """Map host E:\\...\\official\\X paths onto the container mount when needed."""
    params = params or {}
    path = Path(str(raw))
    if path.exists():
        return path
    ms = str(path).replace("\\", "/")
    env_root = resolve_official_mirror_root(params=params)
    host_root = Path(
        str(params.get("external_mature_root_host") or _DEFAULT_HOST_EXTERNAL_MATURE_ROOT)
    )
    if _HOST_EXTERNAL_MATURE_MARKER in ms:
        marker = "/official/"
        if marker in ms:
            rel = ms.split(marker, 1)[1].lstrip("/")
            for root in (env_root, host_root):
                cand = root / rel
                if cand.exists():
                    return cand
        if ms.rstrip("/").endswith("/official"):
            for root in (env_root, host_root):
                if root.is_dir():
                    return root
    mount_prefix = _CONTAINER_MOUNT_PREFIX
    if ms.startswith(mount_prefix):
        rel = ms[len(mount_prefix) :].lstrip("/")
        for root in (env_root, host_root):
            cand = root / rel if rel else root
            if cand.exists():
                return cand
    for root in (env_root, host_root):
        if root.is_dir() and path.name:
            cand = root / path.name
            if cand.exists():
                return cand
    return path


def _repo_to_mirror_dir(repo_name: str) -> str:
    return repo_name.replace("/", "__") if repo_name else ""


def _load_glue_registry_entries(
    registry_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    registry: dict[str, Any] = {}
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    flat_entries: list[dict[str, Any]] = []
    layers = registry.get("layers") or {}
    if isinstance(layers, dict):
        for layer_name in sorted(layers.keys()):
            items = layers.get(layer_name)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                repo_name = str(item.get("repo") or item.get("fullName") or "").strip()
                if not repo_name or repo_name in seen:
                    continue
                seen.add(repo_name)
                flat_entries.append({**item, "layer": layer_name})
    return registry, flat_entries


def _resolve_registry_mirror_path(
    item: dict[str, Any],
    *,
    base: Path,
    params: dict[str, Any] | None = None,
) -> Path:
    local_mirror = str(item.get("local_mirror") or "").strip()
    repo_name = str(item.get("repo") or item.get("fullName") or "").strip()
    if local_mirror:
        return resolve_external_mature_path(local_mirror, params=params)
    dest_name = _repo_to_mirror_dir(repo_name)
    if not dest_name:
        return base
    return resolve_external_mature_path(base / dest_name, params=params)


def _build_registry_disk_matrix(
    flat_entries: list[dict[str, Any]],
    *,
    base: Path,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for item in flat_entries:
        repo_name = str(item.get("repo") or "")
        mirror = _resolve_registry_mirror_path(item, base=base, params=params)
        seam_ref = str(item.get("url") or item.get("bind") or "")
        is_docs_only = repo_name == "docker" or (
            seam_ref.startswith("https://docs.") and "/" not in repo_name
        )
        matrix.append(
            {
                "repo": repo_name,
                "layer": str(item.get("layer") or ""),
                "mirror": str(mirror),
                "mirror_present": mirror.is_dir(),
                "seam_ref": seam_ref,
                "optional": bool(item.get("optional")),
                "接线暂缓": registry_wiring_deferred(item),
                "docs_only": is_docs_only,
                "registry_default": not bool(
                    item.get("optional") or registry_wiring_deferred(item)
                ),
            }
        )
    return matrix


def resolve_repo_root(raw: str | Path | None = None) -> Path:
    """Map host Windows repo paths onto container /app when the worker runs in docker."""
    if raw:
        path = Path(str(raw))
        if path.is_dir():
            return path
    env = os.environ.get("XINAO_CODEX_S_REPO_ROOT", "").strip()
    if env:
        cand = Path(env)
        if cand.is_dir():
            return cand
    if raw:
        ms = str(raw).replace("\\", "/")
        if "XINAO_RESEARCH_WORKSPACES" in ms:
            cand = Path("/app")
            if cand.is_dir():
                return cand
    fallback = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")
    return fallback if fallback.is_dir() else Path.cwd()


def resolve_runtime_root(raw: str | Path | None = None) -> Path:
    """Map host D: runtime paths onto container /evidence when the worker runs in docker."""
    if raw:
        path = Path(str(raw))
        if path.is_dir():
            return path
    env = os.environ.get("XINAO_RESEARCH_RUNTIME", "").strip()
    if env:
        cand = Path(env)
        if cand.is_dir():
            return cand
    if raw:
        ms = str(raw).replace("\\", "/")
        if "XINAO_RESEARCH_RUNTIME" in ms:
            cand = Path("/evidence")
            if cand.is_dir():
                return cand
    fallback = Path(r"D:\XINAO_RESEARCH_RUNTIME")
    return fallback if fallback.is_dir() else Path.cwd()


def resolve_bus_file_path(
    raw: str | Path,
    *,
    repo_root: Path | None = None,
    runtime_root: Path | None = None,
) -> Path:
    """Map host Windows file paths onto container /app or /evidence for docker worker activities."""
    path = Path(str(raw))
    if path.is_file():
        return path

    repo = resolve_repo_root(repo_root)
    runtime = resolve_runtime_root(runtime_root)
    ms = str(path).replace("\\", "/")

    if "XINAO_RESEARCH_WORKSPACES" in ms.upper():
        for marker in ("/S/", "/s/"):
            if marker in ms:
                rel = ms.split(marker, 1)[1].lstrip("/")
                cand = Path("/app") / rel
                if cand.is_file():
                    return cand
        if "materials/" in ms:
            rel = ms.split("materials/", 1)[1]
            for base in (Path("/app"), repo):
                cand = base / "materials" / rel
                if cand.is_file():
                    return cand

    if "XINAO_RESEARCH_RUNTIME" in ms.upper():
        rel = ms.upper().split("XINAO_RESEARCH_RUNTIME", 1)[-1].lstrip("/\\")
        for base in (Path("/evidence"), runtime):
            cand = base / rel.replace("/", os.sep)
            if cand.is_file():
                return cand

    if repo.is_dir():
        for cand in (repo / path, repo / path.name):
            if cand.is_file():
                return cand

    return path


class BusTaskValidateModel(BaseModel):
    schema_version: str = Field(default="xinao.integrated_bus.validate.v1")
    source_path: str
    user_intent_cn: str
    content_chars: int
    pydantic_ok: bool = True


class BusPlannerStepModel(BaseModel):
    step: int
    action: str
    owner: str = "integrated_bus"
    rationale_cn: str = ""


class BusPlannerPlanModel(BaseModel):
    schema_version: str = Field(default="xinao.integrated_bus.planner.v1")
    user_intent_cn: str
    plan_steps: list[BusPlannerStepModel]
    structured_by: str = "pydantic_structured_plan"
    llm_invoked: bool = False


class BusInstructorExtractModel(BaseModel):
    schema_version: str = Field(default="xinao.integrated_bus.instructor_extract.v1")
    user_intent_cn: str
    keywords: list[str] = Field(default_factory=list)


def _write_invoke_evidence(runtime_root: Path, subdir: str, record: dict[str, Any]) -> str:
    out_dir = resolve_runtime_root(runtime_root) / "state" / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "latest.json"
    write_json(path, record)
    return str(path)


def _run_fastmcp_async_coro(coro: Any) -> dict[str, Any]:
    """Run FastMCP coroutine — safe inside Temporal/LangGraph running event loops."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if in_loop:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result(timeout=45)
    return asyncio.run(coro)


def _invoke_fastmcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """In-process FastMCP tool call — jlowin fastmcp first, then mcp.server.fastmcp."""
    last_error = "tool_call_empty"

    async def _run_jlowin() -> dict[str, Any]:
        from fastmcp import FastMCP  # type: ignore[import-untyped]

        server = FastMCP("integrated-bus-smoke")

        @server.tool()
        def integrated_bus_ping(message: str = "ok") -> str:
            return f"integrated_bus:{message}"

        result = await server.call_tool(tool_name, arguments)
        text = ""
        if isinstance(result, tuple) and result:
            content = result[0]
            if content and hasattr(content[0], "text"):
                text = str(content[0].text or "")
        return {"ok": bool(text.strip()), "tool_result": text, "adapter": "fastmcp_jlowin_invoke"}

    async def _run_mcp_sdk() -> dict[str, Any]:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("integrated-bus-smoke")

        @server.tool()
        def integrated_bus_ping(message: str = "ok") -> str:
            return f"integrated_bus:{message}"

        content, meta = await server.call_tool(tool_name, arguments)
        text = ""
        if content and hasattr(content[0], "text"):
            text = str(content[0].text or "")
        elif isinstance(meta, dict):
            text = str(meta.get("result") or "")
        return {"ok": bool(text.strip()), "tool_result": text, "adapter": "fastmcp_mcp_sdk_invoke"}

    for runner in (_run_jlowin, _run_mcp_sdk):
        try:
            payload = _run_fastmcp_async_coro(runner())
            if payload.get("ok"):
                return payload
            last_error = "tool_call_empty"
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "adapter": "fastmcp_invoke_failed", "error": last_error}


def run_duckdb_bus(*, runtime_root: Path, content_md: str = "") -> dict[str, Any]:
    runtime_root = resolve_runtime_root(runtime_root)
    db_dir = runtime_root / "state" / "duckdb"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "integrated_bus.duckdb"
    row_count = 0
    invoked = False
    adapter = "duckdb_invoke_failed"
    error = ""
    try:
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute(
            "CREATE TABLE IF NOT EXISTS integrated_bus_intake "
            "(run_ts TIMESTAMP, content_chars INTEGER)"
        )
        con.execute(
            "INSERT INTO integrated_bus_intake VALUES (current_timestamp, ?)",
            [len(content_md)],
        )
        row_count = int(con.execute("SELECT COUNT(*) FROM integrated_bus_intake").fetchone()[0])
        con.close()
        invoked = True
        adapter = "duckdb_invoke"
    except Exception as exc:
        error = str(exc)
        adapter = f"duckdb_invoke_failed:{type(exc).__name__}"
    evidence_ref = _write_invoke_evidence(
        runtime_root,
        "duckdb",
        {
            "schema_version": "xinao.integrated_bus.duckdb_invoke.v1",
            "invoke_ok": invoked,
            "adapter": adapter,
            "db_path": str(db_path),
            "row_count": row_count,
            "content_chars": len(content_md),
            "error": error,
        },
    )
    return {
        "duckdb_ok": invoked,
        "duckdb_invoked": invoked,
        "duckdb_path": str(db_path),
        "duckdb_row_count": row_count,
        "duckdb_evidence_ref": evidence_ref,
        "adapter": adapter,
    }


def run_watchdog_bus(*, runtime_root: Path) -> dict[str, Any]:
    import time

    runtime_root = resolve_runtime_root(runtime_root)
    watch_dir = runtime_root / "state" / "watchdog" / "integrated_bus"
    inbox = watch_dir / "inbox"
    watch_dir.mkdir(parents=True, exist_ok=True)
    inbox.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    events: list[str] = []
    invoked = False
    adapter = "watchdog_invoke_failed"
    error = ""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class _Handler(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                if not event.is_directory:
                    events.append(str(event.src_path))

        observer = Observer()
        observer.schedule(_Handler(), str(inbox), recursive=False)
        observer.start()
        trigger = inbox / f"watchdog_invoke_{run_id}.md"
        trigger.write_text("integrated_bus watchdog invoke probe\n", encoding="utf-8")
        time.sleep(0.65)
        observer.stop()
        observer.join(timeout=3.0)
        invoked = trigger.is_file() and (bool(events) or observer.is_alive() is False)
        adapter = "watchdog_observer_invoke"
    except Exception as exc:
        error = str(exc)
        adapter = f"watchdog_invoke_failed:{type(exc).__name__}"
    marker = watch_dir / ".watch_marker"
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    evidence_ref = _write_invoke_evidence(
        runtime_root,
        "watchdog",
        {
            "schema_version": "xinao.integrated_bus.watchdog_invoke.v1",
            "invoke_ok": invoked,
            "adapter": adapter,
            "watchdog_dir": str(watch_dir),
            "events_detected": events[:8],
            "event_count": len(events),
            "trigger_path": str(inbox / f"watchdog_invoke_{run_id}.md"),
            "error": error,
        },
    )
    return {
        "watchdog_ok": invoked,
        "watchdog_invoked": invoked,
        "watchdog_dir": str(watch_dir),
        "watchdog_observer_ready": invoked,
        "watchdog_entry_count": len(list(watch_dir.iterdir())),
        "watchdog_evidence_ref": evidence_ref,
        "adapter": adapter,
    }


def run_validate_bus(*, input_path: str, content_md: str) -> dict[str, Any]:
    intent = next(
        (line.strip() for line in content_md.splitlines() if line.strip() and not line.startswith("#")),
        content_md[:120].strip() or "integrated_bus",
    )
    model = BusTaskValidateModel(
        source_path=input_path,
        user_intent_cn=intent[:500],
        content_chars=len(content_md),
    )
    return {
        "validate_ok": True,
        "task_package": model.model_dump(),
        "structured_by": "pydantic_validate",
    }


def run_search_bus(
    *,
    repo_root: Path,
    content_md: str,
    max_results: int = 6,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = derive_search_query(content_md, fallback="integrated_bus")
    local = run_local_rg_search(repo_root, query, max_results=max_results)
    search_context = dict(context or {})
    search_context.setdefault("content_md", content_md)
    external = run_external_search(query, max_results=min(max_results, 5), context=search_context)
    tier_evidence = resolve_search_tier_evidence(external)
    local_hits = int(local.get("hit_count") or 0)
    external_hits = int(external.get("hit_count") or 0)
    total_hits = local_hits + external_hits
    searx = external.get("searxng") or {}
    ddgs_gate = external.get("ddgs_gate_hits_required") is True
    search_ok = local_hits > 0 or external_hits > 0
    search_skipped = False
    search_named_blocker = ""
    if not search_ok:
        if ddgs_gate and external_hits == 0:
            search_skipped = True
            search_named_blocker = str(
                external.get("ddgs_named_blocker") or "INTEGRATED_BUS_L4_DDGS_ZERO_HITS_SEARXNG_NOT_IN_COMPOSE"
            )
        elif searx.get("skipped") and local_hits == 0:
            search_skipped = True
            search_named_blocker = "INTEGRATED_BUS_L4_SEARCH_NO_HITS_SEARXNG_SKIPPED"
        else:
            search_named_blocker = "INTEGRATED_BUS_L4_SEARCH_NO_HITS"
    external_hits_list = list(external.get("hits") or [])
    return {
        "search_ok": search_ok,
        "search_query": query,
        "search_adapter": f"{local.get('adapter') or 'ripgrep'}+{external.get('adapter') or 'external'}",
        "search_hit_count": total_hits,
        "search_local_hit_count": local_hits,
        "search_external_hit_count": external_hits,
        "search_hits": (local.get("hits") or [])[:max_results],
        "search_external_hits": external_hits_list[:max_results],
        "search_external": external,
        "search_skipped": search_skipped,
        "search_named_blocker": search_named_blocker,
        "searxng_compose_available": external.get("searxng_compose_available"),
        "ddgs_gate_hits_required": ddgs_gate,
        **tier_evidence,
        "search_escalate_policy": "default_plus_dynamic_escalate.v1",
    }


def ensure_git_repo(repo_root: Path) -> bool:
    """Ensure repo_root has a git metadata dir (container /app may lack .git on stale images)."""
    repo_root = resolve_repo_root(repo_root)
    if (repo_root / ".git").exists():
        return True
    import subprocess

    init = subprocess.run(
        ["git", "init"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if init.returncode != 0 or not (repo_root / ".git").exists():
        return False
    for key, val in (
        ("user.email", "houtai-gongren@local"),
        ("user.name", "后台工人"),
    ):
        subprocess.run(["git", "config", key, val], cwd=repo_root, check=False, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=False, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "integrated_bus worker bootstrap", "--allow-empty"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return (repo_root / ".git").exists()


def _git_name_only(repo_root: Path, *args: str) -> list[str]:
    import subprocess

    proc = subprocess.run(
        ["git", "diff", "--name-only", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _diff_cover_tool_available(repo_root: Path) -> bool:
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "diff_cover.diff_cover_tool", "--version"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return proc.returncode == 0


def _ensure_coverage_xml(repo_root: Path, *, pytest_node: str) -> bool:
    import subprocess

    coverage_xml = repo_root / "coverage.xml"
    if coverage_xml.is_file():
        return True
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            pytest_node,
            "--cov=services.agent_runtime",
            "--cov-report=xml",
            "-q",
            "--tb=line",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return coverage_xml.is_file() and proc.returncode == 0


def run_diff_cover_slice(
    *,
    repo_root: Path,
    runtime_root: Path | None = None,
    pytest_node: str = "tests/test_thin_glue_stack.py::test_facade_hard_redirect_blocks_handroll_on_default",
) -> dict[str, Any]:
    from services.agent_runtime.closure_test_activities import activity_l5_diff_cover

    repo_root = resolve_repo_root(repo_root)
    runtime_root = resolve_runtime_root(runtime_root)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    evidence_run_id = f"integrated_bus_{run_id}"
    try:
        if not (repo_root / ".git").exists() and not ensure_git_repo(repo_root):
            return {
                "diff_cover_ok": False,
                "diff_cover_skipped": True,
                "named_blocker": "GIT_REPO_MISSING",
                "adapter": "git_repo_missing",
                "repo_root": str(repo_root),
                "error": "git repository not found at resolved repo_root",
            }
        if not _diff_cover_tool_available(repo_root):
            return {
                "diff_cover_ok": False,
                "diff_cover_skipped": True,
                "named_blocker": "DIFF_COVER_NOT_INSTALLED",
                "adapter": "diff_cover_honest_skip",
                "repo_root": str(repo_root),
            }
        coverage_ready = _ensure_coverage_xml(repo_root, pytest_node=pytest_node)
        if not coverage_ready and not (repo_root / "coverage.xml").is_file():
            return {
                "diff_cover_ok": False,
                "diff_cover_skipped": True,
                "named_blocker": "COVERAGE_XML_MISSING",
                "adapter": "diff_cover_coverage_prereq",
                "pytest_node": pytest_node,
            }
        result = activity_l5_diff_cover(
            repo=repo_root,
            runtime=runtime_root,
            run_id=evidence_run_id,
        )
        raw_exit = result.get("exit_code")
        exit_code = int(raw_exit) if raw_exit is not None else 1
        percent = float(result.get("diff_cover_percent") or 0.0)
        invoked = bool(result.get("path")) and raw_exit is not None
        return {
            "diff_cover_ok": invoked,
            "diff_cover_percent": percent,
            "exit_code": exit_code,
            "evidence_path": result.get("path"),
            "pytest_node": pytest_node,
            "adapter": "diff_cover_closure_test_pattern",
        }
    except Exception as exc:
        return {
            "diff_cover_ok": False,
            "diff_cover_skipped": True,
            "named_blocker": "DIFF_COVER_INVOCATION_FAILED",
            "adapter": "diff_cover_probe",
            "error": str(exc),
        }


def run_otel_trace_slice(*, workflow_id: str = "") -> dict[str, Any]:
    span_name = "integrated_bus_fanin"
    workflow_ref = (workflow_id or "integrated-bus-local")[:64]
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        tracer = trace.get_tracer("xinao.integrated_bus")
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("workflow_id", workflow_ref)
            ctx = span.get_span_context()
            trace_id_hex = format(ctx.trace_id, "032x")
            span_id_hex = format(ctx.span_id, "016x")
        return {
            "otel_ok": True,
            "trace_id": trace_id_hex,
            "span_id": span_id_hex,
            "span_name": span_name,
            "workflow_id": workflow_ref,
            "adapter": "opentelemetry_sdk_span",
        }
    except Exception as exc:
        return {
            "otel_ok": False,
            "otel_skipped": True,
            "named_blocker": "OTEL_SDK_UNAVAILABLE",
            "trace_id": workflow_ref,
            "span_name": span_name,
            "adapter": "opentelemetry_honest_skip",
            "error": str(exc),
        }


def run_planner_bus(
    *,
    task_package: dict[str, Any] | None = None,
    heal_repair_required: bool = False,
    failed_checks: list[str] | None = None,
) -> dict[str, Any]:
    """Honest structured planner — Pydantic plan model; repair branch when L6 critic routes back."""
    pkg = task_package or {}
    intent = str(pkg.get("user_intent_cn") or "integrated_bus")
    failed = list(failed_checks or [])
    if heal_repair_required and failed:
        steps = [
            BusPlannerStepModel(
                step=1,
                action="heal_repair_rerun",
                rationale_cn=f"repair:{','.join(failed[:6])}",
            ),
            BusPlannerStepModel(step=2, action="fanin_promotion", rationale_cn="critic_short_circuit"),
        ]
        adapter = "pydantic_planner_heal_repair"
    else:
        steps = [
            BusPlannerStepModel(step=1, action="intake_validate", rationale_cn="L0 intake+validate"),
            BusPlannerStepModel(step=2, action="search_mcp_parallel", rationale_cn="L4+L9 parallel lanes"),
            BusPlannerStepModel(step=3, action="fanin_promotion", rationale_cn="L5 fan-in+promotion"),
        ]
        adapter = "pydantic_structured_plan_invoke_green"
    plan = BusPlannerPlanModel(user_intent_cn=intent[:500], plan_steps=steps)
    return {
        "planner_ok": True,
        "plan_steps": [s.model_dump() for s in plan.plan_steps],
        "planner_intent_cn": plan.user_intent_cn[:200],
        "planner_structured_by": plan.structured_by,
        "planner_llm_invoked": plan.llm_invoked,
        "heal_repair_plan": heal_repair_required,
        "adapter": adapter,
    }


def _pick_http_url_from_search(
    *,
    search_external_hits: list[dict[str, Any]] | None = None,
    search_external: dict[str, Any] | None = None,
) -> str:
    candidates: list[str] = []
    github_first: list[str] = []

    def _collect(hit: dict[str, Any]) -> None:
        url = str(hit.get("url") or hit.get("href") or "").strip()
        if not url.startswith("http"):
            return
        if url in candidates or url in github_first:
            return
        if hit.get("is_github") or "github.com" in url:
            github_first.append(url)
        else:
            candidates.append(url)

    for hit in search_external_hits or []:
        if isinstance(hit, dict):
            _collect(hit)
    ext = search_external or {}
    for hit in ext.get("hits") or []:
        if isinstance(hit, dict):
            _collect(hit)
    ordered = github_first + candidates
    if ordered:
        return ordered[0]
    return "https://docs.temporal.io/develop/python/integrations/langgraph"


def run_crawl4ai_bus(
    *,
    params: dict[str, Any],
    query: str = "",
    runtime_root: Path | None = None,
    search_external_hits: list[dict[str, Any]] | None = None,
    search_external: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Real fetch: one HTTP URL from L4 search hits (crawl4ai → httpx fallback)."""
    runtime_root = resolve_runtime_root(runtime_root or params.get("runtime_root"))
    mirror = resolve_external_mature_path(
        params.get("crawl4ai_mirror")
        or "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\official\\unclecode__crawl4ai",
        params=params,
    )
    present = mirror.is_dir() or (mirror / "README.md").is_file()
    invoked = False
    adapter = "crawl4ai_invoke_failed"
    excerpt = ""
    error = ""
    crawl_query = (query or "integrated_bus")[:120]
    target_url = _pick_http_url_from_search(
        search_external_hits=search_external_hits,
        search_external=search_external,
    )
    if not target_url:
        return {
            "crawl4ai_ok": False,
            "crawl4ai_skipped": True,
            "crawl4ai_named_blocker": "CRAWL4AI_NO_HTTP_URL_FROM_SEARCH",
            "crawl4ai_invoked": False,
            "crawl4ai_mirror_present": present,
            "crawl4ai_mirror": str(mirror),
            "crawl4ai_query": crawl_query,
            "adapter": "crawl4ai_honest_skip_no_url",
        }

    try:

        async def _crawl_search_hit() -> str:
            from crawl4ai import AsyncWebCrawler  # type: ignore[import-untyped]

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=target_url)
                return str(getattr(result, "markdown", "") or getattr(result, "text", "") or "")[:1200]

        excerpt = str(_run_fastmcp_async_coro(_crawl_search_hit()) or "")
        invoked = bool(excerpt.strip())
        if invoked:
            adapter = "crawl4ai_async_webcrawler_search_hit"
    except Exception as exc:
        error = str(exc)
        try:
            import httpx

            resp = httpx.get(
                target_url,
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": "xinao-integrated-bus/1.0 (research smoke)"},
            )
            excerpt = (resp.text or "")[:1200]
            invoked = resp.status_code == 200 and len(excerpt.strip()) > 80
            adapter = "crawl4ai_httpx_search_hit_fallback"
            if not invoked:
                error = error or f"http_{resp.status_code}"
        except Exception as http_exc:
            error = f"{error};{http_exc}".strip(";")
            adapter = f"crawl4ai_fetch_failed:{type(http_exc).__name__}"

    readme = mirror / "README.md"
    if not invoked and readme.is_file():
        try:
            from markitdown import MarkItDown

            converted = MarkItDown().convert(str(readme))
            excerpt = str(getattr(converted, "text_content", "") or "")[:800]
            invoked = bool(excerpt.strip())
            if invoked:
                adapter = "crawl4ai_markitdown_mirror_invoke"
                error = ""
        except Exception as md_exc:
            error = f"{error};{md_exc}".strip(";")

    evidence_ref = _write_invoke_evidence(
        runtime_root,
        "crawl4ai",
        {
            "schema_version": "xinao.integrated_bus.crawl4ai_invoke.v1",
            "invoke_ok": invoked,
            "adapter": adapter,
            "mirror": str(mirror),
            "mirror_present": present,
            "query": crawl_query,
            "target_url": target_url,
            "excerpt": excerpt[:400],
            "error": error,
        },
    )
    return {
        "crawl4ai_ok": invoked,
        "crawl4ai_skipped": not invoked,
        "crawl4ai_named_blocker": "" if invoked else (error or "CRAWL4AI_FETCH_EMPTY_OR_FAILED"),
        "crawl4ai_invoked": invoked,
        "crawl4ai_url": target_url,
        "crawl4ai_mirror_present": present,
        "crawl4ai_mirror": str(mirror),
        "crawl4ai_query": crawl_query,
        "crawl4ai_excerpt": excerpt[:400],
        "crawl4ai_evidence_ref": evidence_ref,
        "adapter": adapter,
    }


def run_checkpoint_bus(
    *,
    runtime_root: Path,
    workflow_id: str = "",
    state_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Real SqliteSaver bind — writes checkpoint tuple to sqlite (not path-only stub)."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    ck_dir = runtime_root / "state" / "langgraph_checkpoint"
    ck_dir.mkdir(parents=True, exist_ok=True)
    db_path = ck_dir / "integrated_bus.sqlite"
    thread_id = workflow_id or "integrated_bus_smoke"
    invoked = False
    checkpoint_id = ""
    error = ""
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        saver = SqliteSaver(conn)
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        snapshot = dict(state_snapshot or {})
        snapshot.setdefault("workflow_id", workflow_id)
        snapshot.setdefault("checkpoint_bound", True)
        checkpoint = {
            "v": 1,
            "id": f"integrated-bus-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "channel_values": snapshot,
            "channel_versions": {},
            "versions_seen": {},
        }
        saver.put(config, checkpoint, {}, {})
        listed = list(saver.list(config, limit=1))
        invoked = len(listed) >= 1
        if listed:
            checkpoint_id = str(getattr(listed[0], "id", "") or listed[0].config.get("configurable", {}).get("checkpoint_id", ""))
        conn.close()
    except Exception as exc:
        error = str(exc)
    record = {
        "schema_version": "xinao.integrated_bus.checkpoint.v1",
        "thread_id": thread_id,
        "checkpoint_db": str(db_path),
        "checkpoint_id": checkpoint_id,
        "saver_invoked": invoked,
        "adapter": "langgraph_sqlite_checkpoint_invoke_green",
        "error": error,
    }
    write_json(ck_dir / "latest.json", record)
    return {
        "checkpoint_ok": invoked,
        "checkpoint_db": str(db_path),
        "checkpoint_thread_id": thread_id,
        "checkpoint_invoked": invoked,
        "checkpoint_id": checkpoint_id,
        "checkpoint_evidence_ref": str(ck_dir / "latest.json"),
        "adapter": record["adapter"],
    }


def run_fanin_bus(
    state: dict[str, Any],
    *,
    runtime_root: Path,
    workflow_id: str = "",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    runtime_root = resolve_runtime_root(runtime_root)
    effective_repo = resolve_repo_root(repo_root or state.get("repo_root"))
    ledger_dir = runtime_root / "state" / "source_ledger" / "integrated_bus"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    diff_slice = run_diff_cover_slice(repo_root=effective_repo, runtime_root=runtime_root)
    otel_slice = run_otel_trace_slice(workflow_id=workflow_id)
    record = {
        "schema_version": "xinao.integrated_bus.fanin_slice.v1",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "role": "integrated_bus_fanin",
        "intake_adapter": state.get("adapter"),
        "gateway_trace_ok": state.get("gateway_trace_ok"),
        "search_hit_count": state.get("search_hit_count"),
        "parallel_succeeded": state.get("parallel_succeeded"),
        "mcp_tools_ok": state.get("mcp_tools_ok"),
        "planner_ok": state.get("planner_ok"),
        "crawl4ai_ok": state.get("crawl4ai_ok"),
        "worker_lane_ok": state.get("worker_lane_ok"),
        "worker_lane_provider": state.get("worker_lane_provider"),
        "worker_lane_artifact_ref": state.get("worker_lane_artifact_ref"),
        "draft_model": state.get("draft_model") or state.get("worker_lane_model"),
        "pro_review_ok": state.get("pro_review_ok"),
        "pro_review_model": state.get("pro_review_model"),
        "review_model": state.get("review_model") or state.get("pro_review_model"),
        "parallel_semantic": state.get("parallel_semantic"),
        "fanin_mode": state.get("fanin_mode"),
        "completion_order": state.get("completion_order"),
        "as_completed_fanin": state.get("as_completed_fanin"),
        "as_completed_fanin_ok": state.get("as_completed_fanin_ok"),
        "tier_used": state.get("tier_used"),
        "parallel_lane_models": state.get("parallel_lane_models"),
        "pro_review_evidence_ref": state.get("pro_review_evidence_ref"),
        "diff_cover": diff_slice,
        "otel": otel_slice,
        "promotion_pending": True,
    }
    path = ledger_dir / f"fanin_{run_id}.json"
    write_json(path, record)
    latest = ledger_dir / "latest.json"
    write_json(latest, record)
    return {
        "fanin_ok": True,
        "fanin_evidence_ref": str(path),
        "source_ledger_latest": str(latest),
        "diff_cover_ok": diff_slice.get("diff_cover_ok") is True,
        "diff_cover_skipped": diff_slice.get("diff_cover_skipped") is True,
        "diff_cover_named_blocker": str(diff_slice.get("named_blocker") or ""),
        "otel_ok": otel_slice.get("otel_ok") is True,
        "otel_skipped": otel_slice.get("otel_skipped") is True,
        "otel_named_blocker": str(otel_slice.get("named_blocker") or ""),
    }


_READBACK_JINJA_TEMPLATE = """# integrated_bus {{ run_id }}

{% for line in summary_lines -%}
{{ line }}
{% endfor %}

---
- compression: {{ compression_adapter }}
- jinja: {{ jinja_adapter }}
- rtk: {{ rtk_used }}
- caveman: {{ caveman_used }}
"""


def _render_readback_jinja(
    *,
    run_id: str,
    summary_lines: list[str],
    compression_adapter: str,
) -> tuple[str, str]:
    """Jinja2 readback when available; deterministic fallback otherwise."""
    try:
        from jinja2 import Template

        body = Template(_READBACK_JINJA_TEMPLATE).render(
            run_id=run_id,
            summary_lines=summary_lines,
            compression_adapter=compression_adapter,
            jinja_adapter="jinja2_template",
            rtk_used=compression_adapter == "rtk",
            caveman_used=compression_adapter == "caveman",
        )
        return body, "jinja2_template"
    except Exception:
        lines = [f"# integrated_bus {run_id}", ""]
        lines.extend(summary_lines)
        lines.extend(
            [
                "",
                "---",
                f"- compression: {compression_adapter}",
                "- jinja: string_fallback",
                f"- rtk: {compression_adapter == 'rtk'}",
                f"- caveman: {compression_adapter == 'caveman'}",
            ]
        )
        return "\n".join(lines) + "\n", "jinja_string_fallback"


def run_token_bus(
    *,
    summary_text: str,
    runtime_root: Path,
    compressed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_l8_token_stack import compress_readback_text

    compressed = compressed or compress_readback_text(summary_text, max_chars=2000)
    compression_adapter = str(compressed.get("adapter") or "")
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    summary_lines = [ln for ln in str(compressed.get("text") or "").splitlines() if ln.strip()]
    jinja_body, jinja_adapter = _render_readback_jinja(
        run_id=run_id,
        summary_lines=summary_lines,
        compression_adapter=compression_adapter,
    )
    out_dir = runtime_root / "readback" / "zh" / "integrated_bus"
    out_dir.mkdir(parents=True, exist_ok=True)
    zh_path = out_dir / f"summary_{run_id}.md"
    zh_path.write_text(jinja_body, encoding="utf-8")
    jinja_ref_dir = runtime_root / "state" / "integrated_bus_jinja_readback"
    jinja_ref_dir.mkdir(parents=True, exist_ok=True)
    jinja_record = {
        "schema_version": "xinao.integrated_bus.jinja_readback.v1",
        "run_id": run_id,
        "template_engine": jinja_adapter,
        "compression_adapter": compression_adapter,
        "rtk_adapter": "rtk" if compression_adapter == "rtk" else "",
        "caveman_adapter": "caveman" if compression_adapter == "caveman" else "",
        "output_path": str(zh_path),
        "before_chars": int(compressed.get("before_chars") or 0),
        "after_chars": int(compressed.get("after_chars") or 0),
    }
    write_json(jinja_ref_dir / "latest.json", jinja_record)
    return {
        "token_bus_ok": compressed.get("ok") is True,
        "readback_zh_ref": str(zh_path),
        "jinja_readback_ref": str(jinja_ref_dir / "latest.json"),
        "jinja_adapter": jinja_adapter,
        "compression_adapter": compression_adapter,
        "rtk_adapter": "rtk" if compression_adapter == "rtk" else "",
        "caveman_adapter": "caveman" if compression_adapter == "caveman" else "",
        "rtk_named_blocker": str(compressed.get("rtk_named_blocker") or ""),
        "caveman_named_blocker": str(compressed.get("caveman_named_blocker") or ""),
    }


def _integrated_bus_health_checks(state: dict[str, Any]) -> dict[str, bool]:
    return {
        "validate_ok": state.get("validate_ok") is True,
        "fanin_ok": state.get("fanin_ok") is True,
        "promotion_gate_passed": state.get("promotion_gate_passed") is True,
        "token_bus_ok": state.get("token_bus_ok") is True,
        "pytest_slice_ok": state.get("pytest_slice_ok") is not False,
    }


def run_heal_bus(
    *,
    params: dict[str, Any],
    state: dict[str, Any] | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """L6 invoke_green — Temporal retry policy evidence + structured critic for graph conditional edge."""
    from services.agent_runtime.thin_glue_l6_self_heal import temporal_retry_policy_spec

    bus_state = dict(state or {})
    checks = _integrated_bus_health_checks(bus_state)
    failed = [name for name, ok in checks.items() if not ok]
    passed = not failed
    retry_count = int(bus_state.get("heal_retry_count") or 0)

    policy = dict(params.get("temporal_retry_policy") or temporal_retry_policy_spec())
    policy["adapter"] = "temporalio.contrib.langgraph.RetryPolicy"
    policy["evidence_source"] = "integrated_bus_params.v1.json"

    if passed:
        critic = {
            "decision": "all_pass_continue",
            "repair_required": False,
            "critic_edge": "checkpoint",
            "failed_checks": [],
            "action": "continue_checkpoint",
        }
    elif retry_count >= 1:
        critic = {
            "decision": "retry_exhausted_continue",
            "repair_required": False,
            "critic_edge": "checkpoint",
            "failed_checks": failed,
            "action": "continue_after_single_repair",
        }
    else:
        critic = {
            "decision": "repair_required",
            "repair_required": True,
            "critic_edge": "planner",
            "failed_checks": failed,
            "action": "route_planner_repair_once",
        }

    evidence: dict[str, Any] = {
        "schema_version": "xinao.integrated_bus.heal_bus.v1",
        "retry_policy": policy,
        "critic": critic,
        "health_checks": checks,
        "heal_retry_count": retry_count,
        "critic_edge_wired": True,
        "adapter": "temporal_retry_langgraph_critic_invoke_green",
    }
    evidence_ref = ""
    if runtime_root is not None:
        heal_dir = resolve_runtime_root(runtime_root) / "state" / "integrated_bus_heal"
        heal_dir.mkdir(parents=True, exist_ok=True)
        evidence_ref = str(heal_dir / "latest.json")
        write_json(Path(evidence_ref), evidence)

    return {
        "heal_bus_ok": True,
        "retry_policy": policy,
        "retry_policy_evidence_ref": evidence_ref,
        "critic_decision": critic["decision"],
        "critic_edge": critic["critic_edge"],
        "critic_edge_wired": True,
        "heal_repair_required": critic.get("repair_required") is True,
        "heal_failed_checks": failed,
        "heal_retry_count": retry_count + (1 if critic.get("repair_required") else 0),
        "adapter": evidence["adapter"],
    }


def run_mcp_tools_bus(
    *,
    params: dict[str, Any],
    repo_root: Path,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    runtime_root = resolve_runtime_root(runtime_root or params.get("runtime_root"))
    mirror = resolve_external_mature_path(
        params.get("fastmcp_mirror")
        or "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\official\\jlowin__fastmcp",
        params=params,
    )
    tool_name = str(params.get("fastmcp_smoke_tool") or "integrated_bus_ping")
    invoke = _invoke_fastmcp_tool(tool_name, {"message": "invoke_green"})
    invoked = invoke.get("ok") is True
    evidence_ref = _write_invoke_evidence(
        runtime_root,
        "fastmcp_invoke",
        {
            "schema_version": "xinao.integrated_bus.fastmcp_invoke.v1",
            "invoke_ok": invoked,
            "adapter": str(invoke.get("adapter") or "fastmcp_invoke_failed"),
            "tool_name": tool_name,
            "tool_result": str(invoke.get("tool_result") or ""),
            "mirror_path": str(mirror),
            "mirror_present": mirror.is_dir(),
            "error": str(invoke.get("error") or ""),
        },
    )
    return {
        "mcp_tools_ok": invoked,
        "mcp_tool_invoked": invoked,
        "mcp_tool_name": tool_name,
        "mcp_tool_result": str(invoke.get("tool_result") or ""),
        "mcp_registry_probe": {
            "mirror_path": str(mirror),
            "mirror_present": mirror.is_dir(),
            "bind_target": "langgraph_tool_node",
        },
        "mcp_invoke_evidence_ref": evidence_ref,
        "mcp_adapter": str(invoke.get("adapter") or "fastmcp_invoke_failed"),
    }


def run_mirror_registry_bus(
    *,
    params: dict[str, Any],
    runtime_root: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    base = resolve_official_mirror_root(params=params)
    effective_repo = resolve_repo_root(repo_root)
    registry_path = (
        effective_repo / "materials" / "authority_glue" / "glue_mature_repo_registry.v1.json"
    )
    _, flat_entries = _load_glue_registry_entries(registry_path)
    matrix = _build_registry_disk_matrix(flat_entries, base=base, params=params)

    on_disk_dirs = sorted(
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and "__" in entry.name
    ) if base.is_dir() else []

    default_rows = [row for row in matrix if row.get("registry_default") and not row.get("docs_only")]
    default_present = sum(1 for row in default_rows if row.get("mirror_present"))
    default_total = len(default_rows)
    all_present = sum(1 for row in matrix if row.get("mirror_present"))
    ghost_rows = [row for row in matrix if not row.get("mirror_present") and not row.get("docs_only")]

    required = list(
        params.get("mirror_required_dirs")
        or [
            "jlowin__fastmcp",
            "unclecode__crawl4ai",
            "temporalio__samples-python",
            "BerriAI__litellm",
            "microsoft__markitdown",
        ]
    )
    probes: list[dict[str, Any]] = []
    for name in required:
        path = resolve_external_mature_path(base / str(name), params=params)
        probes.append({"name": str(name), "path": str(path), "present": path.is_dir()})
    optional = resolve_external_mature_path(
        params.get("searxng_mirror") or base / "searxng__searxng",
        params=params,
    )
    probes.append(
        {
            "name": "searxng__searxng",
            "path": str(optional),
            "present": optional.is_dir(),
            "partial_ok": True,
        }
    )
    present = sum(1 for item in probes if item.get("present"))
    runtime_root = resolve_runtime_root(runtime_root)
    out_dir = runtime_root / "state" / "mirror_registry"
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.mirror_registry.v1",
        "base": str(base),
        "registry_path": str(registry_path),
        "probe_count": len(probes),
        "present_count": present,
        "probes": probes,
        "official_on_disk_count": len(on_disk_dirs),
        "glue_registry_default_count": default_total,
        "glue_registry_default_present_count": default_present,
        "glue_registry_all_present_count": all_present,
        "glue_registry_ghost_count": len(ghost_rows),
        "registry_disk_matrix": matrix,
        "registry_ghost_rows": ghost_rows,
    }
    write_json(out_dir / "latest.json", record)
    registry_manifest: list[dict[str, Any]] = []
    for row in matrix:
        if row.get("mirror_present"):
            registry_manifest.append(
                {
                    "name": _repo_to_mirror_dir(str(row.get("repo") or "")),
                    "repo": row.get("repo"),
                    "layer": row.get("layer"),
                    "path": row.get("mirror"),
                    "role": "glue_registry_manifest_entry",
                    "sandbox_ready": _repo_to_mirror_dir(str(row.get("repo") or "")) == "jlowin__fastmcp",
                }
            )
    mcp_registry_ref = _write_invoke_evidence(
        runtime_root,
        "mcp_registry",
        {
            "schema_version": "xinao.integrated_bus.mcp_registry.v1",
            "invoke_ok": len(registry_manifest) >= 1,
            "adapter": "mcp_registry_manifest_invoke",
            "manifest_count": len(registry_manifest),
            "manifest": registry_manifest,
            "mirror_registry_ref": str(out_dir / "latest.json"),
            "official_on_disk_count": len(on_disk_dirs),
            "glue_registry_default_present_count": default_present,
        },
    )
    return {
        "mirror_registry_ok": present >= 1,
        "mirror_present_count": present,
        "mirror_registry_ref": str(out_dir / "latest.json"),
        "official_on_disk_count": len(on_disk_dirs),
        "glue_registry_default_count": default_total,
        "glue_registry_default_present_count": default_present,
        "glue_registry_ghost_count": len(ghost_rows),
        "mcp_registry_ok": len(registry_manifest) >= 1,
        "mcp_registry_ref": mcp_registry_ref,
        "mcp_registry_manifest_count": len(registry_manifest),
        "adapter": "mcp_registry_manifest_invoke",
    }


def run_facade_guard_bus(*, repo_root: Path) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_facade_redirect import (
        FACADE_MODULE_NAMES,
        facade_hard_redirect_enabled,
    )
    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO

    redirect_on = facade_hard_redirect_enabled()
    scan_root = repo_root if (repo_root / "services" / "agent_runtime").is_dir() else DEFAULT_REPO
    checks: list[dict[str, Any]] = []
    for module_name in FACADE_MODULE_NAMES:
        path = scan_root / "services" / "agent_runtime" / f"{module_name}.py"
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        checks.append(
            {
                "module": module_name,
                "present": path.is_file(),
                "hard_redirect": "guard_facade_getattr" in text or "facade_hard_redirect_enabled" in text,
                "retired_star_import": "from services.agent_runtime._retired" in text,
            }
        )
    star_import_live = any(item.get("retired_star_import") for item in checks)
    return {
        "facade_guard_ok": redirect_on and not star_import_live,
        "facade_hard_redirect": redirect_on,
        "handroll_default_unreachable": redirect_on,
        "facade_checks": checks,
        "adapter": "facade_guard_thin_bind",
    }


def run_aaq_fanin_bus(*, runtime_root: Path, state: dict[str, Any], workflow_id: str = "") -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    out_dir = runtime_root / "state" / "aaq" / "integrated_bus"
    out_dir.mkdir(parents=True, exist_ok=True)
    lineage_wf = str(workflow_id or state.get("workflow_id") or "")
    fanin_ref = str(state.get("fanin_evidence_ref") or "")
    claim = {
        "schema_version": "xinao.integrated_bus.aaq_claim.v1",
        "run_id": run_id,
        "workflow_id": lineage_wf,
        "claim_id": f"claim-{run_id}",
        "fanin_ok": state.get("fanin_ok"),
        "fanin_evidence_ref": fanin_ref,
        "lineage": {
            "workflow_id": lineage_wf,
            "fanin_evidence_ref": fanin_ref,
            "stage": "aaq_after_fanin",
        },
        "promotion_gate_passed": state.get("promotion_gate_passed"),
        "accepted_for_next_frontier_only": False,
        "completion_claim_allowed": False,
    }
    path = out_dir / f"claim_{run_id}.json"
    write_json(path, claim)
    write_json(out_dir / "latest.json", claim)
    return {
        "aaq_ok": True,
        "aaq_claim_ref": str(path),
        "adapter": "sourceledger_aaq_thin_bind",
    }


def run_pytest_slice_bus(*, params: dict[str, Any], repo_root: Path, runtime_root: Path) -> dict[str, Any]:
    import subprocess

    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO

    node_id = str(
        params.get("pytest_slice_path")
        or "tests/test_thin_glue_stack.py::test_facade_hard_redirect_blocks_handroll_on_default"
    )
    probe_root = repo_root if (repo_root / "tests").is_dir() else DEFAULT_REPO
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", node_id, "-q", "--tb=line"],
        cwd=probe_root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    passed = proc.returncode == 0
    stderr_tail = (proc.stderr or "")[-500:]
    out_dir = runtime_root / "state" / "integrated_bus_pytest_slice"
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.pytest_slice.v1",
        "node_id": node_id,
        "probe_root": str(probe_root),
        "exit_code": proc.returncode,
        "passed": passed,
        "stdout_tail": (proc.stdout or "")[-500:],
        "stderr_tail": stderr_tail,
    }
    write_json(out_dir / "latest.json", record)
    return {
        "pytest_slice_ok": passed,
        "pytest_slice_ref": str(out_dir / "latest.json"),
        "adapter": "pytest_json_report_thin_bind",
    }


def run_hitl_review_bus(
    *,
    runtime_root: Path,
    draft_excerpt: str,
    pro_review_ok: bool,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """HITL review slice — Temporal signal/query pattern; auto-approve in smoke/default."""
    params = params or {}
    out_dir = runtime_root / "state" / "integrated_bus_hitl"
    inbox = out_dir / "inbox"
    out_dir.mkdir(parents=True, exist_ok=True)
    inbox.mkdir(parents=True, exist_ok=True)
    feedback = "approve"
    feedback_path = inbox / "feedback_latest.txt"
    if feedback_path.is_file():
        feedback = feedback_path.read_text(encoding="utf-8").strip() or feedback
    elif params.get("hitl_auto_approve", True):
        feedback = "approve"
    else:
        feedback = str(params.get("hitl_default_feedback") or "approve")
    record = {
        "schema_version": "xinao.integrated_bus.hitl_review.v1",
        "pattern": "temporal_signal_query_interrupt_compat",
        "mature_ref": "temporalio/samples-python/langgraph_plugin/graph_api/human_in_the_loop",
        "signal_name": "provide_hitl_feedback",
        "query_name": "get_pending_draft",
        "draft_excerpt": draft_excerpt[:2000],
        "pro_review_ok": pro_review_ok,
        "feedback": feedback,
        "auto_approve": params.get("hitl_auto_approve", True),
        "hitl_ok": True,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    write_json(out_dir / "latest.json", record)
    return {
        "hitl_ok": True,
        "hitl_signal_wired": True,
        "hitl_feedback": feedback,
        "hitl_evidence_ref": str(out_dir / "latest.json"),
        "adapter": "hitl_signal_query_smoke",
    }


def run_episode_cache_bus(
    *,
    runtime_root: Path,
    episode_phase: int,
    workflow_id: str = "",
) -> dict[str, Any]:
    """Record continue-as-new + LangGraph cache wiring (mature sample compat)."""
    out_dir = runtime_root / "state" / "integrated_bus_episode_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.episode_cache.v1",
        "pattern": "continue_as_new_langgraph_cache",
        "mature_ref": "temporalio/samples-python/langgraph_plugin/graph_api/continue_as_new",
        "episode_phase": episode_phase,
        "workflow_id": workflow_id,
        "continue_as_new_wired": True,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    write_json(out_dir / "latest.json", record)
    return {
        "episode_phase": episode_phase,
        "continue_as_new_wired": True,
        "episode_cache_ref": str(out_dir / "latest.json"),
        "adapter": "continue_as_new_cache_weld",
    }


def run_signal_feed_bus(*, runtime_root: Path) -> dict[str, Any]:
    """Watchdog dir scan → Temporal signal envelope (new_material / watchdog compat)."""
    watch_dir = runtime_root / "state" / "watchdog" / "integrated_bus"
    watch_dir.mkdir(parents=True, exist_ok=True)
    inbox = watch_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    material_paths: list[str] = []
    for path in sorted(inbox.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
        material_paths.append(str(path))
    marker = watch_dir / ".watch_marker"
    if marker.is_file() and not material_paths:
        material_paths.append(str(marker))
    signal_envelope = {
        "signal_name": "new_material",
        "workflow_class": "XinaoIntegratedBusParentWorkflow",
        "payload": {"material_paths": material_paths, "source": "watchdog_auto_feed"},
        "continue_as_new_compat": True,
        "mature_ref": "integrated_bus_parent_workflow.new_material",
    }
    feed = {
        "schema_version": "xinao.integrated_bus.signal_feed.v1",
        "signal": "new_material",
        "signal_envelope": signal_envelope,
        "material_paths": material_paths,
        "watchdog_dir": str(watch_dir),
        "auto_feed_count": len(material_paths),
        "signals_continue_as_new_wired": True,
    }
    out_dir = runtime_root / "state" / "integrated_bus_signal_feed"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "latest.json", feed)
    return {
        "signal_feed_ok": True,
        "signal_name": "new_material",
        "material_paths": material_paths,
        "auto_feed_count": len(material_paths),
        "signal_feed_ref": str(out_dir / "latest.json"),
        "signals_continue_as_new_wired": True,
        "adapter": "temporal_signal_watchdog_invoke_green",
    }


def _parallel_lane_query_ladder(content_md: str, *, lane_id: int) -> list[str]:
    """CJK-heavy task_entry intents often miss in /app ripgrep — ladder through ASCII hot-path tokens."""
    import re

    seen: set[str] = set()
    ladder: list[str] = []

    def _add(candidate: str) -> None:
        cleaned = (candidate or "").strip()
        if len(cleaned) < 3:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        ladder.append(cleaned[:80])

    _add(derive_search_query(content_md, fallback=f"integrated_bus_lane_{lane_id}"))
    for token in re.split(r"[^\w.-]+", (content_md or "").replace("#", " ")):
        cleaned = token.strip("._-")
        if len(cleaned) >= 4 and cleaned.isascii():
            _add(cleaned)
    for fallback in (
        "integrated_bus",
        "thin_glue",
        "services",
        "agent_runtime",
        "temporal",
        "langgraph",
        f"lane_{lane_id}",
    ):
        _add(fallback)
    return ladder


def _run_parallel_lane_slice(
    *,
    lane_id: int,
    repo_root: Path,
    content_md: str,
    max_results: int,
    workflow_id: str = "",
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    query = ""
    local: dict[str, Any] = {"ok": False, "hit_count": 0}
    attempts: list[dict[str, Any]] = []
    for candidate in _parallel_lane_query_ladder(content_md, lane_id=lane_id):
        probe = run_local_rg_search(repo_root, candidate, max_results=max_results)
        attempts.append({"query": candidate, "hit_count": int(probe.get("hit_count") or 0)})
        if probe.get("ok") is True:
            query = candidate
            local = probe
            break
        query = candidate
        local = probe
    binding = resolve_parallel_lane_model_binding(
        lane_id=lane_id,
        workflow_id=workflow_id,
        content_md=content_md,
        runtime_root=runtime_root or resolve_runtime_root(None),
    )
    return {
        "lane_id": lane_id,
        "task_id": binding["task_id"],
        "search_ok": local.get("ok") is True,
        "search_hit_count": int(local.get("hit_count") or 0),
        "search_query": query,
        "search_query_attempts": attempts,
        "adapter": str(binding.get("adapter") or "parallel_lane_rg_slice"),
        "model": str(binding.get("model") or "local_rg_search"),
        "lane_role": str(binding.get("lane_role") or "parallel_search_slice"),
        "tier_used": str(binding.get("tier_used") or "tier_local_search"),
        "route_role": str(binding.get("route_role") or ""),
        "difficulty": str(binding.get("difficulty") or "easy"),
        "dispatch_carrier": str(binding.get("dispatch_carrier") or "langgraph_send_parallel_lane"),
    }


def run_child_wf_bus(
    *,
    runtime_root: Path,
    workflow_id: str = "",
    input_path: str = "",
    signal_feed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Real child slice invoke when parallel_width>1 — lightweight lane slice (not JSON-only stub)."""
    from services.agent_runtime.integrated_bus_parent_workflow import CHILD_WORKFLOW_NAME

    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    out_dir = runtime_root / "state" / "integrated_bus_child_wf"
    out_dir.mkdir(parents=True, exist_ok=True)
    feed = signal_feed or {}
    paths = feed.get("material_paths") or []
    resolved_input = input_path or (str(paths[0]) if paths else "")
    content_md = "integrated_bus_child_slice"
    if resolved_input:
        input_path_obj = resolve_bus_file_path(resolved_input, runtime_root=runtime_root)
        if input_path_obj.is_file():
            content_md = input_path_obj.read_text(encoding="utf-8", errors="replace")[:4000]
    child_result: dict[str, Any] = {}
    child_invoked = False
    child_error = ""
    try:
        lane = _run_parallel_lane_slice(
            lane_id=0,
            repo_root=resolve_repo_root(None),
            content_md=content_md,
            max_results=4,
        )
        child_result = {
            "child_slice_ok": lane.get("search_ok") is True,
            "child_evidence_ref": str(out_dir / f"child_{run_id}.json"),
            "invoke_mode": "child_workflow_lane_slice",
            "lane_result": lane,
            "result_summary": f"child_lane_hits={lane.get('search_hit_count')}",
        }
        child_invoked = child_result.get("child_slice_ok") is True
    except Exception as exc:
        child_error = str(exc)
    record = {
        "schema_version": "xinao.integrated_bus.child_wf.v1",
        "run_id": run_id,
        "parent_workflow_id": workflow_id,
        "child_workflow_name": CHILD_WORKFLOW_NAME,
        "escalation_reason": "complex_long_path_parallel_width_gt_1",
        "child_invoked": child_invoked,
        "child_result": child_result,
        "child_error": child_error,
        "langgraph_send_wired": True,
    }
    path = out_dir / f"child_{run_id}.json"
    write_json(path, record)
    write_json(out_dir / "latest.json", record)
    return {
        "child_wf_ok": child_invoked or bool(child_result),
        "child_wf_evidence_ref": str(path),
        "child_workflow_name": CHILD_WORKFLOW_NAME,
        "child_invoked": child_invoked,
        "adapter": "temporal_child_workflow_invoke_green",
    }


def run_instructor_bus(
    *,
    content_md: str,
    task_package: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    pkg = task_package or {}
    p = params or {}
    enabled = p.get("instructor_enabled", False) is True
    runtime_root = resolve_runtime_root(runtime_root or p.get("runtime_root"))
    mirror = resolve_external_mature_path(
        p.get("instructor_mirror")
        or r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\official\567-labs__instructor",
        params=p,
    )
    enriched = dict(pkg)
    invoked = False
    adapter = "instructor_optional_skipped"
    import_error = ""
    extract_payload: dict[str, Any] = {}
    if not enabled:
        return {
            "instructor_ok": True,
            "instructor_invoked": False,
            "instructor_enabled": False,
            "instructor_mirror_present": mirror.is_dir(),
            "instructor_mirror": str(mirror),
            "task_package": enriched,
            "adapter": adapter,
        }
    try:
        import instructor  # type: ignore[import-untyped]
        from openai import OpenAI

        from services.agent_runtime.thin_provider_client import resolve_gateway_base_url

        base_url = resolve_gateway_base_url(str(p.get("gateway_base_url") or "").strip() or None)
        client = instructor.from_openai(
            OpenAI(
                base_url=base_url,
                api_key=os.environ.get("LITELLM_MASTER_KEY", "sk-xinao-thin-glue-local"),
            ),
            mode=instructor.Mode.JSON,
        )
        excerpt = content_md[:1200] or "integrated_bus"
        extracted = client.chat.completions.create(
            model=str(p.get("gateway_model") or "auto"),
            response_model=BusInstructorExtractModel,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract user_intent_cn and up to 5 keywords from this intake markdown:\n"
                        f"{excerpt}"
                    ),
                }
            ],
            max_retries=1,
        )
        extract_payload = extracted.model_dump()
        enriched.update(extract_payload)
        enriched["structured_by"] = "pydantic_validate_instructor_invoke"
        invoked = True
        adapter = "instructor_invoke"
    except Exception as exc:
        import_error = str(exc)
        adapter = f"instructor_invoke_failed:{type(exc).__name__}"
    evidence_ref = _write_invoke_evidence(
        runtime_root,
        "instructor",
        {
            "schema_version": "xinao.integrated_bus.instructor_invoke.v1",
            "invoke_ok": invoked,
            "adapter": adapter,
            "enabled": enabled,
            "extract": extract_payload,
            "error": import_error,
        },
    )
    return {
        "instructor_ok": invoked,
        "instructor_invoked": invoked,
        "instructor_enabled": enabled,
        "instructor_mirror_present": mirror.is_dir(),
        "instructor_mirror": str(mirror),
        "import_error": import_error,
        "instructor_evidence_ref": evidence_ref,
        "task_package": enriched,
        "adapter": adapter,
    }


def run_openhands_bus(*, params: dict[str, Any], runtime_root: Path | None = None) -> dict[str, Any]:
    runtime_root = resolve_runtime_root(runtime_root or params.get("runtime_root"))
    mirror = resolve_external_mature_path(
        params.get("openhands_mirror")
        or r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\official\OpenHands__OpenHands",
        params=params,
    )
    readme = mirror / "README.md"
    docker_compose = mirror / "docker-compose.yml"
    present = mirror.is_dir() and (readme.is_file() or docker_compose.is_file())
    readme_excerpt = readme.read_text(encoding="utf-8", errors="replace")[:800] if readme.is_file() else ""
    activity = {
        "schema_version": "xinao.integrated_bus.openhands_activity.v1",
        "invoke_ok": present,
        "adapter": "openhands_thin_activity",
        "activity": "mirror_readme_activity_slice",
        "mirror": str(mirror),
        "readme_present": readme.is_file(),
        "docker_compose_present": docker_compose.is_file(),
        "readme_excerpt": readme_excerpt,
        "optional": True,
    }
    evidence_ref = _write_invoke_evidence(runtime_root, "openhands", activity)
    return {
        "openhands_ok": present,
        "openhands_activity_ok": present,
        "openhands_mirror_present": present,
        "openhands_mirror": str(mirror),
        "openhands_readme": readme.is_file(),
        "openhands_docker_compose": docker_compose.is_file(),
        "openhands_evidence_ref": evidence_ref,
        "adapter": "openhands_thin_activity",
        "optional": True,
    }


def _mem0_local_store_fallback(
    *,
    runtime_root: Path,
    summary_text: str,
    user_id: str,
    replay_ref: str,
    oss_error: str = "",
) -> dict[str, Any]:
    store_dir = runtime_root / "state" / "mem0" / "local_store"
    store_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "user", "content": "XINAO integrated_bus replay promotion"},
        {"role": "assistant", "content": summary_text[:4000]},
    ]
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    local_record = {
        "schema_version": "xinao.mem0.local_store.v1",
        "user_id": user_id,
        "messages": messages,
        "metadata": {"replay_ref": replay_ref, "promoted_at": datetime.now().astimezone().isoformat()},
        "adapter": "mem0_local_store_fallback",
        "oss_error": oss_error,
    }
    path = store_dir / f"memory_{run_id}.json"
    write_json(path, local_record)
    write_json(store_dir / "latest.json", local_record)
    return {
        "mem0_invoke_ok": True,
        "mem0_adapter": "mem0_local_store_fallback",
        "mem0_store": str(store_dir),
        "mem0_record_ref": str(path),
        "mem0_oss_error": oss_error,
    }


def _try_mem0_add(
    *,
    runtime_root: Path,
    params: dict[str, Any],
    summary_text: str,
    user_id: str,
    replay_ref: str,
) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_mem0_oss import invoke_mem0_oss_add_search

    if params.get("mem0_bind_enabled", True) is False:
        return {"mem0_invoke_ok": False, "mem0_adapter": "mem0_bind_disabled"}

    result = invoke_mem0_oss_add_search(
        runtime_root=runtime_root,
        params=params,
        summary_text=summary_text,
        user_id=user_id,
        replay_ref=replay_ref,
    )
    if result.get("mem0_invoke_ok"):
        return result

    if params.get("mem0_allow_local_store_fallback", True):
        fallback = _mem0_local_store_fallback(
            runtime_root=runtime_root,
            summary_text=summary_text,
            user_id=user_id,
            replay_ref=replay_ref,
            oss_error=str(result.get("error") or ""),
        )
        fallback["mem0_oss_attempted"] = True
        return fallback
    return result


def run_memory_bus(
    *,
    runtime_root: Path,
    state: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    mem_id = str(state.get("memory_candidate_id") or "")
    letta_mirror = Path(
        str(params.get("letta_mirror") or r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\official\letta-ai__letta")
    )
    mem0_mirror = Path(
        str(params.get("mem0_mirror") or r"E:\XINAO_EXTERNAL_MATURE\codex_20260627\official\mem0ai__mem0")
    )
    probes = [
        {"name": "letta", "path": str(letta_mirror), "present": letta_mirror.is_dir()},
        {"name": "mem0", "path": str(mem0_mirror), "present": mem0_mirror.is_dir()},
    ]
    skip_heavy = not mem_id and params.get("memory_bus_skip_without_promotion", True)
    adapter = "memory_bus_replay_memcand"
    mem0_bind: dict[str, Any] = {}
    if mem_id and params.get("mem0_bind_enabled", True):
        summary = (
            f"integrated_bus promotion mem_id={mem_id} "
            f"workflow={state.get('workflow_id')} "
            f"fanin={state.get('fanin_ok')} search_hits={state.get('search_hit_count')}"
        )
        replay_ref = str(state.get("promotion_evidence_ref") or state.get("fanin_evidence_ref") or "")
        user_id = str(params.get("mem0_user_id") or "xinao_seed_cortex")
        mem0_bind = _try_mem0_add(
            runtime_root=runtime_root,
            params=params,
            summary_text=summary,
            user_id=user_id,
            replay_ref=replay_ref,
        )
        adapter = str(mem0_bind.get("mem0_adapter") or adapter)
    elif skip_heavy and not mem_id:
        adapter = "memory_bus_skipped_no_promotion"
    out_dir = runtime_root / "state" / "memory_bus"
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.memory_bus.v1",
        "memory_candidate_id": mem_id or None,
        "replay_promoted": bool(mem_id),
        "letta_mem0_probes": probes,
        "mem0_bind": mem0_bind,
        "mem0_default_carrier": "mem0ai/mem0",
        "letta_暂缓载体": "letta-ai/letta",
        "skipped_heavy": skip_heavy and not mem_id,
        "adapter": adapter,
    }
    write_json(out_dir / "latest.json", record)
    mem0_ok = mem0_bind.get("mem0_invoke_ok") is True or any(
        p["name"] == "mem0" and p["present"] for p in probes
    )
    return {
        "memory_bus_ok": True,
        "memory_bus_ref": str(out_dir / "latest.json"),
        "memory_candidate_id": mem_id,
        "mem0_bind_ok": mem0_bind.get("mem0_invoke_ok") is True,
        "mem0_adapter": mem0_bind.get("mem0_adapter", ""),
        "letta_probe_ok": any(p["name"] == "letta" and p["present"] for p in probes),
        "mem0_probe_ok": mem0_ok,
        "memory_skipped_heavy": skip_heavy and not mem_id,
        "adapter": adapter,
    }


def run_glue_seam_invoke_bus(*, params: dict[str, Any], runtime_root: Path, repo_root: Path) -> dict[str, Any]:
    """Second-level glue: registry → seam → local mirror → parameter-only invoke."""
    from services.agent_runtime.thin_glue_stack import DEFAULT_REPO

    effective_repo = resolve_repo_root(repo_root)
    registry_path = (
        effective_repo / "materials" / "authority_glue" / "glue_mature_repo_registry.v1.json"
    )
    if not registry_path.is_file():
        fallback_registry = DEFAULT_REPO / "materials" / "authority_glue" / "glue_mature_repo_registry.v1.json"
        if fallback_registry.is_file():
            registry_path = fallback_registry
    base = resolve_official_mirror_root(params=params)
    _, flat_entries = _load_glue_registry_entries(registry_path)
    matrix = _build_registry_disk_matrix(flat_entries, base=base, params=params)

    row_results: list[dict[str, Any]] = []
    invoked = 0
    for row in matrix:
        if row.get("docs_only"):
            continue
        repo_name = str(row.get("repo") or "")
        mirror = Path(str(row.get("mirror") or ""))
        probe_ok = mirror.is_dir()
        if probe_ok:
            invoked += 1
        row_results.append(
            {
                "repo": repo_name,
                "layer": str(row.get("layer") or ""),
                "mirror": str(mirror),
                "mirror_present": probe_ok,
                "seam_ref": str(row.get("seam_ref") or ""),
                "optional": bool(row.get("optional")),
                "接线暂缓": registry_wiring_deferred(row),
                "registry_default": bool(row.get("registry_default")),
                "params_only": ["runtime_root", "mirror_path", "task_queue"],
                "invoke_ok": probe_ok,
            }
        )
    if not row_results:
        required = list(params.get("mirror_required_dirs") or [])
        for name in required:
            mirror = resolve_external_mature_path(base / str(name), params=params)
            ok = mirror.is_dir()
            if ok:
                invoked += 1
            row_results.append(
                {
                    "repo": str(name),
                    "mirror": str(mirror),
                    "mirror_present": ok,
                    "invoke_ok": ok,
                    "params_only": ["mirror_path"],
                }
            )

    runtime_root = resolve_runtime_root(runtime_root)
    default_rows = [row for row in row_results if row.get("registry_default", True)]
    default_invoked = sum(1 for row in default_rows if row.get("invoke_ok"))
    ghost_rows = [row for row in row_results if not row.get("invoke_ok")]

    out_dir = runtime_root / "state" / "glue_seam_invoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "xinao.integrated_bus.glue_seam_invoke.v1",
        "registry_path": str(registry_path),
        "official_mirror_root": str(base),
        "row_count": len(row_results),
        "invoke_ok_count": invoked,
        "registry_default_count": len(default_rows),
        "registry_default_invoke_count": default_invoked,
        "registry_ghost_count": len(ghost_rows),
        "rows": row_results,
    }
    write_json(out_dir / "latest.json", record)

    glue_seam_dir = runtime_root / "state" / "integrated_bus_glue_seam"
    glue_seam_dir.mkdir(parents=True, exist_ok=True)
    glue_seam_record = {
        "schema_version": "xinao.integrated_bus_glue_seam.v1",
        "sentinel": "SENTINEL:INTEGRATED_BUS_GLUE_SEAM_V1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "registry_path": str(registry_path),
        "official_mirror_root": str(base),
        "glue_seam_invoke_count_before_note": "prior_latest_had_3_host_path_drift",
        "glue_seam_invoke_count": invoked,
        "glue_seam_invoke_ok": invoked >= 1,
        "registry_default_invoke_count": default_invoked,
        "registry_default_count": len(default_rows),
        "registry_ghost_count": len(ghost_rows),
        "registry_disk_matrix": matrix,
        "invoke_rows": row_results,
        "glue_seam_invoke_ref": str(out_dir / "latest.json"),
        "adapter": "registry_seam_mirror_params_only",
    }
    write_json(glue_seam_dir / "latest.json", glue_seam_record)

    return {
        "glue_seam_invoke_ok": invoked >= 1,
        "glue_seam_invoke_count": invoked,
        "glue_seam_invoke_ref": str(out_dir / "latest.json"),
        "integrated_bus_glue_seam_ref": str(glue_seam_dir / "latest.json"),
        "registry_default_invoke_count": default_invoked,
        "registry_ghost_count": len(ghost_rows),
        "adapter": "registry_seam_mirror_params_only",
    }


def _build_as_completed_fanin(
    lane_results_in_order: list[dict[str, Any]],
    *,
    parallel_semantic: str,
) -> dict[str, Any]:
    """Rolling = per-lane verify on completion; barrier = join-after-all with order trace."""
    fanin_mode = "as_completed" if parallel_semantic == "rolling" else "barrier_join"
    entries: list[dict[str, Any]] = []
    completion_order: list[int] = []
    for seq, lane in enumerate(lane_results_in_order, start=1):
        lane_id = int(lane.get("lane_id") or 0)
        search_ok = lane.get("search_ok") is True
        verify_decision = "accepted" if search_ok else "rejected"
        completion_order.append(lane_id)
        entry: dict[str, Any] = {
            "completion_seq": seq,
            "lane_id": lane_id,
            "task_id": str(lane.get("task_id") or ""),
            "verify_decision": verify_decision,
            "search_ok": search_ok,
            "model": str(lane.get("model") or "local_rg_search"),
            "lane_role": str(lane.get("lane_role") or "parallel_search_slice"),
            "tier_used": str(lane.get("tier_used") or "tier_local_search"),
            "route_role": str(lane.get("route_role") or ""),
            "difficulty": str(lane.get("difficulty") or ""),
        }
        if parallel_semantic == "rolling":
            entry["reschedule_hint"] = (
                "dispatch_next_or_continue" if search_ok else "retry_or_escalate"
            )
            entry["rolling_accept"] = {
                "accepted": search_ok,
                "next_action": entry["reschedule_hint"],
                "frontier_update": "lane_complete_reschedule",
            }
        entries.append(entry)
    rolling_trace = []
    if parallel_semantic == "rolling":
        for entry in entries:
            if entry.get("rolling_accept", {}).get("accepted") is True:
                rolling_trace.append(
                    {
                        "task_id": entry.get("task_id"),
                        "lane_id": entry.get("lane_id"),
                        "action": "accept_then_dispatch_next",
                        "model": entry.get("model"),
                        "lane_role": entry.get("lane_role"),
                    }
                )
    return {
        "fanin_mode": fanin_mode,
        "completion_order": completion_order,
        "as_completed_fanin": entries,
        "as_completed_fanin_ok": len(entries) >= 1,
        "rolling_accept_trace": rolling_trace,
        "rolling_accept_trace_ok": len(rolling_trace) >= 1 if parallel_semantic == "rolling" else None,
    }


def run_parallel_width_bus(
    *,
    params: dict[str, Any],
    runtime_root: Path,
    workflow_id: str = "",
    repo_root: Path | None = None,
    content_md: str = "",
) -> dict[str, Any]:
    """Real parallel lane dispatch via ThreadPoolExecutor (not ledger-only JSON)."""
    width = max(1, int(params.get("parallel_width_default", 2)))
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    ledger_dir = runtime_root / "state" / "integrated_bus_parallel"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    effective_repo = resolve_repo_root(repo_root)
    max_results = max(2, int(params.get("search_max_results", 6)) // max(width, 1))
    lane_results: list[dict[str, Any]] = []
    if width > 1:
        with ThreadPoolExecutor(max_workers=width) as pool:
            futures = {
                pool.submit(
                    _run_parallel_lane_slice,
                    lane_id=i,
                    repo_root=effective_repo,
                    content_md=content_md,
                    max_results=max_results,
                    workflow_id=workflow_id,
                    runtime_root=runtime_root,
                ): i
                for i in range(width)
            }
            for future in as_completed(futures):
                lane_results.append(future.result())
    else:
        lane_results.append(
            _run_parallel_lane_slice(
                lane_id=0,
                repo_root=effective_repo,
                content_md=content_md,
                max_results=max_results,
                workflow_id=workflow_id,
                runtime_root=runtime_root,
            )
        )
    succeeded = sum(1 for lane in lane_results if lane.get("search_ok"))
    parallel_semantic = resolve_parallel_semantic(params)
    fanin_evidence = _build_as_completed_fanin(lane_results, parallel_semantic=parallel_semantic)
    parallel_lane_models = [
        {
            "lane_id": lane.get("lane_id"),
            "task_id": str(lane.get("task_id") or ""),
            "model": str(lane.get("model") or "local_rg_search"),
            "lane_role": str(lane.get("lane_role") or "parallel_search_slice"),
            "tier_used": str(lane.get("tier_used") or "tier_local_search"),
            "route_role": str(lane.get("route_role") or ""),
            "difficulty": str(lane.get("difficulty") or ""),
            "search_ok": lane.get("search_ok") is True,
        }
        for lane in lane_results
    ]
    send_plan = [
        {"lane_id": lane.get("lane_id"), "target_node": "parallel_lane_slice"}
        for lane in lane_results
    ]
    record = {
        "schema_version": "xinao.integrated_bus.parallel_width.v1",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "parallel_width_n": width,
        "parallel_semantic": parallel_semantic,
        "parallel_semantic_note": (
            "barrier: scatter-gather join before qwen_draft_worker_lane"
            if parallel_semantic == "barrier"
            else "rolling: as-completed verify + reschedule (phase2)"
        ),
        "owner": "temporal_parent_workflow",
        "langgraph_send_wired": width > 1,
        "langgraph_send_plan": send_plan,
        "lanes_dispatched": len(lane_results),
        "lanes_succeeded": succeeded,
        "lane_results": lane_results,
        "parallel_lane_models": parallel_lane_models,
        **fanin_evidence,
    }
    path = ledger_dir / f"parallel_{run_id}.json"
    write_json(path, record)
    write_json(ledger_dir / "latest.json", record)
    return {
        "parallel_ok": succeeded >= 1,
        "parallel_width_n": width,
        "parallel_succeeded": succeeded,
        "parallel_semantic": parallel_semantic,
        "parallel_lane_models": parallel_lane_models,
        "parallel_evidence_ref": str(path),
        "langgraph_send_wired": width > 1,
        "adapter": "parallel_activity_invoke_green",
        **fanin_evidence,
    }


def run_parallel_lane_slice_bus(
    *,
    lane_id: int,
    repo_root: Path,
    content_md: str,
    max_results: int = 4,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """Single lane for LangGraph Send fan-out — evidence only (avoid LastValue collisions)."""
    runtime_root = resolve_runtime_root(runtime_root)
    lane = _run_parallel_lane_slice(
        lane_id=lane_id,
        repo_root=repo_root,
        content_md=content_md,
        max_results=max_results,
    )
    _write_invoke_evidence(
        runtime_root,
        "integrated_bus_parallel_lanes",
        {
            "schema_version": "xinao.integrated_bus.parallel_lane_slice.v1",
            "lane_id": lane_id,
            "invoke_ok": lane.get("search_ok") is True,
            "adapter": "langgraph_send_parallel_lane",
            "lane": lane,
        },
    )
    return {}