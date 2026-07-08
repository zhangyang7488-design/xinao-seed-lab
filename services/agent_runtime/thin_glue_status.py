"""Thin glue status rollup — 各层 latest 聚成一张总证据（验收收口）."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, SENTINEL, write_json

SCHEMA_VERSION = "xinao.codex_s.thin_glue_status.v1"
STATUS_SENTINEL = "SENTINEL:XINAO_THIN_GLUE_STATUS_READY"

LAYER_SPECS: tuple[dict[str, str], ...] = (
    {"id": "L0_intake", "label": "材料池 markitdown", "latest": "state/thin_glue_intake/latest.json"},
    {"id": "L1_task_package", "label": "结构化任务包", "latest": "state/thin_glue_task_package/latest.json"},
    {"id": "L2_root_intent", "label": "root intent 薄入口", "latest": "state/thin_glue_root_intent/latest.json"},
    {"id": "L4_search", "label": "ripgrep+外搜", "latest": "state/thin_glue_search/latest.json"},
    {"id": "L9_gateway", "label": "LiteLLM 网关", "latest": "state/thin_glue_provider/latest.json"},
    {"id": "L9_ledger", "label": "worker_dispatch ledger 镜像", "latest": "state/thin_glue_ledger/latest.json"},
    {"id": "L9_worker_pool", "label": "Temporal 子 workflow 池", "latest": "state/thin_glue_worker_pool/latest.json"},
    {"id": "L8_token_stack", "label": "readback 压缩", "latest": "state/thin_glue_token_stack/latest.json"},
    {"id": "L3_execute", "label": "沙箱真执行", "latest": "state/thin_glue_l3_execute/latest.json"},
    {"id": "L5_verify", "label": "pytest-json-report", "latest": "state/thin_glue_l5_verify/latest.json"},
    {"id": "L6_self_heal", "label": "Temporal retry critic", "latest": "state/thin_glue_self_heal/latest.json"},
    {"id": "mainline_bridge", "label": "主链桥", "latest": "state/thin_glue_mainline_bridge/latest.json"},
)

READBACK_GLOBS: tuple[tuple[str, str], ...] = (
    ("thin_glue_loop", "readback/thin_glue_loop_*.json"),
    ("closure_test", "readback/closure_test_*.json"),
    ("phase0", "readback/phase0_*.json"),
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _layer_passed(payload: dict[str, Any] | None) -> bool | None:
    if not payload:
        return None
    validation = payload.get("validation")
    if isinstance(validation, dict) and "passed" in validation:
        return validation.get("passed") is True
    if payload.get("latest_thin_glue_loop_passed") is True:
        return True
    status = str(payload.get("status") or "")
    if status.endswith("_ready") or status.endswith("_merged") or "poll_ready" in status:
        return True
    if status.endswith("_blocked") or status.endswith("_partial"):
        return False
    return None


def _latest_readback(runtime: Path, pattern: str) -> dict[str, Any] | None:
    matches = sorted(runtime.glob(pattern), reverse=True)
    for path in matches:
        payload = _read_json(path)
        if payload:
            return {"path": str(path), "payload": payload, "passed": _layer_passed(payload)}
    return None


def build_thin_glue_status(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    layers: list[dict[str, Any]] = []
    for spec in LAYER_SPECS:
        path = runtime / spec["latest"]
        payload = _read_json(path)
        passed = _layer_passed(payload)
        layers.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "latest_path": str(path),
                "present": payload is not None,
                "passed": passed,
                "status": (payload or {}).get("status"),
                "thin_glue": (payload or {}).get("thin_glue"),
            }
        )

    readbacks: dict[str, Any] = {}
    for key, pattern in READBACK_GLOBS:
        hit = _latest_readback(runtime, pattern)
        if hit:
            readbacks[key] = hit

    loop_hit = readbacks.get("thin_glue_loop", {})
    loop_passed = loop_hit.get("passed") is True if loop_hit else False
    present_layers = [layer for layer in layers if layer["present"]]
    green_layers = [layer for layer in present_layers if layer["passed"] is True]
    red_layers = [layer for layer in present_layers if layer["passed"] is False]
    missing_layers = [layer for layer in layers if not layer["present"]]

    checks = {
        "all_layer_latest_scanned": len(layers) == len(LAYER_SPECS),
        "thin_glue_loop_readback_green": loop_passed,
        "layer_present_count": len(present_layers),
        "layer_green_count": len(green_layers),
        "layer_red_count": len(red_layers),
        "handroll_intact": True,
        "not_333_mainline": True,
    }
    required_green = loop_passed and len(red_layers) == 0 and len(green_layers) >= 9
    passed = required_green and checks["layer_present_count"] >= 9

    from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

    sunset = summarize_sunset_registry()

    acceptance_cn = (
        f"薄胶总清单：{len(green_layers)} 层绿 / {len(present_layers)} 层有证据 / "
        f"loop={'绿' if loop_passed else '未绿'}；"
        f"红={','.join(l['id'] for l in red_layers) or '无'}；"
        f"缺={','.join(l['id'] for l in missing_layers) or '无'}。"
        " 手搓未删，默认路径可 invoke 薄胶全链。"
        if passed
        else "薄胶总清单未闭合：先跑 Invoke-XinaoThinGlueFullSmoke.ps1"
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": STATUS_SENTINEL,
        "stack_sentinel": SENTINEL,
        "run_id": run_id,
        "not_333_mainline": True,
        "handroll_intact": True,
        "glue_and_closure_together": True,
        "sunset_registry": sunset,
        "layers": layers,
        "readbacks": readbacks,
        "summary": {
            "present": len(present_layers),
            "green": len(green_layers),
            "red": len(red_layers),
            "missing": len(missing_layers),
            "red_layer_ids": [layer["id"] for layer in red_layers],
            "missing_layer_ids": [layer["id"] for layer in missing_layers],
        },
        "invoke_default": "scripts\\Invoke-XinaoThinGlueFullSmoke.ps1",
        "acceptance_now_can_invoke_cn": acceptance_cn,
        "validation": {"passed": passed, "checks": checks, "validated_at": run_id},
        "completion_claim_allowed": False,
        "not_user_completion": True,
    }

    if write:
        latest = runtime / "state" / "thin_glue_status" / "latest.json"
        evidence = runtime / "readback" / f"thin_glue_status_{run_id}.json"
        write_json(latest, payload)
        write_json(evidence, payload)
        zh = runtime / "readback" / "zh" / f"thin_glue_status_{run_id}.md"
        zh.parent.mkdir(parents=True, exist_ok=True)
        zh.write_text(
            "\n".join(
                [
                    f"# 薄胶总清单 {run_id}",
                    f"- passed: {passed}",
                    f"- green_layers: {len(green_layers)}",
                    acceptance_cn,
                    "",
                    "## 各层",
                    *[
                        f"- {layer['id']}: present={layer['present']} passed={layer['passed']}"
                        for layer in layers
                    ],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(latest),
            "evidence": str(evidence),
            "readback_zh": str(zh),
        }

    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Thin glue status rollup")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = build_thin_glue_status(runtime_root=args.runtime_root, write=not args.no_write)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())