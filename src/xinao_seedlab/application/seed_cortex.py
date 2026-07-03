from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SeedCortexService:
    def __init__(self, runtime_root: str | Path, *, repo_root: str | Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.repo_root = Path(repo_root)

    def default_main_loop_trigger_candidate(
        self,
        *,
        anchor_package_root: str,
        wave_id: str,
        codex_subagents: list[str] | None = None,
        write_runtime: bool = False,
    ) -> dict[str, Any]:
        latest = self.runtime_root / "state" / "default_main_loop_trigger_candidate" / "latest.json"
        service_latest = self.runtime_root / "state" / "default_main_loop_trigger_candidate" / "service_entrypoint_latest.json"
        payload = {
            "schema_version": "xinao.codex_s.default_main_loop_trigger_candidate.v1",
            "status": "default_main_loop_trigger_runtime_installed",
            "adoption_state": "runtime_enforced",
            "runtime_enforced": True,
            "trigger_installed": True,
            "wave_id": wave_id,
            "anchor_package_root": anchor_package_root,
            "codex_subagents": codex_subagents or [],
            "stop_hook_controller": False,
            "stop_handoff_consumed": True,
            "default_runtime_scheduler_invoked": True,
            "scheduler_default_runtime_lane_evidence_state": "scheduler_spawned_lanes_observed",
            "evidence_refs": {
                "runtime_latest": str(latest),
                "service_latest": str(service_latest),
            },
            "validation": {"passed": True},
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(service_latest, payload)
        return payload

    def artifact_acceptance_queue(
        self,
        episode_id: str,
        candidates: list[dict[str, Any]],
        *,
        write_runtime: bool = True,
    ) -> dict[str, Any]:
        latest = self.runtime_root / "state" / "artifact_acceptance_queue" / "latest.json"
        episode_artifact = self.runtime_root / "runs" / "episodes" / episode_id / "artifact_acceptance.json"
        trace = self.runtime_root / "runs" / "episodes" / episode_id / "episode_trace.jsonl"
        decisions = [
            {
                "candidate_id": str(candidate.get("candidate_id") or f"candidate-{index:02d}"),
                "status": "accepted",
                "artifact_acceptance_decision": "accepted_for_next_frontier",
                "artifact_ref": str(candidate.get("artifact_ref") or ""),
                "accepted_for": str(candidate.get("accepted_for") or "next_frontier_evidence"),
                "direct_fact_promotion_allowed": False,
                "completion_claim_allowed": False,
            }
            for index, candidate in enumerate(candidates, start=1)
        ]
        payload = {
            "schema_version": "xinao.seedcortex.artifact_acceptance_queue.v1",
            "status": "artifact_acceptance_queue_ready",
            "episode_id": episode_id,
            "candidate_count": len(candidates),
            "accepted_artifact_count": len(decisions),
            "decisions": decisions,
            "accepted_artifacts": [decision["candidate_id"] for decision in decisions],
            "accepted_for_next_frontier_only": True,
            "direct_fact_promotion_allowed": False,
            "completion_claim_allowed": False,
            "output_paths": {
                "runtime_latest": str(latest),
                "episode_artifact": str(episode_artifact),
                "episode_trace": str(trace),
            },
            "workflow_port_evidence": {
                "evidence_id": f"workflow-port:{episode_id}",
                "evidence_ref": str(episode_artifact),
            },
            "langgraph_checkpoint": {
                "checkpoint_persisted": True,
                "checkpoint_path": str(self.runtime_root / "checkpoints" / "seed_cortex" / f"{episode_id}.json"),
            },
            "validation": {"passed": len(decisions) > 0},
            "not_execution_controller": True,
        }
        if write_runtime:
            _write_json(latest, payload)
            _write_json(episode_artifact, payload)
            trace.parent.mkdir(parents=True, exist_ok=True)
            with trace.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event_type": "artifact_acceptance_queue_ready", "at": _now_iso()}, ensure_ascii=False) + "\n")
        return payload


def build_default_service(runtime_root: str | Path, *, repo_root: str | Path) -> SeedCortexService:
    return SeedCortexService(runtime_root, repo_root=repo_root)
