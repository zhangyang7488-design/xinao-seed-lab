from __future__ import annotations

import dataclasses
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path

import pytest
from services.agent_runtime.effect_gateway import (
    LOGICAL_ROOT_ADOPTION_ADAPTER,
    CurrentOwnerGrant,
    EffectGateway,
    EffectGatewayError,
    EffectGatewayPolicy,
    HashBoundRef,
    build_logical_root_adoption_request,
    logical_root_adoption_binding,
    production_effect_gateway,
)
from services.xinao_perpetual_world_compute.logical_root_runtime import (
    LogicalRootStore,
    RootIdentity,
)
from tests.test_xinao_logical_root_runtime import _make_committed_run


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class StubOwnerBoundary:
    boundary_id = "test-live-owner-boundary"

    def __init__(self) -> None:
        self._pending: dict[str, tuple[CurrentOwnerGrant, object, float]] = {}

    def issue(self, *, request_sha256: str, effect_owner_scope: str) -> CurrentOwnerGrant:
        proof = object()
        grant = CurrentOwnerGrant(
            grant_id=f"grant-{uuid.uuid4().hex}",
            request_sha256=request_sha256,
            effect_owner_scope=effect_owner_scope,
            boundary_id=self.boundary_id,
            issued_at="2026-08-13T12:00:01+00:00",
            _proof=proof,
        )
        self._pending[grant.grant_id] = (grant, proof, time.monotonic())
        return grant

    def consume(
        self,
        *,
        grant: CurrentOwnerGrant,
        request_sha256: str,
        effect_owner_scope: str,
    ) -> dict[str, object]:
        pending = self._pending.pop(grant.grant_id, None)
        if pending is None:
            raise EffectGatewayError("CURRENT_OWNER_GRANT_CONSUMED", grant.grant_id)
        issued, proof, _ = pending
        if issued is not grant or grant._proof is not proof:  # noqa: SLF001
            raise EffectGatewayError("CURRENT_OWNER_GRANT_REQUIRED", grant.grant_id)
        if (
            grant.request_sha256 != request_sha256
            or grant.effect_owner_scope != effect_owner_scope
        ):
            raise EffectGatewayError("CURRENT_OWNER_GRANT_MISMATCH", grant.grant_id)
        return grant.evidence_dict()


def _fixture(tmp_path: Path, *, fault_injector=None):
    source_root = tmp_path / "source-runtime"
    run = _make_committed_run(
        source_root,
        account_slot="A",
        run_name="gateway-a-run-001",
        root_output=b"selected root cognition\n",
    )
    reality_root = tmp_path / "effect-reality"
    blind_root = tmp_path / "effect-blind"
    reality_path = reality_root / "current.json"
    blind_path = blind_root / "cutoff.json"
    reality_path.parent.mkdir(parents=True)
    blind_path.parent.mkdir(parents=True)
    reality_path.write_text('{"price":"current","world":"observed"}\n', encoding="utf-8")
    blind_path.write_text('{"cutoff":"2026-08-13T12:00:00Z"}\n', encoding="utf-8")
    logical_store = LogicalRootStore(
        tmp_path / "logical-root",
        clock=lambda: "2026-08-13T12:00:00+00:00",
    )
    request = build_logical_root_adoption_request(
        logical_store,
        request_id="adopt-gateway-a-001",
        effect_owner_scope="experiment-effect-owner",
        source_run_dir=run.run_dir,
        account_slot="A",
        expected_predecessor=RootIdentity.genesis(),
        reality_refs=(HashBoundRef.capture("current-reality", reality_path),),
        blind_boundary_refs=(HashBoundRef.capture("blind-input-cutoff", blind_path),),
    )
    policy = EffectGatewayPolicy(
        gateway_root=tmp_path / "effect-gateway",
        logical_root=logical_store.root,
        allowed_source_roots=(source_root,),
        allowed_reality_roots=(reality_root,),
        allowed_blind_roots=(blind_root,),
        reality_labels=frozenset({"current-reality"}),
        blind_labels=frozenset({"blind-input-cutoff"}),
    )
    boundary = StubOwnerBoundary()
    gateway = EffectGateway(
        policy,
        adapters={LOGICAL_ROOT_ADOPTION_ADAPTER: logical_root_adoption_binding(logical_store)},
        owner_boundary=boundary,
        clock=lambda: "2026-08-13T12:00:02+00:00",
        fault_injector=fault_injector,
    )
    return run, reality_path, blind_path, logical_store, request, gateway, boundary, policy


