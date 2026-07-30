# Owner runbook: XINAO researcher provider-egress boundary

## Scope

Candidate source topology for dedicated scientific researcher containers. Codex/Owner only for live Docker mutation. Workers must not provision or flip `provider_egress_runtime_verified`.

Primary Owner path on Windows is **PowerShell 7 + Docker Desktop CLI/Compose + repository Python**. No normal user WSL distribution and no Git Bash are required. Bash scripts under `scripts/*.sh` remain Linux/WSL-compatible twins; they are not hidden prerequisites for Windows Desktop Owners.

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
- Flipping `provider_egress_runtime_verified=true` without live negative suite + positive engineering canary evidence consumed by a separate live-seal path
- Storing credentials under E: or in egress receipts
- Cleanup by broad glob / name-only selection without ID + name (+ label) checks
- Claiming scientific adoption, `research()` success, or parent completion from these carriers

## Stable evidence paths (D:)

Default state root (override with `XINAO_EGRESS_STATE_ROOT` or `-StateRoot`):

`D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container\egress`

| Artifact | Path |
| --- | --- |
| posture | `current_posture.v1.json` |
| live seal (separate consumer) | `current_live_seal.v1.json` |
| pin readback | `image_pin_readback.v1.json` |
| provision receipt | `provision_receipt.v1.json` |
| negative suite | `negative_suite_receipt.v1.json` |
| engineering canary | `engineering_canary_receipt.v1.json` |
| cleanup | `cleanup_receipt.v1.json` |
| fresh-process readback | `fresh_process_readback.v1.json` |

Temp render artifacts default under:

`D:\XINAO_RESEARCH_RUNTIME\tmp\xinao_egress_owner`

Receipt `status` values are honest and distinct: `planned` | `observed` | `verified` | `partial` | `failed`. Carriers in this package do **not** emit `verified` for live provider-egress seal; that remains a separate live-seal consumer.

## Sequence (Windows Docker Desktop / PowerShell 7)

From package root `docker/xinao-researcher-egress` (or absolute paths):

0. **Migrate / build / activate protocol-v2 dedicated researcher image** (prerequisite for live real-provider canary)

   Live egress canary does **not** run on the unlabeled extraction donor (`researcher-runtime-lock.v1.json` `grok_donor_image_id`). That donor is provenance only (binary extract source). Before real-provider canary:

   - Build and activate a protocol-v2 researcher release via the skill runtime (`skills/xinao` migrate/build/activate path).
   - Confirm researcher-container state root has `current.json` schema `xinao.researcher_current_pointer.v2` pointing at an active `xinao.researcher_release.v2` whose `image_id` is the dedicated researcher image.
   - Default researcher-container state root: `D:\XINAO_RESEARCH_RUNTIME\state\xinao_skill\researcher_container` (from runtime-lock `state_root`; override with explicit `-ResearcherContainerStateRoot <absolute path>`). Distinct from egress evidence `-StateRoot` under `...\researcher_container\egress`.
   - Record the active release `image_id` (`sha256:<64hex>`). Pass that ID as `-CanaryImageId`. Floating tags are rejected.
   - If only a legacy v1 pointer exists, real-provider preflight fails with deterministic `ACTIVE_RESEARCHER_RELEASE_V2_ABSENT` (honest; never pretends the donor is a valid canary).

1. **Image pin** — immutable identity only
   `pwsh -File .\scripts\Resolve-ProxyImagePin.ps1`
   Preflight/readback without pull: `-PreflightOnly` / `-ReadbackOnly`
   WhatIf plan: `-WhatIf`
   Never treat floating `latest` as authority.

2. **Discovery scaffold** (credential-safe; Owner fills hosts after redacted lab capture)
   `pwsh -File .\scripts\Owner-DiscoverProviderEndpoints.ps1`
   Then fill `allowlist.v1.json` domains. Empty domains keep deny-all.

3. **Offline render / provision preflight**
   `pwsh -File .\scripts\Owner-ProvisionEgress.ps1 -PreflightOnly`
   Asserts pin resolved, allowlist/render OK, compose has no host ports and no Dify reuse.
   Live provision (Owner only):
   `pwsh -File .\scripts\Owner-ProvisionEgress.ps1`
   Writes posture with **`provider_egress_runtime_verified=false`**.

