from __future__ import annotations

import asyncio
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]


def _completed(*, stdout: str = "1 passed") -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_pytest_slice_returns_immutable_lineage_bound_evidence(tmp_path: Path, monkeypatch) -> None:
    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: _completed())
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "019f-run/id"),
    )

    result = nodes.run_pytest_slice_bus(
        params={},
        repo_root=REPO_ROOT,
        runtime_root=tmp_path / "runtime",
        workflow_id="wf/pytest",
    )

    immutable = Path(result["pytest_slice_ref"])
    latest = Path(result["pytest_slice_latest_ref"])
    record = json.loads(immutable.read_text(encoding="utf-8"))
    assert immutable != latest
    assert immutable.name.startswith("slice_wf_pytest_019f-run_id_")
    assert len(record["evidence_id"]) == 32
    assert record["workflow_id"] == "wf/pytest"
    assert record["temporal_workflow_id"] == "wf/pytest"
    assert record["temporal_run_id"] == "019f-run/id"
    assert json.loads(latest.read_text(encoding="utf-8")) == record


def test_pytest_slice_concurrent_writes_preserve_every_immutable_record(
    tmp_path: Path, monkeypatch
) -> None:
    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: _completed())
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "run-concurrent"),
    )

    def write_one(index: int) -> str:
        result = nodes.run_pytest_slice_bus(
            params={},
            repo_root=REPO_ROOT,
            runtime_root=runtime,
            workflow_id=f"wf-{index % 2}",
        )
        return str(result["pytest_slice_ref"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = list(pool.map(write_one, range(16)))

    assert len(refs) == len(set(refs)) == 16
    records = [json.loads(Path(ref).read_text(encoding="utf-8")) for ref in refs]
    latest = json.loads(
        (runtime / "state" / "integrated_bus_pytest_slice" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest["evidence_id"] in {record["evidence_id"] for record in records}
    assert not list(runtime.rglob("*.tmp"))


def test_pytest_slice_graph_node_passes_workflow_identity(tmp_path: Path, monkeypatch) -> None:
    from services.agent_runtime import integrated_bus_graph as graph

    captured: dict[str, object] = {}

    def fake_slice(**kwargs):
        captured.update(kwargs)
        return {"pytest_slice_ok": True}

    monkeypatch.setattr(graph, "run_pytest_slice_bus", fake_slice)
    result = asyncio.run(
        graph.pytest_slice_node(
            {
                "workflow_id": "wf-node-binding",
                "repo_root": str(REPO_ROOT),
                "runtime_root": str(tmp_path / "runtime"),
            }
        )
    )

    assert result["pytest_slice_ok"] is True
    assert captured["workflow_id"] == "wf-node-binding"
