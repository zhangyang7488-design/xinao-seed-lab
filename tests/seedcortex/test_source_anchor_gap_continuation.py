import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "source_anchor_gap_continuation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("source_anchor_gap_continuation", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_anchor_package(module, anchor: Path) -> None:
    anchor.mkdir(parents=True, exist_ok=True)
    (anchor / "arbitrary_current_material_name_can_change.txt").write_text(
        "入口目录内文本名字和内容可以变化；source-anchor runner 不绑定也不切割。",
        encoding="utf-8",
    )


def _seed_required_runtime_refs(module, runtime: Path) -> None:
    required = {
        "live_backend_watch",
        "default_hot_path_intake",
        "artifact_acceptance_queue",
        "metaminute_preflight_reflection",
        "default_parallelism_policy",
        "parallel_dispatch_plan",
        "parallel_fan_in_acceptance",
    }
    for key in required:
        payload = {
            "schema_version": f"fixture.{key}.v1",
            "status": "ready",
            "sentinel": f"SENTINEL:FIXTURE_{key.upper()}",
            "validation": {"passed": True},
        }
        if key == "live_backend_watch":
            payload["foreground_poll_required"] = False
        _write_json(runtime / module.RUNTIME_REF_PATHS[key], payload)


def test_auto_source_task_slicing_is_frozen_by_default(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "anchors"
    _write_anchor_package(module, anchor)
    _seed_required_runtime_refs(module, runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        continuation_mode_active=True,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["source_anchor_complete"] is True
    assert payload["source_anchors"]["root_ref"]["exists"] is True
    assert payload["source_anchors"]["text_refs"] == {}
    assert payload["source_anchors"]["discovery_policy"] == ("entry_root_only_no_text_file_binding")
    assert payload["source_anchors"]["text_file_scan_enabled"] is False
    assert payload["runtime_ref_complete"] is True
    assert payload["auto_task_slicing_enabled"] is False
    assert payload["source_anchor_task_slicing_frozen"] is True
    assert payload["source_text_debt_open"] is False
    assert payload["source_anchor_coverage"]["frozen_by_user"] is True
    assert payload["source_anchor_coverage"]["sampled_obligation_count"] == 0
    assert payload["coverage_gate_decision"]["report_allowed"] is True
    assert payload["coverage_gate_decision"]["stop_allowed"] is True
    assert payload["coverage_gate_decision"]["continuation_required"] is False
    assert payload["continue_dispatch_expected"] is False
    assert payload["next_loop_packet"]["front_gate"] == "source_anchor_task_slicing_frozen"
    assert payload["next_loop_packet"]["action"] == (
        "do not dispatch source-anchor TaskCard; main brain reads anchor entry root directly"
    )

    coverage = json.loads(
        (runtime / "state" / "source_anchor_coverage" / "latest.json").read_text(encoding="utf-8")
    )
    slices = json.loads(
        (runtime / "state" / "source_anchor_task_slices" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    card = json.loads(
        (runtime / "state" / "task_card" / "source_anchor_coverage_next_ready.json").read_text(
            encoding="utf-8"
        )
    )
    assert coverage["source_text_debt_open"] is False
    assert coverage["frozen_by_user"] is True
    assert slices["status"] == "source_anchor_task_slicing_permanently_frozen"
    assert slices["next_ready"] is False
    assert slices["slice_count"] == 0
    assert card["status"] == "frozen_tombstone_not_taskcard"
    assert card["routing"]["preferred_lane"] == "none_auto_task_slicing_frozen"


def test_source_task_slicing_enable_flag_is_ignored_while_permanently_frozen(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "anchors"
    _write_anchor_package(module, anchor)
    _seed_required_runtime_refs(module, runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        continuation_mode_active=True,
        source_task_slicing_enabled=True,
        write=True,
    )

    assert payload["auto_task_slicing_enabled"] is False
    assert payload["source_anchor_task_slicing_frozen"] is True
    assert payload["source_text_debt_open"] is False
    assert payload["continue_dispatch_expected"] is False
    assert payload["next_loop_packet"]["front_gate"] == "source_anchor_task_slicing_frozen"


def test_ordinary_discussion_can_stop_with_source_anchor_freeze(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "anchors"
    _write_anchor_package(module, anchor)
    _seed_required_runtime_refs(module, runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        continuation_mode_active=False,
        write=False,
    )

    assert payload["source_text_debt_open"] is False
    assert payload["source_anchor_task_slicing_frozen"] is True
    assert payload["continue_dispatch_expected"] is False
    assert payload["coverage_gate_decision"]["report_allowed"] is True
    assert payload["coverage_gate_decision"]["stop_allowed"] is True
    assert payload["coverage_gate_decision"]["continuation_required"] is False
    assert payload["next_loop_packet"]["front_gate"] == "ordinary_checkpoint_stop_allowed"


def test_explicit_user_stop_overrides_source_anchor_freeze(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    anchor = tmp_path / "anchors"
    _write_anchor_package(module, anchor)
    _seed_required_runtime_refs(module, runtime)

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        anchor_package_root=anchor,
        continuation_mode_active=True,
        explicit_user_stop_requested=True,
        write=False,
    )

    assert payload["source_text_debt_open"] is False
    assert payload["source_anchor_task_slicing_frozen"] is True
    assert payload["continue_dispatch_expected"] is False
    assert payload["coverage_gate_decision"]["stop_allowed"] is True
    assert payload["coverage_gate_decision"]["continuation_required"] is False
    assert payload["next_loop_packet"]["front_gate"] == "explicit_user_stop_override"
