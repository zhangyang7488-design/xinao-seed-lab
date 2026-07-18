#!/usr/bin/env python3
"""Compile one fresh model-identity probe from a verified single-lane payload."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ALLOWED_MODELS = frozenset({"grok-composer-2.5-fast", "grok-4.5"})


def compile_identity_payload(
    source: Mapping[str, Any], *, model: str, operation_id: str
) -> dict[str, Any]:
    if model not in ALLOWED_MODELS:
        raise ValueError(f"unsupported Grok identity model: {model}")
    payload = copy.deepcopy(dict(source))
    lanes = payload.get("grok_ready_frontier")
    if not isinstance(lanes, list) or len(lanes) != 1 or not isinstance(lanes[0], dict):
        raise ValueError("identity probe requires exactly one Grok lane")
    lane = lanes[0]
    lane_id = str(lane.get("lane_id") or "")
    bindings = payload.get("lane_bindings")
    routing = payload.get("supervisor_routing")
    if (
        not lane_id
        or not isinstance(bindings, dict)
        or not isinstance(bindings.get(lane_id), dict)
        or not isinstance(routing, dict)
        or not isinstance(routing.get("candidates"), list)
        or len(routing["candidates"]) != 1
        or not isinstance(routing["candidates"][0], dict)
        or not isinstance(routing.get("supervisor_choice"), dict)
    ):
        raise ValueError("identity probe source lacks exact supervisor bindings")

    lane["model"] = model
    bindings[lane_id]["requested_model"] = model
    routing["candidates"][0]["model_id"] = model
    routing["supervisor_choice"]["model_id"] = model
    payload["operation_id"] = operation_id
    payload["parent_operation_id"] = operation_id
    payload["correlation_id"] = f"{operation_id}:identity-probe"
    for ephemeral in (
        "decision_hash",
        "immutable_intent_hash",
        "supervisor_worker_decision",
        "task_id",
        "workflow_id",
    ):
        payload.pop(ephemeral, None)

    selected = [
        lane.get("model"),
        bindings[lane_id].get("requested_model"),
        routing["candidates"][0].get("model_id"),
        routing["supervisor_choice"].get("model_id"),
    ]
    if selected != [model] * 4:
        raise ValueError("identity probe model bindings drifted")
    return payload


def write_json_atomic(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return path.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-payload", type=Path, required=True)
    parser.add_argument("--model", choices=sorted(ALLOWED_MODELS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source_payload.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise TypeError("source payload must be a JSON object")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ").lower()
    operation_id = f"grok-docker-identity-{args.model.replace('.', '-')}-{stamp}"
    payload = compile_identity_payload(source, model=args.model, operation_id=operation_id)
    output = write_json_atomic(args.output_dir / "payload.json", payload)
    print(json.dumps({"operation_id": operation_id, "model": args.model, "payload": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
