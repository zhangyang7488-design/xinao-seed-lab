"""Single thin-glue worker lane — L4 search draft artifact (replaces run_lane hand-roll)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_l4_search import derive_search_query, run_thin_glue_search
from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    now_iso,
    write_json,
)

LANE_SCHEMA = "xinao.codex_s.thin_glue_lane_worker.v1"


def run_thin_glue_lane(
    *,
    lane_id: str,
    mode: str = "draft",
    query: str,
    wave_id: str,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    lane_number: int = 1,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{lane_number}"
    local_q = derive_search_query(query, fallback="thin_glue")
    search = run_thin_glue_search(
        runtime_root=runtime,
        repo_root=repo,
        run_id=f"{wave_id}_{lane_id}",
        local_query=local_q,
        external_query=f"thin_glue {query}",
        write=False,
    )
    local_hits = int(search.get("local_hit_count") or 0)
    ok = local_hits > 0 or search.get("validation", {}).get("passed") is True
    lanes_dir = runtime / "worker_pool" / "lanes"
    artifact_path = lanes_dir / f"{lane_id}_{run_id}.json"
    draft_text = f"# thin_glue lane {lane_id}\nmode={mode} query={query}\nlocal_hits={local_hits}\n"
    artifact_payload = {
        "schema_version": LANE_SCHEMA,
        "lane_id": lane_id,
        "lane_number": lane_number,
        "mode": mode,
        "wave_id": wave_id,
        "query": query,
        "local_hit_count": local_hits,
        "draft_text": draft_text,
        "thin_glue": True,
        "hand_rolled_run_lane_bypassed": True,
        "status": "succeeded" if ok else "blocked",
        "mode_invocation_status": "draft_ready" if ok and mode == "draft" else "blocked",
        "provider_invocation_performed": False,
        "model_invocation_performed": False,
        "tool_invocation_performed": True,
        "external_draft_invocation": False,
        "local_stub": False,
        "artifact_ref": str(artifact_path),
        "draft_ref": str(artifact_path),
        "artifact_exists": ok,
        "named_blocker": "" if ok else "THIN_GLUE_LANE_NO_LOCAL_HITS",
        "timestamp": now_iso(),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    if write:
        lanes_dir.mkdir(parents=True, exist_ok=True)
        write_json(artifact_path, artifact_payload)
    return artifact_payload
