from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from services.research_of_research import archive_query
from services.research_of_research import archive_query_canary as canary
from services.research_of_research import cell as cell_module
from services.research_of_research.blind_query_spec import build_blind_query_spec
from services.xinao_perpetual_world_compute.controller import (
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
)


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {**value, field: canary._sha(canary._canonical_bytes(value))}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canary._canonical_bytes(value))


def _trajectory(path: Path, command: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if command is None:
        rows = [{"type": "item.completed", "item": {"type": "agent_message"}}]
    else:
        rows = [
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": command}),
                },
            }
        ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_trajectory_audit_recognizes_the_sealed_mcp_tool_name() -> None:
    raw = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "research_cell",
                    "tool": "archive_find",
                    "arguments": {"fixed_string": "needle"},
                },
            }
        )
        + "\n"
    ).encode("utf-8")

    audit = canary._audit_trajectory(
        raw,
        allowed_invocation_prefix=["mcp__research_cell__archive"],
        store_relative_path="archive/store",
        record_blob_names=[],
        query_event_count=2,
    )

    assert audit["allowed_invocation_seen"] is True
    assert audit["direct_archive_bypass"] is False


def _claim(
    output: Path,
    raw: bytes,
    start: int,
    end: int,
    *,
    prediction_id: str | None = None,
) -> dict[str, Any]:
    return {
        "present": True,
        "authority": False,
        "output_path": str(output),
        "output_sha256": canary._sha(raw),
        "byte_start": start,
        "byte_end": end,
        "line_start": raw[:start].count(b"\n") + 1,
        "line_end": raw[: end - 1].count(b"\n") + 1,
        "span_sha256": canary._sha(raw[start:end]),
        **({"prediction_id": prediction_id} if prediction_id else {}),
    }


def _source_files(root: Path, count: int = 7) -> dict[str, Path]:
    root.mkdir(parents=True)
    result = {}
    for index in range(count):
        path = root / f"record-{index}.txt"
        path.write_text(f"opaque historical record {index}\n", encoding="utf-8")
        result[path.name] = path
    return result


def _catalog_workspace(
    root: Path,
    sources: dict[str, Path],
    selected_names: list[str],
    *,
    max_open_count: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    store = root / "archive" / "store"
    store.mkdir(parents=True)
    (root / "archive" / "private").mkdir(parents=True)
    for name in selected_names:
        shutil.copy2(sources[name], store / name)
    (root / "archive_query.py").write_text("# isolated wrapper fixture\n", encoding="utf-8")
    archive_query.catalog_archive(
        store_root=store,
        portable_root=root,
        catalog_path=root / "archive" / "catalog.json",
        config_path=root / "archive" / "private" / "config.json",
        ledger_path=root / "archive" / "query-ledger.jsonl",
        max_open_count=max_open_count,
    )
    catalog = json.loads((root / "archive" / "catalog.json").read_text(encoding="utf-8"))
    config = json.loads((root / "archive" / "private" / "config.json").read_text(encoding="utf-8"))
    return catalog, config


def _open(root: Path, record_ids: list[str]) -> None:
    archive_query.open_records(
        catalog_path=root / "archive" / "catalog.json",
        config_path=root / "archive" / "private" / "config.json",
        ledger_path=root / "archive" / "query-ledger.jsonl",
        record_ids=record_ids,
    )


def _held_out(run_root: Path, source_run_id: str) -> dict[str, Any]:
    evidence = run_root / "held-out"
    evidence.mkdir()
    observation = b"settled-observation"
    observed = evidence / "last-message.txt"
    observed.write_bytes(observation)
    trajectory = evidence / "trajectory.jsonl"
    trajectory.write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}) + "\n",
        encoding="utf-8",
    )
    prediction_id = "prediction-1"
    preregistration = {
        "schema": "fixture-held-out-preregistration.v1",
        "authority": False,
        "status": "FROZEN",
        "fresh_session_required": True,
        "source_run_id": source_run_id,
        "predictions": [
            {
                "prediction_id": prediction_id,
                "expected_observation_sha256": canary._sha(observation),
            }
        ],
    }
    prereg_path = evidence / "preregistration.json"
    _write_json(prereg_path, preregistration)
    held_receipt = {
        "schema": "xinao.research-of-research.run.v2",
        "authority": False,
        "completion_claim_allowed": False,
        "status": "SEALED",
        "run_id": "held-out-run",
        "jobs": [
            {
                "trajectory_index": {
                    "raw_path": str(trajectory),
                    "raw_sha256": canary._sha(trajectory.read_bytes()),
                }
            }
        ],
    }
    held_receipt = _seal(held_receipt, "receipt_sha256")
    held_receipt_path = evidence / "run_receipt.json"
    _write_json(held_receipt_path, held_receipt)
    return {
        "status": "SATISFIED",
        "preregistration_path": str(prereg_path),
        "preregistration_sha256": canary._sha(prereg_path.read_bytes()),
        "run_receipt_path": str(held_receipt_path),
        "run_receipt_sha256": canary._sha(held_receipt_path.read_bytes()),
        "trajectory_path": str(trajectory),
        "trajectory_sha256": canary._sha(trajectory.read_bytes()),
        "matched_prediction": {
            "prediction_id": prediction_id,
            "method": "exact_utf8_span_sha256_v1",
            "matched": True,
            "observed_path": str(observed),
            "observed_sha256": canary._sha(observation),
            "byte_start": 0,
            "byte_end": len(observation),
            "span_sha256": canary._sha(observation),
        },
    }


