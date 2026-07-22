"""Run one real-identity H03/H04/H10 hidden benchmark vertical slice.

The runner intentionally keeps one process boundary between public-only subject
execution and private offline scoring.  Secret bytes exist only in the owner/custodian
process and are never passed to Promptfoo or the scorer subprocess.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
SEAM_ROOT = REPO_ROOT / "projects" / "g4-hidden-capability-seam"
SEAM_SRC = SEAM_ROOT / "src"
for source_root in (str(XINAO_SRC), str(SEAM_SRC)):
    if source_root not in sys.path:
        sys.path.insert(0, source_root)

from g4_hidden_capability_seam.canonical import (  # noqa: E402
    raw_bytes_sha256_file,
    write_json,
)
from g4_hidden_capability_seam.promptfoo_runner import (  # noqa: E402
    PROMPTFOO_OUTPUT_BASENAME,
    build_promptfoo_config,
    default_denied_roots,
    run_promptfoo_offline,
)
from g4_hidden_capability_seam.real_vault import (  # noqa: E402
    RealHiddenBootstrapVault,
)
from g4_hidden_capability_seam.vault import EVALUATOR_CAP  # noqa: E402
from xinao.canonical import canonical_sha256  # noqa: E402
from xinao.capability.g4_bootstrap_scoring import (  # noqa: E402
    BOOTSTRAP_FAMILIES,
    TERMINAL_FAIL,
    TERMINAL_PASS,
    score_bootstrap,
)
from xinao.capability.g4_hidden_benchmark import (  # noqa: E402
    GeneratorProfile,
    generate_full_family_suites,
)
from xinao.capability.g4_hidden_benchmark.public_safety import (  # noqa: E402
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)


def _private_records(result: Any) -> list[dict[str, Any]]:
    return [record.as_private_dict() for record in result.heldout_private_bundle.records]


def _selected_records(result: Any) -> list[dict[str, Any]]:
    selected = [
        record
        for record in _private_records(result)
        if record.get("family_id") in BOOTSTRAP_FAMILIES
    ]
    if [record["family_id"] for record in selected] != list(BOOTSTRAP_FAMILIES):
        raise RuntimeError("bootstrap_family_selection_not_exact")
    return selected


def _public_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "public_case_id": record["public_case_id"],
        "public_instructions": record["public_instructions"],
        "task_input": record["task_input"],
        "commitment_sha256": record["commitment_sha256"],
    }


def _verify_public_boundary(records: list[dict[str, Any]]) -> dict[str, Any]:
    problems: list[str] = []
    for record in records:
        payload = _public_payload(record)
        family = str(record["family_id"])
        forbidden = scan_forbidden_public_keys(payload)
        if forbidden:
            problems.append(f"forbidden_public_keys:{family}:{forbidden}")
        if family == "H03":
            hints = scan_h03_public_hints(payload)
            if hints:
                problems.append(f"h03_public_hints:{hints}")
        if family == "H04":
            hints = scan_h04_public_hints(payload)
            if hints:
                problems.append(f"h04_public_hints:{hints}")
    return {"ok": not problems, "problems": problems, "case_count": len(records)}


def _materialize_public_cases(records: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for record in records:
        public_payload = _public_payload(record)
        rows.append(
            json.dumps(
                {
                    "public_case_id": record["public_case_id"],
                    "public_prompt": json.dumps(
                        public_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    "commitment_sha256": record["commitment_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    digest, size = raw_bytes_sha256_file(path)
    return {"path": str(path), "sha256": digest, "bytes": size, "case_count": len(rows)}


def _score_in_subprocess(
    *, vault_root: Path, promptfoo_output: Path, report_path: Path
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        "--score-only",
        "--vault-root",
        str(vault_root),
        "--promptfoo-output",
        str(promptfoo_output),
        "--report-path",
        str(report_path),
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        shell=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
        },
    )
    return {
        "ok": process.returncode == 0 and report_path.is_file(),
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-1000:],
        "stderr_tail": process.stderr[-1000:],
        "report_path": str(report_path),
    }


def score_only(*, vault_root: Path, promptfoo_output: Path, report_path: Path) -> int:
    vault = RealHiddenBootstrapVault(vault_root)
    locked = vault.verify_locked_phase(expected_receipt=True)
    if locked.get("ok") is not True:
        write_json(
            report_path,
            {
                "schema_version": "xinao.g4.bootstrap.offline_score_report.v1",
                "terminal": TERMINAL_FAIL,
                "pipeline_verified": False,
                "capability_bootstrap_pass": False,
                "problems": ["vault_lock_not_verified"],
                "authority": False,
                "g4_closed": False,
            },
        )
        return 2
    private = vault.evaluator_bundle(capability=EVALUATOR_CAP)
    if private.get("ok") is not True:
        return 3
    try:
        promptfoo_result = json.loads(promptfoo_output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 4
    suite_identity = private.get("suite_identity") or {}
    generator_artifact = private.get("generator_artifact") or {}
    report = score_bootstrap(
        evaluator_records=private["records"],
        promptfoo_result=promptfoo_result,
        suite_identity_sha256=str(suite_identity.get("identity_sha256") or ""),
        generator_artifact_sha256=str(generator_artifact.get("artifact_sha256") or ""),
    )
    write_json(report_path, report)
    return 0 if report.get("pipeline_verified") is True else 5


def _materialize_adapter_snapshot(*, package_root: Path) -> dict[str, Any]:
    source = SEAM_ROOT / "adapters" / "promptfoo_c0_bootstrap_adapter.py"
    target = package_root / "adapters" / source.name
    raw = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if target.read_bytes() != raw:
            return {
                "ok": False,
                "reason": "adapter_snapshot_already_exists_with_different_bytes",
                "path": str(target),
            }
    sha256, size = raw_bytes_sha256_file(target)
    return {"ok": True, "path": str(target), "sha256": sha256, "bytes": size}


def _fail_run(op_root: Path, *, phase: str, **detail: Any) -> dict[str, Any]:
    failure: dict[str, Any] = {
        "schema_version": "xinao.g4.vertical_bootstrap.failure_receipt.v1",
        "ok": False,
        "phase": phase,
        **detail,
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "admission_closed": False,
        "parent_complete": False,
    }
    failure["content_hash"] = canonical_sha256(failure)
    path = op_root / "failure_receipt.v1.json"
    write_json(path, failure)
    failure["failure_receipt_path"] = str(path)
    return failure


def run_bootstrap_once(
    *, result: Any, op_root: Path, run_id: str, adapter_snapshot: dict[str, Any]
) -> dict[str, Any]:
    if op_root.exists() and any(op_root.iterdir()):
        return {"ok": False, "phase": "op_root", "reason": "op_root_not_empty"}
    op_root.mkdir(parents=True, exist_ok=True)
    if adapter_snapshot.get("ok") is not True:
        return _fail_run(
            op_root,
            phase="adapter_snapshot",
            detail=adapter_snapshot,
        )
    records = _selected_records(result)
    public_boundary = _verify_public_boundary(records)
    if public_boundary.get("ok") is not True:
        return _fail_run(op_root, phase="public_boundary", detail=public_boundary)

    vault_root = op_root / "vault"
    vault = RealHiddenBootstrapVault(vault_root)
    selected_ids = [str(record["public_case_id"]) for record in records]
    deposit = vault.deposit_private_bundle(
        private_bundle=result.heldout_private_bundle.as_private_dict(),
        suite_identity=result.heldout_identity.as_dict(),
        generator_artifact=result.generator_artifact.as_dict(),
        selected_case_ids=selected_ids,
    )
    if deposit.get("ok") is not True:
        return _fail_run(op_root, phase="custodian_deposit", detail=deposit)

    public_cases = _materialize_public_cases(records, op_root / "public" / "cases.jsonl")
    lockdown = vault.lock_down_host_reads(expected_receipt=False)
    if lockdown.get("ok") is not True:
        return _fail_run(op_root, phase="vault_lockdown", detail=lockdown)
    lockdown_receipt = {
        "schema_version": "xinao.g4.bootstrap.vault_lockdown_receipt.v1",
        "suite_identity_sha256": result.heldout_identity.identity_sha256,
        "generator_artifact_sha256": result.generator_artifact.artifact_sha256,
        "selected_case_ids_sha256": canonical_sha256(selected_ids),
        "target_set_exact": lockdown.get("target_set_exact") is True,
        "isolation_enforced": lockdown.get("isolation_enforced") is True,
        "content_recorded": False,
        "authority": False,
        "g4_closed": False,
    }
    published = vault.publish_lockdown_receipt(lockdown_receipt)
    if published.get("ok") is not True:
        return _fail_run(op_root, phase="vault_receipt_seal", detail=published)

    promptfoo_root = op_root / "promptfoo"
    adapter_path = Path(str(adapter_snapshot["path"]))
    config = build_promptfoo_config(
        config_dir=promptfoo_root / "config",
        adapter_path=adapter_path,
        cases_path=Path(public_cases["path"]),
    )
    adapter_sha256, adapter_size = raw_bytes_sha256_file(adapter_path)
    promptfoo_state = promptfoo_root / "state"
    promptfoo_output = promptfoo_root / "output" / PROMPTFOO_OUTPUT_BASENAME
    allowed_roots = [Path(config["config_path"]).parent, promptfoo_state, promptfoo_output.parent]
    denied_roots = default_denied_roots(
        vault_root=vault_root,
        evaluator_root=op_root / "evaluator",
        op_root=op_root,
    )
    with vault.hold_verified_locked_phase(expected_receipt=True) as live_lock:
        if live_lock.get("ok") is not True:
            return _fail_run(op_root, phase="vault_live_lock", detail=live_lock)
        runner = run_promptfoo_offline(
            config_path=Path(config["config_path"]),
            state_root=promptfoo_state,
            output_path=promptfoo_output,
            adapter_host_path=adapter_path,
            expected_adapter_sha256=adapter_sha256,
            timeout_s=180,
            run_id=run_id,
            package_owner="g4_vertical_bootstrap_v1",
            op_root=op_root,
            vault_root=vault_root,
            evaluator_root=op_root / "evaluator",
            allowed_roots=allowed_roots,
            denied_roots=denied_roots,
            expected_case_ids=selected_ids,
            expected_config_sha256=str(config["config_sha256"]),
            expected_cases_sha256=str(config["cases_sha256"]),
        )
    if runner.get("ok") is not True:
        return _fail_run(
            op_root,
            phase="public_subject_runner",
            runner=runner,
        )

    evaluator_root = op_root / "evaluator"
    evaluator_root.mkdir(parents=True, exist_ok=True)
    score_path = evaluator_root / "offline_score_report.v1.json"
    scorer_process = _score_in_subprocess(
        vault_root=vault_root,
        promptfoo_output=promptfoo_output,
        report_path=score_path,
    )
    if scorer_process.get("ok") is not True:
        return _fail_run(
            op_root,
            phase="independent_offline_scorer",
            scorer_process=scorer_process,
        )
    score_report = json.loads(score_path.read_text(encoding="utf-8"))
    output_sha256, output_size = raw_bytes_sha256_file(promptfoo_output)
    score_sha256, score_size = raw_bytes_sha256_file(score_path)
    runner_receipt_path = promptfoo_state / "promptfoo_run_receipt.v1.json"
    runner_receipt_sha256, runner_receipt_size = raw_bytes_sha256_file(runner_receipt_path)
    promptfoo_identity = runner.get("promptfoo_identity") or {}
    receipt = {
        "schema_version": "xinao.g4.vertical_bootstrap.execution_receipt.v1",
        "terminal": score_report["terminal"],
        "pipeline_verified": score_report.get("pipeline_verified") is True,
        "capability_bootstrap_pass": score_report.get("capability_bootstrap_pass") is True,
        "run_id": run_id,
        "suite_identity_sha256": result.heldout_identity.identity_sha256,
        "generator_artifact_sha256": result.generator_artifact.artifact_sha256,
        "public_cases": public_cases,
        "adapter": {"sha256": adapter_sha256, "bytes": adapter_size},
        "promptfoo": {
            "version": promptfoo_identity.get("version"),
            "image_ref": promptfoo_identity.get("image_ref"),
            "image_id": promptfoo_identity.get("image_id"),
            "image_platform_manifest_sha256": promptfoo_identity.get(
                "image_platform_manifest_sha256"
            ),
            "network_mode": runner.get("network_mode"),
            "offline_enforced": runner.get("offline_enforced"),
            "case_count": (runner.get("result_parse") or {}).get("observed_count"),
            "config_sha256": runner.get("promptfoo_config_sha256"),
            "materialized_cases_sha256": runner.get("promptfoo_public_cases_sha256"),
            "raw_output_sha256": output_sha256,
            "raw_output_bytes": output_size,
            "runner_receipt_sha256": runner_receipt_sha256,
            "runner_receipt_bytes": runner_receipt_size,
            "synthetic_guard_surface_reused": True,
            "runner_alone_is_not_capability_evidence": True,
        },
        "scorer": {
            "process": scorer_process,
            "report_sha256": score_sha256,
            "report_bytes": score_size,
            "subject_outputs_sha256": score_report.get("subject_outputs_sha256"),
            "mandatory_family_results": score_report.get("mandatory_family_results"),
        },
        "vault": {
            "deposit": deposit,
            "lockdown_target_set_exact": lockdown.get("target_set_exact") is True,
            "receipt_resealed": published.get("receipt_resealed") is True,
            "subject_readable": False,
        },
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "admission_closed": False,
        "parent_complete": False,
    }
    receipt["content_hash"] = canonical_sha256(receipt)
    receipt_path = op_root / "execution_receipt.v1.json"
    write_json(receipt_path, receipt)
    receipt_sha256, receipt_size = raw_bytes_sha256_file(receipt_path)
    return {
        "ok": receipt["pipeline_verified"],
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "receipt_bytes": receipt_size,
    }


def run_vertical_bootstrap(*, op_root: Path, repeat_count: int = 2) -> dict[str, Any]:
    if repeat_count < 2:
        raise ValueError("repeat_count_must_be_at_least_two")
    adapter_snapshot = _materialize_adapter_snapshot(package_root=op_root)
    training_secret = secrets.token_bytes(32)
    heldout_secret = secrets.token_bytes(32)
    result = generate_full_family_suites(
        training_secret=training_secret,
        heldout_secret=heldout_secret,
        profile=GeneratorProfile(cases_per_family=1),
    )
    runs = [
        run_bootstrap_once(
            result=result,
            op_root=op_root / "ops" / f"run_{index + 1}",
            run_id=f"run_{index + 1}",
            adapter_snapshot=adapter_snapshot,
        )
        for index in range(repeat_count)
    ]
    successful = all(run.get("ok") is True for run in runs)
    receipts = [run.get("receipt") or {} for run in runs]
    output_hashes = [
        (receipt.get("scorer") or {}).get("subject_outputs_sha256") for receipt in receipts
    ]
    deterministic = bool(
        output_hashes and None not in output_hashes and len(set(output_hashes)) == 1
    )
    capability_pass = successful and all(
        receipt.get("capability_bootstrap_pass") is True for receipt in receipts
    )
    terminal = TERMINAL_PASS if capability_pass else TERMINAL_FAIL
    summary: dict[str, Any] = {
        "schema_version": "xinao.g4.vertical_bootstrap.repeat_summary.v1",
        "terminal": terminal,
        "pipeline_verified": successful and deterministic,
        "capability_bootstrap_pass": capability_pass,
        "repeat_count": repeat_count,
        "fixed_input_subject_outputs_deterministic": deterministic,
        "subject_outputs_sha256": output_hashes[0] if deterministic else None,
        "generator_artifact_sha256": result.generator_artifact.artifact_sha256,
        "training_identity_sha256": result.training_identity.identity_sha256,
        "heldout_identity_sha256": result.heldout_identity.identity_sha256,
        "non_collision_attestation_sha256": result.non_collision_attestation.attestation_sha256,
        "run_receipts": [run.get("receipt_path") for run in runs],
        "run_receipt_sha256s": [run.get("receipt_sha256") for run in runs],
        "failure_receipts": [
            run.get("failure_receipt_path") for run in runs if run.get("ok") is not True
        ],
        "failed_phases": [run.get("phase") for run in runs if run.get("ok") is not True],
        "authority": False,
        "g4_full": False,
        "g4_closed": False,
        "g5_closed": False,
        "admission_closed": False,
        "parent_complete": False,
    }
    summary["content_hash"] = canonical_sha256(summary)
    write_json(op_root / "repeat_summary.v1.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--op-root", type=Path)
    parser.add_argument("--repeat-count", type=int, default=2)
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument("--promptfoo-output", type=Path)
    parser.add_argument("--report-path", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.score_only:
        if args.vault_root is None or args.promptfoo_output is None or args.report_path is None:
            raise SystemExit("score-only requires vault/output/report paths")
        return score_only(
            vault_root=args.vault_root,
            promptfoo_output=args.promptfoo_output,
            report_path=args.report_path,
        )
    if args.op_root is None:
        raise SystemExit("--op-root is required")
    root = args.op_root.resolve()
    allowed = Path(r"D:\XINAO_RESEARCH_RUNTIME").resolve()
    try:
        root.relative_to(allowed)
    except ValueError as exc:
        raise SystemExit("op root must remain under D:\\XINAO_RESEARCH_RUNTIME") from exc
    if root.exists() and any(root.iterdir()):
        raise SystemExit("op root must be new or empty")
    summary = run_vertical_bootstrap(op_root=root, repeat_count=args.repeat_count)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary.get("pipeline_verified") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
