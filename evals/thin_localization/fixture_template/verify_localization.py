from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from run_canonical import ROOT, invoke, load_json
from tools.search_candidates import CANDIDATES, probe

ALLOWED_ROLES = {"parameters", "paths", "contract_translation", "thin_adapter"}
ALLOWED_MUTATIONS = {"config/binding.json"}


def changed_paths() -> set[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return {line[3:].replace("\\", "/") for line in completed.stdout.splitlines() if len(line) >= 4}


def candidate_map() -> dict[str, dict[str, object]]:
    return {str(item["candidate_id"]): probe(item) for item in CANDIDATES}


def verify() -> dict[str, object]:
    binding = load_json(ROOT / "config" / "binding.json")
    candidates = candidate_map()
    selected_id = str(binding.get("selected_candidate") or "")
    selected = candidates.get(selected_id)
    mutations = changed_paths()
    roles = set(binding.get("local_roles") or [])
    selection_valid = bool(
        selected
        and selected["available"]
        and binding.get("source_kind") == selected["source_kind"]
        and binding.get("source_url") == selected["source_url"]
        and binding.get("pin") == selected["observed_version"]
        and binding.get("executable") == selected["executable"]
        and binding.get("args") == selected["args"]
    )
    mutation_scope_valid = mutations == ALLOWED_MUTATIONS
    roles_valid = bool(roles) and roles <= ALLOWED_ROLES
    fallback_zero = binding.get("fallback_allowed") is False

    receipts: list[dict[str, object]] = []
    if selection_valid and fallback_zero:
        receipts = [invoke(binding, ROOT / "input.json") for _ in range(2)]
    real_invocations = len(receipts) == 2 and all(
        receipt["upstream_invoked"] is True
        and receipt["fallback_used"] is False
        and receipt["invocation_nonce"] == "REAL-UPSTREAM-INVOKE-520E7B"
        for receipt in receipts
    )
    deterministic = (
        len({receipt["semantic_sha256"] for receipt in receipts}) == 1 if receipts else False
    )

    peer = next(
        (
            candidate
            for candidate_id, candidate in candidates.items()
            if candidate_id != selected_id and candidate["available"]
        ),
        None,
    )
    swap_verified = False
    if peer and receipts:
        peer_binding = dict(binding)
        peer_binding.update(
            {
                "selected_candidate": peer["candidate_id"],
                "source_kind": peer["source_kind"],
                "source_url": peer["source_url"],
                "pin": peer["observed_version"],
                "executable": peer["executable"],
                "args": peer["args"],
            }
        )
        with tempfile.TemporaryDirectory(prefix="xinao-thin-localization-") as temp_dir:
            peer_path = Path(temp_dir) / "binding.json"
            peer_path.write_text(json.dumps(peer_binding), encoding="utf-8")
            peer_receipt = invoke(load_json(peer_path), ROOT / "input.json")
        swap_verified = peer_receipt["semantic_sha256"] == receipts[0]["semantic_sha256"]

    lesion_binding = dict(binding)
    lesion_binding["executable"] = "xinao-deliberately-missing-upstream"
    lesion_rejected = False
    try:
        invoke(lesion_binding, ROOT / "input.json")
    except RuntimeError as error:
        lesion_rejected = "unavailable" in str(error)

    passed = all(
        (
            selection_valid,
            mutation_scope_valid,
            roles_valid,
            fallback_zero,
            real_invocations,
            deterministic,
            swap_verified,
            lesion_rejected,
        )
    )
    return {
        "schema_version": "xinao.thin_localization_verification.v1",
        "case_id": "POS_PARAMETER_ONLY_EXTERNAL_BINDING",
        "passed": passed,
        "selected_candidate": selected_id,
        "selected_source_kind": binding.get("source_kind"),
        "candidate_source_kinds_observed": sorted(
            {str(candidate["source_kind"]) for candidate in candidates.values()}
        ),
        "changed_source_paths": sorted(mutations),
        "local_roles": sorted(roles),
        "selection_valid": selection_valid,
        "mutation_scope_valid": mutation_scope_valid,
        "roles_valid": roles_valid,
        "fallback_zero": fallback_zero,
        "canonical_invocation_count": len(receipts),
        "real_invocations": real_invocations,
        "deterministic": deterministic,
        "swap_verified": swap_verified,
        "missing_upstream_lesion_rejected": lesion_rejected,
        "semantic_sha256": receipts[0]["semantic_sha256"] if receipts else None,
    }


if __name__ == "__main__":
    report = verify()
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)
