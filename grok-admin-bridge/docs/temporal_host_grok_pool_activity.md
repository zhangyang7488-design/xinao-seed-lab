# Temporal host Grok pool fallback

This path is retained only as a bounded explicit fallback.

Default work goes through Temporal + Docker houtai-gongren + worker-internal LangGraph. The host pool has no authority to become a scheduler, refill loop, watchdog, daemon, or completion ledger.

Use it only when the current user explicitly requests a direct Grok batch or the canonical route is unavailable and a bounded temporary ladder is required. Record the reason, choose width dynamically, and verify every lane artifact on D:.
