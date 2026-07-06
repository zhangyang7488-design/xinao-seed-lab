from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from services.agent_runtime import dp_sidecar_execution_port
from services.agent_runtime import modular_dynamic_worker_pool_phase1 as phase1


SCHEMA_VERSION = "xinao.codex_s.light_research_loop.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_LIGHT_RESEARCH_LOOP"
TASK_ID = "codex_s_light_research_loop_20260706"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = phase1.DEFAULT_REPO
STATE_NAME = "codex_s_light_research_loop"
MODE_CHOICES = ("local_only", "external_light", "architecture_audit")
WORKER_POLICY_CHOICES = ("auto", "local_only", "cloud_allowed", "skip")

RgRunner = Callable[[Path, list[str], str, int], list[dict[str, Any]]]
LocalInvoker = Callable[..., dict[str, Any]]
QwenInvoker = Callable[..., dict[str, Any]]
DpInvoker = Callable[..., dict[str, Any]]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    return cleaned[:120] or "light-research-loop"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def output_paths(runtime: Path, wave_id: str) -> dict[str, Path]:
    wave_stem = safe_stem(wave_id)
    state = runtime / "state" / STATE_NAME
    return {
        "state": state,
        "latest": state / "latest.json",
        "wave": state / "waves" / f"{wave_stem}.json",
        "source_ledger_latest": state / "source_ledger" / "latest.json",
        "source_ledger_wave": state / "source_ledger" / "waves" / f"{wave_stem}.json",
        "claim_cards_latest": state / "claim_cards" / "latest.json",
        "claim_cards_wave": state / "claim_cards" / "waves" / f"{wave_stem}.json",
        "fan_in_latest": state / "fan_in" / "latest.json",
        "fan_in_wave": state / "fan_in" / "waves" / f"{wave_stem}.json",
        "readback": runtime / "readback" / "zh" / f"{STATE_NAME}.md",
        "manifest": runtime / "capabilities" / "codex_s.light_research_loop" / "manifest.json",
        "invoke_evidence": (
            runtime
            / "capabilities"
            / "codex_s.light_research_loop"
            / "invoke_evidence"
            / "latest.json"
        ),
    }


def default_local_roots(repo: Path) -> list[str]:
    return [
        "AGENTS.md",
        "CODEX_S_L0.md",
        "services",
        "scripts",
        "src",
        "tests",
        "docs",
        "contracts",
    ]


def run_rg_scan(repo: Path, roots: list[str], query: str, max_results: int) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    scan_roots = roots or default_local_roots(repo)
    cmd = ["rg", "-n", "--no-heading", "--color", "never", "-S", "--", query, *scan_roots]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback_local_scan(repo, scan_roots, query, max_results)
    if completed.returncode not in {0, 1}:
        return fallback_local_scan(repo, scan_roots, query, max_results)
    results: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        if len(results) >= max_results:
            break
        match = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not match:
            continue
        path_text, line_no, snippet = match.groups()
        results.append(
            {
                "path": str((repo / path_text).resolve()),
                "repo_relative_path": path_text,
                "line": int(line_no),
                "snippet": snippet.strip()[:700],
                "query": query,
            }
        )
    return results


def fallback_local_scan(repo: Path, roots: list[str], query: str, max_results: int) -> list[dict[str, Any]]:
    query_lower = query.lower()
    results: list[dict[str, Any]] = []
    for root_text in roots:
        root = repo / root_text
        files = [root] if root.is_file() else list(root.rglob("*")) if root.is_dir() else []
        for path in files:
            if len(results) >= max_results:
                return results
            if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".exe"}:
                continue
            text = read_text(path)
            if not text:
                continue
            for index, line in enumerate(text.splitlines(), start=1):
                if query_lower in line.lower():
                    results.append(
                        {
                            "path": str(path.resolve()),
                            "repo_relative_path": str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path),
                            "line": index,
                            "snippet": line.strip()[:700],
                            "query": query,
                        }
                    )
                    break
    return results


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"https?://[^\s)）]+", text):
        url = match.group(0).rstrip("，,。.;；")
        if url not in urls:
            urls.append(url)
    return urls


