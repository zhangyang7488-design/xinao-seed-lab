from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.mature_capability_first.v1"
SENTINEL = "SENTINEL:XINAO_MATURE_CAPABILITY_FIRST_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
ROUTE_PROFILE = "seed_cortex_phase0"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_DESKTOP_SPEC = Path(r"C:\Users\xx363\Desktop\新建 文本文档 (3).txt")

GENERIC_CAPABILITY_CATALOG: dict[str, dict[str, Any]] = {
    "provider_registry": {
        "triggers": {"cheap_draft", "provider", "model_gateway", "model_route"},
        "mature_candidates": [
            {"name": "litellm.Router", "import": "litellm", "role": "provider routing, fallback, retry"},
            {"name": "openai.OpenAI compatible client", "import": "openai", "role": "provider client adapter"},
        ],
        "golden_path": "Use a mature router/client as the mechanism; local code may map provider ids and write evidence.",
    },
    "independent_eval": {
        "triggers": {"eval", "audit", "quality_gate", "pre_pass"},
        "mature_candidates": [
            {"name": "pydantic_evals", "import": "pydantic_evals", "role": "structured independent eval"},
            {"name": "OpenAI/Anthropic eval pattern", "import": "", "role": "external eval practice reference"},
        ],
        "golden_path": "Use an independent eval runner for scoring; local validation is evidence only.",
    },
    "checkpoint_interrupt": {
        "triggers": {"durable_temporal", "checkpoint", "interrupt", "workflow", "queue"},
        "mature_candidates": [
            {"name": "temporalio", "import": "temporalio", "role": "durable workflow and signal/query"},
            {"name": "langgraph.checkpoint.sqlite", "import": "langgraph.checkpoint.sqlite", "role": "checkpoint/store"},
        ],
        "golden_path": "Use workflow/checkpoint primitives for state and interrupt; local JSON is evidence, not scheduling truth.",
    },
    "observability_trace": {
        "triggers": {"trace", "telemetry", "usage", "spend", "ledger"},
        "mature_candidates": [
            {"name": "opentelemetry", "import": "opentelemetry", "role": "trace and telemetry"},
            {"name": "langsmith", "import": "langsmith", "role": "LLM trace and run inspection"},
            {"name": "mlflow", "import": "mlflow", "role": "experiment/eval tracking"},
        ],
        "golden_path": "Use mature tracing for runtime facts; local ledger may persist redacted refs.",
    },
    "policy_guardrail": {
        "triggers": {"policy", "guardrail", "fitness", "adr", "build_vs_buy"},
        "mature_candidates": [
            {"name": "OPA/Rego or Conftest", "import": "", "role": "policy-as-code reference"},
        ],
        "golden_path": "Use policy-as-code or a checked decision record for exceptions; local prose cannot promote handroll.",
    },
}

