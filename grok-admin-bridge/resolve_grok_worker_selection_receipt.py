"""Capability-bound CLI adapter for the canonical supervisor-worker selector.

Each root is probed in a fresh isolated interpreter by the PowerShell caller.
This module additionally binds the imported module and all loaded
``services.agent_runtime`` package sources to the exact resolved root before
it may create a selection receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable


MODULE_NAME = "services.agent_runtime.routing_policy_reader"
INTERFACE_NAME = "resolve_supervisor_worker_decision"
PROBE_SCHEMA = "xinao.grok_supervisor_root_capability_probe.v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervisor-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--expected-selector-sha256", default="")
    args = parser.parse_args()
    if not args.probe_only:
        missing = [
            name
            for name in ("runtime_root", "model", "output")
            if getattr(args, name) is None
        ]
        if missing:
            parser.error("normal selection requires: " + ", ".join(missing))
    return args


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"selection receipt already exists: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _package_identity(root: Path) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    observed: dict[str, list[str]] = {}
    foreign: list[dict[str, str]] = []
    for name, module in sorted(sys.modules.items()):
        if name != "services" and not name.startswith("services.agent_runtime"):
            continue
        paths: list[str] = []
        module_file = getattr(module, "__file__", None)
        if module_file:
            paths.append(str(Path(module_file).resolve(strict=True)))
        module_paths = getattr(module, "__path__", None)
        if module_paths:
            paths.extend(str(Path(value).resolve(strict=True)) for value in module_paths)
        unique = list(dict.fromkeys(paths))
        observed[name] = unique
        for value in unique:
            resolved = Path(value)
            if not _under(resolved, root):
                foreign.append({"module": name, "path": value})
    return observed, foreign


def probe_supervisor_root(raw_root: Path) -> tuple[dict[str, Any], Callable[..., dict[str, Any]] | None]:
    report: dict[str, Any] = {
        "schema_version": PROBE_SCHEMA,
        "requested_root": str(raw_root),
        "python_executable": str(Path(sys.executable).resolve(strict=True)),
        "python_isolated": bool(sys.flags.isolated),
        "dont_write_bytecode": bool(sys.dont_write_bytecode),
        "module_name": MODULE_NAME,
        "required_interface": INTERFACE_NAME,
        "capable": False,
        "failure_code": "",
        "failure_detail": "",
    }
    try:
        root = raw_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        report.update(failure_code="SUPERVISOR_ROOT_MISSING", failure_detail=str(exc))
        return report, None
    report["resolved_root"] = str(root)
    selector_source = root / "services" / "agent_runtime" / "routing_policy_reader.py"
    if not selector_source.is_file():
        report.update(
            failure_code="SUPERVISOR_SELECTOR_ENTRY_MISSING",
            failure_detail=str(selector_source),
        )
        return report, None
    selector_source = selector_source.resolve(strict=True)
    selector_sha = hashlib.sha256(selector_source.read_bytes()).hexdigest()
    report["selector_source"] = str(selector_source)
    report["selector_source_sha256"] = selector_sha

    preloaded = sorted(
        name
        for name in sys.modules
        if name == "services" or name.startswith("services.agent_runtime")
    )
    if preloaded:
        report.update(
            failure_code="SUPERVISOR_SELECTOR_PACKAGE_CACHE_PRELOADED",
            failure_detail=",".join(preloaded),
        )
        return report, None

    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        module = importlib.import_module(MODULE_NAME)
    except Exception as exc:  # diagnostic boundary; no receipt is written
        report.update(
            failure_code="SUPERVISOR_SELECTOR_IMPORT_FAILED",
            failure_detail=f"{type(exc).__name__}: {exc}",
        )
        return report, None
    module_file = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    report["imported_module_source"] = str(module_file)
    if module_file != selector_source:
        report.update(
            failure_code="SUPERVISOR_SELECTOR_SOURCE_IDENTITY_MISMATCH",
            failure_detail=f"expected={selector_source};observed={module_file}",
        )
        return report, None
    package_sources, foreign_sources = _package_identity(root)
    report["loaded_package_sources"] = package_sources
    report["foreign_package_sources"] = foreign_sources
    if foreign_sources:
        report.update(
            failure_code="SUPERVISOR_SELECTOR_PACKAGE_IDENTITY_MISMATCH",
            failure_detail=json.dumps(foreign_sources, sort_keys=True, separators=(",", ":")),
        )
        return report, None
    interface = getattr(module, INTERFACE_NAME, None)
    if not callable(interface):
        report.update(
            failure_code="SUPERVISOR_SELECTOR_INTERFACE_MISSING",
            failure_detail=f"{INTERFACE_NAME} is not callable in {module_file}",
        )
        return report, None
    report.update(capable=True, failure_code="", failure_detail="")
    return report, interface


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main() -> int:
    args = _parse_args()
    probe, selector = probe_supervisor_root(args.supervisor_root)
    if args.probe_only:
        _emit(probe)
        return 0 if probe.get("capable") is True else 20
    if probe.get("capable") is not True or selector is None:
        raise RuntimeError(
            "SUPERVISOR_SELECTOR_CAPABILITY_REJECTED:"
            + json.dumps(probe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    expected_sha = str(args.expected_selector_sha256 or "").strip().lower()
    observed_sha = str(probe.get("selector_source_sha256") or "")
    if expected_sha and expected_sha != observed_sha:
        raise RuntimeError(
            "SUPERVISOR_SELECTOR_SOURCE_CHANGED:"
            f"expected={expected_sha};observed={observed_sha}"
        )

    model = str(args.model or "").strip()
    if not model:
        raise ValueError("model must be non-empty")
    identity = {
        "provider_id": "grok_acpx_headless",
        "profile_ref": "grok.com.cached_profile",
        "model_id": model,
        "transport_id": "direct-grok-worker-pool",
    }
    request = {
        "candidates": [
            {
                **identity,
                "declared_active": True,
                "healthy": True,
                "positive_benefit": True,
                "context_capable": False,
            }
        ],
        "task_separable": True,
        "supervisor_choice": identity,
        "context_inheritance_required": False,
    }
    assert args.runtime_root is not None
    receipt = selector(
        request,
        runtime_root=args.runtime_root.resolve(strict=True),
    )
    selected = receipt.get("selected_candidate")
    if receipt.get("decision") != "selected" or not isinstance(selected, dict):
        raise RuntimeError(
            "canonical selector did not select the exact direct Grok candidate: "
            + str(receipt.get("decision_reason") or receipt.get("decision"))
        )
    observed_identity = {
        key: str(selected.get(key) or "")
        for key in ("provider_id", "profile_ref", "model_id", "transport_id")
    }
    if observed_identity != identity:
        raise RuntimeError(
            f"canonical selector identity mismatch: selected={observed_identity} requested={identity}"
        )

    assert args.output is not None
    output = args.output.resolve(strict=False)
    _atomic_write_json(output, receipt)
    _emit(
        {
            "selection_path": str(output),
            "decision_sha256": str(receipt.get("decision_sha256") or ""),
            "selector_binding": {
                "resolved_root": probe["resolved_root"],
                "selector_source": probe["selector_source"],
                "selector_source_sha256": probe["selector_source_sha256"],
                "imported_module_source": probe["imported_module_source"],
                "python_executable": probe["python_executable"],
                "python_isolated": probe["python_isolated"],
                "dont_write_bytecode": probe["dont_write_bytecode"],
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