def test_live_boundary_adopts_exact_candidate_and_seals_receipt(tmp_path: Path) -> None:
    run, _, _, logical_store, request, gateway, _, _ = _fixture(tmp_path)

    result = gateway.invoke_as_current_owner(request)

    assert result.replayed is False
    assert logical_store.read_current_artifact() == run.root_output
    receipt = result.receipt
    assert receipt["request"]["candidate_sha256"] == request.candidate_sha256
    assert receipt["request"]["source_run_sha256"] == request.source_run_sha256
    assert receipt["request"]["root_output_sha256"] == _sha(run.root_output)
    assert receipt["request"]["expected_predecessor"] == RootIdentity.genesis().to_dict()
    assert receipt["adapter_outcome"]["effect_identity"]["generation"] == 1
    grant_evidence = receipt["owner_grant_evidence"]
    assert grant_evidence["boundary_id"] == "test-live-owner-boundary"
    assert grant_evidence["historical_context_can_mint_grant"] is False
    assert "_proof" not in json.dumps(receipt)
    assert receipt["effect_boundary"]["process_acl_boundary_proven"] is False

    generation = logical_store.reconstruct_current().receipt
    assert generation is not None
    assert generation["request"]["selection_ref"] == (
        f"effect-gateway-request-sha256:{request.sha256}"
    )


def test_public_gateway_has_no_owner_self_mint_or_raw_invoke_surface(tmp_path: Path) -> None:
    _, _, _, _, request, gateway, _, _ = _fixture(tmp_path)

    assert not hasattr(gateway, "issue_current_owner_invocation")
    assert not hasattr(gateway, "invoke")
    assert not hasattr(gateway, "register_adapter")
    assert callable(gateway.invoke_as_current_owner)

    fake = CurrentOwnerGrant(
        grant_id="grant-forged",
        request_sha256=request.sha256,
        effect_owner_scope=request.effect_owner_scope,
        boundary_id="test-live-owner-boundary",
        issued_at="2026-08-13T12:00:01+00:00",
        _proof=object(),
    )
    with pytest.raises(EffectGatewayError) as rejected:
        gateway._invoke_with_live_grant(request, fake)  # noqa: SLF001
    assert rejected.value.code == "CURRENT_OWNER_GRANT_CONSUMED"


def test_historical_or_copied_grant_cannot_invoke(tmp_path: Path) -> None:
    _, _, _, logical_store, request, gateway, boundary, _ = _fixture(tmp_path)
    issued = boundary.issue(
        request_sha256=request.sha256,
        effect_owner_scope=request.effect_owner_scope,
    )
    copied = dataclasses.replace(issued)

    with pytest.raises(EffectGatewayError) as rejected:
        gateway._invoke_with_live_grant(request, copied)  # noqa: SLF001
    assert rejected.value.code == "CURRENT_OWNER_GRANT_REQUIRED"
    assert logical_store.reconstruct_current().identity == RootIdentity.genesis()

    with pytest.raises(EffectGatewayError) as consumed:
        gateway._invoke_with_live_grant(request, issued)  # noqa: SLF001
    assert consumed.value.code == "CURRENT_OWNER_GRANT_CONSUMED"


