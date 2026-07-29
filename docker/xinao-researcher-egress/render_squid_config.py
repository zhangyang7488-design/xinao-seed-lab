#!/usr/bin/env python3
"""Offline renderer for XINAO researcher egress Squid config.

Pure functions only: no Docker, no credentials, no network I/O.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "xinao.provider_egress_allowlist.v1"
DOMAIN_PATTERN = re.compile(
    r"^(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
    r"|(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)$"
)
FORBIDDEN_ACL_FRAGMENTS = (
    "http_access allow client_localnet",
    "SSRF_PROXY_ALLOW_PRIVATE",
    "ssl_bump",
    "dify_allowed_private",
    "ssrf_proxy_network",
)


class RenderError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
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


def load_allowlist(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RenderError("ALLOWLIST_INVALID", f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderError("ALLOWLIST_INVALID", "object required")
    if data.get("schema_version") != SCHEMA:
        raise RenderError("ALLOWLIST_SCHEMA_INVALID", str(data.get("schema_version")))
    if data.get("ports") != [443]:
        raise RenderError("ALLOWLIST_PORTS_INVALID", str(data.get("ports")))
    if data.get("methods") != ["CONNECT"]:
        raise RenderError("ALLOWLIST_METHODS_INVALID", str(data.get("methods")))
    domains = data.get("domains")
    if not isinstance(domains, list) or any(not isinstance(item, str) for item in domains):
        raise RenderError("ALLOWLIST_DOMAINS_INVALID", "domains must be a string list")
    ip_literals = data.get("ip_literals_allowed", [])
    if not isinstance(ip_literals, list) or ip_literals:
        raise RenderError(
            "ALLOWLIST_IP_LITERALS_FORBIDDEN",
            "default deny; empty ip_literals_allowed required",
        )
    for domain in domains:
        if not DOMAIN_PATTERN.fullmatch(domain):
            raise RenderError("ALLOWLIST_DOMAIN_TOKEN_INVALID", domain)
        if re.fullmatch(r"[0-9.]+", domain):
            raise RenderError("ALLOWLIST_DOMAIN_LOOKS_LIKE_IP", domain)
    return data


def build_provider_dstdomain_acl(domains: Sequence[str]) -> str:
    if not domains:
        return "acl provider_domains dstdomain .invalid.xinao.local"
    ordered = sorted(set(domains))
    return "acl provider_domains dstdomain " + " ".join(ordered)


def render_template(
    template_text: str,
    *,
    http_port: int = 3128,
    coredump_dir: str = "/var/spool/squid",
    domains: Sequence[str] = (),
) -> str:
    if not (1 <= http_port <= 65535):
        raise RenderError("HTTP_PORT_INVALID", str(http_port))
    acl_line = build_provider_dstdomain_acl(domains)
    rendered = (
        template_text.replace("${HTTP_PORT}", str(http_port))
        .replace("${COREDUMP_DIR}", coredump_dir)
        .replace("${PROVIDER_DSTDOMAIN_ACL}", acl_line)
    )
    lowered = rendered.lower()
    for fragment in FORBIDDEN_ACL_FRAGMENTS:
        if fragment.lower() in lowered:
            raise RenderError("FORBIDDEN_ACL_FRAGMENT", fragment)
    required_fragments = (
        "http_access deny !Safe_ports",
        "http_access deny !CONNECT",
        "http_access deny CONNECT !SSL_ports",
        "http_access deny to_private_networks",
        "http_access deny to_ipv4_literal",
        "http_access deny to_ipv6_literal",
        "http_access allow provider_domains",
        "http_access deny all",
        "acl SSL_ports port 443",
        "acl Safe_ports port 443",
    )
    for fragment in required_fragments:
        if fragment not in rendered:
            raise RenderError("RENDERED_CONF_MISSING_RULE", fragment)
    if "acl Safe_ports port 80" in rendered:
        raise RenderError("CLEARTEXT_PORT_80_OPEN", "Safe_ports must not include 80")
    if "ssl_bump" in lowered:
        raise RenderError("TLS_INTERCEPTION_FORBIDDEN", "ssl_bump")
    return rendered


def render_from_paths(
    allowlist_path: Path,
    template_path: Path,
    *,
    http_port: int = 3128,
    coredump_dir: str = "/var/spool/squid",
) -> dict[str, Any]:
    allowlist = load_allowlist(allowlist_path)
    template = template_path.read_text(encoding="utf-8")
    conf = render_template(
        template,
        http_port=http_port,
        coredump_dir=coredump_dir,
        domains=allowlist["domains"],
    )
    conf_bytes = conf.encode("utf-8")
    allowlist_bytes = canonical_json_bytes(allowlist)
    return {
        "schema_version": "xinao.provider_egress_rendered_config.v1",
        "allowlist_sha256": sha256_bytes(allowlist_bytes),
        "proxy_config_sha256": sha256_bytes(conf_bytes),
        "http_port": http_port,
        "domains": list(allowlist["domains"]),
        "squid_conf": conf,
        "provider_dstdomain_acl": build_provider_dstdomain_acl(allowlist["domains"]),
    }


def assert_image_pin(pin: dict[str, Any]) -> None:
    if pin.get("schema_version") != "xinao.provider_egress_proxy_image_pin.v1":
        raise RenderError("IMAGE_PIN_SCHEMA_INVALID", str(pin.get("schema_version")))
    if pin.get("floating_tag_as_authority") is not False:
        raise RenderError("FLOATING_TAG_AUTHORITY_FORBIDDEN", "floating_tag_as_authority")
    digest = pin.get("image_digest")
    image_id = pin.get("image_id")
    if not digest and not image_id:
        raise RenderError(
            "IMAGE_PIN_UNRESOLVED",
            "image_digest or image_id required before provision",
        )
    if digest is not None:
        if not isinstance(digest, str) or "@sha256:" not in digest:
            raise RenderError("IMAGE_DIGEST_INVALID", str(digest))
    if image_id is not None:
        if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
            raise RenderError("IMAGE_ID_INVALID", str(image_id))
    tag = pin.get("image_tag_observational")
    if tag == "latest" and pin.get("authority") != "immutable_digest_or_image_id_only":
        raise RenderError("FLOATING_TAG_AUTHORITY_FORBIDDEN", str(tag))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="render_squid_config")
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--http-port", type=int, default=3128)
    parser.add_argument("--coredump-dir", default="/var/spool/squid")
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        rendered = render_from_paths(
            args.allowlist,
            args.template,
            http_port=args.http_port,
            coredump_dir=args.coredump_dir,
        )
    except RenderError as exc:
        print(
            json.dumps(
                {
                    "status": "RENDER_FAILED",
                    "reason_code": exc.reason_code,
                    "detail": exc.detail,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    args.output.write_text(rendered["squid_conf"], encoding="utf-8")
    if args.receipt is not None:
        receipt = {
            "schema_version": rendered["schema_version"],
            "allowlist_sha256": rendered["allowlist_sha256"],
            "proxy_config_sha256": rendered["proxy_config_sha256"],
            "http_port": rendered["http_port"],
            "domains": rendered["domains"],
            "provider_dstdomain_acl": rendered["provider_dstdomain_acl"],
            "secrets_present": False,
        }
        args.receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": "RENDERED",
                "allowlist_sha256": rendered["allowlist_sha256"],
                "proxy_config_sha256": rendered["proxy_config_sha256"],
                "domain_count": len(rendered["domains"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
