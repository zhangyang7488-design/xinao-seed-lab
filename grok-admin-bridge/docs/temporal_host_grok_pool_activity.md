# Temporal host Grok pool bounded lane

This path is retained only as an auxiliary Temporal-trigger-to-host-leg-A adapter. It is not durable leg B and is not a canonical fallback.

Route selection comes from task fit or an existing route receipt. Typical bounded online work uses direct leg A; durable leg B is Temporal + Docker houtai-gongren + worker-internal LangGraph only after explicit handoff. The host pool has no authority to become a scheduler, refill loop, watchdog, daemon, or completion ledger.

Use it when direct Grok parallelism has positive net benefit, or when the canonical route is unavailable and a bounded temporary ladder is required. It does not require the user to repeat authorization for an already scoped task. Record the reason, choose width dynamically, and verify every lane artifact on D:.
