#!/usr/bin/env python3
"""Atomically promote or restore the Grok-provider default model policy.

The policy is data only.  Temporal/ACPX performs the model call, and Codex
remains the sole writer that applies this bounded local cutover.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_POLICY = DEFAULT_RUNTIME / "agent_runtime" / "routing_policy.json"
DEFAULT_EVIDENCE_ROOT = DEFAULT_RUNTIME / "state" / "grok_provider_routing" / "promotions"
DEFAULT_MODEL = "grok-composer-2.5-fast"
ROLLBACK_MODEL = "grok-4.5"
ALLOWED_MODELS = frozenset({DEFAULT_MODEL, ROLLBACK_MODEL})
DEFAULT_ROUTE_ROLE = "default_background_worker"
PRO_REVIEW_MODEL = "grok-4.5"
MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v1"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_policy(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("routing policy must be a JSON object")
    return raw, payload


def _default_route(payload: dict[str, Any]) -> dict[str, Any]:
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise ValueError("routing policy routes must be a list")
    matches = [
        item
        for item in routes
        if isinstance(item, dict) and item.get("route_role") == DEFAULT_ROUTE_ROLE
    ]
    if len(matches) != 1:
        raise ValueError("routing policy must contain exactly one default_background_worker route")
    route = matches[0]
    if str(route.get("provider_id") or "") != "grok_acpx_headless":
        raise ValueError("default background route is not the canonical Grok ACPX provider")
    return route


def build_policy(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    if model not in ALLOWED_MODELS:
        raise ValueError(f"unsupported Grok provider model: {model}")
    candidate = copy.deepcopy(payload)
    route = _default_route(candidate)
    route["preferred_model"] = model
    candidate["pro_review_after_draft"] = PRO_REVIEW_MODEL
    candidate["grok_provider_model_policy"] = {
        "schema_version": MODEL_POLICY_ID,
        "default_worker_model": model,
        "escalation_model": PRO_REVIEW_MODEL,
        "formal_writer": "codex",
        "deterministic_first": True,
        "worker_default_capability": "read_only",
        "write_requires_isolated_worktree": True,
        "account_quota_scope": "single_grok_account",
    }
    return candidate


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def plan_set_model(path: Path, *, model: str, expected_current_model: str = "") -> dict[str, Any]:
    before_raw, before = _read_policy(path)
    before_model = str(_default_route(before).get("preferred_model") or "")
    if expected_current_model and before_model != expected_current_model:
        raise ValueError(
            f"routing policy default changed: expected {expected_current_model}, observed {before_model}"
        )
    after = build_policy(before, model=model)
    after_raw = _canonical_bytes(after)
    return {
        "action": "set_model",
        "policy_path": str(path.resolve()),
        "before_model": before_model,
        "after_model": model,
        "before_sha256": _sha256(before_raw),
        "after_sha256": _sha256(after_raw),
        "before_raw": before_raw,
        "after_raw": after_raw,
    }


def plan_restore(path: Path, *, backup: Path, expected_current_model: str = "") -> dict[str, Any]:
    before_raw, before = _read_policy(path)
    restore_raw, restore = _read_policy(backup)
    before_model = str(_default_route(before).get("preferred_model") or "")
    restore_model = str(_default_route(restore).get("preferred_model") or "")
    if expected_current_model and before_model != expected_current_model:
        raise ValueError(
            f"routing policy default changed: expected {expected_current_model}, observed {before_model}"
        )
    if restore_model not in ALLOWED_MODELS:
        raise ValueError(f"backup contains unsupported Grok provider model: {restore_model}")
    return {
        "action": "restore_backup",
        "policy_path": str(path.resolve()),
        "restore_source": str(backup.resolve()),
        "before_model": before_model,
        "after_model": restore_model,
        "before_sha256": _sha256(before_raw),
        "after_sha256": _sha256(restore_raw),
        "before_raw": before_raw,
        "after_raw": restore_raw,
    }


def apply_plan(plan: dict[str, Any], *, evidence_root: Path) -> dict[str, Any]:
    policy_path = Path(str(plan["policy_path"]))
    current_raw, current = _read_policy(policy_path)
    current_model = str(_default_route(current).get("preferred_model") or "")
    if _sha256(current_raw) != plan["before_sha256"] or current_model != plan["before_model"]:
        raise RuntimeError("routing policy changed after planning; refusing stale cutover")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = evidence_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    rollback_path = run_dir / "routing_policy.before.json"
    rollback_path.write_bytes(bytes(plan["before_raw"]))
    _write_atomic(policy_path, bytes(plan["after_raw"]))
    observed_raw, observed = _read_policy(policy_path)
    observed_model = str(_default_route(observed).get("preferred_model") or "")
    if _sha256(observed_raw) != plan["after_sha256"] or observed_model != plan["after_model"]:
        _write_atomic(policy_path, bytes(plan["before_raw"]))
        raise RuntimeError("routing policy verification failed; exact pre-change bytes restored")
    receipt = {
        "schema_version": "xinao.grok.provider_default_cutover.v1",
        "action": plan["action"],
        "policy_path": str(policy_path),
        "before_model": plan["before_model"],
        "after_model": plan["after_model"],
        "before_sha256": plan["before_sha256"],
        "after_sha256": plan["after_sha256"],
        "rollback_path": str(rollback_path),
        "restore_source": str(plan.get("restore_source") or ""),
        "applied": True,
        "verified": True,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {**receipt, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--set-model", choices=sorted(ALLOWED_MODELS))
    mode.add_argument("--restore-backup", type=Path)
    parser.add_argument("--expected-current-model", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.set_model:
        plan = plan_set_model(
            args.policy.resolve(),
            model=args.set_model,
            expected_current_model=args.expected_current_model,
        )
    else:
        plan = plan_restore(
            args.policy.resolve(),
            backup=args.restore_backup.resolve(),
            expected_current_model=args.expected_current_model,
        )
    if args.apply:
        output = apply_plan(plan, evidence_root=args.evidence_root)
    else:
        output = {
            key: value for key, value in plan.items() if key not in {"before_raw", "after_raw"}
        }
        output["applied"] = False
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
