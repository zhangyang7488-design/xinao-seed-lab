"""Promptfoo custom Python subject adapter (offline deterministic synthetic).

Rules:
- No vault locator, seed, parameters, truth, answer, family identity, scorer.
- Deterministic synthetic response from public vars only.
- Never reads sealed vault paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


FORBIDDEN_ENV_PREFIXES = (
    "VAULT_",
    "HIDDEN_",
    "SCORER_",
    "TRUTH_",
)


def _deny_env() -> list[str]:
    hits = []
    for k in os.environ:
        up = k.upper()
        if any(up.startswith(p) for p in FORBIDDEN_ENV_PREFIXES):
            hits.append(k)
        if up in {"VAULT_LOCATOR", "EVALUATOR_TOKEN", "SEALED_TRUTH_PATH"}:
            hits.append(k)
    return hits


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Promptfoo python provider entrypoint."""
    del options  # unused; must not carry vault config
    vars_ = {}
    if isinstance(context, dict):
        vars_ = context.get("vars") or {}
    public_case_id = str(vars_.get("public_case_id") or "unknown")
    public_prompt = str(vars_.get("public_prompt") or prompt or "")
    commitment = str(vars_.get("commitment_sha256") or "")

    env_hits = _deny_env()
    if env_hits:
        return {
            "error": f"subject_forbidden_env:{','.join(sorted(env_hits))}",
        }

    # Refuse any attempt to open vault-like paths from env or vars
    for key in ("vault_locator", "vault_path", "sealed_truth_path", "truth", "answer"):
        if key in vars_:
            return {"error": f"subject_forbidden_var:{key}"}

    # Deterministic synthetic subject output (NOT a capability score)
    material = f"{public_case_id}|{public_prompt}|{commitment}|SYNTHETIC_SUBJECT_V1"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    output = {
        "public_case_id": public_case_id,
        "commitment_sha256": commitment,
        "subject_raw": f"SYNTHETIC_ECHO::{digest[:16]}",
        "synthetic": True,
        "label": "SYNTHETIC_FIXTURE_NOT_REAL_CAPABILITY_NOT_ADMISSION_NOT_DISCOVERY",
        "not_admission": True,
        "not_discovery": True,
        "not_rejection_evidence": True,
        "not_capability_result": True,
        "vault_read_attempted": False,
        "scoring_enabled": False,
    }
    return {"output": json.dumps(output, sort_keys=True, separators=(",", ":"))}