def source_family_for_url(url: str) -> str:
    lowered = url.lower()
    if "github.com" in lowered or "gitlab" in lowered:
        return "external_open_source_project"
    if "docs." in lowered or "/docs" in lowered:
        return "external_official_docs"
    if "arxiv" in lowered or "aclanthology" in lowered:
        return "external_research_paper"
    if "litellm" in lowered or "openrouter" in lowered or "semantic-router" in lowered or "routellm" in lowered:
        return "external_mature_model_routing"
    return "external_mature_source"


def build_local_entries(scan_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for index, item in enumerate(scan_results, start=1):
        path = str(item.get("path") or "")
        line_no = int(item.get("line") or 0)
        entries.append(
            {
                "entry_id": f"local-scan-{index:02d}",
                "source_url": f"file:{path}:{line_no}",
                "source_family": "local_repo_search",
                "claim": str(item.get("snippet") or "")[:700],
                "verification_need": "Codex fan-in must inspect the source ref before treating the hit as design evidence.",
                "accepted_for": "light_research_loop_local_scan",
                "repo_relative_path": str(item.get("repo_relative_path") or ""),
                "line": line_no,
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    return entries


def build_external_entries(
    *,
    source_urls: list[str],
    source_packages: list[Path],
    external_note: str,
    max_results: int,
) -> list[dict[str, Any]]:
    urls = list(dict.fromkeys(url for url in source_urls if url.strip()))
    package_refs: list[dict[str, Any]] = []
    for package in source_packages:
        text = read_text(package)
        for url in extract_urls(text):
            if url not in urls:
                urls.append(url)
        if package.is_file():
            package_refs.append(
                {
                    "path": str(package),
                    "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
                    "char_count": len(text),
                }
            )
    entries: list[dict[str, Any]] = []
    for index, url in enumerate(urls[:max_results], start=1):
        entries.append(
            {
                "entry_id": f"external-source-{index:02d}",
                "source_url": url,
                "source_family": source_family_for_url(url),
                "claim": external_note.strip()
                or "External mature source candidate for light research comparison.",
                "verification_need": "Open/read source or citation verifier before promoting this candidate beyond ClaimCard.",
                "accepted_for": "light_research_loop_external_sourceledger",
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    if not entries and package_refs:
        for index, ref in enumerate(package_refs[:max_results], start=1):
            entries.append(
                {
                    "entry_id": f"external-package-{index:02d}",
                    "source_url": f"file:{ref['path']}",
                    "source_family": "external_source_package",
                    "claim": external_note.strip()
                    or "External source package supplied as retrieval evidence.",
                    "verification_need": "Extract concrete URLs or source spans before promotion.",
                    "accepted_for": "light_research_loop_external_source_package",
                    "package_sha256": ref["sha256"],
                    "direct_fact_promotion_allowed": False,
                    "completion_claim_allowed": False,
                }
            )
    return entries


def build_source_ledger(
    *,
    task_id: str,
    wave_id: str,
    entries: list[dict[str, Any]],
    paths: dict[str, Path],
) -> dict[str, Any]:
    payload = {
        "schema_version": "xinao.seedcortex.source_ledger.v1",
        "status": "source_ledger_ready" if entries else "source_ledger_empty",
        "task_id": task_id,
        "wave_id": wave_id,
        "entry_count": len(entries),
        "entries": [{**entry, "ledger_ref": str(paths["source_ledger_wave"])} for entry in entries],
        "entry_ids": [str(entry.get("entry_id") or "") for entry in entries],
        "global_ledger": False,
        "private_ledger": False,
        "light_research_loop_scoped": True,
        "direct_fact_promotion_allowed": False,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "output_paths": {
            "latest": str(paths["source_ledger_latest"]),
            "wave": str(paths["source_ledger_wave"]),
        },
        "validation": {
            "passed": bool(entries),
            "checks": {
                "entries_present": bool(entries),
                "direct_fact_promotion_denied": True,
                "completion_claim_denied": True,
            },
        },
        "generated_at": now_iso(),
    }
    return payload


def build_claim_cards(entries: list[dict[str, Any]], *, artifact_ref: str) -> dict[str, Any]:
    cards = []
    for index, entry in enumerate(entries, start=1):
        cards.append(
            {
                "candidate_id": f"light-research-claim-{index:02d}",
                "object_type": "ClaimCard",
                "artifact_kind": "ClaimCard",
                "artifact_ref": artifact_ref,
                "source_url": str(entry.get("source_url") or ""),
                "source_family": str(entry.get("source_family") or ""),
                "claim": str(entry.get("claim") or ""),
                "verification_need": str(entry.get("verification_need") or ""),
                "accepted_for": str(entry.get("accepted_for") or "light_research_loop_fan_in"),
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.claim_cards.v1",
        "status": "claim_cards_ready" if cards else "claim_cards_empty",
        "claim_card_count": len(cards),
        "claim_cards": cards,
        "source_families": sorted({str(card.get("source_family") or "") for card in cards}),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def _provider_payload(runner: dict[str, Any]) -> dict[str, Any]:
    payload = runner.get("provider_payload")
    return payload if isinstance(payload, dict) else {}


def _lane_record(lane_id: str, provider_id: str, runner: dict[str, Any]) -> dict[str, Any]:
    payload = _provider_payload(runner)
    return {
        "lane_id": lane_id,
        "provider_id": provider_id,
        "actual_provider_id": provider_id,
        "actual_carrier_provider_id": str(
            payload.get("selected_carrier_provider_id")
            or payload.get("carrier_provider_id")
            or provider_id
        ),
        "selected_model": str(payload.get("selected_model") or ""),
        "mode": str(payload.get("mode") or ""),
        "status": str(payload.get("mode_invocation_status") or ""),
        "provider_invocation_performed": payload.get("provider_invocation_performed") is True,
        "model_invocation_performed": payload.get("model_invocation_performed") is True,
        "tool_invocation_performed": payload.get("tool_invocation_performed") is True,
        "named_blocker": str(payload.get("named_blocker") or ""),
        "result_path": str(payload.get("result_path") or ""),
        "provider_invocation_ref": str(payload.get("provider_invocation_ref") or ""),
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


def invoke_worker_lanes(
    *,
    runtime: Path,
    wave_id: str,
    mode: str,
    objective: str,
    worker_input: str,
    worker_policy: str,
    write: bool,
    local_invoker: LocalInvoker,
    qwen_invoker: QwenInvoker,
    dp_invoker: DpInvoker,
) -> list[dict[str, Any]]:
    if worker_policy == "skip":
        return []
    wave_stem = safe_stem(wave_id)
    records: list[dict[str, Any]] = []
    local_runner = local_invoker(
        runtime_root=runtime,
        task_id=TASK_ID,
        request_id=f"{wave_stem}-local-claimcard-request",
        invocation_id=f"{wave_stem}-local-qwen3-claimcard",
        episode_id=f"{TASK_ID}:{wave_stem}",
        mode="extraction",
        objective=f"{objective} | compress SourceLedger into ClaimCards",
        input_text=worker_input,
        selected_model="qwen3:8b",
        selected_pool_provider_id="local_ollama_qwen3",
        write=write,
    )
    records.append(_lane_record("local-qwen3-claimcard", "local_ollama_qwen3", local_runner))

    local_ok = _provider_payload(local_runner).get("model_invocation_performed") is True
    cloud_allowed = worker_policy == "cloud_allowed" or (
        worker_policy == "auto" and not local_ok
    )
    if cloud_allowed and mode in {"external_light", "architecture_audit", "local_only"}:
        qwen_runner = qwen_invoker(
            runtime_root=runtime,
            task_id=TASK_ID,
            request_id=f"{wave_stem}-qwen-claimcard-request",
            invocation_id=f"{wave_stem}-qwen-claimcard",
            episode_id=f"{TASK_ID}:{wave_stem}",
            mode="extraction",
            objective=f"{objective} | Qwen fallback SourceLedger compression",
            input_text=worker_input,
            write=write,
        )
        records.append(_lane_record("qwen-claimcard", "qwen_prepaid_cheap_worker", qwen_runner))

    if mode == "external_light":
        dp_search = dp_invoker(
            runtime_root=runtime,
            task_id=TASK_ID,
            request_id=f"{wave_stem}-dp-search-request",
            invocation_id=f"{wave_stem}-dp-search",
            episode_id=f"{TASK_ID}:{wave_stem}",
            mode="search",
            objective=f"{objective} | local SourceLedger retrieval check",
            input_text=worker_input,
            write=write,
        )
        records.append(_lane_record("dp-search", "seed_cortex.local_source_ledger_search", dp_search))

    if mode == "architecture_audit":
        local_audit = local_invoker(
            runtime_root=runtime,
            task_id=TASK_ID,
            request_id=f"{wave_stem}-local-r1-audit-request",
            invocation_id=f"{wave_stem}-local-deepseek-r1-audit",
            episode_id=f"{TASK_ID}:{wave_stem}",
            mode="audit",
            objective=f"{objective} | local contradiction / architecture audit",
            input_text=worker_input,
            selected_model="deepseek-r1:8b",
            selected_pool_provider_id="local_ollama_deepseek_r1",
            write=write,
        )
        records.append(_lane_record("local-deepseek-r1-audit", "local_ollama_deepseek_r1", local_audit))
        local_audit_ok = _provider_payload(local_audit).get("model_invocation_performed") is True
        if worker_policy == "cloud_allowed" or (worker_policy == "auto" and not local_audit_ok):
            dp_audit = dp_invoker(
                runtime_root=runtime,
                task_id=TASK_ID,
                request_id=f"{wave_stem}-dp-audit-request",
                invocation_id=f"{wave_stem}-dp-audit",
                episode_id=f"{TASK_ID}:{wave_stem}",
                mode="audit",
                objective=f"{objective} | DP architecture audit",
                input_text=worker_input,
                write=write,
            )
            records.append(_lane_record("dp-audit", "legacy.deepseek_dp_sidecar", dp_audit))
    return records


def build_manifest(paths: dict[str, Path], validation_passed: bool) -> dict[str, Any]:
    return {
        "schema_version": "xinao.capability_manifest.v1",
        "capability_id": "codex_s.light_research_loop",
        "provider_id": "codex_s.light_research_loop",
        "capability_kinds": [
            "light_research_loop",
            "local_repo_search",
            "external_sourceledger",
            "qwen_local_dp_claimcard_fanin",
        ],
        "status": "ready" if validation_passed else "blocked",
        "entrypoint": "python -m xinao_seedlab.cli.__main__ light-research-loop",
        "powershell_entrypoint": "scripts/hardmode/Invoke-CodexSLightResearchLoop.ps1",
        "runtime_latest": str(paths["latest"]),
        "invoke_evidence": str(paths["invoke_evidence"]),
        "not_333_mainline": True,
        "not_execution_controller": True,
        "completion_claim_allowed": False,
    }


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    mode: str = "local_only",
    wave_id: str = "",
    objective: str = "",
    local_query: str = "",
    local_roots: list[str] | None = None,
    source_urls: list[str] | None = None,
    source_packages: list[str | Path] | None = None,
    external_note: str = "",
    max_results: int = 12,
    worker_policy: str = "auto",
    write: bool = True,
    rg_runner: RgRunner | None = None,
    local_invoker: LocalInvoker | None = None,
    qwen_invoker: QwenInvoker | None = None,
    dp_invoker: DpInvoker | None = None,
) -> dict[str, Any]:
    if mode not in MODE_CHOICES:
        raise ValueError(f"Unsupported light research mode: {mode}")
    if worker_policy not in WORKER_POLICY_CHOICES:
        raise ValueError(f"Unsupported worker policy: {worker_policy}")
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    resolved_wave_id = wave_id or f"light-research-loop-{safe_stem(now_iso())}"
    paths = output_paths(runtime, resolved_wave_id)
    package_paths = [Path(item) for item in source_packages or [] if str(item).strip()]
    scan_results = (rg_runner or run_rg_scan)(
        repo,
        local_roots or default_local_roots(repo),
        local_query,
        max_results,
    )
    local_entries = build_local_entries(scan_results)
    external_entries = build_external_entries(
        source_urls=source_urls or [],
        source_packages=package_paths,
        external_note=external_note,
        max_results=max_results,
    )
    entries = [*local_entries, *external_entries]
    source_ledger = build_source_ledger(
        task_id=TASK_ID,
        wave_id=resolved_wave_id,
        entries=entries,
        paths=paths,
    )
    claim_cards = build_claim_cards(entries, artifact_ref=str(paths["source_ledger_wave"]))
    worker_input = json.dumps(
        {
            "objective": objective,
            "mode": mode,
            "source_ledger_ref": str(paths["source_ledger_wave"]),
            "entries": source_ledger.get("entries", [])[:max_results],
            "required_output": "compact ClaimCard/audit staging only; no completion claim",
        },
        ensure_ascii=False,
        indent=2,
    )
    worker_lanes = invoke_worker_lanes(
        runtime=runtime,
        wave_id=resolved_wave_id,
        mode=mode,
        objective=objective,
        worker_input=worker_input,
        worker_policy=worker_policy,
        write=write,
        local_invoker=local_invoker or phase1.invoke_local_ollama_qwen_lane,
        qwen_invoker=qwen_invoker or phase1.invoke_qwen_cheap_worker_lane,
        dp_invoker=dp_invoker or dp_sidecar_execution_port.invoke_dp_sidecar_execution_port,
    )
    from xinao_seedlab.application.seed_cortex import build_default_service

    service = build_default_service(runtime, repo_root=repo)
    aaq_payload = service.artifact_acceptance_queue(
        f"light-research-loop-{safe_stem(resolved_wave_id)}",
        claim_cards.get("claim_cards", []),
        write_runtime=write,
    )
    fan_in = {
        "schema_version": f"{SCHEMA_VERSION}.fan_in.v1",
        "status": "light_research_fan_in_ready" if claim_cards.get("claim_card_count") else "light_research_fan_in_empty",
        "wave_id": resolved_wave_id,
        "source_ledger_ref": str(paths["source_ledger_wave"]),
        "claim_cards_ref": str(paths["claim_cards_wave"]),
        "artifact_acceptance_queue_ref": str(aaq_payload.get("output_paths", {}).get("runtime_latest") or ""),
        "worker_lanes": worker_lanes,
        "actual_provider_ids": [lane["actual_provider_id"] for lane in worker_lanes],
        "codex_role": "fan_in_acceptance_only",
        "not_333_mainline": True,
        "not_execution_controller": True,
        "completion_claim_allowed": False,
        "generated_at": now_iso(),
    }
    external_required = mode in {"external_light", "architecture_audit"}
    checks = {
        "local_scan_performed_or_not_requested": bool(local_query.strip()) == bool(local_entries) or not local_query.strip(),
        "external_sources_bound_when_required": bool(external_entries) if external_required else True,
        "source_ledger_written": bool(entries),
        "claim_cards_ready": claim_cards.get("claim_card_count", 0) > 0,
        "worker_invoked_or_explicitly_skipped": worker_policy == "skip"
        or any(lane.get("provider_invocation_performed") for lane in worker_lanes),
        "actual_provider_ids_recorded": worker_policy == "skip" or bool(fan_in["actual_provider_ids"]),
        "aaq_claimcard_gate_invoked": aaq_payload.get("claim_card_requires_source_ledger") is True,
        "not_333_mainline": True,
        "completion_claim_denied": True,
    }
    validation_passed = all(checks.values())
    manifest = build_manifest(paths, validation_passed)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "status": "light_research_loop_ready" if validation_passed else "light_research_loop_blocked",
        "mode": mode,
        "wave_id": resolved_wave_id,
        "objective": objective,
        "runtime_root": str(runtime),
        "repo_root": str(repo),
        "local_query": local_query,
        "local_roots": local_roots or default_local_roots(repo),
        "source_urls": source_urls or [],
        "source_packages": [str(path) for path in package_paths],
        "worker_policy": worker_policy,
        "source_ledger": source_ledger,
        "claim_cards": claim_cards,
        "worker_lanes": worker_lanes,
        "fan_in": fan_in,
        "artifact_acceptance_queue": aaq_payload,
        "capability_manifest": manifest,
        "not_333_mainline": True,
        "not_mainline_reason": "Foreground light research loop; no Temporal workflow_id/run_id/event history.",
        "not_execution_controller": True,
        "not_completion_boundary": True,
        "not_user_completion": True,
        "completion_claim_allowed": False,
        "direct_fact_promotion_allowed": False,
        "output_paths": {key: str(path) for key, path in paths.items()},
        "validation": {"passed": validation_passed, "checks": checks},
        "generated_at": now_iso(),
    }
    if write:
        write_json(paths["source_ledger_latest"], source_ledger)
        write_json(paths["source_ledger_wave"], source_ledger)
        write_json(paths["claim_cards_latest"], claim_cards)
        write_json(paths["claim_cards_wave"], claim_cards)
        write_json(paths["fan_in_latest"], fan_in)
        write_json(paths["fan_in_wave"], fan_in)
        write_json(paths["manifest"], manifest)
        write_json(paths["invoke_evidence"], payload)
        write_json(paths["latest"], payload)
        write_json(paths["wave"], payload)
        write_text(paths["readback"], render_readback(payload))
    return payload


def render_readback(payload: dict[str, Any]) -> str:
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    fan_in = payload.get("fan_in") if isinstance(payload.get("fan_in"), dict) else {}
    providers = fan_in.get("actual_provider_ids") if isinstance(fan_in.get("actual_provider_ids"), list) else []
    return "\n".join(
        [
            "# Codex S light research loop",
            "",
            SENTINEL,
            "",
            f"- status: `{payload.get('status')}`",
            f"- mode: `{payload.get('mode')}`",
            f"- validation_passed: `{validation.get('passed')}`",
            f"- source_ledger_entries: `{payload.get('source_ledger', {}).get('entry_count', 0)}`",
            f"- claim_cards: `{payload.get('claim_cards', {}).get('claim_card_count', 0)}`",
            f"- actual_provider_ids: `{', '.join(providers)}`",
            "- boundary: foreground light loop, not 333 mainline, not completion boundary.",
            "",
            "现在能 invoke 什么：",
            "- `python -m xinao_seedlab.cli.__main__ light-research-loop --mode architecture_audit --local-query \"<rg query>\" --source-url \"<url>\"`",
            "- `scripts\\hardmode\\Invoke-CodexSLightResearchLoop.ps1 -Mode external_light -LocalQuery \"<rg query>\" -SourceUrl \"<url>\"`",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-s-light-research-loop")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--mode", choices=list(MODE_CHOICES), default="local_only")
    parser.add_argument("--wave-id", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument("--local-query", default="")
    parser.add_argument("--local-root", action="append", default=[])
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--source-package", action="append", default=[])
    parser.add_argument("--external-note", default="")
    parser.add_argument("--max-results", type=int, default=12)
    parser.add_argument("--worker-policy", choices=list(WORKER_POLICY_CHOICES), default="auto")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        mode=args.mode,
        wave_id=args.wave_id,
        objective=args.objective,
        local_query=args.local_query,
        local_roots=args.local_root,
        source_urls=args.source_url,
        source_packages=args.source_package,
        external_note=args.external_note,
        max_results=args.max_results,
        worker_policy=args.worker_policy,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
