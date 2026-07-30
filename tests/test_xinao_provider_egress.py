"""Offline unit/contract tests for XINAO researcher provider-egress boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
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


def test_source_defaults_keep_verified_false() -> None:
    lock = json.loads(
        (SKILL_ROOT / "references" / "researcher-runtime-lock.v1.json").read_text(
            encoding="utf-8"
        )
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
    assert "image:" not in compose or "ssrf_proxy" not in compose.split("services:")[1].split("networks:")[0]
    assert "ssrf_proxy_network:" not in compose
    assert "container_name: ssrf_proxy" not in compose
    # No host port publish mapping block
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("ports:"):
            pytest.fail("host ports mapping present")


def test_require_host_egress_still_fails_closed_when_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": False,
    }
    with pytest.raises(module.XinaoError) as failure:
        module._require_host_egress_boundary(lock)
    assert failure.value.reason_code == "EGRESS_BOUNDARY_UNAVAILABLE"
    # Must not touch docker when unverified.
    monkeypatch.setattr(module, "_docker", lambda: (_ for _ in ()).throw(AssertionError("docker")))
    with pytest.raises(module.XinaoError) as failure2:
        module._require_host_egress_boundary(lock)
    assert failure2.value.reason_code == "EGRESS_BOUNDARY_UNAVAILABLE"


def test_posture_shape_and_secret_redaction() -> None:
    module = _runtime()
    good = _sample_posture()
    assert module._validate_egress_posture_shape(good)["proxy_endpoint"].startswith("http://")
    with pytest.raises(module.XinaoError) as missing:
        module._validate_egress_posture_shape({"schema_version": "xinao.provider_egress_posture.v1"})
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
        "Containers": {
            posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]}
        },
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
    module._docker_json_inspect = inspect_factory(
        network={**network_ok, "Internal": False}
    )  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err.value.reason_code == "EGRESS_NETWORK_NOT_INTERNAL"

    # Image mismatch
    module._docker_json_inspect = inspect_factory(
        proxy={**proxy_ok, "Image": "sha256:" + "0" * 64}
    )  # type: ignore[method-assign]
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

    # Containers populated but proxy absent
    no_proxy_members = {
        **network_ok,
        "Containers": {"other": {"Name": "xinao-researcher-run-1"}},
    }
    module._docker_json_inspect = inspect_factory(network=no_proxy_members)  # type: ignore[method-assign]
    with pytest.raises(module.XinaoError) as err8:
        module._compare_live_egress_objects("docker", posture, lock)
    assert err8.value.reason_code == "EGRESS_NETWORK_MEMBERSHIP_INVALID"


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


def test_verified_true_requires_posture_before_docker_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _runtime()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    lock = {
        "network_profile": "EGRESS_BOUNDARY_REQUIRED_BEFORE_PROVIDER_CALL",
        "provider_egress_runtime_verified": True,
    }
    # Missing posture file
    with pytest.raises(module.XinaoError) as failure:
        module._require_host_egress_boundary(lock)
    assert failure.value.reason_code == "EGRESS_POSTURE_MISSING"

    posture_path = module._egress_posture_path()
    posture_path.parent.mkdir(parents=True, exist_ok=True)
    posture_path.write_text(json.dumps(_sample_posture()), encoding="utf-8")

    def fake_compare(docker, posture, runtime_lock):
        return {
            "internal_network_id": posture["internal_network_id"],
            "internal_network_name": posture["internal_network_name"],
            "internal": True,
            "proxy_container_id": posture["proxy_container_id"],
            "proxy_image_id": posture["proxy_image_id"],
            "proxy_endpoint": posture["proxy_endpoint"],
            "allowlist_sha256": posture["allowlist_sha256"],
            "proxy_config_sha256": posture["proxy_config_sha256"],
            "proxy_networks": [
                "xinao_researcher_internal",
                "xinao_provider_egress_ext",
            ],
            "host_port_published": False,
            "dify_cross_project": False,
        }

    monkeypatch.setattr(module, "_docker", lambda: "docker")
    monkeypatch.setattr(module, "_compare_live_egress_objects", fake_compare)
    bound = module._require_host_egress_boundary(lock)
    assert bound["proxy_endpoint"] == "http://xinao-researcher-egress-proxy:3128"
    assert bound["allowlist_sha256"] == "d" * 64


def test_research_receipt_redaction_shape_for_egress_block() -> None:
    # Static contract: receipt must never embed auth content; provider_egress flags stay honest.
    module = _runtime()
    # Ensure helper rejects secret-looking posture blobs already covered; receipt keys fixed in source.
    source = (SKILL_ROOT / "scripts" / "xinao_runtime.py").read_text(encoding="utf-8")
    assert '"provider_egress":' in source
    assert '"proxy_env_is_routing_hint_only": True' in source
    assert '"provider_egress_runtime_verified": False' in source
    assert "auth_content_sha256" in source
    assert source.count('provider_egress_runtime_verified"] = True') == 0


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
    assert "/etc/squid/squid.conf" not in entry or "SQUID_CONF=" in entry
    assert 'SQUID_CONF="${COREDUMP_DIR}/squid.conf"' in entry
    assert "squid -f \"${SQUID_CONF}\"" in entry or 'squid -f "${SQUID_CONF}"' in entry
    assert "PROVIDER_DSTDOMAIN_ACL must be a single line" in entry
    assert "forbidden ACL fragments" in entry
    # Template-env injection via HTTP_PORT/COREDUMP_DIR must fail closed.
    assert "HTTP_PORT must be a single decimal TCP port" in entry
    assert "COREDUMP_DIR must be a single absolute path" in entry
    assert "http_access allow all" in entry
    assert "live_proxy_config_sha256=" in entry
    # Must not write rendered conf onto read-only rootfs path as the only path.
    assert 'awk' in entry and 'SQUID_CONF' in entry


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
        "Containers": {
            posture["proxy_container_id"]: {"Name": posture["proxy_container_name"]}
        },
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