LANE_CLASS_TO_GENERIC = {
    "cheap_draft": "provider_registry",
    "extraction": "provider_registry",
    "eval": "independent_eval",
    "contradiction": "independent_eval",
    "audit": "independent_eval",
    "search_source": "provider_registry",
    "durable_temporal": "checkpoint_interrupt",
    "ci_verify": "policy_guardrail",
    "repo_exec": "policy_guardrail",
    "merge_accept": "policy_guardrail",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_stem(value: str, *, limit: int = 96) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-_.")
    cleaned = cleaned or "default"
    if len(cleaned) <= limit:
        return cleaned
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{cleaned[: limit - 13].strip('-_.') or 'default'}-{digest}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def read_text(path: Path, *, max_chars: int = 12000) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    return text[:max_chars]


def import_available(module_name: str) -> bool:
    if not module_name:
        return False
    return importlib.util.find_spec(module_name) is not None


def output_paths(runtime_root: Path, *, task_id: str, wave_id: str) -> dict[str, str]:
    root = runtime_root / "state" / "mature_capability_first"
    task_root = root / "tasks" / safe_stem(task_id)
    return {
        "latest": str(root / "latest.json"),
        "task_wave": str(task_root / f"{safe_stem(wave_id)}.json"),
        "fitness_latest": str(root / "fitness_latest.json"),
        "readback_zh": str(runtime_root / "readback" / "zh" / f"mature_capability_first_{safe_stem(wave_id)}.md"),
    }


def adr_exception_refs(repo_root: Path, mechanism_id: str) -> list[str]:
    candidates: list[str] = []
    for rel in ("decisions", "docs/adr", "docs/decisions", "architecture/decisions"):
        root = repo_root / rel
        if not root.is_dir():
            continue
        for path in root.glob("**/*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
                continue
            name = path.name.lower()
            if mechanism_id.replace("_", "-") in name or mechanism_id in name:
                candidates.append(str(path))
                continue
            text = read_text(path, max_chars=4000).lower()
            if mechanism_id.replace("_", " ") in text or "maturecapabilityfirst" in text:
                candidates.append(str(path))
    return sorted(set(candidates))


def detect_generic_mechanisms(
    *,
    lane_allocations: list[dict[str, Any]] | None = None,
    task_text: str = "",
    extra_mechanisms: list[str] | None = None,
) -> list[str]:
    mechanisms: set[str] = set(extra_mechanisms or [])
    for lane in lane_allocations or []:
        if not isinstance(lane, dict):
            continue
        lane_class = str(lane.get("lane_class") or "")
        mechanism = LANE_CLASS_TO_GENERIC.get(lane_class)
        if mechanism:
            mechanisms.add(mechanism)
    lowered = task_text.lower()
    for mechanism_id, spec in GENERIC_CAPABILITY_CATALOG.items():
        triggers = {str(item).lower() for item in spec.get("triggers", set())}
        if any(trigger and trigger in lowered for trigger in triggers):
            mechanisms.add(mechanism_id)
    if not mechanisms:
        mechanisms.add("policy_guardrail")
    return sorted(mechanism for mechanism in mechanisms if mechanism in GENERIC_CAPABILITY_CATALOG)


def classify_mechanism(
    *,
    repo_root: Path,
    mechanism_id: str,
) -> dict[str, Any]:
    spec = GENERIC_CAPABILITY_CATALOG[mechanism_id]
    candidates = []
    for candidate in spec.get("mature_candidates", []):
        module_name = str(candidate.get("import") or "")
        available = import_available(module_name) if module_name else False
        reference_only = not module_name
        candidates.append(
            {
                "name": candidate.get("name", ""),
                "import": module_name,
                "role": candidate.get("role", ""),
                "available": available,
                "reference_only": reference_only,
            }
        )
    available_count = sum(1 for item in candidates if item.get("available") is True)
    exception_refs = adr_exception_refs(repo_root, mechanism_id)
    return {
        "mechanism_id": mechanism_id,
        "mechanism_is_generic": True,
        "build_vs_buy_gate": "buy_or_reuse_by_default",
        "mature_candidates": candidates,
        "mature_candidate_available": available_count > 0,
        "mature_candidate_available_count": available_count,
        "golden_path": spec.get("golden_path", ""),
        "local_impl_allowed_roles": ["thin_adapter", "policy_binding", "evidence", "fallback"],
        "local_impl_promoted_to_default_allowed": False,
        "adr_exception_refs": exception_refs,
        "adr_exception_present": bool(exception_refs),
        "decision": "use_mature_thin_adapter"
        if available_count > 0
        else ("adr_exception_review_required" if exception_refs else "repair_or_install_mature_candidate"),
    }


def build_validation(payload: dict[str, Any]) -> dict[str, Any]:
    mechanisms = payload.get("mechanisms") if isinstance(payload.get("mechanisms"), list) else []
    checks = {
        "generic_mechanisms_detected": bool(mechanisms),
        "mature_candidates_checked": all(
            isinstance(item, dict) and bool(item.get("mature_candidates")) for item in mechanisms
        ),
        "local_impl_roles_bounded": all(
            item.get("local_impl_promoted_to_default_allowed") is False
            and "thin_adapter" in item.get("local_impl_allowed_roles", [])
            for item in mechanisms
            if isinstance(item, dict)
        ),
        "handroll_requires_adr_or_repair": all(
            item.get("mature_candidate_available") is True
            or item.get("adr_exception_present") is True
            or item.get("decision") == "repair_or_install_mature_candidate"
            for item in mechanisms
            if isinstance(item, dict)
        ),
        "policy_as_code_surface_present": payload.get("policy_as_code_gate", {}).get("enabled") is True,
        "fitness_functions_present": bool(payload.get("fitness_functions")),
        "completion_claim_disallowed": payload.get("completion_claim_allowed") is False,
        "not_execution_controller": payload.get("not_execution_controller") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "validated_at": now_iso()}


def render_readback(payload: dict[str, Any]) -> str:
    mechanisms = payload.get("mechanisms") if isinstance(payload.get("mechanisms"), list) else []
    lines = [
        "# MatureCapabilityFirst readback",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- task_id: `{payload.get('task_id')}`",
        f"- wave_id: `{payload.get('wave_id')}`",
        f"- mechanism_count: {len(mechanisms)}",
        f"- validation_passed: {payload.get('validation', {}).get('passed') if isinstance(payload.get('validation'), dict) else ''}",
        "",
        "人话：通用机制先找成熟外部/库/平台能力；本地只能做薄 adapter、policy binding、证据和 fallback。",
        "如果要把本地手搓机制升成默认主路，必须有 ADR 例外和复审证据。",
        "",
    ]
    for item in mechanisms:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('mechanism_id')}: decision=`{item.get('decision')}`, mature_available={item.get('mature_candidate_available')}, adr_exception={item.get('adr_exception_present')}"
        )
    lines.append("")
    return "\n".join(lines)


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    task_id: str = "mature_capability_first_20260705",
    wave_id: str = "mature-capability-first-wave-001",
    task_text: str = "",
    lane_allocations: list[dict[str, Any]] | None = None,
    extra_mechanisms: list[str] | None = None,
    invoked_by: str = "",
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    if not task_text:
        task_text = read_text(DEFAULT_DESKTOP_SPEC)
    output = output_paths(runtime, task_id=task_id, wave_id=wave_id)
    mechanism_ids = detect_generic_mechanisms(
        lane_allocations=lane_allocations,
        task_text=task_text,
        extra_mechanisms=extra_mechanisms,
    )
    mechanisms = [classify_mechanism(repo_root=repo, mechanism_id=mechanism_id) for mechanism_id in mechanism_ids]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": WORK_ID,
        "route_profile": ROUTE_PROFILE,
        "task_id": task_id,
        "wave_id": wave_id,
        "status": "mature_capability_first_ready",
        "generated_at": now_iso(),
        "invoked_by": invoked_by,
        "desktop_spec_ref": str(DEFAULT_DESKTOP_SPEC),
        "policy_model": "build_vs_buy_gate + adr_exception + policy_as_code + golden_path + fitness_function",
        "mechanisms": mechanisms,
        "mechanism_count": len(mechanisms),
        "policy_as_code_gate": {
            "enabled": True,
            "rule": "generic mechanism local handroll cannot be promoted to default unless mature candidates were checked and ADR exception exists when mature path is rejected",
            "blocks_report_only": True,
            "blocks_local_default_without_exception": True,
        },
        "golden_path_catalog": {
            mechanism_id: GENERIC_CAPABILITY_CATALOG[mechanism_id]["golden_path"]
            for mechanism_id in mechanism_ids
        },
        "fitness_functions": [
            "generic_mechanisms_detected",
            "mature_candidates_checked",
            "local_impl_roles_bounded",
            "handroll_requires_adr_or_repair",
            "policy_as_code_surface_present",
        ],
        "output_paths": output,
        "report_substitute_allowed": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
    }
    payload["validation"] = build_validation(payload)
    if payload["validation"]["passed"] is not True:
        payload["status"] = "mature_capability_first_validation_blocked"
    if write:
        write_json(Path(output["latest"]), payload)
        write_json(Path(output["task_wave"]), payload)
        write_json(
            Path(output["fitness_latest"]),
            {
                "schema_version": f"{SCHEMA_VERSION}.fitness.v1",
                "status": "mature_capability_first_fitness_ready",
                "task_id": task_id,
                "wave_id": wave_id,
                "fitness_functions": payload["fitness_functions"],
                "validation": payload["validation"],
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            },
        )
        write_text(Path(output["readback_zh"]), render_readback(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build MatureCapabilityFirst evidence.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--task-id", default="mature_capability_first_20260705")
    parser.add_argument("--wave-id", default="mature-capability-first-wave-001")
    parser.add_argument("--task-text", default="")
    parser.add_argument("--mechanism", action="append", default=[])
    parser.add_argument("--invoked-by", default="cli")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        task_id=args.task_id,
        wave_id=args.wave_id,
        task_text=args.task_text,
        extra_mechanisms=args.mechanism,
        invoked_by=args.invoked_by,
        write=not args.no_write,
    )
    print(
        json.dumps(
            {
                "schema_version": payload["schema_version"],
                "sentinel": payload["sentinel"],
                "status": payload["status"],
                "task_id": payload["task_id"],
                "wave_id": payload["wave_id"],
                "mechanism_count": payload["mechanism_count"],
                "latest_ref": payload["output_paths"]["latest"],
                "readback_zh_ref": payload["output_paths"]["readback_zh"],
                "validation": payload["validation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