def test_same_file_under_two_labels_and_wrong_label_fail_contract(tmp_path: Path) -> None:
    _, reality, _, logical_store, request, gateway, _, _ = _fixture(tmp_path)
    same_file = dataclasses.replace(
        request,
        blind_boundary_refs=(HashBoundRef.capture("blind-input-cutoff", reality),),
    )
    with pytest.raises(EffectGatewayError) as same:
        gateway.invoke_as_current_owner(same_file)
    assert same.value.code == "EVIDENCE_ORIGIN_NOT_INDEPENDENT"
    assert logical_store.reconstruct_current().identity == RootIdentity.genesis()

    wrong_label = dataclasses.replace(
        request,
        reality_refs=(dataclasses.replace(request.reality_refs[0], label="arbitrary"),),
    )
    with pytest.raises(EffectGatewayError) as label:
        gateway.invoke_as_current_owner(wrong_label)
    assert label.value.code == "EVIDENCE_LABEL_INVALID"


def test_alternate_source_or_evidence_root_fails_closed(tmp_path: Path) -> None:
    _, _, _, logical_store, request, gateway, _, _ = _fixture(tmp_path)
    outside = tmp_path / "outside" / "reality.json"
    outside.parent.mkdir()
    outside.write_text("{}\n", encoding="utf-8")
    alternate = dataclasses.replace(
        request,
        reality_refs=(HashBoundRef.capture("current-reality", outside),),
    )

    with pytest.raises(EffectGatewayError) as rejected:
        gateway.invoke_as_current_owner(alternate)

    assert rejected.value.code == "EVIDENCE_ROOT_NOT_ALLOWED"
    assert logical_store.reconstruct_current().identity == RootIdentity.genesis()


@pytest.mark.parametrize(
    "adapter_kind, expected_code",
    [
        ("capital.execute.v1", "ADAPTER_NOT_IMPLEMENTED"),
        ("publication.publish.v1", "ADAPTER_NOT_IMPLEMENTED"),
        ("shared-repository.write.v1", "ADAPTER_NOT_REGISTERED"),
    ],
)
def test_alternate_effect_adapter_fails_closed(
    tmp_path: Path,
    adapter_kind: str,
    expected_code: str,
) -> None:
    _, _, _, logical_store, request, gateway, _, _ = _fixture(tmp_path)
    unsupported = dataclasses.replace(request, adapter_kind=adapter_kind)

    with pytest.raises(EffectGatewayError) as rejected:
        gateway.invoke_as_current_owner(unsupported)

    assert rejected.value.code == expected_code
    assert logical_store.reconstruct_current().identity == RootIdentity.genesis()


def test_receipt_replay_is_readback_only_and_never_reexecutes_effect(tmp_path: Path) -> None:
    _, _, _, logical_store, request, gateway, boundary, policy = _fixture(tmp_path)
    first = gateway.invoke_as_current_owner(request)
    binding = logical_root_adoption_binding(logical_store)

    def must_not_apply(_request, _grant):
        raise AssertionError("receipt replay must not execute apply")

    reopened = EffectGateway(
        policy,
        adapters={
            LOGICAL_ROOT_ADOPTION_ADAPTER: dataclasses.replace(
                binding,
                apply=must_not_apply,
            )
        },
        owner_boundary=boundary,
    )
    replay = reopened.invoke_as_current_owner(request)

    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert logical_store.reconstruct_current().identity.generation == 1


@pytest.mark.parametrize("fault_point", ["after_prepared", "after_effect"])
def test_crash_gap_recovers_without_duplicate_generation(
    tmp_path: Path,
    fault_point: str,
) -> None:
    fired = False

    def crash(point: str) -> None:
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise RuntimeError(f"crash:{point}")

    _, _, _, logical_store, request, gateway, boundary, policy = _fixture(
        tmp_path, fault_injector=crash
    )
    with pytest.raises(RuntimeError, match=fault_point):
        gateway.invoke_as_current_owner(request)

    recovered = EffectGateway(
        policy,
        adapters={LOGICAL_ROOT_ADOPTION_ADAPTER: logical_root_adoption_binding(logical_store)},
        owner_boundary=boundary,
    ).invoke_as_current_owner(request)

    assert recovered.receipt["adapter_outcome"]["effect_identity"]["generation"] == 1
    assert logical_store.reconstruct_current().identity.generation == 1
    transaction = json.loads(
        (policy.gateway_root / "transactions" / f"{request.request_id}.json").read_bytes()
    )
    assert transaction["phase"] == "completed"


