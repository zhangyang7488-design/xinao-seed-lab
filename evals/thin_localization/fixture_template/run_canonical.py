from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, default=ROOT / "config" / "binding.json")
    parser.add_argument("--input", type=Path, default=ROOT / "input.json")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_semantics(raw: str) -> tuple[object, str]:
    value = json.loads(raw)
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return value, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def invoke(binding: dict[str, object], input_path: Path) -> dict[str, object]:
    if binding.get("fallback_allowed") is not False:
        raise RuntimeError("fallback must remain disabled")
    executable = str(binding.get("executable") or "")
    resolved = shutil.which(executable)
    if not resolved:
        raise RuntimeError(f"selected upstream executable is unavailable: {executable}")
    version = subprocess.run(
        [resolved, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    observed_pin = (version.stdout or version.stderr).strip()
    if observed_pin != binding.get("pin"):
        raise RuntimeError(
            f"provider pin mismatch: expected {binding.get('pin')!r}, got {observed_pin!r}"
        )
    command = [resolved, *[str(item) for item in binding.get("args", [])], str(input_path)]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    _, semantic_sha256 = normalize_semantics(completed.stdout)
    return {
        "schema_version": "xinao.external_invocation_receipt.v1",
        "provider_id": binding.get("selected_candidate"),
        "source_kind": binding.get("source_kind"),
        "source_url": binding.get("source_url"),
        "pin": observed_pin,
        "resolved_executable": resolved,
        "command_argv": command,
        "exit_code": completed.returncode,
        "fallback_used": False,
        "upstream_invoked": True,
        "semantic_sha256": semantic_sha256,
        "invocation_nonce": "REAL-UPSTREAM-INVOKE-520E7B",
    }


if __name__ == "__main__":
    arguments = parse_args()
    print(
        json.dumps(
            invoke(load_json(arguments.binding.resolve()), arguments.input.resolve()),
            sort_keys=True,
        )
    )
