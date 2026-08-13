from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import services.agent_runtime.taste_codex_shadow as native_module
import services.agent_runtime.taste_corpus as corpus_module
import services.agent_runtime.taste_live_retrieval as live_module
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_live_retrieval import (
    TasteLiveRetrievalError,
    activate_native_qualified_taste,
    render_qualified_taste_context,
    verify_live_activation_card,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _projection(label: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "s.taste_source_projection.v1",
            "mode": "source_contrastive_episode",
            "episodes": [
                {
                    "prefix": [
                        {
                            "event_id": f"evt_{'1' * 64}",
                            "role": "user",
                            "content": f"{label} compress the repository snapshot",
                        }
                    ],
                    "bad_continuation": {
                        "event_id": f"evt_{'2' * 64}",
                        "role": "assistant",
                        "content": "build three proof packages and audit the whole machine",
                    },
                    "human_corrections": [
                        {
                            "event_id": f"evt_{'3' * 64}",
                            "role": "user",
                            "content": "only the current repository snapshot was requested",
                        }
                    ],
                    "desired_continuation": {
                        "event_id": f"evt_{'4' * 64}",
                        "role": "assistant",
                        "content": "inspect current HEAD tracked dirty ignored and live bytes",
                    },
                }
            ],
        }
    )


def _write_chain(root: Path, *, label: str, qualified: bool = True) -> dict[str, Path]:
    paths = {name: root / name for name in ("source", "evaluation", "plan", "pair", "score")}
    for path in paths.values():
        path.mkdir(parents=True)
    (paths["source"] / "projection.json").write_bytes(_projection(label))
    for name in ("evaluation", "plan", "pair"):
        (paths[name] / "identity.bin").write_bytes(f"{name}-{label}".encode())
    (paths["score"] / "qualified.json").write_text(
        json.dumps({"qualified": qualified}), encoding="utf-8"
    )
    return paths


@pytest.fixture
def native_verifier_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    def verify_plan(plan_dir: Path, *, source_dir: Path, evaluation_dir: Path) -> dict[str, object]:
        projection = (Path(source_dir) / "projection.json").read_bytes()
        plan_raw = (Path(plan_dir) / "identity.bin").read_bytes()
        evaluation_raw = (Path(evaluation_dir) / "identity.bin").read_bytes()
        candidate_sha = _sha(b"candidate\0" + projection)
        return {
            "source": {
                "source_bundle_sha256": _sha(projection),
                "treatment_condition": projection,
            },
            "evaluation": {"evaluation_bundle_sha256": _sha(evaluation_raw)},
            "plan_bundle_sha256": _sha(plan_raw),
            "candidate": {"candidate_sha256": candidate_sha},
        }

    def verify_pair(
        pair_dir: Path, *, plan_dir: Path, source_dir: Path, evaluation_dir: Path
    ) -> dict[str, object]:
        verify_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
        return {"pair_bundle_sha256": _sha((Path(pair_dir) / "identity.bin").read_bytes())}

    def verify_score(
        score_dir: Path,
        *,
        pair_dir: Path,
        plan_dir: Path,
        source_dir: Path,
        evaluation_dir: Path,
    ) -> dict[str, object]:
        plan = verify_plan(plan_dir, source_dir=source_dir, evaluation_dir=evaluation_dir)
        verify_pair(
            pair_dir,
            plan_dir=plan_dir,
            source_dir=source_dir,
            evaluation_dir=evaluation_dir,
        )
        raw = (Path(score_dir) / "qualified.json").read_bytes()
        qualified = json.loads(raw)["qualified"] is True
        receipt_unsigned = {
            "schema_version": "xinao.taste_qualification_receipt.v1",
            "authority": False,
            "completion_claim_allowed": False,
            "qualified": True,
            "candidate_sha256": plan["candidate"]["candidate_sha256"],
            "baseline_outcome_sha256": _sha(b"baseline-outcome"),
            "treatment_outcome_sha256": _sha(b"treatment-outcome"),
            "bindings": {"test_fixture": True},
            "comparisons": {"target_failure": {"improvement": 1}},
            "cold_controls": {
                "fresh_distinct_runs": True,
                "cache_used": False,
                "hooks_enabled": False,
                "oracle_exposed": False,
                "live_retrieval_used": False,
                "hot_mutation_used": False,
                "trajectories_sealed": True,
            },
        }
        receipt = {
            **receipt_unsigned,
            "receipt_sha256": _sha(canonical_json_bytes(receipt_unsigned)),
        }
        return {
            "score_bundle_sha256": _sha(raw),
            "qualified": qualified,
            "qualification_receipt": receipt if qualified else None,
        }

    monkeypatch.setattr(corpus_module, "verify_qualification_plan", verify_plan)
    monkeypatch.setattr(native_module, "verify_codex_shadow_pair", verify_pair)
    monkeypatch.setattr(native_module, "verify_codex_shadow_score", verify_score)


