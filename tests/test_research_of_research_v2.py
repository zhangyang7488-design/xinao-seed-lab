from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from services.research_of_research import cell as cell_module
from services.research_of_research.cell import (
    CELL_SPEC_SCHEMA,
    ResearchCellError,
    freeze_cell,
    run_cell,
    verify_cell,
)
from services.xinao_perpetual_world_compute.controller import (
    WORLD_TURN_QUOTA_LEASE_SCHEMA,
)


def _write_v2_spec(tmp_path: Path) -> Path:
    episode = tmp_path / "episode.txt"
    episode.write_text(
        "COMMON WORLD\nOLD ACTION PATH\nHUMAN CORRECTION\nEXPLICITLY SUPERSEDED\n"
        "DERIVED SUMMARY\nFUTURE_SENTINEL\n",
        encoding="utf-8",
    )
    cap_policy = tmp_path / "cap-policy.json"
    cap_policy.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )
    guard = tmp_path / "production-guard.json"
    guard.write_text(
        json.dumps(
            {
                "run_id": "production-world",
                "account_slot": "A",
                "status": "RUNNING",
                "pid": 555,
                "stop_requested": False,
            }
        ),
        encoding="utf-8",
    )
    sources = []
    declarations = (
        ("common-world", 1, "raw", "model_visible", 1, []),
        ("old-action-path", 2, "raw", "model_visible", 2, []),
        ("human-correction", 3, "raw_human", "model_visible", 3, []),
        ("explicit-supersession", 4, "raw_human", "model_visible", 4, []),
        ("derived-summary", 5, "derived", "evidence_only", 5, ["human-correction"]),
        ("future-settlement", 6, "raw", "future_settlement", 6, []),
    )
    for source_id, line, provenance, visibility, chronology, derived_from in declarations:
        sources.append(
            {
                "id": source_id,
                "role": "historical-event",
                "visibility": visibility,
                "known_at": f"event-{chronology}",
                "chronology_index": chronology,
                "provenance_kind": provenance,
                "derived_from": derived_from,
                "material": {
                    "kind": "line_slice",
                    "path": str(episode),
                    "start_line": line,
                    "end_line": line,
                },
            }
        )
    variants = [
        {
            "id": "direct-old-visible",
            "factor_assignments": {"revision_path": "direct", "old_plan": "visible"},
            "view": ["common-world", "human-correction"],
        },
        {
            "id": "path-old-visible",
            "factor_assignments": {"revision_path": "real", "old_plan": "visible"},
            "view": ["common-world", "old-action-path", "human-correction"],
        },
        {
            "id": "path-old-absent",
            "factor_assignments": {"revision_path": "real", "old_plan": "absent"},
            "view": ["common-world", "human-correction"],
            "workspace_remove": ["OLD_PLAN.md"],
        },
        {
            "id": "path-old-superseded",
            "factor_assignments": {"revision_path": "real", "old_plan": "superseded"},
            "view": [
                "common-world",
                "old-action-path",
                "human-correction",
                "explicit-supersession",
            ],
        },
    ]
    spec = {
        "schema": CELL_SPEC_SCHEMA,
        "cell_id": "revision-path-v2-test",
        "question": "When does the old action cone stop controlling the next action?",
        "episode": {
            "replay_fidelity": "PARTIAL",
            "known_gaps": ["hidden reasoning and exact dirty tree are unavailable"],
            "cutoff": "after the explicit supersession event",
            "cutoff_index": 5,
            "sources": sources,
        },
        "intervention": {
            "common_view": [],
            "terminal_contract": {
                "kind": "literal",
                "text": "Act in the isolated fixture. Do not merely explain.",
            },
            "held_constants": ["model", "tools", "budget", "terminal contract"],
            "intervention_variables": ["revision_path", "old_plan"],
            "known_confounders": ["partial historical workspace reconstruction"],
            "variants": variants,
        },
        "hypotheses": [
            {"id": "h-terminal", "prediction": "The terminal correction alone switches action."},
            {"id": "h-path", "prediction": "The revision path and old-plan visibility matter."},
        ],
        "observables": {
            "old_action_cone_paths": ["OLD_CONE.md"],
            "new_action_cone_paths": ["NEW_CONE.md"],
        },
        "forbidden_future_sentinels": ["FUTURE_SENTINEL"],
        "production_guards": [str(guard)],
        "harness": {
            "account_slot": "C",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "max",
            "launcher": str(tmp_path / "base-launcher.ps1"),
            "workspace_files": {
                "AGENTS.md": "Isolated historical replay fixture. Follow only the supplied view.\n",
                "OLD_PLAN.md": "historical old action cone\n",
            },
            "world_turn_quota_root": str(tmp_path / "quota"),
            "workspace_root": str(tmp_path / "workspaces"),
            "account_research_cap_policy": str(cap_policy),
            "max_account_research_turns": 2,
            "physical_world_turn_slots": 4,
            "root_main_compute_allowed": False,
            "turn_timeout_seconds": 10,
        },
    }
    path = tmp_path / "spec-v2.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def fake_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    def create(_source: Path, destination: Path, **_kwargs: object) -> dict[str, object]:
        raw = b"isolated-v2-launcher"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return {"path": str(destination.resolve()), "sha256": cell_module._sha(raw)}

    monkeypatch.setattr(cell_module, "create_world_isolated_launcher", create)


