"""Falsifying tests for the host-side, two-step ResearchState CAS."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "skills" / "xinao" / "scripts" / "xinao_runtime.py"


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_runtime():
    spec = importlib.util.spec_from_file_location("xinao_research_state_under_test", RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResearch:
    """A one-shot provider receipt fixture, not a continuity implementation."""

    def __init__(self, root: Path, tag: str, *, provider_ok: bool = True) -> None:
        self.root = root
        self.tag = tag
        self.provider_ok = provider_ok
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        question: str,
        as_of: str | None,
        material_paths: Sequence[Path] | None = None,
    ) -> dict[str, Any]:
        paths = [Path(path) for path in (material_paths or ())]
        refs = [
            {
                "material_id": f"sha256:{_sha256_bytes(path.read_bytes())}",
                "source_path": str(path),
                "sha256": _sha256_bytes(path.read_bytes()),
            }
            for path in paths
        ]
        bundle_core = {"tag": self.tag, "materials": refs}
        bundle_sha256 = _sha256_bytes(_canonical_bytes(bundle_core))
        candidate = {
            "schema_version": "xinao.research_candidate.v2",
            "status": "CANDIDATE_READY",
            "research_question": question,
            "as_of": as_of or "2026-07-31T00:00:00Z",
            "material_bundle_id": f"xinao-material-bundle-sha256:{bundle_sha256}",
            "material_refs_used": [
                {"material_id": item["material_id"], "sha256": item["sha256"]} for item in refs
            ],
            "summary": f"candidate {self.tag}",
            "hypotheses": ["candidate only"],
            "competing_explanations": ["candidate may be wrong"],
            "methods": ["sealed material inspection"],
            "evidence_used": [
                {
                    "material_id": item["material_id"],
                    "finding": "bounded fixture",
                    "locator": Path(item["source_path"]).name,
                }
                for item in refs
            ],
            "counterevidence": [],
            "limitations": ["test fixture"],
            "next_evidence": ["fresh observation"],
        }
        run_id = f"xrr_test_{self.tag}"
        run_root = self.root / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        result = {
            "schema_version": "xinao.researcher_container_result.v2",
            "status": "CANDIDATE_READY",
            "candidate": candidate,
            "completion_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
        }
        result_path = run_root / "result.json"
        result_path.write_bytes(_canonical_bytes(result))
        result_sha256 = _sha256_bytes(result_path.read_bytes())
        provider_evidence = {
            "stop_reason": "EndTurn" if self.provider_ok else "Cancelled",
            "num_turns": 1 if self.provider_ok else 0,
            "session_id_present": self.provider_ok,
            "request_id_present": self.provider_ok,
            "model_usage": {"grok-4.5-build": {"modelCalls": 1 if self.provider_ok else 0}},
            "usage": {"total_tokens": 10},
        }
        receipt = {
            "schema_version": "xinao.skill_research_receipt.v2",
            "run_id": run_id,
            "status": "CANDIDATE_READY",
            "candidate": candidate,
            "request_sha256": _sha256_bytes(question.encode("utf-8")),
            "result_sha256": result_sha256,
            "result_path": str(result_path.resolve()),
            "material_bundle_id": candidate["material_bundle_id"],
            "material_manifest_sha256": bundle_sha256,
            "material_packet_sha256": _sha256_bytes(_canonical_bytes(refs)),
            "material_source_refs": refs,
            "provider_evidence": provider_evidence,
            "release_id": "researcher-test",
            "skill_bundle_tree_sha256": "d" * 64,
            "created_at": "2026-07-31T00:00:00Z",
            "research_progress_claim_allowed": False,
            "science_restored": False,
            "parent_complete": False,
            "completion_claim_allowed": False,
        }
        receipt_path = run_root / "receipt.json"
        receipt_path.write_bytes(_canonical_bytes(receipt))
        returned = {
            **receipt,
            "receipt_path": str(receipt_path.resolve()),
            "receipt_sha256": _sha256_bytes(receipt_path.read_bytes()),
        }
        self.calls.append({"paths": [str(path) for path in paths], "refs": refs})
        return returned


class _SplitReceiptResearch(_FakeResearch):
    """Forge a valid memory envelope over different sealed receipt bytes."""

    def __call__(
        self,
        question: str,
        as_of: str | None,
        material_paths: Sequence[Path] | None = None,
    ) -> dict[str, Any]:
        returned = super().__call__(question, as_of, material_paths)
        receipt_path = Path(returned["receipt_path"])
        sealed = json.loads(receipt_path.read_text(encoding="utf-8"))
        sealed["provider_evidence"] = {
            "stop_reason": "Cancelled",
            "num_turns": 0,
            "session_id_present": False,
            "request_id_present": False,
            "model_usage": {"grok-4.5-build": {"modelCalls": 0}},
            "usage": {"total_tokens": 0},
        }
        sealed["material_source_refs"] = []
        sealed["science_restored"] = True
        receipt_path.write_bytes(_canonical_bytes(sealed))
        returned["receipt_sha256"] = _sha256_bytes(receipt_path.read_bytes())
        return returned


class _WrongModelResearch(_FakeResearch):
    """Keep memory and disk identical while forging the locked provider model."""

    def __call__(
        self,
        question: str,
        as_of: str | None,
        material_paths: Sequence[Path] | None = None,
    ) -> dict[str, Any]:
        returned = super().__call__(question, as_of, material_paths)
        receipt_path = Path(returned["receipt_path"])
        sealed = json.loads(receipt_path.read_text(encoding="utf-8"))
        forged = {
            "stop_reason": "EndTurn",
            "num_turns": 1,
            "session_id_present": True,
            "request_id_present": True,
            "model_usage": {"unlocked-model": {"modelCalls": 1}},
            "usage": {"total_tokens": 10},
        }
        sealed["provider_evidence"] = forged
        receipt_path.write_bytes(_canonical_bytes(sealed))
        returned["provider_evidence"] = forged
        returned["receipt_sha256"] = _sha256_bytes(receipt_path.read_bytes())
        return returned


class _MisnamedPriorResearch(_FakeResearch):
    """Keep the four digests while removing their semantic material roles."""

    def __call__(
        self,
        question: str,
        as_of: str | None,
        material_paths: Sequence[Path] | None = None,
    ) -> dict[str, Any]:
        returned = super().__call__(question, as_of, material_paths)
        receipt_path = Path(returned["receipt_path"])
        sealed = json.loads(receipt_path.read_text(encoding="utf-8"))
        refs = []
        for item in sealed["material_source_refs"]:
            changed = dict(item)
            source = Path(changed["source_path"])
            if source.name.startswith("prior_"):
                changed["source_path"] = str(source.with_name(f"misnamed_{source.name}"))
            refs.append(changed)
        sealed["material_source_refs"] = refs
        receipt_path.write_bytes(_canonical_bytes(sealed))
        returned["material_source_refs"] = refs
        returned["receipt_sha256"] = _sha256_bytes(receipt_path.read_bytes())
        return returned


def _probe_main(arguments: list[str]) -> int:
    module = _load_runtime()
    mode = arguments[0]
    state_root = Path(arguments[1])
    work_root = Path(arguments[2])
    try:
        if mode == "genesis":
            fake = _FakeResearch(work_root / "genesis", "genesis")
            result = module.research_state_genesis(
                root=state_root,
                question="step zero",
                as_of="2026-07-31T00:00:00Z",
                research_fn=fake,
            )
            payload = {"result": result, "calls": fake.calls}
        elif mode in {"advance", "stale"}:
            fake = _FakeResearch(work_root / mode, mode)
            result = module.research_state_advance(
                root=state_root,
                expected_head_sha256=arguments[3],
                question="step one revises step zero",
                as_of="2026-07-31T01:00:00Z",
                research_fn=fake,
            )
            payload = {"result": result, "calls": fake.calls}
        elif mode == "inspect":
            payload = {"result": module.research_state_inspect(root=state_root), "calls": []}
        else:  # pragma: no cover - probe misuse
            raise AssertionError(mode)
    except module.XinaoError as exc:
        print(json.dumps({"reason_code": exc.reason_code, "detail": exc.detail}, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


def _run_probe(mode: str, state_root: Path, work_root: Path, head: str | None = None):
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--probe", mode]
    command.extend([str(state_root), str(work_root)])
    if head is not None:
        command.append(head)
    return subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def test_fresh_process_two_step_binds_prior_artifacts_and_rejects_stale_head(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "research-state"
    work_root = tmp_path / "one-shot-runs"

    process_a = _run_probe("genesis", state_root, work_root)
    assert process_a.returncode == 0, process_a.stderr
    genesis = json.loads(process_a.stdout)["result"]
    head0 = genesis["head_state_sha256"]
    assert genesis["step_index"] == 0
    assert genesis["completion_claim_allowed"] is False

    # Destroy the original one-shot run. Advance must use copied CAS artifacts.
    shutil.rmtree(work_root / "genesis")
    process_b = _run_probe("advance", state_root, work_root, head0)
    assert process_b.returncode == 0, process_b.stderr
    body_b = json.loads(process_b.stdout)
    advanced = body_b["result"]
    assert advanced["step_index"] == 1
    assert advanced["predecessor_state_sha256"] == head0
    assert advanced["head_state_sha256"] != head0
    names = {Path(path).name for path in body_b["calls"][0]["paths"]}
    assert names == {
        "prior_research_state.json",
        "prior_candidate.json",
        "prior_result.json",
        "prior_receipt.json",
    }
    predecessor_materials = advanced["state"]["predecessor_material_sha256s"]
    observed = {item["sha256"] for item in body_b["calls"][0]["refs"]}
    assert set(predecessor_materials.values()) <= observed

    process_c = _run_probe("inspect", state_root, work_root)
    assert process_c.returncode == 0, process_c.stderr
    inspected = json.loads(process_c.stdout)["result"]
    assert inspected["head"]["head_state_sha256"] == advanced["head_state_sha256"]
    assert inspected["chain_length"] == 2
    assert inspected["state"]["predecessor_state_sha256"] == head0

    stale = _run_probe("stale", state_root, work_root, head0)
    assert stale.returncode == 2
    assert json.loads(stale.stdout)["reason_code"] == "RESEARCH_STATE_STALE_HEAD"
    assert not (work_root / "stale").exists()


def test_duplicate_genesis_fails_closed(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run-a", "a"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_genesis(
            root=root,
            question="q0 again",
            research_fn=_FakeResearch(tmp_path / "run-b", "b"),
        )
    assert failure.value.reason_code == "RESEARCH_STATE_HEAD_EXISTS"
    assert not (tmp_path / "run-b").exists()


def test_tampered_head_object_fails_closed(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run", "a"),
    )
    digest = genesis["head_state_sha256"]
    object_path = root / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    object_path.write_bytes(object_path.read_bytes() + b" ")
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_inspect(root=root)
    assert failure.value.reason_code == "RESEARCH_STATE_OBJECT_HASH_MISMATCH"


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run", "a"),
    )
    digest = genesis["state"]["candidate_sha256"]
    (root / "artifacts" / "sha256" / digest[:2] / f"{digest}.json").unlink()
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_inspect(root=root)
    assert failure.value.reason_code == "RESEARCH_STATE_ARTIFACT_MISSING"


def test_invalid_second_provider_effect_does_not_advance_head(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run-a", "a"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_advance(
            root=root,
            expected_head_sha256=genesis["head_state_sha256"],
            question="q1",
            research_fn=_FakeResearch(tmp_path / "run-b", "b", provider_ok=False),
        )
    assert failure.value.reason_code == "RESEARCH_STATE_PROVIDER_EFFECT_INVALID"
    inspected = module.research_state_inspect(root=root)
    assert inspected["head"]["head_state_sha256"] == genesis["head_state_sha256"]
    assert inspected["chain_length"] == 1


def test_memory_envelope_cannot_override_sealed_receipt_bytes(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run-a", "a"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_advance(
            root=root,
            expected_head_sha256=genesis["head_state_sha256"],
            question="q1",
            research_fn=_SplitReceiptResearch(tmp_path / "run-b", "b"),
        )
    assert failure.value.reason_code == "RESEARCH_STATE_RECEIPT_ENVELOPE_MISMATCH"
    inspected = module.research_state_inspect(root=root)
    assert inspected["head"]["head_state_sha256"] == genesis["head_state_sha256"]
    assert inspected["chain_length"] == 1


def test_sealed_receipt_must_prove_the_locked_one_shot_model(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_genesis(
            root=root,
            question="q0",
            research_fn=_WrongModelResearch(tmp_path / "run", "wrong-model"),
        )
    assert failure.value.reason_code == "RESEARCH_STATE_PROVIDER_EFFECT_INVALID"
    assert not (root / "series.json").exists()
    assert not (root / "head.json").exists()


def test_prior_material_digests_cannot_be_detached_from_their_roles(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run-a", "a"),
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_advance(
            root=root,
            expected_head_sha256=genesis["head_state_sha256"],
            question="q1",
            research_fn=_MisnamedPriorResearch(tmp_path / "run-b", "misnamed"),
        )
    assert failure.value.reason_code == "RESEARCH_STATE_PREDECESSOR_MATERIAL_UNBOUND"
    inspected = module.research_state_inspect(root=root)
    assert inspected["head"]["head_state_sha256"] == genesis["head_state_sha256"]


def test_chain_replay_binds_child_material_digests_to_actual_predecessor(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    genesis = module.research_state_genesis(
        root=root,
        question="q0",
        research_fn=_FakeResearch(tmp_path / "run-a", "a"),
    )
    advanced = module.research_state_advance(
        root=root,
        expected_head_sha256=genesis["head_state_sha256"],
        question="q1",
        research_fn=_FakeResearch(tmp_path / "run-b", "b"),
    )
    forged = dict(advanced["state"])
    forged["predecessor_material_sha256s"] = dict(forged["predecessor_material_sha256s"])
    forged["predecessor_material_sha256s"]["candidate"] = "e" * 64
    forged_bytes = _canonical_bytes(forged)
    forged_digest = _sha256_bytes(forged_bytes)
    forged_path = root / "objects" / "sha256" / forged_digest[:2] / f"{forged_digest}.json"
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_bytes(forged_bytes)
    head_path = root / "head.json"
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["head_state_sha256"] = forged_digest
    head_path.write_bytes(_canonical_bytes(head))
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_inspect(root=root)
    assert failure.value.reason_code == "RESEARCH_STATE_PREDECESSOR_MATERIAL_UNBOUND"


def test_partial_genesis_has_explicit_nondestructive_reset_path(tmp_path: Path) -> None:
    module = _load_runtime()
    root = tmp_path / "series"
    root.mkdir()
    series_path = root / "series.json"
    series_path.write_bytes(
        _canonical_bytes(
            {
                "schema_version": module.RESEARCH_STATE_SERIES_SCHEMA,
                "series_id": "xrs_20260731T000000_0123456789ab",
                "created_at": "2026-07-31T00:00:00Z",
            }
        )
    )
    with pytest.raises(module.XinaoError) as failure:
        module.research_state_inspect(root=root)
    assert failure.value.reason_code == "RESEARCH_STATE_CRASH_INCONSISTENT"
    recovered = module.research_state_recover_partial(root=root)
    assert recovered["status"] == "PARTIAL_GENESIS_RESET"
    assert recovered["orphan_cas_preserved"] is True
    assert not series_path.exists()
    genesis = module.research_state_genesis(
        root=root,
        question="retry after explicit partial reset",
        research_fn=_FakeResearch(tmp_path / "run", "retry"),
    )
    assert genesis["status"] == "GENESIS_COMMITTED"


def test_research_state_parser_is_additive_and_bare_research_unchanged(tmp_path: Path) -> None:
    module = _load_runtime()
    genesis = module._parser().parse_args(
        ["research-state", "genesis", "--root", str(tmp_path), "--question", "q0"]
    )
    assert genesis.command == "research-state"
    assert genesis.research_state_command == "genesis"
    advance = module._parser().parse_args(
        [
            "research-state",
            "advance",
            "--root",
            str(tmp_path),
            "--expected-head",
            "a" * 64,
            "--question",
            "q1",
        ]
    )
    assert advance.research_state_command == "advance"
    recover = module._parser().parse_args(
        ["research-state", "recover-partial", "--root", str(tmp_path)]
    )
    assert recover.research_state_command == "recover-partial"
    bare = module._parser().parse_args(["research", "--question", "still one shot"])
    assert bare.command == "research"
    assert not hasattr(bare, "research_state_command")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--probe":
    raise SystemExit(_probe_main(sys.argv[2:]))