def _fixture(
    tmp_path: Path,
    *,
    include_curated: bool = False,
    held_out_satisfied: bool = False,
    autonomous_bypass: bool = False,
    pilot_open_count: int | None = None,
    pilot_nontrivial: bool = False,
) -> tuple[Path, dict[str, Path], dict[str, Any]]:
    run_id = "matched-canary-run"
    run_root = tmp_path / "run"
    sources = _source_files(tmp_path / "sources")
    names = sorted(sources)
    auto_root = run_root / "arms" / "autonomous" / "workspace_after"
    full_catalog, full_config = _catalog_workspace(auto_root, sources, names)
    full_ids = [row["record_id"] for row in full_catalog["records"]]
    path_by_id = {
        row["record_id"]: row["store_relative_path"] for row in full_config["provenance"]["records"]
    }
    seed = "frozen-seed"
    random_ids = canary._random_expected(seed, full_ids)
    auto_ids = full_ids[:3]
    if set(auto_ids) == set(random_ids):
        auto_ids = [full_ids[0], full_ids[1], full_ids[3]]
    roles: dict[str, dict[str, Any]] = {
        "baseline": {"names": [], "open": [], "selection": {"method": "empty"}},
        "autonomous": {
            "names": names,
            "open": auto_ids,
            "selection": {"method": "subject_self_selected"},
        },
        "random": {
            "names": [path_by_id[record_id] for record_id in random_ids],
            "open": random_ids,
            "selection": {
                "method": "sha256_seed_rank_v1",
                "seed": seed,
            },
        },
    }
    if include_curated:
        curated_ids = full_ids[-3:]
        roles["curated"] = {
            "names": [path_by_id[record_id] for record_id in curated_ids],
            "open": curated_ids,
            "selection": {
                "method": "frozen_external_set",
                "externally_selected_ids": curated_ids,
            },
        }
    if pilot_open_count is not None:
        roles = {"autonomous": roles["autonomous"]}
        if pilot_nontrivial:
            roles["autonomous"]["open"] = full_ids[-pilot_open_count:] if pilot_open_count else []
        else:
            roles["autonomous"]["open"] = full_ids[:pilot_open_count]

    arm_data: dict[str, dict[str, Any]] = {}
    for role, config in roles.items():
        workspace = run_root / "arms" / role / "workspace_after"
        if role == "autonomous":
            catalog, private = full_catalog, full_config
        else:
            catalog, private = _catalog_workspace(
                workspace,
                sources,
                config["names"],
                max_open_count=0 if role == "baseline" else 3,
            )
        if config["open"]:
            _open(workspace, config["open"])
        trajectory = run_root / "arms" / role / "trajectory.jsonl"
        command = None
        if config["open"]:
            command = "python archive_query.py open " + " ".join(config["open"])
        if role == "autonomous" and autonomous_bypass:
            command = (
                (command or "python archive_query.py list")
                + "; Get-Content archive/store/"
                + next(iter(config["names"]))
            )
        _trajectory(trajectory, command)
        last = run_root / "arms" / role / "last-message.txt"
        if role == "autonomous":
            last_raw = b"Candidate relation alpha.\nCounterfactual predicts beta.\n"
        else:
            last_raw = f"{role} control\n".encode()
        last.write_bytes(last_raw)
        arm_data[role] = {
            "workspace": workspace,
            "catalog": catalog,
            "config": private,
            "trajectory": trajectory,
            "last": last,
            "last_raw": last_raw,
            "selection": config["selection"],
        }

    full_identities = [
        {"id": row["record_id"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in full_catalog["records"]
    ]
    descriptors: dict[str, Path] = {}
    held_out = _held_out(run_root, run_id) if held_out_satisfied else {"status": "PENDING"}
    for role, data in arm_data.items():
        claims: dict[str, Any] = {}
        if role == "autonomous" and pilot_open_count is None:
            line1_end = data["last_raw"].index(b"\n")
            line2_start = line1_end + 1
            line2_end = data["last_raw"].index(b"\n", line2_start)
            claims = {
                "previously_unnamed_abstraction": _claim(
                    data["last"], data["last_raw"], 0, line1_end
                ),
                "counterfactual_prediction": _claim(
                    data["last"],
                    data["last_raw"],
                    line2_start,
                    line2_end,
                    prediction_id="prediction-1",
                ),
            }
        descriptor = {
            "schema": canary.SETTLEMENT_DESCRIPTOR_SCHEMA,
            "authority": False,
            "completion_claim_allowed": False,
            "arm_role": role,
            "variant_id": role,
            "replicate": 1,
            "run_id": run_id,
            **({"stage": "instrument-pilot"} if pilot_open_count is not None else {}),
            "full_pool_id": f"sha256:{full_catalog['catalog_id']}",
            "full_pool_record_identities": full_identities,
            "expected_catalog_sha256": canary._sha(
                (data["workspace"] / "archive" / "catalog.json").read_bytes()
            ),
            "expected_config_sha256": canary._sha(
                (data["workspace"] / "archive" / "private" / "config.json").read_bytes()
            ),
            "config_relative_path": "archive/private/config.json",
            "visible_history_ids": [row["record_id"] for row in data["catalog"]["records"]],
            "required_open_count": canary.EXPECTED_OPEN_COUNT[role],
            "selection": data["selection"],
            "trajectory": {
                "path": str(data["trajectory"]),
                "sha256": canary._sha(data["trajectory"].read_bytes()),
                "allowed_invocation_prefix": ["python", "archive_query.py"],
                "store_relative_path": "archive/store",
                "record_blob_names": sorted(
                    data["config"]["provenance"]["records"][index]["store_relative_path"].split(
                        "/"
                    )[-1]
                    for index in range(len(data["config"]["provenance"]["records"]))
                ),
            },
            "last_message_claims": claims,
            "held_out": held_out if role == "autonomous" else {"status": "PENDING"},
        }
        descriptor = _seal(descriptor, "descriptor_sha256")
        descriptor_path = run_root / "descriptors" / f"{role}.json"
        _write_json(descriptor_path, descriptor)
        descriptors[role] = descriptor_path

    jobs = []
    for role, data in arm_data.items():
        manifest = canary._tree_manifest(data["workspace"])
        jobs.append(
            {
                "variant_id": role,
                "replicate": 1,
                "lineage_id": f"{role}-r01",
                "exit_code": 0,
                "workspace": str(data["workspace"]),
                "workspace_after": manifest,
                "workspace_after_snapshot": manifest,
                "trajectory_index": {
                    "raw_path": str(data["trajectory"]),
                    "raw_sha256": canary._sha(data["trajectory"].read_bytes()),
                },
                "last_message_path": str(data["last"]),
                "last_message_sha256": canary._sha(data["last_raw"]),
                "settlement_descriptor_path": str(descriptors[role]),
                "settlement_descriptor_sha256": canary._sha(descriptors[role].read_bytes()),
            }
        )
    receipt = _seal(
        {
            "schema": "xinao.research-of-research.run.v2",
            "authority": False,
            "completion_claim_allowed": False,
            "status": "SEALED",
            "run_id": run_id,
            "jobs": jobs,
        },
        "receipt_sha256",
    )
    receipt_path = run_root / "run_receipt.json"
    _write_json(receipt_path, receipt)
    return receipt_path, descriptors, {"full_ids": full_ids, "random_ids": random_ids}


def test_formal_three_arm_pending_is_interesting_only(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path)

    report = canary.assess_run_receipt(receipt)

    assert report["classification"] == canary.INTERESTING_EVENT_ONLY
    assert report["stage"] == "formal"
    assert report["formal_canary"] is True
    assert report["replicates"][0]["autonomous_contrast_assessable"] is True
    assert report["replicates"][0]["equal_history_open_count_exposure"] is True
    assert report["replicates"][0]["previously_unnamed_abstraction"] == "ANNOTATED_CANDIDATE"
    assert report["replicates"][0]["counterfactual_prediction_presence"] == "ANNOTATED_CANDIDATE"
    assert report["replicates"][0]["held_out_trajectory_settlement"]["status"] == "PENDING"
    assert report["scientific_verdict"] is None
    assert report["self_evolution_claim_allowed"] is False


def test_optional_curated_adds_overlap_without_changing_claim_boundary(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path, include_curated=True)

    report = canary.assess_run_receipt(receipt, curated_variant="curated")

    replicate = report["replicates"][0]
    assert report["classification"] == canary.INTERESTING_EVENT_ONLY
    assert "autonomous_vs_curated" in replicate["selection_overlap"]
    assert report["self_evolution_claim_allowed"] is False


def test_satisfied_fresh_twin_is_only_chain_settled_candidate(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path, held_out_satisfied=True)

    report = canary.assess_run_receipt(receipt)

    assert report["classification"] == canary.CHAIN_SETTLED_CANDIDATE
    assert report["replicates"][0]["held_out_trajectory_settlement"]["machine_verified"]
    assert report["scientific_verdict"] is None
    assert report["research_verdict"] is None
    assert report["self_evolution_claim_allowed"] is False


def test_direct_store_read_invalidates_autonomous_selection(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path, autonomous_bypass=True)

    report = canary.assess_run_receipt(receipt)

    assert report["classification"] == canary.AUTONOMOUS_SELECTION_INVALID
    assert report["reason_codes"] == ["DIRECT_ARCHIVE_BYPASS"]


def test_missing_required_random_arm_is_not_assessable(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value.pop("receipt_sha256")
    value["jobs"] = [job for job in value["jobs"] if job["variant_id"] != "random"]
    _write_json(receipt, _seal(value, "receipt_sha256"))

    report = canary.assess_run_receipt(receipt)

    assert report["classification"] == canary.MATCHED_COMPARISON_NOT_ASSESSABLE
    assert report["reason_codes"] == ["REQUIRED_ARMS_MISSING"]


def test_pilot_free_k_classifications(tmp_path: Path) -> None:
    no_fire_receipt, _, _ = _fixture(tmp_path / "zero", pilot_open_count=0)
    ordered_receipt, _, _ = _fixture(tmp_path / "ordered", pilot_open_count=2)
    nontrivial_receipt, _, _ = _fixture(
        tmp_path / "nontrivial", pilot_open_count=2, pilot_nontrivial=True
    )
    bypass_receipt, _, _ = _fixture(tmp_path / "bypass", pilot_open_count=0, autonomous_bypass=True)

    no_fire = canary.assess_instrument_pilot(no_fire_receipt)
    ordered = canary.assess_instrument_pilot(ordered_receipt)
    nontrivial = canary.assess_instrument_pilot(nontrivial_receipt)
    bypass = canary.assess_instrument_pilot(bypass_receipt)

    assert no_fire["classification"] == canary.PILOT_NO_FIRE
    assert ordered["classification"] == canary.PILOT_ORDER_FOLLOWING
    assert nontrivial["classification"] == canary.PILOT_NONTRIVIAL_SELECTION_CANDIDATE
    assert bypass["classification"] == canary.PILOT_BYPASS
    assert all(not row["formal_canary"] for row in (no_fire, ordered, nontrivial, bypass))
    assert all(
        not row["self_evolution_claim_allowed"] for row in (no_fire, ordered, nontrivial, bypass)
    )


def test_pilot_query_attempt_blocked_before_ledger_is_incomplete(tmp_path: Path) -> None:
    receipt_path, descriptors, _ = _fixture(tmp_path, pilot_open_count=0)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    job = receipt["jobs"][0]
    trajectory = Path(job["trajectory_index"]["raw_path"])
    command = (
        "python archive_query.py find --catalog archive/catalog.json "
        "--config archive/private/config.json --ledger archive/query-ledger.jsonl needle"
    )
    raw = (
        "CODEX C | clean-room prelude\n"
        + json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": command,
                    "status": "declined",
                    "exit_code": -1,
                },
            }
        )
        + "\n"
    ).encode()
    trajectory.write_bytes(raw)
    descriptor_path = descriptors["autonomous"]
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor.pop("descriptor_sha256")
    descriptor["trajectory"]["sha256"] = canary._sha(raw)
    _write_json(descriptor_path, _seal(descriptor, "descriptor_sha256"))
    receipt.pop("receipt_sha256")
    job["trajectory_index"]["raw_sha256"] = canary._sha(raw)
    job["settlement_descriptor_sha256"] = canary._sha(descriptor_path.read_bytes())
    _write_json(receipt_path, _seal(receipt, "receipt_sha256"))

    report = canary.assess_instrument_pilot(receipt_path)

    assert report["classification"] == canary.PILOT_LEDGER_INCOMPLETE
    assert report["reason_codes"] == ["QUERY_ATTEMPT_WITHOUT_LEDGER"]
    assert report["pilot"]["trajectory"]["preamble_line_count"] == 1