def test_v2_freeze_builds_four_bound_consumers(tmp_path: Path, fake_launcher: None) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    source_map = json.loads((cell_dir / "source_map.json").read_text(encoding="utf-8"))

    assert created["verification"]["ok"] is True
    assert source_map["schema"].endswith("source-map.v2")
    assert Path(source_map["raw_archive_manifest"]["path"]).is_file()
    assert Path(source_map["episode_reconstruction"]["path"]).is_file()
    assert Path(source_map["replay_twin"]["path"]).is_file()
    assert len(source_map["contrast_views"]) == 4
    assert {
        row["terminal_contract_sha256"]
        for row in (
            json.loads(Path(item["contrast_view_path"]).read_text(encoding="utf-8"))
            for item in source_map["variants"]
        )
    } == {source_map["terminal_contract"]["sha256"]}
    for source in source_map["sources"]:
        assert Path(source["archive_path"]).name == f"{source['archive_sha256']}.bin"
        assert (
            Path(source["sealed_copy_path"]).read_bytes()
            == Path(source["archive_path"]).read_bytes()
        )
    for variant in source_map["variants"]:
        prompt = Path(variant["compiled_prompt_path"]).read_text(encoding="utf-8")
        assert "FUTURE_SENTINEL" not in prompt
        assert "Act in the isolated fixture" in prompt
    absent = next(row for row in source_map["variants"] if row["id"] == "path-old-absent")
    assert not (Path(absent["workspace_seed"]["root"]) / "OLD_PLAN.md").exists()


def test_v2_allows_one_compiled_contact_without_a_scientific_ontology(
    tmp_path: Path, fake_launcher: None
) -> None:
    spec_path = _write_v2_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    only_variant = spec["intervention"]["variants"][0]
    only_variant.pop("factor_assignments")
    spec["intervention"]["variants"] = [only_variant]
    spec["intervention"].pop("held_constants")
    spec["intervention"].pop("intervention_variables")
    spec.pop("hypotheses")
    spec.pop("observables")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    created = freeze_cell(spec_path, tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    cell = json.loads((cell_dir / "cell.json").read_text(encoding="utf-8"))
    source_map = json.loads((cell_dir / "source_map.json").read_text(encoding="utf-8"))

    assert created["verification"]["ok"] is True
    assert cell["preregistered_hypotheses"] == []
    assert cell["intervention_variables"] == []
    assert len(source_map["variants"]) == 1


def test_v2_rejects_unprovenanced_derived_source(tmp_path: Path, fake_launcher: None) -> None:
    spec_path = _write_v2_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    next(row for row in spec["episode"]["sources"] if row["id"] == "derived-summary")[
        "derived_from"
    ] = []
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ResearchCellError) as raised:
        freeze_cell(spec_path, tmp_path / "runtime")

    assert raised.value.reason_code == "SOURCE_PROVENANCE_INVALID"


