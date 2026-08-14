from __future__ import annotations

import json
from pathlib import Path

import pytest
from services.research_of_research import cell as cell_module
from services.research_of_research.cell import (
    CELL_SPEC_SCHEMA,
    LEGACY_CELL_SPEC_SCHEMA,
    AccountQuota,
    ResearchCellError,
    freeze_cell,
    validate_runtime_root,
    verify_cell,
)


def _write_spec(tmp_path: Path, *, sentinel: str = "withheld-only-phrase") -> Path:
    source = tmp_path / "episode.txt"
    source.write_text(
        "common line one\ncommon line two\nraw human correction\nwithheld-only-phrase\n",
        encoding="utf-8",
    )
    spec = {
        "schema": LEGACY_CELL_SPEC_SCHEMA,
        "cell_id": "raw-vs-derived-test",
        "question": "Does the representation of a correction change the research trajectory?",
        "episode": {
            "replay_fidelity": "PARTIAL",
            "known_gaps": ["hidden reasoning is unavailable"],
            "cutoff": "after correction, before continuation",
            "sources": [
                {
                    "id": "full-episode",
                    "role": "raw-history",
                    "visibility": "evidence_only",
                    "material": {"kind": "file", "path": str(source)},
                },
                {
                    "id": "withheld-reveal",
                    "role": "future-reveal",
                    "visibility": "withheld",
                    "material": {
                        "kind": "line_slice",
                        "path": str(source),
                        "start_line": 4,
                        "end_line": 4,
                    },
                },
            ],
        },
        "intervention": {
            "common": {
                "kind": "line_slice",
                "path": str(source),
                "start_line": 1,
                "end_line": 2,
            },
            "shared_instruction": "Continue from the historical cutoff.",
            "held_constants": ["model", "workspace", "shared request"],
            "only_changed": "correction representation",
            "variants": [
                {
                    "id": "raw-human",
                    "provenance_kind": "raw_human",
                    "condition": {
                        "kind": "line_slice",
                        "path": str(source),
                        "start_line": 3,
                        "end_line": 3,
                    },
                },
                {
                    "id": "derived-summary",
                    "provenance_kind": "derived",
                    "condition": {"kind": "literal", "text": "the user rejects the prior frame"},
                },
            ],
        },
        "hypotheses": [
            {"id": "h-fixed", "prediction": "Only surface wording changes."},
            {"id": "h-axis", "prediction": "The problem representation changes."},
        ],
        "forbidden_future_sentinels": [sentinel],
        "harness": {
            "account_slot": "C",
            "model": "gpt-5.6-sol",
            "model_reasoning_effort": "max",
            "launcher": str(tmp_path / "base-launcher.ps1"),
            "workspace_files": {"AGENTS.md": "Isolated replay. No external effects.\n"},
        },
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def fake_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    def create(_source: Path, destination: Path, **_kwargs: object) -> dict[str, object]:
        raw = b"isolated-launcher"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return {
            "path": str(destination.resolve()),
            "sha256": cell_module._sha(raw),
            "source_path": str(_source),
            "sandbox_mode": "workspace-write",
            "approval_policy": "never",
        }

    monkeypatch.setattr(cell_module, "create_world_isolated_launcher", create)


def test_freeze_is_hash_bound_and_identical_reuse_is_typed(
    tmp_path: Path, fake_launcher: None
) -> None:
    spec = _write_spec(tmp_path)
    runtime = tmp_path / "runtime"

    created = freeze_cell(spec, runtime)
    reused = freeze_cell(spec, runtime)
    verification = verify_cell(Path(str(created["cell_directory"])))

    assert created["disposition"] == "CREATED"
    assert reused["disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert reused["cell_sha256"] == created["cell_sha256"]
    assert verification["ok"] is True
    prereg = json.loads(
        (Path(str(created["cell_directory"])) / "preregistration.json").read_text(encoding="utf-8")
    )
    assert len(prereg["hypotheses"]) == 2
    assert prereg["intervention"]["only_changed"] == "correction representation"


def test_verifier_detects_preregistration_mutation(tmp_path: Path, fake_launcher: None) -> None:
    created = freeze_cell(_write_spec(tmp_path), tmp_path / "runtime")
    cell_dir = Path(str(created["cell_directory"]))
    prereg = cell_dir / "preregistration.json"
    value = json.loads(prereg.read_text(encoding="utf-8"))
    value["hypotheses"][0]["prediction"] = "post-hoc prediction"
    prereg.write_text(json.dumps(value), encoding="utf-8")

    verification = verify_cell(cell_dir)

    assert verification["ok"] is False
    assert "PREDICTION_MUTATED" in verification["failures"]


def test_freeze_rejects_future_reveal_in_model_visible_bytes(
    tmp_path: Path, fake_launcher: None
) -> None:
    spec = _write_spec(tmp_path, sentinel="common line one")

    with pytest.raises(ResearchCellError) as raised:
        freeze_cell(spec, tmp_path / "runtime")

    assert raised.value.reason_code == "INVALID_EXPERIMENT"


def test_high_fidelity_cannot_hide_known_gaps(tmp_path: Path, fake_launcher: None) -> None:
    spec_path = _write_spec(tmp_path)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["episode"]["replay_fidelity"] = "EXACT_REPLAYABLE"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(ResearchCellError) as raised:
        freeze_cell(spec_path, tmp_path / "runtime")

    assert raised.value.reason_code == "FIDELITY_OVERCLAIM"


def test_runtime_root_rejects_production_overlap() -> None:
    with pytest.raises(ResearchCellError) as raised:
        validate_runtime_root(Path(r"E:\XINAO_RESEARCH_WORKSPACES\S\work\ror"))

    assert raised.value.reason_code == "RUN_ROOT_OVERLAPS_PRODUCTION"


def test_runtime_root_rejects_unlisted_perpetual_runtime() -> None:
    with pytest.raises(ResearchCellError) as raised:
        cell_module.validate_runtime_root(
            Path(r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_perpetual_future_lineage")
        )

    assert raised.value.reason_code == "RUN_ROOT_OVERLAPS_PRODUCTION"


def test_account_quota_claim_bind_release_is_schema_compatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cell_module, "is_process_alive", lambda _pid: False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    quota = AccountQuota(
        account_slot="C",
        quota_root=tmp_path / "quota",
        limit=2,
        run_id="ror-test",
    )

    lease = quota.claim(lineage_id="raw-r01", workspace=workspace, timeout_seconds=1)
    bound = quota.bind(lease, child_pid=999999)
    released = quota.release(bound)
    record = json.loads(Path(str(bound["path"])).read_text(encoding="utf-8"))

    assert bound["status"] == "BOUND"
    assert bound["experiment_candidate_only"] is True
    assert released == "RELEASED"
    assert record["status"] == "RELEASED"
    assert record["run_id"] == "ror-test"


def test_codex_prompt_uses_stdin_not_native_argv(tmp_path: Path) -> None:
    arguments = cell_module._codex_arguments(
        model="gpt-5.6-sol",
        effort="max",
        web_search="disabled",
        last_message_path=tmp_path / "last message.txt",
    )

    assert arguments[-1] == "-"
    assert "--skip-git-repo-check" in arguments
    assert 'web_search="disabled"' in arguments
    assert "prompt words with spaces" not in arguments