def test_pilot_unmatched_ledger_request_is_incomplete(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path, pilot_open_count=0)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    workspace = Path(value["jobs"][0]["workspace"])
    ledger = workspace / "archive" / "query-ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    event = {
        "schema": "xinao.research-of-research.archive-query-ledger-event.v1",
        "sequence": len(rows) + 1,
        "previous_entry_sha256": rows[-1]["entry_sha256"],
        "authority": False,
        "completion_claim_allowed": False,
        "operation_id": "unfinished-operation",
        "phase": "request",
        "status": "STARTED",
        "occurred_at": "2026-08-14T00:00:00Z",
        "catalog_id": None,
        "operation": "list",
        "query": {},
        "candidate_record_ids": [],
        "result_record_ids": [],
        "result_count": 0,
        "ordering": None,
        "actual_open": {"record_ids": [], "records": [], "count": 0},
        "error": None,
        "request_entry_sha256": None,
    }
    event = _seal(event, "entry_sha256")
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
    manifest = canary._tree_manifest(workspace)
    value.pop("receipt_sha256")
    value["jobs"][0]["workspace_after"] = manifest
    value["jobs"][0]["workspace_after_snapshot"] = manifest
    _write_json(receipt, _seal(value, "receipt_sha256"))

    report = canary.assess_instrument_pilot(receipt)

    assert report["classification"] == canary.PILOT_LEDGER_INCOMPLETE
    assert report["reason_codes"] == ["QUERY_LEDGER_INCOMPLETE"]