4. **Live negative suite** (exact object/config identities when posture present)
   `pwsh -File .\scripts\Owner-LiveNegativeSuite.ps1 -PreflightOnly`
   Live execute requires immutable client image (no floating tag default):
   `pwsh -File .\scripts\Owner-LiveNegativeSuite.ps1 -ClientImageId 'sha256:<64hex local image id>'`
   Fail-closed unauthorized-domain / private / metadata / non-443 / IP-literal checks.
   Each case uses a structured probe (Docker exit + bounded stdout/stderr) and the shared
   `Classify-XinaoNegativeProbeOutcome` oracle: infrastructure (missing applet, exit 125/126/127,
   invalid reference/options, daemon/image/network setup) and ambiguous outcomes never count as
   policy denial; proxy denies require concrete HTTP 403 / explicit proxy denial + nonzero client
   exit; direct cases require concrete no-route / unreachable / connect-timeout class (not bare
   `wget:`). Any infrastructure/ambiguous case makes the suite non-seal-eligible.
   Seal-eligible negative receipt must include exact 13 case IDs, `suite_passed`/`all_cases_passed`, escape observations (`unauthorized_domain_reachable=false`, `direct_no_proxy_escape=false`), posture IDs, and only sealer-allowed keys. Never seals verified.
   Local `Test-XinaoNegativeSuiteSealReceipt` is **shape-only** (keys/flags/case IDs); it does not
   enforce observation freshness—strict sealer/runtime do.

5. **Bounded positive engineering canary** (explicitly **not** `research()`, not scientific adoption)

   **CONNECT-only transport subcheck** (never seal-eligible; always `real_provider_call=false`, `provider_effect_verified=false`, `connect_only=true`):

   `pwsh -File .\scripts\Owner-EngineeringCanary.ps1 -PreflightOnly`
   Live CONNECT probe (requires immutable client image):
   `pwsh -File .\scripts\Owner-EngineeringCanary.ps1 -ClientImageId 'sha256:<64hex local image id>'`

   **Real provider effect path** (Owner-only later; worker must **not** execute). Requires explicit absolute regular auth file (no reparse/hardlink/ADS; path never appears in receipts), **active dedicated researcher release image ID** (protocol-v2 pointer/manifest `image_id`, not extraction donor), live labels (donor provenance, binary SHA, requested model, dedicated chain, generic-worker-route forbidden), and immutable client image for CONNECT subcheck:

   ```text
   pwsh -File .\scripts\Owner-EngineeringCanary.ps1 -PreflightOnly `
     -RealProviderCall `
     -AuthFilePath 'C:\path\to\existing\auth.json' `
     -CanaryImageId 'sha256:<active dedicated researcher release image id>' `
     -ClientImageId 'sha256:<64hex local client image id>'
   ```

   Optional absolute override of researcher-container state (tests/Owner):

   ```text
   ... -ResearcherContainerStateRoot 'D:\path\to\researcher_container'
   ```

   Live (Owner only, after v2 researcher activate + posture + negative suite):

   ```text
   pwsh -File .\scripts\Owner-EngineeringCanary.ps1 `
     -RealProviderCall `
     -AuthFilePath 'C:\path\to\existing\auth.json' `
     -CanaryImageId 'sha256:<active dedicated researcher release image id>' `
     -ClientImageId 'sha256:<64hex local client image id>'
   ```

   Real path facts:

   - Admission binds `-CanaryImageId` to protocol-v2 active release: exact immutable ID, pointer/manifest same image, release `source_identity.grok_donor_image_id` equals runtime-lock donor, live labels match donor/binary/model/chain/generic-worker-route-forbidden; no floating tag resolution. Seal receipt `canary_image_id` is that active researcher image ID; donor remains provenance only.
   - Disposable container on `xinao_researcher_internal` only; read-only rootfs; `cap-drop ALL`; `no-new-privileges`; bounded pids/memory/cpu; tmpfs `/tmp` + `/grok-home`; auth bind-mounted read-only at `/grok-home/.grok/auth.json` (inspect RO before start); exact `HTTP(S)_PROXY`; empty `NO_PROXY`/`ALL_PROXY`; no published ports; no extra hosts.
   - Invokes packaged `/usr/local/bin/grok` headless JSON contract with fixed non-scientific tool-free prompt, requested model `grok-4.5`, max-turns 1, bounded wall time; stdout/stderr drained asynchronously under timeout (no redirected-pipe deadlock); Docker CLI exit must be 0.
   - Seal-eligible only when receipt contains every sealer `CANARY_REQUIRED_KEYS` field (including exact `usage={input_tokens,output_tokens,total_tokens}`), only allowed keys, `status=observed`, `path_class=engineering_canary`, `real_provider_call=true`, `provider_effect_verified=true`, observed `grok-4.5-build` / `EndTurn` / positive tokens from **primary** `usage` metadata (not constants; never backfilled from `modelUsage`), `endpoint_host=cli-chat-proxy.grok.com`, exact posture IDs + canonical `canary_image_id=sha256:<64hex>` equal to the **active researcher image** (not the donor), isolation/persistence flags, all science/authority/completion flags false, UTC `observed_at`.
   - Primary `usage` must itself contain integer `input_tokens`, `output_tokens>0`, `total_tokens>=input+output`; positive `modelCalls` and backend `grok-4.5-build` required; if `modelUsage` token counts exist they must match primary (mismatch fails closed).
   - Raw CLI stdout lands only under owned D: temp as a strict child file (prefix-sibling / reparse / hardlink / directory rejected); delete that exact file only; `raw_output_persisted=false`. Disposable canary container must be `docker rm --force`'d and re-inspect must prove absence before any seal-eligible receipt (`canary_container_removed=true` enforced at carrier/builder; fail closed if unobserved). Cleanup fields limited to allowed keys (`canary_container_id`, `canary_container_removed`, `raw_output_sha256`, `connect_probe_ok`).
   - Local `Test-XinaoEngineeringCanarySealReceipt` is **shape-only** (keys/booleans/usage shape); it does not enforce observation freshness—strict sealer/runtime TTL still applies.
   - CONNECT subcheck remains separate transport evidence and **cannot** alone emit a seal-eligible receipt.
   - Empty allowlist cannot PASS.

