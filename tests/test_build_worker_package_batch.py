from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest
from scripts import build_worker_package_batch as builder
from scripts import validate_worker_package_batch as preflight
from services.agent_runtime.dispatch_economics import (
    DispatchEconomicsError,
    validate_dispatch_envelope,
    validate_package_batch_manifest,
)
from tests.test_dispatch_economics import (
    _fixture,
    _owner_adoption_event,
    _owner_event,
    _seal_dispatch,
    _worker_event,
)


def _logical_spec(
    fixture: dict[str, object],
    *,
    rewrite: Callable[[str], str] | None = None,
) -> dict[str, object]:
    manifest = fixture["manifest"]

    def logical(value: object) -> str:
        text = str(value)
        return rewrite(text) if rewrite else text

    packages = []
    for package in manifest["packages"]:
        acceptance = copy.deepcopy(package["acceptance"])
        schema_ref = acceptance.pop("json_schema_ref", None)
        if schema_ref:
            acceptance["json_schema_path"] = logical(schema_ref["path"])
        row = {
            "package_id": package["package_id"],
            "work_key": package["work_key"],
            "work_class": package["work_class"],
            "role": package["role"],
            "phase": package["phase"],
            "prompt_path": logical(package["prompt_ref"]["path"]),
            "context_manifest_path": logical(package["context_manifest_ref"]["path"]),
            "input_paths": [logical(item["path"]) for item in package["input_refs"]],
            "rules_sha256": package["rules_sha256"],
            "output_contract_sha256": package["output_contract_sha256"],
            "write_domains": list(package["write_domains"]),
            "candidate_only": package["candidate_only"],
            "allowed_output_root": logical(package["allowed_output_root"]),
            "cwd": logical(package["cwd"]),
            "depends_on": copy.deepcopy(package["depends_on"]),
            "acceptance": acceptance,
            "timeout_sec": package["timeout_sec"],
        }
        if package.get("prior_attempt_receipt_ref"):
            row["prior_attempt_receipt_ref"] = {
                "path": logical(package["prior_attempt_receipt_ref"]["path"])
            }
        packages.append(row)
    return {
        "schema_version": "xinao.worker_package_batch_spec.v1",
        "parent_work_key": manifest["parent_work_key"],
        "candidate_output_base": logical(manifest["candidate_output_base"]),
        "epoch_id": "epoch-1",
        "graph_revision": manifest["graph_revision"],
        "predecessor_manifest_ref": copy.deepcopy(manifest["predecessor_manifest_ref"]),
        "reseal_of": copy.deepcopy(manifest["reseal_of"]),
        "affected_cone": list(manifest["affected_cone"]),
        "limits": copy.deepcopy(manifest["limits"]),
        "packages": packages,
    }


def _read_json(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _route_receipt(transport_id: str) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "xinao.supervisor_worker_decision_receipt.v1",
        "decision": "selected",
        "selected_candidate": {
            "provider_id": "grok_acpx_headless",
            "profile_ref": "grok.com.cached_profile",
            "model_id": "grok-4.5",
            "transport_id": transport_id,
            "declared_active": True,
            "healthy": True,
            "positive_benefit": True,
        },
    }
    receipt["decision_sha256"] = builder._canonical_sha(receipt)
    return receipt