def test_unqualified_native_chain_never_creates_a_live_root(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=False)
    activation_root = tmp_path / "activated"

    with pytest.raises(TasteLiveRetrievalError) as raised:
        activate_native_qualified_taste(
            score_dir=paths["score"],
            pair_dir=paths["pair"],
            plan_dir=paths["plan"],
            source_dir=paths["source"],
            evaluation_dir=paths["evaluation"],
            activation_root=activation_root,
        )

    assert raised.value.reason_code == "NOT_QUALIFIED"
    assert not activation_root.exists()


def test_qualified_card_is_recomputed_and_retrieved_only_when_relevant(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    activation_root = tmp_path / "activated"
    activated = activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )
    card = verify_live_activation_card(Path(str(activated["activation_directory"])))

    assert card["candidate_sha256"] == activated["candidate_sha256"]
    related = render_qualified_taste_context(
        "please compress the current repository snapshot",
        activation_root=activation_root,
        cwd=REPO_ROOT,
    )
    assert related.count("[QUALIFIED CONTRASTIVE TASTE") == 1
    assert "BAD CONTINUATION TO AVOID" in related
    assert "only the current repository snapshot was requested" in related
    assert "please compress" not in related
    assert (
        render_qualified_taste_context(
            "weather forecast for tomorrow",
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )
    assert (
        render_qualified_taste_context(
            "please continue with the current S repository work",
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )
    assert (
        render_qualified_taste_context(
            "current repository snapshot",
            activation_root=activation_root,
            cwd=tmp_path,
        )
        == ""
    )


def test_tampered_activated_chain_fails_open_without_prompt_injection(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    activation_root = tmp_path / "activated"
    activated = activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )
    card_root = Path(str(activated["activation_directory"]))
    (card_root / "source_projection.json").write_bytes(_projection("tampered"))

    with pytest.raises(TasteLiveRetrievalError):
        verify_live_activation_card(card_root)
    assert (
        render_qualified_taste_context(
            "current repository snapshot",
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )


def test_self_sealed_stub_receipt_cannot_forge_a_live_card(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    activation_root = tmp_path / "activated"
    activated = activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )
    card_root = Path(str(activated["activation_directory"]))
    manifest = json.loads((card_root / "manifest.json").read_bytes())
    stub_unsigned = {
        "authority": False,
        "completion_claim_allowed": False,
        "qualified": True,
        "candidate_sha256": manifest["chain"]["candidate_sha256"],
    }
    stub = {
        **stub_unsigned,
        "receipt_sha256": _sha(canonical_json_bytes(stub_unsigned)),
    }
    stub_raw = canonical_json_bytes(stub)
    (card_root / "qualification_receipt.json").write_bytes(stub_raw)
    manifest["chain"]["qualification_receipt_sha256"] = stub["receipt_sha256"]
    manifest["files"]["qualification_receipt"] = {
        "relative_path": "qualification_receipt.json",
        "sha256": _sha(stub_raw),
        "size_bytes": len(stub_raw),
    }
    manifest.pop("activation_sha256")
    manifest["activation_sha256"] = _sha(canonical_json_bytes(manifest))
    (card_root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    forged_root = card_root.with_name(manifest["activation_sha256"])
    card_root.rename(forged_root)

    with pytest.raises(TasteLiveRetrievalError):
        verify_live_activation_card(forged_root)
    assert (
        render_qualified_taste_context(
            "compress the current repository snapshot",
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )


def test_activation_root_cannot_traverse_a_link_or_junction_ancestor(
    tmp_path: Path,
    native_verifier_stubs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    redirected_parent = tmp_path / "redirected"
    redirected_parent.mkdir()
    activation_root = redirected_parent / "activated"
    original_is_link = live_module._is_link
    monkeypatch.setattr(
        live_module,
        "_is_link",
        lambda path: Path(path) == redirected_parent or original_is_link(Path(path)),
    )

    with pytest.raises(TasteLiveRetrievalError) as raised:
        activate_native_qualified_taste(
            score_dir=paths["score"],
            pair_dir=paths["pair"],
            plan_dir=paths["plan"],
            source_dir=paths["source"],
            evaluation_dir=paths["evaluation"],
            activation_root=activation_root,
        )

    assert raised.value.reason_code == "ACTIVATION_ROOT_INVALID"
    assert not activation_root.exists()


def test_selector_renders_at_most_one_of_multiple_relevant_cards(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    activation_root = tmp_path / "activated"
    for label in ("snapshot alpha", "snapshot beta"):
        paths = _write_chain(tmp_path / label.replace(" ", "-"), label=label, qualified=True)
        activate_native_qualified_taste(
            score_dir=paths["score"],
            pair_dir=paths["pair"],
            plan_dir=paths["plan"],
            source_dir=paths["source"],
            evaluation_dir=paths["evaluation"],
            activation_root=activation_root,
        )

    context = render_qualified_taste_context(
        "compress repository snapshot alpha beta",
        activation_root=activation_root,
        cwd=REPO_ROOT,
    )
    assert context.count("[QUALIFIED CONTRASTIVE TASTE") == 1


def test_hot_retrieval_never_replays_the_cold_native_chain(
    tmp_path: Path,
    native_verifier_stubs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    activation_root = tmp_path / "activated"
    activated = activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )

    def cold_replay_forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("the UserPromptSubmit hot path replayed cold Taste evidence")

    monkeypatch.setattr(corpus_module, "verify_qualification_plan", cold_replay_forbidden)
    monkeypatch.setattr(native_module, "verify_codex_shadow_pair", cold_replay_forbidden)
    monkeypatch.setattr(native_module, "verify_codex_shadow_score", cold_replay_forbidden)

    card_root = Path(str(activated["activation_directory"]))
    assert {path.name for path in card_root.iterdir()} == {
        "manifest.json",
        "qualification_receipt.json",
        "source_projection.json",
    }
    assert "QUALIFIED CONTRASTIVE TASTE" in render_qualified_taste_context(
        "compress the repository snapshot now",
        activation_root=activation_root,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize(
    "prompt",
    (
        "当前仓库状态是什么",
        "看看当前仓库",
        "当前仓库有多少修改",
    ),
)
def test_one_common_chinese_object_phrase_does_not_count_as_three_concepts(
    tmp_path: Path,
    native_verifier_stubs: None,
    prompt: str,
) -> None:
    paths = _write_chain(tmp_path / "cold", label="把当前仓库完整压缩", qualified=True)
    activation_root = tmp_path / "activated"
    activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )

    assert (
        render_qualified_taste_context(
            prompt,
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )
    assert "QUALIFIED CONTRASTIVE TASTE" in render_qualified_taste_context(
        "请把当前仓库压缩成快照",
        activation_root=activation_root,
        cwd=REPO_ROOT,
    )


def test_sensitive_source_contrast_is_never_rendered(
    tmp_path: Path, native_verifier_stubs: None
) -> None:
    paths = _write_chain(tmp_path / "cold", label="snapshot", qualified=True)
    projection = json.loads((paths["source"] / "projection.json").read_text(encoding="utf-8"))
    projection["episodes"][0]["human_corrections"][0]["content"] = (
        "token = secret-value-that-must-not-enter-the-hook"
    )
    (paths["source"] / "projection.json").write_bytes(canonical_json_bytes(projection))
    activation_root = tmp_path / "activated"
    activate_native_qualified_taste(
        score_dir=paths["score"],
        pair_dir=paths["pair"],
        plan_dir=paths["plan"],
        source_dir=paths["source"],
        evaluation_dir=paths["evaluation"],
        activation_root=activation_root,
    )

    assert (
        render_qualified_taste_context(
            "compress the current repository snapshot",
            activation_root=activation_root,
            cwd=REPO_ROOT,
        )
        == ""
    )