def test_stale_predecessor_and_candidate_drift_fail_before_adoption(tmp_path: Path) -> None:
    run, reality, blind, logical_store, request, gateway, _, _ = _fixture(tmp_path)
    gateway.invoke_as_current_owner(request)
    second_run = _make_committed_run(
        tmp_path / "source-runtime",
        account_slot="C",
        run_name="gateway-c-run-002",
        root_output=b"new C candidate\n",
        legacy=True,
    )
    stale = build_logical_root_adoption_request(
        logical_store,
        request_id="adopt-gateway-c-002",
        effect_owner_scope="experiment-effect-owner",
        source_run_dir=second_run.run_dir,
        account_slot="C",
        expected_predecessor=RootIdentity.genesis(),
        reality_refs=(HashBoundRef.capture("current-reality", reality),),
        blind_boundary_refs=(HashBoundRef.capture("blind-input-cutoff", blind),),
    )
    with pytest.raises(EffectGatewayError) as rejected:
        gateway.invoke_as_current_owner(stale)
    assert rejected.value.code == "ADAPTER_REJECTED"
    assert rejected.value.facts["source_code"] == "STALE_PREDECESSOR"
    assert logical_store.read_current_artifact() == run.root_output

    drift = dataclasses.replace(stale, root_output_sha256="f" * 64)
    with pytest.raises(EffectGatewayError) as mismatch:
        gateway.invoke_as_current_owner(drift)
    assert mismatch.value.code in {"IDEMPOTENCY_KEY_CONFLICT", "CANDIDATE_HASH_MISMATCH"}


def test_existing_request_id_cannot_be_rebound(tmp_path: Path) -> None:
    _, _, _, logical_store, request, gateway, _, _ = _fixture(tmp_path)
    gateway.invoke_as_current_owner(request)
    rebound = dataclasses.replace(request, root_output_sha256="e" * 64)

    with pytest.raises(EffectGatewayError) as conflict:
        gateway.invoke_as_current_owner(rebound)

    assert conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert logical_store.reconstruct_current().identity.generation == 1


def test_production_factory_ignores_alternate_roots_and_registry() -> None:
    boundary = StubOwnerBoundary()
    gateway = production_effect_gateway(boundary)

    assert gateway.policy.gateway_root == Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_effect_gateway"
    )
    assert gateway.policy.logical_root == Path(
        r"D:\XINAO_RESEARCH_RUNTIME\state\xinao_logical_root"
    )
    assert set(gateway._adapters) == {LOGICAL_ROOT_ADOPTION_ADAPTER}  # noqa: SLF001


def test_direct_logical_store_remains_outside_gateway_process_acl_claim(tmp_path: Path) -> None:
    """Boundary test: the seam cannot honestly claim OS/process exclusivity yet."""

    run, _, _, logical_store, _, _, _, _ = _fixture(tmp_path)
    direct = logical_store.adopt(
        source_run_dir=run.run_dir,
        account_slot="A",
        expected_predecessor=RootIdentity.genesis(),
        adoption_id="direct-bypass-demonstration",
        selection_ref="direct-call-not-gateway-authorized",
        selected_by="test-only-direct-caller",
    )

    assert direct.adopted.identity.generation == 1
    assert direct.adopted.receipt["request"]["selection_ref"] == (
        "direct-call-not-gateway-authorized"
    )