def test_route_bound_envelopes_keep_neutral_manifest_bytes_but_not_dispatch_identity(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    manifest = builder.build_neutral_manifest(_logical_spec(fixture))
    manifest_path = tmp_path / "neutral.json"
    manifest_ref = {
        "path": str(manifest_path),
        "sha256": builder._atomic_json(manifest_path, manifest),
    }
    manifest_bytes = manifest_path.read_bytes()
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    a_receipt = _route_receipt("direct-grok-worker-pool")
    b_receipt = _route_receipt("temporal-docker-langgraph")
    a = builder.build_route_bound_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=["p1"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=a_receipt,
        selection_ref={"path": "selection-a.json", "sha256": "1" * 64},
    )
    b = builder.build_route_bound_dispatch_envelope(
        leg="B",
        manifest_ref=manifest_ref,
        package_ids=["p1"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=b_receipt,
        selection_ref={"path": "selection-b.json", "sha256": "2" * 64},
    )

    assert a["package_manifest_ref"] == b["package_manifest_ref"] == manifest_ref
    assert manifest_path.read_bytes() == manifest_bytes
    assert a["selection"]["transport_id"] == "direct-grok-worker-pool"
    assert "execution_adapter" not in a
    assert b["selection"]["transport_id"] == "temporal-docker-langgraph"
    assert b["execution_adapter"]["provider_transport_id"] == "grok_cli_json"
    assert (
        a["selection"]["route_decision_binding_sha256"]
        != b["selection"]["route_decision_binding_sha256"]
    )


def test_route_bound_envelope_rejects_wrong_leg_and_selector_capability_claim() -> None:
    kwargs = {
        "manifest_ref": {"path": "manifest.json", "sha256": "1" * 64},
        "package_ids": ["p1"],
        "epoch_id": "epoch-1",
        "snapshot": {"snapshot_id": "snapshot-1"},
        "snapshot_ref": {"path": "quota.json", "sha256": "2" * 64},
        "selection_ref": {"path": "selection.json", "sha256": "3" * 64},
    }
    with pytest.raises(ValueError, match="transport_id"):
        builder.build_route_bound_dispatch_envelope(
            leg="A",
            selection=_route_receipt("temporal-docker-langgraph"),
            **kwargs,
        )
    fake = _route_receipt("direct-grok-worker-pool")
    fake["selected_candidate"]["capability_binding_sha256"] = "4" * 64
    fake.pop("decision_sha256")
    fake["decision_sha256"] = builder._canonical_sha(fake)
    with pytest.raises(ValueError, match="must not claim provider capability"):
        builder.build_route_bound_dispatch_envelope(
            leg="A",
            selection=fake,
            **kwargs,
        )


def test_builder_keeps_one_neutral_manifest_for_host_a_and_docker_b(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path / "physical")
    physical_root = str(Path(fixture["root"]))
    logical_root = "D:/XINAO_RESEARCH_RUNTIME/shared-dispatch"

    def to_logical(value: str) -> str:
        return value.replace(physical_root, logical_root).replace("\\", "/")

    def host_resolver(logical: str) -> Path:
        return Path(logical.replace(logical_root, physical_root))

    def docker_resolver(logical: str) -> Path:
        # Distinct resolver identity; its return stands in for Docker's mounted file.
        return Path(logical.replace(logical_root, physical_root))

    spec = _logical_spec(fixture, rewrite=to_logical)
    manifest = builder.build_neutral_manifest(spec, path_resolver=host_resolver)
    plan = builder.plan_worker_dispatch(manifest, path_resolver=host_resolver)
    assert plan["worker_package_ids"] == ["p1"]
    assert plan["unresolved_pin_package_ids"] == ["p2"]
    assert manifest["graph_revision"] == 1
    assert manifest["limits"] == {
        "max_parallel": 2,
        "fan_in_capacity": 1,
        "candidate_ingestion_capacity": 2,
    }
    assert manifest["packages"][0]["prompt_ref"]["path"].startswith(logical_root)

    manifest_path = Path(fixture["root"]) / "neutral-manifest.json"
    manifest_sha = builder._atomic_json(manifest_path, manifest)
    raw_before = manifest_path.read_bytes()
    manifest_ref = {
        "path": f"{logical_root}/neutral-manifest.json",
        "sha256": manifest_sha,
    }
    quota_path = Path(str(fixture["quota_ref"]["path"]))
    selection_a_path = Path(fixture["root"]) / "selection-a.json"
    selection_b_path = Path(fixture["root"]) / "selection-b.json"
    selection_a = _route_receipt("direct-grok-worker-pool")
    selection_b = _route_receipt("temporal-docker-langgraph")
    _write_json(selection_a_path, selection_a)
    _write_json(selection_b_path, selection_b)
    selection_ref = {
        "path": to_logical(str(selection_a_path)),
        "sha256": builder._sha(selection_a_path),
    }
    selection_b_ref = {
        "path": to_logical(str(selection_b_path)),
        "sha256": builder._sha(selection_b_path),
    }
    quota_ref = {
        "path": to_logical(str(quota_path)),
        "sha256": fixture["quota_ref"]["sha256"],
    }
    snapshot = _read_json(str(quota_path))
    envelope_a = builder.build_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=plan["worker_package_ids"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=quota_ref,
        selection=selection_a,
        selection_ref=selection_ref,
    )
    envelope_b = builder.build_dispatch_envelope(
        leg="B",
        manifest_ref=manifest_ref,
        package_ids=plan["worker_package_ids"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=quota_ref,
        selection=selection_b,
        selection_ref=selection_b_ref,
    )
    validated_a = validate_dispatch_envelope(envelope_a, path_resolver=host_resolver)
    validated_b = validate_dispatch_envelope(envelope_b, path_resolver=docker_resolver)
    assert validated_a["package_manifest_ref"] == validated_b["package_manifest_ref"]
    assert (
        validated_a["validated_package_manifest"]["validated_manifest_sha256"]
        == validated_b["validated_package_manifest"]["validated_manifest_sha256"]
    )
    assert manifest_path.read_bytes() == raw_before
    assert physical_root.encode() not in raw_before
    assert preflight.validate_manifest_and_envelopes(
        manifest,
        [envelope_a],
        path_resolver=host_resolver,
    )["worker_admitted_package_ids"] == ["p1"]
    assert preflight.validate_manifest_and_envelopes(
        manifest,
        [envelope_b],
        path_resolver=docker_resolver,
    )["worker_admitted_package_ids"] == ["p1"]
    with pytest.raises(DispatchEconomicsError, match="dual-dispatched"):
        preflight.validate_manifest_and_envelopes(
            manifest,
            [envelope_a, envelope_b],
            path_resolver=host_resolver,
        )


def test_builder_filters_owner_and_unpinned_packages_before_worker_envelope(
    tmp_path: Path,
) -> None:
    owner_fixture = _fixture(tmp_path / "owner", second_candidate_only=False)
    owner_spec = _logical_spec(owner_fixture)
    owner_spec["packages"][1]["depends_on"] = []
    owner_spec["limits"]["candidate_ingestion_capacity"] = 1
    owner_manifest = builder.build_neutral_manifest(owner_spec)
    owner_plan = builder.plan_worker_dispatch(owner_manifest)
    assert [row["package_id"] for row in owner_plan["frontier"]["admitted"]] == ["p1", "p2"]
    assert owner_plan["worker_package_ids"] == ["p1"]
    assert owner_plan["owner_package_ids"] == ["p2"]

    owner_saturated = builder.plan_worker_dispatch(
        owner_manifest,
        pending_owner_authority_count=1,
    )
    assert owner_saturated["worker_package_ids"] == ["p1"]
    assert owner_saturated["frontier"]["pending_owner_ready_package_ids"] == ["p2"]
    candidate_saturated = builder.plan_worker_dispatch(
        owner_manifest,
        pending_candidate_ingestion_count=1,
    )
    assert candidate_saturated["worker_package_ids"] == []
    assert candidate_saturated["owner_package_ids"] == ["p2"]
    assert candidate_saturated["frontier"]["pending_candidate_ready_package_ids"] == ["p1"]

    invalid_capacity = copy.deepcopy(owner_spec)
    invalid_capacity["limits"]["candidate_ingestion_capacity"] = 0
    with pytest.raises(DispatchEconomicsError, match="candidate_ingestion_capacity"):
        builder.build_neutral_manifest(invalid_capacity)
    invalid_owner_capacity = copy.deepcopy(owner_spec)
    invalid_owner_capacity["limits"]["fan_in_capacity"] = 0
    with pytest.raises(DispatchEconomicsError, match="fan_in_capacity"):
        builder.build_neutral_manifest(invalid_owner_capacity)

    candidate_fixture = _fixture(tmp_path / "candidate")
    candidate_manifest = builder.build_neutral_manifest(_logical_spec(candidate_fixture))
    candidate_plan = builder.plan_worker_dispatch(candidate_manifest)
    assert candidate_plan["worker_package_ids"] == ["p1"]
    assert candidate_plan["unresolved_pin_package_ids"] == ["p2"]
    assert "p2" not in candidate_plan["worker_package_ids"]


def test_validator_rejects_ready_candidate_outside_bounded_admitted_frontier(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    spec = _logical_spec(fixture)
    spec["packages"][1]["depends_on"] = []
    spec["limits"]["max_parallel"] = 1
    manifest = builder.build_neutral_manifest(spec)
    plan = builder.plan_worker_dispatch(manifest)
    assert plan["worker_package_ids"] == ["p1"]
    assert plan["frontier"]["pending_ready_package_ids"] == ["p2"]
    manifest_path = tmp_path / "bounded-manifest.json"
    manifest_ref = {
        "path": str(manifest_path),
        "sha256": builder._atomic_json(manifest_path, manifest),
    }
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    selection_path = tmp_path / "selection-a.json"
    selection = _route_receipt("direct-grok-worker-pool")
    _write_json(selection_path, selection)
    selection_ref = {
        "path": str(selection_path),
        "sha256": builder._sha(selection_path),
    }
    envelope = builder.build_dispatch_envelope(
        leg="A",
        manifest_ref=manifest_ref,
        package_ids=["p2"],
        epoch_id="epoch-1",
        snapshot=snapshot,
        snapshot_ref=fixture["quota_ref"],
        selection=selection,
        selection_ref=selection_ref,
    )
    with pytest.raises(DispatchEconomicsError, match="outside the admitted worker frontier"):
        preflight.validate_manifest_and_envelopes(manifest, [envelope])


def test_builder_admits_typed_pin_only_after_real_owner_event_and_rejects_wrong_type(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    predecessor_ref, envelope_ref, _ = _seal_dispatch(fixture, suffix="-r1")
    _, worker_ref, artifact_ref = _worker_event(
        fixture,
        package_id="p1",
        manifest_ref=predecessor_ref,
        envelope_ref=envelope_ref,
    )
    _, owner_verdict_ref = _owner_event(
        fixture,
        provider_ref=worker_ref,
        artifact_ref=artifact_ref,
    )
    _, owner_ref = _owner_adoption_event(
        fixture,
        owner_verdict_ref=owner_verdict_ref,
        artifact_ref=artifact_ref,
    )
    predecessor = validate_package_batch_manifest(fixture["manifest"])
    revision_two_spec = _logical_spec(fixture)
    revision_two_spec.update(
        graph_revision=2,
        predecessor_manifest_ref=predecessor_ref,
        reseal_of={
            "package_id": "p2",
            "package_identity_sha256": predecessor["packages"][1]["package_identity_sha256"],
            "graph_revision": 1,
        },
        affected_cone=["p2"],
    )
    revision_two_spec["packages"][1]["depends_on"][0]["pin"] = {
        "event_ref": owner_ref,
        "artifact_ref": artifact_ref,
    }
    revision_two = builder.build_neutral_manifest(revision_two_spec)
    plan = builder.plan_worker_dispatch(revision_two)
    assert revision_two["graph_revision"] == 2
    assert revision_two["predecessor_manifest_ref"] == predecessor_ref
    assert revision_two["reseal_of"]["package_id"] == "p2"
    assert revision_two["affected_cone"] == ["p2"]
    assert plan["worker_package_ids"] == ["p2"]
    assert plan["frontier"]["terminal_package_ids"] == ["p1"]

    wrong_type = copy.deepcopy(revision_two_spec)
    wrong_type["packages"][1]["depends_on"][0]["pin"]["event_ref"] = worker_ref
    with pytest.raises(DispatchEconomicsError, match="typed condition"):
        builder.build_neutral_manifest(wrong_type)

    wrong_cone = copy.deepcopy(revision_two_spec)
    wrong_cone["affected_cone"] = ["p1", "p2"]
    with pytest.raises(DispatchEconomicsError, match="affected_cone"):
        builder.build_neutral_manifest(wrong_cone)

    wrong_revision = copy.deepcopy(revision_two_spec)
    wrong_revision["graph_revision"] = 1
    with pytest.raises(DispatchEconomicsError, match="initial graph revision"):
        builder.build_neutral_manifest(wrong_revision)
    wrong_predecessor = copy.deepcopy(revision_two_spec)
    wrong_predecessor["predecessor_manifest_ref"]["sha256"] = "0" * 64
    with pytest.raises(DispatchEconomicsError, match="predecessor_manifest_ref sha256 mismatch"):
        builder.build_neutral_manifest(wrong_predecessor)
    wrong_reseal = copy.deepcopy(revision_two_spec)
    wrong_reseal["reseal_of"]["package_identity_sha256"] = "0" * 64
    with pytest.raises(DispatchEconomicsError, match="reseal_of package identity mismatch"):
        builder.build_neutral_manifest(wrong_reseal)


def test_builder_cli_emits_one_route_at_a_time_and_preserves_neutral_bytes(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "inputs")
    spec_path = tmp_path / "spec.json"
    resolution_path = tmp_path / "quota-resolution.json"
    manifest_a_path = tmp_path / "manifest-a.json"
    manifest_b_path = tmp_path / "manifest-b.json"
    envelope_a_path = tmp_path / "envelope-a.json"
    envelope_b_path = tmp_path / "envelope-b.json"
    selection_a_path = tmp_path / "selection-a.json"
    selection_b_path = tmp_path / "selection-b.json"
    _write_json(spec_path, _logical_spec(fixture))
    _write_json(selection_a_path, _route_receipt("direct-grok-worker-pool"))
    _write_json(selection_b_path, _route_receipt("temporal-docker-langgraph"))
    snapshot = _read_json(str(fixture["quota_ref"]["path"]))
    _write_json(
        resolution_path,
        {
            "snapshot": {
                **snapshot,
                "snapshot_ref": fixture["quota_ref"]["path"],
            }
        },
    )
    dual = subprocess.run(
        [
            sys.executable,
            str(Path(builder.__file__)),
            "--spec",
            str(spec_path),
            "--quota-resolution",
            str(resolution_path),
            "--selection-receipt-a",
            str(selection_a_path),
            "--selection-receipt-b",
            str(selection_b_path),
            "--output",
            str(tmp_path / "must-not-exist.json"),
            "--dispatch-output-a",
            str(envelope_a_path),
            "--dispatch-output-b",
            str(envelope_b_path),
        ],
        cwd=Path(builder.__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert dual.returncode == 20
    assert "mutually exclusive route alternatives" in dual.stderr

    def build_one(leg: str, manifest_path: Path, envelope_path: Path) -> dict[str, object]:
        receipt_path = selection_a_path if leg == "A" else selection_b_path
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(builder.__file__)),
                "--spec",
                str(spec_path),
                "--quota-resolution",
                str(resolution_path),
                f"--selection-receipt-{leg.lower()}",
                str(receipt_path),
                "--output",
                str(manifest_path),
                f"--dispatch-output-{leg.lower()}",
                str(envelope_path),
            ],
            cwd=Path(builder.__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result["worker_package_ids"] == ["p1"]
        assert result["unresolved_pin_package_ids"] == ["p2"]
        assert result["selected_leg"] == leg
        return result

    build_one("A", manifest_a_path, envelope_a_path)
    build_one("B", manifest_b_path, envelope_b_path)
    assert manifest_a_path.read_bytes() == manifest_b_path.read_bytes()
    envelope_a = _read_json(str(envelope_a_path))
    envelope_b = _read_json(str(envelope_b_path))
    assert envelope_a["package_ids"] == envelope_b["package_ids"] == ["p1"]
    assert envelope_a["leg"] == "A"
    assert envelope_b["leg"] == "B"
    assert envelope_a["selection"]["transport_id"] == "direct-grok-worker-pool"
    assert envelope_b["selection"]["transport_id"] == "temporal-docker-langgraph"
    assert envelope_b["execution_adapter"]["provider_transport_id"] == "grok_cli_json"

    for manifest_path, envelope_path in (
        (manifest_a_path, envelope_a_path),
        (manifest_b_path, envelope_b_path),
    ):
        validate = subprocess.run(
            [
                sys.executable,
                str(Path(preflight.__file__)),
                "--manifest",
                str(manifest_path),
                "--dispatch-envelope",
                str(envelope_path),
                "--plan-initial-frontier",
            ],
            cwd=Path(preflight.__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert validate.returncode == 0, validate.stderr
        assert json.loads(validate.stdout)["worker_admitted_package_ids"] == ["p1"]
