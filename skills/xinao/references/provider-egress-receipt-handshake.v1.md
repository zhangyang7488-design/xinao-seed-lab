# Provider egress receipt handshake (Windows PowerShell ↔ platform-neutral sealer)

**Authority:** false (reference only)
**Completion claim allowed:** false

## Purpose

Sibling Windows Owner carriers (`Owner-LiveNegativeSuite.ps1`, `Owner-EngineeringCanary.ps1`) and the platform-neutral sealer (`owner_seal_live_egress.py`) share exact seal-eligible receipt contracts so CONNECT-only or planned/partial receipts cannot false-green a live seal.

## Seal-eligible negative suite

Schema: `xinao.provider_egress_negative_suite_receipt.v1`
JSON Schema: `provider-egress-negative-suite-receipt.v1.schema.json`

Must emit:

| Field | Value |
|---|---|
| `status` | `observed` |
| `path_class` | `negative_suite` |
| `suite_passed` / `all_cases_passed` | `true` |
| `cases` | exact IDs `N1,N3,N4,N5,N6,N7,N8,N9,N15,N17,N17b,N17c,N17d`, each `ok=true`, no missing/duplicate/unknown |
| `fail_count` | `0` |
| `pass_count` | `13` |
| posture identities | exact `internal_network_id`, `proxy_container_id`, `proxy_image_id`, `allowlist_sha256`, `proxy_config_sha256` |
| `unauthorized_domain_reachable` | `false` |
| `direct_no_proxy_escape` | `false` |
| claims | source/live/science/authority/completion all false |
| `observed_at` | UTC `…Z` inside seal freshness window |

Preflight/planned receipts remain useful for Owner dry-run but are **not** seal-eligible.

## Seal-eligible engineering canary

Schema: `xinao.provider_egress_engineering_canary_receipt.v1`
JSON Schema: `provider-egress-engineering-canary-receipt.v1.schema.json`

Must emit:

| Field | Value |
|---|---|
| `status` | `observed` |
| `path_class` | `engineering_canary` |
| `real_provider_call` | `true` |
| `provider_effect_verified` | `true` |
| `requested_model` | `grok-4.5` |
| `observed_backend_model` | `grok-4.5-build` |
| `stop_reason` | `EndTurn` |
| `output_tokens` | integer `> 0` |
| `usage_accounting_complete` | `true` |
| `usage` | `{input_tokens, output_tokens, total_tokens}` complete integers |
| `endpoint_host` | `cli-chat-proxy.grok.com` |
| posture identities | same five identity fields as negative |
| `canary_image_id` | immutable `sha256:<64hex>` |
| isolation | `internal_network_only=true`, `auth_mounted_read_only=true` |
| persistence | `auth_content_persisted=false`, `raw_output_persisted=false` |
| research flags | all false; no adoption/completion |
| `positive_token_value` | must be null if present (never secret material) |

## Explicit non-sealable carrier outputs

The following are rejected by `owner_seal_live_egress.py` before any seal write:

- CONNECT-only engineering receipts (`real_provider_call=false`, null/zero tokens)
- HTTP-only probes (`http_only=true` or missing provider effect)
- `status` in `{planned, partial, failed, verified}`
- wrong model / incomplete usage / replayed posture identities
- observation timestamps outside the seal freshness interval

## Sealer order

1. Semantic validate negative + canary against posture (and freshness)
2. Direct Docker network/proxy/config observation
3. Atomic write of `current_live_seal.v1.json` only if both succeed

Runtime gate reloads seal-bound receipt bytes, rechecks hashes, and re-applies the same semantic contracts against posture before research admission.