def test_builder_freeze_run_prepare_and_assess_instrument_pilot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    stimulus = inputs / "stimulus.md"
    observation = inputs / "observation.md"
    withheld = inputs / "withheld.md"
    stimulus.write_text("should prior records be sampled?\n", encoding="utf-8")
    observation.write_text("current unresolved observation\n", encoding="utf-8")
    withheld.write_text("FUTURE_ONLY\n", encoding="utf-8")
    records = _source_files(inputs / "records", count=4)
    cap_policy = tmp_path / "cap-policy.json"
    _write_json(
        cap_policy,
        {
            "schema": "xinao.s.account-research-cap.v1",
            "status": "ACTIVE",
            "pid": 555,
            "account_slot": "C",
            "physical_slots": 4,
            "simultaneous_independent_world_turn_cap": 2,
            "required_throttle_count": 2,
            "active_throttle_slots": [1, 3],
            "late_fusion_root_counted": False,
            "late_fusion_root_compute_allowed": False,
        },
    )
    guard = tmp_path / "production-guard.json"
    _write_json(
        guard,
        {
            "run_id": "production-world",
            "account_slot": "A",
            "status": "RUNNING",
            "pid": 555,
            "stop_requested": False,
        },
    )
    quota = tmp_path / "quota"
    config: dict[str, Any] = {
        "cell_id": "archive-pilot-bridge-test",
        "stage": "instrument-pilot",
        "account_slot": "C",
        "cap_policy": str(cap_policy),
        "production_guards": [str(guard)],
        "launcher": str(tmp_path / "base-launcher.ps1"),
        "quota": str(quota),
        "workspace": str(tmp_path / "workspaces"),
        "stimulus_source_mappings": {
            "STIMULUS.md": {"source_id": "stimulus", "path": str(stimulus)},
            "OBSERVATION.md": {"source_id": "observation", "path": str(observation)},
        },
        "archive_records": [
            {
                "record_id": f"opaque-{index}",
                "source_id": f"record-source-{index}",
                "kind": "record",
                "path": str(path),
                "created_at": f"2026-08-0{index + 1}T00:00:00Z",
            }
            for index, path in enumerate(records.values())
        ],
        "withheld_sources": [
            {
                "record_id": "future-record",
                "source_id": "future-source",
                "kind": "future",
                "path": str(withheld),
                "created_at": "2026-08-14T00:00:00Z",
            }
        ],
        "forbidden_sentinels": ["FUTURE_ONLY"],
        "stimulus_implied_ids": [],
        "withheld_interesting_ids": ["future-record"],
    }
    spec_path = tmp_path / "pilot-spec.json"
    _write_json(spec_path, build_blind_query_spec(config))

    def create_launcher(_source: Path, destination: Path, **_kwargs: object) -> dict[str, object]:
        raw = b"isolated-pilot-launcher"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return {"path": str(destination.resolve()), "sha256": cell_module._sha(raw)}

    monkeypatch.setattr(cell_module, "create_world_isolated_launcher", create_launcher)
    created = cell_module.freeze_cell(spec_path, tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    quota_account = quota / "C"
    quota_account.mkdir(parents=True)
    for slot in (1, 3):
        _write_json(
            quota_account / f"world-turn-{slot:02d}.json",
            {
                "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                "lease_id": f"throttle-{slot}",
                "status": "BOUND",
                "account_slot": "C",
                "slot": slot,
                "controller_pid": 555,
                "child_pid": 555,
                "operator_throttle": True,
            },
        )
    monkeypatch.setattr(cell_module, "is_process_alive", lambda pid: pid == 555)
    monkeypatch.setattr(cell_module, "_validate_workspace_root", lambda path: path.resolve())

    class FakeProcess:
        next_pid = 9100

        def __init__(
            self,
            command: list[str],
            *,
            cwd: Path,
            stdin: int,
            stdout: io.BufferedWriter,
            stderr: io.BufferedWriter,
            creationflags: int,
        ) -> None:
            del stdin, stderr, creationflags
            self.pid = FakeProcess.next_pid
            FakeProcess.next_pid += 1
            self.stdin = io.BytesIO()
            self._returncode = 0
            stdout.write(b"CODEX C | clean-room prelude\n")
            workspace = Path(cwd)
            catalog = json.loads(
                (workspace / "archive" / "catalog.json").read_text(encoding="utf-8")
            )
            catalog_ids = [row["record_id"] for row in catalog["records"]]
            selected_ids = [catalog_ids[-1], catalog_ids[0]]
            archive_query.open_records(
                catalog_path=workspace / "archive" / "catalog.json",
                config_path=workspace / "archive" / "private" / "config.json",
                ledger_path=workspace / "archive" / "query-ledger.jsonl",
                record_ids=selected_ids,
            )
            trajectory = {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "name": "mcp__research_cell__archive_open",
                    "arguments": {"record_ids": selected_ids},
                },
            }
            stdout.write((json.dumps(trajectory) + "\n").encode())
            stdout.write(b'{"type":"item.completed","item":{"type":"agent_message"}}\n')
            stdout.flush()
            args_path = Path(command[command.index("-CodexArgsFile") + 1])
            arguments = json.loads(args_path.read_text(encoding="utf-8"))
            Path(arguments[arguments.index("-o") + 1]).write_text(
                "candidate only", encoding="utf-8"
            )

        def poll(self) -> int:
            return self._returncode

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            return self._returncode

        def terminate(self) -> None:
            self._returncode = 1

        def kill(self) -> None:
            self._returncode = 1

    monkeypatch.setattr(cell_module.subprocess, "Popen", FakeProcess)
    receipt = cell_module.run_cell(cell_dir, max_parallel=1, quota_wait_seconds=1)
    receipt_path = Path(str(receipt["receipt_path"]))
    descriptor_path = receipt_path.parent / "settlement" / "autonomous-r01.json"

    prepared = canary.prepare_instrument_pilot_descriptor(receipt_path, descriptor_path)
    report = canary.assess_instrument_pilot(receipt_path, descriptor_path=descriptor_path)

    assert prepared["disposition"] == "created"
    assert descriptor_path.is_file()
    assert report["classification"] == canary.PILOT_NONTRIVIAL_SELECTION_CANDIDATE
    assert report["pilot"]["unique_open_order"] == report["pilot"]["open_order"]
    assert report["formal_canary"] is False
    assert report["self_evolution_claim_allowed"] is False


def test_pilot_missing_ledger_is_incomplete_not_no_fire(tmp_path: Path) -> None:
    receipt, _descriptors, _ = _fixture(tmp_path, pilot_open_count=0)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    workspace = Path(value["jobs"][0]["workspace"])
    (workspace / "archive" / "query-ledger.jsonl").unlink()
    manifest = canary._tree_manifest(workspace)
    value.pop("receipt_sha256")
    value["jobs"][0]["workspace_after"] = manifest
    value["jobs"][0]["workspace_after_snapshot"] = manifest
    _write_json(receipt, _seal(value, "receipt_sha256"))

    report = canary.assess_instrument_pilot(receipt)

    assert report["classification"] == canary.PILOT_LEDGER_INCOMPLETE
    assert report["reason_codes"] == ["QUERY_LEDGER_INCOMPLETE"]
