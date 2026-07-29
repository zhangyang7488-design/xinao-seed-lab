# Owner runbook: XINAO researcher provider-egress boundary

## Scope

Candidate source topology for dedicated scientific researcher containers. Codex/Owner only for live Docker mutation. Workers must not provision or flip `provider_egress_runtime_verified`.

## Objects

| Object | Role |
| --- | --- |
| `xinao_researcher_internal` | `internal: true` bridge; researcher only member workload |
| `xinao_provider_egress_ext` | non-internal; proxy only |
| `xinao-researcher-egress-proxy` | dual-homed Squid CONNECT allowlist proxy |

## Forbidden

- Live Dify `ssrf_proxy` / `ssrf_proxy_network` reuse
- Host-published proxy port unless proven necessary
- TLS interception / SSL bump
- Floating `ubuntu/squid:latest` as identity authority
- Flipping `provider_egress_runtime_verified=true` without live negative suite + positive Grok canary
- Storing credentials under E: or in egress receipts

## Sequence

1. `scripts/resolve_proxy_image_pin.sh` — seal immutable image id/digest
2. `scripts/owner_discover_provider_endpoints.sh` — scaffold; complete redacted capture; fill `allowlist.v1.json`
3. Offline: `python3 render_squid_config.py --allowlist ... --template squid.conf.template --output /tmp/squid.conf --receipt /tmp/receipt.json`
4. `scripts/owner_provision_egress.sh` — create networks/proxy; write D-state posture; **verified stays false**
5. `scripts/owner_live_negative_suite.sh` — N1–N17 style denies
6. One real researcher canary through internal network + proxy env with `grok-4.5-build` evidence
7. Only then may Owner seal `provider_egress_runtime_verified=true` in a new runtime-lock/release identity bound to posture hashes

## Rollback

`scripts/owner_cleanup_egress.sh` removes only XINAO egress-labeled objects; forces verified false in posture; never touches Dify.

## Proxy env role

`HTTP_PROXY`/`HTTPS_PROXY` are client routing hints. Enforcement is internal network (no default route) + Squid ACL.
