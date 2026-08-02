"""Offline unit/contract tests for XINAO researcher provider-egress boundary."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"
EGRESS_ROOT = ROOT / "docker" / "xinao-researcher-egress"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _runtime():
    return _load(SKILL_ROOT / "scripts" / "xinao_runtime.py", "xinao_runtime_egress_test")


def _renderer():
    return _load(EGRESS_ROOT / "render_squid_config.py", "xinao_egress_render_test")


def _sealer():
    return _load(
        EGRESS_ROOT / "scripts" / "owner_seal_live_egress.py",
        "xinao_owner_seal_live_egress_test",
    )


def _sample_posture(**overrides):
    base = {
        "schema_version": "xinao.provider_egress_posture.v1",
        "lifecycle_state": "HEALTHY",
        "internal_network_name": "xinao_researcher_internal",
        "internal_network_id": "net_" + "a" * 16,
        "external_network_name": "xinao_provider_egress_ext",
        "proxy_container_name": "xinao-researcher-egress-proxy",
        "proxy_container_id": "ctr_" + "b" * 16,
        "proxy_image_id": "sha256:" + "c" * 64,
        "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "proxy_listen_port": 3128,
        "allowlist_sha256": "d" * 64,
        "proxy_config_sha256": "e" * 64,
        "provider_domains": [],
        "host_port_published": False,
        "dify_cross_project": False,
        "tls_interception": False,
        "provider_egress_runtime_verified": False,
        "verification_evidence": {"negative_suite": None, "positive_canary": None},
        "secrets_present": False,
    }
    base.update(overrides)
    return base


def _write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    import hashlib

    return hashlib.sha256(payload).hexdigest()


REQUIRED_NEGATIVE_CASE_IDS = (
    "N1",
    "N3",
    "N4",
    "N5",
    "N6",
    "N7",
    "N8",
    "N9",
    "N15",
    "N17",
    "N17b",
    "N17c",
    "N17d",
)


def _iso_z(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _sample_negative_receipt(
    posture: dict | None = None, *, observed_at: str | None = None, **overrides
):
    """Every required seal-eligible semantic field is explicit (no implicit defaults)."""
    p = posture or _sample_posture()
    observed = observed_at or _iso_z(dt.datetime.now(dt.UTC))
    base = {
        "schema_version": "xinao.provider_egress_negative_suite_receipt.v1",
        "path_class": "negative_suite",
        "status": "observed",
        "suite_passed": True,
        "all_cases_passed": True,
        "cases": [{"id": case_id, "ok": True} for case_id in REQUIRED_NEGATIVE_CASE_IDS],
        "pass_count": len(REQUIRED_NEGATIVE_CASE_IDS),
        "fail_count": 0,
        "internal_network_id": p["internal_network_id"],
        "proxy_container_id": p["proxy_container_id"],
        "proxy_image_id": p["proxy_image_id"],
        "allowlist_sha256": p["allowlist_sha256"],
        "proxy_config_sha256": p["proxy_config_sha256"],
        "unauthorized_domain_reachable": False,
        "direct_no_proxy_escape": False,
        "provider_egress_runtime_verified": False,
        "provider_egress_live_verified": False,
        "secrets_present": False,
        "completion_claim_allowed": False,
        "authority": False,
        "science_restored": False,
        "parent_complete": False,
        "scientific_research": False,
        "observed_at": observed,
    }
    base.update(overrides)
    return base


def _sample_canary_receipt(
    posture: dict | None = None, *, observed_at: str | None = None, **overrides
):
    """Every required seal-eligible semantic field is explicit (no CONNECT-only fake)."""
    p = posture or _sample_posture()
    observed = observed_at or _iso_z(dt.datetime.now(dt.UTC))
    base = {
        "schema_version": "xinao.provider_egress_engineering_canary_receipt.v1",
        "path_class": "engineering_canary",
        "status": "observed",
        "real_provider_call": True,
        "provider_effect_verified": True,
        "requested_model": "grok-4.5",
        "observed_backend_model": "grok-4.5-build",
        "stop_reason": "EndTurn",
        "output_tokens": 12,
        "usage_accounting_complete": True,
        "usage": {
            "input_tokens": 8,
            "output_tokens": 12,
            "total_tokens": 20,
        },
        "endpoint_host": "cli-chat-proxy.grok.com",
        "internal_network_id": p["internal_network_id"],
        "proxy_container_id": p["proxy_container_id"],
        "proxy_image_id": p["proxy_image_id"],
        "allowlist_sha256": p["allowlist_sha256"],
        "proxy_config_sha256": p["proxy_config_sha256"],
        "canary_image_id": "sha256:" + "a" * 64,
        "internal_network_only": True,
        "auth_mounted_read_only": True,
        "auth_content_persisted": False,
        "raw_output_persisted": False,
        "research_invoked": False,
        "is_research_call": False,
        "scientific_research": False,
        "masquerades_as_research": False,
        "scientific_adoption": False,
        "science_restored": False,
        "parent_complete": False,
        "authority": False,
        "completion_claim_allowed": False,
        "secrets_present": False,
        "provider_egress_runtime_verified": False,
        "provider_egress_live_verified": False,
        "observed_at": observed,
        "positive_token_value": None,
        "connect_only": False,
        "http_only": False,
    }
    base.update(overrides)
    return base


def _sample_connect_only_fake_canary(posture: dict | None = None, **overrides):
    """Sibling CONNECT-only engineering receipt shape (must be rejected by sealer)."""
    p = posture or _sample_posture()
    base = {
        "schema_version": "xinao.provider_egress_engineering_canary_receipt.v1",
        "path_class": "engineering_canary",
        "status": "observed",
        "real_provider_call": False,
        "positive_token_value": None,
        "connect_only": True,
        "completion_claim_allowed": False,
        "authority": False,
        "science_restored": False,
        "parent_complete": False,
        "scientific_research": False,
        "secrets_present": False,
        "masquerades_as_research": False,
        "internal_network_id": p["internal_network_id"],
        "proxy_container_id": p["proxy_container_id"],
        "proxy_image_id": p["proxy_image_id"],
        "allowlist_sha256": p["allowlist_sha256"],
        "proxy_config_sha256": p["proxy_config_sha256"],
    }
    base.update(overrides)
    return base


def _install_posture_and_seal(
    module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    seal_overrides: dict | None = None,
    posture_overrides: dict | None = None,
    sealed_delta: dt.timedelta = dt.timedelta(minutes=-5),
    ttl: dt.timedelta = dt.timedelta(hours=1),
    write_evidence: bool = True,
) -> dict:
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    posture = _sample_posture(**(posture_overrides or {}))
    posture_path = module._egress_posture_path()
    posture_sha = _write_json(posture_path, posture)
    neg_rel = "negative_suite_receipt.v1.json"
    can_rel = "engineering_canary_receipt.v1.json"
    sealed_at = dt.datetime.now(dt.UTC) + sealed_delta
    expires_at = sealed_at + ttl
    observed_at = _iso_z(sealed_at - dt.timedelta(seconds=30))
    if write_evidence:
        _write_json(
            module._egress_state_dir() / neg_rel,
            _sample_negative_receipt(posture, observed_at=observed_at),
        )
        _write_json(
            module._egress_state_dir() / can_rel,
            _sample_canary_receipt(posture, observed_at=observed_at),
        )
        neg_sha = module._sha256(module._egress_state_dir() / neg_rel)
        can_sha = module._sha256(module._egress_state_dir() / can_rel)
    else:
        neg_sha = "1" * 64
        can_sha = "2" * 64
    seal = {
        "schema_version": "xinao.provider_egress_live_seal.v1",
        "provider_egress_live_verified": True,
        "posture_sha256": posture_sha,
        "posture_relative_path": "current_posture.v1.json",
        "negative_suite_receipt_sha256": neg_sha,
        "negative_suite_receipt_relative_path": neg_rel,
        "positive_canary_receipt_sha256": can_sha,
        "positive_canary_receipt_relative_path": can_rel,
        "allowlist_sha256": posture["allowlist_sha256"],
        "proxy_config_sha256": posture["proxy_config_sha256"],
        "proxy_container_id": posture["proxy_container_id"],
        "proxy_image_id": posture["proxy_image_id"],
        "internal_network_id": posture["internal_network_id"],
        "internal_network_name": posture["internal_network_name"],
        "external_network_name": posture["external_network_name"],
        "proxy_endpoint": posture["proxy_endpoint"],
        "docker_engine_observational_id": "engine|desktop",
        "docker_server_version": "29.5.3",
        "docker_ostype": "linux",
        "sealed_at": sealed_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "completion_claim_allowed": False,
        "authority": False,
        "science_restored": False,
        "parent_complete": False,
        "secrets_present": False,
        "trust_boundary": module.EGRESS_SEAL_TRUST_BOUNDARY,
    }
    if seal_overrides:
        seal.update(seal_overrides)
    seal_path = module._egress_live_seal_path()
    seal_sha = _write_json(seal_path, seal)
    return {
        "posture": posture,
        "posture_sha256": posture_sha,
        "seal": seal,
        "seal_sha256": seal_sha,
        "lock": {
            "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
            "provider_egress_runtime_verified": False,
            "egress_internal_network_name": "xinao_researcher_internal",
            "egress_proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
            "egress_host_port_publish_allowed": False,
        },
    }


def _fake_live_ok(module, posture: dict) -> None:
    network_ok = {
        "Id": posture["internal_network_id"],
        "Name": posture["internal_network_name"],
        "Internal": True,
        "Containers": {posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]}},
    }
    proxy_ok = {
        "Id": posture["proxy_container_id"],
        "Image": posture["proxy_image_id"],
        "State": {"Running": True, "Status": "running"},
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "xinao_provider_egress_ext": {},
            },
            "Ports": {},
        },
    }

    def _inspect(docker, kind, target):
        if kind == "network":
            return network_ok
        return proxy_ok

    module._docker_json_inspect = _inspect  # type: ignore[method-assign]
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: posture["proxy_config_sha256"]
    )
    module._docker_engine_observational_identity = (  # type: ignore[method-assign]
        lambda docker: {
            "docker_engine_observational_id": "engine|desktop",
            "docker_server_version": "29.5.3",
            "docker_ostype": "linux",
        }
    )
    module._docker = lambda: "docker"  # type: ignore[method-assign]


def test_source_defaults_keep_verified_false() -> None:
    lock = json.loads(
        (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text(encoding="utf-8")
    )
    assert lock["provider_egress_runtime_verified"] is False
    assert lock["network_profile"] == "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL"
    assert lock["egress_internal_network_name"] == "xinao_researcher_internal"
    assert lock["egress_dify_cross_project_allowed"] is False


def test_render_empty_allowlist_is_default_deny() -> None:
    render = _renderer()
    template = (EGRESS_ROOT / "squid.conf.template").read_text(encoding="utf-8")
    conf = render.render_template(template, domains=())
    assert "http_access deny all" in conf
    assert "http_access allow client_localnet" not in conf
    assert "acl Safe_ports port 80" not in conf
    assert "ssl_bump" not in conf.lower()
    assert "provider_domains" in conf


def test_render_with_domains_is_deterministic() -> None:
    render = _renderer()
    template = (EGRESS_ROOT / "squid.conf.template").read_text(encoding="utf-8")
    conf_a = render.render_template(template, domains=["api.example.test", ".example.test"])
    conf_b = render.render_template(template, domains=[".example.test", "api.example.test"])
    assert conf_a == conf_b
    assert "acl provider_domains dstdomain .example.test api.example.test" in conf_a
    digest_a = render.sha256_bytes(conf_a.encode("utf-8"))
    digest_b = render.sha256_bytes(conf_b.encode("utf-8"))
    assert digest_a == digest_b


def test_render_rejects_ip_literal_domains_and_private_opens() -> None:
    render = _renderer()
    bad = {
        "schema_version": "xinao.provider_egress_allowlist.v1",
        "ports": [443],
        "methods": ["CONNECT"],
        "domains": ["1.2.3.4"],
        "ip_literals_allowed": [],
    }
    path = EGRESS_ROOT / "allowlist.v1.json"
    # in-memory validation path via temporary file
    tmp = path.parent / ".tmp-allowlist-test.json"
    try:
        tmp.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(render.RenderError) as err:
            render.load_allowlist(tmp)
        assert err.value.reason_code in {
            "ALLOWLIST_DOMAIN_TOKEN_INVALID",
            "ALLOWLIST_DOMAIN_LOOKS_LIKE_IP",
        }
        bad2 = dict(bad)
        bad2["domains"] = ["api.example.test"]
        bad2["ip_literals_allowed"] = ["8.8.8.8"]
        tmp.write_text(json.dumps(bad2), encoding="utf-8")
        with pytest.raises(render.RenderError) as err2:
            render.load_allowlist(tmp)
        assert err2.value.reason_code == "ALLOWLIST_IP_LITERALS_FORBIDDEN"
    finally:
        tmp.unlink(missing_ok=True)


def test_image_pin_rejects_floating_tag_authority() -> None:
    render = _renderer()
    with pytest.raises(render.RenderError) as err:
        render.assert_image_pin(
            {
                "schema_version": "xinao.provider_egress_proxy_image_pin.v1",
                "image_repository": "ubuntu/squid",
                "image_tag_observational": "latest",
                "image_digest": None,
                "image_id": None,
                "floating_tag_as_authority": False,
                "authority": "immutable_digest_or_image_id_only",
            }
        )
    assert err.value.reason_code == "IMAGE_PIN_UNRESOLVED"
    render.assert_image_pin(
        {
            "schema_version": "xinao.provider_egress_proxy_image_pin.v1",
            "image_repository": "ubuntu/squid",
            "image_tag_observational": "latest",
            "image_digest": "ubuntu/squid@sha256:" + "f" * 64,
            "image_id": "sha256:" + "e" * 64,
            "floating_tag_as_authority": False,
            "authority": "immutable_digest_or_image_id_only",
        }
    )


def test_compose_has_no_host_ports_and_no_dify_reuse() -> None:
    compose = (EGRESS_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    assert "internal: true" in compose
    assert "xinao_researcher_internal" in compose
    assert "xinao_provider_egress_ext" in compose
    # Comments may mention Dify only as forbidden; service/network names must not be used.
    assert (
        "image:" not in compose
        or "ssrf_proxy" not in compose.split("services:")[1].split("networks:")[0]
    )
    assert "ssrf_proxy_network:" not in compose
    assert "container_name: ssrf_proxy" not in compose
    # No host port publish mapping block
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("ports:"):
            pytest.fail("host ports mapping present")


def test_source_false_absent_seal_fails_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": False,
    }
    # Missing posture/seal must fail closed; docker must not be required before seal/posture.
    with pytest.raises(module.XinaoError) as failure:
        module._require_host_egress_boundary(lock)
    assert failure.value.reason_code in {
        "EGRESS_POSTURE_MISSING",
        "EGRESS_LIVE_SEAL_MISSING",
        "EGRESS_BOUNDARY_UNAVAILABLE",
    }
    posture_path = module._egress_posture_path()
    posture_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(posture_path, _sample_posture())
    monkeypatch.setattr(module, "_docker", lambda: (_ for _ in ()).throw(AssertionError("docker")))
    with pytest.raises(module.XinaoError) as failure2:
        module._require_host_egress_boundary(lock)
    assert failure2.value.reason_code == "EGRESS_LIVE_SEAL_MISSING"


def test_posture_shape_and_secret_redaction() -> None:
    module = _runtime()
    good = _sample_posture()
    assert module._validate_egress_posture_shape(good)["proxy_endpoint"].startswith("http://")
    with pytest.raises(module.XinaoError) as missing:
        module._validate_egress_posture_shape(
            {"schema_version": "xinao.provider_egress_posture.v1"}
        )
    assert missing.value.reason_code == "EGRESS_POSTURE_INCOMPLETE"
    leak = _sample_posture()
    leak["note"] = "Authorization: Bearer secret"
    with pytest.raises(module.XinaoError) as secret:
        module._validate_egress_posture_shape(leak)
    assert secret.value.reason_code == "EGRESS_POSTURE_SECRET_LEAK"
    published = _sample_posture(host_port_published=True)
    with pytest.raises(module.XinaoError) as port:
        module._validate_egress_posture_shape(published)
    assert port.value.reason_code == "EGRESS_HOST_PORT_PUBLISH_FORBIDDEN"
    dify = _sample_posture(dify_cross_project=True)
    with pytest.raises(module.XinaoError) as cross:
        module._validate_egress_posture_shape(dify)
    assert cross.value.reason_code == "EGRESS_DIFY_CROSS_PROJECT_FORBIDDEN"


def test_live_compare_fail_closed_mismatches() -> None:
    module = _runtime()
    posture = _sample_posture()
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": True,
        "egress_internal_network_name": "xinao_researcher_internal",
        "egress_proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "egress_host_port_publish_allowed": False,
    }

    network_ok = {
        "Id": posture["internal_network_id"],
        "Name": posture["internal_network_name"],
        "Internal": True,
        "Containers": {posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]}},
    }
    proxy_ok = {
        "Id": posture["proxy_container_id"],
        "Image": posture["proxy_image_id"],
        "State": {"Running": True, "Status": "running"},
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "xinao_provider_egress_ext": {},
            },
            "Ports": {},
        },
    }

    def inspect_factory(network=None, proxy=None):
        def _inspect(docker, kind, target):
            if kind == "network":
                return network if network is not None else network_ok
            return proxy if proxy is not None else proxy_ok

        return _inspect

    # Offline tests previously passed with posture hash alone; live CAS is mandatory.
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: posture["proxy_config_sha256"]
    )
    module._docker_json_inspect = inspect_factory()  # type: ignore[method-assign]
    observed = module._compare_live_egress_objects("docker", posture, lock)
    assert observed["internal"] is True
    assert observed["live_proxy_config_sha256"] == posture["proxy_config_sha256"]

    # Not internal
    module._docker_json_inspect = inspect_factory(network={**network_ok, "Internal": False})  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err.value.reason_code == "EGRESS_NETWORK_NOT_INTERNAL"

    # Image mismatch
    module._docker_json_inspect = inspect_factory(proxy={**proxy_ok, "Image": "sha256:" + "0" * 64})  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err2:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err2.value.reason_code == "EGRESS_PROXY_IMAGE_MISMATCH"

    # Dify network attach
    bad_proxy = {
        **proxy_ok,
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "ssrf_proxy_network": {},
            },
            "Ports": {},
        },
    }
    module._docker_json_inspect = inspect_factory(proxy=bad_proxy)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err3:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err3.value.reason_code == "EGRESS_DIFY_CROSS_PROJECT_FORBIDDEN"

    # Host port published
    published_proxy = {
        **proxy_ok,
        "NetworkSettings": {
            "Networks": proxy_ok["NetworkSettings"]["Networks"],
            "Ports": {"3128/tcp": [{"HostIp": "0.0.0.0", "HostPort": "3128"}]},
        },
    }
    module._docker_json_inspect = inspect_factory(proxy=published_proxy)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err4:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err4.value.reason_code == "EGRESS_HOST_PORT_PUBLISH_FORBIDDEN"

    # Proxy not running
    module._docker_json_inspect = inspect_factory(
        proxy={**proxy_ok, "State": {"Running": False, "Status": "exited"}}
    )  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err5:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err5.value.reason_code == "EGRESS_PROXY_NOT_RUNNING"

    # Missing dual-home external network
    mono = {
        **proxy_ok,
        "NetworkSettings": {
            "Networks": {"xinao_researcher_internal": {}},
            "Ports": {},
        },
    }
    module._docker_json_inspect = inspect_factory(proxy=mono)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err6:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err6.value.reason_code == "EGRESS_PROXY_NOT_DUAL_HOMED"

    # Foreign container on internal network
    foreign_net = {
        **network_ok,
        "Containers": {
            posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]},
            "other": {"Name": "unrelated-app"},
        },
    }
    module._docker_json_inspect = inspect_factory(network=foreign_net)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err7:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err7.value.reason_code == "EGRESS_FOREIGN_NETWORK_MEMBER"

    # Persistent ResearchEpisode transport: exact lease-bound ID is allowed,
    # while the xinao-transport-* prefix by itself grants nothing.
    episode_transport_id = "f" * 64
    episode_net = {
        **network_ok,
        "Containers": {
            posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]},
            episode_transport_id: {"Name": "xinao-transport-ep-bound"},
        },
    }
    module._docker_json_inspect = inspect_factory(network=episode_net)  # type: ignore[method-assign]
    observed = module._compare_live_egress_objects(
        "docker",
        posture,
        lock,
        allowed_researcher_container_ids={episode_transport_id},
    )
    assert observed["proxy_container_id"] == posture["proxy_container_id"]
    with pytest.raises(module.XinaoError) as short_id_err:
        module._compare_live_egress_objects(
            "docker",
            posture,
            lock,
            allowed_researcher_container_ids={episode_transport_id[:12]},
        )
    assert short_id_err.value.reason_code == "EGRESS_FOREIGN_NETWORK_MEMBER"

    # Containers populated but proxy absent
    no_proxy_members = {
        **network_ok,
        "Containers": {"other": {"Name": "xinao-researcher-run-1"}},
    }
    module._docker_json_inspect = inspect_factory(network=no_proxy_members)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err8:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err8.value.reason_code == "EGRESS_NETWORK_MEMBERSHIP_INVALID"


def test_managed_episode_transport_discovery_requires_exact_live_lease_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    posture = _sample_posture()
    episode_root = tmp_path / "episode-a"
    (episode_root / "output").mkdir(parents=True)
    episode_id = "xre_peer_a"
    session_id = "xrsess_peer_a"
    transport_id = "a" * 64
    tool_id = "b" * 64
    transport_name = "xinao-transport-xre_peer_a"
    transport_image = "sha256:" + "c" * 64
    tool_image = "sha256:" + "d" * 64
    output_source = str(episode_root / "output")
    if sys.platform != "win32":
        # Production inspect data uses a Windows host path.  Keep that contract
        # in cross-platform CI while mapping the synthetic mount to tmp_path.
        output_source = r"D:\xinao-ci-fixture\episode-a\output"
        real_path = module.Path

        def fixture_path(value):
            if str(value) == output_source:
                return episode_root / "output"
            return real_path(value)

        monkeypatch.setattr(module, "Path", fixture_path)
    _write_json(
        episode_root / "episode_meta.json",
        {
            "schema_version": "xinao.research_episode_state.v1",
            "episode_id": episode_id,
            "session_id": session_id,
        },
    )
    lease = {
        "schema_version": "xinao.dual_container_pair_lease.v1",
        "episode_id": episode_id,
        "session_id": session_id,
        "phase": "running",
        "transport_container_id": transport_id,
        "transport_container_name": transport_name,
        "transport_image_id": transport_image,
        "tool_container_id": tool_id,
        "tool_image_id": tool_image,
    }
    _write_json(episode_root / "dual_container_pair_lease.json", lease)
    _write_json(
        episode_root / "session_inventory.json",
        {
            "schema_version": "xinao.dual_container_session_inventory.v1",
            "episode_id": episode_id,
            "host_session_id": session_id,
            "transport_container_id": transport_id,
        },
    )
    _write_json(
        episode_root / "dual_container_pair_receipt.json",
        {
            "schema_version": "xinao.dual_container_pair_receipt.v1",
            "episode_id": episode_id,
            "session_id": session_id,
            "transport_container_id": transport_id,
            "transport_container_name": transport_name,
            "transport_image_id": transport_image,
        },
    )
    proxy_env = module._proxy_env_pairs(posture["proxy_endpoint"])
    inspect = {
        "Id": transport_id,
        "Name": "/" + transport_name,
        "Image": transport_image,
        "Config": {
            "Labels": {
                "io.xinao.researcher.chain": "dedicated-xinao-science",
                "io.xinao.researcher.generic-worker-route": "forbidden",
                "io.xinao.researcher.episode-profile": "GENUINE_SCIENTIST_EPISODE",
            },
            "Env": [f"{key}={value}" for key, value in proxy_env.items()]
            + [
                f"XINAO_EPISODE_ID={episode_id}",
                "XINAO_DUAL_CONTAINER=1",
                "XINAO_GENERIC_FILE_SHELL_TOOLS=0",
            ],
        },
        "HostConfig": {
            "NetworkMode": posture["internal_network_name"],
            "Privileged": False,
            "PublishAllPorts": False,
            "PortBindings": {},
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "RestartPolicy": {"Name": "no"},
        },
        "NetworkSettings": {
            "Networks": {posture["internal_network_name"]: {}},
            "Ports": {},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": output_source,
                "Destination": "/output",
                "RW": True,
            }
        ],
    }
    monkeypatch.setattr(
        module,
        "_docker_json_inspect",
        lambda _docker, kind, _target: inspect if kind == "container" else {},
    )

    class FakeConfig:
        def __init__(self, **kwargs):
            self.episode_root = Path(kwargs["episode_root"])

    class FakeHost:
        def __init__(self, config):
            self.config = config

        def validate_before_start(self):
            return {
                "lease": json.loads(
                    (self.config.episode_root / "dual_container_pair_lease.json").read_text(
                        encoding="utf-8"
                    )
                )
            }

    monkeypatch.setattr(
        module,
        "_research_episode_load_dual_host_module",
        lambda: types.SimpleNamespace(DualHostConfig=FakeConfig, DualContainerHost=FakeHost),
    )
    assert (
        module._managed_episode_transport_root(
            "docker",
            member_id=transport_id,
            member_name=transport_name,
            posture=posture,
        )
        == episode_root
    )

    assert (
        module._managed_episode_transport_root(
            "docker",
            member_id=transport_id[:12],
            member_name=transport_name,
            posture=posture,
        )
        is None
    )

    # A name/label-compatible member with a swapped lease ID is not admitted.
    _write_json(
        episode_root / "dual_container_pair_lease.json",
        {**lease, "transport_container_id": "e" * 64},
    )
    assert (
        module._managed_episode_transport_root(
            "docker",
            member_id=transport_id,
            member_name=transport_name,
            posture=posture,
        )
        is None
    )


def test_dual_host_admits_current_and_all_valid_managed_episode_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    episode_root = tmp_path / "episode-main"
    episode_root.mkdir()
    current_transport_id = "a" * 64
    peer_transport_ids = {"b" * 64, "c" * 64}
    _write_json(
        episode_root / "dual_container_pair_lease.json",
        {"transport_container_id": current_transport_id},
    )
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{}", encoding="utf-8")
    posture = _sample_posture()
    captured: dict[str, set[str]] = {}

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeHost:
        def __init__(self, config):
            self.config = config

    monkeypatch.delenv("XINAO_DUAL_CONTAINER_SYNTHETIC", raising=False)
    monkeypatch.delenv("XINAO_TRANSPORT_NETWORK", raising=False)
    monkeypatch.setattr(
        module,
        "_research_episode_load_dual_host_module",
        lambda: types.SimpleNamespace(DualHostConfig=FakeConfig, DualContainerHost=FakeHost),
    )
    monkeypatch.setattr(
        module,
        "_resolve_research_episode_dual_images",
        lambda: ("sha256:" + "d" * 64, "sha256:" + "e" * 64),
    )
    monkeypatch.setattr(module, "resolve_auth_host_path", lambda **_kwargs: auth_path)
    monkeypatch.setattr(
        module,
        "_posture_file_sha256",
        lambda: (posture, "f" * 64, tmp_path / "posture.json"),
    )
    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(
        module,
        "_discover_managed_episode_transport_ids",
        lambda docker, observed_posture: (
            peer_transport_ids if docker == "docker" and observed_posture == posture else set()
        ),
    )

    def require_boundary(*, allowed_researcher_container_ids):
        captured["allowed"] = set(allowed_researcher_container_ids)
        return {
            "internal_network_name": posture["internal_network_name"],
            "proxy_endpoint": posture["proxy_endpoint"],
        }

    monkeypatch.setattr(module, "_require_host_egress_boundary", require_boundary)

    _host_module, host = module._research_episode_load_dual_host(episode_root)

    assert captured["allowed"] == {current_transport_id, *peer_transport_ids}
    assert host.config.kwargs["episode_root"] == episode_root
    assert host.config.kwargs["network"] == posture["internal_network_name"]


def test_container_inspect_rejects_bridge_and_missing_proxy_env(tmp_path: Path) -> None:
    module = _runtime()
    endpoint = "http://xinao-researcher-egress-proxy:3128"
    network_name = "xinao_researcher_internal"
    network_id = "netid1"
    input_root = tmp_path / "input"
    materials_root = tmp_path / "materials"
    output_root = tmp_path / "output"
    auth_path = tmp_path / "auth.json"
    image_id = "sha256:" + "a" * 64
    base_inspect = {
        "Image": image_id,
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": network_name,
            "PidsLimit": 128,
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "Privileged": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
            },
        },
        "Config": {
            "Env": [
                "XINAO_CHAIN_CLASS=scientific_researcher",
                f"HTTP_PROXY={endpoint}",
                f"HTTPS_PROXY={endpoint}",
                f"http_proxy={endpoint}",
                f"https_proxy={endpoint}",
            ]
        },
        "NetworkSettings": {"Networks": {network_name: {"NetworkID": network_id}}},
        "Mounts": [
            {"Type": "bind", "Source": str(input_root), "Destination": "/input", "RW": False},
            {
                "Type": "bind",
                "Source": str(materials_root),
                "Destination": "/materials",
                "RW": False,
            },
            {"Type": "bind", "Source": str(output_root), "Destination": "/output", "RW": True},
            {
                "Type": "bind",
                "Source": str(auth_path),
                "Destination": "/grok-home/auth.json",
                "RW": False,
            },
        ],
    }
    kwargs = dict(
        image_id=image_id,
        input_root=input_root,
        materials_root=materials_root,
        output_root=output_root,
        auth_path=auth_path,
        internal_network_name=network_name,
        internal_network_id=network_id,
        proxy_endpoint=endpoint,
    )
    module._validate_container_inspect(base_inspect, **kwargs)

    bridged = json.loads(json.dumps(base_inspect))
    bridged["HostConfig"]["NetworkMode"] = "bridge"
    bridged["NetworkSettings"]["Networks"] = {"bridge": {}}
    with pytest.raises(module.XinaoError) as err:
        module._validate_container_inspect(bridged, **kwargs)
    assert err.value.reason_code == "CONTAINER_NETWORK_PROFILE_INVALID"

    multi = json.loads(json.dumps(base_inspect))
    multi["NetworkSettings"]["Networks"] = {
        network_name: {},
        "xinao_provider_egress_ext": {},
    }
    with pytest.raises(module.XinaoError) as err2:
        module._validate_container_inspect(multi, **kwargs)
    assert err2.value.reason_code == "CONTAINER_NETWORK_MEMBERSHIP_INVALID"

    no_proxy = json.loads(json.dumps(base_inspect))
    no_proxy["Config"]["Env"] = ["XINAO_CHAIN_CLASS=scientific_researcher"]
    with pytest.raises(module.XinaoError) as err3:
        module._validate_container_inspect(no_proxy, **kwargs)
    assert err3.value.reason_code == "CONTAINER_PROXY_ENV_INVALID"

    escape = json.loads(json.dumps(base_inspect))
    escape["Config"]["Env"] = list(base_inspect["Config"]["Env"]) + ["NO_PROXY=10.0.0.0/8"]
    with pytest.raises(module.XinaoError) as err4:
        module._validate_container_inspect(escape, **kwargs)
    assert err4.value.reason_code == "CONTAINER_NO_PROXY_ESCAPE"

    dify_net = json.loads(json.dumps(base_inspect))
    dify_net["HostConfig"]["NetworkMode"] = "ssrf_proxy_network"
    dify_net["NetworkSettings"]["Networks"] = {"ssrf_proxy_network": {}}
    with pytest.raises(module.XinaoError) as err5:
        module._validate_container_inspect(
            dify_net,
            **{
                **kwargs,
                "internal_network_name": "ssrf_proxy_network",
                "internal_network_id": "x",
            },
        )
    assert err5.value.reason_code == "EGRESS_DIFY_CROSS_PROJECT_FORBIDDEN"


def test_source_false_valid_live_seal_reaches_docker_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    lock = fixture["lock"]
    assert lock["provider_egress_runtime_verified"] is False

    def fake_compare(docker, posture, runtime_lock, **_kwargs):
        return {
            "internal_network_id": posture["internal_network_id"],
            "internal_network_name": posture["internal_network_name"],
            "internal": True,
            "proxy_container_id": posture["proxy_container_id"],
            "proxy_image_id": posture["proxy_image_id"],
            "proxy_endpoint": posture["proxy_endpoint"],
            "allowlist_sha256": posture["allowlist_sha256"],
            "proxy_config_sha256": posture["proxy_config_sha256"],
            "live_proxy_config_sha256": posture["proxy_config_sha256"],
            "proxy_networks": [
                "xinao_researcher_internal",
                "xinao_provider_egress_ext",
            ],
            "host_port_published": False,
            "dify_cross_project": False,
        }

    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(
        module,
        "_docker_engine_observational_identity",
        lambda docker: {
            "docker_engine_observational_id": "engine|desktop",
            "docker_server_version": "29.5.3",
            "docker_ostype": "linux",
        },
    )
    monkeypatch.setattr(module, "_compare_live_egress_objects", fake_compare)
    bound = module._require_host_egress_boundary(lock)
    assert bound["proxy_endpoint"] == "http://xinao-researcher-egress-proxy:3128"
    assert bound["allowlist_sha256"] == "d" * 64
    assert bound["provider_egress_runtime_verified"] is True
    assert bound["live_seal_sha256"] == fixture["seal_sha256"]
    assert bound["completion_claim_allowed"] is False


def test_research_receipt_redaction_shape_for_egress_block() -> None:
    # Static contract: receipt must never embed auth content; live seal result is measured.
    module = _runtime()
    source = (SKILL_ROOT / "scripts" / "xinao_runtime.py").read_text(encoding="utf-8")
    assert '"provider_egress":' in source
    assert '"proxy_env_is_routing_hint_only": True' in source
    assert '"source_provider_egress_runtime_verified": False' in source
    assert "live_seal_sha256" in source
    assert "observation_before_create" in source
    assert "observation_before_start" in source
    assert "auth_content_sha256" in source
    assert 'provider_egress_runtime_verified"] = True' not in source


def test_cleanup_script_never_mentions_dify_rm() -> None:
    cleanup = (EGRESS_ROOT / "scripts" / "owner_cleanup_egress.sh").read_text(encoding="utf-8")
    assert "ssrf_proxy" in cleanup  # mentioned as leave untouched
    assert "left Dify object untouched" in cleanup
    assert "docker rm -f ssrf_proxy" not in cleanup
    assert "docker network rm ssrf_proxy_network" not in cleanup


def test_provision_script_ignores_comment_dify_mentions() -> None:
    provision = (EGRESS_ROOT / "scripts" / "owner_provision_egress.sh").read_text(encoding="utf-8")
    compose = (EGRESS_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    # Compose may document Dify as forbidden in comments/labels, but must not define Dify services.
    assert "Dify" in compose or "dify" in compose
    assert "container_name: ssrf_proxy" not in compose
    assert "ssrf_proxy_network:" not in compose
    # Provision check must target service keys, not free-text comments.
    assert "container_name:[[:space:]]*ssrf_proxy" in provision
    assert "provider_egress_runtime_verified" in provision
    assert "False" in provision or "false" in provision.lower()


def test_render_denies_cleartext_and_non_443() -> None:
    render = _renderer()
    template = (EGRESS_ROOT / "squid.conf.template").read_text(encoding="utf-8")
    conf = render.render_template(template, domains=["api.example.test"])
    assert "acl SSL_ports port 443" in conf
    assert "acl Safe_ports port 443" in conf
    assert "http_access deny !CONNECT" in conf
    assert "http_access deny CONNECT !SSL_ports" in conf
    assert "http_access deny to_ipv4_literal" in conf
    assert "http_access deny to_private_networks" in conf
    with pytest.raises(render.RenderError) as err:
        bad_template = template + chr(10) + "acl Safe_ports port 80" + chr(10)
        render.render_template(bad_template, domains=["api.example.test"])
    assert err.value.reason_code == "CLEARTEXT_PORT_80_OPEN"


def test_no_unit_test_flips_verified_true_in_source_lock() -> None:
    lock_text = (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text(
        encoding="utf-8"
    )
    lock = json.loads(lock_text)
    assert lock["provider_egress_runtime_verified"] is False
    # Source file must not contain a true assignment for the claim bit.
    assert '"provider_egress_runtime_verified": true' not in lock_text.lower().replace(" ", "")


def test_render_rejects_tld_only_and_trailing_dot_overreach() -> None:
    render = _renderer()
    for bad, code in (
        (".com", "ALLOWLIST_DOMAIN_SUFFIX_OVERREACH"),
        (".ai", "ALLOWLIST_DOMAIN_SUFFIX_OVERREACH"),
        ("localhost", "ALLOWLIST_DOMAIN_SUFFIX_OVERREACH"),
        ("example.com.", "ALLOWLIST_DOMAIN_TOKEN_INVALID"),
        (".example.com.", "ALLOWLIST_DOMAIN_TOKEN_INVALID"),
        ("1.2.3.4", "ALLOWLIST_DOMAIN_LOOKS_LIKE_IP"),
    ):
        with pytest.raises(render.RenderError) as err:
            render.validate_domain_token(bad)
        assert err.value.reason_code == code, bad
    render.validate_domain_token(".example.com")
    render.validate_domain_token("api.example.com")


def test_render_requires_alternate_ip_and_trailing_dot_denies() -> None:
    render = _renderer()
    template = (EGRESS_ROOT / "squid.conf.template").read_text(encoding="utf-8")
    conf = render.render_template(template, domains=["api.example.test"])
    assert "acl to_ipv4_literal dstdom_regex ^[0-9]+$" in conf
    assert "acl to_ipv6_literal dstdom_regex :" in conf
    assert "http_access deny to_trailing_dot_name" in conf
    assert "acl to_trailing_dot_name dstdom_regex \\.$" in conf


def test_entrypoint_writes_conf_to_tmpfs_and_guards_acl_injection() -> None:
    entry = (EGRESS_ROOT / "docker-entrypoint.sh").read_text(encoding="utf-8")
    template = (EGRESS_ROOT / "squid.conf.template").read_text(encoding="utf-8")
    assert "/etc/squid/squid.conf" not in entry or "SQUID_CONF=" in entry
    assert 'SQUID_CONF="${COREDUMP_DIR}/squid.conf"' in entry
    assert 'squid -f "${SQUID_CONF}"' in entry or 'squid -f "${SQUID_CONF}"' in entry
    assert "PROVIDER_DSTDOMAIN_ACL must be a single line" in entry
    assert "forbidden ACL fragments" in entry
    # Template-env injection via HTTP_PORT/COREDUMP_DIR must fail closed.
    assert "HTTP_PORT must be a single decimal TCP port" in entry
    assert "COREDUMP_DIR must be a single absolute path" in entry
    assert "http_access allow all" in entry
    assert "live_proxy_config_sha256=" in entry
    # Must not write rendered conf onto read-only rootfs path as the only path.
    assert "awk" in entry and "SQUID_CONF" in entry
    assert "pid_filename ${COREDUMP_DIR}/squid.pid" in template


def test_read_only_proxy_runs_mounted_entrypoint_and_provision_checks_liveness() -> None:
    compose = (EGRESS_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    provision = (EGRESS_ROOT / "scripts" / "Owner-ProvisionEgress.ps1").read_text(encoding="utf-8")
    assert "read_only: true" in compose
    assert "- /bin/bash\n      - /docker-entrypoint-mount.sh" in compose
    assert "cp /docker-entrypoint-mount.sh" not in compose
    assert "{{.State.Running}}" in provision
    assert "EGRESS_PROXY_NOT_RUNNING" in provision


def test_windows_engineering_canary_encodes_empty_tool_set_without_empty_argv() -> None:
    canary = (EGRESS_ROOT / "scripts" / "Owner-EngineeringCanary.ps1").read_text(encoding="utf-8")
    assert "'--tools='," in canary
    assert "'--tools', ''," not in canary
    assert canary.count("'--max-turns', '2'") == 2
    assert "'--max-turns', '1'" not in canary


def test_research_result_writes_provider_ids_in_result_object() -> None:
    entrypoint = (ROOT / "docker" / "xinao-researcher" / "entrypoint.py").read_text(
        encoding="utf-8"
    )
    result_block = entrypoint.split("    result = {", maxsplit=1)[1].split("    try:", maxsplit=1)[
        0
    ]
    attestation_block = entrypoint.split("def _terminal_attestation_bytes(", maxsplit=1)[1].split(
        "def _emit_terminal_bytes(", maxsplit=1
    )[0]
    assert '"provider_session_id_present": True' in result_block
    assert '"provider_request_id_present": True' in result_block
    assert '"provider_session_id": provider_effect["session_id"]' in result_block
    assert '"provider_request_id": provider_effect["request_id"]' in result_block
    assert "provider_session_id" not in attestation_block
    assert "provider_request_id" not in attestation_block


def test_egress_scripts_are_lf_only() -> None:
    for path in EGRESS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".sh", ".py", ".template", ".yaml", ".yml", ".json", ".md"}:
            if path.name != "docker-entrypoint.sh":
                continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        assert b"\r\n" not in raw, f"CRLF present in {path}"
        assert b"\r" not in raw, f"bare CR present in {path}"


def test_empty_network_membership_fails_closed() -> None:
    module = _runtime()
    posture = _sample_posture()
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": True,
        "egress_internal_network_name": "xinao_researcher_internal",
        "egress_proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "egress_host_port_publish_allowed": False,
    }
    empty_net = {
        "Id": posture["internal_network_id"],
        "Name": posture["internal_network_name"],
        "Internal": True,
        "Containers": {},
    }
    proxy_ok = {
        "Id": posture["proxy_container_id"],
        "Image": posture["proxy_image_id"],
        "State": {"Running": True, "Status": "running"},
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "xinao_provider_egress_ext": {},
            },
            "Ports": {},
        },
    }

    def _inspect(docker, kind, target):
        if kind == "network":
            return empty_net
        return proxy_ok

    module._docker_json_inspect = _inspect  # type: ignore[method-assign]
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: posture["proxy_config_sha256"]
    )
    with pytest.raises(module.XinaoError) as err:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err.value.reason_code == "EGRESS_NETWORK_MEMBERSHIP_INVALID"


def test_live_config_hash_mismatch_fails_closed() -> None:
    module = _runtime()
    posture = _sample_posture()
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": True,
        "egress_internal_network_name": "xinao_researcher_internal",
        "egress_proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "egress_host_port_publish_allowed": False,
    }
    network_ok = {
        "Id": posture["internal_network_id"],
        "Name": posture["internal_network_name"],
        "Internal": True,
        "Containers": {posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]}},
    }
    proxy_ok = {
        "Id": posture["proxy_container_id"],
        "Image": posture["proxy_image_id"],
        "State": {"Running": True, "Status": "running"},
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "xinao_provider_egress_ext": {},
            },
            "Ports": {},
        },
    }

    def _inspect(docker, kind, target):
        if kind == "network":
            return network_ok
        return proxy_ok

    module._docker_json_inspect = _inspect  # type: ignore[method-assign]
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: "f" * 64
    )
    with pytest.raises(module.XinaoError) as err:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err.value.reason_code == "EGRESS_LIVE_CONFIG_HASH_MISMATCH"


def test_researcher_image_sources_are_lf_and_gitattributes_pinned() -> None:
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "docker/xinao-researcher/entrypoint.py text eol=lf" in attrs
    assert "docker/xinao-researcher/Dockerfile text eol=lf" in attrs
    for rel in (
        "docker/xinao-researcher/entrypoint.py",
        "docker/xinao-researcher/Dockerfile",
        "skills/xinao/scripts/xinao.py",
        "skills/xinao/scripts/xinao_runtime.py",
    ):
        raw = (ROOT / rel).read_bytes()
        assert b"\r" not in raw, rel


def test_container_rejects_no_proxy_star_and_extra_hosts(tmp_path: Path) -> None:
    module = _runtime()
    endpoint = "http://xinao-researcher-egress-proxy:3128"
    network_name = "xinao_researcher_internal"
    network_id = "netid1"
    input_root = tmp_path / "input"
    materials_root = tmp_path / "materials"
    output_root = tmp_path / "output"
    auth_path = tmp_path / "auth.json"
    image_id = "sha256:" + "a" * 64
    base_inspect = {
        "Image": image_id,
        "HostConfig": {
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": network_name,
            "PidsLimit": 128,
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "Privileged": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,size=256m,mode=1777",
                "/grok-home": "rw,nosuid,nodev,size=256m,mode=0700",
            },
        },
        "Config": {
            "Env": [
                "XINAO_CHAIN_CLASS=scientific_researcher",
                f"HTTP_PROXY={endpoint}",
                f"HTTPS_PROXY={endpoint}",
                f"http_proxy={endpoint}",
                f"https_proxy={endpoint}",
                "NO_PROXY=*",
            ]
        },
        "NetworkSettings": {"Networks": {network_name: {"NetworkID": network_id}}},
        "Mounts": [
            {"Type": "bind", "Source": str(input_root), "Destination": "/input", "RW": False},
            {
                "Type": "bind",
                "Source": str(materials_root),
                "Destination": "/materials",
                "RW": False,
            },
            {"Type": "bind", "Source": str(output_root), "Destination": "/output", "RW": True},
            {
                "Type": "bind",
                "Source": str(auth_path),
                "Destination": "/grok-home/auth.json",
                "RW": False,
            },
        ],
    }
    kwargs = dict(
        image_id=image_id,
        input_root=input_root,
        materials_root=materials_root,
        output_root=output_root,
        auth_path=auth_path,
        internal_network_name=network_name,
        internal_network_id=network_id,
        proxy_endpoint=endpoint,
    )
    with pytest.raises(module.XinaoError) as err:
        module._validate_container_inspect(base_inspect, **kwargs)
    assert err.value.reason_code == "CONTAINER_NO_PROXY_ESCAPE"

    host_escape = json.loads(json.dumps(base_inspect))
    host_escape["Config"]["Env"] = [
        "XINAO_CHAIN_CLASS=scientific_researcher",
        f"HTTP_PROXY={endpoint}",
        f"HTTPS_PROXY={endpoint}",
        f"http_proxy={endpoint}",
        f"https_proxy={endpoint}",
    ]
    host_escape["HostConfig"]["ExtraHosts"] = ["evil:1.2.3.4"]
    with pytest.raises(module.XinaoError) as err2:
        module._validate_container_inspect(host_escape, **kwargs)
    assert err2.value.reason_code == "CONTAINER_NETWORK_PROFILE_INVALID"


def test_cleanup_receipt_claims_only_observed_removals() -> None:
    cleanup = (EGRESS_ROOT / "scripts" / "owner_cleanup_egress.sh").read_text(encoding="utf-8")
    assert "removed_networks_observed" in cleanup
    assert "proxy_removed_observed" in cleanup
    assert "left Dify object untouched" in cleanup


def test_expired_and_future_seal_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(
        module,
        tmp_path,
        monkeypatch,
        sealed_delta=dt.timedelta(hours=-3),
        ttl=dt.timedelta(hours=1),
    )
    _fake_live_ok(module, fixture["posture"])
    with pytest.raises(module.XinaoError) as expired:
        module._require_host_egress_boundary(fixture["lock"])
    assert expired.value.reason_code == "EGRESS_LIVE_SEAL_EXPIRED"

    fixture2 = _install_posture_and_seal(
        module,
        tmp_path / "future",
        monkeypatch,
        sealed_delta=dt.timedelta(hours=2),
        ttl=dt.timedelta(hours=1),
    )
    _fake_live_ok(module, fixture2["posture"])
    with pytest.raises(module.XinaoError) as future:
        module._require_host_egress_boundary(fixture2["lock"])
    assert future.value.reason_code == "EGRESS_LIVE_SEAL_FUTURE"


def test_seal_unknown_keys_and_posture_hash_drift_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(
        module,
        tmp_path,
        monkeypatch,
        seal_overrides={"extra_unknown": True},
    )
    _fake_live_ok(module, fixture["posture"])
    with pytest.raises(module.XinaoError) as unknown:
        module._require_host_egress_boundary(fixture["lock"])
    assert unknown.value.reason_code == "EGRESS_LIVE_SEAL_INVALID"
    assert "unknown" in unknown.value.detail

    fixture2 = _install_posture_and_seal(module, tmp_path / "drift", monkeypatch)
    # Tamper posture bytes after seal.
    posture_path = module._egress_posture_path()
    tampered = _sample_posture(allowlist_sha256="f" * 64)
    _write_json(posture_path, tampered)
    _fake_live_ok(module, tampered)
    with pytest.raises(module.XinaoError) as drift:
        module._require_host_egress_boundary(fixture2["lock"])
    assert drift.value.reason_code in {
        "EGRESS_LIVE_SEAL_HASH_MISMATCH",
        "EGRESS_LIVE_SEAL_DRIFT",
    }


def test_evidence_path_escape_and_hash_replay_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(
        module,
        tmp_path,
        monkeypatch,
        seal_overrides={
            "negative_suite_receipt_relative_path": "../escape.json",
        },
    )
    _fake_live_ok(module, fixture["posture"])
    with pytest.raises(module.XinaoError) as escape:
        module._require_host_egress_boundary(fixture["lock"])
    assert escape.value.reason_code == "EGRESS_LIVE_SEAL_INVALID"

    fixture2 = _install_posture_and_seal(module, tmp_path / "replay", monkeypatch)
    # Replay: keep seal hash claim but replace evidence file content without reseal.
    evidence = module._egress_state_dir() / "negative_suite_receipt.v1.json"
    _write_json(evidence, _sample_negative_receipt(pass_count=0, fail_count=99))
    _fake_live_ok(module, fixture2["posture"])
    with pytest.raises(module.XinaoError) as replay:
        module._require_host_egress_boundary(fixture2["lock"])
    assert replay.value.reason_code == "EGRESS_LIVE_SEAL_HASH_MISMATCH"


def test_live_config_mismatch_with_valid_seal_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    posture = fixture["posture"]
    _fake_live_ok(module, posture)
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: "0" * 64
    )
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(fixture["lock"])
    assert err.value.reason_code == "EGRESS_LIVE_CONFIG_HASH_MISMATCH"


def test_container_replacement_detected_against_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    posture = fixture["posture"]
    network_ok = {
        "Id": posture["internal_network_id"],
        "Name": posture["internal_network_name"],
        "Internal": True,
        "Containers": {
            "replaced": {"Name": posture["proxy_container_name"]},
        },
    }
    proxy_replaced = {
        "Id": "replaced_proxy_id_0001",
        "Image": posture["proxy_image_id"],
        "State": {"Running": True, "Status": "running"},
        "NetworkSettings": {
            "Networks": {
                "xinao_researcher_internal": {},
                "xinao_provider_egress_ext": {},
            },
            "Ports": {},
        },
    }

    def _inspect(docker, kind, target):
        if kind == "network":
            return network_ok
        return proxy_replaced

    module._docker = lambda: "docker"  # type: ignore[method-assign]
    module._docker_json_inspect = _inspect  # type: ignore[method-assign]
    module._observe_live_proxy_config_sha256 = (  # type: ignore[method-assign]
        lambda docker, proxy_id: posture["proxy_config_sha256"]
    )
    module._docker_engine_observational_identity = (  # type: ignore[method-assign]
        lambda docker: {
            "docker_engine_observational_id": "engine|desktop",
            "docker_server_version": "29.5.3",
            "docker_ostype": "linux",
        }
    )
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(fixture["lock"])
    assert err.value.reason_code in {
        "EGRESS_PROXY_ID_MISMATCH",
        "EGRESS_LIVE_SEAL_DRIFT",
    }


def test_pre_start_reobserve_drift_cleans_unstarted_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    before = {
        "internal_network_id": "net1",
        "internal_network_name": "xinao_researcher_internal",
        "proxy_container_id": "ctr1",
        "proxy_image_id": "sha256:" + "a" * 64,
        "proxy_endpoint": "http://xinao-researcher-egress-proxy:3128",
        "allowlist_sha256": "d" * 64,
        "proxy_config_sha256": "e" * 64,
        "live_proxy_config_sha256": "e" * 64,
        "docker_engine_observational_id": "engine|desktop",
        "live_seal_sha256": "9" * 64,
    }
    after = dict(before)
    after["proxy_container_id"] = "ctr_replaced"
    with pytest.raises(module.XinaoError) as err:
        module._assert_egress_observations_bound(before, after)
    assert err.value.reason_code == "EGRESS_PRE_START_REOBSERVE_DRIFT"


def test_engineering_canary_path_does_not_require_prior_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    posture = _sample_posture()
    _write_json(module._egress_posture_path(), posture)
    _fake_live_ok(module, posture)
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": False,
    }
    bound = module.observe_egress_boundary_for_engineering_canary(lock)
    assert bound["path_class"] == "engineering_canary"
    assert bound["scientific_research"] is False
    assert bound["provider_egress_runtime_verified"] is False
    # Normal research still requires seal.
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(lock)
    assert err.value.reason_code == "EGRESS_LIVE_SEAL_MISSING"


def test_canary_receipt_cannot_be_scientific_research_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    scientific = {
        "schema_version": "xinao.skill_research_receipt.v2",
        "path_class": "scientific_research",
        "scientific_research": True,
        "completion_claim_allowed": False,
        "authority": False,
        "science_restored": False,
        "parent_complete": False,
    }
    with pytest.raises(module.XinaoError) as err:
        module._validate_evidence_receipt_shape(
            scientific,
            expected_schema=module.EGRESS_ENGINEERING_CANARY_SCHEMA,
            reason_code="EGRESS_LIVE_SEAL_INVALID",
        )
    assert err.value.reason_code == "EGRESS_LIVE_SEAL_INVALID"


def test_source_claim_true_is_forbidden_even_with_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    lock = dict(fixture["lock"])
    lock["provider_egress_runtime_verified"] = True
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(lock)
    assert err.value.reason_code == "EGRESS_SOURCE_CLAIM_FORBIDDEN"


def test_seal_schema_reference_and_sealer_script_exist() -> None:
    schema = json.loads(
        (SKILL_ROOT / "references" / "provider-egress-live-seal.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["properties"]["provider_egress_live_verified"]["const"] is True
    assert schema["additionalProperties"] is False
    for name in (
        "provider-egress-negative-suite-receipt.v1.schema.json",
        "provider-egress-engineering-canary-receipt.v1.schema.json",
        "provider-egress-receipt-handshake.v1.md",
    ):
        assert (SKILL_ROOT / "references" / name).is_file()
    neg_schema = json.loads(
        (
            SKILL_ROOT / "references" / "provider-egress-negative-suite-receipt.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    can_schema = json.loads(
        (
            SKILL_ROOT / "references" / "provider-egress-engineering-canary-receipt.v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert neg_schema["properties"]["suite_passed"]["const"] is True
    assert can_schema["properties"]["real_provider_call"]["const"] is True
    assert can_schema["properties"]["endpoint_host"]["const"] == "cli-chat-proxy.grok.com"
    sealer = (EGRESS_ROOT / "scripts" / "owner_seal_live_egress.py").read_text(encoding="utf-8")
    assert "provider_egress_live_verified" in sealer
    assert "source_lock_mutated" in sealer
    assert "no signing PKI" in sealer or "no_signing_pki" in sealer
    assert "skill_research_receipt" in sealer
    assert "CANARY_REAL_PROVIDER_CALL_REQUIRED" in sealer
    assert "REQUIRED_NEGATIVE_CASE_IDS" in sealer
    # LF-only for sealer script
    raw = (EGRESS_ROOT / "scripts" / "owner_seal_live_egress.py").read_bytes()
    assert b"\r" not in raw


def test_sealer_rejects_scientific_receipt_as_canary(tmp_path: Path) -> None:
    sealer = _sealer()
    with pytest.raises(sealer.SealError) as err:
        sealer._validate_evidence(
            {
                "schema_version": "xinao.skill_research_receipt.v2",
                "path_class": "scientific_research",
                "completion_claim_allowed": False,
                "authority": False,
            },
            schema=sealer.CANARY_SCHEMA,
            path_class="engineering_canary",
        )
    assert err.value.reason_code in {
        "EVIDENCE_SCHEMA_INVALID",
        "EVIDENCE_CLAIM_FORBIDDEN",
        "EVIDENCE_PATH_CLASS_INVALID",
    }


def test_sealer_rejects_connect_only_fake_canary() -> None:
    sealer = _sealer()
    posture = _sample_posture()
    fake = _sample_connect_only_fake_canary(posture)
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_engineering_canary_receipt(fake, posture=posture)
    assert err.value.reason_code in {
        "CANARY_RECEIPT_MISSING_KEY",
        "CANARY_REAL_PROVIDER_CALL_REQUIRED",
        "CANARY_CONNECT_ONLY_REJECTED",
        "EVIDENCE_CLAIM_FORBIDDEN",
    }


def test_sealer_accepts_explicit_semantic_valid_receipts() -> None:
    sealer = _sealer()
    posture = _sample_posture()
    observed = _iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(seconds=10))
    neg = _sample_negative_receipt(posture, observed_at=observed)
    can = _sample_canary_receipt(posture, observed_at=observed)
    # Explicit: every required semantic field present and seal-eligible.
    for field in sealer.NEGATIVE_REQUIRED_KEYS:
        assert field in neg, field
    for field in sealer.CANARY_REQUIRED_KEYS:
        assert field in can, field
    assert can["real_provider_call"] is True
    assert can["provider_effect_verified"] is True
    assert can["output_tokens"] > 0
    assert (
        can["usage"]["total_tokens"] >= can["usage"]["input_tokens"] + can["usage"]["output_tokens"]
    )
    sealer.validate_negative_suite_receipt(neg, posture=posture)
    sealer.validate_engineering_canary_receipt(can, posture=posture)


def test_sealer_negative_field_mutations_fail() -> None:
    sealer = _sealer()
    posture = _sample_posture()
    observed = _iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5))
    mutations = [
        ("status", "planned", "NEGATIVE_SUITE_STATUS_INVALID"),
        ("status", "partial", "NEGATIVE_SUITE_STATUS_INVALID"),
        ("suite_passed", False, "NEGATIVE_SUITE_NOT_PASSED"),
        ("all_cases_passed", False, "NEGATIVE_SUITE_NOT_PASSED"),
        ("unauthorized_domain_reachable", True, "NEGATIVE_SUITE_UNAUTHORIZED_DOMAIN"),
        ("direct_no_proxy_escape", True, "NEGATIVE_SUITE_DIRECT_ESCAPE"),
        ("fail_count", 1, "NEGATIVE_SUITE_COUNT_INVALID"),
        ("pass_count", 12, "NEGATIVE_SUITE_COUNT_INVALID"),
        ("internal_network_id", "replayed_net", "NEGATIVE_RECEIPT_POSTURE_MISMATCH"),
        ("proxy_container_id", "replayed_proxy", "NEGATIVE_RECEIPT_POSTURE_MISMATCH"),
        ("proxy_image_id", "sha256:" + "f" * 64, "NEGATIVE_RECEIPT_POSTURE_MISMATCH"),
        ("allowlist_sha256", "0" * 64, "NEGATIVE_RECEIPT_POSTURE_MISMATCH"),
        ("proxy_config_sha256", "1" * 64, "NEGATIVE_RECEIPT_POSTURE_MISMATCH"),
        ("completion_claim_allowed", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("authority", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("scientific_research", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("provider_egress_live_verified", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("provider_egress_runtime_verified", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        (
            "observed_at",
            _iso_z(dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)),
            "EVIDENCE_OBSERVATION_FUTURE",
        ),
        (
            "observed_at",
            _iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)),
            "EVIDENCE_OBSERVATION_STALE",
        ),
    ]
    for field, value, expected_code in mutations:
        receipt = _sample_negative_receipt(posture, observed_at=observed)
        receipt[field] = value
        with pytest.raises(sealer.SealError) as err:
            sealer.validate_negative_suite_receipt(receipt, posture=posture)
        assert err.value.reason_code == expected_code, (field, value, err.value.reason_code)

    # Missing required case.
    missing_case = _sample_negative_receipt(posture, observed_at=observed)
    missing_case["cases"] = [c for c in missing_case["cases"] if c["id"] != "N17"]
    missing_case["pass_count"] = len(missing_case["cases"])
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_negative_suite_receipt(missing_case, posture=posture)
    assert err.value.reason_code == "NEGATIVE_SUITE_MISSING_CASE"

    # Duplicate case.
    dup = _sample_negative_receipt(posture, observed_at=observed)
    dup["cases"] = list(dup["cases"]) + [{"id": "N1", "ok": True}]
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_negative_suite_receipt(dup, posture=posture)
    assert err.value.reason_code == "NEGATIVE_SUITE_DUPLICATE_CASE"

    # Unknown case.
    unknown = _sample_negative_receipt(posture, observed_at=observed)
    unknown["cases"] = list(unknown["cases"]) + [{"id": "N99", "ok": True}]
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_negative_suite_receipt(unknown, posture=posture)
    assert err.value.reason_code == "NEGATIVE_SUITE_UNKNOWN_CASE"

    # Case not ok.
    not_ok = _sample_negative_receipt(posture, observed_at=observed)
    not_ok["cases"] = [{"id": c["id"], "ok": (c["id"] != "N3")} for c in not_ok["cases"]]
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_negative_suite_receipt(not_ok, posture=posture)
    assert err.value.reason_code == "NEGATIVE_SUITE_CASE_NOT_OK"

    # Unknown key.
    extra = _sample_negative_receipt(posture, observed_at=observed, totally_unknown=True)
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_negative_suite_receipt(extra, posture=posture)
    assert err.value.reason_code == "NEGATIVE_RECEIPT_UNKNOWN_KEY"


def test_sealer_canary_field_mutations_fail() -> None:
    sealer = _sealer()
    posture = _sample_posture()
    observed = _iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5))
    mutations = [
        ("status", "planned", "CANARY_STATUS_INVALID"),
        ("status", "partial", "CANARY_STATUS_INVALID"),
        ("real_provider_call", False, "CANARY_REAL_PROVIDER_CALL_REQUIRED"),
        ("provider_effect_verified", False, "CANARY_PROVIDER_EFFECT_REQUIRED"),
        ("connect_only", True, "CANARY_CONNECT_ONLY_REJECTED"),
        ("http_only", True, "CANARY_HTTP_ONLY_REJECTED"),
        ("requested_model", "grok-3", "CANARY_MODEL_INVALID"),
        ("observed_backend_model", "grok-4.5", "CANARY_BACKEND_MODEL_INVALID"),
        ("stop_reason", "MaxTokens", "CANARY_STOP_REASON_INVALID"),
        ("output_tokens", 0, "CANARY_OUTPUT_TOKENS_INVALID"),
        ("output_tokens", None, "CANARY_OUTPUT_TOKENS_INVALID"),
        ("usage_accounting_complete", False, "CANARY_USAGE_INCOMPLETE"),
        ("endpoint_host", "api.x.ai", "CANARY_ENDPOINT_HOST_INVALID"),
        ("canary_image_id", "busybox:1.36", "CANARY_IMAGE_ID_INVALID"),
        ("internal_network_only", False, "CANARY_ISOLATION_INVALID"),
        ("auth_mounted_read_only", False, "CANARY_ISOLATION_INVALID"),
        ("auth_content_persisted", True, "CANARY_PERSISTENCE_FORBIDDEN"),
        ("raw_output_persisted", True, "CANARY_PERSISTENCE_FORBIDDEN"),
        ("research_invoked", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("is_research_call", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("masquerades_as_research", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("scientific_adoption", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("completion_claim_allowed", True, "EVIDENCE_CLAIM_FORBIDDEN"),
        ("positive_token_value", "secret-token", "CANARY_TOKEN_VALUE_FORBIDDEN"),
        ("internal_network_id", "replayed", "CANARY_RECEIPT_POSTURE_MISMATCH"),
        ("proxy_container_id", "replayed", "CANARY_RECEIPT_POSTURE_MISMATCH"),
        ("allowlist_sha256", "9" * 64, "CANARY_RECEIPT_POSTURE_MISMATCH"),
        (
            "observed_at",
            _iso_z(dt.datetime.now(dt.UTC) + dt.timedelta(hours=3)),
            "EVIDENCE_OBSERVATION_FUTURE",
        ),
        (
            "observed_at",
            _iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(days=2)),
            "EVIDENCE_OBSERVATION_STALE",
        ),
    ]
    for field, value, expected_code in mutations:
        receipt = _sample_canary_receipt(posture, observed_at=observed)
        receipt[field] = value
        with pytest.raises(sealer.SealError) as err:
            sealer.validate_engineering_canary_receipt(receipt, posture=posture)
        assert err.value.reason_code == expected_code, (field, value, err.value.reason_code)

    # Incomplete usage accounting (total too small).
    bad_usage = _sample_canary_receipt(
        posture,
        observed_at=observed,
        usage={"input_tokens": 10, "output_tokens": 12, "total_tokens": 15},
    )
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_engineering_canary_receipt(bad_usage, posture=posture)
    assert err.value.reason_code == "CANARY_USAGE_INVALID"

    # Usage output mismatch vs top-level output_tokens.
    mismatch = _sample_canary_receipt(
        posture,
        observed_at=observed,
        output_tokens=12,
        usage={"input_tokens": 1, "output_tokens": 3, "total_tokens": 4},
    )
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_engineering_canary_receipt(mismatch, posture=posture)
    assert err.value.reason_code == "CANARY_USAGE_INVALID"

    # Missing required semantic field.
    missing = _sample_canary_receipt(posture, observed_at=observed)
    del missing["provider_effect_verified"]
    with pytest.raises(sealer.SealError) as err:
        sealer.validate_engineering_canary_receipt(missing, posture=posture)
    assert err.value.reason_code == "CANARY_RECEIPT_MISSING_KEY"


def test_runtime_gate_rejects_connect_only_bound_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    # Replace canary bytes with CONNECT-only fake while keeping seal hash claim:
    # first prove semantic reject on load when hash is updated to match fake.
    fake = _sample_connect_only_fake_canary(fixture["posture"])
    can_path = module._egress_state_dir() / "engineering_canary_receipt.v1.json"
    can_sha = _write_json(can_path, fake)
    seal = dict(fixture["seal"])
    seal["positive_canary_receipt_sha256"] = can_sha
    _write_json(module._egress_live_seal_path(), seal)
    _fake_live_ok(module, fixture["posture"])
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(fixture["lock"])
    assert err.value.reason_code == "EGRESS_LIVE_SEAL_INVALID"


def test_runtime_gate_rejects_negative_suite_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    bad = _sample_negative_receipt(
        fixture["posture"],
        observed_at=_iso_z(dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)),
        suite_passed=False,
        all_cases_passed=False,
        fail_count=1,
    )
    # Make one case fail for consistency of payload content.
    bad["cases"] = [{"id": c["id"], "ok": (c["id"] != "N1")} for c in bad["cases"]]
    neg_path = module._egress_state_dir() / "negative_suite_receipt.v1.json"
    neg_sha = _write_json(neg_path, bad)
    seal = dict(fixture["seal"])
    seal["negative_suite_receipt_sha256"] = neg_sha
    _write_json(module._egress_live_seal_path(), seal)
    _fake_live_ok(module, fixture["posture"])
    with pytest.raises(module.XinaoError) as err:
        module._require_host_egress_boundary(fixture["lock"])
    assert err.value.reason_code == "EGRESS_LIVE_SEAL_INVALID"


def test_no_secrets_in_seal_or_sample_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    fixture = _install_posture_and_seal(module, tmp_path, monkeypatch)
    for path in (
        module._egress_live_seal_path(),
        module._egress_posture_path(),
        module._egress_state_dir() / "negative_suite_receipt.v1.json",
        module._egress_state_dir() / "engineering_canary_receipt.v1.json",
    ):
        text = path.read_text(encoding="utf-8").lower()
        for token in ("authorization", "api_key", "password", "bearer ", "private_key"):
            assert token not in text
    assert fixture["seal"]["secrets_present"] is False
    assert fixture["seal"]["completion_claim_allowed"] is False
    canary = json.loads(
        (module._egress_state_dir() / "engineering_canary_receipt.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert canary["real_provider_call"] is True
    assert canary["positive_token_value"] is None
    assert canary["output_tokens"] > 0