def test_v2_run_consumes_compiled_views_and_keeps_raw_trajectory_separate(
    tmp_path: Path,
    fake_launcher: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    spec = json.loads((cell_dir / "preregistration.json").read_text(encoding="utf-8"))
    quota_root = Path(spec["harness"]["world_turn_quota_root"]) / "C"
    quota_root.mkdir(parents=True)
    for slot in (1, 3):
        (quota_root / f"world-turn-{slot:02d}.json").write_text(
            json.dumps(
                {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": f"throttle-{slot}",
                    "status": "BOUND",
                    "account_slot": "C",
                    "slot": slot,
                    "controller_pid": 555,
                    "child_pid": 555,
                    "operator_throttle": True,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(cell_module, "is_process_alive", lambda pid: pid == 555)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda pid: (
            cell_module.ProcessLiveness.ALIVE
            if pid == 555
            else cell_module.ProcessLiveness.DEAD
        ),
    )
    monkeypatch.setattr(cell_module, "_validate_workspace_root", lambda path: path.resolve())

    class FakeProcess:
        next_pid = 9000

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
            stdout.write(b'{"type":"item.completed","item":{"type":"agent_message"}}\n')
            stdout.flush()
            args_path = Path(command[command.index("-CodexArgsFile") + 1])
            arguments = json.loads(args_path.read_text(encoding="utf-8"))
            Path(arguments[arguments.index("-o") + 1]).write_text(
                "candidate only", encoding="utf-8"
            )
            (Path(cwd) / "NEW_CONE.md").write_text("new action", encoding="utf-8")

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

    selected = ["direct-old-visible", "path-old-absent"]
    receipt = run_cell(
        cell_dir,
        replicates=1,
        max_parallel=2,
        quota_wait_seconds=1,
        variant_ids=selected,
    )
    verification = verify_cell(cell_dir)

    assert receipt["status"] == "SEALED"
    assert receipt["max_account_research_turns"] == 2
    assert receipt["root_main_used"] is False
    assert receipt["root_main_compute_allowed"] is False
    assert receipt["selected_variant_ids"] == selected
    assert len(receipt["jobs"]) == 2
    assert {row["action_cone"]["classification"] for row in receipt["jobs"]} == {"SWITCHED"}
    assert all(
        row["prompt_sha256"] == row["compiled_prompt_expected_sha256"] for row in receipt["jobs"]
    )
    assert set(receipt["ledgers"]) == {"raw_trajectory"}
    assert not (cell_dir / "qualifications").exists()
    assert not (cell_dir / "representations").exists()
    assert verification["ok"] is True

    first_job = receipt["jobs"][0]
    (Path(first_job["workspace"]) / "AFTER_RUN_TAMPER.txt").write_text(
        "workspace drift", encoding="utf-8"
    )
    assert verify_cell(cell_dir)["ok"] is True
    snapshot_root = Path(first_job["workspace_after_snapshot"]["root"])
    (snapshot_root / "AFTER_RUN_TAMPER.txt").write_text("snapshot drift", encoding="utf-8")
    tampered = verify_cell(cell_dir)
    assert tampered["ok"] is False
    assert (
        f"WORKSPACE_AFTER_SNAPSHOT_DRIFT:{first_job['lineage_id']}" in tampered["failures"]
    )


def test_v2_run_rejects_parallelism_above_declared_cap(tmp_path: Path, fake_launcher: None) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")

    with pytest.raises(ResearchCellError) as raised:
        run_cell(Path(str(created["cell_directory"])), max_parallel=3)

    assert raised.value.reason_code == "ACCOUNT_RESEARCH_CAP_EXCEEDED"


def test_v2_run_rejects_an_unregistered_variant(tmp_path: Path, fake_launcher: None) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")

    with pytest.raises(ResearchCellError) as raised:
        run_cell(
            Path(str(created["cell_directory"])),
            max_parallel=1,
            variant_ids=["not-preregistered"],
        )

    assert raised.value.reason_code == "RUN_VARIANT_INVALID"


def test_v2_freeze_requires_the_current_per_account_cap_of_two(
    tmp_path: Path, fake_launcher: None
) -> None:
    spec_path = _write_v2_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["harness"]["max_account_research_turns"] = 3
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ResearchCellError) as raised:
        freeze_cell(spec_path, tmp_path / "runtime")

    assert raised.value.reason_code == "ACCOUNT_RESEARCH_CAP_INVALID"


def test_v2_freeze_seals_a_local_mcp_carrier(tmp_path: Path, fake_launcher: None) -> None:
    spec_path = _write_v2_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["harness"]["workspace_files"].update(
        {
            "research_cell_mcp.py": "# frozen stdio server fixture\n",
            "research-cell-tools.json": json.dumps(
                {
                    "schema": "xinao.research-of-research.cell-mcp-config.v1",
                    "mode": "commit-choice",
                    "choices": {"old": "OLD_CONE.md", "new": "NEW_CONE.md"},
                }
            ),
        }
    )
    spec["harness"]["local_mcp"] = {
        "server_id": "research_cell",
        "script_path": "research_cell_mcp.py",
        "config_path": "research-cell-tools.json",
        "enabled_tools": ["commit_choice"],
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    created = freeze_cell(spec_path, tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    source_map = json.loads((cell_dir / "source_map.json").read_text(encoding="utf-8"))

    assert source_map["local_mcp"]["server_id"] == "research_cell"
    assert source_map["local_mcp"]["enabled_tools"] == ["commit_choice"]
    assert source_map["local_mcp"]["required"] is True
    assert verify_cell(cell_dir)["ok"] is True


def test_v2_run_fails_closed_when_a_production_guard_is_not_live(
    tmp_path: Path,
    fake_launcher: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    monkeypatch.setattr(cell_module, "is_process_alive", lambda _pid: False)

    with pytest.raises(ResearchCellError) as raised:
        run_cell(Path(str(created["cell_directory"])), max_parallel=1)

    assert raised.value.reason_code == "PRODUCTION_GUARD_NOT_LIVE"


def test_v2_run_verifies_the_physical_operator_throttle_records(
    tmp_path: Path,
    fake_launcher: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    spec = json.loads((cell_dir / "preregistration.json").read_text(encoding="utf-8"))
    quota_root = Path(spec["harness"]["world_turn_quota_root"]) / "C"
    quota_root.mkdir(parents=True)
    for slot in (1, 3):
        (quota_root / f"world-turn-{slot:02d}.json").write_text(
            json.dumps(
                {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": f"not-a-throttle-{slot}",
                    "status": "BOUND",
                    "account_slot": "C",
                    "slot": slot,
                    "controller_pid": 555,
                    "child_pid": 555,
                    "operator_throttle": slot == 1,
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(cell_module, "is_process_alive", lambda pid: pid == 555)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda pid: (
            cell_module.ProcessLiveness.ALIVE
            if pid == 555
            else cell_module.ProcessLiveness.DEAD
        ),
    )

    with pytest.raises(ResearchCellError) as raised:
        run_cell(cell_dir, max_parallel=1)

    assert raised.value.reason_code == "CAP_THROTTLE_INVALID"


def test_v2_partial_batch_reservation_is_released_on_quota_timeout(
    tmp_path: Path,
    fake_launcher: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    spec = json.loads((cell_dir / "preregistration.json").read_text(encoding="utf-8"))
    quota_root = Path(spec["harness"]["world_turn_quota_root"]) / "C"
    quota_root.mkdir(parents=True)
    for slot, throttle in ((1, True), (3, True), (4, False)):
        (quota_root / f"world-turn-{slot:02d}.json").write_text(
            json.dumps(
                {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": f"occupied-{slot}",
                    "status": "BOUND",
                    "account_slot": "C",
                    "slot": slot,
                    "controller_pid": 555,
                    "child_pid": 555,
                    "operator_throttle": throttle,
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(cell_module, "is_process_alive", lambda pid: pid == 555)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda pid: (
            cell_module.ProcessLiveness.ALIVE
            if pid == 555
            else cell_module.ProcessLiveness.DEAD
        ),
    )
    monkeypatch.setattr(cell_module, "_validate_workspace_root", lambda path: path.resolve())

    with pytest.raises(ResearchCellError) as raised:
        run_cell(cell_dir, max_parallel=2, quota_wait_seconds=0.08)

    assert raised.value.reason_code == "QUOTA_TIMEOUT"
    released = json.loads((quota_root / "world-turn-02.json").read_text(encoding="utf-8"))
    assert released["status"] == "RELEASED"


def test_v2_popen_failure_releases_every_reserved_slot(
    tmp_path: Path,
    fake_launcher: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    spec = json.loads((cell_dir / "preregistration.json").read_text(encoding="utf-8"))
    quota_root = Path(spec["harness"]["world_turn_quota_root"]) / "C"
    quota_root.mkdir(parents=True)
    for slot in (1, 3):
        (quota_root / f"world-turn-{slot:02d}.json").write_text(
            json.dumps(
                {
                    "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                    "lease_id": f"throttle-{slot}",
                    "status": "BOUND",
                    "account_slot": "C",
                    "slot": slot,
                    "controller_pid": 555,
                    "child_pid": 555,
                    "operator_throttle": True,
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(cell_module, "is_process_alive", lambda pid: pid == 555)
    monkeypatch.setattr(
        cell_module,
        "process_liveness",
        lambda pid: (
            cell_module.ProcessLiveness.ALIVE
            if pid == 555
            else cell_module.ProcessLiveness.DEAD
        ),
    )
    monkeypatch.setattr(cell_module, "_validate_workspace_root", lambda path: path.resolve())
    monkeypatch.setattr(
        cell_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic launch failure")),
    )

    with pytest.raises(OSError, match="synthetic launch failure"):
        run_cell(cell_dir, max_parallel=2, quota_wait_seconds=1)

    for slot in (2, 4):
        record = json.loads(
            (quota_root / f"world-turn-{slot:02d}.json").read_text(encoding="utf-8")
        )
        assert record["status"] == "RELEASED"


def test_account_quota_never_reclaims_a_dead_operator_throttle(tmp_path: Path) -> None:
    quota = cell_module.AccountQuota(
        account_slot="C",
        quota_root=tmp_path / "quota",
        limit=4,
        run_id="candidate-run",
    )
    quota.account_root.mkdir(parents=True)
    throttle_path = quota.account_root / "world-turn-01.json"
    throttle_path.write_text(
        json.dumps(
            {
                "schema": WORLD_TURN_QUOTA_LEASE_SCHEMA,
                "lease_id": "operator-throttle-1",
                "status": "BOUND",
                "account_slot": "C",
                "slot": 1,
                "controller_pid": 999999,
                "child_pid": 999999,
                "operator_throttle": True,
            }
        ),
        encoding="utf-8",
    )

    claimed = quota.try_claim(lineage_id="candidate", workspace=tmp_path / "workspace")

    assert claimed is not None
    assert claimed["slot"] == 2
    assert json.loads(throttle_path.read_text(encoding="utf-8"))["lease_id"] == (
        "operator-throttle-1"
    )


def test_verify_reports_an_unsealed_run_directory(
    tmp_path: Path, fake_launcher: None
) -> None:
    created = freeze_cell(_write_v2_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    incomplete = cell_dir / "runs" / "ror-incomplete-fixture"
    incomplete.mkdir(parents=True)
    (incomplete / "run_state.json").write_text(
        json.dumps({"schema": cell_module.RUN_SCHEMA, "status": "RUNNING"}),
        encoding="utf-8",
    )

    verification = verify_cell(cell_dir)

    assert verification["ok"] is False
    assert "RUN_INCOMPLETE:ror-incomplete-fixture" in verification["failures"]
    assert verify_cell(cell_dir, include_runs=False)["ok"] is True
