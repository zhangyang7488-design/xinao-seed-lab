import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "total_source_episode_entry.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("total_source_episode_entry", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_total_source_episode_entry_writes_invokable_episode_refs(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source = tmp_path / "02_P0_底座全自动任务落地_20260707.txt"
    source.write_text(
        "\n".join(
            [
                "Phase0 先焊 Seed Cortex 耐久内核。",
                "POST /episodes",
                "-> WorkflowPort",
                "-> EvidenceLedger",
                "ResearchEpisode 只能在 Phase1 门槛后启动。",
            ]
        ),
        encoding="utf-8",
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        source_package_path=source,
        wave_id="pytest-total-source-episode-entry",
        write=True,
    )

    assert payload["schema_version"] == "xinao.codex_s.total_source_episode_entry.v1"
    assert payload["sentinel"] == "SENTINEL:XINAO_TOTAL_SOURCE_EPISODE_ENTRY_READY"
    assert payload["theme_family"] == "episode_entry"
    assert payload["validation"]["passed"] is True
    assert payload["workflow_entry"]["validation"]["checks"]["post_episodes_anchor_found"] is True
    assert payload["workflow_entry"]["validation"]["checks"]["workflow_port_anchor_found"] is True
    assert payload["phase1_research_episode_started"] is False
    assert payload["completion_claim_allowed"] is False

    output = payload["output_paths"]
    for key in [
        "runtime_latest",
        "wave_record",
        "workflow_entry",
        "episode_trace",
        "capability_manifest",
        "capability_invoke_latest",
        "readback_zh",
    ]:
        assert Path(output[key]).is_file(), key

    latest = json.loads(Path(output["runtime_latest"]).read_text(encoding="utf-8"))
    assert latest["wave_id"] == "pytest-total-source-episode-entry"
    assert latest["can_invoke_now"]["service"] == "SeedCortexService.total_source_episode_entry(...)"
    assert "现在能干什么" in Path(output["readback_zh"]).read_text(encoding="utf-8")


def test_total_source_episode_entry_can_submit_aaq_and_next_frontier(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    source = tmp_path / "02_P0_底座全自动任务落地_20260707.txt"
    source.write_text(
        "\n".join(
            [
                "Phase0 入口：",
                "POST /episodes",
                "-> WorkflowPort",
                "-> NextFrontier",
            ]
        ),
        encoding="utf-8",
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=repo,
        source_package_path=source,
        wave_id="pytest-total-source-episode-entry-aaq",
        submit_aaq=True,
        write=True,
    )

    assert payload["validation"]["passed"] is True
    assert payload["artifact_acceptance_queue"]["accepted_artifact_count"] == 1
    assert payload["next_frontier"]["validation"]["passed"] is True
    assert payload["workflow_entry"]["artifact_acceptance_queue_ref"]
    assert payload["workflow_entry"]["next_frontier_ref"]
    assert payload["capability_manifest"]["aaq_bound"] is True
    assert Path(payload["output_paths"]["next_frontier_latest"]).is_file()