6. **Fresh-process readback** for a later platform-neutral live-seal validator
   `pwsh -File .\scripts\Owner-FreshProcessReadback.ps1`
   Force new process: `-FreshProcess`
   Does not seal `provider_egress_live_verified`.

7. Only after negative suite (`suite_passed` + complete posture identities) **and** seal-eligible real engineering canary evidence may a **separate** Owner live-seal consumer bind hashes and seal live verification on D-state. This runbook’s carriers do not perform that seal.

### Bash twins (optional non-Windows)

1. `scripts/resolve_proxy_image_pin.sh` — seal immutable image id/digest
2. `scripts/owner_discover_provider_endpoints.sh` — scaffold
3. Offline: `python render_squid_config.py --allowlist ... --template squid.conf.template --output ... --receipt ...`
4. `scripts/owner_provision_egress.sh` — create networks/proxy; posture verified stays false
5. `scripts/owner_live_negative_suite.sh` — N1–N17 style denies
6. One real researcher canary through internal network + proxy env (engineering path above on Windows)
7. Separate live-seal consumer may then seal verified on D-state only

## Rollback

Windows:

`pwsh -File .\scripts\Owner-CleanupEgress.ps1 -WhatIf` then live cleanup without `-WhatIf`.

- Resolves exact XINAO targets by name + ID (+ chain label for researcher containers)
- Rejects Dify/foreign names (`ssrf_proxy`, `ssrf_proxy_network`, …)
- Reports **observed** removals only
- Forces posture `lifecycle_state=ABSENT` and verified false when posture exists
- Deletes `current_live_seal.v1.json` if present (invalidation only)

Bash twin: `scripts/owner_cleanup_egress.sh`.

## Proxy env role

`HTTP_PROXY`/`HTTPS_PROXY` are client routing hints. Enforcement is internal network (no default route) + Squid ACL.

## Safety modes

| Mode | Docker mutation | Typical receipt status |
| --- | --- | --- |
| `-PreflightOnly` | no | `planned` / `observed` (file checks) / `failed` |
| `-WhatIf` | no | `planned` |
| `-ReadbackOnly` (pin) | no | `observed` or `failed` |
| execute | yes (Owner) | `observed` / `partial` / `failed` |

Never invent a fake PASS: missing evidence stays missing; empty allowlist stays fail-closed; cleanup does not claim absent objects were removed.

## Negative suite seal consumption

Execute receipt for strict seal consumers (`owner_seal_live_egress.py` / runtime) requires:

- `status=observed`, `path_class=negative_suite`
- exact 13 case IDs (`N1,N3,N4,N5,N6,N7,N8,N9,N15,N17,N17b,N17c,N17d`), each `ok=true`
- `suite_passed=true`, `all_cases_passed=true`, `pass_count=13`, `fail_count=0`
- `unauthorized_domain_reachable=false`, `direct_no_proxy_escape=false`
- Top-level exact identities: `internal_network_id`, `proxy_container_id`, `proxy_image_id`, `allowlist_sha256`, `proxy_config_sha256`
- non-claims: `secrets_present` / `provider_egress_runtime_verified` / `provider_egress_live_verified` / science / authority / completion all **false**
- only sealer-allowed keys (no `case_count`, `identities_complete`, etc.)
- fresh UTC `observed_at`

Missing posture identities with otherwise-passing cases → honest `partial`, not seal-ready.

## Completion honesty

- `completion_claim_allowed=false` on all carrier receipts
- `authority=false`
- `research_invoked=false` / `is_research_call=false` / `scientific_research=false` on engineering canary
- CONNECT-only never sets `provider_effect_verified=true`
- No science/parent completion claims from this package
