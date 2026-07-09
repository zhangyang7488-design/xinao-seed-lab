"""L5 策略门薄绑 — OPA/Conftest eval smoke (host binary or docker opa)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, SCHEMA_VERSION, SENTINEL, now_iso, write_json

TASK_ID = "thin_glue_opa_conftest"
REPLACES_MODULE = "opa_policy_handroll"
_POLICY_REL = Path("policies") / "integrated_bus_opa_smoke.rego"
_DOCKER_OPA_IMAGE = os.environ.get("XINAO_OPA_DOCKER_IMAGE", "openpolicyagent/opa:1.0.0")


def resolve_policy_path(*, repo_root: Path | None = None) -> Path:
    repo = repo_root or DEFAULT_REPO
    return repo / _POLICY_REL


def _opa_argv(*, repo_root: Path) -> list[str] | None:
    if shutil.which("opa"):
        return ["opa"]
    if shutil.which("docker"):
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo_root}:/repo:ro",
            _DOCKER_OPA_IMAGE,
            "opa",
        ]
    return None


def probe_opa_binary(*, repo_root: Path | None = None) -> dict[str, Any]:
    repo = repo_root or DEFAULT_REPO
    argv = _opa_argv(repo_root=repo)
    if not argv:
        return {
            "adapter": "opa",
            "ok": False,
            "skipped": True,
            "reason": "opa_and_docker_missing",
            "named_blocker": "OPA_BINARY_MISSING",
        }
    try:
        completed = subprocess.run(
            [*argv, "version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {
            "adapter": "opa",
            "ok": False,
            "skipped": True,
            "reason": str(exc),
            "named_blocker": "OPA_VERSION_PROBE_FAILED",
            "invoke_via": argv[0],
        }
    if completed.returncode != 0:
        return {
            "adapter": "opa",
            "ok": False,
            "skipped": True,
            "reason": (completed.stderr or completed.stdout or "opa_version_failed").strip()[:300],
            "named_blocker": "OPA_VERSION_PROBE_FAILED",
            "invoke_via": argv[0],
        }
    return {
        "adapter": "opa",
        "ok": True,
        "skipped": False,
        "invoke_via": argv[0],
        "version_excerpt": (completed.stdout or completed.stderr or "")[:200],
    }


def eval_opa_smoke(
    *,
    repo_root: Path | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    repo = repo_root or DEFAULT_REPO
    policy = policy_path or resolve_policy_path(repo_root=repo)
    probe = probe_opa_binary(repo_root=repo)
    if not probe.get("ok"):
        return {
            "adapter": "opa_conftest",
            "ok": False,
            "skipped": True,
            "reason": probe.get("reason") or "probe_failed",
            "named_blocker": probe.get("named_blocker") or "OPA_PROBE_FAILED",
            "probe": probe,
        }
    if not policy.is_file():
        return {
            "adapter": "opa_conftest",
            "ok": False,
            "skipped": True,
            "reason": f"policy_missing:{policy}",
            "named_blocker": "OPA_POLICY_MISSING",
            "probe": probe,
            "policy_path": str(policy),
        }
    argv = _opa_argv(repo_root=repo) or []
    input_payload = {
        "thin_glue": "integrated_bus_smoke",
        "invoke_ok": True,
        "completion_requested": False,
        "object_preserved": True,
    }
    with tempfile.TemporaryDirectory(prefix="thin_glue_opa_") as tmp:
        input_path = Path(tmp) / "input.json"
        input_path.write_text(json.dumps(input_payload), encoding="utf-8")
        policy_mount = policy
        input_mount = input_path
        if argv[:2] == ["docker", "run"]:
            policy_mount = Path("/repo") / _POLICY_REL
            input_mount = Path("/input") / "input.json"
            argv = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{repo}:/repo:ro",
                "-v",
                f"{tmp}:/input:ro",
                _DOCKER_OPA_IMAGE,
                "opa",
            ]
        allow_cmd = [
            *argv,
            "eval",
            "--format=json",
            "--data",
            str(policy_mount),
            "--input",
            str(input_mount),
            "data.xinao.integrated_bus_opa_smoke.allow",
        ]
        deny_cmd = [
            *argv,
            "eval",
            "--format=json",
            "--data",
            str(policy_mount),
            "--input",
            str(input_mount),
            "data.xinao.integrated_bus_opa_smoke.deny",
        ]
        try:
            allow_proc = subprocess.run(allow_cmd, capture_output=True, text=True, timeout=30, check=False)
            deny_proc = subprocess.run(deny_cmd, capture_output=True, text=True, timeout=30, check=False)
        except Exception as exc:
            return {
                "adapter": "opa_conftest",
                "ok": False,
                "skipped": True,
                "reason": str(exc),
                "named_blocker": "OPA_EVAL_FAILED",
                "probe": probe,
                "policy_path": str(policy),
            }
    if allow_proc.returncode != 0:
        return {
            "adapter": "opa_conftest",
            "ok": False,
            "skipped": True,
            "reason": (allow_proc.stderr or allow_proc.stdout or "allow_eval_failed").strip()[:300],
            "named_blocker": "OPA_ALLOW_EVAL_FAILED",
            "probe": probe,
            "policy_path": str(policy),
        }
    try:
        allow_value = json.loads(allow_proc.stdout)["result"][0]["expressions"][0]["value"]
        deny_value = json.loads(deny_proc.stdout)["result"][0]["expressions"][0]["value"]
    except Exception as exc:
        return {
            "adapter": "opa_conftest",
            "ok": False,
            "skipped": True,
            "reason": f"OPA_PARSE_FAILED:{type(exc).__name__}",
            "named_blocker": "OPA_PARSE_FAILED",
            "probe": probe,
            "policy_path": str(policy),
        }
    ok = allow_value is True and (not deny_value)
    return {
        "adapter": "opa_conftest",
        "ok": ok,
        "skipped": not ok,
        "allow": allow_value,
        "deny": sorted(deny_value) if isinstance(deny_value, list) else deny_value,
        "conftest_style": True,
        "probe": probe,
        "policy_path": str(policy),
        "named_blocker": None if ok else "OPA_POLICY_DENY",
    }


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_opa"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_opa_latest.md",
    }


def run_opa_smoke(
    *,
    runtime: Path | None = None,
    repo_root: Path | None = None,
    run_id: str | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    rt = runtime or DEFAULT_RUNTIME
    resolved_run_id = run_id or datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    evaluated = eval_opa_smoke(repo_root=repo_root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_id": TASK_ID,
        "layer": "L5",
        "replaces": REPLACES_MODULE,
        "run_id": resolved_run_id,
        "timestamp": now_iso(),
        "invoke_ok": evaluated.get("ok") is True,
        "opa_ok": evaluated.get("ok") is True,
        "L5_opa_ok": evaluated.get("ok") is True,
        "named_blocker": evaluated.get("named_blocker"),
        "eval": evaluated,
    }
    if write_evidence:
        paths = output_paths(rt)
        write_json(paths["latest"], payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# thin_glue_opa",
                    f"- invoke_ok: {payload['invoke_ok']}",
                    f"- policy: {evaluated.get('policy_path') or 'none'}",
                    f"- allow: {evaluated.get('allow')}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {k: str(v) for k, v in paths.items()}
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OPA/Conftest thin-glue smoke")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    args = parser.parse_args()
    payload = run_opa_smoke(runtime=Path(args.runtime_root))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("invoke_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())